# GeoAgent · 地理空间分析智能体

把 GIS 分析能力封装成大模型可调用的工具，用一句自然语言驱动「规划 → 执行 → 反思 → 汇总」，
结果直接渲染到 CesiumJS 三维地球上。

> 用户说「算一下四姑娘山的坡度」「规划一条从 A 到 B 的越野路线」，
> 系统自己决定调哪些工具、按什么顺序、参数怎么填，算完把结果画到三维地球上。

---

## 1. 项目构成（两个阶段）

| 阶段 | 内容 | 说明 |
|---|---|---|
| **第一阶段** | CesiumJS 三维地理信息分析平台 | 团队既有系统的延伸：地形因子计算、通行代价建模、越野路径规划、地貌分类（含 ONNX 推理） |
| **第二阶段** | GeoAgent 智能体层 | 本人独立开发：工具层 / 编排层 / MCP / RAG / 对话记忆 / 本地推理 / 微调与评测 |

> **关于本仓库**：这是 GitHub 镜像。本地开发环境目录 `envirment/`（JDK、Tomcat、GeoServer 等约 250 MB
> 第三方二进制）不属于源码，未纳入本仓库，其历史也不在镜像中。原始私有仓库托管在阿里云 Codeup。

---

## 2. 系统架构

```
用户自然语言
      │
      ▼
┌─────────────────┐   命中关键词直接判为分析任务（跳过下一步）
│  意图分流 NLU    │   否则交给 LLM 判定 analysis / knowledge / action / chat / refuse
└────────┬────────┘
         ▼
┌─────────────────┐   按工具 JSON Schema 生成计划：bbox + steps[]
│    Planner      │
└────────┬────────┘
         ▼
┌─────────────────┐   按序调用 12 个工具，产出栅格 / 矢量 / 统计结果
│    Executor     │
└────────┬────────┘
         ▼
┌─────────────────┐   校验结果是否真正回答了原问题，不满足则回退重规划
│     Reflect     │   （消融实测：关闭该节点，工具调用准确率 96.2% → 92.5%）
└────────┬────────┘
         ▼
┌─────────────────┐
│   Responder     │   汇总为自然语言 + 前端三维渲染
└─────────────────┘
```

**分层实现**

| 层 | 位置 | 要点 |
|---|---|---|
| 工具层 | `backend/app/tools/` | 12 个工具，统一 JSON Schema 注册表，新增工具只改 3 处 |
| 编排层 | `backend/app/agent/` | LangGraph `StateGraph` + 条件回边；缺少 langgraph 时自动降级为内置循环 |
| 协议层 | `mcp/` | 以 MCP 标准协议对外暴露地理空间分析能力 |
| 知识层 | `backend/app/rag/` | 文献语料切块 → bge 向量 + BM25 → RRF 融合检索 |
| 记忆层 | `backend/app/agent/memory.py` | 工作记忆 + SQLite 短期（最近 6 轮 + 焦点卡片）+ 长期 |
| 推理层 | `backend/app/agent/llm.py` | 进程内嵌入 llama.cpp（GGUF / CUDA），支持 GBNF 约束解码 |

---

## 3. 12 个工具

| 分类 | 工具 | 作用 |
|---|---|---|
| 数据 | `get_dem_metadata` | 读取 DEM 元信息（坐标系、尺寸、nodata） |
| 数据 | `download_srtm` | 按经纬度范围下载 Copernicus GLO-30 真实 DEM 并缓存 |
| 地形因子 | `compute_slope` / `compute_aspect` / `compute_curvature` | 坡度 / 坡向 / 曲率 |
| 通行分析 | `compute_cost_surface` | 综合坡度、曲率、山脊谷地、等高线密度构建通行代价栅格 |
| 通行分析 | `plan_route` | 代价栅格上 Dijkstra 8 邻域最短路 + **方向性代价场** |
| 地貌分类 | `classify_terrain_rules` | 基于坡度/曲率/TPI 的 8 类规则分类 |
| 地貌分类 | `classify_geomorphons` | Geomorphons 算法（Jasiewicz & Stepinski 2013） |
| 地貌分类 | `classify_terrain_onnx` | ONNX CNN 蒸馏 Geomorphons 判定 |
| 统计 | `zonal_statistics` | 地形指标分级统计并给出业务结论 |
| 数据查询 | `query_tabular` | 自然语言转 SQL 查结构化数据表（只读，三重安全闸门） |

---

## 4. 评测与指标

所有数字均可在仓库内找到对应结果文件，**没有只存在于文档里的数字**。

