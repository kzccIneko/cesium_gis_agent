from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Tuple, cast
import heapq
import math
import numpy as np


@dataclass
class TerrainResult:
    """地形分析结果：网格坐标 + 四类指标 + DEM + 数据来源。"""
    lon_grid: np.ndarray
    lat_grid: np.ndarray
    slope_deg: np.ndarray
    aspect_deg: np.ndarray
    curvature: np.ndarray
    cost: np.ndarray
    min_cost_dir_deg: np.ndarray
    min_cost_dir_slope_deg: np.ndarray
    flowline_intensity: np.ndarray
    dem_grid: np.ndarray  # 原始高程栅格，供地貌分类等下游使用
    dem_source: Literal["synthetic", "real_dem"]


@dataclass
class PathResult:
    """路径规划结果：经纬度路径点 + 路径长度（米）。"""
    path_lonlat: List[Tuple[float, float]]
    distance_m: float


DemDecodeMode = Literal["none", "single_band", "terrain_rgb"]


def _linspace_grid(west: float, south: float, east: float, north: float, resolution: int) -> Tuple[np.ndarray, np.ndarray]:
    """按 BBox 和分辨率生成规则经纬网格。"""
    lon = np.linspace(west, east, resolution)
    lat = np.linspace(south, north, resolution)
    lon_grid, lat_grid = np.meshgrid(lon, lat)
    return lon_grid, lat_grid


def _synthetic_dem(lon_grid: np.ndarray, lat_grid: np.ndarray) -> np.ndarray:
    # 以正弦叠加模拟地形起伏，便于无 DEM 文件时快速联调。
    lon_n = (lon_grid - lon_grid.min()) / max(1e-9, (lon_grid.max() - lon_grid.min()))
    lat_n = (lat_grid - lat_grid.min()) / max(1e-9, (lat_grid.max() - lat_grid.min()))
    z = (
        1200.0 * np.sin(2.0 * np.pi * lon_n)
        + 800.0 * np.cos(2.0 * np.pi * lat_n)
        + 300.0 * np.sin(4.0 * np.pi * lon_n * lat_n)
        + 2200.0
    )
    return z


def _cell_size_meters(west: float, south: float, east: float, north: float, resolution: int) -> float:
    """返回平均网格边长（米），用于曲率/耗时等计算。"""
    sx, sy = _cell_size_xy_meters(west, south, east, north, resolution)
    return max(1e-6, (sx + sy) * 0.5)


def _cell_size_xy_meters(west: float, south: float, east: float, north: float, resolution: int) -> Tuple[float, float]:
    """估算经纬度网格在当前纬度下对应的 x/y 方向米尺度。"""
    if resolution <= 1:
        return 1.0, 1.0
    mean_lat = math.radians((south + north) * 0.5)
    lon_step_m = abs(east - west) * 111320.0 * max(1e-6, math.cos(mean_lat)) / (resolution - 1)
    lat_step_m = abs(north - south) * 110574.0 / (resolution - 1)
    return max(1e-6, lon_step_m), max(1e-6, lat_step_m)


