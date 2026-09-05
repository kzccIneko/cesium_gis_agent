"""GeoMCP —— 把本项目的地理空间分析能力以 MCP 标准协议对外暴露。

接上之后，任意支持 MCP 的客户端（Claude Desktop / Cursor / Cline 等）
都可以直接调用本地的 DEM 分析、地形因子计算、路径规划与地貌分类，
不需要本项目自己的前端，也不需要自己写任何胶水代码。

运行方式
--------
stdio（默认，给 Claude Desktop / Cursor 用）::

    python -m mcp.custom.geo_mcp_server.server
    # 或直接
    python mcp/custom/geo_mcp_server/server.py

HTTP（给需要远程/多客户端接入的场景用）::

    GEO_MCP_TRANSPORT=streamable-http python mcp/custom/geo_mcp_server/server.py

**必须使用 backend 的虚拟环境运行**，因为工具依赖 numpy / rasterio /
onnxruntime 等重型包。配置示例见同目录 `config/`。

设计约束
--------
- 工具 schema 的单一来源是 `backend/app/tools/schemas.py`，
  本文件不重复定义任何参数，避免漂移。
- stdio 传输下 stdout 是协议通道，**任何日志都必须走 stderr**，
  否则会破坏 JSON-RPC 帧解析（这是自写 MCP Server 最常见的翻车点）。
- 工具失败不抛异常，返回带 error_type 与修正建议的文本，
  让客户端模型能自我修正。
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---- 日志必须走 stderr：stdio 传输下 stdout 是 JSON-RPC 通道 -------------
logging.basicConfig(
    stream=sys.stderr,
    level=os.getenv("GEO_MCP_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("geo_mcp")

# ---- 包导入兼容：同时支持「直接跑脚本」和「作为包导入」 ---------------
# 直接运行时 __package__ 为空，相对导入会失败，此时退回绝对导入。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from tools import (  # type: ignore[import-not-found]  # noqa: E402
        BACKEND_ROOT,
        MAX_OUTPUT_CHARS,
        build_tool_functions,
        get_tool_definitions,
    )
else:
    from .tools import (  # noqa: E402
        BACKEND_ROOT,
        MAX_OUTPUT_CHARS,
        build_tool_functions,
        get_tool_definitions,
    )


def _ensure_sdk_importable() -> None:
    """检测 mcp/ 目录遮蔽官方 SDK 的情况并给出可操作的报错。

    项目根目录下有一个同名的 `mcp/` 目录（本服务就放在它下面）。
    如果从项目根以 `python -m mcp.custom.geo_mcp_server.server` 启动，
    Python 会把它当成顶层包 `mcp`，从而遮蔽官方 MCP SDK，
    报错信息是含糊的 "No module named 'mcp.server'"，极难定位。
    """
    import importlib.util

    try:
        if importlib.util.find_spec("mcp.server.fastmcp") is not None:
            return
    except Exception:
        pass

    raise RuntimeError(
        "MCP Python SDK 导入失败：项目根目录下的 mcp/ 目录遮蔽了同名的官方 SDK 包。\n"
        "请不要用 `python -m mcp.custom.geo_mcp_server.server` 从项目根启动。\n"
        "正确方式（直接指定脚本路径，此时 sys.path[0] 是本文件所在目录）：\n"
        f"    python {Path(__file__).resolve()}"
    )


_ensure_sdk_importable()

from mcp.server.fastmcp import FastMCP  # noqa: E402

SERVER_NAME = "GeoMCP"
SERVER_INSTRUCTIONS = """地理空间分析工具集（GeoMCP）。

能力范围：
- DEM：获取栅格元数据、按 bbox 下载真实 SRTM 30m 数据
- 地形因子：坡度 / 坡向 / 曲率 / 通行成本表面
- 路径规划：基于成本表面的最优路径，返回长度、爬升、GeoJSON 线要素
- 地貌分类：规则法 / Geomorphons / ONNX 深度学习三种方法
- 分区统计：按分级区间统计面积占比，回答"多少地方可以修路"这类问题

使用约定：
1. 所有空间范围用 bbox = [minLon, minLat, maxLon, maxLat]，WGS84 经纬度。
2. 大数组不内联返回，工具会给出磁盘上的产物文件路径，把路径告诉用户。
3. resolution 默认 256。ONNX 分类是逐像元滑窗，128×128 约需 25 秒、
   192×192 约需 55 秒，超过 128 会被拒绝 —— 大范围请改用 rules 或 geomorphons。
