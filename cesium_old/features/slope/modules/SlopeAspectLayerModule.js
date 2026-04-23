(function (global) {
  "use strict";

  /**
   * SlopeAspectLayerModule
   *
   * 统一管理分析图层（primitive/entity）：
   * - 注册/注销
   * - 显隐切换
   * - 层级置顶
   * - 与 SidebarManager 同步
   */
  var LayerModule = {
    /**
     * 注册图层元信息。
     * @param {string} layerId 图层唯一 ID。
     * @param {string} layerName 图层显示名。
     * @param {'primitive'|'entity'} type 图层类型。
     * @param {Array|Object} items 图层承载对象。
     * @returns {boolean}
     */
    registerLayer: function (layerId, layerName, type, items) {
      if (!layerId || !layerName || !type) {
        console.warn('注册图层失败：参数不完整');
        return false;
      }

      if (this.layerRegistry[layerId]) {
        console.warn('图层 ' + layerId + ' 已存在，将更新其内容');
      } else {
        this.layerOrder.push(layerId);
      }

      this.layerRegistry[layerId] = {
        name: layerName,
        type: type,
        items: items,
        visible: true,
        registered: new Date().toISOString(),
      };

      if (
        global.sidebarManager &&
        type === 'primitive' &&
        (layerId === 'slope' || layerId === 'aspect' || layerId === 'cost' || layerId.indexOf('cost_land_') === 0)
      ) {
        this._syncLayerToSidebar(layerId, layerName, items);
      }

      return true;
    },

    /**
     * 将分析图层同步到侧边栏树。
     *
     * 约定：通过 extras._sidebarKey 做幂等更新，避免重复创建同名图层项。
     */
    _syncLayerToSidebar: function (layerId, layerName, items) {
      if (!global.sidebarManager) return;

      var bounds = this._getAnalysisBounds();
      var sidebarKey = '_analysis_' + layerId;
      var existing = global.sidebarManager.layers.find(function (l) {
        return l.extras && l.extras._sidebarKey === sidebarKey;
      });

      if (existing) {
        existing.cesiumObject = items;
        existing.extras._colorCache = null;
      } else {
        global.sidebarManager.addLayer({
          name: layerName,
          type: 'Analysis',
          cesiumObject: items,
          extras: {
            _sidebarKey: sidebarKey,
            analysisLayerId: layerId,
            bounds: bounds,
          },
        });
      }
    },

    /**
     * 从 slopeCostGrid 估算当前分析区域经纬度包围盒。
     * @returns {{west:number,south:number,east:number,north:number}|null}
     */
    _getAnalysisBounds: function () {
      if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) return null;
      var minLon = Infinity;
      var maxLon = -Infinity;
      var minLat = Infinity;
      var maxLat = -Infinity;

      for (var i = 0; i < this.slopeCostGrid.length; i++) {
        for (var j = 0; j < this.slopeCostGrid[i].length; j++) {
          var cell = this.slopeCostGrid[i][j];
          if (!cell || !cell.degreeCoordinate) continue;
          var lon = cell.degreeCoordinate[0];
          var lat = cell.degreeCoordinate[1];
          if (lon < minLon) minLon = lon;
          if (lon > maxLon) maxLon = lon;
          if (lat < minLat) minLat = lat;
          if (lat > maxLat) maxLat = lat;
        }
      }

      if (!isFinite(minLon)) return null;
      return { west: minLon, south: minLat, east: maxLon, north: maxLat };
    },

    /**
     * 注销图层并同步移除侧边栏对应项。
     * @param {string} layerId 图层 ID。
     * @returns {boolean}
     */
    unregisterLayer: function (layerId) {
      if (!this.layerRegistry[layerId]) {
        console.warn('图层 ' + layerId + ' 不存在');
        return false;
      }

      delete this.layerRegistry[layerId];

      var index = this.layerOrder.indexOf(layerId);
      if (index > -1) {
        this.layerOrder.splice(index, 1);
      }

      if (layerId.indexOf('cost_land_') === 0 && Array.isArray(this.landUseCostLayers)) {
        this.landUseCostLayers = this.landUseCostLayers.filter(function (x) {
          return x && x.layerId !== layerId;
        });
      }

      if (global.sidebarManager) {
        var sidebarKey = '_analysis_' + layerId;
        var sidebarLayer = global.sidebarManager.layers.find(function (l) {
          return l.extras && l.extras._sidebarKey === sidebarKey;
        });
        if (sidebarLayer) {
          var li = document.querySelector('[data-layer-id="' + sidebarLayer.id + '"]');
          if (li) li.remove();
          var idx = global.sidebarManager.layers.indexOf(sidebarLayer);
          if (idx > -1) global.sidebarManager.layers.splice(idx, 1);
        }
      }

      return true;
    },

    /**
     * 置顶图层。
     *
     * primitive: 使用 scene.primitives.raiseToTop。
     * entity: 通过 remove -> add 方式实现“后添加即在上层”。
     */
    raisePrimitiveToTop: function (layerId) {
      var layer = this.layerRegistry[layerId];
      if (!layer) {
        console.warn('图层 ' + layerId + ' 不存在，请先注册图层');
        return;
      }

      if (layer.type === 'primitive') {
        var primitives = this.viewer.scene.primitives;
        var primitiveItems = layer.items;
        if (!primitiveItems || primitiveItems.length === 0) return;
        primitiveItems.forEach(function (item) {
          if (item && item.primitive) {
            try {
              primitives.raiseToTop(item.primitive);
            } catch (e) {
              console.warn('置顶失败:', e.message);
            }
          }
        });
        return;
      }

      if (layer.type === 'entity') {
        var entities = this.viewer.entities;
        var entityItems = Array.isArray(layer.items) ? layer.items : [layer.items];
        if (!entityItems || entityItems.length === 0) return;

        var tempEntities = [];
        entityItems.forEach(function (entity) {
          if (entity && entities.contains(entity)) {
            entities.remove(entity);
            tempEntities.push(entity);
          }
        });
        tempEntities.forEach(function (entity) {
          entities.add(entity);
        });
      }
    },

    /**
     * 获取可在 UI 中展示的图层列表。
     * @returns {Array<{id:string,name:string,type:string,count:number,visible:boolean}>}
     */
    getAvailablePrimitives: function () {
      var list = [];
      this.layerOrder.forEach(function (layerId) {
        var layer = this.layerRegistry[layerId];
        if (!layer) return;

        var count = 0;
        var visible = false;

        if (layer.type === 'primitive') {
          count = Array.isArray(layer.items) ? layer.items.length : 0;
          visible = count > 0 ? (layer.items[0] && layer.items[0].primitive ? layer.items[0].primitive.show : false) : false;
        } else if (layer.type === 'entity') {
          count = Array.isArray(layer.items) ? layer.items.length : 1;
          visible = layer.visible;
        }

        if (count > 0) {
          list.push({
            id: layerId,
            name: layer.name,
            type: layer.type,
            count: count,
            visible: visible,
          });
        }
      }, this);
      return list;
    },

    /**
     * 切换图层显隐状态。
     * @param {string} layerId 图层 ID。
     */
    toggleLayerVisibility: function (layerId) {
      var layer = this.layerRegistry[layerId];
      if (!layer) {
        console.warn('图层 ' + layerId + ' 不存在');
        return;
      }

      if (layer.type === 'primitive') {
        var primitiveItems = layer.items;
        if (primitiveItems && primitiveItems.length > 0) {
          primitiveItems.forEach(function (item) {
            if (item && item.primitive) {
              item.primitive.show = !item.primitive.show;
            }
          });
          layer.visible = primitiveItems[0] && primitiveItems[0].primitive ? primitiveItems[0].primitive.show : false;
        }
        return;
      }

      if (layer.type === 'entity') {
        var entityItems = Array.isArray(layer.items) ? layer.items : [layer.items];
        entityItems.forEach(function (entity) {
          if (entity && entity.show !== undefined) {
            entity.show = !entity.show;
          }
        });
        layer.visible = !layer.visible;
      }
    },

    /**
     * 同步侧边栏复选框状态（用于坡度/坡向/代价开关联动）。
     * @param {string} analysisId slope/aspect/cost
     * @param {boolean} visible
     */
    _syncSidebarCheckbox: function (analysisId, visible) {
      if (!global.sidebarManager) return;
      var sidebarKey = '_analysis_' + analysisId;
      var layer = global.sidebarManager.layers.find(function (l) {
        return l.extras && l.extras._sidebarKey === sidebarKey;
      });
      if (layer) {
        layer.visible = visible;
        var li = document.querySelector('[data-layer-id="' + layer.id + '"]');
        if (li) {
          var cb = li.querySelector('.layer-item-checkbox');
          if (cb) cb.checked = visible;
        }
      }
    },
  };

  global.SlopeAspectLayerModule = LayerModule;
})(window);
