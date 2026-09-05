"""工具层基础设施：参数校验、栅格统计（含范围告警）、产物落盘。

设计原则（Week 1 核心约束）：
1. 输入必须可序列化 —— bbox 用 [w, s, e, n] 列表，不传 Pydantic 对象 / numpy 数组
2. 输出必须是结构化 dict —— 数值带单位、带范围、带告警
3. 大数组不内联 —— 落盘为 GeoJSON / CZML / KML / NPZ，返回路径
"""

from __future__ import annotations

import json
import math
import uuid
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .errors import ToolErrorType, ToolException

# 工具产物输出目录（与后端 API 的 outputs 目录分离，避免互相干扰）
ARTIFACT_ROOT = Path(gettempdir()) / "geoagent_artifacts"
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

# 分辨率合法区间：过小无意义，过大会导致计算与内存爆炸
MIN_RESOLUTION = 16
MAX_RESOLUTION = 2048

# 经纬度合法范围
LON_RANGE = (-180.0, 180.0)
LAT_RANGE = (-90.0, 90.0)


# ── 参数校验 ────────────────────────────────────────────────────────
def validate_bbox(bbox: Sequence[float]) -> Tuple[float, float, float, float]:
    """校验并规范化 bbox = [west, south, east, north]。"""
    if bbox is None or len(bbox) != 4:
        raise ToolException(
            f"bbox 必须是 4 个数值 [west, south, east, north]，收到：{bbox!r}",
            ToolErrorType.INVALID_BBOX,
        )
    try:
        west, south, east, north = (float(v) for v in bbox)
    except (TypeError, ValueError) as exc:
        raise ToolException(
            f"bbox 含非数值元素：{bbox!r}", ToolErrorType.INVALID_BBOX
        ) from exc

    if not (LON_RANGE[0] <= west <= LON_RANGE[1] and LON_RANGE[0] <= east <= LON_RANGE[1]):
        raise ToolException(
            f"经度越界（应在 {LON_RANGE}）：west={west}, east={east}",
            ToolErrorType.INVALID_BBOX,
        )
    if not (LAT_RANGE[0] <= south <= LAT_RANGE[1] and LAT_RANGE[0] <= north <= LAT_RANGE[1]):
        raise ToolException(
            f"纬度越界（应在 {LAT_RANGE}）：south={south}, north={north}",
            ToolErrorType.INVALID_BBOX,
        )
    if west >= east:
        raise ToolException(
            f"west({west}) 必须小于 east({east})", ToolErrorType.INVALID_BBOX
        )
    if south >= north:
        raise ToolException(
            f"south({south}) 必须小于 north({north})", ToolErrorType.INVALID_BBOX
        )
    return west, south, east, north


def validate_resolution(resolution: Any) -> int:
    """校验分辨率。"""
    try:
        res = int(resolution)
    except (TypeError, ValueError) as exc:
        raise ToolException(
            f"resolution 必须是整数，收到：{resolution!r}",
            ToolErrorType.INVALID_RESOLUTION,
        ) from exc
    if not (MIN_RESOLUTION <= res <= MAX_RESOLUTION):
        raise ToolException(
            f"resolution 必须在 [{MIN_RESOLUTION}, {MAX_RESOLUTION}]，收到 {res}。"
            f"建议：小范围用 128–256，大范围用 512–1024",
            ToolErrorType.INVALID_RESOLUTION,
        )
    return res


def validate_point_in_bbox(
    lon: float, lat: float, bbox: Tuple[float, float, float, float]
) -> None:
    """校验起终点是否落在 bbox 内 —— 路径规划最常见的用户错误。"""
    west, south, east, north = bbox
    if not (west <= lon <= east):
        raise ToolException(
            f"经度 {lon} 不在分析范围 [{west}, {east}] 内",
            ToolErrorType.INVALID_POINT,
        )
    if not (south <= lat <= north):
        raise ToolException(
            f"纬度 {lat} 不在分析范围 [{south}, {north}] 内",
            ToolErrorType.INVALID_POINT,
        )


