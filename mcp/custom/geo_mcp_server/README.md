# GeoMCP —— 地理空间分析 MCP Server

把本项目的 GIS 分析能力以 [MCP](https://modelcontextprotocol.io) 标准协议对外暴露。
接上之后，Claude Desktop / Cursor / Cline 等任意支持 MCP 的客户端都能直接调用本地的
DEM 分析、地形因子计算、路径规划与地貌分类，**不需要本项目自己的前端**。

```
客户端（Claude Desktop / Cursor）
   │  MCP over stdio
   ▼
geo_mcp_server/server.py        FastMCP 入口（12 个工具 + 2 个资源 + 1 个提示词）
   │
   ▼
geo_mcp_server/tools.py         适配层：schema 反推签名、结果渲染、截断
   │
   ▼
backend/app/tools/              11 个分析工具（Week 1）
   │
   ▼
backend/app/services/           既有 GIS 算法（未重写，原样复用）
```

---

## 5 分钟接入

### Claude Desktop

把 `config/claude_desktop.json` 里的 `mcpServers` 一段合并到
`%APPDATA%\Claude\claude_desktop_config.json`，然后**完全退出并重启** Claude Desktop
（关窗口不算，要在托盘图标里退出）。

### Cursor

把 `config/cursor.json` 复制到 `<项目根>/.cursor/mcp.json`（项目级）或
`~/.cursor/mcp.json`（全局级）。

### 验证

在客户端里问一句：

> 分析下经度 103.5–103.7、纬度 30.2–30.4 范围内的坡度，把结果导出成 GeoJSON

能看到坡度统计和产物文件路径，就说明接通了。

---

## 三个必须注意的点

这三个都是「配完了看起来没问题、一调用就崩」的坑，按踩坑概率排序：

### 1. 必须用 backend 的虚拟环境

工具依赖 `numpy` / `rasterio` / `onnxruntime` 等重型包，用系统 Python 启动会在
调用时报 `ModuleNotFoundError`。配置文件里的 `command` 必须指向：

```
<项目根>/backend/.venv/Scripts/python.exe
```

### 2. 必须用脚本绝对路径启动，不能用 `-m`

项目根目录下有一个 `mcp/` 目录（本服务就放在它下面），与官方 SDK 包同名。
从项目根执行 `python -m mcp.custom.geo_mcp_server.server` 时，Python 会把它当成
顶层包 `mcp`，遮蔽掉真正的 SDK，报错是含糊的
`No module named 'mcp.server'`。

直接指定脚本路径启动时，`sys.path[0]` 是本文件所在目录，不会有这个问题。
`server.py` 里也加了主动检测，命中时会给出可操作的提示。

### 3. `starlette` 版本不能动

`mcp` 对 `starlette` 不设上界，直接 `pip install mcp` 会把它升到 1.x，
而 `starlette` 1.x 移除了 `Router(on_startup=...)`，导致
`fastapi 0.116.1` 能导入、但 `FastAPI()` 一实例化就抛 `TypeError` ——
属于「pip 装完没报错、服务起不来」的静默破坏。

当前锁定的组合是 `mcp<2` + `starlette==0.47.3` + `sse-starlette==2.3.6`，
详见 `backend/requirements.txt` 里的注释。**升级或重装依赖后务必复查：**

```bash
python -c "from fastapi import FastAPI; FastAPI()"
```

---

## 可用工具

### 细粒度工具（11 个）

| 工具 | 用途 | 必填 |
|---|---|---|
| `get_dem_metadata` | 读取 DEM 的分辨率、范围、CRS、波段信息 | `dem_path` |
| `download_srtm` | 按 bbox 下载真实 SRTM 30m 数据 | `bbox` |
| `compute_slope` | 坡度（度） | `bbox` |
| `compute_aspect` | 坡向（度，正北为 0，顺时针） | `bbox` |
| `compute_curvature` | 曲率（1/m） | `bbox` |
| `compute_cost_surface` | 通行成本表面 | `bbox` |
| `plan_route` | 基于成本表面的最优路径 | `bbox` `start_point` `end_point` |
| `classify_terrain_rules` | 规则法地貌分类（最快） | `bbox` |
| `classify_geomorphons` | Geomorphons 经典地貌分类 | `bbox` |
| `classify_terrain_onnx` | ONNX 深度学习分类（分辨率 ≤ 128） | `bbox` |
| `zonal_statistics` | 分级面积统计，回答「多少地方能修路」 | `bbox` |

所有工具的 `bbox` 均为 `[minLon, minLat, maxLon, maxLat]`，WGS84 经纬度。
完整参数定义见 `config/` 同级的资源 `geo://tools`。

### 组合工具（1 个）

`geo_agent_query` —— 一个问题走完 Week 2 的「计划 → 执行 → 反思」全流程：
自动拆解任务、调用所需工具、用 9 条领域规则校验结果、失败自动修正重试。

默认不接 LLM（`GEOAGENT_LLM_ENABLED=0`），此时走确定性路径：关键词启发式规划 +
规则校验 + 模板总结，全程离线、秒级返回、不需要 API key。设置
`GEOAGENT_LLM_ENABLED=1` 并配置 `GEOAGENT_LLM_BASE_URL` / `GEOAGENT_LLM_API_KEY` /
`GEOAGENT_LLM_MODEL` 后可接 OpenAI 兼容接口（默认指向本机 Ollama）。

默认关闭不是偷懒：MCP 客户端本身就是一个强模型，让它自己编排 11 个细粒度工具
通常比让本地小模型代劳效果更好。`geo_agent_query` 的价值在于
「不想让客户端多轮往返」或「客户端模型较弱」的场景。

### 资源与提示词

| 名称 | 内容 |
|---|---|
| `geo://tools` | 11 个工具的完整 JSON Schema |
| `geo://capabilities` | 能力、数据来源、已知局限 |
| `geo_site_selection` | 选址/选线分析的标准流程提示词 |

---

## 数据来源与局限

这一节不是免责声明，是使用前提。

**DEM 数据源**：优先真实 SRTM 30m（`download_srtm`，需联网）。
未提供 `dem_path` 时自动降级为**合成地形**（高斯平滑随机场），
此时工具结果会带 `warnings` 字段标明，且渲染给模型的文本里有「⚠️ 告警」一行。
**合成地形的结论不能用于任何真实决策。**

**已知局限**（同时写在 `geo://capabilities` 里，客户端可以自己读到）：

- `classify_terrain_onnx` 是逐像元滑窗（每像元一次 64×64 patch 推理），
  实测 128×128 约 25 秒、192×192 约 55 秒，256×256 约 100 秒且占用约 1 GB 内存，
  因此分辨率超过 128 会被直接拒绝并给出替代方案
- `plan_route` 基于坡度成本表面，不含道路、水体、土地利用等现实约束
- 坡度/坡向按 Horn 方法在投影平面计算，高纬度地区存在畸变

---

## 排障

| 现象 | 原因 | 处理 |
|---|---|---|
| 客户端显示 server 启动失败 | `command` 指向了系统 Python | 改用 `backend/.venv` 的 python |
| `No module named 'mcp.server'` | 用 `-m` 方式启动，项目根 `mcp/` 遮蔽了 SDK | 改用脚本绝对路径 |
| `FastAPI() TypeError: on_startup` | `starlette` 被升到 1.x | 装回 `starlette==0.47.3`，见上文第 3 点 |
| 工具能连上但一调用就报模块缺失 | 同上第一条 | 同上 |
| 没看到日志 | 日志走 stderr，Claude Desktop 在 `~/Library/Logs/Claude/` | 设 `GEO_MCP_LOG_LEVEL=DEBUG` |
| 结果里说「合成地形」 | 未下载真实 DEM | 先调 `download_srtm`，或传 `dem_path` |

---

## 自测

```bash
# 用 backend 虚拟环境
python mcp/custom/geo_mcp_server/tests/test_mcp_server.py
```

22 个测试，不需要真实 MCP 客户端，直接在进程内驱动 FastMCP 接口。
其中 `test_no_schema_drift_between_mcp_and_registry` 守住 schema 单一来源：
后端工具函数签名与 MCP 暴露的参数必须逐一对齐。

> 这个测试真的抓到过 bug —— `zonal_statistics` 的 `breaks` 参数漏写在 schema 里，
> 导致大模型永远无法传自定义分级，只能通过漂移检测发现。

---

## 设计取舍

**为什么不直接把工具函数交给 FastMCP？**
因为参数定义已经在 `backend/app/tools/schemas.py` 里了。再写一遍类型注解，
必然出现「后端改了参数、MCP 侧忘了改」的漂移。这里从 schema 反推 Python 签名
（`build_signature`），保证单一来源。

**为什么工具返回文本而不是结构化 dict？**
MCP 协议本身支持结构化输出，但工具层的 dict 是给 Agent 的规则校验用的
（含 `error_type`、`retryable`、`warnings` 等控制字段），直接透传会让客户端模型
看到一堆它用不上的噪声。这里渲染成「产物路径 → 关键统计 → 告警 → 完整 JSON」
的层次，并对超长结果截断（默认 12000 字符）——栅格类工具很容易产出上千行 JSON，
不截断会直接撑爆客户端上下文。

**为什么失败也要返回详细文本？**
工具层承诺「绝不抛异常」，失败时返回带 `error_type` 的结构化结果。
渲染成「错误类型 + 原因 + 是否可重试 + 修正建议」后，客户端模型能据此自我修正，
而不是看到一句 `Internal error` 就没辙。
