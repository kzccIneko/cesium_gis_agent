"""把前端从 Cesium 自带地形采样来的高程网格落成 GeoTIFF。

为什么需要这一步：

三维系统里本来就挂着 Cesium World Terrain。但后端的分析工具只认"文件路径"，
没有路径就退回 `_synthetic_dem()` —— 一条构造出来的正弦曲面。
结果就是用户问「算一下这片区域的坡度」，拿到的是一堆**和真实地表毫无关系**的数字
（冒烟截图里整片绿油油就是这个原因）。

前端能采样到真实高程，后端能读 GeoTIFF，中间只差一个"把数组写成文件"的环节 ——
就是这个模块。工具层完全不用改：它拿到的就是一个普通的 DEM 文件。

约定（前后端必须一致，改了要两边一起改）：
    · heights 的行序是**从北到南**（第 0 行 = 最北边），与 GeoTIFF 的行序一致；
    · 无效点用 `null` 表示（JSON 不支持 NaN），落盘时写成 nodata；
    · 输出固定为 EPSG:4326 单波段 float32，带 nodata 与 LZW 压缩。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

DEM_CACHE_ROOT = Path(gettempdir()) / "geoagent_dem"
DEM_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

# nodata 取一个明显不可能是真实高程的值
NODATA = -9999.0


def _content_key(bbox: Sequence[float], heights: Sequence[Sequence[Optional[float]]]) -> str:
    """按内容做键 —— 同一块区域重复提问时直接复用，不用重写文件。"""
    h = hashlib.sha1()
    h.update(json.dumps([round(float(v), 6) for v in bbox[:4]]).encode())
    h.update(str(len(heights)).encode())
    h.update(str(len(heights[0]) if heights else 0).encode())
    # 只取少量采样点参与哈希，避免大网格序列化开销
    flat = [v for row in heights for v in row]
    step = max(1, len(flat) // 256)
    for v in flat[::step]:
        h.update(("%.2f" % v if isinstance(v, (int, float)) else "na").encode())
    return h.hexdigest()[:16]


def write_heights_as_geotiff(
    bbox: Sequence[float],
    heights: Sequence[Sequence[Optional[float]]],
    *,
    reuse: bool = True,
) -> Dict[str, Any]:
    """把高程网格写成 GeoTIFF，返回 {"path": ..., "shape": ..., "valid_ratio": ...}。

    Args:
        bbox: [minLon, minLat, maxLon, maxLat]
        heights: 二维高程数组，行序**北 → 南**，无效点用 None
        reuse: 内容相同则复用已落盘的文件

    Raises:
        ValueError: 网格为空、不是矩形、或有效点太少
    """
    west, south, east, north = (float(v) for v in bbox[:4])
    if east <= west or north <= south:
        raise ValueError(f"bbox 非法：{bbox}")

    if not heights or not heights[0]:
        raise ValueError("高程网格为空")

    nrows = len(heights)
    ncols = len(heights[0])
    if ncols < 2 or nrows < 2:
        raise ValueError(f"高程网格太小：{nrows}×{ncols}，至少需要 2×2")

    # 转 float32，None/非法值 → nan → nodata
    arr = np.full((nrows, ncols), np.nan, dtype=np.float32)
    for j, row in enumerate(heights):
        if len(row) != ncols:
            raise ValueError(f"高程网格第 {j} 行长度 {len(row)} 与首行 {ncols} 不一致")
        for i, v in enumerate(row):
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if np.isfinite(fv):
                arr[j, i] = fv

    valid_ratio = float(np.isfinite(arr).mean())
    if valid_ratio < 0.05:
        raise ValueError(
            f"高程网格有效点仅 {valid_ratio:.1%}，地形数据不可用（可能该区域无地形瓦片）"
        )

    out_path = DEM_CACHE_ROOT / f"cesium_{_content_key(bbox, heights)}.tif"
    if reuse and out_path.exists():
        return {
            "path": str(out_path),
            "shape": [nrows, ncols],
            "valid_ratio": valid_ratio,
            "reused": True,
        }

    import rasterio
    from rasterio.transform import from_bounds

    # GeoTIFF 行序为北 → 南，与传入约定一致，无需翻转
    transform = from_bounds(west, south, east, north, ncols, nrows)
    profile = {
        "driver": "GTiff",
        "height": nrows,
        "width": ncols,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": NODATA,
        "compress": "lzw",
    }

    arr = np.where(np.isfinite(arr), arr, NODATA).astype(np.float32)
    # 原子写：先写临时文件再改名，避免读到半个文件
    tmp_path = out_path.with_suffix(".tif.part")
    with rasterio.open(tmp_path, "w", **profile) as ds:
        ds.write(arr, 1)
    tmp_path.replace(out_path)

    return {
        "path": str(out_path),
        "shape": [nrows, ncols],
        "valid_ratio": valid_ratio,
        "reused": False,
    }


def cleanup_older_than(seconds: float = 3600.0) -> int:
    """清理过期的网格文件（默认 1 小时），返回删除数量。"""
    import time

    now = time.time()
    removed = 0
    for p in DEM_CACHE_ROOT.glob("cesium_*.tif*"):
        try:
            if now - p.stat().st_mtime > seconds:
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed
