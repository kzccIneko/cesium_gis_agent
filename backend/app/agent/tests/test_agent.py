"""GeoAgent 编排层测试。

运行方式（二选一）：
    # pytest
    D:/VS_Code_Program/CesiumJS_Debug/backend/.venv/Scripts/python.exe -m pytest backend/app/agent/tests/ -v

    # 直接运行（不依赖 pytest）
    D:/VS_Code_Program/CesiumJS_Debug/backend/.venv/Scripts/python.exe backend/app/agent/tests/test_agent.py

测试分组：
    A. 校验规则（reflector 的确定性部分）—— 每条规则正反两面
    B. LLM 层（JSON 提取容错、Mock 客户端）
    C. 节点（planner 三层降级、reflector 仲裁）
    D. 端到端（含**失败重试**这一关键路径）
    E. 持久化（中断恢复）
    F. 路由

全程使用合成地形 + 低分辨率（64），不依赖网络与外部 API。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import warnings

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.agent import MockClient, run_agent  # noqa: E402
from app.agent.llm import extract_json  # noqa: E402
from app.agent.nodes.executor import execute_node  # noqa: E402
from app.agent.nodes.planner import heuristic_plan, plan_node  # noqa: E402
from app.agent.nodes.reflector import reflect_node  # noqa: E402
from app.agent.routing import route_after_reflect  # noqa: E402
from app.agent.rules import (  # noqa: E402
    check_arguments,
    check_result,
    rule_bbox_order,
    rule_classification_nonempty,
    rule_dem_source_authenticity,
    rule_endpoints_in_bbox,
    rule_path_length_sanity,
    rule_slope_range,
    rule_tile_alignment,
    rule_valid_data_ratio,
)
from app.agent.state import create_initial_state, merge_patch  # noqa: E402

BBOX = [103.5, 30.2, 103.7, 30.4]
RES = 64


def _plan_json(steps, bbox=BBOX, **extra):
    obj = {
        "bbox": bbox,
        "understanding": "测试用计划",
        "steps": steps,
        "final_answer_hint": "报告数值",
    }
    obj.update(extra)
    return json.dumps(obj, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════
# A. 校验规则
# ══════════════════════════════════════════════════════════════════

def test_rule_slope_valid():
    r = rule_slope_range("compute_slope", {}, {"statistics": {"min": 0.5, "max": 31.6}})
    assert r is not None and r.passed


def test_rule_slope_out_of_range():
    r = rule_slope_range("compute_slope", {}, {"statistics": {"min": -3, "max": 95}})
    assert r is not None and not r.passed and r.level == "error"


def test_rule_slope_near_vertical_warn():
    r = rule_slope_range("compute_slope", {}, {"statistics": {"min": 0, "max": 88}})
    assert r is not None and not r.passed and r.level == "warn"


def test_rule_path_shorter_than_straight_line():
    """路径长度小于直线距离 —— 物理上不可能，必须判错。"""
    r = rule_path_length_sanity(
        "plan_route",
        {"start_point": [103.55, 30.25], "end_point": [103.65, 30.35]},
        {"distance_m": 100.0, "straight_line_m": 1000.0, "detour_ratio": 0.1, "node_count": 20},
    )
    assert r is not None and not r.passed and r.level == "error"


def test_rule_path_detour_abnormal():
    r = rule_path_length_sanity(
        "plan_route",
        {"start_point": [103.55, 30.25], "end_point": [103.65, 30.35]},
        {"distance_m": 500_000.0, "straight_line_m": 10_000.0, "detour_ratio": 50.0, "node_count": 20},
    )
    assert r is not None and not r.passed and r.level == "error"


def test_rule_path_degenerate_nodes():
    r = rule_path_length_sanity("plan_route", {}, {"node_count": 1})
    assert r is not None and not r.passed and r.level == "error"


def test_rule_endpoints_outside_bbox_auto_fix():
    """起终点越界必须给出可执行的修正建议（夹取回 bbox 内）。"""
    r = rule_endpoints_in_bbox(
        "plan_route",
        {
            "bbox": BBOX,
            "start_point": [103.0, 30.0],
            "end_point": [103.95, 30.55],
        },
        {},
    )
    assert r is not None and not r.passed
    assert r.suggestion is not None
    w, s, e, n = BBOX
    for key in ("start_point", "end_point"):
        lon, lat = r.suggestion[key]
        assert w <= lon <= e, f"{key} 经度未修正：{lon}"
        assert s <= lat <= n, f"{key} 纬度未修正：{lat}"


def test_rule_endpoints_inside_bbox_pass():
    r = rule_endpoints_in_bbox(
        "plan_route",
        {"bbox": BBOX, "start_point": [103.55, 30.25], "end_point": [103.65, 30.35]},
        {},
    )
    assert r is not None and r.passed


def test_rule_bbox_order_latlon_swapped():
    """[minLat, minLon, maxLat, maxLon] 应被识别并交换。"""
    r = rule_bbox_order("compute_slope", {"bbox": [30.2, 103.5, 30.4, 103.7]}, {})
    assert r is not None and not r.passed
    assert r.suggestion["bbox"] == [103.5, 30.2, 103.7, 30.4]


def test_rule_bbox_order_reversed():
    r = rule_bbox_order("compute_slope", {"bbox": [103.7, 30.4, 103.5, 30.2]}, {})
    assert r is not None and not r.passed
    assert r.suggestion["bbox"] == [103.5, 30.2, 103.7, 30.4]


def test_rule_classification_single_class():
    r = rule_classification_nonempty(
        "classify_terrain_rules", {}, {"distribution": {"distinct_classes": 1}}
    )
    assert r is not None and not r.passed and r.level == "error"


def test_rule_classification_dominant_warn():
    r = rule_classification_nonempty(
        "classify_geomorphons",
        {},
        {"distribution": {"distinct_classes": 3, "dominant_ratio": 0.999}},
    )
    assert r is not None and not r.passed and r.level == "warn"


def test_rule_tile_alignment_mismatch():
    r = rule_tile_alignment(
        "compute_slope", {"resolution": 128}, {"resolution": 128, "statistics": {"shape": [64, 64]}}
    )
    assert r is not None and not r.passed


def test_rule_valid_ratio_low():
    r = rule_valid_data_ratio("zonal_statistics", {}, {"valid_ratio": 0.2})
    assert r is not None and not r.passed and r.level == "error"


def test_rule_dem_synthetic_flagged():
    """合成地形必须被标记 —— 防止 Agent 拿假数据给真结论。"""
    r = rule_dem_source_authenticity("compute_slope", {}, {"dem_source": "synthetic"})
    assert r is not None and not r.passed and r.level == "warn"
    assert "合成地形" in r.message


def test_check_result_runs_all_applicable_rules():
    report = check_result(
        "compute_slope",
        {"bbox": BBOX, "resolution": 64},
        {
            "bbox": BBOX,
            "resolution": 64,
            "dem_source": "synthetic",
            "statistics": {"min": 1.0, "max": 30.0, "shape": [64, 64]},
        },
    )
    names = {r.rule for r in report.results}
    assert "slope_range" in names
    assert "tile_alignment" in names
    assert "dem_source_authenticity" in names
    assert report.passed  # 只有 warn，没有 error


def test_check_arguments_on_failed_call():
    """工具调用失败时仍要跑参数类规则 —— 这是能修正重试的关键。"""
    report = check_arguments(
        "plan_route",
        {"bbox": BBOX, "resolution": 64, "start_point": [103.0, 30.0], "end_point": [103.95, 30.55]},
    )
    assert report.errors, "起终点越界应被参数类规则捕获"
    assert report.errors[0].suggestion is not None


# ══════════════════════════════════════════════════════════════════
# B. LLM 层
# ══════════════════════════════════════════════════════════════════

def test_extract_json_plain():
    assert extract_json('{"a": 1, "b": [1,2]}')["a"] == 1


def test_extract_json_markdown_fence():
    out = extract_json('好的，结果如下：\n```json\n{"action": "accept"}\n```\n希望有用')
    assert out is not None and out["action"] == "accept"


def test_extract_json_leading_text():
    out = extract_json('我认为应该重试。\n\n{"action": "retry", "rule": "x"}')
    assert out is not None and out["action"] == "retry"


def test_extract_json_chinese_quotes():
    out = extract_json('{"action": \u201caccept\u201d}')
    assert out is not None and out["action"] == "accept"


def test_extract_json_garbage():
    assert extract_json("我无法完成这个任务") is None


def test_mock_client_scripted():
    mc = MockClient(['{"n": 1}', '{"n": 2}'])
    r1 = mc.chat([{"role": "user", "content": "x"}])
    r2 = mc.chat([{"role": "user", "content": "x"}])
    assert extract_json(r1.content)["n"] == 1
    assert extract_json(r2.content)["n"] == 2
    assert mc.call_count == 2


# ══════════════════════════════════════════════════════════════════
# C. 节点
# ══════════════════════════════════════════════════════════════════

def test_planner_no_llm_uses_heuristic():
    st = create_initial_state("分析这片区域的坡度", bbox=BBOX)
    patch = plan_node(st, None)
    merged = merge_patch(st, patch)
    assert merged["plan"], "无 LLM 时必须有兜底计划"
    assert any("坡度" in t for t in merged["trace"])
    assert "LLM 规划失败" not in " ".join(merged["trace"]), "不应伪装成 LLM 失败"


def test_planner_llm_valid_json():
    plan = _plan_json([
        {"tool": "compute_slope", "intent": "算坡度", "arguments": {"bbox": BBOX, "resolution": RES}}
    ])
    st = create_initial_state("算坡度", bbox=BBOX)
    merged = merge_patch(st, plan_node(st, MockClient([plan])))
    assert len(merged["plan"]) == 1
    assert merged["plan"][0]["tool"] == "compute_slope"
    assert "LLM 规划成功" in " ".join(merged["trace"])


def test_planner_llm_invalid_json_falls_back():
    st = create_initial_state("分析坡度", bbox=BBOX)
    merged = merge_patch(st, plan_node(st, MockClient(["这不是 JSON"])))
    assert merged["plan"], "LLM 输出非法时必须兜底"
    assert "启发式兜底" in " ".join(merged["trace"])


def test_planner_rejects_unknown_tool_then_falls_back():
    plan = _plan_json(
        [{"tool": "teleport_dem", "intent": "瞬移", "arguments": {}}]
    )
    st = create_initial_state("分析坡度", bbox=BBOX)
    merged = merge_patch(st, plan_node(st, MockClient([plan])))
    assert merged["plan"], "引用不存在的工具必须兜底"
    assert all(s["tool"] != "teleport_dem" for s in merged["plan"])


def test_planner_normalizes_argument_aliases():
    """大模型把 bbox 写成 bounds、分辨率写成字符串，应被归一化。"""
    plan = _plan_json([
        {
            "tool": "plan_route",
            "intent": "规划",
            "arguments": {
                "bounds": BBOX,
                "resolution": "64",
                "start_point": {"lon": 103.55, "lat": 30.25},
                "end_point": {"lon": 103.65, "lat": 30.35},
            },
        }
    ])
    st = create_initial_state("规划路径", bbox=BBOX)
    merged = merge_patch(st, plan_node(st, MockClient([plan])))
    args = merged["plan"][0]["arguments"]
    assert args["bbox"] == BBOX
    assert args["resolution"] == 64 and isinstance(args["resolution"], int)
    assert args["start_point"] == [103.55, 30.25]


def test_heuristic_plan_covers_intents():
    p1 = heuristic_plan("这片区域哪里可以修路", BBOX)
    assert any(s["tool"] == "plan_route" for s in p1["steps"])
    assert any(s["tool"] == "zonal_statistics" for s in p1["steps"])
    p2 = heuristic_plan("做一次地貌分类", BBOX)
    assert any(s["tool"].startswith("classify") for s in p2["steps"])
    p3 = heuristic_plan("坡向如何分布", BBOX)
    assert any(s["tool"] == "compute_aspect" for s in p3["steps"])


def test_executor_records_call():
    st = create_initial_state("算坡度", bbox=BBOX)
    st = merge_patch(st, {"plan": [
        {"tool": "compute_slope", "intent": "算坡度",
         "arguments": {"bbox": BBOX, "resolution": RES}, "status": "pending"}
    ]})
    merged = merge_patch(st, execute_node(st))
    assert len(merged["tool_calls"]) == 1
    assert merged["last_result"]["success"]
    assert merged["tool_calls"][0]["tool"] == "compute_slope"
    assert merged["tool_calls"][0]["duration_ms"] > 0


def test_reflector_accepts_good_result():
    st = create_initial_state("算坡度", bbox=BBOX)
    st = merge_patch(st, {"plan": [
        {"tool": "compute_slope", "intent": "x",
         "arguments": {"bbox": BBOX, "resolution": RES}, "status": "pending"}
    ]})
    st = merge_patch(st, execute_node(st))
    merged = merge_patch(st, reflect_node(st, None))
    assert merged["reflection"]["action"] == "accept"
    assert merged["step_index"] == 1


def test_reflector_retries_on_recoverable_error():
    """起终点越界 → reflector 必须给出修正参数并重试，而不是放弃。"""
    bad_args = {
        "bbox": BBOX, "resolution": RES,
        "start_point": [103.0, 30.0], "end_point": [103.95, 30.55],
    }
    st = create_initial_state("规划路径", bbox=BBOX)
    st = merge_patch(st, {"plan": [
        {"tool": "plan_route", "intent": "规划", "arguments": bad_args, "status": "pending"}
    ]})
    st = merge_patch(st, execute_node(st))
    assert not st["last_result"]["success"], "前置条件：首次调用应失败"

    merged = merge_patch(st, reflect_node(st, None))
    assert merged["reflection"]["action"] == "retry"
    assert merged["reflection"]["suggestion"] is not None
    assert merged["retry_count"] == 1
    # 修正后的参数应已写回计划
    fixed = merged["plan"][0]["arguments"]
    w, s, e, n = BBOX
    assert w <= fixed["start_point"][0] <= e


def test_reflector_aborts_on_fatal_error():
    """不可重试的错误（如 DEM 文件不存在）应立即放弃，不浪费重试次数。"""
    st = create_initial_state("读 DEM", bbox=BBOX)
    st = merge_patch(st, {"plan": [
        {"tool": "get_dem_metadata", "intent": "读元数据",
         "arguments": {"dem_path": "definitely-not-exists.tif"}, "status": "pending"}
    ]})
    st = merge_patch(st, execute_node(st))
    merged = merge_patch(st, reflect_node(st, None))
    assert merged["reflection"]["action"] == "abort"
    assert merged["status"] == "failed"


def test_reflector_llm_can_veto_code_accept():
    """代码判定通过时，LLM 仍可基于语义否决议定重试。"""
    st = create_initial_state("分析坡度", bbox=BBOX)
    st = merge_patch(st, {"plan": [
        {"tool": "compute_slope", "intent": "x",
         "arguments": {"bbox": BBOX, "resolution": RES}, "status": "pending"}
    ]})
    st = merge_patch(st, execute_node(st))
    llm = MockClient(['{"action": "retry", "rule": "semantic", "reason": "分辨率过低", "suggestion": {"resolution": 128}}'])
    merged = merge_patch(st, reflect_node(st, llm))
    assert merged["reflection"]["action"] == "retry"
    assert merged["reflection"]["source"] == "llm"
    assert merged["plan"][0]["arguments"]["resolution"] == 128


def test_reflector_code_error_overrides_llm():
    """代码判定为 error 时，LLM 无权放行（代码是权威）。"""
    st = create_initial_state("规划路径", bbox=BBOX)
    # 构造一个代码能判 error 的结果：路径长度小于直线距离
    st = merge_patch(st, {
        "plan": [{"tool": "plan_route", "intent": "规划",
                  "arguments": {"bbox": BBOX, "resolution": RES}, "status": "pending"}],
        "last_result": {"tool": "plan_route", "success": True, "data": {
            "distance_m": 100.0, "straight_line_m": 5000.0,
            "detour_ratio": 0.02, "node_count": 50, "bbox": BBOX,
        }},
    })
    llm = MockClient(['{"action": "accept", "rule": "ok", "reason": "看起来没问题"}'])
    merged = merge_patch(st, reflect_node(st, llm))
    assert merged["reflection"]["action"] == "retry"
    assert merged["reflection"]["source"] == "code"


def test_reflector_llm_retry_exhausted_aborts_not_accepts():
    """回归测试：LLM 判定结果不可用且重试耗尽时，必须放弃而非接受。

    曾经的缺陷：LLM 返回 retry 但次数耗尽时，代码落进 else 分支判为 accept，
    导致 Agent 拿一个自己刚判定为不合格的结果去回答用户。
    """
    st = create_initial_state("算坡度", bbox=BBOX, max_retries=3)
    st = merge_patch(st, {
        "plan": [{"tool": "compute_slope", "intent": "x",
                  "arguments": {"bbox": BBOX, "resolution": RES}, "status": "pending"}],
        "retry_count": 3,  # 三次重试已全部用尽
        "last_result": {
            "tool": "compute_slope", "success": True,
            "data": {"bbox": BBOX, "resolution": RES, "dem_source": "synthetic",
                     "statistics": {"min": 1.0, "max": 30.0, "shape": [RES, RES]}},
        },
    })
    llm = MockClient([
        '{"action":"retry","rule":"semantic","reason":"分辨率不足以支撑结论","suggestion":{}}'
    ])
    merged = merge_patch(st, reflect_node(st, llm))
    assert merged["reflection"]["source"] == "llm"
    assert merged["reflection"]["action"] == "abort", (
        "LLM 判定不可用且重试耗尽时必须放弃，绝不能当作接受"
    )


def test_reflector_respects_max_retries():
    """重试次数耗尽后必须放弃，不能无限循环。"""
    st = create_initial_state("规划路径", bbox=BBOX, max_retries=2)
    bad_args = {"bbox": BBOX, "resolution": RES,
                "start_point": [103.0, 30.0], "end_point": [103.95, 30.55]}
    st = merge_patch(st, {
        "plan": [{"tool": "plan_route", "intent": "x", "arguments": bad_args, "status": "pending"}],
        "retry_count": 2,
    })
    merged = merge_patch(st, reflect_node(st, None))
    # 参数可修正，但次数已耗尽 → 放弃
    assert merged["reflection"]["action"] == "abort"


# ══════════════════════════════════════════════════════════════════
# D. 端到端
# ══════════════════════════════════════════════════════════════════

def _run_no_warnings(**kwargs):
    """运行 Agent，并把 LangGraph 降级警告升级为错误（确保走的是 LangGraph）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        return run_agent(**kwargs)


