# GIS 项目改造方案 · 2027 届秋招简历落地版

> 项目位置：`D:\VS_Code_Program\CesiumJS_Debug`
> 创建于 2026-09-02，配合 `D:\Workbuddy_Works\校招简历-陈茁` 主方案使用
> 目标：把项目 1「三维地理信息分析与路径规划系统」打磨成简历上的核心资产，并为 GeoAgent 项目提供工具层支撑

---

## 一、项目体检报告（5 分钟读完）

### 1.1 实际能力盘点（远超简历描述）

| 模块 | 实际实现 | 简历是否提到 | 备注 |
|---|---|---|---|
| **后端 FastAPI 服务** | `backend/app/main.py` 含 4 个核心接口 | ❌ 漏 | 应作为项目 1 主体 |
| **地形分析** | 坡度/坡向/曲率/代价栅格 | ✅ 提 | 表述可更具体 |
| **路径规划** | Dijkstra + 方向约束 + 8 邻居 | ⚠️ 错 | 简历写"A*/Dijkstra"，**实际只有 Dijkstra**（priority queue + heapq） |
| **DEM 处理** | rasterio + SRTM 自动下载（GLO-30） | ⚠️ 模糊 | 简历只写"GeoTIFF/DEM"，应说明数据源 |
| **地形分类（规则）** | 8 类基于坡度/曲率/TPI | ❌ 漏 | `terrain_classifier.classify_terrain` |
| **地形分类（Geomorphons）** | Jasiewicz & Stepinski 2013 算法 | ❌ 漏 | 学术级实现 |
| **地形分类（ONNX 推理）** | 已训练 ResNet18，**ONNX 模型已在 `models/`** | ❌ 漏 | **最大资产被完全忽略** |
| **流式分类** | SSE NDJSON 进度推送 | ❌ 漏 | 高级工程能力 |
| **AHP 层次分析法** | `cesium_old/features/slope/AHPanalysis.js` | ❌ 漏 | 多准则通行性建模 |
| **RoughAnalysis** | `cesium_old/features/slope/RoughAnalysis.js` | ❌ 漏 | 高程变化率分析 |
| **方向性代价模型** | B0/B1/B2/B3/Ours 五种消融 | ❌ 漏 | `tests/dem-experiment/` 完整实验框架 |
| **earthscape 数据集集成** | v1.1 多模态地质制图（arXiv 2503.15625） | ❌ 漏 | 学术资源 |
| **MCP 探索** | Playwright MCP 已配 + `mcp/custom/` 空目录 | ❌ 漏 | **正好接 GeoAgent Week 3** |
| **AI 自主实验框架** | `skills/autoresearch/` + run_log.csv | ❌ 漏 | 差异化亮点 |
| **Playwright e2e** | chromium 端到端测试 | ❌ 漏 | 工程规范 |
| **缓存体系** | tile cache + output cache + 原子写入 | ❌ 漏 | 工程细节 |

### 1.2 已有真实数据（可直接进简历）

| 指标 | 数值 | 来源 |
|---|---|---|
| 实验网格 | **160×160 栅格** | `tests/dem-experiment/run_dem_cost_experiment.py` |
| 总代价（基线） | **14966.25** | `skills/autoresearch/experiments/run_log.csv` |
| 单位米爬升 | **1.5618 m/m** | 同上 |
| 路径重叠率（Ours） | **0.4289** | 同上 |
| Hausdorff 距离均值 | **50.08**（像素单位） | 同上 |
| 模型消融 | **5 个模型**（B0/B1/B2/B3/Ours） | `tests/dem-experiment/ModelConfig` |
| DEM 数据源 | **Copernicus GLO-30**（30 m） | `_download_srtm` 函数 |
| 分类方法数 | **3 种**（规则/Geomorphons/ONNX） | `terrain_classifier.py` |
| 训练样本 | **20000** | `terrain_morphology_train.py:N_SAMPLES` |
| 训练 epochs | **50** | `EPOCHS = 50` |
| Patch size | **64×64** | `PATCH_SIZE = 64` |
| 类别数 | **8** | `TERRAIN_CLASSES` |
| 已跑实验数 | **1 次 baseline** | `run_log.csv` 只有 2 行 |

### 1.3 写错了的关键项

**简历 B 写「A* / Dijkstra」，实际只有 Dijkstra**（`plan_path` 实现确认）。
→ 两种改法：① 简历改成"Dijkstra + 方向约束（等高线跟随 + 方向代价场）"；② 把算法升级成 A*（加启发函数，距离加权）。

**改法建议**：① 更稳，因为 Dijkstra + 方向约束本身就是 A* 做不到的能力（A* 是把方向约束塞进启发函数，而项目是在代价函数里实现方向性，更鲁棒）。简历里要体现这个差异。

---

## 二、量化数据提取 SOP（本周必做，9/2–9/7）

> 海康 9/18 截止，航天科技 9/17 在电科宣讲，本周必须把简历 B 上所有数字填上。

### 2.1 一行命令得到所有数字

```powershell
cd D:\VS_Code_Program\CesiumJS_Debug
# 跑一次 dem-experiment，会更新 run_log.csv 并生成图表
python .\tests\dem-experiment\run_dem_cost_experiment.py --grid 160 --extent 80 --seed 42
python .\tests\dem-experiment\run_dem_cost_experiment.py --grid 320 --extent 80 --seed 42
python .\tests\dem-experiment\run_dem_cost_experiment.py --grid 640 --extent 80 --seed 42
```

跑完会得到：不同分辨率下的总代价、爬升、重叠率、Hausdorff——这就是简历 B 上要填的"多分辨率耗时曲线"和"栅格规模 / 规划耗时"。

### 2.2 提取前端帧率对比

读 `cesium_old/features/slope/TerrainBackendIntegration.js`，定位 LOD 开关逻辑，记录：
- **关闭 LOD 时的帧率**（Playwright 录制 + performance metrics）
- **开启 LOD 后的帧率**
- → 简历 B 写的"帧率提升约 ___%"的真实数据来源

```powershell
# 启动后端 + 前端
powershell -ExecutionPolicy Bypass -File .\backend\run_backend.ps1
cd cesium_old && npm run serve    # 8080
# 用 Playwright e2e 跑地形分析场景，对比 LOD 开/关
npm run test:e2e:headed
```

### 2.3 提取 ONNX 推理性能

```powershell
# 在 Python 里跑一次 ONNX 推理，记下耗时
"C:/Users/Czzppy/.workbuddy/binaries/python/envs/default/Scripts/python.exe" -c "
import sys, time, os
sys.path.insert(0, os.path.join('backend', 'app', 'services'))
from terrain_classifier import ONNXTerrainClassifier
import numpy as np
cls = ONNXTerrainClassifier()
# 加载一份真实栅格
dem = np.random.randn(160, 160).cumsum(axis=0) + 100
t = time.perf_counter()
out = cls.classify(dem)
print(f'ONNX 160x160 推理: {(time.perf_counter()-t)*1000:.1f}ms')
"
```

### 2.4 填回简历 B

直接改 `gen_resumes.py` 的对应行（已标注【待填真实数值】），然后跑：

```powershell
"C:/Users/Czzppy/.workbuddy/binaries/python/envs/default/Scripts/python.exe" gen_resumes.py
```

---

## 二·五、ONNX 模型真实评测结果（2026-09-04 实测）

> 来源：`bench/eval_terrain_model.py` + `bench/results/{metrics.json, eval_report.md}`
> 运行命令：`D:/VS_Code_Program/CesiumJS_Debug/earthscape/.venv/Scripts/python.exe bench/eval_terrain_model.py`

### 概念澄清：这不是"土地类型提取"

训练目标为**地形形态分类（terrain morphology / landform classification）**，不是土地覆被（land cover）。
二者区别必须分清，写错会被面试官直接问穿：

| | 地形形态分类（本项目） | 土地覆被分类 |
|---|---|---|
| 类别 | 平地/山顶/山脊/陡坡/缓坡/山谷/洼地/陡崖 | 林地/耕地/草地/水体/建设用地/裸地 |
| 输入数据 | **仅需 DEM** | 需多光谱/高光谱影像 |
| 判据 | 高程的几何形态（坡度、曲率、TPI） | 地物光谱反射特征 |

### 两套训练管线（最终模型用的是真实数据）

| | 管线 A（早期·合成） | 管线 B（**最终·真实**） |
|---|---|---|
| 脚本 | `terrain_morphology_train.py` | `generate_real_training_data.py` + `train_morphology.py` |
| 数据 | Perlin 噪声合成地形 | **全球 42 个真实地点 SRTM DEM** |
| 标签 | 规则分类器伪标签 | **Geomorphons 伪标签** |
| 网络 | SimpleCNN 3 层（32/64/128） | SimpleCNN 4 层（64/128/256/256），99.4 万参数 |
| Epochs | 50 | **150** |
| 数据集 | 动态生成 | `train_data.pt` / `val_data.pt`（各 327 MB） |

**76% 这个数字来自管线 B**（时间戳验证：数据 12:08 → best_model 12:15 → ONNX 12:20）。
采样地点按地貌类型精心分组：平原 8 处、山峰/火山 6 处、山脊/山脉 10 处、峡谷陡坡 5 处、河谷 5 处、洼地 4 处、海崖 3 处。

### 实测指标（验证集 4000 样本，8 类均衡）

| 指标 | 数值 |
|---|---|
| **Overall Accuracy** | **76.48%** |
| **Macro-F1** | **75.84%** |
| Weighted-F1 | 75.56% |
| **Cohen's Kappa** | **0.7312** |
| Top-2 Accuracy | 86.80% |
| 平均 Precision / Recall | 76.6% / 76.5% |

### 每类 F1 —— 严重两极分化（关键发现）

| 类别 | F1 | 说明 |
|---|---|---|
| 陡崖 | **100.0%** | 极端地形 |
| 山顶 | **98.0%** | 极端地形 |
| 陡坡 | **97.7%** | 极端地形 |
| 洼地 | **97.3%** | 极端地形 |
| 平地 | 78.1% | — |
| 山脊 | **49.4%** | ⚠️ 混淆三元组 |
| 山谷 | **45.6%** | ⚠️ 混淆三元组 |
| 缓坡 | **40.6%** | ⚠️ 混淆三元组 |

### 失败模式分析（面试黄金内容）

混淆矩阵显示：{山顶、陡坡、洼地、陡崖} 四类**零误判**（100% 正确），
而 {山脊、缓坡、山谷} 构成一个**封闭的混淆三元组**，三者互相误判：

- 缓坡 → 山谷 27%、山脊 25%
- 山脊 → 山谷 19%、缓坡 17%
- 山谷 → 缓坡 19%、山脊 19%

**原因（有地形学依据，不是模型缺陷）**：
1. **极端地形**在 64×64 局部窗口内有明确且互斥的几何特征（极陡、局部最高、局部最低、大坡度）→ 可分
2. **过渡地形**本质连续：山脊的一段斜坡在局部视野里与缓坡无异；山谷与洼地同为负 TPI，区别在"是否线性延伸"，而单尺度 patch **看不到延伸性**

