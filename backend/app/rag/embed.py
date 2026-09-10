"""文本向量化：复用已编译的 llama.cpp 跑 GGUF 格式的 bge 模型。

技术选型依据
------------
1. **复用而非新增**：项目已有 llama-cpp-python 0.3.35（带 CUDA 编译），
   llama.cpp 原生支持 BERT 架构做 embedding（`embedding=True` + `.embed()`），
   因此走 GGUF 路线可以**零新增重量依赖**——不需要 sentence-transformers、
   不需要 torch（除一次性格式转换外）、不需要 transformers。

2. **模型体积守 5GB 红线**：bge-small-zh-v1.5 是 24M 参数、512 维，
   FP16 GGUF 约 190MB、Q8_0 约 96MB。而 bge-m3 是 568M 参数 / 2.27GB，
   与已有的 Qwen3.5-4B（2.55GB）相加会直接顶到用户设定的模型总量上限。
   在**只有数百块的垂直语料**上，两者的检索质量差距远小于体积差距。

3. **默认跑 CPU，不占用 GPU**：这是刻意的选择，
   - embedding 模型极小，293 块 × 512 token 在 8 核 CPU 上数秒完成，GPU 无必要；
   - 本机（联想 Y7000P / RTX 2060）已证实持续满载会热降频甚至触发 CUDA error，
     把 embedding 留给 CPU 可以**不打扰主 LLM 的显存与散热预算**。

超长文本处理
------------
bge 的最大序列长度是 512 token，而本语料有少量超过 1000 字符的块（整页 PDF）。
直接 truncate 会静默丢掉后半段语义，使这些块几乎不可能被召回。
这里改用**带重叠窗口 + 平均池化**：把长文本切成重叠的窗口分别编码后取平均，
语义覆盖完整，代价只是多几次前向。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL = REPO_ROOT / "models" / "embedding" / "bge-small-zh-v1.5-q8_0.gguf"
FALLBACK_MODEL = REPO_ROOT / "models" / "embedding" / "bge-small-zh-v1.5-f16.gguf"

MAX_SEQ = 512          # bge 的最大序列
WINDOW_STRIDE = 0.75   # 窗口步长比例（重叠 25%）


class Embedder:
    """嵌入器接口 —— 便于注入伪实现做离线测试。"""

    dim: int = 512

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        raise NotImplementedError

    def embed_query(self, text: str) -> np.ndarray:
        raise NotImplementedError


class LlamaCppEmbedder(Embedder):
    """用 llama.cpp 加载 GGUF 格式的 bge 模型。"""

    def __init__(
        self,
        model_path: Optional[Path] = None,
        n_ctx: int = MAX_SEQ,
        n_gpu_layers: int = 0,
        n_threads: Optional[int] = None,
        verbose: bool = False,
    ) -> None:
        self.model_path = Path(model_path) if model_path else self._auto_path()
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"找不到 embedding 模型：{self.model_path}\n"
                f"请先把 bge-small-zh-v1.5 转成 GGUF 放到 models/embedding/ 下。"
            )
        self._llm = self._load(self.model_path, n_ctx, n_gpu_layers, n_threads, verbose)

    @staticmethod
    def _auto_path() -> Path:
        env = os.environ.get("GEOAGENT_EMBED_MODEL")
        if env:
            return Path(env)
        return DEFAULT_MODEL if DEFAULT_MODEL.exists() else FALLBACK_MODEL

    @staticmethod
    def _load(path: Path, n_ctx: int, n_gpu_layers: int, n_threads: Optional[int], verbose: bool):
        from llama_cpp import Llama

        return Llama(
            model_path=str(path),
            embedding=True,
            n_ctx=n_ctx,
            n_batch=n_ctx,
            n_gpu_layers=n_gpu_layers,   # 默认 0：见模块 docstring 第 3 点
            n_threads=n_threads,
            verbose=verbose,
        )

    # ---------------- 内部 ----------------

    def _tokens(self, text: str) -> List[int]:
        return self._llm.tokenize(text.encode("utf-8"), add_bos=True, special=True)

    def _encode_one(self, text: str) -> np.ndarray:
        """单条编码。超过 MAX_SEQ 时用重叠窗口 + 平均池化。"""
        toks = self._tokens(text)
        if len(toks) <= MAX_SEQ:
            return np.asarray(self._llm.embed(text, normalize=False), dtype=np.float32)

        # 估算窗口字符数：<｜hy_place▁holder▁no▁813｜> 用实际 token 反推更准，但开销大；
        # 这里按字符/token 比保守换算，再用 rfind 落在句子边界上避免切坏句子。
        ratio = max(len(text) / max(len(toks), 1), 0.3)
        window_chars = int(MAX_SEQ * ratio * 0.9)
        step_chars = max(int(window_chars * WINDOW_STRIDE), 200)

        pieces: List[str] = []
        start = 0
        while start < len(text):
            end = min(start + window_chars, len(text))
            if end < len(text):
                for sep in ("。", "\n\n", "；", "\n"):
                    cut = text.rfind(sep, start + step_chars // 2, end)
                    if cut > start:
                        end = cut + len(sep)
                        break
            pieces.append(text[start:end].strip())
            if end >= len(text):
                break
            start = max(end - int(window_chars * (1 - WINDOW_STRIDE)), start + 1)

        pieces = [p for p in pieces if p]
        if not pieces:
            return np.asarray(self._llm.embed(text[:window_chars], normalize=False), dtype=np.float32)

        vecs = np.stack(
            [np.asarray(self._llm.embed(p, normalize=False), dtype=np.float32) for p in pieces]
        )
        return vecs.mean(axis=0)

    # ---------------- 对外 ----------------

    def embed_documents(self, texts: Sequence[str], batch_size: int = 8) -> np.ndarray:
        out: List[np.ndarray] = []
        for t in texts:
            out.append(self._encode_one(t))
        return np.stack(out) if out else np.zeros((0, self.dim), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode_one(text)


class HashEmbedder(Embedder):
    """无模型的确定性伪嵌入 —— 只为离线测试 / CI 使用。

    它保留了「字面相似的文本向量更接近」这一性质（基于 token 频次），
    因此 store / retriever 的逻辑可以被真实地测到，不需要下载模型。
    检索质量当然不能代表真模型，测试里不会依赖具体的相似度数值。
    """

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _simple_tokens(text):
            h = _fnv(tok)
            v[h % self.dim] += 1.0
            v[(h >> 16) % self.dim] += 0.5
        nrm = np.linalg.norm(v)
        return v / nrm if nrm > 0 else v

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


def _simple_tokens(text: str) -> List[str]:
    import re

    cjk = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    units = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z]+|\d+", text.lower())
    return units + ["".join(cjk[i : i + 2]) for i in range(len(cjk) - 1)]


def _fnv(s: str) -> int:
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h
