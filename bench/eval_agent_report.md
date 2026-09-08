# Agent Tool-Calling 评测（嵌入式 CUDA）

_generated: 2026-09-09（40/100 条，GPU 稳定性导致其余待补）_

模型：Qwen3.5-4B Q4_K_M，进程内 llama.cpp（CUDA sm_75 全层卸载，51 tok/s）

## 结果（40 条已跑：single_tool 20 + multi_tool 20）

| 指标 | 总体 | single_tool | multi_tool |
|---|---|---|---|
| 工具完全命中 tool_exact | 0.275 | **0.50** | 0.05 |
| 工具集合 F1 | 0.508 | — | — |
| 工具顺序正确率 | 0.438 | — | — |
| bbox 参数正确率 | 0.20 | 0.35 | 0.05 |
| 拒答正确率 | **1.00** | 1.00 | 1.00 |

## 三条关键结论

1. **单工具场景可用**：0.50 完全命中、拒答 1.00。修掉 `<tool_call>` 解析后从 0 涨到 0.5，
   再把 download_srtm 的"必须先调用"改成"默认不调用"后从 0.2 涨到 0.5。
2. **多工具是短板**：模型单轮只吐第一个工具（如"下载→算坡度→分类"只给 download_srtm）。
   这不是模型笨，而是单轮评测方式不对 —— 应改用 LangGraph 的 plan → execute → reflect
   多轮链路来评测（下一步）。
3. **param_bbox 0.35 的根因是缺地名词典**：问"成都周边"时模型只能猜 bbox，
   而评测集有确定值。这正是 Week 4 RAG/地名词典要解决的问题。

## 本轮修掉的 4 个 bug

| # | 问题 | 处理 |
|---|---|---|
| 1 | llama-cpp-python 0.3.35 不解析 Qwen 原生 `<tool_call>`，tool_calls 恒空 | `llm.py` 加 `parse_native_tool_calls()`（5 个单测） |
| 2 | 11 个工具 Schema 占 5213 tokens，n_ctx=4096 全部静默失败 | 默认 n_ctx 8192 |
| 3 | `Llama.reset()` 在长 prompt 下触发 CUDA error 并杀进程 | 评测路径不再调用 reset |
| 4 | chat 未限 max_tokens，模型生成到撑爆上下文 | 加 `GEOAGENT_MAX_TOKENS`（默认 512） |

## 复跑方式

GPU 在连续跑多批后会进入错误态（6GB 卡 + WDDM），必须分块跑：

```bash
python bench/eval_agent.py --offset 0 --limit 20 --out-json D:\llama_build\evalchunks\c0.json
# 每块之间间隔 25s，失败重试；块起点：0 20 40 60 80
```
