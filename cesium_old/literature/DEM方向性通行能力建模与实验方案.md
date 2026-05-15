# 基于 DEM 的方向性地形通行能力代价建模：机理推导、工程实现与实验方案

## Executive Summary

本文给出一套**不依赖车辆主体参数**、仅由 DEM 地形机理驱动的通行代价建模框架：以方向坡度（surface metric）、法曲率（surface bending）、等高线密度（vertical crossing frequency）、山脊-山谷线系强度（flow-organization intensity）和起终点方向约束（anisotropy）构造单元边权，并在栅格图上进行最小代价路径求解。[^1][^2][^3][^4]  
核心思想是：把“平面步长”映射为“地表实际行进长度”作为基底成本，再叠加由几何二阶项与地形组织结构诱发的无量纲阻抗因子；各因子尺度采用**数据内生鲁棒尺度**（median/MAD/IQR）消量纲，避免主观权重。[^5][^6]  
与常见单一坡度代价相比，该模型在理论上可同时表达“爬升难度、地形弯曲、脊谷组织与方向性约束”，并可通过多分辨率与消融实验验证其严谨性、稳定性与优越性。[^2][^4][^7]  
文末给出完整实验流程（合成地形真值、真实 DEM、多尺度鲁棒性、统计显著性检验、创新性验证）与可直接落地到你当前项目的实现映射。[^8][^9][^10]

---

## 1. 研究基础与文献脉络（对应你关心的地形要素）

### 1.1 多方向坡度与坡向

经典 3×3 局部差分可计算 \(\partial z/\partial x,\partial z/\partial y\)（Horn 方法谱系），并由
\[
\theta=\arctan\sqrt{z_x^2+z_y^2}
\]
得到坡度；坡向由 \(\mathrm{atan2}\) 给出。ArcGIS 与 RichDEM 文档均给出该类公式与实现背景。[^1][^2][^3]

### 1.2 曲率（profile / planform / curvature）

曲率来自二阶导数（或局部拟合曲面），用于表征地表弯曲。Zevenbergen & Thorne 体系区分 profile 与 planform 曲率，分别对应沿最大坡降方向与其垂向方向的弯曲效应。[^3][^4]

### 1.3 等高线与地形复杂度

等高线本质是 DEM 等值线；工程上可由 `gdal_contour` 从 DEM 直接构建，且支持固定间距/固定高程层。[^11]  
在微分意义上，单位路径长度穿越等高线频率与方向高程梯度成正比，可作为“起伏复杂度”客观指标。

### 1.4 山脊/山谷线与流向组织

D8/D∞ 流向模型可把局部高程关系映射为流向与坡降；D∞ 还给出连续角度并可分配到两邻元，适合表达脊谷组织。[^7][^8]  
利用正向/反向汇流累积可提取“谷线强（汇聚）/脊线强（发散）”结构强度，作为通行阻抗修正。

### 1.5 方向性与各向异性累积代价

GRASS `r.walk` 明确采用 anisotropic cumulative cost 思路，并支持起点/终点约束，这说明“方向依赖代价场 + 累积最小代价”是成熟路线。[^9]  
图搜索层面，最短路可由 Dijkstra 在带权图上求解，边权即本文构造的方向性代价。[^10]

---

## 2. 从地形机理到代价函数：完整推导

下述推导只依赖 DEM（高程场）与起终点，不引入车辆参数。

### 2.1 连续地表与方向导数

令地表 \(z(x,y)\)，局部梯度 \(\nabla z=(z_x,z_y)\)。  
对于单位方向向量 \(\mathbf{u}_\alpha=(\cos\alpha,\sin\alpha)\)，方向导数：
\[
g_\alpha = \nabla z\cdot \mathbf{u}_\alpha = z_x\cos\alpha+z_y\sin\alpha
\]

若在平面内迈出步长 \(\Delta s\)，地表弧长近似：
\[
\Delta \ell_\alpha=\Delta s\sqrt{1+g_\alpha^2}
\]
这是一阶微分几何直接结果，可视为**纯几何基底成本**（无主观权重）。[^1][^2]

### 2.2 法曲率惩罚（地表弯曲导致附加困难）

