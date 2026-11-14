"""将 SoilGrids 和 NASADEM 原生像元聚合到 M2 格点。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
from functools import lru_cache
import json
import re
from zipfile import ZipFile

import numpy as np


def grid_bounds(grid, bbox, resolution):
    """取研究区裁切后的格点边界。"""
    west, south, east, north = bbox
    half = resolution / 2
    return np.array([(max(west,g["lon"]-half),max(south,g["lat"]-half),
                      min(east,g["lon"]+half),min(north,g["lat"]+half)) for g in grid])


def soil_values(paths, bounds, minimum, report):
    """按完整三层厚度加权，在 Goode 等积投影内计算像元交叠。"""
    import rasterio
    import shapely
    from pyproj import Transformer

    report("读取 SoilGrids", "打开并核对六层 GeoTIFF", total=len(paths), unit="文件")
    with ExitStack() as stack:
        datasets = [stack.enter_context(rasterio.open(p)) for p in paths]
        base = datasets[0]
        transform = base.transform
        dx, dy = transform.a, -transform.e
        if (base.crs is None or "Interrupted_Goode_Homolosine" not in base.crs.to_wkt()
                or not np.allclose((dx, dy), 250, atol=.01, rtol=0) or transform.b or transform.d):
            raise ValueError("SoilGrids 原生投影或分辨率异常。")
        if any((d.crs,d.transform,d.shape,d.dtypes) != (base.crs,transform,base.shape,("int16",)) for d in datasets):
            raise ValueError("SoilGrids 六层网格或类型不一致。")
        arrays = []
        for done, (path, dataset) in enumerate(zip(paths, datasets)):
            report("读取 SoilGrids", f"读取 {path.name}", done=done, total=len(paths), unit="文件")
            arrays.append(dataset.read(1, masked=True))
    report("汇总 SoilGrids", "计算土壤质地与有效像元", total=len(bounds), unit="格点")
    # 六层同时为零的像元缺少可判读的组成信息，保留为缺测并审计。
    all_zero = np.logical_and.reduce([a.filled(-32768)==0 for a in arrays])
    native = []
    for first in (0,3):
        layers = [a.filled(-32768) for a in arrays[first:first+3]]
        valid = ~all_zero & np.logical_and.reduce([(a>=0)&(a<=1000) for a in layers])
        native.append(np.where(valid, (layers[0]*5.+layers[1]*10.+layers[2]*15.)/300., np.nan))
    project = Transformer.from_crs("EPSG:4326",base.crs.to_wkt(),always_xy=True)
    values = []
    for done, (w,s,e,n) in enumerate(bounds):
        if done % 16 == 0:
            report("汇总 SoilGrids", "计算原生像元与格点的交叠面积",
                   done=done, total=len(bounds), unit="格点")
        # 将经纬边界细分至约 0.2 km，再投影至等积坐标。
        t = np.linspace(0.,1.,65)
        lon = np.concatenate((w+(e-w)*t,np.full(65,e),e-(e-w)*t,np.full(65,w)))
        lat = np.concatenate((np.full(65,s),s+(n-s)*t,np.full(65,n),n-(n-s)*t))
        x,y = project.transform(lon,lat)
        polygon = shapely.Polygon(np.column_stack((x,y)))
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError("SoilGrids 目标格点投影异常。")
        l,b,r,u = polygon.bounds
        c0,c1 = max(0,int(np.floor((l-transform.c)/dx))),min(base.width,int(np.ceil((r-transform.c)/dx)))
        r0,r1 = max(0,int(np.floor((transform.f-u)/dy))),min(base.height,int(np.ceil((transform.f-b)/dy)))
        iy,ix = np.mgrid[r0:r1,c0:c1]
        px,py = transform.c+ix*dx,transform.f-iy*dy
        areas = shapely.area(shapely.intersection(polygon,shapely.box(px,py-dy,px+dx,py)))
        record = {}
        for name,layer in zip(("sand_0_30","clay_0_30"),native):
            data=layer[iy,ix]
            valid=np.isfinite(data)
            area=areas[valid].sum()
            record[name+"_coverage"]=float(min(1.,area/polygon.area))
            record[name]=float(np.dot(areas[valid],data[valid])/area) if area and area/polygon.area>=minimum else None
        values.append(record)
    return values, int(all_zero.sum())


def tile_key(path):
    """解析 NASADEM 文件名的西南角。"""
    match = re.fullmatch(r"NASADEM_HGT_n(\d{2})e(\d{3})\.zip",path.name)
    if not match:
        raise ValueError(f"NASADEM 文件名不符：{path.name}")
    return int(match[1]),int(match[2])


def load_dem(path):
    """解码 HGT 和 NUM，并排除产品错误和异常编码。"""
    with ZipFile(path) as src:
        layers = []
        for suffix,dtype in ((".hgt",">i2"),(".num","u1")):
            name, = [n for n in src.namelist() if n.endswith(suffix)]
            values=np.frombuffer(src.read(name),dtype=dtype)
            if values.size != 3601**2:
                raise ValueError(f"NASADEM 栅格尺寸不符：{path.name}")
            layers.append(values.reshape(3601,3601))
    height,num=layers
    if np.any(((height < -500) | (height > 9000)) & (height != -32768) & (num != 255)):
        raise ValueError(f"NASADEM 高程异常：{path.name}")
    return height,num


@lru_cache(maxsize=512)
def gradient_weights(pattern):
    """为有足够有效邻点的局部二次拟合生成梯度系数。"""
    y,x=np.mgrid[1:-2:-1,-1:2]
    x,y=x.ravel(),y.ravel()
    matrix=np.column_stack((x*x,x*y,y*y,x,y,np.ones(9)))
    valid=np.array([(pattern>>i)&1 for i in range(9)],dtype=bool)
    if valid.sum()<6 or np.linalg.matrix_rank(matrix[valid])<6:
        return None
    return valid,np.linalg.pinv(matrix[valid])[3:5]


def slope_patch(padded, latitude):
    """以邻域有效点等权拟合局部二次面并按米制距离求坡度。"""
    from numpy.lib.stride_tricks import sliding_window_view

    windows = sliding_window_view(padded, (3, 3))
    radians=np.deg2rad(latitude)
    eccentricity=0.0066943799901413165
    factor=1-eccentricity*np.sin(radians)**2
    step=np.deg2rad(1/3600)
    dx=step*6378137*np.cos(radians)/np.sqrt(factor)
    dy=step*6378137*(1-eccentricity)/factor**1.5
    if np.isfinite(padded).all():
        _, weights = gradient_weights(511)
        # 直接对窗口视图求两个梯度，避免复制窗口和启动 BLAS 线程。
        slope = np.einsum("ijab,kab->kij", windows, weights.reshape(2, 3, 3))
        return np.rad2deg(np.arctan(np.hypot(slope[0] / dx, slope[1] / dy)))

    windows = windows.reshape(*latitude.shape, 9)
    valid = np.isfinite(windows)
    patterns = np.sum(valid * (1 << np.arange(9, dtype=np.uint16)), axis=-1, dtype=np.uint16)
    out = np.full(latitude.shape, np.nan)
    for pattern in np.unique(patterns):
        coeff=gradient_weights(int(pattern))
        if coeff is None or not pattern & 16:
            continue
        mask,weights=coeff
        selected=patterns==pattern
        slope = np.einsum("ij,kj->ik", windows[selected][:, mask], weights)
        out[selected]=np.rad2deg(np.arctan(np.hypot(slope[:,0]/dx[selected],slope[:,1]/dy[selected])))
    return out


def dem_values(paths, bounds, minimum, report, *, workers=1):
    """使用相邻瓦片邻点求坡度并按球面交叠面积汇总。"""
    files={tile_key(p):p for p in paths}
    if len(files)!=len(paths):
        raise ValueError("NASADEM 瓦片重复。")
    load=lru_cache(maxsize=4)(load_dem)
    totals=np.zeros((len(bounds),4))
    source_area=np.zeros((len(bounds),256))
    step=1/3600
    candidates = {
        (s, w): np.flatnonzero((bounds[:,0]<w+1)&(bounds[:,2]>w)&(bounds[:,1]<s+1)&(bounds[:,3]>s))
        for s, w in files
    }
    total = sum(map(len, candidates.values()))
    done = 0
    executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else nullcontext()
    with executor as pool:
        for (s,w),path in sorted(files.items()):
            candidate = candidates[s, w]
            if not len(candidate):
                continue
            report("汇总 NASADEM", f"读取 {path.stem} 并准备相邻瓦片",
                   done=done, total=total, unit="瓦片格点")
            height,num=load(path)
            padded=np.full((3603,3603),np.nan,dtype=np.float32)
            padded[1:-1,1:-1]=np.where((num!=255)&(height!=-32768),height,np.nan)
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    if not (dy or dx) or (s+dy,w+dx) not in files:
                        continue
                    h,q=load(files[s+dy,w+dx])
                    dst_y,src_y={1:(0,-2),0:(slice(1,-1),slice(None)),-1:(-1,1)}[dy]
                    dst_x,src_x={-1:(0,-2),0:(slice(1,-1),slice(None)),1:(-1,1)}[dx]
                    v,k=h[src_y,src_x],q[src_y,src_x]
                    padded[dst_y,dst_x]=np.where((k!=255)&(v!=-32768),v,np.nan)
            def aggregate_cell(i):
                west,south,east,north=bounds[i]
                x0=max(0,int(np.floor((west-w)/step+.5)))
                x1=min(3601,int(np.ceil((east-w)/step+.5)))
                y0=max(0,int(np.floor((s+1-north)/step+.5)))
                y1=min(3601,int(np.ceil((s+1-south)/step+.5)))
                if x0>=x1 or y0>=y1:
                    return None
                lon=w+np.arange(x0,x1)*step
                lat=s+1-np.arange(y0,y1)*step
                x=np.maximum(0,np.minimum(min(east,w+1),lon+step/2)-np.maximum(max(west,w),lon-step/2))
                top=np.minimum(min(north,s+1),lat+step/2)
                bottom=np.maximum(max(south,s),lat-step/2)
                y=np.maximum(0,np.sin(np.deg2rad(top))-np.sin(np.deg2rad(bottom)))
                weight=y[:,None]*np.deg2rad(x)
                center=padded[y0+1:y1+1,x0+1:x1+1]
                slope=slope_patch(padded[y0:y1+2,x0:x1+2],np.broadcast_to(lat[:,None],center.shape))
                sums = np.empty(4)
                for k,values in enumerate((center,slope)):
                    good=np.isfinite(values)
                    valid_weight = weight[good]
                    sums[2*k:2*k+2] = (valid_weight.sum(), np.einsum("i,i->", valid_weight, values[good]))
                sources=num[y0:y1,x0:x1]
                return i, sums, np.bincount(sources.ravel(), weights=weight.ravel(), minlength=256)

            batch_size = max(8, workers)
            for tile_done in range(0, len(candidate), batch_size):
                report("汇总 NASADEM", f"{path.stem} 计算坡度与高程 · 瓦片内 {tile_done}/{len(candidate)} · {workers} 线程",
                       done=done + tile_done, total=total, unit="瓦片格点")
                batch = candidate[tile_done:tile_done + batch_size]
                results = map(aggregate_cell, batch) if pool is None else pool.map(aggregate_cell, batch)
                for record in results:
                    if record is not None:
                        i, sums, sources = record
                        totals[i] += sums
                        source_area[i] += sources
            done += len(candidate)
    report("汇总 NASADEM", "整理高程、坡度及来源覆盖率", done=done, total=total, unit="瓦片格点")
    results=[]
    for row,(w,s,e,n),sources in zip(totals,bounds,source_area):
        total=np.deg2rad(e-w)*(np.sin(np.deg2rad(n))-np.sin(np.deg2rad(s)))
        record={"nasadem_num_area_fractions":json.dumps(
                    {str(i):float(a/total) for i,a in enumerate(sources) if a>0}),
                "slope_method":"nasadem_quadric_3x3_unweighted_enu"}
        for k,name in enumerate(("elevation_m","slope_deg")):
            area,value=row[2*k:2*k+2]
            record[name+"_coverage"]=float(min(1.,area/total))
            record[name]=float(value/area) if area and area/total>=minimum else None
        results.append(record)
    return results


def static_covariates(soil, terrain, grid, bbox, params, report, *, workers=1):
    """生成逐格点静态协变量及覆盖审计。"""
    bounds=grid_bounds(grid,bbox,params["grid"]["resolution_deg"])
    minimum=params["spatial"]["valid_area_min"]
    soil_rows,zero=soil_values(soil,bounds,minimum,report)
    report("汇总 SoilGrids", f"六层同为零的原生像元数：{zero}",
           done=len(bounds), total=len(bounds), unit="格点")
    terrain_rows=dem_values(terrain, bounds, minimum, report, workers=workers)
    return [dict(grid_id=g["grid_id"],**a,**b) for g,a,b in zip(grid,soil_rows,terrain_rows)]
