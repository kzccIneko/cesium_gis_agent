/**
 * PathPlanning_RRT.js
 * 基于 RRT (Rapidly-exploring Random Tree) 的路径规划算法
 * 用于在坡度代价网格 (slopeCostGrid) 中寻找从起点到终点的可行路径
 * 
 * 算法原理：
 * 1. 从起点开始构建随机探索树
 * 2. 每次迭代随机采样一个点,向其最近的树节点扩展
 * 3. 检查扩展路径是否满足代价约束(坡度、转角等)
 * 4. 当树节点足够接近终点时,回溯生成完整路径
 * 
 * 依赖：需要 SlopeAspect 类实例(包含 slopeCostGrid、distance 等)
 */

class RRT_PathPlanner {
  /**
   * 构造函数
   * @param {SlopeAspect} slopeAspect - 主坡度分析对象实例
   * @param {Object} config - 配置参数
   *   - maxIterations: 最大迭代次数(默认 5000)
   *   - stepSize: 每步扩展距离(默认 2 个网格单位)
   *   - goalThreshold: 到达目标的阈值距离(默认 1.5 个网格单位)
   *   - maxSlopeCost: 最大允许坡度代价(默认 10,超过视为不可通行)
   *   - biasToGoal: 朝目标采样的概率(默认 0.1,即 10% 概率直接朝目标扩展)
   */
  constructor(slopeAspect, config = {}) {
    // 引用主对象(包含网格、坡度代价等数据)
    this.slopeAspect = slopeAspect;
    
    // 算法参数配置(可按需调整)
    this.maxIterations = config.maxIterations || 5000;  // 最大迭代次数
    this.stepSize = config.stepSize || 2;                // 扩展步长(网格单位)
    this.goalThreshold = config.goalThreshold || 1.5;    // 到达目标阈值
    this.maxSlopeCost = config.maxSlopeCost || 10;       // 最大坡度代价限制
    this.biasToGoal = config.biasToGoal || 0.1;          // 朝目标偏向概率
    
    // RRT 树(存储所有节点)
    this.tree = [];
    
    // 网格边界(从 slopeCostGrid 获取)
    this.gridWidth = 0;   // 网格 X 方向尺寸
    this.gridHeight = 0;  // 网格 Y 方向尺寸
  }

  /**
   * 主函数：执行 RRT 寻路
   * @param {Cesium.Cartesian3} startCartesian - 起点笛卡尔坐标
   * @param {Cesium.Cartesian3} endCartesian - 终点笛卡尔坐标
   * @returns {Array|null} 路径点数组(每项包含 {x,y,z,Cartesian3Grid,...})或 null(失败)
   */
  findPath(startCartesian, endCartesian) {
    console.log('RRT: 开始寻路...');
    const startTime = performance.now();
    
    // 1. 初始化：验证网格数据与边界
    if (!this._initializeGrid()) {
      alert('RRT 错误：slopeCostGrid 未初始化或为空');
      return null;
    }
    
    // 2. 将起点和终点的笛卡尔坐标转换为网格索引 (x, y)
    const startNode = this._cartesianToGridNode(startCartesian, true);  // true 表示起点
    const goalNode = this._cartesianToGridNode(endCartesian, false);
    
    if (!startNode || !goalNode) {
      alert('RRT 错误：起点或终点不在有效网格范围内');
      return null;
    }
    
    console.log(`RRT: 起点网格 (${startNode.x}, ${startNode.y}), 终点网格 (${goalNode.x}, ${goalNode.y})`);
    
    // 3. 初始化树：将起点作为根节点加入
    this.tree = [startNode];
    
    // 4. 主循环：迭代扩展树直到找到路径或达到最大迭代次数
    for (let iter = 0; iter < this.maxIterations; iter++) {
      // 4.1 随机采样：生成随机点(偶尔朝目标采样以加速收敛)
      const randomNode = (Math.random() < this.biasToGoal) 
        ? goalNode  // 直接朝目标
        : this._sampleRandomNode();  // 随机采样
      
      // 4.2 找到树中离随机点最近的节点
      const nearestNode = this._findNearestNode(randomNode);
      
      // 4.3 从最近节点朝随机点方向扩展一步(距离 = stepSize)
      const newNode = this._steer(nearestNode, randomNode);
      
      // 4.4 碰撞检测：检查从 nearestNode 到 newNode 的路径是否可行
      //     (检查沿途网格的坡度代价是否超限、是否出界等)
      if (!this._isPathValid(nearestNode, newNode)) {
        continue;  // 路径不可行,跳过此次迭代
      }
      
      // 4.5 将新节点加入树(并记录其父节点用于回溯路径)
      newNode.parent = nearestNode;
      this.tree.push(newNode);
      
      // 4.6 检查是否到达目标：新节点距离目标 < goalThreshold
      if (this._distance(newNode, goalNode) < this.goalThreshold) {
        console.log(`RRT: 找到路径！迭代次数=${iter + 1}, 树节点数=${this.tree.length}`);
        
        // 4.7 回溯路径：从 newNode 沿 parent 指针回溯到起点
        const path = this._backtrackPath(newNode, startCartesian, endCartesian);
        
        const endTime = performance.now();
        console.log(`RRT: 路径长度=${path.length}, 用时=${Math.round(endTime - startTime)}ms`);
        
        return path;  // 返回路径点数组
      }
      
      // 每 500 次迭代打印进度(可选,便于调试)
      if ((iter + 1) % 500 === 0) {
        console.log(`RRT: 迭代 ${iter + 1}/${this.maxIterations}, 树节点数=${this.tree.length}`);
      }
    }
    
    // 5. 达到最大迭代次数仍未找到路径
    console.warn('RRT: 达到最大迭代次数,未找到路径');
    alert('RRT 未找到可行路径,请尝试调整参数或检查地形');
    return null;
  }

