# DEM方向性通行代价模型实验操作流程（完整）

## 一、实验目标

本实验用于完整验证“多要素DEM机理代价模型”的严谨性、创新性与优越性，验证内容包括：

1. 导数计算正确性（坡度/方向/二阶项）
2. 消融对比（B0/B1/B2/B3/Ours）
3. 多分辨率稳定性
4. 方向性（起终点互换）有效性

---

## 二、实验文件与目录

- 主脚本：`run_dem_cost_experiment.py`
- 运行结果：`test\output\YYYYMMDD_HHMMSS\`
  - `derivative_validation.csv`
  - `experiment_summary.csv`
  - `ablation_mean_metrics.csv`
  - `hypothesis_tests.json`
  - `EXPERIMENT_REPORT.md`
  - `sample_paths.png`（若本机有 matplotlib）
  - `ablation_mean_total_cost.png`（若本机有 matplotlib）

---

## 三、运行步骤（每一步的目的与意义）

## Step 1：进入实验目录并执行脚本

```powershell
cd F:\CZ\VS_Code_Programs\CesiumJS_Debug\cesium_old\literature\test
python .\run_dem_cost_experiment.py
```

**目的**：一键跑通全流程（数据生成、建模、求解、统计、出图、报告）。  
**意义**：保证实验可复现、可审计，不依赖手工步骤。

---

## Step 2：导数正确性验证（合成地形）

脚本会自动构建四类可控地形（平面、锥面、鞍面、脊谷起伏），并输出：
- `grad_rmse`
- `laplacian_rmse`
- `aspect_mae_deg`

**目的**：先验证微分算子准确，再讨论代价模型效果。  
**意义**：避免“模型看起来有效但导数本身错误”的伪结论。

---

## Step 3：消融实验（B0/B1/B2/B3/Ours）

模型定义：
- **B0**：仅方向坡度几何基底
- **B1**：B0 + 曲率惩罚
- **B2**：B0 + 脊谷线系惩罚
- **B3**：B0 + 曲率 + 脊谷
- **Ours**：B3 + 等高线密度 + 方向约束

输出指标（`experiment_summary.csv`）：
- `total_cost`
- `path_len_m`
- `cum_ascent`
- `ascent_per_meter`
- `mean_abs_kappa`
- `mean_flowline`
- `tortuosity`

**目的**：逐项验证“每个地形要素是否带来增益”。  
**意义**：证明模型不是黑箱堆叠，而是机理可解释的贡献叠加。

---

## Step 4：多分辨率稳定性实验

脚本自动用尺度因子 `[1,2,4]` 下采样 DEM 并重复求解，输出 `H3_multiscale_stability`：
- `ours_hausdorff_mean`
- `ours_hausdorff_std`

**目的**：检查模型在工程中常见分辨率变化下是否稳定。  
**意义**：若跨尺度路径形态差异过大，模型难以工程落地。

---

## Step 5：方向性实验（起终点互换）

脚本对 Ours 自动执行：
- 正向：`S -> T`
- 反向：`T -> S`

输出指标：
- `forward_mean_cost`
- `reverse_mean_cost`
- `path_overlap_forward_reverse_mean`

**目的**：验证代价场是否真正“方向相关（各向异性）”。  
**意义**：满足“两个点是起终点语义，不只是框选角点”的要求。

---

## Step 6：统计检验与结论

脚本自动给出：
- 配对符号检验（sign test）
- bootstrap 均值差 95% CI

结果写入：`hypothesis_tests.json` 与 `EXPERIMENT_REPORT.md`

**目的**：将“现象”升级为“统计显著结论”。  
**意义**：确保成果可用于论文或项目验收汇报。

---

## 四、重点对比分析了哪些指标

1. **模型优越性**（Ours vs B0/B1/B2/B3）
   - 总代价更低/更合理
   - 单位长度爬升更低
   - 路径曲折率更优（避免不必要绕行）

2. **机理一致性**
   - 导数误差（梯度/二阶项）是否可接受
   - 曲率与脊谷强度在路径上的统计响应是否符合地形直觉

3. **方向性有效性**
   - 起终点互换后路径重合度下降（说明方向约束生效）

4. **工程稳定性**
   - 多分辨率下路径Hausdorff距离与波动水平

---

## 五、可选参数

```powershell
python .\run_dem_cost_experiment.py --grid 160 --extent 80 --seed 20260510
python .\run_dem_cost_experiment.py --outdir F:\CZ\VS_Code_Programs\CesiumJS_Debug\cesium_old\literature\test\output\manual_run
```

---

## 六、判读建议（汇报时可直接使用）

1. 先展示 `derivative_validation.csv`，说明数值基础可靠。  
2. 再展示 `ablation_mean_metrics.csv` 和柱状图，说明综合模型优于基线。  
3. 展示 `hypothesis_tests.json` 里的显著性结果，给出“非偶然”证据。  
4. 最后展示 `sample_paths.png`，直观呈现路径形态差异与方向性效果。

---

## 七、在Cesium项目内可视化对比展示（新增）

本目录已提供页面：`cesium_experiment_compare.html`

### 7.1 打开方式

建议使用 VS Code Live Server 打开：

`F:\CZ\VS_Code_Programs\CesiumJS_Debug\cesium_old\literature\test\cesium_experiment_compare.html`

### 7.2 页面功能

1. 在 Cesium 球上叠加显示 B0/B1/B2/B3/Ours 的样例路径（LineString）
2. START/END 起终点标注
3. 模型路径可勾选开关（按模型显隐）
4. 面板展示：
   - `ablation_mean_metrics.csv` 汇总后的均值表
   - 方向性与稳定性关键统计（来自 `viewer_metrics.json`）

### 7.3 数据来源

每次运行脚本后，输出目录会包含：

- `sample_paths.geojson`（Cesium路径叠加核心数据）
- `viewer_metrics.json`（页面指标面板核心数据）

页面默认读取 `./output/20260510_175400`，可在页面输入框改成任意新输出目录。

