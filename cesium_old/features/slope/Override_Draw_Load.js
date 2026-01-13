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
            if (!cell || cell.length === 0) continue;
            const lon = Number(cell[2] && cell[2][0]);
            const lat = Number(cell[2] && cell[2][1]);
            if (!isFinite(lon) || !isFinite(lat)) continue;

            // 确保有原始备份，方便恢复
            if (cell._origSlope === undefined) cell._origSlope = cell[1];
            if (cell._origSlopeCost === undefined) cell._origSlopeCost = cell[3];

            // 先恢复为基于坡度的默认值（避免多次叠加）
            cell[1] = cell._origSlope;
            cell[3] = cell._origSlopeCost;

            // 后添加的覆盖区优先级更高（覆盖数组按加入顺序保存）
            for (let k = 0; k < this.overrideAreas.length; k++) {
                const area = this.overrideAreas[k];
                if (!area || !area.coords) continue;
                if (this._pointInPolygon(lon, lat, area.coords)) {
                    if (area.type === "road") {
                        // road 等效为坡度 = 0（极易通行），并把 slopeCost 设为一个很大值以降低代价
                        cell[1] = 0; // 等效坡度0
                        cell[3] = Math.max(cell[3] || 1, 1000.0); // 增大代价因子，使通行更容易
                    } else if (area.type === "water") {
                        // water 等效为坡度极大（不可通行），使 slopeCost 极小 -> 代价极大
                        cell[1] = 999999; // 表示坡度极大（用于显示或其它逻辑）
                        cell[3] = 1e-6; // 极小的通行能力，GetCost 会返回非常大的代价
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
            if (!cell || cell.length === 0) continue;
            const slope = Number(cell[1]);
            if (!isFinite(slope)) { cell[3] = 1e-6; continue; }
            // 复用你原来在 FindPath 中的坡度->代价转换（用 Math.pow 替换 ^）
            if (slope <= 5) {
                cell[3] = 10 * 1;
            } else if (slope > 5 && slope <= 9) {
                cell[3] = (10 * (Math.pow(0.02 * (slope - 5), 3) - 3.183 * slope + 41.1103) / 25.18);
            } else if (slope > 9 && slope <= 22) {
                cell[3] = (10 * ((0.45 * Math.pow(22 - slope, 3) + 0.11 * Math.pow(9 - slope, 3)) / 78 + 0.653 * slope - 4.905) / 25.18);
            } else if (slope > 22 && slope <= 35) {
                cell[3] = (10 * ((0.11 * Math.pow(slope - 35, 3)) / 78 - 0.728 * slope + 25.490) / 25.18);
            } else {
                cell[3] = 1e-6;
            }
            // 同步原始备份
            cell._origSlopeCost = cell[3];
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