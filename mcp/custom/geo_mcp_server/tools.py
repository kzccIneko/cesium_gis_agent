"""工具适配层 —— 把 backend/app/tools/ 的 11 个工具包装成 MCP 工具。

为什么需要这一层，而不是直接把工具函数丢给 FastMCP：

1. **schema 单一来源**
   工具的参数定义已经写在 `backend/app/tools/schemas.py`，并由
   `get_mcp_tools()` 导出成 MCP 的 inputSchema 格式。这里从 schema
   反推出 Python 函数签名交给 FastMCP，而不是重新手写一遍类型注解，
   避免「后端改了参数、MCP 这边忘了改」这类必然发生的漂移。

2. **输出形态适配**
   工具返回的是结构化 dict（给 Agent 的 reflector 做规则校验用），
   但 MCP 客户端里的模型需要的是能直接读懂的文本。这里负责把
   dict 渲染成「产物路径 + 关键统计 + 告警 + 完整 JSON」的层次化文本，
   并对超长结果做截断 —— 栅格类工具很容易产出上千行 JSON，
   不截断会直接撑爆客户端上下文。

3. **失败即信息**
   工具层保证「绝不抛异常」，失败时返回带 error_type 的结构化结果。
   这里把失败渲染成「错误类型 + 原因 + 是否可重试 + 修正建议」，
   让客户端模型能据此自我修正，而不是看到一句 "Internal error"。
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger("geo_mcp")

# 单个工具返回文本的长度上限。超出部分截断并标注，避免撑爆客户端上下文。
MAX_OUTPUT_CHARS = int(os.getenv("GEO_MCP_MAX_CHARS", "12000"))

# mcp/custom/geo_mcp_server/tools.py
#   parents[0] = geo_mcp_server
#   parents[1] = custom
#   parents[2] = mcp
#   parents[3] = 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"


def bootstrap_backend() -> Path:
    """把 backend/ 加入 sys.path，使 `import app.tools` 可用。

    必须在导入任何 backend 模块之前调用。MCP 客户端是以子进程方式
    启动本文件的，工作目录不可控，因此这里用文件位置推导绝对路径，
    不依赖 cwd。
    """
    target = str(BACKEND_ROOT)
    if not BACKEND_ROOT.is_dir():
        raise RuntimeError(
            f"未找到 backend 目录：{BACKEND_ROOT}。"
            "请确认 geo_mcp_server 位于 <项目根>/mcp/custom/ 下。"
        )
    if target not in sys.path:
        sys.path.insert(0, target)
    return BACKEND_ROOT


bootstrap_backend()

from app.tools import (  # noqa: E402  （须在 bootstrap 之后）
    call_tool,
    get_mcp_tools,
)

# ---------------------------------------------------------------------------
# JSON Schema → Python 类型注解
# ---------------------------------------------------------------------------

_SCALAR_MAP: Dict[str, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
}


def _annotation(spec: Dict[str, Any]) -> Any:
    """把一个 JSON Schema 属性定义转换成 Python 类型注解。

    enum 会转成 Literal，这样客户端模型在 schema 里就能看到可选值，
    而不是靠描述文本去猜。
    """
    if not isinstance(spec, dict):
        return Any

    enum = spec.get("enum")
    if enum:
        try:
            return Literal[tuple(enum)]  # type: ignore[valid-type]
        except Exception:
            return str

    jtype = spec.get("type")
    if isinstance(jtype, list):  # ["string", "null"] 这类联合类型
        jtype = next((t for t in jtype if t != "null"), None)

    if jtype == "array":
        items = spec.get("items") or {}
        item_type = items.get("type") if isinstance(items, dict) else None
        if item_type == "number":
            return List[float]
        if item_type == "integer":
            return List[int]
        if item_type == "string":
            return List[str]
        return List[Any]

    if jtype == "object":
        return Dict[str, Any]

    return _SCALAR_MAP.get(jtype, Any)


def build_signature(parameters: Dict[str, Any]) -> inspect.Signature:
    """从 inputSchema 反推出 Python 函数签名。

    全部使用 KEYWORD_ONLY 参数：这样「无默认值（必填）」和
    「有默认值（选填）」可以任意交错，不受 Python 位置参数的
    「默认值之后不能再有无默认值参数」限制。
    """
    properties: Dict[str, Any] = parameters.get("properties") or {}
    required = set(parameters.get("required") or [])

    params: List[inspect.Parameter] = []
    for name, spec in properties.items():
        ann = _annotation(spec)
        if name in required:
            param = inspect.Parameter(
                name, inspect.Parameter.KEYWORD_ONLY, annotation=ann
            )
        else:
            default = spec.get("default", None) if isinstance(spec, dict) else None
            param = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Optional[ann],  # type: ignore[valid-type]
                default=default,
            )
        params.append(param)

    return inspect.Signature(params)


# ---------------------------------------------------------------------------
# 结果渲染
# ---------------------------------------------------------------------------


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… （结果过长，已截断；完整内容共 {len(text)} 字符）"


def describe_artifact(data: Dict[str, Any]) -> Optional[str]:
    """把 artifact 字段渲染成一句可直接给用户看的话。

    大数组（栅格、GeoJSON 要素集合）在工具层不内联返回，
    只给出磁盘路径。这里把路径提到最显眼的位置 ——
    这是用户真正想要的东西（"导出的文件在哪"）。
    """
    artifact = data.get("artifact")
    if not isinstance(artifact, dict):
        return None
    path = artifact.get("path") or artifact.get("file")
    if not path:
        return None
    fmt = artifact.get("format")
    parts = [f"产物文件：{path}"]
    if fmt:
        parts.append(f"格式 {fmt}")
    count = artifact.get("feature_count") or artifact.get("count")
    if count is not None:
        parts.append(f"{count} 个要素")
    return "；".join(parts) + "。可直接用 QGIS / Cesium 加载。"


def format_tool_result(
    name: str, result: Dict[str, Any], max_chars: Optional[int] = None
) -> str:
    """把工具返回的 dict 渲染成给模型看的文本。"""
    limit = max_chars or MAX_OUTPUT_CHARS

    if not isinstance(result, dict):
        return str(result)

    # ---- 失败路径：把可修正的信息讲清楚 ----
    if not result.get("success"):
        lines = [
            f"❌ {name} 调用失败",
            f"错误类型：{result.get('error_type') or 'unknown'}",
            f"原因：{result.get('error') or '（未提供）'}",
            f"是否可重试：{'是' if result.get('retryable') else '否'}",
        ]
        for key, label in (("hint", "修正建议"), ("suggestion", "修正建议")):
            value = result.get(key)
            if value:
                lines.append(f"{label}：{value}")
                break
        lines.append(
            "请调整参数后重试，或改用其它工具；"
            "调用 geo_agent_query 可让 Agent 自动完成修正。"
        )
        return "\n".join(lines)

    # ---- 成功路径：产物 → 统计 → 告警 → 完整结果 ----
    data = result.get("data") or {}
    lines = [f"✅ {name} 调用成功"]

    artifact_line = describe_artifact(data)
    if artifact_line:
        lines.append(artifact_line)

    statistics = data.get("statistics")
    if statistics:
        lines.append("关键统计：" + _truncate(_dump(statistics), 1500))

    warnings = data.get("warnings") or []
    if warnings:
        lines.append("⚠️ 告警：" + "；".join(str(w) for w in warnings))

    ignored = data.get("ignored_params")
    if ignored:
        lines.append(f"注意：以下参数被忽略（该工具不支持）：{ignored}")

    # 完整结果中剔除已经单独展示过的部分，避免同一信息占两遍篇幅
    rest = {
        k: v
        for k, v in data.items()
        if k not in ("statistics", "artifact", "warnings")
    }
    if rest:
        lines.append("完整结果：" + _truncate(_dump(rest), limit))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 动态生成 MCP 工具函数
# ---------------------------------------------------------------------------


def make_tool_function(name: str, description: str, parameters: Dict[str, Any]):
    """为一个 backend 工具生成 MCP 可注册的函数。"""
    signature = build_signature(parameters)

    def _mcp_tool(**kwargs: Any) -> str:
        # 选填参数传了 None 的一律丢弃，让工具函数走自己的默认值
        clean = {k: v for k, v in kwargs.items() if v is not None}
        logger.debug("调用工具 %s，参数 keys=%s", name, list(clean))
        try:
            result = call_tool(name, **clean)
        except Exception as exc:  # 兜底：MCP 工具绝不应把异常抛给客户端
            logger.exception("工具 %s 抛出未捕获异常", name)
            return (
                f"❌ {name} 调用时发生未捕获异常：{type(exc).__name__}: {exc}\n"
                "这属于工具层缺陷，请报告给开发者。"
            )
        return format_tool_result(name, result)

    _mcp_tool.__name__ = name
    _mcp_tool.__qualname__ = name
    _mcp_tool.__signature__ = signature  # type: ignore[attr-defined]
    _mcp_tool.__doc__ = description
    return _mcp_tool


def get_tool_definitions() -> List[Dict[str, Any]]:
    """取 MCP 格式的工具定义（{name, description, inputSchema}）。

    与 OpenAI Function Calling 的 schema 同源，由 registry 从同一份定义
    转换而来，不存在两套参数描述不同步的可能。
    """
    return get_mcp_tools()


def build_tool_functions() -> List[Dict[str, Any]]:
    """为每个工具生成 {name, description, parameters, fn}。"""
    built: List[Dict[str, Any]] = []
    for name in [t["name"] for t in get_tool_definitions()]:
        entry = _find_schema(name)
        if entry is None:
            logger.warning("工具 %s 缺少 schema，跳过注册", name)
            continue
        built.append(
            {
                "name": name,
                "description": entry["description"],
                "parameters": entry["inputSchema"],
                "fn": make_tool_function(name, entry["description"], entry["inputSchema"]),
            }
        )
    return built


def _find_schema(name: str) -> Optional[Dict[str, Any]]:
    for item in get_tool_definitions():
        if item["name"] == name:
            return item
    return None
