(function (global) {
    "use strict";

    var ONNX_URL = "./models/terrain_morphology/terrain_morphology.onnx";
    var PATCH_SIZE = 64;
    var HALF = 32;
    var _session = null;

    function initTerrainClassification(viewer) {
        if (!viewer) return;
        global._tcViewer = viewer;
        var btn = document.getElementById("runTerrainClassification");
        if (!btn || btn.dataset.tcBound) return;
        btn.dataset.tcBound = "1";
        btn.addEventListener("click", function (e) {
            if (e) { e.preventDefault(); e.stopPropagation(); }
            var clientMode = document.getElementById("tc-client-mode")?.checked;
            if (clientMode) {
                showMsg("客户端模式已废弃", true);
                return;
            }
            runClassificationServer(viewer);
        });
    }

    // ── Server-side classification (existing) ──────────────────────

    function _showClassifyProgress(current, total) {
        var bar = document.getElementById("classification-progress");
        if (!bar) return;
        var pct = total > 0 ? Math.min(100, Math.round((current / total) * 100)) : 0;
        bar.value = pct;
        bar.max = 100;
        bar.style.display = "inline-block";
        if (total > 1 && current > 0) {
            bar.title = (current * 100 / total).toFixed(0) + "%";
        }
    }

    function _hideClassifyProgress() {
        var bar = document.getElementById("classification-progress");
        if (bar) { bar.style.display = "none"; }
    }

    async function runClassificationServer(viewer) {
        var baseUrl = (document.getElementById("backend-api-url")?.value || "http://127.0.0.1:8000").replace(/\/+$/, "");
        var demPath = document.getElementById("backend-dem-path")?.value?.trim() || "";
        var west = parseFloat(document.getElementById("backend-bbox-west")?.value);
        var south = parseFloat(document.getElementById("backend-bbox-south")?.value);
        var east = parseFloat(document.getElementById("backend-bbox-east")?.value);
        var north = parseFloat(document.getElementById("backend-bbox-north")?.value);
        if (![west, south, east, north].every(Number.isFinite)) {
            showMsg("请先设置分析范围（BBox）", true); return;
        }
        var cellM = parseFloat(document.getElementById("backend-cell-size-m")?.value) || 50;
        var resolution = calcResolution(west, south, east, north, cellM);
        var decodeMode = document.getElementById("backend-dem-decode-mode")?.value || "none";
        var method = document.getElementById("tc-method")?.value || "geomorphons";
        var payload = {
            bbox: { west: west, south: south, east: east, north: north },
            resolution: Math.max(8, Math.min(1024, resolution)),
            classification_method: method,
            dem_path: demPath || null,
            dem_decode_mode: decodeMode,
            dem_decode_band: parseInt(document.getElementById("backend-dem-decode-band")?.value) || 1,
            dem_decode_scale: parseFloat(document.getElementById("backend-dem-decode-scale")?.value) || 1.0,
            dem_decode_offset: parseFloat(document.getElementById("backend-dem-decode-offset")?.value) || 0.0,
            output_formats: ["geojson"],
        };
        var nd = parseFloat(document.getElementById("backend-dem-decode-nodata")?.value);
        if (Number.isFinite(nd)) payload.dem_decode_nodata = nd;

        var methodLabel = method === "onnx" ? "ONNX 推理" : method === "rules" ? "规则法分类" : "Geomorphons 分类";
        showMsg("正在" + methodLabel + "...");
        _hideClassifyProgress();

        var controller = new AbortController();
        var timeoutId = setTimeout(function () { controller.abort(); }, 300000);

        if (method === "onnx") {
            await _runStreamingClassify(viewer, baseUrl, payload, controller);
            clearTimeout(timeoutId);
            return;
        }

        try {
            var resp = await fetch(baseUrl + "/api/v1/analyze/classify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                signal: controller.signal,
            });
            clearTimeout(timeoutId);
            if (!resp.ok) {
                var errBody = await resp.text().catch(function () { return ""; });
                throw new Error("HTTP " + resp.status + " " + errBody.slice(0, 200));
            }
            var data = await resp.json();
            showMsg("分类完成，加载图层...");
            if (Array.isArray(data.legend)) showLegend(data.legend);
            var artifacts = data.artifacts || [];
            if (!artifacts.length) { showMsg("无可用输出", true); return; }
            for (var i = 0; i < artifacts.length; i++) {
                var art = artifacts[i];
                var fullUrl = baseUrl + "/" + art.url.replace(/^\//, "");
                if (art.format === "geojson") {
                    await loadClassifiedGeoJson(viewer, fullUrl, data.legend);
                }
            }
            showMsg("地貌分类图层已加载");
        } catch (err) {
            console.error("[TC]", err);
            if (err.name === "AbortError") {
                showMsg("分类请求超时（5 分钟），请缩小范围或换 Geomorphons 方法", true);
            } else {
                showMsg("分类失败: " + (err.message || err), true);
            }
        }
    }

    async function _runStreamingClassify(viewer, baseUrl, payload, controller) {
        var progressBar = document.getElementById("classification-progress");
        try {
            var resp = await fetch(baseUrl + "/api/v1/analyze/classify/stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                signal: controller.signal,
            });
            if (!resp.ok) {
                var errBody = await resp.text().catch(function () { return ""; });
                throw new Error("HTTP " + resp.status + " " + errBody.slice(0, 200));
            }

            var reader = resp.body.getReader();
            var decoder = new TextDecoder();
            var buffer = "";
            var resultData = null;

            while (true) {
                var chunk = await reader.read();
                if (chunk.done) break;
                buffer += decoder.decode(chunk.value, { stream: true });
                var lines = buffer.split("\n");
                buffer = lines.pop() || "";

                for (var li = 0; li < lines.length; li++) {
                    var line = lines[li].trim();
                    if (!line) continue;
                    try {
                        var evt = JSON.parse(line);
                    } catch (_) { continue; }

                    if (evt.type === "phase") {
                        showMsg(evt.label || "");
                        if (progressBar) {
                            progressBar.title = evt.label || "";
                        }
                    } else if (evt.type === "progress") {
                        if (evt.total > 0) {
                            _showClassifyProgress(evt.current, evt.total);
                        }
                    } else if (evt.type === "result") {
                        resultData = evt;
                    } else if (evt.type === "error") {
                        throw new Error(evt.message || "分类服务端错误");
                    }
                }
            }

            if (!resultData) throw new Error("未收到分类结果");

            showMsg("分类完成，加载图层...");
            _hideClassifyProgress();
            if (Array.isArray(resultData.legend)) showLegend(resultData.legend);
            var artifacts = resultData.artifacts || [];
            if (!artifacts.length) { showMsg("无可用输出", true); return; }
            for (var i = 0; i < artifacts.length; i++) {
                var art = artifacts[i];
                var fullUrl = baseUrl + "/" + art.url.replace(/^\//, "");
                if (art.format === "geojson") {
                    await loadClassifiedGeoJson(viewer, fullUrl, resultData.legend);
                }
            }
            showMsg("地貌分类图层已加载");

        } catch (err) {
            _hideClassifyProgress();
            console.error("[TC]", err);
            if (err.name === "AbortError") {
                showMsg("分类请求超时（5 分钟），请缩小范围或换 Geomorphons 方法", true);
            } else {
                showMsg("分类失败: " + (err.message || err), true);
            }
        }
    }

    // ── Client-side ONNX inference ────────────────────────────────

    async function runClassificationClient(viewer) {
        var west = parseFloat(document.getElementById("backend-bbox-west")?.value);
        var south = parseFloat(document.getElementById("backend-bbox-south")?.value);
        var east = parseFloat(document.getElementById("backend-bbox-east")?.value);
        var north = parseFloat(document.getElementById("backend-bbox-north")?.value);
        if (![west, south, east, north].every(Number.isFinite)) {
            showMsg("请先设置分析范围（BBox）", true); return;
        }

        showMsg("浏览器端推理: 加载 ONNX 模型...");
        try {
            if (!_session) {
                if (typeof ort === "undefined") throw new Error("onnxruntime-web 未加载");
                _session = await ort.InferenceSession.create(ONNX_URL);
            }
        } catch (err) {
            showMsg("ONNX 模型加载失败: " + err.message, true);
            return;
        }

        // Grid: 16×16 for preview
        var gridRows = 16, gridCols = 16;
        var nSampleRows = gridRows + PATCH_SIZE;
        var nSampleCols = gridCols + PATCH_SIZE;

        showMsg("浏览器端推理: 采样地形...");
        try {
            // Build position grid
            var positions = [];
            var lonStep = (east - west) / (gridCols - 1);
            var latStep = (north - south) / (gridRows - 1);
            for (var r = 0; r < nSampleRows; r++) {
                var lat = south + (r - HALF) * latStep;
                for (var c = 0; c < nSampleCols; c++) {
                    var lon = west + (c - HALF) * lonStep;
                    positions.push(Cesium.Cartographic.fromDegrees(lon, lat));
                }
            }
            var sampled = await Cesium.sampleTerrain(viewer.terrainProvider, 11, positions);
            var demGrid = [];
            for (var r = 0; r < nSampleRows; r++) {
                demGrid[r] = [];
                for (var c = 0; c < nSampleCols; c++) {
                    var h = sampled[r * nSampleCols + c].height;
                    demGrid[r][c] = Number.isFinite(h) ? h : 0;
                }
            }

            showMsg("浏览器端推理: 运行模型 (" + gridRows + "×" + gridCols + ") ...");
            var legend = getDefaultLegend();
            var classIds = [];
            var confidences = [];
            var batchSize = 64;
            var allPatches = [];

            for (var r = 0; r < gridRows; r++) {
                for (var c = 0; c < gridCols; c++) {
                    var patch = [];
                    for (var pr = 0; pr < PATCH_SIZE; pr++) {
                        for (var pc = 0; pc < PATCH_SIZE; pc++) {
                            patch.push(demGrid[r + pr][c + pc]);
                        }
                    }
                    // Z-score normalize
                    var sum = 0, sum2 = 0, len = patch.length;
                    for (var i = 0; i < len; i++) { sum += patch[i]; }
                    var mean = sum / len;
                    for (var i = 0; i < len; i++) { var d = patch[i] - mean; sum2 += d * d; }
                    var std = Math.sqrt(sum2 / len) || 1e-8;
                    var norm = new Float32Array(PATCH_SIZE * PATCH_SIZE);
                    for (var i = 0; i < len; i++) { norm[i] = (patch[i] - mean) / std; }
                    allPatches.push(norm);
                }
            }

            for (var start = 0; start < allPatches.length; start += batchSize) {
                var end = Math.min(start + batchSize, allPatches.length);
                var batchTensor = new ort.Tensor("float32", new Float32Array(PATCH_SIZE * PATCH_SIZE * (end - start)), [end - start, 1, PATCH_SIZE, PATCH_SIZE]);
                var bData = batchTensor.data;
                for (var bi = start; bi < end; bi++) {
                    var offset = (bi - start) * PATCH_SIZE * PATCH_SIZE;
                    for (var pi = 0; pi < PATCH_SIZE * PATCH_SIZE; pi++) {
                        bData[offset + pi] = allPatches[bi][pi];
                    }
                }
                var output = await _session.run({ dem_patch: batchTensor });
                var logits = output.logits.data;
                for (var bi = start; bi < end; bi++) {
                    var row = Math.floor(bi / gridCols);
                    var col = bi % gridCols;
                    var offset2 = (bi - start) * 8;
                    var maxL = -Infinity, maxIdx = 0;
                    for (var k = 0; k < 8; k++) {
                        var v = logits[offset2 + k];
                        if (v > maxL) { maxL = v; maxIdx = k; }
                    }
                    // Softmax for confidence
                    var sumExp = 0;
                    for (var k = 0; k < 8; k++) { sumExp += Math.exp(logits[offset2 + k] - maxL); }
                    var conf = Math.exp(logits[offset2 + maxIdx] - maxL) / sumExp;
                    if (!classIds[row]) classIds[row] = [];
                    if (!confidences[row]) confidences[row] = [];
                    classIds[row][col] = maxIdx;
                    confidences[row][col] = conf;
                }
            }

            showMsg("浏览器端推理: 渲染结果...");
            displayClassificationGrid(viewer, west, south, east, north, gridRows, gridCols, classIds, confidences, legend);
            if (Array.isArray(legend)) showLegend(legend);
            showMsg("浏览器端推理完成");
        } catch (err) {
            console.error("[TC-Client]", err);
            showMsg("浏览器推理失败: " + err.message, true);
        }
    }

    function displayClassificationGrid(viewer, west, south, east, north, rows, cols, classIds, confidences, legend) {
        var idToColor = {};
        var idToLabel = {};
        if (Array.isArray(legend)) {
            for (var i = 0; i < legend.length; i++) {
                idToColor[legend[i].id] = legend[i].color;
                idToLabel[legend[i].id] = legend[i].label_cn || legend[i].name;
            }
        }
        var groups = {};
        var lonStep = (east - west) / cols;
        var latStep = (north - south) / rows;

        for (var r = 0; r < rows; r++) {
            for (var c = 0; c < cols; c++) {
                var cid = classIds[r] && classIds[r][c];
                if (cid == null) continue;
                var colLon = west + c * lonStep;
                var rowLat = south + r * latStep;
                var ring = [
                    colLon, rowLat,
                    colLon + lonStep, rowLat,
                    colLon + lonStep, rowLat + latStep,
                    colLon, rowLat + latStep,
                    colLon, rowLat
                ];
                var colorStr = idToColor[cid] || "#888888";
                var parsed = parseColor(colorStr, 0.7);
                var key = Math.round(parsed.red*255) + "_" + Math.round(parsed.green*255) + "_" + Math.round(parsed.blue*255);
                if (!groups[key]) groups[key] = { color: parsed, inst: [] };
                groups[key].inst.push(new Cesium.GeometryInstance({
                    geometry: new Cesium.PolygonGeometry({
                        polygonHierarchy: new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(ring)),
                        height: 0, vertexFormat: Cesium.MaterialAppearance.VERTEX_FORMAT,
                    }),
                }));
            }
        }

        var allPrimitives = [];
        Object.keys(groups).forEach(function (k) {
            var grp = groups[k];
            if (!grp.inst.length) return;
            var prim = viewer.scene.primitives.add(new Cesium.GroundPrimitive({
                geometryInstances: grp.inst,
                appearance: new Cesium.MaterialAppearance({
                    material: new Cesium.Material({ fabric: { type: "Color", uniforms: { color: grp.color } } }),
                    translucent: grp.color.alpha < 1, flat: true,
                }),
            }));
            allPrimitives.push({ primitive: prim, baseColor: grp.color, alpha: grp.color.alpha });
        });

        if (allPrimitives.length && global.sidebarManager && typeof sidebarManager.addLayer === "function") {
            sidebarManager.addLayer({
                name: "地貌分类(浏览器端)",
                type: "Analysis",
                cesiumObject: allPrimitives,
                extras: { _backendManaged: true, _classification: true, _clientSide: true },
            });
        }
    }

    // ── Shared helpers ─────────────────────────────────────────────

    function calcResolution(w, s, e, n, cellM) {
        var cell = Math.max(1, cellM || 50);
        var clat = ((s + n) * 0.5) * Math.PI / 180;
        var mDl = 111320 * Math.max(1e-6, Math.cos(clat));
        var mDa = 110574;
        var span = Math.max(Math.abs(e - w) * mDl, Math.abs(n - s) * mDa);
        return Math.max(16, Math.min(512, Math.ceil(span / cell) + 1));
    }

    async function loadClassifiedGeoJson(viewer, url, legend) {
        var resp = await fetch(url, { cache: "no-store" });
        var fc = await resp.json();
        var feats = Array.isArray(fc && fc.features) ? fc.features : [];
        if (!feats.length) { showMsg("GeoJSON 无要素", true); return; }

        var colorMap = {};
        if (Array.isArray(legend)) {
            for (var li = 0; li < legend.length; li++) {
                colorMap[legend[li].label_cn] = legend[li].color;
            }
        }

        var groups = {};
        for (var i = 0; i < feats.length; i++) {
            var f = feats[i], props = f.properties || {};
            var g = f && f.geometry;
            if (!g || g.type !== "Polygon") continue;
            var ring = g.coordinates && g.coordinates[0];
            if (!ring || ring.length < 4) continue;
            var flat = [];
            for (var j = 0; j < ring.length; j++) {
                var p = ring[j];
                if (Array.isArray(p) && p.length >= 2) flat.push(Number(p[0]), Number(p[1]));
            }
            if (flat.length < 6) continue;
            var fill = props.fill || "#888888";
            var c = parseColor(fill, 0.75);
            var key = Math.round(c.red*255) + "_" + Math.round(c.green*255) + "_" + Math.round(c.blue*255);
            if (!groups[key]) groups[key] = { color: c, inst: [] };
            groups[key].inst.push(new Cesium.GeometryInstance({
                geometry: new Cesium.PolygonGeometry({
                    polygonHierarchy: new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(flat)),
                    height: 0, vertexFormat: Cesium.MaterialAppearance.VERTEX_FORMAT,
                }),
            }));
        }

        var allPrimitives = [];
        Object.keys(groups).forEach(function (k) {
            var grp = groups[k];
            if (!grp.inst.length) return;
            var prim = viewer.scene.primitives.add(new Cesium.GroundPrimitive({
                geometryInstances: grp.inst,
                appearance: new Cesium.MaterialAppearance({
                    material: new Cesium.Material({ fabric: { type: "Color", uniforms: { color: grp.color } } }),
                    translucent: grp.color.alpha < 1, flat: true,
                }),
            }));
            allPrimitives.push({ primitive: prim, baseColor: grp.color, alpha: grp.color.alpha });
        });

        if (allPrimitives.length && global.sidebarManager && typeof sidebarManager.addLayer === "function") {
            sidebarManager.addLayer({
                name: "地貌分类",
                type: "Analysis",
                url: url,
                cesiumObject: allPrimitives,
                extras: { _backendManaged: true, _classification: true },
            });
        }
    }

    function parseColor(css, fallbackAlpha) {
        var r = 100, g = 200, b = 255, a = fallbackAlpha || 0.65;
        if (typeof css === "string") {
            var m = css.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)/);
            if (m) { r = +m[1]; g = +m[2]; b = +m[3]; a = m[4] != null ? +m[4] : (fallbackAlpha || 0.65); }
            else if (css[0] === "#") {
                var h = css.slice(1);
                if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
                if (h.length === 6) { r = parseInt(h.slice(0,2),16); g = parseInt(h.slice(2,4),16); b = parseInt(h.slice(4,6),16); }
            }
        }
        return new Cesium.Color(r / 255, g / 255, b / 255, a);
    }

    function getDefaultLegend() {
        return [
            { id: 0, name: "flat", label_cn: "平地", color: "#38a800" },
            { id: 1, name: "peak", label_cn: "山顶", color: "#ff0000" },
            { id: 2, name: "ridge", label_cn: "山脊", color: "#ff8000" },
            { id: 3, name: "steep_slope", label_cn: "陡坡", color: "#ff00ff" },
            { id: 4, name: "gentle_slope", label_cn: "缓坡", color: "#ffff00" },
            { id: 5, name: "valley", label_cn: "山谷", color: "#00a6ff" },
            { id: 6, name: "depression", label_cn: "洼地", color: "#0040ff" },
            { id: 7, name: "cliff", label_cn: "陡崖", color: "#8b0000" },
        ];
    }

    function showMsg(text, isError) {
        if (typeof global.showToast === "function") global.showToast(text, !!isError);
    }

    function showLegend(legend) {
        var el = document.getElementById("tc-legend");
        if (el) el.remove();
        el = document.createElement("div");
        el.id = "tc-legend";
        el.style.cssText = "position:absolute;bottom:20px;right:20px;z-index:9999;background:rgba(11,28,55,0.88);border:1px solid #3a6ea5;border-radius:6px;padding:10px 14px;color:#fff;font-size:12px;min-width:140px;";
        var title = document.createElement("div");
        title.style.cssText = "font-weight:bold;margin-bottom:6px;border-bottom:1px solid #3a6ea5;padding-bottom:3px;";
        title.textContent = "地貌分类图例";
        var close = document.createElement("span");
        close.textContent = "✕";
        close.style.cssText = "float:right;cursor:pointer;font-size:14px;color:#aaa;";
        close.onclick = function () { el.remove(); };
        title.appendChild(close);
        el.appendChild(title);
        for (var i = 0; i < legend.length; i++) {
            var item = legend[i];
            var row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;margin:2px 0;";
            var sw = document.createElement("span");
            sw.style.cssText = "display:inline-block;width:14px;height:14px;margin-right:6px;border-radius:2px;border:1px solid rgba(255,255,255,0.2);";
            sw.style.backgroundColor = item.color || "#888";
            row.appendChild(sw);
            var lb = document.createElement("span");
            lb.textContent = (item.label_cn || item.name) + " (CF:" + (item.cost_factor || "-") + ")";
            row.appendChild(lb);
            el.appendChild(row);
        }
        document.body.appendChild(el);
    }

    global.initTerrainClassification = initTerrainClassification;

    function autoInit() {
        if (global.__tcAutoInited) return;
        if (!global.viewer) return;
        initTerrainClassification(global.viewer);
        global.__tcAutoInited = true;
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", autoInit);
    else autoInit();
    setTimeout(autoInit, 600);
})(window);
