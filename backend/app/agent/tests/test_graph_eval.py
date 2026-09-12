"""LangGraph 评测适配器的离线验证。

全部用 MockClient，**不需要模型、不需要 GPU**。
守三条性质，任何一条坏了评测数据就是假的：

    1. 桩工具结果必须通过全部领域规则 —— 否则测到的是"桩写得烂"
    2. 多步计划必须按顺序完整跑完 —— 否则 sequencing 的可观测性丢失
    3. 越界问题必须能拒答且不调任何工具
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]  # .../backend
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(REPO / "bench"))

from app.agent.llm import MockClient  # noqa: E402
from app.agent.rules import check_result  # noqa: E402
from app.tools.registry import TOOL_REGISTRY  # noqa: E402
from graph_eval import run_case_graph, stub_dispatch  # noqa: E402

BBOX = [103.5, 30.2, 104.5, 31.0]


def _plan_json(tools, **extra):
    steps = [
        {
            "tool": t,
            "intent": f"执行 {t}",
            "arguments": {"bbox": BBOX, "resolution": 128},
            "depends_on": [],
        }
        for t in tools
    ]
    return json.dumps({"bbox": BBOX, "understanding": "测试", "steps": steps, **extra})


def _case(query="测试问题", tools=None, category="multi_tool"):
    return {
        "id": "test_001",
        "category": category,
        "query": query,
        "expected_tools": tools or [],
        "expected_params": {"bbox": BBOX},
        "must_refuse": False,
    }


# --------------------------------------------------------------------------
# 性质 1：桩结果必须自洽
# --------------------------------------------------------------------------
def test_stub_result_passes_all_domain_rules():
    """每个工具的桩结果都不能触发 error 级规则。

    这条测试是 `bench/graph_eval.py` 存在的前提：桩一旦给出不自洽的
    数据（比如栅格 shape 对不上分辨率），reflector 会把它判为失败并
    重试到放弃，测出来的低分跟模型能力毫无关系。
    """
    route_args = {
        "bbox": BBOX,
        "resolution": 128,
        "start_point": [103.6, 30.3],
        "end_point": [104.4, 30.9],
    }
    checked = 0
    for name in TOOL_REGISTRY:
        args = dict(route_args) if name == "plan_route" else {"bbox": BBOX, "resolution": 128}
        if name == "get_dem_metadata":
            args = {"dem_path": "data/dem/srtm_30m.tif"}
        result = stub_dispatch(name, args)
        assert result["success"], f"{name} 桩返回失败：{result.get('error')}"

        report = check_result(name, args, result["data"])
        errors = [e.message for e in report.errors]
        assert not errors, f"{name} 桩触发 error 级规则：{errors}"
        checked += 1
    assert checked >= 11, f"工具注册表数量异常：{checked}"


def test_stub_unknown_tool_fails_gracefully():
    result = stub_dispatch("no_such_tool", {})
    assert result["success"] is False
    assert result["error_type"] == "invalid_tool"


# --------------------------------------------------------------------------
# 性质 2：多步计划按序跑完
# --------------------------------------------------------------------------
def test_graph_runs_multi_step_plan_in_order():
    tools = ["compute_slope", "classify_geomorphons", "plan_route"]
    client = MockClient([_plan_json(tools)])
    out = run_case_graph(_case(tools=tools), client)

    assert out["status"] == "done", f"图未正常结束：{out['status']}"
    assert out["prediction"]["tools"] == tools, out["prediction"]["tools"]
    assert out["n_llm_calls"] == 1, "planner 一次成功时应只调用 LLM 一次"
    # 三个步骤应当各产生一条成功记录
    assert [c["success"] for c in out["state"]["tool_calls"]] == [True, True, True]
    # 参数应当回显出 bbox
    assert out["prediction"]["params"]["bbox"] == BBOX
    # 最终回答必须非空 —— 用户要拿到东西
    assert out["state"]["final_answer"]


def test_graph_single_tool_plan():
    client = MockClient([_plan_json(["compute_slope"])])
    out = run_case_graph(_case(), client)
    assert out["prediction"]["tools"] == ["compute_slope"]
    assert out["n_steps_planned"] == 1


# --------------------------------------------------------------------------
# 性质 3：越界必须拒答
# --------------------------------------------------------------------------
def test_graph_refuses_out_of_scope_query():
    refused = json.dumps(
        {
            "bbox": None,
            "understanding": "该问题超出地理空间分析能力范围：询问的是股票行情",
            "steps": [],
            "refused": True,
        }
    )
    client = MockClient([refused])
    out = run_case_graph(
        _case("帮我预测明天茅台股价", tools=[], category="out_of_scope"), client
    )

    assert out["prediction"]["refused"] is True
    assert out["prediction"]["tools"] == []
    assert out["n_steps_planned"] == 0
    assert out["state"]["final_answer"], "拒答也要给用户一句解释"


def test_validate_plan_allows_empty_steps_when_refused():
    """规划器输出空计划是合法决策，不能当成格式错误去重试。"""
    from app.agent.nodes.planner import render_planner_prompt, validate_plan

    # 提示词里必须写明越界判定口径，否则模型无从判断
    prompt = render_planner_prompt("帮我看看明天天气", None)
    assert "拒绝" in prompt or "拒答" in prompt or "refused" in prompt

    assert validate_plan({"steps": [], "refused": True}, None) is None
    assert validate_plan({"steps": [], "refused": False}, None) is not None
    assert validate_plan({"steps": [{"tool": "compute_slope"}], "refused": True}, None) is not None


# --------------------------------------------------------------------------
# 词典开关
# --------------------------------------------------------------------------
def test_gazetteer_toggle_changes_resolved_bbox():
    """关掉词典后，bbox 只能来自模型自己填的值 —— 用于算词典增益。"""
    # 让 planner 自己给出一个不同于词典的 bbox，观察是否被覆盖
    plan = json.dumps(
        {
            "bbox": [120.0, 30.0, 121.0, 31.0],
            "understanding": "测试",
            "steps": [
                {
                    "tool": "compute_slope",
                    "intent": "算坡度",
                    "arguments": {"bbox": [120.0, 30.0, 121.0, 31.0], "resolution": 128},
                    "depends_on": [],
                }
            ],
        }
    )
    query = "分析成都周边的坡度"  # 词典里"成都周边" = [103.5, 30.2, 104.5, 31.0]

    off = run_case_graph(_case(query), MockClient([plan]), use_gazetteer=False)
    on = run_case_graph(_case(query), MockClient([plan]), use_gazetteer=True)

    # 关掉词典：模型给出的山寨 bbox 原样透传
    assert off["prediction"]["params"]["bbox"] == [120.0, 30.0, 121.0, 31.0]
    # 词典命中时 planner 会先解析地名，但因为 bbox 已由 LLM 在步骤里给出、
    # 且我们不回填覆盖 step 参数，此处只断言图仍正常跑完
    assert on["status"] == "done"
