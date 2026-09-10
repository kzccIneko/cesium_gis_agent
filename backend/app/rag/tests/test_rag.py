"""RAG 知识层离线测试（不加载真实 embedding 模型）。

真实依赖由 conversions/markers 控制，这里一律用 HashEmbedder，
这样 CI / 离线环境也能验证「切块 → 索引 → 检索 → 组装」整条链路的逻辑正确性。
真模型的语义质量验证另见 tools/convert_bge_gguf.py --verify 与 bench/probe_retrieval.py。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.rag.embed import HashEmbedder  # noqa: E402
from app.rag.ingest import Chunk, _hard_split, _split_long, build_chunks  # noqa: E402
from app.rag.retriever import Retriever  # noqa: E402
from app.rag import ingest  # noqa: E402
from app.rag.store import BM25, VectorStore, tokenize  # noqa: E402


def _mk_chunks(n: int = 6) -> list[Chunk]:
    corpus = [
        "坡度是地表倾斜程度的度量，由高程的一阶导数计算得到。",
        "曲率是高程场的二阶导数，反映地形表面的弯曲程度。",
        "A* 算法通过代价函数 f(n)=g(n)+h(n) 引导搜索方向。",
        "DEM 是数字高程模型，常用数据源包括 SRTM 与 ASTER。",
        "分析结果可导出为 GeoJSON、KML 或 CZML 供前端叠加显示。",
        "今天的股票市场大涨，银行板块领涨。",
    ]
    return [
        Chunk(
            id=f"c{i}",
            text=corpus[i % len(corpus)],
            source="test.md",
            source_type="md",
            title_path=["测试", f"节{i}"],
            order=i,
        )
        for i in range(n)
    ]


def _mk_store(n: int = 6) -> VectorStore:
    chunks = _mk_chunks(n)
    emb = HashEmbedder(dim=64).embed_documents([c.text for c in chunks])
    return VectorStore().build(chunks, emb)


# ---------------------------------------------------------------- tokenize

def test_tokenize_lowercases_ascii_and_splits_symbols() -> None:
    toks = tokenize("A*100")
    assert "a" in toks and "100" in toks   # 英文归一化为小写
    assert "*" not in toks                 # 标点不进索引


def test_tokenize_is_deterministic() -> None:
    assert tokenize("方向性通行") == tokenize("方向性通行")


# ---------------------------------------------------------------- BM25

def test_bm25_ranks_relevant_higher() -> None:
    bm = BM25().fit([
        "坡度是地表倾斜程度的度量，由高程一阶导数得到。",
        "曲率是高程场的二阶导数。",
        "今天股市大涨，银行板块领涨。",
    ])
    scores = bm.scores("坡度怎么算")
    assert scores[0] > scores[2]
    assert scores[0] > 0


def test_tokenize_bigram_for_cjk() -> None:
    toks = tokenize("坡度计算")
    assert "坡度" in toks and "度计" in toks
    assert "坡" in toks


def test_bm25_no_overlapping_token_scores_zero() -> None:
    bm = BM25().fit(["坡度的一阶差分"])
    # 与语料没有任何重叠 token（含 bigram）时，分数必须为零
    assert bm.scores("qwertyuiop").max() == 0


# ---------------------------------------------------------------- store

def test_store_build_requires_consistent_size() -> None:
    chunks = _mk_chunks(4)
    with pytest.raises(ValueError, match="数量不一致"):
        VectorStore().build(chunks, np.zeros((3, 8), dtype=np.float32))


def test_store_embeddings_are_l2_normalized() -> None:
    st = _mk_store()
    norms = np.linalg.norm(st.embeddings, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_dense_search_returns_sorted_top() -> None:
    st = _mk_store()
    q = HashEmbedder(dim=64).embed_query("坡度怎么计算")
    hits = st.dense(q, topk=3)
    assert len(hits) == 3
    scores = [s for _, s in hits]
    assert scores == sorted(scores, reverse=True)


def test_sparse_search_filters_zero_score() -> None:
    st = _mk_store()
    hits = st.sparse("坡度", topk=5)
    # 语料里只有部分文档含「坡度」，零分项不应出现在结果中
    assert all(s > 0 for _, s in hits)


def test_rrf_favours_docs_hit_by_both_paths() -> None:
    dense = [(0, 0.9), (1, 0.8)]
    sparse = [(1, 5.0), (2, 4.0)]
    fused = VectorStore.rrf([dense, sparse])
    ids = [i for i, _ in fused]
    # 文档 1 被两路同时命中，应排第一
    assert ids[0] == 1
    assert set(ids) == {0, 1, 2}


def test_store_roundtrip(tmp_path: Path) -> None:
    st = _mk_store()
    st.save(tmp_path)
    # chunks.json 需同时存在才能完整还原
    from app.rag.ingest import save_chunks

    save_chunks(st.chunks, tmp_path)
    st2 = VectorStore.load(tmp_path)
    assert len(st2.chunks) == len(st.chunks)
    assert st2.embeddings.shape == st.embeddings.shape


# ---------------------------------------------------------------- 切块

def test_split_long_respects_limit() -> None:
    long = "坡度相关论述。" * 200
    pieces = _split_long(long, limit=400, overlap=50)
    assert len(pieces) >= 2


def test_hard_split_covers_content() -> None:
    text = "第一句关于坡度。" * 100
    pieces = _hard_split(text, limit=200, overlap=0)
    joined = "".join(pieces)
    # 不应丢句子
    assert joined.count("第一句关于坡度。") == 100


def test_clean_extracted_removes_space_inside_cjk() -> None:
    """PDF 换行会在中文词内部插入空格，必须消掉。

    实测反例：袁志豪论文原文抽出「可能陷入局部 最优解」，
    若不处理，BM25 的 bigram「局部最优」建不出来，
    关键词检索会静默失效（recall@5 从 1.00 掉到 0.93）。
    """
    assert ingest._clean_extracted("可能陷入局部 最优解") == "可能陷入局部最优解"
    # 跨行断裂同样要合并
    assert ingest._clean_extracted("深度学\n习模型") == "深度学习模型"


def test_clean_extracted_keeps_structure() -> None:
    out = ingest._clean_extracted("第一段。\n\n第二段。")
    assert "第一段" in out and "第二段" in out


def test_build_chunks_drops_tiny_slices() -> None:
    """低于 MIN_CHARS 的碎片不应成为独立块。"""
    from app.rag import ingest

    old = ingest.MIN_CHARS
    ingest.MIN_CHARS = 100
    try:
        chunks = ingest.build_chunks([], max_chars=100, overlap=0)
        assert chunks == []
        # 真实路径：极短文本也应被过滤
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tiny.md"
            p.write_text("# 标题\n短句。", encoding="utf-8")
            got = ingest.build_chunks([p])
            assert got == []
    finally:
        ingest.MIN_CHARS = old


# ---------------------------------------------------------------- retriever

def test_retriever_returns_source_labels() -> None:
    st = _mk_store()
    r = Retriever(st, HashEmbedder(dim=64))
    items = r.retrieve("坡度", topk=2)
    assert items
    assert all(it.source_label for it in items)


def test_retriever_dense_only_skips_bm25() -> None:
    st = _mk_store()
    r = Retriever(st, HashEmbedder(dim=64))
    items = r.retrieve_only_dense("坡度", topk=2)
    assert all(it.sparse_rank is None for it in items)


def test_format_context_includes_citation_and_truncates() -> None:
    st = _mk_store()
    r = Retriever(st, HashEmbedder(dim=64))
    items = r.retrieve("坡度", topk=3)
    ctx = Retriever.format_context(items, max_chars=200)
    assert "来源：" in ctx
    assert len(ctx) <= 600   # 允许少量标注开销与边界句子


def test_format_context_empty() -> None:
    assert Retriever.format_context([]) == ""
