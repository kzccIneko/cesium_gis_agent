"""GeoAgent LLM benchmark: embedded llama.cpp vs Ollama HTTP.

Purpose
-------
Decide (with numbers, not intuition) whether the embedded llama.cpp path is
worth replacing Ollama. Three things get measured:

  1. Latency      - cold load, TTFT, generation speed (tokens/s)
  2. Throughput   - how fast can we chew through the 100-item eval set
  3. GBNF effect  - JSON validity with / without grammar-constrained decoding
                    (this is the real reason to drop Ollama, see IMPROVEMENT_PLAN 3.5.2)

Usage
-----
  python bench/llm_bench.py --mode embedded
  python bench/llm_bench.py --mode ollama
  python bench/llm_bench.py --mode both --report bench/llm_bench_report.md

All numbers are measured on this machine. Never estimate, never copy from docs.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_GGUF = REPO / "models" / "llm" / "qwen3.5-4b-q4km.gguf"

# A realistic GeoAgent planner turn: tool schema + Chinese spatial question.
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "tool": {"type": "string"},
        "arguments": {
            "type": "object",
            "properties": {
                "bbox": {"type": "array", "items": {"type": "number"}},
                "method": {"type": "string"},
            },
            "required": ["bbox"],
        },
    },
    "required": ["tool", "arguments"],
}

SYSTEM = (
    "You are a geospatial analysis agent. Answer with a single JSON object "
    "matching the given schema. No prose, no markdown fences."
)
QUESTIONS = [
    "计算东经 100-101 度、北纬 30-31 度区域的坡度。",
    "分析经度 102.5-103.0、纬度 28.0-28.5 的地貌类型。",
    "在经度 99-100、纬度 27-28 范围内做地形粗糙度分析。",
    "求经度 104-105、纬度 31-32 区域的坡向分布。",
    "对东经 101-102、北纬 25-26 的区域做水系提取。",
]


def gpu_memory_mb() -> float:
    """Sample current GPU memory usage via nvidia-smi. Returns 0 on failure."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return float(out.stdout.strip().splitlines()[0])
    except Exception:
        return 0.0


def build_messages(q: str):
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": q},
    ]


# --------------------------------------------------------------------------
# Embedded llama.cpp (in-process, zero HTTP)
# --------------------------------------------------------------------------
def bench_embedded(gguf: Path, n_ctx: int, n_gpu_layers: int, runs: int) -> dict:
    try:
        from llama_cpp import Llama, LlamaGrammar
    except ImportError:
        return {"error": "llama_cpp not installed"}

    t0 = time.perf_counter()
    llm = Llama(
        model_path=str(gguf),
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
        verbose=False,
    )
    load_s = time.perf_counter() - t0

    grammar = LlamaGrammar.from_json_schema(json.dumps(TOOL_SCHEMA))

    ttfts, tps_list, latencies = [], [], []
    for i in range(runs):
        q = QUESTIONS[i % len(QUESTIONS)]
        start = time.perf_counter()
        stream = llm.create_chat_completion(
            messages=build_messages(q),
            max_tokens=128,
            temperature=0.0,
            stream=True,
        )
        first_tok_at, n_tok = None, 0
        for chunk in stream:
            delta = chunk["choices"][0]["delta"]
            if delta.get("content"):
                if first_tok_at is None:
                    first_tok_at = time.perf_counter()
                n_tok += 1
        end = time.perf_counter()
        if first_tok_at:
            ttfts.append((first_tok_at - start) * 1000)
            gen = end - first_tok_at
            if gen > 0 and n_tok > 1:
                tps_list.append((n_tok - 1) / gen)
        latencies.append((end - start) * 1000)

    # GBNF effect on JSON validity
    def validity(use_grammar: bool) -> float:
        ok = 0
        for i in range(min(runs, 10)):
            out = llm.create_chat_completion(
                messages=build_messages(QUESTIONS[i % len(QUESTIONS)]),
                max_tokens=128,
                temperature=0.0,
                grammar=grammar if use_grammar else None,
            )
            txt = out["choices"][0]["message"].get("content", "")
            try:
                json.loads(txt)
                ok += 1
            except Exception:
                pass
        return ok / min(runs, 10)

    vram = gpu_memory_mb()
    return {
        "backend": "embedded-llama.cpp",
        "model": gguf.name,
        "model_size_gb": round(gguf.stat().st_size / 1024 ** 3, 2),
        "n_gpu_layers": n_gpu_layers,
        "load_s": round(load_s, 2),
        "ttft_ms": round(statistics.mean(ttfts), 1) if ttfts else None,
        "gen_tps": round(statistics.mean(tps_list), 2) if tps_list else None,
        "latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "json_valid_no_grammar": validity(False),
        "json_valid_grammar": validity(True),
        "vram_mb": vram,
    }


