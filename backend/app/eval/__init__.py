"""GeoAgent 评测模块。

用途：量化 Agent 大脑模型（LLM）在地理空间工具调用任务上的能力，
为"模型选型 / 量化档位 / 垂直微调"三条优化路线提供可复现的评测依据。

组成：
    build_dataset.py  构造 100 条中文评测集（单工具 40 / 多工具 40 / 越界拒答 20）
    metrics.py        纯函数指标（JSON 合法率 / 工具选择 / 参数准确 / 拒答 / 完成率）
    runner.py         评测执行器（原生 function calling 与 JSON 输出两种模式）
    dataset.json      生成产物（评测数据）

用法：
    python -m backend.app.eval.build_dataset          # 生成/校验评测集
    python -m backend.app.eval.run_eval --model xxx   # 跑评测
"""

from .metrics import aggregate, bbox_match, score_case, tool_scores
from .runner import EvalRunner, load_dataset

__all__ = [
    "EvalRunner",
    "load_dataset",
    "aggregate",
    "bbox_match",
    "score_case",
    "tool_scores",
]
