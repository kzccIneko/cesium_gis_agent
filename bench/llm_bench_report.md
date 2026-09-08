# LLM 后端基准实测

_generated: 2026-09-08 12:15:48_

| backend | model | model_size_gb | n_gpu_layers | load_s | ttft_ms | gen_tps | latency_ms | json_valid_no_grammar | json_valid_grammar | vram_mb |
|---|---|---|---|---|---|---|---|---|---|---|
| embedded-llama.cpp | Qwen3.5-4B-Q4_K_M.gguf | 2.55 | -1 | 5.47 | 125.0 | 51.33 | 1002.1 | 1.0 | 1.0 | 4507.0 |

> 全部为本机实测。任何写进简历/汇报的数字必须来自本表。