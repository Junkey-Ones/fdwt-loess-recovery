"""汇总非生产气溶胶对照：样本支撑、地类空间分布及季节覆盖；不拟合效应。"""
from pathlib import Path
from collections import Counter,defaultdict
from statistics import median,mean
import sys,csv,json,hashlib
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from workflow.run_module import load_config,DEFAULT_CONFIG
from src.M5.scr_derive_outcomes import sen_slope
from src.M7.scr_fit_route1_models import effective_count
OUT=ROOT/'notebooks/lai_aerosol_audit_20261115';BASE=ROOT/'data/frozen/downstream/2026-11-13_主分析X_QC修复';M2=ROOT/'data/interim/era5land_base/2026-11-13_主分析X_QC修复'

def save(name,rows):
    if not rows:return
    p=OUT/name
    if p.exists():raise FileExistsError(p)
    with p.with_suffix('.tmp').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    p.with_suffix('.tmp').replace(p)

def main():
    params=load_config(DEFAULT_CONFIG);settings=params['lai'];rows=pq.read_table(OUT/'annual_comparison.parquet').to_pylist()
    mask={r['grid_id']:r for r in pq.read_table(BASE/'M3/grid_mask.parquet').to_pylist()};grid={r['grid_id']:r for r in pq.read_table(M2/'grid_manifest.parquet').to_pylist()}
    annual={(r['grid_id'],r['year'],r['version']):r for r in rows};bygroup=defaultdict(list);months=defaultdict(lambda:np.zeros(3));pairs=[]
    for r in rows:
        lc=mask[r['grid_id']]['land_cover'];version=r['version']
        bygroup[version,lc].append(r);bygroup[version,'all'].append(r)
        for m in range(1,13):
            for group in [lc,'all']:
                months[version,group,m]+=np.array([r[f'm{m}_expected'],r[f'm{m}_days'],r[f'm{m}_lai_days']])
        if version==1:
            old=annual[r['grid_id'],r['year'],0];expected=sum(r[f'm{m}_expected'] for m in range(1,13));newdays=r['days_area_sum']-old['days_area_sum']
            assert newdays>=-1e-4
            summer_expected=r['m7_expected']+r['m8_expected']
            pairs.append(dict(grid_id=r['grid_id'],year=r['year'],land_cover=lc,lat=grid[r['grid_id']]['lat'],lon=grid[r['grid_id']]['lon'],strict_valid=old['annual_valid'],relaxed_valid=r['annual_valid'],strict_time=old['temporal_coverage'],relaxed_time=r['temporal_coverage'],strict_mean=old['annual_mean'],relaxed_mean=r['annual_mean'],new_area_day_fraction=newdays/expected if expected else None,relaxed_jul_aug_cover=(r['m7_days']+r['m8_days'])/summer_expected if summer_expected else None))
    save('annual_paired.csv',pairs)
    land=[]
    for (version,lc),rs in sorted(bygroup.items()):
        land.append(dict(version=version,land_cover=lc,n_active_grid_year=len(rs),n_pass=sum(r['annual_valid'] for r in rs),median_time=float(np.median([r['temporal_coverage'] for r in rs]))))
    save('annual_landcover.csv',land)
    monthly=[]
    for (version,lc,m),(expected,days,lai_days) in sorted(months.items()):
        monthly.append(dict(version=version,land_cover=lc,month=m,expected_area_days=expected,valid_area_days=days,area_day_coverage=days/expected if expected else None,observed_day_weighted_lai=lai_days/days if days else None))
    save('monthly_coverage.csv',monthly)
    added=[]
    for (version,lc,m),(expected,days,lai_days) in sorted(months.items()):
        if version!=1:continue
        _,old_days,old_lai=months[0,lc,m];delta=days-old_days
        added.append(dict(land_cover=lc,month=m,added_area_day_fraction=delta/expected if expected else None,added_observation_mean=(lai_days-old_lai)/delta if delta>0 else None,strict_observation_mean=old_lai/old_days if old_days else None))
    save('added_observation_diagnostics.csv',added)
    events=pq.read_table(BASE/'M5/event_master.parquet').to_pylist();expo={r['episode_id']:r for r in pq.read_table(BASE/'M6/event_exposure.parquet').to_pylist()};start,end=settings['exposure_years'];width=settings['window_years'];summary=[];members=[]
    eligible=[r for r in events if start<=r['year']<=end]
    for version in [0,1]:
        good={(r['grid_id'],r['year']):r['annual_mean'] for r in rows if r['version']==version and r['annual_valid']}
        selected=[]
        for e in eligible:
            history=[(y,good[e['grid_id'],y]) for y in range(e['year']-width,e['year']) if (e['grid_id'],y) in good]
            if len(history)!=width or expo[e['episode_id']]['core_covariate_missing_reason']:continue
            selected.append(e);g=grid[e['grid_id']]
            members.append(dict(version=version,episode_id=e['episode_id'],grid_id=e['grid_id'],year=e['year'],land_cover=e['land_cover'],lat=g['lat'],lon=g['lon'],block_id=g['block_id'],lai_base=mean(v for y,v in history),lai_trend=sen_slope(history)))
        for domain in ['all','recovery','fr']:
            subset=[e for e in selected if domain=='all' or (e['recovery_risk_eligible'] if domain=='recovery' else e['route1_FR_eligible'] and e['F_R'] is not None)]
            clusters=[(e['grid_id'],e['year']) for e in subset];blocks=[grid[e['grid_id']]['block_id'] for e in subset]
            summary.append(dict(version=version,domain=domain,n_event=len(subset),n_exposure=len(set(clusters)),n_grid=len({e['grid_id'] for e in subset}),n_year=len({e['year'] for e in subset}),n_block=len(set(blocks)),block_kish=effective_count(blocks),exposure_kish=effective_count(clusters),n_interaction_complete=sum(expo[e['episode_id']]['exposure_complete_D'] for e in subset),latitude_median=median([grid[e['grid_id']]['lat'] for e in subset]) if subset else None,longitude_median=median([grid[e['grid_id']]['lon'] for e in subset]) if subset else None,land_cover=dict(Counter(e['land_cover'] for e in subset)),years=dict(sorted(Counter(e['year'] for e in subset).items()))))
    assert summary[0]['n_event']==sum(e['exposure_complete_L'] for e in expo.values())
    save('candidate_exposures.csv',members)
    # 同一候选暴露窗内比较两种QA，不用结局效应评价测量变化。
    paired_trends=[];seen=set()
    for r in members:
        key=(r['grid_id'],r['year'])
        if r['version']!=1 or key in seen:continue
        seen.add(key)
        history=[(y,annual.get((r['grid_id'],y,0),{}).get('annual_mean')) for y in range(r['year']-width,r['year'])]
        if any(v is None for y,v in history):continue
        oldtrend=sen_slope(history);oldbase=mean(v for y,v in history)
        paired_trends.append(dict(grid_id=r['grid_id'],year=r['year'],land_cover=r['land_cover'],strict_unthresholded_base=oldbase,relaxed_base=r['lai_base'],strict_unthresholded_trend=oldtrend,relaxed_trend=r['lai_trend'],base_change=r['lai_base']-oldbase,trend_change=r['lai_trend']-oldtrend,trend_sign_reversal=oldtrend*r['lai_trend']<0))
    save('same_window_qc_changes.csv',paired_trends)
    qc_change=[]
    for lc in ['all','forest','grassland','cropland','other']:
        rs=[r for r in paired_trends if lc=='all' or r['land_cover']==lc]
        if rs:qc_change.append(dict(land_cover=lc,n_exposure=len(rs),median_base_change=median(r['base_change'] for r in rs),median_absolute_base_change=median(abs(r['base_change']) for r in rs),median_absolute_trend_change=median(abs(r['trend_change']) for r in rs),sign_reversal_fraction=mean(r['trend_sign_reversal'] for r in rs)))
    save('same_window_qc_change_summary.csv',qc_change)
    total_expected=sum(months[1,'all',m][0] for m in range(1,13));total_added=sum(months[1,'all',m][1]-months[0,'all',m][1] for m in range(1,13))
    result=dict(verification=json.loads((OUT/'verification.json').read_text()),annual=land,candidates=summary,n_exposure_period_events=len(eligible),all_area_days_added_fraction=total_added/total_expected,baseline_land_cover=dict(Counter(e['land_cover'] for e in eligible)),baseline_latitude_median=median(grid[e['grid_id']]['lat'] for e in eligible),retained_annual_with_summer_below50=sum(r['relaxed_valid'] and r['relaxed_jul_aug_cover'] is not None and r['relaxed_jul_aug_cover']<.5 for r in pairs),same_window_qc_changes=qc_change,measurement_validation='coverage_and_consistency_only_no_independent_truth')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':main()
