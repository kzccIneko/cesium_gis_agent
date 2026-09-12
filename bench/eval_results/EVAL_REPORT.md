# GeoAgent 工具调用评测报告（LangGraph 编排）

_生成时间：2026-09-10 12:20:41_

- 模型：Qwen3.5-4B Q4_K_M，进程内 llama.cpp + CUDA（RTX 2060 6GB，全层卸载）
- 编排：LangGraph `plan → execute → reflect → summarize`
- 样本：100 条

## 一、指标含义（先读懂再看数）

| 指标 | 含义 | 它低说明什么 |
|---|---|---|
| **解析成功率** | `parsed` | 模型输出能被解析成合法 JSON 的比例。这是漏斗第一层 —— 解析失败后面全部为 0。 |
| **工具链完全命中率（主指标）** | `tool_exact` | 预测的工具序列与标准答案**逐项且同序**完全一致的比例。最严格，也是真实业务里「整条链路能不能跑通」的代理指标。 |
| **工具集合 F1** | `tool_set_f1` | 把工具序列当集合，算查准率与查全率的调和平均。它**不看顺序**，所以高于 tool_exact 就说明「工具选对了但顺序错了或多了/少了」。 |
| **步骤顺序正确率** | `tool_order` | 工具都选对的前提下，执行顺序也对的比例。与 tool_set_f1 配合看：两者都高而 tool_exact 低 → 纯顺序问题；tool_set_f1 高而 tool_order 低 → 依赖倒置。 |
| **bbox 参数准确率** | `param_bbox` | 预测的经纬度范围与标准答案的误差在 0.01°（约 1.1 km）以内的比例。衡量的是**地理知识**，不是推理能力。 |
| **拒答正确率** | `refusal_correct` | 该拒答的拒了、不该拒答的没拒。越界类看它，工具类看「没有误拒」。 |
| **任务完成率** | `completed` | 智能体走完整条状态图并给出最终回答的比例（未卡在重试/异常）。 |

**怎么看一组数**：`tool_set_f1` 明显高于 `tool_exact` → 工具选对了但顺序或数量不对；`param_bbox` 低 → 缺地理知识而非不会推理；`parsed` < 1 → 先修解析/截断，别急着调提示词。

## 二、总体结果

| 类别 | 样本 | 工具链完全命中 | 集合 F1 | 顺序正确 | bbox 准确 | 拒答正确 | 延迟 |
|---|---|---|---|---|---|---|---|
| 单工具调用 | 40 | 75.0% | 90.0% | 97.5% | 100.0% | 100.0% | p50 8.1s / p90 10.7s / LLM 调用 1.00 次/条 |
| 多工具串联 | 40 | 85.0% | 93.1% | 92.5% | 100.0% | 100.0% | p50 14.1s / p90 17.7s / LLM 调用 1.12 次/条 |
| 越界拒答 | 20 | — | — | — | — | 100.0% | p50 4.7s / p90 5.5s / LLM 调用 1.00 次/条 |
| **合计** | **100** | **80.0%** | **91.5%** | **95.0%** | **100.0%** | **100.0%** | p50 9.8s / p90 15.6s / LLM 调用 1.05 次/条 |

> 注：`out_of_scope` 类本就没有标准工具链，`tool_exact` 记为 `—` 属正常，该类只看 `拒答正确率`。

## 三、失分明细

共 16 条 `tool_exact` 未命中：

| 样本 | 问题 | 期望 | 实际 | 多 | 缺 |
|---|---|---|---|---|---|
| single_018 | 计算经度 102.4 到 102.9、纬度 24.8 到 | compute_cost_surface | compute_slope→compute_cost_surface | compute_slope | — |
| single_019 | 锡林郭勒草原哪里好走 | compute_cost_surface | compute_slope→compute_cost_surface | compute_slope | — |
| single_020 | 分析塔克拉玛干的通行难度 | compute_cost_surface | compute_slope→compute_cost_surface | compute_slope | — |
| single_021 | 经度 103.5 到 104.5、纬度 30.2 到 3 | compute_cost_surface | compute_slope→compute_cost_surface | compute_slope | — |
| single_027 | 经度 117.0 到 117.3、纬度 36.2 到 3 | classify_geomorphons | classify_terrain_onnx | classify_terrain_onnx | classify_geomorphons |
| single_031 | 三峡用深度学习模型分类地貌 | classify_terrain_onnx | download_srtm→classify_terrain_onnx | download_srtm | — |
| single_033 | 统计经度 100.1 到 100.3、纬度 27.0 到 | zonal_statistics | compute_slope→zonal_statistics | compute_slope | — |
| single_034 | 拉萨有多少面积可以通行 | zonal_statistics | compute_slope→zonal_statistics | compute_slope | — |
| single_035 | 统计珠峰多少比例的坡度在15度以下 | zonal_statistics | compute_slope→zonal_statistics | compute_slope | — |
| single_037 | 对兰州的坡度做分区统计 | zonal_statistics | compute_slope→zonal_statistics | compute_slope | — |
| multi_003 | 获取贡嘎山的 SRTM 数据然后算坡度 | download_srtm→compute_slope | compute_slope | — | download_srtm |
| multi_005 | 先下载三峡高程数据，再分析那里的坡度 | download_srtm→compute_slope | compute_slope | — | download_srtm |
| multi_032 | 都江堰先算坡度再判断地貌类型 | compute_slope→classify_terrain_rules | compute_slope→classify_geomorphons | classify_geomorphons | classify_terrain_rules |
| multi_033 | 分析成都周边坡度并做地貌分类 | compute_slope→classify_terrain_rules | compute_slope→classify_geomorphons | classify_geomorphons | classify_terrain_rules |
| multi_034 | 拉萨的坡度算出来后分类地形 | compute_slope→classify_terrain_rules | compute_slope→classify_geomorphons | classify_geomorphons | classify_terrain_rules |
| multi_035 | 计算珠峰坡度，再做地形形态分类 | compute_slope→classify_terrain_rules | download_srtm→compute_slope→classify_geomorphons | download_srtm, classify_geomorphons | classify_terrain_rules |
