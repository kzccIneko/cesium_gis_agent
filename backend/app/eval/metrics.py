"""评测指标计算。

设计原则：

1. **全部是纯函数** —— 输入 (case, prediction)，输出分数 dict。
   不碰 LLM、不碰文件系统，因此可以单测，也方便换模型复现。

2. **指标分层** —— 工具调用是链式过程，一个数字说不清问题：
    JSON 解析失败 → 工具选错 → 参数填错 → 越界不拒答，
   每一层失败的原因完全不同，必须分开统计才有诊断价值。

3. **bbox 允许数值容差** —— 模型输出的经纬度几乎不可能与 ground truth 逐位相同，
   1e-6 的误差不应算错；但误差超过 0.01°（约 1 km）就算定位错误。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# bbox 允许的绝对误差（度）。0.01° ≈ 1.1 km，足够宽容又不会放过真错。
BBOX_TOLERANCE = 0.01


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def bbox_match(
    expected: Optional[Sequence[float]],
    actual: Optional[Sequence[float]],
    tolerance: float = BBOX_TOLERANCE,
) -> bool:
    """判断两个 bbox 是否在容差内一致。

    顺序 [west, south, east, north] 必须一致——顺序错了等同于分析范围错了，
    这是地理空间任务最常见的致命错误，不能因为"数值对"就放过。
    """
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if len(expected) != 4 or len(actual) != 4:
        return False
    for e, a in zip(expected, actual):
        if not _is_number(e) or not _is_number(a):
            return False
        if abs(float(e) - float(a)) > tolerance:
            return False
    return True


def _lcs_length(a: Sequence[str], b: Sequence[str]) -> int:
    """最长公共子序列长度 —— 衡量工具调用顺序的保持程度。"""
    if not a or not b:
        return 0
    # 期望序列很短（≤4），O(n*m) 动态规划足够
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[len(a)][len(b)]


def tool_scores(
    expected: Sequence[str], predicted: Sequence[str]
) -> Dict[str, float]:
    """工具选择的多维评分。

    Returns:
        exact:   序列完全一致（最严格）
        set_f1:  集合层面 F1（不管顺序，容忍多调用/少调用）
        order:   LCS / 期望长度（衡量调用顺序是否正确保留）
    """
    expected = list(expected or [])
    predicted = list(predicted or [])

    exact = 1.0 if expected == predicted else 0.0

    if not expected and not predicted:
        return {"exact": 1.0, "set_f1": 1.0, "order": 1.0}
    if not expected or not predicted:
        # 一个为空另一个非空：集合 F1 与顺序分都是 0
        return {"exact": exact, "set_f1": 0.0, "order": 0.0}

    set_e, set_p = set(expected), set(predicted)
    tp = len(set_e & set_p)
    precision = tp / len(set_p) if set_p else 0.0
    recall = tp / len(set_e) if set_e else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    order = _lcs_length(expected, predicted) / len(expected)
    return {"exact": exact, "set_f1": f1, "order": order}


def param_scores(
    expected: Dict[str, Any], actual: Dict[str, Any]
) -> Dict[str, float]:
    """参数准确率。

    目前重点关注 bbox（绝大多数工具的核心参数）。
    其他参数（resolution / output_format 等）有默认值，填错影响较小，
    单独统计但不计入主指标，避免稀释核心信号。
    """
    exp_bbox = (expected or {}).get("bbox")
    act_bbox = (actual or {}).get("bbox")

    # ground truth 没有 bbox（如 get_dem_metadata 只看文件路径）时，
    # 不参与 bbox 评分，返回 None 由上层排除
    bbox_ok = bbox_match(exp_bbox, act_bbox) if exp_bbox is not None else None

    exp_dem = (expected or {}).get("dem_path")
    dem_ok = None
    if exp_dem is not None:
        dem_ok = 1.0 if (actual or {}).get("dem_path") == exp_dem else 0.0

    return {"bbox": bbox_ok, "dem_path": dem_ok}


def score_case(case: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
    """对单条样本打分。

    Args:
        case:       评测集条目（dataset.json 中的一项）
        prediction: 模型/Agent 的预测结果，结构为
                    {
                      "parsed": bool,        # 输出能否被解析
                      "tools": [str, ...],   # 调用的工具名序列（按调用顺序）
                      "params": {...},       # 关键参数（至少含 bbox）
                      "refused": bool,       # 是否拒答
                    }

    Returns:
        分数 dict，各字段为 0/1 或 None（None = 此项不适用，不计入平均）
    """
    parsed = bool(prediction.get("parsed", False))
    tools = prediction.get("tools") or []
    params = prediction.get("params") or {}
    refused = bool(prediction.get("refused", False))
    must_refuse = bool(case.get("must_refuse", False))

    out: Dict[str, Any] = {
        "id": case.get("id"),
        "category": case.get("category"),
        "parsed": 1.0 if parsed else 0.0,
    }

    # ── 越界拒答类：唯一标准是"是否拒答" ──
    if must_refuse:
        out["refusal_correct"] = 1.0 if refused else 0.0
        # 拒答类不看工具与参数
        out["tool_exact"] = None
        out["tool_set_f1"] = None
        out["tool_order"] = None
        out["param_bbox"] = None
        out["completed"] = 1.0 if refused else 0.0
        return out

    ts = tool_scores(case.get("expected_tools") or [], tools)
    ps = param_scores(case.get("expected_params") or {}, params)

    out["tool_exact"] = ts["exact"]
    out["tool_set_f1"] = ts["set_f1"]
    out["tool_order"] = ts["order"]
    out["param_bbox"] = ps["bbox"]
    out["param_dem_path"] = ps["dem_path"]
    out["refusal_correct"] = 0.0 if refused else 1.0  # 不该拒答却拒了 = 错

    # 任务完成 = 解析成功 且 工具序列完全正确 且 (bbox 正确或不适用)
    bbox_ok = ps["bbox"]
    completed = (
        parsed
        and ts["exact"] == 1.0
        and (bbox_ok is None or bbox_ok is True)
    )
    out["completed"] = 1.0 if completed else 0.0
    return out


def aggregate(scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    """汇总多条样本分数。

    只统计非 None 的值——不同类别样本适用的指标不同，
    用 None 排除而不是填 0，否则会系统性低估。
    """
    if not scores:
        return {"n": 0}

    keys = [
        "parsed", "tool_exact", "tool_set_f1", "tool_order",
        "param_bbox", "param_dem_path", "refusal_correct", "completed",
    ]
    agg: Dict[str, Any] = {"n": len(scores)}

    for k in keys:
        vals = [s[k] for s in scores if s.get(k) is not None]
        agg[k] = (sum(vals) / len(vals)) if vals else None

    # 按类别细分
    by_cat: Dict[str, Any] = {}
    cats = sorted({s.get("category") for s in scores if s.get("category")})
    for c in cats:
        sub = [s for s in scores if s.get("category") == c]
        by_cat[c] = {
            "n": len(sub),
            "completed": _mean(sub, "completed"),
            "tool_exact": _mean(sub, "tool_exact"),
            "param_bbox": _mean(sub, "param_bbox"),
            "refusal_correct": _mean(sub, "refusal_correct"),
        }
    agg["by_category"] = by_cat
    return agg


def _mean(scores: List[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [s[key] for s in scores if s.get(key) is not None]
    return (sum(vals) / len(vals)) if vals else None