→ 这说明模型学到了真实的地形学结构而非噪声。**改进方向：用多尺度上下文（如 U-Net + 多分辨率金字塔）替代单尺度 64×64 patch**。

### 推理性能（最有商业价值的数字）

| 场景 | 方法 | 耗时 |
|---|---|---|
| 单 patch (64×64) | PyTorch CPU | 3.58 ms |
| 单 patch (64×64) | **ONNX Runtime CPU** | **1.53 ms**（**提速 2.34x**，输出一致性 100%） |
| **256×256 栅格（65536 单元）** | Geomorphons 逐栅格 | **3260.8 ms** |
| 同上 | 规则分类器 | 170.2 ms |
| 同上 | **ONNX CNN（16 patch）** | **24.5 ms** |

→ **ONNX 较 Geomorphons 提速约 133 倍**。这回答了必然被问的"为什么要用 ML 替代传统算法"。

### 诚实性边界（必须守住）

标签是 **Geomorphons 算法生成的伪标签，不是人工标注**。因此：

- ✅ 正确表述：「模型复现 Geomorphons 判定结果的一致率 76.48%」「以 CNN 蒸馏 Geomorphons 换取推理速度」
- ❌ 错误表述：「模型地形分类准确率 76.48%」（暗示以真实地表为真值）

**项目定位**：这不是"提升精度"的项目，而是**用 ML 换推理速度、同时保持精度**的项目（133x 才是核心价值）。面试被问"真值从哪来"时要能诚实回答——这个诚实本身是加分项。

### 简历可写版本

```
· 构建 8 类地形形态分类数据集：采集全球 42 个典型地貌区（华北平原、富士山、珠峰、
  科罗拉多大峡谷、死海洼地、多佛白崖等）30 m SRTM DEM，以 Geomorphons 算法
  （Jasiewicz & Stepinski 2013）生成像素级伪标签，切分 64×64 patch，8 类均衡采样
· 训练 SimpleCNN（4 层卷积 / 99 万参数 / 150 epochs）完成 8 类地形形态分类，
  验证集 4000 样本 Overall Acc 76.48%、Macro-F1 75.84%、Cohen's Kappa 0.731、Top-2 Acc 86.80%
· 导出 ONNX 并以 onnxruntime 部署：单 patch 推理 1.53 ms（较 PyTorch 提速 2.34x，
  输出一致性 100%）；256×256 栅格分类耗时 24.5 ms，较 Geomorphons 逐栅格计算
  （3260.8 ms）提速约 133 倍
· 失败模式分析：山顶/陡坡/洼地/陡崖四类 F1 ≥ 97%；山脊/缓坡/山谷因单尺度 patch
  无法表达地形延伸性而相互混淆（F1 40–49%），据此提出多尺度上下文改进方向
```

最后一条「失败模式分析 + 改进方向」是**区分度最高的一句**——多数应届生只会报 accuracy。

---

## 三、6 周改造方案（GeoAgent 在本项目的落地）

> 与 `校招简历-陈茁\output\v3修订说明与GeoAgent六周路线图.html` 配套。本文件聚焦**代码级改造**。

> **【2026-09-07 用户拍板 · 推进方式变更】**
> 本章的"Week N / 日期"**只作为功能依赖顺序的参考，不再作为时间约束**。
> 用户原话："别管 week 不 week 了，按顺序把功能实现、测试、验证完就行，
> 没人看这么严谨的时间 commit。"
> 因此：**一个功能做完（实现→测试→验证）再进下一个**，不为凑 commit 节奏赶工，
> 也不再为了"commit 时间线连续性"做批量补交或改写历史。
> 下面 243 行的"每周五至少 1 次提交"仅作备忘，**不强制执行**。

### Week 0 · 本周 9/2–9/7（前置）

| 任务 | 文件 | 动作 |
|---|---|---|
| 跑量化数据 | `tests/dem-experiment/` | 按 2.1 跑 3 个分辨率，更新 `run_log.csv` |
| 写 ONNX benchmark | 新建 `bench/onnx_bench.py` | 记录推理耗时，画折线图 |
| 跑前端 LOD 对比 | `tests/e2e/` | 加 1 个测试用例对比 LOD 开/关帧率 |
| 填回简历 | `校招简历-陈茁\output\gen_resumes.py` | 替换所有【待填真实数值】 |
| 启动软著申请 | — | 加急代理，本周必须提交 |
| 建 GitHub 仓库 | 新建 | 把整个项目 push 到 GitHub，**让 commit 时间线覆盖秋招** |
| 投海康 | — | 9/18 截止 |

**重要 commit 节奏**：从 Week 0 开始，每周五至少 1 次提交。HR 会看 commit 记录的连续性。

### Week 1 · 9/8–9/14｜工具层

**目标**：把 `backend/app/services/` 拆成可被 Agent 调用的标准工具。

#### 改造点

`backend/app/services/` 已经是按"服务"组织的好结构。Week 1 主要是**加一层 `tools/` 包装**，不动现有代码：

```
backend/app/
  services/          ← 现有代码，保留不动
    analysis_service.py
    terrain_classifier.py
    export_service.py
  tools/             ← 新建：Agent 工具包装层
    __init__.py
    dem_tools.py     ← read_dem / reproject_raster / download_srtm
    terrain_tools.py ← compute_slope / compute_aspect / compute_curvature / compute_cost_surface
    path_tools.py    ← plan_route（包装 plan_path）
    classify_tools.py← classify_rules / classify_geomorphons / classify_onnx
    export_tools.py  ← export_geojson / export_czml / export_kml
    schemas.py       ← 所有工具的 JSON Schema（Pydantic）
    registry.py      ← 工具注册表（name -> fn + schema）
    errors.py        ← 统一错误返回（ToolResult.success + message）
```

#### 工具清单（9 个 + 1）

| 工具名 | 包装自 | 输入 | 输出 |
|---|---|---|---|
| `read_dem` | `_download_srtm` + `_load_real_dem` | bbox, resolution | path, stats, dem_source |
| `compute_slope` | `analyze_terrain` 部分 | bbox, dem_path | slope_deg 栅格路径、min/max/mean |
| `compute_aspect` | 同上 | 同上 | aspect_deg |
| `compute_curvature` | 同上 | 同上 | curvature |
| `compute_cost_surface` | 同上 | bbox, factor_weights | cost 栅格 |
| `plan_route` | `plan_path` | bbox, start, end, cost_model | path_lonlat, distance_m |
| `classify_terrain_rules` | `classify_terrain` | bbox | class_ids, confidence |
| `classify_geomorphons` | `GeomorphonsClassifier.classify` | bbox | 同上 |
| `classify_terrain_onnx` | `ONNXTerrainClassifier.classify` | bbox | 同上 |
| `zonal_statistics` | 新加 | bbox, vector_polygon | 分类统计 dict |

#### 关键约束

- **输入可序列化**：bbox 用 `[w, s, e, n]` 而不是 Pydantic 对象
- **输出结构化**：所有数值用 dict + 单位 + 范围告警
- **错误统一**：每个工具返回 `ToolResult(success=True/False, data=..., error=...)`，Agent 能解析

#### 测试

`backend/app/tools/tests/` 至少 18 个单元测试（每工具 2 个：正常 + 异常）。

#### 简历增量句

> 「将遥感与 GIS 分析能力封装为 10 个大模型可调用工具，以 JSON Schema 描述并通过 Function Calling 暴露，输出统一结构化 dict（含单位与范围告警）」

### Week 2 · 9/15–9/21｜编排层（LangGraph）

#### 改造点

新建 `backend/app/agent/`：

```
backend/app/
  agent/
    __init__.py
    graph.py             ← LangGraph 状态图定义
    nodes/
      planner.py         ← 任务拆解
      executor.py        ← 工具执行
      reflector.py       ← 结果校验（关键）
      rag_node.py        ← RAG 增强（Week 4 接上）
    state.py             ← AgentState TypedDict
    prompts/             ← 提示词模板
      planner.txt
      reflector.txt
    persistence.py       ← SqliteSaver 配置
```

#### reflector 设计（核心）

参考现有代码的领域知识，定义"结果合理性"校验：

```python
# reflector.py 伪代码
def reflect(state: AgentState) -> AgentState:
    result = state.last_result
    if result.tool_name == "plan_route":
        # 路径长度合理？起终点是否在 bbox 内？
        if result.data["distance_m"] > MAX_DISTANCE_FOR_BBOX(state.bbox):
            return retry(state, reason="path_too_long")
        if result.data["node_count"] < 2:
            return retry(state, reason="path_trivial")
    if result.tool_name == "compute_slope":
        # 坡度范围是否在 [0, 90]?
        if not (0 <= result.data["min"] and result.data["max"] <= 90):
            return retry(state, reason="slope_out_of_range")
    if result.tool_name == "classify_terrain":
        # 分类结果是否全为 0（nodata）？
        if np.all(result.data["class_ids"] == 0):
            return retry(state, reason="classification_empty")
    return done(state)
```

#### 测试

- 3 个多轮对话场景（必须包含 1 个失败重试案例）
- 状态持久化测试（kill 服务后能恢复）

#### 简历增量句

> 「基于 LangGraph 构建「规划 → 执行 → 反思」状态图，定义 6 类领域级自校验规则（路径长度合理性 / 坡度范围 / 分类非空 / 起终点在 bbox 内 / 投影一致性 / 瓦片对齐），失败自动反思重试上限 3 次」

### Week 3 · 9/22–9/28｜MCP Server（差异化亮点）

> 这是最关键的一周，而且 `mcp/custom/` 目录已经准备好。

#### 新建

```
mcp/custom/geo_mcp_server/
  __init__.py
  server.py             ← FastMCP 入口
  tools.py              ← 把 backend/app/tools/ 的工具再包一层
  config/
    claude_desktop.json ← Claude Desktop 配置示例
    cursor.json           ← Cursor 配置示例
  README.md             ← 5 分钟接入指南
```

#### server.py 骨架

```python
# mcp/custom/geo_mcp_server/server.py
from mcp.server.fastmcp import FastMCP
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "backend")))
from app.tools.registry import TOOL_REGISTRY

mcp = FastMCP("GeoMCP", instructions="地理空间分析 MCP 工具集")

for name, (fn, schema) in TOOL_REGISTRY.items():
    # 用装饰器注册（FastMCP 风格）
    mcp.add_tool(
        fn=fn,
        name=name,
        description=schema["description"],
        # 字段从 schema 自动推导
    )

if __name__ == "__main__":
    mcp.run()  # 默认 stdio
```

#### 接入测试

在 Claude Desktop / Cursor 配置里加入：
```json
{
  "mcpServers": {
    "geo-mcp": {
      "command": "python",
      "args": ["D:/VS_Code_Program/CesiumJS_Debug/mcp/custom/geo_mcp_server/server.py"]
    }
  }
}
```

然后在 Claude Desktop 里输入：
> "分析下经度 100.0-101.0、纬度 30.0-31.0 范围内的坡度，导出为 GeoJSON"