def _compute_terrain_metrics(
    dem: np.ndarray,
    west: float,
    south: float,
    east: float,
    north: float,
    resolution: int,
    start_lon: float | None = None,
    start_lat: float | None = None,
    end_lon: float | None = None,
    end_lat: float | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # 使用与前端一致的“单元 9 点”模型：
    # 每个栅格单元由四角、四边中点和中心点构造 3x3 采样，
    # 以保证前后端在同分辨率下数值与纹理表现一致。
    rows, cols = dem.shape
    if rows < 2 or cols < 2:
        z = np.zeros_like(dem, dtype=np.float64)
        return z, z, z, z, z, z, z

    cell_size_x_m, cell_size_y_m = _cell_size_xy_meters(west, south, east, north, resolution)
    cell_size_m = (cell_size_x_m + cell_size_y_m) * 0.5

    # 前端中的 g 采用“中心到西侧边中点”的距离，即半个单元宽度。
    # 这里保持相同定义，确保可视化结果与既有前端严格对齐。
    g = max(1e-6, cell_size_x_m * 0.5)

    dem_f64 = dem.astype(np.float64)
    slope_deg = np.empty((rows, cols), dtype=np.float64)
    aspect_deg = np.empty((rows, cols), dtype=np.float64)
    curvature = np.empty((rows, cols), dtype=np.float64)
    cost = np.empty((rows, cols), dtype=np.float64)
    min_cost_dir_deg = np.empty((rows, cols), dtype=np.float64)
    min_cost_dir_slope_deg = np.empty((rows, cols), dtype=np.float64)

    for i in range(rows - 1):
        for j in range(cols - 1):
            # 单元四角（行方向按“南到北”）。
            z1 = float(dem_f64[i, j])          # SW
            z3 = float(dem_f64[i, j + 1])      # SE
            z7 = float(dem_f64[i + 1, j])      # NW
            z9 = float(dem_f64[i + 1, j + 1])  # NE

            # 单元边中点与中心点（与双线性插值一致）。
            z2 = 0.5 * (z1 + z3)               # S
            z4 = 0.5 * (z1 + z7)               # W
            z5 = 0.25 * (z1 + z3 + z7 + z9)    # C
            z6 = 0.5 * (z3 + z9)               # E
            z8 = 0.5 * (z7 + z9)               # N

            fx = (z7 - z1 + 2.0 * (z8 - z2) + z9 - z3) / (8.0 * g)
            fy = (z3 - z1 + 2.0 * (z6 - z4) + z9 - z7) / (8.0 * g)

            slope = math.degrees(math.atan(math.sqrt(fx * fx + fy * fy)))
            aspect = math.degrees(math.atan2(-fy, -fx))
            if aspect < 0.0:
                aspect += 360.0

            a = (((z1 + z3 + z4 + z6 + z7 + z9) / 6.0) - ((z2 + z5 + z8) / 3.0)) / (cell_size_m * cell_size_m)
            b = (((z1 + z2 + z3 + z7 + z8 + z9) / 6.0) - ((z4 + z5 + z6) / 3.0)) / (cell_size_m * cell_size_m)
            c = (-z1 + z3 + z7 - z9) / (4.0 * cell_size_m * cell_size_m)
            d = (z3 + z6 + z9 - z1 - z4 - z7) / (6.0 * cell_size_m)
            e = (z1 + z2 + z3 - z7 - z8 - z9) / (6.0 * cell_size_m)
            se = d * d + e * e
            if se <= 1e-12:
                curv = 0.0
            else:
                curv = 2.0 * (a * e * e + b * d * d - c * d * e) / (se * math.sqrt(1.0 + se))

            slope_deg[i, j] = slope
            aspect_deg[i, j] = aspect
            curvature[i, j] = curv
            cost[i, j] = 0.0
            min_cost_dir_deg[i, j] = 0.0
            min_cost_dir_slope_deg[i, j] = 0.0

    # 最后一行/列没有完整单元，复制相邻有效值以补齐输出网格。
    slope_deg[-1, :] = slope_deg[-2, :]
    slope_deg[:, -1] = slope_deg[:, -2]
    aspect_deg[-1, :] = aspect_deg[-2, :]
    aspect_deg[:, -1] = aspect_deg[:, -2]
    curvature[-1, :] = curvature[-2, :]
    curvature[:, -1] = curvature[:, -2]
    min_cost_dir_deg[-1, :] = min_cost_dir_deg[-2, :]
    min_cost_dir_deg[:, -1] = min_cost_dir_deg[:, -2]
    min_cost_dir_slope_deg[-1, :] = min_cost_dir_slope_deg[-2, :]
    min_cost_dir_slope_deg[:, -1] = min_cost_dir_slope_deg[:, -2]

    # 以 D8 正反向汇流累积描述山脊/山谷线系强度（客观几何指标，无车辆参数）。
    flow_acc = np.ones((rows, cols), dtype=np.float64)
    rev_flow_acc = np.ones((rows, cols), dtype=np.float64)
    flow_dir = np.full((rows, cols), -1, dtype=np.int32)
    rev_flow_dir = np.full((rows, cols), -1, dtype=np.int32)
    d8 = (
        (0, 1),
        (1, 1),
        (1, 0),
        (1, -1),
        (0, -1),
        (-1, -1),
        (-1, 0),
        (-1, 1),
    )
    dist_map = (
        cell_size_x_m,
        math.hypot(cell_size_x_m, cell_size_y_m),
        cell_size_y_m,
        math.hypot(cell_size_x_m, cell_size_y_m),
        cell_size_x_m,
        math.hypot(cell_size_x_m, cell_size_y_m),
        cell_size_y_m,
        math.hypot(cell_size_x_m, cell_size_y_m),
    )

    for r in range(rows):
        for c in range(cols):
            z = float(dem_f64[r, c])
            drop_best = -1e18
            rise_best = -1e18
            idx_drop = -1
            idx_rise = -1
            for di, (dr, dc) in enumerate(d8):
                rr = r + dr
                cc = c + dc
                if rr < 0 or rr >= rows or cc < 0 or cc >= cols:
                    continue
                dz = float(dem_f64[rr, cc] - z)
                unit = dist_map[di]
                grad = dz / max(1e-6, unit)
                if -grad > drop_best:
                    drop_best = -grad
                    idx_drop = di
                if grad > rise_best:
                    rise_best = grad
                    idx_rise = di
            flow_dir[r, c] = idx_drop
            rev_flow_dir[r, c] = idx_rise

    order_desc = np.argsort(dem_f64.reshape(-1))[::-1]
    order_asc = np.argsort(dem_f64.reshape(-1))
    for flat_idx in order_desc:
        r = int(flat_idx // cols)
        c = int(flat_idx % cols)
        d = int(flow_dir[r, c])
        if d < 0:
            continue
        rr = r + d8[d][0]
        cc = c + d8[d][1]
        if 0 <= rr < rows and 0 <= cc < cols:
            flow_acc[rr, cc] += flow_acc[r, c]
    for flat_idx in order_asc:
        r = int(flat_idx // cols)
        c = int(flat_idx % cols)
        d = int(rev_flow_dir[r, c])
        if d < 0:
            continue
        rr = r + d8[d][0]
        cc = c + d8[d][1]
        if 0 <= rr < rows and 0 <= cc < cols:
            rev_flow_acc[rr, cc] += rev_flow_acc[r, c]

    flowline_intensity = np.log1p(np.maximum(flow_acc, rev_flow_acc))
    flowline_scale = float(np.median(flowline_intensity[np.isfinite(flowline_intensity)]))
    flowline_scale = max(1e-9, flowline_scale)
    flowline_penalty = 1.0 + (flowline_intensity / flowline_scale)

    curvature_mag = np.abs(curvature) * cell_size_m
    curv_scale = float(np.median(curvature_mag[np.isfinite(curvature_mag)]))
    curv_scale = max(1e-9, curv_scale)
    curvature_penalty = 1.0 + (curvature_mag / curv_scale)

    # 方向代价：以地表几何长度放大系数为主项，再乘曲率与线系强度惩罚项。
    # 若给定起终点，则只允许“朝向终点半平面”的候选方向，得到方向性代价栅格。
    # 不引入主观车辆参数，所有项均由 DEM 派生并做无量纲化。
    dir_angles = (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)
    use_goal_direction = (
        start_lon is not None and start_lat is not None and
        end_lon is not None and end_lat is not None
    )
    global_goal_ux = 1.0
    global_goal_uy = 0.0
    if use_goal_direction:
        mean_lat = math.radians((float(start_lat) + float(end_lat)) * 0.5)
        dx_goal = (float(end_lon) - float(start_lon)) * 111320.0 * max(1e-6, math.cos(mean_lat))
        dy_goal = (float(end_lat) - float(start_lat)) * 110574.0
        n_goal = math.hypot(dx_goal, dy_goal)
        if n_goal > 1e-9:
            global_goal_ux = dx_goal / n_goal
            global_goal_uy = dy_goal / n_goal
    for r in range(rows):
        for c in range(cols):
            # 单元导数，按与上文一致的 3x3 局部模板估计。
            r0 = max(0, r - 1)
            r1 = min(rows - 1, r + 1)
            c0 = max(0, c - 1)
            c1 = min(cols - 1, c + 1)
            z1 = float(dem_f64[r0, c0])
            z2 = float(dem_f64[r0, c])
            z3 = float(dem_f64[r0, c1])
            z4 = float(dem_f64[r, c0])
            z6 = float(dem_f64[r, c1])
            z7 = float(dem_f64[r1, c0])
            z8 = float(dem_f64[r1, c])
            z9 = float(dem_f64[r1, c1])
            fx_local = (z7 - z1 + 2.0 * (z8 - z2) + z9 - z3) / (8.0 * max(1e-6, cell_size_x_m))
            fy_local = (z3 - z1 + 2.0 * (z6 - z4) + z9 - z7) / (8.0 * max(1e-6, cell_size_y_m))

            base_penalty = float(curvature_penalty[r, c] * flowline_penalty[r, c])
            best_cost = float("inf")
            best_angle = 0.0
            best_dir_slope = 0.0
            cell_goal_ux = global_goal_ux
            cell_goal_uy = global_goal_uy
            if use_goal_direction:
                lat_c = float(south + (north - south) * (r / max(1, rows - 1)))
                lon_c = float(west + (east - west) * (c / max(1, cols - 1)))
                lat_c_rad = math.radians(lat_c)
                dx_cell_goal = (float(end_lon) - lon_c) * 111320.0 * max(1e-6, math.cos(lat_c_rad))
                dy_cell_goal = (float(end_lat) - lat_c) * 110574.0
                n_cell_goal = math.hypot(dx_cell_goal, dy_cell_goal)
                if n_cell_goal > 1e-9:
                    cell_goal_ux = dx_cell_goal / n_cell_goal
                    cell_goal_uy = dy_cell_goal / n_cell_goal

            for di, ang in enumerate(dir_angles):
                ang_rad = math.radians(ang)
                ux = math.cos(ang_rad)
                uy = math.sin(ang_rad)
                # 方向性约束：只保留朝向终点半平面的方向。
                if use_goal_direction and (ux * cell_goal_ux + uy * cell_goal_uy) <= 0.0:
                    continue
                dir_grad = fx_local * ux + fy_local * uy
                # 方向坡度的几何意义：沿指定方向单位水平位移的高程变化率。
                dir_surface_factor = math.sqrt(1.0 + dir_grad * dir_grad)
                step = dist_map[di]
                candidate = step * dir_surface_factor * base_penalty
                if candidate < best_cost:
                    best_cost = candidate
                    best_angle = ang
                    best_dir_slope = math.degrees(math.atan(abs(dir_grad)))

            if not math.isfinite(best_cost):
                # 兜底：若终点约束导致无可用方向，则退回全方向最小代价。
                for di2, ang2 in enumerate(dir_angles):
                    ang2_rad = math.radians(ang2)
                    ux2 = math.cos(ang2_rad)
                    uy2 = math.sin(ang2_rad)
                    dir_grad2 = fx_local * ux2 + fy_local * uy2
                    dir_surface_factor2 = math.sqrt(1.0 + dir_grad2 * dir_grad2)
                    step2 = dist_map[di2]
                    candidate2 = step2 * dir_surface_factor2 * base_penalty
                    if candidate2 < best_cost:
                        best_cost = candidate2
                        best_angle = ang2
                        best_dir_slope = math.degrees(math.atan(abs(dir_grad2)))

            cost[r, c] = float(best_cost)
            min_cost_dir_deg[r, c] = float(best_angle)
            min_cost_dir_slope_deg[r, c] = float(best_dir_slope)

    return slope_deg, aspect_deg, curvature, cost, min_cost_dir_deg, min_cost_dir_slope_deg, flowline_intensity


def _smooth_dem_grid(dem: np.ndarray, iterations: int = 1) -> np.ndarray:
    """可选 DEM 平滑（默认关闭，仅保留能力以便后续调参）。"""
    out = dem.astype(np.float64).copy()
    for _ in range(max(0, iterations)):
        p = np.pad(out, 1, mode="edge")
        out = (
            4.0 * p[1:-1, 1:-1]
            + 2.0 * (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:])
            + (p[:-2, :-2] + p[:-2, 2:] + p[2:, :-2] + p[2:, 2:])
        ) / 16.0
    return out


def _workspace_root() -> Path:
    # 由当前文件路径回溯到仓库根目录
    return Path(__file__).resolve().parents[3]


def _validate_dem_raster_profile(ds) -> None:
    # DEM 分析要求单波段高程栅格。
    # 多波段 uint8 文件通常是影像（RGB/RGBA），而非高程数据。
    if int(ds.count) != 1:
        raise RuntimeError(
            f"DEM 文件必须是单波段高程栅格；当前波段数={int(ds.count)}，通常是影像而非高程"
        )

    dtype = str((ds.dtypes[0] if ds.dtypes else "")).lower()
    if dtype in {"uint8", "int8"}:
        raise RuntimeError(
            "DEM 像元类型为 8 位整型（uint8/int8），通常不是高程数据"
            "请使用单波段高程 DEM（常见 float32/int16）"
        )


def _check_dem_raster_profile(ds) -> Tuple[bool, str | None]:
    try:
        _validate_dem_raster_profile(ds)
        return True, None
    except Exception as exc:
        return False, str(exc)


def _suggest_decode_modes(ds) -> List[str]:
    """根据数据特征给出可选 DEM 解码模式。"""
    suggestions: List[str] = []
    if int(ds.count) >= 3:
        suggestions.append("terrain_rgb")
    if int(ds.count) >= 1:
        suggestions.append("single_band")
    return suggestions


def _normalize_decode_mode(decode_mode: str | None) -> DemDecodeMode:
    """规范化并校验解码模式。"""
    raw = str(decode_mode or "none").strip().lower()
    if raw in {"", "none"}:
        return "none"
    if raw in {"single_band", "terrain_rgb"}:
        return cast(DemDecodeMode, raw)
    raise RuntimeError(
        f"不支持的 DEM 解码模式: {decode_mode}。可选: none/single_band/terrain_rgb"
    )


def _decode_dem_source(
    ds,
    rasterio_module,
    decode_mode: str | None,
    decode_band: int | None,
    decode_scale: float | None,
    decode_offset: float | None,
    decode_nodata: float | None,
):
    """按解码配置返回可用于 reproject 的源数据与 nodata。"""
    mode = _normalize_decode_mode(decode_mode)

    try:
        scale = float(1.0 if decode_scale is None else decode_scale)
        offset = float(0.0 if decode_offset is None else decode_offset)
    except Exception as exc:
        raise RuntimeError("DEM 解码参数 scale/offset 无效") from exc

    nodata_candidates: List[float] = []
    if ds.nodata is not None:
        try:
            ds_nodata = float(ds.nodata)
            if np.isfinite(ds_nodata):
                nodata_candidates.append(ds_nodata)
        except Exception:
            pass
    if decode_nodata is not None:
        try:
            user_nodata = float(decode_nodata)
            if np.isfinite(user_nodata):
                nodata_candidates.append(user_nodata)
        except Exception as exc:
            raise RuntimeError("DEM 解码参数 nodata 无效") from exc

    if mode == "none":
        _validate_dem_raster_profile(ds)
        return rasterio_module.band(ds, 1), ds.nodata

    if mode == "single_band":
        band_index = int(1 if decode_band is None else decode_band)
        if band_index < 1 or band_index > int(ds.count):
            raise RuntimeError(
                f"single_band 解码波段越界: {band_index}，可用范围为 1..{int(ds.count)}"
            )

        src = ds.read(band_index).astype(np.float64)
        for nd in nodata_candidates:
            src[np.isclose(src, nd)] = np.nan
        src = src * scale + offset
        return src, np.nan

    if mode == "terrain_rgb":
        if int(ds.count) < 3:
            raise RuntimeError("terrain_rgb 解码至少需要 3 个波段")

        r = ds.read(1).astype(np.float64)
        g = ds.read(2).astype(np.float64)
        b = ds.read(3).astype(np.float64)

        invalid_mask = np.zeros(r.shape, dtype=bool)
        for nd in nodata_candidates:
            invalid_mask |= np.isclose(r, nd) | np.isclose(g, nd) | np.isclose(b, nd)

        # Terrain-RGB 解码公式：高程(米) = -10000 + (R*256^2 + G*256 + B) * 0.1
        src = -10000.0 + (r * 256.0 * 256.0 + g * 256.0 + b) * 0.1
        src = src * scale + offset
        if invalid_mask.any():
            src = np.where(invalid_mask, np.nan, src)
        return src, np.nan

    raise RuntimeError("未知 DEM 解码模式")


def _resolve_dem_path(dem_path: str) -> Path:
    """解析 DEM 路径：先绝对路径，再按仓库/后端相对路径查找。"""
    p = Path(str(dem_path).strip())
    if p.is_absolute() and p.exists():
        return p

    ws_root = _workspace_root()
    backend_root = ws_root / "backend"

    candidates = [
        ws_root / p,
        backend_root / p,
    ]
    for c in candidates:
        if c.exists():
            return c

    raise FileNotFoundError(f"DEM 文件不存在: {dem_path}")


def _load_real_dem(
    west: float,
    south: float,
    east: float,
    north: float,
    resolution: int,
    dem_path: str,
    dem_decode_mode: str | None = None,
    dem_decode_band: int | None = None,
    dem_decode_scale: float | None = None,
    dem_decode_offset: float | None = None,
    dem_decode_nodata: float | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """读取真实 DEM，并重采样到请求 BBox 的规则网格。"""
    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.crs import CRS
        from rasterio.transform import from_bounds
        from rasterio.warp import reproject, transform_bounds
    except Exception as exc:
        raise RuntimeError(
            "未安装 rasterio，无法读取真实 DEM。请先在 backend 环境安装 rasterio。"
        ) from exc

    dem_file = _resolve_dem_path(dem_path)
    lon_grid, lat_grid = _linspace_grid(west, south, east, north, resolution)

    with rasterio.open(dem_file) as ds:
        # 1) 解码源栅格（原始单波段 / 指定波段 / Terrain-RGB）
        if ds.count < 1:
            raise RuntimeError("DEM 波段数为 0，无法读取")
        source_data, source_nodata = _decode_dem_source(
            ds,
            rasterio,
            dem_decode_mode,
            dem_decode_band,
            dem_decode_scale,
            dem_decode_offset,
            dem_decode_nodata,
        )

        # 2) 检查并补齐 CRS（允许同名 .prj）
        src_crs = ds.crs
        if not src_crs:
            prj_path = dem_file.with_suffix(".prj")
            if prj_path.exists():
                try:
                    src_crs = CRS.from_wkt(prj_path.read_text(encoding="utf-8", errors="ignore"))
                except Exception as exc:
                    raise RuntimeError(f"DEM 坐标系缺失，且 .prj 解析失败: {prj_path}") from exc
            else:
                raise RuntimeError(
                    "DEM 缺少坐标系信息（CRS）。请为 tif 写入 CRS，或提供同名 .prj 文件。"
                )

        # 3) 判断请求 BBox 与 DEM 覆盖范围是否相交
        req_bounds = (west, south, east, north)
        try:
            ds_bounds_ll = transform_bounds(src_crs, "EPSG:4326", *ds.bounds, densify_pts=21)
        except Exception as exc:
            raise RuntimeError("DEM 坐标系无法转换到 EPSG:4326，请检查 DEM CRS 定义") from exc
        db_w, db_s, db_e, db_n = ds_bounds_ll
        if east <= db_w or west >= db_e or north <= db_s or south >= db_n:
            raise RuntimeError("请求 BBox 与 DEM 覆盖范围无交集")

        # 4) 将 DEM 重投影并重采样到目标规则网格
        dst_transform = from_bounds(west, south, east, north, resolution, resolution)
        dem = np.full((resolution, resolution), np.nan, dtype=np.float64)

        reproject(
            source=source_data,
            destination=dem,
            src_transform=ds.transform,
            src_crs=src_crs,
            src_nodata=source_nodata,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )

        # 重投影输出第 0 行是北侧，翻转后与“南到北”网格顺序一致。
        dem = np.flipud(dem)

    if not np.isfinite(dem).any():
        raise RuntimeError("DEM 采样结果全部无效，请检查路径与 BBox")

    if np.isnan(dem).any():
        fill = float(np.nanmean(dem))
        dem = np.where(np.isnan(dem), fill, dem)

    return lon_grid, lat_grid, dem


def get_dem_metadata(dem_path: str) -> Dict[str, object]:
    """读取 DEM 元信息，供前端在分析前做可用性检查。"""
    try:
        import rasterio
        from rasterio.crs import CRS
        from rasterio.warp import transform_bounds
    except Exception as exc:
        raise RuntimeError(
            "未安装 rasterio，无法读取真实 DEM。请先在 backend 环境安装 rasterio。"
        ) from exc

    dem_file = _resolve_dem_path(dem_path)
    with rasterio.open(dem_file) as ds:
        profile_ok, profile_message = _check_dem_raster_profile(ds)

        src_crs = ds.crs
        if not src_crs:
            prj_path = dem_file.with_suffix(".prj")
            if prj_path.exists():
                try:
                    src_crs = CRS.from_wkt(prj_path.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    src_crs = None

        bounds_wgs84 = None
        if src_crs:
            try:
                wb = transform_bounds(src_crs, "EPSG:4326", *ds.bounds, densify_pts=21)
                bounds_wgs84 = {
                    "west": float(wb[0]),
                    "south": float(wb[1]),
                    "east": float(wb[2]),
                    "north": float(wb[3]),
                }
            except Exception:
                bounds_wgs84 = None

        return {
            "dem_path": str(dem_path),
            "resolved_path": str(dem_file),
            "crs": str(src_crs) if src_crs else None,
            "width": int(ds.width),
            "height": int(ds.height),
            "count": int(ds.count),
            "dtypes": [str(x) for x in ds.dtypes],
            "nodata": (float(ds.nodata) if ds.nodata is not None else None),
            "analysis_ready": bool(profile_ok),
            "analysis_error": profile_message,
            "decode_suggestions": ([] if profile_ok else _suggest_decode_modes(ds)),
            "bounds_dataset": {
                "left": float(ds.bounds.left),
                "bottom": float(ds.bounds.bottom),
                "right": float(ds.bounds.right),
                "top": float(ds.bounds.top),
            },
            "bounds_wgs84": bounds_wgs84,
        }


def analyze_terrain(
    west: float,
    south: float,
    east: float,
    north: float,
    resolution: int,
    dem_path: str | None = None,
    dem_decode_mode: str | None = None,
    dem_decode_band: int | None = None,
    dem_decode_scale: float | None = None,
    dem_decode_offset: float | None = None,
    dem_decode_nodata: float | None = None,
    start_lon: float | None = None,
    start_lat: float | None = None,
    end_lon: float | None = None,
    end_lat: float | None = None,
) -> TerrainResult:
    """统一地形分析入口：支持真实 DEM 与合成 DEM。"""
    if dem_path:
        lon_grid, lat_grid, dem = _load_real_dem(
            west,
            south,
            east,
            north,
            resolution,
            dem_path,
            dem_decode_mode=dem_decode_mode,
            dem_decode_band=dem_decode_band,
            dem_decode_scale=dem_decode_scale,
            dem_decode_offset=dem_decode_offset,
            dem_decode_nodata=dem_decode_nodata,
        )
        dem_source = "real_dem"
    else:
        lon_grid, lat_grid = _linspace_grid(west, south, east, north, resolution)
        dem = _synthetic_dem(lon_grid, lat_grid)
        dem_source = "synthetic"

    # 默认不平滑：前端是直接在采样网格计算指标；
    # 后端额外平滑会导致同分辨率下前后端结果不一致。
    dem = _smooth_dem_grid(dem, iterations=0)

    slope_deg, aspect_deg, curvature, cost, min_cost_dir_deg, min_cost_dir_slope_deg, flowline_intensity = _compute_terrain_metrics(
        dem,
        west,
        south,
        east,
        north,
        resolution,
        start_lon=start_lon,
        start_lat=start_lat,
        end_lon=end_lon,
        end_lat=end_lat,
    )

    return TerrainResult(
        lon_grid=lon_grid,
        lat_grid=lat_grid,
        slope_deg=slope_deg,
        aspect_deg=aspect_deg,
        curvature=curvature,
        cost=cost,
        min_cost_dir_deg=min_cost_dir_deg,
        min_cost_dir_slope_deg=min_cost_dir_slope_deg,
        flowline_intensity=flowline_intensity,
        dem_grid=dem,
        dem_source=dem_source,
    )


def _grid_index_from_lonlat(
    lon: float,
    lat: float,
    west: float,
    south: float,
    east: float,
    north: float,
    resolution: int,
) -> Tuple[int, int]:
    """将经纬度映射到网格索引，并限制在合法范围内。"""
    x = int(round((lon - west) / max(1e-12, east - west) * (resolution - 1)))
    y = int(round((lat - south) / max(1e-12, north - south) * (resolution - 1)))
    x = max(0, min(resolution - 1, x))
    y = max(0, min(resolution - 1, y))
    return x, y


def _neighbor_8(x: int, y: int, n: int) -> List[Tuple[int, int]]:
    """返回 8 邻域可达节点。"""
    out: List[Tuple[int, int]] = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if 0 <= nx < n and 0 <= ny < n:
                out.append((nx, ny))
    return out


def plan_path(
    west: float,
    south: float,
    east: float,
    north: float,
    resolution: int,
    start_lon: float,
    start_lat: float,
    end_lon: float,
    end_lat: float,
    dem_path: str | None = None,
    dem_decode_mode: str | None = None,
    dem_decode_band: int | None = None,
    dem_decode_scale: float | None = None,
    dem_decode_offset: float | None = None,
    dem_decode_nodata: float | None = None,
) -> PathResult:
    """基于地形成本网格执行最短路（Dijkstra）路径规划。"""
    terrain = analyze_terrain(
        west,
        south,
        east,
        north,
        resolution,
        dem_path=dem_path,
        dem_decode_mode=dem_decode_mode,
        dem_decode_band=dem_decode_band,
        dem_decode_scale=dem_decode_scale,
        dem_decode_offset=dem_decode_offset,
        dem_decode_nodata=dem_decode_nodata,
    )
    cost = terrain.cost

    sx, sy = _grid_index_from_lonlat(start_lon, start_lat, west, south, east, north, resolution)
    ex, ey = _grid_index_from_lonlat(end_lon, end_lat, west, south, east, north, resolution)

    # 距离表：起点到各节点的最小代价；前驱表：用于回溯路径
    inf = float("inf")
    dist = np.full((resolution, resolution), inf, dtype=np.float64)
    prev: Dict[Tuple[int, int], Tuple[int, int]] = {}
    dist[sy, sx] = 0.0
    pq: List[Tuple[float, int, int]] = [(0.0, sx, sy)]

    # 最短路主循环
    while pq:
        cur_d, x, y = heapq.heappop(pq)
        if cur_d > dist[y, x]:
            continue
        if x == ex and y == ey:
            break
        for nx, ny in _neighbor_8(x, y, resolution):
            step = math.hypot(nx - x, ny - y)
            step_cost = step * float(cost[ny, nx])
            nd = cur_d + step_cost
            if nd < dist[ny, nx]:
                dist[ny, nx] = nd
                prev[(nx, ny)] = (x, y)
                heapq.heappush(pq, (nd, nx, ny))

    path_nodes: List[Tuple[int, int]] = []
    cur = (ex, ey)
    if cur not in prev and cur != (sx, sy):
        # 回退直线，确保一定有 Cesium 可显示结果。
        for t in np.linspace(0.0, 1.0, num=64):
            ix = int(round(sx + (ex - sx) * t))
            iy = int(round(sy + (ey - sy) * t))
            path_nodes.append((ix, iy))
    else:
        path_nodes.append(cur)
        while cur != (sx, sy):
            cur = prev[cur]
            path_nodes.append(cur)
        path_nodes.reverse()

    # 将网格路径转回经纬度，并累计近似平面距离（米）。
    path_lonlat: List[Tuple[float, float]] = []
    total_distance_m = 0.0
    for i, (x, y) in enumerate(path_nodes):
        lon = float(terrain.lon_grid[y, x])
        lat = float(terrain.lat_grid[y, x])
        path_lonlat.append((lon, lat))
        if i > 0:
            lon0, lat0 = path_lonlat[i - 1]
            dx = (lon - lon0) * 111320.0
            dy = (lat - lat0) * 111320.0
            total_distance_m += math.hypot(dx, dy)

    return PathResult(path_lonlat=path_lonlat, distance_m=total_distance_m)
