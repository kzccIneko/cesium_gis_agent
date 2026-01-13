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

    this.slopePolygons = []; //存放坡度primitive
    this.aspectPolygons = []; //存放坡向primitive
    this.heightPolygons = []; //存放高度primitive
    this.costPolygons = []; //存放通行代价primitive
    this.drawFlag = true; //是否渲染坡度坡向

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

  }

  // 提升指定图元到最顶层显示
  raisePrimitiveToTop() {
    // 获取当前场景中的所有图元
    const primitives = this.viewer.scene.primitives;console.log('primitives', primitives);
  }

  clearAll() {
    // console.log(this);
    console.log("clear");

    if(this.handler){
      this.handler.destroy();
      this.handler = undefined;
    }
    this.slopePolygons.forEach((element) => {
      this.viewer.scene.primitives.remove(element.primitive);
    });
    this.slopePolygons = [];

    this.aspectPolygons.forEach((element) => {
      this.viewer.scene.primitives.remove(element.primitive);
    });
    this.aspectPolygons = [];

    this.costPolygons.forEach((element) => {
      this.viewer.scene.primitives.remove(element.primitive);
    });
    this.costPolygons = [];
    
    //删除所有点
    this.viewer.entities.removeAll();
    this.slopeCostArray = [];
    this.slopeCostGrid = [];//清空网格数组
    this.ridgeValleyEntities = [];//清空山脊与山谷线

    //清空所有路径
    this.openList = [];
    this.closeList = [];
    this.pathLines = [];
    this.keepStartPoint = null;
    this.keepEndPoint = null;
    this.pathLineNum = 0;
    this.pathPoints = [];

  }

  reFindPath() {
    this.closeList = new Set();
    this.openList = [];
    this.gWeight = $("#gWeight").val();
    this.hWeight = $("#hWeight").val();
    this.carWeight = $('#carWeight').val(); //车辆重量，单位kg
    this.DragF = 9.8 * this.carWeight * Math.sin(this.maxSlope*Math.PI/180) || $('#DragF').val();// 最大牵引力，单位N
    this.potentialField = null;// 重置潜力场
    console.log('keepStartEndFlag', this.keepStartEndFlag, 'clearPathFlag', this.clearPathFlag, 'useOriginRRTFlag', this.useOriginRRTFlag);
    
    // 绘制路径（使用代码内指定起终点）
    if(document.getElementById('specifiedStartEnd').checked){
      this.keepStartPoint = Cesium.Cartesian3.fromDegrees(100.655395, 29.494247, 3419.32);
      this.keepEndPoint = Cesium.Cartesian3.fromDegrees(100.647575, 29.508656, 3386.11);
      new Cesium.Entity({
        position: this.keepStartPoint,
        point: {
          pixelSize: 10,
          color: Cesium.Color.WHITE,
        },
      });
      new Cesium.Entity({
        position: this.keepEndPoint,
        point: {
          pixelSize: 10,
          color: Cesium.Color.WHITE,
        },
      });
      this.FindPath_AStar(this.keepStartPoint, this.keepEndPoint);
      return;
    }

    // 绘制路径（保留原有路径）
    if(this.keepStartEndFlag && !this.clearPathFlag){
      if (this.useOriginRRTFlag) {
        this.FindPath_RRT();
        return;
      }
      // console.log('this.pathLineNum', this.pathLineNum, 'this.keepStartPoint', this.keepStartPoint, 'this.keepEndPoint', this.keepEndPoint);
      this.FindPath_AStar(this.keepStartPoint, this.keepEndPoint);
      return;
    }

    this.pathLineNum = 0;//清空多条路径
    this.pathLines = [];//清空路径信息
    this.pathPoints = [];//清空路径点
    if (this.handler) {
      this.handler.destroy();
      this.handler = undefined;
    }// 移除互动操作
    const toRemove = [];// 存储需要移除的路径点实体
    this.viewer.entities.values.forEach((e) => {
      try {
        if (
          e &&
          (e.isPath === true ||
            (typeof e.id === "string" && e.id.startsWith("slope_path_")))
        ) {
          toRemove.push(e);
        }
      } catch (err) {
        // 忽略无法访问的实体属性
      }
    });
    toRemove.forEach((ent) => this.viewer.entities.remove(ent));

    // 重新绘制路径（删除原有路径）,reFindPathFlag 默认为false，即不保留原路径
    if(this.reFindPathFlag){
      this.GetSlopePath();
      this.reFindPathFlag = false;
    }
  }

   /* 切换图层可见性 */
  slopeLayerVisibility() {
    if (this.slopePolygons && this.slopePolygons.length >= 2) {
      //this.mapPrimitive1.show = !this.mapPrimitive1.show;
      this.slopePolygons.forEach((element) => {
        element.primitive.show = !element.primitive.show;
      });
      //this.mapPrimitive2.show = !this.mapPrimitive2.show;
      console.log("slopeChange");
    }
  }
  aspectLayerVisibility() {
    if (this.aspectPolygons && this.aspectPolygons.length >= 2) {
      this.aspectPolygons.forEach((element) => {
        element.primitive.show = !element.primitive.show;
      });
      console.log("aspectChange");
    }
  }
  costLayerVisibility() { 
    if (this.costPolygons && this.costPolygons.length >= 2) {
      this.costPolygons.forEach((element) => {
        element.primitive.show = !element.primitive.show;
      });
      console.log("costChange");
    }
  }

  // 提示实例信息
  openTip() {
    const $this = this;
    const viewer = this.viewer;
    this.handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
    this.handler.setInputAction(function (movement) {
      let endPos = movement.endPosition;
      var pick = viewer.scene.pick(endPos);
      if (pick && pick.id && (pick.id.type === "SlopeAspect" || pick.id.type === "Cost")) {
        const name = pick.id.name || '';  // '坡度' 或 '坡向'
        const value = pick.id.value;
        $this.toolTip = `${name}: ${value.toFixed(2)}°`;
        CreateRemindertip($this.toolTip, endPos, true);
      } else {
        $this.toolTip = "";
        CreateRemindertip($this.toolTip, endPos, false);
      }
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
  }
  closeTip() {
    if (this.handler) {
      this.handler.destroy();
      this.handler = undefined;
      this.toolTip = "";
    }
  }

// 刷新 UI 下拉列表
  pickPath(){
    const sel = document.getElementById("pathListSelect");
    if (!sel){
      console.warn('pathListSelect element not found');
      return;
    }
    console.log('pathListSelect found:', sel);
    
    sel.innerHTML = "";
    for (const info of this.pathLines) {
      const opt = document.createElement("option");
      opt.value = String(info.pathLineNum);
      opt.text = `路径 ${info.pathLineNum} 长度 ${info.pathLineLength.toFixed(2)} \n
                  g = ${info.pathLineCostg} h = ${info.pathLineCosth}`;

      opt.style.backgroundColor = info.pathLineColorCss;
      opt.style.paddingLeft = '20px';  // 留出空间给颜色条
      opt.style.whiteSpace = 'nowrap'; // 确保文字不换行
      
      sel.appendChild(opt);
    }

    const showBtn = document.getElementById("pathShowBtn");
    const hideBtn = document.getElementById("pathHideBtn");
    if (showBtn) {
      // 点击“显示”：除了显示对应路径实体外，同时把选中的路径传给 RoughAnalysis 绘制粗糙度曲线
      showBtn.onclick = () => {
        const selected = Array.from(sel.selectedOptions).map(o => o.value);
        // 先按原有逻辑显示路径实体
        this._applyPathSelection(selected, true);
      };
    }
    if (hideBtn) {
      hideBtn.onclick = () => {
        const selected = Array.from(sel.selectedOptions).map(o => o.value);
        this._applyPathSelection(selected, false);
      };
    }

    // onchange 行为：仅显示选中，未选隐藏；无选中则显示全部
    sel.onchange = () => {
      // 仅用于调试/提示，不修改实体可见性
      console.log('path selection changed:', Array.from(sel.selectedOptions).map(o => o.value));
    };
  }

  // 内部：设置选中路径显示/隐藏
  _applyPathSelection(selectedArray, visible) {
    const selSet = new Set(selectedArray.map(String));
    for (const info of this.pathLines) {
      if (selSet.has(String(info.pathLineNum))) {
        if (info.pathLineEntity) info.pathLineEntity.show = visible;
        (info.pathPointEntities || []).forEach(e => { if (e) e.show = visible; });
      }
    }
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
          moveCost = this.GetCost_CarWeightCost_BaseV(neighborNode, currentNode).totalT;
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
    distance = distance || 0.05; //默认0.05km精度,yf师兄
    this.distance = distance * 1000;// 转换成米m
    let width = distance * 200 > 35 ? 35 : distance * 200;
    this.arrowWidth = width < 15 ? 15 : width;
    const $this = this;
    const viewer = this.viewer;
    console.log(config);
    $this.config = config;

    CreatePolygonOnGround(
      viewer,
      [],
      {
        color: Cesium.Color.RED.withAlpha(0.1),
        outlineColor: Cesium.Color.YELLOW,
        outlineWidth: 2,
      },
      function (polygon) {
        if(Cesium.defined(polygon)){
          if (!polygon.pottingPoint) return;
          let degrees = $this.Cartesian3ListToWGS84(polygon.pottingPoint);
          viewer.entities.remove(polygon);
          let boundary = [];
          let minX = 10000,
            minY = 10000,
            maxX = -10000,
            maxY = -1000;
          for (let index = 0; index < degrees.length; index++) {
            const element = degrees[index];
            const x = element.lng;
            const y = element.lat;
            boundary.push([x, y]);
            minX = x < minX ? x : minX;
            minY = y < minY ? y : minY;
            maxX = x > maxX ? x : maxX;
            maxY = y > maxY ? y : maxY;
          }
          boundary.push(boundary[0]);
          let bbox = [minX, minY, maxX, maxY];console.log('bbox',bbox);


          var polygonBBOX = new Cesium.Entity({
            polygon: {
              hierarchy: Cesium.Cartesian3.fromDegreesArray([
                  minX, minY, 
                  minX, maxY, 
                  maxX, maxY, 
                  maxX, minY, 
              ]), //参数为四个角点坐标
              material: Cesium.Color.BLUE.withAlpha(0.1)
            },
          });
          viewer.entities.add(polygonBBOX);


          let mask = turf.polygon([boundary]);console.log('mask',mask);       
          let gridSquare = turf.squareGrid(bbox, distance, { mask: mask });//console.log('gridSquare',gridSquare);
          
          $this.createEllipse(gridSquare);
        }  
        return;
      }
    );
  }
  // 等分切分网格，切分成一个num*num的网格（网格数量相同，但长度不同）
  createNew4Num(num, config) {
    const $this = this;
    const viewer = this.viewer;
    console.log(config);
    $this.config = config;

    // 绘制多边形区域
    CreatePolygonOnGround(
      viewer,
      [],
      {
        color: Cesium.Color.RED.withAlpha(0.1), //绘制多边形区域内部的颜色和透明度
        outlineColor: Cesium.Color.YELLOW,
        outlineWidth: 2,
      },
      function (polygon) {
        console.time("从头到尾所花时间");

        // 获取绘制的多边形顶点并转换为地理坐标
        let degrees = $this.Cartesian3ListToWGS84(polygon.pottingPoint);
        viewer.entities.remove(polygon);
        let boundary = [];
        let minX = 10000,
          minY = 10000,
          maxX = -10000,
          maxY = -1000;
        for (let index = 0; index < degrees.length; index++) {
          const element = degrees[index];
          const x = element.lng;
          const y = element.lat;
          boundary.push([x, y]);
          minX = x < minX ? x : minX;
          minY = y < minY ? y : minY;
          maxX = x > maxX ? x : maxX;
          maxY = y > maxY ? y : maxY;
        }
        boundary.push(boundary[0]);
        // let bbox = [minX, minY, maxX, maxY];
        let a = maxX - minX;
        let b = maxY - minY;
        b = b > a ? b : a;
        const step = b / num;
        let width = step * 2000 > 35 ? 35 : step * 2000;
        $this.arrowWidth = width < 15 ? 15 : width;
        console.time("分割网格所需时间");

        let mask = turf.polygon([boundary]);

        // 计算最大深度 test
        const MAX_DEPTH = Math.ceil(Math.log2(num)); // 根据目标网格数计算深度
        const results = [];
        const maskBbox = turf.bbox(mask);
        // 4. 网格生成函数（保持步长精度）
        const generateStepGrid = (bbox) => {
          const [minX, minY, maxX, maxY] = bbox;
          const grids = [];

          for (let x = minX; x < maxX; x += step) {
            for (let y = minY; y < maxY; y += step) {
              const xNext = Math.min(x + step, maxX);
              const yNext = Math.min(y + step, maxY);
              grids.push([x, y, xNext, yNext]);
            }
          }

          return grids;
          const grid = turf.squareGrid(bbox, step, { units: "degrees" });
          return grid.features.map((f) => turf.bbox(f));
        };

        const stopThreshold = step * 10; // 停止分割阈值

        const processNode = (node) => {
          const cellPoly = turf.bboxPolygon(node.bbox);

          // 情形1：完全包含
          if (turf.booleanWithin(cellPoly, mask)) {
            results.push(...generateStepGrid(node.bbox));
            return;
          }

          // 情形2：完全不相交
          if (!turf.intersect(cellPoly, mask)) return;

          // 情形3：部分相交时的处理
          const [minX, minY, maxX, maxY] = node.bbox;
          const width = maxX - minX;
          const height = maxY - minY;

          // 终止条件：当节点尺寸小于等于阈值时
          if (width <= stopThreshold || height <= stopThreshold) {
            generateStepGrid(node.bbox).forEach((cellBbox) => {
              const cell = turf.bboxPolygon(cellBbox);
              if (turf.intersect(cell, mask)) {
                results.push(cellBbox);
              }
            });
            return;
          }

          // 继续分割四叉树
          node.subdivide();
          node.children.forEach(processNode);
        };

        // 6. 从根节点开始处理
        const root = new QuadTreeNode(maskBbox);
        processNode(root);

        // 7. 结果可视化
        console.time("生成网格");
        console.log("网格数量：", results.length);
        const grid = turf.featureCollection(
          results.map((bbox) => turf.bboxPolygon(bbox))
        );
        console.timeEnd("生成网格");
        //测试

        // // 3. 生成原始网格（不带mask）
        // console.time("生成原始网格所需时间");
        // // const grid = turf.squareGrid(bbox, step, { units: "degrees" });
        // console.timeEnd("生成原始网格所需时间");
        // // 4. 通过R树快速过滤网格
        // console.time("R树过滤时间");

        // console.timeEnd("R树过滤时间");

        // 5. 创建最终网格
        // grid.features = filteredFeatures;
        console.timeEnd("分割网格所需时间");
        $this.createEllipse(grid);
      }
    );
  }
  





  //获取对应坐标地形高度
  createEllipse(gridSquare) {
    let boxResults = []; //所有采样点的集合，存放地形高度提取位置（坐标），用于cesium.sampleTerrain(terrainProvider, level, position)函数最后的position参数

    for (let index = 0; index < gridSquare.features.length; index++) {
      const feature = gridSquare.features[index];
      const coordinates = feature.geometry.coordinates[0];
      const centerdegree = [
        (coordinates[0][0] + coordinates[2][0]) / 2,
        (coordinates[0][1] + coordinates[2][1]) / 2,
      ]; //网格中心点坐标
      let centerCartographic = Cesium.Cartographic.fromDegrees(
        centerdegree[0],
        centerdegree[1]
      );
      boxResults.push(centerCartographic);
      for (let i = 0; i < coordinates.length; i++) {
        const coord = coordinates[i];
        let cartographic = Cesium.Cartographic.fromDegrees(coord[0], coord[1]);
        boxResults.push(cartographic);
        const coord1 = coordinates[i + 1];
        if (coord1) {
          let newCoord = [
            (coord[0] + coord1[0]) / 2,
            (coord[1] + coord1[1]) / 2,
          ];
          let newCartographic = Cesium.Cartographic.fromDegrees(
            newCoord[0],
            newCoord[1]
          );
          boxResults.push(newCartographic);
        }
      }
    }
    // console.log(boxResults);
    //计算当前层级  （用于优化绘制速度？）
    function calculateValue(number) {
      // 如果传入的数字大于等于27326097，则直接返回0
      if (number >= 27326097) {
        return 0;
      }

      // 初始化阈值和结果
      var threshold = 28000000;
      var result = 4;

      // 循环判断传入的数字的范围
      while (number < threshold) {
        result++;
        threshold /= 2;
        // // 当结果大于等于15时，返回16
        // if (result >= 15) {
        //   return 16;
        // }
      }

      return result;
    }

    console.time("获取高程点所需时间");

// CCC注释掉的一段，放在文件末尾

    Cesium.sampleTerrain(
      this.viewer.scene.terrainProvider,
      13,
      boxResults
    ).then((updatePositions) => {
      let arrr = [];
      //ellipseResults二维数组，表示每个分割格子的采样点集合
      this.ellipseResults = updatePositions.reduce(function (
        pre,
        item,
        index,
        updatePositions
      ) {
        var begin = index * 10;
        var end = begin + 10;
        var res = updatePositions.slice(begin, end);
        if (res.length != 0) {
          arrr[index] = res;
        }
        return arrr;
      },
      []);
      console.timeEnd("获取高程点所需时间");
      //console.log("ellipseResults", this.ellipseResults);

      this.calculateSlope();
    });
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

    return Math.sqrt(dx * dx + dy * dy);
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
  FindPath_AStar(startPoint, endPoint){
    var startPoint = startPoint || [];
    var endPoint = endPoint || [];
    var d1 = []; //起点距最近网格点两点距离
    var d2 = []; //终点距各个网格点两点距离（遍历）
    let startx = -1;
    let starty = -1;
    let endx = -1;
    let endy = -1;
    this.pathPoints[this.pathLineNum] = []; //途径点(包含起点和终点)用于绘制
    let openList = [];
    let closeList = new Set();
    let nodeInfoMap = new Map(); //节点信息

    const startstartPoint  = startPoint; //绘制非网格中心点最终点到路径
    const endendPoint  = endPoint; //绘制非网格中心点最终点到路径
    const startCarto = Cesium.Cartographic.fromCartesian(startstartPoint);// 笛卡尔(Cartesian)转WGS84(Cartographic)
    const endCarto = Cesium.Cartographic.fromCartesian(endendPoint);   

    for(let i = 0; i < this.slopeCostGrid.length; i++){
      for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
        if(this.slopeCostGrid[i][j].length != 0){

          // 找到距离选取的起点和终点最近的网格点，作为寻路起点和终点
          d2 = Cesium.Cartesian3.distance(this.slopeCostGrid[i][j].Cartesian, endPoint);
          d1 = Cesium.Cartesian3.distance(this.slopeCostGrid[i][j].Cartesian, startPoint);
          if (d1 < this.distance * Math.sqrt(2) / 2 && startx == -1 && starty == -1) {
            startPoint = {x: i, y: j, z: this.slopeCostGrid[i][j].degreeCoordinate[2], Cartesian3Grid: this.slopeCostGrid[i][j].Cartesian};
            startx = i;
            starty = j;
          }
          if (d2 < this.distance * Math.sqrt(2) / 2 && endx == -1 && endy == -1) {
            endPoint = {x: i, y: j, z: this.slopeCostGrid[i][j].degreeCoordinate[2], Cartesian3Grid: this.slopeCostGrid[i][j].Cartesian};
            endx = i;
            endy = j;
          }

        }   
      }     
    }
    console.log('startPoint', startPoint, 'endPoint', endPoint);

    // 若启用潜力场寻路，优先使用全局 cost-to-go 场并按 potential 贪心搜索
    if (this.usePotentialFieldFlag && startx !== -1 && endx !== -1) {
      try {
        this.potentialField = this.computePotentialField({x: endx, y: endy});console.log('potentialField', this.potentialField);

      } catch (e) {
        console.error('预计算 potentialField 失败，回退到几何启发式', e);
        console.log('this.potentialField', this.potentialField);
        this.potentialField = null;
      }
    }

    
    const startTime = performance.now();
    openList = [new findPathNode(startPoint.x, startPoint.y, startPoint.z, startPoint.Cartesian3Grid)];
    // 从OPEN列表中取出总代价最小的节点作为当前节点
    while (openList.length > 0) { //判断当前OPEN列表是否为空
        // 找到f值最小的节点，作为当前节点current
        let currentIndex = 0;
        for (let i = 1; i < openList.length; i++) {
          //console.log('openList[i].f', openList[i].f, 'openList[currentIndex].f', openList[currentIndex].f);
          //console.log('openList[i].f < 10000', openList[i].f < 10000, 'openList[currentIndex].f < 10000', openList[currentIndex].f < 10000);
          if (openList[i].f > 0
              && openList[i].f < openList[currentIndex].f 
              && openList[i].f < 10000
              && openList[currentIndex].f < 10000
              && Number.isFinite(openList[i].f) 
              && openList[i].h < openList[currentIndex].h){       
            currentIndex = i;
          }
        }
        const current = openList[currentIndex];
        const currentKey = `${current.x},${current.y}`;

        // 检查是否到达终点（当前节点是否为终点）
        if (current.x === endPoint.x && current.y === endPoint.y) {
            // 回溯路径
            this.pathPoints[this.pathLineNum] = [];
            let temp = current;
            while (temp) {
              this.pathPoints[this.pathLineNum].unshift({
                                  x: temp.x,
                                  y: temp.y,
                                  z: temp.z,
                                  //slopeCost: temp.slopeCost,
                                  slope: temp.slope,
                                  v: temp.v,
                                  turnAngle: temp.turnAngle,
                                  g: temp.g,
                                  h: temp.h,
                                  f: temp.f,
                                  Cartesian3Grid: temp.Cartesian3Grid,
              });
              temp = temp.parent;// 通过父节点parent回溯路径
            }

            // 把每个节点的转角“往前移一位”：node.turnAngle = nextNode.turnAngle
            if(this.equTimeCostV){
              
              for (let i = 0; i < this.pathPoints[this.pathLineNum].length - 1; i++) {
                const node = this.pathPoints[this.pathLineNum][i];
                const next = this.pathPoints[this.pathLineNum][i + 1];
                // console.log('node', node, 'next', next);
                // 仅当 next 有候选角时回填到 node（即 node 离开时的真实转向）
                if (!Number.isFinite(node.turnAngle)) {
                  node.turnAngle = next.turnAngle;
                  // console.log('node.turnAngle', node.turnAngle, 'next.turnAngle', next.turnAngle);
                } 
              }
            }
            
            const pathPoint1 = this.pathPoints[this.pathLineNum][0];//路径点1
            const pathPoint2 = this.pathPoints[this.pathLineNum][1];//路径点2
            const pathPoint3 = this.pathPoints[this.pathLineNum][this.pathPoints[this.pathLineNum].length-1];//路径点倒数1
            const pathPoint4 = this.pathPoints[this.pathLineNum][this.pathPoints[this.pathLineNum].length-2];//路径点倒数2
            const pathPoint1Carto = Cesium.Cartographic.fromCartesian(pathPoint1.Cartesian3Grid);//路径点1的经纬度
            const pathPoint2Carto = Cesium.Cartographic.fromCartesian(pathPoint2.Cartesian3Grid);//路径点2的经纬度
            const pathPoint3Carto = Cesium.Cartographic.fromCartesian(pathPoint3.Cartesian3Grid);//路径点倒数1的经纬度
            const pathPoint4Carto = Cesium.Cartographic.fromCartesian(pathPoint4.Cartesian3Grid);//路径点倒数2的经纬度
            var S1direction;//起点路径点1方向
            var S2direction;//起点路径点2方向
            var E1direction;//终点路径点1方向
            var E2direction;//终点路径点2方向
            /******/
            if(startCarto.longitude < pathPoint1Carto.longitude && startCarto.latitude < pathPoint1Carto.latitude){
              S1direction = 'NE';
            }
            else if(startCarto.longitude < pathPoint1Carto.longitude && startCarto.latitude > pathPoint1Carto.latitude){
              S1direction = 'SE';
            }
            else if(startCarto.longitude > pathPoint1Carto.longitude && startCarto.latitude < pathPoint1Carto.latitude){
              S1direction = 'NW';
            }
            else if(startCarto.longitude > pathPoint1Carto.longitude && startCarto.latitude > pathPoint1Carto.latitude){
              S1direction = 'SW';
            }
            /******/
            if(startCarto.longitude < pathPoint2Carto.longitude && startCarto.latitude < pathPoint2Carto.latitude){
              S2direction = 'NE';
            }
            else if(startCarto.longitude < pathPoint2Carto.longitude && startCarto.latitude > pathPoint2Carto.latitude){
              S2direction = 'SE';
            }
            else if(startCarto.longitude > pathPoint2Carto.longitude && startCarto.latitude < pathPoint2Carto.latitude){
              S2direction = 'NW';
            }
            else if(startCarto.longitude > pathPoint2Carto.longitude && startCarto.latitude > pathPoint2Carto.latitude){
              S2direction = 'SW';
            }
            /******/
            if(endCarto.longitude < pathPoint3Carto.longitude && endCarto.latitude < pathPoint3Carto.latitude){
              E1direction = 'NE';
            }
            else if(endCarto.longitude < pathPoint3Carto.longitude && endCarto.latitude > pathPoint3Carto.latitude){
              E1direction = 'SE';
            }
            else if(endCarto.longitude > pathPoint3Carto.longitude && endCarto.latitude < pathPoint3Carto.latitude){
              E1direction = 'NW';
            }
            else if(endCarto.longitude > pathPoint3Carto.longitude && endCarto.latitude > pathPoint3Carto.latitude){
              E1direction = 'SW';
            }
            /******/
            if(endCarto.longitude < pathPoint4Carto.longitude && endCarto.latitude < pathPoint4Carto.latitude){
              E2direction = 'NE';
            }
            else if(endCarto.longitude < pathPoint4Carto.longitude && endCarto.latitude > pathPoint4Carto.latitude){
              E2direction = 'SE';
            }
            else if(endCarto.longitude > pathPoint4Carto.longitude && endCarto.latitude < pathPoint4Carto.latitude){
              E2direction = 'NW';
            }
            else if(endCarto.longitude > pathPoint4Carto.longitude && endCarto.latitude > pathPoint4Carto.latitude){
              E2direction = 'SW';
            }
            /******/
            if(S1direction != S2direction){
              this.pathPoints[this.pathLineNum].shift();//点击点的方向和路径点1、2的方向对比判断
            }
            if(E1direction != E2direction){
              this.pathPoints[this.pathLineNum].pop();//点击点的方向和路径点3、4的方向对比判断
            }
            this.pathPoints[this.pathLineNum].push({x: 0, y: 0, z: 0, Cartesian3Grid: endendPoint});
            this.pathPoints[this.pathLineNum].unshift({x: 0, y: 0, z: 0, Cartesian3Grid: startstartPoint});
            console.log('this.pathPoints',this.pathPoints);

            const endTime = performance.now();
            console.log('找到路径！路径长度：' + 
                  this.pathPoints[this.pathLineNum].length + '，搜索时间：' + 
                  Math.round(endTime - startTime) + 'ms，搜索节点数：' + 
                  closeList.size);
        
            // 绘制路径
            this.DrawPath();
        
            return;
        }

        // 若当前节点不是终点，将当前处理的节点从OPEN列表移动到CLOSE列表
        openList.splice(currentIndex, 1);// 从数组下标为currentIndex开始删除一个元素
        closeList.add(currentKey);// 在closeList中添加当前节点

        // 检查邻居
        const neighbors = this.GetNeighbors(current);
        for (let neighbor of neighbors) {
            const key = `${neighbor.x},${neighbor.y}`;
            
            if (closeList.has(key)) continue;// 检查该邻居是否在CLOSE列表中
            let g;
            let h;
            let f;

            if(this.equTimeCostV){ // 固定速度_等效时间计算代价
              // 计算转角（度），并保存到节点
              const turnAngleDeg = this.computeTurnAngle(current.parent, current, neighbor);
              neighbor.turnAngle = turnAngleDeg; // 根据邻域即时计算的转角，不是最终路径的转角, 仅用于计算g值
              const{ slopeT: slopeT, turnT: turnT, Vc: Vn } = this.GetCost_CarWeightCost_BaseV(current, neighbor);
              neighbor.v = Vn; // 保存下一节点速度，供后续计算使用

              g = current.g + slopeT + turnT;
              if(this.potentialField && this.potentialField[neighbor.x] && Number.isFinite(this.potentialField[neighbor.x][neighbor.y])){
                h = this.potentialField[neighbor.x][neighbor.y];
              }
              h = this.Heuristic_CarWeightCost_BaseV(neighbor, endPoint);
              f = this.gWeight * g + this.hWeight * h;
            }
            else if(this.equTimeCostDragF){// 固定牵引力_等效时间计算代价
              // 计算转角（度），并保存到节点
              const turnAngleDeg = this.computeTurnAngle(current.parent, current, neighbor);
              neighbor.turnAngle = turnAngleDeg; // 根据邻域即时计算的转角，不是最终路径的转角, 仅用于计算g值
              const{ slopeT: slopeT, turnT: turnT, Vc: Vn } = this.GetCost_CarWeightCost_BaseDragF(current, neighbor);
              neighbor.v = Vn; // 保存下一节点速度，供后续计算使用

              g = current.g + slopeT + turnT;
              // if(this.potentialField && this.potentialField[neighbor.x] && Number.isFinite(this.potentialField[neighbor.x][neighbor.y])){
              //   h = this.potentialField[neighbor.x][neighbor.y];
              // } // 暂不使用反向搜索
              h = this.Heuristic_CarWeightCost_BaseDragF(neighbor, endPoint);
              f = this.gWeight * g + this.hWeight * h;
            }
            else if(this.useAHPMethod){ // AHP方法计算代价(最短时间，时间代价)
              const turnAngleDeg = this.computeTurnAngle(current.parent, current, neighbor);
              const delta_g = this.AHP_GetCost(current, neighbor);
              g = current.g + delta_g;
              if(turnAngleDeg == 45 || turnAngleDeg == 135) {
                g = g + delta_g * 0.414;// 对角线距离增大1.414倍
              }else if(turnAngleDeg == 90) {
                g = g + delta_g * 0.828;// 水平距离增大1.828倍
              }
              h = this.AHP_Heuristic(neighbor, endPoint, startx, starty, endx, endy) / 25;// 曼哈顿距离 / 最大速度 = 最小时间
              f = this.gWeight * g + this.hWeight * h;
            }
            else{ // 原始计算代价
              // 原始： const g = current.g + this.GetCost(current, neighbor); 新增转向惩罚：使用 current.parent 来计算转向惩罚（首次无惩罚）
              const baseMoveCost = this.GetCost(current, neighbor);
              const turnPen = this.computeTurnAngle(current.parent, current, neighbor) / 180 * 20;// 2是转向惩罚权重，可调
              g = current.g + baseMoveCost + turnPen;
              //const h = this.Heuristic(neighbor, {x: endPoint.x, y: endPoint.y}); 
              // 优先使用预计算的潜力场作为启发式（更贴近代价）
              if (this.potentialField && this.potentialField[neighbor.x] && Number.isFinite(this.potentialField[neighbor.x][neighbor.y])) {
                h = this.potentialField[neighbor.x][neighbor.y];// 使用预计算的最小代价（从 neighbor 到目标的 cost-to-go）
              } else {
                h = this.Heuristic(neighbor, endPoint);// 回退：使用原始几何启发式
              } 
              f = this.gWeight * g + this.hWeight * h;// 立即计算 f 并过滤异常/过大代价的节点，避免它们进入 openList
              // 参数：可调阈值，用于对f做约束，视你的数据量级调整（示例使用 1e6）
           }

            const MAX_ACCEPTABLE_F = 1e5;
            // 如果 f 非有限或超过阈值，跳过该邻居(等同于不可通行),不将其加入搜索列表openlist
            if (!Number.isFinite(f) || f > MAX_ACCEPTABLE_F) continue;

            // 存储节点信息
            nodeInfoMap.set(key, {g: g, h: h, f: f});
            // 检查是否在OPEN列表中
            let inOpen = false;
            for (let node of openList) {
                if (node.x === neighbor.x && node.y === neighbor.y) {
                    inOpen = true;
                    if (g < node.g) {
                        node.g = g;
                        node.f = f;
                        node.parent = current;
                        nodeInfoMap.set(key, {g: g, h: h, f: f});
                    }
                    break;
                }
            }

            if (!inOpen) {
                neighbor.g = g;
                neighbor.h = h;
                neighbor.f = f;
                neighbor.parent = current;
                openList.push(neighbor);// 将当前已处理路径节点的邻居节点都添加到openList
            }
        }
    }

    alert('未找到可行路径！');

    console.log('pathPoint', this.pathPoints);
    console.log('slopeCostGrid', this.slopeCostGrid);
  }

  //RRT算法路径规划
  FindPath_RRT(){
    const rrt = new RRT_PathPlanner(window.SlopeAnalysis, {
      maxIterations: 5000,  // 最大迭代次数
      stepSize: 2,          // 扩展步长
      goalThreshold: 1.5,   // 到达目标阈值
      maxSlopeCost: 10,     // 最大坡度代价
      biasToGoal: 0.1       // 10%朝目标采样
    });
    const path = rrt.findPath(this.keepStartPoint, this.keepEndPoint);
    if(path){
      this.pathPoints[this.pathLineNum] = path;
      this.DrawPath();
    }
    return;
  }

  //获取选择点（起点、终点）的坡度（颜色）和坐标信息
  GetSlopePath() {
    if(this.slopeCostGrid.length != 0){
      let $this = this;
      let flag = 0;// 取点标志位
      $this.keepStartPoint = null;
      $this.keepEndPoint = null;

      $this.handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      $this.handler.setInputAction(function (movement) {
        var ray = viewer.camera.getPickRay(movement.position);
        var cartesian = viewer.scene.globe.pick(ray, viewer.scene);
        
        if (cartesian) {
          switch (flag) {
            case 0:
              console.log("已输入第一个点");
              $this.keepStartPoint = cartesian;
              const StartEntity = new Cesium.Entity({
                id: "slope_path_起点",
                position: cartesian,
                point: {
                  pixelSize: 8,
                  color: Cesium.Color.RED,
                  disableDepthTest: Number.POSITIVE_INFINITY,
                  heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                },
              });
              viewer.entities.add(StartEntity);
              StartEntity.isPath = true;
              flag = 1;
              break;

            case 1:
              console.log("已输入第二个点");
              $this.keepEndPoint = cartesian;
              const EndEntity = new Cesium.Entity({
                id: "slope_path_终点",
                position: cartesian,
                point: {
                  pixelSize: 8,
                  color: Cesium.Color.RED,
                  disableDepthTest: Number.POSITIVE_INFINITY,
                  heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                },
              });
              viewer.entities.add(EndEntity);
              EndEntity.isPath = true;
              flag = -1;
              break;
          }
          var cartographic = Cesium.Cartographic.fromCartesian(cartesian); //将笛卡尔坐标转换为地理坐标
          var longitudeDegree = Cesium.Math.toDegrees(cartographic.longitude);
          var latitudeDegree = Cesium.Math.toDegrees(cartographic.latitude);

          console.log("lng:" + longitudeDegree + ",lat:" + latitudeDegree);
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

      $this.handler.setInputAction(function () { 
        if (flag == -1) { 
          console.log('startPoint',$this.keepStartPoint);
          console.log('endPoint',$this.keepEndPoint);
          if($this.useOriginRRTFlag){
            $this.FindPath_RRT();
          }
          else{
            $this.FindPath_AStar($this.keepStartPoint, $this.keepEndPoint);
          }
        }
        $this.handler.destroy();
      }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
    }
    else{
      alert('请先计算区域坡度！');
    } 
  }

  // 计算通行代价 并 绘制通行代价图
  DrawCostMap(){
    if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) {
      alert('请先计算区域坡度！');
      return;
    }
    let costValArry = [];// 坡度分段代价值数组
    const rows = this.slopeCostGrid.length;       // 行数（Y方向）
    const cols = this.slopeCostGrid[0].length;    // 列数（X方向）
    let slope = 999999;
    let speed = 0; // km/h
    // DEM[i][j] 存储格子 [i,j] 的高程值（单位：米）
    const DEM = new Array(rows);// DEM[i][j] = this.slopeCostGrid[i][j].slopeCost为格子通行代价
    for (let i = 0; i < rows; i++) {
      DEM[i] = new Array(cols).fill(0); 
    }// 初始化DEM[i][j]为 0

    /*// 原始方法
    costValArry = [
      10 * 1,
      (10 * (Math.pow(0.02 * (5 - 5), 3) - 3.183 * 5 + 41.1103) / 25.18),
      (10 * (Math.pow(0.02 * (9 - 5), 3) - 3.183 * 9 + 41.1103) / 25.18),
      (10 * ((0.45 * Math.pow(22 - 9, 3) + 0.11 * Math.pow(9 - 9, 3)) / 78 + 0.653 * 9 - 4.905) / 25.18),
      (10 * ((0.45 * Math.pow(22 - 22, 3) + 0.11 * Math.pow(9 - 22, 3)) / 78 + 0.653 * 22 - 4.905) / 25.18),
      (10 * ((0.11 * Math.pow(22 - 35, 3)) / 78 - 0.728 * 22 + 25.490) / 25.18),
      (10 * ((0.11 * Math.pow(35 - 35, 3)) / 78 - 0.728 * 35 + 25.490) / 25.18),
      1e-6,
    ];*/

    /* // 真实数据驱动的层次分析法
    let Vmax = 20/3.6;
    const S = this.distance;
    this.weights = [0.0573, 0.0748, 0.1024, 0.1613];// 坡度各级别权重
    const T = S / Vmax;// 基础时间代价

    let result = this.AHPanalysistest().weights_eigen;
    console.log('result',result);// AHP权重输出
    const AHPcost = result.map(function(x) { return x * T; });console.log('AHPcost',AHPcost);
    costValArry = [
      AHPcost[0],
      AHPcost[1],
      AHPcost[2],
      AHPcost[3],
      999999,
    ];*/

    // 坡度分段边界时间代价（用于颜色分级）
    let costValArray = [];
    // 第1段: slope <= 6° -> 速度15-25km/h -> 时间7.2-12.0s (绿色)
    costValArray[0] = this.distance / (15 / 3.6);  // 12.0s
    // 第2段: 6° < slope <= 10° -> 速度12-15km/h -> 时间12.0-15.0s (浅绿)
    costValArray[1] = this.distance / (12 / 3.6);  // 15.0s
    // 第3段: 10° < slope <= 15° -> 速度8-12km/h -> 时间15.0-22.5s (黄色)
    costValArray[2] = this.distance / (8 / 3.6);   // 22.5s
    // 第4段: 15° < slope <= 20° -> 速度5-8km/h -> 时间22.5-36.0s (橙色)
    costValArray[3] = this.distance / (5 / 3.6);   // 36.0s
    // 第5段: 20° < slope <= 30° -> 速度0-5km/h -> 时间36.0s-∞ (深橙/浅红)
    costValArray[4] = 999999;  // 30°以上不可通行

    for (let i = 0; i < this.slopeCostGrid.length; i++) {
      for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
        if (this.slopeCostGrid[i][j].length !== 0) {
          // 转换坡度距离为代价
          slope = this.slopeCostGrid[i][j].slope;

          //论文：地形通行性能的研究_张文诗
          /*if (slope <= 5) {
            this.slopeCostGrid[i][j].slopeCost = 10 * 1;// console.log(1111);
          }
          else if (slope > 5 && slope <= 9) {
            this.slopeCostGrid[i][j].slopeCost = (10 * (Math.pow(0.02 * (slope - 5), 3) - 3.183 * slope + 41.1103) / 25.18);// console.log(2222);
          }
          else if (slope > 9 && slope <= 22) {
            this.slopeCostGrid[i][j].slopeCost = (10 * ((0.45 * Math.pow(22 - slope, 3) + 0.11 * Math.pow(9 - slope, 3)) / 78 + 0.653 * slope - 4.905) / 25.18);// console.log(3333);
          }
          else if (slope > 22 && slope <= 35) {
            this.slopeCostGrid[i][j].slopeCost = (10 * ((0.11 * Math.pow(slope - 35, 3)) / 78 - 0.728 * slope + 25.490) / 25.18);// console.log(4444);
          }
          else {//slope > 35 
            this.slopeCostGrid[i][j].slopeCost = 1e-6;// console.log(5555);
          }*/

          //AHP权重叠加计算通行代价（越野汽车）
          /*if (slope <= 6) {
            this.slopeCostGrid[i][j].slopeCost = AHPcost[0]*slope;
          }
          else if (slope > 6 && slope <= 10) {
            this.slopeCostGrid[i][j].slopeCost = AHPcost[1]*slope;
          }
          else if (slope > 10 && slope <= 15) {
            this.slopeCostGrid[i][j].slopeCost = AHPcost[2]*slope;
          }
          else if (slope > 15 && slope <= 20) {
            this.slopeCostGrid[i][j].slopeCost = AHPcost[3]*slope;
          }
          else {//slope > 20 
            this.slopeCostGrid[i][j].slopeCost = 999999;
          }*/
           
          // 根据表3线性插值计算速度
          if (slope <= 0) {
            speed = 25;
          } else if (slope <= 3) {
            // 0-3°: 25 -> 20 km/h
            speed = 25 - (25 - 20) * (slope - 0) / (3 - 0);
          } else if (slope <= 6) {
            // 3-6°: 20 -> 15 km/h
            speed = 20 - (20 - 15) * (slope - 3) / (6 - 3);
          } else if (slope <= 10) {
            // 6-10°: 15 -> 12 km/h
            speed = 15 - (15 - 12) * (slope - 6) / (10 - 6);
          } else if (slope <= 15) {
            // 10-15°: 12 -> 8 km/h
            speed = 12 - (12 - 8) * (slope - 10) / (15 - 10);
          } else if (slope <= 20) {
            // 15-20°: 8 -> 5 km/h
            speed = 8 - (8 - 5) * (slope - 15) / (20 - 15);
          } else if (slope <= 30) {
            // 20-30°: 5 -> 0 km/h（仍可通行，但速度很慢）
            speed = 5 - (5 - 0) * (slope - 20) / (30 - 20);
          } else {
            // slope > 30°: 完全不可通行
            speed = 0;
          }

          // 计算时间代价：时间 = 距离 / 速度
          if (speed > 0.1) { // 速度大于0.1km/h才认为可通行
            this.slopeCostGrid[i][j].slopeCost = this.distance / (speed / 3.6);
          } else {
            this.slopeCostGrid[i][j].slopeCost = 999999; // 不可通行
          }

        }
      }
    }

    let slopeCostColorGrid = this.calculateCostColor(costValArry);// 代价映射颜色绘制代价图
    this.createCostInstance(slopeCostColorGrid);// 绘制代价栅格，默认不显示
    if (this.costPolygons && this.costPolygons.length >= 2) {
      this.costPolygons.forEach((element) => {
        element.primitive.show = false;
      });
    }
    console.log('slopePolygons', this.slopePolygons);
    return;
  }

  DrawPath() {
    // 绘制路径
    const CrossPoints = [];
    const pathPointEntities = [];

    for(let i = 0; i < this.pathPoints[this.pathLineNum].length; i++){
      CrossPoints.push(this.pathPoints[this.pathLineNum][i].Cartesian3Grid);
      const PathPoint = new Cesium.Entity({
        id: 'slope_path_point' + this.pathLineNum + i,
        position: this.pathPoints[this.pathLineNum][i].Cartesian3Grid,
        point: {
          pixelSize: 8,
          color: Cesium.Color.fromCssColorString('#fdfdfdff'),
          disableDepthTest: Number.POSITIVE_INFINITY,
          heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        }
      });
      pathPointEntities.push(PathPoint);
      this.viewer.entities.add(PathPoint);
      PathPoint.isPath = true;
    }

    const PathLine = new Cesium.Entity({
      id: 'slope_path_line' + this.pathLineNum,
      polyline: {
          positions: CrossPoints,
          width: 5,//边界线宽
          material: new Cesium.Color(this.pathLineNum*0.1, 1 - this.pathLineNum*0.3, this.pathLineNum*0.4, 1), // 边界线颜色
          clampToGround: true,
      }
    })
    viewer.entities.add(PathLine);
    PathLine.isPath = true;
    var css = new Cesium.Color(this.pathLineNum*0.1, 1 - this.pathLineNum*0.3, this.pathLineNum*0.4, 1).toCssHexString();

    const pathLineInfo = {
      pathPointEntities: pathPointEntities,
      pathLineEntity: PathLine,
      pathLineNum: this.pathLineNum,
      pathLineLength: this.pathPoints[this.pathLineNum].length,
      pathLineColor: PathLine.polyline.material.color,
      pathLineColorCss: css,
      pathLineCostg: this.gWeight,
      pathLineCosth: this.hWeight,
    };
    this.pathLineNum = (this.pathLineNum || 0) + 1;
    console.log('新增路径，当前 pathLines 长度=', this.pathLines.length, 'next pathLineNum=', this.pathLineNum);
    this.pathLines.push(pathLineInfo);
    try { this.pickPath(); } catch (e) { /* ignore */ }
    
    return;
  }

  // 绘制通行代价图
  createCostInstance(slopeCostColorGrid){
    let Instances = [];
    let positions = [];
    console.log('slopeCostColorGrid',slopeCostColorGrid);
    for (let i = 0; i < slopeCostColorGrid.length; i++) {
      Instances = [];//重置
      positions = [];//重置
      let color = 0;//重置
      if(slopeCostColorGrid[i].length > 0){
        color = Cesium.Color.fromCssColorString(slopeCostColorGrid[i][0].color);console.log('colorCesium',color);
      }
      for (let j = 0; j < slopeCostColorGrid[i].length && slopeCostColorGrid[i].length > 0; j++) {
        const Cost = slopeCostColorGrid[i][j].cost;// 代价值
        const polygonInstance = new Cesium.GeometryInstance({
          id: {
            type: "Cost",           // 类型标识，用于 openTip 判断
            name: '代价：',               // 名称：代价
            value: Cost,         // 实际的代价值
            index: i                       // 可选：实例索引
          }, 
          geometry: new Cesium.PolygonGeometry({
            polygonHierarchy: new Cesium.PolygonHierarchy(slopeCostColorGrid[i][j].gridSquare),
            height: 0,
            vertexFormat: Cesium.MaterialAppearance.VERTEX_FORMAT,
          }),
        });
        Instances.push(polygonInstance);
        positions.push(slopeCostColorGrid[i][j].gridSquare);
      }

      if (color !== 0) {
        //2 创建材质material，作用于外观appearance上
        const material = new Cesium.Material({
          fabric: {
            type: 'Color',
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
        //4 创建GroundPrimitive以实现贴地效果,使用GroundPrimitive创建贴地的面，作用于primitive上
        const primitive = new Cesium.GroundPrimitive({
          geometryInstances: Instances,
          appearance: appearance,
        });
        // 添加到场景
        viewer.scene.primitives.add(primitive);

        // 保存面信息
        const polygonInfo = {
          primitive: primitive,
          positions: positions,
          baseColor: color,
          alpha: color.alpha,
        };
        this.costPolygons.push(polygonInfo);
      }
    }
    
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
    } else if (config == 1) {
      this.aspectPolygons.push(polygonInfo);
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
    //ellipseResults是m x n个3 x 3网格区域
    //let ellipse = []; //ellipse是一个3 x 3网格，在此处记录的是网格内每个格子的高度
    let ColorType = []; //颜色代号0-9，用于颜色分组，相同颜色放在同数组
    let ColorByte = []; //颜色值，转为0-255表示的

    let aspectColor = []; //保存像元的 [颜色编号][颜色值]
    let slopeColor = [];
    let HeightRange = []; //用于计算真实高度范围，用于归一化高度
    let findLongitudeRange = [];//用于找经纬度最值
    let findLatitudeRange = [];

    //初始化坡度坡向颜色类型和对应位置数组
    for (let index = 0; index < 10; index++) {
      this.slopePosArray[index] = [];
      this.aspectPosArray[index] = [];
    }
    console.log(this.ellipseResults);
    //计算分辨率g，点的分布是[5,1,4,7,8,9,6,3,2,1]
    let g = Cesium.Cartesian3.distance(
      Cesium.Cartographic.toCartesian(this.ellipseResults[0][0]),
      Cesium.Cartographic.toCartesian(this.ellipseResults[0][2])
    );
    // console.log(g);
    console.time("计算时间");

    //对分割好的网格ellipseResults进行操作，对每个格子进行计算
    for (let index = 0; index < this.ellipseResults.length; index++) {

      //计算x方向变化率
      let positions = []; //将ellipse八方向内容转换为Cartesian格式
      let DEMheight = []; //存储分割网格的经纬高度用于绘制DEM (笛卡尔坐标系Cartesian)

      const ellipse = this.ellipseResults[index];
      for (let i = 1; i < ellipse.length - 1; i++) {
        positions.push(Cesium.Cartographic.toCartesian(ellipse[i]));
        DEMheight.push(Cesium.Cartographic.toCartesian(ellipse[i]));
      }

      let z1 = ellipse[1].height; //左下
      let z2 = ellipse[8].height; //下
      let z3 = ellipse[7].height; //右下
      let z4 = ellipse[2].height; //左
      let z5 = ellipse[0].height; //中心点
      let z6 = ellipse[6].height; //右
      let z7 = ellipse[3].height; //左上
      let z8 = ellipse[4].height; //上
      let z9 = ellipse[5].height; //右上

      let fx = (z7 - z1 + 2 * (z8 - z2) + z9 - z3) / (8 * g);
      let fy = (z3 - z1 + 2 * (z6 - z4) + z9 - z7) / (8 * g);

      function angleWithXAxis(x, y) {
        let angle = Math.atan2(y, x) * (180 / Math.PI);
        // 将角度限制在 0 到 360 度之间
        angle = (angle + 360) % 360;
        return angle;
      }
      this.curSlope = Math.atan(Math.sqrt(fx * fx + fy * fy)) * (180 / Math.PI);
      this.curAspect = angleWithXAxis(-fx, -fy);

      if (this.drawFlag) {
        let ColorInfo = [];
        //************坡度计算值curSlope与颜色*************** 
        ColorInfo = this.calculateSlopeColor(this.curSlope);
        ColorByte = Cesium.Color.fromCssColorString(ColorInfo[0]);// [0颜色值，1颜色代号]
        ColorType = ColorInfo[1];

        this.slopePosArray[ColorType].push([positions, this.curSlope]); //Cartesian格式
        slopeColor[ColorType] = [ColorByte]; //（颜色值）

        //************坡向计算值curAspect与颜色***************
        ColorInfo = this.calculateAspectColor(this.curAspect);
        ColorByte = Cesium.Color.fromCssColorString(ColorInfo[0]);// [0颜色值，1颜色代号]
        ColorType = ColorInfo[1];

        this.aspectPosArray[ColorType].push([positions, this.curAspect]); //Cartesian格式
        aspectColor[ColorType] = [ColorByte]; //（颜色值）

        //***********高度height与颜色*************** */
        this.heightPosArray.push(DEMheight);
        HeightRange.push(z5);
      }

      //*************坡度顺序数组*************** */
      let longitude = Cesium.Math.toDegrees(ellipse[0].longitude);
      let fixedLon = Math.abs(
        Math.floor(longitude * Math.pow(10, 13)) / Math.pow(10, 13).toFixed(13)
      ); //统一为13位小数
      findLongitudeRange.push(fixedLon);
      let latitude = Cesium.Math.toDegrees(ellipse[0].latitude);
      let fixedLat = Math.abs(
        Math.floor(latitude * Math.pow(10, 13)) / Math.pow(10, 13).toFixed(13)
      );
      findLatitudeRange.push(fixedLat);
      let height = ellipse[0].height;
      let degreeCoordinate = [longitude, latitude, height];
      // slopeCostArray存储格式：[中心点Cartesian坐标，坡度值，经纬高坐标，坡度代价值，单网格绘制9点数组，]
      //                        [0                 ,1     ,2         ,3         ,4               ,         ]
      /***********************************************************************
      this.slopeCostArray.push([
        Cesium.Cartographic.toCartesian(ellipse[0]), //中心点Cartesian坐标
        this.curSlope, //坡度值slope
        degreeCoordinate, //经纬高坐标
        [], //坡度代价值slopeCost
        positions, //单网格绘制9点数组
      ]); //只存中心点（数组形式）
      ************************************************************************/
      this.slopeCostArray.push({
        Cartesian: Cesium.Cartographic.toCartesian(ellipse[0]), // 中心点Cartesian坐标（原索引[0]）
        slope: this.curSlope,                                    // 坡度值（原索引[1]）
        degreeCoordinate: degreeCoordinate,                            // Cartographic经纬高坐标（原索引[2]）
        slopeCost: 0,                                           // 坡度代价值（原索引[3]，初始化为0而非空数组）
        gridSquare: positions                                     // 单网格绘制9点数组（原索引[4]）Cartesian格式
      });//键值对形式存储

      //this.slopePolygons.push(slopePolygonPrimitive);
      //this.slopeColor2 = Cesium.Color.fromCssColorString(slopeColor);
      //console.log('slopeColor2',this.slopeColor2);会一直重复

      // console.log('slopePolygons',this.slopePolygons);
      // console.log('aspectPolygons',this.aspectPolygons);

      //箭头线绘制，目前用不上2025.9.9
      // const startPoint = Cesium.Cartographic.toCartesian(ellipse[4]);
      // const heading = Cesium.Math.toRadians(this.curAspect);
      // const deltaX = g * Math.cos(heading);
      // const deltaY = g * Math.sin(heading);
      // const endPoint = new Cesium.Cartesian3(
      //   startPoint.x + deltaX,
      //   startPoint.y + deltaY,
      //   startPoint.z
      // );
      // const arrowInstance = this.createArrowInstance(
      //   endPoint,
      //   ellipse[0],
      //   this.curAspect
      // );
      // instances.push(arrowInstance);
      /* 根据config选择绘制箭头线还是坡度面
                let config = this.config
                // console.log(config);
                if (config) {
                  // console.log(config);
                  let curSlope = Math.sqrt(fx * fx + fy * fy);
                  curSlope = Math.atan(curSlope) * (180 / Math.PI)
                  let curColor = this.calculateSlopeColor(curSlope, 1);
                  const curPolygonInstance = this.createPolygonInsrance(ellipse, curColor);
                  polygonInstance.push(curPolygonInstance);
                } else {
          
                  let curAspect = angleWithXAxis(-fx, -fy)
                  let aspectColor = this.calculateAspectColor(curAspect, 1)
          
                  const curPolygonInstance2 = this.createPolygonInsrance(ellipse, aspectColor);
                  polygonInstance.push(curPolygonInstance2);
                  const startPoint = Cesium.Cartographic.toCartesian(ellipse[4]);
                  const heading = Cesium.Math.toRadians(curAspect);
                  const deltaX = g * Math.cos(heading);
                  const deltaY = g * Math.sin(heading);
                  const endPoint = new Cesium.Cartesian3(
                    startPoint.x + deltaX,
                    startPoint.y + deltaY,
                    startPoint.z
                  );
                  // console.log(endPoint);
                  const arrowInstance = this.createArrowInstance(
                    endPoint,
                    ellipse[0],
                    curAspect
                  );
                  instances.push(arrowInstance);
                }
              */
    }
    //console.log("HeightRange", HeightRange);
    //const range = this.arrayMinMax(HeightRange)[1] - this.arrayMinMax(HeightRange)[0];
    console.log('slopeCostArray',this.slopeCostArray);
    
    const MaxLongitude = this.arrayMinMax(findLongitudeRange)[1];
    const MinLongitude = this.arrayMinMax(findLongitudeRange)[0];
    const MaxLatitude = this.arrayMinMax(findLatitudeRange)[1];
    const MinLatitude = this.arrayMinMax(findLatitudeRange)[0];
    console.log('最大纬度',MaxLatitude,'最小纬度',MinLatitude,'最大经度',MaxLongitude,'最小经度',MinLongitude);
    let longRange = MaxLongitude - MinLongitude;
    let latRange = MaxLatitude - MinLatitude;
    console.log('经度跨度',longRange,'纬度跨度',latRange);
     

    let lonIntervalArray = [];//经度间隔数组，用于找非0最小间隔
    let latIntervalArray = [];//纬度间隔
    let lonInterval = [];//经度间隔
    let latInterval = [];//纬度间隔
    let lonX = [];//坡度二维数组列号x
    let latY = [];//坡度二维数组行号y

    //计算坡度坡向分析区域的边界，找出最大最小经度纬度，用于将网格数据存入二维数组(测试，节点之间的间隔是否相等)
    for(let i = 0; i < this.slopeCostArray.length-1; i++)
    {
      let num1 = this.slopeCostArray[i].degreeCoordinate[0] - this.slopeCostArray[i+1].degreeCoordinate[0];//js用15位浮点数存储，小数相减后位数会变多，需要限制
      let num2 = this.slopeCostArray[i].degreeCoordinate[1] - this.slopeCostArray[i+1].degreeCoordinate[1];
      if(num1 !== 0){
        lonIntervalArray.push(Math.abs(Math.floor(num1 * Math.pow(10,13)) / Math.pow(10,13).toFixed(13)));//经度间隔
      }
      if(num2 !== 0){ 
        latIntervalArray.push(Math.abs(Math.floor(num2 * Math.pow(10,13)) / Math.pow(10,13).toFixed(13)));//纬度间隔
      }      

    }
    lonInterval = this.arrayMinMax(lonIntervalArray)[0];//找非0最小经度间隔
    latInterval = this.arrayMinMax(latIntervalArray)[0];//找非0最小纬度间隔
    lonX = Math.round(latRange / latInterval) + 1;//行列号（x为列号，y为行号）
    latY = Math.round(longRange / lonInterval) + 1;
    
    // console.log('经度间隔',(lonIntervalArray));
    // console.log('纬度间隔',(latIntervalArray));
    // console.log('y网格数量',lonX,'x网格数量',latY);

    for(let i = 0; i < latY; i++){ //初始化二维网格
      this.slopeCostGrid[i] = [];
      for(let j = 0; j < lonX; j++){ 
        this.slopeCostGrid[i][j] = [];
      }
    }
    //i列(经度lon) j行(纬度lat)
    let latJump = 0;
    let lonJump = 0;
    let arrayID = 0;//this.slopeCostArray的索引

    //根据不同判断条件，将 一维序号网格数据 转为 二维行列号网格分布数据
    for(let i = 0; i < latY; i++){ 
      latJump = 0;
      for(let j = 0; j < lonX; j++){
        //设定最左下角行列号为[0][0]，即从（区域内）坐标[MinLongitude,MinLatitude]开始判断   
        //id为0的格子一定在第一列，但是不一定在第一行
        //slopeCostGrid[][]的遍历赋值顺序需与slopeCostArray的标号顺序一致（从下往上从左往右，柱形（不是s形）
    
        let yInterval = Math.abs(this.slopeCostArray[arrayID].degreeCoordinate[1] - (MinLatitude + latJump*latInterval));
        let xInterval = Math.abs(this.slopeCostArray[arrayID].degreeCoordinate[0] - (MinLongitude + lonJump*lonInterval));
        // console.log("xInterval: " + xInterval + " \nyInterval: " + yInterval + '\n0.05*latInterval: ' + 0.05*latInterval + '\n0.05*lonInterval: ' + 0.05*lonInterval);
        
        if(xInterval < 0.05*lonInterval && yInterval < 0.05*latInterval && this.slopeCostArray[arrayID+1] !== undefined){
          this.slopeCostGrid[i][j] = this.slopeCostArray[arrayID];
          arrayID++;
          latJump++;
        }
        else if(this.slopeCostArray[arrayID+1] == undefined){
          this.slopeCostGrid[i][j] = this.slopeCostArray[arrayID];
          latJump++;
        }
        else{
          this.slopeCostGrid[i][j] = [];
          latJump++;
        }
        
      }
      lonJump++;
    }
    console.log('this.slopeCostGrid',this.slopeCostGrid);   
    
    //BBB 放在代码末尾 用于测试，找出每个网格中心点 位置(二维数组版)

    // 是否渲染
    if(this.drawFlag){
      for (let i = 0; i < 10; i++) {
        if (this.aspectPosArray[i].length > 0) {
          this.createPolygonInstance(this.aspectPosArray[i], aspectColor[i][0], 1);
        }
        if (this.slopePosArray[i].length > 0) {
          this.createPolygonInstance(this.slopePosArray[i], slopeColor[i][0], 0);
        }
      }
    }
    console.log('slopeColor',slopeColor);
    console.log('aspectColor',aspectColor);
    console.timeEnd("计算时间");

    //根据config选择显示图层  1位坡度 0位坡向 通行代价图默认不显示
    let config = this.config;
    this.slopePolygons.forEach((element) => {
      element.primitive.show = config ? true : false;
    });
    this.aspectPolygons.forEach((element) => {
      element.primitive.show = config ? false : true;
    });
    this.DrawCostMap();
//AAA 删去一段和箭头线相关的，已移至文件末尾注释

    console.timeEnd("从头到尾所花时间");
    this.config = Boolean(this.config);
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
    // ==================== 1. 数据校验与初始化 ====================
    
    // 检查 slopeCostGrid 是否已计算
    if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) {
      alert('请先计算区域坡度！');
      return;
    }
    console.time('山脊线山谷线提取');

    // 获取栅格网格的行列数
    // slopeCostGrid[i][j]: i 为行索引（纬度方向），j 为列索引（经度方向）
    const rows = this.slopeCostGrid.length;       // 行数（Y方向）
    const cols = this.slopeCostGrid[0].length;    // 列数（X方向）
    this.valleyThresholdRatio = $('#valleyThresholdRatio').val(); // 山谷线阈值比例
    this.ridgeThresholdRatio = $('#ridgeThresholdRatio').val(); // 山脊线阈值比例

    // ==================== 2. 提取高程矩阵 DEM（Digital Elevation Model）====================
    
    // 创建二维高程矩阵，用于流向分析
    // DEM[i][j] 存储格子 [i,j] 的高程值（单位：米）
    const DEM = new Array(rows);// DEM[i][j] = cell[2][2] = this.slopeCostGrid[i][j].degreeCoordinate[2]为高程值height
    for (let i = 0; i < rows; i++) {
      DEM[i] = new Array(cols).fill(0); // 初始化为 0
    }

    // 从 slopeCostGrid 中提取高程数据（cell[2][2] 为 height）
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const cell = this.slopeCostGrid[i][j];
        // 检查格子是否有效（非空数组）
        if (cell.degreeCoordinate !== undefined) {
          DEM[i][j] = Number(cell.degreeCoordinate[2]); // 高程值（米） // DEM[i][j] = cell[2][2] = this.slopeCostGrid[i][j].degreeCoordinate[2]为高程值height
        } else {
          DEM[i][j] = Number.NaN; // 无效格子标记为 NaN
        }
      }
    }

    // ==================== 3. 计算正向流向（Flow Direction）- 用于提取山谷线 ====================
    
    // 流向矩阵：记录每个格子的水流流向哪个邻居（D8 编码）
    // D8 方向编码（顺时针，从正东开始）：
    //   32  64   128
    //   16  [0]  1
    //   8   4    2
    // 值为 0 表示该格子为汇点（周围所有格子高程都比它高）或无效格子
    const flowDir = new Array(rows);
    for (let i = 0; i < rows; i++) {
      flowDir[i] = new Array(cols).fill(0);
    }

    // D8 八邻域方向数组（相对偏移量 [di, dj]）
    // 遍历顺序：右、右下、下、左下、左、左上、上、右上
    const directions = [
      [0, 1],   // 1: 右（东）
      [1, 1],   // 2: 右下（东南）
      [1, 0],   // 4: 下（南）
      [1, -1],  // 8: 左下（西南）
      [0, -1],  // 16: 左（西）
      [-1, -1], // 32: 左上（西北）
      [-1, 0],  // 64: 上（北）
      [-1, 1]   // 128: 右上（东北）
    ];
    // 对应的 D8 编码值
    const dirCodes = [1, 2, 4, 8, 16, 32, 64, 128];

    // 遍历每个格子，计算其正向流向（水流往高程最低的邻居流）
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const z = DEM[i][j]; // 当前格子高程
        if (!isFinite(z)) continue; // 跳过无效格子

        let maxDrop = 0;           // 最大高程降（当前格子高程 - 邻居高程）
        let flowDirCode = 0;       // 流向编码（D8）

        // 遍历 8 个邻居，找到高程降最大的方向
        for (let d = 0; d < 8; d++) {
          const ni = i + directions[d][0]; // 邻居行索引
          const nj = j + directions[d][1]; // 邻居列索引

          // 检查邻居是否在边界内
          if (ni < 0 || ni >= rows || nj < 0 || nj >= cols) continue;

          const nz = DEM[ni][nj]; // 邻居高程
          if (!isFinite(nz)) continue; // 跳过无效邻居

          // 计算高程降（坡降）
          const drop = z - nz;
          
          // 如果高程降为正且大于当前最大降，则更新流向
          if (drop > maxDrop) {
            maxDrop = drop;
            flowDirCode = dirCodes[d]; // 记录流向编码
          }
        }

        flowDir[i][j] = flowDirCode; // 保存该格子的流向
      }
    }

    // ==================== 4. 计算正向汇流累积（Flow Accumulation）- 山谷线 ====================
    
    // 汇流累积矩阵：记录流经每个格子的上游格子总数（包括自己）
    // 值越大，说明汇集的水流越多，越可能是山谷线
    const flowAcc = new Array(rows);
    for (let i = 0; i < rows; i++) {
      flowAcc[i] = new Array(cols).fill(1); // 初始化为 1（自身）
    }

    // 使用拓扑排序计算汇流累积（从高到低逐格累加）
    // 创建格子列表并按高程降序排序（高程高的先处理）
    const cellList = [];
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const z = DEM[i][j];
        if (isFinite(z)) {
          cellList.push({ i, j, z }); // 保存格子位置和高程
        }
      }
    }
    // 按高程降序排序（从高到低）
    cellList.sort((a, b) => b.z - a.z);

    // 遍历排序后的格子列表，累加汇流
    for (const cell of cellList) {
      const i = cell.i;
      const j = cell.j;
      const dir = flowDir[i][j]; // 该格子的流向

      if (dir === 0) continue; // 无流向（汇点或无效）则跳过

      // 找到流向的目标邻居（根据 D8 编码）
      let targetI = i, targetJ = j;
      for (let d = 0; d < 8; d++) {
        if (dirCodes[d] === dir) {
          targetI = i + directions[d][0];
          targetJ = j + directions[d][1];
          break;
        }
      }

      // 检查目标邻居是否在边界内
      if (targetI >= 0 && targetI < rows && targetJ >= 0 && targetJ < cols) {
        // 将当前格子的累积值传递给下游邻居
        flowAcc[targetI][targetJ] += flowAcc[i][j];
      }
    }

    // ==================== 5. 计算反向流向（Reverse Flow）- 用于提取山脊线 ====================
    
    // 反向流向：水流从低往高流（模拟分水岭的形成）
    const revFlowDir = new Array(rows);
    for (let i = 0; i < rows; i++) {
      revFlowDir[i] = new Array(cols).fill(0);
    }

    // 遍历每个格子，计算反向流向（往高程最高的邻居流）
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const z = DEM[i][j];
        if (!isFinite(z)) continue;

        let maxRise = 0;           // 最大高程升（邻居高程 - 当前格子高程）
        let revFlowDirCode = 0;

        // 遍历 8 个邻居，找到高程升最大的方向
        for (let d = 0; d < 8; d++) {
          const ni = i + directions[d][0];
          const nj = j + directions[d][1];

          if (ni < 0 || ni >= rows || nj < 0 || nj >= cols) continue;

          const nz = DEM[ni][nj];
          if (!isFinite(nz)) continue;

          const rise = nz - z; // 高程升

          if (rise > maxRise) {
            maxRise = rise;
            revFlowDirCode = dirCodes[d];
          }
        }

        revFlowDir[i][j] = revFlowDirCode;
      }
    }

    // ==================== 6. 计算反向汇流累积（Reverse Flow Accumulation）- 山脊线 ====================
    
    const revFlowAcc = new Array(rows);
    for (let i = 0; i < rows; i++) {
      revFlowAcc[i] = new Array(cols).fill(1);
    }

    // 按高程升序排序（从低到高）
    cellList.sort((a, b) => a.z - b.z);

    // 累加反向汇流
    for (const cell of cellList) {
      const i = cell.i;
      const j = cell.j;
      const dir = revFlowDir[i][j];

      if (dir === 0) continue;

      // 找到流向的目标邻居（根据 D8 编码）
      let targetI = i, targetJ = j;
      for (let d = 0; d < 8; d++) {
        if (dirCodes[d] === dir) {
          targetI = i + directions[d][0];
          targetJ = j + directions[d][1];
          break;
        }
      }

      if (targetI >= 0 && targetI < rows && targetJ >= 0 && targetJ < cols) {
        revFlowAcc[targetI][targetJ] += revFlowAcc[i][j];
      }
    }

    // ==================== 7. 提取山脊线和山谷线（阈值法）====================
    
    // 计算汇流累积的统计信息，用于确定阈值
    let maxFlowAcc = 0, maxRevFlowAcc = 0, maxHeight = -Infinity, minHeight = Infinity;
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        if (isFinite(DEM[i][j])) {
          if (flowAcc[i][j] > maxFlowAcc) maxFlowAcc = flowAcc[i][j];
          if (revFlowAcc[i][j] > maxRevFlowAcc) maxRevFlowAcc = revFlowAcc[i][j];
        }
      }
    }
    // 计算区域最小和最大高程值
    minHeight = this.arrayMinMax(DEM.flat().filter(Number.isFinite))[0];// 保留有效数字，过滤NaN Infinite
    maxHeight = this.arrayMinMax(DEM.flat().filter(Number.isFinite))[1];
    console.log('DEM', DEM, '区域最小高程:', minHeight, '区域最大高程:', maxHeight);
    

    // 尝试设置动态阈值，根据当前格子高程在分析区域高程范围的位置（比例），设定对应比例的阈值 20251219
    // 设定阈值（取最大值的百分比，可调整以控制提取的线条密度）
    // 阈值越高，提取的线条越少但越主要；阈值越低，线条越多但越细碎
    let HeightRatio = 0;// 当前格子所在高程比例
    let valleyThreshold = maxFlowAcc * this.valleyThresholdRatio;      // 山谷线阈值（80% 最大汇流累积）
    let ridgeThreshold = maxRevFlowAcc * this.ridgeThresholdRatio;    // 山脊线阈值（80% 最大反向汇流累积）

    console.log('汇流累积最大值:', maxFlowAcc, '山谷线阈值:', valleyThreshold);
    console.log('反向汇流累积最大值:', maxRevFlowAcc, '山脊线阈值:', ridgeThreshold);

    // 提取山谷线点集（汇流累积值 >= 阈值）
    const valleyPoints = [];
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        HeightRatio = (DEM[i][j] - minHeight) / (maxHeight - minHeight);// 当前格子所在高程比例
        if (flowAcc[i][j] >= (valleyThreshold * HeightRatio) && isFinite(DEM[i][j])) {
          const cell = this.slopeCostGrid[i][j];
          if (cell && cell.Cartesian) { // Cartesian3 坐标
            valleyPoints.push(cell.Cartesian);
          }
        }
      }
    }

    // 提取山脊线点集（反向汇流累积值 >= 阈值）
    const ridgePoints = [];
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        HeightRatio = (DEM[i][j] - minHeight) / (maxHeight - minHeight);
        if (revFlowAcc[i][j] >= (ridgeThreshold * HeightRatio) && isFinite(DEM[i][j])) {
          const cell = this.slopeCostGrid[i][j];
          if (cell && cell.Cartesian) { // Cartesian3 坐标
            ridgePoints.push(cell.Cartesian);
          }
        }
      }
    }

    console.log('提取山谷线点数:', valleyPoints.length);
    console.log('提取山脊线点数:', ridgePoints.length);

    // ==================== 8. 在 Cesium 场景中绘制山脊线和山谷线 ====================
    
    const viewer = this.viewer;

    // 清除之前的山脊山谷线实体（如果有）
    if (this.ridgeValleyEntities) {
      this.ridgeValleyEntities.forEach(ent => viewer.entities.remove(ent));
    }
    this.ridgeValleyEntities = [];

    // 绘制山谷线（蓝色点）
    if (valleyPoints.length > 0) {
      valleyPoints.forEach(pos => {
        const entity = viewer.entities.add({
          position: pos,
          point: {
            pixelSize: 6,                          // 点大小
            color: Cesium.Color.BLUE,              // 蓝色表示山谷
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND, // 贴地
          }
        });
        entity.isRidgeValley = true;              // 标记为山脊山谷实体
        this.ridgeValleyEntities.push(entity);
      });
      console.log('✓ 已绘制山谷线（蓝色）');
    }

    // 绘制山脊线（红色点）
    if (ridgePoints.length > 0) {
      ridgePoints.forEach(pos => {
        const entity = viewer.entities.add({
          position: pos,
          point: {
            pixelSize: 6,
            color: Cesium.Color.RED,               // 红色表示山脊
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          }
        });
        entity.isRidgeValley = true;
        this.ridgeValleyEntities.push(entity);
      });
      console.log('✓ 已绘制山脊线（红色）');
    }

    // ==================== 9. 可选：保存结果到对象属性（供后续分析使用）====================
    
    this.flowAccumulation = {
      DEM: DEM,                    // 高程矩阵
      flowDir: flowDir,            // 正向流向矩阵
      flowAcc: flowAcc,            // 正向汇流累积（山谷线）
      revFlowDir: revFlowDir,      // 反向流向矩阵
      revFlowAcc: revFlowAcc,      // 反向汇流累积（山脊线）
      valleyPoints: valleyPoints,  // 山谷线点集
      ridgePoints: ridgePoints     // 山脊线点集
    };

    console.timeEnd('山脊线山谷线提取');
    alert(`提取完成！\n山谷线（蓝色）: ${valleyPoints.length} 点\n山脊线（红色）: ${ridgePoints.length} 点`);
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
    // ==================== 1. 计算每段的代价边界值 ====================
    
    // 根据论文，计算每段的两端代价值
    /*// 第1段: slope <= 5° (常量段)
    const cost_seg1 = costValArray[0]; // = 10
    
    // 第2段: 5° < slope <= 9° (单调递减)
    // 左端点 slope=5: 代入公式计算
    const slope_2_left = 5;
    const cost_seg2_left = costValArray[1];
    // 右端点 slope=9
    const slope_2_right = 9;
    const cost_seg2_right = costValArray[2];
    
    // 第3段: 9° < slope <= 22° (单调递增)
    // 左端点 slope=9
    const slope_3_left = 9;
    const cost_seg3_left = costValArray[3];
    // 右端点 slope=22
    const slope_3_right = 22;
    const cost_seg3_right = costValArray[4];
    
    // 第4段: 22° < slope <= 35° (单调递减)
    // 左端点 slope=22
    const slope_4_left = 22;
    const cost_seg4_left = costValArray[5];
    // 右端点 slope=35
    const slope_4_right = 35;
    const cost_seg4_right = costValArray[6];
    
    // 第5段: slope > 35° (极小值段，不可通行)
    const cost_seg5 = 1e-6;*/
    

    /*// 第1段: slope <= 6° (常量段)
    const cost_seg1 = costValArray[0]; // = 10
    
    // 第2段: 6° < slope <= 10° (单调递减)
    const cost_seg2_left = costValArray[0];
    const cost_seg2_right = costValArray[1];
    
    // 第3段: 10° < slope <= 15° (单调递增)
    const cost_seg3_left = costValArray[1];
    const cost_seg3_right = costValArray[2];
    
    // 第4段: 15° < slope <= 20° (单调递减)
    const cost_seg4_left = costValArray[2];
    const cost_seg4_right = costValArray[3];
    
    // 第5段: slope > 20° (极大值段，不可通行)
    const cost_seg5 = 999999;*/

    console.log('costValArray',costValArray);
    // 收集所有边界值并排序（从小到大，对应难通行到易通行）
    /*const boundaryValues = [
      cost_seg5,          // 极小/大值（不可通行）
      cost_seg4_right,    // 第4段右端
      cost_seg4_left,     // 第4段左端
      cost_seg3_right,    // 第3段右端
      cost_seg3_left,     // 第3段左端
      cost_seg2_right,    // 第2段右端
      cost_seg2_left,     // 第2段左端
      cost_seg1           // 第1段常量
    ].sort((a, b) => a - b); // 升序排序
    
    console.log('代价边界值（升序）:', boundaryValues.map(v => v.toFixed(4)));
    
    // ==================== 2. 使用边界值构建5级分类阈值 ====================
    
    // 根据边界值的分布，选取关键点作为5级分类的阈值
    // boundaryValues 已按升序排序，共8个值，需要选择6个阈值点（5个区间的边界）
    // 策略：取最小值、20%、40%、60%、80%、最大值位置的边界值
    const n = boundaryValues.length;
    const thresholds = [
      boundaryValues[0],                              // 最小值（极小值 1e-6）
      boundaryValues[Math.floor(n * 0.2)],            // 20% 位置
      boundaryValues[Math.floor(n * 0.4)],            // 40% 位置
      boundaryValues[Math.floor(n * 0.6)],            // 60% 位置
      boundaryValues[Math.floor(n * 0.8)],            // 80% 位置
      boundaryValues[n - 1]                           // 最大值（常量 10）
    ];
    
    // 去重并重新排序（防止重复阈值）
    const uniqueThresholds = thresholds;//[...new Set(thresholds)].sort((a, b) => a - b);
    
    // 如果去重后不足6个阈值，补充中间值
    while (uniqueThresholds.length < 6) {
      // 找到最大间隔并插入中点
      let maxGap = 0, maxGapIdx = 0;
      for (let i = 0; i < uniqueThresholds.length - 1; i++) {
        const gap = uniqueThresholds[i + 1] - uniqueThresholds[i];
        if (gap > maxGap) {
          maxGap = gap;
          maxGapIdx = i;
        }
      }
      const midVal = (uniqueThresholds[maxGapIdx] + uniqueThresholds[maxGapIdx + 1]) / 2;
      uniqueThresholds.splice(maxGapIdx + 1, 0, midVal);
      uniqueThresholds.sort((a, b) => a - b);
    }
    
    // 使用前6个阈值（如果超过6个则截取）
    const finalThresholds = uniqueThresholds.slice(0, 6);
    
    console.log('使用的分级阈值（基于边界值）:', finalThresholds.map(v => v.toFixed(4)));*/
    
    /*// ==================== 3. 定义5个颜色等级（从难到易：红→橙→黄→浅绿→绿）====================
    // 颜色等级（RGB格式）
    const colorLevels = [
      { r: 255, g: 0,   b: 0,   name: '红色-最难通行/不可通行',  class: 4 }, // 最难
      { r: 255, g: 140, b: 0,   name: '橙色-较难通行',          class: 3 },
      { r: 255, g: 255, b: 0,   name: '黄色-中等通行',          class: 2 },
      { r: 144, g: 238, b: 144, name: '浅绿-较易通行',          class: 1 },
      { r: 0,   g: 255, b: 0,   name: '绿色-最易通行',          class: 0 }  // 最易
    ];*/
    
    // ==================== 2. 定义6个颜色等级（按坡度分段）====================
    const colorLevels = [
      { r: 0,   g: 255, b: 0,   name: '绿色-最易通行(0-6°)',     slopeMax: 6  },
      { r: 144, g: 238, b: 144, name: '浅绿-较易通行(6-10°)',    slopeMax: 10 },
      { r: 255, g: 255, b: 0,   name: '黄色-中等通行(10-15°)',   slopeMax: 15 },
      { r: 255, g: 140, b: 0,   name: '橙色-较难通行(15-20°)',   slopeMax: 20 },
      { r: 255, g: 69,  b: 0,   name: '深橙-困难通行(20-30°)',   slopeMax: 30 },
      { r: 255, g: 0,   b: 0,   name: '红色-不可通行(>30°)',     slopeMax: 999 }
    ];

    // ==================== 4. 遍历栅格，分类并赋颜色（使用边界值阈值）====================
    
    const slopeCostColorGrid = []; // 代价->颜色映射栅格
    for (let i = 0; i < colorLevels.length; i++) {
      slopeCostColorGrid[i] = [];// 初始化5个等级的数组
    }
    
    for (let i = 0; i < this.slopeCostGrid.length; i++) {
      for (let j = 0; j < this.slopeCostGrid[i].length; j++) {

        const cell = this.slopeCostGrid[i][j];
        // 检查格子是否有效（非空且有代价值）
        if (!cell || cell.slopeCost === undefined || !isFinite(cell.slopeCost)) {
          continue;// 无效格子
        }
        
        const slope = cell.slope;
        const cost = cell.slopeCost;
        
        // 根据代价值判断属于哪个等级（使用 finalThresholds 边界值）
        /*let colorClass = 4; // 默认最难级（红色）
        for (let k = 0; k < 5; k++) {
          if (cost >= finalThresholds[k]*slope && cost <= finalThresholds[k + 1]*slope) {
            colorClass = k; // 等级0最易（绿），等级4最难（红）
            break;
          }
        }*/  
        /*for (let k = 0; k < 5; k++) {
          if (cost >= finalThresholds[k] && cost < finalThresholds[k + 1]) {
            colorClass = 4 - k; // 等级0最易（绿），等级4最难（红）
            break;
          }
        }*/  

        // 根据坡度值判断属于哪个等级
        let colorClass = 5; // 默认最难级（红色，>30°）
        
        if (slope <= 6) {
          colorClass = 0; // 绿色
        } else if (slope <= 10) {
          colorClass = 1; // 浅绿
        } else if (slope <= 15) {
          colorClass = 2; // 黄色
        } else if (slope <= 20) {
          colorClass = 3; // 橙色
        } else if (slope <= 30) {
          colorClass = 4; // 深橙（20-30°仍可通行）
        } else {
          colorClass = 5; // 红色（>30°不可通行）
        }

        // 获取对应等级的颜色
        const colorLevel = colorLevels[colorClass]; //colorClass=0对应索引0（绿），colorClass=5对应索引5（红） // colorClass=0对应索引4（绿），colorClass=4对应索引0（红）
        //转换成16进制颜色字符串
        const color = `#${((1 << 24) + (colorLevel.r << 16) + (colorLevel.g << 8) + colorLevel.b).toString(16).slice(1)}`;
        
        // 存储分类结果
        slopeCostColorGrid[colorClass].push({
          i: i,                           // 行索引
          j: j,                           // 列索引
          cost: cost,                     // 原始代价值
          colorClass: colorClass,         // 颜色等级（0-4）
          colorRGB: colorLevel,           // RGB对象颜色分级数据 {r, g, b}
          color: color,                   // 十六进制颜色字符串
          gridSquare: cell.gridSquare || [] // 网格绘制九点坐标
        });
      }
    }
    
    return slopeCostColorGrid;
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

