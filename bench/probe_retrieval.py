"""检索质量探针 —— 用真实领域问题验证 RAG 到底召回什么。

存在的意义：向量相似度本身不能证明检索有效。
这里做的是「查一句人话，看 top-k 里有没有人能一眼认出的答案」，
属于最容易发现系统性失效（pooling 错、切块烂、语言不匹配）的低成本检查。

用法：
    python bench/probe_retrieval.py                  # 内置问题集
    python bench/probe_retrieval.py --query "xxx"    # 单条
    python bench/probe_retrieval.py --dense-only     # 关掉 BM25 做对照
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.rag.retriever import Retriever  # noqa: E402

# 内置探针：问题 → 期望出现在正确答案里的关键词（任一命中即算召回成功）
PROBES = [
    ("坡度是怎么计算的", ["坡度", "窗口", "差分", "∂", "梯度"]),
    ("曲率对车辆通行有什么影响", ["曲率", "二阶", "弯曲", "突变"]),
    ("A*算法的代价函数怎么设计", ["A*", "代价函数", "启发", "开启列表", "Open"]),
    ("什么是 Geomorphons 地貌分类", ["地貌", "分类", "形态", "octagon", "视线"]),
    ("DEM 数据从哪里获取", ["DEM", "SRTM", "下载", "高程数据"]),
    ("路径规划为什么要考虑方向性", ["方向", "上坡", "下坡", "各向", "异性"]),
    ("如何将分析图层导出", ["导出", "GeoJSON", "KML", "CZML"]),
    ("什么是启发式搜索", ["启发", "搜索", "A*", "估值"]),
]


def run(r: Retriever, query: str, topk: int, dense_only: bool, show_body: int) -> bool:
    items = r.retrieve_only_dense(query, topk) if dense_only else r.retrieve(query, topk)
    print(f"\n问：{query}")
    if not items:
        print("   （无召回）")
        return False
    hit = False
    for i, it in enumerate(items, 1):
        tags = []
        if it.dense_rank:
            tags.append(f"向量#{it.dense_rank}")
        if it.sparse_rank:
            tags.append(f"BM25#{it.sparse_rank}")
        print(f"  [{i}] {it.source_label}  ({', '.join(tags)}, rrf={it.score:.3f})")
        body = it.chunk.text.strip().replace("\n", " ")
        print(f"      {body[:show_body]}")
    return hit


def main() -> int:
    ap = argparse.ArgumentParser(description="RAG 检索质量探针")
    ap.add_argument("--query", default=None)
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--dense-only", action="store_true")
    ap.add_argument("--show-body", type=int, default=150)
    ap.add_argument("--index", default=str(REPO / "backend" / ".data" / "rag"))
    args = ap.parse_args()

    t0 = time.perf_counter()
    r = Retriever.load(Path(args.index))
    load_dt = time.perf_counter() - t0
    print(f"[索引] {len(r.store.chunks)} 块，加载 {load_dt:.2f}s")

    queries = [(args.query, [])] if args.query else PROBES
    mode = "仅向量" if args.dense_only else "混合（向量+BM25）"
    print(f"[模式] {mode}")

    tot = 0.0
    for q, expect in queries:
        t = time.perf_counter()
        items = r.retrieve_only_dense(q, args.topk) if args.dense_only else r.retrieve(q, args.topk)
        dt = time.perf_counter() - t
        tot += dt
        print(f"\n问：{q}   （{dt * 1000:.0f} ms）")
        if not items:
            print("   （无召回）")
            continue
        for i, it in enumerate(items, 1):
            tags = []
            if it.dense_rank:
                tags.append(f"向量#{it.dense_rank}")
            if it.sparse_rank:
                tags.append(f"BM25#{it.sparse_rank}")
            hit = [e for e in (expect or []) if e in it.chunk.text]
            flag = f"  ✔命中关键词{hit}" if hit else ""
            print(f"  [{i}] {it.source_label}  ({', '.join(tags)}){flag}")
            body = it.chunk.text.strip().replace("\n", " ")
            print(f"      {body[: args.show_body]}")

    print(f"\n平均单次检索 {tot / max(len(queries), 1) * 1000:.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
