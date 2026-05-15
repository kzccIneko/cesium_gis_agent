import numpy as np
import rasterio

# 临时脚本：统计 DEM 有效值比例与基础统计量
p=r'F:/CZ/VS_Code_Programs/CesiumJS_Debug/cesium_old/data/Terrain/cite19.tif'
with rasterio.open(p) as ds:
    arr=ds.read(1, masked=True)
    finite=np.asarray(arr.filled(np.nan),dtype=float)
    valid=np.isfinite(finite)
    print('valid_ratio=',float(valid.mean()))
    print('min/max/mean=',float(np.nanmin(finite)),float(np.nanmax(finite)),float(np.nanmean(finite)))
    print('dtype=',arr.dtype,'nodata=',ds.nodata)
