from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


OutputFormat = Literal["geojson", "czml", "kml"]
AnalysisType = Literal["slope", "aspect", "curvature", "cost", "comprehensive"]


class BBox(BaseModel):
    """经纬度包围盒（WGS84）。"""
    west: float = Field(..., ge=-180.0, le=180.0)
    south: float = Field(..., ge=-90.0, le=90.0)
    east: float = Field(..., ge=-180.0, le=180.0)
    north: float = Field(..., ge=-90.0, le=90.0)


class TerrainAnalysisRequest(BaseModel):
    """地形分析请求参数。"""
    bbox: BBox
    # 每边网格点数量（分辨率越高，计算与导出越重）
    resolution: int = Field(default=50, ge=8, le=1024)
    analysis_type: AnalysisType = "comprehensive"
    output_formats: List[OutputFormat] = Field(default_factory=lambda: ["geojson"])
    tile_set_id: Optional[str] = None
    tile_key: Optional[str] = None
    dem_path: Optional[str] = None
    dem_decode_mode: Literal["none", "single_band", "terrain_rgb"] = "none"
    dem_decode_band: int = Field(default=1, ge=1, le=16)
    dem_decode_scale: float = 1.0
    dem_decode_offset: float = 0.0
    dem_decode_nodata: Optional[float] = None
    # 可选：用于方向性代价分析（起点->终点）
    start_point: Optional[List[float]] = Field(default=None, min_length=2, max_length=2)
    end_point: Optional[List[float]] = Field(default=None, min_length=2, max_length=2)


class PathPlanRequest(BaseModel):
    """路径规划请求参数。"""
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
    """导出产物信息。"""
    format: OutputFormat
    url: str
    feature_count: Optional[int] = None


class AnalysisStats(BaseModel):
    """统计信息（最小值/最大值/均值）。"""
    min: float
    max: float
    mean: float


class TerrainAnalysisResponse(BaseModel):
    """地形分析响应。"""
    request_id: str
    analysis_type: AnalysisType
    resolution: int
    dem_source: Literal["synthetic", "real_dem"] = "synthetic"
    cache_hit: bool = False
    artifacts: List[OutputArtifact]
    stats: Dict[str, AnalysisStats]


class PathPlanResponse(BaseModel):
    """路径规划响应。"""
    request_id: str
    distance_m: float
    node_count: int
    artifacts: List[OutputArtifact]


class FormatOption(BaseModel):
    """格式选项（用于前端展示）。"""
    value: OutputFormat
    label: str
    cesium_loader: str


class FormatOptionsResponse(BaseModel):
    """地形/路径可导出格式集合。"""
    terrain: List[FormatOption]
    path: List[FormatOption]
