// import rbush from "rbush";
// 3. 创建四叉树索引
// 3. 四叉树节点类
class QuadTreeNode {
  constructor(bbox) {
    this.bbox = bbox;
    this.children = null;
  }

  subdivide() {
    const [minX, minY, maxX, maxY] = this.bbox;
    const midX = (minX + maxX) / 2;
    const midY = (minY + maxY) / 2;

    this.children = [
      new QuadTreeNode([minX, minY, midX, midY]),
      new QuadTreeNode([midX, minY, maxX, midY]),
      new QuadTreeNode([minX, midY, midX, maxY]),
      new QuadTreeNode([midX, midY, maxX, maxY]),
    ];
  }
}

let colorMap = document.querySelector("#SlopeAspect-color");

/************************************************************************/

const ramp = document.createElement("canvas");
ramp.width = 400;
ramp.height = 30;
const ctx = ramp.getContext("2d");
// let values= [0.0, 0.29, 0.5, Math.sqrt(2) / 2, 0.87, 0.91, 1.0];
let values = [0.0, 0.082, 0.18, 0.27, 0.33, 0.39, 0.46, 0.54, 0.78, 1];//弧度，坡度栏显示界面彩带条和对应位置数字
//let values = [0.0, 7.38, 16.2, 24.3, 29.7, 35.1, 41.4, 48.6, 70.2, 90];//角度
// let values = [0.0, 0.005, 0.01, 0.02, 0.03, 0.04, 1.0];

const grd = ctx.createLinearGradient(0, 0, 400, 0);
grd.addColorStop(values[0], "#38a800"); //black

grd.addColorStop(values[1], "#5ebd00"); //pink
grd.addColorStop(values[2], "#8bd100"); //red
grd.addColorStop(values[3], "#c1e800"); //orange
grd.addColorStop(values[4], "#ffff00"); //yellow
grd.addColorStop(values[5], "#ffbf00"); //white

grd.addColorStop(values[6], "#ff8000"); //pink
grd.addColorStop(values[7], "#ff4000"); //red
grd.addColorStop(values[8], "#ff0000"); //orange
grd.addColorStop(values[9], "#ff0000"); //orange

ctx.fillStyle = grd;
ctx.fillRect(0, 5, 400, 30);
// 在色带上标注 value
ctx.font = "12px Arial";
ctx.fillStyle = "black";
values.forEach((value, index) => {
  const x = value * 400;
  ctx.fillText(Math.round(value*90), x - 20, 20); // 标识文字位置
});
colorMap.appendChild(ramp);

/************************************************************************/

const ramp2 = document.createElement("canvas");
ramp2.style.display = "block";
ramp.style.display = "block";
ramp2.width = 400;
ramp2.height = 30;
const ctx2 = ramp2.getContext("2d");

let values2 = [0.0, 0.001, 0.0625, 0.1875, 0.3125, 0.4375, 0.5625, 0.6875, 0.8125, 0.9375, 1];//弧度，坡向栏显示界面彩带条和对应位置数字
//let values2 = [0.0, 0.36, 22.5, 67.5, 112.5, 157.5, 202.5, 247.5, 292.5, 337.5, 360];//角度
const grd2 = ctx2.createLinearGradient(0, 0, 400, 40);

grd2.addColorStop(0.0, "#B0B0B0"); //black
grd2.addColorStop(0.001, "#FF00FF"); //pink
grd2.addColorStop(0.0625, "#FF0000"); //red
grd2.addColorStop(0.1875, "#FFA600"); //orange
grd2.addColorStop(0.3125, "#FFFF00"); //yellow
grd2.addColorStop(0.4375, "#00FF00"); //white

grd2.addColorStop(0.5625, "#00FFFF"); //pink
grd2.addColorStop(0.6875, "#00A6FF"); //red
grd2.addColorStop(0.8125, "#0000FF"); //orange
grd2.addColorStop(0.9375, "#FF00FF"); //orange
grd2.addColorStop(1, "#FF0000"); //orange

ctx2.fillStyle = grd2;
ctx2.fillRect(0, 5, 400, 30);
ctx2.font = "12px Arial";
ctx2.fillStyle = "black";
values2.forEach((value, index) => {
  const x = value * 400;
  ctx2.fillText(Math.round(value*360), x - 20, 20); // 标识文字位置
});
const originalElement = document.querySelector("#SlopeRange");
console.log(originalElement);
const clonedElement = originalElement.cloneNode();
clonedElement.value = "坡向0-360°";//坡向分析显示在页面中的文字
colorMap.appendChild(clonedElement);
colorMap.appendChild(ramp2);

/************************************************************************/

class findPathNode{
  constructor(x, y, z, Cartesian3Grid = [], slopeCost = 0, slope = 0, v = 0, turnAngle = 0, g = 0, h = 0, f = 0, parent = null) {
    this.x = x;
    this.y = y;
    this.z = z;
    this.slopeCost = slopeCost;// 坡度代价
    this.slope = slope;// 坡度
    this.v = v;// 当前速度
    this.turnAngle = turnAngle;// 转向角度(不分正负)
    this.g = g;
    this.h = h;
    this.f = f;
    this.parent = parent;
    this.Cartesian3Grid = Cartesian3Grid;
  }
}

class SlopeAspect {
  // area_alpha = parseInt(document.getElementById("slopetransparency").value);

