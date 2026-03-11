// 开始绘制覆盖区（type: 'road' 或 'water'）
SlopeAspect.prototype.startDrawOverride = function (type = 'road') {
    // 使用项目中已有的交互绘制函数 CreatePolygonOnGround(viewer, ..., callback)
    const viewer = this.viewer;
    const fillColor = type === 'road' ? Cesium.Color.YELLOW.withAlpha(0.4) : Cesium.Color.BLUE.withAlpha(0.4);
    CreatePolygonOnGround(viewer, [], { color: fillColor, outlineColor: Cesium.Color.BLACK }, (polygon) => {
        try {
            // polygon.pottingPoint 为绘制多边形的 Cartesian3 顶点数组（你的项目中已有该约定）
            const pts = polygon.pottingPoint || polygon.positions || [];
            // 转换为经纬数组 [lon, lat]
            const coords = pts.map(p => {
                const c = Cesium.Cartographic.fromCartesian(p);
                return [Cesium.Math.toDegrees(c.longitude), Cesium.Math.toDegrees(c.latitude)];
            });
            if (coords.length && (coords[0][0] !== coords[coords.length - 1]?.[0] || coords[0][1] !== coords[coords.length - 1]?.[1])) {
                coords.push(coords[0]); // 闭合环
            }
            // 添加可视实体用于展示覆盖区（保存以便清理）
            const ent = viewer.entities.add({
                polygon: {
                    hierarchy: pts,
                    material: fillColor,
                    classificationType: Cesium.ClassificationType.TERRAIN
                }
            });
            this.overrideAreas = this.overrideAreas || [];
            this.overrideAreas.push({ type: type, polygonEntity: ent, coords: coords });
            this.overrideAreaEntities.push(ent);
            
            // ==================== 自动注册到图层管理系统 ====================
            const layerId = type === 'road' ? 'roadOverride' : 'waterOverride';
            const layerName = type === 'road' ? '道路覆盖' : '水域覆盖';
            this.registerLayer(layerId, layerName, 'entity', this.overrideAreaEntities);
            // ==================== 注册结束 ====================
            
            // 应用覆盖到格网并刷新可视化
            this.applyOverridesToGrid();
        } catch (e) {
            console.error('startDrawOverride error', e);
        } finally {
            // 移除临时绘制实体（CreatePolygonOnGround 可能返回一个临时实体）
            try { viewer.entities.remove(polygon); } catch (e) { }
        }
    });
}
// 将覆盖区应用到 this.slopeCostGrid：road -> 增大 slopeCost（更易通行），water -> 设为极小（不可通行）
SlopeAspect.prototype.applyOverridesToGrid = function () {
    if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) return;
    this.overrideAreas = this.overrideAreas || [];
    // 遍历格网并检测每个格子中心是否在覆盖区内
    for (let i = 0; i < this.slopeCostGrid.length; i++) {
        for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
            const cell = this.slopeCostGrid[i][j];
            if (!cell || !cell.degreeCoordinate) continue;
            const lon = cell.degreeCoordinate[0];
            const lat = cell.degreeCoordinate[1];
            if (!isFinite(lon) || !isFinite(lat)) continue;

            // 确保有原始备份，方便恢复
            if (cell._origSlope === undefined) cell._origSlope = cell.slope;
            if (cell._origSlopeCost === undefined) cell._origSlopeCost = cell.slopeCost;

            // 先恢复为基于坡度的默认值（避免多次叠加）
            cell.slope = cell._origSlope;
            cell.slopeCost = cell._origSlopeCost;

            // 后添加的覆盖区优先级更高（覆盖数组按加入顺序保存）
            for (let k = 0; k < this.overrideAreas.length; k++) {
                const area = this.overrideAreas[k];
                if (!area || !area.coords) continue;
                if (this._pointInPolygon(lon, lat, area.coords)) {
                    if (area.type === "road") {
                        // road 等效为坡度 = 0（极易通行），slopeCost 极小使通行代价低
                        cell.slope = 0;
                        cell.slopeCost = this.distance / (25 / 3.6); // 最高速度25km/h对应最低代价
                    } else if (area.type === "water") {
                        // water 等效为坡度极大（不可通行），代价极大
                        cell.slope = 999999;
                        cell.slopeCost = 999999;
                    }
                    // 不 break：允许运行后续覆盖覆盖前面的（后画者优先）
                }
            }
        }
    }
    // 覆盖改变后，潜力场与路径缓存失效须重算
    this.potentialField = null;
}
// 在覆盖区中根据每个格子的 slope 值重新计算默认 slopeCost（用于恢复或首次计算）
SlopeAspect.prototype.recomputeSlopeCosts = function () {
    if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) return;
    for (let i = 0; i < this.slopeCostGrid.length; i++) {
        for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
            const cell = this.slopeCostGrid[i][j];
            if (!cell || !cell.degreeCoordinate) continue;
            const slope = cell.slope;
            if (!isFinite(slope)) { cell.slopeCost = 999999; continue; }
            // 与 DrawCostMap 保持一致：根据表3线性插值计算速度 → 时间代价
            let speed;
            if (slope <= 0) {
                speed = 25;
            } else if (slope <= 3) {
                speed = 25 - (25 - 20) * (slope - 0) / (3 - 0);
            } else if (slope <= 6) {
                speed = 20 - (20 - 15) * (slope - 3) / (6 - 3);
            } else if (slope <= 10) {
                speed = 15 - (15 - 12) * (slope - 6) / (10 - 6);
            } else if (slope <= 15) {
                speed = 12 - (12 - 8) * (slope - 10) / (15 - 10);
            } else if (slope <= 20) {
                speed = 8 - (8 - 5) * (slope - 15) / (20 - 15);
            } else if (slope <= 30) {
                speed = 5 - (5 - 0) * (slope - 20) / (30 - 20);
            } else {
                speed = 0;
            }
            if (speed > 0.1) {
                cell.slopeCost = this.distance / (speed / 3.6);
            } else {
                cell.slopeCost = 999999;
            }
            // 同步原始备份
            cell._origSlopeCost = cell.slopeCost;
        }
    }
    this.potentialField = null;
}
// 清除所有覆盖区（移除实体并恢复默认代价）
SlopeAspect.prototype.clearOverrideAreas = function () {
    if (this.overrideAreas && this.overrideAreas.length) {
        for (const a of this.overrideAreas) {
            try { this.viewer.entities.remove(a.polygonEntity); } catch (e) { }
        }
        this.overrideAreas = [];
        // 恢复默认 slopeCost
        this.recomputeSlopeCosts();
    }
}
// 覆盖区分析中，点在多边形内判定：优先使用 turf.booleanPointInPolygon（若加载了 turf），否则回退到射线法
SlopeAspect.prototype._pointInPolygon = function (lon, lat, polyCoords) {
    if (!polyCoords || polyCoords.length < 3) return false;
    try {
        if (typeof turf !== 'undefined' && turf.booleanPointInPolygon) {
            const pt = turf.point([lon, lat]);
            const poly = turf.polygon([polyCoords]);
            return turf.booleanPointInPolygon(pt, poly);
        }
    } catch (e) { /* ignore */ }
    // fallback: ray-casting
    let inside = false;
    for (let i = 0, j = polyCoords.length - 1; i < polyCoords.length; j = i++) {
        const xi = polyCoords[i][0], yi = polyCoords[i][1];
        const xj = polyCoords[j][0], yj = polyCoords[j][1];
        const intersect = ((yi > lat) !== (yj > lat)) && (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi);
        if (intersect) inside = !inside;
    }
    return inside;
}

