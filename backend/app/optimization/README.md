# 地形分类模型优化（垂直场景）

> **定位说明（重要）**：本层是**计划外支线**，对应 `IMPROVEMENT_PLAN.md` **二·五节
> 「ONNX 模型真实评测结果」** 的工程化延伸，**不是 Week 4，也不替代 Week 4（RAG 知识层）**。
> 它优化的是**工具层内部被 Agent 调用的 ONNX 地貌分类模型**，**不是 Agent 的大脑 LLM**
> （后者见 `backend/app/agent/llm.py`，默认 qwen2.5:14b / 本地 Ollama）。
> 计划与进度对齐见仓库根 `GEOAGENT_PROGRESS.md`。

针对本项目的 ONNX 地貌分类模型（8 类 / 3.9 MB / 输入 `[batch,1,64,64]`）
在**滑窗推理**场景下的优化与量化。

## 结论先行

| 手段 | 体积 | 速度 | 领域验证 | 可否上线 |
|---|---|---|---|---|
| 图结构修复 | 3.79 MB | — | 输出逐位一致 | ✅ 必须做，否则无法量化 |
| 静态量化 int8（真实地形校准） | **0.96 MB（3.96x）** | **1.55x** | **PASS** | ✅ **推荐** |
| stride=2 隔点采样 | — | 4.0x | **FAIL** | ❌ 不可用 |
| 向量化 + 分块 patch 提取 | — | 1.06x | 输出逐像素一致 | ✅ 主要为修内存 |
| 线程数调优 | — | 4.5x（1→8 线程） | 无影响 | ✅ 已默认开启 |

**stride=2 拿不到 4 倍的加速**，原因见下文验证结果 —— 这是本层最重要的产出：
一个好看的加速比背后，是 6 个地貌类别的 IoU 不达标和 6.5%~7.9% 的通行成本偏差。
（实测数字随合成地形 seed 有小幅波动，结论稳定：一致率约 0.79，cost 偏差超 5% 阈值。）

### 一条被否掉的路：全卷积化改造

模型是**全卷积**的（conv1–4 全 stride=1 pad=1，4 个 2×2 MaxPool，
64×64 → 4×4 后展平 256·4·4=4096 接 Gemm），理论上 Gemm 可转成 1×1 卷积，
把 `N²` 次 patch 推理换成整图一次前向，FLOPs 能降两个数量级。

**但没有采用**，理由是输出步长对不上：64×64 patch 只产出 1 个预测，
整图推理的输出步长是 16 像素，而滑窗要的是逐像元（步长 1）。
要还原步长 1 得做 shift-and-stitch（16×16=256 次带偏移前向），
而 MaxPool 的偶数对齐会让拼接结果不再严格等价于滑窗。
按本仓库的验证标准，stride=2（仅 2 倍降采样）已经被判 FAIL，
16 倍降采样必然被否决 —— 做一个永远通不过验证的优化没有意义。

结论：**在"逐像元稠密分类"这个语义下，该架构的 FLOPs 是不可约的**。
能拿到的只有量化（1.55x）、线程（4.5x）与内存上界，已在表中列出。

## 为什么先算法后算子

原实现 256×256 栅格要跑 65536 次 patch 推理。直觉是「模型太大，量化它」，
但拆开看完全不是这么回事：

| 环节 | 原实现 | 实测占比 |
|---|---|---|
| patch 提取（Python 双层循环） | 逐像元切片 + mean + std | ~6% |
| **ONNX 推理** | 65536 次 64×64 前向 | **~94%** |
| 内存 | 预分配 `N²·64²·4` 字节 | 256² 约 **1.07 GB** |

所以向量化 patch 提取只带来 1.06x —— 它真正的价值是把峰值内存从
O(N²) 降到 O(块高·N)（`patches.py` 按 64 MB 预算分块），
而不是提速。真正的开销在推理。

内存分块实测（tracemalloc 峰值，预算 64 MB / 96² 输入约 199 MB）：

| 输入 | 朴素实现 | 分块后 | 说明 |
|---|---|---|---|
| 64² | 67 MB | 134 MB | 小输入分块无收益，直接一次性算完 |
| 96² | 151 MB | 199 MB | 已低于朴素 |
| 128² | 268 MB | 202 MB | **内存不再随面积增长** |

峰值约为预算的 3 倍（fancy-index 物化 + 归一化临时数组），故预算取 64 MB
把峰值压在 200 MB 量级。`test_memory_is_bounded_by_chunk_budget` 守着这条性质。

**模型体积也骗人**：3.9 MB 看着很小，但结构是
`conv1(64) → conv2(128) → conv3(256) → conv4(256)` 加 4 次 MaxPool，
conv2 / conv3 各约 75M MACs，**单个 patch 约 191M MACs（382 MFLOPs）**。
128×128 的栅格总计算量 3.13 TMACs。这是"小模型、大计算量"的典型。

线程数是性价比最高的一项：1→8 线程 4.5x，已设为默认（ORT auto 等价于 8）。

## 领域验证：四道门槛

通用量化只看 top-1 accuracy，在地理场景不够。本层用四条更严格的口径
（`validate.py`，阈值可调，任一不过即判 FAIL）：

