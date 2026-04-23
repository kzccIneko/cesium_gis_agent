(function (global) {
  "use strict";

  /**
   * SlopeAspectInteractionModule
   *
   * 负责鼠标悬停提示交互：
   * - openTip: 绑定 MOUSE_MOVE，显示坡度/代价信息
   * - closeTip: 解除事件绑定并清理提示文本
   */
  var InteractionModule = {
    _metricLabel: function (metricName) {
      var key = String(metricName || "value").toLowerCase();
      if (key === "slope_deg") return "坡度";
      if (key === "aspect_deg") return "坡向";
      if (key === "curvature") return "曲率";
      if (key === "cost") return "代价";
      return "数值";
    },

    _extractTipText: function (pick) {
      if (!pick || !pick.id) return "";

      // Backend terrain analysis primitives (GroundPrimitive GeometryInstance id).
      if (pick.id.type === "TerrainBackendCell" && Number.isFinite(Number(pick.id.value))) {
        var backendName = InteractionModule._metricLabel(pick.id.metric);
        return backendName + ": " + Number(pick.id.value).toFixed(4);
      }

      // Frontend slope/aspect/cost/curvature entities.
      if (pick.id.type === "SlopeAspect" || pick.id.type === "Cost" || pick.id.type === "Curvature") {
        var name = pick.id.name || InteractionModule._metricLabel(pick.id.type);
        var value = pick.id.value;
        if (!Number.isFinite(Number(value))) return "";
        var suffix = (pick.id.type === "SlopeAspect" || /坡度|坡向/.test(String(name))) ? "°" : "";
        return name + ": " + Number(value).toFixed(6) + suffix;
      }

      // GeoJsonDataSource entities with properties.value style payload.
      var entity = pick.id;
      if (entity && entity.properties && entity.properties.value) {
        var val = entity.properties.value.getValue ? entity.properties.value.getValue() : entity.properties.value;
        if (!Number.isFinite(Number(val))) return "";

        var metricCandidates = ["slope_deg", "aspect_deg", "curvature", "cost"];
        var metric = "value";
        for (var i = 0; i < metricCandidates.length; i++) {
          var key = metricCandidates[i];
          if (entity.properties[key]) {
            metric = key;
            break;
          }
        }
        var suffix2 = metric === "slope_deg" || metric === "aspect_deg" ? "°" : "";
        return InteractionModule._metricLabel(metric) + ": " + Number(val).toFixed(4) + suffix2;
      }

      return "";
    },

    /**
     * 开启鼠标悬停提示。
     *
     * 读取 pick.id 中的 type/name/value，生成提示文案并调用 CreateRemindertip。
     */
    openTip: function () {
      var self = this;
      var viewer = this.viewer;
      this.handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
      this.handler.setInputAction(function (movement) {
        var endPos = movement.endPosition;
        var pick = viewer.scene.pick(endPos);
        var tipText = InteractionModule._extractTipText.call(self, pick);
        if (tipText) {
          self.toolTip = tipText;
          CreateRemindertip(self.toolTip, endPos, true);
        } else {
          self.toolTip = "";
          CreateRemindertip(self.toolTip, endPos, false);
        }
      }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    },

    /**
     * 关闭提示并销毁事件监听。
     */
    closeTip: function () {
      if (this.handler) {
        this.handler.destroy();
        this.handler = undefined;
        this.toolTip = "";
      }
      if (typeof CreateRemindertip === "function") {
        CreateRemindertip("", { x: 0, y: 0 }, false);
      }
    },
  };

  global.SlopeAspectInteractionModule = InteractionModule;
})(window);