def test_e2e_no_llm_single_step():
    st = _run_no_warnings(query="分析这片区域的坡度", bbox=BBOX, session_id="e2e-1")
    assert st["status"] == "done"
    assert st["final_answer"]
    assert len(st["tool_calls"]) >= 1
    assert "坡度" in st["final_answer"]
    # 合成地形必须被显式声明
    assert "合成地形" in st["final_answer"] or "数据说明" in st["final_answer"]


def test_e2e_multi_step_plan():
    plan = _plan_json([
        {"tool": "compute_slope", "intent": "算坡度",
         "arguments": {"bbox": BBOX, "resolution": RES}},
        {"tool": "zonal_statistics", "intent": "统计可通行面积",
         "arguments": {"bbox": BBOX, "resolution": RES, "metric": "slope"}},
    ])
    llm = MockClient([plan, '{"action":"accept"}', '{"action":"accept"}', "坡度较缓区域占比约三成。"])
    st = _run_no_warnings(
        query="这片区域有多少地方能通车", bbox=BBOX, llm=llm, session_id="e2e-2"
    )
    assert st["status"] == "done"
    tools = [c["tool"] for c in st["tool_calls"]]
    assert "compute_slope" in tools
    assert "zonal_statistics" in tools
    assert st["step_index"] == 2