| 项目 | 指标 | 出处 |
|---|---|---|
| 主评测集（100 条：单工具 40 / 多工具 40 / 越界拒答 20） | 工具调用完全正确 **98.75%**、坐标参数 **100%**（底座模型） | `bench/eval_results/v19_*.json` |
| 微调对照（v20 / v21 / v22） | 32.5% / 47.5% / 31.2% —— **均不及底座**，根因见案例 12 | `bench/eval_results/v2*_*.json` |
| 意图判断独立测试集（56 条，46 条为不含关键词的改写问法） | 提示词优化 **80.4%** ｜ 专用小分类器 78.3% ｜ 底座 69.6% ｜ 微调模型 37.0% ｜ 纯正则 **0.0%** | `bench/eval_results/intent_methods.json` |
| 自然语言查表 | 执行正确 **100%** ｜ 恶意 SQL 拦截 **100%** ｜ 翻译正确 **96.7%** | `bench/eval_results/text2sql.json` |
| 评测回归 | 一键与基线比对 + 翻转样本清单 | `bench/REGRESSION.md` |
| 本地推理（Qwen3.5-4B Q4_K_M，RTX 2060 6GB） | **51.3 tok/s**、TTFT **125 ms**、常驻显存 **4.5 GB** | `bench/llm_bench_report.md` |
| ONNX 地貌分类 | 准确率 **76.48%**、Macro-F1 **75.84%**、推理 **2.34×** 加速；256×256 栅格比 Geomorphons 快 **133.2×** | `bench/results/eval_report.md` |
| RAG 检索 | recall@5 **1.000**、MRR **0.782**、单次检索 **8 ms** | `backend/app/rag/`（语料需本地重建） |

### 评测设计上的两条纪律

1. **训练/评测数据不得同源。** 意图测试集刻意采用「不含任何专业关键词的改写问法」，
   因为主评测集里绝大多数问句会命中关键词规则被直接旁路，测不出真实语义理解。
2. **负结果照实记录。** 微调后主评测集从 98.75% 跌到 32.5%，原因定位为训练目标与部署任务不一致
   （灾难性遗忘），修正训练目标后回升到 47.5% 仍不及底座，最终归因到训练数据的工具分布偏差。
   完整过程见 `PROBLEM_SOLVING_LOG.md` 案例 11、12。

---

## 5. 快速开始

### 前端（三维可视化）

```bash
npm install
npm run serve          # http://localhost:8080
# 打开 cesium_old/Cesium_coordinate_copy_czDebugging.html
```

### 后端（分析服务 + Agent）

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

> Agent 相关依赖未安装时会**自动降级**：无 langgraph → 内置执行循环；
> 无 OpenAI Key → 规划走关键词启发式、回答走模板。原有分析服务不受影响。

### 本地大模型（可选）

```bash
# 把量化模型放到 models/llm/（该目录不入库）
export GEOAGENT_GGUF=/path/to/Qwen3.5-4B-Q4_K_M.gguf
```

支持的其它环境变量：`GEOAGENT_N_CTX`、`GEOAGENT_LLM_BACKEND`、`GEOAGENT_LLM_BASE_URL` 等，
详见 `backend/app/agent/llm.py` 顶部注释。

---

## 6. 目录结构

```
backend/            FastAPI 服务
  app/agent/        编排层：图、节点、提示词、记忆、LLM 客户端
  app/tools/        12 个工具 + 统一 schema 注册表
  app/rag/          语料切块、向量化、BM25、RRF
  app/eval/         评测集与指标计算
bench/              训练 / 评测 / 回归脚本与结果（数字来源）
cesium_old/         前端主页面、功能模块、Cesium 库
mcp/                MCP Server（协议层）
literature/         领域文献与算法笔记
```

---

## 7. 文档索引

| 文档 | 内容 |
|---|---|
| `IMPROVEMENT_PLAN.md` | 权威实施路线与技术选型理由 |
| `GEOAGENT_PROGRESS.md` | 逐阶段完成状态、偏离项与原因 |
| `PROBLEM_SOLVING_LOG.md` | **13 个开发问题案例**（现象 → 直觉 → 定位 → 根因 → 收获），面试主用 |
| `FRONTEND_AUDIT.md` | 第一阶段前端架构债审计 |
| `bench/CLOUD_TRAIN.md` | 云端 GPU 训练与推理环境手册 |
| `AGENTS.md` | 本仓库的硬约定（改代码前必读） |

---

## 8. 已知限制

- **Docker 部署未完成**：目前是本地直跑，容器化与 CI 仍在待办清单里。
- **微调未达预期**：SFT 三个版本均未超过底座（98.75%），结论是底座已足够强时应优先提示词工程
  与小分类器，而非微调整个 4B 模型。该结论有数据支撑，见案例 12。
- **`envirment/` 不在仓库内**：运行前端需自备 JDK / Tomcat / GeoServer 环境。
- **语料与模型权重不入库**：`.data/`、`models/llm/`、`bench/lora_out/**/*.safetensors` 均被忽略，
  需按脚本重建或自行下载。

---

## 9. 说明

- 第一阶段的三维可视化平台为团队既有系统，本仓库在其基础上延伸；第二阶段 Agent 模块为独立开发。
- 项目内文献目录中的 PDF 仅用于本地实验，版权归原作者所有。
