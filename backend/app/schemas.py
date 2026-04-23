from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


OutputFormat = Literal["geojson", "czml", "kml"]
AnalysisType = Literal["slope", "aspect", "curvature", "cost", "comprehensive"]


class BBox(BaseModel):
    west: float = Field(..., ge=-180.0, le=180.0)
    south: float = Field(..., ge=-90.0, le=90.0)
    east: float = Field(..., ge=-180.0, le=180.0)
    north: float = Field(..., ge=-90.0, le=90.0)


class TerrainAnalysisRequest(BaseModel):
    bbox: BBox
    resolution: int = Field(default=50, ge=8, le=1024) #只接收每边网格数
    analysis_type: AnalysisType = "comprehensive"
    output_formats: List[OutputFormat] = Field(default_factory=lambda: ["geojson"])
    dem_path: Optional[str] = None
    dem_decode_mode: Literal["none", "single_band", "terrain_rgb"] = "none"
    dem_decode_band: int = Field(default=1, ge=1, le=16)
    dem_decode_scale: float = 1.0
    dem_decode_offset: float = 0.0
    dem_decode_nodata: Optional[float] = None


class PathPlanRequest(BaseModel):
    bbox: BBox
    start_point: List[float] = Field(..., min_length=2, max_length=2)
    end_point: List[float] = Field(..., min_length=2, max_length=2)
    resolution: int = Field(default=80, ge=16, le=512)
    output_formats: List[OutputFormat] = Field(default_factory=lambda: ["geojson", "czml"])
    dem_path: Optional[str] = None
    dem_decode_mode: Literal["none", "single_band", "terrain_rgb"] = "none"
    dem_decode_band: int = Field(default=1, ge=1, le=16)
    dem_decode_scale: float = 1.0
    dem_decode_offset: float = 0.0
    dem_decode_nodata: Optional[float] = None


class OutputArtifact(BaseModel):
    format: OutputFormat
    url: str
    feature_count: Optional[int] = None


class AnalysisStats(BaseModel):
    min: float
    max: float
    mean: float


class TerrainAnalysisResponse(BaseModel):
    request_id: str
    analysis_type: AnalysisType
    resolution: int
    dem_source: Literal["synthetic", "real_dem"] = "synthetic"
    artifacts: List[OutputArtifact]
    stats: Dict[str, AnalysisStats]


class PathPlanResponse(BaseModel):
    request_id: str
    distance_m: float
    node_count: int
    artifacts: List[OutputArtifact]


class FormatOption(BaseModel):
    value: OutputFormat
    label: str
    cesium_loader: str


class FormatOptionsResponse(BaseModel):
    terrain: List[FormatOption]
    path: List[FormatOption]
