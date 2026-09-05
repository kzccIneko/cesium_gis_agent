"""GeoAgent —— 地理空间分析智能体编排层。

架构：

    backend/app/tools/    工具层（Week 1）：11 个大模型可调用工具
    backend/app/agent/    编排层（Week 2）：计划 → 执行 → 反思 → 总结

    用户问题
       │
       ▼
    ┌────────┐   LLM 拆解 / 关键词兜底
    │ planner│──────────────────────────┐
    └────────┘                          │
       │ 计划（工具调用序列）            │
       ▼                                │
    ┌─────────┐                         │
    │ executor│──→ 调用 tools 层         │
    └─────────┘                         │
       │ 结构化结果（含单位与告警）      │
       ▼                                │
    ┌──────────┐  9 条确定性规则 + LLM 语义复核
    │ reflector│────────────────────────┘
    └──────────┘
       │  accept → 下一步 / retry（≤3）→ 回到 executor / abort → 总结
       ▼
    ┌───────────┐
    │ summarizer│──→ 最终回答（含数据来源与局限说明）
    └───────────┘

快速开始：
    from app.agent import run_agent

    # 无 LLM 也能跑（规划走关键词兜底，回答走模板）
    state = run_agent("分析该区域坡度", bbox=[103.5, 30.2, 103.7, 30.4])
    print(state["final_answer"])

    # 接 LLM
    from app.agent.llm import OpenAICompatClient
    llm = OpenAICompatClient(base_url="https://api.deepseek.com", api_key="sk-...", model="deepseek-chat")
    state = run_agent("这片区域哪里可以修路？", bbox=[103.5, 30.2, 103.7, 30.4], llm=llm)
"""

from __future__ import annotations

from .llm import (
    MockClient,
    OpenAICompatClient,
    LLMClient,
    LLMResponse,
    build_client,
    extract_json,
)
from .runner import run_agent, stream_agent
from .state import AgentState, create_initial_state

__all__ = [
    "run_agent",
    "stream_agent",
    "AgentState",
    "create_initial_state",
    "LLMClient",
    "LLMResponse",
    "OpenAICompatClient",
    "MockClient",
    "build_client",
    "extract_json",
]
