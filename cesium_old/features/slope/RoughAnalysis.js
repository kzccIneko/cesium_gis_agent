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
    this.lastHeight = null;   // 保存上一点高度
    this.roughnessRates = [];// 保存所有路径所有点的陡峭度变化率
    this.heightRates = [];// 保存所有路径所有点的高度变化率
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

      //高程变化量
      const heightRate = (centerH - this.lastHeight) / delta;
      this.lastHeight = centerH;// 保存当前高度给下一轮用

      results.push({
        distance: cumulativeDistance,  // 累计行驶距离（m）
        height: centerH,               // 当前点高度（m）
        heightRate: heightRate,        // 高度变化率（m/m）
        roughness: roughness,         // 陡峭度（相对无量纲值）
        roughnessRate: roughnessRate, // 陡峭度变化
        H_mapped: H_mapped,           // 调试用映射后 9 值
        nodeIndex: i,                 // 当前节点索引
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
   * - pathCollection: 嵌套数组，pathCollection[i] 为第 i 条路径的点数组（每点含 Cartesian3Grid 或 z），文件中为SlopeAnalysis.pathPoints
   * - pathLines: 路径元信息数组（用于取颜色/name），可选
   */
RoughAnalysis.prototype.showMultipleRoughness = function (indices, pathCollection, pathLines) {
        if (!Array.isArray(indices) || indices.length === 0) return alert('请先选择要显示的路径');
        if (!Array.isArray(pathCollection) || pathCollection.length === 0) return alert('没有路径数据可用');
        // 准备图表容器（与单条曲线逻辑一致）
        let container = document.getElementById('roughnessChartContainer');
        if (!container) {
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
            panel.style.resize = 'both';// 原改变窗口大小方法，只能拖拽右下角
            panel.style.overflow = 'hidden';

            panel.innerHTML = ''
            +    '<div id="roughMultiHeader" class="move" style="height:40px;display:flex;justify-content:space-between;align-items:center;padding:6px;border-bottom:1px solid #eee;cursor:move;background:#fafafa;">'
            +      '<div style="font-weight:600">陡峭度曲线 (距离 ： 陡峭度) — 多路径</div>'
            +      '<div><button id="closeRoughChartBtn">关闭</button></div>'
            +    '</div>'
            +    '<div id="roughnessChartContainer" style="width:100%;height:calc(100% - 40px);overflow:auto;"></div>'
            +    '<div id="resize-top" style="position:absolute;top:0;left:0;right:0;height:5px;cursor:n-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-right" style="position:absolute;right:0;top:0;bottom:0;width:5px;cursor:e-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-bottom" style="position:absolute;bottom:0;left:0;right:0;height:5px;cursor:s-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-left" style="position:absolute;left:0;top:0;bottom:0;width:5px;cursor:w-resize;z-index:10;background:transparent;"></div>';
            document.body.appendChild(panel);
            container = document.getElementById('roughnessChartContainer');
            const closeBtnMulti = document.getElementById('closeRoughChartBtn');
            if (closeBtnMulti) closeBtnMulti.onclick = function () { panel.remove(); };

            // 拖拽由 eventBindInit.js 的 document 级委托统一处理（头部带 class="move" 即生效）

            // 四边拖拽调整大小功能
            (function makeResizable(p) {
              const resizeElements = {      //见panel.innerHTML中对应id
                top: document.getElementById('resize-top'),
                right: document.getElementById('resize-right'),
                bottom: document.getElementById('resize-bottom'),
                left: document.getElementById('resize-left')
              };

              // 最小窗口尺寸
              const minWidth = 300;
              const minHeight = 200;

              // 各个方向的拖拽处理
              Object.keys(resizeElements).forEach(dir => {
                const el = resizeElements[dir];
                if (!el) return;

                el.addEventListener('mousedown', function (e) {
                  e.preventDefault();
                  const startX = e.clientX;
                  const startY = e.clientY;
                  const startWidth = parseInt(document.defaultView.getComputedStyle(p).width, 10);
                  const startHeight = parseInt(document.defaultView.getComputedStyle(p).height, 10);
                  const startLeft = p.offsetLeft;
                  const startTop = p.offsetTop;

                  function doDrag(e) {
                    switch (dir) {
                      case 'top':
                        const dy = startY - e.clientY;
                        const newHeight = startHeight + dy;
                        if (newHeight >= minHeight) {
                          p.style.height = newHeight + 'px';
                          p.style.top = (startTop - dy) + 'px';
                        }
                        break;
                      case 'right':
                        const dx = e.clientX - startX;
                        const newWidth = startWidth + dx;
                        if (newWidth >= minWidth) {
                          p.style.width = newWidth + 'px';
                        }
                        break;
                      case 'bottom':
                        const dy2 = e.clientY - startY;
                        const newHeight2 = startHeight + dy2;
                        if (newHeight2 >= minHeight) {
                          p.style.height = newHeight2 + 'px';
                        }
                        break;
                      case 'left':
                        const dx2 = startX - e.clientX;
                        const newWidth2 = startWidth + dx2;
                        if (newWidth2 >= minWidth) {
                          p.style.width = newWidth2 + 'px';
                          p.style.left = (startLeft - dx2) + 'px';
                        }
                        break;
                    }

                    // 触发图表重绘
                    window.dispatchEvent(new Event('resize'));
                  }

                  function stopDrag() {
                    document.documentElement.removeEventListener('mousemove', doDrag, false);
                    document.documentElement.removeEventListener('mouseup', stopDrag, false);
                  }

                  document.documentElement.addEventListener('mousemove', doDrag, false);
                  document.documentElement.addEventListener('mouseup', stopDrag, false);
                });
              });
            })(panel);
        }

    const series = [];
    const legendNames = [];
    const palette = ['#ff5722','#2196f3','#4caf50','#9c27b0','#ff9800','#03a9f4','#8bc34a','#e91e63','#607d8b'];

    for (let idx of indices) {
      if (!Number.isFinite(idx) || !pathCollection[idx] || pathCollection[idx].length === 0) continue;
      const seq = this.analyzePathRoughness(pathCollection[idx]);
      if (!seq || seq.length === 0) continue;
      const seqForChart = (seq.length > 2) ? seq.slice(1, -1) : seq;// 去掉首1尾1点后再映射为图表数据（如果长度 <=2 则保留全部）
      const data = seqForChart.map(d => [Number(d.distance.toFixed(2)), Number(d.roughness.toFixed(6)), Number(d.nodeIndex)]);// 图表中折线各点数据

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
        showSymbol: true,// 显示数据圆圈点
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
      tooltip: { trigger: 'axis', formatter: params => params.map(p => `${p.seriesName}: 点 ${p.value[2]}, 距离 ${p.value[0]} m, 陡峭度 ${p.value[1]}`).join('<br/>') },
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
            panel.style.resize = 'both';// 原调节窗口大小功能，只能右下角拖拽调节
            panel.style.overflow = 'hidden';

            panel.innerHTML = ''
            +    '<div id="roughRateMultiHeader" class="move" style="height:40px;display:flex;justify-content:space-between;align-items:center;padding:6px;border-bottom:1px solid #eee;cursor:move;background:#fafafa;">'
            +      '<div style="font-weight:600">陡峭度变化曲线 (距离 ： 陡峭度变化) — 多路径</div>'
            +      '<div><button id="closeroughRateChartBtn">关闭</button></div>'
            +    '</div>'
            +    '<div id="roughnessRateChartContainer" style="width:100%;height:calc(100% - 40px);overflow:auto;"></div>'
            +    '<div id="resize-rate-top" style="position:absolute;top:0;left:0;right:0;height:5px;cursor:n-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-rate-right" style="position:absolute;right:0;top:0;bottom:0;width:5px;cursor:e-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-rate-bottom" style="position:absolute;bottom:0;left:0;right:0;height:5px;cursor:s-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-rate-left" style="position:absolute;left:0;top:0;bottom:0;width:5px;cursor:w-resize;z-index:10;background:transparent;"></div>';
            document.body.appendChild(panel);
            container = document.getElementById('roughnessRateChartContainer');
            const closeBtnMulti = document.getElementById('closeroughRateChartBtn');
            if (closeBtnMulti) closeBtnMulti.onclick = function () { panel.remove(); };

            // 拖拽由 eventBindInit.js 的 document 级委托统一处理（头部带 class="move" 即生效）

          // 四边拖拽调整大小功能
          (function makeResizable(p) {
            const resizeElements = {      //见panel.innerHTML中对应id
              top: document.getElementById('resize-rate-top'),
              right: document.getElementById('resize-rate-right'),
              bottom: document.getElementById('resize-rate-bottom'),
              left: document.getElementById('resize-rate-left')
            };

            // 最小窗口尺寸
            const minWidth = 300;
            const minHeight = 200;

            // 检查是否有resize元素
            let hasResizableElements = false;
            Object.keys(resizeElements).forEach(dir => {
              if (resizeElements[dir]) hasResizableElements = true;
            });

            if (!hasResizableElements) return;

            // 各个方向的拖拽处理
            Object.keys(resizeElements).forEach(dir => {
              const el = resizeElements[dir];
              if (!el) return;

              el.addEventListener('mousedown', function (e) {
                e.preventDefault();
                const startX = e.clientX;
                const startY = e.clientY;
                const startWidth = parseInt(document.defaultView.getComputedStyle(p).width, 10);
                const startHeight = parseInt(document.defaultView.getComputedStyle(p).height, 10);
                const startLeft = p.offsetLeft;
                const startTop = p.offsetTop;

                function doDrag(e) {
                  switch (dir) {
                    case 'top':
                      const dy = startY - e.clientY;
                      const newHeight = startHeight + dy;
                      if (newHeight >= minHeight) {
                        p.style.height = newHeight + 'px';
                        p.style.top = (startTop - dy) + 'px';
                      }
                      break;
                    case 'right':
                      const dx = e.clientX - startX;
                      const newWidth = startWidth + dx;
                      if (newWidth >= minWidth) {
                        p.style.width = newWidth + 'px';
                      }
                      break;
                    case 'bottom':
                      const dy2 = e.clientY - startY;
                      const newHeight2 = startHeight + dy2;
                      if (newHeight2 >= minHeight) {
                        p.style.height = newHeight2 + 'px';
                      }
                      break;
                    case 'left':
                      const dx2 = startX - e.clientX;
                      const newWidth2 = startWidth + dx2;
                      if (newWidth2 >= minWidth) {
                        p.style.width = newWidth2 + 'px';
                        p.style.left = (startLeft - dx2) + 'px';
                      }
                      break;
                  }

                  // 触发图表重绘
                  try {
                    if (window._roughRateCharts && window._roughRateCharts.length > 0) {
                      const chartObj = window._roughRateCharts.find(c => c.container === container);
                      if (chartObj && chartObj.chart) {
                        chartObj.chart.resize({
                          width: container.clientWidth,
                          height: container.clientHeight
                        });
                      }
                    }
                  } catch (e) {
                    console.warn('图表resize失败:', e);
                  }
                }

                function stopDrag() {
                  document.documentElement.removeEventListener('mousemove', doDrag, false);
                  document.documentElement.removeEventListener('mouseup', stopDrag, false);
                }

                document.documentElement.addEventListener('mousemove', doDrag, false);
                document.documentElement.addEventListener('mouseup', stopDrag, false);
              });
            });
          })(panel);
        }

    const series = [];
    const legendNames = [];
    const palette = ['#ff5722','#2196f3','#4caf50','#9c27b0','#ff9800','#03a9f4','#8bc34a','#e91e63','#607d8b'];

    for (let idx of indices) {
      if (!Number.isFinite(idx) || !pathCollection[idx] || pathCollection[idx].length === 0) continue;
      const seq = this.analyzePathRoughness(pathCollection[idx]);
      if (!seq || seq.length === 0) continue;
      const seqForChart = (seq.length > 3) ? seq.slice(2, -1) : seq;// 去掉首2尾1点后再映射为图表数据（如果长度 <=2 则保留全部）
      const data = seqForChart.map(d => [Number(d.distance.toFixed(2)), Number(d.roughnessRate.toFixed(6)), Number(d.nodeIndex)]);// 图表中折线各点数据
      this.roughnessRates[idx] = seqForChart.map(d => d.roughnessRate);//用于计算最值和均值

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
        showSymbol: true,
        smooth: false,
        lineStyle: { width: 2, color: color },
        itemStyle: { color: color }
      });

      const roughnessRateMax = Math.max(...this.roughnessRates[idx].flat());
      console.log('idx', idx, 'roughnessRateMax', roughnessRateMax);
      const roughnessRateAvg = this.roughnessRates[idx].flat().reduce((a, b) => a + b, 0) / this.roughnessRates[idx].flat().length;
      console.log('idx', idx, 'roughnessRateAvg', roughnessRateAvg);
    }

    if (series.length === 0) return alert('所选路径无有效陡峭度变化数据');

    let chart;
    try { chart = echarts.init(container); } catch (e) { return alert('ECharts 未加载'); }
    const option = {
      title: { text: '行驶距离 ： 陡峭度变化', left: 'center', textStyle: { fontSize: 12 } },
      tooltip: { trigger: 'axis', formatter: params => params.map(p => `${p.seriesName}: 点 ${p.value[2]}, 距离 ${p.value[0]} m, 陡峭度变化 ${p.value[1]}`).join('<br/>') },
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
    // if (window.ResizeObserver) {
    //     const resizeObserver = new ResizeObserver(handleChartResize);
    //     resizeObserver.observe(container);
    // }
    try {
      if (typeof window.ResizeObserver === 'function' && container) {
        const resizeObserver = new ResizeObserver(handleChartResize);
        // 观察 container（若 container 为 null，observe 会抛错，故已检查）
        resizeObserver.observe(container);
        // 如果面板存在，把 observer 存到 panel 上，关闭面板时可以断开观察
        if (typeof panel !== 'undefined' && panel && panel.nodeType === 1) {
          panel._resizeObserver = resizeObserver;
        } else {
          // 备份到全局数组，防止找不到 panel
          window._roughResizeObservers = window._roughResizeObservers || [];
          window._roughResizeObservers.push(resizeObserver);
        }
      }
    } catch (e) {
      console.warn('RoughAnalysis: ResizeObserver 注册失败或发生异常：', e);
    }
    
    // 保存图表实例引用，以便外部可以访问
    if (!window._roughRateCharts) window._roughRateCharts = [];
    window._roughRateCharts.push({ chart, container, resize: handleChartResize });
    };
 

RoughAnalysis.prototype.showMultipleHeightRate = function (indices, pathCollection, pathLines) {
        if (!Array.isArray(indices) || indices.length === 0) return alert('请先选择要显示的路径');
        if (!Array.isArray(pathCollection) || pathCollection.length === 0) return alert('没有路径数据可用');
        // 准备图表容器（与单条曲线逻辑一致）
        let container = document.getElementById('heightRateChartContainer');
        if (!container) {
            const panel = document.createElement('div');
            panel.id = 'heightRateChartPanel';
            panel.style.position = 'absolute';
            panel.style.left = 'calc(50% - 360px)';
            panel.style.top = '120px';
            panel.style.width = '720px';
            panel.style.height = '420px';
            panel.style.background = '#fff';
            panel.style.border = '1px solid #ccc';
            panel.style.zIndex = 99999;
            panel.style.boxShadow = '0 2px 12px rgba(0,0,0,0.3)';
            panel.style.resize = 'both';// 原改变窗口大小方法，只能拖拽右下角
            panel.style.overflow = 'hidden';

            panel.innerHTML = ''
            +    '<div id="heightRateMultiHeader" class="move" style="height:40px;display:flex;justify-content:space-between;align-items:center;padding:6px;border-bottom:1px solid #eee;cursor:move;background:#fafafa;">'
            +      '<div style="font-weight:600">高程变化率曲线 (距离 ： 高程变化率) — 多路径</div>'
            +      '<div><button id="closeheightRateChartBtn">关闭</button></div>'
            +    '</div>'
            +    '<div id="heightRateChartContainer" style="width:100%;height:calc(100% - 40px);overflow:auto;"></div>'
            +    '<div id="resize-heightRate-top" style="position:absolute;top:0;left:0;right:0;height:5px;cursor:n-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-heightRate-right" style="position:absolute;right:0;top:0;bottom:0;width:5px;cursor:e-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-heightRate-bottom" style="position:absolute;bottom:0;left:0;right:0;height:5px;cursor:s-resize;z-index:10;background:transparent;"></div>'
            +    '<div id="resize-heightRate-left" style="position:absolute;left:0;top:0;bottom:0;width:5px;cursor:w-resize;z-index:10;background:transparent;"></div>';
            document.body.appendChild(panel);
            container = document.getElementById('heightRateChartContainer');
            const closeBtnMulti = document.getElementById('closeheightRateChartBtn');
            if (closeBtnMulti) closeBtnMulti.onclick = function () { panel.remove(); };

            // 拖拽由 eventBindInit.js 的 document 级委托统一处理（头部带 class="move" 即生效）

            // 四边拖拽调整大小功能
            (function makeResizable(p) {
              const resizeElements = {      //见panel.innerHTML中对应id
                top: document.getElementById('resize-heightRate-top'),
                right: document.getElementById('resize-heightRate-right'),
                bottom: document.getElementById('resize-heightRate-bottom'),
                left: document.getElementById('resize-heightRate-left')
              };

              // 最小窗口尺寸
              const minWidth = 300;
              const minHeight = 200;

              // 各个方向的拖拽处理
              Object.keys(resizeElements).forEach(dir => {
                const el = resizeElements[dir];
                if (!el) return;

                el.addEventListener('mousedown', function (e) {
                  e.preventDefault();
                  const startX = e.clientX;
                  const startY = e.clientY;
                  const startWidth = parseInt(document.defaultView.getComputedStyle(p).width, 10);
                  const startHeight = parseInt(document.defaultView.getComputedStyle(p).height, 10);
                  const startLeft = p.offsetLeft;
                  const startTop = p.offsetTop;

                  function doDrag(e) {
                    switch (dir) {
                      case 'top':
                        const dy = startY - e.clientY;
                        const newHeight = startHeight + dy;
                        if (newHeight >= minHeight) {
                          p.style.height = newHeight + 'px';
                          p.style.top = (startTop - dy) + 'px';
                        }
                        break;
                      case 'right':
                        const dx = e.clientX - startX;
                        const newWidth = startWidth + dx;
                        if (newWidth >= minWidth) {
                          p.style.width = newWidth + 'px';
                        }
                        break;
                      case 'bottom':
                        const dy2 = e.clientY - startY;
                        const newHeight2 = startHeight + dy2;
                        if (newHeight2 >= minHeight) {
                          p.style.height = newHeight2 + 'px';
                        }
                        break;
                      case 'left':
                        const dx2 = startX - e.clientX;
                        const newWidth2 = startWidth + dx2;
                        if (newWidth2 >= minWidth) {
                          p.style.width = newWidth2 + 'px';
                          p.style.left = (startLeft - dx2) + 'px';
                        }
                        break;
                    }

                    // 触发图表重绘
                    window.dispatchEvent(new Event('resize'));
                  }

                  function stopDrag() {
                    document.documentElement.removeEventListener('mousemove', doDrag, false);
                    document.documentElement.removeEventListener('mouseup', stopDrag, false);
                  }

                  document.documentElement.addEventListener('mousemove', doDrag, false);
                  document.documentElement.addEventListener('mouseup', stopDrag, false);
                });
              });
            })(panel);
        }

    const series = [];
    const legendNames = [];
    const palette = ['#ff5722','#2196f3','#4caf50','#9c27b0','#ff9800','#03a9f4','#8bc34a','#e91e63','#607d8b'];

    for (let idx of indices) {
      if (!Number.isFinite(idx) || !pathCollection[idx] || pathCollection[idx].length === 0) continue;
      const seq = this.analyzePathRoughness(pathCollection[idx]);
      if (!seq || seq.length === 0) continue;
      const seqForChart = (seq.length > 3) ? seq.slice(2, -1) : seq;// 去掉首2尾1点后再映射为图表数据（如果长度 <=2 则保留全部）
      const data = seqForChart.map(d => [Number(d.distance.toFixed(2)), Number(d.heightRate.toFixed(6)), Number(d.nodeIndex)]);// 图表中折线各点数据
      this.heightRates[idx] = seqForChart.map(d => Math.abs(d.heightRate));//用于计算最值和均值

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
        showSymbol: true,// 显示数据圆圈点
        smooth: false,
        lineStyle: { width: 2, color: color },
        itemStyle: { color: color }
      });

      const heightRateMax = Math.max(...this.heightRates[idx].flat());// 绝对值最大值
      console.log('idx', idx, 'heightRateMax', heightRateMax);
      const heightRateAvg = this.heightRates[idx].flat().reduce((a, b) => a + b, 0) / this.heightRates[idx].flat().length;// 绝对值平均值
      console.log('idx', idx, 'heightRateAvg', heightRateAvg);
    }
    

    if (series.length === 0) return alert('所选路径无有效高程变化数据');

    let chart;
    try { chart = echarts.init(container); } catch (e) { return alert('ECharts 未加载'); }
    const option = {
      title: { text: '行驶距离 ： 高程变化率', left: 'center', textStyle: { fontSize: 12 } },
      tooltip: { trigger: 'axis', formatter: params => params.map(p => `${p.seriesName}: 点 ${p.value[2]}, 距离 ${p.value[0]} m, 高程变化率 ${p.value[1]}`).join('<br/>') },
      legend: { data: legendNames, top: 30, left: '20%' },
      grid: { left: '8%', right: '6%', top: 60, bottom: '12%' },
      xAxis: { type: 'value', name: '行驶距离 (m)', nameLocation: 'middle', nameGap: 25 },
      yAxis: { type: 'value', name: '高程变化率', nameLocation: 'middle', nameGap: 30 },
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

    // 正确暴露到全局作用域
  global.RoughAnalysis = RoughAnalysis;

})(window);