// ====================================================================
//  土地覆盖类型通行代价叠加（基于KML/KMZ图层的 gridcode 字段）
// ====================================================================

/**
 * gridcode -> 土地分类映射表
 * gridcode 值对应 10 m 全球土地覆盖分类体系
 * 
 * | gridcode | Class         | 分类       | 速度系数 | 说明                           |
 * |----------|---------------|------------|----------|--------------------------------|
 * | 0        | Unclassified  | 未分类地区 | 1.0      | 无修正                         |
 * | 1        | Cropland      | 农田       | 0.9      | 平整，但有农作物轻微阻碍       |
 * | 2        | Forest        | 森林       | 0.4      | 树木密集，严重影响通行         |
 * | 3        | Shrub         | 灌木       | 0.55     | 灌木丛有一定通行阻力           |
 * | 4        | Grassland     | 草原       | 0.85     | 较为平坦开阔，通行较容易       |
 * | 5        | Water         | 水域       | 0.0      | 不可通行                       |
 * | 6        | Snow/Ice      | 冰雪       | 0.25     | 极滑，车辆几乎无法通行         |
 * | 7        | Barren        | 裸地       | 0.75     | 无植被覆盖，通行条件中等       |
 * | 8        | Impervious    | 不透水地表 | 1.2      | 道路/建筑区域，通行最佳        |
 * | 9        | Wetland       | 湿地       | 0.3      | 松软泥泞，通行非常困难         |
 */
