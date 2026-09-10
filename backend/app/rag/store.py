"""向量 / 稀疏索引的构建与加载。

为什么不用 Chroma / FAISS：

本知识库规模是 **293 块 × 512 维**——浮点矩阵总共约 **600 KB**，
一次余弦相似度矩阵乘法在这个量级上是毫秒级完成的。
Chroma 为十万级以上向量设计，附带服务端/依赖 DLL 体积与版本风险；
FAISS 的价值在于近似检索与分片，而我们在精确暴力检索下就已经足够快。

引入它们的收益 ≈ 0，成本是：额外依赖、（对本机已很脆弱的 GPU 环境而言）
额外的运行时风险、以及简历上多写一个用不上的组件。
因此这里用 NumPy 精确检索 + 纯 Python BM25，**零新增重量依赖**。

这里同时保留**稀疏检索（BM25）**，原因是密集向量的典型失效场景：
专业名词、型号编号、公式符号（如 "IGA*" "云壤;i>0" 这类 token）
向量模型往往映射到相近区域而丧失区分度，而字面匹配能精确命中。
两者用 RRF 融合，是当前 RAG 的主流做法。
"""

from __future__ import annotations

import json
import math
import pickle
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .ingest import DEFAULT_INDEX_DIR, Chunk, load_chunks

# BM25 参数（Robertson 经典取值）
K1 = 1.5
B = 0.75

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z]+|\d+")


def tokenize(text: str) -> List[str]:
    """中英文混合分词：中文取 unigram + bigram，英文数字取整词。

    中文不用分词器（jieba 之类）：一是零依赖，二是 bigram 检索对短查询
    的召回通常优于严格分词，且不存在新词识别失败的问题。
    """
    cjk = [c for c in text if "\u4e00" <= c <= "\u9fff"]
    units = _TOKEN_RE.findall(text.lower())

    toks: List[str] = list(units)
    # 中文 bigram
    toks.extend("".join(cjk[i : i + 2]) for i in range(len(cjk) - 1))
    return toks


class BM25:
    """极简 BM25，纯 Python，pickle 落盘。"""

    def __init__(self) -> None:
        self.df: Dict[str, int] = defaultdict(int)
        self.tf: List[Counter] = []
        self.doc_len: List[int] = []
        self.avg_len: float = 0.0
        self.n: int = 0

    def fit(self, docs: Sequence[str]) -> "BM25":
        self.tf = []
        self.doc_len = []
        for d in docs:
            c = Counter(tokenize(d))
            self.tf.append(c)
            self.doc_len.append(sum(c.values()))
            for t in c:
                self.df[t] += 1
        self.n = len(docs)
        self.avg_len = sum(self.doc_len) / max(self.n, 1)
        return self

    def scores(self, query: str) -> np.ndarray:
        """对全部文档打分，返回 ndarray（长度 n）。"""
        out = np.zeros(self.n, dtype=np.float32)
        for term in set(tokenize(query)):
            df = self.df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))
            for i, c in enumerate(self.tf):
                tf = c.get(term, 0)
                if not tf:
                    continue
                dl = self.doc_len[i]
                denom = tf + K1 * (1 - B + B * dl / self.avg_len)
                out[i] += idf * (tf * (K1 + 1)) / denom
        return out

    def save(self, path: Path) -> None:
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "df": dict(self.df),
                    "tf": self.tf,
                    "doc_len": self.doc_len,
                    "avg_len": self.avg_len,
                    "n": self.n,
                },
                f,
            )

    @classmethod
    def load(cls, path: Path) -> "BM25":
        obj = cls()
        with open(path, "rb") as f:
            d = pickle.load(f)
        obj.df = defaultdict(int, d["df"])
        obj.tf = d["tf"]
        obj.doc_len = d["doc_len"]
        obj.avg_len = d["avg_len"]
        obj.n = d["n"]
        return obj


