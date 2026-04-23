/**
 * SidebarManager.js - 仿谷歌地球侧边栏管理器
 * 
 * 功能：
 * 1. 搜索地点（调用 Cesium 内置 Geocoder 服务 + 经纬度解析）
 * 2. 图层管理（管理通过数据加载功能加载的所有图层）
 * 
 * 图层分组：
 *   - My Places：KML, GeoJSON, CZML 等矢量数据
 *   - Terrain：地形数据
 *   - Imagery：Tiff 等影像数据
 *   - 3D Models：3DTiles, GLTF, GLB 模型数据
 * 
 * 使用方式：
 *   在 earthInit() 之后初始化：
 *   window.sidebarManager = new SidebarManager(viewer);
 */

class SidebarManager {
    /**
     * @param {Cesium.Viewer} viewer - Cesium Viewer 实例
     */
    constructor(viewer) {
        this.viewer = viewer;

        // ==================== 图层存储 ====================
        // 每个图层对象结构：
        // {
        //   id: 唯一标识,
        //   name: 显示名称,
        //   type: 数据类型（Terrain/KML/GeoJson/CZML/Tileset/Gltf/GLB/Tiff）,
        //   group: 所属分组（myPlaces/terrain/imagery/models）,
        //   visible: 是否可见,
        //   cesiumObject: Cesium 对象引用（dataSource / entity / tileset / imageryLayer / terrainProvider）,
        //   extras: 额外信息（如遮罩 entity、事件处理器等）
        // }
        this.layers = [];
        this.layerIdCounter = 0;   // 图层 ID 自增计数器
        this.selectedLayerId = null; // 当前选中的图层 ID

        // ==================== 搜索历史 ====================
        this.searchHistory = [];
        this.maxSearchHistory = 10;

        // ==================== 初始化 ====================
        this._initSidebarToggle();
        this._initSearchEvents();
        this._initLayerGroupEvents();
        this._initAddLayerButton();
        this._initOpacitySlider();

        console.log('[SidebarManager] 侧边栏管理器初始化完成');
    }

    // ====================================================================
    //  一、侧边栏折叠/展开
    // ====================================================================

    /**
     * 初始化侧边栏折叠/展开按钮事件
     */
    _initSidebarToggle() {
        const sidebar = document.getElementById('sidebar');
        const toggleBtn = document.getElementById('sidebarToggleBtn');

        if (!toggleBtn || !sidebar) return;

        toggleBtn.addEventListener('click', () => {
            const isCollapsed = sidebar.classList.toggle('collapsed');
            toggleBtn.classList.toggle('collapsed', isCollapsed);
        });
    }

    // ====================================================================
    //  二、搜索地点功能
    // ====================================================================