  constructor(viewer) {
    if (!viewer) throw new Error("no viewer object!");
    this.viewer = viewer;
    this.result = []; //存储创建的坡度分析结果，primitive集合
    this.handler = undefined;
    this.toolTip = "";
    this.config = null;
    this.distance = 0.05 * 1000;//网格分辨率
    this.ellipseResults = []; //对应坐标地形高度
    this.curSlope = []; //坡度
    this.curAspect = []; //坡向
    this.area_alpha = 1; //透明度

    this.slopePosArray = []; //存储某个颜色的所有像元位置信息
    this.aspectPosArray = [];
    this.heightPosArray = []; //高度数组，8点围成方格为一个元素
    this.slopeCostArray = [];//坡度代价矩阵，按左上到右下顺序存放坡度和位置信息
    this.slopeCostGrid = [];//二维数组(网格)，存放计算出的坡度和相互位置关系
    this.curvatureGrid = [];// 曲率计算结果网格（含 A/B/C/D/E/kProf/kPlan）

    this.slopePolygons = []; //存放坡度primitive
    this.aspectPolygons = []; //存放坡向primitive
    this.heightPolygons = []; //存放高度primitive
    this.costPolygons = []; //存放通行代价primitive
    this.curvaturePolygons = []; //存放曲率primitive
    this.landUseCostLayers = []; // 土地因素叠加后的代价图层快照（用于对比）
    this.landUseCostLayerCounter = 0; // 叠加层计数器，保证 layerId 唯一
    this.drawFlag = true; //是否渲染坡度坡向

    // ==================== 通用图层管理系统 ====================
    // 用于动态管理所有类型的 primitive 和 entity
    this.layerRegistry = {}; // 图层注册表（动态添加）
    this.layerOrder = []; // 图层显示顺序列表
    // ==================== 图层管理系统结束 ====================

    // 覆盖区支持：用户绘制的 road/water 覆盖区信息与可视实体缓存
    this.overrideAreas = []; // 存 { type: 'road'|'water', polygonEntity, coords: [[lon,lat],...] }
    this.overrideAreaEntities = []; // 方便一次性移除显示实体

    this.openList = []; //OPEN列表 每个openList用于找一次（一个）路径点，xyz信息，每个格子一个node，用于存储：1.已发现但尚未探索的节点 2.新发现的邻居节点（其实一个意思）
    this.closeList = new Set(); //记录已被访问过的节点，用set.has判断是否存在
    this.pathPoints = [];// 路径点数据集合
    this.pathLines = []; //路径线Entity集合
    this.reFindPathFlag = false;//绘制路径
    this.clearPathFlag = false;//清除路径
    this.gWeight = 1;//g权重
    this.hWeight = 1;//h权重
    this.carWeight = 1500;//车重，单位kg
    this.maxSlope = 28;//最大坡度，单位度
    this.DragF = 0;// 牵引力/N
    this.keepStartEndFlag = false;//是否保留起终点 标志位
    this.keepStartPoint = null;//（保留的）起点坐标
    this.keepEndPoint = null;//（保留的）终点坐标
    this.pathLineNum = 0;//路径线ID
    this.potentialField = null;// 反向搜索潜力场（二维数组），用于存储从每个点到目标的最小代价（cost-to-go）
    this.equTimeCostV = false;// 使用等效时间计算代价（固定速度）（坡度、距离、转向用时间表示代价）
    this.equTimeCostDragF = false;//（固定牵引力）
    this.useAHPMethod = true;// AHP方法计算代价
    this.usePotentialFieldFlag = false;// 是否使用潜力场（反向 Dijkstra -> 从起点按 potential 最小方向跟随）进行全局寻路
    this.useOriginRRTFlag = false;// 是否使用原始RRT算法寻路

    this.elementC = [];// AHP分析法各元素重要性矩阵
    this.weights = [];// AHP分析法各元素权重值数组
    this.ridgeValleyEntities = [];// 山脊线和山谷线实体集合
    this.valleyThresholdRatio = 0.4;// 山谷线阈值比例（相对于最大汇流累积）
    this.ridgeThresholdRatio = 0.4;// 山脊线阈值比例（相对于最大反向汇流累积）
  }
  // 找一维数组最大最小值，代替Math.min和Math.max，不会栈溢出的方法
  arrayMinMax = (arr) => {
    // Math.min 和 Math.max 在大数组时报“Maximum call stack size exceeded.”
    return arr.reduce(
      ([min, max], val) => [Math.min(min, val), Math.max(max, val)],
      [Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]
    );
  };
  // 判断是否为无穷大,true表示是无穷大，false表示不是
  isInfinite(number) {
    return number === Infinity || number === -Infinity;
  }
  
  updateAlpha(newAlpha) {
    this.slopePolygons.forEach((polygon) => {
      polygon.alpha = parseFloat(newAlpha);
      // 更新颜色透明度 - 使用MaterialAppearance方式
      const newColor = polygon.baseColor.withAlpha(parseFloat(newAlpha));
      polygon.primitive.appearance.material.uniforms.color = newColor;
      polygon.primitive.appearance.translucent = parseFloat(newAlpha) < 1.0;
    });

    this.aspectPolygons.forEach((polygon) => {
      polygon.alpha = parseFloat(newAlpha);
      // 更新颜色透明度 - 使用MaterialAppearance方式
      const newColor = polygon.baseColor.withAlpha(parseFloat(newAlpha));
      polygon.primitive.appearance.material.uniforms.color = newColor;
      polygon.primitive.appearance.translucent = parseFloat(newAlpha) < 1;
    });

    this.costPolygons.forEach((polygon) => {
      polygon.alpha = parseFloat(newAlpha);
      // 更新颜色透明度 - 使用MaterialAppearance方式
      const newColor = polygon.baseColor.withAlpha(parseFloat(newAlpha));
      polygon.primitive.appearance.material.uniforms.color = newColor;
      polygon.primitive.appearance.translucent = parseFloat(newAlpha) < 1;
    });

    this.curvaturePolygons.forEach((polygon) => {
      polygon.alpha = parseFloat(newAlpha);
      const newColor = polygon.baseColor.withAlpha(parseFloat(newAlpha));
      polygon.primitive.appearance.material.uniforms.color = newColor;
      polygon.primitive.appearance.translucent = parseFloat(newAlpha) < 1;
    });

  }

  /**
   * 注册新图层到管理系统
   * @param {string} layerId - 图层唯一标识（如 'road', 'water', 'pathLine'）
   * @param {string} layerName - 图层显示名称（如 '道路覆盖', '水域覆盖'）
   * @param {string} type - 图层类型 'primitive' 或 'entity'
   * @param {Array|Object} items - 图层内容（primitive 数组或 entity 对象）
   * @returns {boolean} 注册成功返回 true
   */
  registerLayer(layerId, layerName, type, items) {
    const delegated = window.SlopeAspectLayerModule && window.SlopeAspectLayerModule.registerLayer;
    if (typeof delegated === 'function') {
      return delegated.call(this, layerId, layerName, type, items);
    }
    console.error('[SlopeAspect] SlopeAspectLayerModule.registerLayer 未加载');
    return false;
  }

  /**
   * 将分析图层同步到侧边栏管理
   * @param {string} layerId - 图层标识 (slope/aspect/cost)
   * @param {string} layerName - 显示名称
   * @param {Array} items - primitive 数组
   */
  _syncLayerToSidebar(layerId, layerName, items) {
    const delegated = window.SlopeAspectLayerModule && window.SlopeAspectLayerModule._syncLayerToSidebar;
    if (typeof delegated === 'function') {
      return delegated.call(this, layerId, layerName, items);
    }
    console.error('[SlopeAspect] SlopeAspectLayerModule._syncLayerToSidebar 未加载');
    return;
  }

  /**
   * 从 slopeCostGrid 计算分析区域地理范围
   * @returns {Object|null} { west, south, east, north }
   */
  _getAnalysisBounds() {
    const delegated = window.SlopeAspectLayerModule && window.SlopeAspectLayerModule._getAnalysisBounds;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectLayerModule._getAnalysisBounds 未加载');
    return null;
  }
  
