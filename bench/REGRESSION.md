# Agent 评测回归报告

> 由 `bench/run_regression.py` 自动生成，**请勿手工编辑** —— 重跑即覆盖。
> 生成时间：2026-10-16 14:31:36

- 基线：`v19`（100 条）
- 候选：`v21_planner`（100 条）
- 可比样本：100 条

## 一、分项指标

| 类别 | 指标 | 基线 | 候选 | 变化 |
|---|---|---|---|---|
| 合计 | `completed` | 99.00% | 53.00% | -46.00pp |
| 合计 | `tool_exact` | 98.75% | 47.50% | -51.25pp |
| 合计 | `tool_set_f1` | 99.58% | 69.83% | -29.75pp |
| 合计 | `tool_order` | 99.38% | 69.27% | -30.10pp |
| 合计 | `param_bbox` | 100.00% | 90.91% | -9.09pp |
| 合计 | `refusal_correct` | 100.00% | 96.00% | -4.00pp |
| 合计 | `parsed` | 100.00% | 100.00% | 持平 |
| single_tool | `tool_exact` | 100.00% | 47.50% | -52.50pp |
| single_tool | `completed` | 100.00% | 45.00% | -55.00pp |
| single_tool | `refusal_correct` | 100.00% | 100.00% | 持平 |
| multi_tool | `tool_exact` | 97.50% | 47.50% | -50.00pp |
| multi_tool | `completed` | 97.50% | 47.50% | -50.00pp |
| multi_tool | `refusal_correct` | 100.00% | 100.00% | 持平 |
| out_of_scope | `completed` | 100.00% | 80.00% | -20.00pp |
| out_of_scope | `refusal_correct` | 100.00% | 80.00% | -20.00pp |

## 二、退步样本（基线对 → 候选错）：45 条