定义 Hessian
\[
H=\begin{bmatrix}z_{xx}&z_{xy}\\z_{xy}&z_{yy}\end{bmatrix}
\]
方向 \(\alpha\) 的二阶变化为
\[
\kappa_\alpha \propto \mathbf{u}_\alpha^\top H\mathbf{u}_\alpha
\]
（严格法曲率形式还包含 \(\nabla z\) 的归一化项；离散栅格上可用该主项近似）。  
构造无量纲弯曲惩罚：
\[
M_\kappa(\alpha)=1+\frac{|\kappa_\alpha|}{S_\kappa}
\]
其中 \(S_\kappa\) 用数据内生鲁棒尺度（如 median 或 MAD）确定，避免手调系数。[^3][^4]

### 2.3 等高线密度惩罚（起伏频繁穿越）

给定等高距 \(\Delta h\)，方向上单位长度穿越等高线频率近似
\[
\rho_\alpha \approx \frac{|g_\alpha|}{\Delta h}
\]
若 \(\Delta h\) 取 DEM 自适应尺度（如 \(S_h=\mathrm{MAD}(z)\) 或分位间距），得到：
\[
M_c(\alpha)=1+\rho_\alpha
\]
该项客观反映“局部起伏密集程度”，等价于“单位距离高程振荡密度”。

### 2.4 山脊-山谷线系强度惩罚

由 D8/D∞ 方向场构造汇流强度 \(A^+\)（顺地形）与逆向汇流强度 \(A^-\)（反向），定义
\[
I_{rv}=\log(1+\max(A^+,A^-))
\]
并归一化成
\[
M_{rv}=1+\frac{I_{rv}}{S_{rv}}
\]
其中 \(S_{rv}\) 取鲁棒尺度。该项让脊谷骨架附近成本体现为与地形组织一致的变化。[^7][^8]

### 2.5 起终点方向性（各向异性约束）

设当前栅格中心 \(\mathbf{x}\)，终点 \(\mathbf{t}\)，目标方向
\[
\mathbf{g}(\mathbf{x})=\frac{\mathbf{t}-\mathbf{x}}{\|\mathbf{t}-\mathbf{x}\|}
\]
候选方向 \(\mathbf{u}_\alpha\) 仅在
\[
\mathbf{u}_\alpha\cdot \mathbf{g}(\mathbf{x})>0
\]
时有效（朝向终点半平面）；否则不可行或施加大惩罚。  
该约束将“两个点不只是框选范围，而是起终点语义”严格写入代价场。

### 2.6 综合单步代价函数（最终形式）

对边 \(e=(i\to j,\alpha)\)：
\[
C_e=\Delta s_e\sqrt{1+g_\alpha^2}\cdot M_\kappa(\alpha)\cdot M_c(\alpha)\cdot M_{rv}\cdot M_{\text{dir}}(\alpha)
\]
其中
\[
M_{\text{dir}}(\alpha)=
\begin{cases}
1,& \mathbf{u}_\alpha\cdot\mathbf{g}(\mathbf{x})>0\\
\infty\ \text{或大常数},&\text{否则}
\end{cases}
\]

> 说明：这里没有主观加权和（无 \(\sum w_k f_k\)）；而是“几何基底 × 机理乘子”。每个乘子来源明确且量纲可解释，尺度参数采用数据内生鲁棒统计量。

### 2.7 栅格最优路径

在 8 邻域或 16 邻域有向图上，边权取 \(C_e\)，用 Dijkstra/A* 求最小累计代价路径。[^10]  
若只需要“通行能力场”而非单条路径，可输出每栅格最优方向 \(\alpha^\*\) 与最小单步代价 \(C^\*\)。

---

## 3. DEM 工程化可行性与关键技术细节

### 3.1 分辨率对定量/定性影响（必须显式评估）

1. **定量影响**：\(z_x,z_y,z_{xx},z_{xy},z_{yy}\) 都与栅格间距相关；分辨率变化会引起坡度/曲率统计分布漂移。[^1][^2]  
2. **定性影响**：高分辨率可揭示微地貌但放大噪声；低分辨率平滑地形细节。ArcGIS 也建议对高分辨率数据使用更大窗口或自适应窗口。[^1][^2]