4. 调用失败时返回 error_type 与修正建议，请据此调整参数重试。
5. 需要"一条指令完成分析"时用 geo_agent_query，它会自行规划、执行并校验。
"""

mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)


# ---------------------------------------------------------------------------
# 注册 11 个分析工具
# ---------------------------------------------------------------------------

_registered: List[str] = []
for _spec in build_tool_functions():
    mcp.add_tool(
        fn=_spec["fn"],
        name=_spec["name"],
        description=_spec["description"],
    )
    _registered.append(_spec["name"])

logger.info("已注册 %d 个工具：%s", len(_registered), ", ".join(_registered))


# ---------------------------------------------------------------------------
# Resources —— 让客户端不必猜
# ---------------------------------------------------------------------------


@mcp.resource("geo://tools")
def resource_tools() -> str:
    """全部工具的完整参数定义（JSON Schema）。

    客户端如果需要精确构造参数，可以读取本资源而不是靠猜。
    """
    return json.dumps(get_tool_definitions(), ensure_ascii=False, indent=2)


@mcp.resource("geo://capabilities")
def resource_capabilities() -> str:
    """服务端能力、数据来源与已知局限。

    数据来源是地理分析的严肃性问题：合成地形和真实 SRTM 的结论
    天差地别，必须让调用方知道自己在跟哪种数据打交道。
    """
    caps: Dict[str, Any] = {
        "server": SERVER_NAME,
        "backend_root": str(BACKEND_ROOT),
        "tools": _registered,
        "output_char_limit": MAX_OUTPUT_CHARS,
        "crs": "EPSG:4326 (WGS84)",
        "dem": {
            "primary": "SRTM 30m（通过 dem_stitcher 在线下载，需联网）",
            "fallback": "合成地形（高斯平滑随机场），无网络时自动降级",
            "warning": "降级为合成地形时，结论不能用于任何真实决策，"
                       "工具结果会带 warning 字段标明。",
        },
        "known_limits": [
            "ONNX 地貌分类为逐像元滑窗（每像元一次 64×64 patch 推理），"
            "128×128 约 25s、192×192 约 55s，超过 128 分辨率会被拒绝",
            "路径规划基于坡度成本表面，不含道路、水体、土地利用等现实约束",
            "坡度/坡向按 Horn 方法在投影平面计算，高纬度地区存在畸变",
        ],
    }
    return json.dumps(caps, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Prompt —— 常见分析流程的起手式
# ---------------------------------------------------------------------------


@mcp.prompt("geo_site_selection")
def prompt_site_selection(requirement: str, bbox: str) -> str:
    """选址/选线分析的标准流程。

    Args:
        requirement: 用户的实际需求，例如"找可以修施工便道的缓坡区域"
        bbox: 研究区范围，格式 "minLon,minLat,maxLon,maxLat"
    """
    return f"""请对 bbox={bbox} 的范围完成以下分析，需求是：{requirement}。

建议流程：

1. 先用 get_dem_metadata 确认数据源。若返回显示使用了合成地形而非真实
   SRTM，必须在最终结论里明确告知用户「本次结果基于合成地形，不可用于
   真实决策」。

2. 用 zonal_statistics 按坡度分级统计面积占比，从宏观上判断可行性。
   分级建议用 [0, 5, 10, 15, 25, 90]，对应「平地 / 缓坡 / 中等 / 较陡 / 陡峭」。

3. 若需求涉及选线，用 plan_route 给出具体路径，并报告长度与累计爬升。

4. 若需求涉及地貌类型，优先用 classify_terrain_rules（快），
   需要经典地貌学分类时用 classify_geomorphons；
   classify_terrain_onnx 仅限 resolution ≤ 128。

5. 结论必须包含：
   - 关键数值（面积占比 / 路径长度 / 爬升），并带单位
   - 产物文件路径（用户需要拿去 QGIS 里看）
   - 数据来源（真实 SRTM 还是合成地形）
   - 方法局限（例如路径规划未考虑水体与土地利用）

