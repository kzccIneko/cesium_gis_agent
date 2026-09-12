# Agent Tool-Calling 评测（嵌入式 CUDA）

_generated: 2026-09-13 06:10:37_

- 模型：Qwen3.5-4B Q4_K_M（进程内 llama.cpp，CUDA sm_75，全层卸载）
- 编排：LangGraph 编排（plan→execute→reflect→summarize）
- 模式：tool_calling
- 样本：30 条，本次耗时 308.1s（10.27s/条）
- 每样本 LLM 调用次数：1.17
- 结束状态分布：done 30
- 解析成功率：30/30

```json
{
  "n": 30,
  "parsed": 1.0,
  "tool_exact": 0.8181818181818182,
  "tool_set_f1": 0.9212121212121211,
  "tool_order": 0.9318181818181818,
  "param_bbox": null,
  "param_dem_path": null,
  "refusal_correct": 0.9333333333333333,
  "completed": 0.8,
  "by_category": {
    "multi_tool": {
      "n": 12,
      "completed": 0.75,
      "tool_exact": 0.75,
      "param_bbox": null,
      "refusal_correct": 1.0
    },
    "out_of_scope": {
      "n": 8,
      "completed": 0.75,
      "tool_exact": null,
      "param_bbox": null,
      "refusal_correct": 0.75
    },
    "single_tool": {
      "n": 10,
      "completed": 0.9,
      "tool_exact": 0.9,
      "param_bbox": null,
      "refusal_correct": 1.0
    }
  }
}
```

> 本机实测。写进简历/汇报的数字必须来自本表。