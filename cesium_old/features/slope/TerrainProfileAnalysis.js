/*
 * 剖面分析模块
 * 功能: 用户在地形上绘制剖面线 → 采样高程 → 生成剖面图(高程+坡度)
 * 参考: 文老师建议 — 任意方向剖面分析, 在剖面曲线上计算坡度
 *       杨欣师兄原始实现思路 + RoughAnalysis.js 图表展示模式
 */
(function (global) {
  'use strict';

  var Cesium = window.Cesium;

  /**
   * TerrainProfileAnalysis 构造函数
   * @param {Cesium.Viewer} viewer
   */
  function TerrainProfileAnalysis(viewer) {
    if (!viewer) throw new Error('TerrainProfileAnalysis 需要传入 viewer');
    this.viewer = viewer;
    this.handler = null;
    this.activePoints = [];       // 用户绘制的点 (Cartesian3)
    this.profileEntity = null;   // 剖面线实体
    this.markerEntities = [];    // 点标记实体
    this.chartPanel = null;      // 图表面板 DOM
    this.chartInstance = null;   // ECharts 实例
    this.profileData = null;     // 最新剖面数据
    this.sampleInterval = 30;    // 默认采样间距 (米)
    this._isDrawing = false;
    this._highlightEntity = null; // 点击高亮实体
    this._sidebarLayerId = null;  // 侧边栏图层 ID
  }

  /**
   * 清除剖面实体和数据，但保留面板
   */
  TerrainProfileAnalysis.prototype._clearEntities = function () {
    this.stopDrawing();
    this.activePoints = [];
    this.markerEntities.forEach(function (e) { try { this.viewer.entities.remove(e); } catch (_) {} }, this);
    this.markerEntities = [];
    if (this.profileEntity) {
      try { this.viewer.entities.remove(this.profileEntity); } catch (_) {}
      this.profileEntity = null;
    }
    if (this._highlightEntity) {
      try { this.viewer.entities.remove(this._highlightEntity); } catch (_) {}
      this._highlightEntity = null;
    }
    this._removeSidebarLayer();
    this.profileData = null;
    this._cachedElevData = null;
    this._cachedSlopeData = null;
  };

  /**
   * 启动剖面绘制模式
   */
  TerrainProfileAnalysis.prototype.startDrawing = function () {
    if (this._isDrawing) return;
    this._isDrawing = true;
    this._clearEntities();

    var self = this;
    var tooltipDiv = document.getElementById('profileTooltip');
    if (!tooltipDiv) {
      tooltipDiv = document.createElement('div');
      tooltipDiv.id = 'profileTooltip';
      tooltipDiv.style.cssText = 'position:absolute;bottom:40px;left:50%;transform:translateX(-50%);'
        + 'background:rgba(0,0,0,0.75);color:#fff;padding:8px 16px;border-radius:4px;'
        + 'font-size:14px;z-index:10000;pointer-events:none;white-space:nowrap;';
      document.body.appendChild(tooltipDiv);
    }
    tooltipDiv.textContent = '左键点击添加剖面点，右键结束绘制，Ctrl+Z 撤销';
    tooltipDiv.style.display = 'block';

    this.handler = new Cesium.ScreenSpaceEventHandler(this.viewer.canvas);

    // 左键: 添加点
    this.handler.setInputAction(function (click) {
      var cartesian = self._pickTerrain(click.position);
      if (!cartesian) return;

      self.activePoints.push(cartesian);
      self._addMarker(cartesian);
      self._updateProfileLine();

      if (self.activePoints.length === 1) {
        tooltipDiv.textContent = '已添加起点，继续点击添加中间点，右键结束';
      } else {
        tooltipDiv.textContent = '已添加 ' + self.activePoints.length + ' 个点，右键结束，Ctrl+Z 撤销';
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    // 右键: 结束绘制并开始分析
    this.handler.setInputAction(function () {
      if (self.activePoints.length < 2) {
        self.stopDrawing();
        return;
      }
      tooltipDiv.textContent = '正在采样地形高程...';
      self.stopDrawing();
      self._analyzeProfile();
    }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);

    // Ctrl+Z 撤销
    document.addEventListener('keydown', this._keyHandler = function (e) {
      if (!self._isDrawing) return;
      if (e.ctrlKey && e.key === 'z') {
        e.preventDefault();
        if (self.activePoints.length > 0) {
          self.activePoints.pop();
          // 移除最后一个标记
          var lastMarker = self.markerEntities.pop();
          if (lastMarker) self.viewer.entities.remove(lastMarker);
          self._updateProfileLine();
          tooltipDiv.textContent = '已撤销，当前 ' + self.activePoints.length + ' 个点';
          if (self.activePoints.length === 0) {
            tooltipDiv.textContent = '左键点击添加剖面点，右键结束绘制，Ctrl+Z 撤销';
          }
        }
      }
    });

    console.log('[剖面分析] 绘制模式已启动');
  };

  /**
   * 停止绘制模式
   */
  TerrainProfileAnalysis.prototype.stopDrawing = function () {
    this._isDrawing = false;
    if (this.handler) {
      this.handler.destroy();
      this.handler = null;
    }
    if (this._keyHandler) {
      document.removeEventListener('keydown', this._keyHandler);
      this._keyHandler = null;
    }
    var tooltipDiv = document.getElementById('profileTooltip');
    if (tooltipDiv) tooltipDiv.style.display = 'none';
  };

  /**
   * 清除所有绘制和分析结果
   */
  TerrainProfileAnalysis.prototype.clearAll = function () {
    this.stopDrawing();
    this.activePoints = [];
    // 清除标记
    this.markerEntities.forEach(function (e) { try { this.viewer.entities.remove(e); } catch (_) {} }, this);
    this.markerEntities = [];
    // 清除剖面线
    if (this.profileEntity) {
      try { this.viewer.entities.remove(this.profileEntity); } catch (_) {}
      this.profileEntity = null;
    }
    // 清除点击高亮标记
    if (this._highlightEntity) {
      try { this.viewer.entities.remove(this._highlightEntity); } catch (_) {}
      this._highlightEntity = null;
    }
    // 从侧边栏移除
    this._removeSidebarLayer();
    // 清除图表
    this._closeChart();
    this.profileData = null;
  };

  // ─── 内部方法 ──────────────────────────────────────────

  /**
   * 从屏幕坐标拾取地形点
   */
  TerrainProfileAnalysis.prototype._pickTerrain = function (screenPos) {
    var cartesian = this.viewer.scene.pickPosition(screenPos);
    if (!cartesian) {
      // 如果拾取不到地形，尝试用相机+椭球面
      var ray = this.viewer.camera.getPickRay(screenPos);
      if (ray) {
        cartesian = this.viewer.scene.globe.pick(ray, this.viewer.scene);
      }
    }
    return cartesian;
  };

  /**
   * 添加点标记（允许被地形遮挡）
   */
  TerrainProfileAnalysis.prototype._addMarker = function (cartesian) {
    var marker = this.viewer.entities.add({
      position: cartesian,
      point: {
        pixelSize: 6,
        color: Cesium.Color.YELLOW,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 1
      }
    });
    this.markerEntities.push(marker);
  };

  /**
   * 更新剖面线实体
   */
  TerrainProfileAnalysis.prototype._updateProfileLine = function () {
    if (this.profileEntity) {
      this.viewer.entities.remove(this.profileEntity);
    }
    if (this.activePoints.length < 2) return;

    this.profileEntity = this.viewer.entities.add({
      polyline: {
        positions: this.activePoints.slice(),
        width: 3,
        material: Cesium.Color.fromCssColorString('#00E5FF'),
        clampToGround: true,
        depthFailMaterial: Cesium.Color.fromCssColorString('#00E5FF').withAlpha(0.3)
      }
    });
  };

  /**
   * 核心: 采样剖面并生成图表
   */
  TerrainProfileAnalysis.prototype._analyzeProfile = function () {
    if (this.activePoints.length < 2) {
      alert('请至少绘制两个点');
      return;
    }

    var self = this;
    var cartographicPoints = [];
    var i;

    // 转为经纬度弧度
    for (i = 0; i < this.activePoints.length; i++) {
      var c = Cesium.Cartographic.fromCartesian(this.activePoints[i]);
      cartographicPoints.push(c);
    }

    // 计算剖面总长度
    var totalDistance = 0;
    var segmentLengths = [];
    for (i = 1; i < this.activePoints.length; i++) {
      var d = Cesium.Cartesian3.distance(this.activePoints[i - 1], this.activePoints[i]);
      segmentLengths.push(d);
      totalDistance += d;
    }

    // 沿剖面线等距采样
    var samplePoints = Math.min(Math.ceil(totalDistance / this.sampleInterval), 2000);
    samplePoints = Math.max(samplePoints, this.activePoints.length); // 至少包含用户点击的点

    var sampleCartographics = [];
    var lastProgress = -1;

    // 先按段插值生成采样点 (经纬度)
    for (i = 0; i < samplePoints; i++) {
      var t = samplePoints > 1 ? i / (samplePoints - 1) : 0;
      var targetDist = t * totalDistance;
      var accumulated = 0;
      var segIdx = 0;
      for (segIdx = 0; segIdx < segmentLengths.length; segIdx++) {
        if (accumulated + segmentLengths[segIdx] >= targetDist) break;
        accumulated += segmentLengths[segIdx];
      }

      if (segIdx >= segmentLengths.length) segIdx = segmentLengths.length - 1;

      var segT = segmentLengths[segIdx] > 0
        ? (targetDist - accumulated) / segmentLengths[segIdx]
        : 0;
      segT = Math.max(0, Math.min(1, segT));

      var from = cartographicPoints[segIdx];
      var to = cartographicPoints[Math.min(segIdx + 1, cartographicPoints.length - 1)];

      var lon = Cesium.Math.lerp(from.longitude, to.longitude, segT);
      var lat = Cesium.Math.lerp(from.latitude, to.latitude, segT);

      sampleCartographics.push(new Cesium.Cartographic(lon, lat, 0));
    }

    // 使用 Cesium 批量采样地形高程
    Cesium.sampleTerrainMostDetailed(this.viewer.terrainProvider, sampleCartographics)
      .then(function (updatedSamples) {
        console.log('[剖面分析] 地形采样完成, 共 ' + updatedSamples.length + ' 个点');

        // 构建剖面数据
        var distances = [];
        var elevations = [];
        var slopes = [];
        var cumDist = 0;

        for (i = 0; i < updatedSamples.length; i++) {
          var carto = updatedSamples[i];
          if (i > 0) {
            var prev = updatedSamples[i - 1];
            // 计算两点间实际地表距离 (考虑高程差)
            var p0 = Cesium.Cartesian3.fromRadians(prev.longitude, prev.latitude, prev.height);
            var p1 = Cesium.Cartesian3.fromRadians(carto.longitude, carto.latitude, carto.height);
            var stepDist = Cesium.Cartesian3.distance(p0, p1);
            cumDist += stepDist;
          }
          distances.push(cumDist);
          elevations.push(carto.height);

          if (i > 0 && cumDist > 0) {
            var dh = carto.height - updatedSamples[i - 1].height;
            var dd = cumDist - (distances[i - 1] || 0);
            // 坡度角度 (度)
            var slopeDeg = Math.atan(Math.abs(dh) / Math.max(dd, 0.01)) * (180 / Math.PI);
            // 保留符号 (上坡正, 下坡负)
            slopes.push(dh >= 0 ? slopeDeg : -slopeDeg);
          } else {
            slopes.push(0);
          }
        }

        self.profileData = {
          distances: distances,
          elevations: elevations,
          slopes: slopes,
          sampleCount: updatedSamples.length,
          totalDistance: cumDist,
          minElevation: Math.min.apply(null, elevations),
          maxElevation: Math.max.apply(null, elevations),
          avgElevation: elevations.reduce(function (a, b) { return a + b; }, 0) / elevations.length,
          maxSlope: Math.max.apply(null, slopes.map(Math.abs)),
          avgSlope: slopes.reduce(function (a, b) { return a + Math.abs(b); }, 0) / slopes.length,
          rawCartographics: updatedSamples
        };

        self._showChart();
        self._showProfileLine3D();
        self._registerSidebarLayer();
      })
      .catch(function (err) {
        console.error('[剖面分析] 地形采样失败:', err);
        alert('地形采样失败，请确保已加载地形数据。\n' + err.message);
      });
  };

  /**
   * 在地图上更新剖面线（采样完成后用密集采样点替换用户原始点）
   */
  TerrainProfileAnalysis.prototype._showProfileLine3D = function () {
    if (!this.profileData) return;
    var data = this.profileData;

    var positions = data.rawCartographics.map(function (c) {
      return Cesium.Cartesian3.fromRadians(c.longitude, c.latitude, c.height);
    });

    // 不删旧实体，直接更新 polyline 属性，避免删除/重建导致的渲染抖动
    if (this.profileEntity) {
      this.profileEntity.polyline.positions = positions;
      this.profileEntity.polyline.width = 6;
      this.profileEntity.polyline.material = Cesium.Color.fromCssColorString('#FF6B35').withAlpha(0.9);
      this.profileEntity.polyline.clampToGround = true;
    } else {
      this.profileEntity = this.viewer.entities.add({
        polyline: {
          positions: positions,
          width: 6,
          material: Cesium.Color.fromCssColorString('#FF6B35').withAlpha(0.9),
          clampToGround: true,
          depthFailMaterial: Cesium.Color.fromCssColorString('#FF6B35').withAlpha(0.35)
        }
      });
    }
    console.log('[剖面分析] 3D剖面线已更新, 采样点数: ' + positions.length);
  };

  /**
   * 显示面板（不含图表数据），作为剖面分析功能窗口
   * 可重复调用，面板已存在时仅恢复显示
   */
  TerrainProfileAnalysis.prototype._showPanel = function () {
    var self = this;

    // 面板已存在 → 直接显示
    if (this.chartPanel) {
      this.chartPanel.style.display = '';
      this._updatePanelButtons();
      return;
    }

    // ── 创建面板 DOM ──
    var panel = document.createElement('div');
    panel.id = 'profileChartPanel';
    panel.style.cssText = 'position:absolute;left:calc(50% - 400px);top:60px;width:800px;height:500px;'
      + 'background:#fff;border:1px solid #ccc;z-index:99999;'
      + 'box-shadow:0 2px 12px rgba(0,0,0,0.3);resize:both;overflow:hidden;';
    document.body.appendChild(panel);

    // 头部
    var header = document.createElement('div');
    header.id = 'profileChartHeader';
    header.className = 'move';   // 拖拽由 eventBindInit.js 的 document 级委托统一处理
    header.style.cssText = 'height:40px;display:flex;justify-content:space-between;align-items:center;'
      + 'padding:6px 12px;border-bottom:1px solid #eee;cursor:move;background:#fafafa;';
    header.innerHTML = '<div style="font-weight:600;font-size:14px;">'
      + '地形剖面分析 <span id="profileStats" style="color:#999;font-weight:400;font-size:12px;"></span>'
      + '</div>'
      + '<div>'
      + '<button id="profileStartRedoBtn" style="margin-right:4px;font-size:12px;">开始分析</button>'
      + '<button id="profileExportBtn" style="margin-right:4px;font-size:12px;display:none;">导出CSV</button>'
      + '<button id="profileClearBtn" style="margin-right:4px;font-size:12px;display:none;">清除</button>'
      + '<select id="profileIntervalSelect" style="font-size:12px;margin-right:4px;display:none;">'
      + '<option value="10">采样10m</option>'
      + '<option value="30" selected>采样30m</option>'
      + '<option value="50">采样50m</option>'
      + '<option value="100">采样100m</option>'
      + '</select>'
      + '<button id="profileCloseBtn" style="font-size:12px;">关闭</button>'
      + '</div>';
    panel.appendChild(header);

    // 图表容器（初始显示占位提示）
    var chartDiv = document.createElement('div');
    chartDiv.id = 'profileChartContainer';
    chartDiv.style.cssText = 'width:100%;height:calc(100% - 40px);display:flex;align-items:center;justify-content:center;color:#999;font-size:15px;text-align:center;line-height:2;';
    chartDiv.innerHTML = '点击 <b style="color:#1890ff">开始分析</b> 在地球上绘制剖面线<br>左键添加点，右键结束绘制，Ctrl+Z 撤销';
    panel.appendChild(chartDiv);

    this.chartPanel = panel;

    // 拖拽由 eventBindInit.js 的 document 级委托统一处理（头部带 class="move" 即生效，
    // 头部内按钮/下拉框不触发拖拽的守卫也在委托 handler 里）

    // 关闭按钮 → 隐藏面板
    panel.querySelector('#profileCloseBtn').onclick = function () {
      self.chartPanel.style.display = 'none';
      if (self._highlightEntity) {
        self.viewer.entities.remove(self._highlightEntity);
        self._highlightEntity = null;
      }
    };

    // 开始分析 / 重新分析 → 统一：清除实体后开始绘制
    panel.querySelector('#profileStartRedoBtn').onclick = function () {
      self._clearEntities();
      // 重置占位文本（图表实例已由 _clearEntities → profileData=null 标记）
      var cd = panel.querySelector('#profileChartContainer');
      if (self.chartInstance) {
        self.chartInstance.dispose();
        self.chartInstance = null;
        self._chartEventsBound = false;
      }
      cd.style.cssText = 'width:100%;height:calc(100% - 40px);display:flex;align-items:center;justify-content:center;color:#999;font-size:15px;text-align:center;line-height:2;';
      cd.innerHTML = '正在等待绘制…<br>左键在地球上点击添加剖面点，右键结束';
      self._updatePanelButtons();
      self.startDrawing();
    };

    // 导出CSV
    panel.querySelector('#profileExportBtn').onclick = function () {
      self.exportCSV();
    };

    // 清除按钮 → 清除实体、图表和面板
    panel.querySelector('#profileClearBtn').onclick = function () {
      self.clearAll();
      self._chartEventsBound = false;
      // 面板回退到占位状态
      self._showPanel();
    };

    // 采样间距切换
    panel.querySelector('#profileIntervalSelect').onchange = function () {
      self.sampleInterval = Number(this.value);
      self._analyzeProfile();
    };

    // 鼠标离开整个面板时清除指示点
    panel.addEventListener('mouseleave', function () {
      if (self.chartInstance && self.profileData) {
        var d = self.profileData;
        var elevData = d.distances.map(function (dist, i) { return [dist, d.elevations[i]]; });
        var slopeData = d.distances.map(function (dist, i) { return [dist, d.slopes[i]]; });
        self.chartInstance.setOption({
          series: [
            { data: elevData },
            { data: slopeData },
            { data: [] },
            { data: [] }
          ]
        });
      }
    });
  };

  /**
   * 根据当前数据状态更新面板按钮显隐和文字
   */
  TerrainProfileAnalysis.prototype._updatePanelButtons = function () {
    var panel = this.chartPanel;
    if (!panel) return;
    var hasData = !!this.profileData;
    var startBtn = panel.querySelector('#profileStartRedoBtn');
    var exportBtn = panel.querySelector('#profileExportBtn');
    var clearBtn = panel.querySelector('#profileClearBtn');
    var intervalSel = panel.querySelector('#profileIntervalSelect');
    var statsSpan = panel.querySelector('#profileStats');

    if (startBtn) startBtn.textContent = hasData ? '重新分析' : '开始分析';
    if (exportBtn) exportBtn.style.display = hasData ? '' : 'none';
    if (clearBtn) clearBtn.style.display = hasData ? '' : 'none';
    if (intervalSel) intervalSel.style.display = hasData ? '' : 'none';
    if (statsSpan && !hasData) statsSpan.textContent = '';
  };

  /**
   * 显示/更新 ECharts 剖面图
   * 先确保面板存在，再初始化/更新图表数据
   */
  TerrainProfileAnalysis.prototype._showChart = function () {
    if (!this.profileData) return;
    var data = this.profileData;
    var self = this;

    // 确保面板存在且可见
    this._showPanel();

    var panel = this.chartPanel;
    var chartDiv = panel.querySelector('#profileChartContainer');

    // 更新统计信息
    var statsSpan = panel.querySelector('#profileStats');
    if (statsSpan) {
      statsSpan.textContent = '总长: ' + data.totalDistance.toFixed(0) + 'm | '
        + '最高: ' + data.maxElevation.toFixed(1) + 'm | '
        + '最大坡度: ' + data.maxSlope.toFixed(1) + '° | '
        + '平均坡度: ' + data.avgSlope.toFixed(1) + '°';
    }

    // 更新采样间距下拉
    var selectEl = panel.querySelector('#profileIntervalSelect');
    if (selectEl) selectEl.value = String(this.sampleInterval);

    // 更新按钮状态（有数据 → 显示导出/清除/采样）
    this._updatePanelButtons();

    // ── 初始化 / 更新 ECharts ──
    var chart = this.chartInstance;
    if (!chart) {
      // 清除占位文本，恢复图表容器样式
      chartDiv.innerHTML = '';
      chartDiv.style.cssText = 'width:100%;height:calc(100% - 40px);';
      chart = echarts.init(chartDiv);
      this.chartInstance = chart;
      console.log('[剖面分析] ECharts 实例已初始化');
    }

    var elevationData = data.distances.map(function (d, i) { return [d, data.elevations[i]]; });
    var slopeData = data.distances.map(function (d, i) { return [d, data.slopes[i]]; });
    console.log('[剖面分析] 图表数据: ' + elevationData.length + ' 点, 首=[' + elevationData[0][0].toFixed(0) + ',' + elevationData[0][1].toFixed(1) + '], 末=[' + elevationData[elevationData.length - 1][0].toFixed(0) + ',' + elevationData[elevationData.length - 1][1].toFixed(1) + ']');

    var option = {
      title: { text: '', left: 'center' },
      tooltip: {
        trigger: 'axis',
        formatter: function (params) {
          var dist = Number(params[0].axisValue);
          var lines = [];
          for (var i = 0; i < params.length; i++) {
            var p = params[i];
            var val = Array.isArray(p.value) ? p.value[1] : p.value;
            lines.push(p.marker + ' ' + p.seriesName + ': ' + (typeof val === 'number' ? val.toFixed(3) : val));
          }
          return '距离: ' + dist.toFixed(3) + ' m<br/>' + lines.join('<br/>');
        }
      },
      legend: { data: ['高程(m)', '坡度(°)'], top: 5 },
      grid: [
        { left: 60, right: 40, top: 50, height: '40%' },
        { left: 60, right: 40, top: '62%', height: '30%' }
      ],
      xAxis: [
        { type: 'value', name: '距离(m)', nameLocation: 'center', nameGap: 30, gridIndex: 0, axisLabel: { show: false } },
        { type: 'value', name: '距离(m)', nameLocation: 'center', nameGap: 30, gridIndex: 1 }
      ],
      yAxis: [
        { type: 'value', name: '高程(m)', gridIndex: 0, min: Math.max(0, Math.floor((data.minElevation - 500) / 100) * 100) },
        { type: 'value', name: '坡度(°)', gridIndex: 1 }
      ],
      dataZoom: [
        { type: 'slider', xAxisIndex: [0, 1], bottom: 5, height: 20 },
        { type: 'inside', xAxisIndex: [0, 1] }
      ],
      series: [
        {
          name: '高程(m)', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: elevationData,
          smooth: true, symbol: 'none', lineStyle: { color: '#1890ff', width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(24,144,255,0.3)' },
              { offset: 1, color: 'rgba(24,144,255,0.02)' }
            ])
          },
          markLine: {
            silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: '#aaa' },
            data: [
              { yAxis: data.minElevation, label: { formatter: '最低: {c}m' } },
              { yAxis: data.maxElevation, label: { formatter: '最高: {c}m' } }
            ]
          }
        },
        {
          name: '坡度(°)', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: slopeData,
          smooth: true, symbol: 'none', lineStyle: { color: '#ff4d4f', width: 1.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(255,77,79,0.25)' },
              { offset: 1, color: 'rgba(255,77,79,0.02)' }
            ])
          }
        },
        { name: '高程指示', type: 'scatter', xAxisIndex: 0, yAxisIndex: 0, data: [], symbolSize: 12, symbol: 'circle', itemStyle: { color: '#1890ff', borderColor: '#fff', borderWidth: 2 }, z: 10, silent: true, tooltip: { show: false } },
        { name: '坡度指示', type: 'scatter', xAxisIndex: 1, yAxisIndex: 1, data: [], symbolSize: 12, symbol: 'circle', itemStyle: { color: '#ff4d4f', borderColor: '#fff', borderWidth: 2 }, z: 10, silent: true, tooltip: { show: false } }
      ]
    };

    chart.setOption(option, { notMerge: true });

    // 缓存线系列数据数组，供鼠标事件复用
    this._cachedElevData = elevationData;
    this._cachedSlopeData = slopeData;

    // ── 只在首次初始化时绑定交互事件 ──
    if (!this._chartEventsBound) {
      this._chartEventsBound = true;

      // 二分查找最近数据点
      function findNearestIndex(sortedDist, target) {
        if (target <= sortedDist[0]) return 0;
        if (target >= sortedDist[sortedDist.length - 1]) return sortedDist.length - 1;
        var lo = 0, hi = sortedDist.length - 1;
        while (lo < hi) { var mid = (lo + hi) >> 1; if (sortedDist[mid] < target) lo = mid + 1; else hi = mid; }
        if (lo > 0 && Math.abs(sortedDist[lo - 1] - target) < Math.abs(sortedDist[lo] - target)) return lo - 1;
        return lo;
      }

      var zr = chart.getZr();

      // 鼠标悬停 → 指示圆点（RAF 节流 + 仅在索引变化时更新，保留 tooltip）
      var _rafId = null;
      var _lastIdx = -1;
      zr.on('mousemove', function (zrEvent) {
        var d = self.profileData;
        if (!d || !d.distances.length) return;
        var evt = zrEvent.event;
        if (!evt) return;
        if (_rafId) return;
        _rafId = requestAnimationFrame(function () {
          _rafId = null;
          var rect = chartDiv.getBoundingClientRect();
          var rx = evt.clientX - rect.left;
          var ry = evt.clientY - rect.top;
          if (rx < 55 || rx > rect.width - 35 || ry < 45 || ry > rect.height - 45) {
            if (_lastIdx !== -1) {
              _lastIdx = -1;
              chart.setOption({
                series: [
                  { data: self._cachedElevData },
                  { data: self._cachedSlopeData },
                  { data: [] },
                  { data: [] }
                ]
              });
            }
            return;
          }
          var pg = chart.convertFromPixel({ gridIndex: 0 }, [rx, ry]);
          if (!pg || isNaN(pg[0])) {
            if (_lastIdx !== -1) {
              _lastIdx = -1;
              chart.setOption({
                series: [
                  { data: self._cachedElevData },
                  { data: self._cachedSlopeData },
                  { data: [] },
                  { data: [] }
                ]
              });
            }
            return;
          }
          var idx = findNearestIndex(d.distances, pg[0]);
          if (idx === _lastIdx) return; // 索引未变，不触发 setOption，tooltip 保持显示
          _lastIdx = idx;
          chart.setOption({
            series: [
              { data: self._cachedElevData },
              { data: self._cachedSlopeData },
              { data: [[d.distances[idx], d.elevations[idx]]] },
              { data: [[d.distances[idx], d.slopes[idx]]] }
            ]
          });
        });
      });

      // 点击 → 地图高亮
      zr.on('click', function (zrEvent) {
        var d = self.profileData;
        if (!d || !d.distances.length) return;
        var evt = zrEvent.event;
        if (!evt) return;
        var rect = chartDiv.getBoundingClientRect();
        var rx = evt.clientX - rect.left;
        var ry = evt.clientY - rect.top;
        if (rx < 55 || rx > rect.width - 35 || ry < 45 || ry > rect.height - 45) return;
        var pg = chart.convertFromPixel({ gridIndex: 0 }, [rx, ry]);
        if (!pg || isNaN(pg[0])) return;
        var idx = findNearestIndex(d.distances, pg[0]);
        if (idx < 0 || idx >= d.rawCartographics.length) return;

        var carto = d.rawCartographics[idx];
        var pos = Cesium.Cartesian3.fromRadians(carto.longitude, carto.latitude, carto.height);

        if (self._highlightEntity) {
          self.viewer.entities.remove(self._highlightEntity);
        }
        self._highlightEntity = self.viewer.entities.add({
          position: pos,
          billboard: {
            image: self._createMarkerCanvas('#FF00FF', 16),
            verticalOrigin: Cesium.VerticalOrigin.CENTER,
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
          },
          label: {
            text: '距离: ' + d.distances[idx].toFixed(0) + 'm\n'
              + '高程: ' + d.elevations[idx].toFixed(1) + 'm\n'
              + '坡度: ' + d.slopes[idx].toFixed(1) + '°',
            font: '14px sans-serif', fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK, outlineWidth: 2,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.TOP,
            pixelOffset: new Cesium.Cartesian2(0, 16),
            disableDepthTestDistance: Number.POSITIVE_INFINITY
          }
        });
        self.viewer.flyTo(self._highlightEntity, {
          duration: 1.5,
          offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-60), 500)
        });
      });

      // ResizeObserver
      var ro = new ResizeObserver(function () { chart.resize(); });
      ro.observe(panel);
    }

    chart.resize();
  };

  /**
   * 关闭/销毁图表面板
   */
  TerrainProfileAnalysis.prototype._closeChart = function () {
    if (this.chartInstance) {
      this.chartInstance.dispose();
      this.chartInstance = null;
    }
    if (this.chartPanel) {
      try { this.chartPanel.remove(); } catch (_) {}
      this.chartPanel = null;
    }
    this._chartEventsBound = false;
    this._cachedElevData = null;
    this._cachedSlopeData = null;
  };

  /**
   * 将剖面分析实体注册到侧边栏 Analysis 分组
   */
  TerrainProfileAnalysis.prototype._registerSidebarLayer = function () {
    var sm = window.sidebarManager;
    if (!sm) return;

    // 先移除旧图层
    this._removeSidebarLayer();

    // 收集所有剖面相关实体，构造成 { primitive } 条目供侧边栏管理
    var items = [];
    var self = this;
    this.markerEntities.forEach(function (e, i) {
      if (e) items.push({ name: '剖面点 ' + (i + 1), primitive: e });
    });
    if (this.profileEntity) {
      items.push({ name: '剖面线', primitive: this.profileEntity });
    }

    if (items.length === 0) return;

    // 使用已加载的地形数据命名
    var name = '剖面分析';
    if (this.profileData) {
      name += ' ' + this.profileData.totalDistance.toFixed(0) + 'm';
    }

    this._sidebarLayerId = sm.addLayer({
      type: 'Analysis',
      name: name,
      cesiumObject: items,
      extras: { analysisLayerId: 'terrainProfile' }
    });
    console.log('[剖面分析] 已注册到侧边栏, layerId=' + this._sidebarLayerId);
  };

  /**
   * 从侧边栏移除剖面分析图层
   */
  TerrainProfileAnalysis.prototype._removeSidebarLayer = function () {
    var sm = window.sidebarManager;
    if (sm && this._sidebarLayerId != null) {
      sm.removeLayer(this._sidebarLayerId);
      this._sidebarLayerId = null;
    }
  };

  /**
   * 创建 Canvas 标记图标（用于地图高亮）
   */
  TerrainProfileAnalysis.prototype._createMarkerCanvas = function (colorHex, size) {
    size = size || 16;
    var canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    var ctx = canvas.getContext('2d');
    var r = size / 2;

    // 外圈半透明光晕
    var glow = ctx.createRadialGradient(r, r, r * 0.5, r, r, r);
    glow.addColorStop(0, colorHex);
    glow.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = glow;
    ctx.beginPath();
    ctx.arc(r, r, r, 0, 2 * Math.PI);
    ctx.fill();

    // 实心圆
    ctx.fillStyle = colorHex;
    ctx.beginPath();
    ctx.arc(r, r, r * 0.5, 0, 2 * Math.PI);
    ctx.fill();

    // 白色边框
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(r, r, r * 0.5, 0, 2 * Math.PI);
    ctx.stroke();

    return canvas.toDataURL();
  };

  /**
   * 导出剖面数据为 CSV
   */
  TerrainProfileAnalysis.prototype.exportCSV = function () {
    if (!this.profileData) {
      alert('请先完成剖面分析');
      return;
    }
    var data = this.profileData;
    var lines = ['距离(m),高程(m),坡度(°)'];
    for (var i = 0; i < data.distances.length; i++) {
      lines.push([
        data.distances[i].toFixed(2),
        data.elevations[i].toFixed(2),
        data.slopes[i].toFixed(4)
      ].join(','));
    }
    var blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = '剖面数据_' + new Date().toISOString().slice(0, 10) + '.csv';
    a.click();
    URL.revokeObjectURL(url);
  };

  // 挂载到全局
  global.TerrainProfileAnalysis = TerrainProfileAnalysis;
})(window);
