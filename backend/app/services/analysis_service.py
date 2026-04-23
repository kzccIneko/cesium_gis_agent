from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Tuple, cast
import heapq
import math
import numpy as np


@dataclass
class TerrainResult:
    lon_grid: np.ndarray
    lat_grid: np.ndarray
    slope_deg: np.ndarray
    aspect_deg: np.ndarray
    curvature: np.ndarray
    cost: np.ndarray
    dem_source: Literal["synthetic", "real_dem"]


@dataclass
class PathResult:
    path_lonlat: List[Tuple[float, float]]
    distance_m: float


DemDecodeMode = Literal["none", "single_band", "terrain_rgb"]


def _linspace_grid(west: float, south: float, east: float, north: float, resolution: int) -> Tuple[np.ndarray, np.ndarray]:
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
    sx, sy = _cell_size_xy_meters(west, south, east, north, resolution)
    return max(1e-6, (sx + sy) * 0.5)


def _cell_size_xy_meters(west: float, south: float, east: float, north: float, resolution: int) -> Tuple[float, float]:
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
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # Use a frontend-equivalent "single-grid-cell, 9-point" model:
    # for each cell, build 3x3 samples from the cell corners/edge-midpoints/center.
    # This matches the frontend's per-cell sampling behavior and avoids front/back pattern drift.
    rows, cols = dem.shape
    if rows < 2 or cols < 2:
        z = np.zeros_like(dem, dtype=np.float64)
        return z, z, z, z

    cell_size_x_m, cell_size_y_m = _cell_size_xy_meters(west, south, east, north, resolution)
    cell_size_m = (cell_size_x_m + cell_size_y_m) * 0.5

    # Frontend computes g from center->west-edge-midpoint, i.e. half of cell width.
    # Keep this choice for strict visual parity with existing frontend results.
    g = max(1e-6, cell_size_x_m * 0.5)

    dem_f64 = dem.astype(np.float64)
    slope_deg = np.empty((rows, cols), dtype=np.float64)
    aspect_deg = np.empty((rows, cols), dtype=np.float64)
    curvature = np.empty((rows, cols), dtype=np.float64)
    cost = np.empty((rows, cols), dtype=np.float64)

    for i in range(rows - 1):
        for j in range(cols - 1):
            # Cell corners in south->north row order.
            z1 = float(dem_f64[i, j])          # SW
            z3 = float(dem_f64[i, j + 1])      # SE
            z7 = float(dem_f64[i + 1, j])      # NW
            z9 = float(dem_f64[i + 1, j + 1])  # NE

            # Cell edge-midpoints and center (bilinear-equivalent on the cell).
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

            if slope <= 0.0:
                speed = 25.0
            elif slope <= 3.0:
                speed = 25.0 - ((25.0 - 20.0) * (slope - 0.0)) / (3.0 - 0.0)
            elif slope <= 6.0:
                speed = 20.0 - ((20.0 - 15.0) * (slope - 3.0)) / (6.0 - 3.0)
            elif slope <= 10.0:
                speed = 15.0 - ((15.0 - 12.0) * (slope - 6.0)) / (10.0 - 6.0)
            elif slope <= 15.0:
                speed = 12.0 - ((12.0 - 8.0) * (slope - 10.0)) / (15.0 - 10.0)
            elif slope <= 20.0:
                speed = 8.0 - ((8.0 - 5.0) * (slope - 15.0)) / (20.0 - 15.0)
            elif slope <= 30.0:
                speed = 5.0 - ((5.0 - 0.0) * (slope - 20.0)) / (30.0 - 20.0)
            else:
                speed = 0.0

            if speed > 0.1:
                cost_val = cell_size_m / (speed / 3.6)
            else:
                cost_val = 999999.0

            slope_deg[i, j] = slope
            aspect_deg[i, j] = aspect
            curvature[i, j] = curv
            cost[i, j] = cost_val

    # Last row/column are not explicit cells; copy nearest valid cell values.
    slope_deg[-1, :] = slope_deg[-2, :]
    slope_deg[:, -1] = slope_deg[:, -2]
    aspect_deg[-1, :] = aspect_deg[-2, :]
    aspect_deg[:, -1] = aspect_deg[:, -2]
    curvature[-1, :] = curvature[-2, :]
    curvature[:, -1] = curvature[:, -2]
    cost[-1, :] = cost[-2, :]
    cost[:, -1] = cost[:, -2]

    return slope_deg, aspect_deg, curvature, cost


