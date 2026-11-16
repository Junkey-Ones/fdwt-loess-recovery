"""非生产原生LAI抽查：27格点年，严格QA与仅释放气溶胶对照。"""
from pathlib import Path
import sys,json,csv
from collections import defaultdict
from datetime import date
import numpy as np
import pyarrow.parquet as pq
from pyhdf.SD import SD,SDC
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.M6.scr_prepare_vegetation import tile_geometry,tile_mapping,lai_qc,native_year,composite_weights
BASE=ROOT/'data/frozen/downstream/2026-11-13_主分析X_QC修复';OUT=ROOT/'notebooks/audit_support_20261114';years=[2003,2013,2022]
grid=pq.read_table(ROOT/'data/interim/era5land_base/2026-11-13_主分析X_QC修复/grid_manifest.parquet').to_pylist();gd={r['grid_id']:r for r in grid}
veg=pq.read_table(BASE/'M6/vegetation_grid_year.parquet').to_pylist();vd={(r['grid_id'],r['year']):r for r in veg}
mask=pq.read_table(BASE/'M3/grid_mask.parquet').to_pylist();selected=[]
for lc in ['forest','grassland','cropland']:
 pool=sorted([r['grid_id'] for r in mask if r['land_cover']==lc and all(vd.get((r['grid_id'],y),{}).get('active_pentad_n',0)>0 for y in years)],key=lambda g:(gd[g]['lat'],gd[g]['lon']))
 selected += [pool[int((len(pool)-1)*q)] for q in [.2,.5,.8]]
grid=[gd[g] for g in selected];lcmap={r['grid_id']:r['land_cover'] for r in mask}
active=defaultdict(list)
for r in pq.read_table(BASE/'M3/grid_active_pentad.parquet',columns=['grid_id','year','pentad','active_flag'],filters=[('grid_id','in',selected),('year','in',years)]).to_pylist():
 if r['active_flag']:active[r['grid_id'],r['year']].append(r['pentad']-1)
calendar=defaultdict(list)
for r in pq.read_table(ROOT/'data/interim/era5land_base/2026-11-13_主分析X_QC修复/time_pentad_calendar.parquet').to_pylist():calendar[r['year']].append(r)
files=defaultdict(dict)
for p in (ROOT/'data/raw/modis/MCD15A3H/V061').rglob('*.hdf'):
 bits=p.name.split('.');year=int(bits[1][1:5]);day=int(bits[1][5:])
 if year in years:files[year,bits[2]][(day-1)//4]=p
maps={}
for tile in sorted({t for y,t in files}):
 ds=SD(str(next(iter(files[years[0],tile].values()))),SDC.READ);geometry=tile_geometry(ds);ds.end()
 m=tile_mapping(grid,[102,34,115,41],.1,geometry)
 if m:maps[tile]=m
output=[];monthly=[];done=0
for year in years:
 sums=np.zeros((len(grid),2,3));diagnostic=np.zeros((len(grid),4));weights=composite_weights(year,calendar[year])
 for tile,mapping in maps.items():
  pixels=np.unique(np.concatenate([v[0] for v in mapping.values()]));slots=(date(year+1,1,1)-date(year,1,1)).days;slots=(slots+3)//4
  stacks=[np.full((slots,len(pixels)),255,dtype=np.uint8) for _ in range(2)]
  for slot,p in sorted(files[year,tile].items()):
   ds=SD(str(p),SDC.READ);layers=[]
   try:
    for name in ['Lai_500m','FparLai_QC','FparExtra_QC']:
     field=ds.select(name);layers.append(field[:].ravel()[pixels]);field.endaccess()
   finally:ds.end()
   raw,qc,extra=layers;strict=lai_qc(raw,qc,extra);relaxed=lai_qc(raw,qc,extra & np.uint8(247)) & (extra!=255)
   stacks[0][slot]=np.where(strict,raw,255);stacks[1][slot]=np.where(relaxed,raw,255)
   for i,(indices,area) in mapping.items():
    ix=np.searchsorted(pixels,indices);periods=active[grid[i]['grid_id'],year];days=sum(c for pp in periods for idx,c in weights[pp] if idx==slot)
    if not days:continue
    total=area.sum()*days;diagnostic[i,0]+=total;diagnostic[i,1]+=np.dot(area,((extra[ix]&8)!=0)&(extra[ix]!=255))*days;diagnostic[i,2]+=np.dot(area,relaxed[ix]&~strict[ix])*days
   done+=1
  for i,(indices,area) in mapping.items():
   ix=np.searchsorted(pixels,indices);periods=active[grid[i]['grid_id'],year]
   for version,stack in enumerate(stacks):
    value,days,count,observed=native_year(stack[:,ix],weights,periods);valid=count>0
    sums[i,version]+=[area[valid].sum(),np.dot(area[valid],value[valid]/count[valid]),np.dot(area[valid],days[valid])]
  print('completed',year,tile,done,flush=True)
 for i,g in enumerate(grid):
  total=g['area_km2']*1e6*(6371.007181/6371.0088)**2;nd=sum(calendar[year][p]['n_days'] for p in active[g['grid_id'],year]);row=dict(grid_id=g['grid_id'],year=year,land_cover=lcmap[g['grid_id']],lat=g['lat'],lon=g['lon'])
  for version,label in enumerate(['strict','relaxed']):
   area,value,days=sums[i,version];row[label+'_time']=days/(area*nd) if area else 0;row[label+'_space']=area/total;row[label+'_mean']=value/area*.1 if area else None;row[label+'_pass70']=row[label+'_time']>=.7 and row[label+'_space']>=.7
  row['frozen_time']=vd[g['grid_id'],year]['temporal_coverage'];row['time_error']=row['strict_time']-row['frozen_time'];row['only_aerosol_fraction_observed_support']=diagnostic[i,2]/diagnostic[i,0] if diagnostic[i,0] else None
  output.append(row)
with (OUT/'native_qc_sample.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
print(json.dumps(dict(n=len(output),files_read=done,strict_pass=int(sum(r['strict_pass70'] for r in output)),relaxed_pass=int(sum(r['relaxed_pass70'] for r in output)),max_time_error=max(abs(r['time_error']) for r in output),median_time_gain=float(np.median([r['relaxed_time']-r['strict_time'] for r in output])))))
