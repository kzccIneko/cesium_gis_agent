# Agent Tool-Calling 评测（嵌入式 CUDA）

_generated: 2026-09-17 00:50:09_

- 模型：Qwen3.5-4B Q4_K_M（进程内 llama.cpp，CUDA sm_75，全层卸载）
- 编排：LangGraph 编排（plan→execute→reflect→summarize）
- 模式：tool_calling
- 样本：20 条，本次耗时 299.3s（14.97s/条）
- 每样本 LLM 调用次数：1.25
- 结束状态分布：done 20
- 解析成功率：20/20

```json
{
  "n": 20,
  "parsed": 1.0,
  "tool_exact": null,
  "tool_set_f1": null,
  "tool_order": null,
  "param_bbox": null,
  "param_dem_path": null,
  "refusal_correct": 0.95,
  "completed": 0.95,
  "by_category": {
    "out_of_scope": {
      "n": 20,
      "completed": 0.95,
      "tool_exact": null,
      "param_bbox": null,
      "refusal_correct": 0.95
    }
  }
}
```

> 本机实测。写进简历/汇报的数字必须来自本表。