SlopeAspect.prototype.LAND_USE_COST_TABLE = {
    0: { name: '未分类地区', nameEn: 'Unclassified', speedFactor: 1.0,  color: [255, 255, 255] },
    1: { name: '农田',       nameEn: 'Cropland',     speedFactor: 0.9,  color: [250, 227, 156] },
    2: { name: '森林',       nameEn: 'Forest',       speedFactor: 0.4,  color: [68,  111, 51]  },
    3: { name: '灌木',       nameEn: 'Shrub',        speedFactor: 0.55, color: [51,  160, 44]  },
    4: { name: '草原',       nameEn: 'Grassland',    speedFactor: 0.85, color: [171, 211, 123] },
    5: { name: '水域',       nameEn: 'Water',        speedFactor: 0.0,  color: [30,  105, 180] },
    6: { name: '冰雪',       nameEn: 'Snow/Ice',     speedFactor: 0.25, color: [166, 206, 227] },
    7: { name: '裸地',       nameEn: 'Barren',       speedFactor: 0.75, color: [207, 189, 163] },
    8: { name: '不透水地表', nameEn: 'Impervious',   speedFactor: 1.2,  color: [226, 66,  144] },
    9: { name: '湿地',       nameEn: 'Wetland',      speedFactor: 0.3,  color: [40,  155, 232] }
};

/**
 * 收集可用于土地覆盖提取的 DataSource（viewer + sidebar 注册），并去重
 * @returns {Array}
 */
SlopeAspect.prototype._collectLandUseDataSources = function () {
    const list = [];
    const seen = new Set();

    const pushDs = (ds) => {
        if (!ds) return;
        if (seen.has(ds)) return;
        if (!ds.entities || !ds.entities.values) return;
        seen.add(ds);
        list.push(ds);
    };

    const dataSources = this.viewer && this.viewer.dataSources;
    if (dataSources && typeof dataSources.length === 'number') {
        for (let i = 0; i < dataSources.length; i++) {
            pushDs(dataSources.get(i));
        }
    }

    // 兜底：某些场景对象只挂在 sidebar 图层管理中
    if (window.sidebarManager && Array.isArray(window.sidebarManager.layers)) {
        for (let i = 0; i < window.sidebarManager.layers.length; i++) {
            const layer = window.sidebarManager.layers[i];
            if (!layer) continue;
            if ((layer.type === 'KML' || layer.type === 'GeoJson' || layer.type === 'CZML') && layer.cesiumObject) {
                pushDs(layer.cesiumObject);
            }
        }
    }

    return list;
};

/**
 * 从 Entity 中提取 gridcode（优先 properties，其次 description HTML）
 * @param {Cesium.Entity} entity
 * @returns {number|null}
 */
