# RRT 路径规划算法使用说明

## 算法概述

RRT (Rapidly-exploring Random Tree) 是一种基于采样的路径规划算法，特别适合高维空间和复杂约束环境。本实现针对坡度代价网格进行了优化。

## 核心特性

1. **随机探索**：通过随机采样快速探索整个空间
2. **偏向目标**：可配置朝目标采样的概率以加速收敛
3. **碰撞检测**：自动检查路径沿途的坡度代价是否超限
4. **灵活配置**：支持调整最大迭代次数、步长、代价限制等参数

## 使用方法

### 1. 在 HTML 中引入脚本

```html
<!-- 在 Cesium 和 SlopeAspect 脚本之后引入 -->
<script src="./libs/slope/PathPlanning_RRT.js"></script>
```

### 2. 在 eventBindInit.js 中集成

```javascript
// 在 GetSlopePath() 调用后使用 RRT
document.querySelector('#GetSlopePath_RRT')?.addEventListener('click', () => {
    if (!window.SlopeAnalysis || !window.SlopeAnalysis.slopeCostGrid.length) {
        return alert('请先计算区域坡度！');
    }
    
    // 创建 RRT 规划器实例
    const rrt = new RRT_PathPlanner(window.SlopeAnalysis, {
        maxIterations: 5000,    // 最大迭代次数
        stepSize: 2,            // 步长（网格单位）
        goalThreshold: 1.5,     // 到达目标阈值
        maxSlopeCost: 10,       // 最大坡度代价
        biasToGoal: 0.1         // 10% 概率朝目标采样
    });
    
    // 设置起点终点（复用 GetSlopePath 的交互逻辑）
    let flag = 0;
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    
    handler.setInputAction(function (movement) {
        const ray = viewer.camera.getPickRay(movement.position);
        const cartesian = viewer.scene.globe.pick(ray, viewer.scene);
        
        if (!cartesian) return;
        
        if (flag === 0) {
            // 标记起点
            window.SlopeAnalysis.keepStartPoint = cartesian;
            const StartEntity = new Cesium.Entity({
                id: "rrt_path_起点",
                position: cartesian,
                point: {
                    pixelSize: 8,
                    color: Cesium.Color.GREEN,
                    disableDepthTest: Number.POSITIVE_INFINITY,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                },
            });
            viewer.entities.add(StartEntity);
            StartEntity.isPath = true;
            flag = 1;
            console.log('RRT: 已选择起点');
        } else if (flag === 1) {
            // 标记终点并执行寻路
            window.SlopeAnalysis.keepEndPoint = cartesian;
            const EndEntity = new Cesium.Entity({
                id: "rrt_path_终点",
                position: cartesian,
                point: {
                    pixelSize: 8,
                    color: Cesium.Color.GREEN,
                    disableDepthTest: Number.POSITIVE_INFINITY,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                },
            });
            viewer.entities.add(EndEntity);
            EndEntity.isPath = true;
            flag = -1;
            
            console.log('RRT: 已选择终点，开始寻路...');
            
            // 执行 RRT 寻路
            const path = rrt.findPath(
                window.SlopeAnalysis.keepStartPoint,
                window.SlopeAnalysis.keepEndPoint
            );
            
            if (path && path.length > 0) {
                // 将路径保存到 pathPoints 并绘制
                const pathIdx = window.SlopeAnalysis.pathLineNum || 0;
                window.SlopeAnalysis.pathPoints[pathIdx] = path;
                window.SlopeAnalysis.DrawPath();
                console.log('RRT: 路径绘制完成！');
            }
            
            handler.destroy();
        }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
});
```

### 3. 在 HTML 中添加按钮

```html
<!-- 在坡度分析面板中添加 RRT 按钮 -->
<div class="row">
    <input id="GetSlopePath" type="button" class="btn btn--primary" value="A*寻路" />
    <input id="GetSlopePath_RRT" type="button" class="btn btn--primary" value="RRT寻路" />
    <input id="ClearPath" type="button" class="btn btn--primary" value="清除路径" />
</div>
```

