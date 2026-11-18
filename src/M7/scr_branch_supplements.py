"""F_Z发生与分支DFAI强度的预设探索补充。
作者：Codex。输入M5主事件/分支/恢复轨迹、M6暴露及冻结参数；M7统一发布。
只创建结局视图，不修改FR主样本；未知判定不归阴性。
"""
from collections import Counter
from src.M7.scr_fit_route1_models import fit_route1_models,summarize_fr_support
from src.M7.scr_model_sensitivity import TABLES
from src.M7.scr_recovery_distribution import recovery_distribution


def prepare_branch_views(events,branches,trajectories):
    """按各分支自己的接续候连接活跃窗，严格强度域不筛发生模型。"""
    lookup={}
    for row in branches:
        key=row["episode_id"],row["branch"]
        if key in lookup:raise ValueError("分支补充不允许混合重复分支定义。")
        lookup[key]=row
    active={(r["episode_id"],r["t_abs"]):r.get("active_flag") for r in trajectories}
    view=[];intensities={"F_R":[],"F_Z":[]};audit=Counter()
    for event in events:
        eligible=bool(event["route1_A_eligible"])
        fz=event.get("F_Z");fz_branch=lookup.get((event["episode_id"],"F_Z"))
        if fz is True and fz_branch is None:
            raise ValueError("FZ阳性事件缺少自身接续分支。")
        if eligible:
            audit["n_a"]+=1
            if fz is True:
                flag=active.get((event["episode_id"],fz_branch["t_w"]))
                eligible=flag is True
                if not eligible:audit["unknown_active_window" if flag is None else "outside_active_window"]+=1
            if eligible:audit["unknown" if fz is None else "positive" if fz else "negative"]+=1
        tw=fz_branch["t_w"] if fz_branch is not None else None
        view.append(dict(event,F_R=fz,route1_FR_eligible=eligible,F_R_subtype=None if tw is None else
                         "pre" if tw<event["t_e"] else "sync" if tw==event["t_e"] else "post"))
        for name in intensities:
            branch=lookup.get((event["episode_id"],name))
            if branch is None or not event["route1_A_eligible"]:continue
            if active.get((event["episode_id"],branch["t_w"])) is not True:continue
            if branch["E2a_eligible"] and branch.get("DFAI") is not None:
                intensities[name].append(dict(event,DFAI=branch["DFAI"]))
    return view,intensities,dict(audit)


def branch_supplements(events,exposures,branches,trajectories,blocks,superblocks,params,identity,report=None):
    """四个FZ logit与按分支DFAI分布单列，不产生主检验p值。"""
    view,intensities,audit=prepare_branch_views(events,branches,trajectories)
    result={name:[] for name in TABLES.values()}
    result.update(fz_grid_year=[],fz_spatial=[],dfai_distribution=[])
    if "fz" in params["route1"]["supplements"]:
        output=fit_route1_models(view,exposures,[],blocks,superblocks,params,identity,
                                selection="fr_only",exploratory=True,report=report)
        for source,target in TABLES.items():
            for row in output[source]:
                row=dict(row,sensitivity="fz",analysis_id=row["analysis_id"].replace("q2_fr","q2_fz").replace("q3_fr_","q3_fz_"))
                if "outcome" in row:row["outcome"]="F_Z"
                if row.get("formula"):row["formula"]=row["formula"].replace("F_R ~","F_Z ~")
                if "estimand" in row:row["estimand"]=row["analysis_id"]
                result[target].append(row)
        result["fz_grid_year"],result["fz_spatial"]=summarize_fr_support(view,blocks,superblocks,params)
    if "dfai" in params["route1"]["supplements"]:
        for branch,rows in intensities.items():
            summaries=recovery_distribution(rows,exposures,blocks,superblocks,params,metrics=("DFAI",))
            result["dfai_distribution"].extend(dict(r,branch=branch,population="route1_A_positive_branch_strict_E2a")
                for r in summaries if r["domain"]=="region")
    audit["dfai_strict_counts"]={k:len(v) for k,v in intensities.items()}
    return result,audit