### 3.2 方向离散误差

D8 速度快但角度量化粗；D∞ 提供连续角可减弱方向栅格化误差。建议：  
- 代价计算层可用 8 或 16 离散方向；  
- 脊谷组织层优先 D∞（或至少 D8+反向累积）。[^7][^8]

### 3.3 边界/NoData

坡度和坡向计算需足够有效邻元；边缘与 NoData 邻接区域要统一掩膜，否则会引入假梯度。[^1][^2]

### 3.4 去噪与尺度一致

可选高斯平滑（\(\sigma\) 与分辨率挂钩）降低高频噪声对二阶导数的放大；注意平滑会损失细节，需在实验中报告。[^12]

### 3.5 等高线工程输出

如果需要显式等高线层用于解释，可由 `gdal_contour -i` 固定间距生成；也可直接用梯度近似 contour density 以减少 I/O。[^11]

---

## 4. 严谨完整的实验流程（验证“严谨性 + 创新性 + 优越性”）

## 4.1 研究假设

- **H1**：加入曲率和脊谷组织后，代价场对地形结构的解释力显著优于仅坡度模型。  
- **H2**：方向性约束后，起终点对调会产生统计显著不同的方向代价场（符合各向异性）。  
- **H3**：在多分辨率下，鲁棒尺度归一化模型比固定权重模型更稳定。

## 4.2 数据与场景设计

1. **合成真值地形**（可解析导数）：平面、锥面、鞍面、正弦山脊谷。  
2. **真实 DEM**：至少 3 类（低山丘陵/高山峡谷/平原起伏），每类多区域。  
3. **多尺度重采样**：例如 2m、5m、10m、30m。

## 4.3 基线模型

| 基线 | 说明 |
|---|---|
| B0 | 仅几何坡度基底 \(\Delta s\sqrt{1+g_\alpha^2}\) |
| B1 | B0 + 曲率 |
| B2 | B0 + 脊谷组织 |
| B3 | B0 + 曲率 + 脊谷组织（无方向约束） |
| Ours | B3 + 等高线密度 + 起终点方向约束 |

## 4.4 评价指标

1. **解析一致性**（合成地形）：  
   - 梯度 RMSE、曲率 RMSE、方向误差 MAE。  
2. **路径物理一致性**（真实 DEM）：  
   - 单位长度累计爬升、累计曲率、脊谷穿越强度。  
3. **方向性有效性**：  
   - 正向/反向端点的路径重合率下降与代价分布差异（KS 检验）。  
4. **多尺度稳定性**：  
   - 不同分辨率路径的 Fréchet 距离、累计代价变异系数 CV。

## 4.5 统计检验

- 配对样本下：Wilcoxon signed-rank（非正态）或 paired t-test（近似正态）。  
- 多模型比较：Friedman + Nemenyi。  
- 置信区间：bootstrap 95% CI。

## 4.6 创新性验证（你最关心）

1. **机理完整性**：证明每个因子对应独立地形机制（坡度/弯曲/线系/方向）。  
2. **非主观性**：所有尺度来自数据鲁棒统计量，不使用人工经验权重。  
3. **工程可复现性**：给出固定流程、固定随机种子、固定重采样与掩膜规则。

## 4.7 可复现实验步骤（执行清单）

1. DEM 预处理（投影统一、NoData 统一、可选平滑）。  
2. 计算一阶/二阶导数、D∞或D8流向与双向累积。  
3. 构建各因子图与鲁棒尺度。  
4. 生成方向边权图（8/16 邻域）。  
5. 执行最短路并输出路径/代价场。  
6. 做消融、分辨率、端点互换实验。  
7. 统计检验并出图（箱线图、显著性表、案例可视化）。

---

## 5. 与你当前项目实现的映射与差距

你当前后端已具备较强基础：  
- 已在 terrain 接口中显式接收 `start_point/end_point`，并把其纳入缓存键，避免方向性缓存污染。[^5][^6]  
- 已实现 8 方向候选、朝向终点半平面约束、最优方向坡度输出。[^13]  
- 已有“曲率惩罚 + 脊谷强度惩罚 + 几何长度因子”的乘式结构。[^13]  

