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

let curSlope_save = [];
let curAspect_save = [];

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
    this.keepStartEndFlag = false;//是否保留起终点 标志位
    this.keepStartPoint = null;//保留的起点坐标
    this.keepEndPoint = null;//保留的终点坐标
    this.pathLineNum = 0;//路径线ID
    this.potentialField = null;// 反向搜索潜力场（二维数组），用于存储从每个点到目标的最小代价（cost-to-go）
    this.equTimeCost = false;// 使用等效时间计算代价（坡度、距离、转向用时间表示代价）
    this.usePotentialFieldFlag = false;// 是否使用潜力场（反向 Dijkstra -> 从起点按 potential 最小方向跟随）进行全局寻路
  }
  // 不会栈溢出的方法，找最大最小值，代替Math.min和Math.max
  arrayMinMax = (arr) => {
    // Math.min 和 Math.max 在大数组时报“Maximum call stack size exceeded.”
    return arr.reduce(
      ([min, max], val) => [Math.min(min, val), Math.max(max, val)],
      [Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]
    );
  };
  update_curSlope() {
    curSlope_save = this.curSlope;
  }
  return_curSlope() {
    return curSlope_save;
  }
  update_curAspect() {
    curAspect_save = this.curAspect;
  }
  return_curAspect() {
    return curAspect_save;
  }
  return_alpha() {
    return this.area_alpha;
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
    
    //删除所有点
    this.viewer.entities.removeAll();
    this.slopeCostArray = [];
    this.slopeCostGrid = [];//清空网格数组

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
    this.potentialField = null;// 重置潜力场
    console.log('keepStartEndFlag', this.keepStartEndFlag, 'clearPathFlag', this.clearPathFlag);

    if(this.keepStartEndFlag && !this.clearPathFlag){
      console.log('this.pathLineNum', this.pathLineNum, 'this.keepStartPoint', this.keepStartPoint, 'this.keepEndPoint', this.keepEndPoint);
      this.FindPath(this.keepStartPoint, this.keepEndPoint);
      return;
    }//重新绘制路径（保留原有路径）

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

    
    if(this.reFindPathFlag){
      this.GetSlopePath();
      this.reFindPathFlag = false;
    }// 重新绘制路径（删除原有路径）
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
      //this.mapPrimitive1.show = !this.mapPrimitive1.show;
      this.aspectPolygons.forEach((element) => {
        element.primitive.show = !element.primitive.show;
      });
      //this.mapPrimitive2.show = !this.mapPrimitive2.show;
      console.log("aspectChange");
    }
  }

  openTip() {
    const $this = this;
    const viewer = this.viewer;
    this.handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
    this.handler.setInputAction(function (movement) {
      let endPos = movement.endPosition;
      var pick = viewer.scene.pick(endPos);
      if (pick && pick.id && pick.id.type === "SlopeAspect") {
        $this.toolTip = pick.id.value.toFixed(2);
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

        // 再绘制选中路径的粗糙度曲线（如果已加载 RoughAnalysis 和 echarts）
        try {
          // 把 option.value（pathLineNum）解析为数字索引数组
          const indices = selected.map(v => Number(v)).filter(n => Number.isFinite(n));
          if (indices.length === 0) return;

          // 确保 RoughAnalysis 可用（脚本应已在页面中引入）
          window._RoughAnalysisInstance = window._RoughAnalysisInstance || new RoughAnalysis();
          // pathPoints：嵌套数组，this.pathPoints[i] 为第 i 条路径点数组
          // pathLines：路径元信息数组，包含颜色等用于配色
          window._RoughAnalysisInstance.showMultipleRoughness(indices, this.pathPoints, this.pathLines);
        } catch (err) {
          // 只打印错误，不影响原有路径显示功能
          console.warn('绘制粗糙度曲线失败', err);
        }
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
        z: cell && cell[2] ? cell[2][2] : 0,
        Cartesian3Grid: cell && cell[0] ? cell[0] : null,
        slopeCost: cell && cell[3] ? cell[3] : null,
        slope: cell && cell[1] ? cell[1] : null,
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
        if(this.equTimeCost){
          moveCost = this.CarWeightCost_GetCost(neighborNode, currentNode).totalT;
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
    distance = distance || 0.1; //默认0.1km精度,yf师兄
    this.distance = distance * 1000;
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
        let gridSquare = turf.squareGrid(bbox, distance, { mask: mask });console.log('gridSquare',gridSquare);
        
        $this.createEllipse(gridSquare);
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

  // 开始绘制覆盖区（type: 'road' 或 'water'）
  startDrawOverride(type = 'road') {
      // 使用项目中已有的交互绘制函数 CreatePolygonOnGround(viewer, ..., callback)
      const viewer = this.viewer;
      const fillColor = type === 'road' ? Cesium.Color.YELLOW.withAlpha(0.4) : Cesium.Color.BLUE.withAlpha(0.4);
      CreatePolygonOnGround(viewer, [], { color: fillColor, outlineColor: Cesium.Color.BLACK }, (polygon) => {
        try {
       // polygon.pottingPoint 为绘制多边形的 Cartesian3 顶点数组（你的项目中已有该约定）
       const pts = polygon.pottingPoint || polygon.positions || [];
       // 转换为经纬数组 [lon, lat]
       const coords = pts.map(p => {
         const c = Cesium.Cartographic.fromCartesian(p);
         return [Cesium.Math.toDegrees(c.longitude), Cesium.Math.toDegrees(c.latitude)];
       });
       if (coords.length && (coords[0][0] !== coords[coords.length-1]?.[0] || coords[0][1] !== coords[coords.length-1]?.[1])) {
         coords.push(coords[0]); // 闭合环
       }
       // 添加可视实体用于展示覆盖区（保存以便清理）
       const ent = viewer.entities.add({
         polygon: {
           hierarchy: pts,
           material: fillColor,
           classificationType: Cesium.ClassificationType.TERRAIN
         }
       });
       this.overrideAreas = this.overrideAreas || [];
       this.overrideAreas.push({ type: type, polygonEntity: ent, coords: coords });
       this.overrideAreaEntities.push(ent);
       // 应用覆盖到格网并刷新可视化
       this.applyOverridesToGrid();
     } catch (e) {
       console.error('startDrawOverride error', e);
     } finally {
       // 移除临时绘制实体（CreatePolygonOnGround 可能返回一个临时实体）
       try { viewer.entities.remove(polygon); } catch (e) {}
     }
   });
 }
  
  // 将覆盖区应用到 this.slopeCostGrid：road -> 增大 slopeCost（更易通行），water -> 设为极小（不可通行）
  applyOverridesToGrid() {
  if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) return;
  this.overrideAreas = this.overrideAreas || [];
  // 遍历格网并检测每个格子中心是否在覆盖区内
  for (let i = 0; i < this.slopeCostGrid.length; i++) {
    for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
      const cell = this.slopeCostGrid[i][j];
      if (!cell || cell.length === 0) continue;
      const lon = Number(cell[2] && cell[2][0]);
      const lat = Number(cell[2] && cell[2][1]);
      if (!isFinite(lon) || !isFinite(lat)) continue;

      // 确保有原始备份，方便恢复
      if (cell._origSlope === undefined) cell._origSlope = cell[1];
      if (cell._origSlopeCost === undefined) cell._origSlopeCost = cell[3];

      // 先恢复为基于坡度的默认值（避免多次叠加）
      cell[1] = cell._origSlope;
      cell[3] = cell._origSlopeCost;

      // 后添加的覆盖区优先级更高（覆盖数组按加入顺序保存）
      for (let k = 0; k < this.overrideAreas.length; k++) {
        const area = this.overrideAreas[k];
        if (!area || !area.coords) continue;
        if (this._pointInPolygon(lon, lat, area.coords)) {
          if (area.type === "road") {
            // road 等效为坡度 = 0（极易通行），并把 slopeCost 设为一个很大值以降低代价
            cell[1] = 0; // 等效坡度0
            cell[3] = Math.max(cell[3] || 1, 1000.0); // 增大代价因子，使通行更容易
          } else if (area.type === "water") {
            // water 等效为坡度极大（不可通行），使 slopeCost 极小 -> 代价极大
            cell[1] = 99999; // 表示坡度极大（用于显示或其它逻辑）
            cell[3] = 1e-6; // 极小的通行能力，GetCost 会返回非常大的代价
          }
          // 不 break：允许运行后续覆盖覆盖前面的（后画者优先）
        }
      }
    }
  }
  // 覆盖改变后，潜力场与路径缓存失效须重算
  this.potentialField = null;
  // 若需要立即重新绘制代价图，调用者负责触发 DrawCostMap / FindPath
}
    
  // 根据每个格子的 slope 值重新计算默认 slopeCost（用于恢复或首次计算）
  recomputeSlopeCosts() {
    if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) return;
    for (let i = 0; i < this.slopeCostGrid.length; i++) {
      for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
        const cell = this.slopeCostGrid[i][j];
        if (!cell || cell.length === 0) continue;
        const slope = Number(cell[1]);
        if (!isFinite(slope)) { cell[3] = 1e-6; continue; }
        // 复用你原来在 FindPath 中的坡度->代价转换（用 Math.pow 替换 ^）
        if (slope <= 5) {
          cell[3] = 10 * 1;
        } else if (slope > 5 && slope <= 9) {
          cell[3] = (10 * (Math.pow(0.02 * (slope - 5), 3) - 3.183 * slope + 41.1103) / 25.18);
        } else if (slope > 9 && slope <= 22) {
          cell[3] = (10 * ((0.45 * Math.pow(22 - slope, 3) + 0.11 * Math.pow(9 - slope, 3)) / 78 + 0.653 * slope - 4.905) / 25.18);
        } else if (slope > 22 && slope <= 35) {
          cell[3] = (10 * ((0.11 * Math.pow(slope - 35, 3)) / 78 - 0.728 * slope + 25.490) / 25.18);
        } else {
          cell[3] = 1e-6;
        }
        // 同步原始备份
        cell._origSlopeCost = cell[3];
      }
    }
    this.potentialField = null;
  }
    
  // 清除所有覆盖区（移除实体并恢复默认代价）
  clearOverrideAreas() {
    if (this.overrideAreas && this.overrideAreas.length) {
      for (const a of this.overrideAreas) {
        try { this.viewer.entities.remove(a.polygonEntity); } catch (e) {}
      }
      this.overrideAreas = [];
      // 恢复默认 slopeCost
      this.recomputeSlopeCosts();
    }
  }
    
  // 点在多边形内判定：优先使用 turf.booleanPointInPolygon（若加载了 turf），否则回退到射线法
  _pointInPolygon(lon, lat, polyCoords) {
    if (!polyCoords || polyCoords.length < 3) return false;
    try {
      if (typeof turf !== 'undefined' && turf.booleanPointInPolygon) {
        const pt = turf.point([lon, lat]);
        const poly = turf.polygon([polyCoords]);
        return turf.booleanPointInPolygon(pt, poly);
      }
    } catch (e) { /* ignore */ }
    // fallback: ray-casting
    let inside = false;
    for (let i = 0, j = polyCoords.length - 1; i < polyCoords.length; j = i++) {
      const xi = polyCoords[i][0], yi = polyCoords[i][1];
      const xj = polyCoords[j][0], yj = polyCoords[j][1];
      const intersect = ((yi > lat) !== (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }


  //获取对应坐标地形高度
  createEllipse(gridSquare) {
    let boxResults = []; //所有采样点的集合，存放地形高度提取位置（坐标），用于cesium.sampleTerrain(terrainProvider, level, position)函数最后的position参数
    // console.log(gridSquare);
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
    //提取高程，并且按照十个点分为二维数组
    // Cesium.sampleTerrainMostDetailed
    // Cesium.sampleTerrain(this.viewer.scene.terrainProvider,11,boxResults)
    // Cesium.sampleTerrainMostDetailed(
    //   this.viewer.scene.terrainProvider,

    //   boxResults
    // )

    console.time("获取高程点所需时间");

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

  // DrawHeight(DEMheight, HeightRange) {
  //   for (let i = 0; i < DEMheight.length; i++) {
  //     DEMheight[i].height =
  //       (DEMheight[i].height - Math.min(...HeightRange)) /
  //       (Math.max(...HeightRange) - Math.min(...HeightRange));
  //   }
  // }

  //平地距离等效时间（启发函数）
  CarWeightCost_Heuristic(current, end){
    //const G = 9.8;// 重力加速度
    //const DragF = this.carWeight * G;// 牵引力
    const Vc = current.v;// 当前速度
    console.log('Vc2', Vc)
    //const a0 = DragF / this.carWeight;// 加速度
    const dx = Math.abs(current.x - end.x);
    const dy = Math.abs(current.y - end.y);
    const S = Math.sqrt(dx * dx + dy * dy);// 当前点到终点距离
    //const T = -Vc + Math.sqrt(Vc*Vc + 2*a0*S) / a0;// 距离等效时间
    const T = S / Vc;// 距离等效时间
    return T;
  }
  //上下坡转向等效时间
  CarWeightCost_GetCost(from, to){
    const G = 9.8;
    const DragF = 0;// 牵引力
    const dx = Math.abs(from.x - to.x);
    const dy = Math.abs(from.y - to.y);
    //const S = Math.sqrt(dx * dx + dy * dy);// 当前点到下一点距离
    const S = this.distance;
    //const Vc = from.v;// 当前速度
    const slopeAngle = to.slope;// 目标点坡度角(角度)
    const slopeAngle_Rad = (Number(to.slope) || 0) * Math.PI / 180;// 目标点坡度角(弧度)
    const a0 = DragF / this.carWeight;// 牵引力加速度
    let Vc = Math.sqrt(2 * G*Math.sin(28 * (Math.PI / 180)) * S); //当前速度 = 最大坡度速度

    const ap = a0 - G * Math.sin(slopeAngle_Rad);// 坡度加速度
    console.log('from', from, 'ap', ap, 'Vc1', Vc);
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
      const atmax = G*Math.sin((28 - to.slope)*Math.PI / 180); // 最大转向加速度（坡度阈值-当前坡度算出来的重力加速度分量）
      const turnAngle_Rad = to.turnAngle !== undefined ? ((to.turnAngle / 180) * Math.PI) : 0;// 转向角(弧度)
      const k = Math.abs(2 * Math.tan(turnAngle_Rad / 2) / S) == 0 ? 1e-6 : Math.abs(2 * Math.tan(turnAngle_Rad / 2) / S);// 曲率
      const Vtmax = Math.sqrt(atmax / k); // 最大转向速度
      let SL = S * turnAngle_Rad; // 初始转向路程等于总路程
      console.log('Vtmax', Vtmax, 'Vc', Vc);
      if (Number.isFinite(Vtmax) && Vtmax < Vc && !Number.isNaN(Vtmax)) { 
        //SL = S - Math.max(0, (Vtmax*Vtmax - Vc*Vc) / (2*ap)); // 转向路程
        const SS =  Math.max(0, (Vtmax*Vtmax - Vc*Vc) / (2*atmax));
        const TS = (Vtmax - Vc) / atmax;
        Vc = Vtmax;
        const ST = (to.turnAngle/180)*Math.PI*S - SS;
        const TT = ST / Vc;
          
        //turnT = Math.abs((Vtmax - Vc) / ap) + (Math.sqrt(Vtmax*Vtmax + 2*ap*SL) - Vtmax) / ap;// 转向分量等效时间
        turnT = TS + TT;  
        console.log(111);
      }
      else{
        turnT = SL / Vc;
        // if(1 < to.turnAngle && to.turnAngle < 91){
        //   turnT = SL / Vc;
        // }
        // else if(to.turnAngle < 1){ R = 0; turnT = 0; }
        // else{R = 999999; turnT = 999999;}    
      }
    }
    const totalT = slopeT + turnT;
        console.log('Angle', to.turnAngle, 'R', R, '\nturnT', turnT, 'slopeT', slopeT, 'totalT', totalT);
    return { slopeT, turnT, Vc };
  }

  Heuristic(a, b) {
      const dx = Math.abs(a.x - b.x);
      const dy = Math.abs(a.y - b.y);

      return Math.sqrt(dx * dx + dy * dy) * 10;
  }

  GetCost(from, to) {
      const dx = to.x - from.x;
      const dy = to.y - from.y;
      // const distance = Math.sqrt(dx * dx + dy * dy);
      // const elevationDiff = Math.abs(to.z - from.z);
      // return distance * 10 + elevationDiff * 2;

      let distanceCost;
      if (dx === 1 && dy === 1) {
          distanceCost = 12; // 对角移动
      } else {
          distanceCost = 10; // 水平/垂直移动
      }

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

      // 计算的坡度代价（值越大越能通行，故要减去）
      const slopeCost = to.slopeCost * 10;

      // 总预估代价            
      return (distanceCost + elevationCost) / slopeCost;
  }

  // 小函数：计算转向惩罚（角度越大惩罚越高），放在类内部
  turningPenalty(prevNode, currentNode, nextNode) {
    if (!prevNode || !currentNode || !nextNode) return 0;
    // 向量： prev->current 和 current->next
    const v1x = currentNode.x - prevNode.x;
    const v1y = currentNode.y - prevNode.y;
    const v2x = nextNode.x - currentNode.x;
    const v2y = nextNode.y - currentNode.y;
    const mag1 = Math.sqrt(v1x*v1x + v1y*v1y) || 1;
    const mag2 = Math.sqrt(v2x*v2x + v2y*v2y) || 1;
    const dot = (v1x*v2x + v1y*v2y) / (mag1 * mag2);
    const cos = Math.max(-1, Math.min(1, dot));
    const angle = Math.acos(cos); // 0..PI
    const PEN_BASE = 2.0; // 可调，单位代价
    return PEN_BASE * (angle / Math.PI); // 0..PEN_BASE
  }

   // 计算三个格点（prev->current->next）之间的转角，返回度数（带符号或绝对值）
  computeTurnAngle(prevNode, currentNode, nextNode, { signed = false } = {}) {
    if (!prevNode || !currentNode || !nextNode) return 0;
    const v1x = currentNode.x - prevNode.x;
    const v1y = currentNode.y - prevNode.y;
    const v2x = nextNode.x - currentNode.x;
    const v2y = nextNode.y - currentNode.y;
    const mag1 = Math.hypot(v1x, v1y) || 1;
    const mag2 = Math.hypot(v2x, v2y) || 1;
    const dot = (v1x * v2x + v1y * v2y) / (mag1 * mag2);
    // 限定数值范围以避免 NaN
    const c = Math.max(-1, Math.min(1, dot));
    // 无符号角度（0..180）
    const angleRad = Math.acos(c);
    // 计算 z 分量标志位（用于判断左右转）
    if (signed) {
      const cross = v1x * v2y - v1y * v2x;
      const signedRad = Math.atan2(cross, dot); // -PI..PI
      return signedRad * (180 / Math.PI);
    }
    return Math.abs(angleRad * (180 / Math.PI));
  }

  GetNeighbors(node){
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
            this.slopeCostGrid[nx][ny][2][2],// z
            this.slopeCostGrid[nx][ny][0],// Cartesian3Grid
            this.slopeCostGrid[nx][ny][3], // slopeCost
            this.slopeCostGrid[nx][ny][1], // slope
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
    

  //最小代价（坡度）路径计算
  FindPath(startPoint, endPoint){
    var startPoint = startPoint || [];
    var endPoint = endPoint || [];
    var d1 = []; //起点距最近网格点两点距离
    var d2 = []; //终点距各个网格点两点距离（遍历）
    let slope = 999;//量化坡度代价
    let startx = -1;
    let starty = -1;
    let endx = -1;
    let endy = -1;
    this.pathPoints[this.pathLineNum] = []; //途径点(包含起点和终点)用于绘制
    let openList = [];
    let closeList = new Set();
    let nodeInfoMap = new Map(); //节点信息
    let Maxh = 0;// 起点终点距离

    this.carWeight = $('#carWeight').val(); //车辆重量，单位kg
    
    // 初始化pathPoints i j , 在别的地方做了
    // for(let i = 0; i < this.slopeCostGrid.length-1; i++){
    //   this.pathPoints[i] = [];
    //   for (let j = 0; j < this.slopeCostGrid[i].length-1; j++) {
    //     this.pathPoints[i][j] = [];
    //   }
    // }
    

    Maxh = Cesium.Cartesian3.distance(startPoint, endPoint) / 3;// distance * 10 / 30
    console.log('Maxh', Maxh);
    const startstartPoint  = startPoint; //绘制非网格中心点最终点到路径
    const endendPoint  = endPoint; //绘制非网格中心点最终点到路径
    const startCarto = Cesium.Cartographic.fromCartesian(startstartPoint);
    const endCarto = Cesium.Cartographic.fromCartesian(endendPoint);   

    for(let i = 0; i < this.slopeCostGrid.length; i++){
      for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
        if(this.slopeCostGrid[i][j].length != 0){

          slope = this.slopeCostGrid[i][j][1];// 坡度值
          d2 = Cesium.Cartesian3.distance(this.slopeCostGrid[i][j][0], endPoint);
          d1 = Cesium.Cartesian3.distance(this.slopeCostGrid[i][j][0], startPoint);
          
          if (d1 < this.distance * Math.sqrt(2) / 2 && startx == -1 && starty == -1) {
            startPoint = {x: i, y: j, z: this.slopeCostGrid[i][j][2][2], Cartesian3Grid: this.slopeCostGrid[i][j][0]};
            startx = i;
            starty = j;
          }
          if (d2 < this.distance * Math.sqrt(2) / 2 && endx == -1 && endy == -1) {
            endPoint = {x: i, y: j, z: this.slopeCostGrid[i][j][2][2], Cartesian3Grid: this.slopeCostGrid[i][j][0]};
            endx = i;
            endy = j;
          }
          
          // console.log('i', i, 'j', j, 'slope', slope);
          // 转换坡度距离为代价
          if(slope<=5){ 
            this.slopeCostGrid[i][j][3] = 10*1;// console.log(1111);
          }
          else if(slope>5 && slope<=9){
            this.slopeCostGrid[i][j][3] = (10 * (Math.pow(0.02 * (slope - 5), 3) - 3.183 * slope + 41.1103) / 25.18);// console.log(2222);
          }
          else if(slope>9 && slope<=22){
            this.slopeCostGrid[i][j][3] = (10 * ((0.45 * Math.pow(22 - slope, 3) + 0.11 * Math.pow(9 - slope, 3)) / 78 + 0.653 * slope - 4.905) / 25.18);// console.log(3333);
          }
          else if(slope>22 && slope<=35){
            this.slopeCostGrid[i][j][3] = (10 * ((0.11 * Math.pow(slope - 35, 3)) / 78 - 0.728 * slope + 25.490) / 25.18);// console.log(4444);
          }
          else{
            this.slopeCostGrid[i][j][3] = 1e-6;// console.log(5555);
          }//slope > 35   

        }   
      }     
    }


    // 若启用潜力场寻路，优先使用全局 cost-to-go 场并按 potential 贪心跟随
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
            if (openList[i].f < openList[currentIndex].f 
                && openList[i].f < 100000 
                && openList[currentIndex].f < 100000
                ||(openList[i].f === openList[currentIndex].f && openList[i].h < openList[currentIndex].h)) {       
              //console.log('openList[i].f', openList[i].f, 'openList[currentIndex].f', openList[currentIndex].f);
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
              this.pathPoints[this.pathLineNum].unshift({x: temp.x,
                                  y: temp.y,
                                  z: temp.z,
                                  slopeCost: temp.slopeCost,
                                  slope: temp.slope,
                                  v: temp.v,
                                  turnAngle: temp.turnAngle,
                                  g: temp.g,
                                  h: temp.h,
                                  f: temp.f,
                                  Cartesian3Grid: temp.Cartesian3Grid
              });
              temp = temp.parent;// 通过父节点parent回溯路径
            }

            if(this.equTimeCost){
              // 把每个节点的转角“往前移一位”：node.turnAngle = nextNode.turnAngle
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
            const pathPoint3 = this.pathPoints[this.pathLineNum][this.pathPoints[this.pathLineNum].length-1];//路径点3
            const pathPoint4 = this.pathPoints[this.pathLineNum][this.pathPoints[this.pathLineNum].length-2];//路径点4
            const pathPoint1Carto = Cesium.Cartographic.fromCartesian(pathPoint1.Cartesian3Grid);//路径点1的经纬度
            const pathPoint2Carto = Cesium.Cartographic.fromCartesian(pathPoint2.Cartesian3Grid);//路径点2的经纬度
            const pathPoint3Carto = Cesium.Cartographic.fromCartesian(pathPoint3.Cartesian3Grid);//路径点3的经纬度
            const pathPoint4Carto = Cesium.Cartographic.fromCartesian(pathPoint4.Cartesian3Grid);//路径点4的经纬度
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

            if(this.equTimeCost){ //等效时间计算代价
              // 计算转角（度），并保存到节点
              const turnAngleDeg = this.computeTurnAngle(current.parent, current, neighbor);
              neighbor.turnAngle = turnAngleDeg; // 根据邻域即时计算的转角，不是最终路径的转角, 仅用于计算g值
              const{ slopeT: slopeT, turnT: turnT, Vc: Vn } = this.CarWeightCost_GetCost(current, neighbor);
              neighbor.v = Vn; // 保存下一节点速度，供后续计算使用

              g = current.g + slopeT + turnT;
              if(this.potentialField && this.potentialField[neighbor.x] && Number.isFinite(this.potentialField[neighbor.x][neighbor.y])){
                h = this.potentialField[neighbor.x][neighbor.y];
              }
              h = this.CarWeightCost_Heuristic(neighbor, endPoint);
              f = this.gWeight * g + this.hWeight * h;
            }
            else{ //原始计算代价
              // 原始： const g = current.g + this.GetCost(current, neighbor); 新增转向惩罚：使用 current.parent 来计算转向惩罚（首次无惩罚）
              const baseMoveCost = this.GetCost(current, neighbor);
              const turnPen = this.turningPenalty(current.parent, current, neighbor);
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
              const MAX_ACCEPTABLE_F = 1e6;
              // 如果 f 非有限或超过阈值，跳过该邻居（等同于不可通行）
              if (!Number.isFinite(f) || f > MAX_ACCEPTABLE_F) {
                // 可选：记录日志便于调试
                // console.debug('skip neighbor due to large f', key, 'f=', f, 'slopeCost=', neighbor.slopeCost);
                continue;
              }
           }
            
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


  //获取选择点坡度（颜色）和坐标信息
  GetSlopePath() {
    if(this.slopeCostGrid.length != 0){
      let $this = this;
      let flag = 0;
      $this.keepStartPoint = null;
      $this.keepEndPoint = null;

      // var startPoint = [];
      // var endPoint = [];
      $this.handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

      $this.handler.setInputAction(function (movement) {
        var ray = viewer.camera.getPickRay(movement.position);
        var cartesian = viewer.scene.globe.pick(ray, viewer.scene);
        const pickObject = viewer.scene.pick(movement.position);
        if ($this.drawFlag && Cesium.defined(pickObject) && pickObject.primitive) {
          console.log('点击primitive的color是', pickObject.primitive.appearance.material.uniforms.color);
          //pickObject.primitive.color = Cesium.Color.BLUE;
          console.log('Primitivecolor',pickObject.primitive)
        }
        if (cartesian) {
          switch (flag) {
            case 0:
              console.log("已输入第一个点");
              $this.keepStartPoint = cartesian;
              const StartEntity = new Cesium.Entity({
                id: "slope_path_起点",
                position: cartesian,
                point: {
                  pixelSize: 10,
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
                  pixelSize: 10,
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
          $this.FindPath($this.keepStartPoint, $this.keepEndPoint);
        }
        $this.handler.destroy();
      }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
    }
    else{
      alert('请先计算区域坡度！');
    } 
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

  //绘制坡度坡向图，相同颜色的格子放在同一数组下创建Instance
  createPolygonInsrance(PosArray, colorHex, config) {
    //PosArray = aspect/slopePosArray[i]
    //const color = Cesium.Color.fromCssColorString(colorHex);
    const color = colorHex;
    let Instances = [];
    //console.log('PosArray',PosArray);//输入slopePosArray和aspectPosArray
    

    //1 创建几何实例Instance，给予形状、位置等信息
    for (let i = 0; i < PosArray.length && PosArray[i][0].length > 0; i++) {
      const polygonInstance = new Cesium.GeometryInstance({
        id: '坡度：' + PosArray[i][1] + '第' + i + '个实例',
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

    let aspectColor = []; //保存像元的[位置，颜色值，颜色编号]
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
      //根据高度差计算
      /*
          const ellipse = ellipseResults[index];
          const center = ellipse[0];
          let heightDifference = 0;
          let maxIndex = 0;
          for (let i = 1; i < ellipse.length - 1; i++) {
            const point = ellipse[i];
            let curHD = point.height - center.height;
            if (Math.abs(curHD) > heightDifference) {
              heightDifference = curHD;
              maxIndex = i;
            }
          }
          let pos0 = new Cesium.Cartographic(center.longitude, center.latitude, 0);
          let pos1 = new Cesium.Cartographic(
            ellipse[maxIndex].longitude,
            ellipse[maxIndex].latitude,
            0
          );
          let distance = Cesium.Cartesian3.distance(
            Cesium.Cartographic.toCartesian(pos0),
            Cesium.Cartographic.toCartesian(pos1)
          );
          let curSlope = Math.abs(heightDifference / distance); //坡度的tan值
          */
      //计算x方向变化率
      let positions = []; //将ellipse八方向内容转换为Cartesian格式
      let DEMheight = []; //存储分割网格的经纬高度用于绘制DEM (笛卡尔坐标系Cartesian)

      const ellipse = this.ellipseResults[index];
      //console.log("ellipse", ellipse);
      //console.log('coordinate', Cesium.Cartographic.toCartesian(ellipse[1]));

      for (let i = 1; i < ellipse.length - 1; i++) {
        positions.push(Cesium.Cartographic.toCartesian(ellipse[i]));
        DEMheight.push(Cesium.Cartographic.toCartesian(ellipse[i]));
      }

      let z1 = ellipse[1].height; //左下
      let z2 = ellipse[8].height;
      let z3 = ellipse[7].height;
      let z4 = ellipse[2].height; //左
      let z5 = ellipse[0].height; //中心点
      let z6 = ellipse[6].height;
      let z7 = ellipse[3].height;
      let z8 = ellipse[4].height;
      let z9 = ellipse[5].height;

      let fx = (z7 - z2 + 2 * (z8 - z2) + z9 - z3) / (8 * g);
      let fy = (z3 - z1 + 2 * (z6 - z4) + z9 - z7) / (8 * g);

      function angleWithXAxis(x, y) {
        let angle = Math.atan2(y, x) * (180 / Math.PI);
        // 将角度限制在 0 到 360 度之间
        angle = (angle + 360) % 360;
        return angle;
      }
      this.curSlope = Math.atan(Math.sqrt(fx * fx + fy * fy)) * (180 / Math.PI);
      this.update_curSlope();
      this.curAspect = angleWithXAxis(-fx, -fy);
      this.update_curAspect();

      if (this.drawFlag) {
        //************坡度计算值curSlope与颜色***************
        let ColorInfo = this.calculateSlopeColor(this.curSlope);
        ColorByte = Cesium.Color.fromCssColorString(ColorInfo[0]);
        ColorType = ColorInfo[1];

        this.slopePosArray[ColorType].push([positions, this.curSlope]); //Cartesian格式
        slopeColor[ColorType] = [ColorByte]; //（颜色值）

        //************坡向计算值curAspect与颜色***************
        ColorInfo = this.calculateAspectColor(this.curAspect);
        ColorByte = Cesium.Color.fromCssColorString(ColorInfo[0]);
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
      // slopeCostArray存储格式：[Cartesian坐标，坡度值，经纬高坐标，坡度代价值，单网格绘制9点数组，]
      //                        [0            ,1     ,2         ,3         ,4               ,         ]
      this.slopeCostArray.push([
        Cesium.Cartographic.toCartesian(ellipse[0]), //Cartesian坐标
        this.curSlope, //坡度值slope
        degreeCoordinate, //经纬高坐标
        [], //坡度代价值slopeCost
        positions, //单网格绘制9点数组
      ]); //只存中心点

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
      let num1 = this.slopeCostArray[i][2][0] - this.slopeCostArray[i+1][2][0];//js用15位浮点数存储，小数相减后位数会变多，需要限制
      let num2 = this.slopeCostArray[i][2][1] - this.slopeCostArray[i+1][2][1];
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
    
        let yInterval = Math.abs(this.slopeCostArray[arrayID][2][1] - (MinLatitude + latJump*latInterval));
        let xInterval = Math.abs(this.slopeCostArray[arrayID][2][0] - (MinLongitude + lonJump*lonInterval));
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

    // 是否渲染
    if(this.drawFlag){
      for (let i = 0; i < 10; i++) {
        if (this.aspectPosArray[i].length > 0) {
          this.createPolygonInsrance(this.aspectPosArray[i], aspectColor[i][0], 1);
        }
        // console.log("aspectPosArray[", i, "]", this.aspectPosArray[i]);

        if (this.slopePosArray[i].length > 0) {
          this.createPolygonInsrance(this.slopePosArray[i], slopeColor[i][0], 0);
        }
      }
    }
    
    console.timeEnd("计算时间");

    //根据config选择显示图层  1位坡度 0位坡向
    let config = this.config;
    this.slopePolygons.forEach((element) => {
      element.primitive.show = config ? true : false;
    });
    this.aspectPolygons.forEach((element) => {
      element.primitive.show = config ? false : true;
    });

//AAA 删去一段和箭头线相关的，放在末尾

    console.timeEnd("从头到尾所花时间");
    this.config = Boolean(this.config);
  }

  //根据坡度值赋值颜色
  calculateSlopeColor(value) {
    console.log(666666666666666);

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

//AAA

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
    /* 箭头添加 */
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