  /**
   * 注销图层
   * @param {string} layerId - 图层 ID
   */
  unregisterLayer(layerId) {
    const delegated = window.SlopeAspectLayerModule && window.SlopeAspectLayerModule.unregisterLayer;
    if (typeof delegated === 'function') {
      return delegated.call(this, layerId);
    }
    console.error('[SlopeAspect] SlopeAspectLayerModule.unregisterLayer 未加载');
    return false;
  }
  
  /**
   * 提升指定图层到最顶层（支持 primitive 和 entity）
   * @param {string} layerId - 图层 ID
   * 
   * 原理：
   * - Primitive: 使用 scene.primitives.raiseToTop() 方法
   * - Entity: Cesium 中 Entity 无直接置顶方法，通过删除再添加实现
   */
  raisePrimitiveToTop(layerId) {
    const delegated = window.SlopeAspectLayerModule && window.SlopeAspectLayerModule.raisePrimitiveToTop;
    if (typeof delegated === 'function') {
      return delegated.call(this, layerId);
    }
    console.error('[SlopeAspect] SlopeAspectLayerModule.raisePrimitiveToTop 未加载');
    return;
  }
  
  /**
   * 获取所有已注册图层列表（用于下拉框）
   * @returns {Array} [{id, name, type, count, visible}, ...]
   */
  getAvailablePrimitives() {
    const delegated = window.SlopeAspectLayerModule && window.SlopeAspectLayerModule.getAvailablePrimitives;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectLayerModule.getAvailablePrimitives 未加载');
    return [];
  }
  
  /**
   * 切换图层可见性
   * @param {string} layerId - 图层 ID
   */
  toggleLayerVisibility(layerId) {
    const delegated = window.SlopeAspectLayerModule && window.SlopeAspectLayerModule.toggleLayerVisibility;
    if (typeof delegated === 'function') {
      return delegated.call(this, layerId);
    }
    console.error('[SlopeAspect] SlopeAspectLayerModule.toggleLayerVisibility 未加载');
    return;
  }

  clearAll() {
    const delegated = window.SlopeAspectStateModule && window.SlopeAspectStateModule.clearAll;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectStateModule.clearAll 未加载');
    return;
  }

  reFindPath() {
    const delegated = window.SlopeAspectStateModule && window.SlopeAspectStateModule.reFindPath;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectStateModule.reFindPath 未加载');
    return;
  }

   /* 切换图层可见性 */
  slopeLayerVisibility() {
    const delegated = window.SlopeAspectStateModule && window.SlopeAspectStateModule.slopeLayerVisibility;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectStateModule.slopeLayerVisibility 未加载');
    return;
  }
  aspectLayerVisibility() {
    const delegated = window.SlopeAspectStateModule && window.SlopeAspectStateModule.aspectLayerVisibility;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectStateModule.aspectLayerVisibility 未加载');
    return;
  }
  costLayerVisibility() { 
    const delegated = window.SlopeAspectStateModule && window.SlopeAspectStateModule.costLayerVisibility;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectStateModule.costLayerVisibility 未加载');
    return;
  }

  // 曲率图层显隐
  curvatureLayerVisibility() {
    const delegated = window.SlopeAspectCurvatureModule && window.SlopeAspectCurvatureModule.curvatureLayerVisibility;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectCurvatureModule.curvatureLayerVisibility 未加载');
    return;
  }

  /**
   * 同步侧边栏中分析图层的复选框状态
   * @param {string} analysisId - slope/aspect/cost
   * @param {boolean} visible - 可见状态
   */
  _syncSidebarCheckbox(analysisId, visible) {
    const delegated = window.SlopeAspectLayerModule && window.SlopeAspectLayerModule._syncSidebarCheckbox;
    if (typeof delegated === 'function') {
      return delegated.call(this, analysisId, visible);
    }
    console.error('[SlopeAspect] SlopeAspectLayerModule._syncSidebarCheckbox 未加载');
    return;
  }

