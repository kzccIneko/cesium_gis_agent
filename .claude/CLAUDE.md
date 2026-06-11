# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 用户偏好

- 每次对话开头输出今日日期，按 年/月/日 写
- commit message 写中文
- 思考过程用中文展示

## 常用命令

### 前端开发

```powershell
# 安装前端依赖
cd cesium_old && npm install

# 启动静态服务 (8080端口)
npm run serve        # npx http-server ./cesium_old -p 8080 -c-1 --cors

# VS Code Live Server 打开主页 (端口5501)
# 打开 cesium_old\Cesium_coordinate_copy_czDebugging.html
```

### 后端开发

```powershell
# 启动 FastAPI 后端 (8000端口, auto-reload)
powershell -ExecutionPolicy Bypass -File .\backend\run_backend.ps1
```

该脚本自动创建 `backend\.venv`、安装依赖、启动 uvicorn。

### 测试

```powershell
npm run test:e2e          # Playwright e2e (headless)
npm run test:e2e:ui       # Playwright UI 模式
npm run test:e2e:headed   # Playwright 有头浏览器
npm run test:report       # 查看 HTML 报告
```

### 研究实验

```powershell
# 跑一次 DEM 方向性代价模型实验
cd tests\dem-experiment
python .\run_dem_cost_experiment.py
python .\run_dem_cost_experiment.py --grid 160 --extent 80 --seed <种子>

# 初始化 autoresearch 环境
python skills\autoresearch\init_autoresearch.py
```

## 架构概览

### 整体架构

本仓库是一个 **Cesium 静态前端 + FastAPI 分析后端** 的 GIS 地形分析系统。

```
cesium_old/                        ← 静态前端 (Cesium + 原生 JS)
  ├── Cesium_coordinate_copy_czDebugging.html  ← 主页面入口
  ├── features/
  │   ├── earthOpera.js             ← viewer 初始化 + UI shell
  │   ├── SidebarManager.js         ← 侧栏图层/搜索管理
  │   ├── eventBindInit.js          ← 全局事件绑定 + 要素下拉逻辑
  │   ├── slope/                    ← 地形分析核心
  │   │   ├── SlopeAspect.js        ← 坡度/坡向/曲率前端计算 (旧版，仍被引用)
  │   │   ├── TerrainBackendIntegration.js  ← 后端联动主控 (请求编排/动态LOD/缓存/图层)
  │   │   ├── CreatePolygonOnGround.js      ← 分析区域绘制
  │   │   ├── RoughAnalysis.js              ← 高程变化率分析
  │   │   └── AHPanalysis.js                ← AHP 层次分析法
  │   └── router-tracker/           ← 路径规划模块
  │       ├── DrawHelper.js         ← 图元绘制辅助 (ChangeablePrimitive 模式)
  │       └── flycesium.js
  ├── libs/                         ← Cesium 库文件

backend/                           ← FastAPI 后端 (Python)
  └── app/
      ├── main.py                   ← API 入口 (路由 + CORS + 静态文件挂载)
      ├── schemas.py                ← Pydantic 请求/响应模型
      └── services/
          ├── analysis_service.py   ← 核心计算 (地形分析/路径规划/DEM元数据)
          └── export_service.py     ← 结果导出 (GeoJSON/CZML/KML 原子写入)

skills/autoresearch/               ← AI 代理自主研究配置 (Skill)
  ├── program.md                   ← 研究程序说明 (AI 阅读后自主迭代实验)
  ├── init_autoresearch.py         ← 一键初始化脚本
  └── experiments/run_log.csv      ← 实验追踪记录

tests/                             ← 测试用例
  ├── e2e/                         ← Playwright e2e 测试 (chromium)
  └── dem-experiment/              ← DEM 代价模型实验脚本与输出
literature/                        ← 项目研究文档 (算法推导/架构图/文献资料)
mcp/                               ← MCP 工具配置与自定义服务器
skills/                            ← Claude Code Skills (自定义斜杠命令)
```

### 前后端数据流

1. 用户在地图上绘制分析区域或选点 → `CreatePolygonOnGround.js` 捕获几何
2. `TerrainBackendIntegration.js` 组装请求 → `POST /api/v1/analyze/terrain` (或 `/path`)
3. 大图幅自动分块 (tiling + overlap) → 后端逐个计算
4. 后端返回 GeoJSON/CZML URL (`/outputs/...` 或 `/tile-cache/...`)
5. 前端按分块动态 LOD 加载结果到 Cesium，侧栏统一管理图层
6. 鼠标悬浮显示数值提示 (坡度/坡向/曲率/方向代价)

### 后端缓存体系

- 输出缓存: `%TEMP%/cesiumjs_debug_outputs/` — 通过 `/outputs/` 静态挂载
- 瓦片缓存: `backend/outputs/tiles/` — 通过 `/tile-cache/` 静态挂载
- 缓存清除接口: `POST /api/v1/cache/outputs/clear`, `POST /api/v1/cache/tiles/clear`
- 输出文件采用原子写入 (临时文件 + rename)

## 核心约定

- **脚本加载顺序至关重要。** 本应用不经过模块打包，多个文件依赖全局变量。修改 `Cesium_coordinate_copy_czDebugging.html` 时保持 `<script>` 标签顺序不变。
- **全局状态是设计意图。** 文件间通过 `window`/全局符号共享状态 (`viewer`, `SlopeAnalysis`, `_terrainBackend*`, `sidebarManager`)。不要引入模块隔离重构，除非同步更新所有依赖方。
- **前后端视觉/计算一致性。** `analysis_service.py` 和 `export_service.py` 中的公式、颜色分箱必须与前端 `SlopeAspect.js` 的行为匹配。修改指标或配色时两端同步。
- **缓存生命周期是 UX 的一部分。** 前端在初始化/pagehide 时触发后端缓存清除；新后端输出需遵循原子写入模式。
- **后端结果 URL 优先。** 前端加载结果图层时，优先使用后端返回的 artifact URL，而非前端本地计算。
- **当前主页面是 `Cesium_coordinate_copy_czDebugging.html`。** `test/` 和 `literature/test/` 下的 HTML 是实验/演示页面。
- **方向性代价分析需要起点/终点。** 缓存键包含 `start_point/end_point`，避免不同起终点的方向场复用错误。