/*AAA*/

    // this.mapPrimitive1.show = config ? true : false;
    // this.mapPrimitive2.show = !this.mapPrimitive1.show;
    // this.viewer.scene.primitives.add(config? this.mapPrimitive1: this.mapPrimitive2 );
    // this.viewer.scene.primitives.add(this.mapPrimitive1);
    // this.viewer.scene.primitives.add(this.mapPrimitive2);
    // console.log(this.viewer.scene.primitives);

    // const this.mapPrimitive2 = this.viewer.scene.primitives.add(
    //   new Cesium.GroundPrimitive({
    //     geometryInstances: aspectInstance,
    //     appearance: new Cesium.PerInstanceColorAppearance({
    //       translucent: true, //false时透明度无效
    //       closed: false,
    //     }),
    //   })
    // );
    // 箭头添加 */
    // const arrowPrimitive = this.viewer.scene.primitives.add(
    //   new Cesium.GroundPolylinePrimitive({
    //     geometryInstances: instances,
    //     appearance: new Cesium.PolylineMaterialAppearance({
    //       material: new Cesium.Material({
    //         fabric: {
    //           type: "PolylineArrow",
    //           uniforms: {
    //             color: new Cesium.Color(1.0, 1.0, 0.0, 0.8),
    //           },
    //         },
    //       }),
    //     }),
    //   })
    // );
    // this.aspectPolygons.push(arrowPrimitive, this.mapPrimitive);
    //this.result.push(this.mapPrimitive1, this.mapPrimitive2); //已用slopePolygon和aspectPolygon代替

