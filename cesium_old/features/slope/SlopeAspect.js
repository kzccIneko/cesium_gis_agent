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

let colorMap = document.querySelector("#slope-color");

const ramp = document.createElement("canvas");
ramp.width = 400;
ramp.height = 30;
const ctx = ramp.getContext("2d");
// let values= [0.0, 0.29, 0.5, Math.sqrt(2) / 2, 0.87, 0.91, 1.0];
let values = [0.0, 0.082, 0.18, 0.27, 0.33, 0.39, 0.46, 0.54, 0.78, 1];
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
  ctx.fillText(value.toFixed(2), x - 20, 20); // 标识文字位置
});

colorMap.appendChild(ramp);

const ramp2 = document.createElement("canvas");
ramp2.style.display = "block";
ramp.style.display = "block";
ramp2.width = 400;
ramp2.height = 30;
const ctx2 = ramp2.getContext("2d");

let values2 = [0.0, 0.001, 0.0625, 0.1875, 0.3125, 0.4375, 0.5625, 0.6875, 0.8125, 0.9375, 1];
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
  ctx2.fillText(value.toFixed(2), x - 20, 20); // 标识文字位置
});
const originalElement = document.querySelector("#slopeRange");
// console.log(originalElement);
const clonedElement = originalElement.cloneNode();
clonedElement.value = "坡向0-360";
colorMap.appendChild(clonedElement);
colorMap.appendChild(ramp2);

