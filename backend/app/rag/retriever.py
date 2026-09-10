"""检索门面：混合召回 + 上下文组装。

对外只暴露两个动作：
- `retrieve(query)` —— 拿回最相关的若干块
- `format_context(chunks)` —— 把块拼成可直接塞给 LLM 的带出处文本

混合策略（默认同时开 dense + sparse 再 RRF 融合）的理由见 store.py 的模块说明：
密集语义 + 字面匹配互补，且不引入 rerank 模型那样的额外参数量与延迟。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np

from .embed import DEFAULT_MODEL, Embedder, HashEmbedder, LlamaCppEmbedder
from .ingest import DEFAULT_INDEX_DIR, Chunk
from .store import VectorStore


@dataclass
class Retrieved:
    chunk: Chunk
    score: float = 0.0
    dense_rank: Optional[int] = None
    sparse_rank: Optional[int] = None

    @property
    def source_label(self) -> str:
        c = self.chunk
        loc = c.source.rsplit("/", 1)[-1]
        if c.page is not None:
            loc = f"{loc}#{c.page}"
        head = c.heading
        return f"{loc}｜{head}" if head else loc


class Retriever:
    def __init__(self, store: VectorStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    @classmethod
    def load(
        cls,
        index_dir: Path = DEFAULT_INDEX_DIR,
        embedder: Optional[Embedder] = None,
        allow_missing_model: bool = False,
    ) -> "Retriever":
        """从磁盘加载索引。

        allow_missing_model=True 时，模型文件缺失会退化为 HashEmbedder，
        仅用于离线测试 / CI —— 生产路径必须真实模型，否则检索无意义。
        """
        store = VectorStore.load(index_dir)
        if embedder is not None:
            return cls(store, embedder)
        try:
            return cls(store, LlamaCppEmbedder())
        except FileNotFoundError:
            if allow_missing_model:
                return cls(store, HashEmbedder())
            raise

    # ---------------- 检索 ----------------

    def retrieve(
        self,
        query: str,
        topk: int = 5,
        dense_weight: int = 2,
        use_sparse: bool = True,
    ) -> List[Retrieved]:
        """混合召回。

        dense_weight=2 表示把密集向量结果在 RRF 融合里重复计数两次，
        即略微偏向语义匹配 —— 默认让「意思对」压过「字面像」。
        """
        qv = self.embedder.embed_query(query)
        dense = self.store.dense(qv, topk * dense_weight)
        sparse = self.store.sparse(query, topk * 2) if use_sparse else []

        rankings: List[List[tuple]] = [list(dense)] * dense_weight
        if sparse:
            rankings.append(list(sparse))

        fused = VectorStore.rrf(rankings)
        dense_pos = {cid: i + 1 for i, (cid, _) in enumerate(dense)}
        sparse_pos = {cid: i + 1 for i, (cid, _) in enumerate(sparse)}

        out: List[Retrieved] = []
        for cid, score in fused[:topk]:
            if cid >= len(self.store.chunks):
                continue
            out.append(
                Retrieved(
                    chunk=self.store.chunks[cid],
                    score=float(score),
                    dense_rank=dense_pos.get(cid),
                    sparse_rank=sparse_pos.get(cid),
                )
            )
        return out

    def retrieve_only_dense(self, query: str, topk: int = 5) -> List[Retrieved]:
        """只用向量 —— 供消融实验对照（Week 5 会用到）。"""
        qv = self.embedder.embed_query(query)
        dense = self.store.dense(qv, topk)
        return [
            Retrieved(chunk=self.store.chunks[c], score=s, dense_rank=i + 1)
            for i, (c, s) in enumerate(dense)
        ]

    # ---------------- 组装 ----------------

    @staticmethod
    def format_context(items: Sequence[Retrieved], max_chars: int = 2400) -> str:
        """把检索结果拼成 LLM 可读的上下文，**每段带出处**。

        带出处不只是为了好看：LLM 回答时引用来源，用户可以回溯核查，
        这是垂直领域问答能被人信任的前提（否则无法区分「查到」和「编的」）。
        """
        if not items:
            return ""
        lines: List[str] = []
        used = 0
        for i, it in enumerate(items, 1):
            body = it.chunk.text.strip()
            room = max_chars - used
            if room <= 80:
                break
            if len(body) > room:
                body = body[:room].rsplit("\n", 1)[0] + " …"
            lines.append(f"[{i}] 来源：{it.source_label}\n{body}")
            used += len(body)
        return "\n\n".join(lines)
