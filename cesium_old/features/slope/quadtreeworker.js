importScripts("../turf/turf.min.js");
// importScripts("../Cesium-1.93/Build/Cesium/Cesium.js");
// const Cesium = require("../Cesium-1.93/Build/Cesium/Cesium.js");
// const turf = require("../turf/turf.min.js");
// var terrainProvider = new Cesium.CesiumTerrainProvider({
//   url: "http://127.0.0.1:5501/data/terrain",
// });
// var positions = Cesium.Cartographic.fromDegrees(101.9644, 29.631937);
// Cesium.sampleTerrain(terrainProvider, 13, [positions]).then((result) => {
//   console.log(result);
// });

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

self.onmessage = function (e) {
  //   console.log(213123);
  console.time("woker");
  //   console.log("hdushdiu");
  const [step, mask, bbox2] = e.data;
  //   const rootBbox = [bbox2[0], (bbox2[1] + bbox2[3]) / 2, bbox2[2], bbox2[3]];
  const results = [];
  const stopThreshold = step * 10; // 停止分割阈值
  const node2 = new QuadTreeNode(bbox2);
  //   const node3 = new QuadTreeNode(bbox3);
  //   const node4 = new QuadTreeNode(bbox4);
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
  //   processNode(node2);
  node2.subdivide();
  node2.children.splice(0, 2).forEach(processNode);
  //   processNode(node3);
  //   processNode(node4);
  console.timeEnd("woker");
  self.postMessage(results);
};
