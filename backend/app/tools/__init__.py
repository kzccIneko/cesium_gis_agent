"""GeoAgent 工具层（Week 1 交付）。

把 backend/app/services 中的地理空间分析能力封装为大模型可调用的标准工具：

    get_dem_metadata        读取 DEM 元信息
    download_srtm           下载真实 DEM（Copernicus GLO-30）
    compute_slope           坡度
    compute_aspect          坡向
    compute_curvature       曲率
    compute_cost_surface    通行代价栅格（支持方向性代价）
    plan_route              越野路径规划（Dijkstra 8 邻域）
    classify_terrain_rules      规则地貌分类
    classify_geomorphons        Geomorphons 地貌分类
    classify_terrain_onnx       ONNX CNN 地貌分类
    zonal_statistics        分级统计与可通行性结论

三条设计约束（决定了 Week 2 编排层能否跑通）：
1. 输入可序列化 —— bbox 用 [w,s,e,n] 数组，不传对象或 numpy 数组
2. 输出结构化 dict —— 数值带单位、带取值范围、带 warnings 告警
3. 错误不抛异常 —— 统一返回 ToolResult，error_type 供 reflector 决策重试策略

典型用法：
    from app.tools import dispatch, get_openai_tools

    tools = get_openai_tools()                      # 传给 LLM
    result = dispatch("compute_slope", {"bbox": [103.5, 30.2, 104.5, 31.0]})
    print(result["data"]["statistics"]["mean"])
"""

from .cache import TerrainResultCache, terrain_cache
from .classify_tools import (
    classify_geomorphons,
    classify_terrain_onnx,
    classify_terrain_rules,
)
from .dem_tools import download_srtm, get_dem_metadata
from .errors import ToolErrorType, ToolException, ToolResult, fail, ok
from .path_tools import plan_route
from .registry import (
    TOOL_FUNCTIONS,
    TOOL_REGISTRY,
    call_tool,
    dispatch,
    get_mcp_tools,
    get_openai_tools,
    list_tools,
)
from .stats_tools import zonal_statistics
from .terrain_tools import (
    compute_aspect,
    compute_cost_surface,
    compute_curvature,
    compute_slope,
)

__all__ = [
    # 工具函数
    "get_dem_metadata",
    "download_srtm",
    "compute_slope",
    "compute_aspect",
    "compute_curvature",
    "compute_cost_surface",
    "plan_route",
    "classify_terrain_rules",
    "classify_geomorphons",
    "classify_terrain_onnx",
    "zonal_statistics",
    # 注册表与调度
    "TOOL_REGISTRY",
    "TOOL_FUNCTIONS",
    "list_tools",
    "get_openai_tools",
    "get_mcp_tools",
    "call_tool",
    "dispatch",
    # 错误与结果
    "ToolResult",
    "ToolErrorType",
    "ToolException",
    "ok",
    "fail",
    # 缓存
    "terrain_cache",
    "TerrainResultCache",
]