## 参数说明

### 构造函数参数 (config)

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| maxIterations | number | 5000 | 最大迭代次数，超过后放弃寻路 |
| stepSize | number | 2 | 每步扩展距离（网格单位），越大越快但路径越粗糙 |
| goalThreshold | number | 1.5 | 到达目标的阈值距离（网格单位） |
| maxSlopeCost | number | 10 | 最大允许坡度代价，超过视为障碍 |
| biasToGoal | number | 0.1 | 朝目标采样的概率（0-1），越大越快但可能陷入局部最优 |

## 算法流程

1. **初始化**
   - 验证 slopeCostGrid 是否已计算
   - 将起点终点坐标转换为网格索引

2. **构建树**
   - 从起点开始，迭代扩展随机探索树
   - 每次随机采样或朝目标采样
   - 找到树中最近节点并朝采样点扩展

3. **碰撞检测**
   - 检查扩展路径沿途网格的坡度代价
   - 超过 maxSlopeCost 的格子视为障碍

4. **路径回溯**
   - 当树节点到达目标附近时
   - 沿 parent 指针回溯到起点
   - 生成完整路径点数组

## 与 A* 算法对比

| 特性 | RRT | A* |
|------|-----|-----|
| 搜索方式 | 随机采样 | 启发式搜索 |
| 最优性 | 不保证 | 保证最优（启发函数可接受） |
| 速度 | 快速探索，但迭代次数不确定 | 稳定但可能慢 |
| 适用场景 | 复杂约束、高维空间 | 已知代价场、需要最优解 |
| 路径质量 | 可能弯曲 | 平滑且短 |

## 调试技巧

1. **打开控制台**：查看每次迭代的进度和找到路径的详细信息
2. **调整参数**：
   - 找不到路径：增加 maxIterations 或 maxSlopeCost
   - 路径太长：减小 stepSize 或增加 biasToGoal
   - 速度太慢：增加 stepSize 或减少 maxIterations

3. **可视化树**（可选扩展）：
   ```javascript
   // 在 _steer 或 findPath 中添加：
   viewer.entities.add(new Cesium.Entity({
       polyline: {
           positions: [nearestNode.Cartesian3Grid, newNode.Cartesian3Grid],
           width: 1,
           material: Cesium.Color.YELLOW.withAlpha(0.3)
       }
   }));
   ```

## 常见问题

**Q: 为什么找不到路径？**  
A: 检查起点终点是否在网格内，坡度代价是否过高，或增加 maxIterations

**Q: 路径为什么弯曲？**  
A: RRT 不保证最优，可以减小 stepSize 或后处理平滑路径

**Q: 如何让路径更贴近 A* 的效果？**  
A: 增加 biasToGoal 到 0.3-0.5，或使用 RRT* 变体（需额外实现重连）

## 扩展方向

1. **RRT***：添加重连逻辑以优化路径
2. **路径平滑**：对结果路径做样条插值或贝塞尔曲线拟合
3. **动态障碍**：实时更新 slopeCostGrid 并重新规划
4. **多目标**：支持途经点路径规划

## 代码结构

```
PathPlanning_RRT.js
├── RRT_PathPlanner (类)
│   ├── constructor(slopeAspect, config)
│   ├── findPath(start, end)           // 主函数
│   ├── _initializeGrid()              // 初始化
│   ├── _cartesianToGridNode()         // 坐标转换
│   ├── _sampleRandomNode()            // 随机采样
│   ├── _findNearestNode()             // 最近节点
│   ├── _steer()                       // 扩展
│   ├── _isPathValid()                 // 碰撞检测
│   ├── _distance()                    // 距离计算
│   └── _backtrackPath()               // 路径回溯
└── window.RRT_PathPlanner (全局暴露)
```

---
*文档更新日期：2025-12-09*
