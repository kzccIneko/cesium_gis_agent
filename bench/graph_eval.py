"""把 LangGraph 编排接进评测链路。

为什么单独一层适配器
--------------------
`graph.py` 里的状态图本来就有 **51 个单测**覆盖，缺的不是"图能不能跑"，
而是**它能不能被评测打分**。这个模块只做三件事：

    1. 把 executor 的工具执行换成桩（`dispatch` 换掉，图不感知）
    2. 用真实 `build_graph()` 编译的图跑完整 plan→execute→reflect→summarize
    3. 从结束状态里抽出 prediction，交给 `score_case` 打分

三处刻意的设计取舍
------------------
* **为什么桩工具要"假装通过全部领域规则"**
  本评测考察的是「规划 + 编排」能力，不是工具本身的数值正确性
  （工具层另有 28 个单测）。如果桩返回一个会触发 `slope_range` /
  `tile_alignment` 报错的假结果，reflector 会义无反顾地重试到耗尽
  —— 那测到的是"桩写得烂"，不是"模型规划得差"。桩数据因此必须
  严格自洽：栅格 shape 对齐分辨率、bbox 回显传参、路径距离用
  Haversine 独立算出。

* **为什么默认关掉 reflect/summarize 的 LLM**
  这两处 LLM 与"规划能力"无关，却会让每条样本的调用次数翻 3–5 倍。
  关掉后一条样本**恰好一次 LLM 调用**（就是 planner），才能干净地
  和 `--orchestrator loop`（多轮试探）做 "调用次数 / 延迟 / 准确率"
  三项对比。要测反思质量时用 `--reflect-llm` 单独开。

* **为什么不把 ground truth 的 bbox 喂进去**
  那是标准答案。喂进去等于开卷考试，param_bbox 拿到满分也没有任何
  信息量。bbox 只能来自两条正当途径：**地名词典查表** 或 **模型自己
  从问题的显式坐标里读出来**。
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "backend") not in sys.path:
    sys.path.insert(0, str(REPO / "backend"))

from app.agent.graph import DEFAULT_RECURSION_LIMIT  # noqa: E402
from app.agent.state import create_initial_state  # noqa: E402
from app.tools.registry import TOOL_REGISTRY  # noqa: E402

CLASSIFY_TOOLS = {
    "classify_terrain_rules",
    "classify_geomorphons",
    "classify_terrain_onnx",
}
RASTER_METRIC_TOOLS = {
    "compute_slope",
    "compute_aspect",
    "compute_curvature",
    "compute_cost_surface",
}


# --------------------------------------------------------------------------
# LLM 调用计数器
# --------------------------------------------------------------------------
class CountingLLM:
    """包一层只为计数 —— 调用次数是本次对比的核心开销指标之一。

    它必须把 `chat` 之外的属性也转发出去（如 EmbeddedLlamaClient 的
    `_ensure_model`），否则评测脚本的预热逻辑会失效。
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.n_calls = 0

    def chat(self, *args: Any, **kwargs: Any):
        self.n_calls += 1
        return self._inner.chat(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


class NullGazetteer:
    """关闭词典时的替身 —— 用于做有无词典的 A/B。"""

    def resolve_bbox(self, text: str) -> Optional[List[float]]:
        return None

    def lookup(self, text: str, limit: int = 3) -> List[Any]:
        return []

    def annotate(self, query: str) -> str:
        return query


# --------------------------------------------------------------------------
# 工具桩：返回自洽的假结果
# --------------------------------------------------------------------------
def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """与 rules.py 里那条独立复算完全同一个公式 —— 直线距离必须对得上，
    否则 `path_length_sanity` 会判定工具自洽性失败。"""
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _cell_size_m(bbox: Optional[List[float]], res: int) -> float:
    """像元边长（米）。夹到合法区间内，避免 crs_consistency 误判。"""
    if not bbox or len(bbox) != 4 or not res:
        return 30.0
    w, s, e, n = [float(v) for v in bbox]
    width_m = _haversine_m(w, (s + n) / 2, e, (s + n) / 2)
    size = width_m / max(int(res), 1)
    return float(min(max(size, 1.0), 20_000.0))


def _failed(tool: str, error_type: str, error: str, retryable: bool) -> Dict[str, Any]:
    return {
        "tool": tool,
        "success": False,
        "error": error,
        "error_type": error_type,
        "retryable": retryable,
        "duration_ms": 0.1,
        "data": {},
    }


def stub_dispatch(tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """替身版 `registry.dispatch`。

    返回结构必须与 ToolResult.to_dict() 对齐，且 data 字段要通过
    `app.agent.rules` 的全部适用规则 —— 这条约束是刻意的，
    理由见本文件开头的说明。
    """
    arguments = dict(arguments or {})
    if tool not in TOOL_REGISTRY:
        return _failed(tool, "invalid_tool", f"未知工具: {tool}", False)

    res = int(arguments.get("resolution") or 128)
    bbox = arguments.get("bbox")
    bbox_out = [float(v) for v in bbox] if isinstance(bbox, (list, tuple)) and len(bbox) == 4 else None

    base_stats = {
        "shape": [res, res],
        "min": 0.0,
        "max": 45.0,
        "mean": 18.4,
        "std": 9.6,
        "valid_ratio": 1.0,
    }
    common: Dict[str, Any] = {
        "bbox": bbox_out,
        "resolution": res,
        "crs": "EPSG:4326",
        "cell_size_m": _cell_size_m(bbox_out, res),
        "dem_source": "stub",
        "warnings": [],
    }

    if tool in RASTER_METRIC_TOOLS:
        stats = dict(base_stats)
        if tool == "compute_aspect":      # 坡向合法区间是 [0, 360)
            stats["max"] = 358.0
        data = {**common, "statistics": stats,
                "raster_path": f"data/out/{tool}.tif",
                "summary": f"{tool} 完成：{res}×{res} 栅格，均值 {stats['mean']}"}
    elif tool in CLASSIFY_TOOLS:
        data = {
            **common,
            "statistics": dict(base_stats),
            "class_path": f"data/out/{tool}.tif",
            "distribution": {"distinct_classes": 4, "dominant_ratio": 0.42},
            "summary": f"{tool} 完成：4 个地貌类别，主导占比 42%",
        }
    elif tool == "plan_route":
        start = arguments.get("start_point") or [0.0, 0.0]
        end = arguments.get("end_point") or [0.0, 0.0]
        try:
            straight = _haversine_m(float(start[0]), float(start[1]),
                                    float(end[0]), float(end[1]))
        except (TypeError, ValueError, IndexError):
            straight = 1000.0
        detour = 1.25
        data = {
            **common,
            "node_count": max(3, res // 32),
            "straight_line_m": straight,
            "distance_m": straight * detour,
            "detour_ratio": detour,
            "path": [list(start), list(end)],
            "summary": f"路径规划完成：直线 {straight/1000:.1f} km，绕行系数 {detour}",
        }
    elif tool == "download_srtm":
        data = {
            **common,
            "dem_path": arguments.get("dem_path") or "data/dem/srtm_30m.tif",
            "resolution_m": 30,
            "summary": "SRTM 30m DEM 下载完成",
        }
    elif tool == "get_dem_metadata":
        data = {
            **common,
            "dem_path": arguments.get("dem_path") or "data/dem/srtm_30m.tif",
            "width": 3601, "height": 3601, "resolution_m": 30, "nodata": -32768,
            "summary": "DEM 元数据读取完成",
        }
    elif tool == "zonal_statistics":
        data = {
            **common,
            "zones": 6, "mean": 21.4, "std": 9.8,
            "statistics": dict(base_stats),
            "summary": "分区统计完成：6 个分区",
        }
    else:
        data = {**common, "summary": f"{tool} 完成"}

    return {
        "tool": tool,
        "success": True,
        "error": None,
        "error_type": None,
        "retryable": False,
        "duration_ms": 1.0,
        "data": data,
    }


# --------------------------------------------------------------------------
# 跑一条样本
# --------------------------------------------------------------------------
def _prediction_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """把结束状态翻译成 EvalRunner 同款的 prediction 结构。

    工具序列取**实际执行成功**的调用并保序去重：
    同一工具被重试两次只算一次，否则工具序列会因为自我修正而虚增长度。
    """
    calls = list(state.get("tool_calls") or [])
    tools: List[str] = []
    params: Dict[str, Any] = {}
    for c in calls:
        name = c.get("tool", "")
        if c.get("success") and name and name not in tools:
            tools.append(name)
        args = c.get("arguments") or {}
        if isinstance(args, dict):
            for k, v in args.items():
                params.setdefault(k, v)

    return {
        "parsed": True,
        "tools": tools,
        "params": params,
        "refused": bool(state.get("refused")),
        "parse_error": None,
        "raw_head": None,
    }


def run_case_graph(
    case: Dict[str, Any],
    client: Any,
    *,
    use_gazetteer: bool = True,
    reflect_llm: bool = False,
    summarize_llm: bool = False,
    recursion_limit: int = DEFAULT_RECURSION_LIMIT,
    checkpointer: Any = None,
) -> Dict[str, Any]:
    """用真实 LangGraph 状态图跑一条评测样本。

    Args:
        case: dataset.json 里的一条
        client: LLM 客户端（会被 CountingLLM 包一层以统计调用次数）
        use_gazetteer: 是否允许 planner 查地名词典取 bbox
        reflect_llm: 反思节点是否启用 LLM 语义复核
        summarize_llm: 总结节点是否用 LLM 写自然语言回答
        recursion_limit: 防死循环上限
        checkpointer: LangGraph checkpointer；None = 不持久化

    Returns:
        {"prediction", "elapsed", "n_llm_calls", "status", "n_steps_planned", "state"}
    """
    counting = CountingLLM(client)

    # 图节点按 role 取不同 LLM：关掉反思/总结的模型，就传 None
    # （None 时 reflect 只跑代码规则、summarize 走模板 —— 见节点实现）
    graph = build_graph_from_llms(
        plan_llm=counting,
        reflect_llm=counting if reflect_llm else None,
        summarize_llm=counting if summarize_llm else None,
        checkpointer=checkpointer,
    )

    import app.agent.nodes.executor as _exec_mod
    import app.agent.nodes.planner as _plan_mod

    # 两个补丁都必须在 finally 里还原：
    # 这是评测脚手架，跑完不能把真实运行时的行为改掉。
    orig_dispatch = _exec_mod.dispatch
    orig_get_gazetteer = _plan_mod.get_gazetteer
    _exec_mod.dispatch = stub_dispatch
    if not use_gazetteer:
        _plan_mod.get_gazetteer = lambda *a, **kw: NullGazetteer()
    try:
        state = create_initial_state(
            query=case["query"],
            bbox=None,  # 绝不喂 ground truth —— 坐标只能来自词典或模型
            session_id=f"eval-{case['id']}",
        )
        t0 = time.perf_counter()
        final = graph.invoke(
            state,
            config={
                "recursion_limit": recursion_limit,
                "configurable": {"thread_id": f"eval-{case['id']}"},
            },
        )
        elapsed = time.perf_counter() - t0
    finally:
        _exec_mod.dispatch = orig_dispatch
        _plan_mod.get_gazetteer = orig_get_gazetteer

    return {
        "prediction": _prediction_from_state(final),
        "elapsed": elapsed,
        "n_llm_calls": counting.n_calls,
        "status": final.get("status"),
        "n_steps_planned": len(final.get("plan") or []),
        "state": final,
    }


def build_graph_from_llms(
    plan_llm: Any,
    reflect_llm: Any = None,
    summarize_llm: Any = None,
    checkpointer: Any = None,
):
    """按节点粒度注入 LLM —— 评测要单独关掉某些节点的模型。

    `graph.build_graph` 只接受单个 llm，这里手工复用同样的四个节点
    与同一套路由函数，保证两条路径的**拓扑完全一致**，差别只在
    某个节点有没有模型。
    """
    from langgraph.graph import END, START, StateGraph

    from app.agent.nodes.executor import execute_node
    from app.agent.nodes.planner import plan_node
    from app.agent.nodes.reflector import reflect_node
    from app.agent.nodes.summarizer import summarize_node
    from app.agent.routing import (
        NODE_EXECUTE,
        NODE_PLAN,
        NODE_REFLECT,
        NODE_SUMMARIZE,
        route_after_execute,
        route_after_plan,
        route_after_reflect,
    )
    from app.agent.state import AgentState

    g = StateGraph(AgentState)
    g.add_node(NODE_PLAN, lambda s: plan_node(s, plan_llm))
    g.add_node(NODE_EXECUTE, execute_node)
    g.add_node(NODE_REFLECT, lambda s: reflect_node(s, reflect_llm))
    g.add_node(NODE_SUMMARIZE, lambda s: summarize_node(s, summarize_llm))

    g.add_edge(START, NODE_PLAN)
    g.add_conditional_edges(
        NODE_PLAN, route_after_plan,
        {NODE_EXECUTE: NODE_EXECUTE, NODE_SUMMARIZE: NODE_SUMMARIZE},
    )
    g.add_conditional_edges(NODE_EXECUTE, route_after_execute, {NODE_REFLECT: NODE_REFLECT})
    g.add_conditional_edges(
        NODE_REFLECT, route_after_reflect,
        {NODE_EXECUTE: NODE_EXECUTE, NODE_SUMMARIZE: NODE_SUMMARIZE},
    )
    g.add_edge(NODE_SUMMARIZE, END)
    return g.compile(checkpointer=checkpointer)