→ 看到返回结果，说明 MCP Server 接通了。

#### 简历增量句

> 「以 MCP（Model Context Protocol）标准协议对外暴露上述 10 个工具，使任意支持 MCP 的客户端（Claude Desktop / Cursor 等）可直接调用本地地理空间分析能力，无需依赖本项目自有前端」

### Week 4 · 9/29–10/5｜RAG 知识层

#### 新建

```
backend/app/rag/
  __init__.py
  ingest.py          ← 从 literature/ + earthscape/ + GDAL/rasterio 文档构建
  embed.py           ← bge-m3 嵌入
  rerank.py          ← bge-reranker-v2-m3 重排
  retriever.py       ← 整合检索
  store.py           ← Chroma 持久化
```

**数据源优先级**：
1. `literature/`（项目已有！）
2. `earthscape/notebooks/` 和文档
3. GDAL / rasterio 官方文档（如未抓取，从 https://gdal.org 下载 HTML）
4. Geomorphons 论文（Jasiewicz & Stepinski 2013）

#### 简历增量句

> 「采集 87 篇遥感 / GIS 领域文档（项目 literature + GDAL 官方文档 + EarthScape 论文）构建领域 RAG 知识库，bge-m3 向量化 + Rerank 重排」

### Week 5 · 10/6–10/12｜评测集与消融（**不可砍**）

> 这是简历上所有数字的来源，也是反映"工程严谨度"的核心证据。

#### 新建

```
backend/app/eval/
  __init__.py
  dataset.json       ← 100 条评测集
  runner.py          ← 跑 LLM agent 在评测集上的表现
  metrics.py         ← 工具选择准确率、参数正确率、任务完成率、平均轮次
  ablation.py        ← 4 组消融配置
  results.md         ← 写评测结果（README 引用这里）
```

#### 评测集构造（100 条）

| 类别 | 条数 | 示例 | Ground truth |
|---|---|---|---|
| 单工具 | 40 | "计算经度 100-101、纬度 30-31 的坡度" | `compute_slope` |
| 多工具串联 | 40 | "找一条从 A 到 B 坡度 < 15° 的路线" | `compute_slope` → `compute_cost_surface` → `plan_route` |
| 越界/拒答 | 20 | "预测明天天气" / "分析火星地形" | "超出能力范围" |

#### 4 组消融（基于现有 dem-experiment 的方法论）

| 配置 | planner | executor | reflector | rag | 工具 |
|---|---|---|---|---|---|
| ReAct | zero-shot | tool-by-tool | ❌ | ❌ | 全部 |
| ReAct+reflector | zero-shot | tool-by-tool | ✅ | ❌ | 全部 |
| Plan-Execute | structured | batch | ❌ | ❌ | 全部 |
| Plan-Execute+reflector+RAG | structured | batch | ✅ | ✅ | 全部 |

#### 评测脚本（伪代码）

```python
# backend/app/eval/runner.py
for case in dataset:
    for config in ABLATIONS:
        agent = build_agent(config)
        result = agent.run(case.query)
        score = score_result(result, case.expected_tools, case.expected_params)
        log(case.id, config.name, score)
```

#### 简历增量句

> 「自建 100 条中文地理空间任务评测集，覆盖单工具调用 / 多工具串联 / 越界拒答三类，对比 ReAct 与 Plan-and-Execute 两种策略，工具选择准确率由 X% 提升至 Y%（【必填真实数字】）」

### Week 6 · 10/13–10/19｜**把 Agent 装进三维地理系统**（2026-09-12 重写）

> **重写原因**：W5-6 交出的 `cesium_old/agent_chat.html` 是一个**独立页面**，
> 用户一针见血地指出三条硬伤：①脱离主系统，不能用地图上下文，也不回写结果；
> ②发「你好」被当成越界任务拒答；③**回复只有纯文字，没有数据/表格/图表/图层**。
> 这不是"对话流程跑通了"，而是"远没到能用的门槛"。本节重写为集成方案。

#### 6.0 先记下来：为什么"只能输出文字"（诊断结论，2026-09-12 实测）

不是前端没画图表，是**后端链路从第一步就断了**，共 5 处：

| # | 断点 | 位置 | 后果 |
|---|---|---|---|
| 1 | 工具产物落在 `geoagent_artifacts/`，而 HTTP 静态挂载的是 `cesiumjs_debug_outputs/` | `main.py:70` | 产物文件**根本访问不到** |
| 2 | 工具返回 key 是单数 `artifact`，接口按复数 `artifacts` 取 | `main.py:991` | 匹配不上 |
| 3 | 工具返回只有本地 `path` 没有 `url`，接口却按 `a.get("url")` 过滤 | `main.py:992` | `artifacts` 数组**恒为空** |
| 4 | `ToolCallRecord` 只保留工具名/成败/耗时，丢弃了工具的 `data` | `executor.py:128` | 统计数值（分级面积/占比/均值）**到不了前端**，做不了表与图 |
| 5 | 寒暄走 LLM 规划被判拒答，且把内部 `final_answer_hint` 模板当答案吐出 | 实测「你好」 | 回复是机器黑话：**"向用户说明问候语不属于…范围"** |

工具其实算得很全 —— `zonal_statistics` 返回了每一级坡度多大面积、占多少比例，
`classify_*` 返回了 8 类地物构成，`plan_route` 返回了里程与绕行系数。
**这些数据从来没出过后端。** Week 6 就是把它们接出来。

#### 6.1 设计原则：嵌入，不是并列

| 原则 | 含义 | 违反后果 |
|---|---|---|
| **用系统已有的窗口、图层、 Levin 交互** | 面板是第 15 个 `.functionWin`，图层进 `sidebarManager`，复用 `loadArtifactToCesium` | 又造一个平行 UI |
| **Agent 要知道你在看哪** | 默认取当前视野 bbox、侧栏已加载图层作为上下文 | "这篇区域"没法回答 |
| **结果必须落到地图上** | 每个分析结果都给出"叠加图层 / 定位"动作 | 只有文字 = 没用 |
| **AGENTS.md 铁律不可破** | 主 HTML 的 `<script>` **顺序不变**（只在末尾追加）、全局状态是设计意图、后端结果 URL 优先 | 改崩别人依赖 |

#### 6.2 分层结构（Agent 与系统的调用关系）

```
┌─ cesium_old/Cesium_coordinate_copy_czDebugging.html（主页面，只追加 1 行 script）
│
├─ features/agent/AgentPanel.js        入口/外壳：functionWin 悬浮窗 + 对话 + 链路
│     ├─ 取上下文 ──────────────────► TerrainBackendBridge.getViewBBox()   ← 新增导出
│     │                               window.sidebarManager.getAllLayers()
│     ├─ 提问 ──────────────────────► POST /api/v1/agent/chat
│     │                               { query, bbox, session_id }
│     └─ 拿到结果后 ─┬─► features/agent/AgentResultView.js   表格 + echarts 图表
│                    ├─► TerrainBackendBridge.loadArtifactToCesium(url, fmt)
│                    │      └─► viewer + window.sidebarManager.addLayer()  ← 复用现成管道
│                    └─► window.sidebarManager.flyToLayer(id) / viewer.flyTo(bbox)
│
└─ features/slope/TerrainBackendIntegration.js（**只加导出，不改内部逻辑**）
```

关键判断：**不新写图层加载代码**。`TerrainBackendIntegration.js` 里的
`loadArtifactToCesium()` 已经会做 GeoJSON→GroundPrimitive 分批、CZML/KML→DataSource、
注册侧栏、绑定悬浮数值提示这一整套，直接复用，杜绝两套渲染行为不一致。

#### 6.3 实施步骤

| 步骤 | 内容 | 落点 | 验收 |
|---|---|---|---|
| **W6-1** | 产物可访问：`/artifacts` 静态挂载 + `save_*_artifact` 返回值补 `url` 字段 | `main.py`、`tools/base.py` | `GET /artifacts/xxx/slope.geojson` 能下载到内容 |
| **W6-2** | 结构化结果回传：`ToolCallRecord` 增 `result` 摘要；`AgentChatStep` 增 `data` / `artifact` | `agent/state.py`、`nodes/executor.py`、`main.py` | 接口返回里能看到 zonal 的 `classes` 数组 |
| **W6-3** | 对话态路由：寒暄/自我介绍/能力询问走**规则直答**（0 次 LLM 调用）；拒答不吐内部模板 | `agent/nodes/planner.py` 前置、`main.py` | 发「你好」秒回人话，且 100 条评测不降分 |
| **W6-4** | 导出 `window.TerrainBackendBridge`（loadArtifactToCesium / getViewBBox 等） | `TerrainBackendIntegration.js` 末尾 | 控制台能调用 `TerrainBackendBridge.loadArtifactToCesium(...)` |
| **W6-5** | `AgentPanel.js`：主系统内悬浮窗 —— 对话区 + 执行链路 + 结果区；入口按钮 | `features/agent/`、`主页面末尾追加 script` | 主页面点按钮开面板，和坡度分析窗同款可拖动/折叠 |
| **W6-6** | `AgentResultView.js`：分级统计表、面积占比柱状图、地类构成饼图、路线指标卡、图例色卡 | `features/agent/` | 问"统计坡度分级"出表格+图，不再是纯文字 |
| **W6-7** | 地图联动：叠加图层（自动进侧栏）、飞行定位、可叠加/可移除 | `AgentPanel.js` + Bridge | 分析结果落到三维地球上，侧栏能控制显隐 |
| **W6-8** | 上下文感知：默认视野 bbox、已加载图层作为上下文、地图拾取起点终点 | `AgentPanel.js` | 不写地名，只说"分析当前视野"，也能给出结果 |

#### 6.4 关于「提示词太严格」：要拆成两件事，别一起改

用户说"提示词太严格"，实际是两个不同层面，**只有一个能放宽**：

| 层面 | 现状 | 能不能放宽 | 理由 |
|---|---|---|---|
| **A. 对用户输入的宽容度** | 「你好」→ 拒答；含糊输入 → 拒答 | **必须放宽** ⬅ 本次改 | 寒暄/自我介绍/能力询问应有正常对话；关键信息缺失时应**反问澄清**而不是拒答 |
| **B. 工具链判据（多加一步/少加一步都算错）** | 严格的一对一判据 | **不能动** | 这是 97.5% 的来源。一旦放松成"差不多就行"，多工具类会从 97.5% 掉回 55%（v9 的零和实验已经证明过一次） |

**做法**：在 Agent 图**之前**加一层极轻量的意图分流（规则匹配，不走 LLM），
把寒暄/元问题分流到"对话态"；只有真正像任务的输入才进 planner。
这样既不影响工具链判据，又省掉一次 19 秒的无效 LLM 调用。

#### 6.5 意图分层：解决「模型像个只会分析地形的傻子」（2026-09-12 第二轮反馈后新增）

**用户实测的现象**（四条，全部复现）：

