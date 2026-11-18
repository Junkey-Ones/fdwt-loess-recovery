"""离散RT中位数的CDF同时带反演；避免连续分位数密度近似。
作者：Codex。空间×年份均值得分协方差，Bonferroni同时带，渐近方法。
输入整数恢复候数和簇标签；输出可有开放端点的中位数区间及状态。
"""
from statistics import NormalDist
import numpy as np


def discrete_median_interval(values,space,years,params):
    """逐整数阈值估计CDF，先构造同时带，再反演其中位数集合。"""
    values=np.asarray(values,dtype=float)
    if len(space)!=len(values) or len(years)!=len(values):
        raise ValueError("恢复候数与空间、年份标签长度必须一致。")
    if not len(values) or not np.isfinite(values).all() or np.any(values<1) or np.any(values!=np.floor(values)):
        raise ValueError("恢复候数必须是有限正整数。")
    if len(set(years))<params["infer"]["year_score_bootstrap"]["min_clusters"]:
        return (None,None),"insufficient_years"
    maximum=int(values.max());cuts=np.arange(1,maximum)
    if not len(cuts):return (1.,None),"upper_unbounded"
    n=len(values);cdf=np.cumsum(np.bincount(values.astype(int),minlength=maximum+1))[1:maximum]/n
    components=[]
    for labels in (space,years,list(zip(space,years))):
        distinct={label:i for i,label in enumerate(sorted(set(labels)))}
        if len(distinct)<2:return (None,None),"insufficient_clusters"
        histogram=np.zeros((len(distinct),maximum+1))
        for label,value in zip(labels,values,strict=True):histogram[distinct[label],int(value)]+=1
        sizes=histogram.sum(axis=1)
        score=np.cumsum(histogram,axis=1)[:,1:maximum]-sizes[:,None]*cdf
        components.append(np.sum(score**2,axis=0)*len(distinct)/(len(distinct)-1)/n**2)
    variance=components[0]+components[1]-components[2]
    valid=(variance>0)&(cdf>0)&(cdf<1)
    lower=np.zeros(len(cuts));upper=np.ones(len(cuts))
    z=NormalDist().inv_cdf(1-params["multiple_testing"]["family_alpha"]/(2*len(cuts)))
    center=np.log(cdf[valid]/(1-cdf[valid]))
    half=z*np.sqrt(variance[valid])/(cdf[valid]*(1-cdf[valid]))
    lower[valid]=np.exp(-np.logaddexp(0,-(center-half)))
    upper[valid]=np.exp(-np.logaddexp(0,-(center+half)))
    lower=np.maximum.accumulate(lower);upper=np.minimum.accumulate(upper[::-1])[::-1]
    left=np.flatnonzero(upper>=.5);right=np.flatnonzero(lower>.5)
    low=float(cuts[left[0]]) if len(left) else float(maximum)
    high=float(cuts[right[0]]) if len(right) else None
    if high is not None and low>high:return (None,None),"inconsistent_band"
    return (low,high),"available" if high is not None else "upper_unbounded"
