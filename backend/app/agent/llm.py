"""LLM 客户端抽象层。

为什么要有这一层：

1. **测试不能依赖 API key**
   编排层的测试（尤其是"失败重试"这种关键路径）必须能离线跑。
   MockClient 让测试完全可控、可复现。

2. **不能绑死某家厂商**
   用户的 LLM 可能是 DeepSeek、通义、本地 Ollama 或 OpenAI。
   它们都兼容 OpenAI 的 `/chat/completions` 协议，
   抽象成"base_url + api_key + model"三元组即可统一。

3. **JSON 解析必须容错**
   大模型输出 JSON 时经常裹 markdown 代码块、加前缀后缀、用中文引号。
   这里的 extract_json 是编排层的生命线——解析失败就整轮白跑。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Protocol

# 默认配置：本地 Ollama。用户改环境变量即可切到任何 OpenAI 兼容服务。
DEFAULT_BASE_URL = os.getenv("GEOAGENT_LLM_BASE_URL", "http://localhost:11434/v1")
DEFAULT_API_KEY = os.getenv("GEOAGENT_LLM_API_KEY", "ollama")
DEFAULT_MODEL = os.getenv("GEOAGENT_LLM_MODEL", "qwen2.5:14b")
DEFAULT_TIMEOUT = float(os.getenv("GEOAGENT_LLM_TIMEOUT", "120"))


class LLMResponse:
    """统一的 LLM 响应结构。"""

    def __init__(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        raw: Optional[Any] = None,
    ):
        self.content = content or ""
        self.tool_calls = tool_calls or []
        self.raw = raw

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def first_tool_call(self) -> Optional[Dict[str, Any]]:
        return self.tool_calls[0] if self.tool_calls else None

    def __repr__(self) -> str:
        return (
            f"LLMResponse(content={self.content[:40]!r}..., "
            f"tool_calls={len(self.tool_calls)})"
        )


class LLMClient(Protocol):
    """所有 LLM 客户端需实现的接口。"""

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        ...


# --------------------------------------------------------------------------
# JSON 提取
# --------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE
)


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中稳健地提取第一个 JSON 对象。

    依次尝试：
        1. 整体解析
        2. 抽取 ```json ... ``` 代码块
        3. 取首个 { 到最后一个 } 之间的内容
        4. 中文引号 / 全角括号归一化后重试

    Returns:
        解析出的 dict；全部失败返回 None
    """
    if not text:
        return None

    candidates = [text]

    blocks = _JSON_BLOCK_RE.findall(text)
    candidates.extend(blocks)

    # 花括号截取
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])

    for cand in candidates:
        cand = cand.strip()
        if not cand:
            continue
        for variant in (cand, _normalize_quotes(cand)):
            try:
                obj = json.loads(variant)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                continue
    return None


def _normalize_quotes(text: str) -> str:
    """中文引号 → 英文引号（模型在中文语境下高频错误）。"""
    return (
        text.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("（", "(")
        .replace("）", ")")
    )


# --------------------------------------------------------------------------
# OpenAI 兼容客户端
# --------------------------------------------------------------------------

class OpenAICompatClient:
    """OpenAI Chat Completions 兼容客户端。

    适配范围：OpenAI / DeepSeek / 通义千问 / 月之暗面 / 本地 Ollama / vLLM。

    依赖 openai 包；未安装时抛 ImportError 并给出安装提示，
    而不是在 import 阶段就炸掉整个 agent 包。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.base_url = base_url or DEFAULT_BASE_URL
        self.api_key = api_key or DEFAULT_API_KEY
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout or DEFAULT_TIMEOUT
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ImportError(
                    "使用真实 LLM 需要 openai 包：pip install openai"
                ) from exc
            self._client = OpenAI(
                base_url=self.base_url,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        client = self._ensure_client()
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        tool_calls = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tool_calls.append(
                    {"name": tc.function.name, "arguments": args or {}}
                )

        return LLMResponse(content=msg.content or "", tool_calls=tool_calls, raw=resp)


# --------------------------------------------------------------------------
# Mock 客户端（测试用）
# --------------------------------------------------------------------------

class MockClient:
    """脚本化 LLM 客户端 —— 让编排层测试完全离线、可复现。

    用法：
        client = MockClient([
            '{"steps": [...]}',                 # 第 1 次调用（planner）
            '{"valid": true, "action": "accept"}',  # 第 2 次调用（reflector）
        ])

    队列耗尽后返回 default_response（默认一个合法的 accept）。
    所有调用记录在 self.calls 中，供断言使用。
    """

    def __init__(
        self,
        responses: Optional[List[str]] = None,
        default_response: str = '{"valid": true, "action": "accept"}',
    ):
        self._queue = list(responses or [])
        self.default_response = default_response
        self.calls: List[Dict[str, Any]] = []

    def push(self, response: str) -> "MockClient":
        """追加一个脚本响应（支持链式调用）。"""
        self._queue.append(response)
        return self

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": messages,
                "tools": tools,
                "temperature": temperature,
            }
        )
        text = self._queue.pop(0) if self._queue else self.default_response
        return LLMResponse(content=text)

    @property
    def call_count(self) -> int:
        return len(self.calls)


def build_client(
    use_mock: bool = False,
    mock_responses: Optional[List[str]] = None,
    **kwargs: Any,
) -> LLMClient:
    """工厂函数。

    Args:
        use_mock: True 时用 MockClient（测试/演示）
        mock_responses: Mock 脚本
        **kwargs: 传给 OpenAICompatClient 的 base_url/api_key/model
    """
    if use_mock:
        return MockClient(mock_responses)
    return OpenAICompatClient(**kwargs)
