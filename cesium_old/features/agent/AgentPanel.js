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

    /**
     * 组装给后端的「当前视图」。
     *
     * ⚠ 与 `currentViewBBox()` 的区别：那个是**分析范围**（视野过大时返回 null，
     * 不让后端拿整个地球去算）；这个是**视图事实**，无论多大都如实上报。
     * 模型要靠它回答「这里是什么地方」「跳转到某地」这类问题。
     */
    function buildViewContext() {
        var bbox = _rawViewBBox();
        if (!bbox) return null;
        var spanLon = Math.abs(bbox[2] - bbox[0]);
        var spanLat = Math.abs(bbox[3] - bbox[1]);
        return {
            bbox: bbox,
            center: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
            area_km2: approxAreaKm2(bbox),
            is_global: (spanLon > 180 && spanLat > 90)
        };
    }

    /** 执行后端下发的系统动作（目前只有 flyTo） */
    function runActions(actions) {
        if (!actions || !actions.length) return 0;
        var done = 0;
        actions.forEach(function (a) {
            if (!a || !a.type) return;
            if (a.type === 'flyTo' && a.bbox && a.bbox.length === 4) {
                locateBBox(a.bbox);
                done++;
            }
        });
        return done;
    }

    /* ---------------- 会话标识 ---------------- */

    // 会话 ID 持久化在 localStorage：刷新页面、关掉再打开，上文仍然在。
    // 以前这里是硬编码的 'web-panel' —— 所有会话共用一个 ID，
    // 既没法区分用户，也没法按会话隔离记忆。
    var SESSION_KEY = 'geoagent.session_id';

    function getSessionId() {
        try {
            var id = global.localStorage.getItem(SESSION_KEY);
            if (!id) {
                id = 'web-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
                global.localStorage.setItem(SESSION_KEY, id);
            }
            return id;
        } catch (e) {
            return 'web-panel';
        }
    }

    /** 开一个新会话（旧会话的记忆仍在库里，只是不再被引用） */
    function startNewSession() {
        try {
            global.localStorage.removeItem(SESSION_KEY);
        } catch (e) { /* 隐私模式下 localStorage 可能不可用，忽略 */ }
    }

    /* ---------------- 是否需要地形采样 ---------------- */

    // 与后端 planner.py 的 _FORCE_ANALYSIS_KEYWORDS 保持同源 ——
    // 两边判据必须一致，否则会出现"前端不采、后端偏要算"的错配。
    // 改这里的时候记得同步改后端那份。
    var ANALYSIS_RE = /坡度|坡向|朝向|阴坡|阳坡|曲率|山脊|沟谷|山谷线|地形因子|地形起伏|地貌|地形分类|地形形态|通行|代价栅格|路径|路线|分区统计|面积占比|多少面积|多大面积|陡|好走|能走|爬升|DEM|高程数据|SRTM|分析|计算|统计|评估/i;

    // 明确的地图操作 / 浏览意图
    var NAV_RE = /跳转|跳到|飞往|飞到|定位到|移动到|切换到|导航到|前往|带我|看看|看一下|瞅瞅|游览|去一下|转到/;

    // 概念询问 / 社交 / 能力询问 —— 都不需要地形
    var CONCEPT_RE = /什么是|是什么|什么意思|是什么样|介绍一下|介绍下|为什么|怎么理解|概念|科普|你好|您好|谢谢|再见|你是谁|你能做什么|你有什么|有什么功能|会什么/;

    /**
     * 这一句话需不需要先采一份地形高程？
     *
     * 【为什么必须判】采样是 128×128 = 16384 个点，实测要几分钟。
     * 以前是**无条件采样**，于是「跳转到阿尔卑斯山」这种纯操作请求也要先等采样完
     * 才把请求发出去 —— 用户看到的是"执行了地形分析，几分钟后才跳转"。
     *
     * 判据顺序：先看有没有分析信号（有就一定要地形），再看是不是纯操作/常识（不是就不采），
     * 都不是则**保守采样** —— 多采一次只是慢一点，漏采会让分析落到合成地形上，性质更严重。
     */
    function needsTerrainGrid(text) {
        var t = String(text || '');
        if (ANALYSIS_RE.test(t)) return true;
        if (NAV_RE.test(t)) return false;
        if (CONCEPT_RE.test(t)) return false;
        return true;
    }

    /* ---------------- 请求 ---------------- */

    /** 发一次 Agent 请求（抽出来是为了 need_terrain 回退时能重发一次） */
    function postAgent(payload) {
        return fetch(API_BASE + '/api/v1/agent/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        }).then(function (resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        });
    }

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

        // 【关键修复】只在"这句话确实需要地形"时才采样。
        // 以前是无条件采样（只要视野有范围），于是「跳转到阿尔卑斯山」这种
        // 纯操作请求也要先花几分钟采完地形才把请求发出去 —— 用户实测反馈的
        // "执行了地形分析、几分钟后才跳转"就是这么来的。判据见 needsTerrainGrid。
        if (bboxForRequest && needsTerrainGrid(text)) {
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
        } else if (bboxForRequest) {
            // 不需要地形 —— 直接进意图理解，不再让用户白等
            waiting.textContent = '正在理解你的意图…';
        }

        var payload = {
            query: text,
            bbox: bboxForRequest,
            session_id: getSessionId(),
            dem_grid: demGrid,
            // 视图上下文始终上报（与分析范围分开）——
            // 模型据此回答「这里是什么地方」，也据此理解「跳转到海南省」。
            view_context: buildViewContext()
        };

        try {
            var data = await postAgent(payload);

            // 安全网：后端判为分析任务、但这次没带地形（前端预判偏保守时可能发生）
            // → 补采一份再发一次，用第二次的结果覆盖展示。
            // 宁可偶尔多跑一轮，也不能让分析落到合成地形上给出没有意义的数字。
            if (data.need_terrain && bboxForRequest && !demGrid && !data.error) {
                waiting.textContent = '这次分析需要真实地形，正在采样…';
                try {
                    demGrid = await prepareDemGrid(bboxForRequest, function (p) {
                        if (p >= 0) {
                            waiting.textContent = '正在采样地形高程… ' + Math.round(p * 100) + '%';
                        }
                    });
                } catch (e2) {
                    demGrid = null;
                }
                if (demGrid) {
                    payload.dem_grid = demGrid;
                    waiting.textContent = '地形已就绪，正在重新分析…';
                    data = await postAgent(payload);
                }
            }

            waiting.remove();
            if (data.error) {
                wrap.className = 'agentp-msg agentp-msg-error';
                wrap.querySelector('.bubble').textContent = data.answer || ('出错了：' + data.error);
            } else {
                wrap.querySelector('.bubble').textContent = data.answer || '（没有生成回答）';
                // 记忆先展示 —— 用户要先知道"系统把我的话理解成了什么"，
                // 再去看结果才有意义（理解错了的话结果也不用看了）。
                addMemoryNote(wrap, data.memory_notes, data.session_turns);
                addDataSourceTag(wrap, data.dem_source);
                addSteps(wrap, data.steps || []);
                addResults(wrap, data.steps || []);

                // 模型下发的系统动作（例如「跳转到海南省」）—— 这是用户明确要求的操作，
                // 与早前"自作主张移动地图"是两回事。
                var acted = runActions(data.actions);
                if (acted) {
                    var tip = document.createElement('div');
                    tip.className = 'agentp-source';
                    tip.textContent = '已执行 ' + acted + ' 个地图操作';
                    wrap.appendChild(tip);
                }
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

    /** 往对话区插一条系统提示（不是模型说的话，所以样式不同） */
    function appendSystemNote(text) {
        if (!state.chatEl) return;
        var box = document.createElement('div');
        box.className = 'agentp-memory';
        var head = document.createElement('div');
        head.className = 'agentp-memory-head';
        head.textContent = text;
        box.appendChild(head);
        state.chatEl.appendChild(box);
    }

    /**
     * 展示记忆机制刚刚做了什么。
     *
     * 必须可见：记忆是个"看不见的推断"，用户只有看到"我把『这个地方』理解成了五指山一带"
     * 才知道系统有没有理解错 —— 猜错了要能立刻纠正，否则错得无声无息。
     */
    function addMemoryNote(wrap, notes, turns) {
        if (!notes || !notes.length) return;
        var box = document.createElement('div');
        box.className = 'agentp-memory';

        var head = document.createElement('div');
        head.className = 'agentp-memory-head';
        head.textContent = turns
            ? '结合上文理解（本会话第 ' + Math.max(1, Math.round(turns / 2)) + ' 轮）'
            : '结合上文理解';
        box.appendChild(head);

        notes.forEach(function (n) {
            var line = document.createElement('div');
            line.className = 'agentp-memory-line';
            line.textContent = '· ' + n;
            box.appendChild(line);
        });
        wrap.appendChild(box);
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
                } else {
                    if (tip) {
                        tip.textContent = '模型未加载：' + (d.error || '未知原因');
                        tip.style.color = '#f0b35f';
                    }
                }
            })
            .catch(function () {
                var tip = document.getElementById('agentpHealthTip');
                if (tip) {
                    tip.textContent = '后端未启动，请先运行 backend\\run_backend.ps1';
                    tip.style.color = '#f08a8a';
                }
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

        // 新会话：清空聊天区并换一个 session_id。
        // 旧会话的记忆仍留在库里（换回来还能接着用），只是不再作为上下文引用。
        var newSessBtn = document.getElementById('agentpNewSessionBtn');
        if (newSessBtn) {
            newSessBtn.addEventListener('click', function () {
                if (state.busy) return;
                startNewSession();
                if (state.chatEl) state.chatEl.innerHTML = '';
                appendSystemNote('已开新会话 —— 之前的对话不再作为上下文。');
                scrollToBottom();
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
        syncNavActive();
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

    /** 面板开关状态 → 顶部菜单图标的高亮（真实状态，不是装饰） */
    function syncNavActive() {
        var entry = document.getElementById('agentChat');
        if (!entry || !state.win) return;
        entry.classList.toggle('is-active', isWinOpen());
    }

    function toggle() {
        if (!state.win) buildUiOnce();
        if (!state.win) return;
        if (isWinOpen()) {
            state.win.style.display = 'none';
        } else {
            open();
        }
        syncNavActive();
    }

    /** 绑定各种入口（菜单项、悬浮按钮、面板内的控件） */
    function bindEntries() {
        if (state._entriesBound) return;
        state._entriesBound = true;
        if (!buildUiOnce()) return;

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
        var mo = new MutationObserver(function () { syncNavActive(); });
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