不要编造数值。所有数字必须来自工具返回结果。
"""


# ---------------------------------------------------------------------------
# Agent 工具 —— 一个问题走完全流程
# ---------------------------------------------------------------------------

_AGENT_LLM_ENABLED = os.getenv("GEOAGENT_LLM_ENABLED", "0").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _resolve_llm():
    """按环境变量决定是否接 LLM。

    默认关闭：此时 Agent 走确定性路径 —— 关键词启发式规划 + 9 条规则校验
    + 模板化总结，全程离线、秒级返回、无 API key 要求。

    开启后（GEOAGENT_LLM_ENABLED=1）用 OpenAI 兼容接口做规划与语义复核，
    需要在环境变量里配置 GEOAGENT_LLM_BASE_URL / GEOAGENT_LLM_API_KEY /
    GEOAGENT_LLM_MODEL。默认值指向本机 Ollama。

    默认关闭不是消极取舍：MCP 客户端本身就是一个强模型，让它自己编排
    11 个细粒度工具通常比让一个本地小模型代劳效果更好。geo_agent_query
    的价值在于"不想让客户端多轮往返"或"客户端模型较弱"的场景。
    """
    if not _AGENT_LLM_ENABLED:
        return None
    try:
        from app.agent.llm import build_client

        return build_client()
    except Exception as exc:
        logger.warning("LLM 客户端构建失败，本次以无 LLM 模式运行：%s", exc)
        return None


@mcp.tool(
    name="geo_agent_query",
    description=(
        "端到端回答一个地理空间问题：自动拆解任务、调用所需工具、"
        "用 9 条领域规则校验结果并在失败时自动修正重试，最后给出结论。"
        "适合「这片区域哪里适合修路」这类需要多步分析的提问；"
        "若你只想拿到某个单项指标，直接调用对应的细粒度工具更快。"
    ),
)
def geo_agent_query(
    question: str,
    bbox: List[float],
    max_retries: int = 3,
    session_id: str = "mcp",
    include_trace: bool = False,
) -> str:
    """一个问题走完「计划 → 执行 → 反思」全流程。

    Args:
        question: 自然语言问题，例如"这片区域哪里适合修施工便道"
        bbox: 研究区范围 [minLon, minLat, maxLon, maxLat]，WGS84
        max_retries: 单步失败后的最大反思重试次数
        session_id: 会话标识，相同 id 可复用历史状态
        include_trace: 是否附带上执行轨迹（调试用）
    """
    try:
        from app.agent import run_agent
    except Exception as exc:
        return (
            "❌ 无法加载编排层（backend/app/agent）："
            f"{type(exc).__name__}: {exc}\n"
            "请确认使用 backend 虚拟环境启动本服务。"
        )

    if len(bbox) != 4:
        return (
            "❌ bbox 必须是 [minLon, minLat, maxLon, maxLat] 四个数，"
            f"收到 {len(bbox)} 个：{bbox}"
        )

    llm = _resolve_llm()

    try:
        state = run_agent(
            question,
            bbox=list(bbox),
            session_id=session_id,
            llm=llm,
            max_retries=max(0, int(max_retries)),
        )
    except Exception as exc:
        logger.exception("Agent 执行失败")
        return f"❌ Agent 执行失败：{type(exc).__name__}: {exc}"

    status = state.get("status")
    answer = state.get("final_answer") or "（Agent 未产出结论）"
    calls = state.get("tool_calls") or []

    lines = [answer, ""]
    lines.append(
        f"—— 状态：{status}｜LLM：{'已启用' if llm else '未启用（确定性模式）'}"
        f"｜工具调用 {len(calls)} 次"
    )

    succeeded = [c for c in calls if c.get("success")]
    failed = [c for c in calls if not c.get("success")]
    if failed:
        lines.append(
            "⚠️ 以下步骤失败：" + "、".join(f"{c['tool']}" for c in failed)
        )
    if succeeded:
        lines.append("已执行：" + "、".join(f"{c['tool']}" for c in succeeded))

    artifacts = []
    for c in calls:
        data = (c.get("result") or {}).get("data") or {}
        art = data.get("artifact")
        if isinstance(art, dict) and art.get("path"):
            artifacts.append(art["path"])
    if artifacts:
        lines.append("产物文件：" + "；".join(dict.fromkeys(artifacts)))

    if include_trace:
        lines.append("")
        lines.append("执行轨迹：")
        lines.extend("  - " + t for t in (state.get("trace") or []))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main(transport: Optional[str] = None) -> None:
    transport = transport or os.getenv("GEO_MCP_TRANSPORT", "stdio")
    logger.info("启动 %s，传输方式=%s，已注册 %d 个工具",
                SERVER_NAME, transport, len(_registered))
    mcp.run(transport)


if __name__ == "__main__":
    main()
