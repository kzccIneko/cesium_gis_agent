# Agent Tool-Calling 评测（嵌入式 CUDA）

_generated: 2026-09-12 04:49:35_

- 模型：Qwen3.5-4B Q4_K_M（进程内 llama.cpp，CUDA sm_75，全层卸载）
- 编排：LangGraph 编排（plan→execute→reflect→summarize）
- 模式：tool_calling
- 样本：30 条，本次耗时 7.5s（7.53s/条）
- 每样本 LLM 调用次数：1.0
- 结束状态分布：done 30
- 解析成功率：30/30

```json
{
  "n": 30,
  "parsed": 1.0,
  "tool_exact": 1.0,
  "tool_set_f1": 1.0,
  "tool_order": 1.0,
  "param_bbox": null,
  "param_dem_path": null,
  "refusal_correct": 1.0,
  "completed": 1.0,
  "by_category": {
    "multi_tool": {
      "n": 12,
      "completed": 1.0,
      "tool_exact": 1.0,
      "param_bbox": null,
      "refusal_correct": 1.0
    },
    "out_of_scope": {
      "n": 8,
      "completed": 1.0,
      "tool_exact": null,
      "param_bbox": null,
      "refusal_correct": 1.0
    },
    "single_tool": {
      "n": 10,
      "completed": 1.0,
      "tool_exact": 1.0,
      "param_bbox": null,
      "refusal_correct": 1.0
    }
  }
}
```

> 本机实测。写进简历/汇报的数字必须来自本表。