def _smooth_dem_grid(dem: np.ndarray, iterations: int = 1) -> np.ndarray:
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
    # backend/app/services/analysis_service.py -> workspace root
    return Path(__file__).resolve().parents[3]


def _validate_dem_raster_profile(ds) -> None:
    # DEM analysis requires a single-band elevation raster.
    # Multi-band uint8 files are usually imagery (RGB/RGBA), not elevation.
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
    suggestions: List[str] = []
    if int(ds.count) >= 3:
        suggestions.append("terrain_rgb")
    if int(ds.count) >= 1:
        suggestions.append("single_band")
    return suggestions


def _normalize_decode_mode(decode_mode: str | None) -> DemDecodeMode:
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

        # Terrain-RGB 公式: h(m) = -10000 + (R*256^2 + G*256 + B) * 0.1
        src = -10000.0 + (r * 256.0 * 256.0 + g * 256.0 + b) * 0.1
        src = src * scale + offset
        if invalid_mask.any():
            src = np.where(invalid_mask, np.nan, src)
        return src, np.nan

    raise RuntimeError("未知 DEM 解码模式")


def _resolve_dem_path(dem_path: str) -> Path:
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

        req_bounds = (west, south, east, north)
        try:
            ds_bounds_ll = transform_bounds(src_crs, "EPSG:4326", *ds.bounds, densify_pts=21)
        except Exception as exc:
            raise RuntimeError("DEM 坐标系无法转换到 EPSG:4326，请检查 DEM CRS 定义") from exc
        db_w, db_s, db_e, db_n = ds_bounds_ll
        if east <= db_w or west >= db_e or north <= db_s or south >= db_n:
            raise RuntimeError("请求 BBox 与 DEM 覆盖范围无交集")

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

        # reproject 输出第 0 行是北侧，翻转后与 south->north 的网格一致。
        dem = np.flipud(dem)

    if not np.isfinite(dem).any():
        raise RuntimeError("DEM 采样结果全部无效，请检查路径与 BBox")

    if np.isnan(dem).any():
        fill = float(np.nanmean(dem))
        dem = np.where(np.isnan(dem), fill, dem)

    return lon_grid, lat_grid, dem


def get_dem_metadata(dem_path: str) -> Dict[str, object]:
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
) -> TerrainResult:
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

    # Do not smooth by default: frontend computes metrics directly on sampled grid.
    # Extra backend smoothing causes front/back value mismatch under same resolution.
    dem = _smooth_dem_grid(dem, iterations=0)

    slope_deg, aspect_deg, curvature, cost = _compute_terrain_metrics(
        dem,
        west,
        south,
        east,
        north,
        resolution,
    )

    return TerrainResult(
        lon_grid=lon_grid,
        lat_grid=lat_grid,
        slope_deg=slope_deg,
        aspect_deg=aspect_deg,
        curvature=curvature,
        cost=cost,
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
    x = int(round((lon - west) / max(1e-12, east - west) * (resolution - 1)))
    y = int(round((lat - south) / max(1e-12, north - south) * (resolution - 1)))
    x = max(0, min(resolution - 1, x))
    y = max(0, min(resolution - 1, y))
    return x, y


def _neighbor_8(x: int, y: int, n: int) -> List[Tuple[int, int]]:
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

    inf = float("inf")
    dist = np.full((resolution, resolution), inf, dtype=np.float64)
    prev: Dict[Tuple[int, int], Tuple[int, int]] = {}
    dist[sy, sx] = 0.0
    pq: List[Tuple[float, int, int]] = [(0.0, sx, sy)]

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