  /**
   * 初始化网格边界信息
   * @returns {boolean} 是否成功初始化
   */
  _initializeGrid() {
    const grid = this.slopeAspect.slopeCostGrid;
    if (!grid || grid.length === 0) return false;
    
    this.gridWidth = grid.length;           // X 方向(列数)
    this.gridHeight = grid[0].length || 0;  // Y 方向(行数)
    
    return this.gridHeight > 0;
  }

  /**
   * 将笛卡尔坐标转换为网格节点(包含网格索引与实际坐标)
   * @param {Cesium.Cartesian3} cartesian - 笛卡尔坐标
   * @param {boolean} isStart - 是否为起点(用于初始化速度等)
   * @returns {Object|null} 节点对象 {x, y, z, Cartesian3Grid, slopeCost, ...} 或 null
   */
  _cartesianToGridNode(cartesian, isStart = false) {
    const grid = this.slopeCostGrid;
    let minDist = Infinity;
    let closestNode = null;
    
    // 遍历网格找到最近的格子
    for (let i = 0; i < this.gridWidth; i++) {
      for (let j = 0; j < this.gridHeight; j++) {
        // slopeCostGrid[i][j] 结构示例：[Cartesian3, slope, [lon,lat,h], slopeCost, ...]
        const gridCell = grid[i][j];
        if (!gridCell || !gridCell[0]) continue;  // 跳过无效格子
        
        const cellCartesian = gridCell[0];  // 格子中心的笛卡尔坐标
        const dist = Cesium.Cartesian3.distance(cartesian, cellCartesian);
        
        if (dist < minDist) {
          minDist = dist;
          closestNode = {
            x: i,                      // 网格 X 索引
            y: j,                      // 网格 Y 索引
            z: 0,                      // 高度(暂不用,可从 gridCell[2][2] 获取)
            Cartesian3Grid: cellCartesian,  // 笛卡尔坐标(用于绘制)
            slopeCost: Number(gridCell[3]) || 1,  // 坡度代价(gridCell[3])
            slope: Number(gridCell[1]) || 0,      // 坡度值(度,gridCell[1])
            v: isStart ? 5 : 0,        // 初始速度(起点给默认值 5 m/s)
            parent: null               // 父节点(回溯用)
          };
        }
      }
    }
    
    return closestNode;
  }

  /**
   * 在网格范围内随机采样一个节点
   * @returns {Object} 随机节点 {x, y}(只需网格索引,其它信息后续补充)
   */
  _sampleRandomNode() {
    return {
      x: Math.floor(Math.random() * this.gridWidth),   // 随机 X 索引 [0, gridWidth)
      y: Math.floor(Math.random() * this.gridHeight),  // 随机 Y 索引 [0, gridHeight)
    };
  }

  /**
   * 在树中找到离目标点最近的节点(欧氏距离)
   * @param {Object} target - 目标节点 {x, y}
   * @returns {Object} 树中最近的节点
   */
  _findNearestNode(target) {
    let minDist = Infinity;
    let nearest = this.tree[0];
    
    for (const node of this.tree) {
      const dist = this._distance(node, target);
      if (dist < minDist) {
        minDist = dist;
        nearest = node;
      }
    }
    
    return nearest;
  }

  /**
   * 从起始节点朝目标节点方向扩展固定步长(stepSize)
   * @param {Object} from - 起始节点 {x, y, ...}
   * @param {Object} to - 目标节点 {x, y}
   * @returns {Object} 新节点(距离 from 为 stepSize 的点,方向朝 to)
   */
  _steer(from, to) {
    // 计算方向向量
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    
    // 如果距离小于步长,直接返回目标点；否则按步长缩放
    let newX, newY;
    if (dist <= this.stepSize) {
      newX = to.x;
      newY = to.y;
    } else {
      const ratio = this.stepSize / dist;
      newX = from.x + dx * ratio;
      newY = from.y + dy * ratio;
    }
    
    // 四舍五入到整数网格索引
    newX = Math.round(newX);
    newY = Math.round(newY);
    
    // 边界检查
    newX = Math.max(0, Math.min(this.gridWidth - 1, newX));
    newY = Math.max(0, Math.min(this.gridHeight - 1, newY));
    
    // 从 slopeCostGrid 读取该格子的完整信息
    const gridCell = this.slopeCostGrid[newX][newY];
    if (!gridCell) {
      // 无效格子,返回最小代价节点作为占位
      return {
        x: newX,
        y: newY,
        z: 0,
        Cartesian3Grid: from.Cartesian3Grid,  // 暂用 from 的坐标
        slopeCost: 999,  // 设为极大值表示不可行
        slope: 0,
        v: from.v || 0,
        parent: null
      };
    }
    
    return {
      x: newX,
      y: newY,
      z: 0,
      Cartesian3Grid: gridCell[0],              // 笛卡尔坐标
      slopeCost: Number(gridCell[3]) || 1,      // 坡度代价
      slope: Number(gridCell[1]) || 0,          // 坡度(度)
      v: from.v || 0,                           // 继承速度
      parent: null                              // 稍后设置
    };
  }

