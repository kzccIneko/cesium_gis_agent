(function (global) {
  "use strict";

  /**
   * SlopeAspectPathModule
   *
   * 提供路径规划与路径可视化能力：
   * - A* 主路径搜索
   * - RRT 备选搜索
   * - 鼠标交互取起终点
   * - 路径线与路径点绘制
   * - 路径列表 UI 同步
   */
  var PathModule = {
    /**
     * A* 路径规划主入口。
     *
     * 说明：
     * - 先把输入起终点吸附到最近可用网格；
     * - 根据配置选择不同代价模型（基础/AHP/等效时间）；
     * - 搜索成功后回溯路径并调用 DrawPath()。
     */
    FindPath_AStar: function (startPoint, endPoint) {
      var NodeCtor = global.findPathNode || (typeof findPathNode !== 'undefined' ? findPathNode : null);
      if (!NodeCtor) {
        console.error('[SlopeAspectPathModule] findPathNode 未定义，无法执行 A*');
        alert('路径节点构造器缺失，无法执行寻路');
        return;
      }

      startPoint = startPoint || [];
      endPoint = endPoint || [];
      var d1 = [];
      var d2 = [];
      var startx = -1;
      var starty = -1;
      var endx = -1;
      var endy = -1;
      this.pathPoints[this.pathLineNum] = [];
      var openList = [];
      var closeList = new Set();
      var nodeInfoMap = new Map();

      if (!startPoint || !endPoint) {
        alert('起点或终点无效，无法寻路');
        return;
      }

      var startstartPoint = startPoint;
      var endendPoint = endPoint;
      var startCarto = Cesium.Cartographic.fromCartesian(startstartPoint);
      var endCarto = Cesium.Cartographic.fromCartesian(endendPoint);

      for (var i = 0; i < this.slopeCostGrid.length; i++) {
        for (var j = 0; j < this.slopeCostGrid[i].length; j++) {
          if (this.slopeCostGrid[i][j].length != 0) {
            d2 = Cesium.Cartesian3.distance(this.slopeCostGrid[i][j].Cartesian, endPoint);
            d1 = Cesium.Cartesian3.distance(this.slopeCostGrid[i][j].Cartesian, startPoint);
            if (d1 < (this.distance * Math.sqrt(2)) / 2 && startx == -1 && starty == -1) {
              startPoint = { x: i, y: j, z: this.slopeCostGrid[i][j].degreeCoordinate[2], Cartesian3Grid: this.slopeCostGrid[i][j].Cartesian };
              startx = i;
              starty = j;
            }
            if (d2 < (this.distance * Math.sqrt(2)) / 2 && endx == -1 && endy == -1) {
              endPoint = { x: i, y: j, z: this.slopeCostGrid[i][j].degreeCoordinate[2], Cartesian3Grid: this.slopeCostGrid[i][j].Cartesian };
              endx = i;
              endy = j;
            }
          }
        }
      }
      console.log('startPoint', startPoint, 'endPoint', endPoint);

      if (this.usePotentialFieldFlag && startx !== -1 && endx !== -1) {
        try {
          this.potentialField = this.computePotentialField({ x: endx, y: endy });
          console.log('potentialField', this.potentialField);
        } catch (e) {
          console.error('预计算 potentialField 失败，回退到几何启发式', e);
          console.log('this.potentialField', this.potentialField);
          this.potentialField = null;
        }
      }

      var startTime = performance.now();
      if (startx === -1 || starty === -1 || endx === -1 || endy === -1) {
        alert('未找到有效网格起终点，请检查点位是否在分析网格范围内');
        return;
      }

      openList = [new NodeCtor(startPoint.x, startPoint.y, startPoint.z, startPoint.Cartesian3Grid)];

      while (openList.length > 0) {
        var currentIndex = 0;
        for (var oi = 1; oi < openList.length; oi++) {
          if (
            openList[oi].f > 0 &&
            openList[oi].f < openList[currentIndex].f &&
            openList[oi].f < 10000 &&
            openList[currentIndex].f < 10000 &&
            Number.isFinite(openList[oi].f) &&
            openList[oi].h < openList[currentIndex].h
          ) {
            currentIndex = oi;
          }
        }

        var current = openList[currentIndex];
        var currentKey = current.x + ',' + current.y;

        if (current.x === endPoint.x && current.y === endPoint.y) {
          this.pathPoints[this.pathLineNum] = [];
          var temp = current;
          while (temp) {
            this.pathPoints[this.pathLineNum].unshift({
              x: temp.x,
              y: temp.y,
              z: temp.z,
              slope: temp.slope,
              v: temp.v,
              turnAngle: temp.turnAngle,
              g: temp.g,
              h: temp.h,
              f: temp.f,
              Cartesian3Grid: temp.Cartesian3Grid,
            });
            temp = temp.parent;
          }

          if (this.equTimeCostV) {
            for (var ti = 0; ti < this.pathPoints[this.pathLineNum].length - 1; ti++) {
              var node = this.pathPoints[this.pathLineNum][ti];
              var next = this.pathPoints[this.pathLineNum][ti + 1];
              if (!Number.isFinite(node.turnAngle)) {
                node.turnAngle = next.turnAngle;
              }
            }
          }

          var pathPoint1 = this.pathPoints[this.pathLineNum][0];
          var pathPoint2 = this.pathPoints[this.pathLineNum][1];
          var pathPoint3 = this.pathPoints[this.pathLineNum][this.pathPoints[this.pathLineNum].length - 1];
          var pathPoint4 = this.pathPoints[this.pathLineNum][this.pathPoints[this.pathLineNum].length - 2];
          var pathPoint1Carto = Cesium.Cartographic.fromCartesian(pathPoint1.Cartesian3Grid);
          var pathPoint2Carto = Cesium.Cartographic.fromCartesian(pathPoint2.Cartesian3Grid);
          var pathPoint3Carto = Cesium.Cartographic.fromCartesian(pathPoint3.Cartesian3Grid);
          var pathPoint4Carto = Cesium.Cartographic.fromCartesian(pathPoint4.Cartesian3Grid);

          var S1direction;
          var S2direction;
          var E1direction;
          var E2direction;

          if (startCarto.longitude < pathPoint1Carto.longitude && startCarto.latitude < pathPoint1Carto.latitude) S1direction = 'NE';
          else if (startCarto.longitude < pathPoint1Carto.longitude && startCarto.latitude > pathPoint1Carto.latitude) S1direction = 'SE';
          else if (startCarto.longitude > pathPoint1Carto.longitude && startCarto.latitude < pathPoint1Carto.latitude) S1direction = 'NW';
          else if (startCarto.longitude > pathPoint1Carto.longitude && startCarto.latitude > pathPoint1Carto.latitude) S1direction = 'SW';

          if (startCarto.longitude < pathPoint2Carto.longitude && startCarto.latitude < pathPoint2Carto.latitude) S2direction = 'NE';
          else if (startCarto.longitude < pathPoint2Carto.longitude && startCarto.latitude > pathPoint2Carto.latitude) S2direction = 'SE';
          else if (startCarto.longitude > pathPoint2Carto.longitude && startCarto.latitude < pathPoint2Carto.latitude) S2direction = 'NW';
          else if (startCarto.longitude > pathPoint2Carto.longitude && startCarto.latitude > pathPoint2Carto.latitude) S2direction = 'SW';

          if (endCarto.longitude < pathPoint3Carto.longitude && endCarto.latitude < pathPoint3Carto.latitude) E1direction = 'NE';
          else if (endCarto.longitude < pathPoint3Carto.longitude && endCarto.latitude > pathPoint3Carto.latitude) E1direction = 'SE';
          else if (endCarto.longitude > pathPoint3Carto.longitude && endCarto.latitude < pathPoint3Carto.latitude) E1direction = 'NW';
          else if (endCarto.longitude > pathPoint3Carto.longitude && endCarto.latitude > pathPoint3Carto.latitude) E1direction = 'SW';

          if (endCarto.longitude < pathPoint4Carto.longitude && endCarto.latitude < pathPoint4Carto.latitude) E2direction = 'NE';
          else if (endCarto.longitude < pathPoint4Carto.longitude && endCarto.latitude > pathPoint4Carto.latitude) E2direction = 'SE';
          else if (endCarto.longitude > pathPoint4Carto.longitude && endCarto.latitude < pathPoint4Carto.latitude) E2direction = 'NW';
          else if (endCarto.longitude > pathPoint4Carto.longitude && endCarto.latitude > pathPoint4Carto.latitude) E2direction = 'SW';

          if (S1direction != S2direction) this.pathPoints[this.pathLineNum].shift();
          if (E1direction != E2direction) this.pathPoints[this.pathLineNum].pop();

          this.pathPoints[this.pathLineNum].push({ x: 0, y: 0, z: 0, Cartesian3Grid: endendPoint });
          this.pathPoints[this.pathLineNum].unshift({ x: 0, y: 0, z: 0, Cartesian3Grid: startstartPoint });

          var endTime = performance.now();
          console.log('找到路径！路径长度：' + this.pathPoints[this.pathLineNum].length + '，搜索时间：' + Math.round(endTime - startTime) + 'ms，搜索节点数：' + closeList.size);

          this.DrawPath();
          return;
        }

        openList.splice(currentIndex, 1);
        closeList.add(currentKey);

        var neighbors = this.GetNeighbors(current);
        for (var ni3 = 0; ni3 < neighbors.length; ni3++) {
          var neighbor = neighbors[ni3];
          var key = neighbor.x + ',' + neighbor.y;
          if (closeList.has(key)) continue;

          var g;
          var h;
          var f;

          if (this.equTimeCostV) {
            if (typeof this.GetCost_CarWeightCost_BaseV !== 'function' || typeof this.Heuristic_CarWeightCost_BaseV !== 'function') {
              console.warn('[SlopeAspectPathModule] 等效时间(BaseV)函数未定义，自动回退到基础代价模型');
              this.equTimeCostV = false;
            }

            if (!this.equTimeCostV) {
              var baseMoveCost2 = this.GetCost(current, neighbor);
              var turnPen2 = (this.computeTurnAngle(current.parent, current, neighbor) / 180) * 20;
              g = current.g + baseMoveCost2 + turnPen2;
              if (this.potentialField && this.potentialField[neighbor.x] && Number.isFinite(this.potentialField[neighbor.x][neighbor.y])) {
                h = this.potentialField[neighbor.x][neighbor.y];
              } else {
                h = this.Heuristic(neighbor, endPoint);
              }
              f = this.gWeight * g + this.hWeight * h;
            } else {
            var turnAngleDeg = this.computeTurnAngle(current.parent, current, neighbor);
            neighbor.turnAngle = turnAngleDeg;
            var result = this.GetCost_CarWeightCost_BaseV(current, neighbor);
            neighbor.v = result.Vc;
            g = current.g + result.slopeT + result.turnT;
            if (this.potentialField && this.potentialField[neighbor.x] && Number.isFinite(this.potentialField[neighbor.x][neighbor.y])) {
              h = this.potentialField[neighbor.x][neighbor.y];
            }
            h = this.Heuristic_CarWeightCost_BaseV(neighbor, endPoint);
            f = this.gWeight * g + this.hWeight * h;
            }
          } else if (this.equTimeCostDragF) {
            var turnAngleDeg2 = this.computeTurnAngle(current.parent, current, neighbor);
            neighbor.turnAngle = turnAngleDeg2;
            var result2 = this.GetCost_CarWeightCost_BaseDragF(current, neighbor);
            neighbor.v = result2.Vc;
            g = current.g + result2.slopeT + result2.turnT;
            h = this.Heuristic_CarWeightCost_BaseDragF(neighbor, endPoint);
            f = this.gWeight * g + this.hWeight * h;
          } else if (this.useAHPMethod) {
            var turnAngleDeg3 = this.computeTurnAngle(current.parent, current, neighbor);
            var delta_g = this.AHP_GetCost(current, neighbor);
            g = current.g + delta_g;
            if (turnAngleDeg3 == 45 || turnAngleDeg3 == 135) g = g + delta_g * 0.414;
            else if (turnAngleDeg3 == 90) g = g + delta_g * 0.828;
            h = this.AHP_Heuristic(neighbor, endPoint, startx, starty, endx, endy) / 25;
            f = this.gWeight * g + this.hWeight * h;
          } else {
            var baseMoveCost = this.GetCost(current, neighbor);
            var turnPen = (this.computeTurnAngle(current.parent, current, neighbor) / 180) * 20;
            g = current.g + baseMoveCost + turnPen;
            if (this.potentialField && this.potentialField[neighbor.x] && Number.isFinite(this.potentialField[neighbor.x][neighbor.y])) {
              h = this.potentialField[neighbor.x][neighbor.y];
            } else {
              h = this.Heuristic(neighbor, endPoint);
            }
            f = this.gWeight * g + this.hWeight * h;
          }

          var MAX_ACCEPTABLE_F = 1e5;
          if (!Number.isFinite(f) || f > MAX_ACCEPTABLE_F) continue;

          nodeInfoMap.set(key, { g: g, h: h, f: f });

          var inOpen = false;
          for (var oi2 = 0; oi2 < openList.length; oi2++) {
            var node2 = openList[oi2];
            if (node2.x === neighbor.x && node2.y === neighbor.y) {
              inOpen = true;
              if (g < node2.g) {
                node2.g = g;
                node2.f = f;
                node2.parent = current;
                nodeInfoMap.set(key, { g: g, h: h, f: f });
              }
              break;
            }
          }

          if (!inOpen) {
            neighbor.g = g;
            neighbor.h = h;
            neighbor.f = f;
            neighbor.parent = current;
            openList.push(neighbor);
          }
        }
      }

      alert('未找到可行路径！');
      console.log('pathPoint', this.pathPoints);
      console.log('slopeCostGrid', this.slopeCostGrid);
    },

    /**
     * RRT 路径规划入口（可选算法分支）。
     */
    FindPath_RRT: function () {
      if (typeof RRT_PathPlanner === 'undefined') {
        console.error('[SlopeAspectPathModule] RRT_PathPlanner 未定义');
        alert('RRT 算法模块未加载');
        return;
      }

      var rrt = new RRT_PathPlanner(window.SlopeAnalysis, {
        maxIterations: 5000,
        stepSize: 2,
        goalThreshold: 1.5,
        maxSlopeCost: 10,
        biasToGoal: 0.1,
      });
      var path = rrt.findPath(this.keepStartPoint, this.keepEndPoint);
      if (path) {
        this.pathPoints[this.pathLineNum] = path;
        this.DrawPath();
      }
      return;
    },

    /**
     * 交互获取起终点：
     * - 左键依次取起点/终点
     * - 右键触发寻路
     */
    GetSlopePath: function () {
      if (this.slopeCostGrid.length != 0) {
        var self = this;
        var viewer = self.viewer;
        if (!viewer) {
          alert('viewer 未初始化，无法取点');
          return;
        }

        var flag = 0;
        self.keepStartPoint = null;
        self.keepEndPoint = null;

        self.handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
        self.handler.setInputAction(function (movement) {
          var ray = viewer.camera.getPickRay(movement.position);
          var cartesian = viewer.scene.globe.pick(ray, viewer.scene);

          if (cartesian) {
            switch (flag) {
              case 0:
                self.keepStartPoint = cartesian;
                var StartEntity = new Cesium.Entity({
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
                self.keepEndPoint = cartesian;
                var EndEntity = new Cesium.Entity({
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

            var cartographic = Cesium.Cartographic.fromCartesian(cartesian);
            var longitudeDegree = Cesium.Math.toDegrees(cartographic.longitude);
            var latitudeDegree = Cesium.Math.toDegrees(cartographic.latitude);
            console.log("lng:" + longitudeDegree + ",lat:" + latitudeDegree);
          }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

        self.handler.setInputAction(function () {
          if (flag == -1) {
            if (self.useOriginRRTFlag) {
              self.FindPath_RRT();
            } else {
              self.FindPath_AStar(self.keepStartPoint, self.keepEndPoint);
            }
          }
          self.handler.destroy();
        }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
      } else {
        alert('请先计算区域坡度！');
      }
    },

    /**
     * 刷新路径下拉列表，并绑定“显示/隐藏选中路径”按钮事件。
     */
    pickPath: function () {
      var sel = document.getElementById("pathListSelect");
      if (!sel) {
        console.warn('pathListSelect element not found');
        return;
      }

      sel.innerHTML = "";
      for (var i = 0; i < this.pathLines.length; i++) {
        var info = this.pathLines[i];
        var opt = document.createElement("option");
        opt.value = String(info.pathLineNum);
        opt.text = "路径 " + info.pathLineNum + " 长度 " + info.pathLineLength.toFixed(2) + " \n                  g = " + info.pathLineCostg + " h = " + info.pathLineCosth;
        opt.style.backgroundColor = info.pathLineColorCss;
        opt.style.paddingLeft = '20px';
        opt.style.whiteSpace = 'nowrap';
        sel.appendChild(opt);
      }

      var self = this;
      var showBtn = document.getElementById("pathShowBtn");
      var hideBtn = document.getElementById("pathHideBtn");
      if (showBtn) {
        showBtn.onclick = function () {
          var selected = Array.from(sel.selectedOptions).map(function (o) { return o.value; });
          self._applyPathSelection(selected, true);
        };
      }
      if (hideBtn) {
        hideBtn.onclick = function () {
          var selected = Array.from(sel.selectedOptions).map(function (o) { return o.value; });
          self._applyPathSelection(selected, false);
        };
      }

      sel.onchange = function () {
        console.log('path selection changed:', Array.from(sel.selectedOptions).map(function (o) { return o.value; }));
      };
    },

    /**
     * 根据下拉选中项批量控制路径实体可见性。
     * @param {string[]} selectedArray 选中路径编号数组。
     * @param {boolean} visible 目标显隐状态。
     */
    _applyPathSelection: function (selectedArray, visible) {
      var selSet = new Set(selectedArray.map(String));
      for (var i = 0; i < this.pathLines.length; i++) {
        var info = this.pathLines[i];
        if (selSet.has(String(info.pathLineNum))) {
          if (info.pathLineEntity) info.pathLineEntity.show = visible;
          (info.pathPointEntities || []).forEach(function (e) {
            if (e) e.show = visible;
          });
        }
      }
    },

    /**
     * 绘制当前路径（点+线）并注册到图层系统。
     */
    DrawPath: function () {
      var viewer = this.viewer;
      if (!viewer) {
        console.error('[SlopeAspectPathModule] viewer 未初始化，无法绘制路径');
        return;
      }

      if (!this.pathPoints[this.pathLineNum] || this.pathPoints[this.pathLineNum].length === 0) {
        console.warn('[SlopeAspectPathModule] 当前路径点为空，跳过绘制');
        return;
      }

      var CrossPoints = [];
      var pathPointEntities = [];

      for (var i = 0; i < this.pathPoints[this.pathLineNum].length; i++) {
        CrossPoints.push(this.pathPoints[this.pathLineNum][i].Cartesian3Grid);
        var PathPoint = new Cesium.Entity({
          id: 'slope_path_point' + this.pathLineNum + i,
          position: this.pathPoints[this.pathLineNum][i].Cartesian3Grid,
          point: {
            pixelSize: 8,
            color: Cesium.Color.fromCssColorString('#fdfdfdff'),
            disableDepthTest: Number.POSITIVE_INFINITY,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          },
        });
        pathPointEntities.push(PathPoint);
        viewer.entities.add(PathPoint);
        PathPoint.isPath = true;
      }

      var lineColor = new Cesium.Color(this.pathLineNum * 0.1, 1 - this.pathLineNum * 0.3, this.pathLineNum * 0.4, 1);
      var PathLine = new Cesium.Entity({
        id: 'slope_path_line' + this.pathLineNum,
        polyline: {
          positions: CrossPoints,
          width: 5,
          material: lineColor,
          clampToGround: true,
        },
      });
      viewer.entities.add(PathLine);
      PathLine.isPath = true;

      var css = lineColor.toCssHexString();
      var pathLineInfo = {
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
      this.pathLines.push(pathLineInfo);
      this.registerLayer('pathLines', '路径线', 'entity', this.pathLines.map(function (p) { return p.pathLineEntity; }));

      try {
        this.pickPath();
      } catch (e) {
        // ignore ui refresh errors
      }
    },
  };

  global.SlopeAspectPathModule = PathModule;
})(window);
