"""非生产全域LAI审计：严格QA与仅释放Aerosol单项的配对复算。

不写正式冻结表，不拟合结局效应。参数通过统一加载器读取。
按瓦片年原子保存检查点；运行身份改变时禁止续接。
"""
from pathlib import Path
from collections import defaultdict
from datetime import date
import sys, json, hashlib, csv, time
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from pyhdf.SD import SD, SDC

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from workflow.run_module import load_config, DEFAULT_CONFIG
from src.M6.scr_prepare_vegetation import tile_geometry, tile_mapping, composite_weights, lai_qc

OUT=ROOT/'notebooks/lai_aerosol_audit_20261115'
BASE=ROOT/'data/frozen/downstream/2026-11-13_主分析X_QC修复'
M2=ROOT/'data/interim/era5land_base/2026-11-13_主分析X_QC修复'

def log(message):
    print(time.strftime('%H:%M:%S'),message,flush=True)

def atomic_table(path, rows):
    """非生产检查点原子写入，既有完整文件不覆盖。"""
    if path.exists():raise FileExistsError(path)
    tmp=path.with_suffix('.tmp')
    pq.write_table(pa.Table.from_pylist(rows),tmp)
    tmp.replace(path)

def pentads(stack, weights):
    """一次展开整瓦片候值，与原逐像元日重叠加权数学等价。"""
    values=np.zeros((len(weights),stack.shape[1]),dtype=np.float64)
    days=np.zeros(values.shape,dtype=np.uint8)
    for p, slots in enumerate(weights):
        for slot,count in slots:
            raw=stack[slot];valid=raw<=100
            values[p]+=np.where(valid,raw,0).astype(np.uint16)*count
            days[p]+=valid.astype(np.uint8)*count
        np.divide(values[p],days[p],out=values[p],where=days[p]>0)
    return values,days

