(function (global) {
  "use strict";

  /*
   * TerrainBackendIntegration.js
   *
   * 角色定位（前端文件）：
   * 1) 读取页面参数并发起后端分析请求（HTTP -> FastAPI）
   * 2) 把后端返回的 GeoJSON/CZML/KML 加载到 Cesium
   * 3) 承担前端动态LOD调度（含四叉树缓存与视域按需请求）
   *
   * 注意：真正的“后端分析算法”仍在 Python 中，不在本文件。
   * 本文件更像“前端编排器 + 渲染调度器 + UI交互层”。
  *
  * 快速导航：
  * A. 参数与工具函数（文件前1/3）
  * B. 请求编排（requestAnalysisJson/runTerrainAnalysisWithAutoTiling/runPathAnalysisByStages）
  * C. 四叉树动态LOD（getDynamicTerrainLodLevel/refreshDynamicTerrainRequestLod/startDynamicTerrainRequestLod）
  * D. 渲染装配（renderTerrainArtifacts/loadArtifactToCesium）
  * E. UI入口（createRunner/initTerrainBackendTools）
   */

  // =========================
  // 基础阈值与请求参数
  // =========================
  // 单次接口请求默认超时时间（毫秒）。用于 fetch 超时控制与错误提示文案。
  var REQUEST_TIMEOUT_MS = 25000;
  // 地形分析允许的最大网格分辨率（每边点数上限）。过大将显著增加后端计算量与前端渲染压力。
  var TERRAIN_MAX_RESOLUTION = 1024;
  // 路径分析允许的最大网格分辨率（每边点数上限）。路径算法复杂度随分辨率上升而快速增加。
  var PATH_MAX_RESOLUTION = 512;
  // 地形自动分块时，期望单块边长（按“网格单元数”估算）。值越小分块越多、单块更轻。
  var TERRAIN_TILE_EDGE_TARGET = 420;
  // 地形分块请求时的重叠单元数。用于减少分块边界处可视缝隙与数值突变。
  var TERRAIN_TILE_OVERLAP_CELLS = 1;
  // 单个 Cesium GroundPrimitive 允许挂载的最大实例数。超过后会自动切批，避免浏览器内存峰值过高。
  var FRONTEND_MAX_INSTANCES_PER_PRIMITIVE = 6000;

  // =========================
  // 历史LOD参数（旧方案保留，兼容遗留逻辑）
  // 当前主流程不依赖这组参数进行四叉树调度。
  // =========================
  // 旧版 LOD 总开关（历史兼容）。
  var TERRAIN_LOD_ENABLE = false;
  // 旧版 LOD 生效的最小分块数阈值。
  var TERRAIN_LOD_MIN_TILE_COUNT = 4;
  // 旧版 LOD：近景最多保留的活动瓦片数。
  var TERRAIN_LOD_ACTIVE_TILES_NEAR = 3;
  // 旧版 LOD：中景最多保留的活动瓦片数。
  var TERRAIN_LOD_ACTIVE_TILES_MID = 2;
  // 旧版 LOD：远景最多保留的活动瓦片数。
  var TERRAIN_LOD_ACTIVE_TILES_FAR = 1;
  // 旧版 LOD：近景/中景高度分界（米）。
  var TERRAIN_LOD_HEIGHT_NEAR_M = 12000;
  // 旧版 LOD：中景/远景高度分界（米）。
  var TERRAIN_LOD_HEIGHT_MID_M = 40000;
  // 旧版 LOD：在当前视域外额外扩展的边界比例，避免相机小幅移动导致频繁切换。
  var TERRAIN_LOD_VIEW_PADDING_FACTOR = 0.15;
  // 旧版 LOD：相机变化后的延迟刷新时间（毫秒），用于节流。
  var TERRAIN_LOD_UPDATE_DELAY_MS = 180;

  // =========================
  // 请求级LOD（单次请求内仅改网格密度，不改分块布局）
  // =========================
  // 请求级 LOD：保持分块数量不变，仅调整“块内网格密度”。
  // 作用：相机较远时用更粗网格，降低后端计算与前端渲染开销。
  var TERRAIN_REQUEST_LOD_ENABLE = false;
  // 请求级 LOD：近景阈值高度（米）。
  var TERRAIN_REQUEST_LOD_HEIGHT_NEAR_M = 10000;
  // 请求级 LOD：中景阈值高度（米）。
  var TERRAIN_REQUEST_LOD_HEIGHT_MID_M = 30000;
  // 请求级 LOD：近景网格倍率（1.0=保持用户设定米/格）。
  var TERRAIN_REQUEST_LOD_CELL_SCALE_NEAR = 1.0;
  // 请求级 LOD：中景网格倍率（2.0=米/格扩大 2 倍，分辨率更粗）。
  var TERRAIN_REQUEST_LOD_CELL_SCALE_MID = 2.0;
  // 请求级 LOD：远景网格倍率（4.0=米/格扩大 4 倍，优先性能）。
  var TERRAIN_REQUEST_LOD_CELL_SCALE_FAR = 4.0;

  // 四叉树动态请求 LOD：
  // 先加载全域最粗层 L0，再按视域和相机高度请求更细层级（L1~L4）。
  // 作用：首屏更快可见，同时在用户关注区域逐步精细化。
  var TERRAIN_DYNAMIC_LOD_ENABLE = true;
  // 四叉树层级切换防抖延时（毫秒），避免相机连续移动时频繁发请求。
  var TERRAIN_DYNAMIC_LOD_SWITCH_DELAY_MS = 900;
  // L0~L4 对应的米/格倍率。索引越大表示层级越细、倍率越小。
  var TERRAIN_DYNAMIC_QTREE_CELL_SCALES = [16.0, 8.0, 4.0, 2.0, 1.0];//L0-L4对应栅格分辨率
  // 计算“当前视域命中哪些四叉树瓦片”时的额外外扩比例。
  var TERRAIN_DYNAMIC_QTREE_VIEW_PADDING_FACTOR = 0.05;
  // 视域占比平滑系数（EMA）。值越大跟随越快，值越小越平滑稳定。
  var TERRAIN_DYNAMIC_QTREE_RATIO_SMOOTHING = 0.35;
  // 视域占比阈值：小于该阈值可提升到 L1。
  var TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L1 = 0.78;
  // 视域占比阈值：小于该阈值可提升到 L2。
  var TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L2 = 0.42;
  // 视域占比阈值：小于该阈值可提升到 L3。
  var TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L3 = 0.18;
  // 视域占比阈值：小于该阈值可提升到 L4（最细层）。
  var TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L4 = 0.08;
  // 相机高度阈值：低于该值倾向至少 L1。
  var TERRAIN_DYNAMIC_QTREE_HEIGHT_L1_M = 45000;
  // 相机高度阈值：低于该值倾向至少 L2。
  var TERRAIN_DYNAMIC_QTREE_HEIGHT_L2_M = 22000;
  // 相机高度阈值：低于该值倾向至少 L3。
  var TERRAIN_DYNAMIC_QTREE_HEIGHT_L3_M = 9000;
  // 相机高度阈值：低于该值倾向至少 L4。
  var TERRAIN_DYNAMIC_QTREE_HEIGHT_L4_M = 4000;
  // 高度建议层级允许的“额外奖励级数”，防止仅凭视域占比直接跳得过细。
  var TERRAIN_DYNAMIC_QTREE_HEIGHT_BONUS_LEVELS = 3;
  // 单次刷新最多允许的“视域目标瓦片数”，用于限制瞬时请求压力。
  var TERRAIN_DYNAMIC_QTREE_VISIBLE_TILE_LIMIT = 64;
  // 四叉树缓存上限（仅统计已加载的细节节点），超限时执行淘汰。
  var TERRAIN_DYNAMIC_QTREE_CACHE_LIMIT = 56;
  // 四叉树瓦片并发加载数，平衡后端吞吐与浏览器稳定性。
  var TERRAIN_DYNAMIC_QTREE_LOAD_CONCURRENCY = 3;
  // GeoJSON 渲染失败的最大重试次数（用于后端文件尚未完全写出等短暂异常）。
  var TERRAIN_GEOJSON_RENDER_RETRY_MAX = 3;
  // 动态 LOD 默认目标块边长（网格单元）。层级越高可采用更小目标值。
  var TERRAIN_DYNAMIC_TILE_EDGE_TARGET = 220;
  // L3 层单块目标边长。
  var TERRAIN_DYNAMIC_TILE_EDGE_TARGET_L3 = 200;
  // L4 层单块目标边长（最细层，进一步减小单块规模以降低前端压力）。
  var TERRAIN_DYNAMIC_TILE_EDGE_TARGET_L4 = 160;

  // 拆分模块需要访问这些常量（运行时由主文件统一注入到全局）。
  global.REQUEST_TIMEOUT_MS = REQUEST_TIMEOUT_MS;
  global.TERRAIN_MAX_RESOLUTION = TERRAIN_MAX_RESOLUTION;
  global.PATH_MAX_RESOLUTION = PATH_MAX_RESOLUTION;
  global.TERRAIN_TILE_EDGE_TARGET = TERRAIN_TILE_EDGE_TARGET;
  global.TERRAIN_TILE_OVERLAP_CELLS = TERRAIN_TILE_OVERLAP_CELLS;
  global.TERRAIN_LOD_VIEW_PADDING_FACTOR = TERRAIN_LOD_VIEW_PADDING_FACTOR;

  global.TERRAIN_REQUEST_LOD_ENABLE = TERRAIN_REQUEST_LOD_ENABLE;
  global.TERRAIN_REQUEST_LOD_HEIGHT_NEAR_M = TERRAIN_REQUEST_LOD_HEIGHT_NEAR_M;
  global.TERRAIN_REQUEST_LOD_HEIGHT_MID_M = TERRAIN_REQUEST_LOD_HEIGHT_MID_M;
  global.TERRAIN_REQUEST_LOD_CELL_SCALE_NEAR = TERRAIN_REQUEST_LOD_CELL_SCALE_NEAR;
  global.TERRAIN_REQUEST_LOD_CELL_SCALE_MID = TERRAIN_REQUEST_LOD_CELL_SCALE_MID;
  global.TERRAIN_REQUEST_LOD_CELL_SCALE_FAR = TERRAIN_REQUEST_LOD_CELL_SCALE_FAR;

  global.TERRAIN_DYNAMIC_LOD_ENABLE = TERRAIN_DYNAMIC_LOD_ENABLE;
  global.TERRAIN_DYNAMIC_LOD_SWITCH_DELAY_MS = TERRAIN_DYNAMIC_LOD_SWITCH_DELAY_MS;
  global.TERRAIN_DYNAMIC_QTREE_CELL_SCALES = TERRAIN_DYNAMIC_QTREE_CELL_SCALES;
  global.TERRAIN_DYNAMIC_QTREE_VIEW_PADDING_FACTOR = TERRAIN_DYNAMIC_QTREE_VIEW_PADDING_FACTOR;
  global.TERRAIN_DYNAMIC_QTREE_RATIO_SMOOTHING = TERRAIN_DYNAMIC_QTREE_RATIO_SMOOTHING;
  global.TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L1 = TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L1;
  global.TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L2 = TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L2;
  global.TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L3 = TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L3;
  global.TERRAIN_DYNAMIC_QTREE_HEIGHT_L1_M = TERRAIN_DYNAMIC_QTREE_HEIGHT_L1_M;
  global.TERRAIN_DYNAMIC_QTREE_HEIGHT_L2_M = TERRAIN_DYNAMIC_QTREE_HEIGHT_L2_M;
  global.TERRAIN_DYNAMIC_QTREE_HEIGHT_L3_M = TERRAIN_DYNAMIC_QTREE_HEIGHT_L3_M;
  global.TERRAIN_DYNAMIC_QTREE_VISIBLE_TILE_LIMIT = TERRAIN_DYNAMIC_QTREE_VISIBLE_TILE_LIMIT;
  global.TERRAIN_DYNAMIC_QTREE_CACHE_LIMIT = TERRAIN_DYNAMIC_QTREE_CACHE_LIMIT;
  global.TERRAIN_DYNAMIC_QTREE_LOAD_CONCURRENCY = TERRAIN_DYNAMIC_QTREE_LOAD_CONCURRENCY;
  global.TERRAIN_GEOJSON_RENDER_RETRY_MAX = TERRAIN_GEOJSON_RENDER_RETRY_MAX;

  // 统一 toast 提示：用于分析状态、错误、回退信息。
  function ensureToast() {
    var toast = document.getElementById("terrain-backend-toast");
    if (toast) return toast;
    toast = document.createElement("div");
    toast.id = "terrain-backend-toast";
    toast.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:12000;max-width:420px;padding:10px 12px;border-radius:8px;background:rgba(8,18,36,.92);color:#e8f1ff;border:1px solid #4f6c99;font-size:12px;box-shadow:0 8px 20px rgba(0,0,0,.35);display:none;";
    document.body.appendChild(toast);
    return toast;
  }

  function showToast(message, isError) {
    var toast = ensureToast();
    toast.textContent = message;
    toast.style.display = "block";
    toast.style.borderColor = isError ? "#d9534f" : "#4f6c99";
    toast.style.color = isError ? "#ffdede" : "#e8f1ff";
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(function () {
      toast.style.display = "none";
    }, 3200);
  }

  function ensureBackendGuideModal() {
    var modal = document.getElementById("terrain-backend-guide-modal");
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = "terrain-backend-guide-modal";
    modal.style.cssText = "position:fixed;inset:0;z-index:13000;background:rgba(0,0,0,.45);display:none;";
    modal.innerHTML = [
      '<div id="terrain-backend-guide-dialog" style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(620px,92vw);max-height:min(78vh,720px);background:#0d1d38;color:#e8f1ff;border:1px solid #4f6c99;border-radius:12px;padding:16px;box-shadow:0 12px 36px rgba(0,0,0,.45);display:flex;flex-direction:column;">',
      '  <div id="terrain-backend-guide-header" style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid rgba(143,174,216,.25);cursor:move;user-select:none;">',
      '    <strong style="font-size:15px;line-height:1.4;">后端未就绪，按以下步骤处理</strong>',
      '    <button id="terrain-backend-guide-close" type="button" style="flex:0 0 auto;border:1px solid #6e86ad;background:#122a50;color:#e8f1ff;border-radius:6px;padding:4px 10px;cursor:pointer;">关闭</button>',
      '  </div>',
      '  <ol style="margin:0 0 12px 18px;padding:0;line-height:1.75;overflow:auto;word-break:break-word;white-space:normal;">',
      '    <li>在 VS Code 中打开命令面板，运行 <b>Tasks: Run Task</b>，选择 <b>Start Backend</b>。</li>',
      '    <li>如果任务不存在，在终端切到 backend 目录，执行下面命令。</li>',
      '    <li>看到 <b>Uvicorn running on http://127.0.0.1:8000</b> 后，再点“执行后端分析”。</li>',
      '  </ol>',
      '  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:auto;">',
      '    <input id="terrain-backend-guide-cmd" readonly value="cd backend; .\\run_backend.ps1" style="flex:1 1 300px;min-width:0;background:#e9f1ff;color:#0a1f3a;border:1px solid #8aa9d6;border-radius:6px;padding:8px;" />',
      '    <button id="terrain-backend-guide-copy" type="button" style="flex:0 0 auto;border:1px solid #6e86ad;background:#17345f;color:#e8f1ff;border-radius:6px;padding:8px 12px;cursor:pointer;">复制命令</button>',
      '  </div>',
      '</div>'
    ].join("");
    document.body.appendChild(modal);

    var dialog = document.getElementById("terrain-backend-guide-dialog");
    var header = document.getElementById("terrain-backend-guide-header");
    if (dialog && header) {
      var dragging = false;
      var offsetX = 0;
      var offsetY = 0;
      header.addEventListener("mousedown", function (event) {
        dragging = true;
        var rect = dialog.getBoundingClientRect();
        offsetX = event.clientX - rect.left;
        offsetY = event.clientY - rect.top;
        dialog.style.transform = "none";
        dialog.style.left = rect.left + "px";
        dialog.style.top = rect.top + "px";
        event.preventDefault();
      });
      window.addEventListener("mousemove", function (event) {
        if (!dragging) return;
        var minVisible = 56;
        var nextLeft = Math.max(minVisible - dialog.offsetWidth, Math.min(window.innerWidth - minVisible, event.clientX - offsetX));
        var nextTop = Math.max(minVisible - dialog.offsetHeight, Math.min(window.innerHeight - minVisible, event.clientY - offsetY));
        dialog.style.left = nextLeft + "px";
        dialog.style.top = nextTop + "px";
      });
      window.addEventListener("mouseup", function () {
        dragging = false;
      });
    }

    var closeBtn = document.getElementById("terrain-backend-guide-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        modal.style.display = "none";
      });
    }
    modal.addEventListener("click", function (e) {
      if (e.target === modal) modal.style.display = "none";
    });

    var copyBtn = document.getElementById("terrain-backend-guide-copy");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        var input = document.getElementById("terrain-backend-guide-cmd");
        var cmd = input ? input.value : "cd backend; .\\run_backend.ps1";
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(cmd).then(function () {
            showToast("启动命令已复制");
          }).catch(function () {
            showToast("复制失败，请手动复制命令", true);
          });
        }
      });
    }

    return modal;
  }

  function openBackendGuide() {
    var modal = ensureBackendGuideModal();
    if (modal) modal.style.display = "block";
  }

  function setStatus(message, isError) {
    var status = document.getElementById("backend-run-status");
    if (!status) return;
    status.textContent = message;
    status.style.color = isError ? "#ffb4b4" : "#b7d4ff";
  }

  function setStartButtonState(isRunning) {
    var btn = document.getElementById("sidebarStartBackendBtn");
    if (!btn) return;
    btn.style.opacity = isRunning ? "0.75" : "1";
    btn.style.transform = isRunning ? "scale(0.96)" : "scale(1)";
    btn.title = isRunning ? "后端启动检测中..." : "启动后端服务";
  }

  function toFixed6(value) {
    return Number(value).toFixed(6);
  }

  function getViewBBox(viewer) {
    try {
      const rect = viewer.camera.computeViewRectangle(viewer.scene.globe.ellipsoid);
      if (!rect) return null;
      return {
        west: Cesium.Math.toDegrees(rect.west),
        south: Cesium.Math.toDegrees(rect.south),
        east: Cesium.Math.toDegrees(rect.east),
        north: Cesium.Math.toDegrees(rect.north),
      };
    } catch (error) {
      console.warn("[TerrainBackend] 获取视域范围失败:", error);
      return null;
    }
  }

  function resolveDynamicViewBBox(state) {
    if (!state) return null;
    var viewBBox = getViewBBox(state.viewer);
    if (viewBBox) {
      state.lastViewBBox = viewBBox;
      return viewBBox;
    }
    return state.lastViewBBox || null;
  }

  function fillBBoxInputs(bbox) {
    if (!bbox) return;
    const west = document.getElementById("backend-bbox-west");
    const south = document.getElementById("backend-bbox-south");
    const east = document.getElementById("backend-bbox-east");
    const north = document.getElementById("backend-bbox-north");
    if (west) west.value = toFixed6(bbox.west);
    if (south) south.value = toFixed6(bbox.south);
    if (east) east.value = toFixed6(bbox.east);
    if (north) north.value = toFixed6(bbox.north);
  }

  function getBBoxFromInputs() {
    return {
      west: Number(document.getElementById("backend-bbox-west")?.value),
      south: Number(document.getElementById("backend-bbox-south")?.value),
      east: Number(document.getElementById("backend-bbox-east")?.value),
      north: Number(document.getElementById("backend-bbox-north")?.value),
    };
  }

  function getSelectedFormats() {
    const checked = Array.from(document.querySelectorAll("input[name='backend-format']:checked"));
    return checked.map((item) => item.value);
  }

  function getMaxResolutionForMode(mode) {
    return mode === "path" ? PATH_MAX_RESOLUTION : TERRAIN_MAX_RESOLUTION;
  }

  function estimateResolutionFromCellSize(bbox, cellSizeMeters, maxResolution) {
    var cell = Math.max(1.0, Number(cellSizeMeters) || 50.0);
    var cap = Math.max(16, Number(maxResolution) || PATH_MAX_RESOLUTION);
    var centerLat = ((bbox.south + bbox.north) * 0.5) * Math.PI / 180.0;
    var metersPerDegLon = 111320.0 * Math.max(1e-6, Math.cos(centerLat));
    var metersPerDegLat = 110574.0;
    var widthM = Math.abs(bbox.east - bbox.west) * metersPerDegLon;
    var heightM = Math.abs(bbox.north - bbox.south) * metersPerDegLat;
    var span = Math.max(widthM, heightM);

    // 用 ceil 而非 round，确保“实际米/格”不会大于用户目标米/格。
    var cellsPerEdgeRaw = Math.max(1, Math.ceil(span / cell));
    var resolutionRaw = cellsPerEdgeRaw + 1;
    var resolution = Math.max(16, Math.min(cap, resolutionRaw));

    var actualCellX = widthM / Math.max(1, (resolution - 1));
    var actualCellY = heightM / Math.max(1, (resolution - 1));

    return {
      resolution: resolution,
      requestedCell: cell,
      actualCellX: actualCellX,
      actualCellY: actualCellY,
      widthM: widthM,
      heightM: heightM,
      maxResolution: cap,
      clippedByLimit: resolution !== resolutionRaw,
    };
  }

  function updateGridSchemeUi(mode) {
    var currentMode = mode || document.getElementById("backend-analysis-mode")?.value || "terrain";
    var maxResolution = getMaxResolutionForMode(currentMode);
    var hint = document.getElementById("backend-grid-hint");
    if (hint) {
      hint.textContent = "按米/格自动换算后端网格数(每边16~" + maxResolution + ")";
    }
  }

  function estimateAnalysisTimeoutMs(mode, resolution, formatCount, hasDemPath) {
    var n = Math.max(16, Number(resolution) || 16);
    var f = Math.max(1, Number(formatCount) || 1);
    var base = REQUEST_TIMEOUT_MS;
    var byGrid = n * n * 0.12;
    var byFormat = f * 4000;
    var byMode = mode === "path" ? 30000 : 12000;
    var byDem = hasDemPath ? 12000 : 0;
    var estimated = base + byGrid + byFormat + byMode + byDem;
    return Math.max(25000, Math.min(240000, Math.round(estimated)));
  }

  function formatRequestIds(requestIds) {
    var ids = Array.isArray(requestIds) ? requestIds.filter(Boolean) : [];
    if (!ids.length) return "-";
    if (ids.length <= 3) return ids.join(",");
    return ids.slice(0, 3).join(",") + "...(+" + (ids.length - 3) + ")";
  }

  function splitBBoxIntoTiles(bbox, cols, rows) {
    var c = Math.max(1, Math.floor(Number(cols) || 1));
    var r = Math.max(1, Math.floor(Number(rows) || 1));
    var lonStep = (bbox.east - bbox.west) / c;
    var latStep = (bbox.north - bbox.south) / r;
    var tiles = [];
    var index = 0;

    for (var row = 0; row < r; row++) {
      var south = bbox.south + latStep * row;
      var north = row === r - 1 ? bbox.north : (bbox.south + latStep * (row + 1));
      for (var col = 0; col < c; col++) {
        var west = bbox.west + lonStep * col;
        var east = col === c - 1 ? bbox.east : (bbox.west + lonStep * (col + 1));
        index += 1;
        tiles.push({
          index: index,
          row: row,
          col: col,
          bbox: {
            west: west,
            south: south,
            east: east,
            north: north,
          },
        });
      }
    }
    return tiles;
  }

  function expandTileBBoxWithOverlap(tileBBox, fullBBox, cols, rows, overlapCells) {
    var overlap = Math.max(0, Number(overlapCells) || 0);
    if (overlap <= 0) {
      return {
        west: tileBBox.west,
        south: tileBBox.south,
        east: tileBBox.east,
        north: tileBBox.north,
      };
    }

    var c = Math.max(1, Number(cols) || 1);
    var r = Math.max(1, Number(rows) || 1);
    var lonStep = (fullBBox.east - fullBBox.west) / c;
    var latStep = (fullBBox.north - fullBBox.south) / r;
    var dx = lonStep * overlap;
    var dy = latStep * overlap;

    return {
      west: Math.max(fullBBox.west, tileBBox.west - dx),
      south: Math.max(fullBBox.south, tileBBox.south - dy),
      east: Math.min(fullBBox.east, tileBBox.east + dx),
      north: Math.min(fullBBox.north, tileBBox.north + dy),
    };
  }

  function estimateTerrainTileLayout(bbox, cellSizeMeters, maxResolution, options) {
    var opts = options || {};
    var cell = Math.max(1.0, Number(cellSizeMeters) || 50.0);
    var hardCapCellsPerEdge = Math.max(1, (Math.max(16, Number(maxResolution) || TERRAIN_MAX_RESOLUTION) - 1));
    // 避免单块过大导致浏览器 JSON 解析或渲染压力过高。
    var edgeTarget = Number(opts.edgeTarget);
    var target = Number.isFinite(edgeTarget) ? edgeTarget : TERRAIN_TILE_EDGE_TARGET;
    var capCellsPerEdge = Math.max(1, Math.min(hardCapCellsPerEdge, Math.max(16, target)));

    var centerLat = ((bbox.south + bbox.north) * 0.5) * Math.PI / 180.0;
    var metersPerDegLon = 111320.0 * Math.max(1e-6, Math.cos(centerLat));
    var metersPerDegLat = 110574.0;
    var widthM = Math.abs(bbox.east - bbox.west) * metersPerDegLon;
    var heightM = Math.abs(bbox.north - bbox.south) * metersPerDegLat;

    var cellsX = Math.max(1, Math.ceil(widthM / cell));
    var cellsY = Math.max(1, Math.ceil(heightM / cell));
    var cols = Math.max(1, Math.ceil(cellsX / capCellsPerEdge));
    var rows = Math.max(1, Math.ceil(cellsY / capCellsPerEdge));
    return {
      cols: cols,
      rows: rows,
      total: cols * rows,
      widthM: widthM,
      heightM: heightM,
      cellsX: cellsX,
      cellsY: cellsY,
      capCellsPerEdge: capCellsPerEdge,
      hardCapCellsPerEdge: hardCapCellsPerEdge,
    };
  }

  function getTerrainRequestLodCellScale(viewer) {
    if (!TERRAIN_REQUEST_LOD_ENABLE) return 1.0;
    if (!viewer || !viewer.camera || !viewer.camera.positionCartographic) return TERRAIN_REQUEST_LOD_CELL_SCALE_NEAR;

    var h = Number(viewer.camera.positionCartographic.height) || 0;
    if (h >= TERRAIN_REQUEST_LOD_HEIGHT_MID_M) return TERRAIN_REQUEST_LOD_CELL_SCALE_FAR;
    if (h >= TERRAIN_REQUEST_LOD_HEIGHT_NEAR_M) return TERRAIN_REQUEST_LOD_CELL_SCALE_MID;
    return TERRAIN_REQUEST_LOD_CELL_SCALE_NEAR;
  }

  function buildPathResolutionStages(targetResolution) {
    var target = Math.max(16, Math.min(PATH_MAX_RESOLUTION, Math.floor(Number(targetResolution) || 80)));
    var stages = [];
    if (target <= 96) {
      stages = [target];
    } else if (target <= 160) {
      stages = [96, target];
    } else if (target <= 256) {
      stages = [96, 160, target];
    } else {
      stages = [96, 160, 256, target];
    }

    var uniq = [];
    for (var i = 0; i < stages.length; i++) {
      var n = Math.max(16, Math.min(PATH_MAX_RESOLUTION, Math.floor(Number(stages[i]) || 16)));
      if (uniq.indexOf(n) < 0) uniq.push(n);
    }
    return uniq;
  }

  function sleepMs(ms) {
    return new Promise(function (resolve) {
      setTimeout(resolve, Math.max(0, Number(ms) || 0));
    });
  }

  function roundTo(value, digits) {
    var num = Number(value);
    if (!Number.isFinite(num)) return 0;
    var pow = Math.pow(10, Math.max(0, Math.floor(Number(digits) || 0)));
    return Math.round(num * pow) / pow;
  }

  function stableStringify(value) {
    if (value === null || typeof value === "undefined") return "null";
    if (typeof value !== "object") return JSON.stringify(value);
    if (Array.isArray(value)) {
      return "[" + value.map(stableStringify).join(",") + "]";
    }
    var keys = Object.keys(value).sort();
    var parts = [];
    for (var i = 0; i < keys.length; i++) {
      var key = keys[i];
      parts.push(JSON.stringify(key) + ":" + stableStringify(value[key]));
    }
    return "{" + parts.join(",") + "}";
  }

  function hashStringFNV1a(text) {
    var str = String(text || "");
    var hash = 2166136261;
    for (var i = 0; i < str.length; i++) {
      hash ^= str.charCodeAt(i);
      hash = (hash * 16777619) >>> 0;
    }
    return ("00000000" + hash.toString(16)).slice(-8);
  }

  function buildTerrainTileSetId(options) {
    var opt = options || {};
    var bbox = opt.bbox || {};
    var decode = opt.decodePayload || {};
    var payload = {
      bbox: {
        west: roundTo(bbox.west, 6),
        south: roundTo(bbox.south, 6),
        east: roundTo(bbox.east, 6),
        north: roundTo(bbox.north, 6),
      },
      cellSizeMeters: roundTo(opt.cellSizeMeters, 3),
      maxResolution: Math.round(Number(opt.maxResolution) || TERRAIN_MAX_RESOLUTION),
      demPath: String(opt.demPath || ""),
      demDecodeMode: String(decode.dem_decode_mode || "none"),
      demDecodeBand: Number(decode.dem_decode_band || 1),
      demDecodeScale: roundTo(decode.dem_decode_scale, 6),
      demDecodeOffset: roundTo(decode.dem_decode_offset, 6),
      demDecodeNodata: (decode.dem_decode_nodata === null || typeof decode.dem_decode_nodata === "undefined")
        ? null
        : roundTo(decode.dem_decode_nodata, 6),
      startPoint: Array.isArray(opt.startPoint) ? [roundTo(opt.startPoint[0], 6), roundTo(opt.startPoint[1], 6)] : null,
      endPoint: Array.isArray(opt.endPoint) ? [roundTo(opt.endPoint[0], 6), roundTo(opt.endPoint[1], 6)] : null,
    };
    return "ts_" + hashStringFNV1a(stableStringify(payload));
  }

  function appendCacheBust(url, marker) {
    var base = String(url || "");
    var sep = base.indexOf("?") >= 0 ? "&" : "?";
    return base + sep + "_cb=" + encodeURIComponent(String(marker || Date.now()));
  }

  async function parseJsonResponseSafe(response, label) {
    var text = "";
    try {
      text = await response.text();
    } catch (error) {
      throw new Error((label || "响应") + " 读取失败：" + (error && error.message ? error.message : String(error || "未知错误")));
    }

    if (!text || !text.trim()) {
      throw new Error((label || "响应") + " 为空，可能服务端仍在写出结果文件，请重试");
    }

    try {
      return JSON.parse(text);
    } catch (error2) {
      throw new Error((label || "响应") + " 不是完整 JSON：" + (error2 && error2.message ? error2.message : "解析失败"));
    }
  }

  // 统一请求入口：内置超时、HTTP错误翻译、JSON完整性校验、有限重试。
  async function requestAnalysisJson(baseUrl, endpoint, payload, timeoutMs, stageLabel, runCtx) {
    var label = String(stageLabel || "分析请求");
    var maxAttempts = 3;
    var lastError = null;

    for (var attempt = 1; attempt <= maxAttempts; attempt++) {
      ensureRunNotCancelled(runCtx);
      var response;
      try {
        response = await fetchJsonWithTimeout(`${baseUrl}${endpoint}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }, timeoutMs, runCtx);
      } catch (error) {
        if (runCtx && runCtx.cancelled) {
          throw new Error(runCtx.reason || "分析已终止");
        }
        if (error && error.name === "AbortError") {
          throw new Error(label + " 超时并中止（" + Math.round((timeoutMs || REQUEST_TIMEOUT_MS) / 1000) + "s）");
        }
        lastError = new Error(label + " 网络请求失败：" + (error && error.message ? error.message : String(error || "未知错误")));
        if (attempt < maxAttempts) {
          continue;
        }
        throw lastError;
      }

      if (!response.ok) {
        var message = await extractErrorMessage(response);
        var httpError;
        if (response.status === 422) {
          httpError = new Error(label + " 参数校验失败(422)，请检查 BBox、分辨率和起终点");
        } else if (response.status >= 500) {
          httpError = new Error(label + " 后端错误(" + response.status + ")：" + message);
        } else {
          httpError = new Error(label + " 请求失败(" + response.status + ")：" + message);
        }

        lastError = httpError;
        if (attempt < maxAttempts && response.status >= 500) {
          continue;
        }
        throw httpError;
      }

      try {
        ensureRunNotCancelled(runCtx);
        var data = await parseJsonResponseSafe(response, label + " 返回");
        var artifacts = Array.isArray(data.artifacts) ? data.artifacts : [];
        if (!artifacts.length) {
          throw new Error(label + " 未返回可展示文件");
        }
        return data;
      } catch (parseError) {
        lastError = parseError;
        if (attempt < maxAttempts) {
          await sleepMs(300 * attempt);
          continue;
        }
        throw parseError;
      }
    }

    throw lastError || new Error(label + " 请求失败");
  }

  // 地形分析分块编排：
  // 1) 计算分块布局
  // 2) 按块请求后端
  // 3) 合并所有artifact并返回给渲染层
  async function runTerrainAnalysisWithAutoTiling(options) {
    var baseUrl = options.baseUrl;
    var bbox = options.bbox;
    var cellSizeMeters = options.cellSizeMeters;
    var viewer = options.viewer;
    var maxResolution = options.maxResolution;
    var formats = options.formats;
    var demPath = options.demPath;
    var decodePayload = options.decodePayload;
    var analysisType = options.analysisType;
    var startPoint = Array.isArray(options.startPoint) ? options.startPoint : null;
    var endPoint = Array.isArray(options.endPoint) ? options.endPoint : null;
    var silent = !!options.silent;
    var overlapCells = Math.max(0, Number(options.tileOverlapCells) || 0);
    var tileSetId = options.tileSetId || null;
    var tileKeyBase = options.tileKey || null;
    var tileEdgeTarget = options.tileEdgeTarget;
    var skipRequestLodScale = !!options.skipRequestLodScale;
    var runCtx = options.runCtx || null;

    var fixedTileLayout = options.fixedTileLayout || null;
    var layout = fixedTileLayout || estimateTerrainTileLayout(
      bbox,
      cellSizeMeters,
      maxResolution,
      { edgeTarget: tileEdgeTarget }
    );
    if (layout.total > 64) {
      throw new Error("当前图幅过大，自动分块后达到 " + layout.total + " 块（上限64）。请增大米/格或缩小范围。");
    }

    if (!silent && layout.total > 1) {
      showToast("检测到超大图幅，已启用自动分块分析（" + layout.cols + "x" + layout.rows + "）", false);
    }

    var tiles = splitBBoxIntoTiles(bbox, layout.cols, layout.rows);
    var allArtifacts = [];
    var requestIds = [];
    var demSource = null;
    var lastTimeoutMs = REQUEST_TIMEOUT_MS;
    var cacheHits = 0;
    var cacheMisses = 0;
    var requestLodCellScale = skipRequestLodScale ? 1.0 : getTerrainRequestLodCellScale(viewer);
    var effectiveCellSizeMeters = Math.max(1.0, Number(cellSizeMeters) * requestLodCellScale);

    // 顺序请求分块，便于控制峰值负载和错误定位。
    for (var i = 0; i < tiles.length; i++) {
      ensureRunNotCancelled(runCtx);
      var tile = tiles[i];
      var expandedBbox = expandTileBBoxWithOverlap(tile.bbox, bbox, layout.cols, layout.rows, overlapCells);
      var tileResInfo = estimateResolutionFromCellSize(expandedBbox, effectiveCellSizeMeters, maxResolution);
      var tileResolution = Number(tileResInfo.resolution);
      var timeoutMs = estimateAnalysisTimeoutMs("terrain", tileResolution, formats.length, !!demPath);
      lastTimeoutMs = timeoutMs;

      var tileLabel = "分块分析 " + (i + 1) + "/" + tiles.length + " (N=" + tileResolution + ")";
      if (!silent) {
        setStatus(tileLabel + "...");
      }

      var tileKey = null;
      if (tileKeyBase) {
        tileKey = layout.total > 1
          ? (tileKeyBase + "/sub/" + tile.row + "_" + tile.col)
          : tileKeyBase;
      }

      var tilePayload = Object.assign({
        bbox: expandedBbox,
        resolution: tileResolution,
        analysis_type: analysisType,
        output_formats: formats,
        dem_path: demPath || null,
        tile_set_id: tileSetId,
        tile_key: tileKey,
      }, decodePayload);
      if (analysisType === "cost" && startPoint && endPoint) {
        tilePayload.start_point = startPoint;
        tilePayload.end_point = endPoint;
      }

      var tileData = await requestAnalysisJson(baseUrl, "/api/v1/analyze/terrain", tilePayload, timeoutMs, tileLabel, runCtx);
      ensureRunNotCancelled(runCtx);
      var cacheHit = !!tileData.cache_hit;
      if (cacheHit) {
        cacheHits += 1;
      } else {
        cacheMisses += 1;
      }
      if (!silent) {
        setStatus(tileLabel + (cacheHit ? " (缓存命中)" : " (新算)"));
      }
      var tileArtifacts = Array.isArray(tileData.artifacts) ? tileData.artifacts : [];
      tileArtifacts = tileArtifacts.map(function (artifact) {
        if (!artifact || typeof artifact !== "object") return artifact;
        var extended = Object.assign({}, artifact);
        // 记录“核心bbox”：重叠环用于计算，但渲染时按核心区域裁剪，避免邻块重复绘制。
        extended._tileCoreBBox = tile.bbox;
        return extended;
      });
      requestIds.push(tileData.request_id || "-");
      demSource = tileData.dem_source || demSource;
      allArtifacts = allArtifacts.concat(tileArtifacts);
    }

    return {
      artifacts: allArtifacts,
      demSource: demSource,
      requestIds: requestIds,
      tileCount: tiles.length,
      tileLayout: layout,
      fixedTileLayoutApplied: !!fixedTileLayout,
      requestLodCellScale: requestLodCellScale,
      effectiveCellSizeMeters: effectiveCellSizeMeters,
      lastTimeoutMs: lastTimeoutMs,
      cacheHits: cacheHits,
      cacheMisses: cacheMisses,
    };
  }

  async function runPathAnalysisByStages(options) {
    var baseUrl = options.baseUrl;
    var bbox = options.bbox;
    var targetResolution = options.targetResolution;
    var formats = options.formats;
    var demPath = options.demPath;
    var decodePayload = options.decodePayload;
    var startPoint = options.startPoint;
    var endPoint = options.endPoint;
    var runCtx = options.runCtx || null;

    var stages = buildPathResolutionStages(targetResolution);
    var tried = [];
    var succeeded = [];
    var bestData = null;
    var bestResolution = null;
    var lastTimeoutMs = REQUEST_TIMEOUT_MS;

    for (var i = 0; i < stages.length; i++) {
      ensureRunNotCancelled(runCtx);
      var stageResolution = stages[i];
      tried.push(stageResolution);
      var timeoutMs = estimateAnalysisTimeoutMs("path", stageResolution, formats.length, !!demPath);
      lastTimeoutMs = timeoutMs;
      var label = "路径分级 " + (i + 1) + "/" + stages.length + " (N=" + stageResolution + ")";

      setStatus(label + "...");
      var payload = Object.assign({
        bbox: bbox,
        resolution: stageResolution,
        start_point: startPoint,
        end_point: endPoint,
        output_formats: formats,
        dem_path: demPath || null,
      }, decodePayload);

      try {
        var data = await requestAnalysisJson(baseUrl, "/api/v1/analyze/path", payload, timeoutMs, label, runCtx);
        ensureRunNotCancelled(runCtx);
        bestData = data;
        bestResolution = stageResolution;
        succeeded.push(stageResolution);
      } catch (error) {
        if (bestData) {
          showToast("更高分辨率路径阶段失败，自动回退到 N=" + bestResolution, true);
          break;
        }
        throw error;
      }
    }

    if (!bestData) {
      throw new Error("路径分级策略全部失败，请缩小图幅或增大米/格后重试");
    }

    return {
      artifacts: Array.isArray(bestData.artifacts) ? bestData.artifacts : [],
      demSource: bestData.dem_source || null,
      requestIds: [bestData.request_id || "-"],
      bestResolution: bestResolution,
      stagesTried: tried,
      stagesSucceeded: succeeded,
      lastTimeoutMs: lastTimeoutMs,
    };
  }

  function normalizeUrl(baseUrl, relative) {
    const b = String(baseUrl || "").replace(/\/+$/, "");
    const r = String(relative || "");
    if (/^https?:\/\//i.test(r)) return r;
    return `${b}${r}`;
  }

  function validateBBox(bbox) {
    var vals = [bbox.west, bbox.south, bbox.east, bbox.north];
    for (var i = 0; i < vals.length; i++) {
      if (!Number.isFinite(vals[i])) {
        throw new Error("BBox 参数不完整，请先点击“使用当前视域”或手动填写四个范围值");
      }
    }
    if (bbox.west >= bbox.east || bbox.south >= bbox.north) {
      throw new Error("BBox 范围无效：west/east 或 south/north 顺序不正确");
    }
  }

  function bboxIntersects(a, b) {
    if (!a || !b) return false;
    return !(a.east <= b.west || a.west >= b.east || a.north <= b.south || a.south >= b.north);
  }

  function bboxCenter(b) {
    if (!b) return null;
    return {
      lon: (Number(b.west) + Number(b.east)) * 0.5,
      lat: (Number(b.south) + Number(b.north)) * 0.5,
    };
  }

  function expandBBoxByRatio(b, ratio) {
    if (!b) return null;
    var r = Math.max(0, Number(ratio) || 0);
    var dx = (Number(b.east) - Number(b.west)) * r;
    var dy = (Number(b.north) - Number(b.south)) * r;
    return {
      west: Number(b.west) - dx,
      south: Number(b.south) - dy,
      east: Number(b.east) + dx,
      north: Number(b.north) + dy,
    };
  }

  function approxTileDistanceScore(tileBBox, viewBBox) {
    if (!tileBBox || !viewBBox) return Number.MAX_VALUE;
    var tc = bboxCenter(tileBBox);
    var vc = bboxCenter(viewBBox);
    if (!tc || !vc) return Number.MAX_VALUE;
    var dLon = tc.lon - vc.lon;
    var dLat = tc.lat - vc.lat;
    return dLon * dLon + dLat * dLat;
  }

  function getTerrainLodMaxActiveByHeight(viewer) {
    if (!viewer || !viewer.camera || !viewer.camera.positionCartographic) {
      return TERRAIN_LOD_ACTIVE_TILES_NEAR;
    }
    var h = Number(viewer.camera.positionCartographic.height) || 0;
    if (h >= TERRAIN_LOD_HEIGHT_MID_M) return TERRAIN_LOD_ACTIVE_TILES_FAR;
    if (h >= TERRAIN_LOD_HEIGHT_NEAR_M) return TERRAIN_LOD_ACTIVE_TILES_MID;
    return TERRAIN_LOD_ACTIVE_TILES_NEAR;
  }

  function bboxText(b) {
    if (!b) return "-";
    return "[" +
      Number(b.west).toFixed(6) + ", " +
      Number(b.south).toFixed(6) + ", " +
      Number(b.east).toFixed(6) + ", " +
      Number(b.north).toFixed(6) + "]";
  }

  // 近似面积（经纬度矩形）用于视域占比估算，驱动LOD层级选择。
  function bboxAreaApprox(b) {
    if (!b) return 0;
    var w = Math.max(0, Number(b.east) - Number(b.west));
    var h = Math.max(0, Number(b.north) - Number(b.south));
    return w * h;
  }

  function intersectBBox(a, b) {
    if (!a || !b) return null;
    var west = Math.max(Number(a.west), Number(b.west));
    var south = Math.max(Number(a.south), Number(b.south));
    var east = Math.min(Number(a.east), Number(b.east));
    var north = Math.min(Number(a.north), Number(b.north));
    if (west >= east || south >= north) return null;
    return { west: west, south: south, east: east, north: north };
  }

  function smoothDynamicQtreeRatio(state, rawRatio) {
    var alpha = Number(TERRAIN_DYNAMIC_QTREE_RATIO_SMOOTHING);
    if (!state || !(alpha > 0 && alpha < 1)) return rawRatio;
    if (!Number.isFinite(state.lastRatio)) {
      state.lastRatio = rawRatio;
      return rawRatio;
    }
    state.lastRatio = state.lastRatio * (1 - alpha) + rawRatio * alpha;
    return state.lastRatio;
  }

  // 四叉树最大层级由 TERRAIN_DYNAMIC_QTREE_CELL_SCALES 数组长度决定。
  function getTerrainQtreeMaxLevel() {
    return Math.max(0, (Array.isArray(TERRAIN_DYNAMIC_QTREE_CELL_SCALES) ? TERRAIN_DYNAMIC_QTREE_CELL_SCALES.length : 1) - 1);
  }

  // 根据层级取网格缩放倍率：层级越高，scale 越小，分辨率越细。
  function getTerrainQtreeCellScale(levelIndex) {
    var maxLevel = getTerrainQtreeMaxLevel();
    var idx = Math.max(0, Math.min(maxLevel, Number(levelIndex) || 0));
    var scales = Array.isArray(TERRAIN_DYNAMIC_QTREE_CELL_SCALES) ? TERRAIN_DYNAMIC_QTREE_CELL_SCALES : [1.0];
    var s = Number(scales[idx]);
    var safe = Number.isFinite(s) && s > 0 ? s : 1.0;
    return Math.max(1.0, safe);
  }

  function getDynamicTileEdgeTargetByLevel(levelIndex, baseTarget) {
    var idx = Math.max(0, Number(levelIndex) || 0);
    var target = Number(baseTarget) || TERRAIN_DYNAMIC_TILE_EDGE_TARGET;
    if (idx >= 4) {
      target = TERRAIN_DYNAMIC_TILE_EDGE_TARGET_L4;
    } else if (idx >= 3) {
      target = TERRAIN_DYNAMIC_TILE_EDGE_TARGET_L3;
    }
    return Math.max(64, Math.round(target));
  }

  // 按相机高度建议层级（越近越细）。
  function getTerrainQtreeLodByHeight(viewer) {
    var maxLevel = getTerrainQtreeMaxLevel();
    if (!viewer || !viewer.camera || !viewer.camera.positionCartographic) {
      return { levelIndex: 0, height: 0 };
    }

    var h = Number(viewer.camera.positionCartographic.height) || 0;
    var idx = 0;
    if (h < TERRAIN_DYNAMIC_QTREE_HEIGHT_L1_M) idx = 1;
    if (h < TERRAIN_DYNAMIC_QTREE_HEIGHT_L2_M) idx = 2;
    if (h < TERRAIN_DYNAMIC_QTREE_HEIGHT_L3_M) idx = 3;
    if (h < TERRAIN_DYNAMIC_QTREE_HEIGHT_L4_M) idx = 4;
    return {
      levelIndex: Math.max(0, Math.min(maxLevel, idx)),
      height: h,
    };
  }

  // 按“视域占分析范围比例”建议层级（视域越小越细）。
  function getTerrainQtreeLodByRatio(ratio) {
    var r = Math.max(0, Math.min(1, Number(ratio) || 1));
    var idx = 0;
    if (r <= TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L1) idx = 1;
    if (r <= TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L2) idx = 2;
    if (r <= TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L3) idx = 3;
    if (r <= TERRAIN_DYNAMIC_QTREE_VIEW_RATIO_L4) idx = 4;
    return Math.max(0, Math.min(getTerrainQtreeMaxLevel(), idx));
  }

  function ensureTerrainLodBadge() {
    var badge = document.getElementById("terrain-lod-badge");
    if (badge) return badge;

    badge = document.createElement("div");
    badge.id = "terrain-lod-badge";
    badge.style.cssText = "position:fixed;right:16px;top:92px;z-index:12020;padding:7px 10px;border-radius:8px;background:rgba(5,16,34,.9);border:1px solid rgba(120,160,210,.6);color:#d8e8ff;font-size:12px;line-height:1.35;display:none;box-shadow:0 6px 18px rgba(0,0,0,.35);";
    document.body.appendChild(badge);
    return badge;
  }

  // 角标只负责“可观测性”：给用户实时看到当前层级、米/格、缓存规模。
  function updateTerrainLodBadge(lod, baseCellSizeMeters) {
    var badge = ensureTerrainLodBadge();
    if (!lod) {
      badge.style.display = "none";
      return;
    }

    var cellSize = Math.max(1, Number(baseCellSizeMeters) * Number(lod.scale || 1));
    var ratioText = Number.isFinite(Number(lod.ratio)) ? (Number(lod.ratio) * 100).toFixed(1) + "%" : "-";
    var hText = Number.isFinite(Number(lod.height)) ? Number(lod.height).toFixed(0) + "m" : "-";
    var tileText = Number.isFinite(Number(lod.targetTileCount)) ? (" | 视域瓦片: " + Number(lod.targetTileCount)) : "";
    var cacheText = Number.isFinite(Number(lod.cachedTileCount)) ? (" | 缓存瓦片: " + Number(lod.cachedTileCount)) : "";
    badge.innerHTML = "LOD: <b>" + lod.level + "</b> | 米/格: <b>" + cellSize.toFixed(1) + "</b>" + tileText + cacheText + "<br>视域占比: " + ratioText + " | 相机高: " + hText;
    badge.style.display = "block";
  }

  function hideTerrainLodBadge() {
    var badge = document.getElementById("terrain-lod-badge");
    if (badge) {
      badge.style.display = "none";
    }
  }

  // 合成LOD：取“高度建议”和“视域比例建议”的保守结果，避免过细导致OOM。
  function getDynamicTerrainLodLevel(viewer, analysisBBox, viewBBox, state) {
    var effectiveView = viewBBox || getViewBBox(viewer);
    var byHeight = getTerrainQtreeLodByHeight(viewer);
    if (!effectiveView) {
      return {
        level: "L0",
        levelIndex: 0,
        scale: getTerrainQtreeCellScale(0),
        ratio: 1,
        height: byHeight.height,
        byRatioLevel: "L0",
        byHeightLevel: "L" + byHeight.levelIndex,
      };
    }

    var analysisArea = bboxAreaApprox(analysisBBox);
    var intersected = intersectBBox(effectiveView, analysisBBox);
    var viewArea = bboxAreaApprox(intersected);
    var ratio = analysisArea > 0 ? Math.max(0, Math.min(1, viewArea / analysisArea)) : 1;
    ratio = smoothDynamicQtreeRatio(state, ratio);

    var byRatioIdx = getTerrainQtreeLodByRatio(ratio);
    var maxLevel = getTerrainQtreeMaxLevel();
    var bonus = Math.max(0, Math.floor(Number(TERRAIN_DYNAMIC_QTREE_HEIGHT_BONUS_LEVELS) || 0));
    var heightCap = Math.min(maxLevel, byHeight.levelIndex + bonus);
    // 若视域基本覆盖全域，则保持 L0，即使相机高度建议可升到 L1+。
    var idx = byRatioIdx === 0
      ? 0
      : Math.max(byHeight.levelIndex, Math.min(byRatioIdx, heightCap));
    var chosen = {
      level: "L" + idx,
      levelIndex: idx,
      scale: getTerrainQtreeCellScale(idx),
    };
    chosen.ratio = ratio;
    chosen.height = byHeight.height;
    chosen.byRatioLevel = "L" + byRatioIdx;
    chosen.byHeightLevel = "L" + byHeight.levelIndex;
    return chosen;
  }

  function setDecodePanelVisible(visible, message, suggestions) {
    var panel = document.getElementById("backend-dem-decode-panel");
    if (!panel) return;
    panel.style.display = visible ? "flex" : "none";
    if (!visible) return;

    var hint = document.getElementById("backend-dem-decode-hint");
    if (!hint) return;
    var msg = String(message || "当前 DEM 默认不可直接分析，请选择解码模式后再次执行");
    hint.textContent = msg;
  }

  function applySuggestedDecodeMode(suggestions) {
    var modeSelect = document.getElementById("backend-dem-decode-mode");
    if (!modeSelect) return;

    var current = String(modeSelect.value || "none").toLowerCase();
    if (current !== "none") return;
    if (!Array.isArray(suggestions) || !suggestions.length) return;

    var allowed = { single_band: true, terrain_rgb: true };
    var options = Array.from(modeSelect.options || []).map(function (opt) {
      return String(opt.value || "").toLowerCase();
    });

    for (var i = 0; i < suggestions.length; i++) {
      var candidate = String(suggestions[i] || "").toLowerCase();
      if (allowed[candidate] && options.indexOf(candidate) >= 0) {
        modeSelect.value = candidate;
        return;
      }
    }
  }

  function updateDecodeModeUi() {
    var mode = document.getElementById("backend-dem-decode-mode")?.value || "none";
    var showBand = mode === "single_band";
    var bandLabel = document.getElementById("backend-dem-decode-band-label");
    var bandInput = document.getElementById("backend-dem-decode-band");
    if (bandLabel) bandLabel.style.display = showBand ? "inline-block" : "none";
    if (bandInput) bandInput.style.display = showBand ? "inline-block" : "none";
  }

  function parseOptionalNumberInput(inputId) {
    var el = document.getElementById(inputId);
    if (!el) return null;
    var raw = String(el.value || "").trim();
    if (!raw) return null;
    var num = Number(raw);
    if (!Number.isFinite(num)) {
      throw new Error(inputId + " 不是有效数字");
    }
    return num;
  }

  function getDecodePayloadFromUi() {
    var mode = document.getElementById("backend-dem-decode-mode")?.value || "none";
    var scale = Number(document.getElementById("backend-dem-decode-scale")?.value || 1);
    var offset = Number(document.getElementById("backend-dem-decode-offset")?.value || 0);
    var band = Number(document.getElementById("backend-dem-decode-band")?.value || 1);
    var nodata = parseOptionalNumberInput("backend-dem-decode-nodata");

    if (!Number.isFinite(scale) || !Number.isFinite(offset)) {
      throw new Error("DEM 解码 scale/offset 必须是有效数字");
    }
    if (mode === "single_band") {
      if (!Number.isFinite(band) || band < 1 || Math.floor(band) !== band) {
        throw new Error("single_band 解码要求波段为正整数");
      }
    }

    return {
      dem_decode_mode: mode,
      dem_decode_band: Number.isFinite(band) ? band : 1,
      dem_decode_scale: scale,
      dem_decode_offset: offset,
      dem_decode_nodata: nodata,
    };
  }

  function resetDecodeUi() {
    var mode = document.getElementById("backend-dem-decode-mode");
    var band = document.getElementById("backend-dem-decode-band");
    var scale = document.getElementById("backend-dem-decode-scale");
    var offset = document.getElementById("backend-dem-decode-offset");
    var nodata = document.getElementById("backend-dem-decode-nodata");
    if (mode) mode.value = "none";
    if (band) band.value = "1";
    if (scale) scale.value = "1";
    if (offset) offset.value = "0";
    if (nodata) nodata.value = "";
    updateDecodeModeUi();
    setDecodePanelVisible(false);
  }

  function createAnalysisRunContext() {
    return {
      id: Date.now() + "_" + Math.random().toString(36).slice(2, 8),
      cancelled: false,
      reason: "",
      controllers: [],
    };
  }

  function registerRunController(runCtx, controller) {
    if (!runCtx || !controller) return;
    if (!Array.isArray(runCtx.controllers)) {
      runCtx.controllers = [];
    }
    runCtx.controllers.push(controller);
  }

  function cancelAnalysisRun(runCtx, reason) {
    if (!runCtx || runCtx.cancelled) return;
    runCtx.cancelled = true;
    runCtx.reason = String(reason || "分析已终止");
    var ctrls = Array.isArray(runCtx.controllers) ? runCtx.controllers : [];
    for (var i = 0; i < ctrls.length; i++) {
      try {
        ctrls[i].abort();
      } catch (_) {
        // 忽略重复 abort。
      }
    }
  }

  function ensureRunNotCancelled(runCtx) {
    if (runCtx && runCtx.cancelled) {
      throw new Error(runCtx.reason || "分析已终止");
    }
  }

  async function fetchJsonWithTimeout(url, options, timeoutMs, runCtx) {
    ensureRunNotCancelled(runCtx);
    var controller = new AbortController();
    registerRunController(runCtx, controller);
    var timer = setTimeout(function () {
      controller.abort();
    }, timeoutMs || REQUEST_TIMEOUT_MS);
    try {
      if (runCtx && runCtx.cancelled) {
        controller.abort();
      }
      var response = await fetch(url, Object.assign({}, options || {}, { signal: controller.signal }));
      return response;
    } finally {
      clearTimeout(timer);
    }
  }

  async function checkBackendReady(baseUrl) {
    var url = (String(baseUrl || "http://127.0.0.1:8000").replace(/\/+$/, "")) + "/api/v1/formats";
    try {
      var response = await fetchJsonWithTimeout(url, { method: "GET" }, 4500);
      return response.ok;
    } catch (error) {
      return false;
    }
  }

  async function getDemMetadata(baseUrl, demPath) {
    var safe = encodeURIComponent(String(demPath || "").trim());
    var url = (String(baseUrl || "http://127.0.0.1:8000").replace(/\/+$/, "")) + "/api/v1/dem/meta?dem_path=" + safe;
    var response = await fetchJsonWithTimeout(url, { method: "GET" }, 12000);
    if (!response.ok) {
      var txt = "";
      try {
        txt = await response.text();
      } catch (_) {
        txt = "";
      }
      throw new Error(txt || ("读取 DEM 元数据失败: HTTP " + response.status));
    }
    return response.json();
  }

  function pickLonLatOnGlobe(viewer, screenPosition) {
    if (!viewer || !screenPosition) return null;
    var ray = viewer.camera.getPickRay(screenPosition);
    var cartesian = ray ? viewer.scene.globe.pick(ray, viewer.scene) : null;
    if (!cartesian && viewer.scene.pickPositionSupported) {
      cartesian = viewer.scene.pickPosition(screenPosition);
    }
    if (!cartesian) return null;
    var c = Cesium.Cartographic.fromCartesian(cartesian);
    if (!c) return null;
    return {
      lon: Cesium.Math.toDegrees(c.longitude),
      lat: Cesium.Math.toDegrees(c.latitude),
    };
  }

  function pointInBboxWgs84(pt, bbox) {
    if (!pt || !bbox) return false;
    return pt.lon >= Number(bbox.west) &&
      pt.lon <= Number(bbox.east) &&
      pt.lat >= Number(bbox.south) &&
      pt.lat <= Number(bbox.north);
  }

  function buildExpandedDiagonalBBoxWgs84(p1, p2, expandMeters, limitBBox) {
    var west0 = Math.min(Number(p1.lon), Number(p2.lon));
    var east0 = Math.max(Number(p1.lon), Number(p2.lon));
    var south0 = Math.min(Number(p1.lat), Number(p2.lat));
    var north0 = Math.max(Number(p1.lat), Number(p2.lat));
    var centerLatRad = Cesium.Math.toRadians((south0 + north0) * 0.5);
    var metersPerDegLon = 111320.0 * Math.max(1e-6, Math.cos(centerLatRad));
    var metersPerDegLat = 110574.0;
    var dLon = Math.max(0, Number(expandMeters) || 0) / metersPerDegLon;
    var dLat = Math.max(0, Number(expandMeters) || 0) / metersPerDegLat;

    var bbox = {
      west: west0 - dLon,
      south: south0 - dLat,
      east: east0 + dLon,
      north: north0 + dLat,
    };

    if (limitBBox) {
      bbox.west = Math.max(Number(limitBBox.west), bbox.west);
      bbox.south = Math.max(Number(limitBBox.south), bbox.south);
      bbox.east = Math.min(Number(limitBBox.east), bbox.east);
      bbox.north = Math.min(Number(limitBBox.north), bbox.north);
    }
    return bbox;
  }

  function cleanupCostTwoPointPick(viewer) {
    var ctx = global._terrainBackendCostPickCtx;
    if (!ctx) return;
    if (ctx.handler) {
      try {
        ctx.handler.destroy();
      } catch (_) {
        // 忽略销毁异常。
      }
    }
    if (viewer && Array.isArray(ctx.entities)) {
      for (var i = 0; i < ctx.entities.length; i++) {
        try {
          viewer.entities.remove(ctx.entities[i]);
        } catch (_) {
          // 忽略无效实体句柄。
        }
      }
    }
    global._terrainBackendCostPickCtx = null;
  }

  function cancelCostTwoPointPick(viewer) {
    var ctx = global._terrainBackendCostPickCtx;
    if (ctx && typeof ctx.finish === "function") {
      try {
        ctx.finish(null);
        return;
      } catch (_) {
        // 若 finish 异常，降级到直接清理。
      }
    }
    cleanupCostTwoPointPick(viewer);
  }

  function pickCostAnalysisDiagonalBBox(viewer, demBounds, expandMeters) {
    cleanupCostTwoPointPick(viewer);
    return new Promise(function (resolve) {
      var selected = [];
      var entities = [];
      var movingPoint = null;
      var handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);

      var settled = false;
      function finish(result) {
        if (settled) return;
        settled = true;
        cleanupCostTwoPointPick(viewer);
        resolve(result || null);
      }

      handler.setInputAction(function (movement) {
        if (!selected[0]) return;
        movingPoint = pickLonLatOnGlobe(viewer, movement && movement.endPosition);
      }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

      handler.setInputAction(function (movement) {
        var pt = pickLonLatOnGlobe(viewer, movement && movement.position);
        if (!pt) {
          showToast("未拾取到地面点，请在地形区域重试", true);
          return;
        }
        if (!pointInBboxWgs84(pt, demBounds)) {
          showToast("选点超出 DEM 覆盖范围，请重新选择", true);
          return;
        }

        selected.push(pt);
        var marker = viewer.entities.add({
          position: Cesium.Cartesian3.fromDegrees(pt.lon, pt.lat),
          point: {
            pixelSize: 10,
            color: selected.length === 1 ? Cesium.Color.LIME : Cesium.Color.YELLOW,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
          },
        });
        entities.push(marker);

        if (selected.length === 1) {
          var previewRect = viewer.entities.add({
            rectangle: {
              coordinates: new Cesium.CallbackProperty(function () {
                var p2 = movingPoint || selected[0];
                return Cesium.Rectangle.fromDegrees(
                  Math.min(selected[0].lon, p2.lon),
                  Math.min(selected[0].lat, p2.lat),
                  Math.max(selected[0].lon, p2.lon),
                  Math.max(selected[0].lat, p2.lat)
                );
              }, false),
              material: Cesium.Color.CYAN.withAlpha(0.15),
              outline: true,
              outlineColor: Cesium.Color.CYAN,
              height: 0,
            },
          });
          entities.push(previewRect);
          showToast("已选第1点，请点击第2点完成通行代价分析区域");
          return;
        }

        var minSpan = 1e-7;
        if (Math.abs(selected[0].lon - selected[1].lon) < minSpan ||
            Math.abs(selected[0].lat - selected[1].lat) < minSpan) {
          showToast("两个点过近或共经纬线，无法形成有效区域，请重选", true);
          selected = [];
          for (var ei = 0; ei < entities.length; ei++) {
            try {
              viewer.entities.remove(entities[ei]);
            } catch (_) {}
          }
          entities = [];
          return;
        }

        var bbox = buildExpandedDiagonalBBoxWgs84(selected[0], selected[1], expandMeters, demBounds);
        finish({
          bbox: bbox,
          startPoint: [selected[0].lon, selected[0].lat],
          endPoint: [selected[1].lon, selected[1].lat],
        });
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

      handler.setInputAction(function () {
        showToast("已取消两点选区");
        finish(null);
      }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);

      global._terrainBackendCostPickCtx = {
        handler: handler,
        entities: entities,
        finish: finish,
      };
    });
  }

  // 由于后端可能在写出结果文件后才清理缓存，所以前端在分析完成后会主动请求一次清理，避免用户下一次分析时拿到过期的结果文件。
  async function clearBackendOutputCache(baseUrl, options) {
    var cfg = options || {};
    var useBeacon = !!cfg.useBeacon;
    var silent = cfg.silent !== false;
    var root = String(baseUrl || "http://127.0.0.1:8000").replace(/\/+$/, "");
    var url = root + "/api/v1/cache/outputs/clear";

    try {
      if (useBeacon && navigator && typeof navigator.sendBeacon === "function") {
        navigator.sendBeacon(url, new Blob([], { type: "text/plain" }));
        return;
      }

      var response = await fetch(url, {
        method: "POST",
        keepalive: true,
        cache: "no-store",
      });
      if (!response.ok) {
        if (!silent) {
          showToast("后端缓存清理失败: HTTP " + response.status, true);
        }
        return;
      }

      if (!silent) {
        showToast("后端输出缓存已清理", false);
      }
    } catch (_) {
      if (!silent) {
        showToast("后端缓存清理请求失败", true);
      }
    }
  }

  async function clearBackendTileCache(baseUrl, options) {
    var cfg = options || {};
    var silent = cfg.silent !== false;
    var root = String(baseUrl || "http://127.0.0.1:8000").replace(/\/+$/, "");
    var url = root + "/api/v1/cache/tiles/clear";
    try {
      var response = await fetch(url, {
        method: "POST",
        keepalive: true,
        cache: "no-store",
      });
      if (!response.ok && !silent) {
        showToast("后端瓦片缓存清理失败: HTTP " + response.status, true);
      }
    } catch (_) {
      if (!silent) {
        showToast("后端瓦片缓存清理请求失败", true);
      }
    }
  }

  function getBackendTaskUri() {
    return "vscode://command/workbench.action.tasks.runTask?%5B%22Start%20Backend%22%5D";
  }

  function launchBackendService() {
    const baseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
    const taskUri = getBackendTaskUri();
    const isHttpPage = window.location && /^https?:$/i.test(window.location.protocol || "");

    setStatus("正在尝试启动后端服务...");
    setStartButtonState(true);

    if (isHttpPage) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText("cd backend; .\\run_backend.ps1").catch(function () {
          // 忽略剪贴板写入失败，不阻断主流程。
        });
      }
      setStatus("当前为浏览器页面，无法静默拉起 VS Code 任务；已复制启动命令", true);
      showToast("请在 VS Code 中运行任务 Start Backend（命令已复制）", true);
      openBackendGuide();
      setStartButtonState(false);
      return false;
    }

    try {
      const popup = window.open(taskUri, "_blank");
      if (popup && !popup.closed) {
        setStatus("已请求 VS Code 运行后端任务...");
        showToast("已发送启动请求，正在等待后端就绪...");
        setTimeout(async function () {
          var ok = await checkBackendReady(baseUrl);
          if (ok) {
            setStatus("后端已就绪");
            showToast("后端已启动，可直接执行分析");
          } else {
            setStatus("未检测到后端，请在终端手动运行 run_backend.ps1", true);
            showToast("后端还没起来，请到 backend 目录运行 run_backend.ps1", true);
          }
          setStartButtonState(false);
        }, 1800);
        return true;
      }
    } catch (error) {
      console.warn("[TerrainBackend] 直接打开任务 URI 失败:", error);
    }

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText("cd backend; .\\run_backend.ps1").catch(function () {
        // 忽略剪贴板写入失败，不阻断主流程。
      });
    }
    setStatus("无法自动启动后端，已复制启动命令", true);
    showToast("无法自动启动后端，命令已复制到剪贴板", true);
    setStartButtonState(false);
    return false;
  }

  async function extractErrorMessage(response) {
    var fallback = "HTTP " + response.status;
    var text = "";
    try {
      text = await response.text();
    } catch (_) {
      text = "";
    }
    if (!text) return fallback;
    try {
      var obj = JSON.parse(text);
      if (obj && typeof obj.detail === "string" && obj.detail.trim()) {
        return obj.detail;
      }
      return text.slice(0, 240);
    } catch (_) {
      return text.slice(0, 240);
    }
  }

  function withTimeout(promise, timeoutMs, timeoutMessage) {
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () {
        reject(new Error(timeoutMessage || "操作超时"));
      }, timeoutMs || REQUEST_TIMEOUT_MS);
      promise.then(function (res) {
        clearTimeout(timer);
        resolve(res);
      }).catch(function (err) {
        clearTimeout(timer);
        reject(err);
      });
    });
  }

  function metricLabel(metricName) {
    var key = String(metricName || "value").toLowerCase();
    if (key === "slope_deg") return "坡度(°)";
    if (key === "aspect_deg") return "坡向(°)";
    if (key === "curvature") return "曲率";
    if (key === "cost") return "代价";
    return "值";
  }

  function hideNumericTip() {
    if (typeof global.CreateRemindertip === "function") {
      global.CreateRemindertip("", { x: 0, y: 0 }, false);
    }
  }

  function extractBackendTipText(pickedObject) {
    if (!Cesium.defined(pickedObject) || !Cesium.defined(pickedObject.id)) return "";
    var pickedId = pickedObject.id;

    if (pickedId && pickedId.type === "TerrainBackendCell" && Number.isFinite(Number(pickedId.value))) {
      var baseText = metricLabel(pickedId.metric) + ": " + Number(pickedId.value).toFixed(4);
      if (String(pickedId.metric || "").toLowerCase() === "cost") {
        var parts = [baseText];
        if (Number.isFinite(Number(pickedId.slopeDeg))) {
          parts.push("坡度: " + Number(pickedId.slopeDeg).toFixed(3) + "°");
        }
        if (Number.isFinite(Number(pickedId.minCostDirDeg))) {
          parts.push("最小代价坡向: " + Number(pickedId.minCostDirDeg).toFixed(1) + "°");
        }
        if (Number.isFinite(Number(pickedId.minCostDirSlopeDeg))) {
          parts.push("该方向坡度: " + Number(pickedId.minCostDirSlopeDeg).toFixed(3) + "°");
        }
        return parts.join(" | ");
      }
      return baseText;
    }

    var entity = pickedId;
    if (!entity || !entity.properties || !entity.properties.value) return "";
    var val = entity.properties.value.getValue ? entity.properties.value.getValue() : entity.properties.value;
    if (!Number.isFinite(Number(val))) return "";

    var nameCandidates = ["slope_deg", "aspect_deg", "curvature", "cost"];
    var propName = "value";
    for (var i = 0; i < nameCandidates.length; i++) {
      var n = nameCandidates[i];
      if (entity.properties[n]) {
        propName = n;
        break;
      }
    }
    return metricLabel(propName) + ": " + Number(val).toFixed(4);
  }

  function enableTerrainBackendNumericTip(viewer) {
    if (!viewer || typeof global.CreateRemindertip !== "function") return;
    if (global._terrainBackendHoverHandler) return;

    var handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction(function (movement) {
      var endPos = movement && movement.endPosition;
      if (!endPos) {
        hideNumericTip();
        return;
      }
      var pickedObject = viewer.scene.pick(endPos);
      var text = extractBackendTipText(pickedObject);
      if (text) {
        global.CreateRemindertip(text, endPos, true);
      } else {
        hideNumericTip();
      }
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    global._terrainBackendHoverHandler = handler;
    global._terrainBackendNumericTipEnabled = true;
  }

  function disableTerrainBackendNumericTip() {
    global._terrainBackendNumericTipEnabled = false;
    if (global._terrainBackendHoverHandler) {
      global._terrainBackendHoverHandler.destroy();
      global._terrainBackendHoverHandler = undefined;
    }
    hideNumericTip();
  }

  function setTerrainBackendNumericTipEnabled(enabled, viewer) {
    var flag = !!enabled;
    global._terrainBackendNumericTipEnabled = flag;
    if (flag) {
      enableTerrainBackendNumericTip(viewer || global._terrainBackendViewer || global.viewer);
      return;
    }
    disableTerrainBackendNumericTip();
  }

  function beautifyBackendPanel(panel) {
    if (!panel || panel.dataset.beautified === "1") return;
    panel.style.position = "fixed";
    panel.style.top = "72px";
    panel.style.right = "16px";
    panel.style.left = "auto";
    panel.style.width = "min(640px, 94vw)";
    panel.style.maxHeight = "80vh";
    panel.style.overflow = "auto";
    panel.style.borderRadius = "12px";
    panel.style.padding = "12px";

    var header = panel.firstElementChild;
    if (header) {
      header.style.position = "sticky";
      header.style.top = "0";
      header.style.background = "rgba(8, 18, 36, 0.96)";
      header.style.paddingBottom = "8px";
      header.style.cursor = "move";
      header.style.zIndex = "1";

      var dragging = false;
      var offsetX = 0;
      var offsetY = 0;
      header.addEventListener("mousedown", function (e) {
        dragging = true;
        var rect = panel.getBoundingClientRect();
        offsetX = e.clientX - rect.left;
        offsetY = e.clientY - rect.top;
        panel.style.right = "auto";
        panel.style.left = rect.left + "px";
        panel.style.top = rect.top + "px";
        e.preventDefault();
      });
      window.addEventListener("mousemove", function (e) {
        if (!dragging) return;
        var minVisible = 56;
        var nextLeft = Math.max(minVisible - panel.offsetWidth, Math.min(window.innerWidth - minVisible, e.clientX - offsetX));
        var nextTop = Math.max(minVisible - panel.offsetHeight, Math.min(window.innerHeight - minVisible, e.clientY - offsetY));
        panel.style.left = nextLeft + "px";
        panel.style.top = nextTop + "px";
      });
      window.addEventListener("mouseup", function () {
        dragging = false;
      });
    }

    var rows = panel.querySelectorAll(".row");
    rows.forEach(function (row) {
      if (row.id !== "backend-dem-decode-panel") {
        row.style.display = "flex";
      }
      row.style.alignItems = "center";
      row.style.flexWrap = "wrap";
      row.style.gap = "6px";
      row.style.margin = "0 0 8px 0";
    });

    var labels = panel.querySelectorAll("label");
    labels.forEach(function (label) {
      if (!label.style.minWidth) {
        label.style.minWidth = "90px";
      }
      label.style.wordBreak = "break-all";
      label.style.lineHeight = "1.35";
    });

    var status = panel.querySelector("#backend-run-status");
    if (status) {
      status.style.display = "inline-block";
      status.style.maxWidth = "95%";
      status.style.wordBreak = "break-all";
      status.style.lineHeight = "1.35";
    }

    panel.dataset.beautified = "1";
  }

  function clearManagedBackendLayers(viewer, options) {
    var cfg = options || {};
    cancelCostTwoPointPick(viewer);
    if (!cfg.keepDynamicLod) {
      stopDynamicTerrainRequestLod(viewer);
    }

    if (global._terrainBackendLodState && viewer) {
      try {
        releaseTerrainLodState(viewer);
      } catch (_) {
        // 全量清理阶段忽略 LOD 释放异常，避免影响主清理流程。
      }
    }

    if (window.sidebarManager && Array.isArray(window.sidebarManager.layers)) {
      var managed = window.sidebarManager.layers.filter(function (layer) {
        return layer && layer.extras && layer.extras._backendManaged === true;
      });
      managed.forEach(function (layer) {
        try {
          window.sidebarManager.removeLayer(layer.id);
        } catch (_) {
          // 忽略单图层清理异常，继续处理剩余图层。
        }
      });
    }

    var layers = global._terrainBackendLayers || [];
    for (var i = 0; i < layers.length; i++) {
      var layer = layers[i];
      if (layer && layer.type === "analysis" && Array.isArray(layer.items)) {
        for (var k = 0; k < layer.items.length; k++) {
          try {
            var item = layer.items[k];
            if (item && item.primitive) {
              viewer.scene.primitives.remove(item.primitive);
            }
          } catch (_) {
            // 忽略失效 primitive 句柄异常。
          }
        }
        continue;
      }
      try {
        viewer.dataSources.remove(layer, true);
      } catch (_) {
        // 忽略失效 dataSource 句柄异常。
      }
    }
    global._terrainBackendLayers = [];
    global._terrainBackendSidebarLayerId = null;
  }

  async function renderTerrainArtifacts(viewer, artifacts, baseUrl, bbox, analysisType, options) {
    options = options || {};
    var runCtx = options.runCtx || null;
    var targetLayerStore = Array.isArray(options.layerStore) ? options.layerStore : global._terrainBackendLayers;
    var visibleOverride = typeof options.visibleOverride === "boolean" ? options.visibleOverride : null;
    var registerSidebar = options.registerSidebar !== false;

    releaseTerrainLodState(viewer);

    var loadedCount = 0;
    var failedCount = 0;
    var firstError = null;

    // 逐个artifact加载，失败可局部重试并容错，不让单个瓦片拖垮整体。
    for (var i = 0; i < artifacts.length; i++) {
      ensureRunNotCancelled(runCtx);
      var item = artifacts[i];
      var url = normalizeUrl(baseUrl, item.url);
      var clipBbox = item._tileCoreBBox || bbox;
      var isSlope = /slope_deg\./i.test(String(item.url || ""));
      var keepVisible = !(analysisType === "comprehensive" && !isSlope);
      var shouldShow = visibleOverride === null ? keepVisible : visibleOverride;

      var maxRetry = item.format === "geojson" ? TERRAIN_GEOJSON_RENDER_RETRY_MAX : 1;
      var success = false;
      var lastError = null;
      for (var attempt = 1; attempt <= maxRetry; attempt++) {
        try {
          await loadArtifactToCesium(
            viewer,
            url,
            item.format,
            targetLayerStore,
            shouldShow,
            { clipBbox: clipBbox, registerSidebar: registerSidebar, runCtx: runCtx }
          );
          ensureRunNotCancelled(runCtx);
          success = true;
          loadedCount += 1;
          break;
        } catch (error) {
          lastError = error;
          if (attempt < maxRetry) {
            await sleepMs(350 * attempt);
          }
        }
      }

      if (!success) {
        failedCount += 1;
        if (!firstError) firstError = lastError;
        console.warn("[TerrainBackend] 分块渲染失败，已跳过:", item && item.url, lastError);
      }
    }

    if (!loadedCount) {
      throw firstError || new Error("图层渲染失败：没有可用分块被成功加载");
    }
    if (failedCount > 0) {
      showToast("部分分块渲染失败（" + failedCount + "），已加载其余可用分块", true);
    }

    return {
      loadedCount: loadedCount,
      failedCount: failedCount,
    };
  }

  function terrainQtreeNodeKey(z, x, y) {
    return z + "/" + x + "/" + y;
  }

  function getTerrainQtreeTileBBox(rootBBox, z, x, y) {
    var levelDiv = Math.pow(2, Math.max(0, Number(z) || 0));
    var lonStep = (Number(rootBBox.east) - Number(rootBBox.west)) / levelDiv;
    var latStep = (Number(rootBBox.north) - Number(rootBBox.south)) / levelDiv;

    return {
      west: Number(rootBBox.west) + lonStep * x,
      south: Number(rootBBox.south) + latStep * y,
      east: x === levelDiv - 1 ? Number(rootBBox.east) : (Number(rootBBox.west) + lonStep * (x + 1)),
      north: y === levelDiv - 1 ? Number(rootBBox.north) : (Number(rootBBox.south) + latStep * (y + 1)),
    };
  }

  function ensureTerrainQtreeNode(state, z, x, y) {
    if (!state) return null;
    if (!state.nodeMap) state.nodeMap = {};

    var zi = Math.max(0, Number(z) || 0);
    var div = Math.pow(2, zi);
    var xi = Math.max(0, Math.min(div - 1, Math.floor(Number(x) || 0)));
    var yi = Math.max(0, Math.min(div - 1, Math.floor(Number(y) || 0)));
    var key = terrainQtreeNodeKey(zi, xi, yi);
    if (state.nodeMap[key]) return state.nodeMap[key];

    var parentKey = null;
    if (zi > 0) {
      var parent = ensureTerrainQtreeNode(state, zi - 1, Math.floor(xi / 2), Math.floor(yi / 2));
      parentKey = parent ? parent.key : null;
    }

    // 说明：nodeMap 是本文件核心“前端四叉树缓存”。
    var node = {
      key: key,
      z: zi,
      x: xi,
      y: yi,
      bbox: getTerrainQtreeTileBBox(state.bbox, zi, xi, yi),
      parentKey: parentKey,
      childrenKeys: [],
      layerEntries: [],
      loaded: false,
      loading: false,
      lastUsedAt: 0,
      failureCount: 0,
    };
    state.nodeMap[key] = node;

    if (parentKey && state.nodeMap[parentKey]) {
      state.nodeMap[parentKey].childrenKeys.push(key);
    }

    return node;
  }

  function countTerrainQtreeLoadedDetailNodes(state) {
    if (!state || !state.nodeMap) return 0;
    var count = 0;
    var keys = Object.keys(state.nodeMap);
    for (var i = 0; i < keys.length; i++) {
      var node = state.nodeMap[keys[i]];
      if (node && node.z > 0 && node.loaded) {
        count += 1;
      }
    }
    return count;
  }

  function getTerrainQtreeNodesForView(state, targetLevel, viewBBox) {
    if (!state || targetLevel <= 0) return [];
    if (!viewBBox) return [];

    var root = state.bbox;
    var pad = Number(state.viewPaddingFactor);
    if (!Number.isFinite(pad)) {
      pad = TERRAIN_DYNAMIC_QTREE_VIEW_PADDING_FACTOR;
    }
    var expanded = expandBBoxByRatio(viewBBox, pad) || viewBBox;
    if (!bboxIntersects(expanded, root)) {
      return [];
    }

    var clamped = {
      west: Math.max(Number(root.west), Number(expanded.west)),
      south: Math.max(Number(root.south), Number(expanded.south)),
      east: Math.min(Number(root.east), Number(expanded.east)),
      north: Math.min(Number(root.north), Number(expanded.north)),
    };

    var n = Math.pow(2, targetLevel);
    var spanLon = Math.max(1e-12, Number(root.east) - Number(root.west));
    var spanLat = Math.max(1e-12, Number(root.north) - Number(root.south));

    var xMin = Math.floor(((Number(clamped.west) - Number(root.west)) / spanLon) * n);
    var xMax = Math.floor((((Number(clamped.east) - Number(root.west)) / spanLon) * n) - 1e-9);
    var yMin = Math.floor(((Number(clamped.south) - Number(root.south)) / spanLat) * n);
    var yMax = Math.floor((((Number(clamped.north) - Number(root.south)) / spanLat) * n) - 1e-9);

    xMin = Math.max(0, Math.min(n - 1, xMin));
    xMax = Math.max(0, Math.min(n - 1, xMax));
    yMin = Math.max(0, Math.min(n - 1, yMin));
    yMax = Math.max(0, Math.min(n - 1, yMax));

    var nodes = [];
    for (var y = yMin; y <= yMax; y++) {
      for (var x = xMin; x <= xMax; x++) {
        nodes.push(ensureTerrainQtreeNode(state, targetLevel, x, y));
      }
    }

    nodes.sort(function (a, b) {
      return approxTileDistanceScore(a && a.bbox, viewBBox) - approxTileDistanceScore(b && b.bbox, viewBBox);
    });

    var cap = Math.max(8, Math.min(TERRAIN_DYNAMIC_QTREE_VISIBLE_TILE_LIMIT, 4 * Math.pow(2, targetLevel)));
    if (nodes.length > cap) {
      nodes = nodes.slice(0, cap);
    }
    return nodes;
  }

  function removeTerrainQtreeNodeLayerData(viewer, node) {
    if (!node || !Array.isArray(node.layerEntries) || !node.layerEntries.length) return;
    var entries = node.layerEntries.slice();
    for (var i = 0; i < entries.length; i++) {
      removeManagedLayerEntry(viewer, entries[i]);
    }
    node.layerEntries = [];
    node.loaded = false;
  }

  async function loadTerrainQtreeNode(state, node, requestSeq) {
    if (!state || !node || state.disposed) return;
    if (node.loaded || node.loading) return;

    node.loading = true;
    try {
      var tileCellScale = getTerrainQtreeCellScale(node.z);
      var tileEdgeTarget = getDynamicTileEdgeTargetByLevel(node.z, state.tileEdgeTarget);
      // 只请求当前节点bbox，对应“动态请求”而非全域重算。
      var runResult = await runTerrainAnalysisWithAutoTiling({
        baseUrl: state.baseUrl,
        viewer: state.viewer,
        bbox: node.bbox,
        cellSizeMeters: state.baseCellSizeMeters * tileCellScale,
        maxResolution: state.maxResolution,
        formats: state.formats,
        demPath: state.demPath,
        decodePayload: state.decodePayload,
        analysisType: state.analysisType,
        startPoint: state.startPoint,
        endPoint: state.endPoint,
        silent: true,
        tileOverlapCells: TERRAIN_TILE_OVERLAP_CELLS,
        tileSetId: state.tileSetId || null,
        tileKey: node.key,
        tileEdgeTarget: tileEdgeTarget,
        skipRequestLodScale: true,
      });

      if (state.disposed || state.requestSeq !== requestSeq) {
        return;
      }

      var artifacts = Array.isArray(runResult.artifacts) ? runResult.artifacts : [];
      if (!artifacts.length) {
        throw new Error("四叉树瓦片无可用结果");
      }

      // staged加载：先加载到临时数组，确认成功后再挂入全局管理。
      var tileLayers = [];
      try {
        await renderTerrainArtifacts(
          state.viewer,
          artifacts,
          state.baseUrl,
          node.bbox,
          state.analysisType,
          {
            layerStore: tileLayers,
            visibleOverride: false,
            registerSidebar: false,
          }
        );
      } catch (stageError) {
        cleanupManagedLayerStore(state.viewer, tileLayers);
        throw stageError;
      }

      if (state.disposed || state.requestSeq !== requestSeq) {
        cleanupManagedLayerStore(state.viewer, tileLayers);
        return;
      }

      node.layerEntries = tileLayers;
      for (var i = 0; i < tileLayers.length; i++) {
        addManagedLayerEntry(tileLayers[i]);
      }
      node.loaded = true;
      node.lastUsedAt = Date.now();
      node.failureCount = 0;

      var shouldShow = !!(state.requiredSet && state.requiredSet[node.key]);
      setManagedLayerStoreVisibility(node.layerEntries, shouldShow);
    } catch (error) {
      node.failureCount = (node.failureCount || 0) + 1;
      console.warn("[TerrainBackend] 四叉树瓦片加载失败:", node.key, error);
      if (node.failureCount <= 2) {
        showToast("四叉树瓦片加载失败(" + node.key + ")，将按需重试", true);
      }
    } finally {
      node.loading = false;
    }
  }

  async function loadTerrainQtreeNodes(state, nodes, requestSeq) {
    var queue = Array.isArray(nodes) ? nodes.slice() : [];
    if (!queue.length) return;

    var cursor = 0;
    // 限制并发，避免并发过高压垮浏览器和后端。
    var workerCount = Math.max(1, Math.min(4, Number(TERRAIN_DYNAMIC_QTREE_LOAD_CONCURRENCY) || 1));
    var workers = [];
    for (var w = 0; w < workerCount; w++) {
      workers.push((async function () {
        while (true) {
          if (state.disposed || state.requestSeq !== requestSeq) return;
          if (cursor >= queue.length) return;
          var node = queue[cursor];
          cursor += 1;
          await loadTerrainQtreeNode(state, node, requestSeq);
        }
      })());
    }
    await Promise.all(workers);
  }

  function evictTerrainQtreeCache(state, requiredSet) {
    if (!state || !state.nodeMap) return;
    var loadedDetail = [];
    var keys = Object.keys(state.nodeMap);
    for (var i = 0; i < keys.length; i++) {
      var node = state.nodeMap[keys[i]];
      if (!node || node.z <= 0 || !node.loaded || node.loading) continue;
      if (requiredSet && requiredSet[node.key]) continue;
      loadedDetail.push(node);
    }

    var loadedCount = countTerrainQtreeLoadedDetailNodes(state);
    if (loadedCount <= TERRAIN_DYNAMIC_QTREE_CACHE_LIMIT) return;

    // LRU近似：按最后使用时间淘汰旧节点。
    loadedDetail.sort(function (a, b) {
      return Number(a.lastUsedAt || 0) - Number(b.lastUsedAt || 0);
    });

    for (var k = 0; k < loadedDetail.length && loadedCount > TERRAIN_DYNAMIC_QTREE_CACHE_LIMIT; k++) {
      removeTerrainQtreeNodeLayerData(state.viewer, loadedDetail[k]);
      loadedCount -= 1;
    }
  }

  function stopDynamicTerrainRequestLod(viewer) {
    var state = global._terrainBackendDynamicLodState;
    if (!state) {
      hideTerrainLodBadge();
      return;
    }
    state.disposed = true;
    state.requestSeq = (state.requestSeq || 0) + 1;

    if (state.timer) {
      clearTimeout(state.timer);
      state.timer = null;
    }
    if (state.onMoveEnd && state.viewer && state.viewer.camera && state.viewer.camera.moveEnd) {
      try {
        state.viewer.camera.moveEnd.removeEventListener(state.onMoveEnd);
      } catch (_) {
        // 忽略相机事件解绑异常。
      }
    }
    if (state.onCameraChanged && state.viewer && state.viewer.camera && state.viewer.camera.changed) {
      try {
        state.viewer.camera.changed.removeEventListener(state.onCameraChanged);
      } catch (_) {
        // 忽略相机事件解绑异常。
      }
    }
    hideTerrainLodBadge();
    global._terrainBackendDynamicLodState = null;
  }

  function scheduleDynamicTerrainRequestLod(state, immediate) {
    if (!state || state.disposed) return;
    if (state.timer) {
      clearTimeout(state.timer);
      state.timer = null;
    }
    if (immediate) {
      refreshDynamicTerrainRequestLod(state, false);
      return;
    }
    state.timer = setTimeout(function () {
      state.timer = null;
      refreshDynamicTerrainRequestLod(state, false);
    }, TERRAIN_DYNAMIC_LOD_SWITCH_DELAY_MS);
  }

  async function refreshDynamicTerrainRequestLod(state, force) {
    if (!state || state.disposed) return;
    if (state.refreshing) {
      state.pendingForce = state.pendingForce || !!force;
      return;
    }

    state.refreshing = true;
    try {
      do {
        var shouldForce = !!state.pendingForce || !!force;
        state.pendingForce = false;
        force = false;

        // Step 1: 计算目标层级 + 当前视域。
        var viewBBox = resolveDynamicViewBBox(state);
        var lod = getDynamicTerrainLodLevel(state.viewer, state.bbox, viewBBox, state);
        var requiredNodes = getTerrainQtreeNodesForView(state, lod.levelIndex, viewBBox);
        var requiredSet = {};
        for (var i = 0; i < requiredNodes.length; i++) {
          requiredSet[requiredNodes[i].key] = true;
        }
        state.requiredSet = requiredSet;

        // Step 2: 用签名判断“视域目标集合是否变化”，避免无效刷新。
        var requiredSignature = requiredNodes.map(function (n) { return n.key; }).sort().join("|");
        lod.targetTileCount = requiredNodes.length;
        lod.cachedTileCount = countTerrainQtreeLoadedDetailNodes(state);
        updateTerrainLodBadge(lod, state.baseCellSizeMeters);

        if (!shouldForce && state.currentLevel === lod.level && state.currentRequiredSignature === requiredSignature) {
          continue;
        }

        var seq = (state.requestSeq || 0) + 1;
        state.requestSeq = seq;

        setStatus(
          "四叉树动态请求中：" + lod.level +
          "，视域瓦片=" + requiredNodes.length +
          "，当前米/格=" + (state.baseCellSizeMeters * lod.scale).toFixed(1)
        );

        // Step 3: 先切换已缓存节点显隐，立即响应视图变化。
        var keys = Object.keys(state.nodeMap || {});
        for (var n = 0; n < keys.length; n++) {
          var node = state.nodeMap[keys[n]];
          if (!node || node.z <= 0 || !node.loaded) continue;
          var shouldShowNode = !!requiredSet[node.key] && getTerrainBackendSidebarLayerVisible();
          setManagedLayerStoreVisibility(node.layerEntries, shouldShowNode);
          if (shouldShowNode) {
            node.lastUsedAt = Date.now();
          }
        }

        // Step 4: 只请求缺失节点。
        var missingNodes = requiredNodes.filter(function (node2) {
          return node2 && !node2.loaded && !node2.loading;
        });
        await loadTerrainQtreeNodes(state, missingNodes, seq);

        if (state.disposed || state.requestSeq !== seq) {
          continue;
        }

        for (var j = 0; j < requiredNodes.length; j++) {
          var reqNode = requiredNodes[j];
          if (reqNode && reqNode.loaded) {
            reqNode.lastUsedAt = Date.now();
            setManagedLayerStoreVisibility(reqNode.layerEntries, getTerrainBackendSidebarLayerVisible());
          }
        }

        // Step 5: 做缓存回收，控制内存上限。
        evictTerrainQtreeCache(state, requiredSet);
        lod.cachedTileCount = countTerrainQtreeLoadedDetailNodes(state);
        updateTerrainLodBadge(lod, state.baseCellSizeMeters);

        state.currentLevel = lod.level;
        state.currentRequiredSignature = requiredSignature;
        setStatus(
          "四叉树动态LOD已更新：" + lod.level +
          "，视域瓦片=" + requiredNodes.length +
          "，缓存瓦片=" + lod.cachedTileCount +
          "，米/格=" + (state.baseCellSizeMeters * lod.scale).toFixed(1)
        );
      } while (state.pendingForce && !state.disposed);
    } catch (error) {
      if (!state.disposed) {
        console.warn("[TerrainBackend] 四叉树动态LOD刷新失败:", error);
        showToast("四叉树动态LOD刷新失败：" + (error && error.message ? error.message : "未知错误"), true);
      }
    } finally {
      state.refreshing = false;
    }
  }

  function startDynamicTerrainRequestLod(state) {
    stopDynamicTerrainRequestLod(state.viewer);

    state.disposed = false;
    state.refreshing = false;
    state.pendingForce = false;
    state.requestSeq = 0;
    state.timer = null;
    state.currentLevel = state.initialLevel || "L0";
    state.currentRequiredSignature = "";
    state.nodeMap = {};
    state.requiredSet = {};
    state.lastViewBBox = null;
    state.lastRatio = NaN;
    state.viewPaddingFactor = TERRAIN_DYNAMIC_QTREE_VIEW_PADDING_FACTOR;

    // 绑定 L0：初始全域粗层作为根节点常驻展示。
    var rootNode = ensureTerrainQtreeNode(state, 0, 0, 0);
    rootNode.loaded = true;
    rootNode.layerEntries = Array.isArray(global._terrainBackendLayers) ? global._terrainBackendLayers.slice() : [];
    rootNode.lastUsedAt = Date.now();
    setManagedLayerStoreVisibility(rootNode.layerEntries, getTerrainBackendSidebarLayerVisible());

    state.onMoveEnd = function () {
      scheduleDynamicTerrainRequestLod(state, false);
    };
    state.viewer.camera.moveEnd.addEventListener(state.onMoveEnd);

    state.onCameraChanged = function () {
      var viewBBox = resolveDynamicViewBBox(state);
      var lod = getDynamicTerrainLodLevel(state.viewer, state.bbox, viewBBox, state);
      lod.cachedTileCount = countTerrainQtreeLoadedDetailNodes(state);
      updateTerrainLodBadge(lod, state.baseCellSizeMeters);
      if (lod.level !== state.currentLevel) {
        scheduleDynamicTerrainRequestLod(state, false);
      }
    };
    state.viewer.camera.changed.addEventListener(state.onCameraChanged);

    global._terrainBackendDynamicLodState = state;
    scheduleDynamicTerrainRequestLod(state, true);
  }

  function removeOneManagedLayer(viewer, layer) {
    if (!layer) return;
    if (layer.type === "analysis" && Array.isArray(layer.items)) {
      for (var k = 0; k < layer.items.length; k++) {
        try {
          var item = layer.items[k];
          if (item && item.primitive) viewer.scene.primitives.remove(item.primitive);
        } catch (_) {
          // 忽略失效 primitive 句柄异常。
        }
      }
      return;
    }
    try {
      viewer.dataSources.remove(layer, true);
    } catch (_) {
      // 忽略失效 dataSource 句柄异常。
    }
  }

  function setOneManagedLayerVisibility(layer, visible) {
    if (!layer) return;
    if (layer.type === "analysis" && Array.isArray(layer.items)) {
      for (var k = 0; k < layer.items.length; k++) {
        try {
          var item = layer.items[k];
          if (item && item.primitive) {
            item.primitive.show = !!visible;
          }
        } catch (_) {
          // 忽略失效 primitive 句柄异常。
        }
      }
      return;
    }

    if (typeof layer.show !== "undefined") {
      layer.show = !!visible;
    }
  }

  function setManagedLayerStoreVisibility(layerStore, visible) {
    var list = Array.isArray(layerStore) ? layerStore : [];
    for (var i = 0; i < list.length; i++) {
      setOneManagedLayerVisibility(list[i], visible);
    }
  }

  function cleanupManagedLayerStore(viewer, layerStore) {
    var list = Array.isArray(layerStore) ? layerStore : [];
    for (var i = 0; i < list.length; i++) {
      removeOneManagedLayer(viewer, list[i]);
    }
  }

  function addManagedLayerEntry(entry) {
    if (!entry) return;
    if (!Array.isArray(global._terrainBackendLayers)) global._terrainBackendLayers = [];
    global._terrainBackendLayers.push(entry);
    syncTerrainBackendSidebarLayerObject();
    // 新加载的 LOD 图层继承侧边栏当前可见性与透明度状态。
    applyTerrainBackendSidebarStateToEntry(entry);
  }

  function removeManagedLayerEntry(viewer, entry) {
    if (!entry) return;
    removeOneManagedLayer(viewer, entry);
    var all = global._terrainBackendLayers || [];
    var idx = all.indexOf(entry);
    if (idx >= 0) {
      all.splice(idx, 1);
    }
    syncTerrainBackendSidebarLayerObject();
  }

  function getTerrainBackendSidebarLayer() {
    if (!window.sidebarManager || !global._terrainBackendSidebarLayerId) return null;
    if (typeof window.sidebarManager.getLayerById !== "function") return null;
    return window.sidebarManager.getLayerById(global._terrainBackendSidebarLayerId) || null;
  }

  function syncTerrainBackendSidebarLayerObject() {
    var layer = getTerrainBackendSidebarLayer();
    if (!layer) return;
    layer.cesiumObject = Array.isArray(global._terrainBackendLayers) ? global._terrainBackendLayers : [];
  }

  function getTerrainBackendSidebarLayerVisible() {
    var layer = getTerrainBackendSidebarLayer();
    if (!layer) return true;
    return layer.visible !== false;
  }

  function getTerrainBackendSidebarLayerOpacity() {
    var layer = getTerrainBackendSidebarLayer();
    if (!layer || !layer.extras) return 1.0;
    var opacity = Number(layer.extras._opacity);
    return Number.isFinite(opacity) ? Math.max(0, Math.min(1, opacity)) : 1.0;
  }

  function setPrimitiveItemOpacity(item, opacity) {
    if (!item || !item.primitive || !item.primitive.appearance) return;
    var mat = item.primitive.appearance.material;
    if (!mat || !mat.uniforms || !mat.uniforms.color) return;
    var c = item.baseColor || mat.uniforms.color;
    mat.uniforms.color = new Cesium.Color(c.red, c.green, c.blue, opacity);
  }

  function setOneManagedLayerOpacity(entry, opacity) {
    if (!entry) return;
    var alpha = Math.max(0, Math.min(1, Number(opacity)));
    if (!Number.isFinite(alpha)) alpha = 1.0;

    if (entry.type === "analysis" && Array.isArray(entry.items)) {
      for (var i = 0; i < entry.items.length; i++) {
        setPrimitiveItemOpacity(entry.items[i], alpha);
      }
      return;
    }

    if (entry && entry.primitive) {
      setPrimitiveItemOpacity(entry, alpha);
      return;
    }
  }

  function applyTerrainBackendSidebarStateToEntry(entry) {
    setOneManagedLayerVisibility(entry, getTerrainBackendSidebarLayerVisible());
    setOneManagedLayerOpacity(entry, getTerrainBackendSidebarLayerOpacity());
  }

  function registerOrUpdateTerrainBackendSidebarLayer(modeLabel) {
    if (!window.sidebarManager || typeof window.sidebarManager.addLayer !== "function") return;
    if (!Array.isArray(global._terrainBackendLayers)) global._terrainBackendLayers = [];

    var typeLabel = modeLabel === "path" ? "路径分析" : "地形分析";
    var layerName = "后端" + typeLabel + "（含动态LOD）";
    if (global._terrainBackendSidebarLayerId &&
        typeof window.sidebarManager.getLayerById === "function" &&
        window.sidebarManager.getLayerById(global._terrainBackendSidebarLayerId)) {
      var existing = window.sidebarManager.getLayerById(global._terrainBackendSidebarLayerId);
      existing.name = layerName;
      existing.type = "Analysis";
      existing.group = "analysis";
      existing.cesiumObject = global._terrainBackendLayers;
      existing.extras = Object.assign({}, existing.extras || {}, {
        _backendManaged: true,
        _backendUnifiedLayer: true,
      });
      var nameEl = document.querySelector('[data-layer-id="' + existing.id + '"] .layer-item-name');
      if (nameEl) {
        nameEl.textContent = layerName;
        nameEl.title = layerName + " (Analysis)";
      }
      return;
    }

    global._terrainBackendSidebarLayerId = window.sidebarManager.addLayer({
      name: layerName,
      type: "Analysis",
      url: "__terrain_backend_unified__",
      cesiumObject: global._terrainBackendLayers,
      extras: {
        _backendManaged: true,
        _backendUnifiedLayer: true,
      },
    });
  }

  async function loadTerrainLodDescriptor(viewer, descriptor) {
    // 旧方案遗留：按“描述符列表”做装卸载。
    // 当前主流程已迁移到“四叉树nodeMap”，该函数保留以兼容历史调用。
    if (!descriptor || descriptor.loaded || descriptor.loading) return;
    descriptor.loading = true;
    descriptor.layerEntries = [];
    try {
      await loadArtifactToCesium(
        viewer,
        descriptor.absoluteUrl,
        descriptor.format,
        descriptor.layerEntries,
        descriptor.keepVisible,
        {
          clipBbox: descriptor.clipBbox,
          registerSidebar: false,
        }
      );

      for (var i = 0; i < descriptor.layerEntries.length; i++) {
        addManagedLayerEntry(descriptor.layerEntries[i]);
      }

      descriptor.loaded = true;
      descriptor.lastUsedAt = Date.now();
    } finally {
      descriptor.loading = false;
    }
  }

  function unloadTerrainLodDescriptor(viewer, descriptor) {
    if (!descriptor || !descriptor.loaded || descriptor.loading) return;
    var entries = Array.isArray(descriptor.layerEntries) ? descriptor.layerEntries.slice() : [];
    for (var i = 0; i < entries.length; i++) {
      removeManagedLayerEntry(viewer, entries[i]);
    }
    descriptor.layerEntries = [];
    descriptor.loaded = false;
  }

  function pickTerrainLodTargets(state) {
    if (!state || !Array.isArray(state.descriptors)) return [];
    var viewer = state.viewer;
    var maxActive = getTerrainLodMaxActiveByHeight(viewer);
    if (maxActive <= 0) return [];

    var viewBBox = getViewBBox(viewer);
    var expandedView = expandBBoxByRatio(viewBBox, TERRAIN_LOD_VIEW_PADDING_FACTOR);
    var candidates = state.descriptors.filter(function (d) {
      if (!d || !d.keepVisible) return false;
      if (!expandedView) return true;
      return bboxIntersects(d.tileBBox, expandedView);
    });

    if (!candidates.length) {
      candidates = state.descriptors.filter(function (d2) {
        return d2 && d2.keepVisible;
      });
    }

    candidates.sort(function (a, b) {
      var da = approxTileDistanceScore(a.tileBBox, viewBBox);
      var db = approxTileDistanceScore(b.tileBBox, viewBBox);
      return da - db;
    });

    return candidates.slice(0, Math.max(0, maxActive));
  }

  async function refreshTerrainLodNow(state) {
    if (!state || state.disposed) return;
    if (state.refreshing) {
      state.pending = true;
      return;
    }

    state.refreshing = true;
    try {
      do {
        state.pending = false;
        var targets = pickTerrainLodTargets(state);
        var targetSet = {};
        for (var i = 0; i < targets.length; i++) {
          targetSet[targets[i].id] = true;
        }

        // 先卸载再加载，优先回收内存，避免加载近景新瓦片时内存峰值过高。
        for (var j = 0; j < state.descriptors.length; j++) {
          var d = state.descriptors[j];
          if (d.loaded && !targetSet[d.id]) {
            unloadTerrainLodDescriptor(state.viewer, d);
          }
        }

        for (var k = 0; k < targets.length; k++) {
          if (state.disposed) break;
          await loadTerrainLodDescriptor(state.viewer, targets[k]);
        }
      } while (state.pending && !state.disposed);
    } finally {
      state.refreshing = false;
    }
  }

  function scheduleTerrainLodRefresh(state, immediate) {
    if (!state || state.disposed) return;
    if (state.timer) {
      clearTimeout(state.timer);
      state.timer = null;
    }
    if (immediate) {
      refreshTerrainLodNow(state);
      return;
    }
    state.timer = setTimeout(function () {
      state.timer = null;
      refreshTerrainLodNow(state);
    }, TERRAIN_LOD_UPDATE_DELAY_MS);
  }

  function releaseTerrainLodState(viewer) {
    // 旧方案状态释放（与四叉树动态LOD状态并存时，优先确保资源可回收）。
    var state = global._terrainBackendLodState;
    if (!state) return;
    state.disposed = true;

    if (state.timer) {
      clearTimeout(state.timer);
      state.timer = null;
    }
    if (state.onMoveEnd && state.viewer && state.viewer.camera && state.viewer.camera.moveEnd) {
      try {
        state.viewer.camera.moveEnd.removeEventListener(state.onMoveEnd);
      } catch (_) {
        // 忽略相机监听解绑异常。
      }
    }

    if (Array.isArray(state.descriptors)) {
      for (var i = 0; i < state.descriptors.length; i++) {
        unloadTerrainLodDescriptor(viewer || state.viewer, state.descriptors[i]);
      }
    }

    global._terrainBackendLodState = null;
  }

  function initTerrainLodState(viewer, descriptors) {
    releaseTerrainLodState(viewer);

    var state = {
      viewer: viewer,
      descriptors: Array.isArray(descriptors) ? descriptors : [],
      timer: null,
      refreshing: false,
      pending: false,
      disposed: false,
      onMoveEnd: null,
    };

    state.onMoveEnd = function () {
      scheduleTerrainLodRefresh(state, false);
    };
    viewer.camera.moveEnd.addEventListener(state.onMoveEnd);

    global._terrainBackendLodState = state;
    scheduleTerrainLodRefresh(state, true);
  }

  function parseRgbaString(rgbaStr, fallbackAlpha) {
    var fallback = Cesium.Color.BLUE.withAlpha(fallbackAlpha || 0.65);
    if (!rgbaStr || typeof rgbaStr !== "string") return fallback;
    try {
      var c = Cesium.Color.fromCssColorString(rgbaStr);
      return c || fallback;
    } catch (_) {
      return fallback;
    }
  }

  var FRONTEND_FIXED_COLOR_KEYS = {
    "56,168,0,70": true,
    "94,189,0,70": true,
    "139,209,0,70": true,
    "193,232,0,70": true,
    "255,255,0,70": true,
    "255,191,0,70": true,
    "255,128,0,70": true,
    "255,64,0,70": true,
    "255,0,0,70": true,
    "176,176,176,70": true,
    "255,166,0,70": true,
    "0,255,0,70": true,
    "0,255,255,70": true,
    "0,166,255,70": true,
    "0,0,255,70": true,
    "255,0,255,70": true,
  };

  function quantizeColorForBatching(color) {
    var rRaw = Math.round(Math.max(0, Math.min(255, color.red * 255)));
    var gRaw = Math.round(Math.max(0, Math.min(255, color.green * 255)));
    var bRaw = Math.round(Math.max(0, Math.min(255, color.blue * 255)));
    var aRaw = Math.round(Math.max(0, Math.min(100, color.alpha * 100)));
    var rawKey = rRaw + "," + gRaw + "," + bRaw + "," + aRaw;
    if (FRONTEND_FIXED_COLOR_KEYS[rawKey]) {
      return {
        key: rawKey,
        color: Cesium.Color.fromBytes(rRaw, gRaw, bRaw, Math.round(aRaw * 2.55)),
      };
    }

    var r = Math.round(Math.max(0, Math.min(255, color.red * 255)) / 12) * 12;
    var g = Math.round(Math.max(0, Math.min(255, color.green * 255)) / 12) * 12;
    var b = Math.round(Math.max(0, Math.min(255, color.blue * 255)) / 12) * 12;
    var a = Math.round(Math.max(0, Math.min(100, color.alpha * 100)) / 5) * 5;
    var alphaByte = Math.round(a * 2.55);
    var q = Cesium.Color.fromBytes(r, g, b, alphaByte);
    return {
      key: r + "," + g + "," + b + "," + a,
      color: q,
    };
  }

  async function loadGeojsonAsAnalysisPrimitives(viewer, absoluteUrl, shouldShow, options) {
    options = options || {};
    var clipBbox = options.clipBbox || null;
    var runCtx = options.runCtx || null;
    var fc = null;
    var parseErr = null;
    var maxAttempts = 8;
    for (var attempt = 1; attempt <= maxAttempts; attempt++) {
      ensureRunNotCancelled(runCtx);
      var requestUrl = appendCacheBust(absoluteUrl, Date.now() + "_" + attempt);
      var response = await fetchJsonWithTimeout(requestUrl, {
        method: "GET",
        cache: "no-store",
        headers: { "Cache-Control": "no-cache" },
      }, 30000, runCtx);
      if (!response.ok) {
        if ((response.status === 404 || response.status === 503) && attempt < maxAttempts) {
          await sleepMs(Math.min(2500, 400 * attempt));
          continue;
        }
        throw new Error("GeoJSON 加载失败: HTTP " + response.status);
      }
      try {
        ensureRunNotCancelled(runCtx);
        fc = await parseJsonResponseSafe(response, "GeoJSON文件(" + attempt + "/" + maxAttempts + ")");
        parseErr = null;
        break;
      } catch (error) {
        parseErr = error;
        if (attempt < maxAttempts) {
          await sleepMs(Math.min(4000, 500 * attempt));
        }
      }
    }
    if (!fc) {
      throw parseErr || new Error("GeoJSON 解析失败");
    }

    var features = Array.isArray(fc && fc.features)
      ? fc.features
      : [];

    if (!features.length) {
      throw new Error("GeoJSON 中没有可渲染要素");
    }

    var colorGroups = {};
    var minLon = Infinity;
    var minLat = Infinity;
    var maxLon = -Infinity;
    var maxLat = -Infinity;

    for (var i = 0; i < features.length; i++) {
      var f = features[i] || {};
      var g = f.geometry || {};
      if (g.type !== "Polygon" || !Array.isArray(g.coordinates) || !g.coordinates.length) continue;

      var ring = g.coordinates[0];
      if (!Array.isArray(ring) || ring.length < 4) continue;

      var props = f.properties || {};
      var metricName = "value";
      ["slope_deg", "aspect_deg", "curvature", "cost"].forEach(function (k) {
        if (props[k] !== undefined) metricName = k;
      });
      var value = Number(props.value !== undefined ? props.value : props[metricName]);
      if (!Number.isFinite(value)) value = null;
      var slopeDegProp = Number(props.slope_deg);
      if (!Number.isFinite(slopeDegProp)) slopeDegProp = null;
      var minCostDirDegProp = Number(props.min_cost_dir_deg);
      if (!Number.isFinite(minCostDirDegProp)) minCostDirDegProp = null;
      var minCostDirSlopeDegProp = Number(props.min_cost_dir_slope_deg);
      if (!Number.isFinite(minCostDirSlopeDegProp)) minCostDirSlopeDegProp = null;

      var first = ring[0];
      var last = ring[ring.length - 1];
      var end = (first && last && first[0] === last[0] && first[1] === last[1]) ? ring.length - 1 : ring.length;

      var flat = [];
      for (var j = 0; j < end; j++) {
        var p = ring[j];
        if (!Array.isArray(p) || p.length < 2) continue;
        var lon = Number(p[0]);
        var lat = Number(p[1]);
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
        flat.push(lon, lat);
        minLon = Math.min(minLon, lon);
        minLat = Math.min(minLat, lat);
        maxLon = Math.max(maxLon, lon);
        maxLat = Math.max(maxLat, lat);
      }
      if (flat.length < 6) continue;

      if (clipBbox) {
        var cLon = Number(props.center_lon !== undefined ? props.center_lon : NaN);
        var cLat = Number(props.center_lat !== undefined ? props.center_lat : NaN);
        if (!Number.isFinite(cLon) || !Number.isFinite(cLat)) {
          cLon = 0;
          cLat = 0;
          var pairs = Math.floor(flat.length / 2);
          for (var ci = 0; ci < pairs; ci++) {
            cLon += flat[ci * 2];
            cLat += flat[ci * 2 + 1];
          }
          if (pairs > 0) {
            cLon /= pairs;
            cLat /= pairs;
          }
        }

        if (!(cLon >= clipBbox.west && cLon <= clipBbox.east && cLat >= clipBbox.south && cLat <= clipBbox.north)) {
          continue;
        }
      }

      var fillCss = props.fill || "rgba(100,200,255,0.65)";
      var parsedColor = parseRgbaString(fillCss, 0.65);
      var quantized = quantizeColorForBatching(parsedColor);
      if (!colorGroups[quantized.key]) {
        colorGroups[quantized.key] = {
          color: quantized.color,
          instances: [],
        };
      }

      var positions = Cesium.Cartesian3.fromDegreesArray(flat);
      colorGroups[quantized.key].instances.push(
        new Cesium.GeometryInstance({
          id: {
            type: "TerrainBackendCell",
            metric: metricName,
            value: value,
            slopeDeg: slopeDegProp,
            minCostDirDeg: minCostDirDegProp,
            minCostDirSlopeDeg: minCostDirSlopeDegProp,
          },
          geometry: new Cesium.PolygonGeometry({
            polygonHierarchy: new Cesium.PolygonHierarchy(positions),
            height: 0,
            vertexFormat: Cesium.MaterialAppearance.VERTEX_FORMAT,
          }),
        })
      );
    }

    var primitiveItems = [];
    var totalInstances = 0;
    Object.keys(colorGroups).forEach(function (key) {
      var group = colorGroups[key];
      if (!group.instances.length) return;

      var material = new Cesium.Material({
        fabric: {
          type: "Color",
          uniforms: { color: group.color },
        },
      });
      var appearance = new Cesium.MaterialAppearance({
        material: material,
        translucent: group.color.alpha < 1.0,
        flat: true,
      });
      for (var idx = 0; idx < group.instances.length; idx += FRONTEND_MAX_INSTANCES_PER_PRIMITIVE) {
        var chunk = group.instances.slice(idx, idx + FRONTEND_MAX_INSTANCES_PER_PRIMITIVE);
        totalInstances += chunk.length;

        var primitive = new Cesium.GroundPrimitive({
          geometryInstances: chunk,
          appearance: appearance,
        });
        primitive.show = shouldShow;
        viewer.scene.primitives.add(primitive);

        primitiveItems.push({
          primitive: primitive,
          baseColor: group.color,
          alpha: group.color.alpha,
        });
      }
    });

    if (!primitiveItems.length) {
      throw new Error("GeoJSON 可用要素为空，无法创建分析图层");
    }

    return {
      primitiveItems: primitiveItems,
      renderedCount: totalInstances,
      bounds: Number.isFinite(minLon)
        ? { west: minLon, south: minLat, east: maxLon, north: maxLat }
        : null,
    };
  }

  async function loadArtifactToCesium(viewer, absoluteUrl, format, layerStore, visible) {
    var options = arguments.length > 5 ? arguments[5] : null;
    var shouldShow = visible !== false;
    var registerSidebar = !(options && options.registerSidebar === false);
    var runCtx = options && options.runCtx ? options.runCtx : null;
    ensureRunNotCancelled(runCtx);
    if (format === "geojson") {
      var loaded = await loadGeojsonAsAnalysisPrimitives(viewer, absoluteUrl, shouldShow, options || {});
      ensureRunNotCancelled(runCtx);
      layerStore.push({ type: "analysis", items: loaded.primitiveItems });

      if (registerSidebar && window.sidebarManager) {
        var layerName = absoluteUrl.split('/').pop().replace(/\.[^/.]+$/, '');
        var layerId = window.sidebarManager.addLayer({
          name: layerName,
          type: 'Analysis',
          url: absoluteUrl,
          cesiumObject: loaded.primitiveItems,
          extras: { _backendManaged: true, bounds: loaded.bounds }
        });
        if (!shouldShow) {
          window.sidebarManager.setLayerVisibility(layerId, false);
        }
      }
      if (global._terrainBackendNumericTipEnabled &&
          !(global.SlopeAnalysis && typeof global.SlopeAnalysis.openTip === "function")) {
        enableTerrainBackendNumericTip(viewer);
      }
      return;
    }
    if (format === "czml") {
      ensureRunNotCancelled(runCtx);
      const ds = await withTimeout(Cesium.CzmlDataSource.load(absoluteUrl), 20000, "CZML 图层加载超时");
      ensureRunNotCancelled(runCtx);
      viewer.dataSources.add(ds);
      ds.show = shouldShow;
      layerStore.push(ds);
      // 注册到侧边栏图层管理（可见性开关、后续统一清理）。
      if (registerSidebar && window.sidebarManager) {
        var layerName = absoluteUrl.split('/').pop().replace(/\.[^/.]+$/, '');
        window.sidebarManager.addLayer({
          name: layerName,
          type: 'CZML',
          url: absoluteUrl,
          cesiumObject: ds,
          extras: { _backendManaged: true }
        });
      }
      return;
    }
    if (format === "kml") {
      ensureRunNotCancelled(runCtx);
      const ds = await withTimeout(Cesium.KmlDataSource.load(absoluteUrl, {
        camera: viewer.scene.camera,
        canvas: viewer.scene.canvas,
        clampToGround: true,
      }), 20000, "KML 图层加载超时");
      ensureRunNotCancelled(runCtx);
      viewer.dataSources.add(ds);
      ds.show = shouldShow;
      layerStore.push(ds);
      // 注册到侧边栏图层管理（可见性开关、后续统一清理）。
      if (registerSidebar && window.sidebarManager) {
        var layerName = absoluteUrl.split('/').pop().replace(/\.[^/.]+$/, '');
        window.sidebarManager.addLayer({
          name: layerName,
          type: 'KML',
          url: absoluteUrl,
          cesiumObject: ds,
          extras: { _backendManaged: true }
        });
      }
      return;
    }
    console.warn("[TerrainBackend] 未支持的格式:", format);
  }

  function createRunner(viewer, slopeAnalysis) {
    // 页面“执行后端分析”按钮的主流程入口。
    return async function runBackendAnalysis() {
      // 运行态关键变量：
      // runBtn：执行按钮句柄（用于防重复点击与结束后恢复）
      // baseUrl：后端接口根地址（FastAPI 服务入口）
      // demPath：用户选择的 DEM 文件路径（为空时走测试地形）
      // mode：分析模式（terrain/path）
      // formats：结果输出格式列表（geojson/czml/kml）
      // requestTimeoutMs：当前流程估算出的请求超时时间
      const runBtn = document.getElementById("runBackendAnalysis");
      const baseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
      const demPath = document.getElementById("backend-dem-path")?.value?.trim() || "";
      const mode = document.getElementById("backend-analysis-mode")?.value || "terrain";
      const analysisTypeForEntry = document.getElementById("backend-terrain-type")?.value || "comprehensive";
      const formats = getSelectedFormats();
      var requestTimeoutMs = REQUEST_TIMEOUT_MS;
      var runCtx = null;

      if (!formats.length) {
        alert("请至少选择一种输出格式");
        return;
      }

      if (runBtn) runBtn.disabled = true;
      setStatus("正在检查后端状态...");

      try {
        const ready = await checkBackendReady(baseUrl);
        if (!ready) {
          openBackendGuide();
          throw new Error("后端未就绪。请先点“启动后端服务”或在 backend 目录运行 run_backend.ps1");
        }

        // 通行代价专项入口：先两点选区，再自动填充 BBox 后继续后端分析。
        if (mode === "terrain" &&
            analysisTypeForEntry === "cost" &&
            !global._terrainBackendCostPickBypass) {
          if (!demPath) {
            throw new Error("代价分析需基于 DEM 边界约束，请先填写 DEM 路径");
          }
          setStatus("正在读取 DEM 范围并等待两点选区...");
          var demMetaForPick = await getDemMetadata(baseUrl, demPath);
          if (!demMetaForPick || !demMetaForPick.bounds_wgs84) {
            throw new Error("DEM 缺少可用坐标范围，无法进行两点选区");
          }
          showToast("请在地图中依次点击两个对角点，右键可取消");
          var inputCell = Number(document.getElementById("backend-cell-size-m")?.value || 50);
          var selectedPick = await pickCostAnalysisDiagonalBBox(viewer, demMetaForPick.bounds_wgs84, Math.max(1, inputCell) * 2.0);
          if (!selectedPick || !selectedPick.bbox) {
            setStatus("已取消两点选区");
            return;
          }
          fillBBoxInputs(selectedPick.bbox);
          var startLonEl = document.getElementById("backend-start-lon");
          var startLatEl = document.getElementById("backend-start-lat");
          var endLonEl = document.getElementById("backend-end-lon");
          var endLatEl = document.getElementById("backend-end-lat");
          if (startLonEl && startLatEl && endLonEl && endLatEl &&
              Array.isArray(selectedPick.startPoint) && Array.isArray(selectedPick.endPoint)) {
            startLonEl.value = Number(selectedPick.startPoint[0]).toFixed(6);
            startLatEl.value = Number(selectedPick.startPoint[1]).toFixed(6);
            endLonEl.value = Number(selectedPick.endPoint[0]).toFixed(6);
            endLatEl.value = Number(selectedPick.endPoint[1]).toFixed(6);
          }
          global._terrainBackendCostPickBypass = true;
          try {
            return await runBackendAnalysis();
          } finally {
            global._terrainBackendCostPickBypass = false;
          }
        }

        runCtx = createAnalysisRunContext();
        global._terrainBackendActiveRun = runCtx;

        const bbox = getBBoxFromInputs();
        validateBBox(bbox);
        var maxResolution = getMaxResolutionForMode(mode);
        var cellSizeMeters = Number(document.getElementById("backend-cell-size-m")?.value || 50);
        var resolutionInfo = estimateResolutionFromCellSize(bbox, cellSizeMeters, maxResolution);
        var resolution = Number(resolutionInfo.resolution);
        if (!Number.isFinite(resolution) || resolution < 16) {
          throw new Error("栅格分辨率换算失败，请检查 BBox 和分辨率参数");
        }

        requestTimeoutMs = estimateAnalysisTimeoutMs(mode, resolution, formats.length, !!demPath);

        if (resolutionInfo.clippedByLimit &&
            (resolutionInfo.actualCellX > resolutionInfo.requestedCell || resolutionInfo.actualCellY > resolutionInfo.requestedCell)) {
          showToast(
            "当前范围较大，受后端网格上限(" + resolutionInfo.maxResolution + ")限制，实际米/格会大于设定值。",
            true
          );
        }

        setStatus(
          "分辨率换算: " +
          resolutionInfo.actualCellX.toFixed(1) + "m x " +
          resolutionInfo.actualCellY.toFixed(1) + "m / 格"
        );

        if (demPath) {
          setStatus("正在校验 DEM 坐标范围...");
          var demMeta = await getDemMetadata(baseUrl, demPath);
          if (!demMeta || !demMeta.bounds_wgs84) {
            throw new Error("DEM 缺少可用坐标系，无法匹配当前经纬度 BBox。请为 tif 写入 CRS 或提供同名 .prj 文件。");
          }
          if (!bboxIntersects(bbox, demMeta.bounds_wgs84)) {
            throw new Error(
              "当前 BBox 与 DEM 覆盖范围无交集。" +
              "\n当前 BBox=" + bboxText(bbox) +
              "\nDEM 范围=" + bboxText(demMeta.bounds_wgs84)
            );
          }

          if (demMeta.analysis_ready === false) {
            setDecodePanelVisible(true, demMeta.analysis_error, demMeta.decode_suggestions);
            applySuggestedDecodeMode(demMeta.decode_suggestions);
            updateDecodeModeUi();
            var selectedDecodeMode = document.getElementById("backend-dem-decode-mode")?.value || "none";
            if (selectedDecodeMode === "none") {
              throw new Error(
                "当前 DEM 默认不可直接分析，请先选择解码模式后再点击执行。" +
                (demMeta.analysis_error ? (" 原因: " + demMeta.analysis_error) : "")
              );
            }
          } else {
            setDecodePanelVisible(false);
          }
        } else {
          setDecodePanelVisible(false);
        }

        var decodePayload = {
          dem_decode_mode: "none",
          dem_decode_band: 1,
          dem_decode_scale: 1,
          dem_decode_offset: 0,
          dem_decode_nodata: null,
        };
        if (demPath) {
          decodePayload = getDecodePayloadFromUi();
        }

        var analysisType = document.getElementById("backend-terrain-type")?.value || "comprehensive";
        var terrainStartPoint = [
          Number(document.getElementById("backend-start-lon")?.value),
          Number(document.getElementById("backend-start-lat")?.value),
        ];
        var terrainEndPoint = [
          Number(document.getElementById("backend-end-lon")?.value),
          Number(document.getElementById("backend-end-lat")?.value),
        ];
        var hasTerrainCostDirection =
          Number.isFinite(terrainStartPoint[0]) && Number.isFinite(terrainStartPoint[1]) &&
          Number.isFinite(terrainEndPoint[0]) && Number.isFinite(terrainEndPoint[1]);
        var tileSetId = null;
        if (mode === "terrain") {
          tileSetId = buildTerrainTileSetId({
            bbox: bbox,
            cellSizeMeters: cellSizeMeters,
            maxResolution: maxResolution,
            demPath: demPath,
            decodePayload: decodePayload,
            startPoint: (analysisType === "cost" && hasTerrainCostDirection) ? terrainStartPoint : null,
            endPoint: (analysisType === "cost" && hasTerrainCostDirection) ? terrainEndPoint : null,
          });
        }
        var enableDynamicLodForRun = TERRAIN_DYNAMIC_LOD_ENABLE && analysisType !== "cost";
        var runResult;
        var artifacts = [];
        var requestIds = [];
        var demSource = null;

        // 分支A：路径分析（多阶段分辨率回退策略）。
        if (mode === "path") {
          var startPoint = [
            Number(document.getElementById("backend-start-lon")?.value),
            Number(document.getElementById("backend-start-lat")?.value),
          ];
          var endPoint = [
            Number(document.getElementById("backend-end-lon")?.value),
            Number(document.getElementById("backend-end-lat")?.value),
          ];
          if (!Number.isFinite(startPoint[0]) || !Number.isFinite(startPoint[1]) ||
              !Number.isFinite(endPoint[0]) || !Number.isFinite(endPoint[1])) {
            throw new Error("路径起终点参数无效，请填写经纬度");
          }

          runResult = await runPathAnalysisByStages({
            baseUrl: baseUrl,
            bbox: bbox,
            targetResolution: resolution,
            formats: formats,
            demPath: demPath,
            decodePayload: decodePayload,
            startPoint: startPoint,
            endPoint: endPoint,
            runCtx: runCtx,
          });

          requestTimeoutMs = runResult.lastTimeoutMs || requestTimeoutMs;
          artifacts = runResult.artifacts;
          requestIds = runResult.requestIds || [];
          demSource = runResult.demSource;

          if (Array.isArray(runResult.stagesSucceeded) && runResult.stagesSucceeded.length > 1) {
            showToast(
              "路径分级已完成，最终使用分辨率 N=" + runResult.bestResolution,
              false
            );
          }
        } else {
          // 分支B：地形分析（先L0粗层，再动态LOD细化）。
          var initialDynamicLod = enableDynamicLodForRun
            ? {
                level: "L0",
                levelIndex: 0,
                scale: getTerrainQtreeCellScale(0),
                ratio: 1,
                height: Number(viewer && viewer.camera && viewer.camera.positionCartographic && viewer.camera.positionCartographic.height) || 0,
              }
            : { level: "L0", scale: 1.0, ratio: 1, height: 0 };
          var initialTerrainCellSize = Number(cellSizeMeters) * Number(initialDynamicLod.scale || 1.0);
          if (enableDynamicLodForRun) {
            updateTerrainLodBadge(initialDynamicLod, Number(cellSizeMeters));
          }

          runResult = await runTerrainAnalysisWithAutoTiling({
            baseUrl: baseUrl,
            viewer: viewer,
            bbox: bbox,
            cellSizeMeters: initialTerrainCellSize,
            maxResolution: maxResolution,
            formats: formats,
            demPath: demPath,
            decodePayload: decodePayload,
            analysisType: analysisType,
            startPoint: (analysisType === "cost" && hasTerrainCostDirection) ? terrainStartPoint : null,
            endPoint: (analysisType === "cost" && hasTerrainCostDirection) ? terrainEndPoint : null,
            tileOverlapCells: TERRAIN_TILE_OVERLAP_CELLS,
            tileSetId: tileSetId,
            tileKey: enableDynamicLodForRun ? "0/0/0" : null,
            runCtx: runCtx,
          });

          requestTimeoutMs = runResult.lastTimeoutMs || requestTimeoutMs;
          artifacts = runResult.artifacts;
          requestIds = runResult.requestIds || [];
          demSource = runResult.demSource;

          if (runResult.tileCount > 1) {
            showToast("分块分析完成，已拼接加载 " + runResult.tileCount + " 个分块结果", false);
          }
          if (enableDynamicLodForRun) {
            showToast(
              "已渲染四叉树 L0 粗层，当前米/格=" + Number(initialTerrainCellSize).toFixed(1) + "m",
              false
            );
          }
        }

        if (!Array.isArray(artifacts) || !artifacts.length) {
          throw new Error("后端未返回可展示文件");
        }

        // 渲染前先清理旧图层，避免结果叠加混杂。
        clearManagedBackendLayers(viewer);
        global._terrainBackendLayers = [];
        global._terrainBackendSidebarLayerId = null;

        releaseTerrainLodState(viewer);
        await renderTerrainArtifacts(viewer, artifacts, baseUrl, bbox, analysisType, { registerSidebar: false, runCtx: runCtx });
        registerOrUpdateTerrainBackendSidebarLayer(mode);

        // 地形模式下启动动态四叉树请求调度。
        if (mode === "terrain" && enableDynamicLodForRun) {
          var dynamicState = {
            viewer: viewer,
            baseUrl: baseUrl,
            bbox: bbox,
            baseCellSizeMeters: Number(cellSizeMeters),
            maxResolution: maxResolution,
            formats: formats.slice(),
            demPath: demPath,
            decodePayload: Object.assign({}, decodePayload),
            analysisType: analysisType,
            startPoint: (analysisType === "cost" && hasTerrainCostDirection) ? terrainStartPoint.slice() : null,
            endPoint: (analysisType === "cost" && hasTerrainCostDirection) ? terrainEndPoint.slice() : null,
            initialLevel: (typeof initialDynamicLod !== "undefined" && initialDynamicLod && initialDynamicLod.level) ? initialDynamicLod.level : "L0",
            tileSetId: tileSetId,
            tileEdgeTarget: TERRAIN_DYNAMIC_TILE_EDGE_TARGET,
          };
          startDynamicTerrainRequestLod(dynamicState);
          showToast("四叉树动态LOD已开启：将按当前视域动态请求更细层级瓦片", false);
        } else {
          stopDynamicTerrainRequestLod(viewer);
        }

        var modeExtra = "";
        if (mode === "path" && runResult && Number.isFinite(Number(runResult.bestResolution))) {
          modeExtra = "，路径分级N=" + runResult.bestResolution;
        }
        if (mode === "terrain" && runResult && Number(runResult.tileCount) > 1) {
          modeExtra = "，分块数=" + runResult.tileCount;
        }

        var cacheExtra = "";
        if (mode === "terrain" && runResult && Number.isFinite(Number(runResult.cacheHits))) {
          cacheExtra = "，缓存命中 " + runResult.cacheHits + "/" + runResult.tileCount;
        }

        setStatus(`分析完成：request_id=${formatRequestIds(requestIds)}，加载 ${artifacts.length} 个图层${modeExtra}${cacheExtra}`);
        if (demSource === "synthetic") {
          showToast("当前结果使用测试地形；要用真实 DEM，请在 DEM路径 填入 .tif 路径", false);
        }
        if (demSource === "real_dem") {
          showToast("已使用真实 DEM 完成分析", false);
        }

        console.log("[TerrainBackend] 分析完成", {
          mode: mode,
          requestIds: requestIds,
          artifactCount: artifacts.length,
          runResult: runResult,
        });
      } catch (error) {
        var message = error && error.message ? error.message : String(error || "未知错误");
        if (runCtx && runCtx.cancelled) {
          message = runCtx.reason || "分析已终止";
        }
        if (error && error.name === "AbortError") {
          message = "请求超时并已中止（" + Math.round(requestTimeoutMs / 1000) + "s）。可减小图幅、增大米/格或减少输出格式后重试。";
        }
        setStatus(`分析失败：${message}`, true);
        showToast(`分析失败：${message}`, true);
        console.error("[TerrainBackend] 分析失败", error);
      } finally {
        if (global._terrainBackendActiveRun === runCtx) {
          global._terrainBackendActiveRun = null;
        }
        if (runBtn) runBtn.disabled = false;
      }
    };
  }

  function initTerrainBackendTools(viewer, slopeAnalysis) {
    // 面板初始化：负责按钮绑定、弹窗行为、默认参数与状态提示。
    if (!viewer) return;
    global._terrainBackendViewer = viewer;

    // 面板级 DOM 句柄（统一在初始化时取一次，避免后续重复查询）：
    // panel/openBtn/closeBtn：主面板开关
    // runBtn/clearBtn：执行分析与清理图层
    // useViewBtn/useDemBtn：一键填充 BBox（当前视域 / DEM 覆盖范围）
    // modeSelect/startBtn：分析模式切换与后端启动按钮
    // decodeModeSelect/demPathInput：DEM 解码相关控件
    const panel = document.getElementById("backend-format-modal");
    const openBtn = document.getElementById("openBackendFormatModal");
    const closeBtn = document.getElementById("closeBackendFormatModal");
    const runBtn = document.getElementById("runBackendAnalysis");
    const stopBtn = document.getElementById("stopBackendAnalysis");
    const clearBtn = document.getElementById("clearBackendLayers");
    const useViewBtn = document.getElementById("backend-use-view-bbox");
    const useDemBtn = document.getElementById("backend-use-dem-bbox");
    const modeSelect = document.getElementById("backend-analysis-mode");
    const startBtn = document.getElementById("sidebarStartBackendBtn");
    const decodeModeSelect = document.getElementById("backend-dem-decode-mode");
    const demPathInput = document.getElementById("backend-dem-path");

    if (!panel || !openBtn || !closeBtn || !runBtn || !clearBtn || !useViewBtn || !modeSelect || !startBtn || !useDemBtn) {
      return;
    }

    beautifyBackendPanel(panel);

    if (!panel.dataset.inited) {
      if (!global.__backendOutputCacheBootCleared) {
        var bootBaseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
        clearBackendOutputCache(bootBaseUrl, { silent: true });
        global.__backendOutputCacheBootCleared = true;
      }

      if (!global.__backendOutputCacheUnloadBound) {
        global.addEventListener("pagehide", function () {
          var unloadBaseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
          clearBackendOutputCache(unloadBaseUrl, { silent: true, useBeacon: true });
        });
        global.__backendOutputCacheUnloadBound = true;
      }

      if (!global.__analysisLeavePromptBound) {
        global.addEventListener("beforeunload", function (event) {
          var msg = "刷新或退出网页会丢失当前分析结果，请确认是否继续。";
          event.preventDefault();
          event.returnValue = msg;
          return msg;
        });
        global.__analysisLeavePromptBound = true;
      }

      openBtn.addEventListener("click", function (event) {
        if (event) {
          event.preventDefault();
          event.stopPropagation();
        }
        panel.style.display = "block";
        const bbox = (slopeAnalysis && typeof slopeAnalysis._getAnalysisBounds === "function" && slopeAnalysis._getAnalysisBounds()) || getViewBBox(viewer);
        fillBBoxInputs(bbox);
        var demPathCurrent = document.getElementById("backend-dem-path")?.value?.trim() || "";
        if (!demPathCurrent) {
          resetDecodeUi();
        }
      });

      closeBtn.addEventListener("click", function (event) {
        if (event) {
          event.preventDefault();
          event.stopPropagation();
        }
        panel.style.display = "none";
      });

      useViewBtn.addEventListener("click", function (event) {
        if (event) {
          event.preventDefault();
          event.stopPropagation();
        }
        fillBBoxInputs(getViewBBox(viewer));
      });

      useDemBtn.addEventListener("click", async function (event) {
        if (event) {
          event.preventDefault();
          event.stopPropagation();
        }
        var baseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
        var demPath = document.getElementById("backend-dem-path")?.value?.trim() || "";
        if (!demPath) {
          showToast("请先填写 DEM 路径", true);
          setStatus("请先填写 DEM 路径", true);
          return;
        }
        try {
          setStatus("正在读取 DEM 范围...");
          var meta = await getDemMetadata(baseUrl, demPath);
          if (!meta || !meta.bounds_wgs84) {
            throw new Error("DEM 缺少可用坐标系，无法自动转换到经纬度范围");
          }
          fillBBoxInputs(meta.bounds_wgs84);
          if (meta.analysis_ready === false) {
            setDecodePanelVisible(true, meta.analysis_error, meta.decode_suggestions);
            applySuggestedDecodeMode(meta.decode_suggestions);
            updateDecodeModeUi();
            setStatus("DEM 范围已填入；该 DEM 默认不可直接分析，请选择解码模式", true);
            showToast("该 DEM 默认不可直接分析，请先选择解码模式", true);
          } else {
            setDecodePanelVisible(false);
            setStatus("已读取 DEM 范围并填入 BBox");
            showToast("DEM 范围已填入，可直接执行分析");
          }
        } catch (error) {
          setStatus("读取 DEM 范围失败：" + error.message, true);
          showToast("读取 DEM 范围失败：" + error.message, true);
        }
      });

      modeSelect.addEventListener("change", function () {
        const pathBox = document.getElementById("backend-path-params");
        if (pathBox) pathBox.style.display = modeSelect.value === "path" ? "block" : "none";
        updateGridSchemeUi(modeSelect.value);
      });

      if (decodeModeSelect) {
        decodeModeSelect.addEventListener("change", function () {
          updateDecodeModeUi();
        });
      }

      if (demPathInput) {
        demPathInput.addEventListener("change", function () {
          resetDecodeUi();
        });
      }

      updateGridSchemeUi(modeSelect.value);
      resetDecodeUi();

      panel.dataset.inited = "1";
    }

    runBtn.onclick = function (event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      return createRunner(viewer, slopeAnalysis)();
    };

    if (stopBtn) {
      stopBtn.onclick = function (event) {
        if (event) {
          event.preventDefault();
          event.stopPropagation();
        }
        if (typeof global.cancelTerrainBackendAnalysis === "function") {
          global.cancelTerrainBackendAnalysis();
        }
      };
    }

    startBtn.onclick = function (event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      launchBackendService();
    };

    clearBtn.onclick = function () {
      clearManagedBackendLayers(viewer);
      var baseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
      clearBackendOutputCache(baseUrl, { silent: false });
      clearBackendTileCache(baseUrl, { silent: true });
      setStatus("后端图层已清空");
      showToast("后端图层已清空");
    };

    if (global.__analysisNumericTipEnabled &&
        !(global.SlopeAnalysis && typeof global.SlopeAnalysis.openTip === "function")) {
      setTerrainBackendNumericTipEnabled(true, viewer);
    }
  }

  // 拆分模块需要调用的函数（渲染/UI工具）。
  global.showToast = showToast;
  global.setStatus = setStatus;
  global.getViewBBox = getViewBBox;
  global.bboxIntersects = bboxIntersects;
  global.expandBBoxByRatio = expandBBoxByRatio;
  global.renderTerrainArtifacts = renderTerrainArtifacts;
  global.cleanupManagedLayerStore = cleanupManagedLayerStore;
  global.setManagedLayerStoreVisibility = setManagedLayerStoreVisibility;
  global.addManagedLayerEntry = addManagedLayerEntry;
  global.removeManagedLayerEntry = removeManagedLayerEntry;

  global.initTerrainBackendTools = initTerrainBackendTools;
  global.setTerrainBackendNumericTipEnabled = function (enabled) {
    setTerrainBackendNumericTipEnabled(!!enabled, global._terrainBackendViewer || global.viewer);
  };
  global.enableTerrainBackendNumericTip = function () {
    setTerrainBackendNumericTipEnabled(true, global._terrainBackendViewer || global.viewer);
  };
  global.disableTerrainBackendNumericTip = function () {
    setTerrainBackendNumericTipEnabled(false, global._terrainBackendViewer || global.viewer);
  };
  global.clearTerrainBackendLayers = function () {
    var viewer = global._terrainBackendViewer || global.viewer;
    if (!viewer) return;
    var baseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
    clearManagedBackendLayers(viewer);
    clearBackendOutputCache(baseUrl, { silent: true });
    clearBackendTileCache(baseUrl, { silent: true });
    setStatus("后端图层已清空");
    showToast("后端图层已清空");
  };
  global.cancelTerrainBackendAnalysis = function () {
    var viewer = global._terrainBackendViewer || global.viewer;
    var baseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
    var activeRun = global._terrainBackendActiveRun || null;
    if (activeRun) {
      cancelAnalysisRun(activeRun, "用户终止了当前分析");
    }
    cancelCostTwoPointPick(viewer);
    if (viewer) {
      clearManagedBackendLayers(viewer);
    }
    clearBackendOutputCache(baseUrl, { silent: true });
    clearBackendTileCache(baseUrl, { silent: true });
    var runBtn = document.getElementById("runBackendAnalysis");
    if (runBtn) runBtn.disabled = false;
    setStatus("已终止分析并清理本次结果缓存");
    showToast("已终止分析并清理本次结果缓存");
  };

  function bindStartButtonOnly() {
    var btn = document.getElementById("sidebarStartBackendBtn");
    if (!btn || btn.dataset.backendBound === "1") return;
    btn.addEventListener("click", function (event) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      launchBackendService();
    });
    btn.dataset.backendBound = "1";
  }

  function autoInitFromGlobals() {
    if (global.__terrainBackendAutoInitDone) return;
    if (!global.viewer || !global.SlopeAnalysis) return;
    initTerrainBackendTools(global.viewer, global.SlopeAnalysis);
    global.__terrainBackendAutoInitDone = true;
  }

  // 兜底：避免 eventBindInit 调用时机早于本文件加载，导致按钮事件未绑定。
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      bindStartButtonOnly();
      autoInitFromGlobals();
    });
  } else {
    bindStartButtonOnly();
    autoInitFromGlobals();
  }

  // 再兜底一次，适配部分脚本异步加载顺序。
  setTimeout(function () {
    bindStartButtonOnly();
    autoInitFromGlobals();
  }, 300);
})(window);
