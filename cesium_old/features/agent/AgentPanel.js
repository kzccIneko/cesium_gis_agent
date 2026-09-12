/* AgentPanel.js
 *
 * 嵌在三维地理信息系统里的分析助手面板。
 *
 * 它不是另一个网页 —— 面板本身就是主页面里的第 15 个 .functionWin 窗口
 * （和「坡度坡向分析」「剖面分析」那些同款），共用主系统的：
 *   · 拖拽 / 折叠 / 关闭  —— eventBindInit.js 的委托，带 .move/.close/.toggle_win 即自动生效
 *   · 置顶管理            —— window.WindowMgr
 *   · 图层树              —— window.sidebarManager（分析结果图层进同一个侧栏）
 *   · Cesium 渲染管道      —— window.TerrainBackendBridge（复用现有加载逻辑，不另写一套）
 *
 * 与系统的交互点：
 *   输入侧：读取当前相机视野作为默认分析范围（"所见即所问"）
 *   输出侧：把矢量产物叠加到三维地球、纳入侧栏图层管理，并把相机飞到分析范围
 */
(function (global) {
    'use strict';

    var API_BASE = (global.__AGENT_API_BASE__) || 'http://127.0.0.1:8000';
    var WIN_ID = 'agentAssistantWin';
    // Agent 自己加载的图层登记在这里，便于统一清理
    var _agentLayerStore = [];

    var state = {
        useViewBBox: true,
        busy: false,
        win: null,
        chatEl: null,
        inputEl: null,
        ctxValueEl: null
    };

    /* ---------------- 上下文：当前视野 ---------------- */

    // 视野跨度超过这个值就不拿来当分析范围了。
    // 相机在初始高度时 computeViewRectangle 会返回接近全球的矩形（实测 -180,-90 → 180,90），
    // 拿它做 256×256 栅格等于在全地球上采样，结果毫无意义还慢。
    // 一个山地研究区通常在几度以内，20° 是个宽松的上限。
    var MAX_VIEW_SPAN_DEG = 20;

    /** 相机视野的原始 bbox（不设阈值，问"我在看哪"时要如实回答） */
    function _rawViewBBox() {
        try {
            if (!(global.TerrainBackendBridge && global.TerrainBackendBridge.getViewBBox)) return null;
            var bbox = global.TerrainBackendBridge.getViewBBox(global.viewer);
            if (!bbox || bbox.length < 4) return null;
            return bbox;
        } catch (e) {
            console.warn('[AgentPanel] 读取视野范围失败:', e);
            return null;
        }
    }

    function currentViewBBox() {
        if (!state.useViewBBox) return null;
        var bbox = _rawViewBBox();
        if (!bbox) return null;
        // 视野太大时不递给后端（原因见 isViewTooLarge 的注释）
        if (isViewTooLarge(bbox)) return null;
        return bbox;
    }

    function refreshCtxLabel() {
        if (!state.ctxValueEl) return;
        if (!state.useViewBBox) {
            state.ctxValueEl.textContent = '(不限定，由提问中的地名决定)';
            return;
        }
        try {
            if (global.TerrainBackendBridge && global.TerrainBackendBridge.getViewBBox) {
                var bbox = global.TerrainBackendBridge.getViewBBox(global.viewer);
                if (!bbox || bbox.length < 4) {
                    state.ctxValueEl.textContent = '(地图未就绪)';
                    return;
                }
                var spanLon = Math.abs(bbox[2] - bbox[0]);
                var spanLat = Math.abs(bbox[3] - bbox[1]);
                if (spanLon > MAX_VIEW_SPAN_DEG || spanLat > MAX_VIEW_SPAN_DEG) {
                    state.ctxValueEl.textContent =
                        '视野过大（' + spanLon.toFixed(0) + '°×' + spanLat.toFixed(0) +
                        '°），请放大到具体分析范围';
                    return;
                }
                state.ctxValueEl.textContent =
                    bbox[0].toFixed(2) + ', ' + bbox[1].toFixed(2) + ' → ' +
                    bbox[2].toFixed(2) + ', ' + bbox[3].toFixed(2);
                return;
            }
        } catch (e) {
            console.warn('[AgentPanel] 读取视野范围失败:', e);
        }
        state.ctxValueEl.textContent = '(地图未就绪)';
    }

    /* ---------------- 消息渲染 ---------------- */

    function scrollToBottom() {
        if (!state.chatEl) return;
        state.chatEl.scrollTop = state.chatEl.scrollHeight;
    }

    function addUserMessage(text) {
        var wrap = document.createElement('div');
        wrap.className = 'agentp-msg agentp-msg-user';
        var b = document.createElement('div');
        b.className = 'bubble';
        b.textContent = text;
        wrap.appendChild(b);
        state.chatEl.appendChild(wrap);
        scrollToBottom();
    }

    function addBotShell() {
        var wrap = document.createElement('div');
        wrap.className = 'agentp-msg agentp-msg-bot';
        var who = document.createElement('div');
        who.className = 'who';
        who.textContent = 'GeoAgent';
        var bubble = document.createElement('div');
        bubble.className = 'bubble';
        wrap.appendChild(who);
        wrap.appendChild(bubble);
        state.chatEl.appendChild(wrap);
        scrollToBottom();
        return wrap;
    }

    function addWaiting(wrap) {
        var w = document.createElement('div');
        w.className = 'agentp-waiting';
        w.textContent = '正在规划…（本地模型，通常需要 5–30 秒）';
        wrap.appendChild(w);
        scrollToBottom();
        return w;
    }

    function addSteps(wrap, steps) {
        if (!steps || !steps.length) return;
        if (!steps.length) return;
        var box = document.createElement('div');
        box.className = 'agentp-steps';
        steps.forEach(function (s) {
            var row = document.createElement('div');
            row.className = 'agentp-step ' + (s.success ? 'ok' : 'fail');
            row.innerHTML =
                '<span class="icon">' + (s.success ? '✓' : '✗') + '</span>' +
                '<span class="name"></span>' +
                '<span class="ms"></span>' +
                (s.intent ? '<span class="intent"></span>' : '');
            row.querySelector('.name').textContent = s.tool || '—';
            row.querySelector('.ms').textContent =
                s.duration_ms ? (Math.round(s.duration_ms) + ' ms') : '';
            if (s.intent) row.querySelector('.intent').textContent = s.intent;
            box.appendChild(row);
        });
        wrap.appendChild(box);
        scrollToBottom();
    }

    function addResults(wrap, steps) {
        var view = global.AgentResultView;
        if (!view || !steps) return;
        var mounted = false;
        steps.forEach(function (s) {
            var node = view.renderStep(s, {
                onOverlay: overlayArtifact,
                onLocate: locateBBox
            });
            if (node) {
                wrap.appendChild(node);
                mounted = true;
            }
        });
        if (mounted) {
            view.mountCharts(wrap);
            scrollToBottom();
        }
    }

    /* ---------------- 地图联动 ---------------- */

    function overlayArtifact(artifact) {
        var bridge = global.TerrainBackendBridge;
        var viewer = global.viewer;
        if (!bridge || !viewer) {
            console.error('[AgentPanel] 地图尚未就绪，无法叠加图层');
            return Promise.resolve(false);
        }
        var url = artifact.url.startsWith('http')
            ? artifact.url
            : (API_BASE + artifact.url);
        try {
            return Promise.resolve(
                bridge.loadArtifactToCesium(viewer, url, artifact.format, _agentLayerStore, true)
            ).then(function () {
                // 图层进来后打开左下角的悬浮数值提示，和"坡度坡向分析"的行为保持一致
                try { bridge.setNumericTipEnabled(true, viewer); } catch (e) { /* ignore */ }
                return true;
            }).catch(function (err) {
                console.error('[AgentPanel] 加载图层失败:', err);
                return false;
            });
        } catch (err) {
            console.error('[AgentPanel] 加载图层异常:', err);
            return Promise.resolve(false);
        }
    }

    function locateBBox(bbox) {
        var bridge = global.TerrainBackendBridge;
        if (!bridge || !global.viewer) return;
        bridge.flyToBBox(global.viewer, bbox);
    }

    /* ---------------- 元问题：直接回答，不调大模型 ---------------- */

    // 「我现在看到的是哪一块？」这类问题问的是**视图本身**，不是地理分析任务。
    // 以前它会被丢给规划器，规划器发现"没有地点"就自己编一个默认范围（成都周边）
    // 然后真的跑一遍地形计算 —— 用户没问这些，还会看到地图莫名其妙跑走。
    var VIEW_QUERY_WORDS = [
        '视野', '范围', '区域范围', '这是哪', '这是什么地方', '什么地方',
        '当前区域', '现在看到', '在看哪', '看的哪', '哪个区域', '哪个地方',
    ];
    // 出现这些词说明用户真的想做分析，不能当元问题拦掉
    var ANALYSIS_WORDS = [
        '坡度', '坡向', '曲率', '分类', '统计', '路径', '路线', '下载', '分析',
        '计算', '规划', '代价', '高程', '占比', '面积', '地貌', '通行', '生成',
    ];

    function _squeeze(text) {
        return String(text || '').replace(/[\s，。！？、,.!?~～…：:；;]/g, '');
    }

    function isViewQuery(text) {
        var q = _squeeze(text);
        if (!q) return false;
        for (var i = 0; i < ANALYSIS_WORDS.length; i++) {
            if (q.indexOf(ANALYSIS_WORDS[i]) >= 0) return false;
        }
        for (var j = 0; j < VIEW_QUERY_WORDS.length; j++) {
            if (q.indexOf(VIEW_QUERY_WORDS[j]) >= 0) return true;
        }
        return false;
    }

    /** 与后端 bbox_area_km2 同一套近似公式，保证两边报的面积一致 */
    function approxAreaKm2(bbox) {
        var midLat = ((bbox[1] + bbox[3]) / 2) * Math.PI / 180;
        var wKm = (bbox[2] - bbox[0]) * 111.320 * Math.max(1e-6, Math.cos(midLat));
        var hKm = (bbox[3] - bbox[1]) * 110.574;
        return Math.abs(wKm * hKm);
    }

    function fmtCoord(v, isLat) {
        var hemi = isLat ? (v >= 0 ? 'N' : 'S') : (v >= 0 ? 'E' : 'W');
        return Math.abs(v).toFixed(3) + '°' + hemi;
    }

    function answerViewQuery() {
        var bbox = _rawViewBBox();
        if (!bbox) {
            return '地图还没初始化好，稍等一下再问我。';
        }
        var spanLon = Math.abs(bbox[2] - bbox[0]);
        var spanLat = Math.abs(bbox[3] - bbox[1]);

        if (spanLon > 180 && spanLat > 90) {
            return (
                '你现在看到的是**整个地球**（全球范围，约 360°×180°）。\n\n' +
                '这个范围没法做地形分析 —— 真要算得先把地图放大到目标区域，' +
                '或者直接点明地名，比如「分析贡嘎山的坡度」。'
            ).replace(/\*\*/g, '');
        }

        var centerLon = (bbox[0] + bbox[2]) / 2;
        var centerLat = (bbox[1] + bbox[3]) / 2;
        return (
            '你当前视野的经纬度范围：\n' +
            '· 西 / 南：' + fmtCoord(bbox[0], false) + '，' + fmtCoord(bbox[1], true) + '\n' +
            '· 东 / 北：' + fmtCoord(bbox[2], false) + '，' + fmtCoord(bbox[3], true) + '\n' +
            '· 中心点：' + fmtCoord(centerLon, false) + '，' + fmtCoord(centerLat, true) + '\n' +
            '· 跨度：' + spanLon.toFixed(2) + '° × ' + spanLat.toFixed(2) + '°\n' +
            '· 覆盖面积：约 ' + Math.round(approxAreaKm2(bbox)).toLocaleString('zh-CN') + ' 平方公里\n\n' +
            '想分析这块地方的话，直接说「分析当前视野的坡度」「统计这里的坡度分级」就行。'
        );
    }

    /* ---------------- 地形数据来源 ---------------- */

    /**
     * 判断视野是不是大到没法算。
     * 视野过大时**不要把范围递给后端** —— 规划器有"未提地点就填一个默认范围"的规则，
     * 它会自己编一块地方真的算起来，用户看到的就是"地图自己跳走了 + 算了一堆没人要的东西"。
     */
    function isViewTooLarge(bbox) {
        if (!bbox) return false;
        return Math.abs(bbox[2] - bbox[0]) > MAX_VIEW_SPAN_DEG ||
               Math.abs(bbox[3] - bbox[1]) > MAX_VIEW_SPAN_DEG;
    }

    // 功能词/指示词：把这些从问句里去掉后如果还剩有意义的词，就认为用户点了地名
    var FUNCTION_WORDS = [
        '帮我', '请', '我要', '我想', '想要', '给我', '一下', '看看', '进行', '做',
        '算', '计算', '分析', '统计', '判断', '生成', '获取', '下载', '评估', '处理',
        '当前', '现在', '此时', '这片', '这里', '这个', '这块', '该', '这片区域', '当前视野',
        '视野', '范围', '区域', '地方', '地形', '地貌', '高程', '海拔', '数据',
        '坡度', '坡向', '曲率', '分类', '类型', '路径', '路线', '通行', '代价',
        '面积', '占比', '比例', '多少', '多大', '以下', '以上', '之内', '高于', '低于',
        '先', '再', '然后', '并且', '以及', '和', '与', '的', '是', '在', '用', '以',
        '最', '更', '比较', '结果', '情况', '怎么样', '如何', '怎么', '什么', '哪里', '哪个',
        '能', '可以', '会', '要', '把', '给', '对', '为', '从', '到', '条', '个', '项',
    ];

    function hasPlaceName(text) {
        var q = _squeeze(text);
        if (!q) return false;
        for (var i = 0; i < FUNCTION_WORDS.length; i++) {
            q = q.split(FUNCTION_WORDS[i]).join('');
        }
        // 去掉功能词后还剩 2 个以上汉字 → 大概率是地名
        return q.replace(/[a-zA-Z0-9]/g, '').length >= 2;
    }

    /* ---------------- Cesium 自带地形采样 ---------------- */

    // 采样网格边长。128×128 = 16384 个点，够表达一个研究区的地形起伏，
    // 又不至于把 Cesium 的瓦片请求压垮（实测分批后秒级完成）。
    var TERRAIN_GRID_N = 128;
    var SAMPLE_BATCH = 2048;

    /**
     * 保证 viewer 上挂的是真地形。
     *
     * 主页面里 `terrainProvider: Cesium.createWorldTerrain(...)` 那行是**注释掉**的，
     * 所以默认是 EllipsoidTerrainProvider —— 光滑椭球，采出来的高程全是 0。
     * 这一步在需要采样时把它换成 Cesium World Terrain。
     */
    function ensureTerrainProvider() {
        var viewer = global.viewer;
        if (!viewer || typeof Cesium === 'undefined') {
            return Promise.resolve({ ok: false, reason: '地图未就绪' });
        }
        var tp = viewer.terrainProvider;
        var isEllipsoid = tp && Cesium.EllipsoidTerrainProvider &&
            tp instanceof Cesium.EllipsoidTerrainProvider;
        if (tp && !isEllipsoid) {
            return Promise.resolve({ ok: true, swapped: false });
        }

        function apply(provider) {
            viewer.terrainProvider = provider;
            return { ok: true, swapped: true };
        }
        function fail(err) {
            return { ok: false, reason: '加载 Cesium 世界地形失败：' + (err && err.message ? err.message : err) };
        }

        var opts = { requestWaterMask: false, requestVertexNormals: true };

        // ⚠ 本项目用的 Cesium 1.93 只有**同步版** createWorldTerrain，
        //   createWorldTerrainAsync 是后续版本才有的（实测 1.93 下为 undefined）。
        //   两个分支都留着，将来升级 Cesium 也不会悄悄失效。
        if (typeof Cesium.createWorldTerrainAsync === 'function') {
            return Cesium.createWorldTerrainAsync(opts).then(apply).catch(fail);
        }
        if (typeof Cesium.createWorldTerrain === 'function') {
            try {
                return Promise.resolve(apply(Cesium.createWorldTerrain(opts)));
            } catch (e) {
                return Promise.resolve(fail(e));
            }
        }
        return Promise.resolve({ ok: false, reason: '当前 Cesium 版本不支持创建世界地形' });
    }

    /**
     * 在 bbox 上按 N×N 采样地形高程。
     * 返回的行序是**从北到南**（第 0 行最北），与后端 GeoTIFF 的行序约定一致。
     *
     * @param {number[]} bbox [minLon, minLat, maxLon, maxLat]
     * @param {number} n 网格边长
     * @param {function(number)} onProgress 0~1
     */
    function sampleTerrainGrid(bbox, n, onProgress) {
        var viewer = global.viewer;
        var positions = [];
        for (var j = 0; j < n; j++) {
            // 纬度从北往南走
            var lat = bbox[3] + (bbox[1] - bbox[3]) * (j / (n - 1));
            for (var i = 0; i < n; i++) {
                var lon = bbox[0] + (bbox[2] - bbox[0]) * (i / (n - 1));
                positions.push(Cesium.Cartographic.fromDegrees(lon, lat));
            }
        }

        var heights = new Array(positions.length);
        var provider = viewer.terrainProvider;

        function runChunk(start) {
            if (start >= positions.length) return Promise.resolve();
            var chunk = positions.slice(start, start + SAMPLE_BATCH);
            return Cesium.sampleTerrainMostDetailed(provider, chunk).then(function (updated) {
                for (var k = 0; k < updated.length; k++) {
                    var h = updated[k] && updated[k].height;
                    heights[start + k] = (typeof h === 'number' && isFinite(h)) ? h : null;
                }
                if (onProgress) onProgress(Math.min(1, (start + chunk.length) / positions.length));
                return runChunk(start + chunk.length);
            });
        }

        return runChunk(0).then(function () {
            var rows = [];
            for (var r = 0; r < n; r++) {
                rows.push(heights.slice(r * n, (r + 1) * n));
            }
            return rows;
        });
    }

    /** 采样并返回可发送的 dem_grid 载荷；失败返回 null（调用方据此降级） */
    function prepareDemGrid(bbox, onProgress) {
        if (!bbox) return Promise.resolve(null);
        return ensureTerrainProvider().then(function (st) {
            if (!st.ok) {
                console.warn('[AgentPanel] 无法使用 Cesium 地形：', st.reason);
                return null;
            }
            if (st.swapped && onProgress) onProgress(-1); // 首次换地形会稍慢
            return sampleTerrainGrid(bbox, TERRAIN_GRID_N, onProgress)
                .then(function (heights) { return { bbox: bbox, heights: heights }; })
                .catch(function (err) {
                    console.warn('[AgentPanel] 地形采样失败：', err);
                    return null;
                });
        });
    }

    /* ---------------- 请求 ---------------- */

    async function send(text) {
        if (state.busy || !text || !text.trim()) return;
        text = String(text).trim();

        addUserMessage(text);

        // ① 元问题：「我现在看的是哪一块」——
        //    这类问题问的是视图本身，本地直接回答，不调大模型、不做任何计算。
        if (isViewQuery(text)) {
            var vw = addBotShell();
            vw.querySelector('.bubble').textContent = answerViewQuery();
            scrollToBottom();
            return;
        }

        // ② 视野过大且没有点明地名 —— 拦下来，别让规划器自己编一块地方去算。
        //    以前这种情况会走到「未提及地点就填默认范围」的规则上，模型编一块地方
        //    真的跑一遍计算，用户看到的就是"算了一堆我没问的东西"。
        var rawBox = state.useViewBBox ? _rawViewBBox() : null;
        if (state.useViewBBox && isViewTooLarge(rawBox) && !hasPlaceName(text)) {
            var bw = addBotShell();
            const spanTxt = rawBox
                ? (Math.abs(rawBox[2] - rawBox[0]).toFixed(0) + '° × ' + Math.abs(rawBox[3] - rawBox[1]).toFixed(0) + '°')
                : '全球';
            bw.querySelector('.bubble').textContent =
                '当前地图视野是 ' + spanTxt + '（全球范围），太大，没法直接算地形。\n\n' +
                '两个办法任选其一：\n' +
                '· 用滚轮把地图放大到你要看的区域，再说一次；\n' +
                '· 直接点明地名，比如「分析贡嘎山的坡度」「统计珠峰坡度在 15 度以下的比例」。';
            scrollToBottom();
            return;
        }

        state.busy = true;
        setBusy(true);

        var wrap = addBotShell();
        var waiting = addWaiting(wrap);

        var bboxForRequest = currentViewBBox();
        var demGrid = null;

        // 有明确范围就先采一份 Cesium 地形。用户没自带 DEM 时，
        // 后端拿它当数据源，而不是退回那张"和实地毫无关系"的合成曲面。
        if (bboxForRequest) {
            waiting.textContent = '正在从 Cesium 地形采样高程…';
            try {
                demGrid = await prepareDemGrid(bboxForRequest, function (p) {
                    if (p < 0) {
                        waiting.textContent = '正在启用 Cesium 世界地形（首次稍慢）…';
                    } else {
                        waiting.textContent = '正在采样地形高程… ' + Math.round(p * 100) + '%';
                    }
                });
            } catch (e) {
                demGrid = null;
            }
            waiting.textContent = demGrid
                ? '地形已就绪，正在规划…'
                : '未取到地形数据，本次将使用默认数据源…';
        }

        var payload = {
            query: text,
            bbox: bboxForRequest,
            session_id: 'web-panel',
            dem_grid: demGrid
        };

        try {
            var resp = await fetch(API_BASE + '/api/v1/agent/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            var data = await resp.json();

            waiting.remove();
            if (data.error) {
                wrap.className = 'agentp-msg agentp-msg-error';
                wrap.querySelector('.bubble').textContent = data.answer || ('出错了：' + data.error);
            } else {
                wrap.querySelector('.bubble').textContent = data.answer || '（没有生成回答）';
                addDataSourceTag(wrap, data.dem_source);
                addSteps(wrap, data.steps || []);
                addResults(wrap, data.steps || []);
                scrollToBottom();
            }
        } catch (err) {
            waiting.remove();
            wrap.className = 'agentp-msg agentp-msg-error';
            wrap.querySelector('.bubble').textContent =
                '连不上本地分析服务（' + API_BASE + '）。\n' +
                '请先运行 backend\\run_backend.ps1 启动后端，再试一次。\n' +
                '错误信息：' + err.message;
            scrollToBottom();
        } finally {
            state.busy = false;
            setBusy(false);
        }
    }

    /** 如实标出这次分析用的高程是哪来的 —— 用户有权知道数字建立在什么数据上 */
    function addDataSourceTag(wrap, demSource) {
        if (!demSource) return;
        var text = '';
        var cls = '';
        if (demSource === 'cesium_terrain') {
            text = '数据来源：Cesium 世界地形（由当前视野实时采样）';
        } else if (demSource === 'real_dem') {
            text = '数据来源：本地 DEM 文件';
        } else if (demSource === 'synthetic') {
            text = '数据来源：合成地形（仅用于流程演示，不能作为真实地理结论）';
            cls = 'warn';
        } else {
            return;
        }
        var tag = document.createElement('div');
        tag.className = 'agentp-source ' + cls;
        tag.textContent = text;
        wrap.appendChild(tag);
    }

    function setBusy(busy) {
        var btn = document.getElementById('agentpSendBtn');
        if (btn) {
            btn.disabled = busy;
            btn.textContent = busy ? '…' : '发送';
        }
        if (state.inputEl) state.inputEl.disabled = busy;
    }

    /* ---------------- 探活 ---------------- */

    function probe() {
        fetch(API_BASE + '/api/v1/agent/health', { method: 'GET' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var tip = document.getElementById('agentpHealthTip');
                if (d.ready) {
                    if (tip) {
                        tip.textContent = '本地模型就绪（' + (d.backend || '') + '）';
                        tip.style.color = '#5fd08a';
                    }
                    syncNavDot('is-ready');
                } else {
                    if (tip) {
                        tip.textContent = '模型未加载：' + (d.error || '未知原因');
                        tip.style.color = '#f0b35f';
                    }
                    syncNavDot('is-down');
                }
            })
            .catch(function () {
                var tip = document.getElementById('agentpHealthTip');
                if (tip) {
                    tip.textContent = '后端未启动，请先运行 backend\\run_backend.ps1';
                    tip.style.color = '#f08a8a';
                }
                syncNavDot('is-down');
            });
    }

    /* ---------------- 初始化 ---------------- */

    function buildUiOnce() {
        if (state.win) return state.win;
        var win = document.getElementById(WIN_ID);
        if (!win) return null;
        state.win = win;
        state.chatEl = document.getElementById('agentpChat');
        state.inputEl = document.getElementById('agentpInput');
        state.ctxValueEl = document.getElementById('agentpCtxValue');

        // 视野范围开关
        var viewBtn = document.getElementById('agentpUseViewBtn');
        if (viewBtn) {
            viewBtn.classList.add('on');
            viewBtn.addEventListener('click', function () {
                state.useViewBBox = !state.useViewBBox;
                viewBtn.classList.toggle('on', state.useViewBBox);
                refreshCtxLabel();
            });
        }

        // 发送
        var sendBtn = document.getElementById('agentpSendBtn');
        if (sendBtn) sendBtn.addEventListener('click', function () { send(state.inputEl.value); });
        if (state.inputEl) {
            state.inputEl.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    send(state.inputEl.value);
                    state.inputEl.value = '';
                }
            });
        }

        // 快捷问法
        var quickBox = document.getElementById('agentpQuick');
        if (quickBox) {
            quickBox.addEventListener('click', function (e) {
                if (e.target.tagName !== 'BUTTON') return;
                send(e.target.textContent);
            });
        }

        if (global.WindowMgr) global.WindowMgr.register(WIN_ID, win);
        refreshCtxLabel();
        syncFloatBtn();
        watchCamera();
        if (global.AgentResultView && state.chatEl) {
            global.AgentResultView.resizeCharts(state.chatEl);
        }
        probe();
    }

    /** 跟着相机走：视野变了就刷新范围标签（面板打开时才刷，避免白算） */
    function watchCamera() {
        if (state._camWatching) return;
        if (!global.viewer || !global.viewer.camera) {
            setTimeout(watchCamera, 800);
            return;
        }
        state._camWatching = true;
        var timer = null;
        global.viewer.camera.changed.addEventListener(function () {
            if (timer) clearTimeout(timer);
            timer = setTimeout(function () {
                if (state.win && state.win.style.display !== 'none') refreshCtxLabel();
            }, 600);
        });
    }

    /** 对外：打开面板（供顶部菜单/侧栏按钮调用） */
    function open() {
        var win = buildUiOnce();
        if (!win) return;
        if (global.WindowMgr) {
            global.WindowMgr.open(WIN_ID);
        } else {
            win.style.display = 'block';
        }
        refreshCtxLabel();
        if (global.AgentResultView && state.chatEl) {
            global.AgentResultView.resizeCharts(state.chatEl);
        }
        probe();
    }

    /**
     * 面板当前是否可见。
     *
     * ⚠ 不能只看 `el.style.display` —— 窗口初始时根本没有内联 style，
     * 可见性来自 CSS 的 `.functionWin { display: none }`，
     * 此时 `style.display` 是空串，用 `!== 'none'` 判断会误判成"已打开"，
     * 导致第一次点击悬浮按钮反而把面板关掉（实测踩过）。
     */
    function isWinOpen() {
        if (!state.win) return false;
        var inline = state.win.style.display;
        if (inline) return inline !== 'none';
        return getComputedStyle(state.win).display !== 'none';
    }

    /** 面板开关状态 → 悬浮按钮的明暗（真实状态，不是装饰） */
    function syncFloatBtn() {
        var btn = document.getElementById('agentFloatBtn');
        if (!btn || !state.win) return;
        btn.classList.toggle('is-active', isWinOpen());
    }

    /** 探活结果 → 顶部菜单那个状态点 */
    function syncNavDot(cls) {
        var dot = document.querySelector('#agentChat .agent-nav-dot');
        if (!dot) return;
        dot.classList.remove('is-ready', 'is-down');
        if (cls) dot.classList.add(cls);
    }

    function toggle() {
        if (!state.win) buildUiOnce();
        if (!state.win) return;
        if (isWinOpen()) {
            state.win.style.display = 'none';
        } else {
            open();
        }
        syncFloatBtn();
    }

    /** 绑定各种入口（菜单项、悬浮按钮、面板内的控件） */
    function bindEntries() {
        if (state._entriesBound) return;
        state._entriesBound = true;
        if (!buildUiOnce()) return;

        // 悬浮常驻入口
        var floatBtn = document.getElementById('agentFloatBtn');
        if (floatBtn) {
            floatBtn.addEventListener('click', function (e) {
                e.preventDefault();
                toggle();
            });
        }

        // 顶部独立菜单入口 —— 自己绑定，不去动 eventBindInit.js（那里逻辑多，风险高）
        var menu = document.getElementById('agentChat');
        if (menu) {
            menu.addEventListener('click', function (e) {
                e.preventDefault();
                toggle();
            });
        }

        // 用户可能通过窗口自带的关闭/折叠按钮改变显示状态，
        // 用 MutationObserver 兜住，保证悬浮按钮的明暗始终与面板一致。
        var mo = new MutationObserver(function () { syncFloatBtn(); });
        mo.observe(state.win, { attributes: true, attributeFilter: ['style'] });

        probe();
    }

    function init() {
        if (buildUiOnce()) {
            bindEntries();
            return;
        }
        // 本页的 `</body>` 位置靠前（在第 131 行），导航栏、地图容器、面板 DOM
        // 等主体内容其实都排在它**后面**，靠浏览器容错渲染。
        // 于是这里存在一个真实时序问题：defer 脚本执行时，后面的元素可能还没进 DOM。
        // 所以初始化要能重试，而不是一锤子买卖。
        document.addEventListener('DOMContentLoaded', bindEntries);
        var tries = 0;
        var timer = setInterval(function () {
            if (buildUiOnce()) {
                bindEntries();
                clearInterval(timer);
            } else if (++tries > 40) {
                clearInterval(timer);
                console.warn('[AgentPanel] 等待面板 DOM 超时，未完成初始化');
            }
        }, 250);
    }

    init();

    global.AgentPanel = {
        open: open,
        send: send,
        apiBase: API_BASE
    };
})(window);
