"""工具注册表与统一调度入口。

对外提供：
    TOOL_REGISTRY   name -> {fn, schema}
    list_tools()    列出全部工具（名称 + 简述）
    get_openai_tools()  OpenAI Function Calling / Chat Completions tools 格式
    get_mcp_tools()     MCP 协议格式（Week 3 的 MCP Server 直接使用）
    call_tool()         按名称调用，自动过滤非法参数
    dispatch()          从参数字典调用（Function Calling 的标准入口）
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional

from .classify_tools import (
    classify_geomorphons,
    classify_terrain_onnx,
    classify_terrain_rules,
)
from .dem_tools import download_srtm, get_dem_metadata
from .errors import ToolErrorType, fail
from .path_tools import plan_route
from .schemas import TOOL_SCHEMAS
from .stats_tools import zonal_statistics
from .table_tools import query_tabular
from .terrain_tools import (
    compute_aspect,
    compute_cost_surface,
    compute_curvature,
    compute_slope,
)

# 工具名 → 实现函数
TOOL_FUNCTIONS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "get_dem_metadata": get_dem_metadata,
    "download_srtm": download_srtm,
    "compute_slope": compute_slope,
    "compute_aspect": compute_aspect,
    "compute_curvature": compute_curvature,
    "compute_cost_surface": compute_cost_surface,
    "plan_route": plan_route,
    "classify_terrain_rules": classify_terrain_rules,
    "classify_geomorphons": classify_geomorphons,
    "classify_terrain_onnx": classify_terrain_onnx,
    "zonal_statistics": zonal_statistics,
    "query_tabular": query_tabular,
}

# 完整注册表：函数名 → {fn, schema}
TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    name: {"fn": fn, "schema": TOOL_SCHEMAS[name]}
    for name, fn in TOOL_FUNCTIONS.items()
    if name in TOOL_SCHEMAS
}


def list_tools() -> List[Dict[str, str]]:
    """列出所有工具（名称 + 一句话说明）。"""
    out = []
    for name, item in TOOL_REGISTRY.items():
        desc = item["schema"]["function"]["description"]
        out.append({"name": name, "description": desc.split("。")[0] + "。"})
    return out


def get_openai_tools(names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """OpenAI Function Calling 格式的工具定义列表。

    Args:
        names: 只导出指定工具；None 表示全部
    """
    if names is None:
        return [item["schema"] for item in TOOL_REGISTRY.values()]
    return [TOOL_REGISTRY[n]["schema"] for n in names if n in TOOL_REGISTRY]


def get_mcp_tools(names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """MCP（Model Context Protocol）格式的工具定义列表。

    MCP 的 inputSchema 与 JSON Schema 兼容，可直接从 OpenAI 格式转换，
    Week 3 的 MCP Server 无需重复定义 schema。
    """
    items = (
        TOOL_REGISTRY.values()
        if names is None
        else [TOOL_REGISTRY[n] for n in names if n in TOOL_REGISTRY]
    )
    out = []
    for item in items:
        fn_schema = item["schema"]["function"]
        out.append({
            "name": fn_schema["name"],
            "description": fn_schema["description"],
            "inputSchema": fn_schema["parameters"],
        })
    return out


def call_tool(name: str, **kwargs: Any) -> Dict[str, Any]:
    """按名称调用工具，自动过滤函数签名不接受的参数。

    大模型经常多传参数（如把 bbox 写成 bounds），
    这里做宽容处理：丢弃多余参数而不是直接报错。
    """
    entry = TOOL_REGISTRY.get(name)
    if entry is None:
        return fail(
            name,
            f"未知工具 {name!r}。可用工具：{list(TOOL_REGISTRY)}",
            ToolErrorType.OUT_OF_CAPABILITY,
        ).to_dict()

    fn = entry["fn"]
    sig = inspect.signature(fn)
    dropped = [k for k in kwargs if k not in sig.parameters]
    valid = {k: v for k, v in kwargs.items() if k in sig.parameters}

    result = fn(**valid)
    if dropped and isinstance(result, dict) and result.get("success"):
        # 把被忽略的参数告知调用方，便于修正
        result.setdefault("data", {}).setdefault(
            "ignored_params", dropped
        )
    return result


def dispatch(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """从参数字典调用工具 —— Function Calling 的标准入口。

    Args:
        name: 工具名
        arguments: 模型生成的参数字典（可为空）

    Returns:
        工具的 ToolResult.to_dict()
    """
    return call_tool(name, **(arguments or {}))