def test_e2e_retry_recovers_from_bad_endpoints():
    """端到端失败重试：越界起终点 → 自动修正 → 成功。"""
    plan = _plan_json([
        {"tool": "plan_route", "intent": "规划路径",
         "arguments": {"bbox": BBOX, "resolution": RES,
                       "start_point": [103.0, 30.0], "end_point": [103.95, 30.55]}}
    ])
    llm = MockClient([plan, '{"action":"accept"}', "路径规划完成。"])
    st = _run_no_warnings(
        query="规划一条穿越研究区的路径", bbox=BBOX, llm=llm, session_id="e2e-retry"
    )
    assert st["status"] == "done"
    calls = st["tool_calls"]
    assert len(calls) >= 2, "应发生至少一次重试"
    assert calls[0]["success"] is False, "首次调用应因越界失败"
    assert calls[-1]["success"] is True, "重试后应成功"
    assert any(c["attempt"] >= 2 for c in calls)


def test_e2e_retry_exhausted_aborts():
    """LLM 持续要求重试 → 达到上限后放弃，而不是死循环。"""
    plan = _plan_json([
        {"tool": "compute_slope", "intent": "算坡度",
         "arguments": {"bbox": BBOX, "resolution": RES}}
    ])
    responses = [plan] + ['{"action":"retry","rule":"semantic","reason":"不满意","suggestion":{}}'] * 12
    llm = MockClient(responses, default_response='{"action":"accept"}')
    st = _run_no_warnings(
        query="分析坡度", bbox=BBOX, llm=llm, session_id="e2e-exhaust", max_retries=3
    )
    assert st["status"] == "failed"
    assert st["reflection"]["action"] == "abort"
    # 1 次首次 + 3 次重试 = 4 次调用，不应超过
    assert len(st["tool_calls"]) == 4, f"实际调用 {len(st['tool_calls'])} 次"
    assert st["final_answer"], "放弃后仍要向用户说明情况"


