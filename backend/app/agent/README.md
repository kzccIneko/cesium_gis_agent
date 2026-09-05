# GeoAgent 编排层

把工具层的 11 个地理分析工具编排进一个**会自我校验**的执行流程。

## 架构

```
用户问题
   │
   ▼
┌────────┐   LLM 拆解 / 关键词兜底
│ planner│ ── 输出：工具调用序列
└────────┘
   │
   ▼
┌─────────┐
│ executor│ ── 调用 tools 层，只执行不判断
└─────────┘
   │ 结构化结果（含单位与告警）
   ▼
┌──────────┐  9 条确定性规则 + LLM 语义复核
│ reflector│ ── accept → 下一步
└──────────┘   retry（≤N 次，自动修正参数）→ 回到 executor
   │            abort → 总结
   ▼
┌───────────┐
│ summarizer│ ── 最终回答（强制声明数据来源与局限）
└───────────┘
```

## 快速开始

```python
from app.agent import run_agent

# 无 LLM 也能跑通全流程：规划走关键词兜底，回答走模板
state = run_agent("分析这片区域的坡度", bbox=[103.5, 30.2, 103.7, 30.4])
print(state["final_answer"])
print(state["tool_calls"])   # 每次调用的入参、结果、耗时
print(state["trace"])        # 人类可读的执行轨迹
```

接 LLM（任何 OpenAI 兼容服务均可）：

```python
from app.agent.llm import OpenAICompatClient
from app.agent import run_agent

llm = OpenAICompatClient(
    base_url="https://api.deepseek.com",   # 或 http://localhost:11434/v1（Ollama）
    api_key="sk-...",
    model="deepseek-chat",
)
state = run_agent("这片区域哪里适合修路？", bbox=[103.5, 30.2, 103.7, 30.4], llm=llm)
```

也支持环境变量配置：`GEOAGENT_LLM_BASE_URL` / `GEOAGENT_LLM_API_KEY` / `GEOAGENT_LLM_MODEL`。

带持久化（支持中断恢复与多轮对话）：

```python
from app.agent.persistence import build_checkpointer
cp = build_checkpointer()
state = run_agent("分析坡度", bbox=[...], session_id="user-42", checkpointer=cp)
```

## 目录结构

```
agent/
  state.py        AgentState 定义 + 状态合并工具
  rules.py        9 条领域校验规则（reflector 的确定性部分）
  routing.py      状态图路由（纯函数，两种运行时共享）
  graph.py        LangGraph 状态图定义
  runner.py       运行入口（LangGraph 优先，缺失时内置循环接管）
  persistence.py  SqliteSaver 配置
  llm.py          LLM 客户端抽象（OpenAI 兼容 / Mock）+ JSON 容错解析
  nodes/
    planner.py    任务拆解（LLM → 重试修正 → 关键词兜底）
    executor.py   工具调用
    reflector.py  结果校验与重试决策（核心）
    summarizer.py 最终回答
  prompts/
    planner.txt   规划提示词
    reflector.txt 反思提示词
  tests/
    test_agent.py 46 个单元测试
```

## 关键设计决策

### 1. 代码规则优先于 LLM 判定

数值越界、路径短于直线距离、起终点在区域外——这些是**客观错误**，
LLM 的"看起来没问题"不能推翻它们。反过来，代码查不出
"用户问了坡度和坡向但只算了坡度"这类语义遗漏。

因此：

| 代码规则 | LLM 权限 |
|---|---|
| 判定 error | **无权放行**，必须重试或放弃 |
| 判定无 error | 可否决并要求重试 |
| 不可用 / 输出非法 | 信任代码，直接接受 |

### 2. 工具失败时仍跑参数类规则

最初的实现只在工具成功时校验结果。这导致一个隐蔽缺陷：
起终点越界 → 工具返回 `invalid_point` → 规则不执行 →
**用同一组错误参数重试 3 次** → 放弃。

修正：把只依赖 `arguments` 的规则（起终点在 bbox 内、bbox 顺序）抽为
`ARGUMENT_RULES`，工具失败时照常执行，先修正参数再重试。
现在同样的场景会在第 2 次尝试成功。

### 3. 重试次数语义

`max_retries=3` 表示**最多重试 3 次**（共 4 次调用），
判定条件是 `retry_count < max_retries` 而非 `attempt < max_retries`——
后者会少给一次机会。

### 4. 状态 100% 可 JSON 序列化

SqliteSaver 要把 state 写进数据库，任何 numpy 数组 / 栅格对象都不能进 state。
栅格一律以 artifact 路径引用。

### 5. 节点返回完整替换值而非增量

若返回增量（`messages = [new_msg]`），两种运行时的合并语义会分叉：
LangGraph 默认覆盖、`add_messages` reducer 追加、自研 runner 需自定义规则。
改为"读旧值 → 拼新列表 → 返回完整列表"，所有运行时语义统一为覆盖。

### 6. 双运行时

LangGraph 优先；缺失或版本不兼容时内置执行循环接管。
两者**共享同一套节点函数与路由函数**，不存在行为分叉。
降级路径是真实可用的：打包给没有 langgraph 的环境时自动生效。

## 9 条校验规则

| 规则 | 判定内容 | 级别 |
|---|---|---|
| `path_length_sanity` | 路径不短于直线距离、绕行系数不过大、节点数不退化 | error / warn |
| `slope_range` | 坡度 ∈ [0, 90] 度 | error / warn |
| `aspect_range` | 坡向 ∈ [0, 360) 度 | error |
| `classification_nonempty` | 类别数 ≥ 2，非单一类别主导 | error / warn |
| `endpoints_in_bbox` | 起终点在 bbox 内（可自动夹取修正） | error |
| `bbox_order` | bbox 顺序（经纬颠倒、边界反置，可自动修正） | error |
| `crs_consistency` | 坐标系一致、请求与结果 bbox 一致、像元尺寸合理 | error |
| `tile_alignment` | 输出栅格 shape 与请求分辨率一致 | error |
| `valid_data_ratio` | 有效像元占比 ≥ 50% | error / warn |
| `dem_source_authenticity` | 合成地形不得作为真实结论 | warn |

最后一条是本项目特有的诚实性约束：系统在没有真实 DEM 时会退化为合成地形，
若不校验，Agent 会拿合成地形给出看似专业的真实地理结论——这是最危险的失败模式。

## 测试

```bash
# 编排层 46 个测试
backend/.venv/Scripts/python.exe backend/app/agent/tests/test_agent.py

# 工具层 28 个测试
backend/.venv/Scripts/python.exe backend/app/tools/tests/test_tools.py
```

测试全程使用合成地形与低分辨率，不依赖网络与外部 API。
端到端测试会把"LangGraph 降级警告"升级为错误，确保测的是真实图执行路径。

## 已知限制 / 下一步

- **MCP Server（Week 3）**：把工具层暴露给 Claude Desktop / Cursor 等外部客户端。
  注意 `.gitignore` 当前忽略了整个 `mcp/` 目录，届时需要为例外路径加白名单。
- **步骤间数据传递**：`PlanStep.depends_on` 字段已就位，但尚未实现前序结果
  作为后序输入的参数占位符解析。
- **RAG 增强（Week 4）**：接入文献知识库，让规划与反思有领域资料可依据。
