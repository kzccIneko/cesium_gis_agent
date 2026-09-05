"""DEM 数据类工具：元信息读取与真实 DEM 下载。

包含工具：
    get_dem_metadata   —— 读取本地 DEM 文件元信息（分析前的可用性检查）
    download_srtm      —— 按 bbox 下载 Copernicus GLO-30 DEM 并缓存
"""

from __future__ import annotations

import time
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict, Sequence

import numpy as np

from .base import ARTIFACT_ROOT, bbox_area_km2, validate_bbox
from .errors import ToolErrorType, ToolException, fail, ok

# 单次下载的面积上限（km²）—— 超过则拒绝，避免长时间阻塞
MAX_DOWNLOAD_AREA_KM2 = 250_000

DEM_CACHE_DIR = Path(gettempdir()) / "cesiumjs_dem_cache"


def get_dem_metadata(dem_path: str) -> Dict[str, Any]:
    """读取 DEM 元信息，判断该文件能否直接用于分析。

    典型用途：用户提供本地 DEM 后，先调用本工具确认坐标系、
    波段数、是否需要 terrain_rgb 解码，再决定后续分析参数。

    Args:
        dem_path: DEM 文件路径（GeoTIFF）

    Returns:
        data.crs / width / height / count / analysis_ready /
              decode_suggestions / bounds_wgs84
    """
    tool = "get_dem_metadata"
    t0 = time.perf_counter()

    from ..services.analysis_service import get_dem_metadata as _meta

    if not dem_path or not str(dem_path).strip():
        return fail(
            tool, "dem_path 不能为空", ToolErrorType.INVALID_BBOX,
            (time.perf_counter() - t0) * 1000,
        ).to_dict()

    try:
        meta = _meta(str(dem_path).strip())
    except FileNotFoundError as exc:
        return fail(
            tool, f"DEM 文件不存在：{dem_path}", ToolErrorType.DEM_NOT_FOUND,
            (time.perf_counter() - t0) * 1000,
        ).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(
            tool, f"读取 DEM 失败：{exc}", ToolErrorType.DEM_LOAD_FAILED,
            (time.perf_counter() - t0) * 1000,
        ).to_dict()

    warnings = []
    if not meta.get("analysis_ready"):
        warnings.append(
            f"该 DEM 不能直接用于分析：{meta.get('analysis_error')}。"
            f"建议解码方式：{meta.get('decode_suggestions')}"
        )
    if not meta.get("crs"):
        warnings.append("未识别到坐标系（CRS），分析前需确认投影")

    data: Dict[str, Any] = {
        "summary": (
            f"DEM 尺寸 {meta.get('width')}×{meta.get('height')}，"
            f"坐标系统 {meta.get('crs') or '未识别'}，"
            f"{'可直接分析' if meta.get('analysis_ready') else '需要解码后分析'}"
        ),
        "dem_path": meta.get("dem_path"),
        "crs": meta.get("crs"),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "band_count": meta.get("count"),
        "dtype": meta.get("dtypes"),
        "nodata": meta.get("nodata"),
        "analysis_ready": meta.get("analysis_ready"),
        "decode_suggestions": meta.get("decode_suggestions"),
        "bounds_wgs84": meta.get("bounds_wgs84"),
    }
    if warnings:
        data["warnings"] = warnings

    return ok(tool, data, (time.perf_counter() - t0) * 1000).to_dict()


def download_srtm(bbox: Sequence[float]) -> Dict[str, Any]:
    """按经纬度范围下载 Copernicus GLO-30（30 m）DEM 并本地缓存。

    首次调用需联网下载（10–30 s），后续相同范围直接命中缓存。
    返回的 dem_path 可直接传给其他工具作为 dem_path 参数。

    Args:
        bbox: [west, south, east, north]

    Returns:
        data.dem_path / resolution_m / area_km2 / cached
    """
    tool = "download_srtm"
    t0 = time.perf_counter()

    try:
        west, south, east, north = validate_bbox(bbox)
    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()

    area = bbox_area_km2((west, south, east, north))
    if area > MAX_DOWNLOAD_AREA_KM2:
        return fail(
            tool,
            f"请求范围约 {area:,.0f} km²，超过单次下载上限 "
            f"{MAX_DOWNLOAD_AREA_KM2:,} km²。请缩小范围后重试",
            ToolErrorType.INVALID_BBOX,
            (time.perf_counter() - t0) * 1000,
        ).to_dict()

    DEM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DEM_CACHE_DIR / f"dem_{west:.3f}_{south:.3f}_{east:.3f}_{north:.3f}.tif"

    if out_path.exists():
        return ok(
            tool,
            {
                "summary": f"命中本地缓存 DEM（约 {area:,.0f} km²，30 m 分辨率）",
                "dem_path": str(out_path),
                "resolution_m": 30.0,
                "area_km2": area,
                "cached": True,
            },
            (time.perf_counter() - t0) * 1000,
        ).to_dict()

    try:
        from dem_stitcher import stitch_dem
        import rasterio
        from rasterio.transform import from_bounds
    except ImportError:
        return fail(
            tool,
            "未安装 dem_stitcher，无法下载在线 DEM。"
            "可改用本地 DEM 文件，或不传 dem_path 使用合成地形做流程验证",
            ToolErrorType.OUT_OF_CAPABILITY,
            (time.perf_counter() - t0) * 1000,
        ).to_dict()

    try:
        arr, _profile = stitch_dem(
            bounds=(west, south, east, north), dem_name="glo_30"
        )
        rows, cols = arr.shape
        with rasterio.open(
            out_path, "w", driver="GTiff",
            height=rows, width=cols, count=1, dtype=np.float64,
            crs="EPSG:4326",
            transform=from_bounds(west, south, east, north, cols, rows),
            nodata=np.nan,
        ) as dst:
            dst.write(arr, 1)
    except Exception as exc:  # noqa: BLE001
        return fail(
            tool,
            f"DEM 下载失败：{exc}。可能是网络不可达或该范围无数据覆盖",
            ToolErrorType.OUT_OF_CAPABILITY,
            (time.perf_counter() - t0) * 1000,
        ).to_dict()

    return ok(
        tool,
        {
            "summary": (
                f"已下载 {area:,.0f} km² 的 30 m DEM（栅格 {rows}×{cols}），"
                f"耗时 {(time.perf_counter()-t0):.1f}s"
            ),
            "dem_path": str(out_path),
            "resolution_m": 30.0,
            "area_km2": area,
            "grid_shape": [rows, cols],
            "cached": False,
        },
        (time.perf_counter() - t0) * 1000,
    ).to_dict()
