"""反思节点：判定工具结果是否可用，并决定 接受 / 重试 / 放弃。

决策权分配（本文件最重要的设计）：

    代码规则  判定为 error  →  必须重试或放弃，LLM 无权放行
    代码规则  判定无 error  →  交 LLM 做语义复核，LLM 可否决并要求重试
    LLM 不可用 / 输出非法   →  信任代码规则，直接接受

**为什么代码优先级更高？**
数值越界、路径短于直线距离、起终点在区域外 —— 这些是客观错误，
LLM 的"看起来没问题"不能推翻它们。反过来，代码查不出
"用户问了坡度和坡向但只算了坡度"这类语义遗漏，需要 LLM 补位。
两者是正交关系，不是投票关系。

重试策略：
    - 优先使用规则给出的 suggestion（精确修正，如把越界点夹回 bbox）
    - 无 suggestion 时，按错误类型套用通用修正（如降分辨率、换分类方法）
    - 重试次数耗尽 → abort，并把已获得的部分结果交给总结节点
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm import LLMClient, extract_json
from ..rules import (
    LEVEL_ERROR,
    LEVEL_WARN,
    check_arguments,
    check_result,
    collect_warnings,
)
from ..state import (
    AgentState,
    STATUS_FAILED,
    STATUS_REFLECTING,
    append_trace,
    current_step,
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# 动作
ACTION_ACCEPT = "accept"
ACTION_RETRY = "retry"
ACTION_ABORT = "abort"

# 需要降分辨率重试的错误
_RESOLUTION_ERRORS = {"invalid_resolution", "all_nodata"}


def _generic_fix(
    tool: str,
    arguments: Dict[str, Any],
    error_type: Optional[str],
    error: Optional[str],
) -> Optional[Dict[str, Any]]:
    """规则未给出精确修正时，按错误类型套用通用修正策略。"""
    args = dict(arguments)

    if error_type in _RESOLUTION_ERRORS:
        res = args.get("resolution")
        if isinstance(res, int) and res > 64:
            args["resolution"] = max(64, res // 2)
            return args

    if error_type == "invalid_bbox":
        bbox = args.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                w, s, e, n = [float(v) for v in bbox]
            except (TypeError, ValueError):
                return None
            # 常见错误：纬度经度顺序颠倒，或南北/东西颠倒
            if w > e:
                w, e = e, w
            if s > n:
                s, n = n, s
            if abs(w) > 90 and abs(e) > 90:
                return None
            if abs(s) <= 90 and abs(n) <= 90 and abs(w) > 90:
                w, s, e, n = s, w, n, e  # 经纬度互换
            args["bbox"] = [w, s, e, n]
            return args

    if tool == "classify_terrain_onnx" and error_type in (
        "invalid_resolution", "computation_failed"
    ):
        return None  # 换工具由上层处理

    if error_type == "invalid_point":
        return None

    if error and "超时" in str(error):
        res = args.get("resolution")
        if isinstance(res, int) and res > 64:
            args["resolution"] = max(64, res // 2)
            return args
    return None


def _pick_suggestion(rule_report, tool: str, arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从规则报告中挑一个可执行的修正建议。"""
    for r in rule_report.errors:
        if r.suggestion:
            return dict(r.suggestion)
    return None


def render_reflector_prompt(
    tool: str,
    arguments: Dict[str, Any],
    result: Dict[str, Any],
    rule_report_text: str,
    query: str,
    attempt: int,
    max_retries: int,
) -> str:
    template = (PROMPTS_DIR / "reflector.txt").read_text(encoding="utf-8")
    return (
        template.replace("{{TOOL}}", tool)
        .replace("{{ARGUMENTS}}", str(arguments))
        .replace("{{QUERY}}", query)
        .replace("{{RESULT}}", str(result)[:4000])
        .replace("{{RULE_REPORT}}", rule_report_text)
        .replace("{{ATTEMPT}}", str(attempt))
        .replace("{{MAX_RETRIES}}", str(max_retries))
    )


