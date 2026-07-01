(function (global) {
    "use strict";

    function initTerrainClassification(viewer) {
        if (!viewer) return;
        global._terrainClassifyViewer = viewer;

        var btn = document.getElementById("runTerrainClassification");
        if (!btn) {
            console.warn("[TerrainClassification] 按钮 #runTerrainClassification 不存在");
            return;
        }
        if (btn.dataset.tcInited === "1") return;
        btn.dataset.tcInited = "1";

        btn.addEventListener("click", async function (event) {
            if (event) { event.preventDefault(); event.stopPropagation(); }
            await runTerrainClassification(viewer);
        });
    }

    async function runTerrainClassification(viewer) {
        var baseUrl = document.getElementById("backend-api-url")?.value?.trim() || "http://127.0.0.1:8000";
        var demPath = document.getElementById("backend-dem-path")?.value?.trim() || "";

        var west = parseFloat(document.getElementById("backend-bbox-west")?.value);
        var south = parseFloat(document.getElementById("backend-bbox-south")?.value);
        var east = parseFloat(document.getElementById("backend-bbox-east")?.value);
        var north = parseFloat(document.getElementById("backend-bbox-north")?.value);
        var cellSizeMeters = parseFloat(document.getElementById("backend-cell-size-m")?.value) || 50;
        var resolution = estimateResolution(west, south, east, north, cellSizeMeters);

        if (!Number.isFinite(west) || !Number.isFinite(south) || !Number.isFinite(east) || !Number.isFinite(north)) {
            global.showToast && global.showToast("请先设置分析范围（BBox）", true);
            return;
        }

        var decodeMode = document.getElementById("backend-dem-decode-mode")?.value || "none";
        var decodeBand = parseInt(document.getElementById("backend-dem-decode-band")?.value) || 1;
        var decodeScale = parseFloat(document.getElementById("backend-dem-decode-scale")?.value) || 1.0;
        var decodeOffset = parseFloat(document.getElementById("backend-dem-decode-offset")?.value) || 0.0;
        var decodeNoData = parseFloat(document.getElementById("backend-dem-decode-nodata")?.value);
        if (!Number.isFinite(decodeNoData)) decodeNoData = null;

        var payload = {
            bbox: { west: west, south: south, east: east, north: north },
            resolution: Math.max(8, Math.min(1024, resolution)),
            dem_path: demPath || null,
            dem_decode_mode: decodeMode,
            dem_decode_band: decodeBand,
            dem_decode_scale: decodeScale,
            dem_decode_offset: decodeOffset,
            dem_decode_nodata: decodeNoData,
            output_formats: ["geojson"],
        };

        global.showToast && global.showToast("正在请求地貌分类...");

        try {
            var resp = await fetch(baseUrl + "/api/v1/analyze/classify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!resp.ok) {
                var errText = await resp.text().catch(function () { return resp.statusText; });
                throw new Error("分类请求失败: HTTP " + resp.status + " " + errText);
            }
            var data = await resp.json();
            global.showToast && global.showToast("分类结果已返回，正在加载图层...");

            var legend = data.legend;
            if (Array.isArray(legend) && legend.length) {
                showClassificationLegend(legend);
            }

            var artifacts = data.artifacts || [];
            if (!artifacts.length) {
                global.showToast && global.showToast("分类结果无可用输出格式", true);
                return;
            }

            if (typeof global.renderTerrainArtifacts === "function") {
                var bbox = { west: west, south: south, east: east, north: north };
                await global.renderTerrainArtifacts(viewer, artifacts, baseUrl, bbox, "classification", {
                    registerSidebar: true,
                });
                global.showToast && global.showToast("地貌分类图层已加载");
            } else {
                for (var i = 0; i < artifacts.length; i++) {
                    var art = artifacts[i];
                    var url = normalizeUrl(baseUrl, art.url);
                    if (art.format === "geojson") {
                        await loadGeojsonDirectly(viewer, url);
                    }
                }
                global.showToast && global.showToast("地貌分类图层已加载（直接模式）");
            }
        } catch (error) {
            console.error("[TerrainClassification] 分类失败:", error);
            global.showToast && global.showToast("分类失败: " + error.message, true);
        }
    }

    function normalizeUrl(baseUrl, url) {
        if (!url) return "";
        if (url.indexOf("://") >= 0) return url;
        var base = (baseUrl || "").replace(/\/+$/, "");
        return base + "/" + url.replace(/^\/+/, "");
    }

    async function loadGeojsonDirectly(viewer, url) {
        var response = await fetch(url, { cache: "no-store" });
        if (!response.ok) throw new Error("GeoJSON 加载失败: HTTP " + response.status);
        var fc = await response.json();
        var features = Array.isArray(fc && fc.features) ? fc.features : [];
        if (!features.length) throw new Error("GeoJSON 无要素");

        var colorGroups = {};
        for (var i = 0; i < features.length; i++) {
            var f = features[i];
            var g = f && f.geometry;
            if (!g || g.type !== "Polygon" || !Array.isArray(g.coordinates) || !g.coordinates[0]) continue;
            var ring = g.coordinates[0];
            if (ring.length < 4) continue;
            var flat = [];
            for (var j = 0; j < ring.length; j++) {
                var p = ring[j];
                if (Array.isArray(p) && p.length >= 2) { flat.push(Number(p[0]), Number(p[1])); }
            }
            if (flat.length < 6) continue;
            var props = f.properties || {};
            var fillCss = props.fill || "rgba(100,200,255,0.65)";
            var parsedColor = parseRgbaString(fillCss, 0.65);
            var key = parsedColor.red + "_" + parsedColor.green + "_" + parsedColor.blue;
            if (!colorGroups[key]) {
                colorGroups[key] = { color: parsedColor, instances: [] };
            }
            var positions = Cesium.Cartesian3.fromDegreesArray(flat);
            colorGroups[key].instances.push(
                new Cesium.GeometryInstance({
                    geometry: new Cesium.PolygonGeometry({
                        polygonHierarchy: new Cesium.PolygonHierarchy(positions),
                        height: 0,
                        vertexFormat: Cesium.MaterialAppearance.VERTEX_FORMAT,
                    }),
                })
            );
        }

        Object.keys(colorGroups).forEach(function (key) {
            var group = colorGroups[key];
            if (!group.instances.length) return;
            var material = new Cesium.Material({
                fabric: { type: "Color", uniforms: { color: group.color } },
            });
            var appearance = new Cesium.MaterialAppearance({
                material: material,
                translucent: group.color.alpha < 1.0,
                flat: true,
            });
            var primitive = new Cesium.GroundPrimitive({
                geometryInstances: group.instances,
                appearance: appearance,
            });
            viewer.scene.primitives.add(primitive);
        });

        if (global.sidebarManager && typeof global.sidebarManager.addLayer === "function") {
            global.sidebarManager.addLayer({
                name: "Terrain Classification",
                type: "GeoJson",
                url: url,
                cesiumObject: viewer.scene.primitives,
            });
        }
    }

    function parseRgbaString(cssColor, fallbackAlpha) {
        var r = 100, g = 200, b = 255, a = fallbackAlpha || 0.65;
        if (typeof cssColor === "string") {
            var rgbaMatch = cssColor.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)/);
            if (rgbaMatch) {
                r = parseInt(rgbaMatch[1]) || 0;
                g = parseInt(rgbaMatch[2]) || 0;
                b = parseInt(rgbaMatch[3]) || 0;
                a = rgbaMatch[4] !== undefined ? parseFloat(rgbaMatch[4]) : (fallbackAlpha || 0.65);
            } else if (cssColor.startsWith("#")) {
                var hex = cssColor.replace("#", "");
                if (hex.length === 3) hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
                if (hex.length === 6) {
                    r = parseInt(hex.substr(0, 2), 16) || 0;
                    g = parseInt(hex.substr(2, 2), 16) || 0;
                    b = parseInt(hex.substr(4, 2), 16) || 0;
                    a = fallbackAlpha || 0.65;
                }
            }
        }
        return new Cesium.Color(r / 255, g / 255, b / 255, a);
    }

    function showClassificationLegend(legend) {
        var existing = document.getElementById("tc-legend-overlay");
        if (existing) existing.remove();

        var overlay = document.createElement("div");
        overlay.id = "tc-legend-overlay";
        overlay.style.cssText = "position:absolute;bottom:20px;right:20px;z-index:9999;background:rgba(11,28,55,0.85);border:1px solid #3a6ea5;border-radius:6px;padding:12px 16px;color:#fff;font-size:12px;min-width:140px;max-height:360px;overflow-y:auto;";

        var title = document.createElement("div");
        title.style.cssText = "font-weight:bold;margin-bottom:8px;border-bottom:1px solid #3a6ea5;padding-bottom:4px;";
        title.textContent = "地貌分类图例";
        overlay.appendChild(title);

        var closeBtn = document.createElement("span");
        closeBtn.textContent = "✕";
        closeBtn.style.cssText = "float:right;cursor:pointer;font-size:14px;color:#aaa;";
        closeBtn.addEventListener("click", function () { overlay.remove(); });
        title.appendChild(closeBtn);

        for (var i = 0; i < legend.length; i++) {
            var item = legend[i];
            var row = document.createElement("div");
            row.style.cssText = "display:flex;align-items:center;margin:3px 0;";

            var swatch = document.createElement("span");
            swatch.style.cssText = "display:inline-block;width:16px;height:16px;margin-right:8px;border-radius:2px;border:1px solid rgba(255,255,255,0.3);";
            swatch.style.backgroundColor = item.color || "#888";
            row.appendChild(swatch);

            var label = document.createElement("span");
            label.textContent = (item.label_cn || item.name || "class " + item.id) + " (CF:" + (item.cost_factor || "—") + ")";
            row.appendChild(label);

            overlay.appendChild(row);
        }

        document.body.appendChild(overlay);
    }

    function estimateResolution(west, south, east, north, cellSizeMeters) {
        var cell = Math.max(1.0, Number(cellSizeMeters) || 50.0);
        var maxRes = 512;
        var centerLat = ((Number(south) + Number(north)) * 0.5) * Math.PI / 180.0;
        var mPerDegLon = 111320.0 * Math.max(1e-6, Math.cos(centerLat));
        var mPerDegLat = 110574.0;
        var wM = Math.abs(Number(east) - Number(west)) * mPerDegLon;
        var hM = Math.abs(Number(north) - Number(south)) * mPerDegLat;
        var span = Math.max(wM, hM);
        var raw = Math.max(1, Math.ceil(span / cell)) + 1;
        return Math.max(16, Math.min(maxRes, raw));
    }

    global.initTerrainClassification = initTerrainClassification;

    function autoInit() {
        if (global.__tcAutoInitDone) return;
        if (!global.viewer) return;
        initTerrainClassification(global.viewer);
        global.__tcAutoInitDone = true;
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", autoInit);
    } else {
        autoInit();
    }
    setTimeout(autoInit, 500);
})(window);
