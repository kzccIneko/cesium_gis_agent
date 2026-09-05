"""地形因子提取工具：坡度 / 坡向 / 曲率 / 通行代价栅格。

四个工具共享同一次 analyze_terrain 结果（经 TerrainResultCache 复用），
因此 Agent 连续询问多个指标时不会重复解析 DEM 与重算全部因子。

包含工具：
    compute_slope         坡度（度，合法区间 0–90）
    compute_aspect        坡向（度，0–360，0 表示正北）
    compute_curvature     曲率（1/m，正值凸起、负值凹陷）
    compute_cost_surface  通行代价栅格（可传入起终点启用方向性代价）
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Sequence, Tuple

from .base import (
    cell_size_m,
    grid_stats,
    save_grid_artifact,
    validate_bbox,
    validate_resolution,
)
from .cache import terrain_cache
from .errors import ToolErrorType, ToolException, fail, ok

# 指标元数据：字段名 / 中文名 / 单位 / 合法区间（用于范围告警）
_METRIC_SPECS: Dict[str, Dict[str, Any]] = {
    "slope": {
        "field": "slope_deg",
        "label_cn": "坡度",
        "unit": "degree",
        "range": (0.0, 90.0),
    },
    "aspect": {
        "field": "aspect_deg",
        "label_cn": "坡向",
        "unit": "degree",
        "range": (0.0, 360.0),
    },
    "curvature": {
        "field": "curvature",
        "label_cn": "曲率",
        "unit": "1/m",
        "range": None,  # 量级随尺度变化，不做硬范围校验
    },
}


def _run_metric(
    tool: str,
    metric_key: str,
    bbox: Sequence[float],
    resolution: int,
    dem_path: Optional[str],
    output_format: str,
    t0: float,
) -> Dict[str, Any]:
    """坡度/坡向/曲率的公共执行逻辑。"""
    spec = _METRIC_SPECS[metric_key]
    west, south, east, north = validate_bbox(bbox)
    res = validate_resolution(resolution)

    terrain, cache_hit = terrain_cache.get_or_compute(
        (west, south, east, north), res, dem_path=dem_path
    )

    grid = getattr(terrain, spec["field"])
    stats = grid_stats(grid, spec["field"], spec["unit"], spec["range"])
    artifact = save_grid_artifact(
        grid, terrain.lon_grid, terrain.lat_grid, spec["field"], output_format
    )

    warnings = list(stats.pop("warnings", []))
    if terrain.dem_source == "synthetic":
        warnings.append(
            "当前使用合成地形（未提供 dem_path），结果仅用于流程验证，"
            "真实分析请先调用 download_srtm 或传入本地 DEM 路径"
        )

    data: Dict[str, Any] = {
        "summary": (
            f"{spec['label_cn']}：均值 {stats['mean']} {spec['unit']}，"
            f"范围 [{stats['min']}, {stats['max']}]，栅格 {res}×{res}"
        ),
        "metric": metric_key,
        "label_cn": spec["label_cn"],
        "bbox": [west, south, east, north],
        "resolution": res,
        "cell_size_m": cell_size_m((west, south, east, north), res),
        "dem_source": terrain.dem_source,
        "statistics": stats,
        "artifact": artifact,
        "cache_hit": cache_hit,
    }
    if warnings:
        data["warnings"] = warnings

    return ok(tool, data, (time.perf_counter() - t0) * 1000).to_dict()


def compute_slope(
    bbox: Sequence[float],
    resolution: int = 256,
    dem_path: Optional[str] = None,
    output_format: str = "geojson",
) -> Dict[str, Any]:
    """计算指定范围的坡度栅格（度）。

    坡度是通行性评估、地貌分类与路径规划最基础的地形因子。

    Args:
        bbox: [west, south, east, north]
        resolution: 栅格分辨率（边长像元数），建议 128–512
        dem_path: 本地 DEM 路径；留空则使用合成地形
        output_format: 导出格式 geojson / czml / kml / npz

    Returns:
        data.statistics —— min/max/mean/std/有效值比例/范围告警
        data.artifact   —— 落盘文件路径（大数组不内联）
    """
    tool = "compute_slope"
    t0 = time.perf_counter()
    try:
        return _run_metric(tool, "slope", bbox, resolution, dem_path, output_format, t0)
    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"坡度计算失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()


def compute_aspect(
    bbox: Sequence[float],
    resolution: int = 256,
    dem_path: Optional[str] = None,
    output_format: str = "geojson",
) -> Dict[str, Any]:
    """计算坡向栅格（度，0 = 正北，顺时针增大）。

    常用于判断阴坡/阳坡、冰雪消融与植被分布分析。
    """
    tool = "compute_aspect"
    t0 = time.perf_counter()
    try:
        return _run_metric(tool, "aspect", bbox, resolution, dem_path, output_format, t0)
    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"坡向计算失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()


def compute_curvature(
    bbox: Sequence[float],
    resolution: int = 256,
    dem_path: Optional[str] = None,
    output_format: str = "geojson",
) -> Dict[str, Any]:
    """计算曲率栅格（1/m，正值凸起如山脊，负值凹陷如沟谷）。

    是区分山脊与沟谷、判断水土流失与汇流的关键因子。
    """
    tool = "compute_curvature"
    t0 = time.perf_counter()
    try:
        return _run_metric(tool, "curvature", bbox, resolution, dem_path, output_format, t0)
    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"曲率计算失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()


def compute_cost_surface(
    bbox: Sequence[float],
    resolution: int = 256,
    dem_path: Optional[str] = None,
    start_point: Optional[Sequence[float]] = None,
    end_point: Optional[Sequence[float]] = None,
    output_format: str = "geojson",
) -> Dict[str, Any]:
    """构建通行代价栅格（cost surface）。

    代价由坡度、曲率、山脊谷地、等高线密度等因子加权合成。
    **若同时传入起终点，将生成方向性代价场**：使路径倾向于沿等高线绕行
    而非直上直下，更贴近越野车辆与人员的实际通行行为。

    Args:
        bbox: [west, south, east, north]
        resolution: 栅格分辨率
        dem_path: 本地 DEM 路径
        start_point: 起点 [lon, lat]，与 end_point 同时传入才启用方向性代价
        end_point: 终点 [lon, lat]
        output_format: 导出格式

    Returns:
        data.statistics          —— 代价栅格统计
        data.directional         —— 是否启用方向性代价
        data.min_cost_dir_stats  —— 启用时的最小代价方向统计
    """
    tool = "compute_cost_surface"
    t0 = time.perf_counter()

    try:
        west, south, east, north = validate_bbox(bbox)
        res = validate_resolution(resolution)

        directional = bool(start_point and end_point)
        if bool(start_point) != bool(end_point):
            return fail(
                tool,
                "start_point 与 end_point 必须同时传入（用于方向性代价场）"
                "或同时省略（仅基础代价场）",
                ToolErrorType.INVALID_POINT,
                (time.perf_counter() - t0) * 1000,
            ).to_dict()

        if directional:
            start_lon, start_lat = float(start_point[0]), float(start_point[1])
            end_lon, end_lat = float(end_point[0]), float(end_point[1])
        else:
            start_lon = start_lat = end_lon = end_lat = None

        terrain, cache_hit = terrain_cache.get_or_compute(
            (west, south, east, north), res, dem_path=dem_path,
            start_lon=start_lon, start_lat=start_lat,
            end_lon=end_lon, end_lat=end_lat,
        )

        stats = grid_stats(terrain.cost, "cost", "cost")
        artifact = save_grid_artifact(
            terrain.cost, terrain.lon_grid, terrain.lat_grid, "cost", output_format
        )

        data: Dict[str, Any] = {
            "summary": (
                f"通行代价栅格：均值 {stats['mean']}，范围 "
                f"[{stats['min']}, {stats['max']}]，栅格 {res}×{res}"
                f"{'（已启用方向性代价）' if directional else '（基础代价场）'}"
            ),
            "bbox": [west, south, east, north],
            "resolution": res,
            "cell_size_m": cell_size_m((west, south, east, north), res),
            "dem_source": terrain.dem_source,
            "directional": directional,
            "statistics": stats,
            "artifact": artifact,
            "cache_hit": cache_hit,
        }

        warnings = list(stats.pop("warnings", []))
        if directional:
            dir_stats = grid_stats(
                terrain.min_cost_dir_deg, "min_cost_dir_deg", "degree", (0.0, 360.0)
            )
            warnings.extend(dir_stats.pop("warnings", []))
            data["min_cost_dir_stats"] = dir_stats
        else:
            warnings.append(
                "未传入起终点，生成的是无方向的基础代价场。"
                "若要做路径规划，建议传入 start_point / end_point 以启用方向性代价"
            )
        if terrain.dem_source == "synthetic":
            warnings.append("当前使用合成地形，结果仅用于流程验证")
        if warnings:
            data["warnings"] = warnings

        return ok(tool, data, (time.perf_counter() - t0) * 1000).to_dict()

    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"通行代价计算失败：{exc}",
                    ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()