class SlopeAspect {
  constructor(viewer) {
    if (!viewer) throw new Error("no viewer object!");
    this.viewer = viewer;
    this.result = []; //存储创建的坡度分析结果，primitive集合
    this.handler = undefined;
    this.toolTip = "";
    this.config = null;
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
  //等距离切分网格
  createNew4Distance(distance) {
    distance = distance || 0.01; //默认0.1km精度
    let width = distance * 200 > 35 ? 35 : distance * 200;
    this.arrowWidth = width < 15 ? 15 : width;
    const $this = this;
    const viewer = this.viewer;
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
        let bbox = [minX, minY, maxX, maxY];
        let mask = turf.polygon([boundary]);
        let gridSquare = turf.squareGrid(bbox, distance, { mask: mask });
        $this.createEllipse(gridSquare);
      }
    );
  }
  // 等分切分网格，切分成一个num*num的网格
  createNew4Num(num, config) {
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
        console.time("从头到尾所花时间");

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
        root.subdivide();
        const [child1, child2, child3, child4] = root.children;
        //多线程quadtreeworker
        // const taskProcessor = new Cesium.TaskProcessor(
        //   "http://127.0.0.1:5501/libs/slope/quadtreeworker.js"
        // );
        // const promise = taskProcessor.scheduleTask({
        //   someParameter: true,
        //   another: "hello",
        // });
        // if (!Cesium.defined(promise)) {
        //   // too many active tasks - try again later
        // } else {
        //   promise.then(function (result) {
        //     // use the result of the task
        //   });
        // }

        const worker = new Worker(
          "http://127.0.0.1:5501/libs/slope/quadtreeworker.js"   //127.0.0.1是计算机本地回环地址，也叫localhost
        );
        // const workerTask = new Promise((resolve, reject) => {
        //   worker.postMessage([
        //     step,
        //     mask,
        //     child2.bbox,
        //     child3.bbox,
        //     child4.bbox,
        //   ]);
        //   worker.onmessage = (e) => {
        //     console.timeEnd("分割网格所需时间");
        //     const grid = turf.featureCollection(
        //       e.data.map((bbox) => turf.bboxPolygon(bbox))
        //     );
        //     $this.createEllipse(grid);

        //     resolve(e.data);
        //   };
        // });

        worker.postMessage([step, mask, root.bbox]);
        worker.onmessage = (e) => {
          console.timeEnd("分割网格所需时间");
          const grid = turf.featureCollection(
            e.data.map((bbox) => turf.bboxPolygon(bbox))
          );
          $this.createEllipse(grid);
        };

        // workerTask.then((data) => {
        //   //   console.log(1122);

        //   let res = results.concat(data);
        //   // 7. 结果可视化
        //   console.time("生成网格");
        //   const grid = turf.featureCollection(
        //     res.map((bbox) => turf.bboxPolygon(bbox))
        //   );
        //   console.timeEnd("生成网格");
        //   //测试

        //   // // 3. 生成原始网格（不带mask）
        //   // console.time("生成原始网格所需时间");
        //   // // const grid = turf.squareGrid(bbox, step, { units: "degrees" });
        //   // console.timeEnd("生成原始网格所需时间");

        //   // 5. 创建最终网格
        //   // grid.features = filteredFeatures;
        //   $this.createEllipse(grid);
        // });
        console.time("浏览器堵塞时间");
        processNode(child3);
        processNode(child4);

        const grid = turf.featureCollection(
          results.map((bbox) => turf.bboxPolygon(bbox))
        );
        $this.createEllipse(grid);

        console.timeEnd("浏览器堵塞时间");
        // 创建Worker池
      }
    );
  }
  createEllipse(gridSquare) {
    let boxResults = [];
    // console.log(gridSquare);
    for (let index = 0; index < gridSquare.features.length; index++) {
      const feature = gridSquare.features[index];
      const coordinates = feature.geometry.coordinates[0];
      // console.log(coordinates);
      const centerdegree = [
        (coordinates[0][0] + coordinates[2][0]) / 2,
        (coordinates[0][1] + coordinates[2][1]) / 2,
      ];
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
    //计算当前层级
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
      let ellipseResults = updatePositions.reduce(function (
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

      this.calculateSlope(ellipseResults);
    });
  }

  createPolygonInsrance(points, color = "rgb(19, 7, 7)") {
    let positions = [];
    for (let index = 1; index < points.length - 1; index++) {
      const element = points[index];
      positions.push(Cesium.Cartographic.toCartesian(element));
    }
    let polygon = new Cesium.PolygonGeometry({
      polygonHierarchy: new Cesium.PolygonHierarchy(positions),
    });

    let polygonInstance = new Cesium.GeometryInstance({
      geometry: polygon,
      attributes: {
        color: Cesium.ColorGeometryInstanceAttribute.fromColor(
          Cesium.Color.fromCssColorString(color)
        ),
        show: new Cesium.ShowGeometryInstanceAttribute(true), //显示或者隐藏
      },
    });
    return polygonInstance;
  }
  // createArrowInstance(
  //   targetPoint,
  //   center,
  //   diagonalPoint,
  //   heightDifference,
  //   curSlope
  // ) {
  //   let cartographic_0 = new Cesium.Cartographic(
  //     (targetPoint.longitude + center.longitude) / 2,
  //     (targetPoint.latitude + center.latitude) / 2,
  //     (targetPoint.height + center.height) / 2
  //   );
  //   let cartographic_1 = new Cesium.Cartographic(
  //     (diagonalPoint.longitude + center.longitude) / 2,
  //     (diagonalPoint.latitude + center.latitude) / 2,
  //     (diagonalPoint.height + center.height) / 2
  //   );
  //   //偏移的
  //   let positions1 =
  //     heightDifference > 0
  //       ? [
  //         Cesium.Cartographic.toCartesian(cartographic_0),
  //         Cesium.Cartographic.toCartesian(cartographic_1),
  //       ]
  //       : [
  //         Cesium.Cartographic.toCartesian(cartographic_1),
  //         Cesium.Cartographic.toCartesian(cartographic_0),
  //       ];
  //   //箭头线
  //   const instance = new Cesium.GeometryInstance({
  //     id: {
  //       type: "SlopeAspect",
  //       value: curSlope,
  //     },
  //     geometry: new Cesium.GroundPolylineGeometry({
  //       positions: positions1,
  //       width: this.arrowWidth,
  //     }),
  //     attributes: {
  //       color: Cesium.ColorGeometryInstanceAttribute.fromColor(
  //         Cesium.Color.BLUE.withAlpha(0.6)
  //       ),
  //       show: new Cesium.ShowGeometryInstanceAttribute(true), //显示或者隐藏
  //     },
  //   });
  //   return instance;
  // }
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
  calculateSlope(ellipseResults) {
    // console.log(ellipseResults);
    // let newEllipse = ellipseResults.map((item)=>{
    //   let height;
    //   return height = viewer.scene.globe.getHeight(item)
    // })
    // console.log(newEllipse);
    // console.log(ellipseResults[0][1].height);
    // console.log(ellipseResults[0][1]);
    //计算分辨率g，点的分布是[5,1,4,7,8,9,6,3,2,1]
    let g = Cesium.Cartesian3.distance(
      Cesium.Cartographic.toCartesian(ellipseResults[0][0]),
      Cesium.Cartographic.toCartesian(ellipseResults[0][2])
    );
    // console.log(g);
    let instances = [];
    let polygonInstance = [];
    let aspectInstance = [];
    let results = [];
    console.time("计算时间");
    for (let index = 0; index < ellipseResults.length; index++) {
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
      let maxIndex = 0;
      //计算x方向变化率
      const ellipse = ellipseResults[index];
      let z1 = ellipse[1].height;
      let z2 = ellipse[8].height;
      let z3 = ellipse[7].height;
      let z4 = ellipse[2].height;
      let z5 = ellipse[0].height;
      let z6 = ellipse[6].height;
      let z7 = ellipse[3].height;
      let z8 = ellipse[4].height;
      let z9 = ellipse[5].height;

      let fx = (z7 - z2 + 2 * (z8 - z2) + z9 - z3) / (8 * g);
      let fy = (z3 - z1 + 2 * (z6 - z4) + z9 - z7) / (8 * g);
      // console.log(fx,fy);

      function angleWithXAxis(x, y) {
        let angle = Math.atan2(y, x) * (180 / Math.PI);
        // 将角度限制在 0 到 360 度之间
        angle = (angle + 360) % 360;
        return angle;
      }

      //坡度计算值与颜色
      let curSlope = Math.sqrt(fx * fx + fy * fy);
      curSlope = Math.atan(curSlope) * (180 / Math.PI);

      let curColor = this.calculateSlopeColor(curSlope, 1);
      const curPolygonInstance = this.createPolygonInsrance(ellipse, curColor);
      polygonInstance.push(curPolygonInstance);
      //坡向计算值与颜色
      let curAspect = angleWithXAxis(-fx, -fy);
      let aspectColor = this.calculateAspectColor(curAspect, 1);
      if (index % 100 == 0) {
        results.push([
          curSlope,
          Cesium.Math.toDegrees(ellipse[0].longitude),
          Cesium.Math.toDegrees(ellipse[0].latitude),
        ]);
      }
      const curPolygonInstance2 = this.createPolygonInsrance(
        ellipse,
        aspectColor
      );
      aspectInstance.push(curPolygonInstance2);
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
      /* 根据config选择
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
    console.timeEnd("计算时间");
    //根据config选择  1位坡度 0位坡向
    // console.log(results.toString());
    // 在收集完数据后调用这个函数
    function downloadCSV() {
      // 创建CSV内容（添加表头）
      const csvContent = [
        ["slope", "longitude", "latitude"], // 列标题
        ...results, // 你的数据
      ]
        .map((row) => row.join(","))
        .join("\n");

      // 创建Blob文件
      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });

      // 创建下载链接
      const link = document.createElement("a");
      const url = URL.createObjectURL(blob);
      link.href = url;
      link.download = "terrain_data.csv"; // 文件名

      // 触发下载
      document.body.appendChild(link);
      link.click();

      // 清理资源
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }

    // 当数据收集完成后调用
    downloadCSV();

    let config = this.config;
    // console.log(config);

    const mapPrimitive2 = new Cesium.GroundPrimitive({
      geometryInstances: aspectInstance,
      appearance: new Cesium.PerInstanceColorAppearance({
        translucent: true, //false时透明度无效
        closed: false,
      }),
    });

    const mapPrimitive1 = new Cesium.GroundPrimitive({
      geometryInstances: polygonInstance,
      appearance: new Cesium.PerInstanceColorAppearance({
        translucent: true, //false时透明度无效
        closed: false,
      }),
    });
    mapPrimitive1.show = config ? true : false;
    mapPrimitive2.show = !mapPrimitive1.show;
    // this.viewer.scene.primitives.add(config? mapPrimitive1: mapPrimitive2 );
    this.viewer.scene.primitives.add(mapPrimitive1);
    this.viewer.scene.primitives.add(mapPrimitive2);
    // console.log(this.viewer.scene.primitives);
    console.timeEnd("从头到尾所花时间");
    // const mapPrimitive2 = this.viewer.scene.primitives.add(
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
    // this.result.push(arrowPrimitive, mapPrimitive);
    this.result.push(mapPrimitive1, mapPrimitive2);
    this.config = Boolean(this.config);
  }
  clearAll() {
    // console.log(this.result);
    // console.log(this);

    console.log("clear");

    this.result.forEach((element) => {
      this.viewer.scene.primitives.remove(element);
    });
    this.result = [];
  }
  toggle() {
    // this.config = !this.config;

    // console.log(this.config);
    const [mapPrimitive1, mapPrimitive2] = this.result;
    mapPrimitive1.show = !mapPrimitive1.show;
    mapPrimitive2.show = !mapPrimitive2.show;

    // if(this.config){
    //   this.viewer.scene.primitives.add(this.result[0]);

    //   // this.viewer.scene.primitives.remove(this.result[1]);
    //   console.log(this.result);

    // }else{
    //   // this.viewer.scene.primitives.remove(this.result[0]);
    //   this.viewer.scene.primitives.add(this.result[1]);
    // }
  }
  //根据坡度值赋值颜色
  calculateSlopeColor(value, alpha) {
    /*     // 0°～0.5°为平原0.00872686779075879,rgb(85,182,43)
         // 0.5°～2°为微斜坡0.03492076949174773,rgb(135,211,43)
         // 2°～5°为缓斜坡0.08748866352592401,rgb(204,244,44)
         // 5°～15°为斜坡0.2679491924311227,rgb(245,233,44)
         // 15°～35°为陡坡0.7002075382097097,rgb(255,138,43)
         // 35°～55°为峭坡1.4281480067421144,rgb(255,84,43)
         // 55°～90°为垂直壁,rgb(255,32,43)
         // if (value < 0.00872686779075879) {
         //   return "rgba(85,182,43," + alpha + ")";
         // } else if (value < 0.03492076949174773) {
         //   return "rgba(135,211,43," + alpha + ")";
         // } else if (value < 0.08748866352592401) {
         //   return "rgba(204,244,44," + alpha + ")";
         // } else if (value < 0.2679491924311227) {
         //   return "rgba(245,233,44," + alpha + ")";
         // } else if (value < 0.7002075382097097) {
         //   return "rgba(255,138,43," + alpha + ")";
         // } else if (value < 1.4281480067421144) {
         //   return "rgba(255,84,43," + alpha + ")";
         // } else {
         //   return "rgba(255,32,43," + alpha + ")";
         // }
         // if (value < 0.00872686779075879) {
         //   return "rgba(0,255,128," + alpha + ")";
         // } else if (value < 0.03492076949174773) {
         //   return "rgba(0,255,9," + alpha + ")";
         // } else if (value < 0.08748866352592401) {
         //   return "rgba(255,255,00," + alpha + ")";
         // } else if (value < 0.2679491924311227) {
         //   return "rgba(255,137,00" + alpha + ")";
         // } else if (value < 0.7002075382097097) {
         //   return "rgba(255,94,00," + alpha + ")";
         // } else if (value < 1.4281480067421144) {
         //   return "rgba(255,43,00," + alpha + ")";
         // } else {
         //   return "rgba(255,00,00," + alpha + ")";
         // }*/

    /* 使用画布
        const normalizedValue = Math.min(1, Math.max(0, value / 90));
   
   // 从Canvas上获取对应位置的颜色
   const imageData = ctx.getImageData(Math.round(normalizedValue * (ramp.width - 1)), 0, 1, 1).data;
   // console.log(imageData);
   // 将颜色转换为rgba字符串
   const color = `rgba(${imageData[0]}, ${imageData[1]}, ${imageData[2]}, ${alpha})`;
   // console.log(normalizedValue);
   // console.log(color);
   return color;
      */

    let color;
    if (value <= 7.4) {
      return (color = "rgba(56,168,0," + alpha + ")");
    } else if (value < 16.568) {
      return (color = "rgba(94,189,0," + alpha + ")");
    } else if (value < 23.971) {
      return (color = "rgba(139,209,0," + alpha + ")");
    } else if (value < 29.96) {
      return (color = "rgba(193,232,0," + alpha + ")");
    } else if (value < 35.25) {
      return (color = "rgba(255,255,0," + alpha + ")");
    } else if (value < 41.244) {
      return (color = "rgba(255,191,0," + alpha + ")");
    } else if (value < 49) {
      return (color = "rgba(255,128,0," + alpha + ")");
    } else if (value < 70.5) {
      return (color = "rgba(255,64,0," + alpha + ")");
    } else if (value < 89) {
      return (color = "rgba(255,0,0," + alpha + ")");
    } else if (value <= 91) {
      return (color = "rgba(255,0,0," + alpha + ")");
    }
  }
  calculateAspectColor(value, alpha) {
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
      return (color = "rgba(176,176,176," + alpha + ")");
    } else if (value < 22.5) {
      return (color = "rgba(255,0,0," + alpha + ")");
    } else if (value < 67.5) {
      return (color = "rgba(255,166,0," + alpha + ")");
    } else if (value < 112.5) {
      return (color = "rgba(255,255,0," + alpha + ")");
    } else if (value < 157.5) {
      return (color = "rgba(0,255,0," + alpha + ")");
    } else if (value < 202.5) {
      return (color = "rgba(0,255,255," + alpha + ")");
    } else if (value < 247.5) {
      return (color = "rgba(0,166,255," + alpha + ")");
    } else if (value < 292.5) {
      return (color = "rgba(0,0,255," + alpha + ")");
    } else if (value < 337.5) {
      return (color = "rgba(255,0,255," + alpha + ")");
    } else if (value <= 360) {
      return (color = "rgba(255,0,0," + alpha + ")");
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
// export default SlopeAspect;
