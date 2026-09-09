# Agent Tool-Calling 评测（嵌入式 CUDA · 本机实测）

_generated: 2026-09-09 · 模型 Qwen3.5-4B Q4_K_M（进程内 llama.cpp，CUDA sm_75 全层卸载）_

## 一、结论先行

| 指标 | 单轮 100 条 | 多轮 20 条（multi_tool） |
|---|---|---|
| tool_exact | 0.35 | **0.00 → 0.30** |
| tool_set_f1 | 0.56 | 0.56 |
| tool_order | 0.50 | 0.56 |
| param_bbox | 0.18 | 0.05 |
| refusal_correct | 0.94 | 0.85 |
| completed | 0.31 | 0.00 |

拆分看类别（单轮 100 条）：

| 类别 | n | tool_exact | param_bbox | refusal_correct |
|---|---|---|---|---|
| single_tool | 40 | **0.70** | 0.35 | 1.00 |
| multi_tool | 40 | **0.00** | 0.025 | 0.95 |
| out_of_scope | 20 | — | — | 0.80 |

两条可读出的结论：
1. **单工具已经可用（0.70）**，瓶颈不在模型智力。
2. **多工具 0.00 是"单轮直问"的结构性缺陷**——4B 模型一次只吐一个工具。
   改成多轮链路后 0.00 → 0.30，20 条里 14 条吐出了 2–3 步工具链。
   剩余失败集中在"多调一个 download_srtm"，是提示词策略问题，可继续修。

## 二、三个工程问题的答案

### max_tokens 取多少：384

实测 60 条、放开到 1024 让它自由生成（`bench/measure_tokens.py`）：

```
min=35  p50=116  p90=193  p95=272  p99=318  max=318
>256 占 5%   >384 占 0%
single_tool: p50=68 max=279    multi_tool: p50=162 max=318
```

三约束取交集：

- **A 下界**：≥ p99(318)，384 留 21% 余量（取 256 会截断 5% 回答，人为丢分）
- **B 上下文上界**：`n_ctx(8192) - prompt(5323) = 2869`，384 远在安全区
- **C 延迟上界**：384 / ~50 tok/s ≈ 7.7s 最坏；典型 p50 仅 2.3s

它是**护栏不是目标值**——取 1024 就失去防跑飞的作用（不设上限会生成到撑爆上下文并触发 CUDA error）。

### CUDA error 为什么：不是显存，是笔记本 GPU 热/功耗降频

| 假设 | 验证方式 | 结论 |
|---|---|---|
| 显存泄漏 / OOM | 每条采样，稳定 4621–4739 MiB（总量 6144，桌面程序占 1075） | 排除 |
| WDDM TDR（TdrDelay=15s） | 单次 max_tokens=2048 连续生成 38.7s 不崩 | 排除 |
| 长 prompt 必崩 | 同一条 4937-token prompt 重复 15 次不崩 | 排除 |
| **热/功耗降频** | `clocks_throttle_reasons.active` = `0x4` Sw Power Cap → `0x20` Sw Thermal Slowdown；62°C → 82°C；75W → 47W | **确认** |

崩在 `ggml-cuda.cu:106`，C 层直接 abort，**Python try/except 拦不住**（exit 127）。

### 怎么提速：KV 前缀复用 1.63x + 断点续跑

system+tools 占 4937 token 且对所有样本相同，没必要每条重算：

| 方案 | 平均耗时/条 |
|---|---|
| 原始 | 6.94s |
| `Llama.save_state()` | 7.22s（**等于没加速**） |
| C 接口 `llama_state_get/set_data` | **4.26s（1.63x）** |

`save_state()` 无效的坑：它会 `self._scores.copy()`，而 `_scores` 是
`(n_ctx=8192, vocab=151936)` 的 float32 = **4.98 GB**，省下的 prefill 全被它吃光。

配合**每条落盘 + `--resume` 断点续跑**，全量 100 条 **6m14s 跑完，零崩溃**
（此前跑 40 条都要崩好几次，靠分块 + sleep 25s 硬扛）。

## 三、复现命令

```bash
# 单轮全量（前缀复用 + 续跑）
python bench/eval_agent.py --all --resume --prefix-cache \
    --out-json D:\llama_build\eval_full.json

# 多轮链路（3 轮，工具结果用桩）
python bench/eval_agent.py --category multi_tool --limit 20 --turns 3 \
    --resume --out-json D:\llama_build\eval_multiturn.json

# 输出 token 分布（max_tokens 取值的依据）
python bench/measure_tokens.py --limit 60
```

> 数字全部来自本机实测。写进简历/汇报的数字必须来自本表。