    /**
     * 初始化搜索相关事件绑定
     */
    _initSearchEvents() {
        const searchInput = document.getElementById('sidebarSearchInput');
        const searchBtn = document.getElementById('sidebarSearchBtn');

        if (!searchInput || !searchBtn) return;

        // 点击搜索按钮
        searchBtn.addEventListener('click', () => {
            this._performSearch(searchInput.value.trim());
        });

        // 回车搜索
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this._performSearch(searchInput.value.trim());
            }
        });
    }

    /**
     * 执行搜索
     * 支持两种方式：
     *   1. 经纬度格式（如 "101.5, 30.2" 或 "101.5 30.2"）→ 直接飞入
     *   2. 地名搜索 → 调用 Cesium Ion Geocoder 服务
     * @param {string} query - 搜索关键词
     */
    async _performSearch(query) {
        if (!query) return;

        const resultsList = document.getElementById('sidebarSearchResults');
        resultsList.innerHTML = '<li style="color:#666; padding:8px;">搜索中...</li>';

        // 尝试解析为经纬度坐标
        const coords = this._parseCoordinates(query);
        if (coords) {
            this._flyToLocation(coords.lng, coords.lat, coords.name || `${coords.lng.toFixed(4)}, ${coords.lat.toFixed(4)}`);
            this._addSearchResult(resultsList, `📍 ${coords.lng.toFixed(4)}, ${coords.lat.toFixed(4)}`, coords.lng, coords.lat);
            return;
        }

        // 地名搜索：使用 Cesium IonGeocoderService
        try {
            const geocoderService = new Cesium.IonGeocoderService({ scene: this.viewer.scene });
            const results = await geocoderService.geocode(query);

            resultsList.innerHTML = '';

            if (results.length === 0) {
                resultsList.innerHTML = '<li style="color:#888; padding:8px;">未找到结果</li>';
                return;
            }

            // 显示搜索结果
            results.forEach((result, index) => {
                const dest = result.destination;
                let lng, lat;

                // destination 可能是 Cartesian3 或 Rectangle
                if (dest instanceof Cesium.Rectangle) {
                    lng = Cesium.Math.toDegrees((dest.west + dest.east) / 2);
                    lat = Cesium.Math.toDegrees((dest.south + dest.north) / 2);
                } else {
                    const carto = Cesium.Cartographic.fromCartesian(dest);
                    lng = Cesium.Math.toDegrees(carto.longitude);
                    lat = Cesium.Math.toDegrees(carto.latitude);
                }

                const name = result.displayName || query;
                this._addSearchResult(resultsList, name, lng, lat, result.destination);
            });

            // 自动飞入第一个结果
            if (results.length > 0) {
                const firstDest = results[0].destination;
                this.viewer.camera.flyTo({ destination: firstDest });
            }

            // 保存搜索历史
            this._saveSearchHistory(query);

        } catch (err) {
            console.warn('[SidebarManager] Geocoder 搜索失败，使用备选方案:', err);
            // 备选：使用 Cesium Viewer 自带的 geocoder widget
            this._fallbackSearch(query, resultsList);
        }
    }

    /**
     * 备选搜索方案：尝试使用 OpenStreetMap Nominatim（无需 API key）
     * @param {string} query - 搜索关键词
     * @param {HTMLElement} resultsList - 搜索结果容器
     */
    async _fallbackSearch(query, resultsList) {
        try {
            // 使用 Cesium 内置的 geocode 搜索
            const geocoder = this.viewer.geocoder;
            if (geocoder && geocoder.viewModel) {
                geocoder.viewModel.searchText = query;
                geocoder.viewModel.search();
                resultsList.innerHTML = '<li style="color:#aaa; padding:8px;">已通过内置搜索定位</li>';
            } else {
                resultsList.innerHTML = '<li style="color:#888; padding:8px;">搜索服务不可用</li>';
            }
        } catch (e) {
            resultsList.innerHTML = '<li style="color:#888; padding:8px;">搜索失败</li>';
        }
    }

    /**
     * 添加搜索结果项到列表
     * @param {HTMLElement} container - 结果容器
     * @param {string} name - 显示文字
     * @param {number} lng - 经度
     * @param {number} lat - 纬度
     * @param {*} destination - Cesium 目的地对象（可选）
     */
    _addSearchResult(container, name, lng, lat, destination) {
        container.innerHTML = '';
        const li = document.createElement('li');
        li.innerHTML = `
            <span class="search-result-icon">📌</span>
            <span class="search-result-text" title="${name}">${name}</span>
        `;
        li.addEventListener('click', () => {
            if (destination) {
                this.viewer.camera.flyTo({ destination: destination });
            } else {
                this._flyToLocation(lng, lat, name);
            }
        });
        container.appendChild(li);
    }

    /**
     * 解析经纬度字符串
     * 支持格式：
     *   "101.5, 30.2"  "101.5 30.2"  "101.5，30.2"
     * @param {string} text - 输入文本
     * @returns {Object|null} { lng, lat } 或 null
     */
    _parseCoordinates(text) {
        // 匹配数字（含小数和负数），分隔符为逗号、中文逗号或空格
        const match = text.match(/^\s*(-?\d+\.?\d*)\s*[,，\s]+\s*(-?\d+\.?\d*)\s*$/);
        if (match) {
            const a = parseFloat(match[1]);
            const b = parseFloat(match[2]);
            // 经度范围 -180~180, 纬度范围 -90~90
            if (a >= -180 && a <= 180 && b >= -90 && b <= 90) {
                return { lng: a, lat: b };
            }
            // 尝试反转（纬度在前）
            if (b >= -180 && b <= 180 && a >= -90 && a <= 90) {
                return { lng: b, lat: a };
            }
        }
        return null;
    }

    /**
     * 飞入指定经纬度位置
     * @param {number} lng - 经度
     * @param {number} lat - 纬度
     * @param {string} name - 地点名称
     */
    _flyToLocation(lng, lat, name) {
        this.viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(lng, lat, 50000),
            orientation: {
                heading: 0,
                pitch: Cesium.Math.toRadians(-60),
                roll: 0
            }
        });
        console.log(`[SidebarManager] 飞入: ${name} (${lng}, ${lat})`);
    }

    /**
     * 保存搜索历史
     * @param {string} query - 搜索词
     */
    _saveSearchHistory(query) {
        // 去重
        this.searchHistory = this.searchHistory.filter(h => h !== query);
        this.searchHistory.unshift(query);
        // 限制最大条数
        if (this.searchHistory.length > this.maxSearchHistory) {
            this.searchHistory.pop();
        }
    }

    // ====================================================================
    //  三、图层分组折叠/展开事件
    // ====================================================================

    /**
     * 初始化图层分组的折叠/展开和全选事件
     */
    _initLayerGroupEvents() {
        // 为每个图层组头绑定折叠事件
        document.querySelectorAll('.layer-group-header').forEach(header => {
            header.addEventListener('click', (e) => {
                // 如果点击的是复选框，不触发折叠
                if (e.target.classList.contains('layer-group-checkbox')) return;

                const group = header.getAttribute('data-group');
                const childrenList = document.getElementById(`layerList-${group}`);
                const toggleIcon = header.querySelector('.layer-group-toggle');

                if (childrenList) {
                    const isVisible = childrenList.style.display !== 'none';
                    childrenList.style.display = isVisible ? 'none' : 'block';
                    toggleIcon.classList.toggle('expanded', !isVisible);
                }
            });
        });

        // 为每个图层组的复选框绑定全选/取消事件
        document.querySelectorAll('.layer-group-checkbox').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const groupId = checkbox.id.replace('chk-', '');
                this._toggleGroupVisibility(groupId, checkbox.checked);
            });
        });

        // 图层区域折叠/展开
        const layersHeader = document.getElementById('layersSectionHeader');
        if (layersHeader) {
            layersHeader.addEventListener('click', (e) => {
                // 点头部按钮时不触发整个图层树折叠
                if (e.target && (e.target.closest('#sidebarAddLayerBtn') || e.target.closest('#sidebarStartBackendBtn'))) {
                    return;
                }
                const tree = document.getElementById('layerTree');
                const toggleIcon = layersHeader.querySelector('.sidebar-section-toggle');
                if (tree) {
                    const isVisible = tree.style.display !== 'none';
                    tree.style.display = isVisible ? 'none' : 'block';
                    toggleIcon.classList.toggle('collapsed', isVisible);
                }
            });
        }
    }

    // ====================================================================
    //  四、侧边栏内嵌数据加载按钮
    // ====================================================================

    /**
     * 初始化侧边栏中的 "加载数据" 按钮
     * 点击后打开已有的数据加载弹窗（loadDataWin）
     */
    _initAddLayerButton() {
        const addBtn = document.getElementById('sidebarAddLayerBtn');
        if (!addBtn) return;

        addBtn.addEventListener('click', (e) => {
            e.stopPropagation(); // 阻止触发父级 header 的折叠事件
            // 调用已有的数据加载功能
            if (typeof EventModel !== 'undefined' && EventModel.dataLoad) {
                EventModel.dataLoad();
            } else {
                // 直接显示弹窗作为后备方案
                $('#loadDataWin').css('display', 'block');
            }
        });
    }

    // ====================================================================
    //  五、图层管理核心方法
    // ====================================================================

    /**
     * 根据数据类型确定图层所属分组
     * @param {string} dataType - 数据类型
     * @returns {string} 分组 ID
     */
    _getGroupByType(dataType) {
        switch (dataType) {
            case 'Terrain':  return 'terrain';
            case 'Tiff':     return 'imagery';
            case 'Tileset':
            case 'Gltf':
            case 'GLB':      return 'models';
            case 'Analysis': return 'analysis';
            case 'KML':
            case 'GeoJson':
            case 'CZML':
            default:         return 'myPlaces';
        }
    }

    /**
     * 获取图层类型对应的图标
     * @param {string} dataType - 数据类型
     * @returns {string} 图标字符
     */
    _getIconByType(dataType) {
        const icons = {
            'Terrain': '🏔️',
            'KML':     '📋',
            'GeoJson': '🗂️',
            'CZML':    '🎬',
            'Tileset': '🏗️',
            'Gltf':    '📦',
            'GLB':     '📦',
            'Tiff':    '🖼️',
            'Analysis': '📊'
        };
        return icons[dataType] || '📄';
    }

    /**
     * 获取图层类型对应的 CSS 类名
     * @param {string} dataType - 数据类型
     * @returns {string} CSS 类名
     */
    _getIconClass(dataType) {
        const classes = {
            'Terrain': 'layer-icon-terrain',
            'KML':     'layer-icon-kml',
            'GeoJson': 'layer-icon-geojson',
            'CZML':    'layer-icon-czml',
            'Tileset': 'layer-icon-tileset',
            'Gltf':    'layer-icon-gltf',
            'GLB':     'layer-icon-gltf',
            'Tiff':    'layer-icon-tiff',
            'Analysis': 'layer-icon-analysis'
        };
        return classes[dataType] || '';
    }

    /**
     * 从文件 URL 中提取文件名作为图层显示名称
     * @param {string} url - 文件 URL 或路径
     * @param {string} dataType - 数据类型
     * @returns {string} 显示名称
     */
    _extractName(url, dataType) {
        if (!url) return `${dataType} 图层`;
        // 清理 blob URL
        if (url.startsWith('blob:')) {
            return `${dataType} 文件 (本地上传)`;
        }
        // 提取文件名
        const parts = url.replace(/\\/g, '/').split('/');
        let name = parts[parts.length - 1] || parts[parts.length - 2] || url;
        // 去掉参数
        name = name.split('?')[0];
        return name || `${dataType} 图层`;
    }

    /**
     * 添加图层到侧边栏（核心方法）
     * 在数据加载成功后调用此方法注册图层
     * 
     * @param {Object} options - 图层配置
     * @param {string} options.name - 图层名称（可选，自动从 URL 提取）
     * @param {string} options.type - 数据类型：Terrain/KML/GeoJson/CZML/Tileset/Gltf/GLB/Tiff
     * @param {string} options.url - 数据源 URL
     * @param {*}      options.cesiumObject - Cesium 对象引用
     * @param {Object} options.extras - 附加数据（如遮罩 entity 等）
     * @returns {number} 图层 ID（若重复则返回已有图层的 ID）
     */
    addLayer(options) {
        const { type, url, cesiumObject, extras } = options;
        const name = options.name || this._extractName(url, type);

        // ===== 去重检查：同类型 + (同 URL 或同名称) 的图层不重复添加 =====
        // 非 blob URL 按 URL 去重；blob URL 按文件名 (name) 去重
        const isBlobUrl = url && url.startsWith('blob:');
        const existing = this.layers.find(l => {
            if (l.type !== type) return false;
            // 对 blob URL，按图层名称去重（原始文件名）
            if (isBlobUrl) return l.name === name;
            // 对普通 URL，按 URL 去重
            return l.url === url && url;
        });
        if (existing) {
            console.warn(`[SidebarManager] 图层已存在，跳过重复添加: ${name} (${type})`);
            // 先移除旧的 Cesium 对象（避免场景中残留无法操作的对象）
            this._removeCesiumObject(existing);
            // 更新 cesiumObject 引用为最新加载的对象
            existing.cesiumObject = cesiumObject;
            existing.url = url; // 更新 URL（blob URL 每次不同）
            if (extras) existing.extras = Object.assign(existing.extras || {}, extras);
            return existing.id;
        }

        const id = ++this.layerIdCounter;
        const group = this._getGroupByType(type);

        const layer = {
            id,
            name,
            type,
            group,
            url,
            visible: true,
            cesiumObject,
            extras: extras || {}
        };

        this.layers.push(layer);

        // 在 DOM 中添加图层项
        this._renderLayerItem(layer);

        // 自动展开所在分组
        this._expandGroup(group);

        console.log(`[SidebarManager] 添加图层: [${id}] ${name} (${type}) → ${group}`);
        return id;
    }

    /**
     * 渲染单个图层项到对应分组的 DOM 列表中
     * @param {Object} layer - 图层对象
     */
    _renderLayerItem(layer) {
        const listEl = document.getElementById(`layerList-${layer.group}`);
        if (!listEl) return;

        const li = document.createElement('li');
        li.className = 'layer-item';
        li.setAttribute('data-layer-id', layer.id);

        li.innerHTML = `
            <input type="checkbox" class="layer-item-checkbox" 
                   ${layer.visible ? 'checked' : ''} 
                   title="显示/隐藏" />
            <span class="layer-item-icon ${this._getIconClass(layer.type)}">${this._getIconByType(layer.type)}</span>
            <span class="layer-item-name" title="${layer.name} (${layer.type})">${layer.name}</span>
            <span class="layer-item-actions">
                <button class="layer-item-action delete" title="移除图层">✕</button>
            </span>
        `;

        // ===== 事件绑定 =====

        // 1. 复选框：控制图层显示/隐藏
        const checkbox = li.querySelector('.layer-item-checkbox');
        checkbox.addEventListener('change', (e) => {
            e.stopPropagation();
            this.setLayerVisibility(layer.id, checkbox.checked);
        });

        // 2. 删除按钮：删除图层
        const deleteBtn = li.querySelector('.delete');
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.removeLayer(layer.id);
        });

        // 3. 单击图层项：选中高亮
        li.addEventListener('click', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return;
            this._selectLayer(layer.id);
        });

        // 4. 双击图层项：飞入定位
        li.addEventListener('dblclick', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'BUTTON') return;
            e.preventDefault();
            this.flyToLayer(layer.id);
        });

        listEl.appendChild(li);
    }

    /**
     * 展开指定分组
     * @param {string} groupId - 分组 ID
     */
    _expandGroup(groupId) {
        const childrenList = document.getElementById(`layerList-${groupId}`);
        const header = document.querySelector(`[data-group="${groupId}"]`);
        if (childrenList) {
            childrenList.style.display = 'block';
        }
        if (header) {
            const toggle = header.querySelector('.layer-group-toggle');
            if (toggle) toggle.classList.add('expanded');
        }
    }

    /**
     * 选中某个图层（高亮）
     * @param {number} layerId - 图层 ID
     */
    _selectLayer(layerId) {
        // 取消之前的选中
        document.querySelectorAll('.layer-item.selected').forEach(el => {
            el.classList.remove('selected');
        });
        // 选中当前
        const el = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (el) el.classList.add('selected');
        this.selectedLayerId = layerId;

        // 更新透明度滑块显示
        this._updateOpacitySlider(layerId);
    }

    /**
     * 设置图层的可见性
     * @param {number} layerId - 图层 ID
     * @param {boolean} visible - 是否可见
     */
    setLayerVisibility(layerId, visible) {
        const layer = this.layers.find(l => l.id === layerId);
        if (!layer) return;

        layer.visible = visible;
        const obj = layer.cesiumObject;

        // 根据不同类型的 Cesium 对象设置可见性
        switch (layer.type) {
            case 'Terrain':
                // 地形无法隐藏，但可以切换回默认椭球
                if (!visible) {
                    layer.extras._savedTerrain = this.viewer.terrainProvider;
                    this.viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
                } else if (layer.extras._savedTerrain) {
                    this.viewer.terrainProvider = layer.extras._savedTerrain;
                }
                // 同时隐藏/显示遮罩 entity
                if (layer.extras.maskEntities) {
                    layer.extras.maskEntities.forEach(entity => {
                        entity.show = visible;
                    });
                }
                break;

            case 'KML':
            case 'GeoJson':
            case 'CZML':
                // DataSource 类型：控制 show 属性
                if (obj && obj.show !== undefined) {
                    obj.show = visible;
                }
                break;

            case 'Tileset':
                // Cesium3DTileset：控制 show 属性
                if (obj && obj.show !== undefined) {
                    obj.show = visible;
                }
                break;

            case 'Gltf':
            case 'GLB':
                // Entity 类型：控制 show 属性
                if (obj && obj.show !== undefined) {
                    obj.show = visible;
                }
                break;

            case 'Tiff':
                // ImageryLayer 类型：控制 show 属性
                if (obj && obj.show !== undefined) {
                    obj.show = visible;
                }
                break;

            case 'Analysis':
                // 分析图层：cesiumObject 是 primitive 数组 [{primitive, ...}, ...]
                if (Array.isArray(obj)) {
                    obj.forEach(item => {
                        if (item && item.primitive) item.primitive.show = visible;
                    });
                }
                // 同步工具栏中的复选框
                if (layer.extras && layer.extras.analysisLayerId) {
                    var chkMap = { slope: 'slope-layer', aspect: 'aspect-layer', cost: 'cost-layer' };
                    var chkId = chkMap[layer.extras.analysisLayerId];
                    if (chkId) {
                        var chk = document.getElementById(chkId);
                        if (chk) chk.checked = visible;
                    }
                }
                break;

            default:
                if (obj && obj.show !== undefined) {
                    obj.show = visible;
                }
                break;
        }

        console.log(`[SidebarManager] 图层 [${layerId}] ${layer.name} 可见性: ${visible}`);
    }

    /**
     * 飞入定位到图层
     * @param {number} layerId - 图层 ID
     */
    flyToLayer(layerId) {
        const layer = this.layers.find(l => l.id === layerId);
        if (!layer) return;

        const obj = layer.cesiumObject;

        switch (layer.type) {
            case 'Terrain':
                // 地形：飞入坐标范围（若有），否则提示
                if (layer.extras && layer.extras.bounds) {
                    const b = layer.extras.bounds;
                    this.viewer.camera.flyTo({
                        destination: Cesium.Rectangle.fromDegrees(b.west, b.south, b.east, b.north)
                    });
                } else {
                    console.log('[SidebarManager] Terrain 图层无坐标范围，无法自动飞入');
                }
                break;

            case 'KML':
            case 'GeoJson':
            case 'CZML':
                // DataSource：使用 viewer.flyTo
                if (obj) {
                    this.viewer.flyTo(obj);
                }
                break;

            case 'Tileset':
                // 3DTileset：使用 viewer.flyTo
                if (obj) {
                    this.viewer.flyTo(obj);
                }
                break;

            case 'Gltf':
            case 'GLB':
                // Entity：使用 viewer.flyTo
                if (obj) {
                    this.viewer.flyTo(obj);
                }
                break;

            case 'Tiff':
                // ImageryLayer：飞入坐标范围（若有），否则飞入imagery的rectangle
                if (layer.extras && layer.extras.bounds) {
                    const b = layer.extras.bounds;
                    this.viewer.camera.flyTo({
                        destination: Cesium.Rectangle.fromDegrees(b.west, b.south, b.east, b.north)
                    });
                } else if (obj && obj.imageryProvider && obj.imageryProvider.rectangle) {
                    this.viewer.camera.flyTo({
                        destination: obj.imageryProvider.rectangle
                    });
                } else {
                    console.log('[SidebarManager] Tiff 图层无坐标范围，无法自动飞入');
                }
                break;

            case 'Analysis':
                // 分析图层：使用 extras.bounds 飞入
                if (layer.extras && layer.extras.bounds) {
                    const b = layer.extras.bounds;
                    this.viewer.camera.flyTo({
                        destination: Cesium.Rectangle.fromDegrees(b.west, b.south, b.east, b.north)
                    });
                }
                break;

            default:
                if (obj) {
                    this.viewer.flyTo(obj);
                }
                break;
        }

        console.log(`[SidebarManager] 飞入图层: [${layerId}] ${layer.name}`);
    }

    /**
     * 仅从 Cesium 场景中移除指定图层的旧对象（不删除侧边栏 DOM 和数据记录）
     * 用于重复加载时清除旧的残留对象
     * @param {Object} layer - 图层对象
     */
    _removeCesiumObject(layer) {
        const obj = layer.cesiumObject;
        if (!obj) return;

        try {
            switch (layer.type) {
                case 'Terrain':
                    // 地形：恢复为椭球
                    this.viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
                    if (layer.extras && layer.extras.maskEntities) {
                        layer.extras.maskEntities.forEach(e => this.viewer.entities.remove(e));
                    }
                    break;
                case 'KML':
                case 'GeoJson':
                case 'CZML':
                    this.viewer.dataSources.remove(obj, true);
                    break;
                case 'Tileset':
                    this.viewer.scene.primitives.remove(obj);
                    break;
                case 'Gltf':
                case 'GLB':
                    this.viewer.entities.remove(obj);
                    break;
                case 'Tiff':
                    this.viewer.scene.imageryLayers.remove(obj);
                    if (layer.extras && layer.extras.eventHandler) {
                        layer.extras.eventHandler.destroy();
                    }
                    break;
                case 'Analysis':
                    // 分析图层不从此处删除 primitive（由 SlopeAspect 自行管理）
                    break;
            }
            console.log(`[SidebarManager] 已清除旧的 Cesium 对象: ${layer.name} (${layer.type})`);
        } catch (e) {
            console.warn('[SidebarManager] 清除旧对象时出错:', e);
        }
    }

    /**
     * 移除图层（从 Cesium 场景和侧边栏中删除）
     * @param {number} layerId - 图层 ID
     */
    removeLayer(layerId) {
        const layerIndex = this.layers.findIndex(l => l.id === layerId);
        if (layerIndex === -1) return;

        const layer = this.layers[layerIndex];
        const obj = layer.cesiumObject;

        // 从 Cesium 场景中移除
        switch (layer.type) {
            case 'Terrain':
                // 恢复默认地形
                this.viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
                // 清除遮罩 entity
                if (layer.extras.maskEntities) {
                    layer.extras.maskEntities.forEach(entity => {
                        this.viewer.entities.remove(entity);
                    });
                }
                // 销毁事件处理器
                if (layer.extras.eventHandler) {
                    layer.extras.eventHandler.destroy();
                }
                break;

            case 'KML':
            case 'GeoJson':
            case 'CZML':
                if (obj) {
                    this.viewer.dataSources.remove(obj, true);
                }
                break;

            case 'Tileset':
                if (obj) {
                    this.viewer.scene.primitives.remove(obj);
                }
                break;

            case 'Gltf':
            case 'GLB':
                if (obj) {
                    this.viewer.entities.remove(obj);
                }
                break;

            case 'Tiff':
                if (obj) {
                    this.viewer.scene.imageryLayers.remove(obj);
                }
                // 销毁事件处理器
                if (layer.extras.eventHandler) {
                    layer.extras.eventHandler.destroy();
                }
                break;

            case 'Analysis':
                // 分析图层：移除所有 primitive 并通知 SlopeAspect 清理
                if (Array.isArray(obj)) {
                    obj.forEach(item => {
                        if (item && item.primitive) {
                            try { this.viewer.scene.primitives.remove(item.primitive); } catch (e) {}
                        }
                    });
                }
                // 同步清理 SlopeAspect 中的引用
                if (window.SlopeAnalysis && layer.extras && layer.extras.analysisLayerId) {
                    const aId = layer.extras.analysisLayerId;
                    if (aId === 'slope')  window.SlopeAnalysis.slopePolygons = [];
                    if (aId === 'aspect') window.SlopeAnalysis.aspectPolygons = [];
                    if (aId === 'cost')   window.SlopeAnalysis.costPolygons = [];
                    if (aId.indexOf('cost_land_') === 0 && Array.isArray(window.SlopeAnalysis.landUseCostLayers)) {
                        window.SlopeAnalysis.landUseCostLayers = window.SlopeAnalysis.landUseCostLayers.filter(function (x) {
                            return x && x.layerId !== aId;
                        });
                    }
                    if (window.SlopeAnalysis.layerRegistry && window.SlopeAnalysis.layerRegistry[aId]) {
                        window.SlopeAnalysis.unregisterLayer(aId);
                    }
                }
                break;

            default:
                break;
        }

        // 从 DOM 中移除
        const li = document.querySelector(`[data-layer-id="${layerId}"]`);
        if (li) li.remove();

        // 从数据中移除
        this.layers.splice(layerIndex, 1);

        console.log(`[SidebarManager] 移除图层: [${layerId}] ${layer.name}`);
    }

    /**
     * 切换某个分组下所有图层的可见性
     * @param {string} groupId - 分组 ID
     * @param {boolean} visible - 是否可见
     */
    _toggleGroupVisibility(groupId, visible) {
        this.layers
            .filter(l => l.group === groupId)
            .forEach(layer => {
                this.setLayerVisibility(layer.id, visible);
                // 同步复选框状态
                const li = document.querySelector(`[data-layer-id="${layer.id}"]`);
                if (li) {
                    const checkbox = li.querySelector('.layer-item-checkbox');
                    if (checkbox) checkbox.checked = visible;
                }
            });
    }

    /**
     * 获取所有图层信息
     * @returns {Array} 图层列表
     */
    getAllLayers() {
        return this.layers.map(l => ({
            id: l.id,
            name: l.name,
            type: l.type,
            group: l.group,
            visible: l.visible
        }));
    }

    /**
     * 根据 ID 获取图层
     * @param {number} layerId - 图层 ID
     * @returns {Object|null} 图层对象
     */
    getLayerById(layerId) {
        return this.layers.find(l => l.id === layerId) || null;
    }

    // ====================================================================
    //  七、图层透明度调节
    // ====================================================================

    /**
     * 判断图层类型是否支持透明度调节
     * @param {string} type - 图层类型
     * @returns {boolean}
     */
    _supportsOpacity(type) {
        return ['KML', 'GeoJson', 'CZML', 'Tiff', 'Gltf', 'GLB', 'Tileset', 'Analysis'].includes(type);
    }

    /**
     * 初始化透明度滑块事件（使用 requestAnimationFrame 节流）
     */
    _initOpacitySlider() {
        const slider = document.getElementById('layerOpacitySlider');
        if (!slider) return;

        this._opacityRafId = null;

        slider.addEventListener('input', (e) => {
            const opacity = parseFloat(e.target.value);
            const label = document.getElementById('opacityValueLabel');
            if (label) label.textContent = Math.round(opacity * 100) + '%';

            if (this.selectedLayerId !== null) {
                // 使用 requestAnimationFrame 节流，避免每次 input 都触发完整更新
                if (this._opacityRafId) cancelAnimationFrame(this._opacityRafId);
                this._opacityRafId = requestAnimationFrame(() => {
                    this.setLayerOpacity(this.selectedLayerId, opacity);
                    this._opacityRafId = null;
                });
            }
        });
    }

    /**
     * 更新透明度滑块UI（选中图层时调用）
     * @param {number} layerId - 图层 ID
     */
    _updateOpacitySlider(layerId) {
        const control = document.getElementById('layerOpacityControl');
        const slider = document.getElementById('layerOpacitySlider');
        const nameLabel = document.getElementById('opacityLayerName');
        const valueLabel = document.getElementById('opacityValueLabel');
        if (!control || !slider) return;

        const layer = this.layers.find(l => l.id === layerId);
        if (!layer || !this._supportsOpacity(layer.type)) {
            control.style.display = 'none';
            return;
        }

        // 读取当前图层的透明度
        const currentOpacity = (layer.extras && layer.extras._opacity !== undefined)
            ? layer.extras._opacity : 1.0;

        control.style.display = 'block';
        slider.value = currentOpacity;
        if (nameLabel) nameLabel.textContent = layer.name;
        if (valueLabel) valueLabel.textContent = Math.round(currentOpacity * 100) + '%';
    }

    /**
     * 设置图层透明度（使用缓存原始颜色方式，高性能）
     * @param {number} layerId - 图层 ID
     * @param {number} opacity - 透明度 0~1
     */
    setLayerOpacity(layerId, opacity) {
        const layer = this.layers.find(l => l.id === layerId);
        if (!layer) return;

        // 保存透明度值
        if (!layer.extras) layer.extras = {};
        layer.extras._opacity = opacity;

        const obj = layer.cesiumObject;
        if (!obj) return;

        switch (layer.type) {
            case 'KML':
            case 'GeoJson':
            case 'CZML':
                // DataSource: 批量处理所有 entity（使用缓存颜色）
                if (obj.entities && obj.entities.values) {
                    // 首次调用：缓存所有 entity 的原始颜色
                    if (!layer.extras._colorCache) {
                        layer.extras._colorCache = this._cacheEntityColors(obj.entities.values);
                    }
                    this._batchSetEntityOpacity(obj.entities.values, opacity, layer.extras._colorCache);
                }
                break;

            case 'Gltf':
            case 'GLB':
                // 单个 Entity（model）：直接使用 Cesium model.color
                if (obj.model) {
                    obj.model.color = Cesium.Color.WHITE.withAlpha(opacity);
                    obj.model.colorBlendMode = Cesium.ColorBlendMode.MIX;
                    obj.model.colorBlendAmount = (opacity < 1.0) ? 0.5 : 0.0;
                }
                break;

            case 'Tiff':
                // ImageryLayer: 直接设置 alpha
                if (obj.alpha !== undefined) {
                    obj.alpha = opacity;
                }
                break;

            case 'Tileset':
                // Cesium3DTileset: 通过 style 设置透明度
                obj.style = new Cesium.Cesium3DTileStyle({
                    color: 'color("white", ' + opacity + ')'
                });
                break;

            case 'Analysis':
                // 分析图层：修改每个 primitive 的 material color alpha
                if (Array.isArray(obj)) {
                    obj.forEach(item => {
                        if (item && item.primitive && item.primitive.appearance) {
                            var mat = item.primitive.appearance.material;
                            if (mat && mat.uniforms && mat.uniforms.color) {
                                var c = item.baseColor || mat.uniforms.color;
                                mat.uniforms.color = new Cesium.Color(c.red, c.green, c.blue, opacity);
                            }
                        }
                    });
                }
                break;

            default:
                break;
        }
    }

    /**
     * 缓存 entity 列表的原始颜色（只在首次设置透明度时调用一次）
     * @param {Array<Cesium.Entity>} entities
     * @returns {Map} entityId -> { polygon, polyline, point, billboard, label, ellipse }
     */
    _cacheEntityColors(entities) {
        const cache = new Map();
        const now = Cesium.JulianDate.now();
        for (let i = 0; i < entities.length; i++) {
            const e = entities[i];
            const entry = {};
            if (e.polygon) {
                const mat = e.polygon.material;
                if (mat && mat.color) {
                    try { entry.polygon = mat.color.getValue(now); } catch (_) {}
                }
                if (!entry.polygon) entry.polygon = Cesium.Color.WHITE;
            }
            if (e.polyline) {
                const mat = e.polyline.material;
                if (mat && mat.color) {
                    try { entry.polyline = mat.color.getValue(now); } catch (_) {}
                }
                if (!entry.polyline) entry.polyline = Cesium.Color.WHITE;
            }
            if (e.point && e.point.color) {
                try { entry.point = e.point.color.getValue(now); } catch (_) {}
                if (!entry.point) entry.point = Cesium.Color.WHITE;
            }
            if (e.billboard) {
                entry.billboard = true;
            }
            if (e.label) {
                try {
                    entry.label = e.label.fillColor ? e.label.fillColor.getValue(now) : Cesium.Color.WHITE;
                } catch (_) { entry.label = Cesium.Color.WHITE; }
            }
            if (e.ellipse) {
                const mat = e.ellipse.material;
                if (mat && mat.color) {
                    try { entry.ellipse = mat.color.getValue(now); } catch (_) {}
                }
                if (!entry.ellipse) entry.ellipse = Cesium.Color.WHITE;
            }
            cache.set(e.id, entry);
        }
        return cache;
    }

    /**
     * 批量设置 entity 透明度（使用缓存的原始颜色，避免重复 getValue）
     * @param {Array<Cesium.Entity>} entities
     * @param {number} opacity
     * @param {Map} colorCache
     */
    _batchSetEntityOpacity(entities, opacity, colorCache) {
        for (let i = 0; i < entities.length; i++) {
            const e = entities[i];
            const cached = colorCache.get(e.id) || {};

            if (e.polygon && cached.polygon) {
                e.polygon.material = new Cesium.ColorMaterialProperty(cached.polygon.withAlpha(opacity));
            }
            if (e.polyline && cached.polyline) {
                e.polyline.material = new Cesium.ColorMaterialProperty(cached.polyline.withAlpha(opacity));
            }
            if (e.point && cached.point) {
                e.point.color = new Cesium.ConstantProperty(cached.point.withAlpha(opacity));
            }
            if (e.billboard) {
                e.billboard.color = new Cesium.ConstantProperty(Cesium.Color.WHITE.withAlpha(opacity));
            }
            if (e.label && cached.label) {
                e.label.fillColor = new Cesium.ConstantProperty(cached.label.withAlpha(opacity));
            }
            if (e.ellipse && cached.ellipse) {
                e.ellipse.material = new Cesium.ColorMaterialProperty(cached.ellipse.withAlpha(opacity));
            }
        }
    }
}
