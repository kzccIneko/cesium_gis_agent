from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir
from time import perf_counter
from typing import Any, AsyncGenerator, Dict, List, Optional, Literal, cast
from uuid import uuid4
import asyncio
import hashlib
import json
import math
import re
import shutil
import numpy as np

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
from .services.terrain_classifier import (
    ONNX_PATH,
    ONNXTerrainClassifier,
    GeomorphonsClassifier,
    classify_terrain,
    get_terrain_class_legend,
)
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

# Agent 工具层的矢量产物目录（GeoJSON / CZML / KML / NPZ）
# ⚠ 以前这里漏了挂载：工具把产物写进 geoagent_artifacts/，而前端只能通过 /outputs 访问
#   cesiumjs_debug_outputs/，结果 Agent 的图层从来没被加载过 —— 这是"只有纯文字"的硬根因。
AGENT_ARTIFACT_ROOT = Path(gettempdir()) / "geoagent_artifacts"
AGENT_ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

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
app.mount("/artifacts", StaticFiles(directory=str(AGENT_ARTIFACT_ROOT)), name="artifacts")


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


def _download_srtm(west: float, south: float, east: float, north: float) -> str:
    """Download Copernicus GLO-30 DEM for the given bounding box.

    Uses dem-stitcher to fetch 30 m resolution tiles (AWS Open Data).
    Returns path to a GeoTIFF saved in a local cache directory.
    First call may take 10-30s to download; subsequent calls are instant (cached).
    """
    from dem_stitcher import stitch_dem
    import rasterio
    from rasterio.transform import from_bounds

    cache_dir = Path(gettempdir()) / "cesiumjs_dem_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(cache_dir / f"dem_{west:.3f}_{south:.3f}_{east:.3f}_{north:.3f}.tif")

    if Path(out_path).exists():
        return out_path

    X, p = stitch_dem(
        bounds=(west, south, east, north),
        dem_name="glo_30",
    )
    out_rows, out_cols = X.shape
    transform = from_bounds(west, south, east, north, out_cols, out_rows)
    with rasterio.open(
        out_path, "w", driver="GTiff",
        height=out_rows, width=out_cols,
        count=1, dtype=np.float64,
        crs="EPSG:4326",
        transform=transform,
        nodata=np.nan,
    ) as dst:
        dst.write(X, 1)
    return out_path


