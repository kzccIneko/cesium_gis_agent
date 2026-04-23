(function (global) {
  "use strict";

  /**
   * SlopeAspectGridModule
   *
   * 职责：
   * 1) 交互绘制分析多边形；
   * 2) 生成规则网格（按距离或按数量）；
   * 3) 采样地形高程并计算坡度/坡向；
   * 4) 生成 slopeCostGrid 供路径与代价模块使用。
   */
  var GridModule = {
    /**
     * 按固定网格边长（km）切分分析区。
     * @param {number} distance 网格边长，单位 km。
     * @param {boolean} config true=显示坡度，false=显示坡向。
     */
    createNew4Distance: function (distance, config) {
      if (!this.viewer) {
        console.error('[SlopeAspectGridModule] viewer 未初始化');
        return;
      }
      distance = distance || 0.05;
      this.distance = distance * 1000;
      var width = distance * 200 > 35 ? 35 : distance * 200;
      this.arrowWidth = width < 15 ? 15 : width;
      var self = this;
      var viewer = this.viewer;
      self.config = config;

      CreatePolygonOnGround(
        viewer,
        [],
        {
          color: Cesium.Color.RED.withAlpha(0.1),
          outlineColor: Cesium.Color.YELLOW,
          outlineWidth: 2,
        },
        function (polygon) {
          if (Cesium.defined(polygon)) {
            if (!polygon.pottingPoint) return;
            var degrees = self.Cartesian3ListToWGS84(polygon.pottingPoint);
            viewer.entities.remove(polygon);

            var boundary = [];
            var minX = 10000;
            var minY = 10000;
            var maxX = -10000;
            var maxY = -1000;

            for (var i = 0; i < degrees.length; i++) {
              var e = degrees[i];
              var x = e.lng;
              var y = e.lat;
              boundary.push([x, y]);
              minX = x < minX ? x : minX;
              minY = y < minY ? y : minY;
              maxX = x > maxX ? x : maxX;
              maxY = y > maxY ? y : maxY;
            }
            boundary.push(boundary[0]);

            var bbox = [minX, minY, maxX, maxY];
            var polygonBBOX = new Cesium.Entity({
              polygon: {
                hierarchy: Cesium.Cartesian3.fromDegreesArray([minX, minY, minX, maxY, maxX, maxY, maxX, minY]),
                material: Cesium.Color.BLUE.withAlpha(0.1),
              },
            });
            viewer.entities.add(polygonBBOX);

            var mask = turf.polygon([boundary]);
            var gridSquare = turf.squareGrid(bbox, distance, { mask: mask });
            self.createEllipse(gridSquare);
          }
        }
      );
    },

    /**
     * 按 num * num 的目标数量切分网格（每格边长自适应）。
     * @param {number} num 每边分割数。
     * @param {boolean} config true=显示坡度，false=显示坡向。
     */
    createNew4Num: function (num, config) {
      if (!this.viewer) {
        console.error('[SlopeAspectGridModule] viewer 未初始化');
        return;
      }
      if (!num || Number(num) <= 0) {
        alert('等分网格参数无效');
        return;
      }

      var self = this;
      var viewer = this.viewer;
      self.config = config;

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
          var degrees = self.Cartesian3ListToWGS84(polygon.pottingPoint);
          viewer.entities.remove(polygon);

          var boundary = [];
          var minX = 10000;
          var minY = 10000;
          var maxX = -10000;
          var maxY = -1000;
          for (var i = 0; i < degrees.length; i++) {
            var e = degrees[i];
            var x = e.lng;
            var y = e.lat;
            boundary.push([x, y]);
            minX = x < minX ? x : minX;
            minY = y < minY ? y : minY;
            maxX = x > maxX ? x : maxX;
            maxY = y > maxY ? y : maxY;
          }
          boundary.push(boundary[0]);

          var a = maxX - minX;
          var b = maxY - minY;
          b = b > a ? b : a;
          var step = b / num;
          var width = step * 2000 > 35 ? 35 : step * 2000;
          self.arrowWidth = width < 15 ? 15 : width;

          var mask = turf.polygon([boundary]);
          var results = [];
          var maskBbox = turf.bbox(mask);

          var generateStepGrid = function (bbox) {
            var minX2 = bbox[0];
            var minY2 = bbox[1];
            var maxX2 = bbox[2];
            var maxY2 = bbox[3];
            var grids = [];
            for (var gx = minX2; gx < maxX2; gx += step) {
              for (var gy = minY2; gy < maxY2; gy += step) {
                var xNext = Math.min(gx + step, maxX2);
                var yNext = Math.min(gy + step, maxY2);
                grids.push([gx, gy, xNext, yNext]);
              }
            }
            return grids;
          };

          var stopThreshold = step * 10;
          var processNode = function (node) {
            var cellPoly = turf.bboxPolygon(node.bbox);
            if (turf.booleanWithin(cellPoly, mask)) {
              results.push.apply(results, generateStepGrid(node.bbox));
              return;
            }
            if (!turf.intersect(cellPoly, mask)) return;

            var minX3 = node.bbox[0];
            var minY3 = node.bbox[1];
            var maxX3 = node.bbox[2];
            var maxY3 = node.bbox[3];
            var w = maxX3 - minX3;
            var h = maxY3 - minY3;

            if (w <= stopThreshold || h <= stopThreshold) {
              var cells = generateStepGrid(node.bbox);
              for (var ci = 0; ci < cells.length; ci++) {
                var cell = turf.bboxPolygon(cells[ci]);
                if (turf.intersect(cell, mask)) {
                  results.push(cells[ci]);
                }
              }
              return;
            }

            node.subdivide();
            node.children.forEach(processNode);
          };

          var root = new QuadTreeNode(maskBbox);
          processNode(root);

          var grid = turf.featureCollection(
            results.map(function (bbox) {
              return turf.bboxPolygon(bbox);
            })
          );

          self.createEllipse(grid);
        }
      );
    },

    /**
     * 对网格采样地形高程。
     *
     * 每个格子采样 10 个点（中心 + 顶点/边中点），结果写入 this.ellipseResults，
     * 然后进入 calculateSlope()。
     */
    createEllipse: function (gridSquare) {
      if (!gridSquare || !gridSquare.features || !gridSquare.features.length) {
        alert('网格为空，无法采样高程');
        return;
      }

      var boxResults = [];
      for (var index = 0; index < gridSquare.features.length; index++) {
        var feature = gridSquare.features[index];
        var coordinates = feature.geometry.coordinates[0];
        var centerdegree = [(coordinates[0][0] + coordinates[2][0]) / 2, (coordinates[0][1] + coordinates[2][1]) / 2];
        var centerCartographic = Cesium.Cartographic.fromDegrees(centerdegree[0], centerdegree[1]);
        boxResults.push(centerCartographic);

        for (var i = 0; i < coordinates.length; i++) {
          var coord = coordinates[i];
          var cartographic = Cesium.Cartographic.fromDegrees(coord[0], coord[1]);
          boxResults.push(cartographic);
          var coord1 = coordinates[i + 1];
          if (coord1) {
            var newCoord = [(coord[0] + coord1[0]) / 2, (coord[1] + coord1[1]) / 2];
            var newCartographic = Cesium.Cartographic.fromDegrees(newCoord[0], newCoord[1]);
            boxResults.push(newCartographic);
          }
        }
      }

      var self = this;
      Cesium.sampleTerrain(this.viewer.scene.terrainProvider, 13, boxResults).then(function (updatePositions) {
        var arrr = [];
        self.ellipseResults = updatePositions.reduce(function (pre, item, index2, arr) {
          var begin = index2 * 10;
          var end = begin + 10;
          var res = arr.slice(begin, end);
          if (res.length != 0) {
            arrr[index2] = res;
          }
          return arrr;
        }, []);

        self.calculateSlope();
      });
    },

    /**
     * 计算坡度/坡向并构建二维网格映射。
     *
     * 输出关键数据：
     * - this.slopeCostArray: 一维格网属性列表
     * - this.slopeCostGrid: 二维格网矩阵（路径/代价模块主输入）
     */
    calculateSlope: function () {
      if (!this.ellipseResults || this.ellipseResults.length === 0) {
        alert('高程采样结果为空，无法计算坡度');
        return;
      }

      // 每次计算前重置，避免重复调用产生历史数据污染
      this.slopeCostArray = [];
      this.slopeCostGrid = [];

      var target = this.analysisTarget || (this.config ? 'slope' : 'aspect');
      var collectSlope = this.drawFlag && target === 'slope';
      var collectAspect = this.drawFlag && target === 'aspect';

      var ColorType = [];
      var ColorByte = [];
      var aspectColor = [];
      var slopeColor = [];
      var findLongitudeRange = [];
      var findLatitudeRange = [];

      for (var index = 0; index < 10; index++) {
        this.slopePosArray[index] = [];
        this.aspectPosArray[index] = [];
      }

      var g = Cesium.Cartesian3.distance(
        Cesium.Cartographic.toCartesian(this.ellipseResults[0][0]),
        Cesium.Cartographic.toCartesian(this.ellipseResults[0][2])
      );

      for (var idx = 0; idx < this.ellipseResults.length; idx++) {
        var positions = [];
        var DEMheight = [];

        var ellipse = this.ellipseResults[idx];
        for (var i2 = 1; i2 < ellipse.length - 1; i2++) {
          positions.push(Cesium.Cartographic.toCartesian(ellipse[i2]));
          DEMheight.push(Cesium.Cartographic.toCartesian(ellipse[i2]));
        }

        var z1 = ellipse[1].height;
        var z2 = ellipse[8].height;
        var z3 = ellipse[7].height;
        var z4 = ellipse[2].height;
        var z5 = ellipse[0].height;
        var z6 = ellipse[6].height;
        var z7 = ellipse[3].height;
        var z8 = ellipse[4].height;
        var z9 = ellipse[5].height;

        var fx = (z7 - z1 + 2 * (z8 - z2) + z9 - z3) / (8 * g);
        var fy = (z3 - z1 + 2 * (z6 - z4) + z9 - z7) / (8 * g);

        var angle = Math.atan2(-fy, -fx) * (180 / Math.PI);
        angle = (angle + 360) % 360;

        this.curSlope = Math.atan(Math.sqrt(fx * fx + fy * fy)) * (180 / Math.PI);
        this.curAspect = angle;

        if (collectSlope) {
          var slopeColorInfo = this.calculateSlopeColor(this.curSlope);
          ColorByte = Cesium.Color.fromCssColorString(slopeColorInfo[0]);
          ColorType = slopeColorInfo[1];
          this.slopePosArray[ColorType].push([positions, this.curSlope]);
          slopeColor[ColorType] = [ColorByte];

          this.heightPosArray.push(DEMheight);
        }

        if (collectAspect) {
          var aspectColorInfo = this.calculateAspectColor(this.curAspect);
          ColorByte = Cesium.Color.fromCssColorString(aspectColorInfo[0]);
          ColorType = aspectColorInfo[1];
          this.aspectPosArray[ColorType].push([positions, this.curAspect]);
          aspectColor[ColorType] = [ColorByte];

          this.heightPosArray.push(DEMheight);
        }

        var longitude = Cesium.Math.toDegrees(ellipse[0].longitude);
        var fixedLon = Math.abs(Math.floor(longitude * Math.pow(10, 13)) / Math.pow(10, 13).toFixed(13));
        findLongitudeRange.push(fixedLon);

        var latitude = Cesium.Math.toDegrees(ellipse[0].latitude);
        var fixedLat = Math.abs(Math.floor(latitude * Math.pow(10, 13)) / Math.pow(10, 13).toFixed(13));
        findLatitudeRange.push(fixedLat);

        var degreeCoordinate = [longitude, latitude, ellipse[0].height];
        this.slopeCostArray.push({
          Cartesian: Cesium.Cartographic.toCartesian(ellipse[0]),
          slope: this.curSlope,
          degreeCoordinate: degreeCoordinate,
          slopeCost: 0,
          gridSquare: positions,
        });
      }

      var MaxLongitude = this.arrayMinMax(findLongitudeRange)[1];
      var MinLongitude = this.arrayMinMax(findLongitudeRange)[0];
      var MaxLatitude = this.arrayMinMax(findLatitudeRange)[1];
      var MinLatitude = this.arrayMinMax(findLatitudeRange)[0];
      var longRange = MaxLongitude - MinLongitude;
      var latRange = MaxLatitude - MinLatitude;

      var lonIntervalArray = [];
      var latIntervalArray = [];
      for (var si = 0; si < this.slopeCostArray.length - 1; si++) {
        var num1 = this.slopeCostArray[si].degreeCoordinate[0] - this.slopeCostArray[si + 1].degreeCoordinate[0];
        var num2 = this.slopeCostArray[si].degreeCoordinate[1] - this.slopeCostArray[si + 1].degreeCoordinate[1];
        if (num1 !== 0) lonIntervalArray.push(Math.abs(Math.floor(num1 * Math.pow(10, 13)) / Math.pow(10, 13).toFixed(13)));
        if (num2 !== 0) latIntervalArray.push(Math.abs(Math.floor(num2 * Math.pow(10, 13)) / Math.pow(10, 13).toFixed(13)));
      }

      var lonInterval = this.arrayMinMax(lonIntervalArray)[0];
      var latInterval = this.arrayMinMax(latIntervalArray)[0];
      var lonX = Math.round(latRange / latInterval) + 1;
      var latY = Math.round(longRange / lonInterval) + 1;

      for (var gi = 0; gi < latY; gi++) {
        this.slopeCostGrid[gi] = [];
        for (var gj = 0; gj < lonX; gj++) {
          this.slopeCostGrid[gi][gj] = [];
        }
      }

      var latJump = 0;
      var lonJump = 0;
      var arrayID = 0;

      for (var r = 0; r < latY; r++) {
        latJump = 0;
        for (var c = 0; c < lonX; c++) {
          var yInterval = Math.abs(this.slopeCostArray[arrayID].degreeCoordinate[1] - (MinLatitude + latJump * latInterval));
          var xInterval = Math.abs(this.slopeCostArray[arrayID].degreeCoordinate[0] - (MinLongitude + lonJump * lonInterval));

          if (xInterval < 0.05 * lonInterval && yInterval < 0.05 * latInterval && this.slopeCostArray[arrayID + 1] !== undefined) {
            this.slopeCostGrid[r][c] = this.slopeCostArray[arrayID];
            arrayID++;
            latJump++;
          } else if (this.slopeCostArray[arrayID + 1] == undefined) {
            this.slopeCostGrid[r][c] = this.slopeCostArray[arrayID];
            latJump++;
          } else {
            this.slopeCostGrid[r][c] = [];
            latJump++;
          }
        }
        lonJump++;
      }

      var drawSlope = this.drawFlag && target === 'slope';
      var drawAspect = this.drawFlag && target === 'aspect';

      if (drawSlope || drawAspect) {
        for (var ci2 = 0; ci2 < 10; ci2++) {
          if (drawAspect && this.aspectPosArray[ci2].length > 0) {
            this.createPolygonInstance(this.aspectPosArray[ci2], aspectColor[ci2][0], 1);
          }
          if (drawSlope && this.slopePosArray[ci2].length > 0) {
            this.createPolygonInstance(this.slopePosArray[ci2], slopeColor[ci2][0], 0);
          }
        }
      }

      this.slopePolygons.forEach(function (element) {
        element.primitive.show = drawSlope;
      });
      this.aspectPolygons.forEach(function (element) {
        element.primitive.show = drawAspect;
      });

      this.DrawCostMap({
        renderLayer: target === 'cost',
        visible: target === 'cost',
      });
      this.config = target === 'slope';
    },
  };

  global.SlopeAspectGridModule = GridModule;
})(window);
