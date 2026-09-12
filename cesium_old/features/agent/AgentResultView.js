/* AgentResultView.js
 *
 * 把一步工具调用的结构化结果渲染成「表格 / 图表 / 指标卡」。
 *
 * 为什么需要它：后端每个工具其实都返回了很完整的数据
 * （zonal_statistics 给出每一级坡度多大面积、占多少比例；
 *  classify_* 给出 8 类地貌各自的像元数与标准配色；plan_route 给出里程、爬升、绕行系数），
 * 但以前这些字段在回传途中被丢掉了，前端只拿到一句总结文字。
 * 这个模块负责把它们变成肉眼可读、且能落到地图上的东西。
 *
 * 约定：只读渲染，不持有状态；需要回调的操作（叠加图层、定位）由调用方传入。
 */
(function (global) {
    'use strict';

    var API_BASE = (global.__AGENT_API_BASE__) || 'http://127.0.0.1:8000';

    var METRIC_UNIT_CN = {
        degree: '°',
        m: 'm',
        cost: '',
        ratio: '',
        '1/m': '1/m'
    };

    function fmt(n, digits) {
        if (n === null || n === undefined || (typeof n === 'number' && !isFinite(n))) return '—';
        var d = digits === undefined ? 2 : digits;
        if (Math.abs(n) >= 10000) return n.toLocaleString('zh-CN', { maximumFractionDigits: d });
        return String(Number(Number(n).toFixed(d)));
    }

    function pct(r) {
        if (r === null || r === undefined) return '—';
        return (r * 100).toFixed(1) + '%';
    }

    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html !== undefined) e.innerHTML = html;
        return e;
    }

    /** 一组指标卡 [ {k:名称, v:值, u:单位} ]；v 可以是数字，也可以是已经格式化好的字符串 */
    function metricsBox(items) {
        var box = el('div', 'agentp-metrics');
        items.forEach(function (it) {
            var card = el('div', 'agentp-metric');
            card.appendChild(el('div', 'k', it.k));
            // 数字走 fmt 保留位数；字符串（如 "128×128"）原样显示 ——
            // 曾经这里对字符串也调用 fmt，结果渲染成 NaN。
            var text = (typeof it.v === 'number')
                ? fmt(it.v, it.d === undefined ? 2 : it.d)
                : String(it.v === undefined || it.v === null ? '—' : it.v);
            var v = el('div', 'v', text);
            if (it.u) v.appendChild(el('span', 'u', it.u));
            card.appendChild(v);
            box.appendChild(card);
        });
        return box;
    }

    function tableBox(headers, rows, firstColIsHtml) {
        var table = el('table', 'agentp-table');
        var thead = el('thead');
        var trh = el('tr');
        headers.forEach(function (h) { trh.appendChild(el('th', '', h)); });
        thead.appendChild(trh);
        table.appendChild(thead);

        var tbody = el('tbody');
        rows.forEach(function (r) {
            var tr = el('tr');
            r.forEach(function (cell, i) {
                if (i === 0 && firstColIsHtml) {
                    tr.appendChild(el('td', '', cell));
                } else {
                    tr.appendChild(el('td', '', String(cell)));
                }
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        return table;
    }

    var _chartSeq = 0;

    /** 建一个 echarts 容器（延迟到插入 DOM 后再 init，否则拿不到宽高） */
    function chartBox(buildOption) {
        var id = 'agentp_chart_' + (++_chartSeq) + '_' + Date.now();
        var div = el('div', 'agentp-chart');
        div.id = id;
        div.__buildOption = buildOption;
        return div;
    }

    /** 面板插入文档后统一初始化图表 */
    function mountCharts(root) {
        if (!global.echarts) {
            console.warn('[AgentResultView] echarts 未加载，跳过图表渲染');
            return;
        }
        var nodes = root.querySelectorAll('.agentp-chart');
        for (var i = 0; i < nodes.length; i++) {
            (function (node) {
                if (node.__chartMounted || !node.__buildOption) return;
                node.__chartMounted = true;
                var chart = global.echarts.init(node);
                chart.setOption(node.__buildOption());
                node.__chart = chart;
            })(nodes[i]);
        }
    }

    function resizeCharts(root) {
        var nodes = root.querySelectorAll('.agentp-chart');
        for (var i = 0; i < nodes.length; i++) {
            if (nodes[i].__chart) {
                try { nodes[i].__chart.resize(); } catch (e) { /* ignore */ }
            }
        }
    }

    /* 统一的深色主题字色 */
    var AXIS_STYLE = {
        axisLine: { lineStyle: { color: 'rgba(141,190,224,0.45)' } },
        axisLabel: { color: '#a9c8e4', fontSize: 11 },
        splitLine: { lineStyle: { color: 'rgba(141,190,224,0.12)' } }
    };

    function baseOption() {
        return {
            backgroundColor: 'transparent',
            tooltip: {
                backgroundColor: 'rgba(5,16,33,0.92)',
                borderColor: '#8dbee0',
                textStyle: { color: '#e3f1fd', fontSize: 12 }
            },
            legend: { textStyle: { color: '#a9c8e4', fontSize: 11 } },
            grid: { left: 46, right: 14, top: 24, bottom: 34 }
        };
    }

    /* ============ zonal_statistics：分级面积表格 + 柱状图 ============ */
    function renderZonal(data) {
        var frag = document.createDocumentFragment();
        var unit = METRIC_UNIT_CN[data.unit] || data.unit || '';

        var items = [
            { k: '总面积', v: data.total_area_km2, u: 'km²', d: 1 },
            { k: '有效像元', v: data.valid_ratio ? pct(data.valid_ratio) : '—', d: 0 }
        ];
        var ov = data.overall || {};
        if (ov.mean !== undefined) items.push({ k: '均值', v: ov.mean, u: unit, d: 2 });
        if (ov.max !== undefined) items.push({ k: '最大值', v: ov.max, u: unit, d: 2 });
        frag.appendChild(metricsBox(items));

        var classes = data.classes || [];
        if (!classes.length) return frag;

        // 表格
        var rows = classes.map(function (c) {
            return [
                c.label,
                c.range ? (c.range[0] + ' ~ ' + c.range[1]) : '—',
                fmt(c.area_km2, 2),
                pct(c.ratio)
            ];
        });
        frag.appendChild(tableBox(
            ['分级', '区间' + (unit ? '（' + unit + '）' : ''), '面积 km²', '占比'],
            rows
        ));

        // 柱状图
        frag.appendChild(chartBox(function () {
            var opt = baseOption();
            opt.tooltip.trigger = 'axis';
            opt.tooltip.axisPointer = { type: 'shadow' };
            opt.xAxis = Object.assign({ type: 'category', data: classes.map(function (c) { return c.label; }) }, AXIS_STYLE);
            opt.yAxis = Object.assign({ type: 'value', name: '面积 km²', nameTextStyle: { color: '#8dbee0', fontSize: 11 } }, AXIS_STYLE);
            opt.series = [{
                name: '面积',
                type: 'bar',
                barMaxWidth: 34,
                data: classes.map(function (c) { return c.area_km2; }),
                itemStyle: {
                    color: new global.echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: '#8dbee0' },
                        { offset: 1, color: '#195185' }
                    ]),
                    borderRadius: [3, 3, 0, 0]
                }
            }];
            return opt;
        }));

        return frag;
    }

    /* ============ classify_*：8 类地貌构成饼图 + 图例 ============ */
    function renderClassify(data) {
        var frag = document.createDocumentFragment();
        var dist = data.distribution || {};
        var legend = data.legend || [];
        var counts = dist.counts || {};
        var total = dist.total_cells || 0;

        // 只显示真实出现的类别
        var pieData = [];
        legend.forEach(function (lg) {
            var label = lg.label_cn || lg.name;
            var c = counts[label];
            if (!c) return;
            pieData.push({ name: label, value: c, itemStyle: { color: lg.color } });
        });

        var items = [];
        if (dist.dominant_class) items.push({ k: '主导地类', v: dist.dominant_class, d: 0 });
        if (dist.dominant_ratio !== undefined) items.push({ k: '主导占比', v: pct(dist.dominant_ratio), d: 0 });
        if (dist.distinct_classes !== undefined) items.push({ k: '类别数', v: dist.distinct_classes, d: 0 });
        if (data.mean_confidence !== undefined) items.push({ k: '平均置信度', v: pct(data.mean_confidence), d: 0 });
        if (data.infer_ms !== undefined) items.push({ k: '推理耗时', v: data.infer_ms, u: 'ms', d: 1 });
        if (items.length) frag.appendChild(metricsBox(items));

        if (pieData.length) {
            frag.appendChild(chartBox(function () {
                var opt = baseOption();
                opt.tooltip.trigger = 'item';
                opt.tooltip.formatter = '{b}: {c} 像元 ({d}%)';
                opt.legend = {
                    orient: 'vertical',
                    right: 4,
                    top: 'middle',
                    textStyle: { color: '#a9c8e4', fontSize: 11 }
                };
                opt.series = [{
                    type: 'pie',
                    radius: ['34%', '64%'],
                    center: ['36%', '52%'],
                    avoidLabelOverlap: true,
                    label: { show: false },
                    data: pieData
                }];
                return opt;
            }));
        }

        // 图例色卡（含完整 8 类，未出现的标 0）
        if (legend.length) {
            var lgBox = el('div', 'agentp-legend');
            legend.forEach(function (lg) {
                var label = lg.label_cn || lg.name;
                var c = counts[label] || 0;
                var r = total ? (c / total * 100).toFixed(1) : '0.0';
                var item = el('div', 'item');
                item.appendChild(el('span', 'swatch')).style.background = lg.color;
                item.appendChild(document.createTextNode(label + ' ' + r + '%'));
                lgBox.appendChild(item);
            });
            frag.appendChild(lgBox);
        }

        return frag;
    }

    /* ============ plan_route：路线指标卡 ============ */
    function renderPath(data) {
        var frag = document.createDocumentFragment();
        var items = [];
        if (data.distance_m !== undefined) items.push({ k: '路径长度', v: (data.distance_m / 1000).toFixed(2), u: 'km', d: 2 });
        if (data.straight_line_m !== undefined) items.push({ k: '直线距离', v: (data.straight_line_m / 1000).toFixed(2), u: 'km', d: 2 });
        if (data.detour_ratio !== undefined) items.push({ k: '绕行系数', v: data.detour_ratio, d: 2 });
        if (data.ascent_m !== undefined) items.push({ k: '累计爬升', v: data.ascent_m, u: 'm', d: 0 });
        if (data.descent_m !== undefined) items.push({ k: '累计下降', v: data.descent_m, u: 'm', d: 0 });
        if (data.max_slope_deg !== undefined) items.push({ k: '最大坡度', v: data.max_slope_deg, u: '°', d: 1 });
        if (data.mean_slope_deg !== undefined) items.push({ k: '平均坡度', v: data.mean_slope_deg, u: '°', d: 1 });
        if (data.node_count !== undefined) items.push({ k: '路径节点', v: data.node_count, d: 0 });
        frag.appendChild(metricsBox(items));

        if (data.reachable === false) {
            frag.appendChild(el('div', 'agentp-hint',
                '⚠ 起终点在代价栅格上不可达，当前返回的是直线近似，不能当作真实路径使用。'));
        }
        return frag;
    }

    /* ============ compute_* ：栅格概览 ============ */
    function renderGrid(data) {
        var frag = document.createDocumentFragment();
        var st = data.statistics || data.min_cost_dir_stats || {};
        var unit = METRIC_UNIT_CN[st.unit] || st.unit || '';

        var items = [];
        if (data.cell_size_m !== undefined) items.push({ k: '栅格边长', v: data.cell_size_m, u: 'm', d: 1 });
        if (data.resolution !== undefined) items.push({ k: '分辨率', v: data.resolution + '×' + data.resolution, d: 0 });
        if (st.mean !== undefined) items.push({ k: '均值', v: st.mean, u: unit, d: 2 });
        if (st.min !== undefined) items.push({ k: '最小', v: st.min, u: unit, d: 2 });
        if (st.max !== undefined) items.push({ k: '最大', v: st.max, u: unit, d: 2 });
        if (st.std !== undefined) items.push({ k: '标准差', v: st.std, u: unit, d: 2 });
        if (st.p50 !== undefined) items.push({ k: '中位数', v: st.p50, u: unit, d: 2 });
        frag.appendChild(metricsBox(items));

        var warns = data.warnings || [];
        var alreadyWarnedSynthetic = warns.some(function (w) {
            return String(w).indexOf('合成地形') >= 0;
        });
        if (data.dem_source === 'synthetic' && !alreadyWarnedSynthetic) {
            frag.appendChild(el('div', 'agentp-hint',
                '⚠ 当前使用合成地形，结果仅供流程验证。想要真实数据，问我「下载这片区域的 SRTM 数据」。'));
        }
        return frag;
    }

    /* ============ DEM 数据类：简要信息 ============ */
    function renderDem(data) {
        var frag = document.createDocumentFragment();
        var items = [];
        if (data.resolution !== undefined) items.push({ k: '分辨率', v: data.resolution + '×' + data.resolution, d: 0 });
        if (data.cell_size_m !== undefined) items.push({ k: '栅格边长', v: data.cell_size_m, u: 'm', d: 1 });
        if (data.bounds) {
            var b = data.bounds;
            var arr = Array.isArray(b) ? b : [b.west, b.south, b.east, b.north];
            items.push({ k: '范围', v: arr[0].toFixed(2) + ', ' + arr[1].toFixed(2), d: 0 });
        }
        frag.appendChild(metricsBox(items));

        if (data.path || data.dem_path) {
            frag.appendChild(el('div', 'agentp-hint', '数据文件：' + (data.path || data.dem_path)));
        }
        return frag;
    }

    var TOOL_LABEL = {
        compute_slope: '坡度',
        compute_aspect: '坡向',
        compute_curvature: '曲率',
        compute_cost_surface: '通行代价',
        plan_route: '路径规划',
        zonal_statistics: '分区统计',
        classify_terrain_rules: '地貌分类（规则法）',
        classify_geomorphons: '地貌分类（Geomorphons）',
        classify_terrain_onnx: '地貌分类（深度学习）',
        download_srtm: 'DEM 下载',
        get_dem_metadata: 'DEM 元信息'
    };

    /**
     * 渲染一步结果。
     * @param {Object} step  AgentChatStep：{tool, intent, success, data, artifact}
     * @param {Object} hooks {onOverlay(view, artifact), onLocate(view, bbox)}
     * @returns {HTMLElement|null}
     */
    function renderStep(step, hooks) {
        var data = step && step.data;
        if (!data || !Object.keys(data).length || !step.success) return null;

        var tool = step.tool || '';
        var box = el('div', 'agentp-result');

        var head = el('div', 'r-head');
        head.appendChild(el('span', 'r-title', TOOL_LABEL[tool] || tool));

        // 叠加到地图
        var art = step.artifact || data.artifact;
        var fmtName = art && art.format;
        if (art && art.url && (fmtName === 'geojson' || fmtName === 'czml' || fmtName === 'kml')) {
            var overlayBtn = el('button', 'agentp-btn primary', '叠加到地图');
            overlayBtn.addEventListener('click', function () {
                overlayBtn.disabled = true;
                overlayBtn.textContent = '加载中…';
                var p = hooks.onOverlay(art);
                Promise.resolve(p).then(function (ok) {
                    overlayBtn.textContent = ok ? '已叠加 ✓' : '加载失败';
                    overlayBtn.disabled = !!ok;
                }).catch(function (err) {
                    overlayBtn.textContent = '加载失败';
                    overlayBtn.disabled = false;
                    console.error('[AgentResultView] 叠加图层失败:', err);
                });
            });
            head.appendChild(overlayBtn);
        }

        // 定位
        if (data.bbox && Array.isArray(data.bbox) && data.bbox.length === 4) {
            var locateBtn = el('button', 'agentp-btn', '定位');
            locateBtn.addEventListener('click', function () {
                hooks.onLocate(data.bbox);
            });
            head.appendChild(locateBtn);
        }
        box.appendChild(head);

        var body = el('div', 'r-body');
        var frag = null;
        if (tool === 'zonal_statistics') frag = renderZonal(data);
        else if (tool.indexOf('classify_') === 0) frag = renderClassify(data);
        else if (tool === 'plan_route') frag = renderPath(data);
        else if (tool === 'download_srtm' || tool === 'get_dem_metadata') frag = renderDem(data);
        else if (tool.indexOf('compute_') === 0) frag = renderGrid(data);

        if (frag && frag.childNodes.length) {
            body.appendChild(frag);
        } else if (data.summary) {
            body.appendChild(el('div', '', data.summary));
        }

        // 数据局限提示
        var warns = data.warnings || [];
        if (warns.length) {
            warns.forEach(function (w) {
                body.appendChild(el('div', 'agentp-hint', '⚠ ' + w));
            });
        }

        box.appendChild(body);
        return box;
    }

    global.AgentResultView = {
        renderStep: renderStep,
        mountCharts: mountCharts,
        resizeCharts: resizeCharts,
        apiBase: API_BASE
    };
})(window);