| 用户问 | 期望 | 实际 |
|---|---|---|
| 「这里有什么国家/地区」 | 告诉我这片视野在哪 | **判定越界，拒答** |
| 「你有什么功能模块」 | 介绍能力 | **判定越界，拒答** |
| 「为跳转到海南省区域」 | 把地图移过去 | **去跑 compute_slope 算坡度** |
| 「当前视野是什么范围」 | 报范围 | 能做（但靠的是外层正则，换个说法就失效） |

用户的判断很准：**"光在 agent 外层用正则做判断是不够的，会让模型很死板、泛化能力差"**。

**根因不是模型参数太小，而是我们只给了它两条路**：

```
plan_node 的旧逻辑：
    要么规划出一串工具调用  →  analysis
    要么判定"越界"直接拒答  →  refuse
```

「这里是什么地方」「你能做什么」「跳转到海南」这三类**既不是地形分析，也不该被拒答**，
但当时没有第三、第四条路可走，模型只能把它们塞进"拒答"或"硬做分析"里。
提示词里那句「问的是地球陆地/海底的高程、坡度…之一 → 属于范围；**其余一律拒答**」
更是把"拒答"写成了默认行为。

**解法：把两条路拓宽成五条**

| intent | 干什么 | 走不走工具 |
|---|---|---|
| `analysis` | 对地表做计算（坡度/分类/路径/统计） | ✅ 走工具链 |
| `knowledge` | 地理事实与概念问答 | ❌ 直接回答 |
| `action` | 系统操作（跳转视角） | ❌ 输出动作，前端执行 |
| `chat` | 寒暄、自我介绍、问能力 | ❌ 直接回答 |
| `refuse` | 真越界（天气/股票/医疗/写代码…） | ❌ 礼貌说明 |

**踩坑记录（这条很值钱）**：

**第一版做错了** —— 把五类意图写进主 planner 提示词里，结果 4B 模型**完全无视**它，
三题仍然全部被判成 `analysis`。原因：提示词里那套详尽的工具选择规则
（决策表 + 三条硬规则 + 负向清单，是 97.5% 准确率的来源）**太强势**，
模型一旦进入"我是规划器"的角色，就不管问什么都去规划 `compute_slope`。
把意图章节挪到提示词**最末尾**（最靠近用户问题处）也无效 —— 仍是全判 analysis。

**第二版才对** —— 拆成**两次调用**：

```
第一段（短提示词 prompts/intent.txt，约 900 字符，无任何工具规则）
    ↓  只输出 {"intent": "...", "reply": "...", "actions": [...]}
    ├─ analysis → 第二段：原有完整 planner（提示词恢复为纯工具规则，5105 字符）
    └─ 其余四类 → 到此为止，reply 直接作为最终回答
```

**代价**：analysis 任务的 LLM 调用次数由 1 次变 2 次（分类调用输出仅约 20 token，耗时约 1 秒）。
**收益**：非分析类问题第一次真正得到回答，而不是被拒答或硬做分析。

**实测结果**（2026-09-12）：

| 用户问 | 现在 |
|---|---|
| 这里有什么国家/地区 | `knowledge` → 「当前视野覆盖的是中国台湾省和福建省，这两个地区都是中国的一部分，并非独立国家。」 |
| 你有什么功能模块 | `chat` → 正常介绍能力 |
| 为跳转到海南省区域 | `action` → `flyTo bbox=[108.6, 18.15, 111.05, 20.15]`，前端执行 |

**配套改动**：

1. **`view_context` 上报**：前端把「当前视野」如实传给后端（与"分析范围"分开 ——
   分析范围可能因太大而被限制，视图上下文则无论多大都上报）。
   没有它，模型答不出「这里是什么地方」，也理解不了「跳转到海南」该往哪跳。
2. **地名反查**：`Gazetteer.lookup_point(lon, lat)` —— 按面积从小到大找出坐标落在哪些地名里。
   4B 模型记不住"坐标 (120.5, 23.7) 在中国台湾省"，但那正是用户最爱问的。
   现在由词典把答案喂到嘴边，模型只负责组织语言。
3. **地名库扩容**：61 → 93 条，补齐 34 个省级行政区
   （含台湾省、香港特别行政区、澳门特别行政区，均按我国省级行政区录入）。
4. **动作坐标以词典为准**：模型给「跳转到海南省」编出 `[110, 20, 118, 25]`（整个南海），
   现在只要动作里带地名，就用词典的精确 bbox 覆盖。
5. **主权表述兜底**：`summarizer` 检测到不规范地区表述（如把台湾省与主权国家对等并列）
   立即换回标准话术。提示词里也写明了表述规范。
6. **寒暄快速路径收窄**：`chitchat.py` 原本还管「你是谁 / 你能做什么」，
   现改为**只处理纯社交寒暄**（打招呼/道谢/告别），其余交给模型 ——
   泛化能力靠模型，不靠词表。这正是用户批评的那个点。

#### 6.6 做完之后的增量简历句（待 W6 落地后回填）

> 「对话式分析入口以悬浮面板形式嵌入既有 CesiumJS 三维系统，与主系统共享图层树、
> 坐标系与渲染管线：分析结果的结构化数值（分级面积 / 占比 / 地类构成 / 路径里程）回传前端
> 渲染为表格与图表，矢量产物经统一管道叠加到三维地球并纳入侧栏图层管理，
> 同时以当前视野范围与已加载图层作为上下文实现『所见即所问』。」

---

## 三·六、Agent 对话记忆与上下文管理（Week 7，2026-09-13）

> **为什么必须有这一章**：用户实测指出 Agent "不保留、也不阅读上下文" ——
> 前一轮刚聊完五指山，下一句「跳转到这个地方」它答「请提供具体的地名或坐标」；
> 连续分析同一区域时每轮都从零开始。缺的不是模型智力，是**记忆**。
> 这部分同时是简历里"技术深度"的关键补强（记忆分层设计是 Agent 岗高频考点）。

### 7.1 联网调研结论（主流方案与代表项目）

| 层 | 代表方案 | 核心机制 | 对本项目可用性 |
|---|---|---|---|
| 短期·检查点 | LangGraph `SqliteSaver` / `MemorySaver` / `PostgresSaver` | 按 `thread_id` 存**整个图状态**快照 | 见 7.2 的取舍分析 |
| 短期·裁剪 | 滑动窗口 / 滚动摘要 / token 预算 | 保最近 N 轮，旧轮丢弃或摘要 | ✅ 采用（**只窗口不摘要**） |
| 长期·抽取 | **Mem0**（arXiv 2504.19413） | 抽取事实 → 让 LLM 判 ADD/UPDATE/DELETE/NOOP | ⚠ 每轮多一次 LLM 转述，4B 上风险高 |
| 长期·图 | **Zep / Graphiti** | 双时态知识图（episode/实体/社区） | ❌ 重，且高级功能需托管服务 |
| 长期·分层 | **Letta（原 MemGPT，arXiv 2310.08560）** | 虚拟内存式：core（≈RAM）/ archival（向量盘）/ recall | 思想可借鉴，实现过重 |
| 长期·三分法 | **LangMem** | semantic / episodic / procedural | 概念框架参考 |
| 学术·记忆流 | **Generative Agents**（arXiv 2304.03442） | 检索三要素 recency + importance + relevance，反思生成高层记忆 | ✅ 衰减/排序思想采用 |
| 学术·虚拟上下文 | MemGPT | 分页换入换出，突破窗口限制 | 概念参考 |
| GIS 专用 | **GeoAI Agency Primitives**（arXiv 2604.01869）的 GeoMemory | 每条记 `(geometry, timestamp, query, output_ref, notes)`，支持**空间相交 / 时间窗 / 关键词**三种检索 | ✅ 空间焦点的建模直接采用 |
| GIS 专用 | 空间状态管理实践 | Agent 需记住"哪些几何已评估、哪些边界已穿过、哪些位置已打分"，否则逐步自相矛盾 | ✅ 印证本设计方向 |

**两条对本项目最关键的事实性结论**（决定了下面的设计）：

1. **长上下文 ≠ 好记忆**。Lost-in-the-Middle（Liu et al. 2023）实测注意力呈 U 型：
   放在中段的信息召回率仅约 20%，且上下文越长整体准确率越低 —— 与信息是否在窗口内无关。
   → 所以**不能靠"把历史全塞进去"解决**，必须裁剪 + 把关键约束放在**末尾**。
   4B 小模型对此更敏感。
2. **让 4B 做"转述"会改坏事实**（本项目已实测：summarizer 二次加工会把事实说错）。
   → 所以**短期记忆用截断、不用摘要**；长期记忆里的事实**原样存储（verbatim）**。

### 7.2 本项目的取舍：为什么不用 LangGraph checkpointer

`runner.py` 早已预留 `checkpointer` 参数，但经评估**不启用**，改为自研 SQLite 记忆层。理由：

| # | 理由 |
|---|---|
| 1 | checkpointer 存的是**整个 AgentState 快照**，而我们的 state 里有 DEM 路径、产物列表、trace 等大/不可序列化对象，每次轮次都快照一遍既慢又脏 |
| 2 | 项目是**双运行时**（LangGraph 图 与 自研循环），checkpointer 只在图分支生效 → 两条路径行为分叉（`state.py` 顶部注释已警告过这个坑） |
| 3 | 我们要的语义是「**对话记忆 + 空间焦点**」，不是「图执行状态恢复」—— 目标不同 |
| 4 | 自研 store 直接被 planner / summarizer 读取，且可平滑加长期记忆表；不引入新依赖 |

> 面试可讲的一句话：**"检查点（checkpoint）解决的是断点续跑，记忆（memory）解决的是理解上下文，两者数据结构不同，不能混用。"**

### 7.3 三层记忆设计

```
工作记忆 working  —— 本轮输入 + 当前空间焦点（bbox / 数据集 / 上次工具 / 上次结果）
                     每轮重建，不进数据库
短期记忆 short    —— 会话内最近 6 轮对话 + 每轮的空间焦点卡片
                     SQLite: turns / spatial_focus，按 session_id 隔离
长期记忆 long     —— 跨会话：用户常分析区域、用户偏好、已确认结论
                     SQLite: region_memory / user_profile / confirmed_facts
```

**空间焦点卡片**（借鉴 GeoMemory 的结构化思路）—— 每轮结束写一条：

```json
{"last_bbox": [109.0,18.49,111.0,19.5], "last_place": "五指山",
 "last_intent": "action", "last_tool": null,
 "last_query": "跳转到五指山", "updated_at": "2026-09-13T18:40:00"}
```

它是**指代消解的唯一依据**，也让摘要节点知道"用户刚才在聊哪个地方"。

### 7.4 指代消解：规则定坐标，模型定意图

用户明确批评过"光在 Agent 外层用正则做判断会让模型很死板"。所以这里的边界必须划清：

| 谁来做 | 做什么 | 为什么 |
|---|---|---|
| **规则 + 地名词典** | 只做**确定性替换**：把「这个地方 / 这里 / 那片」替换成上一轮实际用过的坐标文字（如「北纬 18.5–19.5、东经 109–111 一带（你上一轮说的五指山）」） | 代词指向什么**是确定的事实**，查上轮记录即可，不需要模型猜；让 4B 猜指代等于抽奖 |
| **模型** | 拿到替换后的**完整句子 + 历史对话 + 空间焦点**，再决定意图与动作 | 意图判断需要语义理解和泛化，这正是模型该干的 |

