(function (global) {
  "use strict";

  /**
   * SlopeAspectCostModule
   *
   * 职责：
   * 1) 基于坡度计算每个网格的通行代价（时间代价）；
   * 2) 将代价重分类为颜色等级；
   * 3) 生成并注册 Cesium 贴地代价图层。
   *
   * 依赖：
   * - this.slopeCostGrid / this.distance / this.viewer
   * - this.registerLayer(...)（由图层管理模块提供）
   */
  var CostModule = {
    /**
     * 计算代价值并绘制代价图。
     *
     * 输入：读取 this.slopeCostGrid 中的 slope。
     * 输出：写回每格 slopeCost，并创建 costPolygons。
     */
    DrawCostMap: function (options) {
      options = options || {};
      var renderLayer = options.renderLayer !== false;
      var visible = options.visible === true;

      if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) {
        alert('请先计算区域坡度！');
        return;
      }

      var slope = 999999;
      var speed = 0;

      for (var i = 0; i < this.slopeCostGrid.length; i++) {
        for (var j = 0; j < this.slopeCostGrid[i].length; j++) {
          if (this.slopeCostGrid[i][j].length !== 0) {
            slope = this.slopeCostGrid[i][j].slope;

            if (slope <= 0) speed = 25;
            else if (slope <= 3) speed = 25 - ((25 - 20) * (slope - 0)) / (3 - 0);
            else if (slope <= 6) speed = 20 - ((20 - 15) * (slope - 3)) / (6 - 3);
            else if (slope <= 10) speed = 15 - ((15 - 12) * (slope - 6)) / (10 - 6);
            else if (slope <= 15) speed = 12 - ((12 - 8) * (slope - 10)) / (15 - 10);
            else if (slope <= 20) speed = 8 - ((8 - 5) * (slope - 15)) / (20 - 15);
            else if (slope <= 30) speed = 5 - ((5 - 0) * (slope - 20)) / (30 - 20);
            else speed = 0;

            if (speed > 0.1) {
              this.slopeCostGrid[i][j].slopeCost = this.distance / (speed / 3.6);
            } else {
              this.slopeCostGrid[i][j].slopeCost = 999999;
            }
          }
        }
      }

      if (!renderLayer) {
        return;
      }

      var slopeCostColorGrid = this.calculateCostColor([]);
      this.createCostInstance(slopeCostColorGrid);

      if (this.costPolygons && this.costPolygons.length > 0) {
        this.costPolygons.forEach(function (element) {
          element.primitive.show = visible;
        });
      }
      if (typeof this._syncSidebarCheckbox === 'function') {
        this._syncSidebarCheckbox('cost', visible);
      }
      return;
    },

    /**
     * 根据颜色分组结果创建 GroundPrimitive。
     *
     * @param {Array[]} slopeCostColorGrid 按颜色等级分组的网格集合。
     * @param {Object=} options 可选项：targetPolygons/layerId/layerName。
     */
    createCostInstance: function (slopeCostColorGrid, options) {
      options = options || {};
      var targetPolygons = Array.isArray(options.targetPolygons) ? options.targetPolygons : this.costPolygons;
      var layerId = options.layerId || 'cost';
      var layerName = options.layerName || '代价图层';

      var viewer = this.viewer;
      if (!viewer) {
        console.error('[SlopeAspectCostModule] viewer 未初始化');
        return;
      }

      for (var i = 0; i < slopeCostColorGrid.length; i++) {
        var Instances = [];
        var positions = [];
        var color = 0;

        if (slopeCostColorGrid[i].length > 0) {
          color = Cesium.Color.fromCssColorString(slopeCostColorGrid[i][0].color);
        }

        for (var j = 0; j < slopeCostColorGrid[i].length && slopeCostColorGrid[i].length > 0; j++) {
          var Cost = slopeCostColorGrid[i][j].cost;
          var polygonInstance = new Cesium.GeometryInstance({
            id: {
              type: "Cost",
              name: '代价：',
              value: Cost,
              index: i,
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
          var material = new Cesium.Material({
            fabric: {
              type: 'Color',
              uniforms: {
                color: color,
              },
            },
          });
          var appearance = new Cesium.MaterialAppearance({
            material: material,
            translucent: color.alpha < 1.0,
            flat: true,
          });
          var primitive = new Cesium.GroundPrimitive({
            geometryInstances: Instances,
            appearance: appearance,
          });

          viewer.scene.primitives.add(primitive);

          var polygonInfo = {
            primitive: primitive,
            positions: positions,
            baseColor: color,
            alpha: color.alpha,
          };
          targetPolygons.push(polygonInfo);
        }
      }

      if (targetPolygons.length > 0) {
        this.registerLayer(layerId, layerName, 'primitive', targetPolygons);
      }
    },

    /**
     * 把 slopeCost 映射到颜色等级。
     *
     * @returns {Array[]} 6 个等级数组，每项包含 i/j/cost/color/gridSquare 等字段。
     */
    calculateCostColor: function (costValArray) {
      console.log('costValArray', costValArray);

      var dist = this.distance || 50;
      var costThresholds = [
        dist / (25 / 3.6),
        dist / (15 / 3.6),
        dist / (12 / 3.6),
        dist / (8 / 3.6),
        dist / (5 / 3.6),
        dist / (0.1 / 3.6),
      ];

      var colorLevels = [
        { r: 0, g: 255, b: 0, name: '绿色-最易通行' },
        { r: 144, g: 238, b: 144, name: '浅绿-较易通行' },
        { r: 255, g: 255, b: 0, name: '黄色-中等通行' },
        { r: 255, g: 140, b: 0, name: '橙色-较难通行' },
        { r: 255, g: 69, b: 0, name: '深橙-困难通行' },
        { r: 255, g: 0, b: 0, name: '红色-不可通行' },
      ];

      var slopeCostColorGrid = [];
      for (var i = 0; i < colorLevels.length; i++) {
        slopeCostColorGrid[i] = [];
      }

      for (var x = 0; x < this.slopeCostGrid.length; x++) {
        for (var y = 0; y < this.slopeCostGrid[x].length; y++) {
          var cell = this.slopeCostGrid[x][y];
          if (!cell || cell.slopeCost === undefined || !isFinite(cell.slopeCost)) continue;

          var cost = cell.slopeCost;
          var colorClass = 5;

          if (cost >= 999999) colorClass = 5;
          else if (cost <= costThresholds[1]) colorClass = 0;
          else if (cost <= costThresholds[2]) colorClass = 1;
          else if (cost <= costThresholds[3]) colorClass = 2;
          else if (cost <= costThresholds[4]) colorClass = 3;
          else if (cost <= costThresholds[5]) colorClass = 4;
          else colorClass = 5;

          var colorLevel = colorLevels[colorClass];
          var color = '#' + ((1 << 24) + (colorLevel.r << 16) + (colorLevel.g << 8) + colorLevel.b).toString(16).slice(1);

          slopeCostColorGrid[colorClass].push({
            i: x,
            j: y,
            cost: cost,
            colorClass: colorClass,
            colorRGB: colorLevel,
            color: color,
            gridSquare: cell.gridSquare || [],
          });
        }
      }

      return slopeCostColorGrid;
    },
  };

  global.SlopeAspectCostModule = CostModule;
})(window);