def validate_metric(metric: str, allowed: Sequence[str]) -> str:
    """校验指标名。"""
    if metric not in allowed:
        raise ToolException(
            f"未知指标 {metric!r}，可选值：{list(allowed)}",
            ToolErrorType.UNKNOWN_METRIC,
        )
    return metric


# ── 栅格统计（带范围告警）────────────────────────────────────────────
def grid_stats(
    arr: np.ndarray,
    name: str,
    unit: Optional[str] = None,
    valid_range: Optional[Tuple[float, float]] = None,
) -> Dict[str, Any]:
    """计算栅格统计信息，并给出数据质量告警。

    返回的 warnings 是 Week 2 reflector 判断「结果是否合理」的核心依据，
    例如：坡度超出 [0, 90]、超过半数栅格为无效值。

    Args:
        arr: 输入栅格（允许含 NaN）
        name: 指标名
        unit: 单位（如 "degree" / "m" / "cost"）
        valid_range: 合法取值区间，用于范围校验
    """
    a = np.asarray(arr, dtype=np.float64)
    finite = np.isfinite(a)
    valid_ratio = float(finite.mean()) if a.size else 0.0
    nodata_count = int(a.size - finite.sum())

    if not finite.any():
        raise ToolException(
            f"{name} 全部栅格为无效值（NaN/Inf），无法统计。"
            f"可能原因：DEM 未覆盖该范围、数据解析失败或范围选择在水域/无数据区",
            ToolErrorType.ALL_NODATA,
        )

    vals = a[finite]
    stats: Dict[str, Any] = {
        "name": name,
        "unit": unit,
        "shape": list(a.shape),
        "min": round(float(vals.min()), 4),
        "max": round(float(vals.max()), 4),
        "mean": round(float(vals.mean()), 4),
        "std": round(float(vals.std()), 4),
        "p25": round(float(np.percentile(vals, 25)), 4),
        "p50": round(float(np.percentile(vals, 50)), 4),
        "p75": round(float(np.percentile(vals, 75)), 4),
        "valid_ratio": round(valid_ratio, 4),
        "nodata_count": nodata_count,
    }

    warnings: List[str] = []

    # 范围校验
    out_of_range = 0
    if valid_range is not None:
        lo, hi = valid_range
        out_of_range = int(((vals < lo) | (vals > hi)).sum())
        stats["valid_range"] = [lo, hi]
        stats["out_of_range_count"] = out_of_range
        if out_of_range:
            warnings.append(
                f"{name} 有 {out_of_range} 个像元超出合法区间 [{lo}, {hi}]，"
                f"结果可能异常"
            )

    # 有效值比例告警
    if valid_ratio < 0.5:
        warnings.append(
            f"{name} 有效栅格仅占 {valid_ratio:.1%}（{nodata_count} 个无效），"
            f"统计结果可能不可靠，建议调整分析范围或检查 DEM 覆盖"
        )
    elif valid_ratio < 0.95:
        warnings.append(f"{name} 含 {nodata_count} 个无效栅格（有效 {valid_ratio:.1%}）")

    # 常量栅格告警（可能是数据错误）
    if vals.std() < 1e-9:
        warnings.append(f"{name} 全栅格为常数 {vals.min():.4f}，地形可能无起伏或数据异常")

    if warnings:
        stats["warnings"] = warnings
    return stats


def class_distribution(class_ids: np.ndarray, legend: List[Dict[str, Any]]) -> Dict[str, Any]:
    """分类结果的类别分布 —— 供 reflector 判断「分类是否有效」。"""
    flat = np.asarray(class_ids).ravel()
    total = int(flat.size)
    legend_map = {int(c["id"]): c.get("label_cn") or c.get("name") for c in legend}

    counts: Dict[str, int] = {}
    for cid in sorted(legend_map):
        counts[legend_map[cid]] = int((flat == cid).sum())

    present = {k: v for k, v in counts.items() if v > 0}
    dominant = max(counts, key=lambda k: counts[k]) if counts else None
    dominant_ratio = counts[dominant] / total if dominant and total else 0.0

    out: Dict[str, Any] = {
        "total_cells": total,
        "counts": counts,
        "distinct_classes": len(present),
        "dominant_class": dominant,
        "dominant_ratio": round(float(dominant_ratio), 4),
    }

    warnings = []
    if len(present) <= 1:
        warnings.append(
            f"分类结果仅含 {len(present)} 类（{dominant}），"
            f"地形可能过于单一或分类失败"
        )
    elif dominant_ratio > 0.9:
        warnings.append(
            f"{dominant} 占比 {dominant_ratio:.1%}，类别极度不平衡，"
            f"可考虑扩大分析范围"
        )
    if warnings:
        out["warnings"] = warnings
    return out