def test_e2e_state_is_json_serializable():
    st = _run_no_warnings(query="分析坡度", bbox=BBOX, session_id="e2e-json")
    json.dumps(dict(st), ensure_ascii=False, default=str)  # 不应抛异常


# ══════════════════════════════════════════════════════════════════
# E. 持久化
# ══════════════════════════════════════════════════════════════════

def test_persistence_restore_after_restart():
    from app.agent.graph import build_graph
    from app.agent.persistence import build_checkpointer

    db = os.path.join(tempfile.gettempdir(), "geoagent_pytest.sqlite")
    if os.path.exists(db):
        os.remove(db)

    cp = build_checkpointer(db)
    if cp is None:
        return  # 环境无持久化能力，跳过

    st = _run_no_warnings(
        query="分析这片区域的坡度", bbox=BBOX, session_id="persist-1", checkpointer=cp
    )
    assert st["status"] == "done"

    # 模拟服务重启：全新 graph + 全新 checkpointer，读同一个 db
    cp2 = build_checkpointer(db)
    g2 = build_graph(llm=None, checkpointer=cp2)
    snap = g2.get_state({"configurable": {"thread_id": "persist-1"}})
    restored = dict(snap.values)
    assert restored["query"] == "分析这片区域的坡度"
    assert restored["status"] == "done"
    assert restored["final_answer"]
    assert len(restored["tool_calls"]) == len(st["tool_calls"])

    history = list(g2.get_state_history({"configurable": {"thread_id": "persist-1"}}))
    assert len(history) >= 3, "应保留完整执行快照"