def main():
    params=load_config(DEFAULT_CONFIG);settings=params['lai']
    OUT.mkdir(exist_ok=True)
    with (ROOT/'metadata/study_area_manifest.csv').open(encoding='utf-8-sig') as f:
        areas=list(csv.DictReader(f))
    bbox=json.loads(areas[-1]['bbox'])
    source_paths=[DEFAULT_CONFIG,Path(__file__),M2/'grid_manifest.parquet',M2/'time_pentad_calendar.parquet',BASE/'M3/grid_active_pentad.parquet',BASE/'M6/vegetation_grid_year.parquet']
    identity={'kind':'nonproduction_aerosol_only_audit','bbox':bbox,'inputs':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}}
    manifest=OUT/'identity.json'
    if manifest.exists():
        if json.loads(manifest.read_text(encoding='utf-8'))!=identity:raise ValueError('审计身份变化，不能续接旧检查点。')
    else:manifest.write_text(json.dumps(identity,ensure_ascii=False,indent=2),encoding='utf-8')
    calendar=defaultdict(list)
    for r in pq.read_table(M2/'time_pentad_calendar.parquet').to_pylist():calendar[r['year']].append(r)
    active=defaultdict(list)
    table=pq.read_table(BASE/'M3/grid_active_pentad.parquet',columns=['grid_id','year','pentad'],filters=[('active_flag','=',True)])
    for batch in table.to_batches(max_chunksize=8192):
        for r in batch.to_pylist():active[r['grid_id'],r['year']].append(r['pentad']-1)
    del table
    included={g for g,y in active}
    grid=[r for r in pq.read_table(M2/'grid_manifest.parquet').to_pylist() if r['grid_id'] in included]
    files=defaultdict(dict)
    first,last=settings['complete_years']
    for p in sorted((ROOT/'data/raw/modis/MCD15A3H/V061').rglob('*.hdf')):
        bits=p.name.split('.');year=int(bits[1][1:5]);day=int(bits[1][5:]);tile=bits[2]
        if first<=year<=last:
            slot=(day-1)//4
            if slot in files[year,tile]:raise ValueError('重复MODIS日期瓦片')
            files[year,tile][slot]=p
    tiles=sorted({t for y,t in files});mappings={};geometries={};covered=np.zeros(len(grid))
    for tile in tiles:
        ds=SD(str(next(iter(files[first,tile].values()))),SDC.READ)
        try:geometries[tile]=tile_geometry(ds)
        finally:ds.end()
        original=tile_mapping(grid,bbox,params['grid']['resolution_deg'],geometries[tile])
        if not original:continue
        pixels=np.unique(np.concatenate([a for a,b in original.values()]))
        mappings[tile]=(pixels,{i:(np.searchsorted(pixels,ix),area) for i,(ix,area) in original.items()})
        for i,(ix,area) in original.items():covered[i]+=area.sum()
        log(f'映射 {tile}：{len(original)} 格点，{len(pixels)} 原生像元')
    expected=np.array([g['area_km2']*1e6*(6371.007181/params['native_era5land']['earth_radius_km'])**2 for g in grid])
    assert np.allclose(covered,expected,rtol=1e-6,atol=0)
    for year in range(first,last+1):
        weights=composite_weights(year,calendar[year])
        for tile,(pixels,mapping) in mappings.items():
            target=OUT/f'checkpoint_{year}_{tile}.parquet'
            if target.exists():log(f'复用 {year} {tile}');continue
            slots=((date(year+1,1,1)-date(year,1,1)).days+3)//4
            stacks=[np.full((slots,len(pixels)),255,dtype=np.uint8) for _ in range(2)]
            log(f'读取 {year} {tile}，{len(files[year,tile])} 文件')
            for slot,p in sorted(files[year,tile].items()):
                ds=SD(str(p),SDC.READ)
                try:
                    if tile_geometry(ds)!=geometries[tile]:raise ValueError('原生瓦片几何变化')
                    layers=[]
                    for name in ['Lai_500m','FparLai_QC','FparExtra_QC']:
                        field=ds.select(name)
                        try:
                            values=field[:]
                            assert values.shape==(2400,2400) and values.dtype==np.uint8
                            if name=='Lai_500m':
                                attrs=field.attributes();assert np.isclose(attrs['scale_factor'],settings['scale_factor']) and attrs['add_offset']==0
                            layers.append(values.ravel()[pixels])
                        finally:field.endaccess()
                    raw,qc,extra=layers
                    strict=lai_qc(raw,qc,extra)
                    relaxed=lai_qc(raw,qc,extra & np.uint8(247)) & (extra!=255)
                    assert np.all(~strict | relaxed)
                    stacks[0][slot]=np.where(strict,raw,255);stacks[1][slot]=np.where(relaxed,raw,255)
                finally:ds.end()
            results=[]
            for version,stack in enumerate(stacks):
                values,days=pentads(stack,weights)
                for i,(ix,area) in mapping.items():
                    g=grid[i];periods=active.get((g['grid_id'],year),[])
                    if not periods:continue
                    val=values[np.ix_(periods,ix)];day=days[np.ix_(periods,ix)];valid=day>0;count=valid.sum(axis=0);keep=count>0
                    result=dict(grid_id=g['grid_id'],year=year,tile=tile,version=version,
                                native_valid_area=float(area[keep].sum()),
                                mean_area_sum=float(np.dot(area[keep],val[:,keep].sum(axis=0)/count[keep])),
                                days_area_sum=float(np.dot(area,day.sum(axis=0))),
                                valid_pentads=[p for j,p in enumerate(periods) if valid[j].any()])
                    for month in range(1,13):
                        positions=[j for j,p in enumerate(periods) if calendar[year][p]['start_date'].month==month]
                        expected_days=sum(calendar[year][periods[j]]['n_days'] for j in positions)
                        result[f'm{month}_expected']=float(area.sum()*expected_days)
                        result[f'm{month}_days']=float(np.dot(area,day[positions].sum(axis=0))) if positions else 0.
                        result[f'm{month}_lai_days']=float(np.dot(area,(val[positions]*day[positions]).sum(axis=0))*settings['scale_factor']) if positions else 0.
                    results.append(result)
                del values,days
            atomic_table(target,results)
            del stacks
            log(f'完成 {year} {tile}，{len(results)} 条配对格点记录')
    # 年表只做合成和质量比较，不读取任何效应结果。
    sums={}
    for f in sorted(OUT.glob('checkpoint_*.parquet')):
        for r in pq.read_table(f).to_pylist():
            key=(r['grid_id'],r['year'],r['version'])
            if key not in sums:sums[key]={**r,'valid_pentads':set(r['valid_pentads'])}
            else:
                item=sums[key];item['valid_pentads'].update(r['valid_pentads'])
                for name,value in r.items():
                    if name in ['native_valid_area','mean_area_sum','days_area_sum'] or name.startswith('m') and name[1:2].isdigit():item[name]+=value
    gd={g['grid_id']:g for g in grid};frozen={(r['grid_id'],r['year']):r for r in pq.read_table(BASE/'M6/vegetation_grid_year.parquet').to_pylist()};annual=[];max_time=0.;max_mean=0.
    for (gid,year,version),r in sorted(sums.items()):
        area=r['native_valid_area'];total=gd[gid]['area_km2']*1e6*(6371.007181/params['native_era5land']['earth_radius_km'])**2
        nd=sum(calendar[year][p]['n_days'] for p in active[gid,year]);space=min(1.,area/total);coverage=min(1.,r['days_area_sum']/(area*nd)) if area else 0.
        mean=r['mean_area_sum']/area*settings['scale_factor'] if area else None
        passed=space>=settings['annual_space_cover_min'] and coverage>=settings['annual_time_cover_min']
        r.update(temporal_coverage=coverage,spatial_coverage=space,annual_valid=passed,annual_mean=mean,valid_pentads=sorted(r['valid_pentads']))
        if version==0:
            old=frozen[gid,year];max_time=max(max_time,abs(coverage-old['temporal_coverage']));assert passed==old['annual_valid']
            assert abs(space-old['spatial_coverage'])<1e-10
            if passed:max_mean=max(max_mean,abs(mean-old['vegetation_annual_mean']))
        annual.append(r)
    assert max_time<1e-10 and max_mean<1e-10
    atomic_table(OUT/'annual_comparison.parquet',annual)
    (OUT/'verification.json').write_text(json.dumps(dict(n_active_grid_year=len(annual)//2,max_strict_time_error=max_time,max_strict_mean_error=max_mean,n_source_files=sum(map(len,files.values()))),indent=2),encoding='utf-8')
    log('全域配对复算完成，严格方案已核对冻结年表。')

if __name__=='__main__':main()
