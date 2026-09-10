"""领域问答评测 —— 只评测「检索」这一环。

为什么先只评检索：
    RAG 的最终质量 = 检索质量 × 生成质量。若把它俩混在一个分数里，
    检索召回失败时无法判断是检索的锅还是 LLM 的锅，改进也就无从下手。
    因此这里单独量化检索，且**只用 CPU**（293 块 × 512 维，毫秒级），
    可以秒级反复运行，适合作为回归 gate。

指标口径：
    recall@k    —— top-k 里是否存在一块同时命中全部 required_keywords
    source_hit@k—— top-k 里是否出现 expected_source 指定的文档
    mrr         —— 首个命中块的排名倒数（1.0 = 第一名就命中）

用法：
    python bench/eval_retrieval.py                 # 默认混合检索
    python bench/eval_retrieval.py --dense-only    # 消融：只留向量
    python bench/eval_retrieval.py --sparse-only   # 消融：只留 BM25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.rag.store import BM25  # noqa: E402
from app.rag.retriever import Retriever  # noqa: E402


def load_cases(path: Path) -> List[Dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"] if isinstance(data, dict) else data


def hit_rank(keywords: List[str], texts: List[str], expected_source: str) -> Tuple[int, int]:
    """返回 (关键词命中位置, 来源命中位置)，1-based；未命中为 0。"""
    kw_rank = 0
    src_rank = 0
    for i, t in enumerate(texts, 1):
        if not kw_rank and all(k in t for k in keywords):
            kw_rank = i
        if not src_rank and expected_source in t:
            src_rank = i
        if kw_rank and src_rank:
            break
    return kw_rank, src_rank


def main() -> int:
    ap = argparse.ArgumentParser(description="领域问答检索评测")
    ap.add_argument("--dataset", default=str(REPO / "backend" / "app" / "eval" / "dataset_rag.json"))
    ap.add_argument("--index", default=str(REPO / "backend" / ".data" / "rag"))
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--dense-only", action="store_true")
    ap.add_argument("--sparse-only", action="store_true")
    ap.add_argument("--show-miss", action="store_true")
    args = ap.parse_args()

    cases = load_cases(Path(args.dataset))
    r = Retriever.load(Path(args.index))
    print(f"[评测集] {len(cases)} 条  | [索引] {len(r.store.chunks)} 块")
    if args.dense_only:
        print("[模式] 仅向量")
    elif args.sparse_only:
        print("[模式] 仅 BM25")
    else:
        print("[模式] 混合（向量 + BM25，RRF 融合）")

    rows = []
    for c in cases:
        if args.dense_only:
            items = r.retrieve_only_dense(c["query"], args.topk)
        elif args.sparse_only:
            hits = r.store.sparse(c["query"], args.topk)
            items = [
                __import__("app.rag.retriever", fromlist=["Retrieved"]).Retrieved(
                    chunk=r.store.chunks[i], score=s, sparse_rank=n + 1
                )
                for n, (i, s) in enumerate(hits)
            ]
        else:
            items = r.retrieve(c["query"], args.topk)

        sources = [it.chunk.source for it in items]
        texts = [f"{it.chunk.source} {it.chunk.text}" for it in items]
        kw_rank, src_rank = hit_rank(c["required_keywords"], texts, c["expected_source"])
        rows.append(
            {
                "id": c["id"],
                "query": c["query"],
                "kw_rank": kw_rank,
                "src_rank": src_rank,
                "recall": 1.0 if kw_rank else 0.0,
                "source_hit": 1.0 if src_rank else 0.0,
                "rr": 1.0 / kw_rank if kw_rank else 0.0,
                "top1": sources[0] if sources else "",
            }
        )

    n = len(rows)
    avg = lambda key: sum(x[key] for x in rows) / n  # noqa: E731
    recall = avg("recall")
    src_hit = avg("source_hit")
    mrr = avg("rr")

    print("\n" + "=" * 62)
    print(f"{'指标':<16}{'值':>10}      说明")
    print("-" * 62)
    print(f"{'recall@k':<16}{recall:>9.3f}      top-{args.topk} 命中全部关键词的比例")
    print(f"{'source_hit@k':<16}{src_hit:>9.3f}      top-{args.topk} 出现正确文档的比例")
    print(f"{'MRR':<16}{mrr:>9.3f}      首个命中块的平均排名倒数")
    print("=" * 62)

    miss = [x for x in rows if not x["recall"]]
    if miss:
        print(f"\n未命中 {len(miss)}/{n}：")
        for x in miss:
            print(f"  {x['id']}  {x['query']}")
            print(f"      top1 -> {x['top1']}")
    return 0 if recall >= 0.99 else 1


if __name__ == "__main__":
    raise SystemExit(main())
