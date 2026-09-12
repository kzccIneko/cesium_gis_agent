"""路径规划工具。

包含工具：
    plan_route  —— 基于通行代价栅格的 Dijkstra 8 邻域最短路，带完整路径质量诊断

与原有 analysis_service.plan_path 的区别：
    原实现在「起终点不可达」时会静默回退为直线插值，调用方无从得知路径是否有效。
    本工具将这一情况显式暴露为 reachable=False + 告警，
    使 Agent（以及 Week 2 的 reflector）能判断结果是否可信并决定重试策略。
"""

from __future__ import annotations

import heapq
import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .base import (
    cell_size_m,
    save_json_artifact,
    validate_bbox,
    validate_point_in_bbox,
    validate_resolution,
)
from .cache import terrain_cache
from .errors import ToolErrorType, ToolException, fail, ok

# 绕行系数告警阈值：路径长度 / 直线距离
DETOUR_WARN_RATIO = 3.0
# 路径过陡告警阈值（度）
STEEP_SLOPE_WARN_DEG = 30.0


def _neighbor8(x: int, y: int, n: int) -> List[Tuple[int, int]]:
    """8 邻域（含对角线）。"""
    out = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < n and 0 <= ny < n:
                out.append((nx, ny))
    return out


def _grid_index(lon: float, lat: float, bbox: Tuple[float, float, float, float], res: int) -> Tuple[int, int]:
    """经纬度 → 栅格行列号。"""
    west, south, east, north = bbox
    ix = int(round((lon - west) / (east - west) * (res - 1)))
    iy = int(round((lat - south) / (north - south) * (res - 1)))
    return max(0, min(res - 1, ix)), max(0, min(res - 1, iy))


def _dijkstra(
    cost: np.ndarray, res: int, start: Tuple[int, int], end: Tuple[int, int]
) -> Tuple[Optional[List[Tuple[int, int]]], int]:
    """Dijkstra 8 邻域最短路。

    Returns:
        (路径节点列表, 已弹出节点数)。不可达时返回 (None, 已探索节点数)。
    """
    sx, sy = start
    ex, ey = end

    # NaN 视为不可通行：转成 +inf，避免污染最短距离
    c = np.asarray(cost, dtype=np.float64)
    c = np.where(np.isfinite(c), c, np.inf)

    if not np.isfinite(c[sy, sx]) or not np.isfinite(c[ey, ex]):
        return None, 0

    inf = float("inf")
    dist = np.full((res, res), inf, dtype=np.float64)
    prev: Dict[Tuple[int, int], Tuple[int, int]] = {}
    dist[sy, sx] = 0.0
    pq: List[Tuple[float, int, int]] = [(0.0, sx, sy)]
    popped = 0

    while pq:
        cur_d, x, y = heapq.heappop(pq)
        popped += 1
        if cur_d > dist[y, x]:
            continue
        if x == ex and y == ey:
            break
        for nx, ny in _neighbor8(x, y, res):
            step = math.hypot(nx - x, ny - y)
            step_cost = step * float(c[ny, nx])
            if not math.isfinite(step_cost):
                continue
            nd = cur_d + step_cost
            if nd < dist[ny, nx]:
                dist[ny, nx] = nd
                prev[(nx, ny)] = (x, y)
                heapq.heappush(pq, (nd, nx, ny))

    if (ex, ey) not in prev and start != end:
        return None, popped

    path = [(ex, ey)]
    cur = (ex, ey)
    while cur != (sx, sy):
        cur = prev[cur]
        path.append(cur)
    path.reverse()
    return path, popped


def _parse_point(point: Any, name: str) -> Tuple[float, float]:
    """解析 [lon, lat]，对大模型可能传入的各类非法形态给出明确错误。"""
    if point is None:
        raise ToolException(
            f"缺少 {name}，路线规划必须提供起点与终点，格式为 [经度, 纬度]",
            ToolErrorType.INVALID_POINT,
        )
    if isinstance(point, (str, bytes)) or not isinstance(point, (list, tuple)):
        raise ToolException(
            f"{name} 必须是 [经度, 纬度] 数组，收到：{point!r}",
            ToolErrorType.INVALID_POINT,
        )
    if len(point) != 2:
        raise ToolException(
            f"{name} 必须恰好包含 2 个数值 [经度, 纬度]，收到 {len(point)} 个：{point!r}",
            ToolErrorType.INVALID_POINT,
        )
    try:
        lon, lat = float(point[0]), float(point[1])
    except (TypeError, ValueError) as exc:
        raise ToolException(
            f"{name} 含非数值元素：{point!r}", ToolErrorType.INVALID_POINT
        ) from exc
    if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
        raise ToolException(
            f"{name} 经纬度越界：{point!r}（经度 ±180，纬度 ±90）",
            ToolErrorType.INVALID_POINT,
        )
    return lon, lat