def reflect_node(state: AgentState, llm: Optional[LLMClient]) -> Dict[str, Any]:
    """反思节点。

    Returns:
        patch：reflection / retry_count / step_index / plan / status / trace
    """
    trace = list(state.get("trace") or [])
    result = state.get("last_result") or {}
    step = current_step(state)
    tool = (step or {}).get("tool", "")
    arguments = dict((step or {}).get("arguments") or {})
    query = state.get("query", "")
    max_retries = state.get("max_retries", 3)
    retry_count = state.get("retry_count", 0)
    attempt = retry_count + 1
    # 已重试 retry_count 次，还可再试几次。
    # 注意不要用 attempt < max_retries —— 那会少给一次重试机会
    # （max_retries=3 本该允许 1 次首次 + 3 次重试 = 4 次调用）。
    can_retry = retry_count < max_retries
    idx = state.get("step_index", 0)

    if not result:
        trace.append("反思节点收到空结果 —— 判定放弃")
        return {
            "reflection": {
                "valid": False, "action": ACTION_ABORT,
                "rule": "no_result", "reason": "没有可校验的工具结果",
                "suggestion": None, "source": "code",
            },
            "status": STATUS_FAILED,
            "trace": trace,
        }

    success = bool(result.get("success"))
    error_type = result.get("error_type")
    data = result.get("data") or {}

    # ---------- 第一层：代码规则 ----------
    if success:
        report = check_result(tool, arguments, data)
        report_text = report.format_for_prompt()
        code_errors = report.errors
        code_warnings = report.warnings
    else:
        # 工具失败时改跑「参数类规则」，在重试前先把明显的参数错误修掉。
        # 否则 Agent 会拿同一组错误参数重试 N 次，最后还是失败。
        report = check_arguments(tool, arguments)
        report_text = (
            "（工具调用失败，仅执行参数类规则校验）\n" + report.format_for_prompt()
        )
        code_errors = report.errors
        code_warnings = report.warnings
        retryable = bool(result.get("retryable"))
        if not retryable:
            # 不可重试的致命错误 —— 直接放弃
            trace.append(f"工具返回不可重试错误 {error_type}，判定放弃")
            return {
                "reflection": {
                    "valid": False, "action": ACTION_ABORT,
                    "rule": f"fatal:{error_type}",
                    "reason": str(result.get("error")),
                    "suggestion": None, "source": "code",
                },
                "status": STATUS_FAILED,
                "trace": trace,
            }

    # ---------- 第二层：LLM 语义复核 ----------
    # 仅在代码未判 error 时才问 LLM：代码判错时结论已确定，不必浪费一次调用。
    llm_verdict: Optional[Dict[str, Any]] = None
    if not code_errors and llm is not None:
        try:
            prompt = render_reflector_prompt(
                tool, arguments, result, report_text, query, attempt, max_retries
            )
            resp = llm.chat([{"role": "user", "content": prompt}], temperature=0.0)
            obj = extract_json(resp.content)
            if isinstance(obj, dict) and obj.get("action") in (
                ACTION_ACCEPT, ACTION_RETRY, ACTION_ABORT
            ):
                llm_verdict = obj
                trace.append(
                    f"LLM 语义复核：{obj.get('action')} —— {str(obj.get('reason'))[:100]}"
                )
            else:
                trace.append("LLM 语义复核输出非法，信任代码判定")
        except Exception as exc:
            trace.append(f"LLM 语义复核异常（{type(exc).__name__}），信任代码判定")

    # ---------- 第三层：仲裁 ----------
    if code_errors:
        action = ACTION_RETRY if can_retry else ACTION_ABORT
        suggestion = _pick_suggestion(report, tool, arguments) if report else None
        if suggestion is None and action == ACTION_RETRY:
            suggestion = _generic_fix(tool, arguments, error_type, result.get("error"))
        reason = "；".join(e.message for e in code_errors)
        rule_name = ",".join(e.rule for e in code_errors)
        source = "code"
        trace.append(f"代码规则判定失败（{rule_name}），决策：{action}")
    elif llm_verdict and llm_verdict.get("action") == ACTION_RETRY:
        if can_retry:
            action = ACTION_RETRY
            suggestion = llm_verdict.get("suggestion") or None
            if isinstance(suggestion, dict):
                merged = dict(arguments)
                merged.update(suggestion)
                suggestion = merged
            reason = str(llm_verdict.get("reason") or "LLM 判定结果不可用")
            rule_name = str(llm_verdict.get("rule") or "llm_semantic")
            source = "llm"
            trace.append("LLM 判定结果不足以回答问题，决策：重试")
        else:
            # 关键：LLM 认为结果不可用但重试次数已耗尽时，绝不能降级为 accept。
            # 否则 Agent 会拿一个自己判定为不合格的结果去回答用户。
            action = ACTION_ABORT
            suggestion = None
            reason = (
                f"已达重试上限（{max_retries} 次），LLM 仍判定结果不可用："
                f"{llm_verdict.get('reason')}"
            )
            rule_name = str(llm_verdict.get("rule") or "llm_semantic")
            source = "llm"
            trace.append("LLM 要求重试但重试次数已耗尽，决策：放弃")
    elif llm_verdict and llm_verdict.get("action") == ACTION_ABORT:
        action = ACTION_ABORT
        suggestion = None
        reason = str(llm_verdict.get("reason") or "LLM 判定放弃")
        rule_name = str(llm_verdict.get("rule") or "llm_semantic")
        source = "llm"
    else:
        action = ACTION_ACCEPT
        suggestion = None
        reason = "结果通过全部校验"
        rule_name = "all_passed"
        source = "code"

    # ---------- 生成 patch ----------
    reflection: Dict[str, Any] = {
        "valid": action == ACTION_ACCEPT,
        "action": action,
        "rule": rule_name,
        "reason": reason,
        "suggestion": suggestion,
        "source": source,
        "attempt": attempt,
        "rule_report": report.to_dict() if report else None,
        "warnings": collect_warnings(data) if success else [],
        "code_warnings": [w.message for w in code_warnings],
    }

    plan: List[Dict[str, Any]] = [dict(s) for s in (state.get("plan") or [])]
    patch: Dict[str, Any] = {"reflection": reflection, "trace": trace}

    if action == ACTION_ACCEPT:
        patch["step_index"] = idx + 1
        patch["retry_count"] = 0
        patch["status"] = STATUS_REFLECTING
    elif action == ACTION_RETRY:
        if suggestion and 0 <= idx < len(plan):
            plan[idx]["arguments"] = suggestion
            plan[idx]["status"] = "pending"
            trace.append(f"  修正参数后重试：{ {k: v for k, v in suggestion.items() if k != 'bbox'} }")
        patch["plan"] = plan
        patch["retry_count"] = attempt
        patch["status"] = STATUS_REFLECTING
    else:  # abort
        patch["status"] = STATUS_FAILED
        patch["reflection"] = reflection

    patch["trace"] = trace
    return patch