SlopeAspect.prototype._extractGridcodeFromEntity = function (entity) {
    if (!entity) return null;
    const now = Cesium.JulianDate.now();
    let gridcode = null;

    // 1) PropertyBag 读取（常规方式）
    if (entity.properties) {
        const propNamesToTry = ['gridcode', 'GRIDCODE', 'GridCode', 'grid_code', 'GRID_CODE', 'gridCode'];
        const availableNames = Array.isArray(entity.properties.propertyNames) ? entity.properties.propertyNames : [];

        for (let i = 0; i < availableNames.length; i++) {
            const pName = availableNames[i];
            const lower = String(pName).toLowerCase();
            if (lower === 'gridcode' || lower === 'grid_code') {
                try {
                    const prop = entity.properties[pName];
                    const val = (prop && typeof prop.getValue === 'function') ? prop.getValue(now) : prop;
                    const parsed = parseInt(val, 10);
                    if (!isNaN(parsed)) return parsed;
                } catch (_) { }
            }
        }

        for (let i = 0; i < propNamesToTry.length; i++) {
            try {
                const key = propNamesToTry[i];
                const prop = entity.properties[key];
                if (prop === undefined || prop === null) continue;
                const val = (typeof prop.getValue === 'function') ? prop.getValue(now) : prop;
                const parsed = parseInt(val, 10);
                if (!isNaN(parsed)) return parsed;
            } catch (_) { }
        }

        if (typeof entity.properties.getValue === 'function') {
            try {
                const allProps = entity.properties.getValue(now);
                if (allProps) {
                    for (let i = 0; i < propNamesToTry.length; i++) {
                        const val = allProps[propNamesToTry[i]];
                        if (val === undefined || val === null) continue;
                        const parsed = parseInt(val, 10);
                        if (!isNaN(parsed)) return parsed;
                    }
                }
            } catch (_) { }
        }
    }

    // 2) description HTML 解析（你提供的 KML 就是这种形态）
    try {
        let desc = null;
        if (entity.description) {
            desc = (typeof entity.description.getValue === 'function')
                ? entity.description.getValue(now)
                : entity.description;
        }

        if (desc !== undefined && desc !== null) {
            const text = String(desc);
            // 先走正则快速提取：<td>gridcode</td><td>2</td>
            const re = /<td[^>]*>\s*gridcode\s*<\/td>\s*<td[^>]*>\s*(-?\d+)\s*<\/td>/i;
            const m = text.match(re);
            if (m && m[1] !== undefined) {
                const parsed = parseInt(m[1], 10);
                if (!isNaN(parsed)) return parsed;
            }

            // 次选：纯文本模式匹配 gridcode : 2
            const plain = text.replace(/<[^>]+>/g, ' ');
            const m2 = plain.match(/gridcode\s*[:=]?\s*(-?\d+)/i);
            if (m2 && m2[1] !== undefined) {
                const parsed = parseInt(m2[1], 10);
                if (!isNaN(parsed)) return parsed;
            }
        }
    } catch (_) { }

    return gridcode;
};

/**
 * 从已加载的 KML/KMZ DataSource 中提取包含 gridcode 字段的多边形特征
 * 
 * Cesium KmlDataSource 加载后，每个 Entity 的扩展属性（ExtendedData / SimpleData）
 * 存储在 entity.properties（一个 PropertyBag 对象）中。
 * 
 * @returns {Array} 提取的土地覆盖特征列表
 *   每个元素: { gridcode: number, coords: [[lon,lat],...], entityId: string }
 */
SlopeAspect.prototype.extractLandUseFeatures = function () {
    const features = [];
    const dataSources = this._collectLandUseDataSources();

    console.log('[SlopeAspect] === 开始提取土地覆盖特征 ===');
    console.log('[SlopeAspect] 可检查的 DataSource 数量:', dataSources.length);

    for (let dsIdx = 0; dsIdx < dataSources.length; dsIdx++) {
        const ds = dataSources[dsIdx];
        console.log('[SlopeAspect] DataSource[' + dsIdx + ']:', ds.name || '(unnamed)',
            '| 构造函数:', ds.constructor && ds.constructor.name,
            '| entities数量:', ds.entities ? ds.entities.values.length : 0);

        if (!ds.entities || !ds.entities.values || ds.entities.values.length === 0) continue;

        const entities = ds.entities.values;
        let foundInDs = 0;

        for (let i = 0; i < entities.length; i++) {
            const entity = entities[i];
            if (i < 3) {
                const names = (entity.properties && Array.isArray(entity.properties.propertyNames))
                    ? entity.properties.propertyNames.join(', ')
                    : '(无properties)';
                console.log('[SlopeAspect]   Entity[' + i + '] id:', entity.id, '| 可用属性:', names);
            }

            // 1. 提取 gridcode 值（含 description HTML 兜底）
            const gridcode = this._extractGridcodeFromEntity(entity);

            if (gridcode === null || gridcode < 0 || gridcode > 9) continue;

            // 2. 提取多边形坐标
            var coordsList = [];  // 可能有多个多边形（multiPolygon）

            if (entity.polygon && entity.polygon.hierarchy) {
                var hierarchy = entity.polygon.hierarchy.getValue(Cesium.JulianDate.now());
                if (hierarchy && hierarchy.positions) {
                    var coords = this._cartesian3ArrayToLonLat(hierarchy.positions);
                    if (coords.length >= 3) {
                        // 确保闭合
                        if (coords[0][0] !== coords[coords.length - 1][0] ||
                            coords[0][1] !== coords[coords.length - 1][1]) {
                            coords.push(coords[0]);
                        }
                        coordsList.push(coords);
                    }
                }
            }

            for (var cIdx = 0; cIdx < coordsList.length; cIdx++) {
                features.push({
                    gridcode: gridcode,
                    coords: coordsList[cIdx],
                    entityId: entity.id,
                    landUseInfo: this.LAND_USE_COST_TABLE[gridcode] || this.LAND_USE_COST_TABLE[0]
                });
                foundInDs++;
            }
        }

        console.log('[SlopeAspect] DataSource[' + dsIdx + '] "' + (ds.name || '') + '" 提取到', foundInDs, '个特征');
    }

    if (features.length === 0) {
        console.warn('[SlopeAspect] 未提取到有效特征：请确认 KMZ 已完全加载且包含 polygon。');
    }

    console.log('[SlopeAspect] === 共提取到 ' + features.length + ' 个土地覆盖多边形特征 ===');
    return features;
};