# --------------------------------------------------------------------------
# Ollama HTTP (baseline to be replaced)
# --------------------------------------------------------------------------
def bench_ollama(model: str, runs: int) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        return {"error": "openai package not installed"}

    client = OpenAI(base_url="http://127.0.0.1:11434/v1", api_key="ollama")

    t0 = time.perf_counter()
    try:
        client.models.list()
    except Exception as e:
        return {"error": f"ollama unreachable: {e}"}
    connect_s = time.perf_counter() - t0

    ttfts, tps_list, latencies = [], [], []
    for i in range(runs):
        q = QUESTIONS[i % len(QUESTIONS)]
        start = time.perf_counter()
        stream = client.chat.completions.create(
            model=model,
            messages=build_messages(q),
            max_tokens=128,
            temperature=0.0,
            stream=True,
        )
        first_tok_at, n_tok = None, 0
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                if first_tok_at is None:
                    first_tok_at = time.perf_counter()
                n_tok += 1
        end = time.perf_counter()
        if first_tok_at:
            ttfts.append((first_tok_at - start) * 1000)
            gen = end - first_tok_at
            if gen > 0 and n_tok > 1:
                tps_list.append((n_tok - 1) / gen)
        latencies.append((end - start) * 1000)

    return {
        "backend": "ollama-http",
        "model": model,
        "connect_s": round(connect_s, 3),
        "ttft_ms": round(statistics.mean(ttfts), 1) if ttfts else None,
        "gen_tps": round(statistics.mean(tps_list), 2) if tps_list else None,
        "latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "vram_mb": gpu_memory_mb(),
    }


def render(results: list[dict]) -> str:
    lines = ["# LLM 后端基准实测", "", f"_generated: {time.strftime('%Y-%m-%d %H:%M:%S')}_", ""]
    keys = ["backend", "model", "model_size_gb", "n_gpu_layers", "load_s", "connect_s",
            "ttft_ms", "gen_tps", "latency_ms", "json_valid_no_grammar",
            "json_valid_grammar", "vram_mb"]
    present = [k for k in keys if any(k in r for r in results)]
    lines.append("| " + " | ".join(present) + " |")
    lines.append("|" + "|".join(["---"] * len(present)) + "|")
    for r in results:
        lines.append("| " + " | ".join(str(r.get(k, "-")) for k in present) + " |")
    lines.append("")
    lines.append("> 全部为本机实测。任何写进简历/汇报的数字必须来自本表。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["embedded", "ollama", "both"], default="embedded")
    ap.add_argument("--gguf", default=str(DEFAULT_GGUF))
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--n-ctx", type=int, default=8192)
    ap.add_argument("--n-gpu-layers", type=int, default=-1)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--report", default=str(REPO / "bench" / "llm_bench_report.md"))
    args = ap.parse_args()

    results = []
    if args.mode in ("embedded", "both"):
        gguf = Path(args.gguf)
        if not gguf.exists():
            print(f"[FATAL] GGUF not found: {gguf}", file=sys.stderr)
            return 1
        print(f"[bench] embedded: {gguf.name}")
        results.append(bench_embedded(gguf, args.n_ctx, args.n_gpu_layers, args.runs))

    if args.mode in ("ollama", "both"):
        print(f"[bench] ollama: {args.model}")
        results.append(bench_ollama(args.model, args.runs))

    print(json.dumps(results, ensure_ascii=False, indent=2))

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(render(results), encoding="utf-8")
    print(f"\n[bench] report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