| 用例 | 类别 | 问句 | 期望工具 | 基线输出 | 候选输出 |
|---|---|---|---|---|---|
| `multi_001` | multi_tool | 下载四姑娘山的真实高程数据并计算坡度 | `['download_srtm', 'compute_slope']` | `['download_srtm', 'compute_slope']` | `['compute_slope']` |
| `multi_002` | multi_tool | 我没有秦岭的 DEM 文件，先下数据再算坡度 | `['download_srtm', 'compute_slope']` | `['download_srtm', 'compute_slope']` | `['compute_slope']` |
| `multi_003` | multi_tool | 获取贡嘎山的 SRTM 数据然后算坡度 | `['download_srtm', 'compute_slope']` | `['download_srtm', 'compute_slope']` | `['compute_slope']` |
| `multi_004` | multi_tool | 横断山的坡度，用真实 DEM 数据算 | `['download_srtm', 'compute_slope']` | `['download_srtm', 'compute_slope']` | `['compute_slope']` |
| `multi_005` | multi_tool | 先下载三峡高程数据，再分析那里的坡度 | `['download_srtm', 'compute_slope']` | `['download_srtm', 'compute_slope']` | `['compute_slope']` |
| `multi_014` | multi_tool | 规划拉萨内的通行路径，尽量走缓坡 | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope', 'plan_route']` |
| `multi_015` | multi_tool | 珠峰从西边到东边怎么走最省力 | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope']` |
| `multi_016` | multi_tool | 在西安找一条适合车辆通行的路线 | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope']` |
| `multi_017` | multi_tool | 兰州内两点之间的最优越野路径 | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope']` |
| `multi_018` | multi_tool | 帮我规划昆明的穿越路线，考虑坡度代价 | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope', 'compute_cost_surface', 'plan_route']` | `['compute_slope', 'plan_route']` |
| `multi_021` | multi_tool | 下载四姑娘山的 DEM，算坡度，再做地貌分类 | `['download_srtm', 'compute_slope', 'classify_geomorphons']` | `['download_srtm', 'compute_slope', 'classify_geomorphons']` | `['compute_slope', 'classify_geomorphons']` |
| `multi_022` | multi_tool | 秦岭没数据，先下高程再用地貌分类 | `['download_srtm', 'classify_geomorphons']` | `['download_srtm', 'classify_geomorphons']` | `['classify_geomorphons']` |
| `multi_023` | multi_tool | 获取贡嘎山真实地形数据并分类地貌类型 | `['download_srtm', 'classify_geomorphons']` | `['download_srtm', 'classify_geomorphons']` | `['classify_geomorphons']` |
| `multi_024` | multi_tool | 横断山的地貌分析，用真实 DEM 数据 | `['download_srtm', 'classify_geomorphons']` | `['download_srtm', 'classify_geomorphons']` | `['classify_geomorphons']` |
| `multi_027` | multi_tool | 峨眉山没有 DEM，先下数据再规划路径 | `['download_srtm', 'compute_slope', 'compute_cost_surface', 'plan_route']` | `['download_srtm', 'compute_slope', 'compute_cost_surface', 'plan_route']` | `['plan_route']` |
| `multi_031` | multi_tool | 算雅安的坡度，然后用地貌规则分类 | `['compute_slope', 'classify_terrain_rules']` | `['compute_slope', 'classify_terrain_rules']` | `['compute_slope', 'classify_geomorphons']` |
| `multi_037` | multi_tool | 兰州没有 DEM，先下数据算坡度再统计通行比例 | `['download_srtm', 'compute_slope', 'zonal_statistics']` | `['download_srtm', 'compute_slope', 'zonal_statistics']` | `['compute_slope', 'zonal_statistics', 'plan_route']` |
| `multi_038` | multi_tool | 获取昆明真实地形，计算坡度并统计有多少能走 | `['download_srtm', 'compute_slope', 'zonal_statistics']` | `['download_srtm', 'compute_slope', 'zonal_statistics']` | `['compute_slope', 'zonal_statistics']` |
| `multi_039` | multi_tool | 锡林郭勒草原的坡度统计，需要真实 DEM 数据 | `['download_srtm', 'compute_slope', 'zonal_statistics']` | `['download_srtm', 'compute_slope', 'zonal_statistics']` | `['compute_slope', 'zonal_statistics']` |
| `multi_040` | multi_tool | 下载塔克拉玛干数据，算坡度并给出车辆可通行面积占比 | `['download_srtm', 'compute_slope', 'zonal_statistics']` | `['download_srtm', 'compute_slope', 'zonal_statistics']` | `['compute_slope', 'zonal_statistics', 'plan_route']` |
| `refuse_003` | out_of_scope | 分析一下火星表面的地形 | `[]` | `[]` | `['compute_slope']` |
| `refuse_011` | out_of_scope | 计算圆的面积公式是什么 | `[]` | `[]` | `['compute_slope', 'zonal_statistics']` |
| `refuse_016` | out_of_scope | 分析月球背面的地貌类型 | `[]` | `[]` | `['classify_geomorphons']` |
| `refuse_020` | out_of_scope | 金星表面的坡度是多少 | `[]` | `[]` | `['compute_slope', 'zonal_statistics']` |
| `single_002` | single_tool | 四姑娘山这一带的坡度是多少 | `['compute_slope']` | `['compute_slope']` | `['compute_slope', 'zonal_statistics']` |
| `single_016` | single_tool | 西安哪里是沟谷 | `['compute_curvature']` | `['compute_curvature']` | `['compute_slope', 'zonal_statistics']` |
| `single_018` | single_tool | 计算经度 102.4 到 102.9、纬度 24.8 到 25.3的通行代价 | `['compute_cost_surface']` | `['compute_cost_surface']` | `['plan_route']` |
| `single_019` | single_tool | 锡林郭勒草原哪里好走 | `['compute_cost_surface']` | `['compute_cost_surface']` | `['compute_slope', 'zonal_statistics']` |
| `single_020` | single_tool | 分析塔克拉玛干的通行难度 | `['compute_cost_surface']` | `['compute_cost_surface']` | `['plan_route']` |
| `single_021` | single_tool | 经度 103.5 到 104.5、纬度 30.2 到 31.0的越野通行性怎么样 | `['compute_cost_surface']` | `['compute_cost_surface']` | `['plan_route']` |
| `single_022` | single_tool | 生成四姑娘山的通行代价栅格 | `['compute_cost_surface']` | `['compute_cost_surface']` | `['plan_route']` |
| `single_023` | single_tool | 用规则法对秦岭做地貌分类 | `['classify_terrain_rules']` | `['classify_terrain_rules']` | `['classify_geomorphons']` |
| `single_024` | single_tool | 经度 101.6 到 102.0、纬度 29.4 到 29.8的地貌类型有哪些， | `['classify_terrain_rules']` | `['classify_terrain_rules']` | `['classify_geomorphons', 'zonal_statistics']` |
| `single_025` | single_tool | 对张家界用地形规则做地貌分类 | `['classify_terrain_rules']` | `['classify_terrain_rules']` | `['classify_geomorphons']` |
| `single_030` | single_tool | 用 ONNX 模型对经度 103.4 到 103.8、纬度 30.9 到 31. | `['classify_terrain_onnx']` | `['classify_terrain_onnx']` | `['classify_geomorphons']` |
| `single_031` | single_tool | 三峡用深度学习模型分类地貌 | `['classify_terrain_onnx']` | `['classify_terrain_onnx']` | `['classify_geomorphons']` |
| `single_032` | single_tool | 调用 CNN 模型对横断山做地貌分类 | `['classify_terrain_onnx']` | `['classify_terrain_onnx']` | `['classify_geomorphons']` |
| `single_033` | single_tool | 统计经度 100.1 到 100.3、纬度 27.0 到 27.2的坡度分级情况 | `['zonal_statistics']` | `['zonal_statistics']` | `['compute_slope', 'zonal_statistics']` |
| `single_034` | single_tool | 拉萨有多少面积可以通行 | `['zonal_statistics']` | `['zonal_statistics']` | `['zonal_statistics', 'plan_route']` |
| `single_035` | single_tool | 统计珠峰多少比例的坡度在15度以下 | `['zonal_statistics']` | `['zonal_statistics']` | `['compute_slope', 'zonal_statistics']` |
| `single_036` | single_tool | 经度 108.7 到 109.2、纬度 34.0 到 34.5的高程分布怎么统计 | `['zonal_statistics']` | `['zonal_statistics']` | `['compute_slope', 'zonal_statistics']` |
| `single_037` | single_tool | 对兰州的坡度做分区统计 | `['zonal_statistics']` | `['zonal_statistics']` | `['compute_slope', 'zonal_statistics']` |
| `single_038` | single_tool | 检查一下这个 DEM 文件能不能用：data/dem/gdem_kunming. | `['get_dem_metadata']` | `['get_dem_metadata']` | `['compute_slope']` |
| `single_039` | single_tool | 读取 DEM 元信息：data/dem/srtm_chengdu.tif | `['get_dem_metadata']` | `['get_dem_metadata']` | `['compute_slope']` |
| `single_040` | single_tool | 看看 data/dem/srtm_qinling.tif 这个 DEM 的坐标系 | `['get_dem_metadata']` | `['get_dem_metadata']` | `['compute_slope']` |

## 三、修好样本（基线错 → 候选对）：0 条

（无）

---

*口径：所有指标经 `app.eval.metrics.aggregate()`，`tool_exact` 只在有工具期望的样本上计算（越界拒答题看 `refusal_correct`）。*

## 四、结果文件出处

- `v19` / multi_tool：`bench/eval_results/v19_multi_tool.json`
- `v19` / out_of_scope：`bench/eval_results/v19_out_of_scope.json`
- `v19` / single_tool：`bench/eval_results/v19_single_tool.json`
- `v21_planner` / multi_tool：`bench/eval_results/v21_planner_multi_tool.json`
- `v21_planner` / out_of_scope：`bench/eval_results/v21_planner_out_of_scope.json`
- `v21_planner` / single_tool：`bench/eval_results/v21_planner_single_tool.json`
