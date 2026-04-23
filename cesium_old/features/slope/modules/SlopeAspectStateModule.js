(function (global) {
  "use strict";

  /**
   * SlopeAspectStateModule
   *
   * 职责：
   * - 清空分析结果与交互状态
   * - 依据 UI 参数重新计算路径
   * - 坡度/坡向/代价图层显隐开关
   */
  var StateModule = {
    /**
     * 全量清理分析状态。
     *
     * 清理内容包含：
     * - 交互 handler
     * - primitive/entity 图层
     * - 网格与路径缓存
     */
    clearAll: function () {
      console.log("clear");

      if (this.handler) {
        this.handler.destroy();
        this.handler = undefined;
      }

      this.slopePolygons.forEach(function (element) {
        this.viewer.scene.primitives.remove(element.primitive);
      }, this);
      this.slopePolygons = [];

      this.aspectPolygons.forEach(function (element) {
        this.viewer.scene.primitives.remove(element.primitive);
      }, this);
      this.aspectPolygons = [];

      this.costPolygons.forEach(function (element) {
        this.viewer.scene.primitives.remove(element.primitive);
      }, this);
      this.costPolygons = [];

      this.curvaturePolygons.forEach(function (element) {
        this.viewer.scene.primitives.remove(element.primitive);
      }, this);
      this.curvaturePolygons = [];

      if (this.landUseCostLayers && this.landUseCostLayers.length > 0) {
        this.landUseCostLayers.forEach(function (layer) {
          if (!layer || !Array.isArray(layer.polygons)) return;
          layer.polygons.forEach(function (element) {
            this.viewer.scene.primitives.remove(element.primitive);
          }, this);
        }, this);
        this.landUseCostLayers = [];
      }

      this.viewer.entities.removeAll();

      // Ensure registry/sidebar analysis entries are removed together with scene primitives.
      if (this.layerRegistry && typeof this.unregisterLayer === "function") {
        var layerIds = Object.keys(this.layerRegistry);
        for (var li = 0; li < layerIds.length; li++) {
          try {
            this.unregisterLayer(layerIds[li]);
          } catch (_) {
            // ignore stale registry entries
          }
        }
      }
      this.layerRegistry = {};
      this.layerOrder = [];

      this.slopeCostArray = [];
      this.slopeCostGrid = [];
      this.curvatureGrid = [];
      this.ridgeValleyEntities = [];

      this.openList = [];
      this.closeList = [];
      this.pathLines = [];
      this.keepStartPoint = null;
      this.keepEndPoint = null;
      this.pathLineNum = 0;
      this.pathPoints = [];
    },

    /**
     * 重新寻路。
     *
     * 策略：
     * 1) 读取 UI 参数并重置搜索状态；
     * 2) 若启用固定起终点则直接求解；
     * 3) 否则按“保留路径/清空重选”分支执行。
     */
    reFindPath: function () {
      this.closeList = new Set();
      this.openList = [];
      this.gWeight = $("#gWeight").val();
      this.hWeight = $("#hWeight").val();
      this.carWeight = $('#carWeight').val();
      this.DragF = 9.8 * this.carWeight * Math.sin(this.maxSlope * Math.PI / 180) || $('#DragF').val();
      this.potentialField = null;

      if (document.getElementById('specifiedStartEnd').checked) {
        this.keepStartPoint = Cesium.Cartesian3.fromDegrees(100.655395, 29.494247, 3419.32);
        this.keepEndPoint = Cesium.Cartesian3.fromDegrees(100.647575, 29.508656, 3386.11);
        new Cesium.Entity({
          position: this.keepStartPoint,
          point: { pixelSize: 10, color: Cesium.Color.WHITE },
        });
        new Cesium.Entity({
          position: this.keepEndPoint,
          point: { pixelSize: 10, color: Cesium.Color.WHITE },
        });
        this.FindPath_AStar(this.keepStartPoint, this.keepEndPoint);
        return;
      }

      if (this.keepStartEndFlag && !this.clearPathFlag) {
        if (this.useOriginRRTFlag) {
          this.FindPath_RRT();
          return;
        }
        this.FindPath_AStar(this.keepStartPoint, this.keepEndPoint);
        return;
      }

      this.pathLineNum = 0;
      this.pathLines = [];
      this.pathPoints = [];

      if (this.handler) {
        this.handler.destroy();
        this.handler = undefined;
      }

      var toRemove = [];
      this.viewer.entities.values.forEach(function (e) {
        try {
          if (e && (e.isPath === true || (typeof e.id === "string" && e.id.startsWith("slope_path_")))) {
            toRemove.push(e);
          }
        } catch (err) {
          // ignore entity access failures
        }
      });
      toRemove.forEach(function (ent) {
        this.viewer.entities.remove(ent);
      }, this);

      if (this.reFindPathFlag) {
        this.GetSlopePath();
        this.reFindPathFlag = false;
      }
    },

    /**
     * 切换坡度图层显隐并同步侧边栏复选框。
     */
    slopeLayerVisibility: function () {
      if (this.slopePolygons && this.slopePolygons.length >= 2) {
        this.slopePolygons.forEach(function (element) {
          element.primitive.show = !element.primitive.show;
        });
        this._syncSidebarCheckbox('slope', this.slopePolygons[0].primitive.show);
      }
    },

    /**
     * 切换坡向图层显隐并同步侧边栏复选框。
     */
    aspectLayerVisibility: function () {
      if (this.aspectPolygons && this.aspectPolygons.length >= 2) {
        this.aspectPolygons.forEach(function (element) {
          element.primitive.show = !element.primitive.show;
        });
        this._syncSidebarCheckbox('aspect', this.aspectPolygons[0].primitive.show);
      }
    },

    /**
     * 切换代价图层显隐并同步侧边栏复选框。
     */
    costLayerVisibility: function () {
      if (this.costPolygons && this.costPolygons.length >= 2) {
        this.costPolygons.forEach(function (element) {
          element.primitive.show = !element.primitive.show;
        });
        this._syncSidebarCheckbox('cost', this.costPolygons[0].primitive.show);
      }
    },
  };

  global.SlopeAspectStateModule = StateModule;
})(window);
