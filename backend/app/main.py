from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir
from time import perf_counter
from typing import Dict, List, Optional, Literal, cast
from uuid import uuid4
import hashlib
import json
import re
import shutil
import numpy as np

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .schemas import (
    AnalysisStats,
    FormatOption,
    FormatOptionsResponse,
    OutputArtifact,
    PathPlanRequest,
    PathPlanResponse,
    TerrainAnalysisRequest,
    TerrainAnalysisResponse,
    TerrainClassifyRequest,
    TerrainClassifyResponse,
)
from .services.analysis_service import analyze_terrain, get_dem_metadata, plan_path
from .services.terrain_classifier import classify_terrain, get_terrain_class_legend
from .services.export_service import (
    export_grid_as_czml,
    export_grid_as_geojson,
    export_grid_as_kml,
    export_grid_classification_as_geojson,
    export_path_as_czml,
    export_path_as_geojson,
    export_path_as_kml,
)


# 后端目录、输出目录与瓦片缓存目录
APP_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(gettempdir()) / "cesiumjs_debug_outputs"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
TILE_CACHE_ROOT = APP_ROOT.parent / "outputs" / "tiles"
TILE_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

# 后端接口应用与跨域配置
app = FastAPI(title="DEM Cesium Analysis API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_ROOT)), name="outputs")
app.mount("/tile-cache", StaticFiles(directory=str(TILE_CACHE_ROOT)), name="tile-cache")


def _dir_size_bytes(path: Path) -> int:
    """递归计算目录大小（字节）。"""
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except Exception:
        return total
    return total


def _write_json_atomic(path: Path, payload: Dict[str, object]) -> None:
    """原子写 JSON，避免并发写入造成半文件状态。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp_" + uuid4().hex)
    tmp.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _round_bbox(bbox) -> Dict[str, float]:
    """统一 BBox 精度，保证缓存键稳定。"""
    return {
        "west": round(float(bbox.west), 6),
        "south": round(float(bbox.south), 6),
        "east": round(float(bbox.east), 6),
        "north": round(float(bbox.north), 6),
    }


def _stable_hash(payload: Dict[str, object]) -> str:
    """生成稳定哈希，用于缓存目录与请求 ID。"""
    text = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _sanitize_tile_segment(value: str) -> str:
    """清洗缓存路径片段，避免非法字符与目录穿越。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("\\", "/")
    raw = re.sub(r"[^A-Za-z0-9_\-\/\.]", "_", raw)
    raw = raw.strip().strip("/")
    while "//" in raw:
        raw = raw.replace("//", "/")
    if ".." in raw:
        raw = raw.replace("..", "_")
    return raw[:240]


def _build_tile_cache_context(req: TerrainAnalysisRequest) -> Optional[Dict[str, object]]:
    """根据请求构造瓦片缓存上下文（目录、URL 前缀、缓存 ID）。"""
    raw_set = (req.tile_set_id or "").strip()
    raw_key = (req.tile_key or "").strip()
    if not raw_set and not raw_key:
        return None

    base_payload = {
        "bbox": _round_bbox(req.bbox),
        "resolution": int(req.resolution),
        "dem_path": str(req.dem_path or ""),
        "dem_decode_mode": str(req.dem_decode_mode or "none"),
        "dem_decode_band": int(req.dem_decode_band or 1),
        "dem_decode_scale": float(req.dem_decode_scale or 1.0),
        "dem_decode_offset": float(req.dem_decode_offset or 0.0),
        "dem_decode_nodata": None if req.dem_decode_nodata is None else float(req.dem_decode_nodata),
        "start_point": [float(req.start_point[0]), float(req.start_point[1])] if req.start_point else None,
        "end_point": [float(req.end_point[0]), float(req.end_point[1])] if req.end_point else None,
    }

    tile_set_id = _sanitize_tile_segment(raw_set) if raw_set else ("ts_" + _stable_hash(base_payload)[:16])
    tile_key = _sanitize_tile_segment(raw_key) if raw_key else (
        "tile_" + _stable_hash({"bbox": base_payload["bbox"], "resolution": base_payload["resolution"]})[:16]
    )
    if not tile_set_id or not tile_key:
        return None

    resolution_tag = f"r{int(req.resolution)}"
    cache_dir = TILE_CACHE_ROOT / tile_set_id / tile_key / resolution_tag
    cache_url_prefix = f"/tile-cache/{tile_set_id}/{tile_key}/{resolution_tag}"
    cache_id = _stable_hash({
        "tile_set_id": tile_set_id,
        "tile_key": tile_key,
        "resolution": int(req.resolution),
    })[:20]

    return {
        "tile_set_id": tile_set_id,
        "tile_key": tile_key,
        "cache_dir": cache_dir,
        "cache_url_prefix": cache_url_prefix,
        "cache_id": cache_id,
    }


def _load_tile_cache_stats(cache_dir: Path) -> Optional[Dict[str, object]]:
    """读取缓存目录中的 stats.json。"""
    stats_file = cache_dir / "stats.json"
    if not stats_file.exists():
        return None
    try:
        data = json.loads(stats_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or "stats" not in data:
        return None
    return data


def _normalize_stats_payload(stats: Dict[str, AnalysisStats]) -> Dict[str, Dict[str, float]]:
    """将 Pydantic 对象统一转换为可序列化字典。"""
    out: Dict[str, Dict[str, float]] = {}
    for key, value in stats.items():
        if hasattr(value, "model_dump"):
            out[key] = value.model_dump()
        elif hasattr(value, "dict"):
            out[key] = value.dict()
        else:
            out[key] = {"min": float(value.min), "max": float(value.max), "mean": float(value.mean)}
    return out


def _clear_output_cache() -> Dict[str, int]:
    """清理输出缓存目录，并统计释放空间。"""
    deleted_dirs = 0
    freed_bytes = 0
    if not OUTPUT_ROOT.exists():
        return {"deleted_dirs": 0, "freed_bytes": 0}

    for child in OUTPUT_ROOT.iterdir():
        if not child.is_dir():
            continue
        try:
            freed_bytes += _dir_size_bytes(child)
            shutil.rmtree(child, ignore_errors=True)
            deleted_dirs += 1
        except Exception:
            continue

    return {"deleted_dirs": deleted_dirs, "freed_bytes": int(freed_bytes)}


def _clear_tile_cache() -> Dict[str, int]:
    """清理瓦片缓存目录，并统计释放空间。"""
    deleted_dirs = 0
    freed_bytes = 0
    if not TILE_CACHE_ROOT.exists():
        return {"deleted_dirs": 0, "freed_bytes": 0}

    for child in TILE_CACHE_ROOT.iterdir():
        if not child.is_dir():
            continue
        try:
            freed_bytes += _dir_size_bytes(child)
            shutil.rmtree(child, ignore_errors=True)
            deleted_dirs += 1
        except Exception:
            continue

    return {"deleted_dirs": deleted_dirs, "freed_bytes": int(freed_bytes)}


def _stats(values: np.ndarray) -> AnalysisStats:
    """计算最小值、最大值、均值。"""
    return AnalysisStats(min=float(np.min(values)), max=float(np.max(values)), mean=float(np.mean(values)))


@app.get("/api/v1/formats", response_model=FormatOptionsResponse)
def get_formats() -> FormatOptionsResponse:
    """返回前端可选导出格式及 Cesium 对应加载器。"""
    terrain = [
        FormatOption(value="geojson", label="GeoJSON 网格矢量", cesium_loader="GeoJsonDataSource.load"),
        FormatOption(value="czml", label="CZML 栅格采样点", cesium_loader="CzmlDataSource.load"),
        FormatOption(value="kml", label="KML 网格矢量", cesium_loader="KmlDataSource.load"),
    ]
    path = [
        FormatOption(value="geojson", label="GeoJSON 路径", cesium_loader="GeoJsonDataSource.load"),
        FormatOption(value="czml", label="CZML 轨迹", cesium_loader="CzmlDataSource.load"),
        FormatOption(value="kml", label="KML 路径", cesium_loader="KmlDataSource.load"),
    ]
    return FormatOptionsResponse(terrain=terrain, path=path)


@app.get("/api/v1/dem/meta")
def get_dem_meta(dem_path: str = Query(..., min_length=1)):
    """读取 DEM 元数据（用于前端分析前检查）。"""
    try:
        return get_dem_metadata(dem_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/cache/outputs/clear")
def clear_outputs_cache():
    """清空输出缓存。"""
    return _clear_output_cache()


@app.post("/api/v1/cache/tiles/clear")
def clear_tiles_cache():
    """清空瓦片缓存。"""
    return _clear_tile_cache()


@app.post("/api/v1/analyze/terrain", response_model=TerrainAnalysisResponse)
def analyze_terrain_api(req: TerrainAnalysisRequest) -> TerrainAnalysisResponse:
    """地形分析接口：支持缓存命中与多格式导出。"""
    t0 = perf_counter()
    analysis_name_map = {
        "slope": "slope_deg",
        "aspect": "aspect_deg",
        "curvature": "curvature",
        "cost": "cost",
    }

    if req.analysis_type == "comprehensive":
        selected_names = [
            ("slope", analysis_name_map["slope"]),
            ("aspect", analysis_name_map["aspect"]),
            ("curvature", analysis_name_map["curvature"]),
            ("cost", analysis_name_map["cost"]),
        ]
    else:
        selected_names = [(req.analysis_type, analysis_name_map[req.analysis_type])]

    cache_ctx = _build_tile_cache_context(req)
    if cache_ctx:
        # 若缓存文件齐全则直接返回，避免重复计算与导出。
        cache_dir = cast(Path, cache_ctx["cache_dir"])
        expected_files: List[Path] = []
        for fmt in req.output_formats:
            for _, selected_name in selected_names:
                expected_files.append(cache_dir / f"{selected_name}.{fmt}")

        cache_stats = _load_tile_cache_stats(cache_dir)
        if cache_stats and all(p.exists() for p in expected_files):
            artifacts: List[OutputArtifact] = []
            for fmt in req.output_formats:
                for _, selected_name in selected_names:
                    artifacts.append(
                        OutputArtifact(
                            format=fmt,
                            url=f"{cache_ctx['cache_url_prefix']}/{selected_name}.{fmt}",
                            feature_count=None,
                        )
                    )

            stats_payload = cast(Dict[str, AnalysisStats], cache_stats.get("stats") or {})
            dem_source_raw = str(cache_stats.get("dem_source") or "synthetic")
            dem_source_value: Literal["synthetic", "real_dem"] = (
                "real_dem" if dem_source_raw == "real_dem" else "synthetic"
            )
            return TerrainAnalysisResponse(
                request_id=str(cache_ctx["cache_id"]),
                analysis_type=req.analysis_type,
                resolution=req.resolution,
                dem_source=dem_source_value,
                cache_hit=True,
                artifacts=artifacts,
                stats=stats_payload,
            )

    request_id = uuid4().hex
    out_dir = OUTPUT_ROOT / request_id
    url_prefix = f"/outputs/{request_id}"
    if cache_ctx:
        # 开启瓦片缓存时，输出目录切换到瓦片缓存路径。
        request_id = str(cache_ctx["cache_id"])
        out_dir = cast(Path, cache_ctx["cache_dir"])
        url_prefix = cast(str, cache_ctx["cache_url_prefix"])

    try:
        terrain = analyze_terrain(
            west=req.bbox.west,
            south=req.bbox.south,
            east=req.bbox.east,
            north=req.bbox.north,
            resolution=req.resolution,
            dem_path=req.dem_path,
            dem_decode_mode=req.dem_decode_mode,
            dem_decode_band=req.dem_decode_band,
            dem_decode_scale=req.dem_decode_scale,
            dem_decode_offset=req.dem_decode_offset,
            dem_decode_nodata=req.dem_decode_nodata,
            start_lon=(float(req.start_point[0]) if req.start_point else None),
            start_lat=(float(req.start_point[1]) if req.start_point else None),
            end_lon=(float(req.end_point[0]) if req.end_point else None),
            end_lat=(float(req.end_point[1]) if req.end_point else None),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    analysis_map = {
        "slope": (terrain.slope_deg, "slope_deg"),
        "aspect": (terrain.aspect_deg, "aspect_deg"),
        "curvature": (terrain.curvature, "curvature"),
        "cost": (terrain.cost, "cost"),
    }

    if req.analysis_type == "comprehensive":
        selected_items = [
            ("slope", terrain.slope_deg, "slope_deg"),
            ("aspect", terrain.aspect_deg, "aspect_deg"),
            ("curvature", terrain.curvature, "curvature"),
            ("cost", terrain.cost, "cost"),
        ]
    else:
        selected_grid, selected_name = analysis_map[req.analysis_type]
        selected_items = [(req.analysis_type, selected_grid, selected_name)]

    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts = []
    for fmt in req.output_formats:
        # 仅在目标文件不存在时导出，避免重复写盘。
        for _, selected_grid, selected_name in selected_items:
            if fmt == "geojson":
                out_file = out_dir / f"{selected_name}.geojson"
                feature_count = None
                if not out_file.exists():
                    extra_fields = None
                    if selected_name == "cost":
                        # 代价图层额外写入方向最小代价相关字段，供前端数值提示显示。
                        extra_fields = {
                            "slope_deg": terrain.slope_deg,
                            "aspect_deg": terrain.aspect_deg,
                            "curvature": terrain.curvature,
                            "min_cost_dir_deg": terrain.min_cost_dir_deg,
                            "min_cost_dir_slope_deg": terrain.min_cost_dir_slope_deg,
                            "flowline_intensity": terrain.flowline_intensity,
                        }
                    feature_count = export_grid_as_geojson(
                        out_file,
                        terrain.lon_grid,
                        terrain.lat_grid,
                        selected_grid,
                        selected_name,
                        extra_fields=extra_fields,
                    )
                artifacts.append(OutputArtifact(format="geojson", url=f"{url_prefix}/{selected_name}.geojson", feature_count=feature_count))
            elif fmt == "czml":
                out_file = out_dir / f"{selected_name}.czml"
                feature_count = None
                if not out_file.exists():
                    feature_count = export_grid_as_czml(
                        out_file,
                        terrain.lon_grid,
                        terrain.lat_grid,
                        selected_grid,
                        selected_name,
                    )
                artifacts.append(OutputArtifact(format="czml", url=f"{url_prefix}/{selected_name}.czml", feature_count=feature_count))
            elif fmt == "kml":
                out_file = out_dir / f"{selected_name}.kml"
                feature_count = None
                if not out_file.exists():
                    feature_count = export_grid_as_kml(
                        out_file,
                        terrain.lon_grid,
                        terrain.lat_grid,
                        selected_grid,
                        selected_name,
                    )
                artifacts.append(OutputArtifact(format="kml", url=f"{url_prefix}/{selected_name}.kml", feature_count=feature_count))

    stats = {
        "slope": _stats(terrain.slope_deg),
        "aspect": _stats(terrain.aspect_deg),
        "curvature": _stats(terrain.curvature),
        "cost": _stats(terrain.cost),
        "duration_ms": AnalysisStats(min=0.0, max=0.0, mean=(perf_counter() - t0) * 1000.0),
    }

    if cache_ctx:
        # 缓存开启时，写入统计文件供后续快速命中返回。
        _write_json_atomic(
            out_dir / "stats.json",
            {"stats": _normalize_stats_payload(stats), "dem_source": terrain.dem_source},
        )

    return TerrainAnalysisResponse(
        request_id=request_id,
        analysis_type=req.analysis_type,
        resolution=req.resolution,
        dem_source=terrain.dem_source,
        cache_hit=False,
        artifacts=artifacts,
        stats=stats,
    )


@app.post("/api/v1/analyze/classify", response_model=TerrainClassifyResponse)
def classify_terrain_api(req: TerrainClassifyRequest) -> TerrainClassifyResponse:
    """地貌语义分类接口。"""
    t0 = perf_counter()
    request_id = uuid4().hex
    out_dir = OUTPUT_ROOT / request_id
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        terrain = analyze_terrain(
            west=req.bbox.west,
            south=req.bbox.south,
            east=req.bbox.east,
            north=req.bbox.north,
            resolution=req.resolution,
            dem_path=req.dem_path,
            dem_decode_mode=req.dem_decode_mode,
            dem_decode_band=req.dem_decode_band,
            dem_decode_scale=req.dem_decode_scale,
            dem_decode_offset=req.dem_decode_offset,
            dem_decode_nodata=req.dem_decode_nodata,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 用 BBox 估算栅格单元大小（米）
    lon_span = abs(float(req.bbox.east) - float(req.bbox.west))
    lat_span = abs(float(req.bbox.north) - float(req.bbox.south))
    mean_lat = math.radians((float(req.bbox.south) + float(req.bbox.north)) * 0.5)
    lon_m = lon_span * 111320.0 * max(1e-6, math.cos(mean_lat)) / max(1, req.resolution - 1)
    lat_m = lat_span * 110574.0 / max(1, req.resolution - 1)
    cell_size_m = (lon_m + lat_m) * 0.5

    class_ids, cost_adjustment, confidence = classify_terrain(
        dem=terrain.dem_grid,
        slope_deg=terrain.slope_deg,
        curvature=terrain.curvature,
        cell_size_m=cell_size_m,
    )

    legend = get_terrain_class_legend()
    url_prefix = f"/outputs/{request_id}"
    artifacts: List[OutputArtifact] = []

    for fmt in req.output_formats:
        if fmt == "geojson":
            out_file = out_dir / "terrain_classification.geojson"
            feature_count = None
            if not out_file.exists():
                feature_count = export_grid_classification_as_geojson(
                    out_file,
                    terrain.lon_grid,
                    terrain.lat_grid,
                    class_ids,
                    confidence,
                    legend,
                )
            artifacts.append(OutputArtifact(
                format="geojson",
                url=f"{url_prefix}/terrain_classification.geojson",
                feature_count=feature_count,
            ))
        elif fmt == "czml":
            out_file = out_dir / "terrain_classification.czml"
            if not out_file.exists():
                export_grid_as_czml(
                    out_file,
                    terrain.lon_grid,
                    terrain.lat_grid,
                    class_ids.astype(np.float64),
                    "terrain_classification",
                )
            artifacts.append(OutputArtifact(
                format="czml",
                url=f"{url_prefix}/terrain_classification.czml",
            ))
        elif fmt == "kml":
            out_file = out_dir / "terrain_classification.kml"
            if not out_file.exists():
                export_grid_as_kml(
                    out_file,
                    terrain.lon_grid,
                    terrain.lat_grid,
                    class_ids.astype(np.float64),
                    "terrain_classification",
                )
            artifacts.append(OutputArtifact(
                format="kml",
                url=f"{url_prefix}/terrain_classification.kml",
            ))

    return TerrainClassifyResponse(
        request_id=request_id,
        resolution=req.resolution,
        dem_source=terrain.dem_source,
        artifacts=artifacts,
        legend=legend,
    )


@app.post("/api/v1/analyze/path", response_model=PathPlanResponse)
def analyze_path_api(req: PathPlanRequest) -> PathPlanResponse:
    """路径规划接口：输出路径长度、节点数量与导出文件。"""
    request_id = uuid4().hex
    out_dir = OUTPUT_ROOT / request_id
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        path_result = plan_path(
            west=req.bbox.west,
            south=req.bbox.south,
            east=req.bbox.east,
            north=req.bbox.north,
            resolution=req.resolution,
            start_lon=float(req.start_point[0]),
            start_lat=float(req.start_point[1]),
            end_lon=float(req.end_point[0]),
            end_lat=float(req.end_point[1]),
            dem_path=req.dem_path,
            dem_decode_mode=req.dem_decode_mode,
            dem_decode_band=req.dem_decode_band,
            dem_decode_scale=req.dem_decode_scale,
            dem_decode_offset=req.dem_decode_offset,
            dem_decode_nodata=req.dem_decode_nodata,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    artifacts: List[OutputArtifact] = []
    for fmt in req.output_formats:
        if fmt == "geojson":
            out_file = out_dir / "path.geojson"
            feature_count = export_path_as_geojson(out_file, path_result.path_lonlat)
            artifacts.append(OutputArtifact(format="geojson", url=f"/outputs/{request_id}/path.geojson", feature_count=feature_count))
        elif fmt == "czml":
            out_file = out_dir / "path.czml"
            feature_count = export_path_as_czml(out_file, path_result.path_lonlat)
            artifacts.append(OutputArtifact(format="czml", url=f"/outputs/{request_id}/path.czml", feature_count=feature_count))
        elif fmt == "kml":
            out_file = out_dir / "path.kml"
            feature_count = export_path_as_kml(out_file, path_result.path_lonlat)
            artifacts.append(OutputArtifact(format="kml", url=f"/outputs/{request_id}/path.kml", feature_count=feature_count))

    return PathPlanResponse(
        request_id=request_id,
        distance_m=float(path_result.distance_m),
        node_count=len(path_result.path_lonlat),
        artifacts=artifacts,
    )
