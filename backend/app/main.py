from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir
from time import perf_counter
from typing import Dict, List
from uuid import uuid4
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
)
from .services.analysis_service import analyze_terrain, get_dem_metadata, plan_path
from .services.export_service import (
    export_grid_as_czml,
    export_grid_as_geojson,
    export_grid_as_kml,
    export_path_as_czml,
    export_path_as_geojson,
    export_path_as_kml,
)


APP_ROOT = Path(__file__).resolve().parent
OUTPUT_ROOT = Path(gettempdir()) / "cesiumjs_debug_outputs"
OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="DEM Cesium Analysis API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_ROOT)), name="outputs")


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
    except Exception:
        return total
    return total


def _clear_output_cache() -> Dict[str, int]:
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


def _stats(values: np.ndarray) -> AnalysisStats:
    return AnalysisStats(min=float(np.min(values)), max=float(np.max(values)), mean=float(np.mean(values)))


@app.get("/api/v1/formats", response_model=FormatOptionsResponse)
def get_formats() -> FormatOptionsResponse:
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
    try:
        return get_dem_metadata(dem_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/cache/outputs/clear")
def clear_outputs_cache():
    return _clear_output_cache()


@app.post("/api/v1/analyze/terrain", response_model=TerrainAnalysisResponse)
def analyze_terrain_api(req: TerrainAnalysisRequest) -> TerrainAnalysisResponse:
    t0 = perf_counter()
    request_id = uuid4().hex
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

    out_dir = OUTPUT_ROOT / request_id
    out_dir.mkdir(parents=True, exist_ok=True)

    artifacts: List[OutputArtifact] = []
    for fmt in req.output_formats:
        for _, selected_grid, selected_name in selected_items:
            if fmt == "geojson":
                out_file = out_dir / f"{selected_name}.geojson"
                feature_count = export_grid_as_geojson(
                    out_file,
                    terrain.lon_grid,
                    terrain.lat_grid,
                    selected_grid,
                    selected_name,
                )
                artifacts.append(OutputArtifact(format="geojson", url=f"/outputs/{request_id}/{selected_name}.geojson", feature_count=feature_count))
            elif fmt == "czml":
                out_file = out_dir / f"{selected_name}.czml"
                feature_count = export_grid_as_czml(
                    out_file,
                    terrain.lon_grid,
                    terrain.lat_grid,
                    selected_grid,
                    selected_name,
                )
                artifacts.append(OutputArtifact(format="czml", url=f"/outputs/{request_id}/{selected_name}.czml", feature_count=feature_count))
            elif fmt == "kml":
                out_file = out_dir / f"{selected_name}.kml"
                feature_count = export_grid_as_kml(
                    out_file,
                    terrain.lon_grid,
                    terrain.lat_grid,
                    selected_grid,
                    selected_name,
                )
                artifacts.append(OutputArtifact(format="kml", url=f"/outputs/{request_id}/{selected_name}.kml", feature_count=feature_count))

    stats: Dict[str, AnalysisStats] = {
        "slope": _stats(terrain.slope_deg),
        "aspect": _stats(terrain.aspect_deg),
        "curvature": _stats(terrain.curvature),
        "cost": _stats(terrain.cost),
        "duration_ms": AnalysisStats(min=0.0, max=0.0, mean=(perf_counter() - t0) * 1000.0),
    }

    return TerrainAnalysisResponse(
        request_id=request_id,
        analysis_type=req.analysis_type,
        resolution=req.resolution,
        dem_source=terrain.dem_source,
        artifacts=artifacts,
        stats=stats,
    )


@app.post("/api/v1/analyze/path", response_model=PathPlanResponse)
def analyze_path_api(req: PathPlanRequest) -> PathPlanResponse:
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
