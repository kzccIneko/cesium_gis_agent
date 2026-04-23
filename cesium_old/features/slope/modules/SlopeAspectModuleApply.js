(function (global) {
  "use strict";

  /**
   * 模块挂载入口。
   *
   * 作用：
   * 1) 查找主类 SlopeAspect 构造函数（各个功能函数）；
   * 2) 将各子模块方法挂到 SlopeAspect.prototype；
   * 3) 保持外部调用接口不变（eventBindInit 无需改名）。
   */
  function applyModules() {
    var SlopeAspectCtor = global.SlopeAspect || (typeof SlopeAspect !== 'undefined' ? SlopeAspect : null);
    if (!SlopeAspectCtor || !SlopeAspectCtor.prototype) return;

    if (global.SlopeAspectGridModule) {
      SlopeAspectCtor.prototype.createNew4Distance = global.SlopeAspectGridModule.createNew4Distance;
      SlopeAspectCtor.prototype.createNew4Num = global.SlopeAspectGridModule.createNew4Num;
      SlopeAspectCtor.prototype.createEllipse = global.SlopeAspectGridModule.createEllipse;
      SlopeAspectCtor.prototype.calculateSlope = global.SlopeAspectGridModule.calculateSlope;
    }

    if (global.SlopeAspectPathModule) {
      SlopeAspectCtor.prototype.FindPath_AStar = global.SlopeAspectPathModule.FindPath_AStar;
      SlopeAspectCtor.prototype.FindPath_RRT = global.SlopeAspectPathModule.FindPath_RRT;
      SlopeAspectCtor.prototype.GetSlopePath = global.SlopeAspectPathModule.GetSlopePath;
      SlopeAspectCtor.prototype.DrawPath = global.SlopeAspectPathModule.DrawPath;
      SlopeAspectCtor.prototype.pickPath = global.SlopeAspectPathModule.pickPath;
      SlopeAspectCtor.prototype._applyPathSelection = global.SlopeAspectPathModule._applyPathSelection;
    }

    if (global.SlopeAspectTerrainModule) {
      SlopeAspectCtor.prototype.Ridge_Valley_Analysis = global.SlopeAspectTerrainModule.Ridge_Valley_Analysis;
    }

    if (global.SlopeAspectCostModule) {
      SlopeAspectCtor.prototype.DrawCostMap = global.SlopeAspectCostModule.DrawCostMap;
      SlopeAspectCtor.prototype.createCostInstance = global.SlopeAspectCostModule.createCostInstance;
      SlopeAspectCtor.prototype.calculateCostColor = global.SlopeAspectCostModule.calculateCostColor;
    }

    if (global.SlopeAspectLayerModule) {
      SlopeAspectCtor.prototype.registerLayer = global.SlopeAspectLayerModule.registerLayer;
      SlopeAspectCtor.prototype.unregisterLayer = global.SlopeAspectLayerModule.unregisterLayer;
      SlopeAspectCtor.prototype.toggleLayerVisibility = global.SlopeAspectLayerModule.toggleLayerVisibility;
      SlopeAspectCtor.prototype.raisePrimitiveToTop = global.SlopeAspectLayerModule.raisePrimitiveToTop;
      SlopeAspectCtor.prototype.getAvailablePrimitives = global.SlopeAspectLayerModule.getAvailablePrimitives;
      SlopeAspectCtor.prototype._syncLayerToSidebar = global.SlopeAspectLayerModule._syncLayerToSidebar;
      SlopeAspectCtor.prototype._getAnalysisBounds = global.SlopeAspectLayerModule._getAnalysisBounds;
      SlopeAspectCtor.prototype._syncSidebarCheckbox = global.SlopeAspectLayerModule._syncSidebarCheckbox;
    }

    if (global.SlopeAspectStateModule) {
      SlopeAspectCtor.prototype.clearAll = global.SlopeAspectStateModule.clearAll;
      SlopeAspectCtor.prototype.reFindPath = global.SlopeAspectStateModule.reFindPath;
      SlopeAspectCtor.prototype.slopeLayerVisibility = global.SlopeAspectStateModule.slopeLayerVisibility;
      SlopeAspectCtor.prototype.aspectLayerVisibility = global.SlopeAspectStateModule.aspectLayerVisibility;
      SlopeAspectCtor.prototype.costLayerVisibility = global.SlopeAspectStateModule.costLayerVisibility;
    }

    if (global.SlopeAspectInteractionModule) {
      SlopeAspectCtor.prototype.openTip = global.SlopeAspectInteractionModule.openTip;
      SlopeAspectCtor.prototype.closeTip = global.SlopeAspectInteractionModule.closeTip;
    }

    if (global.SlopeAspectCurvatureModule) {
      SlopeAspectCtor.prototype.DrawCurvatureMap = global.SlopeAspectCurvatureModule.DrawCurvatureMap;
      SlopeAspectCtor.prototype.calculateCurvatureColor = global.SlopeAspectCurvatureModule.calculateCurvatureColor;
      SlopeAspectCtor.prototype.createCurvatureInstance = global.SlopeAspectCurvatureModule.createCurvatureInstance;
      SlopeAspectCtor.prototype.curvatureLayerVisibility = global.SlopeAspectCurvatureModule.curvatureLayerVisibility;
    }

    console.log("[SlopeAspect] 模块化方法已挂载");
  }

  // 页面尚未完成解析时，延后到 DOMContentLoaded 再挂载，避免脚本顺序导致主类尚未定义。
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyModules);
  } else {
    // 页面已可用时立即挂载，支持热刷新场景。
    applyModules();
  }
})(window);
