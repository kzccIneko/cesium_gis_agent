"""分区统计工具。

包含工具：
    zonal_statistics  —— 对地形指标做分级统计，并给出可通行性结论

与 compute_* 系列的区别：
    compute_slope 等返回栅格与整体统计；
    zonal_statistics 回答的是业务问题，例如
    「这片区域有多少面积坡度小于 15°（车辆可通行）」。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Sequence

import numpy as np

from .base import (
    bbox_area_km2,
    cell_size_m,
    save_json_artifact,
    validate_bbox,
    validate_metric,
    validate_resolution,
)
from .cache import terrain_cache
from .errors import ToolErrorType, ToolException, fail, ok

# 可支持的指标 → (TerrainResult 字段名, 中文名, 单位)
_METRICS: Dict[str, Dict[str, Any]] = {
    "slope": {"field": "slope_deg", "label_cn": "坡度", "unit": "degree"},
    "aspect": {"field": "aspect_deg", "label_cn": "坡向", "unit": "degree"},
    "curvature": {"field": "curvature", "label_cn": "曲率", "unit": "1/m"},
    "cost": {"field": "cost", "label_cn": "通行代价", "unit": "cost"},
    "elevation": {"field": "dem_grid", "label_cn": "高程", "unit": "m"},
}

# 坡度分级（度）—— 依据越野车辆与人员的一般通行能力
SLOPE_BREAKS = [0.0, 5.0, 15.0, 25.0, 35.0, 90.0]
SLOPE_CLASS_LABELS = [
    "0–5° 平缓",
    "5–15° 缓坡（车辆可通行）",
    "15–25° 陡坡（需越野能力）",
    "25–35° 急坡（车辆困难）",
    ">35° 极陡（车辆不可通行）",
]
# 车辆通行的坡度上限（度）
VEHICLE_SLOPE_LIMIT_DEG = 15.0


def _quantile_breaks(vals: np.ndarray, n: int = 5) -> list:
    """按分位数生成分级断点。"""
    qs = np.linspace(0, 100, n + 1)
    b = [float(np.percentile(vals, q)) for q in qs]
    b[0], b[-1] = float(vals.min()), float(vals.max())
    # 去重并保持递增
    out = []
    for v in b:
        if not out or v > out[-1] + 1e-12:
            out.append(v)
    return out


def zonal_statistics(
    bbox: Sequence[float],
    metric: str = "slope",
    resolution: int = 256,
    dem_path: Optional[str] = None,
    breaks: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """对地形指标做分级统计，并给出可通行性结论。

    典型用途：
        - 「这片区域有多少面积可以开车」
        - 「高程分布是怎样的」
        - 「通行代价的空间分布」

    Args:
        bbox: [west, south, east, north]
        metric: slope / aspect / curvature / cost / elevation
        resolution: 栅格分辨率
        dem_path: 本地 DEM 路径
        breaks: 自定义分级断点；省略则按指标默认方案（高程/代价用分位数）

    Returns:
        data.classes   —— 各等级的像元数、面积、占比
        data.passable  —— 仅坡度指标：车辆可通行面积占比等结论
    """
    tool = "zonal_statistics"
    t0 = time.perf_counter()

    try:
        west, south, east, north = validate_bbox(bbox)
        res = validate_resolution(resolution)
        metric = validate_metric(str(metric).lower(), list(_METRICS))

        terrain, cache_hit = terrain_cache.get_or_compute(
            (west, south, east, north), res, dem_path=dem_path
        )

        spec = _METRICS[metric]
        grid = np.asarray(getattr(terrain, spec["field"]), dtype=np.float64)
        finite = np.isfinite(grid)
        vals = grid[finite]

        if vals.size == 0:
            return fail(
                tool,
                f"{spec['label_cn']}栅格全部为无效值，无法统计",
                ToolErrorType.ALL_NODATA,
                (time.perf_counter() - t0) * 1000,
            ).to_dict()

        total_cells = int(grid.size)
        valid_cells = int(vals.size)
        cell_area = (cell_size_m((west, south, east, north), res) ** 2) / 1e6  # km²

        # 分级断点
        if breaks and len(breaks) >= 2:
            b = [float(x) for x in breaks]
        elif metric == "slope":
            b = list(SLOPE_BREAKS)
        elif metric == "curvature":
            b = [float(vals.min()), -0.01, -0.001, 0.001, 0.01, float(vals.max())]
            b = sorted(set(round(x, 10) for x in b))
        else:
            b = _quantile_breaks(vals, n=5)

        labels = (
            list(SLOPE_CLASS_LABELS)
            if (metric == "slope" and not breaks)
            else [f"[{b[i]:.4g}, {b[i+1]:.4g})" for i in range(len(b) - 1)]
        )

        classes = []
        for i in range(len(b) - 1):
            lo, hi = b[i], b[i + 1]
            if i == len(b) - 2:
                mask = finite & (grid >= lo) & (grid <= hi)
            else:
                mask = finite & (grid >= lo) & (grid < hi)
            cnt = int(mask.sum())
            classes.append({
                "label": labels[i] if i < len(labels) else f"[{lo:.4g}, {hi:.4g})",
                "range": [round(lo, 4), round(hi, 4)],
                "cells": cnt,
                "area_km2": round(cnt * cell_area, 3),
                "ratio": round(cnt / total_cells, 4) if total_cells else 0.0,
            })

        data: Dict[str, Any] = {
            "summary": None,  # 稍后填
            "metric": metric,
            "label_cn": spec["label_cn"],
            "unit": spec["unit"],
            "bbox": [west, south, east, north],
            "resolution": res,
            "total_area_km2": bbox_area_km2((west, south, east, north)),
            "valid_cells": valid_cells,
            "total_cells": total_cells,
            "valid_ratio": round(valid_cells / total_cells, 4),
            "overall": {
                "min": round(float(vals.min()), 4),
                "max": round(float(vals.max()), 4),
                "mean": round(float(vals.mean()), 4),
                "std": round(float(vals.std()), 4),
            },
            "classes": classes,
            "dem_source": terrain.dem_source,
            "cache_hit": cache_hit,
        }

        warnings = []

        # 坡度指标：给出车辆可通行性结论
        if metric == "slope":
            passable_mask = finite & (grid <= VEHICLE_SLOPE_LIMIT_DEG)
            passable_cells = int(passable_mask.sum())
            passable_ratio = passable_cells / total_cells if total_cells else 0.0
            data["passable"] = {
                "slope_limit_deg": VEHICLE_SLOPE_LIMIT_DEG,
                "passable_cells": passable_cells,
                "passable_area_km2": round(passable_cells * cell_area, 3),
                "passable_ratio": round(passable_ratio, 4),
                "note": f"以坡度 ≤ {VEHICLE_SLOPE_LIMIT_DEG}° 作为一般车辆可通行判据",
            }
            data["summary"] = (
                f"坡度分级统计：{passable_ratio:.1%} 的面积坡度 ≤ "
                f"{VEHICLE_SLOPE_LIMIT_DEG}°（车辆可通行），"
                f"均值 {data['overall']['mean']}°，最大 {data['overall']['max']}°"
            )
            if passable_ratio < 0.2:
                warnings.append(
                    f"仅 {passable_ratio:.1%} 的面积坡度 ≤ {VEHICLE_SLOPE_LIMIT_DEG}°，"
                    f"该区域整体通行条件较差"
                )
        else:
            data["summary"] = (
                f"{spec['label_cn']}分级统计：均值 {data['overall']['mean']} "
                f"{spec['unit']}，范围 [{data['overall']['min']}, {data['overall']['max']}]，"
                f"共 {len(classes)} 级"
            )

        if terrain.dem_source == "synthetic":
            warnings.append("当前使用合成地形，结果仅用于流程验证")
        if valid_cells / total_cells < 0.9:
            warnings.append(
                f"有效栅格仅占 {valid_cells/total_cells:.1%}，统计可能偏差"
            )
        if warnings:
            data["warnings"] = warnings

        # 结果落盘（分级统计结果较小，可直接内联；同时提供文件便于复用）
        data["artifact"] = save_json_artifact(
            {"metric": metric, "classes": classes, "overall": data["overall"]},
            f"zonal_{metric}",
        )

        return ok(tool, data, (time.perf_counter() - t0) * 1000).to_dict()

    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"分区统计失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()
