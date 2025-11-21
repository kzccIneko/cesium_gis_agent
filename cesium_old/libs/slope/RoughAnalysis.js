// 全新文件：根据传入的 pathPoints 计算粗糙度并用 ECharts 绘图
(function (global) {
  'use strict';

  /**
   * RoughAnalysis 构造函数
   * 可以直接 new RoughAnalysis()，所有分析函数都以传入的 pathPoints 为准
   */
  function RoughAnalysis() {
    this._lastResults = null; // 缓存最近一次计算结果
    this.lastRoughness = null;// 保存上一点陡峭度
  }

  /**
   * analyzePathRoughness(pathPoints)
   * - 输入 pathPoints：数组，按顺序（起点 -> 终点），每项期望包含：
   *     - Cartesian3Grid: Cesium.Cartesian3（用于计算距离）
   *     - z: 数值高度（可选，优先使用）
   *     - x,y 可选（不强制）
   * - 返回：[{ distance: 累计距离(m), roughness: 粗糙度, H_mapped: [...], nodeIndex: i }, ...]
   *
   * 说明：实现基于你给出的公式图的工程化版本（用 9 个样点的高度差映射并计算 S，再除以 3*delta）。
   */
  RoughAnalysis.prototype.analyzePathRoughness = function (pathPoints) {
    if (!pathPoints || !Array.isArray(pathPoints) || pathPoints.length === 0) return [];

    // 计算两点笛卡尔距离（米）
    const cartDist = function (a, b) {
      try { return Cesium.Cartesian3.distance(a, b); } catch (e) { return 0; }
    };

    // 估算 delta：用路径相邻点平均距离作为采样间距估计（行驶总距离 / 路径线段数） 
    let sumD = 0, cntD = 0;
    for (let i = 1; i < pathPoints.length; i++) {
      const d = cartDist(pathPoints[i-1].Cartesian3Grid, pathPoints[i].Cartesian3Grid);
      if (Number.isFinite(d) && d > 1e-6) { sumD += d; cntD++; }
    }
    const delta = (cntD > 0) ? (sumD / cntD) : 1.0;

    const results = [];
    let cumulativeDistance = 0;

    // 窗口法构造 9 个样点（中心前后各 4 个点），仅使用 pathPoints 数据
    const WINDOW_HALF = 4;

    for (let i = 0; i < pathPoints.length; i++) {
      const node = pathPoints[i];

      // 累计距离（米）
      if (i > 0) cumulativeDistance += cartDist(pathPoints[i-1].Cartesian3Grid, node.Cartesian3Grid);

      // 中心高度：优先使用 node.z，否则从 Cartesian3Grid 推导
      let centerH = 0;
      if (Number.isFinite(node.z)) {
        centerH = Number(node.z);
      } else if (node.Cartesian3Grid) {
        try {
          const c = Cesium.Cartographic.fromCartesian(node.Cartesian3Grid);
          centerH = Number(c && c.height) || 0;
        } catch (e) { centerH = 0; }
      }

      // 构建伪 3x3 邻域高度 Hvals（长度 9）
      const Hvals = [];
      for (let k = i - WINDOW_HALF; k <= i + WINDOW_HALF; k++) {
        if (k >= 0 && k < pathPoints.length) {
          const pn = pathPoints[k];
          if (Number.isFinite(pn.z)) {
            Hvals.push(Number(pn.z));
          } else if (pn.Cartesian3Grid) {
            try {
              const c = Cesium.Cartographic.fromCartesian(pn.Cartesian3Grid);
              Hvals.push(Number(c && c.height) || centerH);
            } catch (e) { Hvals.push(centerH); }
          } else {
            Hvals.push(centerH);
          }
        } else {
          Hvals.push(centerH);
        }
      }
      while (Hvals.length < 9) Hvals.push(centerH);

      // 计算高度差绝对值并映射到 0..8（用于公式）
      const diffs = Hvals.map(h => Math.abs(h - centerH));
      const maxDiff = Math.max.apply(null, diffs) || 1e-6;
      const H_mapped = diffs.map(d => {
        const v = Math.round((d / maxDiff) * 8);
        return Math.max(0, Math.min(8, v));
      });

      // 计算 S = sum_k ( Hk / (9 - Hk) )
      let S = 0;
      for (let k = 0; k < H_mapped.length; k++) {
        const Hk = H_mapped[k];
        const denom = (9 - Hk) || 1e-6;
        S += Hk / denom;
      }

      // 粗糙度：sigma_hat_n = |S| / (3 * delta)
      const roughness = Math.abs(S) / (3.0 * Math.max(1e-6, delta));
      
      // 单位距离粗糙度变化：sigma_hat_n - sigma_hat_n-1 / delta
      const roughnessRate = Math.abs((roughness - this.lastRoughness) / delta);
      this.lastRoughness = roughness;// 保存当前陡峭度给下一轮用

      results.push({
        distance: cumulativeDistance, // 累计行驶距离（m）
        roughness: roughness,         // 陡峭度（相对无量纲值）
        roughnessRate: roughnessRate,// 陡峭度变化
        H_mapped: H_mapped,           // 调试用映射后 9 值
        nodeIndex: i,
        nodeX: node.x, nodeY: node.y
      });
    }

    this._lastResults = results;
    return results;
  };


  
  /**
   * showMultipleRoughness(indices, pathCollection, pathLines)
   * - 在同一张图上绘制多条路径的“距离 vs 粗糙度”曲线
   * - indices: 数组，pathCollection 中待绘制路径的索引
   * - pathCollection: 嵌套数组，pathCollection[i] 为第 i 条路径的点数组（每点含 Cartesian3Grid 或 z）
   * - pathLines: 路径元信息数组（用于取颜色/name），可选
   */
    RoughAnalysis.prototype.showMultipleRoughness = function (indices, pathCollection, pathLines) {
        if (!Array.isArray(indices) || indices.length === 0) return alert('请先选择要显示的路径');
        if (!Array.isArray(pathCollection) || pathCollection.length === 0) return alert('没有路径数据可用');

        // 准备图表容器（与单条曲线逻辑一致）
        let container = document.getElementById('roughnessChartContainer');
        if (!container) {
            //   const panel = document.createElement('div');
            //   panel.id = 'roughnessChartPanel';
            //   panel.style.position = 'absolute';
            //   panel.style.right = '12px';
            //   panel.style.top = '120px';
            //   panel.style.width = '720px';
            //   panel.style.height = '420px';
            //   panel.style.background = '#fff';
            //   panel.style.border = '1px solid #ccc';
            //   panel.style.zIndex = 99999;
            //   panel.style.boxShadow = '0 2px 12px rgba(0,0,0,0.3)';
            //   panel.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px;border-bottom:1px solid #eee;">' +
            //                     '<div style="font-weight:600">陡峭度曲线 (距离 vs 陡峭度) — 多路径</div>' +
            //                     '<div><button id="closeRoughChartBtn">关闭</button></div></div>' +
            //                     '<div id="roughnessChartContainer" style="width:100%;height:calc(100% - 40px);"></div>';
            //   document.body.appendChild(panel);
            //   container = document.getElementById('roughnessChartContainer');
            //   document.getElementById('closeRoughChartBtn').onclick = function () { panel.remove(); };
            const panel = document.createElement('div');
            panel.id = 'roughnessChartPanel';
            panel.style.position = 'absolute';
            panel.style.left = 'calc(50% - 360px)';
            panel.style.top = '120px';
            panel.style.width = '720px';
            panel.style.height = '420px';
            panel.style.background = '#fff';
            panel.style.border = '1px solid #ccc';
            panel.style.zIndex = 99999;
            panel.style.boxShadow = '0 2px 12px rgba(0,0,0,0.3)';
            panel.style.resize = 'both';
            panel.style.overflow = 'hidden';

            panel.innerHTML = ''
            +    '<div id="roughMultiHeader" style="height:40px;display:flex;justify-content:space-between;align-items:center;padding:6px;border-bottom:1px solid #eee;cursor:move;background:#fafafa;">'
            +      '<div style="font-weight:600">陡峭度曲线 (距离 ： 陡峭度) — 多路径</div>'
            +      '<div><button id="closeRoughChartBtn">关闭</button></div>'
            +    '</div>'
            +    '<div id="roughnessChartContainer" style="width:100%;height:calc(100% - 40px);overflow:auto;"></div>';
            document.body.appendChild(panel);
            container = document.getElementById('roughnessChartContainer');
            const closeBtnMulti = document.getElementById('closeRoughChartBtn');
            if (closeBtnMulti) closeBtnMulti.onclick = function () { panel.remove(); };

            // 可拖拽头部
            (function makeDraggable(p, headerId) {
                const header = document.getElementById(headerId);
                if (!header) return;
                header.addEventListener('mousedown', startDrag);
                function startDrag(e) {
                    e.preventDefault();
                    const rect = p.getBoundingClientRect();
                    const offsetX = e.clientX - rect.left;
                    const offsetY = e.clientY - rect.top;
                    function onMove(ev) {
                        p.style.left = Math.max(0, ev.clientX - offsetX) + 'px';
                        p.style.top = Math.max(0, ev.clientY - offsetY) + 'px';
                    }
                    function endDrag() {
                        window.removeEventListener('mousemove', onMove);
                        window.removeEventListener('mouseup', endDrag);
                    }
                    window.addEventListener('mousemove', onMove);
                    window.addEventListener('mouseup', endDrag);
                }
            })(panel, 'roughMultiHeader');
        }

    const series = [];
    const legendNames = [];
    const palette = ['#ff5722','#2196f3','#4caf50','#9c27b0','#ff9800','#03a9f4','#8bc34a','#e91e63','#607d8b'];

    for (let idx of indices) {
      if (!Number.isFinite(idx) || !pathCollection[idx] || pathCollection[idx].length === 0) continue;
      const seq = this.analyzePathRoughness(pathCollection[idx]);
      if (!seq || seq.length === 0) continue;
      const data = seq.map(d => [Number(d.distance.toFixed(2)), Number(d.roughness.toFixed(6))]);

      // 尝试从 pathLines 取颜色
      let color = null;
      try {
        if (Array.isArray(pathLines) && pathLines[idx]) {
          const pl = pathLines[idx];
          if (pl.pathLineColorCss) color = pl.pathLineColorCss;
          else if (pl.colorStr) color = pl.colorStr;
          else if (pl.name && pl.color) color = pl.color;
          else if (pl.polyline && pl.polyline.material && pl.polyline.material.color && pl.polyline.material.color._value) {
            const cc = pl.polyline.material.color._value;
            color = `rgba(${Math.round(cc.red*255)},${Math.round(cc.green*255)},${Math.round(cc.blue*255)},${cc.alpha})`;
          }
        }
      } catch (e) { color = null; }
      if (!color) color = palette[idx % palette.length];

      const name = (pathLines && pathLines[idx] && pathLines[idx].name) ? pathLines[idx].name : `路径 ${idx}`;
      legendNames.push(name);
      series.push({
        name: name,
        type: 'line',
        data: data,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2, color: color },
        itemStyle: { color: color }
      });
    }

    if (series.length === 0) return alert('所选路径无有效陡峭度数据');

    let chart;
    try { chart = echarts.init(container); } catch (e) { return alert('ECharts 未加载'); }
    const option = {
      title: { text: '行驶距离 ： 陡峭度', left: 'center', textStyle: { fontSize: 12 } },
      tooltip: { trigger: 'axis', formatter: params => params.map(p => `${p.seriesName}: 距离 ${p.value[0]} m, 陡峭度 ${p.value[1]}`).join('<br/>') },
      legend: { data: legendNames, top: 30, left: '20%' },
      grid: { left: '8%', right: '6%', top: 60, bottom: '12%' },
      xAxis: { type: 'value', name: '行驶距离 (m)', nameLocation: 'middle', nameGap: 25 },
      yAxis: { type: 'value', name: '陡峭度', nameLocation: 'middle', nameGap: 30 },
      series: series
    };
    chart.setOption(option);
    //window.addEventListener('resize', () => { try { chart.resize(); } catch(e){} });
     // 图表resize处理函数
    function handleChartResize() {
        try {
            // 强制重新计算图表尺寸，让图标尺寸适配窗口大小
            chart.resize({
                width: container.clientWidth,
                height: container.clientHeight
            });
        } catch (e) {
            console.warn('图表resize失败:', e);
        }
    }
    
    // 监听窗口resize事件
    window.addEventListener('resize', handleChartResize);
    
    // 监听容器元素的resize事件（使用ResizeObserver API如果支持）
    if (window.ResizeObserver) {
        const resizeObserver = new ResizeObserver(handleChartResize);
        resizeObserver.observe(container);
    }
    
    // 保存图表实例引用，以便外部可以访问
    if (!window._roughCharts) window._roughCharts = [];
    window._roughCharts.push({ chart, container, resize: handleChartResize });
};
 

RoughAnalysis.prototype.showMultipleRoughnessRate = function (indices, pathCollection, pathLines) {
        if (!Array.isArray(indices) || indices.length === 0) return alert('请先选择要显示的路径');
        if (!Array.isArray(pathCollection) || pathCollection.length === 0) return alert('没有路径数据可用');

        // 准备图表容器（与单条曲线逻辑一致）
        let container = document.getElementById('roughnessRateChartContainer');
        if (!container) {
            const panel = document.createElement('div');
            panel.id = 'roughnessRateChartPanel';
            panel.style.position = 'absolute';
            panel.style.left = 'calc(50% - 360px)';
            panel.style.top = '120px';
            panel.style.width = '720px';
            panel.style.height = '420px';
            panel.style.background = '#fff';
            panel.style.border = '1px solid #ccc';
            panel.style.zIndex = 99999;
            panel.style.boxShadow = '0 2px 12px rgba(0,0,0,0.3)';
            panel.style.resize = 'both';
            panel.style.overflow = 'hidden';

            panel.innerHTML = ''
            +    '<div id="roughRateMultiHeader" style="height:40px;display:flex;justify-content:space-between;align-items:center;padding:6px;border-bottom:1px solid #eee;cursor:move;background:#fafafa;">'
            +      '<div style="font-weight:600">陡峭度变化曲线 (距离 ： 陡峭度变化) — 多路径</div>'
            +      '<div><button id="closeRoughRateChartBtn">关闭</button></div>'
            +    '</div>'
            +    '<div id="roughnessRateChartContainer" style="width:100%;height:calc(100% - 40px);overflow:auto;"></div>';
            document.body.appendChild(panel);
            container = document.getElementById('roughnessRateChartContainer');
            const closeBtnMulti = document.getElementById('closeRoughRateChartBtn');
            if (closeBtnMulti) closeBtnMulti.onclick = function () { panel.remove(); };

            // 可拖拽头部
            (function makeDraggable(p, headerId) {
                const header = document.getElementById(headerId);
                if (!header) return;
                header.addEventListener('mousedown', startDrag);
                function startDrag(e) {
                    e.preventDefault();
                    const rect = p.getBoundingClientRect();
                    const offsetX = e.clientX - rect.left;
                    const offsetY = e.clientY - rect.top;
                    function onMove(ev) {
                        p.style.left = Math.max(0, ev.clientX - offsetX) + 'px';
                        p.style.top = Math.max(0, ev.clientY - offsetY) + 'px';
                    }
                    function endDrag() {
                        window.removeEventListener('mousemove', onMove);
                        window.removeEventListener('mouseup', endDrag);
                    }
                    window.addEventListener('mousemove', onMove);
                    window.addEventListener('mouseup', endDrag);
                }
            })(panel, 'roughRateMultiHeader');
        }

    const series = [];
    const legendNames = [];
    const palette = ['#ff5722','#2196f3','#4caf50','#9c27b0','#ff9800','#03a9f4','#8bc34a','#e91e63','#607d8b'];

    for (let idx of indices) {
      if (!Number.isFinite(idx) || !pathCollection[idx] || pathCollection[idx].length === 0) continue;
      const seq = this.analyzePathRoughness(pathCollection[idx]);
      if (!seq || seq.length === 0) continue;
      const data = seq.map(d => [Number(d.distance.toFixed(2)), Number(d.roughnessRate.toFixed(6))]);

      // 尝试从 pathLines 取颜色
      let color = null;
      try {
        if (Array.isArray(pathLines) && pathLines[idx]) {
          const pl = pathLines[idx];
          if (pl.pathLineColorCss) color = pl.pathLineColorCss;
          else if (pl.colorStr) color = pl.colorStr;
          else if (pl.name && pl.color) color = pl.color;
          else if (pl.polyline && pl.polyline.material && pl.polyline.material.color && pl.polyline.material.color._value) {
            const cc = pl.polyline.material.color._value;
            color = `rgba(${Math.round(cc.red*255)},${Math.round(cc.green*255)},${Math.round(cc.blue*255)},${cc.alpha})`;
          }
        }
      } catch (e) { color = null; }
      if (!color) color = palette[idx % palette.length];

      const name = (pathLines && pathLines[idx] && pathLines[idx].name) ? pathLines[idx].name : `路径 ${idx}`;
      legendNames.push(name);
      series.push({
        name: name,
        type: 'line',
        data: data,
        showSymbol: false,
        smooth: false,
        lineStyle: { width: 2, color: color },
        itemStyle: { color: color }
      });
    }

    if (series.length === 0) return alert('所选路径无有效陡峭度变化数据');

    let chart;
    try { chart = echarts.init(container); } catch (e) { return alert('ECharts 未加载'); }
    const option = {
      title: { text: '行驶距离 ： 陡峭度变化', left: 'center', textStyle: { fontSize: 12 } },
      tooltip: { trigger: 'axis', formatter: params => params.map(p => `${p.seriesName}: 距离 ${p.value[0]} m, 陡峭度变化 ${p.value[1]}`).join('<br/>') },
      legend: { data: legendNames, top: 30, left: '20%' },
      grid: { left: '8%', right: '6%', top: 60, bottom: '12%' },
      xAxis: { type: 'value', name: '行驶距离 (m)', nameLocation: 'middle', nameGap: 25 },
      yAxis: { type: 'value', name: '陡峭度变化 (m)', nameLocation: 'middle', nameGap: 30 },
      series: series
    };
    chart.setOption(option);
    //window.addEventListener('resize', () => { try { chart.resize(); } catch(e){} });
     // 图表resize处理函数
    function handleChartResize() {
        try {
            // 强制重新计算图表尺寸，让图标尺寸适配窗口大小
            chart.resize({
                width: container.clientWidth,
                height: container.clientHeight
            });
        } catch (e) {
            console.warn('图表resize失败:', e);
        }
    }
    
    // 监听窗口resize事件
    window.addEventListener('resize', handleChartResize);
    
    // 监听容器元素的resize事件（使用ResizeObserver API如果支持）
    if (window.ResizeObserver) {
        const resizeObserver = new ResizeObserver(handleChartResize);
        resizeObserver.observe(container);
    }
    
    // 保存图表实例引用，以便外部可以访问
    if (!window._roughRateCharts) window._roughRateCharts = [];
    window._roughRateCharts.push({ chart, container, resize: handleChartResize });
    };
 
  global.RoughAnalysis = RoughAnalysis;
})(window);