/**
 * Cartesian3 数组转 [lon, lat] 数组
 * @param {Array<Cesium.Cartesian3>} positions - Cartesian3 坐标数组
 * @returns {Array<Array<number>>} [[lon, lat], ...]
 */
SlopeAspect.prototype._cartesian3ArrayToLonLat = function (positions) {
    const result = [];
    for (let i = 0; i < positions.length; i++) {
        const carto = Cesium.Cartographic.fromCartesian(positions[i]);
        result.push([
            Cesium.Math.toDegrees(carto.longitude),
            Cesium.Math.toDegrees(carto.latitude)
        ]);
    }
    return result;
};

/**
 * 将土地覆盖类型的通行代价叠加到分析网格（slopeCostGrid）
 * 
 * 算法流程：
 * ┌─────────────────────────────────────────────────────────────────┐
 * │ 1. 从已加载的 KML/KMZ DataSource 中提取带 gridcode 的多边形     │
 * │ 2. 遍历 slopeCostGrid 每个网格单元                              │
 * │ 3. 对每个单元的中心点，检查它是否落在某个土地覆盖多边形内       │
 * │ 4. 如果命中，根据 gridcode 对应的 speedFactor 修正 slopeCost：  │
 * │    - speedFactor > 0: slopeCost = slopeCost / speedFactor       │
 * │      （因子 < 1.0 表示减速，代价升高；> 1.0 表示加速，代价降低）│
 * │    - speedFactor = 0: slopeCost = 999999（不可通行）             │
 * │ 5. 记录每个格子的土地类型信息（用于可视化和调试）               │
 * │ 6. 如果多个多边形覆盖同一格子，后处理的覆盖前面的               │
 * └─────────────────────────────────────────────────────────────────┘
 * 
 * 对代价的影响说明：
 * - slopeCost 原本是基于坡度计算的通行时间（时间 = 距离 / 速度）
 * - speedFactor 是一个速度乘数系数：
 *   · 森林(0.4): 实际速度 = 基础速度 × 0.4 → 时间代价 = 原代价 / 0.4 = 2.5倍
 *   · 水域(0.0): 不可通行 → 999999
 *   · 道路(1.2): 实际速度 = 基础速度 × 1.2 → 时间代价 = 原代价 / 1.2 ≈ 0.83倍
 * 
 * @returns {Object} 统计信息 { totalCells, modifiedCells, landUseStats }
 */
