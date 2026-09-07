"""评测执行器：把评测集跑在指定 LLM 上并打分。

为什么要单独一个 runner 而不是复用 agent.runner：

1. 评测的是**模型的工具调用能力**，不是 Agent 端到端能力。
   这里每一步只做"给 query + tools → 看模型选什么工具、填什么参数"，
   默认**不真实执行工具**（不下载 SRTM、不算坡度），
   否则 100 条 × 4 组消融会跑几个小时，而且网络失败会污染评测结果。

2. 需要记录延迟、token 消耗、解析失败原因等诊断信息，
   Agent runner 不关心这些。

3. 支持两种调用模式，用于对比"原生 function calling"与"JSON 输出"的差异：
       mode="tool_calling" —— 走 OpenAI tools 协议（Ollama / Qwen 支持）
       mode="json"         —— 要求模型直接输出 JSON，再用 extract_json 解析
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ..agent.llm import LLMClient, extract_json
from ..tools.registry import get_openai_tools
from .metrics import aggregate, score_case

# 让模型以 JSON 形式给出工具计划的提示词（mode="json" 时使用）
JSON_MODE_SYSTEM = """你是一个地理空间分析助手。根据用户的问题，选择合适的工具并给出参数。

只输出 JSON，不要有任何其他文字，格式如下：
{"tools": [{"name": "工具名", "arguments": {"参数名": "参数值"}}]}

如果用户的问题超出地理空间分析能力范围（如天气预测、股票、医学、法律、
外星天体等），输出：{"tools": [], "refused": true}

可用工具见 tools 定义。注意 bbox 顺序固定为 [西经, 南纬, 东经, 北纬]。"""

TOOL_MODE_SYSTEM = """你是一个地理空间分析助手，负责为用户的地理空间分析请求选择合适的工具。

如果用户的问题超出地理空间分析能力范围（如天气预测、股票、医学、法律、
外星天体、月球火星地形等），不要调用任何工具，直接说明这超出了你的能力范围。

