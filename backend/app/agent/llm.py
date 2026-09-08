"""LLM 客户端抽象层。

为什么要有这一层：

1. **测试不能依赖 API key**
   编排层的测试（尤其是"失败重试"这种关键路径）必须能离线跑。
   MockClient 让测试完全可控、可复现。

2. **不能绑死某家厂商**
   默认走**进程内嵌入式推理**（EmbeddedLlamaClient，零外部依赖）；
   如需云端能力可切 OpenAICompatClient —— DeepSeek、通义、vLLM、OpenAI
   都兼容 `/chat/completions` 协议，抽象成"base_url + api_key + model"即可。

3. **JSON 解析必须容错**
   大模型输出 JSON 时经常裹 markdown 代码块、加前缀后缀、用中文引号。
   这里的 extract_json 是编排层的生命线——解析失败就整轮白跑。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

# OpenAI 兼容后端配置（仅 GEOAGENT_LLM_BACKEND=openai 时用到）
DEFAULT_BASE_URL = os.getenv("GEOAGENT_LLM_BASE_URL", "")
DEFAULT_API_KEY = os.getenv("GEOAGENT_LLM_API_KEY", "")
DEFAULT_MODEL = os.getenv("GEOAGENT_LLM_MODEL", "")
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


# Qwen 系列原生工具调用格式（llama-cpp-python 0.3.35 不解析，必须自己来）：
#   <tool_call>
#   <function=compute_slope>
#   <parameter=bbox>
#   [103.5, 30.2, 104.5, 31.0]
#   </parameter>
#   </function>
#   </tool_call>
_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_TOOL_FUNC_RE = re.compile(r"<function=([^>]+)>(.*?)</function>", re.DOTALL)
_TOOL_PARAM_RE = re.compile(r"<parameter=([^>]+)>(.*?)</parameter>", re.DOTALL)


def parse_native_tool_calls(text: str) -> List[Dict[str, Any]]:
    """从模型正文里解析 Qwen 原生 <tool_call> 块。

    为什么需要：llama-cpp-python 0.3.35 的 chat handler 不认 Qwen 的
    <tool_call> 格式，tool_calls 字段恒为空，导致 Agent 永远以为模型没调工具。
    """
    calls: List[Dict[str, Any]] = []
    if not text:
        return calls

    for block in _TOOL_CALL_BLOCK_RE.findall(text):
        for name, body in _TOOL_FUNC_RE.findall(block):
            args: Dict[str, Any] = {}
            for key, raw in _TOOL_PARAM_RE.findall(body):
                value: Any = raw.strip()
                try:  # 参数值可能是 JSON 数组/对象，也可能是纯字符串
                    value = json.loads(value)
                except Exception:
                    pass
                args[key.strip()] = value
            calls.append({"name": name.strip(), "arguments": args})

    if not calls:
        # 退化格式：没有 <tool_call> 包裹，只有 <function=...>
        for name, body in _TOOL_FUNC_RE.findall(text):
            args = {}
            for key, raw in _TOOL_PARAM_RE.findall(body):
                try:
                    args[key.strip()] = json.loads(raw.strip())
                except Exception:
                    args[key.strip()] = raw.strip()
            calls.append({"name": name.strip(), "arguments": args})
    return calls


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

    适配范围：OpenAI / DeepSeek / 通义千问 / 月之暗面 / vLLM 等自建服务。

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


# --------------------------------------------------------------------------
# 嵌入式 llama.cpp 客户端（进程内推理，零 HTTP）
# --------------------------------------------------------------------------

# 注意：不接受 Ollama 的 blob 文件（qwen35.rope.dimension_sections 只有 3 个值，
# llama.cpp 要求 4 个），必须用 unsloth 等官方发布的 GGUF。
DEFAULT_GGUF = os.getenv(
    "GEOAGENT_GGUF",
    str(
        Path(__file__).resolve().parents[3]
        / "models"
        / "llm"
        / "Qwen3.5-4B-Q4_K_M.gguf"
    ),
)


class EmbeddedLlamaClient:
    """进程内 llama.cpp 推理客户端（**不经 HTTP**）。

    与 OpenAICompatClient 实现同一个 `chat()` 接口，但直接在 Python 进程内
    通过 ctypes 调用 libllama，没有服务进程、没有端口、没有 JSON 网络往返。

    为什么用它作为默认后端：
      - **GBNF 文法约束解码**：解码阶段强制输出合法 JSON，
        这是提升 tool-calling「JSON 合法率」的杀手锏（云端 API 的 format 做不到）
      - 部署 turnkey：不要求用户先装并启动任何外部服务
      - 模型常驻可控，空闲不会被卸载
      - 批量评测可用 batch 解码，吞吐显著高于串行 HTTP

    实测（2026-09-08，RTX 2060，Qwen3.5-4B Q4_K_M）：**51.3 tok/s**，
    TTFT 125 ms，显存 4.5 GB —— 比原 Ollama 方案（~40 tok/s）快 28%，
    故 Ollama 已于当日卸载。详见 `IMPROVEMENT_PLAN.md`。

    环境变量：
        GEOAGENT_GGUF          模型文件路径
        GEOAGENT_N_CTX         上下文长度（默认 8192）
        GEOAGENT_N_GPU_LAYERS  GPU 层数，-1 = 全放 GPU（默认）
        GEOAGENT_GRAMMAR       "1" 启用 GBNF 约束（需配合 response_schema）
    """

    # 模型单例：按 (model_path, n_ctx, n_gpu_layers) 缓存，
    # 避免重复把 2.55 GB 权重读进显存。
    _models: Dict[tuple, Any] = {}

    def __init__(
        self,
        model_path: Optional[str] = None,
        n_ctx: Optional[int] = None,
        n_gpu_layers: Optional[int] = None,
        use_grammar: Optional[bool] = None,
        verbose: bool = False,
    ):
        self.model_path = model_path or DEFAULT_GGUF
        self.n_ctx = int(n_ctx or os.getenv("GEOAGENT_N_CTX", "8192"))
        self.n_gpu_layers = int(
            n_gpu_layers
            if n_gpu_layers is not None
            else os.getenv("GEOAGENT_N_GPU_LAYERS", "-1")
        )
        self.use_grammar = (
            bool(use_grammar)
            if use_grammar is not None
            else os.getenv("GEOAGENT_GRAMMAR", "0") == "1"
        )
        self.verbose = verbose

    def _ensure_model(self):
        key = (self.model_path, self.n_ctx, self.n_gpu_layers)
        if key in self._models:
            return self._models[key]
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ImportError(
                "嵌入式推理需要 llama-cpp-python。"
                "本机 Python 3.14 无预编译 wheel，需源码编译："
                "bash D:\\llama_build\\build_lcpp.sh"
            ) from exc

        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"GGUF 模型不存在: {self.model_path}")

        self._models[key] = Llama(
            model_path=self.model_path,
            n_ctx=self.n_ctx,
            n_gpu_layers=self.n_gpu_layers,
            verbose=self.verbose,
        )
        return self._models[key]

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        response_schema: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """调用模型。

        Args:
            messages: OpenAI 格式消息列表
            tools: 工具定义（走模型原生 tool calling）
            temperature: 采样温度
            response_schema: 若提供，用 GBNF 文法强制输出符合该 JSON Schema
                            的内容（优先级高于 tools）
            max_tokens: 生成上限。不设的话模型可能一直生成到撑爆上下文
                       （实测会触发 CUDA error 并终止进程），故默认 512
        """
        llm = self._ensure_model()
        kwargs: Dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": int(
                max_tokens or os.getenv("GEOAGENT_MAX_TOKENS", "512")
            ),
        }

        # GBNF 约束优先：强制输出合法 JSON，从解码层面杜绝格式错误
        if response_schema is not None and self.use_grammar:
            try:
                from llama_cpp import LlamaGrammar

                kwargs["grammar"] = LlamaGrammar.from_json_schema(
                    json.dumps(response_schema, ensure_ascii=False)
                )
            except Exception:
                # 文法构造失败不应让整轮 Agent 崩掉，退回普通生成
                pass
        elif tools:
            kwargs["tools"] = tools

        resp = llm.create_chat_completion(**kwargs)
        msg = resp["choices"][0]["message"]

        tool_calls = []
        raw_calls = msg.get("tool_calls") or []
        if not raw_calls and msg.get("content"):
            # 兜底：Qwen 原生 <tool_call> 格式不被 llama-cpp-python 解析
            raw_calls = [
                {"function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in parse_native_tool_calls(msg["content"])
            ]
        for tc in raw_calls:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            tool_calls.append({"name": fn.get("name", ""), "arguments": args or {}})

        return LLMResponse(
            content=msg.get("content") or "", tool_calls=tool_calls, raw=resp
        )


def build_client(
    use_mock: bool = False,
    mock_responses: Optional[List[str]] = None,
    embedded: bool = False,
    **kwargs: Any,
) -> LLMClient:
    """工厂函数。

    Args:
        use_mock: True 时用 MockClient（测试/演示，完全离线）
        mock_responses: Mock 脚本
        embedded: True 时用 **进程内 llama.cpp**（默认后端，零 HTTP）
        **kwargs: 传给对应客户端的参数

    默认策略（未显式指定时）：
        GEOAGENT_LLM_BACKEND=embedded|openai，默认 embedded
    """
    if use_mock:
        return MockClient(mock_responses)

    if embedded:
        return EmbeddedLlamaClient(**kwargs)

    backend = os.getenv("GEOAGENT_LLM_BACKEND", "embedded")
    if backend == "openai":
        return OpenAICompatClient(**kwargs)
    return EmbeddedLlamaClient(**kwargs)
