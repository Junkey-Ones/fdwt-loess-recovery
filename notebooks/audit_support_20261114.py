"""非生产只读审计，不拟合暴露结局效应。"""
from pathlib import Path
import sys,json,csv,hashlib
from collections import Counter,defaultdict
import numpy as np
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from src.M5.scr_group_wet_processes import build_superblocks
from src.M6.scr_prepare_vegetation import lai_qc
BASE=ROOT/'data/frozen/downstream/2026-11-13_主分析X_QC修复';OUT=ROOT/'notebooks/audit_support_20261114';OUT.mkdir(exist_ok=True)
def read(n):return pq.read_table(BASE/(n+'.parquet')).to_pylist()
def kish(v):
 c=Counter(v);n=sum(c.values());return n*n/sum(a*a for a in c.values()) if n else 0
def groups(rows,key):
 d=defaultdict(list)
 for r in rows:d[r[key]].append(r)
 return d
def save(n,rows):
 if rows:
  with (OUT/n).open('w',encoding='utf-8-sig',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
events=read('M5/event_master');veg=read('M6/vegetation_grid_year');expo=read('M6/event_exposure');ed={r['episode_id']:r for r in expo}
grid=pq.read_table(ROOT/'data/interim/era5land_base/2026-11-13_主分析X_QC修复/grid_manifest.parquet').to_pylist();gd={r['grid_id']:r for r in grid};mask={r['grid_id']:r for r in read('M3/grid_mask')}
s={'spatial':[]};s['input_sha256']={n:hashlib.sha256((BASE/(n+'.parquet')).read_bytes()).hexdigest() for n in ['M5/event_master','M6/vegetation_grid_year','M6/event_exposure']}
s['model_status']=[{k:r[k] for k in ['analysis_id','n_event','n_block','n_superblock','n_eff','convergence_status']} for r in read('M7/model_fit_manifest')]
for km in [50,100,200]:
 gg=[]
 for g in grid:
  lat=np.deg2rad(g['lat']);l0=np.deg2rad(37.5);dl=np.deg2rad(g['lon']-108.5);k=np.sqrt(2/(1+np.sin(l0)*np.sin(lat)+np.cos(l0)*np.cos(lat)*np.cos(dl)))
  x=6371.0088*k*np.cos(lat)*np.sin(dl);y=6371.0088*k*(np.cos(l0)*np.sin(lat)-np.sin(l0)*np.cos(lat)*np.cos(dl));b=f'{int(np.floor(x/km))}:{int(np.floor(y/km))}'
  if km==100:assert b==g['block_id']
  gg.append({**g,'block_id':b})
 bm={r['grid_id']:r['block_id'] for r in gg};bs=[bm[r['grid_id']] for r in events];sm={r['block_id']:r['superblock_id'] for r in build_superblocks(events,gg)}
 sizes=[len({bm[r['grid_id']] for r in rs}) for key,rs in groups(events,'cluster_id').items() if key]
 s['spatial'].append(dict(km=km,n_blocks=len(set(bs)),n_superblocks=len({sm[b] for b in bs}),fixed_block_kish=kish(bs),cross_block_regions=sum(a>1 for a in sizes),max_region_blocks=max(sizes)))
bm={r['grid_id']:r['block_id'] for r in grid};yy=[]
for year,ev in sorted(groups(events,'year').items()):
 sm={r['block_id']:r['superblock_id'] for r in build_superblocks(ev,grid)};bs=[bm[r['grid_id']] for r in ev];c=Counter(sm[b] for b in bs)
 yy.append(dict(year=year,n_event=len(ev),n_blocks=len(set(bs)),n_superblocks=len(c),largest_component_fraction=max(c.values())/len(ev)))
save('spatial_by_year.csv',yy);s['year_superblocks_range']=[min(r['n_superblocks'] for r in yy),max(r['n_superblocks'] for r in yy)];s['cross_start_year_regions']=sum(len({r['year'] for r in rs})>1 for key,rs in groups(events,'cluster_id').items() if key)
a=[r for r in veg if r['active_pentad_n']>0];s['annual']=dict(n_rows=len(veg),active=len(a),space70=sum(r['spatial_coverage']>=.7 for r in a),time70=sum(r['temporal_coverage']>=.7 for r in a),both70=sum(r['annual_valid'] for r in a),time_quantiles=np.quantile([r['temporal_coverage'] for r in a],[0,.1,.25,.5,.75,.9,1]).tolist())
for key in ['year','land_cover']:
 rows=[{**r,'land_cover':mask[r['grid_id']]['land_cover']} for r in a]
 save('lai_'+key+'_support.csv',[{key:k,'n':len(rs),'time_median':float(np.median([r['temporal_coverage'] for r in rs])),'passed':sum(r['annual_valid'] for r in rs)} for k,rs in sorted(groups(rows,key).items())])
base=[{**r,**{k:gd[r['grid_id']][k] for k in ['lat','lon','block_id']}} for r in events if 2008<=r['year']<=2023];s['exposure_period_events']=len(base);s['candidates']=[]
for threshold,required,width in [(.7,5,5),(.7,4,5),(.6,5,5),(.5,5,5),(.7,3,3)]:
 good={(r['grid_id'],r['year']) for r in veg if r['temporal_coverage']>=threshold and r['spatial_coverage']>=.7}
 sel=[r for r in base if sum((r['grid_id'],r['year']-j) in good for j in range(1,width+1))>=required and not ed[r['episode_id']]['core_covariate_missing_reason']];key=f't{int(threshold*100)}_n{required}_w{width}'
 s['candidates'].append(dict(candidate=key,n_event=len(sel),n_exposure=len({(r['grid_id'],r['year']) for r in sel}),n_grid=len({r['grid_id'] for r in sel}),n_year=len({r['year'] for r in sel}),n_block=len({r['block_id'] for r in sel}),block_kish=kish(r['block_id'] for r in sel),lat_median=float(np.median([r['lat'] for r in sel])),lon_median=float(np.median([r['lon'] for r in sel])),land_cover=dict(Counter(r['land_cover'] for r in sel)),years=dict(sorted(Counter(r['year'] for r in sel).items())),n_recovery_eligible=sum(r['recovery_risk_eligible'] for r in sel),n_fr_eligible=sum(r['route1_FR_eligible'] for r in sel)))
 save(key+'_members.csv',[{k:r[k] for k in ['episode_id','grid_id','year','lat','lon','block_id','land_cover']} for r in sel])
s['baseline']=dict(land_cover=dict(Counter(r['land_cover'] for r in base)),lat_median=float(np.median([r['lat'] for r in base])),lon_median=float(np.median([r['lon'] for r in base])))
q,e=np.meshgrid(np.arange(256,dtype=np.uint8),np.arange(256,dtype=np.uint8));ex=(q!=255)&((q&1)==0)&(((q>>2)&1)==0)&(((q>>3)&3)==0)&np.isin(q>>5,[0,1])&(e!=255)&((e&3)<=1)
for b in [2,3,4,5,6]:ex &= ((e>>b)&1)==0
s['qc_exhaustive_check']=dict(combinations=65536,mismatches=int((lai_qc(np.ones_like(q),q,e)!=ex).sum()))
(OUT/'summary.json').write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(s,ensure_ascii=True))
