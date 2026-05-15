## 项目名称
> Cesium地理信息可视化系统_调试版


## 新增功能
***
2025/10/28 
增加非结构化地图路径规划功能，路径通行能力代价基于论文给的坡度或转向映射出的代价值和权重值计算
***
2025/11/5
新增原始映射方法的反向搜索计算代价值作为正向搜索的启发函数代价值
***
2025/11/10
新增水域与可通行区域划定
***
2025/11/21 
新增基于速度、坡度、转向因素计算等效时间作为寻路代价的方法（基于运动学公式）（v01）
新增全路径陡峭度和陡峭度变化分析功能
问题: 
1.没设置牵引力，牵引力能更好反映通行能力？而不是设定初始速度。固定好牵引力为最大牵引力。
2.牵引力、坡度、转向、路程结合算速度，速度放在全局根据运动学公式累积计算（比如坡度大的地方即使牵引力不足，速度够也能过，下坡不限速）
***            
2025/12/22
（SlopeAspect copy debug.js）
新增基于牵引力的等效时间代价计算方式
新增A*寻路时网格搜索方式，变为可选择
新增移植的山脊线山谷线提取功能
新增AHP层次分析法的整个步骤（原计用于分析各要素对通行代价的影响，绘制通行代价图，暂时用不上）
（PathPlanning_RRT.js）
新增基础RRT寻路算法
（CreatePolygonOnGround.js）
优化绘制（坡度坡向）分析区域的逻辑，添加提示。能正确应对重复点击时，前事件和绘制实体不删除的重复性问题
（RoughAnalysis.js）
新增高程变化率分析功能
问题:
通过讨论分析，重新规划了路径规划的流程，首先应合理量化各要素（地形地貌）对代价的具体影响，设置代价函数，绘制出通行代价图，所有过程都应**以各要素为主体**，而不是以车为主体分析，每个栅格代价值都应固定且明确，不应该与行车过程有关。
***
2026/01/13
调整文件结构，将功能文件（地形分析、路径规划、等高线等模块）单独放在./features目录下，将师兄师姐测试文件放在./test目录下
将杂糅在坡度坡向分析类SlopeAspect文件中的部分其他功能分离到单独的js文件中
***
2026/01/16
新增图元管理功能（图层显示顺序功能尚未做完，待完善）
***
2026/03/11
新增左侧工具栏用于管理图层和窗口组件工具，新增土地类型kmz矢量文件叠加到地形分析网格中，进行通行能力分析和通行能力图叠加绘制
***
2026/04/23
【后端地形分析联动与工程化增强】
1. 新增后端分析工作流接入能力：支持前端发起 terrain/path 分析请求并自动加载结果图层。
2. 新增分析结果数值提示统一能力：后端结果在鼠标悬浮时可显示对应数值（坡度/坡向/曲率/代价）。
3. 新增分析要素下拉执行逻辑：前端可按目标要素执行并控制单要素展示，避免多要素混合干扰。
4. 新增大图幅自动分块策略（terrain）与分级策略（path），降低单次请求与单文件体量风险。
5. 新增请求超时估算、失败重试、GeoJSON 读取重试、cache-bust/no-store 等稳健性机制。
6. 优化后端导出写文件流程为原子写入，降低前端读取到半写文件导致 JSON 解析失败的概率。

【清理、缓存与误操作防护】
1. 新增后端输出缓存清理接口，并在前端清除、初始化和页面离开时联动触发，减少临时目录膨胀。
2. 清除全部时同步清理后端分析图层，修复侧栏图层残留问题。
3. 新增页面离开前确认提示，降低刷新/关闭导致结果误丢失风险。

【大图幅渲染稳定性修复】
1. 增加分块邻域外扩计算能力（overlap），用于缓解分块边界处分析割裂。
2. 渲染阶段改为按“分块核心范围”裁剪，重叠圈仅参与计算不重复绘制，降低边界重叠伪影。
3. 移除前端采样降格和实例截断绘制逻辑，避免出现蜂窝状/条带状伪影，确保结果完整性优先。
4. 保留按批次构建图元机制以控制单批渲染压力，但不再以牺牲结果正确性为代价。

【当前说明】
1. 本次更新重点从“功能可用”推进到“高负载稳定可用”，主要围绕大图幅分析、结果一致性、缓存治理和交互防误操作展开。
2. 若后续在极端超大图幅下仍遇到性能瓶颈，将继续通过分层可视化与按需加载策略优化，而不采用改变结果语义的采样方案。