/*BBB*/

    //用于测试，找出每个网格中心点 位置(二维数组版)
    // for(let i = 0; i < latY; i++){ 
    //   for(let j = 0; j < lonX; j++){
    //     const color1 = Cesium.Color.WHITE;
    //     const slopePoint = new Cesium.Entity({
    //       position: this.slopeCostGrid[i][j][0],
    //       id:
    //         "i：" +
    //         i +
    //         "    j：" +
    //         j +
    //         "    slope：" +
    //         this.slopeCostGrid[i][j][1] +
    //         "\n" ,
    //       point: {
    //         pixelSize: 0.1,
    //         color: color1,
    //         outlineColor: Cesium.Color.BLACK,
    //         outlineWidth: 2,
    //         heightReference: Cesium.HeightReference.CLAMP_TO_GROUND, //设置贴地
    //         disableDepthTestDistance: Number.POSITIVE_INFINITY,
    //       },
    //     });
    //     viewer.entities.add(slopePoint);
    //   }
    // }
    // for(let i = 0; i < this.slopeCostArray.length; i++){ //用于测试，找出每个网格中心点 位置(一维数组版)
    //   const color1 = new Cesium.Color(WHITE);
    //   const slopePoint = new Cesium.Entity({
    //     position: this.slopeCostArray[i][0],
    //     id:
    //       "id：" +
    //       i +
    //       "    slope：" +
    //       this.slopeCostArray[i][1] +
    //       "\n" ,
    //     point: {
    //       pixelSize: 0.5,
    //       color: color1,
    //       outlineColor: Cesium.Color.WHITE,
    //       outlineWidth: 2,
    //       heightReference: Cesium.HeightReference.CLAMP_TO_GROUND, //设置贴地
    //       disableDepthTestDistance: Number.POSITIVE_INFINITY,
    //     },
    //   });
    //   viewer.entities.add(slopePoint);
    // }

    // for (let i = 0; i < this.heightPosArray.length; i++) {
    //   this.heightPosArray[i].height =
    //     (this.heightPosArray[i].height - Math.min(...HeightRange)) / range;
    //   this.DrawHeight(this.heightPosArray[i], HeightRange);
    // }
    // console.log("heightPosArray", this.heightPosArray);