注意：bbox 顺序固定为 [西经, 南纬, 东经, 北纬]，即 [west, south, east, north]。"""


class EvalRunner:
    """在评测集上运行指定 LLM。"""

    def __init__(
        self,
        client: LLMClient,
        mode: str = "tool_calling",
        tools: Optional[List[Dict[str, Any]]] = None,
        model_label: str = "unknown",
    ):
        """
        Args:
            client: LLM 客户端（OpenAICompatClient 或 MockClient）
            mode:   "tool_calling" | "json"
            tools:  OpenAI 格式工具定义；None 表示全部工具
            model_label: 模型标识，写入结果文件便于对比
        """
        if mode not in ("tool_calling", "json"):
            raise ValueError(f"未知 mode: {mode!r}")
        self.client = client
        self.mode = mode
        self.tools = tools if tools is not None else get_openai_tools()
        self.model_label = model_label

    # ------------------------------------------------------------------
    def _build_messages(self, query: str) -> List[Dict[str, Any]]:
        system = TOOL_MODE_SYSTEM if self.mode == "tool_calling" else JSON_MODE_SYSTEM
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": query},
        ]

    def _parse_prediction(self, resp: Any) -> Dict[str, Any]:
        """把 LLM 响应解析成统一的 prediction 结构。

        这是评测的**生命线**：解析失败要给出原因，便于定位是模型问题还是代码问题。
        """
        out: Dict[str, Any] = {
            "parsed": False,
            "tools": [],
            "params": {},
            "refused": False,
            "parse_error": None,
            "raw_head": None,
        }

        if self.mode == "tool_calling":
            calls = getattr(resp, "tool_calls", None) or []
            content = getattr(resp, "content", "") or ""
            out["raw_head"] = (content or "")[:200]

            if calls:
                out["parsed"] = True
                out["tools"] = [c.get("name", "") for c in calls]
                # 参数合并：多工具时取第一个含 bbox 的（多数场景 bbox 相同）
                merged: Dict[str, Any] = {}
                for c in calls:
                    args = c.get("arguments") or {}
                    if isinstance(args, dict):
                        for k, v in args.items():
                            merged.setdefault(k, v)
                out["params"] = merged
            else:
                # 没调用工具 —— 可能是正确拒答，也可能是模型没理解
                out["parsed"] = True
                out["refused"] = _looks_like_refusal(content)
            return out

        # ---- JSON 模式 ----
        text = getattr(resp, "content", "") or ""
        out["raw_head"] = text[:200]
        obj = extract_json(text)
        if obj is None:
            out["parse_error"] = "extract_json 未能解析出 JSON 对象"
            return out

        out["parsed"] = True
        if obj.get("refused"):
            out["refused"] = True
            return out

        tools_raw = obj.get("tools") or []
        if isinstance(tools_raw, dict):
            tools_raw = [tools_raw]
        names: List[str] = []
        merged = {}
        for t in tools_raw:
            if not isinstance(t, dict):
                continue
            name = t.get("name")
            if name:
                names.append(name)
            args = t.get("arguments") or {}
            if isinstance(args, dict):
                for k, v in args.items():
                    merged.setdefault(k, v)
        out["tools"] = names
        out["params"] = merged
        out["refused"] = _looks_like_refusal(text) if not names else False
        return out

    # ------------------------------------------------------------------
    def run_case(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """跑单条样本，返回 (分数, 预测, 耗时)。"""
        messages = self._build_messages(case["query"])
        kwargs: Dict[str, Any] = {}
        if self.mode == "tool_calling":
            kwargs["tools"] = self.tools

        t0 = time.perf_counter()
        try:
            resp = self.client.chat(messages, temperature=0.0, **kwargs)
            prediction = self._parse_prediction(resp)
        except Exception as exc:  # 网络/超时/OOM 都不能中断整轮评测
            prediction = {
                "parsed": False,
                "tools": [],
                "params": {},
                "refused": False,
                "parse_error": f"调用异常: {type(exc).__name__}: {exc}",
                "raw_head": None,
            }
        elapsed = time.perf_counter() - t0

        score = score_case(case, prediction)
        return {
            "score": score,
            "prediction": prediction,
            "elapsed": elapsed,
            "query": case["query"],
        }

    def run_all(
        self, cases: List[Dict[str, Any]], verbose: bool = False
    ) -> Dict[str, Any]:
        """跑完整评测集。"""
        scores: List[Dict[str, Any]] = []
        details: List[Dict[str, Any]] = []
        t_start = time.perf_counter()

        for i, case in enumerate(cases, 1):
            r = self.run_case(case)
            scores.append(r["score"])
            details.append({
                "id": case["id"],
                "category": case["category"],
                "query": case["query"],
                "expected_tools": case.get("expected_tools"),
                "predicted_tools": r["prediction"]["tools"],
                "predicted_params": r["prediction"]["params"],
                "refused": r["prediction"]["refused"],
                "parsed": r["prediction"]["parsed"],
                "parse_error": r["prediction"].get("parse_error"),
                "elapsed": round(r["elapsed"], 3),
                "score": r["score"],
            })
            if verbose:
                print(
                    f"[{i}/{len(cases)}] {case['id']} "
                    f"完成={r['score'].get('completed')} "
                    f"工具={r['prediction']['tools']} "
                    f"({r['elapsed']:.2f}s)"
                )

        total = time.perf_counter() - t_start
        agg = aggregate(scores)
        agg["model"] = self.model_label
        agg["mode"] = self.mode
        agg["total_elapsed"] = round(total, 2)
        agg["avg_latency"] = round(total / len(cases), 3) if cases else 0.0
        return {"summary": agg, "details": details}


_REFUSAL_HINTS = (
    "超出", "无法", "不能", "不在", "范围", "抱歉", "无能为力",
    "能力之外", "不支持", "无法提供", "无法完成", "没有相关",
    "cannot", "unable", "sorry", "out of scope", "beyond",
)


def _looks_like_refusal(text: str) -> bool:
    """判断文本是否是拒答。

    简单关键词匹配即可：拒答话术有限，且这类判断只用于辅助指标。
    真正决定越界类样本成败的是"有没有调用工具"。
    """
    if not text:
        return False
    low = text.lower()
    return any(h in low for h in _REFUSAL_HINTS)


def load_dataset(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """加载评测集。"""
    if path is None:
        path = _default_dataset_path()
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _default_dataset_path() -> str:
    import os

    return os.path.join(os.path.dirname(__file__), "dataset.json")
