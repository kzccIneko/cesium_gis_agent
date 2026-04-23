(function (global) {
  "use strict";

  /**
   * SlopeAspectCurvatureModule
   *
   * 基于 3x3 DEM 邻域计算曲率并可视化：
   * 1) 从 slopeCostGrid 读取中心点及邻域高程
   * 2) 计算二次曲面系数 A/B/C/D/E
   * 3) 计算剖面曲率 k_prof 与平面曲率 k_plan
   * 4) 将曲率分级着色并绘制贴地网格
   */
  var CurvatureModule = {
    /**
     * 计算曲率并绘制曲率图。
     * 采用平面曲率 k_plan 作为默认可视化指标。
     */
    DrawCurvatureMap: function () {
      if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) {
        alert('请先计算区域坡度！');
        return;
      }

      var tStart = performance.now();
      console.time('[Curvature] 总耗时');
      console.time('[Curvature] 阶段1-曲率计算');

      var rows = this.slopeCostGrid.length;
      var cols = (this.slopeCostGrid[0] || []).length;
      var L = Number(this.distance) || 50;
      // 数值稳定阈值：当 D^2 + E^2 很接近 0 时，说明局部几乎水平（坡向不稳定）
      // 曲率公式分母含 (D^2+E^2)，直接计算会放大浮点噪声，因此用 eps 做“近零判断”。
      // 1e-12 对应 |D|、|E| 约 1e-6 量级（极平缓），足以过滤数值噪声但不影响正常坡面。
      var eps = 1e-12;

      this.curvatureGrid = [];
      for (var i = 0; i < rows; i++) {
        this.curvatureGrid[i] = [];
        for (var j = 0; j < cols; j++) {
          this.curvatureGrid[i][j] = [];
        }
      }

      function validCell(cell) {
        return !!(cell && cell.degreeCoordinate && Number.isFinite(Number(cell.degreeCoordinate[2])));
      }

      function h(grid, x, y) {
        var c = grid[x] && grid[x][y];
        if (!validCell(c)) return null;
        return Number(c.degreeCoordinate[2]);
      }

      for (var x = 1; x < rows - 1; x++) {
        for (var y = 1; y < cols - 1; y++) {
          var center = this.slopeCostGrid[x][y];
          if (!validCell(center)) continue;

          var z1 = h(this.slopeCostGrid, x - 1, y - 1);
          var z2 = h(this.slopeCostGrid, x, y - 1);
          var z3 = h(this.slopeCostGrid, x + 1, y - 1);
          var z4 = h(this.slopeCostGrid, x - 1, y);
          var z5 = h(this.slopeCostGrid, x, y);
          var z6 = h(this.slopeCostGrid, x + 1, y);
          var z7 = h(this.slopeCostGrid, x - 1, y + 1);
          var z8 = h(this.slopeCostGrid, x, y + 1);
          var z9 = h(this.slopeCostGrid, x + 1, y + 1);

          if (
            z1 === null || z2 === null || z3 === null ||
            z4 === null || z5 === null || z6 === null ||
            z7 === null || z8 === null || z9 === null
          ) {
            continue;
          }

          // 与 DEM曲率图解文件保持一致的 3x3 最小二乘闭式解
          var A = (((z1 + z3 + z4 + z6 + z7 + z9) / 6) - ((z2 + z5 + z8) / 3)) / (L * L);
          var B = (((z1 + z2 + z3 + z7 + z8 + z9) / 6) - ((z4 + z5 + z6) / 3)) / (L * L);
          var C = (-z1 + z3 + z7 - z9) / (4 * L * L);
          var D = (z3 + z6 + z9 - z1 - z4 - z7) / (6 * L);
          var E = (z1 + z2 + z3 - z7 - z8 - z9) / (6 * L);

          // se = D^2 + E^2，本质是一阶梯度模长平方（坡度强度）
          // 后续 kProf/kPlan 分母都依赖 se。
          var se = D * D + E * E;
          if (se <= eps) {
            // se 过小：局部可视为“近水平面”，坡向不可稳定定义。
            // 此时把曲率置空(null)，避免除以近零导致的异常大值/噪声条纹。
            this.curvatureGrid[x][y] = {
              A: A,
              B: B,
              C: C,
              D: D,
              E: E,
              kProf: null, // 剖面曲率：未定义（近水平）
              kPlan: null, // 平面曲率：未定义（近水平）
              curvature: null, // 当前可视化主值（默认映射 kPlan）
              gridSquare: center.gridSquare || [],
            };
            continue;
          }

          var kProf = -2 * (A * D * D + B * E * E + C * D * E) / (se * Math.pow(1 + se, 1.5));
          var kPlan = 2 * (A * E * E + B * D * D - C * D * E) / (se * Math.sqrt(1 + se));

          this.curvatureGrid[x][y] = {
            A: A,
            B: B,
            C: C,
            D: D,
            E: E,
            kProf: kProf,
            kPlan: kPlan,
            curvature: kPlan,
            gridSquare: center.gridSquare || [],
          };
        }
      }
      console.timeEnd('[Curvature] 阶段1-曲率计算');

      console.time('[Curvature] 阶段2-分级着色');
      var colorGrid = this.calculateCurvatureColor();
      console.timeEnd('[Curvature] 阶段2-分级着色');

      console.time('[Curvature] 阶段3-图层绘制');
      this.createCurvatureInstance(colorGrid);
      console.timeEnd('[Curvature] 阶段3-图层绘制');

      if (this.curvaturePolygons && this.curvaturePolygons.length > 0) {
        this.curvaturePolygons.forEach(function (p) {
          if (p && p.primitive) p.primitive.show = true;
        });
      }

      console.timeEnd('[Curvature] 总耗时');
      var tEnd = performance.now();
      console.log('[Curvature] 分析完成，网格尺寸=', rows + 'x' + cols, '总计=', (tEnd - tStart).toFixed(2) + 'ms');
    },

    /**
     * 曲率分级着色：
     * 负值(山谷) -> 蓝
     * 近零 -> 灰
     * 正值(山脊) -> 红
     */
    calculateCurvatureColor: function () {
      var rows = this.curvatureGrid.length;
      var cols = rows > 0 ? this.curvatureGrid[0].length : 0;

      var values = [];
      for (var i = 0; i < rows; i++) {
        for (var j = 0; j < cols; j++) {
          var c = this.curvatureGrid[i][j];
          if (!c || !Number.isFinite(c.curvature)) continue;
          values.push(c.curvature);
        }
      }

      var absMax = 0;
      for (var k = 0; k < values.length; k++) {
        var av = Math.abs(values[k]);
        if (av > absMax) absMax = av;
      }
      if (absMax <= 0) absMax = 1e-6;

      var thresholds = {
        t0: -0.66 * absMax,
        t1: -0.33 * absMax,
        t2: -0.08 * absMax,
        t3: 0.08 * absMax,
        t4: 0.33 * absMax,
        t5: 0.66 * absMax,
      };

      // 7 级发散色带
      var colors = ['#2b5cbe', '#4f88d9', '#8ebae8', '#b0b0b0', '#f2b0a5', '#e46b5a', '#c0392b'];
      var groups = [];
      for (var g = 0; g < colors.length; g++) groups[g] = [];

      for (var x = 0; x < rows; x++) {
        for (var y = 0; y < cols; y++) {
          var cell = this.curvatureGrid[x][y];
          if (!cell || !Number.isFinite(cell.curvature)) continue;

          var n = cell.curvature / absMax; // [-1, 1]
          var idx = 3;
          if (n <= -0.66) idx = 0;
          else if (n <= -0.33) idx = 1;
          else if (n < -0.08) idx = 2;
          else if (n <= 0.08) idx = 3;
          else if (n < 0.33) idx = 4;
          else if (n < 0.66) idx = 5;
          else idx = 6;

          groups[idx].push({
            i: x,
            j: y,
            curvature: cell.curvature,
            kPlan: cell.kPlan,
            kProf: cell.kProf,
            colorClass: idx,
            color: colors[idx],
            gridSquare: cell.gridSquare || [],
          });
        }
      }

      this.curvatureColorMeta = {
        absMax: absMax,
        thresholds: thresholds,
        colors: colors.slice(),
        counts: groups.map(function (g) { return g.length; }),
      };

      console.log('[Curvature] 色带映射=', {
        rule: 'n = curvature/absMax，按[-0.66,-0.33,-0.08,0.08,0.33,0.66]分7级',
        absMax: absMax,
        thresholds: thresholds,
        colors: colors,
        counts: this.curvatureColorMeta.counts,
      });

      return groups;
    },

    /**
     * 绘制曲率图层。
     */
    createCurvatureInstance: function (curvatureColorGrid, options) {
      options = options || {};
      var targetPolygons = Array.isArray(options.targetPolygons) ? options.targetPolygons : this.curvaturePolygons;
      var layerId = options.layerId || 'curvature';
      var layerName = options.layerName || '曲率图层';
      var viewer = this.viewer;

      if (!viewer) {
        console.error('[SlopeAspectCurvatureModule] viewer 未初始化');
        return;
      }

      for (var i = 0; i < curvatureColorGrid.length; i++) {
        if (!curvatureColorGrid[i] || curvatureColorGrid[i].length === 0) continue;

        var instances = [];
        var positions = [];
        var color = Cesium.Color.fromCssColorString(curvatureColorGrid[i][0].color);

        for (var j = 0; j < curvatureColorGrid[i].length; j++) {
          var item = curvatureColorGrid[i][j];
          var polygonInstance = new Cesium.GeometryInstance({
            id: {
              type: 'Curvature',
              name: '曲率：',
              value: item.curvature,
              index: i,
            },
            geometry: new Cesium.PolygonGeometry({
              polygonHierarchy: new Cesium.PolygonHierarchy(item.gridSquare),
              height: 0,
              vertexFormat: Cesium.MaterialAppearance.VERTEX_FORMAT,
            }),
          });
          instances.push(polygonInstance);
          positions.push(item.gridSquare);
        }

        var material = new Cesium.Material({
          fabric: {
            type: 'Color',
            uniforms: { color: color },
          },
        });
        var appearance = new Cesium.MaterialAppearance({
          material: material,
          translucent: color.alpha < 1.0,
          flat: true,
        });

        var primitive = new Cesium.GroundPrimitive({
          geometryInstances: instances,
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

      if (targetPolygons.length > 0) {
        this.registerLayer(layerId, layerName, 'primitive', targetPolygons);
      }
    },

    /**
     * 曲率图层显隐开关。
     */
    curvatureLayerVisibility: function () {
      if (this.curvaturePolygons && this.curvaturePolygons.length > 0) {
        this.curvaturePolygons.forEach(function (element) {
          if (element && element.primitive) {
            element.primitive.show = !element.primitive.show;
          }
        });
        this._syncSidebarCheckbox('curvature', this.curvaturePolygons[0].primitive.show);
      }
    },
  };

  global.SlopeAspectCurvatureModule = CurvatureModule;
})(window);
