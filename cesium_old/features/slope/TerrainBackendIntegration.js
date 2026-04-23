(function (global) {
  "use strict";

  var REQUEST_TIMEOUT_MS = 25000;
  var TERRAIN_MAX_RESOLUTION = 1024;
  var PATH_MAX_RESOLUTION = 512;
  var TERRAIN_TILE_EDGE_TARGET = 420;
  var TERRAIN_TILE_OVERLAP_CELLS = 1;
  var FRONTEND_MAX_INSTANCES_PER_PRIMITIVE = 6000;

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

    // Use ceil instead of round so effective cell size will not exceed target cell size.
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

  function estimateTerrainTileLayout(bbox, cellSizeMeters, maxResolution) {
    var cell = Math.max(1.0, Number(cellSizeMeters) || 50.0);
    var hardCapCellsPerEdge = Math.max(1, (Math.max(16, Number(maxResolution) || TERRAIN_MAX_RESOLUTION) - 1));
    // Do not let a single tile become too large for browser JSON parsing/rendering.
    var capCellsPerEdge = Math.max(1, Math.min(hardCapCellsPerEdge, TERRAIN_TILE_EDGE_TARGET));

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

  async function requestAnalysisJson(baseUrl, endpoint, payload, timeoutMs, stageLabel) {
    var label = String(stageLabel || "分析请求");
    var maxAttempts = 3;
    var lastError = null;

    for (var attempt = 1; attempt <= maxAttempts; attempt++) {
      var response;
      try {
        response = await fetchJsonWithTimeout(`${baseUrl}${endpoint}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        }, timeoutMs);
      } catch (error) {
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

  async function runTerrainAnalysisWithAutoTiling(options) {
    var baseUrl = options.baseUrl;
    var bbox = options.bbox;
    var cellSizeMeters = options.cellSizeMeters;
    var maxResolution = options.maxResolution;
    var formats = options.formats;
    var demPath = options.demPath;
    var decodePayload = options.decodePayload;
    var analysisType = options.analysisType;
    var overlapCells = Math.max(0, Number(options.tileOverlapCells) || 0);

    var layout = estimateTerrainTileLayout(bbox, cellSizeMeters, maxResolution);
    if (layout.total > 64) {
      throw new Error("当前图幅过大，自动分块后达到 " + layout.total + " 块（上限64）。请增大米/格或缩小范围。");
    }

    if (layout.total > 1) {
      showToast("检测到超大图幅，已启用自动分块分析（" + layout.cols + "x" + layout.rows + "）", false);
    }

    var tiles = splitBBoxIntoTiles(bbox, layout.cols, layout.rows);
    var allArtifacts = [];
    var requestIds = [];
    var demSource = null;
    var lastTimeoutMs = REQUEST_TIMEOUT_MS;

    for (var i = 0; i < tiles.length; i++) {
      var tile = tiles[i];
      var expandedBbox = expandTileBBoxWithOverlap(tile.bbox, bbox, layout.cols, layout.rows, overlapCells);
      var tileResInfo = estimateResolutionFromCellSize(expandedBbox, cellSizeMeters, maxResolution);
      var tileResolution = Number(tileResInfo.resolution);
      var timeoutMs = estimateAnalysisTimeoutMs("terrain", tileResolution, formats.length, !!demPath);
      lastTimeoutMs = timeoutMs;

      var tileLabel = "分块分析 " + (i + 1) + "/" + tiles.length + " (N=" + tileResolution + ")";
      setStatus(tileLabel + "...");

      var tilePayload = Object.assign({
        bbox: expandedBbox,
        resolution: tileResolution,
        analysis_type: analysisType,
        output_formats: formats,
        dem_path: demPath || null,
      }, decodePayload);

      var tileData = await requestAnalysisJson(baseUrl, "/api/v1/analyze/terrain", tilePayload, timeoutMs, tileLabel);
      var tileArtifacts = Array.isArray(tileData.artifacts) ? tileData.artifacts : [];
      tileArtifacts = tileArtifacts.map(function (artifact) {
        if (!artifact || typeof artifact !== "object") return artifact;
        var extended = Object.assign({}, artifact);
        // Keep tile core bbox for frontend clipping so overlap ring participates in
        // calculation but is not rendered twice across adjacent tiles.
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
      lastTimeoutMs: lastTimeoutMs,
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

    var stages = buildPathResolutionStages(targetResolution);
    var tried = [];
    var succeeded = [];
    var bestData = null;
    var bestResolution = null;
    var lastTimeoutMs = REQUEST_TIMEOUT_MS;

    for (var i = 0; i < stages.length; i++) {
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
        var data = await requestAnalysisJson(baseUrl, "/api/v1/analyze/path", payload, timeoutMs, label);
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

  function bboxText(b) {
    if (!b) return "-";
    return "[" +
      Number(b.west).toFixed(6) + ", " +
      Number(b.south).toFixed(6) + ", " +
      Number(b.east).toFixed(6) + ", " +
      Number(b.north).toFixed(6) + "]";
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

  async function fetchJsonWithTimeout(url, options, timeoutMs) {
    var controller = new AbortController();
    var timer = setTimeout(function () {
      controller.abort();
    }, timeoutMs || REQUEST_TIMEOUT_MS);
    try {
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
          // ignore clipboard failures
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
        // ignore clipboard failures
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
      return metricLabel(pickedId.metric) + ": " + Number(pickedId.value).toFixed(4);
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

  function clearManagedBackendLayers(viewer) {
    if (window.sidebarManager && Array.isArray(window.sidebarManager.layers)) {
      var managed = window.sidebarManager.layers.filter(function (layer) {
        return layer && layer.extras && layer.extras._backendManaged === true;
      });
      managed.forEach(function (layer) {
        try {
          window.sidebarManager.removeLayer(layer.id);
        } catch (_) {
          // ignore single-layer cleanup errors
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
            // ignore stale primitive handles
          }
        }
        continue;
      }
      try {
        viewer.dataSources.remove(layer, true);
      } catch (_) {
        // ignore stale datasource handles
      }
    }
    global._terrainBackendLayers = [];
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
    var fc = null;
    var parseErr = null;
    var maxAttempts = 8;
    for (var attempt = 1; attempt <= maxAttempts; attempt++) {
      var requestUrl = appendCacheBust(absoluteUrl, Date.now() + "_" + attempt);
      var response = await withTimeout(fetch(requestUrl, {
        method: "GET",
        cache: "no-store",
        headers: { "Cache-Control": "no-cache" },
      }), 30000, "GeoJSON 文件请求超时");
      if (!response.ok) {
        if ((response.status === 404 || response.status === 503) && attempt < maxAttempts) {
          await sleepMs(Math.min(2500, 400 * attempt));
          continue;
        }
        throw new Error("GeoJSON 加载失败: HTTP " + response.status);
      }
      try {
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
    if (format === "geojson") {
      var loaded = await loadGeojsonAsAnalysisPrimitives(viewer, absoluteUrl, shouldShow, options || {});
      layerStore.push({ type: "analysis", items: loaded.primitiveItems });

      if (window.sidebarManager) {
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
      const ds = await withTimeout(Cesium.CzmlDataSource.load(absoluteUrl), 20000, "CZML 图层加载超时");
      viewer.dataSources.add(ds);
      ds.show = shouldShow;
      layerStore.push(ds);
      // Register layer to sidebar
      if (window.sidebarManager) {
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
      const ds = await withTimeout(Cesium.KmlDataSource.load(absoluteUrl, {
        camera: viewer.scene.camera,
        canvas: viewer.scene.canvas,
        clampToGround: true,
      }), 20000, "KML 图层加载超时");
      viewer.dataSources.add(ds);
      ds.show = shouldShow;
      layerStore.push(ds);
      // Register layer to sidebar
      if (window.sidebarManager) {
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
    return async function runBackendAnalysis() {
      const runBtn = document.getElementById("runBackendAnalysis");
      const baseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
      const demPath = document.getElementById("backend-dem-path")?.value?.trim() || "";
      const mode = document.getElementById("backend-analysis-mode")?.value || "terrain";
      const formats = getSelectedFormats();
      var requestTimeoutMs = REQUEST_TIMEOUT_MS;

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
        var runResult;
        var artifacts = [];
        var requestIds = [];
        var demSource = null;

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
          runResult = await runTerrainAnalysisWithAutoTiling({
            baseUrl: baseUrl,
            bbox: bbox,
            cellSizeMeters: cellSizeMeters,
            maxResolution: maxResolution,
            formats: formats,
            demPath: demPath,
            decodePayload: decodePayload,
            analysisType: analysisType,
            tileOverlapCells: TERRAIN_TILE_OVERLAP_CELLS,
          });

          requestTimeoutMs = runResult.lastTimeoutMs || requestTimeoutMs;
          artifacts = runResult.artifacts;
          requestIds = runResult.requestIds || [];
          demSource = runResult.demSource;

          if (runResult.tileCount > 1) {
            showToast("分块分析完成，已拼接加载 " + runResult.tileCount + " 个分块结果", false);
          }
        }

        if (!Array.isArray(artifacts) || !artifacts.length) {
          throw new Error("后端未返回可展示文件");
        }

        clearManagedBackendLayers(viewer);
        global._terrainBackendLayers = [];

        for (const item of artifacts) {
          const url = normalizeUrl(baseUrl, item.url);
          var clipBbox = mode === "terrain"
            ? (item._tileCoreBBox || bbox)
            : null;
          var isSlope = /slope_deg\./i.test(String(item.url || ""));
          var keepVisible = true;
          if (mode === "terrain") {
            keepVisible = !(analysisType === "comprehensive" && !isSlope);
          }
          await loadArtifactToCesium(
            viewer,
            url,
            item.format,
            global._terrainBackendLayers,
            keepVisible,
            { clipBbox: clipBbox }
          );
        }

        var modeExtra = "";
        if (mode === "path" && runResult && Number.isFinite(Number(runResult.bestResolution))) {
          modeExtra = "，路径分级N=" + runResult.bestResolution;
        }
        if (mode === "terrain" && runResult && Number(runResult.tileCount) > 1) {
          modeExtra = "，分块数=" + runResult.tileCount;
        }

        setStatus(`分析完成：request_id=${formatRequestIds(requestIds)}，加载 ${artifacts.length} 个图层${modeExtra}`);
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
        if (error && error.name === "AbortError") {
          message = "请求超时并已中止（" + Math.round(requestTimeoutMs / 1000) + "s）。可减小图幅、增大米/格或减少输出格式后重试。";
        }
        setStatus(`分析失败：${message}`, true);
        showToast(`分析失败：${message}`, true);
        console.error("[TerrainBackend] 分析失败", error);
      } finally {
        if (runBtn) runBtn.disabled = false;
      }
    };
  }

  function initTerrainBackendTools(viewer, slopeAnalysis) {
    if (!viewer) return;
    global._terrainBackendViewer = viewer;

    const panel = document.getElementById("backend-format-modal");
    const openBtn = document.getElementById("openBackendFormatModal");
    const closeBtn = document.getElementById("closeBackendFormatModal");
    const runBtn = document.getElementById("runBackendAnalysis");
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
      setStatus("后端图层已清空");
      showToast("后端图层已清空");
    };

    if (global.__analysisNumericTipEnabled &&
        !(global.SlopeAnalysis && typeof global.SlopeAnalysis.openTip === "function")) {
      setTerrainBackendNumericTipEnabled(true, viewer);
    }
  }

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
    setStatus("后端图层已清空");
    showToast("后端图层已清空");
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