SlopeAspect.prototype.applyLandUseCostToGrid = function () {
    if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) {
        console.warn('[SlopeAspect] 请先计算区域坡度并生成代价网格！');
        alert('请先计算区域坡度！');
        return null;
    }

    // 1. 提取土地覆盖特征
    const features = this.extractLandUseFeatures();
    if (features.length === 0) {
        console.warn('[SlopeAspect] 未找到包含 gridcode 字段的 KML/KMZ 图层');
        alert('未找到包含 gridcode 字段的 KML/KMZ 图层。\n请先加载包含土地覆盖分类（gridcode）的 KMZ 文件。');
        return null;
    }

    // 2. 构建 turf 多边形集合（预处理，避免重复创建）
    const turfFeatures = [];
    for (let f = 0; f < features.length; f++) {
        try {
            const poly = turf.polygon([features[f].coords]);
            turfFeatures.push({
                polygon: poly,
                gridcode: features[f].gridcode,
                info: features[f].landUseInfo
            });
        } catch (e) {
            console.warn(`[SlopeAspect] 跳过无效多边形: ${e.message}`);
        }
    }

    if (turfFeatures.length === 0) {
        alert('提取的多边形均无效，请检查 KMZ 数据');
        return null;
    }

    // 3. 遍历网格，逐格判断土地覆盖类型
    const stats = {};  // gridcode -> count
    let modifiedCells = 0;
    let totalCells = 0;

    console.time('[SlopeAspect] 土地覆盖代价叠加');

    for (let i = 0; i < this.slopeCostGrid.length; i++) {
        for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
            const cell = this.slopeCostGrid[i][j];
            if (!cell || cell.length === 0 || !cell.degreeCoordinate) continue;
            totalCells++;

            const lon = cell.degreeCoordinate[0];
            const lat = cell.degreeCoordinate[1];
            if (!isFinite(lon) || !isFinite(lat)) continue;

            // 备份原始值（首次）
            if (cell._origSlopeCost_land === undefined) {
                cell._origSlopeCost_land = cell.slopeCost;
            }

            // 恢复为坡度基础代价（避免多次叠加）
            cell.slopeCost = cell._origSlopeCost_land;
            cell.landUseType = null;

            // 逐个多边形检测（后者覆盖前者）
            const pt = turf.point([lon, lat]);
            for (let f = 0; f < turfFeatures.length; f++) {
                try {
                    if (turf.booleanPointInPolygon(pt, turfFeatures[f].polygon)) {
                        const info = turfFeatures[f].info;
                        const gridcode = turfFeatures[f].gridcode;

                        if (info.speedFactor <= 0) {
                            // 不可通行（水域、冰雪极端等）
                            cell.slopeCost = 999999;
                        } else {
                            // 速度系数修正：代价 = 原代价 / speedFactor
                            cell.slopeCost = cell._origSlopeCost_land / info.speedFactor;
                        }

                        cell.landUseType = {
                            gridcode: gridcode,
                            name: info.name,
                            nameEn: info.nameEn,
                            speedFactor: info.speedFactor
                        };
                        // 不 break：后覆盖的特征优先级更高
                    }
                } catch (e) {
                    // 跳过判断失败的情况
                }
            }

            if (cell.landUseType) {
                modifiedCells++;
                const gc = cell.landUseType.gridcode;
                stats[gc] = (stats[gc] || 0) + 1;
            }
        }
    }

    console.timeEnd('[SlopeAspect] 土地覆盖代价叠加');

    // 4. 输出统计信息
    const result = { totalCells, modifiedCells, landUseStats: stats };
    console.log('[SlopeAspect] 土地覆盖代价叠加完成:', result);
    console.log('[SlopeAspect] 各类型网格数量:');
    for (const gc in stats) {
        const info = this.LAND_USE_COST_TABLE[gc];
        console.log(`  gridcode=${gc} (${info.name}): ${stats[gc]} 格`);
    }

    // 5. 使潜力场缓存失效
    this.potentialField = null;

    // 6. 重新绘制代价图（保留历史叠加结果，便于对比）
    const overlayMeta = this._refreshCostMapAfterLandUse({
        appendOverlay: true,
        landUseStats: stats
    });

    const layerTip = overlayMeta ? `\n已新增图层：${overlayMeta.layerName}` : '';
    alert(`土地覆盖代价叠加完成！\n共 ${totalCells} 个网格，其中 ${modifiedCells} 个受到土地类型影响。${layerTip}`);
    return result;
};

/**
 * 构建土地因素叠加图层元信息
 * 命名规则：原始代价图层名 + 土地代号 gridcode
 * 例如：代价图层+gridcode(2,5,8)
 */