| 门槛 | 默认阈值 | 为什么 |
|---|---|---|
| 整体像素一致率 | ≥ 0.90 | 基础 |
| **稀有类 IoU**（面积占比 <2%） | ≥ 0.60 | 平地/缓坡占七八成，悬崖/洼地/山顶常不到 1%。**整体一致率 98% 的量化模型，可能已经把悬崖全抹成陡坡** —— 而悬崖恰恰是地质灾害评估的关键类 |
| 常见类 IoU | ≥ 0.75 | — |
| **斑块边界密度比** | ≤ 1.30 | 量化噪声的典型表现不是整体偏移，而是在大片同类区域里打出椒盐噪点。噪点只占几个百分点，一致率看不出来，但边界密度会暴涨 |
| cost surface 平均相对偏差 | ≤ 0.05 | 分类结果会转成通行成本再喂给路径规划，要确认下游不受影响 |

### 实测结果

参考基准 = fp32 / stride=1 / 128×128 合成地形。

**int8 静态量化（真实地形 patch 校准）— PASS**

```
一致率 0.9846 | 分布TVD 0.0058 | 边界密度比 0.9997 | cost 偏差 0.0056
不达标类别：无
```

边界密度比 0.9997 说明**没有产生椒盐噪声**，cost 偏差 0.56% 远低于阈值。
可以放心上线。

**stride=2 — FAIL**

```
一致率 0.8074 | 分布TVD 0.0037 | 边界密度比 0.7945 | cost 偏差 0.0649
不达标类别：平地、山顶、山脊、缓坡、山谷、洼地
```

有意思的是**类别分布几乎没变**（TVD 只有 0.0037），
但逐像素一致率只有 80.7%，cost 偏差 6.5% 超阈值。
分布对不代表图对 —— 这正是只看分布指标会漏掉的问题。
边界密度反而下降到 0.79，是最近邻回填把边界抹平了。

## 图结构修复（量化的前置条件）

导出模型里有这么一段（`x.view(x.size(0), -1)` 的标准产物）::

    Shape(dem_patch)[0:1] → val_0
    Concat(val_0, [-1])   → val_34      # [batch, -1]
    Reshape(pool4, val_34) → view       # [batch, 4096]

动态 batch 叠上 `-1`，ONNX 的 shape inference 推不出形状，
**量化直接失败**，报 `Inferred shape and existing shape differ in dimension 0: (4096) vs (8)`。
推理时 ORT 能容忍，所以这个缺陷一直藏着，直到要做量化才炸出来。

`graph.py::fix_dynamic_flatten` 把它换成静态常量 `[-1, 4096]`
（4096 从 `fc.weight` 的第二维反推，不硬编码），删掉 Shape/Concat，
并用同输入跑两个模型验证**输出逐位一致**（max_abs_diff = 0.0）。

> 顺带记录：ORT 的**动态**量化在本模型上不可用。它会先调
> `replace_gemm_with_matmul()`，把 Gemm 拆成 MatMul+Add 时权重维度处理有
> 问题，随后 shape inference 必然失败。静态量化不走这条路，因此选它。

## 用法

```bash
# 检查执行后端、模型、图结构（并生成修好的图）
python backend/scripts/optimize_terrain_onnx.py check

# 性能基准
python backend/scripts/optimize_terrain_onnx.py bench --sizes 64,128 --with-quant

# 量化（默认用合成地形校准；有真实 DEM 时务必传 --real-dem）
python backend/scripts/optimize_terrain_onnx.py quantize --real-dem path/to/dem.npy

# 领域验证 —— 决定能不能上线
python backend/scripts/optimize_terrain_onnx.py validate

# 一条龙并导出报告
python backend/scripts/optimize_terrain_onnx.py all --json report.json
```

校准数据用**真实 DEM 切出来的 patch**（`quantize.py::DemPatchCalibrationReader`），
不是随机数：地形 patch 经 z-score 后数值分布集中且有强空间自相关，
用随机张量标定会给出错误的激活范围，把量化误差放大到肉眼可见。

## 未来方向：全卷积化（本轮未做，附分析）

滑窗的理论冗余很大 —— 输出步长是 16，却每个像元都算一遍 64×64，
理想情况下「全卷积 + shift-and-stitch」能到 **约 16x 且数学等价**。

但本模型做不到等价，原因是**逐 patch z-score 归一化**：
归一化统计量绑定在 patch 上，而不是绑定在位置上的局部窗口统计量，
因此整个网络对原始 DEM **不是平移等变**的，卷积无法复用。

要让这条路走通，需要把归一化改成「每个位置取其 64×64 邻域统计量」
（平移等变），但这改变了模型的输入分布 —— 每个 patch 内部的归一化
不再一致，必须重新验证精度，大概率需要微调。
考虑到现有模型验证准确率只有 76%，这个改造的收益风险比不高，
本轮只记录分析不改模型。

## 文件

```
backend/app/optimization/
  session.py     会话构建 + 执行后端探测（为什么没用上 GPU 要能查出来）
  patches.py     向量化 + 分块 patch 提取
  classifier.py  OptimizedONNXClassifier，可 drop-in 替换原分类器
  graph.py       图结构修复（动态展平 → 静态 Reshape）
  quantize.py    静态量化 + 真实地形patch 校准
  validate.py    领域一致性验证（四道门槛）
  benchmark.py   延迟 / 吞吐 / 内存
backend/scripts/optimize_terrain_onnx.py   流水线 CLI
```

`OptimizedONNXClassifier.classify()` 与
`services.terrain_classifier.ONNXTerrainClassifier.classify()` 同签名，
有 `test_optimized_matches_legacy_exactly` 守着逐像素一致。