@app.post("/api/v1/analyze/classify", response_model=TerrainClassifyResponse)
def classify_terrain_api(req: TerrainClassifyRequest) -> TerrainClassifyResponse:
    """地貌语义分类接口。

    自动下载 SRTM DEM 作为真实地形数据源，然后使用 Geomorphons
    算法（Jasiewicz & Stepinski 2013）进行形态分类。
    """
    t0 = perf_counter()
    request_id = uuid4().hex
    out_dir = OUTPUT_ROOT / request_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Auto-download SRTM DEM when no local file is provided
    dem_path = req.dem_path
    mode = req.dem_decode_mode
    if not dem_path:
        try:
            dem_path = _download_srtm(
                req.bbox.west, req.bbox.south,
                req.bbox.east, req.bbox.north,
            )
            mode = "none"
        except Exception as srtm_err:
            print(f"[classify] SRTM download failed, fallback to synthetic: {srtm_err}")
            # fall through with dem_path=None → analyze_terrain uses synthetic

    try:
        terrain = analyze_terrain(
            west=req.bbox.west,
            south=req.bbox.south,
            east=req.bbox.east,
            north=req.bbox.north,
            resolution=req.resolution,
            dem_path=dem_path,
            dem_decode_mode=mode,
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

    # User-selectable classification method
    method = req.classification_method
    if method == "geomorphons":
        _geo_cls = GeomorphonsClassifier()
        class_ids, cost_adjustment, confidence = _geo_cls.classify(
            dem=terrain.dem_grid,
            slope_deg=terrain.slope_deg,
            curvature=terrain.curvature,
            cell_size_m=cell_size_m,
        )
    elif method == "onnx":
        if not ONNX_PATH.exists():
            raise HTTPException(status_code=503, detail="ONNX model not found")
        _ml_cls = ONNXTerrainClassifier()
        print(f"[classify] ONNX inference on {terrain.dem_grid.shape[0]}×{terrain.dem_grid.shape[1]} grid...")
        t1 = perf_counter()
        class_ids, cost_adjustment, confidence = _ml_cls.classify(terrain.dem_grid)
        print(f"[classify] ONNX done in {perf_counter()-t1:.1f}s")
    elif method == "rules":
        class_ids, cost_adjustment, confidence = classify_terrain(
            dem=terrain.dem_grid,
            slope_deg=terrain.slope_deg,
            curvature=terrain.curvature,
            cell_size_m=cell_size_m,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown method: {method}")

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
                    stride=1,
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


# ── Streaming classify (with progress events) ──────────────────────

def _emit(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"

def _calc_cell_size(req, resolution: int) -> float:
    lon_span = abs(float(req.bbox.east) - float(req.bbox.west))
    lat_span = abs(float(req.bbox.north) - float(req.bbox.south))
    mean_lat = math.radians((float(req.bbox.south) + float(req.bbox.north)) * 0.5)
    lon_m = lon_span * 111320.0 * max(1e-6, math.cos(mean_lat)) / max(1, resolution - 1)
    lat_m = lat_span * 110574.0 / max(1, resolution - 1)
    return (lon_m + lat_m) * 0.5

def _do_download_and_analyze(req: TerrainClassifyRequest):
    """Synchronous helper: download DEM + analyze_terrain, returns (terrain, cell_size_m)."""
    dem_path = req.dem_path
    mode = req.dem_decode_mode
    if not dem_path:
        dem_path = _download_srtm(
            req.bbox.west, req.bbox.south,
            req.bbox.east, req.bbox.north,
        )
        mode = "none"
    terrain = analyze_terrain(
        west=req.bbox.west, south=req.bbox.south,
        east=req.bbox.east, north=req.bbox.north,
        resolution=req.resolution,
        dem_path=dem_path, dem_decode_mode=mode,
        dem_decode_band=req.dem_decode_band,
        dem_decode_scale=req.dem_decode_scale,
        dem_decode_offset=req.dem_decode_offset,
        dem_decode_nodata=req.dem_decode_nodata,
    )
    cell_size_m = _calc_cell_size(req, req.resolution)
    return terrain, cell_size_m, dem_path

async def _classify_stream_events(req: TerrainClassifyRequest) -> AsyncGenerator[str, None]:
    request_id = uuid4().hex
    out_dir = OUTPUT_ROOT / request_id
    out_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_event_loop()

    # Phase 1: DEM download
    yield _emit({"type": "phase", "phase": "dem", "label": "DEM 下载中…"})
    try:
        terrain, cell_size_m, dem_path = await loop.run_in_executor(
            None, _do_download_and_analyze, req
        )
    except Exception as exc:
        yield _emit({"type": "error", "message": str(exc)})
        return

    # Phase 2: ready
    grid_h, grid_w = terrain.dem_grid.shape
    yield _emit({"type": "phase", "phase": "classify",
                 "label": f"分类中 ({grid_h}×{grid_w})…",
                 "total_patches": grid_h * grid_w})

    # Phase 3: classify
    method = req.classification_method
    try:
        if method == "geomorphons":
            yield _emit({"type": "progress", "current": 0, "total": 1, "phase": "geomorphons"})
            _geo_cls = GeomorphonsClassifier()
            class_ids, cost_adjustment, confidence = _geo_cls.classify(
                dem=terrain.dem_grid, slope_deg=terrain.slope_deg,
                curvature=terrain.curvature, cell_size_m=cell_size_m,
            )
            yield _emit({"type": "progress", "current": 1, "total": 1, "phase": "geomorphons"})

        elif method == "onnx":
            if not ONNX_PATH.exists():
                yield _emit({"type": "error", "message": "ONNX model not found"})
                return
            _ml_cls = ONNXTerrainClassifier()
            progress_queue: asyncio.Queue = asyncio.Queue()

            def _progress_cb(current, total):
                loop.call_soon_threadsafe(
                    progress_queue.put_nowait,
                    ("progress", current, total),
                )

            def _run_onnx():
                return _ml_cls.classify(
                    terrain.dem_grid,
                    progress_callback=_progress_cb,
                )

            # Signal start
            yield _emit({"type": "progress", "current": 0,
                         "total": grid_h * grid_w, "phase": "onnx"})

            # Run in thread pool, collect progress events concurrently
            onnx_fut = loop.run_in_executor(None, _run_onnx)

            # Drain progress queue while waiting
            done = False
            while not done:
                try:
                    msg = await asyncio.wait_for(
                        asyncio.ensure_future(progress_queue.get()),
                        timeout=0.5,
                    )
                    if msg[0] == "progress":
                        yield _emit({
                            "type": "progress",
                            "current": msg[1],
                            "total": msg[2],
                            "phase": "onnx",
                        })
                except asyncio.TimeoutError:
                    pass
                # Check if ONNX done
                if onnx_fut.done():
                    done = True

            class_ids, cost_adjustment, confidence = await onnx_fut

        elif method == "rules":
            yield _emit({"type": "progress", "current": 0, "total": 1, "phase": "rules"})
            class_ids, cost_adjustment, confidence = classify_terrain(
                dem=terrain.dem_grid, slope_deg=terrain.slope_deg,
                curvature=terrain.curvature, cell_size_m=cell_size_m,
            )
            yield _emit({"type": "progress", "current": 1, "total": 1, "phase": "rules"})
        else:
            yield _emit({"type": "error", "message": f"Unknown method: {method}"})
            return
    except Exception as exc:
        yield _emit({"type": "error", "message": str(exc)})
        return

    # Phase 4: export
    yield _emit({"type": "phase", "phase": "export", "label": "导出 GeoJSON…"})
    legend = get_terrain_class_legend()
    url_prefix = f"/outputs/{request_id}"
    artifacts = []
    for fmt in req.output_formats:
        if fmt == "geojson":
            out_file = out_dir / "terrain_classification.geojson"
            feature_count = None
            if not out_file.exists():
                feature_count = export_grid_classification_as_geojson(
                    out_file, terrain.lon_grid, terrain.lat_grid,
                    class_ids, confidence, legend, stride=1,
                )
            artifacts.append({
                "format": "geojson",
                "url": f"{url_prefix}/terrain_classification.geojson",
                "feature_count": feature_count,
            })
        elif fmt == "czml":
            out_file = out_dir / "terrain_classification.czml"
            if not out_file.exists():
                export_grid_as_czml(out_file, terrain.lon_grid, terrain.lat_grid,
                                    class_ids.astype(np.float64), "terrain_classification")
            artifacts.append({"format": "czml", "url": f"{url_prefix}/terrain_classification.czml"})
        elif fmt == "kml":
            out_file = out_dir / "terrain_classification.kml"
            if not out_file.exists():
                export_grid_as_kml(out_file, terrain.lon_grid, terrain.lat_grid,
                                   class_ids.astype(np.float64), "terrain_classification")
            artifacts.append({"format": "kml", "url": f"{url_prefix}/terrain_classification.kml"})

    yield _emit({
        "type": "result",
        "request_id": request_id,
        "resolution": req.resolution,
        "dem_source": terrain.dem_source,
        "artifacts": artifacts,
        "legend": legend,
    })


@app.post("/api/v1/analyze/classify/stream")
async def classify_terrain_api_stream(req: TerrainClassifyRequest):
    return StreamingResponse(
        _classify_stream_events(req),
        media_type="application/x-ndjson",
    )


# ─────────────────────────────────────────────────────────────────────────
# Agent 对话接口（Week 5 · W5-6）
#
# 这是「网页上能用 Agent」的最后一环：前端把一句中文发过来，
# 后端跑完整的 计划 → 执行 → 反思 → 总结，把最终回答和调用链路一起回传。
#
# 注意：这条路径不经过 MCP。MCP 是给外部客户端（Claude Desktop 等）用的，
# 网页走 HTTP 直接打到编排层。
# ─────────────────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field  # noqa: E402
import threading  # noqa: E402

_AGENT_LLM = None
_AGENT_LLM_LOCK = threading.Lock()


def _get_agent_llm():
    """惰性加载并全局复用 LLM 客户端。

    模型 2.55 GB，加载一次约 10 秒且常驻显存。若每个请求都新建客户端，
    会在显存里堆出多份拷贝 —— 本机 RTX 2060 只有 6 GB，很快就 OOM。
    """
    global _AGENT_LLM
    if _AGENT_LLM is not None:
        return _AGENT_LLM
    with _AGENT_LLM_LOCK:
        if _AGENT_LLM is None:
            from .agent.llm import build_client

            _AGENT_LLM = build_client()
    return _AGENT_LLM


class DemGridPayload(BaseModel):
    """前端从 Cesium 自带地形（Cesium World Terrain）采样出的高程网格。

    用户没有上传自己的 DEM 时用它 —— 拿真实地表算，而不是回退到合成地形。
    heights 的行序是从北到南（第 0 行 = 最北边），无效点用 null。
    """

    bbox: List[float]
    heights: List[List[Optional[float]]]


class ViewContextPayload(BaseModel):
    """前端上报的「用户此刻在看哪」。

    单独于 bbox 传：bbox 是"分析范围"（可能被限制），
    view_context 是"视图事实"（如实上报，哪怕它大到整个地球）。
    没有它，模型答不出「这里是什么地方」，也理解不了「跳转到海南省」。
    """

    bbox: Optional[List[float]] = None
    center: Optional[List[float]] = None
    area_km2: Optional[float] = None
    is_global: bool = False


class AgentChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    bbox: Optional[List[float]] = None
    session_id: str = "web"
    dem_grid: Optional[DemGridPayload] = None
    view_context: Optional[ViewContextPayload] = None


class AgentChatStep(BaseModel):
    tool: str
    intent: str = ""
    success: bool = True
    duration_ms: float = 0.0
    # 该步的结构化结果（统计分级 / 分类构成 / 路径指标 / 产物 URL）—— 前端据此渲染表格与图表
    data: Dict[str, Any] = {}
    # 单独抽出矢量产物，方便前端直接叠加到三维地球
    artifact: Dict[str, Any] = {}


class AgentChatResponse(BaseModel):
    answer: str = ""
    refused: bool = False
    understanding: str = ""
    steps: List[AgentChatStep] = []
    bbox: Optional[List[float]] = None
    artifacts: List[Dict[str, Any]] = []
    # 本次分析用的地形来源：cesium（前端采样）/ real_dem（用户自带或下载）/ synthetic（兜底）
    dem_source: str = ""
    # 规划器判定的意图，便于前端区分"在分析"还是"在聊天/做操作"
    intent: str = ""
    # 需要前端执行的系统动作（目前只有 flyTo 跳转视角）
    actions: List[Dict[str, Any]] = []
    # —— 记忆相关 ——
    # 指代消解说明：把「这个地方」理解成了什么。必须回传，用户才能判断系统有没有理解错
    memory_notes: List[str] = []
    # 补全后的句子（原句里若有指代词，这里是被替换过的版本）
    resolved_query: str = ""
    # 本会话已记住的轮数，前端据此显示记忆状态
    session_turns: int = 0
    # 后端判定"这一步必须要有真实地形，但前端这次没给" → 前端补采后重发一次
    need_terrain: bool = False
    elapsed_ms: float = 0.0
    trace: List[str] = []
    error: str = ""


@app.post("/api/v1/agent/chat", response_model=AgentChatResponse)
def agent_chat(req: AgentChatRequest) -> AgentChatResponse:
    """用自然语言问一个地理空间分析问题，返回答案与执行链路。"""
    t0 = perf_counter()

    def _fail(msg: str) -> AgentChatResponse:
        return AgentChatResponse(
            answer=f"分析失败：{msg}",
            elapsed_ms=(perf_counter() - t0) * 1000,
            error=msg,
        )

    # 记忆层的导入放在函数内：与上面 LLM 的加载策略一致，
    # 避免后端启动时就去建库连接（首次请求才初始化）。
    from .agent.memory import (
        build_focus_text,
        get_memory_store,
        infer_place_name,
        resolve_coreference,
    )

    # —— 记忆：读 ——
    # 取本会话的空间焦点（上一轮用的 bbox / 地名 / 工具）与最近几轮对话。
    # 指代消解在这里做：规则只负责把「这个地方」补全成显式坐标，
    # 意图判断仍然交给模型（见 memory/__init__.py 的设计说明）。
    store = get_memory_store()
    focus = store.get_focus(req.session_id) if store else {}
    view_ctx = req.view_context.model_dump() if req.view_context else None
    resolved_query, coref_notes = resolve_coreference(req.query, focus, view_ctx)
    history = store.recent_turns(req.session_id) if store else []
    focus_text = build_focus_text(focus, view_ctx) if focus else ""

    try:
        from .agent import run_agent
        from .agent.chitchat import try_chitchat

        # 寒暄 / 自我介绍 / 能力询问走规则直答，不进 Agent 图。
        # 以前这类输入也要走一遍 LLM 规划（约 19 秒）才被拒答，既慢又答非所问。
        # 注意：这里用**原句**判断，避免指代替换把寒暄改得不像寒暄。
        quick = try_chitchat(req.query)
        if quick:
            if store:
                store.append_turn(req.session_id, "user", req.query, intent="chat")
                store.append_turn(req.session_id, "assistant", quick, intent="chat")
            return AgentChatResponse(
                answer=quick,
                bbox=req.bbox,
                intent="chat",
                memory_notes=coref_notes,
                resolved_query=resolved_query,
                session_turns=len(history) + 2,
                elapsed_ms=(perf_counter() - t0) * 1000,
                trace=["命中寒暄/元问题，规则直答（未调用大模型）"],
            )

        llm = _get_agent_llm()
    except Exception as exc:
        # 模型加载失败不应让整个后端挂掉，前端仍可用其他分析接口
        return _fail(f"无法加载本地大模型（{type(exc).__name__}）：{exc}")

    # 用户没有自带 DEM 时，用前端从 Cesium 地形采样来的高程网格 ——
    # 这样工具算的是真实地表，而不是合成地形那种"看着有起伏、其实与实地无关"的数字。
    session_dem_path: Optional[str] = None
    dem_note = ""
    if req.dem_grid:
        try:
            from .services.grid_to_dem import write_heights_as_geotiff

            info = write_heights_as_geotiff(req.dem_grid.bbox, req.dem_grid.heights)
            session_dem_path = info["path"]
            dem_note = (
                f"已接入 Cesium 地形采样（{info['shape'][0]}×{info['shape'][1]} 网格，"
                f"有效点 {info['valid_ratio']:.0%}）"
            )
        except Exception as exc:  # noqa: BLE001
            dem_note = (
                f"地形网格不可用（{type(exc).__name__}: {exc}），"
                f"本次将使用默认数据源"
            )

    try:
        state = run_agent(
            query=resolved_query,
            bbox=req.bbox,
            llm=llm,
            session_id=req.session_id,
            session_dem_path=session_dem_path,
            view_context=view_ctx,
            history=history,
            focus_context=focus_text,
        )
    except Exception as exc:
        return _fail(f"{type(exc).__name__}：{exc}")

    # 优先用真实调用记录（含耗时与成败），没有则退回计划步骤
    records = state.get("tool_calls") or []
    steps: List[AgentChatStep] = []
    if records:
        for r in records:
            view = r.get("result") or {}
            art = view.get("artifact") or {}
            steps.append(
                AgentChatStep(
                    tool=str(r.get("tool") or ""),
                    intent=str(r.get("summary") or ""),
                    success=bool(r.get("success", True)),
                    duration_ms=float(r.get("duration_ms") or 0.0),
                    data=view,
                    artifact=art if isinstance(art, dict) else {},
                )
            )
    else:
        for s in state.get("plan") or []:
            steps.append(
                AgentChatStep(
                    tool=str(s.get("tool") or ""),
                    intent=str(s.get("intent") or ""),
                    success=s.get("status") != "failed",
                )
            )

    # 收集可加载的矢量产物（GeoJSON / CZML / KML），供前端叠加到三维地球。
    # 以前这里遍历的是 r.get("artifacts")（复数），而工具返回的是 artifact（单数），
    # 且要求 a.get("url")，而工具当时只返回本地 path —— 三个条件都对不上，
    # 于是这个数组**恒为空**，矢量图层从来没有到达过前端。
    from .agent.result_view import collect_artifacts

    artifacts: List[Dict[str, Any]] = collect_artifacts(
        [s.data for s in steps if s.data]
    )

    # 把这次用的地形来源也带回前端，界面上要如实标出"这份数据是哪来的"
    dem_source = ""
    for s in steps:
        ds_name = (s.data or {}).get("dem_source")
        if ds_name:
            dem_source = str(ds_name)
            break

    trace_out = list(state.get("trace") or [])[-20:]
    if dem_note:
        trace_out = [dem_note] + trace_out
    if coref_notes:
        # 指代消解结果放最前面 —— 用户第一眼就该看到"系统把我的『这个地方』理解成了哪儿"
        trace_out = [f"记忆：{n}" for n in coref_notes] + trace_out

    intent_out = str(state.get("intent") or "")
    actions_out = list(state.get("actions") or [])
    answer_out = str(state.get("final_answer") or "")
    bbox_out = state.get("bbox")

    # 跳转类动作里带的坐标也要记进空间焦点，而且**优先级高于请求里的 bbox**。
    # 请求里那个 bbox 是"当前视野"（用户原来在看哪），不是他要去的目标 ——
    # 实测踩过：第 3 轮「跳转到阿尔卑斯山」执行成功，但焦点里存的是视野坐标，
    # 于是第 4 轮出现「阿尔卑斯山一带（北纬 18.5°、东经 109°）」这种名字配海南坐标的错配。
    for _a in actions_out:
        _ab = (_a or {}).get("bbox")
        if _ab and len(_ab) >= 4:
            bbox_out = list(_ab)[:4]
            break

    # —— 判断要不要让前端补采地形 ——
    # 前端为省时间做了规则预判（跳转/常识类不采样，见 AgentPanel.js needsTerrain）。
    # 万一预判错了（该采样却没采），后端这边会退化成合成地形，算出来的数字没有意义。
    # 所以这里明确告诉前端"请补一份地形，再发一次"。
    need_terrain = bool(
        intent_out == "analysis"
        and not session_dem_path
        and bbox_out
        and dem_source in ("", "synthetic")
    )

    # —— 记忆：写 ——
    # 写回顺序讲究：先 user 后 assistant，空间焦点最后写（它要用到本轮的结果）。
    if store:
        try:
            place = infer_place_name(resolved_query, actions_out)
            store.append_turn(
                req.session_id, "user", req.query, intent=intent_out or None, bbox=bbox_out
            )
            store.append_turn(
                req.session_id, "assistant", answer_out, intent=intent_out or None
            )
            store.update_focus(
                req.session_id,
                last_bbox=bbox_out,
                last_place=place,
                last_intent=intent_out or None,
                last_tool=(steps[-1].tool if steps else None),
                last_query=req.query,
                last_answer=answer_out[:200] if answer_out else None,
            )
            # 只有真的分析了某个区域才进长期记忆 —— 跳转/闲聊不该污染"常用区域"
            if intent_out == "analysis" and bbox_out and place:
                store.remember_region(place, bbox_out)
            store.trim_turns(req.session_id)
        except Exception as exc:  # noqa: BLE001 —— 记忆写失败不该影响这次回答
            trace_out.append(f"记忆写入失败（{type(exc).__name__}）：{exc}")

    return AgentChatResponse(
        answer=answer_out,
        refused=bool(state.get("refused", False)),
        understanding=str(state.get("understanding") or ""),
        steps=steps,
        bbox=bbox_out,
        artifacts=artifacts,
        dem_source=dem_source,
        intent=intent_out,
        actions=actions_out,
        memory_notes=coref_notes,
        resolved_query=resolved_query if coref_notes else "",
        session_turns=len(history) + 2 if store else 0,
        need_terrain=need_terrain,
        elapsed_ms=(perf_counter() - t0) * 1000,
        trace=trace_out,
    )


@app.get("/api/v1/agent/health")
def agent_health():
    """Agent 是否可用（前端首次进入时探一次，避免用户干等）。"""
    try:
        llm = _get_agent_llm()
        return {"ready": True, "backend": type(llm).__name__}
    except Exception as exc:
        return {"ready": False, "backend": "", "error": str(exc)}