# ── 产物落盘 ────────────────────────────────────────────────────────
def save_grid_artifact(
    grid: np.ndarray,
    lon_grid: np.ndarray,
    lat_grid: np.ndarray,
    name: str,
    fmt: str = "geojson",
    extra_fields: Optional[Dict[str, np.ndarray]] = None,
) -> Dict[str, Any]:
    """将栅格落盘为矢量/三维格式，返回路径信息（不内联大数组）。"""
    from ..services.export_service import (
        export_grid_as_czml,
        export_grid_as_geojson,
        export_grid_as_kml,
    )

    fmt = (fmt or "geojson").lower()
    if fmt not in {"geojson", "czml", "kml", "npz"}:
        raise ToolException(
            f"不支持的导出格式 {fmt!r}，可选：geojson / czml / kml / npz",
            ToolErrorType.UNSUPPORTED_FORMAT,
        )

    subdir = ARTIFACT_ROOT / uuid.uuid4().hex[:12]
    subdir.mkdir(parents=True, exist_ok=True)

    if fmt == "npz":
        path = subdir / f"{name}.npz"
        np.savez_compressed(path, **{name: np.asarray(grid)})
        return {
            "format": "npz",
            "name": name,
            "path": str(path),
            "shape": list(np.asarray(grid).shape),
        }

    path = subdir / f"{name}.{fmt}"
    if fmt == "geojson":
        feature_count = export_grid_as_geojson(
            path, lon_grid, lat_grid, np.asarray(grid), name,
            extra_fields=extra_fields,
        )
    elif fmt == "czml":
        feature_count = export_grid_as_czml(
            path, lon_grid, lat_grid, np.asarray(grid), name
        )
    else:
        feature_count = export_grid_as_kml(
            path, lon_grid, lat_grid, np.asarray(grid), name
        )

    return {
        "format": fmt,
        "name": name,
        "path": str(path),
        "feature_count": feature_count,
    }


def save_json_artifact(payload: Dict[str, Any], name: str) -> Dict[str, Any]:
    """落盘任意 JSON 可序列化结果。"""
    subdir = ARTIFACT_ROOT / uuid.uuid4().hex[:12]
    subdir.mkdir(parents=True, exist_ok=True)
    path = subdir / f"{name}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return {"format": "json", "name": name, "path": str(path)}


def _json_default(obj: Any) -> Any:
    """numpy 类型的 JSON 兜底序列化。"""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, Path):
        return str(obj)
    return str(obj)


def bbox_area_km2(bbox: Tuple[float, float, float, float]) -> float:
    """粗略估算 bbox 面积（km²），用于给用户范围大小参考。"""
    west, south, east, north = bbox
    mean_lat = math.radians((south + north) / 2.0)
    width_km = (east - west) * 111.320 * max(1e-6, math.cos(mean_lat))
    height_km = (north - south) * 110.574
    return round(width_km * height_km, 2)


def cell_size_m(bbox: Tuple[float, float, float, float], resolution: int) -> float:
    """估算栅格单元边长（米）。"""
    west, south, east, north = bbox
    mean_lat = math.radians((south + north) / 2.0)
    lon_m = (east - west) * 111320.0 * max(1e-6, math.cos(mean_lat)) / max(1, resolution - 1)
    lat_m = (north - south) * 110574.0 / max(1, resolution - 1)
    return round((lon_m + lat_m) / 2.0, 2)