class VectorStore:
    """密集向量 + BM25 的联合索引。"""

    def __init__(self) -> None:
        self.chunks: List[Chunk] = []
        self.embeddings: Optional[np.ndarray] = None   # (n, dim) L2-normalized
        self.bm25: Optional[BM25] = None

    # ---------------- build ----------------

    def build(self, chunks: Sequence[Chunk], embeddings: np.ndarray) -> "VectorStore":
        if len(chunks) != embeddings.shape[0]:
            raise ValueError(
                f"chunks({len(chunks)}) 与 embeddings({embeddings.shape[0]}) 数量不一致"
            )
        self.chunks = list(chunks)
        # 归一化后余弦相似度 = 点积
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1e-12
        self.embeddings = (embeddings / norms).astype(np.float32)
        self.bm25 = BM25().fit([c.text for c in self.chunks])
        return self

    # ---------------- search ----------------

    def dense(self, query_vec: np.ndarray, topk: int) -> List[Tuple[int, float]]:
        if self.embeddings is None:
            return []
        q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        nrm = np.linalg.norm(q)
        if nrm > 0:
            q = q / nrm
        sims = self.embeddings @ q
        k = min(topk, len(sims))
        idx = np.argpartition(-sims, k - 1)[:k]
        order = idx[np.argsort(-sims[idx])]
        return [(int(i), float(sims[i])) for i in order]

    def sparse(self, query: str, topk: int) -> List[Tuple[int, float]]:
        if self.bm25 is None:
            return []
        s = self.bm25.scores(query)
        k = min(topk, len(s))
        if k <= 0:
            return []
        idx = np.argpartition(-s, k - 1)[:k]
        order = idx[np.argsort(-s[idx])]
        return [(int(i), float(s[i])) for i in order if s[i] > 0]

    @staticmethod
    def rrf(
        rankings: Iterable[Sequence[Tuple[int, float]]],
        k: int = 60,
    ) -> List[Tuple[int, float]]:
        """Reciprocal Rank Fusion —— 融合多路排序。

        score(d) = Σ 1/(k + rank_i(d))，未命中的文档不贡献。
        相比分数加权，RRF 不要求两路分数在同一量纲上可比，
        这对「余弦相似度 ∈ [-1,1]」和「BM25 ∈ [0, +∞)」的组合尤其重要。
        """
        fused: Dict[int, float] = defaultdict(float)
        for ranking in rankings:
            for rank, (doc_id, _score) in enumerate(ranking, 1):
                fused[doc_id] += 1.0 / (k + rank)
        return sorted(fused.items(), key=lambda x: -x[1])

    # ---------------- persist ----------------

    def save(self, index_dir: Path = DEFAULT_INDEX_DIR) -> None:
        index_dir.mkdir(parents=True, exist_ok=True)
        if self.embeddings is not None:
            np.save(index_dir / "embeddings.npy", self.embeddings)
        if self.bm25 is not None:
            self.bm25.save(index_dir / "bm25.pkl")
        meta = [asdict_safe(c) for c in self.chunks]
        (index_dir / "meta.json").write_text(
            json.dumps({"count": len(meta), "chunks": meta}, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, index_dir: Path = DEFAULT_INDEX_DIR) -> "VectorStore":
        obj = cls()
        from .ingest import load_chunks

        obj.chunks = load_chunks(index_dir)
        emb_path = index_dir / "embeddings.npy"
        if emb_path.exists():
            obj.embeddings = np.load(emb_path)
        bm_path = index_dir / "bm25.pkl"
        if bm_path.exists():
            obj.bm25 = BM25.load(bm_path)
        return obj


def asdict_safe(c: Chunk) -> Dict[str, Any]:
    return {
        "id": c.id,
        "text": c.text,
        "source": c.source,
        "source_type": c.source_type,
        "title_path": list(c.title_path),
        "page": c.page,
        "order": c.order,
    }