/*CCC*/

    // let num = Cesium.Cartographic.fromCartesian(viewer.camera.position).height;
    // let levelTer = calculateValue(num);
    // if (levelTer >= 14) {
    //   Cesium.sampleTerrainMostDetailed(this.viewer.scene.terrainProvider, boxResults).then((updatePositions) => {
    //     let arrr = [];
    //     let ellipseResults = updatePositions.reduce(function (
    //       pre,
    //       item,
    //       index,
    //       updatePositions
    //     ) {
    //       var begin = index * 10;
    //       var end = begin + 10;
    //       var res = updatePositions.slice(begin, end);
    //       if (res.length != 0) {
    //         arrr[index] = res;
    //       }
    //       return arrr;
    //     }, []);
    //     this.calculateSlope(ellipseResults);
    //   });
    // } else {
    //   if (levelTer)
    //     Cesium.sampleTerrain(this.viewer.scene.terrainProvider, levelTer, boxResults).then((updatePositions) => {
    //       let arrr = [];
    //       let ellipseResults = updatePositions.reduce(function (
    //         pre,
    //         item,
    //         index,
    //         updatePositions
    //       ) {
    //         var begin = index * 10;
    //         var end = begin + 10;
    //         var res = updatePositions.slice(begin, end);
    //         if (res.length != 0) {
    //           arrr[index] = res;
    //         }
    //         return arrr;
    //       }, []);
    //       console.timeEnd('获取高程点所需时间')

    //       this.calculateSlope(ellipseResults);
    //       console.timeEnd('从头到尾所花时间')

    //     });
    // }

    // Cesium.sampleTerrainMostDetailed(
    //   this.viewer.scene.terrainProvider,
    //   boxResults
    // ).then((updatePositions) => {
    //   let arrr = [];
    //   let ellipseResults = updatePositions.reduce(function (
    //     pre,
    //     item,
    //     index,
    //     updatePositions
    //   ) {
    //     var begin = index * 10;
    //     var end = begin + 10;
    //     var res = updatePositions.slice(begin, end);
    //     if (res.length != 0) {
    //       arrr[index] = res;
    //     }
    //     return arrr;
    //   },
    //   []);
    //   console.timeEnd("获取高程点所需时间");
    //   console.time("计算坡度所花时间");
    //   this.calculateSlope(ellipseResults);
    //   console.timeEnd("计算坡度所花时间");
    // });