  /**
   * 检查从 from 节点到 to 节点的路径是否可行
   * 检查内容：
   *   1. 沿途网格坐标是否在边界内
   *   2. 沿途网格的坡度代价是否超过 maxSlopeCost
   *   3. (可选)转角是否过大、坡度是否超限等
   * 
   * @param {Object} from - 起始节点
   * @param {Object} to - 目标节点
   * @returns {boolean} true 表示路径可行,false 表示不可行
   */
  _isPathValid(from, to) {
    // 1. 检查目标节点是否越界
    if (to.x < 0 || to.x >= this.gridWidth || to.y < 0 || to.y >= this.gridHeight) {
      return false;
    }
    
    // 2. 检查目标节点的坡度代价是否超限
    if (to.slopeCost > this.maxSlopeCost) {
      return false;  // 该格子坡度过大,视为障碍
    }
    
    // 3. (可选)沿路径插值检查中间点(防止跳过障碍)
    //    这里用简单的布雷森汉姆直线算法逐格检查
    const steps = Math.max(Math.abs(to.x - from.x), Math.abs(to.y - from.y));
    if (steps === 0) return true;  // 同一格子
    
    for (let i = 1; i <= steps; i++) {
      const ratio = i / steps;
      const cx = Math.round(from.x + (to.x - from.x) * ratio);
      const cy = Math.round(from.y + (to.y - from.y) * ratio);
      
      // 边界检查
      if (cx < 0 || cx >= this.gridWidth || cy < 0 || cy >= this.gridHeight) {
        return false;
      }
      
      // 坡度代价检查
      const cell = this.slopeCostGrid[cx][cy];
      if (!cell) return false;
      const cost = Number(cell[3]) || 1;
      if (cost > this.maxSlopeCost) {
        return false;  // 中间某格坡度过大
      }
    }
    
    // 4. 全部通过,路径可行
    return true;
  }

  /**
   * 计算两节点间的欧氏距离(网格索引空间)
   * @param {Object} a - 节点 {x, y}
   * @param {Object} b - 节点 {x, y}
   * @returns {number} 距离
   */
  _distance(a, b) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  /**
   * 回溯路径：从目标节点沿 parent 指针回溯到起点
   * @param {Object} goalNode - 到达目标附近的树节点
   * @param {Cesium.Cartesian3} startCartesian - 原始起点笛卡尔坐标(非网格中心)
   * @param {Cesium.Cartesian3} endCartesian - 原始终点笛卡尔坐标(非网格中心)
   * @returns {Array} 路径点数组(从起点到终点顺序,每项包含完整节点信息)
   */
  _backtrackPath(goalNode, startCartesian, endCartesian) {
    const path = [];
    let current = goalNode;
    
    // 从目标回溯到起点
    while (current) {
      path.unshift({  // 插入到数组开头(保证最终顺序为起点->终点)
        x: current.x,
        y: current.y,
        z: current.z,
        Cartesian3Grid: current.Cartesian3Grid,
        slopeCost: current.slopeCost,
        slope: current.slope,
        v: current.v,
        turnAngle: 0,  // RRT 不计算转角,可按需扩展
        g: 0,
        h: 0,
        f: 0,
        parent: null   // 绘制时不需要 parent 引用
      });
      current = current.parent;
    }
    
    // 在路径首尾插入真实起点/终点(非网格中心)
    //   - 起点：用户点击的实际位置
    //   - 终点：用户点击的实际位置
    path.unshift({
      x: 0, y: 0, z: 0,
      Cartesian3Grid: startCartesian,
      slopeCost: 1, slope: 0, v: 0, turnAngle: 0, g: 0, h: 0, f: 0, parent: null
    });
    path.push({
      x: 0, y: 0, z: 0,
      Cartesian3Grid: endCartesian,
      slopeCost: 1, slope: 0, v: 0, turnAngle: 0, g: 0, h: 0, f: 0, parent: null
    });
    
    return path;
  }

  /**
   * 便捷属性：访问主对象的 slopeCostGrid(避免重复写 this.slopeAspect.slopeCostGrid)
   */
  get slopeCostGrid() {
    return this.slopeAspect.slopeCostGrid;
  }
}

// 暴露到全局(供 eventBindInit.js 或其它脚本调用)
window.RRT_PathPlanner = RRT_PathPlanner;