***
2026/05/13
【最新版项目对比总结（本轮累计改动）】
1. 后端地形代价分析新增“方向性建模”参数：请求体支持起点/终点，经 DEM 多方向坡度、曲率与线系强度组合计算方向最小代价，并在代价图层属性中写入方向相关字段用于前端数值提示。
2. 前端后端分析流程支持“起终点选取驱动代价分析区域”：选择代价分析后可先在地图选两点，按起终点方向约束分析；点位越界会提示重选；并支持在区域基础上做栅格外扩。
3. 新增“终止分析”能力：页面增加“终止分析”按钮，前端通过 AbortController 中断请求链路，停止动态 LOD 后续加载，并联动清理本次结果缓存与绘制状态。
4. 动态 LOD 与图层管理联动增强：L0 与后续 LOD 细化结果统一纳入分析图层组管理，透明度滑块可作用于 DataSource/Primitive 混合对象，避免仅底层可调透明度的问题。
5. 图层顺序控制落地：左侧图层项新增“置顶/上移/下移”，底层调用 Cesium `raiseToTop/raise/lower`，并同步 DOM 顺序，实现可视叠加顺序可控。
6. 后端缓存与输出工程化继续加强：地形瓦片缓存命中返回、统计落盘、输出与瓦片缓存清理接口、原子写文件流程完善，降低大图幅重复计算与半写入读取异常风险。
7. 后端与前后端接口关键代码完成中文注释增强：补充重要变量、核心函数和关键计算步骤注释，并将主要英文注释替换/补充为中文，便于后续维护与汇报讲解。
8. 新增通行能力研究与实验资产（`literature/test`）：包含方向性代价实验脚本、操作流程、统计与图表输出、GeoJSON 导出、Cesium 对比页面（`cesium_experiment_compare.html`）及两批实验结果产物。
9. 实验脚本新增运行完成提示：`run_dem_cost_experiment.py` 结束时输出结果目录、关键文件路径与统计行数，便于直接定位产出。
10. 新增 Playwright 自动化测试基础设施：`playwright.config.js`、`tests/e2e`、`package.json` 测试脚本（`test:e2e` 等）与 `http-server` 本地服务配置，可用于后续关键交互回归测试。
11. 工程配置补充：`.gitignore` 增加 Playwright 报告与缓存忽略项，减少测试产物污染版本库。

【本轮新增/更新重点文件（摘要）】
1. 前端：`Cesium_coordinate_copy_czDebugging.html`、`features/slope/TerrainBackendIntegration.js`、`features/SidebarManager.js`、`features/eventBindInit.js`、`css/index.css`
2. 后端：`backend/app/main.py`、`backend/app/schemas.py`、`backend/app/services/analysis_service.py`、`backend/app/services/export_service.py`
3. 实验与展示：`literature/DEM方向性通行能力建模与实验方案.md`、`literature/test/run_dem_cost_experiment.py`、`literature/test/README_实验操作流程.md`、`literature/test/cesium_experiment_compare.html`
4. 测试与配置：`playwright.config.js`、`tests/e2e/`、`package.json`、`.gitignore`

***
2026/05/15
【VSCode工作区累计更改合并提交】
1. 合并提交本轮 VSCode 工作区累计改动（含后端、前端、实验资产、测试配置与文档图示），统一对齐当前开发状态。
2. 后端接口与分析服务继续完善：地形分析请求/响应结构、代价要素计算、导出流程与分阶段方案脚本同步更新。
3. 前端后端联动模块 `TerrainBackendIntegration.js` 持续增强：请求编排、动态 LOD、终止分析、缓存清理、两点选取与结果渲染流程进一步补齐。
4. 侧栏图层管理能力继续增强：图层条目交互、透明度调节、顺序控制、不同 Cesium 对象类型的统一管理逻辑完善。
5. 主页面与样式更新：分析面板控件、按钮行为和相关 UI 样式同步迭代，支撑后端分析与交互流程。
6. 新增与完善实验资产：`literature/test` 下实验脚本、操作流程、Cesium 对比页面、两批实验输出结果，以及研究与汇报支撑材料。
7. 新增自动化测试基础设施：Playwright 配置、e2e smoke 用例、前端测试脚本与依赖锁文件更新。
8. 补充项目展示/研究路线文件：新增项目框架图、功能流程图、后端技术路线与方向性代价算法研究文档（`literature` 目录）。

【本次合并提交包含的代表性目录/文件】
1. 后端：`backend/app/main.py`、`backend/app/schemas.py`、`backend/app/services/analysis_service.py`、`backend/app/services/export_service.py`
2. 前端：`Cesium_coordinate_copy_czDebugging.html`、`features/slope/TerrainBackendIntegration.js`、`features/SidebarManager.js`、`features/eventBindInit.js`、`css/index.css`
3. 实验：`cesium_old/literature/test/`、`cesium_old/literature/*.md`、`literature/*.mmd`、`literature/*.md`
4. 测试与配置：`cesium_old/playwright.config.js`、`cesium_old/tests/e2e/`、`cesium_old/package.json`、`cesium_old/package-lock.json`、`cesium_old/.gitignore`
