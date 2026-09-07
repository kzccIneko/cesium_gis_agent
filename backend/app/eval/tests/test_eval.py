"""评测模块测试。

为什么值得单独写测试：

评测结果是"模型优化"整条线的决策依据。如果指标算错了，
后面所有"量化档位 A 比 B 好""微调后提升 X%"的结论都是错的，
而这类错误极难事后发现。所以指标逻辑必须有测试兜底。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from backend.app.eval.metrics import (  # noqa: E402
    aggregate,
    bbox_match,
    score_case,
    tool_scores,
)
from backend.app.eval.runner import EvalRunner  # noqa: E402


# ── bbox_match ────────────────────────────────────────────────────
def test_bbox_exact():
    assert bbox_match([100.0, 30.0, 101.0, 31.0], [100.0, 30.0, 101.0, 31.0])


def test_bbox_within_tolerance():
    # 1e-6 的浮点误差必须算对
    assert bbox_match([100.0, 30.0, 101.0, 31.0], [100.000001, 30.0, 101.0, 31.0])


def test_bbox_beyond_tolerance():
    # 差 0.1 度（约 11 km）必须算错
    assert not bbox_match([100.0, 30.0, 101.0, 31.0], [100.1, 30.0, 101.0, 31.0])


def test_bbox_wrong_order_is_wrong():
    """经纬度顺序写反 = 分析范围错，不能因为数值相同就放过。"""
    assert not bbox_match([100.0, 30.0, 101.0, 31.0], [30.0, 100.0, 31.0, 101.0])


def test_bbox_none_handling():
    assert bbox_match(None, None) is True
    assert bbox_match([1, 2, 3, 4], None) is False
    assert bbox_match(None, [1, 2, 3, 4]) is False


def test_bbox_bad_length():
    assert not bbox_match([1, 2, 3], [1, 2, 3, 4])


# ── tool_scores ───────────────────────────────────────────────────
def test_tool_exact_match():
    r = tool_scores(["compute_slope"], ["compute_slope"])
    assert r["exact"] == 1.0
    assert r["set_f1"] == 1.0
    assert r["order"] == 1.0


def test_tool_sequence_order_matters():
    """调用顺序错了：集合 F1 满分，但 exact 与 order 必须扣分。"""
    exp = ["compute_slope", "compute_cost_surface", "plan_route"]
    pred = ["plan_route", "compute_cost_surface", "compute_slope"]
    r = tool_scores(exp, pred)
    assert r["set_f1"] == 1.0      # 选对了工具，只是顺序乱
    assert r["exact"] == 0.0
    assert r["order"] < 1.0        # LCS 只保留了 1 个（compute_cost_surface）


def test_tool_partial_credit():
    exp = ["compute_slope", "compute_cost_surface", "plan_route"]
    pred = ["compute_slope", "plan_route"]
    r = tool_scores(exp, pred)
    assert r["exact"] == 0.0
    assert 0.0 < r["set_f1"] < 1.0
    assert r["order"] == pytest.approx(2 / 3)


def test_tool_empty_both():
    r = tool_scores([], [])
    assert r["exact"] == 1.0


def test_tool_expected_empty_but_called():
    """该拒答却调用了工具 —— 集合 F1 为 0。"""
    r = tool_scores([], ["compute_slope"])
    assert r["set_f1"] == 0.0
    assert r["exact"] == 0.0


def test_tool_called_nothing_but_expected():
    r = tool_scores(["compute_slope"], [])
    assert r["set_f1"] == 0.0


# ── score_case ────────────────────────────────────────────────────
def test_score_single_tool_correct():
    case = {
        "id": "t1",
        "category": "single_tool",
        "expected_tools": ["compute_slope"],
        "expected_params": {"bbox": [100, 30, 101, 31]},
        "must_refuse": False,
    }
    pred = {
        "parsed": True,
        "tools": ["compute_slope"],
        "params": {"bbox": [100, 30, 101, 31]},
        "refused": False,
    }
    s = score_case(case, pred)
    assert s["completed"] == 1.0
    assert s["param_bbox"] is True
    assert s["tool_exact"] == 1.0


def test_score_single_tool_wrong_bbox():
    case = {
        "id": "t2",
        "category": "single_tool",
        "expected_tools": ["compute_slope"],
        "expected_params": {"bbox": [100, 30, 101, 31]},
        "must_refuse": False,
    }
    pred = {
        "parsed": True,
        "tools": ["compute_slope"],
        "params": {"bbox": [110, 30, 111, 31]},  # 经度差 10 度
        "refused": False,
    }
    s = score_case(case, pred)
    assert s["param_bbox"] is False
    assert s["completed"] == 0.0   # 工具对但位置错 = 任务没完成


def test_score_parse_failure():
    case = {
        "id": "t3",
        "category": "single_tool",
        "expected_tools": ["compute_slope"],
        "expected_params": {"bbox": [100, 30, 101, 31]},
        "must_refuse": False,
    }
    pred = {"parsed": False, "tools": [], "params": {}, "refused": False}
    s = score_case(case, pred)
    assert s["parsed"] == 0.0
    assert s["completed"] == 0.0


def test_score_refusal_case_correct():
    case = {
        "id": "t4",
        "category": "out_of_scope",
        "expected_tools": [],
        "expected_params": {},
        "must_refuse": True,
    }
    s = score_case(case, {"parsed": True, "tools": [], "params": {}, "refused": True})
    assert s["refusal_correct"] == 1.0
    assert s["completed"] == 1.0
    # 拒答类不适用工具/参数指标，必须为 None（否则会污染均值）
    assert s["tool_exact"] is None
    assert s["param_bbox"] is None


def test_score_refusal_case_wrong():
    case = {
        "id": "t5",
        "category": "out_of_scope",
        "expected_tools": [],
        "expected_params": {},
        "must_refuse": True,
    }
    s = score_case(
        case,
        {"parsed": True, "tools": ["compute_slope"], "params": {}, "refused": False},
    )
    assert s["refusal_correct"] == 0.0
    assert s["completed"] == 0.0


def test_score_false_refusal_penalized():
    """不该拒答却拒答，必须扣分。"""
    case = {
        "id": "t6",
        "category": "single_tool",
        "expected_tools": ["compute_slope"],
        "expected_params": {"bbox": [100, 30, 101, 31]},
        "must_refuse": False,
    }
    s = score_case(case, {"parsed": True, "tools": [], "params": {}, "refused": True})
    assert s["refusal_correct"] == 0.0
    assert s["completed"] == 0.0


def test_score_dem_path_case():
    """get_dem_metadata 类样本：没有 bbox，只看 dem_path。"""
    case = {
        "id": "t7",
        "category": "single_tool",
        "expected_tools": ["get_dem_metadata"],
        "expected_params": {"dem_path": "data/dem/a.tif"},
        "must_refuse": False,
    }
    pred = {
        "parsed": True,
        "tools": ["get_dem_metadata"],
        "params": {"dem_path": "data/dem/a.tif"},
        "refused": False,
    }
    s = score_case(case, pred)
    assert s["param_bbox"] is None   # 不适用，不参与统计
    assert s["param_dem_path"] == 1.0
    assert s["completed"] == 1.0


# ── aggregate ─────────────────────────────────────────────────────
def test_aggregate_excludes_none():
    """None 必须被排除，不能当 0 算，否则拒答类会拉低工具准确率。"""
    scores = [
        {"category": "single_tool", "completed": 1.0, "tool_exact": 1.0,
         "param_bbox": True, "refusal_correct": 1.0, "parsed": 1.0},
        {"category": "out_of_scope", "completed": 1.0, "tool_exact": None,
         "param_bbox": None, "refusal_correct": 1.0, "parsed": 1.0},
    ]
    agg = aggregate(scores)
    assert agg["n"] == 2
    assert agg["tool_exact"] == 1.0      # 只有 1 个有效值，应为 1.0 而非 0.5
    assert agg["by_category"]["out_of_scope"]["n"] == 1


def test_aggregate_empty():
    assert aggregate([]) == {"n": 0}


# ── 评测集校验 ────────────────────────────────────────────────────
def test_dataset_valid():
    """评测集必须通过 build_dataset 的全部校验。"""
    from backend.app.eval import build_dataset

    cases = build_dataset.build()
    problems = build_dataset.validate(cases)
    assert problems == [], f"评测集校验失败：{problems}"
    assert len(cases) == 100


def test_dataset_categories():
    from backend.app.eval import build_dataset

    cases = build_dataset.build()
    cats = {}
    for c in cases:
        cats[c["category"]] = cats.get(c["category"], 0) + 1
    assert cats == {"single_tool": 40, "multi_tool": 40, "out_of_scope": 20}


def test_dataset_ids_unique():
    from backend.app.eval import build_dataset

    cases = build_dataset.build()
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))


# ── EvalRunner 解析逻辑 ──────────────────────────────────────────
class _FakeResponse:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeClient:
    """返回固定响应的假客户端，用于测试解析逻辑。"""

    def __init__(self, responses):
        self._q = list(responses)

    def chat(self, messages, tools=None, temperature=0.0):
        return self._q.pop(0) if self._q else _FakeResponse("")


def test_runner_tool_calling_mode():
    runner = EvalRunner(_FakeClient([
        _FakeResponse(
            content="",
            tool_calls=[{
                "name": "compute_slope",
                "arguments": {"bbox": [100, 30, 101, 31]},
            }],
        )
    ]), mode="tool_calling", model_label="fake")

    case = {
        "id": "r1",
        "category": "single_tool",
        "query": "算坡度",
        "expected_tools": ["compute_slope"],
        "expected_params": {"bbox": [100, 30, 101, 31]},
        "must_refuse": False,
    }
    r = runner.run_case(case)
    assert r["score"]["completed"] == 1.0
    assert r["prediction"]["tools"] == ["compute_slope"]


def test_runner_json_mode():
    runner = EvalRunner(_FakeClient([
        _FakeResponse(
            content='```json\n{"tools": [{"name": "compute_slope", '
                    '"arguments": {"bbox": [100, 30, 101, 31]}}]}\n```'
        )
    ]), mode="json", model_label="fake")

    case = {
        "id": "r2",
        "category": "single_tool",
        "query": "算坡度",
        "expected_tools": ["compute_slope"],
        "expected_params": {"bbox": [100, 30, 101, 31]},
        "must_refuse": False,
    }
    r = runner.run_case(case)
    assert r["prediction"]["parsed"] is True
    assert r["score"]["completed"] == 1.0


def test_runner_json_mode_garbage():
    """模型输出非 JSON 时不能崩，必须记下原因。"""
    runner = EvalRunner(
        _FakeClient([_FakeResponse(content="我不知道该怎么做")]),
        mode="json",
        model_label="fake",
    )
    case = {
        "id": "r3",
        "category": "single_tool",
        "query": "算坡度",
        "expected_tools": ["compute_slope"],
        "expected_params": {"bbox": [100, 30, 101, 31]},
        "must_refuse": False,
    }
    r = runner.run_case(case)
    assert r["prediction"]["parsed"] is False
    assert r["prediction"]["parse_error"] is not None


def test_runner_handles_exception():
    """LLM 调用异常不能中断整轮评测。"""

    class _Boom:
        def chat(self, messages, tools=None, temperature=0.0):
            raise RuntimeError("connection refused")

    runner = EvalRunner(_Boom(), mode="tool_calling", model_label="fake")
    case = {
        "id": "r4",
        "category": "single_tool",
        "query": "算坡度",
        "expected_tools": ["compute_slope"],
        "expected_params": {"bbox": [100, 30, 101, 31]},
        "must_refuse": False,
    }
    r = runner.run_case(case)
    assert r["prediction"]["parsed"] is False
    assert "connection refused" in r["prediction"]["parse_error"]


def test_runner_invalid_mode():
    with pytest.raises(ValueError):
        EvalRunner(_FakeClient([]), mode="nope")


def test_runner_run_all_aggregates():
    runner = EvalRunner(_FakeClient([
        _FakeResponse(tool_calls=[
            {"name": "compute_slope", "arguments": {"bbox": [100, 30, 101, 31]}}
        ]),
        _FakeResponse(content="抱歉，这超出了我的能力范围"),
    ]), mode="tool_calling", model_label="fake")

    cases = [
        {
            "id": "a1", "category": "single_tool", "query": "q",
            "expected_tools": ["compute_slope"],
            "expected_params": {"bbox": [100, 30, 101, 31]},
            "must_refuse": False,
        },
        {
            "id": "a2", "category": "out_of_scope", "query": "q",
            "expected_tools": [], "expected_params": {}, "must_refuse": True,
        },
    ]
    res = runner.run_all(cases)
    assert res["summary"]["n"] == 2
    assert res["summary"]["model"] == "fake"
    assert len(res["details"]) == 2
