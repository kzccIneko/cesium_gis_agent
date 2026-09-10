"""一键构建检索索引：chunks → embeddings → 落盘。

用法：
    python -m backend.app.rag.build            # 全量重建
    python -m backend.app.rag.build --dry-run  # 只统计不写盘
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from .embed import Embedder, LlamaCppEmbedder
from .ingest import DEFAULT_INDEX_DIR, build_chunks, discover_sources, load_chunks, save_chunks
from .store import VectorStore


def build_index(
    literature_dir: Path | None = None,
    index_dir: Path = DEFAULT_INDEX_DIR,
    embedder: Embedder | None = None,
    rebuild_chunks: bool = True,
) -> tuple[VectorStore, float]:
    """返回 (索引, 嵌入耗时秒数)。"""
    if rebuild_chunks or not (index_dir / "chunks.json").exists():
        sources = discover_sources(literature_dir) if literature_dir else discover_sources()
        chunks = build_chunks(sources)
        save_chunks(chunks, index_dir)
    else:
        chunks = load_chunks(index_dir)

    if embedder is None:
        embedder = LlamaCppEmbedder()

    t0 = time.perf_counter()
    emb = embedder.embed_documents([c.text for c in chunks])
    dt = time.perf_counter() - t0

    store = VectorStore().build(chunks, emb)
    store.save(index_dir)
    return store, dt


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 GeoAgent 领域 RAG 索引")
    ap.add_argument("--dir", default=None, help="语料目录（默认 literature/）")
    ap.add_argument("--out", default=str(DEFAULT_INDEX_DIR))
    ap.add_argument("--no-rebuild", action="store_true", help="复用已有 chunks.json")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写盘")
    args = ap.parse_args()

    lit = Path(args.dir) if args.dir else None
    out = Path(args.out)

    if args.dry_run:
        sources = discover_sources(lit) if lit else discover_sources()
        chunks = build_chunks(sources)
        print(f"[dry-run] 语料 {len(sources)} 个文件 → {len(chunks)} 块")
        emb_bytes = len(chunks) * 512 * 4
        print(f"[dry-run] 若建索引，向量矩阵约 {emb_bytes / 1024:.0f} KB")
        return 0

    store, dt = build_index(lit, out, rebuild_chunks=not args.no_rebuild)
    n = len(store.chunks)
    print(f"[索引] {n} 块已入库")
    print(f"[嵌入] 耗时 {dt:.1f}s（{dt / max(n, 1) * 1000:.0f} ms/块）")
    print(f"[落盘] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