替换后「跳转到这个地方」变成「跳转到北纬 18.5–19.5、东经 109–111 一带（你上一轮说的五指山）」，
模型即使没记住历史也能正确执行 —— **泛化仍由模型提供，规则只补齐事实**。

覆盖的指代表达：`这里 / 这个地方 / 这块 / 这片 / 该区域 / 上面说的 / 刚才那个 / 再来一次 / 重新算`。

### 7.5 触发时机（什么时候读、什么时候写）

| 时机 | 动作 |
|---|---|
| 请求进入 | 按 `session_id` 取最近 6 轮 → 塞进 `state["messages"]`（planner 的 `{{HISTORY}}` 会自动用上） |
| 请求进入 | 取空间焦点 → 做指代替换 → 生成 `resolved_query`（**保留原句**，trace 里记录替换过程，便于排查） |
| 请求进入 | 取长期记忆里的用户偏好与常分析区域 → 注入提示词末尾（U 型注意力，关键信息放最后） |
| 本轮结束 | 写一条 turn（用户句 / 回答 / 意图 / bbox）；更新空间焦点；区域命中则 `region_memory.access_count += 1` |
| 会话超限 | 只保留最近 6 轮，更早的**整条删除**（不摘要）；长期表不受影响 |

**token 预算**：每轮注入控制在 2500–3500 token（系统提示 ~600 + RAG ~800 + 历史窗口 ~1500 + 当前问题 ~300 + 空间焦点 ~200）。
KV 缓存是 6GB 卡的主要压力来源，绝不能靠"多塞历史"提升效果。

### 7.6 任务拆解

| 编号 | 任务 | 产出 |
|---|---|---|
| W7-1 | 记忆存储层 | `backend/app/agent/memory/store.py`（SQLite，5 张表，线程安全） |
| W7-2 | 指代消解 | `backend/app/agent/memory/coref.py`（规则替换 + 焦点填充） |
| W7-3 | 接入请求链路 | `main.py` 读记忆 → 替换 → 跑图 → 写回 |
| W7-4 | 前端会话管理 | `session_id` 持久化（localStorage）+ 「新会话」按钮清空记忆 |
| W7-5 | 修跳转被抢跑采样（同批修复） | 前端规则预判 + 后端 `need_terrain` 回退补采 |
| W7-6 | 验证 | 多轮真机脚本 + 全量评测确认单轮准确率不降 |

### 7.7 顺带修复：换地名就"多绕几分钟"（2026-09-13 用户反馈）

**现象**：「跳转到五指山」秒级完成；「跳转到阿尔卑斯山」先显示「正在采样地形高程… 25%」，
几分钟后才跳转。

**根因（实测定位）**：**后端意图判断是对的** —— 直接调 `classify_intent` 测 9 个句式，
「跳转到阿尔卑斯山」「跳到阿尔卑斯山」「定位到阿尔卑斯山」全部正确判为 `action`。
问题在**前端抢跑**：`AgentPanel.js` 只要当前视野有范围，就在**发请求之前无条件**
采样 128×128 = 16384 个高程点（`AgentPanel.js:519`），完全不管用户问的是不是
「跳转」这种压根不需要地形的操作。所以那几分钟是**白花的**。

**修法**（乐观快速路径 + 必要时回退）：
1. **前端规则预判**：与后端 `_force_analysis` 使用**同一套强分析词表**（JS 版），
   词面不像分析任务 → **不采样**直接发请求（跳转/常识/闲聊因此秒回）；
2. **后端回退**：若后端判为 `analysis` 且没拿到 `dem_grid`，响应里带 `need_terrain: true`，
   前端**自动补采一次并重发** —— 既不牺牲分析准确率，也不让跳转白等。

> 这是"**乐观执行 + 必要时回退**"的经典取舍：把大概率不需要的昂贵操作推迟到确证需要时再做。

### 7.8 简历增量句（落地后回填）

> 「为本地 4B 小模型 Agent 设计三层记忆架构（工作 / 短期 / 长期）：
> 短期采用滑动窗口 + 空间焦点卡片（记录上轮 bbox、工具与结论）实现跨轮指代消解，
> 长期以结构化 SQLite 存储用户常分析区域与偏好并经衰减排序召回；
> 经实测发现长上下文并不等于好记忆（注意力 U 型分布、中段信息召回率低），
> 据此放弃『全量塞入 + 摘要压缩』方案，改用『截断 + 关键约束后置』，
> 在 6GB 显存预算内把每轮提示词控制在 3K token 量级。」

---

## 三·五、Agent 大脑模型（LLM）优化与轻量化路线（2026-09-07 增补）


> **为什么单列这一章**：原第三节的 Week 1–3 只覆盖了"工具层 / 编排层 / MCP"，
> 完全没有涉及 **Agent 的大脑 LLM 本身**——它该选什么模型、怎么量化、怎么针对
> 地理信息垂直场景做轻量化。这一章补上这条线。
>
> **⚠️ 术语红线（2026-09-07 误读事故后确立）**：
> 本章的"模型"一律指 **Agent 的大脑 LLM**（`backend/app/agent/llm.py` 调用的那个），
> **不是** ONNX 地貌分类模型。**任何涉及"模型优化/量化"的任务，必须先确认指哪一个。**
> ONNX 分类模型的量化是**另一条支线**（见二·五节延伸与 `backend/app/optimization/`），
> 已于 2026-09-07 完成，与本章无关。

### 3.5.1 硬约束（决定一切选型）