# ══════════════════════════════════════════════════════════════════
# F. 路由
# ══════════════════════════════════════════════════════════════════

def test_route_after_reflect_accept_with_remaining_steps():
    """两步计划的第 1 步被接受后，应回到执行继续第 2 步。

    走完整的 execute → reflect 序列，而不是手工拼状态：
    手工构造很容易漏掉"reflector 会先推进 step_index"这个隐式契约，
    从而写出看似通过、实则与真实流程不符的测试。
    """
    st = create_initial_state("统计可通行面积", bbox=BBOX)
    st = merge_patch(st, {
        "plan": [
            {"tool": "compute_slope", "intent": "算坡度",
             "arguments": {"bbox": BBOX, "resolution": RES}, "status": "pending"},
            {"tool": "zonal_statistics", "intent": "分级统计",
             "arguments": {"bbox": BBOX, "resolution": RES, "metric": "slope"},
             "status": "pending"},
        ]
    })
    st = merge_patch(st, execute_node(st))
    st = merge_patch(st, reflect_node(st, None))
    assert st["reflection"]["action"] == "accept"
    assert st["step_index"] == 1
    assert route_after_reflect(st) == "execute"


def test_route_after_reflect_accept_last_step():
    """最后一步被接受后应进入总结。"""
    st = create_initial_state("算坡度", bbox=BBOX)
    st = merge_patch(st, {"plan": [
        {"tool": "compute_slope", "intent": "x",
         "arguments": {"bbox": BBOX, "resolution": RES}, "status": "pending"}
    ]})
    st = merge_patch(st, execute_node(st))
    st = merge_patch(st, reflect_node(st, None))
    assert st["reflection"]["action"] == "accept"
    assert st["step_index"] == 1
    assert route_after_reflect(st) == "summarize"


def test_route_after_reflect_retry_and_abort():
    base = create_initial_state("x", bbox=BBOX)
    base = merge_patch(base, {"plan": [{"tool": "compute_slope", "arguments": {}}], "step_index": 0})
    assert route_after_reflect(merge_patch(base, {"reflection": {"action": "retry"}})) == "execute"
    assert route_after_reflect(merge_patch(base, {"reflection": {"action": "abort"}})) == "summarize"


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    passed, failed = 0, []
    print(f"运行 {len(tests)} 个测试\n" + "=" * 60)
    for name, fn in tests:
        t0 = time.perf_counter()
        try:
            fn()
            print(f"  ✓ {name:<48} {(time.perf_counter() - t0) * 1000:7.1f} ms")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ {name:<48} {exc}")
            failed.append((name, exc))
    print("=" * 60)
    print(f"通过 {passed}/{len(tests)}")
    if failed:
        print("\n失败详情：")
        for name, exc in failed:
            print(f"  {name}: {exc!r}")
        sys.exit(1)