def plan_route(
    bbox: Sequence[float],
    start_point: Optional[Sequence[float]] = None,
    end_point: Optional[Sequence[float]] = None,
    resolution: int = 256,
    dem_path: Optional[str] = None,
    output_format: str = "geojson",
) -> Dict[str, Any]:
    """在通行代价栅格上规划越野路径（Dijkstra 8 邻域 + 方向性代价场）。

    方向性代价场使路径倾向沿等高线绕行而非直上直下，
    更贴近车辆与人员的实际通行行为。

    Args:
        bbox: [west, south, east, north]
        start_point: 起点 [lon, lat]
        end_point: 终点 [lon, lat]
        resolution: 栅格分辨率，建议 128–512
        dem_path: 本地 DEM 路径；留空使用合成地形
        output_format: 导出格式（geojson / czml / kml / json）

    Returns:
        data.reachable      —— 是否找到真实路径（False 表示起终点间不可通行）
        data.distance_m     —— 路径长度（米）
        data.detour_ratio   —— 绕行系数（路径长 / 直线距离）
        data.ascent_m / descent_m —— 累计爬升 / 下降
        data.max_slope_deg  —— 路径经过的最大坡度
        data.artifact       —— 落盘路径文件
    """
    tool = "plan_route"
    t0 = time.perf_counter()

    try:
        west, south, east, north = validate_bbox(bbox)
        res = validate_resolution(resolution)

        start_lon, start_lat = _parse_point(start_point, "start_point")
        end_lon, end_lat = _parse_point(end_point, "end_point")

        validate_point_in_bbox(start_lon, start_lat, (west, south, east, north))
        validate_point_in_bbox(end_lon, end_lat, (west, south, east, north))

        # 带起终点取地形 —— 触发方向性代价场
        terrain, cache_hit = terrain_cache.get_or_compute(
            (west, south, east, north), res, dem_path=dem_path,
            start_lon=start_lon, start_lat=start_lat,
            end_lon=end_lon, end_lat=end_lat,
        )

        s_idx = _grid_index(start_lon, start_lat, (west, south, east, north), res)
        e_idx = _grid_index(end_lon, end_lat, (west, south, east, north), res)

        path_nodes, explored = _dijkstra(terrain.cost, res, s_idx, e_idx)
        reachable = path_nodes is not None

        # 不可达时回退直线，但显式标记（原实现是静默回退）
        if not reachable:
            sx, sy = s_idx
            ex, ey = e_idx
            path_nodes = [
                (int(round(sx + (ex - sx) * t)), int(round(sy + (ey - sy) * t)))
                for t in np.linspace(0.0, 1.0, num=64)
            ]

        # 栅格 → 经纬度，并累计距离与高程剖面
        lonlat: List[Tuple[float, float]] = []
        elevations: List[float] = []
        slopes: List[float] = []
        distance_m = 0.0
        ascent_m = 0.0
        descent_m = 0.0

        for i, (x, y) in enumerate(path_nodes):  # noqa: B007
            lon = float(terrain.lon_grid[y, x])
            lat = float(terrain.lat_grid[y, x])
            lonlat.append((lon, lat))
            elevations.append(float(terrain.dem_grid[y, x]))
            slopes.append(float(terrain.slope_deg[y, x]))
            if i > 0:
                plon, plat = lonlat[i - 1]
                dx = (lon - plon) * 111320.0 * max(1e-6, math.cos(math.radians(lat)))
                dy = (lat - plat) * 110574.0
                distance_m += math.hypot(dx, dy)
                dh = elevations[i] - elevations[i - 1]
                if dh > 0:
                    ascent_m += dh
                else:
                    descent_m += -dh

        straight_m = math.hypot(
            (end_lon - start_lon) * 111320.0 * max(1e-6, math.cos(math.radians((start_lat + end_lat) / 2))),
            (end_lat - start_lat) * 110574.0,
        )
        detour_ratio = distance_m / straight_m if straight_m > 1e-6 else float("inf")

        # 落盘
        if output_format == "json":
            artifact = save_json_artifact(
                {
                    "path": [[lon, lat] for lon, lat in lonlat],
                    "distance_m": round(distance_m, 2),
                    "reachable": reachable,
                },
                "path",
            )
        else:
            from ..services.export_service import (
                export_path_as_czml,
                export_path_as_geojson,
                export_path_as_kml,
            )
            from .base import ARTIFACT_ROOT
            import uuid

            fmt = (output_format or "geojson").lower()
            if fmt not in {"geojson", "czml", "kml"}:
                raise ToolException(
                    f"不支持的路径导出格式 {output_format!r}，可选 geojson / czml / kml / json",
                    ToolErrorType.UNSUPPORTED_FORMAT,
                )
            subdir = ARTIFACT_ROOT / uuid.uuid4().hex[:12]
            subdir.mkdir(parents=True, exist_ok=True)
            p = subdir / f"path.{fmt}"
            if fmt == "geojson":
                cnt = export_path_as_geojson(p, lonlat)
            elif fmt == "czml":
                cnt = export_path_as_czml(p, lonlat)
            else:
                cnt = export_path_as_kml(p, lonlat)
            artifact = {
                "format": fmt,
                "name": "path",
                "path": str(p),
                "url": f"/artifacts/{subdir.name}/{p.name}",
                "feature_count": cnt,
            }

        warnings: List[str] = []
        if not reachable:
            warnings.append(
                "起终点之间在代价栅格上不可达（可能存在大面积无效值或不可通行区），"
                "当前返回的是直线近似，不可作为真实路径使用"
            )
        if detour_ratio > DETOUR_WARN_RATIO:
            warnings.append(
                f"绕行系数 {detour_ratio:.2f} 偏高（路径长为直线距离的 "
                f"{detour_ratio:.1f} 倍），地形可能对通行约束过强"
            )
        max_slope = max(slopes) if slopes else 0.0
        if max_slope > STEEP_SLOPE_WARN_DEG:
            warnings.append(
                f"路径经过最大坡度 {max_slope:.1f}°，超过 {STEEP_SLOPE_WARN_DEG}°，"
                f"普通车辆可能难以通行"
            )
        if terrain.dem_source == "synthetic":
            warnings.append("当前使用合成地形，结果仅用于流程验证")

        data: Dict[str, Any] = {
            "summary": (
                f"路径长 {distance_m:,.0f} m（直线 {straight_m:,.0f} m，"
                f"绕行系数 {detour_ratio:.2f}），累计爬升 {ascent_m:,.0f} m"
                f"{'' if reachable else '；⚠ 不可达，已回退直线'}"
            ),
            "reachable": reachable,
            "distance_m": round(distance_m, 2),
            "straight_line_m": round(straight_m, 2),
            "detour_ratio": round(detour_ratio, 4),
            "node_count": len(path_nodes),
            "explored_nodes": explored,
            "ascent_m": round(ascent_m, 2),
            "descent_m": round(descent_m, 2),
            "mean_slope_deg": round(float(np.mean(slopes)), 2) if slopes else None,
            "max_slope_deg": round(max_slope, 2),
            "start_elevation_m": round(elevations[0], 2) if elevations else None,
            "end_elevation_m": round(elevations[-1], 2) if elevations else None,
            "bbox": [west, south, east, north],
            "resolution": res,
            "cell_size_m": cell_size_m((west, south, east, north), res),
            "dem_source": terrain.dem_source,
            "directional_cost": True,
            "artifact": artifact,
            "cache_hit": cache_hit,
        }
        if warnings:
            data["warnings"] = warnings

        return ok(tool, data, (time.perf_counter() - t0) * 1000).to_dict()

    except ToolException as exc:
        return fail(tool, exc.message, exc.error_type,
                    (time.perf_counter() - t0) * 1000).to_dict()
    except Exception as exc:  # noqa: BLE001
        return fail(tool, f"路径规划失败：{exc}", ToolErrorType.COMPUTATION_FAILED,
                    (time.perf_counter() - t0) * 1000).to_dict()