仍建议增强的点（面向论文/成果展示）：
1. 脊谷组织从 D8 升级到 D∞（降低方向量化误差）。[^8]  
2. 曲率从当前混合曲率扩展到 profile/planform 分解并分别报告。[^3][^4]  
3. 等高线密度项显式加入（或输出独立解释图层）。[^11]  
4. 方向离散从 8 邻域扩展至 16 邻域并做误差-耗时权衡实验。  

---

## 6. 结论（可直接用于方案陈述）

这套模型的“严谨性”来自：**每个代价因子都可追溯到 DEM 几何/水文机理与文献算法**；  
“创新性”来自：**在无车辆参数前提下，把多要素地形机制与起终点方向约束统一到一个可计算、可解释、可统计验证的方向性代价框架**；  
“优越性”可通过你要求的完整实验流程在合成真值 + 真实 DEM + 多尺度场景下定量证明。  

---

## Confidence Assessment

- **高置信**：坡度/坡向/曲率/D8-D∞/各向异性累积代价的基础方法、公式脉络与工程实现路径。[^1][^2][^3][^4][^7][^8][^9][^10]  
- **中高置信**：本文给出的“无主观权重乘式模型”是机理一致且可工程落地的合理综合方案；它是对现有文献组件的系统集成，而非单一文献直接给出的闭式公式。  
- **中置信**：创新性强弱最终依赖你选取的对照基线与实验数据覆盖度，建议严格执行第 4 节统计流程。

---

## Footnotes

[^1]: ArcGIS Pro, *How Slope works*（3×3 邻域、\(dz/dx, dz/dy\)、坡度公式、分辨率与窗口影响）: https://pro.arcgis.com/en/pro-app/latest/tool-reference/3d-analyst/how-slope-works.htm  
[^2]: ArcGIS Pro, *How Aspect works*（3×3 邻域、\(\mathrm{atan2}\) 规则、边界/NoData 条件、尺度建议）: https://pro.arcgis.com/en/pro-app/latest/tool-reference/spatial-analyst/how-aspect-works.htm  
[^3]: RichDEM 文档（Horn 1981 坡度/坡向；Zevenbergen & Thorne 曲率族）: https://richdem.readthedocs.io/en/latest/terrain_attributes.html  
[^4]: GRASS `r.slope.aspect`（输出 slope/aspect/pcurvature/tcurvature 与一二阶偏导）: https://grass.osgeo.org/grass-stable/manuals/r.slope.aspect.html  
[^5]: `F:\CZ\VS_Code_Programs\CesiumJS_Debug\backend\app\schemas.py:19-37`（terrain 请求结构含 `start_point/end_point`）  
[^6]: `F:\CZ\VS_Code_Programs\CesiumJS_Debug\backend\app\main.py:112-130,333-350`（缓存 payload 与 `analyze_terrain` 入参已纳入起终点）  
[^7]: TauDEM D8 文档（最陡下降方向、drop/distance、平坦区处理）: https://hydrology.usu.edu/taudem/taudem5/help53/D8FlowDirections.html  
[^8]: TauDEM D∞ 文档（三角面最陡下降、连续角度、按两邻元分配流）: https://hydrology.usu.edu/taudem/taudem5/help53/DInfinityFlowDirections.html  
[^9]: GRASS `r.walk` 文档（anisotropic cumulative cost，起止点约束）: https://grass.osgeo.org/grass-stable/manuals/r.walk.html  
[^10]: NetworkX `dijkstra_path`（带权图最短路径求解）: https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.weighted.dijkstra_path.html  
[^11]: GDAL `gdal_contour`（由 DEM 生成等高线/等值面，固定间距与固定层）: https://gdal.org/en/stable/programs/gdal_contour.html  
[^12]: SciPy `gaussian_filter`（可控 \(\sigma\) 的高斯平滑，边界模式说明）: https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.gaussian_filter.html  
[^13]: `F:\CZ\VS_Code_Programs\CesiumJS_Debug\backend\app\services\analysis_service.py:73-107,161-243,244-333`（当前实现：曲率与线系惩罚、8方向候选、终点半平面约束、最优方向输出）