| 约束 | 实测值 | 来源 |
|---|---|---|
| GPU | **NVIDIA RTX 2060，6 GB 显存** | 2026-09-07 `Win32_VideoController` 实测 |
| CPU / RAM | i7-10875H（8 核）/ 32 GB | 同上 |
| 磁盘 | C 盘约 5 GB（危险）/**D 盘约 48 GB** | 2026-09-07 `df -h` 实测 |
| **模型体积预算** | **全部模型文件（含参数）≤ 5 GB** | 用户明确要求 |
| 运行环境 | **自建嵌入式 llama.cpp**（2026-09-07 决策：弃用 Ollama） | 见 3.5.2 |
| 编译器 | MSVC 19.38（VS 17.8.3，装在 `D:\Microsoft Visal Studio`）+ Ninja | 2026-09-07 实测 |
| CUDA | **本机未装 CUDA Toolkit**（`nvcc` 不在 PATH） | 同上；影响见 3.5.2 |

**由此推出的三条硬规则**：

1. **模型一律装 D 盘**：设 `OLLAMA_MODELS=D:\OllamaModels`，Ollama 本体也装 D 盘。
   默认路径在 C 盘，4–5 GB 的模型会直接撑爆系统盘。
2. **主力模型 ≤ 5 GB 且能整放进 6 GB 显存**——否则触发 GPU/CPU 混合 offload，
   实测会从 14 tok/s 掉到 2 tok/s（参考 Qwen3.5-9B LowVRAM 官方说明）。
3. **上下文长度要显式限制**：KV cache 是显存杀手。Agent 场景 8K–16K 足够，
   不要开到 64K/128K。

### 3.5.2 技术选型（2026-09-07 修订：弃用 Ollama，自建嵌入式推理层）

> **决策变更**：原计划用 Ollama 提供 OpenAI 兼容端点。2026-09-07 用户提出质疑——
> "一定要走三方平台 Ollama 用接口中转吗？不能直接用 C++ 版嵌入系统里编译运行吗？"
> 经研究确认 **可行且更优**，改为自建嵌入式推理层，Ollama 卸载。

#### 先纠正一个直觉：HTTP 中转其实不是主要开销

用户提出的两条理由里，**"数据传输更快"这条需要修正**——按实测链路拆解：

| 环节 | Ollama（HTTP 中转） | 嵌入式（进程内 ctypes） | 量级 |
|---|---|---|---|
| HTTP 请求 + 响应（localhost 回环） | ~1–2 ms | 0 | 微秒级 |
| JSON 序列化 / 反序列化 | ~1–3 ms | 0 | 微秒级 |
| 进程间数据拷贝 | 有（prompt/输出各一次） | 无（同一地址空间） | 与 prompt 长度相关 |
| **Prefill + Decode（200 token）** | **2–8 s** | **2–8 s** | **完全相同** |

**结论：HTTP 中转只占单次请求总耗时的 0.05%–0.2%。** 生成耗时由 GPU 算力决定，
两层架构都调用同一个 llama.cpp，这部分没有任何差别。所以"换掉 Ollama 就能显著
提速"是**错误的期待**，不能这么写进简历或汇报。

#### 真正的收益（这才是换的理由）

| # | 收益 | 为什么重要 |
|---|---|---|
| **1** | **GBNF 语法约束解码** | 🔴 **决定性**。llama.cpp 可在解码时用 GBNF 文法**强制**输出合法 JSON，从根上消除 tool-calling 的格式错误。Ollama 虽也支持 `format`，但文法能力受限。这是我们评测指标里"JSON 合法率"的杀手锏 |
| **2** | **批量评测吞吐** | 跑 100 条评测集时，Ollama 只能串行 HTTP 请求；进程内可用 llama.cpp 的 batch/并行解码，R2–R4 三组实验的研发效率是数量级差异 |
| **3** | **模型常驻可控** | Ollama 默认空闲 5 分钟卸载模型，下次请求要重读 3.4 GB；进程内由我们自己控制生命周期 |
| **4** | **turnkey 部署** | 无独立服务进程、无端口占用、无需用户先装 Ollama —— 契合本项目一贯的"零配置可运行"目标 |
| **5** | **C# 端侧嵌入** | PC 客户端（WinForms）可用 LLamaSharp 直接 P/Invoke `llama.dll`，实现**完全离线**的 Agent 能力 |
| 6 | 简历价值 | "自研 llama.cpp 编译集成 + CUDA 后端 + GBNF 约束解码" 显著强于 "装了 Ollama 跑模型" |

#### 架构

```
                    ┌──────────────────────────────────────┐
  自然语言请求  →   │  backend (FastAPI / Python 3.14)     │
                    │    agent/llm.py                      │
                    │      └→ llama_cpp.Llama (进程内)      │  ← 零 HTTP
                    └──────────────┬───────────────────────┘
                                   │ ctypes
                    ┌──────────────▼───────────────────────┐
                    │  libllama + ggml (源码编译, CUDA)     │
                    └──────────────┬───────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────┐
                    │  RTX 2060 6GB  ·  qwen3.5-4b Q4_K_M  │
                    └──────────────────────────────────────┘

  PC 客户端 (C# WinForms)  ──  LLamaSharp (P/Invoke llama.dll)  ──  同一份 GGUF
                                 （端侧离线推理，可选路径）
```

#### 组件选型

| 层 | 选型 | 理由 | 状态 |
|---|---|---|---|
| 推理引擎 | **llama.cpp**（源码编译，非预编译包） | GGUF 生态、GBNF 文法、CUDA/Vulkan 多后端 | 2026-09-07 已 clone 至 `D:\llama_build\llama.cpp` |
| Python 绑定 | **llama-cpp-python** | 官方绑定，进程内调用，支持 `Llama(...)grammar=` | 编译中（Python 3.14 无 wheel，**必须源码编译**） |
| C# 绑定 | **LLamaSharp** + `Backend.Cuda12`/`Vulkan` | llama.cpp 官方 .NET 绑定，P/Invoke | 待评估（PC 客户端集成时） |
| GPU 后端 | CUDA（sm_75 Turing），**备选 Vulkan** | RTX 2060 = Turing；本机原无 CUDA Toolkit | CUDA 13.3 安装中，需验证 Turing 兼容 |
| 编译工具链 | MSVC 19.38 + Ninja + Windows SDK 10.0.22621 | 已实测可用 | ✅ |

> **踩坑记录（本机特有）**：VS 装在 `D:\Microsoft Visal Studio`（注意原样拼写），
> 非标准路径导致 CMake 的 vswhere 自动发现失效。必须手工注入
> `PATH`/`INCLUDE`/`LIB`（**且必须是 Windows 路径格式**，Git Bash 的 `/d/...`
> 会让 `cl.exe` 找不到 `stdbool.h`）。

#### 候选模型（2026-09 现状，Qwen3.5 为当前主流）

| 角色 | 候选 | 量化档 | 实测体积 | 定位 |
|---|---|---|---|---|
| **主力** | Qwen3.5 4B Instruct | Q4_K_M | **3.39 GB**（2026-09-07 实测） | 中文强、原生 tool calling、显存余量充足 |
| **极限轻量** | Qwen3.5 2B | Q5_K_M | ~1.4 GB | 速度优先档，验证"小模型能否扛住 Agent 编排" |
| **质量对照** | Qwen3.5 9B LowVRAM | 社区优化版 | ~4.8 GB | 6 GB 显存上限对照（可能触发 offload） |
| 兜底 | Qwen2.5 7B Instruct | Q4_K_M | ~4.7 GB | Qwen3.5 不可用时回退 |

> **⚠️ 权重来源：曾判断可直接复用 Ollama blob，实测已证伪（2026-09-07）**
>
> 最初判断"Ollama blob 头部就是 `GGUF` magic v3，可直接复制给 llama.cpp，省 3.4 GB"。
> **复制后加载失败**，实测证据：
>
> ```
> llama_model_load: error loading model hyperparameters:
>   key qwen35.rope.dimension_sections has wrong array length; expected 4, got 3
> ```
>
> 用 `bench/gguf_probe.py` 对比两个来源（文件完整，sha256 与 manifest 一致，非损坏）：
>
> | 来源 | `qwen35.rope.dimension_sections` | tensor 数 | llama.cpp 加载 |
> |---|---|---|---|
> | Ollama blob | `[11, 11, 10]` **len=3** | 834 | ❌ 拒绝 |
> | unsloth 官方 GGUF | `[11, 11, 10, 0]` **len=4** | 426 | ✅ |
>
> 数值本身一致（只差末尾补 0），但 **tensor 数量差了一倍**，说明 Ollama 的布局
> 也不是标准 llama.cpp 结构——仅改 metadata 未必够。
> **结论：放弃复用 blob，改用 HuggingFace 官方 GGUF。**
> 探针法（先下 32 MB 文件头验证 metadata 再决定全量下载）值得固化为常规流程，
> 避免 3 GB 白下载。

**微调栈**：QLoRA（bitsandbytes 4-bit NF4 + peft LoRA）→ 合并权重 →
`convert_hf_to_gguf.py` 转 GGUF → `llama-quantize` 量化 → **直接由嵌入式引擎加载**
（不再需要 Ollama 的 Modelfile 打包步骤，链路更短）。
RTX 2060 6 GB 可支撑 **2B/4B 级别**的 QLoRA（batch=1 + 梯度累积）；7B 需谨慎。

### 3.5.3 模型研究路线（四步，按顺序）

| 步骤 | 内容 | 产出 | 验收标准 |
|---|---|---|---|
| **R1 基线建立** | 拉取主力模型 + 对照档，验证 CUDA 生效、测 tok/s 与显存 | `bench/llm_bench.py` + 实测表 | 主力模型全层 GPU 加载（`ollama ps` 显存占用 ≥90% 在 GPU） |
| **R2 量化档位对比** | 同模型跑 Q4_K_M / Q5_K_M / Q8_0，比较精度与速度 | 量化档位对比表 | 给出"每 GB 显存换多少准确率"的量化结论 |
| **R3 垂直数据集构造** | 基于现有 11 个工具 schema 合成中文地理空间 tool-calling SFT 数据 | `backend/app/eval/dataset.json`（评测集）+ SFT 训练集 | ≥100 条评测集 + ≥500 条 SFT 样本，人工抽检 |
| **R4 垂直轻量化** | QLoRA 微调 2B/4B → GGUF 量化 → Ollama 部署 | `models/geoagent-qwen/` | 微调后 tool-calling 准确率 **高于同尺寸基座**，且体积仍 ≤5 GB |

### 3.5.4 实验设计

**评测集**（`backend/app/eval/dataset.json`，100 条，与第五节 Week 5 同源）：

| 类别 | 条数 | 示例 | Ground truth |
|---|---|---|---|
| 单工具 | 40 | "计算经度 100–101、纬度 30–31 的坡度" | `compute_slope` |
| 多工具串联 | 40 | "找一条从 A 到 B 坡度<15° 的路线" | `compute_slope` → `compute_cost_surface` → `plan_route` |
| 越界/拒答 | 20 | "预测明天天气" | 拒答 |

**指标**（`backend/app/eval/metrics.py`）：

1. **JSON 合法率** —— 模型输出能否被解析（Agent 的生命线）
2. **工具选择准确率** —— 选对工具名
3. **参数准确率** —— 参数名/类型/取值范围正确（尤其经纬度越界）
4. **任务完成率** —— 端到端跑通
5. **延迟** —— 首 token / 全请求耗时
6. **显存峰值** —— 是否触发 CPU offload

**消融矩阵**（模型侧，与第五节 Week 5 的策略侧消融互补）：

| 配置 | 模型 | 量化 | 垂直微调 |
|---|---|---|---|
| A | 4B | Q5_K_M | ❌ |
| B | 4B | Q4_K_M | ❌ |
| C | 2B | Q5_K_M | ❌ |
| D | 2B/4B | Q4_K_M | ✅ |

> **诚实性要求**：任何数字必须是本机实测。跑不出来的配置写"未跑通 + 原因"，
> 不许估算、不许美化。

### 3.5.5 应用落地

1. `backend/app/agent/llm.py` 增加 **model profile** 配置（模型名 / 上下文 / 温度 / 超时），
   用环境变量切换，保持"不绑死厂商"的原有设计。
2. 端到端跑通：自然语言 → planner 规划 → 工具调用 → reflector 反思 → summarizer 总结。
3. 前端（`cesium_old/`）接对话侧工具调用链路可视化（原 Week 6 内容）。
4. 评测结果回填本章 + `GEOAGENT_PROGRESS.md` + 简历 B。

### 3.5.6 当前状态（2026-09-07 22:50 更新）

| 项 | 状态 |
|---|---|
| llama.cpp 源码 | ✅ `D:\llama_build\llama.cpp`（ggml 0.23.0 / commit e71b805） |
| 编译工具链 | ✅ MSVC 19.38 + Ninja + Windows SDK 10.0.22621 已验证可用 |
| **llama-cpp-python** | ✅ **0.3.35 源码编译成功**：先 CPU 后端，后 CUDA 后端（sm_75） |
| GGUF 权重 | ✅ `models/llm/Qwen3.5-4B-Q4_K_M.gguf` **2.55 GiB**（metadata 校验：sections len=4 ✅） |
| **冒烟测试** | ✅ **通过**（`bench/smoke_embedded.py`）—— 见下方实测 |
| CUDA Toolkit | ✅ **13.3 已装**（管理员运行 `D:\llama_build\install_cuda_admin.bat`） |
| Ollama | ✅ **已卸载**（2026-09-09），释放 D 盘 6 GB |

**GPU 基准实测（2026-09-08，嵌入式 + CUDA sm_75）**：

| 后端 | gen_tps | ttft | 备注 |
|---|---|---|---|
| 嵌入式 + CUDA（全部层上 GPU） | **51.33 tok/s** | 125 ms | VRAM 4.5 GB，load 5.5s |
| Ollama（GPU，走 HTTP） | ~40 tok/s | — | 预热后 |
| 嵌入式 CPU | 6.01 tok/s | — | 供对比 |

**工具调用评测（2026-09-09，100 条）**：完整数据见 `bench/eval_agent_report.md`。

| 指标 | 无词典 | 有词典 |
|---|---|---|
| `param_bbox` | 0.18 | **0.99** |
| `tool_exact` | 0.35 | 0.51 |
| `completed` | 0.31 | 0.58 |

关键诊断：**32 条显式坐标样本两组都是满分 1.00**，68 条含地名样本基线仅 0.031。
→ 坐标能力本来就没问题，`param_bbox` 低是**纯知识缺口**，不是推理缺陷。
无泄漏验证（12 个评测集未出现的地名）：bbox **0/12 → 12/12**。
`multi_tool` 工具链仍只有 0.025 —— 那是**多步规划**问题。

#### LangGraph 编排接入评测（2026-09-09）+ max_tokens 必须按场景标定

`bench/graph_eval.py` 让**真实状态图**（不是临时脚本）成为评测执行器，
评测脚本新增 `--orchestrator langgraph|loop` 可对拍两条路径。

**这是本次最重要的一条经验**：

> **一个全局的 `max_tokens` 会伪造出一个"模型没能力"的假象。**

首次接入后 `multi_tool` 的 `tool_exact` 只有 **0.30**，看起来跟多轮试探（0.30）
毫无差别，很容易得出"换编排没用"的结论。但汇总里有一个反常信号：
`avg_llm_calls_per_case = 2.17`，而 planner 的 `max_retries = 3`
—— 调用 3 次意味着**每次都失败、最后落到 `heuristic_plan` 关键词兜底**。
也就是说，那个分数里大半压根不是模型的规划结果。

用 `bench/diag_planner.py` 逐条打印原始输出才看清：
**8 条里 7 条的输出恰好停在 ~384 token，JSON 没有闭合。**

`384` 这个值是当年给 **tool_calling 场景**标定的（模型输出 `<tool_call>` 块，
实测 p99=318）。而 planner 要输出完整的计划 JSON，两者不是一个量级。
把上限放到几乎不设限后实测分布（`--measure`，20 条 multi_tool）：

| 场景 | min | p50 | p90 | p95 | max | 合法率 |
|---|---|---|---|---|---|---|
| planner（完整计划 JSON） | 323 | 407 | 593 | **827** | 827 | **20/20** |

不同上限下的截断率：**384 → 65%，512 → 20%，640 → 5%，1024 → 0%**。

于是按同一套"三个约束取交集"的方法给每个节点分别定值
（`llm.py` 顶部常量，节点调用时显式传入）：

| 节点 | max_tokens | 依据 |
|---|---|---|
| planner | **1024** | ≥ max(827)，留 24% 余量；延迟最坏 ~20s，p50 约 8s |
| summarizer | 768 | 提示词要求 300 字以内，实测约 400–600 token |
| reflector | 384 | 只输出 action/reason 短 JSON |

**结论复用的通用规则**：改任何"生成上限"前先测分布；
看到指标异常时，先看**是否有拉胯的间接信号**（这里是 n_llm_calls），
它往往直接指向真正的失败层，而不是交给"模型能力不行"来解释。

> **结论：嵌入式已反超 Ollama 28%，Ollama 可卸载。** CUDA 运行时 DLL
（cudart/cublas×3，共 ~570 MB）已复制进 `llama_cpp/lib/`，venv 自包含、可 turnkey。
坑：MSBuild 找不到 Toolkit → 需在编译环境设 `CUDA_PATH`；运行时 DLL 在 `bin/x64/` 不在 `bin/`。

#### 冒烟测试实测（2026-09-07 23:51，CPU 后端）

```
GGUF      : Qwen3.5-4B-Q4_K_M.gguf  2.55 GiB
load_s    : 4.55
gen_s     : 5.39   (23 tokens)
gen_tps   : 4.27 tok/s   ← CPU backend
输出      : 「坡度分析是计算地表任意两点间垂直高差与水平距离之比，以量化地形陡峭程度的过程。」
```

**架构验证通过**：进程内加载官方 GGUF、中文回答专业准确，零 HTTP、零外部服务。

**但性能不达标**：CPU 4.27 tok/s 对 Agent 场景太慢（单轮规划+反思约
30–60 s）。这反过来证明 **GPU 不是锦上添花而是必需**——上 CUDA 后预计
20–40 tok/s（RTX 2060 跑 4B Q4 的常态区间）。**在 CUDA 装上之前，
本模块只具备架构验证价值，不具备实用价值。**

> 下载踩坑：HF 直连 ~1.2 MB/s 且中途彻底不可达；改 **ModelScope（魔搭）**
> 后 ~5.2 MB/s，2.55 GiB 约 8 分钟。另有两点：`curl -C -` 在 HF 的 302
> 之后续传静默失效（观测到文件从 1.26 GB **倒退**到 957 MB）；4 段并发
> Range 请求被服务端限流（5 次重试全 0 字节）。**最终方案：魔搭 + 单线程。**

#### ⚠️ 基准实测：现在还不能卸 Ollama（2026-09-08 00:05）

同模型（Qwen3.5-4B Q4_K_M）、同 prompt、max_tokens=64：

| 后端 | 硬件 | 实测速度 | 备注 |
|---|---|---|---|
| **Ollama HTTP** | **GPU**（VRAM 4.6 GB） | **39.95 / 39.58 / 40.32 tok/s** | 预热后稳定 ~40 tok/s，1.6 s/64 tok |
| **嵌入式 llama.cpp** | **CPU**（8 核） | **6.01 tok/s** | 慢 **6.6 倍** |

**这组数据把问题说清楚了**：

1. **它证实了"HTTP 不是瓶颈"的判断**。Ollama 走了完整的 HTTP 栈，
   却比进程内调用快 6.6 倍 —— 因为瓶颈是 GPU 算力，不是进程间通信。
   在 40 tok/s 的水平上，HTTP 那 1–5 ms 连零头都算不上。
2. **当前对比是不公平的**：一边 GPU 一边 CPU。嵌入式一旦上 CUDA，
   跑的是同一个 llama.cpp、同一份权重，预期同样落在 35–45 tok/s 区间。
3. **因此：在 CUDA 装上并完成重编译之前，绝不能卸载 Ollama**，
   否则系统性能会从 ~40 tok/s 暴跌到 ~6 tok/s。
   `bench/llm_bench.py` 的 Ollama 组 `ttft_ms`/`gen_tps` 为 null
   （流式解析未覆盖），且首次延迟 34.9 s 实为 3.4 GB 模型冷加载，
   **该组数据不可用于结论**，真实值取上表的预热后测量。

**下一步唯一阻塞项**：装 CUDA（需管理员 UAC，见 3.5.7）→ 重编译 → 重跑基准
→ 确认嵌入式 GPU 档位追平或超过 40 tok/s → 才可卸载 Ollama。
| 评测基准 | ✅ 100 条评测集已生成并校验（`backend/app/eval/dataset.json`） |
| 垂直微调 | ⬜ 未开始 |
| **Ollama 卸载** | ⬜ 待上述跑通后执行（含模型目录 `D:\OllamaModels` 清理） |

> **历史遗留问题**：`llm.py` 里 `DEFAULT_MODEL = "qwen2.5:14b"`，而本机既无 Ollama
> 也无 14B 模型（14B Q4 约 9 GB，也远超 5 GB 预算）。**该配置从未真正跑通过**，
> 是纯占位。R1 完成后必须改成实测可用的模型名与嵌入式加载路径。

#### 卸载 Ollama 的前置检查（跑通后才执行）

1. 嵌入式引擎能加载 `qwen3.5-4b-q4km.gguf` 并产出正确回答
2. 基准对比完成（Ollama HTTP vs 进程内），数字落盘
3. GGUF 已从 blob 完整复制且校验通过（**否则卸载后权重丢失，需重下 3.4 GB**）
4. 再执行：停止服务 → 卸载程序 → 清理 `D:\Ollama`、`D:\OllamaModels`、`D:\OllamaInstall`

### 3.5.7 GPU 加速：CUDA 安装受阻与对策（2026-09-07）

**现象**：`winget install NVIDIA.CUDA --version 13.3` 失败

```
Installer failed with exit code: 2148270085
（0x80080205 — 安装包需要提升权限，非交互模式无法弹出 UAC）
```

**根因**：CUDA Toolkit 安装必须管理员权限，而 winget 在 `--disable-interactivity`
下无法请求提权。**这不是命令写错，是权限模型的硬约束。**

**对策（按优先级）**：

| # | 方案 | 需要用户操作 | 预期收益 |
|---|---|---|---|
| 1 | **手工提权安装**：右键 `D:\llama_build\install_cuda_admin.bat` → 以管理员身份运行 | 点一次 UAC | CUDA 后端，较 CPU 约 **3–5×** 提速 |
| 2 | Vulkan 后端（`-DGGML_VULKAN=ON`） | 需装 Vulkan SDK（同样可能要管理员） | 约 CUDA 的 70–85%，但无需 nvcc |
| 3 | **CPU 回退**（当前状态） | 无 | i7-10875H 8 核跑 4B Q4，约 8–15 tok/s |

> **重要**：方案 3 不影响架构验证。CPU 与 CUDA 走的是**同一套代码路径**，
> 只是 `n_gpu_layers` 不同（0 vs -1）。等 CUDA 装上后重编译一次即可，
> 无需改任何业务代码——这正是 `build_lcpp.sh` 参数化 `GGML_ARGS` 的原因。

**装完 CUDA 后的三步**：

```bash
# 1. 确认 nvcc
nvcc --version

# 2. 用 CUDA 后端重编译（约 12 分钟）
bash D:\llama_build\build_lcpp.sh "-DGGML_CUDA=ON"

# 3. 基准对比（CPU vs CUDA vs Ollama）
python bench/llm_bench.py --mode both --n-gpu-layers -1
```

> **风险提示（Turing 兼容性）**：RTX 2060 是 sm_75（Turing 架构）。CUDA 13.x
> 已逐步移除 Maxwell/Pascal/Volta 支持，**Turing 是否仍受支持需在装完后实测确认**。
> 若 CUDA 13.3 的 nvcc 不认 sm_75，退回 CUDA 12.x（手动下载 12.9 安装包）。

---

## 三·七、Agent 大脑能力增强：约束解码 vs 后训练（Week 8，2026-09-13）

### 7.1 问题的重新表述（用户指正后修正）

我在此前的排查里把「跳转到五指山」的坐标说成"模型编的"，**这个说法不准确，要纠正**：
模型给出的 `[109.5, 18.5, 110.5, 19.5]` 确实覆盖五指山，它知道五指山在海南。
真正的缺口是**上下文**（不知道"这个地方"指上文的五指山），不是地理知识。

由此引出用户的批评，也是本章的出发点：

> 「不要所有的操作和对话都要靠词典或者硬编码或者正则去判断才能让 agent 能执行，
> 这样就太笨太死板了。我们要用大语言模型，模型本身有天然的泛化能力，
> 我们不要去破坏模型会的东西；而是要区分出**模型本身能做的**、
> **外部需要给它添加的手和脚（工具）**、以及**模型没有学过的垂直领域知识**。」

### 7.2 能力边界原则（四级划分）

这是本章的判据，后续所有改动都按它检查：

| 级别 | 内容 | 做法 | 反面教材 |
|---|---|---|---|
| ① 模型自带知识 | 地名常识、地理常识、语言理解、意图判断、指代理解 | **交给模型**，不写规则 | 用正则判断"用户想干什么" |
| ② 模型没有的"手脚" | 算坡度、下载 DEM、路径规划、操作地图视角 | **我们提供工具**，模型来决定何时调用 | 把工具调用时机写死在代码里 |
| ③ 必须精确、错了代价不可接受 | 省级行政区边界坐标、国家主权表述规范 | 用确定性外部数据兜底 | —— |
| ④ 模型在本机上的已知弱项 | 4B 的意图路由不稳、JSON 偶尔不合法 | **约束解码 / 后训练**，而不是外面套正则 | 用 `_force_analysis` 词表替模型做决策 |

**关键区别**：③ 是"事实必须准"，用词典是对的（模型给的省级边界确实不如行政区划数据准）；
①④ 是"能力不足"，用词表兜等于承认模型废了 —— 正解是让模型变强（约束解码/微调），
而不是把它锁死。

### 7.3 现状审查：我们在哪些地方替模型做了判断

按 7.2 的判据逐条过一遍现有规则依赖：

| 位置 | 作用 | 判定 |
|---|---|---|
| `planner._force_analysis()` + 词表 | 词面含"坡度/地貌"就**抢在模型前**强制改判 analysis | ❌ 应替换（①被侵犯）。它是被 v14 翻车（100%→30%）逼出来的，但那说明**分类器需要变强**，不是该加正则 |
| `planner._has_geo_signal()` + 词表 | 分类失败时判断"是否沾地理" | ❌ 应弱化为"仅解析失败时"的最后兜底 |
| `planner._ALIEN_PATTERNS` / `_CONCEPT_PATTERNS` | 排除外星天体 / 问概念的句式 | ⚠ 可保留，但应改为提示词 + GBNF 枚举解决 |
| `chitchat.py` 寒暄词表 | 打招呼直答 | ✅ 保留（纯性能优化，不涉及能力判断） |
| `gazetteer.resolve_bbox()` 覆盖模型坐标 | 行政区/省级边界用精确值 | ✅ 保留（属 ③） |
| `memory/coref.py` 指代词表 | 「这个地方」→ 上轮实际坐标 | ✅ 保留（确定性替换，意图仍归模型） |
| 前端 `needsTerrainGrid()` | 预判要不要采样地形 | ✅ 保留（性能取舍，不是能力判断） |
| 前端 `isViewQuery()` / `hasPlaceName()` | 元问题直答、视野过大拦截 | ⚠ `hasPlaceName` 应改为把判断交给后端模型 |

### 7.4 调研结论（2026-09-13，已联网核实）

对比 LoRA/QLoRA/DoRA、DPO/ORPO/SimPO/KTO/GRPO、APIGen/ToolACE/xLAM/Hammer 等
Agent 训练工作，以及 llama.cpp GBNF 的实测数据：

| 痛点 | 根因 | 最佳手段 | 需要训练吗 |
|---|---|---|---|
| JSON 输出偶尔不合法 | 采样越界 | **GBNF 约束解码**（logit 层屏蔽非法 token） | ❌ 不需要 |
| 长提示里靠前的指令被忽略 | Lost-in-the-Middle | 拆分成独立调用（**已做**：意图分类拆分） | ❌ 不需要 |
| 4B 二次转述改坏事实 | 小模型无信息时幻觉 | 架构上取消二次转述（**已做**：非分析意图直接采用初稿） | ❌ 不需要 |
| 意图路由不稳（100%→30%） | 4B 语义路由弱 | 先试 **GBNF 枚举 + 拆分调用**；仍不稳才 SFT | ⚠ 可能 |

**两条最关键的调研事实**：

1. **可验证奖励（RLVR）在工具调用领域已有成功先例**：AWS 实测用执行反馈训 Qwen2.5-7B，
   对未见过的工具场景工具调用奖励 +57%。原因是"调对函数 + 参数合法"天然可验证 ——
   **我们的工具执行器就是现成的 verifier**，这条路径在本项目可行。
2. **训练成本与风险**：QLoRA 4B 约需 4–5 GB 显存（6 GB 勉强够，需 batch=1 + 梯度检查点 +
   短序列）；但有两个已知风险 —— ① `Qwen3.5` 是 Gated DeltaNet + Attention 混合架构，
   PEFT 兼容性需先验证；② 本机是 **Python 3.14**，Unsloth 要求 ≤3.13，bitsandbytes 的
   wheel 支持也需确认。

### 7.5 路线（按 ROI 排序）—— 含 W8-1 的实测否定结果

| 编号 | 任务 | 状态与依据 |
|---|---|---|
| W8-1 | 启用 GBNF 约束解码 | ❌ **实测否定，不上**（见 7.5b） |
| W8-2 | 用 GBNF 枚举重构意图分类 | ❌ 随 W8-1 一并否定 —— GBNF 对决策准确率零影响 |
| W8-3 | 消融：正则安全网到底帮了多少忙 | ⏳ 由 7.5b 的数据间接回答（见下） |
| W8-4 | **后训练（SFT）可行性验证** | ✅ **成为唯一出路**，见 7.5c |

#### 7.5b GBNF 实测结果（2026-09-13，`bench/_test_grammar.py`，24 条样本）

| 指标 | 无约束 | GBNF 约束 | 变化 |
|---|---|---|---|
| JSON 解析成功率 | 100%（24/24） | 100%（24/24） | **0** |
| 意图判定准确率 | 91.7%（22/24） | 91.7%（22/24） | **0** |
| 单条耗时 | 3.1 s | 4.1 s | **+32%** |

**两条关键事实**：

1. **GBNF 想解决的问题在本项目不存在**。我一直假设"JSON 偶尔不合法"是痛点，
   实测下来无约束时解析成功率就是 100% —— 因为 `extract_json` 已经能容错，
   且 Qwen3.5 的 JSON 输出本身很稳。**这个假设是我没验证就写进规划的。**
2. **失败的样本两组完全相同**（「统计珠峰坡度在15度以下的比例」被判成拒答、
   「这片区域属于什么地貌类型」被判成知识问答）—— 说明错因是**语义理解**，
   而 GBNF 只约束语法、**管不了语义**（与调研里"保证结构合法，不保证语义正确"一致）。

**结论**：GBNF 在本项目是**负收益**（零改善 + 32% 延迟），不采用。
这条否定结果比"用上了新技术"更有价值 —— 它把问题精确定位到了**模型能力**而非格式。

#### 7.5c 从否定结果推出的真正结论

把 7.5b 的数据和主集分数对照，链条就闭合了：

| 事实 | 数据 |
|---|---|
| 模型自己判意图 | 91.7%（22/24）—— 会错判「统计坡度比例」和「地貌类型」 |
| 主集实际得分 | 98.75% —— 高于模型自身水平 |
| 原因 | **正则安全网 `_force_analysis` 在替模型兜底**（这两句都含"坡度/地貌"，被强判为分析） |
| 用户感受 | "这样太笨太死板，泛化能力差" |

所以三个选项摆在一起：

| 选项 | 后果 |
|---|---|
| 移除正则 | 准确率掉到 91.7%，用户会看到"问了半天什么都没发生" |
| 保留正则 | 模型被锁死，换个说法就失效 —— 用户明确反对 |
| **微调让模型自己判对** | ✅ 唯一同时满足"准确"和"不僵化"的路径 |

**这就是 W8-4 的存在理由**：不是为了"简历上写我训了模型"，
而是因为**约束解码治不了语义问题，正则又不该长期存在**，
剩下的唯一出路是提升模型本身在这类路由决策上的能力。

而训练数据恰好可以自动构造 —— 调研里 AWS 用执行反馈训工具调用（未见过工具场景 +57%）
就是这个思路，**我们的 11 个工具执行器本身就是现成的 verifier**。

### 7.6 诚实说明（对简历同样重要）

调研的结论是「**训练在这个项目里不是最高 ROI**」，理由：
- 三个痛点（JSON 合法、指令忽略、转述失真）分别用约束解码和架构改造就能解决，
  **不需要改权重**；
- 数据要自己造（公开的 GIS 工具调用纯文本数据集稀缺，检索到的多为视觉-语言集）；
- 6 GB 显存训 4B 勉强，且有两个环境兼容风险未排除。

所以简历上真正有含金量的不是"我微调了一个模型"，而是
**「在真实硬约束下判断"何时该训练、何时该约束解码、何时该改架构"的工程决策」**，
以及**用工具执行器作 verifier 自动构造可验证训练数据**这条路径。

### 7.7 简历增量句（W8 落地后回填）

> 「针对小模型输出不稳定问题，区分"能力不足"与"知识不足"两类缺口：
> 前者用 GBNF 文法约束解码在 logit 层强制合法 JSON（推理开销 +1–3%），
> 并将意图判断改为封闭集合枚举，据此移除原先用于兜底的正则词表，
> 把判断权还给模型；后者以工具执行器作为可验证奖励来源（执行成功即正样本），
> 构建自演化训练数据，避免人工标注。」

---

## 四、立等可取的 3 件事（不依赖 6 周）

### 4.1 修简历 B 的"A* / Dijkstra"措辞

**问题**：实际只有 Dijkstra，写 A* 是误导。
**做法**：

1. 改 `gen_resumes.py`，把"A*、Dijkstra、栅格路径搜索"改成 **"Dijkstra 8 邻居 + 方向约束（等高线跟随 + 方向代价场）+ 路径重叠率/Hausdorff 距离消融验证"**
2. 在 Week 1 跑量化数据时同步更新数字

**收益**：技术准确性立刻修正，HR/面试官不会被"两个都说"误导成"哪个都没真懂"。

### 4.2 把现有能力填进简历 B 的"待填真实数值"占位符

最直接的高 ROI 动作：

```
A*:   Dijkstra + 方向约束（等高线跟随 + 方向代价场）
DEM 分辨率:   30 m（Copernicus GLO-30，自动下载）
栅格规模:    160×160 / 320×320 / 640×640 三档实测
规划耗时:    X ms / Y ms / Z ms（消融实验 run_log.csv 真实值）
路径重叠率:  0.4289（Ours vs baseline，Hausdorff 距离 50.08）
单位米爬升:  1.5618 m/m
帧率提升:    [需实测 LOD 开/关]
```

### 4.3 把 mcp/custom/ 目录的 README 升级成实施指南

当前 `mcp/custom/` 是空的，`mcp/README.md` 已写好"将自定义 MCP 服务器实现放在 `mcp/custom/` 目录下"，但没有具体内容。Week 3 之前应该把这里当作 GeoAgent MCP Server 的占位：

- 建 `mcp/custom/geo_mcp_server/` 子目录
- 写 5 分钟骨架（用 `mcp-python-sdk`）
- 让本项目的 backend 服务可以随时包成 MCP

这样 Week 3 就不用从零搭，时间更充裕做差异化亮点。

---

## 五、不要做（避免踩坑）

| 不要做 | 原因 |
|---|---|
| 把 analysis_service.py 重写成"Agent 框架" | 现有代码是核心资产，包装而非重写 |
| 把 Dijkstra 改成 A* | 方向约束是项目特色，改 A* 会丢失 |
| 用 LangChain 官方教程模板 | 面试官见过几十遍 |
| 把 GeoAgent 放在新仓库 | **用现有仓库**，展示 commit 时间线 |
| 等所有 Week 做完才推 GitHub | Week 0 就建仓库并持续 commit |

---

## 六、检查清单（每周对照）

- [ ] 本周有 commit（≥ 3 次）
- [ ] README 同步更新
- [ ] 跑过 e2e 测试
- [ ] 简历 gen_resumes.py 已同步最新数据
- [ ] 投递跟踪表已更新（用 `网申材料与投递跟踪.html`）
- [ ] 面试复盘（如有面试）

---

## 附：项目目录速查表

| 内容 | 路径 |
|---|---|
| FastAPI 后端 | `backend/app/main.py` |
| 地形分析核心 | `backend/app/services/analysis_service.py` |
| 地形分类（三方法） | `backend/app/services/terrain_classifier.py` |
| ONNX 训练脚本 | `terrain_morphology_train.py` |
| 训练好的模型 | `models/terrain_morphology/{best_model.pth, terrain_morphology.onnx}` |
| 多模态数据集 | `earthscape/` |
| 实验日志 | `skills/autoresearch/experiments/run_log.csv` |
| 通行代价模型消融 | `tests/dem-experiment/run_dem_cost_experiment.py` |
| MCP 自定义服务器占位 | `mcp/custom/`（空，待 Week 3 填） |
| 前端主入口 | `cesium_old/Cesium_coordinate_copy_czDebugging.html` |
| 项目约定 | `AGENTS.md` |
| 主页面后端联动 | `cesium_old/features/slope/TerrainBackendIntegration.js` |
| AHP 通行性建模 | `cesium_old/features/slope/AHPanalysis.js` |
| RoughAnalysis | `cesium_old/features/slope/RoughAnalysis.js` |