SlopeAspect.prototype._buildLandUseCostLayerMeta = function (landUseStats) {
    const stats = landUseStats || {};
    const gridcodes = Object.keys(stats)
        .map(function (k) { return parseInt(k, 10); })
        .filter(function (v) { return !isNaN(v); })
        .sort(function (a, b) { return a - b; });

    const gridcodeText = gridcodes.length > 0 ? gridcodes.join(',') : 'none';
    const layerName = '代价图层+gridcode(' + gridcodeText + ')';

    this.landUseCostLayerCounter = (this.landUseCostLayerCounter || 0) + 1;
    const layerId = 'cost_land_' + this.landUseCostLayerCounter + '_' + (gridcodes.length > 0 ? gridcodes.join('_') : 'none');

    return {
        layerId: layerId,
        layerName: layerName,
        gridcodes: gridcodes
    };
};

/**
 * 土地覆盖叠加后刷新代价图可视化
 * 清除旧代价 primitive，重新调用 calculateCostColor + createCostInstance
 */
SlopeAspect.prototype._refreshCostMapAfterLandUse = function (options) {
    options = options || {};

    // 叠加模式：新增一个独立代价图层快照，不覆盖已有图层
    if (options.appendOverlay) {
        const slopeCostColorGrid = this.calculateCostColor([]);
        const meta = this._buildLandUseCostLayerMeta(options.landUseStats || {});
        const overlayPolygons = [];

        this.createCostInstance(slopeCostColorGrid, {
            targetPolygons: overlayPolygons,
            layerId: meta.layerId,
            layerName: meta.layerName
        });

        if (overlayPolygons.length > 0) {
            overlayPolygons.forEach(function (element) {
                if (element && element.primitive) element.primitive.show = true;
            });
            this.landUseCostLayers = this.landUseCostLayers || [];
            this.landUseCostLayers.push({
                layerId: meta.layerId,
                layerName: meta.layerName,
                polygons: overlayPolygons,
                gridcodes: meta.gridcodes
            });
            return meta;
        }
        return null;
    }

    // 非叠加模式：重建基础代价图层（cost）
    if (this.costPolygons && this.costPolygons.length > 0) {
        this.costPolygons.forEach(item => {
            try {
                this.viewer.scene.primitives.remove(item.primitive);
            } catch (e) { }
        });
        this.costPolygons = [];
        if (this.layerRegistry && this.layerRegistry['cost']) {
            this.unregisterLayer('cost');
        }
    }

    const slopeCostColorGrid = this.calculateCostColor([]);
    this.createCostInstance(slopeCostColorGrid, {
        targetPolygons: this.costPolygons,
        layerId: 'cost',
        layerName: '代价图层'
    });

    if (this.costPolygons && this.costPolygons.length > 0) {
        this.costPolygons.forEach(element => {
            element.primitive.show = true;
        });
    }
    return null;
};

/**
 * 清除所有土地叠加生成的代价图层（保留基础代价图）
 */
SlopeAspect.prototype._clearLandUseOverlayLayers = function () {
    if (!Array.isArray(this.landUseCostLayers) || this.landUseCostLayers.length === 0) return;

    const layerIds = this.landUseCostLayers.map(function (layer) {
        return layer && layer.layerId;
    }).filter(function (id) { return !!id; });

    for (let i = 0; i < layerIds.length; i++) {
        const layerId = layerIds[i];

        if (this.layerRegistry && this.layerRegistry[layerId] && Array.isArray(this.layerRegistry[layerId].items)) {
            this.layerRegistry[layerId].items.forEach(item => {
                if (item && item.primitive) {
                    try { this.viewer.scene.primitives.remove(item.primitive); } catch (e) { }
                }
            });
        }

        this.unregisterLayer(layerId);
    }

    this.landUseCostLayers = [];
};

/**
 * 清除土地覆盖代价叠加效果（恢复到纯坡度代价）
 */
SlopeAspect.prototype.clearLandUseCost = function () {
    if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) return;

    for (let i = 0; i < this.slopeCostGrid.length; i++) {
        for (let j = 0; j < this.slopeCostGrid[i].length; j++) {
            const cell = this.slopeCostGrid[i][j];
            if (!cell || cell.length === 0) continue;
            if (cell._origSlopeCost_land !== undefined) {
                cell.slopeCost = cell._origSlopeCost_land;
                delete cell._origSlopeCost_land;
            }
            delete cell.landUseType;
        }
    }

    this.potentialField = null;
    this._clearLandUseOverlayLayers();
    this._refreshCostMapAfterLandUse();
    console.log('[SlopeAspect] 已清除土地覆盖代价叠加');
};