  // 提示实例信息
  openTip() {
    const delegated = window.SlopeAspectInteractionModule && window.SlopeAspectInteractionModule.openTip;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectInteractionModule.openTip 未加载');
    return;
  }
  closeTip() {
    const delegated = window.SlopeAspectInteractionModule && window.SlopeAspectInteractionModule.closeTip;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectInteractionModule.closeTip 未加载');
    return;
  }

// 刷新 UI 下拉列表
  pickPath() {
    const delegated = window.SlopeAspectPathModule && window.SlopeAspectPathModule.pickPath;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  // 内部：设置选中路径显示/隐藏
  _applyPathSelection(selectedArray, visible) {
    const delegated = window.SlopeAspectPathModule && window.SlopeAspectPathModule._applyPathSelection;
    if (typeof delegated === 'function') {
      return delegated.call(this, selectedArray, visible);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  // 反向 Dijkstra：计算每个格子到终点的最小代价（potential）
  computePotentialField(endPoint) {
    const cols = this.slopeCostGrid.length;
    if (!cols) return [];
    const rows = (this.slopeCostGrid[0] || []).length;
    const INF = Number.POSITIVE_INFINITY;
    const potential = Array.from({ length: cols }, () => Array(rows).fill(INF));
    const visited = Array.from({ length: cols }, () => Array(rows).fill(false));
    
    class MinHeap {
      constructor() {
        this.a = [];
      }
      // 新元素入堆并保持堆序
      push(item) {
        this.a.push(item); // 1) 先把新元素放到数组末尾
        let i = this.a.length - 1; //    i 是“当前节点”索引（从末尾开始）,向上冒泡，若父节点比当前索引元素大就交换（小根堆，每个父节点元素必须小于他的子节点元素）
        while (i > 0) {
          // 2) 只要没到根（索引0），就继续尝试上浮
          let p = Math.floor((i - 1) / 2); //    找父节点索引（向下取整，即不管左子还是右子都能匹配到相应父节点）
          if (this.a[p].d <= this.a[i].d)
            // 3) 若父节点的 d 已经 <= 当前 d，堆序满足，停止上浮
            break;
          [this.a[p], this.a[i]] = [this.a[i], this.a[p]]; // 4) 否则交换 当前 与 父节点 位置
          i = p; // 5) 继续以父节点位置为“当前节点”，上浮下一层
        }
      }
      // 移除并取出堆顶元素（最小元素）
      pop() {
        if (!this.a.length) return null; // 空堆直接返回 null
        const r = this.a[0]; // 1) 堆顶是最小元素，先存起来，等会儿返回
        const last = this.a.pop(); // 2) 拿掉数组最后一个元素
        if (this.a.length) {
          // 3) 如果堆里还剩元素
          this.a[0] = last; //    把“最后一个”放到堆顶空位
          let i = 0; //    从根开始向下沉
          while (true) {
            let l = 2 * i + 1,
                r = 2 * i + 2,
                s = i; // l=左子, r=右子, s=最小值索引(先假设是自己)
            if (l < this.a.length && this.a[l].d < this.a[s].d) s = l; // 拿左子比较，选更小
            if (r < this.a.length && this.a[r].d < this.a[s].d) s = r; // 拿右子比较，选更小
            if (s === i) break; // 如果自己就是最小的，已经满足堆序，结束
            [this.a[i], this.a[s]] = [this.a[s], this.a[i]]; // 否则跟更小的那个孩子交换
            i = s; // 继续往下沉
          }
        }
        return r; // 返回之前的堆顶（最小元素）
      }
      isEmpty() {
        return this.a.length === 0;
      }
    }

    const heap = new MinHeap();
    const gx = endPoint.x,
      gy = endPoint.y;
    if (gx < 0 || gx >= cols || gy < 0 || gy >= rows) return potential;
    potential[gx][gy] = 0;
    heap.push({ x: gx, y: gy, d: 0 });

    const dirs = [
      [-1, -1],
      [-1, 0],
      [-1, 1],
      [0, -1],
      [0, 1],
      [1, -1],
      [1, 0],
      [1, 1],
    ];
    const nodeFromGrid = (i, j) => {
      const cell = this.slopeCostGrid[i][j];
      return {
        x: i,
        y: j,
        z: cell && cell.degreeCoordinate ? cell.degreeCoordinate[2] : 0,
        Cartesian3Grid: cell && cell.Cartesian ? cell.Cartesian : null,
        slopeCost: cell && cell.slopeCost ? cell.slopeCost : null,
        slope: cell && cell.slope ? cell.slope : null,
      };
    };

    while (!heap.isEmpty()) {
      const cur = heap.pop();
      const cx = cur.x,
        cy = cur.y;
      if (visited[cx][cy]) continue;
      visited[cx][cy] = true;

      for (const [dx, dy] of dirs) {
        const nx = cx + dx,
          ny = cy + dy;
        if (nx < 0 || nx >= cols || ny < 0 || ny >= rows) continue;
        if (
          !this.slopeCostGrid[nx][ny] ||
          this.slopeCostGrid[nx][ny].length === 0
        )
          continue;
        
        const neighborNode = nodeFromGrid(nx, ny);
        const currentNode = nodeFromGrid(cx, cy);
        let moveCost = 0;
        if(this.equTimeCostV){
          if (typeof this.GetCost_CarWeightCost_BaseV === 'function') {
            const costResult = this.GetCost_CarWeightCost_BaseV(neighborNode, currentNode);
            if (costResult && Number.isFinite(costResult.slopeT) && Number.isFinite(costResult.turnT)) {
              moveCost = costResult.slopeT + costResult.turnT;
            }
          }
          if (!Number.isFinite(moveCost) || moveCost <= 0) {
            // 回退到基础代价，避免等效时间函数缺失或返回异常导致潜力场失败
            moveCost = this.GetCost(neighborNode, currentNode);
          }
        }
        else{
          // 注意：GetCost(from,to) 计算 from->to 的代价，这里反向松弛用 neighbor->current
          moveCost = this.GetCost(neighborNode, currentNode);
          if (!Number.isFinite(moveCost) || moveCost <= 0) continue;
        }

        const nd = potential[cx][cy] + moveCost;
        if (nd < potential[nx][ny]) {
          potential[nx][ny] = nd;
          heap.push({ x: nx, y: ny, d: nd });
        }
      }
    }
    return potential;
  }


  //等距离切分网格（网格长度相同）
  createNew4Distance(distance, config) {
    const delegated = window.SlopeAspectGridModule && window.SlopeAspectGridModule.createNew4Distance;
    if (typeof delegated === 'function') {
      return delegated.call(this, distance, config);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }
  // 等分切分网格，切分成一个num*num的网格（网格数量相同，但长度不同）
  createNew4Num(num, config) {
    const delegated = window.SlopeAspectGridModule && window.SlopeAspectGridModule.createNew4Num;
    if (typeof delegated === 'function') {
      return delegated.call(this, num, config);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }
  





  //获取对应坐标地形高度
  createEllipse(gridSquare) {
    const delegated = window.SlopeAspectGridModule && window.SlopeAspectGridModule.createEllipse;
    if (typeof delegated === 'function') {
      return delegated.call(this, gridSquare);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }
  

  //基于固定牵引力计算
  Heuristic_CarWeightCost_BaseDragF(current, end){
    const G = 9.8;
    const a0 = this.DragF / this.carWeight;// 牵引力加速度
    const Vc = current.v;// 当前速度（需要设成0才行？）
    const dx = Math.abs(current.x - end.x);
    const dy = Math.abs(current.y - end.y);
    const L = Math.sqrt(dx * dx + dy * dy) * this.distance;// 当前点到终点距离(欧几里得距离)
    //const L = (dx + dy) * this.distance;// 曼哈顿距离
    const T = (-Vc + Math.sqrt(Vc*Vc + 2*a0*L)) / a0;// 距离等效时间
    return T;
  }
  GetCost_CarWeightCost_BaseDragF(from, to){
    let height_Direction = 0;
    if (Math.abs(to.z - from.z) > 1e-10) { // 添加小阈值判断
        height_Direction = (to.z - from.z) / Math.abs(to.z - from.z);
    } else {
        height_Direction = 0; // 平地情况
    }//console.log('height_Direction', height_Direction, this.carWeight, this.DragF);
    const G = 9.8;
    let Vc = from.v;// 当前速度
    const dx = Math.abs(from.x - to.x);
    const dy = Math.abs(from.y - to.y);
    const S = Math.sqrt(dx * dx + dy * dy) * this.distance;// 当前点到下一点的距离
    const slopeAngle = to.slope;// 目标点坡度角(角度)
    const slopeAngle_Rad = (Number(to.slope) || 0) * Math.PI / 180;// 目标点坡度角(弧度)
    const a0 = this.DragF / this.carWeight;// 牵引力加速度
    const ap = a0 - G * Math.sin(slopeAngle_Rad) * height_Direction;// 坡度加速度（考虑上下坡height_Direction）
    // let slopeT = (-Vc + Math.sqrt(Vc*Vc + 2*ap*S))/ap;
    // if(slopeT < 0 || Number.isNaN(slopeT)){
    //   slopeT = 999999;
    // }
    let slopeT = 999999; // 默认值
    if (Math.abs(ap) > 1e-10) { // 确保分母不为0
      const discriminant = Vc*Vc + 2*ap*S;
      if (discriminant >= 0) { // 确保根号内非负
          slopeT = (-Vc + Math.sqrt(discriminant)) / ap;
          Vc = Vc + ap * slopeT;
      } else {
          // 处理物理上不可能的情况（坡度太陡）
          slopeT = 999999;
      }
    }
    //console.log('Vc1', Vc);

    let turnT = 0;
    const atmax = G*Math.sin((this.maxSlope - to.slope)*Math.PI / 180); // 最大转向加速度（坡度阈值-当前坡度算出来的重力加速度分量）
    const turnAngle_Rad = to.turnAngle !== undefined ? (to.turnAngle * (Math.PI / 180)) : 0;// 转向角(弧度)
    const k = Math.abs(2 * Math.tan(turnAngle_Rad / 2) / S) == 0 ? 1e-6 : Math.abs(2 * Math.tan(turnAngle_Rad / 2) / S);// 曲率
    const Vtmax = Math.sqrt(atmax / k); // 最大转向速度（与坡度和曲率半径(最小转向半径)相关）
    let SL = S * turnAngle_Rad; // 初始转向路程等于 总路程 * 转向角

    if (Number.isFinite(Vtmax) && Vtmax < Vc && !Number.isNaN(Vtmax)) { 
      //SL = S - Math.max(0, (Vtmax*Vtmax - Vc*Vc) / (2*ap)); // 转向路程
      let SS =  Math.max(0, (Vtmax*Vtmax - Vc*Vc) / (2*atmax));// 直行减速路程 S Straight
      let TS = Math.abs((Vtmax - Vc) / atmax);// T Straight
      let ST = 0, TT = 0;
      Vc = Vtmax;
      if(turnAngle_Rad*S - SS > 0){
        ST = turnAngle_Rad*S - SS;// 转向路程 S Turn
        TT = ST / Vc;// T Turn
      }       
      //turnT = Math.abs((Vtmax - Vc) / ap) + (Math.sqrt(Vtmax*Vtmax + 2*ap*SL) - Vtmax) / ap;// 转向分量等效时间
      turnT = TS + TT;  
    }
    else{
      turnT = SL / Vc;  
    }
    if(Number.isNaN(turnT)){
      turnT = 999999;
    }
    
    //console.log('slopeT', slopeT, 'turnT', turnT, 'Vc2', Vc);
    return { slopeT, turnT, Vc };
  }
  
  /*
  //基于固定初始速度计算   作废，不合理(?)
  //平地距离等效时间（启发函数）
  Heuristic_CarWeightCost_BaseV(current, end){
    //const G = 9.8;// 重力加速度
    //const DragF = this.carWeight * G;// 牵引力
    //const a0 = DragF / this.carWeight;// 加速度
    const Vc = current.v;// 当前速度
    const dx = Math.abs(current.x - end.x);
    const dy = Math.abs(current.y - end.y);
    const S = Math.sqrt(dx * dx + dy * dy);// 当前点到终点距离
    //const T = -Vc + Math.sqrt(Vc*Vc + 2*a0*S) / a0;// 距离等效时间
    const T = S / Vc;// 距离等效时间
    return T;
  }
  //上下坡转向等效时间
  GetCost_CarWeightCost_BaseV(from, to){
    const G = 9.8;
    const DragF = 0;// 牵引力, 此方法牵引力为0，不用this.DragF
    const dx = Math.abs(from.x - to.x);
    const dy = Math.abs(from.y - to.y);
    //const S = Math.sqrt(dx * dx + dy * dy);// 当前点到下一点距离
    const S = this.distance;
    //const Vc = from.v;// 当前速度

    //const slopeAngle = to.slope;// 目标点坡度角(角度)(直接用to.slope了)
    const slopeAngle_Rad = (Number(to.slope) || 0) * Math.PI / 180;// 目标点坡度角(弧度)
    const a0 = DragF / this.carWeight;// 牵引力加速度（此方法为0）
    let Vc = Math.sqrt(2 * G*Math.sin(this.maxSlope * (Math.PI / 180)) * S); //当前速度 = 最大坡度速度
    const ap = a0 - G * Math.sin(slopeAngle_Rad);// 坡度加速度
    let slopeT = (Math.sqrt(Vc*Vc + 2*ap*S) - Vc) / ap / to.slopeCost;// 坡度分量等效时间
    if(Number.isNaN(slopeT)){ slopeT = 999999; }
    
    let turnT = 0;
    let R = S;// 转向半径（未达到速度限制，原速转弯）
    if(this.usePotentialFieldFlag){
      const turnAngle_Rad = to.turnAngle !== undefined ? ((to.turnAngle * Math.PI) / 180) : 0;
      let SL = S * turnAngle_Rad;
      turnT = SL / Vc;
    }
    else{ 
      const atmax = G*Math.sin((this.maxSlope - to.slope)*Math.PI / 180); // 最大转向加速度（坡度阈值-当前坡度算出来的重力加速度分量）
      const turnAngle_Rad = to.turnAngle !== undefined ? ((to.turnAngle / 180) * Math.PI) : 0;// 转向角(弧度)
      const k = Math.abs(2 * Math.tan(turnAngle_Rad / 2) / S) == 0 ? 1e-6 : Math.abs(2 * Math.tan(turnAngle_Rad / 2) / S);// 曲率
      const Vtmax = Math.sqrt(atmax / k); // 最大转向速度
      let SL = S * turnAngle_Rad; // 初始转向路程等于总路程
      //console.log('from', from, 'ap', ap, 'Vtmax', Vtmax, 'Vc', Vc);
      if (Number.isFinite(Vtmax) && Vtmax < Vc && !Number.isNaN(Vtmax)) { 
        //SL = S - Math.max(0, (Vtmax*Vtmax - Vc*Vc) / (2*ap)); // 转向路程
        let SS =  Math.max(0, (Vtmax*Vtmax - Vc*Vc) / (2*atmax));
        let TS = Math.abs((Vtmax - Vc) / atmax);
        let ST = 0, TT = 0;
        Vc = Vtmax;
        if((to.turnAngle/180)*Math.PI*S - SS > 0){
          ST = (to.turnAngle/180)*Math.PI*S - SS;
          TT = ST / Vc;
        }
           
        //turnT = Math.abs((Vtmax - Vc) / ap) + (Math.sqrt(Vtmax*Vtmax + 2*ap*SL) - Vtmax) / ap;// 转向分量等效时间
        turnT = TS + TT;  
      }
      else{
        turnT = SL / Vc;  
      }
    }
    //const totalT = slopeT + turnT; console.log('Angle', to.turnAngle, 'R', R, '\nturnT', turnT, 'slopeT', slopeT, 'totalT', totalT);

    return { slopeT, turnT, Vc };
  }*/

  // AHP方法
  AHP_Heuristic(a, b, startx, starty, endx, endy) {
    const dx = Math.abs(a.x - b.x);
    const dy = Math.abs(a.y - b.y);

    // 垂距
    //const cross = (b.x - startx)*(endy - starty)-(b.y - starty)*(endx - startx);

    return Math.sqrt(dx * dx + dy * dy)// + Math.abs(cross);
    //return dx + dy;
  }
  AHP_GetCost(from, to) {
    // 计算的坡度代价（值越大越难通行）
    const slopeCost = to.slopeCost;

    // 总预估代价            
    return slopeCost;
  }

  // 原始方法，查表法
  Heuristic(a, b) {
    const dx = Math.abs(a.x - b.x);
    const dy = Math.abs(a.y - b.y);

    return Math.sqrt(dx * dx + dy * dy);// 欧几里得距离
  }
  GetCost(from, to) {
    const dx = to.x - from.x;
    const dy = to.y - from.y;

    let distanceCost = Math.hypot(dx, dy) * this.distance;
    // if (dx === 1 && dy === 1) {
    //     distanceCost = 12; // 对角移动
    // } else {
    //     distanceCost = 10; // 水平/垂直移动
    // }

    // 高程代价（上坡更困难）
    const elevationDiff = to.z - from.z;
    let elevationCost;
    if (elevationDiff > 0) {
        // 上坡，使用非线性增加
        elevationCost = Math.pow(elevationDiff, 1.3) * 3;
    } else {
        // 下坡或平地
        elevationCost = Math.abs(elevationDiff) * 0.5;
    }

    // 计算的坡度代价（值越大越能通行，故要除掉）
    const slopeCost = to.slopeCost;

    // 总预估代价            
    return (distanceCost + elevationCost) / slopeCost;
  }

  // 计算三个格点（prev->current->next）之间的转角，返回度数（带符号或绝对值）
  computeTurnAngle(prevNode, currentNode, nextNode, { signed = false } = {}) {
    if (!prevNode || !currentNode || !nextNode) return 0;
    const v1x = currentNode.x - prevNode.x;
    const v1y = currentNode.y - prevNode.y;
    const v2x = nextNode.x - currentNode.x;
    const v2y = nextNode.y - currentNode.y;
    const mag1 = Math.hypot(v1x, v1y) || 1;// 两点间欧式距离计算
    const mag2 = Math.hypot(v2x, v2y) || 1;
    const dot = (v1x*v2x + v1y*v2y) / (mag1*mag2);
    // 限定数值范围以避免 NaN
    const cos = Math.max(-1, Math.min(1, dot));
    // 无符号角度（0..180）
    const angleRad = Math.acos(cos);
    // 计算 z 分量标志位（用于判断左右转）
    if (signed) {
      const cross = v1x * v2y - v1y * v2x;
      const signedRad = Math.atan2(cross, dot); // -PI..PI
      return signedRad * (180 / Math.PI);
    }
    return Math.abs(angleRad * (180 / Math.PI));
  }

  //8邻域
  GetNeighbors_8(node){
    const neighbors = [];
    const dirs = [[-1,-1], [-1,0], [-1,1], [0,-1], [0,1], [1,-1], [1,0], [1,1]];
    const xSize = this.slopeCostGrid.length - 1;
    const ySize = this.slopeCostGrid[0].length - 1;

    let nx = 0;
    let ny = 0;

    try{
      //循环遍历dirs找到中心像元邻域8个像元
      for (let [dx, dy] of dirs) {
        nx = node.x + dx;
        ny = node.y + dy;
        
        if (nx >= 0 && nx < xSize && ny >= 0 && ny < ySize && this.slopeCostGrid[nx][ny].length != 0) {
          neighbors.push(new findPathNode(
            nx, ny,// x, y
            this.slopeCostGrid[nx][ny].degreeCoordinate[2],// z
            this.slopeCostGrid[nx][ny].Cartesian,// Cartesian3Grid
            this.slopeCostGrid[nx][ny].slopeCost, // slopeCost
            this.slopeCostGrid[nx][ny].slope, // slope
          ));
        }
      }     
      return neighbors;
    } 
    catch(error){
      console.log('nx', nx, 'ny', ny);
      throw error;
    }
  }
  //5邻域（基于父节点方向扩展）
  GetNeighbors_5(node){
    const neighbors = [];
    const xSize = this.slopeCostGrid.length - 1;
    const ySize = this.slopeCostGrid[0].length - 1;
    
    // 如果有父节点，则根据父节点确定前进方向
    if (node.parent) {
      const px = node.parent.x;
      const py = node.parent.y;
      const cx = node.x;
      const cy = node.y;
      
      // 计算进入当前节点的方向
      const in_dx = cx - px;
      const in_dy = cy - py;    
      // 基于进入方向确定5个搜索方向
      let forwardDirs = [];
      
      // 正前方（沿进入方向继续前进）
      const forward = [in_dx, in_dy];
      // 左前方（相对于进入方向）
      const left_forward = [in_dx - in_dy, in_dy + in_dx];
      // 右前方（相对于进入方向）
      const right_forward = [in_dx + in_dy, in_dy - in_dx];      
      // 左侧（相对于进入方向）
      const left = [-in_dy, in_dx];      
      // 右侧（相对于进入方向）
      const right = [in_dy, -in_dx];
      
      forwardDirs = [forward, left_forward, right_forward, left, right];
      
      // 查找邻居节点
      for (let [dx, dy] of forwardDirs) {
        // 归一化方向（防止对角线移动过远）
        if (dx !== 0) dx = dx > 0 ? 1 : -1;
        if (dy !== 0) dy = dy > 0 ? 1 : -1;
        
        const nx = cx + dx;
        const ny = cy + dy;
        
        if (nx >= 0 && nx < xSize && ny >= 0 && ny < ySize && 
            this.slopeCostGrid[nx] && this.slopeCostGrid[nx][ny] && 
            this.slopeCostGrid[nx][ny].length != 0) {
          neighbors.push(new findPathNode(
            nx, ny,
            this.slopeCostGrid[nx][ny].degreeCoordinate[2], // z
            this.slopeCostGrid[nx][ny].Cartesian,    // Cartesian3Grid
            this.slopeCostGrid[nx][ny].slopeCost,    // slopeCost
            this.slopeCostGrid[nx][ny].slope     // slope
          ));
        }
      }
    } else {
      // 如果没有父节点（起始节点），使用默认的8个方向
      const dirs = [[-1,-1], [-1,0], [-1,1], [0,-1], [0,1], [1,-1], [1,0], [1,1]];
      const cx = node.x;
      const cy = node.y;
      
      for (let [dx, dy] of dirs) {
        const nx = cx + dx;
        const ny = cy + dy;
        
        if (nx >= 0 && nx < xSize && ny >= 0 && ny < ySize && 
            this.slopeCostGrid[nx] && this.slopeCostGrid[nx][ny] && 
            this.slopeCostGrid[nx][ny].length != 0) {
          neighbors.push(new findPathNode(
            nx, ny,
            this.slopeCostGrid[nx][ny].degreeCoordinate[2], // z
            this.slopeCostGrid[nx][ny].Cartesian,    // Cartesian3Grid
            this.slopeCostGrid[nx][ny].slopeCost,    // slopeCost
            this.slopeCostGrid[nx][ny].slope     // slope
          ));
        }
      }
    }
    
    return neighbors;
  }
  //选择邻域搜索方法
  GetNeighbors(node){
    switch($('.GetNeighborMethod_select').val()){
      case '8Neighbor':
        return this.GetNeighbors_8(node);
      case '5Neighbor':
        return this.GetNeighbors_5(node);
      default:
        return this.GetNeighbors_8(node);
    }
  }

  //A*算法 最小代价（坡度）路径计算
  FindPath_AStar(startPoint, endPoint) {
    const delegated = window.SlopeAspectPathModule && window.SlopeAspectPathModule.FindPath_AStar;
    if (typeof delegated === 'function') {
      return delegated.call(this, startPoint, endPoint);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  //RRT算法路径规划
  FindPath_RRT() {
    const delegated = window.SlopeAspectPathModule && window.SlopeAspectPathModule.FindPath_RRT;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  //获取选择点（起点、终点）的坡度（颜色）和坐标信息
  GetSlopePath() {
    const delegated = window.SlopeAspectPathModule && window.SlopeAspectPathModule.GetSlopePath;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  // 计算通行代价 并 绘制通行代价图
  DrawCostMap(options) {
    const delegated = window.SlopeAspectCostModule && window.SlopeAspectCostModule.DrawCostMap;
    if (typeof delegated === 'function') {
      return delegated.call(this, options);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  // 计算并绘制曲率图
  DrawCurvatureMap() {
    const delegated = window.SlopeAspectCurvatureModule && window.SlopeAspectCurvatureModule.DrawCurvatureMap;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectCurvatureModule.DrawCurvatureMap 未加载');
    return;
  }

  DrawPath() {
    const delegated = window.SlopeAspectPathModule && window.SlopeAspectPathModule.DrawPath;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  // 绘制通行代价图
  // options: { targetPolygons, layerId, layerName }
  createCostInstance(slopeCostColorGrid, options) {
    const delegated = window.SlopeAspectCostModule && window.SlopeAspectCostModule.createCostInstance;
    if (typeof delegated === 'function') {
      return delegated.call(this, slopeCostColorGrid, options);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  createCurvatureInstance(curvatureColorGrid, options) {
    const delegated = window.SlopeAspectCurvatureModule && window.SlopeAspectCurvatureModule.createCurvatureInstance;
    if (typeof delegated === 'function') {
      return delegated.call(this, curvatureColorGrid, options);
    }
    console.error('[SlopeAspect] SlopeAspectCurvatureModule.createCurvatureInstance 未加载');
    return;
  }

  //绘制坡度坡向图，相同颜色的格子放在同一数组下创建Instance
  createPolygonInstance(PosArray, colorHex, config) {
    //PosArray = aspect/slopePosArray[i]    i为0-9
    //PosArray[i] = aspect/slopePosArray[i'][i]     i'为0-9，i为该颜色下的第几个多边形
    //PosArray[i][0] = aspect/slopePosArray[i'][i][0]     多边形九点绘制坐标positions
    //PosArray[i][1] = aspect/slopePosArray[i'][i][1]     多边形坡度/坡向值
    //const color = Cesium.Color.fromCssColorString(colorHex);

    const color = colorHex;
    let Instances = [];
    let polygonID = '';
    if (config == 0)  {polygonID = '坡度：';}
    else              {polygonID = '坡向：';}

    //1 创建几何实例Instance，给予形状、位置等信息
    for (let i = 0; i < PosArray.length && PosArray[i][0].length > 0; i++) {
      const polygonInstance = new Cesium.GeometryInstance({
        id: {
          type: "SlopeAspect",           // 类型标识，用于 openTip 判断
          name: polygonID,               // 名称：'坡度' 或 '坡向'
          value: PosArray[i][1],         // 实际的坡度/坡向数值
          index: i                       // 可选：实例索引，第i个实例
        },
        geometry: new Cesium.PolygonGeometry({
          polygonHierarchy: new Cesium.PolygonHierarchy(PosArray[i][0]),
          height: 0,
          vertexFormat: Cesium.MaterialAppearance.VERTEX_FORMAT,
        }),
      });
      Instances.push(polygonInstance);
    }
    //2 创建材质material，作用于外观appearance上
    const material = new Cesium.Material({
      fabric: {
        type: "Color",
        uniforms: {
          color: color,
        },
      },
    });
    //3 创建MaterialAppearance以支持动态调节参数，作用于primitive上
    const appearance = new Cesium.MaterialAppearance({
      material: material,
      translucent: color.alpha < 1.0,
      flat: true,
    });
    //4 创建GroundPrimitive以实现贴地效果,使用GroundPrimitive创建贴地的面，作用域primitive上
    const primitive = new Cesium.GroundPrimitive({
      geometryInstances: Instances,
      appearance: appearance,
    });

    // 添加到场景
    viewer.scene.primitives.add(primitive);

    // 保存面信息
    const polygonInfo = {
      primitive: primitive,
      positions: PosArray,
      baseColor: color,
      alpha: color.alpha,
    };

    if (config == 0) {
      this.slopePolygons.push(polygonInfo);
      // 自动注册/更新坡度图层
      this.registerLayer('slope', '坡度图层', 'primitive', this.slopePolygons);
    } else if (config == 1) {
      this.aspectPolygons.push(polygonInfo);
      // 自动注册/更新坡向图层
      this.registerLayer('aspect', '坡向图层', 'primitive', this.aspectPolygons);
    } else return;

    return polygonInfo;
  }

  createArrowInstance(targetPoint, center, curAspect) {
    let positions1 = [Cesium.Cartographic.toCartesian(center), targetPoint];

    //箭头线
    const instance = new Cesium.GeometryInstance({
      id: {
        type: "SlopeAspect",
        value: curAspect,
      },
      geometry: new Cesium.GroundPolylineGeometry({
        positions: positions1,
        width: this.arrowWidth,
      }),
      attributes: {
        color: Cesium.ColorGeometryInstanceAttribute.fromColor(
          Cesium.Color.RED.withAlpha(0.8)
        ),
        show: new Cesium.ShowGeometryInstanceAttribute(true), //显示或者隐藏
      },
    });
    return instance;
  }
  calculateSlope() {
    const delegated = window.SlopeAspectGridModule && window.SlopeAspectGridModule.calculateSlope;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  //山脊线山谷线提取
  /**
   * Ridge_Valley_Analysis()
   * 功能：使用汇流累积法（Flow Accumulation）提取栅格的山脊线和山谷线
   * 
   * 算法原理：
   * 1. 山谷线：水流汇集处（正向汇流累积，高程从高到低流动）
   *    - 汇流累积值大的格子为山谷线（水流汇聚）
   * 2. 山脊线：水流分散处（反向汇流累积，高程从低到高流动）
   *    - 反向汇流累积值大的格子为山脊线（分水岭）
   * 
   * 方法：D8 算法（8邻域流向分析）
   * 输出：在 Cesium 场景中绘制山脊线（红色）和山谷线（蓝色）
   */
  Ridge_Valley_Analysis() {
    const delegated = window.SlopeAspectTerrainModule && window.SlopeAspectTerrainModule.Ridge_Valley_Analysis;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }


  //根据坡度值赋值颜色(代价版：)
  calculateSlopeCostColor(value) {
    let color;
    if (value <= 5) {
      return [(color = "#38A800"), 0];
    } else if (value < 10) {
      //return [(color = "#8BD100"), 1];
      return [(color = "#C1E800"), 1];
    } else if (value < 22) {
      //return [(color = "#C1E800"), 2];
      return [(color = "#FFBF00"), 2];
    } else if (value < 35) {
      //return [(color = "#FFFF00"), 3];
      return [(color = "#FF8000"), 3];
    } else if (value < 25) {
      //return [(color = "#FFBF00"), 4];
      return [(color = "#FF0000"), 4];
    } else if (value < 30) {
      //return [(color = "#FF8000"), 5];
      return [(color = "#FF0000"), 5];
    } else if (value < 49) {
      return [(color = "#FF0000"), 6];
    } else if (value < 70.5) {
      return [(color = "#FF0000"), 7];
    } else if (value < 89) {
      return [(color = "#FF0000"), 8];
    } else if (value <= 91) {
      return [(color = "#FF0000"), 9];
    }
  }
   //根据坡度值赋值颜色
  calculateSlopeColor(value) {
    let color;
    if (value <= 7.4) {
      return [(color = "#38A800"), 0];
    } else if (value < 16.568) {
      return [(color = "#5EBD00"), 1];
    } else if (value < 23.971) {
      return [(color = "#8BD100"), 2];
    } else if (value < 29.96) {
      return [(color = "#C1E800"), 3];
    } else if (value < 35.25) {
      return [(color = "#FFFF00"), 4];
    } else if (value < 41.244) {
      return [(color = "#FFBF00"), 5];
    } else if (value < 49) {
      return [(color = "#FF8000"), 6];
    } else if (value < 70.5) {
      return [(color = "#FF4000"), 7];
    } else if (value < 89) {
      return [(color = "#FF0000"), 8];
    } else if (value <= 91) {
      return [(color = "#FF0000"), 9];
    }
  }
  //根据坡向值赋值颜色
  calculateAspectColor(value) {
    /*
        ****使用画布****
        const normalizedValue = Math.min(1, Math.max(0, value / 360));
        const imageData = ctx2.getImageData(Math.round(normalizedValue * (ramp.width - 1)), 0, 1, 1).data;
        // console.log(imageData);
        // 将颜色转换为rgba字符串
        const color = `rgba(${imageData[0]}, ${imageData[1]}, ${imageData[2]}, ${alpha})`;
        // console.log(normalizedValue);
        // console.log(color);
    
        return color;
        */
    let color;
    if (value <= 0.0) {
      return [(color = "#B0B0B0"), 0];
    } else if (value < 22.5) {
      return [(color = "#FF0000"), 1];
    } else if (value < 67.5) {
      return [(color = "#FFA600"), 2];
    } else if (value < 112.5) {
      return [(color = "#FFFF00"), 3];
    } else if (value < 157.5) {
      return [(color = "#00FF00"), 4];
    } else if (value < 202.5) {
      return [(color = "#00FFFF"), 5];
    } else if (value < 247.5) {
      return [(color = "#00A6FF"), 6];
    } else if (value < 292.5) {
      return [(color = "#0000FF"), 7];
    } else if (value < 337.5) {
      return [(color = "#FF00FF"), 8];
    } else if (value <= 360) {
      return [(color = "#FF0000"), 9];
    }
  }

  /**
   * calculateCostColor() - 将通行代价值重分类为5个等级并映射到颜色
   * 
   * 颜色分级依据：
   * 根据坡度-代价计算公式（2067-2083行）的5个单调分段，计算每段的代价范围：
   *   第1段: slope <= 5°        → slopeCost = 10 (常量)
   *   第2段: 5° < slope <= 9°   → slopeCost 单调递减
   *   第3段: 9° < slope <= 22°  → slopeCost 单调递增
   *   第4段: 22° < slope <= 35° → slopeCost 单调递减
   *   第5段: slope > 35°        → slopeCost = 1e-6 (极小值，表示不可通行)
   * 
   * 每段两端值作为阈值，将所有代价值重分类为5个等级，从易通行到难通行：
   *   等级1（绿色）: 最易通行
   *   等级2（浅绿）: 较易通行
   *   等级3（黄色）: 中等通行
   *   等级4（橙色）: 较难通行
   *   等级5（红色）: 最难通行/不可通行
   * 
   * @returns {Array} slopeCostColorGrid - 二维数组，每个元素包含 {i, j, color, colorClass, gridSquare}
   */
  calculateCostColor(costValArray) {
    const delegated = window.SlopeAspectCostModule && window.SlopeAspectCostModule.calculateCostColor;
    if (typeof delegated === 'function') {
      return delegated.call(this, costValArray);
    }
    console.error('[SlopeAspect] 对应模块方法未加载');
    return;
  }

  calculateCurvatureColor() {
    const delegated = window.SlopeAspectCurvatureModule && window.SlopeAspectCurvatureModule.calculateCurvatureColor;
    if (typeof delegated === 'function') {
      return delegated.call(this);
    }
    console.error('[SlopeAspect] SlopeAspectCurvatureModule.calculateCurvatureColor 未加载');
    return [];
  }

  /**
   * 笛卡尔坐标数组转WGS84
   * @param {Array} cartesianList 笛卡尔坐标数组
   * @returns {Array} WGS84经纬度坐标数组
   */
  Cartesian3ListToWGS84(cartesianList) {
    let ellipsoid = Cesium.Ellipsoid.WGS84;
    let result = [];
    for (let index = 0; index < cartesianList.length; index++) {
      const cartesian = cartesianList[index];
      let cartographic = ellipsoid.cartesianToCartographic(cartesian);
      result.push({
        lng: Cesium.Math.toDegrees(cartographic.longitude),
        lat: Cesium.Math.toDegrees(cartographic.latitude),
        alt: cartographic.height,
      });
    }
    return result;
  }
}



