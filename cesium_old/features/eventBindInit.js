//import { formUrl, fromArrayBuffer, fromBlob} from 'geotiff';
//import GeoTIFF, { fromUrl, fromUrls, fromArrayBuffer, fromBlob } from 'geotiff';  //引入后再earthOpera中会报错
//import TIFFImageryProvider from 'tiff-imagery-provider';


var center = [110.98, 30.83];
var tracker = null;

var layerId = "globerDrawDemoLayer"

var shapeDic = {};
var flag = 0;
var bxmap = bxmap || {};

var area_alpha;//透明度

//封装函数，向给定url发送请求
async function data_download(obj) {


    // function add_downloadEvent(){

    // }  
    //请求
    const result = await axios({
        url: 'http://localhost:8080/api/v1/Search/locationSearch',
        // method: 'GET',
        params: obj,

    })
    if (result.data.data[0]) {
        console.log("result.data", result.data.data);
        console.log("result", result);

        const data_img = result.data.data
        data_ul.innerHTML = data_img.map((item) => {
            // return `<li class="list-group-item" >title:${item.title}时间${item.date}</li>`
            return `<a href="#" id="${item.title}"class="list-group-item list-group-item-action">title:${item.title}时间${item.date}</a>`

        }).join('')
        //如果有数据，则添加列表点击事件
        // console.log(data_ul);
        // if (data_ul.hasOwnProperty('click')) {
        //     console.log(11);
        //     return 
        // }
        for (let i = 0; i < data_ul.childNodes.length; i++) {
            data_ul.childNodes[i].addEventListener('click', (e) => {
                console.log(e.target.id);
                flagevent = 1
                console.log(flagevent);
                axios({
                    url: 'http://localhost:8080/api/v1/Search/downLoad',
                    // method: 'GET',
                    params: {
                        title: e.target.id
                    },
                    // headers: {

                    //     'Access-Control-Allow-Origin': 'http://localhost:8080'// 设置允许的跨域来源，可以使用通配符*或指定特定的来源
                    //   },
                    responseType: 'blob'
                }).then((result) => {
                    const blob = new Blob([result.data], {
                        type: 'image/tiff'
                    });
                    const url = window.URL.createObjectURL(blob);
                    console.log(url)
                    const link = document.createElement('a');
                    link.href = url;
                    link.download = e.target.id;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    URL.revokeObjectURL(url);
                    // console.log(data_ul.hasAttribute('onclick'));

                })
            })
        }




    } else {
        //如果无数据，则显示没有查询结果
        data_ul.innerHTML = `<a href="#" class="list-group-item list-group-item-action">查询范围内无结果</a>`
        //并解除存在的点击事件
        data_ul.removeEventListener("click", () => {
            console.log('无数据');
        })

    }


}

//绑定事件初始化
$(document).ready(
    function () {
        //轨迹czml
        $('#satellite-track').click(function () {
            EventModel.Satellite();
        });
        //坡度坡向分析
        $('#slop').click(function () {
            EventModel.slope();
        });
        //剖面分析
        $('#profileAnalysis').click(function () {
            EventModel.profile();
        });
        //等高线分析
        $('#contour').click(function () {
            EventModel.contour();
        })
        //跟图回放
        $('#czml-track').click(function () {
            EventModel.czmlTrack();
        })
        //流程化演示
        $('#Processoriented').click(function () {
            EventModel.czmlTrack();
        })
        $('#satelliteFacilities-track').click(function () {
            OtherData.ClusterPoints();
        });
        $('#route-track').click(function () {
            addVehicleCZML();
        });
        $('#czml-track').click(function () {
            //addCZMLPath();
        });



        //功能管理(其他功能)
        //影像数据
        $('#load-Tif').click(function () {
            EventModel.loadTif();
        });
        //数据加载
        $('#loadData_fun').click(function () {
            EventModel.dataLoad();
        });
        //三维模型
        $('#load-3Dtiles').click(function () {
            EventModel.load3Dtiles();
        })
        //空间量算
        $('#spatial-measure').click(function () {
            EventModel.SpatialMeasure();
        })
        //标绘功能
        $('#draw_fun').click(function () {
            //按键可以到这
            EventModel.mark_draw();
        });


        /*2022.07.19  在一个表格下显示大地坐标和投影坐标
        * 无法做到切换显示
        * remove Coordinates()函数可以删除坐标显示框
        * 需要在加上坐标显示标志位 来关闭坐标显示*/
        //高斯坐标测量*/
        $('#gaosiMousePosition').click(function () {
            //高斯坐标展示
            /*  console.log("高斯坐标")
              removeShowCoordinates();*/
            showGaosiCoordinates();
        })
        //避打区域分析
        $('#avoidanceAreaAnalysis').click(function () {
            EventModel.AvoidanceAreaAnalysis()
        })
        $('#bida').click(function () {
            EventModel.AvoidanceAreaAnalysis()
        })
        //数据加载
        $('#loadData_funTest').click(function () {
            OtherData.addPoints();
        });

        //场景收藏
        $('#saveMap').click(function () {
            console.log('场景收藏');
            let canvas = viewer.scene.canvas;
            console.log(canvas);
            let image = canvas.toDataURL("image/png").replace("image/png", "image/octet-stream");
            //将canvas转为64位编码
            console.log('image=' + image);


            //创建 <a> 的动态元素
            let link = document.createElement("a");

            //console.log('link=' + typeof link);

            let blob = EventModel.dataURLtoBlob(image);

            let objurl = URL.createObjectURL(blob);
            link.download = "scene.png";
            link.href = objurl;
            console.log('link=' + link);
            console.log('link.click=' + link);
            console.log('typr=' + typeof link)
            link.click();
        })
        //目标历史影响积累
        $('#goalhistory').click(function () {
            providerLayer = new Cesium.WebMapServiceImageryProvider({
                url: 'http://localhost:8082/geoserver/nanjing/wms?service=WMS',
                layers: 'sana',
                parameters: {
                    service: 'WMS',
                    format: 'image/png',
                    transparent: true,
                }
            })
            viewer.imageryLayers.addImageryProvider(providerLayer)
            viewer.camera.flyTo({
                //destination:Cesium.Cartesian3.fromDegrees(102.220 , 29.833,13000)
                destination: Cesium.Cartesian3.fromDegrees(44.21081, 15.47648, 13000)
            }
            )
        })

        // 初始化窗口组件复选框事件（侧边栏）
        EventModel.displaySetting();

        // 窗口事件
        // 用事件委托而非直接绑定：RoughAnalysis / TerrainProfileAnalysis 等模块的
        // 面板是运行时动态创建的，直接绑定抓不到，过去只能各复制一份实现。
        // 委托后，凡是带 .move / .close / .toggle_win 的元素（含后续动态插入的）
        // 都自动生效。详见 FRONTEND_AUDIT.md 第三节。
        $(document).on('mousedown', '.move', function (e) {
            toolbarMove(this, e);
        });
        $(document).on('click', '.close', function () {
            $(this).closest('.functionWin').css('display', 'none');
        });
        $(document).on('click', '.toggle_win', function () {
            $(".content", $(this).closest('.functionWin')).slideToggle();
        });

        //搜索设置
        var serch_btn = window.setTimeout(function () {
            $('.cesium-geocoder-searchButton').off();
            $('.cesium-geocoder-searchButton').click(function () {
                EventModel.search();
            });
            window.clearTimeout(serch_btn);
        }, 6000)
    }
)



var EventModel = {
    //等高线分析
    contour: function () {
        console.log('等高线分析');
        $('#contourWindow').css('display', 'block');


        ContourAnalysis = new ContourMaterial(viewer);console.log(111);
        ContourAnalysis.init();
    },

    // 剖面分析
    profile: function () {
        console.log('剖面分析');
        var v = window.viewer || (typeof viewer !== 'undefined' ? viewer : null);
        if (!v) {
            var container = document.querySelector('.cesium-viewer');
            if (container && container.__cesium_viewer) {
                v = container.__cesium_viewer;
            }
        }
        if (!v) { console.error('viewer 未初始化'); return; }
        if (!window._profileAnalysisInstance) {
            window._profileAnalysisInstance = new TerrainProfileAnalysis(v);
        }
        var inst = window._profileAnalysisInstance;
        // 面板被隐藏 → 重新显示（不重新绘制）
        if (inst.chartPanel && inst.chartPanel.style.display === 'none') {
            inst.chartPanel.style.display = '';
            if (inst.chartInstance) inst.chartInstance.resize();
            return;
        }
        // 显示功能面板，用户点击"开始分析"后再开始绘制
        inst._showPanel();
    },

    // 坡度分析
    slope: function () {
        console.log('坡度坡向分析');
        $('#slopeWindow').css('display', 'block');
/*AAA这里注释掉了一段内容，放在末尾*/ 
        // 使实例对页面脚本可见
        window.SlopeAnalysis = SlopeAnalysis = new SlopeAspect(viewer); 
        if (typeof window.initTerrainBackendTools === 'function') {
            window.initTerrainBackendTools(viewer, window.SlopeAnalysis);
        }

        const getSelectedAnalysisTarget = () => {
            const val = document.getElementById('analysisTargetSelect')?.value || 'slope';
            return ['slope', 'aspect', 'cost'].includes(val) ? val : 'slope';
        };

        const ensureSingleLayerVisible = (target) => {
            const wantSlope = target === 'slope';
            const wantAspect = target === 'aspect';
            const wantCost = target === 'cost';

            const setPrimitiveArrayVisible = (arr, visible) => {
                if (!Array.isArray(arr)) return;
                arr.forEach((item) => {
                    if (item && item.primitive) {
                        item.primitive.show = !!visible;
                    }
                });
            };

            document.getElementById('slope-layer').checked = wantSlope;
            document.getElementById('aspect-layer').checked = wantAspect;
            document.getElementById('cost-layer').checked = wantCost;
            document.getElementById('curvature-layer').checked = false;

            setPrimitiveArrayVisible(SlopeAnalysis.slopePolygons, wantSlope);
            setPrimitiveArrayVisible(SlopeAnalysis.aspectPolygons, wantAspect);
            setPrimitiveArrayVisible(SlopeAnalysis.costPolygons, wantCost);
            setPrimitiveArrayVisible(SlopeAnalysis.curvaturePolygons, false);

            if (typeof SlopeAnalysis._syncSidebarCheckbox === 'function') {
                SlopeAnalysis._syncSidebarCheckbox('slope', wantSlope);
                SlopeAnalysis._syncSidebarCheckbox('aspect', wantAspect);
                SlopeAnalysis._syncSidebarCheckbox('cost', wantCost);
            }
        };

        const applyTargetVisibilityWithRetry = (target) => {
            let retries = 0;
            const maxRetries = 40;
            const timer = setInterval(() => {
                retries += 1;
                const slopeReady = Array.isArray(SlopeAnalysis.slopePolygons) && SlopeAnalysis.slopePolygons.length > 0;
                const aspectReady = Array.isArray(SlopeAnalysis.aspectPolygons) && SlopeAnalysis.aspectPolygons.length > 0;
                const costReady = Array.isArray(SlopeAnalysis.costPolygons) && SlopeAnalysis.costPolygons.length > 0;
                const ready = target === 'cost' ? costReady : (slopeReady || aspectReady || costReady);

                if (ready || retries >= maxRetries) {
                    clearInterval(timer);
                    ensureSingleLayerVisible(target);
                }
            }, 250);
        };

        const bindAlphaInput = () => {
            let alpha = document.getElementById("SAalpha");
            alpha.oninput = function () {
                document.getElementById('SAalpha_val').innerText = alpha.value;
                SlopeAnalysis.area_alpha = alpha.value;
                SlopeAnalysis.updateAlpha(alpha.value);
            };
        };
        const runSelectedAnalysis = (byNum) => {
            const target = getSelectedAnalysisTarget();
            const config = target === 'aspect' ? 0 : 1;
            const num = Number($("#Num").val());
            const distance = Number($("#Distance").val());

            SlopeAnalysis.clearAll();
            SlopeAnalysis.analysisTarget = target;
            document.getElementById('drawFlag').checked = SlopeAnalysis.drawFlag;

            if (byNum) {
                SlopeAnalysis.createNew4Num(num, config);
            } else {
                SlopeAnalysis.createNew4Distance(distance, config);
            }

            applyTargetVisibilityWithRetry(target);
            bindAlphaInput();
        };
        
        document.querySelector('#slopeByNum').addEventListener('click', () => {
            runSelectedAnalysis(true);
        });
        document.querySelector('#slopeByDistance').addEventListener('click', () => {
            runSelectedAnalysis(false);
        });

        document.getElementById('slope-layer').addEventListener('change', function () {
            SlopeAnalysis.slopeLayerVisibility();//坡度显示隐藏
            if (document.getElementById('aspect-layer').checked) {
                document.getElementById('aspect-layer').checked = false;
                SlopeAnalysis.aspectLayerVisibility();
            }
            if(document.getElementById('cost-layer').checked){
                document.getElementById('cost-layer').checked = false;
                SlopeAnalysis.costLayerVisibility();
            }
            if(document.getElementById('curvature-layer').checked){
                document.getElementById('curvature-layer').checked = false;
                SlopeAnalysis.curvatureLayerVisibility();
            }
        });
        document.getElementById('aspect-layer').addEventListener('change', function () {
            SlopeAnalysis.aspectLayerVisibility();//坡向显示隐藏
            if (document.getElementById('slope-layer').checked) {
                document.getElementById('slope-layer').checked = false;
                SlopeAnalysis.slopeLayerVisibility();
            }
            if(document.getElementById('cost-layer').checked){
                document.getElementById('cost-layer').checked = false;
                SlopeAnalysis.costLayerVisibility();
            }
            if(document.getElementById('curvature-layer').checked){
                document.getElementById('curvature-layer').checked = false;
                SlopeAnalysis.curvatureLayerVisibility();
            }
        });
        document.getElementById('cost-layer').addEventListener('change', function () {
            SlopeAnalysis.costLayerVisibility();//代价图层显示隐藏
            if (document.getElementById('slope-layer').checked) {
                document.getElementById('slope-layer').checked = false;
                SlopeAnalysis.slopeLayerVisibility();
            }
            if (document.getElementById('aspect-layer').checked) {
                document.getElementById('aspect-layer').checked = false;
                SlopeAnalysis.aspectLayerVisibility();
            }
            if (document.getElementById('curvature-layer').checked) {
                document.getElementById('curvature-layer').checked = false;
                SlopeAnalysis.curvatureLayerVisibility();
            }
        });

        document.getElementById('curvature-layer').addEventListener('change', function () {
            SlopeAnalysis.curvatureLayerVisibility();//曲率图层显示隐藏
            if (document.getElementById('slope-layer').checked) {
                document.getElementById('slope-layer').checked = false;
                SlopeAnalysis.slopeLayerVisibility();
            }
            if (document.getElementById('aspect-layer').checked) {
                document.getElementById('aspect-layer').checked = false;
                SlopeAnalysis.aspectLayerVisibility();
            }
            if(document.getElementById('cost-layer').checked){
                document.getElementById('cost-layer').checked = false;
                SlopeAnalysis.costLayerVisibility();
            }
        });

        document.querySelector('#drawFlag').addEventListener('click', () => { 
                SlopeAnalysis.drawFlag = !SlopeAnalysis.drawFlag;
                document.getElementById('drawFlag').checked = SlopeAnalysis.drawFlag;
                console.log(SlopeAnalysis.drawFlag);
        })// 是否渲染坡度坡向


        document.querySelector('#GetSlopePath').addEventListener('click', () => { 
            if(SlopeAnalysis.slopeCostGrid.length == 0){
                alert('请先生成坡度/坡向图层，再进行路径计算');
            }
            else{
                SlopeAnalysis.reFindPathFlag = true;    
                SlopeAnalysis.reFindPath();
            }
        });// 计算+绘制路径

        document.querySelector('#ClearPath').addEventListener('click', () => { 
            SlopeAnalysis.reFindPathFlag = false; 
            SlopeAnalysis.clearPathFlag = true;   
            SlopeAnalysis.reFindPath();
            SlopeAnalysis.clearPathFlag = false;
        });// 清除路径

        document.querySelector('#keepStartEnd').addEventListener('change', () => {
            SlopeAnalysis.keepStartEndFlag = !SlopeAnalysis.keepStartEndFlag;
            document.querySelector('#keepStartEnd').checked = SlopeAnalysis.keepStartEndFlag;
        });// 保持起点和终点

        document.querySelector('.PathPlanningMethod_select')?.addEventListener('change', function() {
            var selectedMethod = $('.PathPlanningMethod_select').val();
            switch(selectedMethod) {
                case 'OriginA*':
                    SlopeAnalysis.equTimeCostV = false;
                    SlopeAnalysis.equTimeCostDragF = false;
                    SlopeAnalysis.useAHPMethod = false;
                    SlopeAnalysis.useOriginRRTFlag = false;
                    break;
                case 'equTimeCost_BaseV':
                    SlopeAnalysis.equTimeCostV = true;
                    SlopeAnalysis.equTimeCostDragF = false;
                    SlopeAnalysis.useAHPMethod = false;
                    SlopeAnalysis.useOriginRRTFlag = false;
                    break;
                case 'equTimeCost_BaseDragF':
                    SlopeAnalysis.equTimeCostV = false;
                    SlopeAnalysis.equTimeCostDragF = true;
                    SlopeAnalysis.useAHPMethod = false;
                    SlopeAnalysis.useOriginRRTFlag = false;
                    break;
                case 'AHPMethod':
                    SlopeAnalysis.equTimeCostV = false;
                    SlopeAnalysis.equTimeCostDragF = false;
                    SlopeAnalysis.useAHPMethod = true;
                    SlopeAnalysis.useOriginRRTFlag = false;
                    break;
                case 'OriginRRT':
                    SlopeAnalysis.equTimeCostV = false;
                    SlopeAnalysis.equTimeCostDragF = false;
                    SlopeAnalysis.useAHPMethod = false;
                    SlopeAnalysis.useOriginRRTFlag = true;
                    break;
                default:
                    console.log('未知的寻路方法');
            }
        });// 选择寻路方法

        // 覆盖区绘制与清除按钮绑定
        document.getElementById('drawRoadArea').addEventListener('click', () => {
            if (!window.SlopeAnalysis || window.SlopeAnalysis.slopeCostGrid.length === 0) return alert('请先初始化坡度分析');
            window.SlopeAnalysis.startDrawOverride('road');
        });// 道路覆盖区
        document.getElementById('drawWaterArea').addEventListener('click', () => {
            if (!window.SlopeAnalysis || window.SlopeAnalysis.slopeCostGrid.length === 0) return alert('请先初始化坡度分析');
            window.SlopeAnalysis.startDrawOverride('water');
        });// 水体覆盖区
        document.getElementById('clearOverrides').addEventListener('click', () => {
            if (!window.SlopeAnalysis || window.SlopeAnalysis.slopeCostGrid.length === 0) return alert('请先初始化坡度分析');
            window.SlopeAnalysis.clearOverrideAreas();
        });// 清除覆盖区

        // ==================== 土地覆盖代价叠加按钮绑定 ====================
        document.getElementById('applyLandUseCost').addEventListener('click', () => {
            if (!window.SlopeAnalysis || window.SlopeAnalysis.slopeCostGrid.length === 0) {
                return alert('请先计算区域坡度并生成代价网格！');
            }
            window.SlopeAnalysis.applyLandUseCostToGrid();
        });
        document.getElementById('clearLandUseCost').addEventListener('click', () => {
            if (!window.SlopeAnalysis || window.SlopeAnalysis.slopeCostGrid.length === 0) {
                return alert('请先计算区域坡度！');
            }
            window.SlopeAnalysis.clearLandUseCost();
        });

        // ==================== 图元置顶功能绑定 ====================
        // 刷新图元列表下拉框
        function refreshPrimitiveList() {
            const select = document.getElementById('primitiveTopSelect');
            if (!select) return;
            
            // 清空现有选项（保留第一个占位选项，设置白底黑字）
            select.innerHTML = '<option value="" style="background-color: white; color: black;">-- 选择图层 --</option>';
            
            // 检查 SlopeAnalysis 是否已初始化
            if (!window.SlopeAnalysis) return;
            
            // 获取可用图元列表
            const primitives = window.SlopeAnalysis.getAvailablePrimitives();
            
            // 填充下拉框选项（白底黑字）
            primitives.forEach(item => {
                const option = document.createElement('option');
                option.value = item.id;
                option.textContent = `${item.name} (${item.count}个${item.visible ? ', 显示中' : ', 已隐藏'})`;
                option.style.backgroundColor = 'white';
                option.style.color = 'black';
                select.appendChild(option);
            });
        }
        
        // 刷新按钮点击事件
        document.getElementById('refreshPrimitivesBtn')?.addEventListener('click', () => {
            refreshPrimitiveList();
            console.log('图元列表已刷新');
        });
        
        // 置顶按钮点击事件
        document.getElementById('raiseToTopBtn')?.addEventListener('click', () => {
            const select = document.getElementById('primitiveTopSelect');
            const selectedId = select?.value;
            
            // 检查是否选择了有效图元
            if (!selectedId) {
                return alert('请先选择要置顶的图层');
            }
            
            // 检查 SlopeAnalysis 是否已初始化
            if (!window.SlopeAnalysis) {
                return alert('请先初始化坡度分析');
            }
            
            // 执行置顶操作
            window.SlopeAnalysis.raisePrimitiveToTop(selectedId);
            
            // 刷新列表（更新显示状态）
            refreshPrimitiveList();
        });
        
        // 下拉框选择变化时的提示（可选）
        document.getElementById('primitiveTopSelect')?.addEventListener('change', (e) => {
            const selectedText = e.target.options[e.target.selectedIndex]?.text;
            if (selectedText && selectedText !== '-- 选择图层 --') {
                console.log('已选择图层:', selectedText);
            }
        });
        // ==================== 图元置顶功能绑定结束 ====================

        //下拉选择图表显示
        document.querySelector('.PathAnalysisChart_select')?.addEventListener('change', function() {
            var selectedChart = $('.PathAnalysisChart_select').val();
            // 根据选择的值触发相应的图表显示
            switch(selectedChart) {
                case 'ShowRoughness':
                    showRoughnessChart();
                    break;
                case 'ShowRoughnessRate':
                    showRoughnessRateChart();
                    break;
                case 'ShowHeightRate':
                    showHeightRateChart();
                    break;
                default:
                    console.log('未知的图表选项');
            }
        });

        function showRoughnessChart() {
            let pathLineNum = window.SlopeAnalysis.pathLineNum - 1;// 每一个当前pathLineNum都是为下一条将要绘制的线准备的，即对应数字是没数据的pathPoints
            let pathPoints = window.SlopeAnalysis.pathPoints;

            if (!window.SlopeAnalysis || !Array.isArray(pathPoints[pathLineNum]) || pathPoints[pathLineNum].length === 0) {
               return alert('请先计算并绘制路径');
            }
            // 创建或复用 RoughAnalysis 实例（RoughAnalysis.js 需已被引入）
            window._RoughAnalysisInstance = window._RoughAnalysisInstance || new RoughAnalysis();
            const total = pathPoints.length;
            const indices = Array.from({length: total}, (_, i) => i);
            window._RoughAnalysisInstance.showMultipleRoughness(indices, pathPoints, window.SlopeAnalysis.pathLines);
        }// 陡峭度分析绘制二维图
        function showRoughnessRateChart() {
            let pathLineNum = window.SlopeAnalysis.pathLineNum - 1;// 每一个当前pathLineNum都是为下一条将要绘制的线准备的，即对应数字是没数据的pathPoints
            let pathPoints = window.SlopeAnalysis.pathPoints;

           if (!window.SlopeAnalysis || !Array.isArray(pathPoints[pathLineNum]) || pathPoints[pathLineNum].length === 0) {
               return alert('请先计算并绘制路径');
           }
           // 创建或复用 RoughAnalysis 实例（RoughAnalysis.js 需已被引入）
           window._RoughAnalysisInstance = window._RoughAnalysisInstance || new RoughAnalysis();
           const total = pathPoints.length;
           const indices = Array.from({length: total}, (_, i) => i);
           window._RoughAnalysisInstance.showMultipleRoughnessRate(indices, pathPoints, window.SlopeAnalysis.pathLines);
        }// 陡峭度变化分析绘制二维图
        function showHeightRateChart() { 
            let pathLineNum = window.SlopeAnalysis.pathLineNum - 1;// 每一个当前pathLineNum都是为下一条将要绘制的线准备的，即对应数字是没数据的pathPoints
            let pathPoints = window.SlopeAnalysis.pathPoints;

            if (!window.SlopeAnalysis || !Array.isArray(pathPoints[pathLineNum]) || pathPoints[pathLineNum].length === 0) {
               return alert('请先计算并绘制路径');
            }
            window._RoughAnalysisInstance = window._RoughAnalysisInstance || new RoughAnalysis();
            const total = pathPoints.length;
            const indices = Array.from({length: total}, (_, i) => i);
            window._RoughAnalysisInstance.showMultipleHeightRate(indices, pathPoints, window.SlopeAnalysis.pathLines);  
        }// 高程变化率分析绘制二维图

        const setAnalysisNumericTipEnabled = (enabled) => {
            const flag = !!enabled;
            window.__analysisNumericTipEnabled = flag;
            const hasUnifiedSlopeTip = !!(window.SlopeAnalysis && typeof window.SlopeAnalysis.openTip === 'function' && typeof window.SlopeAnalysis.closeTip === 'function');

            if (hasUnifiedSlopeTip) {
                if (flag) {
                    window.SlopeAnalysis.openTip();
                } else {
                    window.SlopeAnalysis.closeTip();
                }
            }

            if (typeof window.setTerrainBackendNumericTipEnabled === 'function') {
                // Prefer one unified handler to avoid multiple MOUSE_MOVE handlers fighting each other.
                if (hasUnifiedSlopeTip) {
                    window.setTerrainBackendNumericTipEnabled(false);
                } else {
                    window.setTerrainBackendNumericTipEnabled(flag);
                }
            }

            const sidebarToggle = document.querySelector('#sidebarWindowComponents input[value="numeric-tip"]');
            if (sidebarToggle && sidebarToggle.checked !== flag) {
                sidebarToggle.checked = flag;
            }
        };
        window.setAnalysisNumericTipEnabled = setAnalysisNumericTipEnabled;

        document.getElementById('openTipBtn')?.addEventListener('click', () => {
            setAnalysisNumericTipEnabled(true);
        });
        document.getElementById('closeTipBtn')?.addEventListener('click', () => {
            setAnalysisNumericTipEnabled(false);
        });
        
        document.querySelector('#ShowAHP')?.addEventListener('click', () => { 
            SlopeAnalysis.AHPanalysistest();
        });// AHP综合分析

        document.querySelector('#Ridge_Valley_Analysis')?.addEventListener('click', () => { 
            // if(SlopeAnalysis.slopeCostGrid.length == 0){alert('请生成二维高程栅格，再提取山脊与山谷')}//在函数内实现判断了
            window.SlopeAnalysis.Ridge_Valley_Analysis();
        });// 山脊与山谷提取

        document.querySelector('#Curvature_Analysis')?.addEventListener('click', () => {
            if(!window.SlopeAnalysis || window.SlopeAnalysis.slopeCostGrid.length === 0){
                return alert('请先计算坡度/坡向网格，再进行曲率分析');
            }
            window.SlopeAnalysis.DrawCurvatureMap();

            document.getElementById('curvature-layer').checked = true;
            if (document.getElementById('slope-layer').checked) {
                document.getElementById('slope-layer').checked = false;
                window.SlopeAnalysis.slopeLayerVisibility();
            }
            if (document.getElementById('aspect-layer').checked) {
                document.getElementById('aspect-layer').checked = false;
                window.SlopeAnalysis.aspectLayerVisibility();
            }
            if (document.getElementById('cost-layer').checked) {
                document.getElementById('cost-layer').checked = false;
                window.SlopeAnalysis.costLayerVisibility();
            }
        });// 曲率分析

        document.querySelector('#clearAll').addEventListener('click', () => {
            window.SlopeAnalysis.clearAll();
            if (typeof window.clearTerrainBackendLayers === 'function') {
                window.clearTerrainBackendLayers();
            }
        });// 清除所有

        // 关闭面板不做图层清理，保留当前分析结果。

    },
    //场景收藏
    dataURLtoBlob: function (dataurl) {
        console.log('dataurl=' + dataurl);
        let arr = dataurl.split(',')
        //console.log('arr='+arr)
        let mime = arr[0].match(/:(.*?);/)[1]
        //console.log('mime='+mime)
        //mime=image/octet-stream
        let bstr = atob(arr[1])
        //解码64位编码 png格式 乱码
        //console.log('bstr='+bstr)
        let n = bstr.length
        //console.log('n=' + n)
        //n=955759
        let u8arr = new Uint8Array(n)
        //输出全为0的数组  长度为n
        while (n--) {
            u8arr[n] = bstr.charCodeAt(n);
            //输出数字
        }
        return new Blob([u8arr], { type: mime });
        /*blobParts： 数组类型， 数组中的每一项连接起来构成Blob对象的数据，数组中的每项元素可以是ArrayBuffer(二进制数据缓冲区), ArrayBufferView,Blob,DOMString。或其他类似对象的混合体。
          options： 可选项，字典格式类型，可以指定如下两个属性：
    */
    },
    //加载tif数据（用到的模块：影像数据、
    loadTif: function () {
        $('#loadLayerWin').css('display', 'block');
        $('#sureTifUrl').click(function () {
            console.log('确定')
            var tifUrl = $('#tifUrl').val();
            var layername = $('#layerName').val();
            //分析url地址
            let res = {}
            const urlObj = new URL(tifUrl);
            console.dir(urlObj);
            // const params = new URLSearchParams(urlObj.search);
            // console.log(params);
            urlObj.searchParams.forEach((value, key) => {
                res[key] = value;

            })
            let layerPos = res.bbox.split(',')//bbbox--boundingbox，即是网址框内输入的url内容，通过split分割，由‘，’作分割判断（可优化完善分割条件，提升网址内容辨析精度，从url获得信息更丰富）
            tifUrl = urlObj.origin + urlObj.pathname + "?" + res.service;
            console.log('tifUrl: ' + tifUrl);

            providerLayer = new Cesium.WebMapServiceImageryProvider({
                url: tifUrl,    //协议路径
                layers: layername,  //图层名称
                parameters: {
                    service: 'WMS',   //服务类型
                    format: 'image/png',
                    transparent: true,  //透明度
                }
            })
            // console.dir(providerLayer._tileProvider);
            // console.log(viewer.imageryLayers);
            // fetch(tifUrl).then((res) => console.log(res))
            viewer.imageryLayers.addImageryProvider(providerLayer)
            viewer.camera.flyTo({
                //luding
                // destination: Cesium.Cartesian3.fromDegrees(102.220, 29.833, 13000)
                destination: Cesium.Cartesian3.fromDegrees(+layerPos[0], +layerPos[1], 5000)//经度，纬度，相机高度

                //ali
                //destination:Cesium.Cartesian3.fromDegrees(78.82,33.196 ,13000)
                //sana
                // destination: Cesium.Cartesian3.fromDegrees(44.221081, 15.47648, 13000)
                //冒县
                //destination:Cesium.Cartesian3.fromDegrees(99.90852,23.80457,13000)

            }
            )
            let layers = viewer.imageryLayers._layers[0]
            console.log(layers);


        })
        $('#delLayer').click(function () {
            //删除图层
            viewer.imageryLayers.get(viewer.imageryLayers.length - 1).show = false;
            /*viewer.imageryLayers.removeAll();*/
        })
    },
    //加载三维模型
    load3Dtiles: function () {
        let tileset = new Cesium.Cesium3DTileset({ url: '/cesium_old/data/3DTiles/white/tileset.json' });
        viewer.scene.primitives.add(tileset);
        viewer.flyTo(tileset);
    },
    //跟图回放
    czmlTrack: function () {
        $('#czml-trackWin').css('display', 'block');
        var drawHelper = new DrawHelper(viewer);
        //三维飞行初始化
        bxmap.FlyCesium.Init(viewer, drawHelper);//初始化漫游飞行路径功能
    },
    //避打区域分析
    AvoidanceAreaAnalysis: function () {
        //避打区域分析
        $('#avoidanceAreaAnalysisWin').css('display', 'block');

        //根据文件添加
        function handleFileSelect(evt) {
            var files = evt.target.files; // files为局部变量 去掉var就是全局变量
            for (var i = 0, f; f = files[i]; i++) {
                var reader = new FileReader();//通过构造函数初始化一个FileReader对象。您可以指示FileReader将文件读取为数组缓冲区、数据 URL 或文本
                reader.onload = function (theFile)//事件在读取完成后触发。
                {
                    return function (e) {
                        let txt_info = reader.result.split("\n");//x1是数组
                        //console.log(x1.length);
                        //console.log(x1.length);
                        for (let i = 0; i < txt_info.length; i++) {

                            let single_txt_info = txt_info[i].split(" ");
                            //经纬度  内外圈半径
                            let rdf_longitude = single_txt_info[2];
                            let rdf_latitude = single_txt_info[3];
                            let out_radius = single_txt_info[4];
                            let inner_radius = single_txt_info[5];
                            //添加圆形实体
                            let circleBig = viewer.entities.add({
                                position: Cesium.Cartesian3.fromDegrees(rdf_longitude, rdf_latitude),
                                ellipse: {
                                    semiMajorAxis: out_radius,
                                    semiMinorAxis: out_radius,
                                    material: Cesium.Color.RED.withAlpha(0.4),
                                }
                            })
                            let circleSmall = viewer.entities.add({
                                position: Cesium.Cartesian3.fromDegrees(rdf_longitude, rdf_latitude),
                                ellipse: {
                                    semiMinorAxis: inner_radius,
                                    semiMajorAxis: inner_radius,
                                    material: Cesium.Color.BLUE.withAlpha(0.5)
                                }
                            })
                            console.log("jiazai chenggong ")
                            viewer.zoomTo(circleBig)

                        }
                    };
                }(f);
                reader.readAsText(f);
            }
        }

        document.getElementById('files').addEventListener('change', handleFileSelect, false);

        //根据输入经纬度  添加同心圆
        $('#sureCircle').click(function () {
            //中心经度、纬度、大圆半径、小圆半径
            var center_lat = $('#center_lat').val()
            var center_lng = $('#center_lng').val()
            var outer_radius = $('#outer_radius').val()
            var inner_radius = $('#inner_radius').val()
            console.log('center_lat=' + center_lat)
            console.log('center_lng=' + center_lng)
            //可以正常输出
            var circleBig = viewer.entities.add({
                position: Cesium.Cartesian3.fromDegrees(center_lng, center_lat),
                ellipse: {
                    semiMinorAxis: outer_radius,
                    semiMajorAxis: outer_radius,
                    material: Cesium.Color.RED.withAlpha(0.3)
                },

            })
            var circleSmall = viewer.entities.add({
                position: Cesium.Cartesian3.fromDegrees(center_lng, center_lat),
                ellipse: {
                    semiMajorAxis: inner_radius,
                    semiMinorAxis: inner_radius,
                    material: Cesium.Color.YELLOW.withAlpha(0.4)
                }
            })
            var circleCenter = viewer.entities.add({
                position: Cesium.Cartesian3.fromDegrees(center_lng, center_lat),
                billboard: {
                    image: 'libs/Cesium-1.93/Specs/Data/Images/Green2x2.png'
                }
            })
            viewer.zoomTo(circleBig)
        })
        //输入角点坐标输入矩形
        $('#sureRectangle').click(function () {
            var ws_lng = $('#ws_lng').val();
            var ws_lat = $('#ws_lat').val();
            var en_lng = $('#en_lng').val();
            var en_lat = $('#en_lat').val();
            var rectangle = viewer.entities.add({
                rectangle: {
                    coordinates: Cesium.Rectangle.fromDegrees(ws_lng, ws_lat, en_lng, en_lat),
                    material: Cesium.Color.YELLOW.withAlpha(0.5),
                    outline: true,
                    outlineColor: Cesium.Color.YELLOW
                }
            })
            viewer.zoomTo(rectangle)
        })
    },
    //空间量算 函数
    SpatialMeasure: function () {
        $('#spatialMeasureWin').css('display', 'block');
        /*111*/
        let measure = new Cesium.Measure(viewer);
        let clampToGround = true;
        console.log(measure)

        function loadModel() {
            viewer.flyTo(viewer.entities.add({
                position: Cesium.Cartesian3.fromDegrees(116.32878855240442, 39.95208707482746, 0.0),
                model: { uri: '../measure/qiche.gltf' }
            }))
        }

        $('.ctl button').on('click', function () {
            let text = $(this).text()
            if (text) {
                
                switch (text) {
                    case '不贴地':
                        clampToGround = false;
                        console.log('不贴地运行')
                        break;
                    case '空间距离':
                        measure.drawLineMeasureGraphics({
                            clampToGround: clampToGround, callback: () => {
                            }
                        });
                        break;
                    case '空间面积':
                        measure.drawAreaMeasureGraphics({
                            clampToGround: clampToGround, callback: () => {
                            }
                        });
                        break;
                    case '三角量测':
                        measure.drawTrianglesMeasureGraphics({
                            callback: () => {
                            }
                        });
                        break;
                    case '清除量测':
                        measure._drawLayer.entities.removeAll();
                        break;
                    case '加载模型':
                        loadModel();
                        break;
                }
            }
        })
    },
    //模型加载

    //数据加载
    dataLoad: function () {
        $('#loadDataWin').css('display', 'block');

        // ===== 防止重复绑定：仅在首次调用时绑定事件 =====
        if (EventModel._dataLoadInitialized) return;
        EventModel._dataLoadInitialized = true;

        // 存储已创建的Blob URLs
        let blobUrls = [];
        // 当前自动识别的数据类型
        let detectedType = null;

        // ==================== 文件类型自动识别 ====================
        /**
         * 根据文件名扩展名自动识别数据类型
         * @param {string} fileName - 文件名
         * @returns {string|null} 对应的数据类型
         */
        function detectDataType(fileName) {
            if (!fileName) return null;
            const name = fileName.toLowerCase();
            const ext = name.split('.').pop();
            // 按扩展名映射
            const typeMap = {
                'czml':    'CZML',
                'kml':     'KML',
                'kmz':     'KML',
                'json':    'GeoJson',   // .json 默认当 GeoJson；tileset.json 特殊处理
                'geojson': 'GeoJson',
                'glb':     'GLB',
                'gltf':    'Gltf',
                'tif':     'Tiff',
                'tiff':    'Tiff',
                'png':     'Tiff',      // 单张图片当 Tiff(SingleTileImageryProvider) 处理
                'jpg':     'Tiff',
                'jpeg':    'Tiff',
            };
            // 3DTiles: tileset.json
            if (name === 'tileset.json' || name.endsWith('/tileset.json')) {
                return 'Tileset';
            }
            return typeMap[ext] || null;
        }

        /**
         * 根据 URL 路径自动识别类型（对手动输入的 URL 路径）
         * @param {string} url - URL 或路径
         * @returns {string|null}
         */
        function detectDataTypeFromUrl(url) {
            if (!url) return null;
            const trimmed = url.trim().replace(/\/+$/, ''); // 去尾部斜杠
            // 如果路径以 / 结尾或包含典型 terrain 文件夹特征
            if (url.trim().endsWith('/') || trimmed.match(/(_ctb|_terrain|terrain)$/i)) {
                return 'Terrain';
            }
            // 按文件名识别
            const lastSegment = trimmed.split('/').pop().split('\\').pop();
            return detectDataType(lastSegment);
        }

        /**
         * 更新界面上显示的识别类型
         */
        function updateDetectedTypeDisplay(type) {
            detectedType = type;
            const label = document.getElementById('detectedTypeLabel');
            if (label) {
                label.textContent = type || '未识别';
                label.style.color = type ? '#70bdf9' : '#ff6b6b';
            }
        }

        // 获取DOM元素
        const uploadArea = document.getElementById('uploadArea');
        const fileInput = document.getElementById('fileInput');
        const terrainFolderBtn = document.getElementById('terrainFolderBtn');
        const terrainFolderInput = document.getElementById('terrainFolderInput');
        
        // 点击上传区域时触发文件选择
        uploadArea.addEventListener('click', () => {
            fileInput.click();
        });
        
        // 文件选择后处理
        fileInput.addEventListener('change', (e) => {
            handleFiles(e.target.files);
            fileInput.value = '';
        });

        // ==================== Terrain 文件夹选择 ====================
        terrainFolderBtn.addEventListener('click', () => {
            terrainFolderInput.click();
        });

        terrainFolderInput.addEventListener('change', (e) => {
            const files = e.target.files;
            if (files.length > 0) {
                // 获取文件夹路径：取第一个文件的 webkitRelativePath 的第一段
                const firstPath = files[0].webkitRelativePath;
                const folderName = firstPath.split('/')[0];
                // 设置 URL 为相对路径（用户需确保服务器可访问）
                const folderUrl = './data/DEM/' + folderName + '/';
                document.getElementById("loadDataUrl_text").value = folderUrl;
                document.getElementById("loadDataUrl_text").dataset.fileName = folderName;
                updateDetectedTypeDisplay('Terrain');
                console.log('[dataLoad] 选择 Terrain 文件夹:', folderName, '→', folderUrl);
            }
            terrainFolderInput.value = '';
        });
        
        // 阻止拖拽时的默认行为
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            uploadArea.addEventListener(eventName, preventDefaults, false);
            document.body.addEventListener(eventName, preventDefaults, false);
        });
        
        // 添加拖拽时的视觉反馈
        ['dragenter', 'dragover'].forEach(eventName => {
            uploadArea.addEventListener(eventName, highlight, false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            uploadArea.addEventListener(eventName, unhighlight, false);
        });
        
        // 处理文件拖拽放置事件
        uploadArea.addEventListener('drop', handleDrop, false);
        
        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        function highlight() {
            uploadArea.classList.add('dragover');
        }
        
        function unhighlight() {
            uploadArea.classList.remove('dragover');
        }
        
        function handleDrop(e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            handleFiles(files);
        }
        
        // 处理选择的文件（自动识别类型）
        function handleFiles(files) {
            if (files.length > 0) {
                for (let i = 0; i < files.length; i++) {
                    const file = files[i];
                    const blobUrl = URL.createObjectURL(file);
                    blobUrls.push(blobUrl);
                    console.log('[dataLoad] 文件:', file.name, '→ blobUrl:', blobUrl);
                
                    document.getElementById("loadDataUrl_text").value = blobUrl;
                    document.getElementById("loadDataUrl_text").dataset.fileName = file.name;

                    // 自动识别文件类型
                    const type = detectDataType(file.name);
                    updateDetectedTypeDisplay(type);
                }
            }
        }

        // 监听 URL 输入框变化，自动识别路径对应的类型
        document.getElementById("loadDataUrl_text").addEventListener('input', function() {
            const type = detectDataTypeFromUrl(this.value);
            updateDetectedTypeDisplay(type);
        });

        // 页面卸载时清理Blob URLs
        window.addEventListener('beforeunload', () => {
            blobUrls.forEach(url => {
                URL.revokeObjectURL(url);
            });
        });

        // ==================== 取消/加载按钮 ====================
        $('#loadDataWin .cansole_btn').off('click').on('click', function () {
            $('#loadDataWin').css('display', 'none');
            $("#maskalpha").attr("disabled", true);
        });

        $('#loadDataWin .sure_btn').off('click').on('click', function () {
            var dataUrl = $('.loadDataUrl_text').val();
            var originalFileName = document.getElementById("loadDataUrl_text").dataset.fileName || null;
            // 自动识别的类型（也可从 URL 重新识别）
            var dataType = detectedType || detectDataTypeFromUrl(dataUrl);
            $("#maskalpha").attr("disabled", false);

            if (!dataUrl) {
                showMessageInfo('地址不能为空');
                return;
            }
            if (!dataType) {
                showMessageInfo('无法识别文件类型，请检查文件格式');
                return;
            }

            console.log('[dataLoad] 加载:', dataType, dataUrl, '原始文件名:', originalFileName);

            switch (dataType) {
                case 'Terrain':
                    var terrainProvider = new Cesium.CesiumTerrainProvider({
                        url: dataUrl
                    });
                    viewer.terrainProvider = terrainProvider;

                    // 注册到侧边栏图层管理
                    if (window.sidebarManager) {
                        window.sidebarManager.addLayer({
                            name: originalFileName,
                            type: 'Terrain',
                            url: dataUrl,
                            cesiumObject: terrainProvider,
                            extras: {}
                        });
                    }

                    viewer.scene.globe.depthTestAgainstTerrain = true;

                    // 鼠标左键查询高程
                    var CesiumEventHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
                    var Clickpoints = [];
                    var pointcolor = 0;

                    CesiumEventHandler.setInputAction(function (movement) {
                        var color1 = new Cesium.Color(1.0, pointcolor, 0.0, 1);
                        pointcolor = pointcolor + 0.1;
                        var ray = viewer.camera.getPickRay(movement.position);
                        var cartesian = viewer.scene.globe.pick(ray, viewer.scene);
                        if (cartesian) {
                            var cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                            var longitudeDegree = Cesium.Math.toDegrees(cartographic.longitude);
                            var latitudeDegree = Cesium.Math.toDegrees(cartographic.latitude);
                            var cartographic2 = Cesium.Cartographic.fromDegrees(longitudeDegree, latitudeDegree);
                            console.log('height:', viewer.scene.globe.getHeight(cartographic));
                            var promise = Cesium.sampleTerrainMostDetailed(terrainProvider, [cartographic2]);
                            point = new Cesium.Entity({
                                position: cartesian,
                                point: {
                                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                                    disableDepthTestDistance: Number.POSITIVE_INFINITY,
                                    color: color1,
                                    pixelSize: 10
                                }
                            });
                            Clickpoints.push(viewer.entities.add(point));
                            promise.then(function (updatedPositions) {
                                if (updatedPositions.length > 0) {
                                    console.log(
                                        'lng:' + Cesium.Math.toDegrees(updatedPositions[0].longitude) +
                                        ',lat:' + Cesium.Math.toDegrees(updatedPositions[0].latitude) +
                                        ',height:' + (updatedPositions[0].height ? updatedPositions[0].height : 0));
                                } else {
                                    console.log('无法获取高程');
                                }
                            });
                        }
                    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

                    CesiumEventHandler.setInputAction(() => {
                        while (Clickpoints.length > 0) {
                            viewer.entities.remove(Clickpoints[Clickpoints.length - 1]);
                            Clickpoints.pop();
                        }
                    }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);

                    $('.close').click(function () {
                        while (Clickpoints.length > 0) {
                            viewer.entities.remove(Clickpoints[Clickpoints.length - 1]);
                            Clickpoints.pop();
                        }
                        CesiumEventHandler.destroy();
                        $(this.parentNode.parentNode).css('display', 'none');
                    });

                    break;
                case 'CZML':
                    var czml = new Czml(dataUrl);
                    if (window.sidebarManager) {
                        setTimeout(() => {
                            var ds = viewer.dataSources.get(viewer.dataSources.length - 1);
                            window.sidebarManager.addLayer({ name: originalFileName, type: 'CZML', url: dataUrl, cesiumObject: ds });
                        }, 2000);
                    }
                    break;
                case 'Tileset':
                    var tileset = new Tileset(dataUrl);
                    if (window.sidebarManager) {
                        setTimeout(() => {
                            var lastPrim = viewer.scene.primitives.get(viewer.scene.primitives.length - 1);
                            window.sidebarManager.addLayer({ name: originalFileName, type: 'Tileset', url: dataUrl, cesiumObject: lastPrim });
                        }, 2000);
                    }
                    break;
                case 'KML':
                    var kmlUrl = dataUrl;
                    new Cesium.KmlDataSource.load(kmlUrl, {
                        camera: viewer.scene.camera,
                        canvas: viewer.scene.canvas,
                        clampToGround: true
                    }).then(function(dataSource) {
                        viewer.dataSources.add(dataSource);
                        viewer.flyTo(dataSource);
                        if (window.sidebarManager) {
                            window.sidebarManager.addLayer({ name: originalFileName, type: 'KML', url: kmlUrl, cesiumObject: dataSource });
                        }
                    });
                    break;
                case 'GeoJson':
                    var geojsonUrl = dataUrl;
                    new Cesium.GeoJsonDataSource.load(geojsonUrl, {
                        clampToGround: true,
                        stroke: Cesium.Color.BLACK,
                        fill: Cesium.Color.ORANGE.withAlpha(0.6),
                        strokeWidth: 5,
                        markerSize: 10,
                        markerSymbol: '●'
                    }).then(function (dataSource) {
                        viewer.dataSources.add(dataSource);
                        viewer.flyTo(dataSource);
                        if (window.sidebarManager) {
                            window.sidebarManager.addLayer({ name: originalFileName, type: 'GeoJson', url: geojsonUrl, cesiumObject: dataSource });
                        }
                    });
                    break;
                case 'GLB':
                    var position = Cesium.Cartesian3.fromDegrees(103.5, 29.8, 2000.0);
                    var heading = Cesium.Math.toRadians(0);
                    var pitch = Cesium.Math.toRadians(0);
                    var roll = Cesium.Math.toRadians(0);
                    var hpr = new Cesium.HeadingPitchRoll(heading, pitch, roll);
                    var orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);
                    var entity = viewer.entities.add({
                        position: position,
                        orientation: orientation,
                        model: {
                            uri: dataUrl,
                            scale: 10,
                            color: Cesium.Color.fromCssColorString("rgba(254, 129, 6, 0.65)"),
                            silhouetteColor: Cesium.Color.fromCssColorString("#001aff"),
                            silhouetteSize: 5,
                            colorBlendMode: Cesium.ColorBlendMode.MIX,
                            runAnimations: true,
                            shadows: Cesium.ShadowMode.CAST_ONLY,
                            colorBlendAmount: 0
                        }
                    });
                    viewer.flyTo(entity);
                    if (window.sidebarManager) {
                        window.sidebarManager.addLayer({ name: originalFileName, type: 'GLB', url: dataUrl, cesiumObject: entity });
                    }
                    break;
                case 'Gltf':
                    var Gltif = new Gltf(dataUrl);
                    modelEntity = Gltif.modelEntity;
                    console.log(Gltif.modelEntity.orientation.getValue());
                    console.log(Gltif.modelEntity.model.maximumScale.getValue());
                    if (window.sidebarManager) {
                        window.sidebarManager.addLayer({ name: originalFileName, type: 'Gltf', url: dataUrl, cesiumObject: Gltif.modelEntity });
                    }

                    let temp = Cesium.Ellipsoid.WGS84.cartesianToCartographic(Gltif.modelEntity.position.getValue());
                    $('#modelWindow').css('display', 'block');
                    $('#modelLat').val(temp.latitude * (180 / Math.PI));
                    $('#modelLon').val(temp.longitude * (180 / Math.PI));
                    $('#modelHeight').val(temp.height);
                    temp.height += 3000;
                    viewer.camera.setView({ destination: Cesium.Ellipsoid.WGS84.cartographicToCartesian(temp) });
                    viewer.trackedEntity = Gltif.modelEntity;

                    var scene = viewer.scene;
                    var handler = new Cesium.ScreenSpaceEventHandler(scene.canvas);
                    var isDragging = false;
                    var pickedEntity;
                    var initialPosition;
                    var dragStartPosition;
                    viewer.scene.globe.depthTestAgainstTerrain = true;

                    handler.setInputAction(function (click) {
                        var pickedObject = scene.pick(click.position);
                        if (Cesium.defined(pickedObject) && pickedObject.id === Gltif.modelEntity) {
                            isDragging = true;
                            modelEntity = pickedObject.id;
                            pickedEntity = pickedObject.id;
                            initialPosition = pickedEntity.position.getValue(viewer.clock.currentTime);
                            dragStartPosition = scene.camera.pickEllipsoid(click.position);
                            viewer.scene.screenSpaceCameraController.enableRotate = false;
                        }

                        handler.setInputAction(function (movement) {
                            if (isDragging) {
                                var cartesian = viewer.scene.pickPosition(movement.endPosition);
                                if (Cesium.defined(cartesian)) {
                                    var cartographic = Cesium.Cartographic.fromCartesian(cartesian);
                                    let height = scene.globe.getHeight(cartographic);
                                    var newPosition2 = Cesium.Cartesian3.fromRadians(cartographic.longitude, cartographic.latitude, height);
                                    pickedEntity.position = newPosition2;
                                }
                            }
                        }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

                        handler.setInputAction(function () {
                            isDragging = false;
                            if (pickedEntity) {
                                let temp = Cesium.Ellipsoid.WGS84.cartesianToCartographic(pickedEntity.position.getValue());
                                $('#modelLat').val(temp.latitude * (180 / Math.PI));
                                $('#modelLon').val(temp.longitude * (180 / Math.PI));
                                $('#modelHeight').val(temp.height);
                            }
                            viewer.scene.screenSpaceCameraController.enableRotate = true;
                            pickedEntity = undefined;
                        }, Cesium.ScreenSpaceEventType.LEFT_UP);
                    }, Cesium.ScreenSpaceEventType.LEFT_DOWN);

                    break;
                case 'Tiff':
                    var tiffHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
                    var imageryProvider = new Cesium.SingleTileImageryProvider({
                        "url": dataUrl,
                        id: '1',
                    });
                    const tifLayer = viewer.scene.imageryLayers.addImageryProvider(imageryProvider);

                    if (window.sidebarManager) {
                        window.sidebarManager.addLayer({
                            name: originalFileName,
                            type: 'Tiff',
                            url: dataUrl,
                            cesiumObject: tifLayer,
                            extras: { eventHandler: tiffHandler }
                        });
                    }

                    var maskalpha = document.getElementById('maskalpha');
                    maskalpha.addEventListener('input', function () {
                        document.getElementById('maskalpha_val').innerText = maskalpha.value;
                        tifLayer.alpha = maskalpha.value;
                    });

                    tiffHandler.setInputAction(function () {
                        viewer.scene.imageryLayers.remove(tifLayer);
                        tiffHandler.destroy();
                    }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);

                    break;
                default:
                    showMessageInfo('不支持的文件类型: ' + dataType);
                    break;
            }
        });
    },

    /***********************************标绘*******************************************************/
    //标绘
    mark_draw: function () {
        //按键到此
        $('#markWin').css('display', 'block');

        tracker = new GlobeTracker(viewer);

        $('#drawPolygon').click(function () {
            falg = 0;
            tracker.trackPolygon(function (positions) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = positions;
                showPolygon(objId, positions);
            })
        });

        $("#drawPolyline").click(function () {
            flag = 0;
            tracker.trackPolyline(function (positions) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = positions;
                showPolyline(objId, positions);
            });
        });
        $("#drawRectangle").click(function () {
            flag = 0;
            tracker.trackRectangle(function (positions) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = positions;
                showRectangle(objId, positions);
            });
        });
        $("#drawCircle").click(function () {
            flag = 0;
            tracker.trackCircle(function (positions) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = positions;
                showCircle(objId, positions);
            });
        });
        $("#drawPoint").click(function () {
            flag = 0;
            tracker.trackPoint(function (position) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = position;
                showPoint(objId, position);
            });
        });
        $("#posMeasure").click(function () {
            flag = 0;
            tracker.pickPosition(function (position, lonLat) {
            });
        });
        $("#drawBufferLine").click(function () {
            flag = 0;
            tracker.trackBufferLine(function (positions, radius) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = {
                    positions: positions,
                    radius: radius
                };
                showBufferLine(objId, positions, radius);
            });
        });
        $("#straightArrow").click(function () {
            flag = 0;
            tracker.trackStraightArrow(function (positions) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = positions;
                showStraightArrow(objId, positions);
            });
        });
        $("#attackArrow").click(function () {
            flag = 0;
            tracker.trackAttackArrow(function (positions, custom) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = {
                    custom: custom,
                    positions: positions
                };
                showAttackArrow(objId, positions);
            });
        });
        $("#pincerArrow").click(function () {
            flag = 0;
            tracker.trackPincerArrow(function (positions, custom) {
                var objId = (new Date()).getTime();
                shapeDic[objId] = {
                    custom: custom,
                    positions: positions
                };
                showPincerArrow(objId, positions);
            });
        });
        $("#editShape").click(function () {
            layer.msg("点击要编辑的箭头！");
            flag = 1;
            //清除标绘状态
            tracker.clear();
        });
        $("#deleteShape").click(function () {
            layer.msg("点击要删除的箭头！");
            flag = 2;
            //清除标绘状态
            tracker.clear();
        });
        var handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
        handler.setInputAction(function (movement) {
            //鼠标选中对象
            var pick = viewer.scene.pick(movement.position);
            //没有选中对象
            if (!pick) {
                return;
            }
            var obj = pick.id;
            //如果没有点击选中图形或删除图形按钮，flag=0 直接返回
            if (!obj || !obj.layerId || flag == 0) {
                return;
            }
            var objId = obj.objId;
            console.log('obj=' + objId)  //输出鼠标选中对象的id
            console.log('flag=' + flag)
            //flag为编辑或删除标识,1为编辑，2为删除
            if (flag == 1) {
                switch (obj.shapeType) {
                    case "Polygon":
                        flag = 0;
                        editPolygon(objId);
                        break;
                    case "Polyline":
                        flag = 0;
                        editPolyline(objId);
                        break;
                    case "Rectangle":
                        flag = 0;
                        editRectangle(objId);
                        break;
                    case "Circle":
                        flag = 0;
                        editCircle(objId);
                        break;
                    case "Point":
                        flag = 0;
                        editPoint(objId);
                        break;
                    case "BufferLine":
                        flag = 0;
                        editBufferLine(objId);
                        break;
                    case "StraightArrow":
                        flag = 0;
                        editStraightArrow(objId);
                        break;
                    case "AttackArrow":
                        flag = 0;
                        editAttackArrow(objId);
                        break;
                    case "PincerArrow":
                        flag = 0;
                        editPincerArrow(objId);
                        break;
                    default:
                        break;
                }
            } else if (flag == 2) {
                clearEntityById(objId);
            }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    },


    /****************************窗口组件显示设置*************************/
    displaySetting: function () {
        // 旧弹窗保留但不再作为主入口，改为侧边栏“窗口组件”面板
        $('#displaySettingWin').css('display', 'none');
        $("#displaySettingWin input[type='checkbox'], #sidebarWindowComponents input[type='checkbox']")
        .off('change.displaySetting')
        .on('change.displaySetting', function () {
            switch ($(this).val()) {
                case 'toolbar':
                    if ($(this).is(':checked')) {
                        CesiumToolbar.init();
                    } else {
                        CesiumToolbar.hide();
                    }
                    break;
                case 'mapShadows':
                    if ($(this).is(':checked')) {
                        viewer.shadows = true;
                        viewer.terrainShadows = Cesium.ShadowMode.ENABLED;
                    } else {
                        viewer.shadows = false;
                        viewer.terrainShadows = Cesium.ShadowMode.DISABLED;
                    }
                    break;
                case 'waterMap':
                    if ($(this).is(':checked')) {
                        return;
                        var terrainProvider = Cesium.createWorldTerrain({
                            requestWaterMask: true,
                            requestVertexNormals: true
                        });
                        viewer.terrainProvider = terrainProvider;
                    } else {
                    }
                    break;
                case 'VRButton':
                    if ($(this).is(':checked')) {
                        $('.cesium-viewer-vrContainer').css('display', 'block');
                    } else {
                        $('.cesium-viewer-vrContainer').css('display', 'none');
                    }
                    break;
                case 'compass':
                    if ($(this).is(':checked')) {
                        $('.compass').css('display', 'block');
                    } else {
                        $('.compass').css('display', 'none');
                    }
                    break;
                case 'navigation-controls':
                    if ($(this).is(':checked')) {
                        $('.navigation-controls').css('display', 'block');
                    } else {
                        $('.navigation-controls').css('display', 'none');
                    }
                    break;
                case 'distance-legend':
                    if ($(this).is(':checked')) {
                        $('.distance-legend').css('display', 'block');
                    } else {
                        $('.distance-legend').css('display', 'none');
                    }
                    break;
                case 'time-controls':
                    if ($(this).is(':checked')) {
                        $('.cesium-viewer-animationContainer').css('display', 'block');
                        $('.cesium-viewer-timelineContainer').css('display', 'block');
                    } else {
                        $('.cesium-viewer-animationContainer').css('display', 'none');
                        $('.cesium-viewer-timelineContainer').css('display', 'none');
                    }
                    break;
                case 'fullscreen-controls':
                    if ($(this).is(':checked')) {
                        $('.cesium-fullscreenButton').css('display', 'block');
                    } else {
                        $('.cesium-fullscreenButton').css('display', 'none');
                    }
                    break;
                case 'numeric-tip':
                    if (typeof window.setAnalysisNumericTipEnabled === 'function') {
                        window.setAnalysisNumericTipEnabled($(this).is(':checked'));
                    }
                    break;
                default:
                    break;
            }
        });
    },
    //跟图回放相关函数
    /**
     * 清空漫游路径
     * @method stopFly3DPaths
     * @param
     * @return
     */
    clearFly3DPaths: function () {
        this.cesiumViewer.trackedEntity = undefined;
        bxmap.FlyCesium.isDrawFly = false;
        bxmap.FlyCesium.draw3DObj = null;
        this.cesiumViewer.entities.removeAll();//清空所有模型
        //清空绘制飞行路线
        if (this.drawPolyline) {
            this.cesiumViewer.scene.primitives.remove(this.drawPolyline);
            this.drawPolyline = null;
        }
    },
    /**
     * 飞行漫游路径
     * @method showFly3DPaths
     * @param  pathsData 飞行路径信息,格式如下:{"orientation":{"heading":2.411783930363565,"pitch":-0.21097267398444197,"roll":0.0015622392231300353},"position": {"x":-2206260.239730831,"y":5510911.392077349,"z":2331987.10863007}, "geometry":{"type": "LineString", "coordinates": [[101.80089882736969, 26.60700234866561], [101.80082205161088, 26.607156056057718]]} }
     * @param  position 飞行路径跳转位置
     * @return
     */
    showFly3DPaths: function (pathsData) {
        var T = this;
        this.clearFly3DPaths();
        T.cesiumViewer.camera.setView({
            destination: pathsData.position,
            orientation: pathsData.orientation,
        });
        setTimeout(function () {
            executeFly3D();
        }, 200);

        function executeFly3D() {
            if (pathsData && pathsData.geometry) {
                var positionA = pathsData.geometry.coordinates;
                var position = [];
                if (positionA.length > 0) {
                    for (var i = 0; i < positionA.length; i++) {
                        var x = positionA[i][0];
                        var y = positionA[i][1];
                        position.push({ x: x, y: y });
                    }
                } else {
                    return;
                }

                function computeCirclularFlight() {
                    var property = new Cesium.SampledPositionProperty();
                    for (var i = 0; i < position.length; i++) {
                        if (i == 0) {
                            var time = Cesium.JulianDate.addSeconds(start, i, new Cesium.JulianDate());
                            //var _position = Cesium.Cartesian3.fromDegrees(position[i].x, position[i].y, 1170);
                            var _position = Cesium.Cartesian3.fromDegrees(position[i].x, position[i].y, 0);
                            property.addSample(time, _position);
                        }
                        if (i < 10000 && i > 0) {
                            var position_a = new Cesium.Cartesian3(property._property._values[i * 3 - 3], property._property._values[i * 3 - 2], property._property._values[i * 3 - 1]);
                            if (i < 976) {
                                //var _position = Cesium.Cartesian3.fromDegrees(position[i].x, position[i].y, 1170);
                                var _position = Cesium.Cartesian3.fromDegrees(position[i].x, position[i].y, 0);
                            } else if (i > 975 && i < 986) {
                                //var _position = Cesium.Cartesian3.fromDegrees(position[i].x, position[i].y, 1170 + 20 * (i - 980));
                                var _position = Cesium.Cartesian3.fromDegrees(position[i].x, position[i].y, 0);
                            } else if (i > 985) {
                                //var _position = Cesium.Cartesian3.fromDegrees(position[i].x, position[i].y, 1170 + 200);
                                var _position = Cesium.Cartesian3.fromDegrees(position[i].x, position[i].y, 0);
                            }

                            var positions = [Cesium.Ellipsoid.WGS84.cartesianToCartographic(position_a), Cesium.Ellipsoid.WGS84.cartesianToCartographic(_position)];
                            var a = new Cesium.EllipsoidGeodesic(positions[0], positions[1]);
                            var long = a.surfaceDistance;
                            var _time = long / 50;
                            var time = Cesium.JulianDate.addSeconds(property._property._times[i - 1], _time, new Cesium.JulianDate());

                            property.addSample(time, _position);
                        }
                    }
                    return property;
                }

                var start = Cesium.JulianDate.fromDate(new Date(2018, 3, 15, 16));
                var stop = Cesium.JulianDate.addSeconds(start, 30000, new Cesium.JulianDate());

                //Make sure viewer is at the desired time.
                T.cesiumViewer.clock.startTime = start.clone();
                T.cesiumViewer.clock.stopTime = stop.clone();
                T.cesiumViewer.clock.currentTime = start.clone();
                T.cesiumViewer.clock.clockRange = Cesium.ClockRange.LOOP_STOP; //Loop at the end
                //T.cesiumViewer.clock.clockRange = Cesium.ClockRange.UNBOUNDED; //
                //T.cesiumViewer.clock.clockStep = Cesium.ClockStep.SYSTEM_CLOCK; //
                //T.cesiumViewer.clock.multiplier = 10;//值越大，飞行越快
                T.cesiumViewer.clock.multiplier = 0.6;
                T.cesiumViewer.clock.canAnimate = false;
                T.cesiumViewer.clock.shouldAnimate = true;//设置时间轴动态效果

                var _position = computeCirclularFlight();

                T.entityFly = T.cesiumViewer.entities.add({
                    //Set the entity availability to the same interval as the simulation time.
                    availability: new Cesium.TimeIntervalCollection([new Cesium.TimeInterval({
                        start: start,
                        stop: stop
                    })]),
                    position: _position,
                    orientation: new Cesium.VelocityOrientationProperty(_position),
                    /*model: {
                        uri:GLOBAL.domainResource+"/systems/common-bx-gis/models/cesium/SampleData/models/CesiumAir/Cesium_Air.gltf",
                        scale: 6,
                        minimumPixelSize: 64,
                        //heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND
                    },*/
                    point: {
                        color: Cesium.Color.RED,
                        outlineColor: Cesium.Color.WHITE,
                        outlineWidth: 2,
                        pixelSize: 15,
                    },
                    //Show the path as a pink line sampled in 1 second increments.
                    path: {
                        resolution: 1,
                        material: new Cesium.PolylineGlowMaterialProperty({
                            glowPower: 0.1,
                            color: Cesium.Color.YELLOW
                        }),
                        //width: 30
                        width: 10
                    }
                });
                T.cesiumViewer.trackedEntity = T.entityFly;
                setTimeout(function () {
                    T.cesiumViewer.camera.zoomOut(500.0);//缩小地图，避免底图没有数据
                }, 100);
            } else {
                return;
            }
        }
    },
    /**
     * 暂停飞行漫游路径
     * @method pauseFly3DPaths
     * @return
     */
    pauseFly3DPaths: function () {
        var clockViewModel = this.cesiumViewer.clockViewModel;
        if (clockViewModel.shouldAnimate) {
            clockViewModel.shouldAnimate = false;
        } else if (this.cesiumViewer.clockViewModel.canAnimate) {
            clockViewModel.shouldAnimate = true;
        }
    },
    /**
     * 向前飞行漫游路径
     * @method playForwardFly3DPaths
     * @return
     */
    playForwardFly3DPaths: function () {
        var clockViewModel = this.cesiumViewer.clockViewModel;
        var multiplier = clockViewModel.multiplier;
        if (multiplier < 0) {
            clockViewModel.multiplier = -multiplier;
        }
        clockViewModel.shouldAnimate = true;
    },
    /**
     * 向后飞行漫游路径
     * @method playForwardFly3DPaths
     * @return
     */
    playReverseFly3DPaths: function () {
        var clockViewModel = this.cesiumViewer.clockViewModel;
        var multiplier = clockViewModel.multiplier;
        if (multiplier > 0) {
            clockViewModel.multiplier = -multiplier;
        }
        clockViewModel.shouldAnimate = true;
    },
    /**
     * 设定飞行漫游路径
     * @method DrawFly3DPaths
     * @return
     */
    DrawFly3DPaths: function (drawHelper) {
        var T = this;
        this.clearFly3DPaths();
        drawHelper.startDrawingPolyline({
            callback: function (positions) {
                T.drawPolyline = new DrawHelper.PolylinePrimitive({
                    positions: positions,
                    width: 5,
                    type: "plot",
                    geodesic: true
                });
                T.cesiumViewer.scene.primitives.add(T.drawPolyline);
                T.drawPolyline.setEditable();
                //构造设定路线的返回信息
                var coordinates = [];
                var position = null;
                var heading = null;
                var pitch = null;
                var roll = null;
                for (var i = 0; i < positions.length; i++) {
                    var cartographic = Cesium.Cartographic.fromCartesian(positions[i]);//世界坐标转地理坐标（弧度）
                    var point = [cartographic.longitude / Math.PI * 180, cartographic.latitude / Math.PI * 180];//地理坐标（弧度）转经纬度坐标
                    //console.log(point);
                    coordinates.push(point);
                }
                //orientation":{"heading":2.411783930363565,"pitch":-0.21097267398444197,"roll":0.0015622392231300353},"position": {"x":-2206260.239730831,"y":5510911.392077349,"z":2331987.10863007},
                position = drawHelper._cameraPosition;
                heading = drawHelper._cameraHeading;
                pitch = drawHelper._cameraPitch;
                roll = drawHelper._cameraRoll;
                var pathsData = {
                    "orientation": { "heading": heading, "pitch": pitch, "roll": roll },
                    "position": position,
                    "geometry": { "type": "LineString", "coordinates": coordinates }
                };
                if (bxmap.FlyCesium) {
                    bxmap.FlyCesium.draw3DObj = T.draw3DObj = pathsData;
                    bxmap.FlyCesium.isDrawFly = true;
                }
                //return T.draw3DObj;

            }
        });
    },
    /**
     * 退出飞行漫游路径
     * @method stopFly3DPaths
     * @param
     * @return
     */
    stopFly3DPaths: function () {
        var start = Cesium.JulianDate.fromDate(new Date());
        this.cesiumViewer.clock.startTime = start.clone();
        var stop = Cesium.JulianDate.addSeconds(start, 300000000, new Cesium.JulianDate());
        this.cesiumViewer.clock.stopTime = stop.clone();
        //this.cesiumViewer.entities.remove(this.entityFly);
        this.clearFly3DPaths();
    },
};
var modelEntity
$('#modelLLH').click(() => {
    var modelLat = $('#modelLat').val();
    var modelLon = $('#modelLon').val();
    var modelHeight = $('#modelHeight').val();
    console.log(modelLon, modelLat, modelHeight);
    modelEntity.position = Cesium.Cartesian3.fromDegrees(modelLon, modelLat, modelHeight)
})


const $minInput = $("#min-value");
const $maxInput = $("#max-value");
const $stepInput = $("#step-value");
const $setRangeButton = $("#set-range");
const $sliderScal = $('#slider-scal');
const $sliderValueDisplay = $("#scal-value");

// 设置滑动条的最小值和最大值
$setRangeButton.on("click", () => {
    const min = parseFloat($minInput.val());
    const max = parseFloat($maxInput.val());
    const step = parseFloat($stepInput.val());
    console.log(step);
    if (min >= max) {
        alert("最小值必须小于最大值！");
        return;
    }
    if (step <= 0) {
        alert("步长必须大于 0！");
        return;
    }
    $sliderScal.attr({
        min: min,
        max: max,
        step: step,
        value: min,
    });

    // 更新滑动条值显示
    $sliderValueDisplay.text($sliderScal.val());

});
$sliderScal.on('input', () => {
    let inputValue = $sliderScal.val();  // 获取 input 的值
    console.log(inputValue);
    console.log(modelEntity);
    $sliderValueDisplay.text(inputValue);
    modelEntity.model.maximumScale.setValue(inputValue)
    if (inputValue > 2) {
        modelEntity.model.scale.setValue(inputValue)
    }
})



// 获取滑块及其值显示的 DOM 元素
const $headingSlider = $("#heading-slider");
const $pitchSlider = $("#pitch-slider");
const $rollSlider = $("#roll-slider");

const $headingValue = $("#heading-value");
const $pitchValue = $("#pitch-value");
const $rollValue = $("#roll-value");

// 假设 Cesium 的模型实体已经存在

// 更新模型的 Orientation
function updateOrientation() {
    const heading = Cesium.Math.toRadians(parseFloat($headingSlider.val()));
    const pitch = Cesium.Math.toRadians(parseFloat($pitchSlider.val()));
    const roll = Cesium.Math.toRadians(parseFloat($rollSlider.val()));

    const position = modelEntity.position.getValue(Cesium.JulianDate.now());
    const hpr = new Cesium.HeadingPitchRoll(heading, pitch, roll);
    const orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);

    modelEntity.orientation = orientation;
}

// 绑定滑块变化事件
$headingSlider.on("input", () => {
    $headingValue.text($headingSlider.val());
    updateOrientation();
});

$pitchSlider.on("input", () => {
    $pitchValue.text($pitchSlider.val());
    updateOrientation();
});

$rollSlider.on("input", () => {
    $rollValue.text($rollSlider.val());
    updateOrientation();
});

$('#heading').blur(() => {
    console.log(modelEntity);

    let position = modelEntity.position.getValue(Cesium.JulianDate.now());
    let heading = Cesium.Math.toRadians($('#heading').val())
    let pitch = Cesium.Math.toRadians($('#pitch').val())
    let roll = Cesium.Math.toRadians($('#roll').val())
    var hpr = new Cesium.HeadingPitchRoll(heading, pitch, roll);
    let orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);
    modelEntity.orientation.setValue(orientation)
})
$('#pitch').blur(() => {
    let position = modelEntity.position.getValue(Cesium.JulianDate.now());
    let heading = Cesium.Math.toRadians($('#heading').val())
    let pitch = Cesium.Math.toRadians($('#pitch').val())
    let roll = Cesium.Math.toRadians($('#roll').val())
    var hpr = new Cesium.HeadingPitchRoll(heading, pitch, roll);
    console.log(hpr);
    let orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);
    modelEntity.orientation.setValue(orientation)
})
$('#roll').blur(() => {
    let position = modelEntity.position.getValue(Cesium.JulianDate.now());
    let heading = Cesium.Math.toRadians($('#heading').val())
    let pitch = Cesium.Math.toRadians($('#pitch').val())
    let roll = Cesium.Math.toRadians($('#roll').val())
    var hpr = new Cesium.HeadingPitchRoll(heading, pitch, roll);
    console.log(hpr);
    let orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);
    modelEntity.orientation.setValue(orientation)
})

/* 三维坐标显示函数  显示经纬度坐标*/
function show3DCoordinates() {
    //地图底部工具栏显示地图坐标信息
    console.log('显示经纬度')

    var coordinatesDiv = document.getElementById("map_coordinates");
    if (coordinatesDiv) {
        //展示  坐标显示框
        coordinatesDiv.style.display = "block";
    } else {
        coordinatesDiv = document.createElement("div");
        coordinatesDiv.id = "map_coordinates";
        coordinatesDiv.style.zIndex = "50";
        coordinatesDiv.style.bottom = "100px";
        coordinatesDiv.style.height = "29px";
        coordinatesDiv.style.position = "absolute";
        coordinatesDiv.style.overflow = "hidden";
        coordinatesDiv.style.textAlign = "center";
        coordinatesDiv.style.left = "10px";
        coordinatesDiv.style.lineHeight = "29px";
        coordinatesDiv.innerHTML = "<span id='cd_label' style='font-size:13px;text-align:center;font-family:微软雅黑;color:#edffff;'>暂无坐标信息</span>";
        $(".cesium-viewer").append(coordinatesDiv);
        var handler3D = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
        handler3D.setInputAction(function (movement) {
            var pick = new Cesium.Cartesian2(movement.endPosition.x, movement.endPosition.y);
            if (pick) {
                var cartesian = viewer.scene.globe.pick(viewer.camera.getPickRay(pick), viewer.scene);
                if (cartesian) {
                    //世界坐标转地理坐标（弧度）
                    var cartographic = viewer.scene.globe.ellipsoid.cartesianToCartographic(cartesian);
                    if (cartographic) {
                        //海拔
                        var height = viewer.scene.globe.getHeight(cartographic);
                        //视角海拔高度
                        var he = Math.sqrt(viewer.scene.camera.positionWC.x * viewer.scene.camera.positionWC.x + viewer.scene.camera.positionWC.y * viewer.scene.camera.positionWC.y + viewer.scene.camera.positionWC.z * viewer.scene.camera.positionWC.z);
                        var he2 = Math.sqrt(cartesian.x * cartesian.x + cartesian.y * cartesian.y + cartesian.z * cartesian.z);
                        //地理坐标（弧度）转经纬度坐标
                        var point = [cartographic.longitude / Math.PI * 180, cartographic.latitude / Math.PI * 180];
                        if (!height) {
                            height = 0;
                        }
                        if (!he) {
                            he = 0;
                        }
                        if (!he2) {
                            he2 = 0;
                        }
                        if (!point) {
                            point = [0, 0];
                        }
                        coordinatesDiv.innerHTML = "<span id='cd_label' style='font-size:13px;text-align:center;font-family:微软雅黑;color:#edffff;'>视角高度:" + (he - he2).toFixed(2) + "米&nbsp;&nbsp;&nbsp;&nbsp;海拔高度:" + height.toFixed(2) + "米&nbsp;&nbsp;&nbsp;&nbsp;经度：" + point[0].toFixed(6) + "&nbsp;&nbsp;纬度：" + point[1].toFixed(6) + "</span>";
                    }
                }
            }
        }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

        handler3D.setInputAction(function () {
            handler3D.destroy();
            coordinatesDiv.remove();
        }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);//销毁事件处理器和底部显示框
    }
}

/*三维坐标显示函数  显示高斯坐标*///放在earthOpera.js中了，不在这改
function showGaosiCoordinates() {
    //地图底部工具栏显示地图坐标信息（常驻）
    console.log('显示高斯坐标');
    var elementbottom = document.createElement("div1");
    $(".cesium-viewer").append(elementbottom);
    elementbottom.style.width = "100%";
    elementbottom.style.height = "30px";
    elementbottom.style.background = "rgba(0,0,0,0)";
    elementbottom.style.position = "absolute";
    elementbottom.style.bottom = "0px";
    elementbottom.style.cursor = "default";

    var coordinatesDiv = document.getElementById("map_coordinates1");
    if (coordinatesDiv) {
        //展示  坐标显示框
        coordinatesDiv.style.display = "block";
    } else {
        coordinatesDiv = document.createElement("div1");
        coordinatesDiv.id = "map_coordinates1";
        coordinatesDiv.style.zIndex = "50";
        coordinatesDiv.style.bottom = "1px";
        coordinatesDiv.style.height = "29px";
        coordinatesDiv.style.left = "0px";
        coordinatesDiv.style.position = "absolute";
        coordinatesDiv.style.overflow = "hidden";
        coordinatesDiv.style.textAlign = "center";        
        coordinatesDiv.style.lineHeight = "29px";
        coordinatesDiv.innerHTML = "<span id='cd_label' style='font-size:13px;text-align:center;font-family:微软雅黑;color:#edffff;'>暂无坐标信息</span>";
        $(".cesium-viewer").append(coordinatesDiv);
        var handler3D = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
        handler3D.setInputAction(function (movement) {
            var pick = new Cesium.Cartesian2(movement.endPosition.x, movement.endPosition.y);
            if (pick) {
                var cartesian = viewer.scene.globe.pick(viewer.camera.getPickRay(pick), viewer.scene);
                if (cartesian) {
                    //世界坐标转地理坐标（弧度）
                    var cartographic = viewer.scene.globe.ellipsoid.cartesianToCartographic(cartesian);
                    if (cartographic) {
                        //海拔
                        var height = viewer.scene.globe.getHeight(cartographic);
                        //视角海拔高度
                        var he = Math.sqrt(viewer.scene.camera.positionWC.x * viewer.scene.camera.positionWC.x + viewer.scene.camera.positionWC.y * viewer.scene.camera.positionWC.y + viewer.scene.camera.positionWC.z * viewer.scene.camera.positionWC.z);
                        var he2 = Math.sqrt(cartesian.x * cartesian.x + cartesian.y * cartesian.y + cartesian.z * cartesian.z);
                        //地理坐标（弧度）转经纬度坐标
                        var point = [cartographic.longitude / Math.PI * 180, cartographic.latitude / Math.PI * 180];
                        if (!height) {
                            height = 0;
                        }
                        if (!he) {
                            he = 0;
                        }
                        if (!he2) {
                            he2 = 0;
                        }
                        if (!point) {
                            point = [0, 0];
                        }
                        //point[0]：经度     point[1]：纬度
                        //var [Gaosi_latitude, Gaosi_longitude] = DadiPoint2ProjectPoint(point[1], point[0]);
                        coordinatesDiv.innerHTML = "<span id='cd_label' style='font-size:13px;text-align:center;font-family:微软雅黑;color:#edffff;'>" + 0 + "&nbsp;&nbsp;&nbsp;&nbsp;海拔:" + height.toFixed(2) + "米&nbsp;&nbsp;&nbsp;&nbsp;纬度：" + point[1].toFixed(6) + "&nbsp;&nbsp;经度：" + point[0].toFixed(6) + "</span>";
                    }
                }
            }
        }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    }

}

/*经纬度转高斯坐标   转换函数    参数：纬度 精度*/

//经纬度转高斯投影  输入经纬度
function DadiPoint2ProjectPoint(B, L) {
    //B纬度  L精度
    //定义常数
    const PI = Math.PI
    const p0 = 206264.8062470963551564
    //wgs84参考椭球
    const e = 0.00669438002290;
    const e1 = 0.00673949677548;
    const b = 6356752.3141
    const a = 6378137.0;
    //度转化为弧度
    B = B * Math.PI / 180;
    L = L * Math.PI / 180;

    let N, t, n, c, V, Xz, m1, m2, m3, m4, m5, m6, a0, a2, a4, a6, a8, M0, M2, M4, M6, M8, x0, y0, l;
    let i, L_num, L_center;

    //中央子午线精度，6°带
    L_num = parseInt(L * 180 / PI / 6.0) + 1;
    L_center = 6 * L_num - 3;

    /*//中央子午线精度，3°带
    L_num=L*180/PI/3.0+0.5;
    L_center=3*L_num;*/

    l = (L / PI * 180 - L_center) * 3600; //求带号、中央经线、经差
    M0 = a * (1 - e);
    M2 = 3.0 / 2.0 * e * M0;
    M4 = 5.0 / 4.0 * e * M2;
    M6 = 7.0 / 6.0 * e * M4;
    M8 = 9.0 / 8.0 * e * M6;

    a0 = M0 + M2 / 2.0 + 3.0 / 8.0 * M4 + 5.0 / 16.0 * M6 + 35.0 / 128.0 * M8;
    a2 = M2 / 2.0 + M4 / 2 + 15.0 / 32.0 * M6 + 7.0 / 16.0 * M8;
    a4 = M4 / 8.0 + 3.0 / 16.0 * M6 + 7.0 / 32.0 * M8;
    a6 = M6 / 32.0 + M8 / 16.0;
    a8 = M8 / 128.0;

    Xz = a0 * B - a2 / 2.0 * Math.sin(2 * B) + a4 / 4.0 * Math.sin(4 * B) - a6 / 6.0 * Math.sin(6 * B) + a8 / 8.0 * Math.sin(8 * B);  //计算子午线弧长
    c = a * a / b;
    V = Math.sqrt(1 + e1 * Math.cos(B) * Math.cos(B));
    N = c / V;
    t = Math.tan(B);
    n = e1 * Math.cos(B) * Math.cos(B);
    m1 = N * Math.cos(B);
    m2 = N / 2.0 * Math.sin(B) * Math.cos(B);
    m3 = N / 6.0 * Math.pow(Math.cos(B), 3) * (1 - t * t + n);
    m4 = N / 24.0 * Math.sin(B) * Math.pow(Math.cos(B), 3) * (5 - t * t + 9 * n);
    m5 = N / 120.0 * Math.pow(Math.cos(B), 5) * (5 - 18 * t * t + Math.pow(t, 4) + 14 * n - 58 * n * t * t);
    m6 = N / 720.0 * Math.sin(B) * Math.pow(Math.cos(B), 5) * (61 - 58 * t * t + Math.pow(t, 4));
    x0 = Xz + m2 * l * l / Math.pow(p0, 2) + m4 * Math.pow(l, 4) / Math.pow(p0, 4) + m6 * Math.pow(l, 6) / Math.pow(p0, 6);
    y0 = m1 * l / p0 + m3 * Math.pow(l, 3) / Math.pow(p0, 3) + m5 * Math.pow(l, 5) / Math.pow(p0, 5);   //计算x y坐标
    x = x0;
    y = y0 + 500000 + 1000000 * L_num;    //化为国家统一坐标
    return [x, y]
}

/*关闭坐标显示界面*/
function removeShowCoordinates() {
    if (document.getElementById("map_coordinates") && document.getElementById("map-elementary")) {
        let parentMapCoordinates = document.getElementById("map_coordinates").parentNode;
        console.log(parentMapCoordinates);
        parentMapCoordinates.removeChild(document.getElementById("map_coordinates"));
        let parentMapElementary = document.getElementById("map-elementary").parentNode;
        console.log(parentMapElementary);
        parentMapElementary.removeChild(document.getElementById("map-elementary"));
    }

}

/*
展示和编辑图形
若要移动到另一个文件，需要同时改变开头的全局变量
可以后续优化
* */
function showPolygon(objId, positions) {
    var material = Cesium.Color.fromCssColorString('#ff0').withAlpha(0.5);
    var outlineMaterial = new Cesium.PolylineDashMaterialProperty({
        dashLength: 16,
        color: Cesium.Color.fromCssColorString('#00f').withAlpha(0.7)
    });
    var outlinePositions = [].concat(positions);
    outlinePositions.push(positions[0]);
    var bData = {
        layerId: layerId,
        objId: objId,
        shapeType: "Polygon",
        polyline: {
            positions: outlinePositions,
            clampToGround: true,
            width: 2,
            material: outlineMaterial
        },
        polygon: new Cesium.PolygonGraphics({
            hierarchy: positions,
            asynchronous: false,
            material: material
        })
    };
    var entity = viewer.entities.add(bData);
}

function showPolyline(objId, positions) {
    var material = new Cesium.PolylineGlowMaterialProperty({
        glowPower: 0.25,
        color: Cesium.Color.fromCssColorString('#00f').withAlpha(0.9)
    });
    var bData = {
        layerId: layerId,
        objId: objId,
        shapeType: "Polyline",
        polyline: {
            positions: positions,
            clampToGround: true,
            width: 8,
            material: material
        }
    };
    var entity = viewer.entities.add(bData);
}

function showRectangle(objId, positions) {
    var material = Cesium.Color.fromCssColorString('#ff0').withAlpha(0.5);
    var outlineMaterial = new Cesium.PolylineDashMaterialProperty({
        dashLength: 16,
        color: Cesium.Color.fromCssColorString('#00f').withAlpha(0.7)
    });
    var rect = Cesium.Rectangle.fromCartesianArray(positions);
    var arr = [rect.west, rect.north, rect.east, rect.north, rect.east, rect.south, rect.west, rect.south, rect.west, rect.north];
    var outlinePositions = Cesium.Cartesian3.fromRadiansArray(arr);
    var bData = {
        layerId: layerId,
        objId: objId,
        shapeType: "Rectangle",
        polyline: {
            positions: outlinePositions,
            clampToGround: true,
            width: 2,
            material: outlineMaterial
        },
        rectangle: {
            coordinates: rect,
            material: material
        }
    };
    var entity = viewer.entities.add(bData);
}

function showCircle(objId, positions) {
    var material = Cesium.Color.fromCssColorString('#ff0').withAlpha(0.5);
    var outlineMaterial = new Cesium.PolylineDashMaterialProperty({
        dashLength: 16,
        color: Cesium.Color.fromCssColorString('#f00').withAlpha(0.7)
    });
    var radiusMaterial = new Cesium.PolylineDashMaterialProperty({
        dashLength: 16,
        color: Cesium.Color.fromCssColorString('#00f').withAlpha(0.7)
    });
    var pnts = tracker.circleDrawer._computeCirclePolygon(positions);
    var dis = tracker.circleDrawer._computeCircleRadius3D(positions);
    dis = (dis / 1000).toFixed(3);
    var text = dis + "km";
    var bData = {
        layerId: layerId,
        objId: objId,
        shapeType: "Circle",
        position: positions[0],
        label: {
            text: text,
            font: '16px Helvetica',
            fillColor: Cesium.Color.SKYBLUE,
            outlineColor: Cesium.Color.BLACK,
            outlineWidth: 1,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            eyeOffset: new Cesium.ConstantProperty(new Cesium.Cartesian3(0, 0, -9000)),
            pixelOffset: new Cesium.Cartesian2(16, 16)
        },
        billboard: {
            image: "img/circle_center.png",
            eyeOffset: new Cesium.ConstantProperty(new Cesium.Cartesian3(0, 0, -500)),
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
        },
        polyline: {
            positions: positions,
            clampToGround: true,
            width: 2,
            material: radiusMaterial
        },
        polygon: new Cesium.PolygonGraphics({
            hierarchy: pnts,
            asynchronous: false,
            material: material
        })
    };
    var entity = viewer.entities.add(bData);

    var outlineBdata = {
        layerId: layerId,
        objId: objId,
        shapeType: "Circle",
        polyline: {
            positions: pnts,
            clampToGround: true,
            width: 2,
            material: outlineMaterial
        }
    };
    var outlineEntity = viewer.entities.add(outlineBdata);
}

function showPoint(objId, position) {
    var entity = viewer.entities.add({
        layerId: layerId,
        objId: objId,
        shapeType: "Point",
        position: position,
        billboard: {
            image: "img/circle_red.png",
            eyeOffset: new Cesium.ConstantProperty(new Cesium.Cartesian3(0, 0, -500)),
            heightReference: Cesium.HeightReference.CLAMP_TO_GROUND
        }
    });
}

function showBufferLine(objId, positions, radius) {
    var buffer = tracker.bufferLineDrawer.computeBufferLine(positions, radius);
    var material = Cesium.Color.fromCssColorString('#ff0').withAlpha(0.5);
    var lineMaterial = new Cesium.PolylineDashMaterialProperty({
        dashLength: 16,
        color: Cesium.Color.fromCssColorString('#00f').withAlpha(0.7)
    });
    var bData = {
        layerId: layerId,
        objId: objId,
        shapeType: "BufferLine",
        polygon: new Cesium.PolygonGraphics({
            hierarchy: buffer,
            asynchronous: false,
            material: material
        }),
        polyline: {
            positions: positions,
            clampToGround: true,
            width: 2,
            material: lineMaterial
        }
    };
    var entity = viewer.entities.add(bData);
}

function showStraightArrow(objId, positions) {
    var material = Cesium.Color.fromCssColorString('#ff0').withAlpha(0.5);
    const outlineMaterial = new Cesium.PolylineDashMaterialProperty({
        dashLength: 16,
        color: Cesium.Color.fromCssColorString('#f00').withAlpha(0.7)
    });
    var outlinePositions = [].concat(positions);
    outlinePositions.push(positions[0]);
    var bData = {
        layerId: layerId,
        objId: objId,
        shapeType: "StraightArrow",
        polyline: {
            positions: outlinePositions,
            clampToGround: true,
            width: 2,
            material: outlineMaterial
        },
        polygon: new Cesium.PolygonGraphics({
            hierarchy: positions,
            asynchronous: false,
            material: material
        })
    };
    var entity = viewer.entities.add(bData);
}

function showAttackArrow(objId, positions) {
    var material = Cesium.Color.fromCssColorString('#ff0').withAlpha(0.5);
    var outlineMaterial = new Cesium.PolylineDashMaterialProperty({
        dashLength: 16,
        color: Cesium.Color.fromCssColorString('#f00').withAlpha(0.7)
    });
    var outlinePositions = [].concat(positions);
    outlinePositions.push(positions[0]);
    var bData = {
        layerId: layerId,
        objId: objId,
        shapeType: "AttackArrow",
        polyline: {
            positions: outlinePositions,
            clampToGround: true,
            width: 2,
            material: outlineMaterial
        },
        polygon: new Cesium.PolygonGraphics({
            hierarchy: positions,
            asynchronous: false,
            material: material
        })
    };
    var entity = viewer.entities.add(bData);
}

function showPincerArrow(objId, positions) {
    var material = Cesium.Color.fromCssColorString('#ff0').withAlpha(0.5);
    var outlineMaterial = new Cesium.PolylineDashMaterialProperty({
        dashLength: 16,
        color: Cesium.Color.fromCssColorString('#f00').withAlpha(0.7)
    });
    var outlinePositions = [].concat(positions);
    outlinePositions.push(positions[0]);
    var bData = {
        layerId: layerId,
        objId: objId,
        shapeType: "PincerArrow",
        polyline: {
            positions: outlinePositions,
            clampToGround: true,
            width: 2,
            material: outlineMaterial
        },
        polygon: new Cesium.PolygonGraphics({
            hierarchy: positions,
            asynchronous: false,
            material: material
        })
    };
    var entity = viewer.entities.add(bData);
}

function editPolygon(objId) {
    var oldPositions = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    //进入编辑状态
    tracker.polygonDrawer.showModifyPolygon(oldPositions, function (positions) {
        shapeDic[objId] = positions;
        showPolygon(objId, positions);
    }, function () {
        showPolygon(objId, oldPositions);
    });
}

function editPolyline(objId) {
    var oldPositions = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    //进入编辑状态
    tracker.polylineDrawer.showModifyPolyline(oldPositions, function (positions) {
        shapeDic[objId] = positions;
        showPolyline(objId, positions);
    }, function () {
        showPolyline(objId, oldPositions);
    });
}

function editRectangle(objId) {
    var oldPositions = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    //进入编辑状态
    tracker.rectDrawer.showModifyRectangle(oldPositions, function (positions) {
        shapeDic[objId] = positions;
        showRectangle(objId, positions);
    }, function () {
        showRectangle(objId, oldPositions);
    });
}

function editCircle(objId) {
    var oldPositions = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    //进入编辑状态
    tracker.circleDrawer.showModifyCircle(oldPositions, function (positions) {
        shapeDic[objId] = positions;
        showCircle(objId, positions);
    }, function () {
        showCircle(objId, oldPositions);
    });
}

function editPoint(objId) {
    var oldPosition = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    //进入编辑状态
    tracker.pointDrawer.showModifyPoint(oldPosition, function (position) {
        shapeDic[objId] = position;
        showPoint(objId, position);
    }, function () {
        showPoint(objId, oldPosition);
    });
}

function editBufferLine(objId) {
    var old = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    //进入编辑状态
    tracker.bufferLineDrawer.showModifyBufferLine(old.positions, old.radius, function (positions, radius) {
        shapeDic[objId] = {
            positions: positions,
            radius: radius
        };
        showBufferLine(objId, positions, radius);
    }, function () {
        showBufferLine(old.positions, old.radius, oldPositions);
    });
}

function editStraightArrow(objId) {
    var oldPositions = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    //进入编辑状态
    tracker.straightArrowDrawer.showModifyStraightArrow(oldPositions, function (positions) {
        shapeDic[objId] = positions;
        showStraightArrow(objId, positions);
    }, function () {
        showStraightArrow(objId, oldPositions);
    });
}

function editAttackArrow(objId) {
    var old = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    tracker.attackArrowDrawer.showModifyAttackArrow(old.custom, function (positions, custom) {
        //保存编辑结果
        shapeDic[objId] = {
            custom: custom,
            positions: positions
        };
        showAttackArrow(objId, positions);
    }, function () {
        showAttackArrow(objId, old.positions);
    });
}

function editPincerArrow(objId) {
    var old = shapeDic[objId];

    //先移除entity
    clearEntityById(objId);

    tracker.pincerArrowDrawer.showModifyPincerArrow(old.custom, function (positions, custom) {
        //保存编辑结果
        shapeDic[objId] = {
            custom: custom,
            positions: positions
        };
        showPincerArrow(objId, positions);
    }, function () {
        showPincerArrow(objId, old.positions);
    });
}

function clearEntityById(objId) {
    var entityList = viewer.entities.values;
    if (entityList == null || entityList.length < 1) {
        return;
    }
    for (var i = 0; i < entityList.length; i++) {
        var entity = entityList[i];
        if (entity.layerId == layerId && entity.objId == objId) {
            viewer.entities.remove(entity);
            i--;
        }
    }
}
/*AAA坡度分析部分注释掉的内容*//*
        绘制一片区域
        $('#slope_polygon').click(function (){
            viewer.cesiumWidget.screenSpaceEventHandler.removeInputAction(
                Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK
              );
              function createPoint(worldPosition) {
                const point = viewer.entities.add({
                  position: worldPosition,
                  point: {
                    color: Cesium.Color.WHITE,
                    pixelSize: 5,
                    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
                  },
                });
                return point;
              }

            let drawingMode = "polygon";
            function drawShape(positionData) {
                let shape;

                shape = viewer.entities.add({
                polygon: {
                    hierarchy: positionData,
                    material: new Cesium.ColorMaterialProperty(
                    Cesium.Color.WHITE.withAlpha(0.2)
                    ),
                },
                });
                return shape;
                }  

            let activeShapePoints = [];
            let activeShape;
            let floatingPoint;
            const handler = new Cesium.ScreenSpaceEventHandler(viewer.canvas);
            handler.setInputAction(function (event) {
                const ray = viewer.camera.getPickRay(event.position);
                const earthPosition = viewer.scene.globe.pick(ray, viewer.scene);
                if (Cesium.defined(earthPosition)) {
                    if (activeShapePoints.length === 0) {
                      floatingPoint = createPoint(earthPosition);
                      activeShapePoints.push(earthPosition);
                      const dynamicPositions = new Cesium.CallbackProperty(function () {
                        if (drawingMode === "polygon") {
                          return new Cesium.PolygonHierarchy(activeShapePoints);
                        }

                        return activeShapePoints;
                      }, false);
                      activeShape = drawShape(dynamicPositions);
                      console.log(dynamicPositions);

                    }
                    activeShapePoints.push(earthPosition);
                    createPoint(earthPosition);
                  }           
            }, Cesium.ScreenSpaceEventType.LEFT_CLICK)
            handler.setInputAction(function (event) {
                if (Cesium.defined(floatingPoint)) {
                  const ray = viewer.camera.getPickRay(event.endPosition);
                  const newPosition = viewer.scene.globe.pick(ray, viewer.scene);
                  if (Cesium.defined(newPosition)) {
                    floatingPoint.position.setValue(newPosition);
                    activeShapePoints.pop();
                    activeShapePoints.push(newPosition);
                  }
                }
              }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
            function terminateShape() {
                activeShapePoints.pop();
                let shape1 = drawShape(activeShapePoints);
                console.log(shape1.id);
                function getInnerCoordinates(positions) {
                    const innerCoordinates = [];
                    // 通过Ray casting算法检查点是否在多边形内部
                    const polygon = new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(positions));
                    const boundingRectangle = Cesium.Rectangle.fromCartesianArray(positions);
                    for (let lon = Cesium.Math.toDegrees(boundingRectangle.west); lon < Cesium.Math.toDegrees(boundingRectangle.east); lon += 0.1) {
                      for (let lat = Cesium.Math.toDegrees(boundingRectangle.south); lat < Cesium.Math.toDegrees(boundingRectangle.north); lat += 0.1) {
                        const point = Cesium.Cartesian3.fromDegrees(lon, lat);
                        if (Cesium.Cartesian3.angleBetween(point, Cesium.Cartesian3.UNIT_Z) !== 0 && Cesium.Cartesian3.angleBetween(point, Cesium.Cartesian3.UNIT_Z) !== Math.PI) {
                          if (Cesium.PolygonPipeline.classifyPointAgainstPolygon(point, polygon.positions) === Cesium.Intersect.INSIDE) {
                            innerCoordinates.push([lon, lat]);
                          }
                        }
                      }
                    }
                    return innerCoordinates;
                  }
                viewer.entities.remove(floatingPoint);
                viewer.entities.remove(activeShape);
                floatingPoint = undefined;
                activeShape = undefined;
                activeShapePoints = [];

            }
            handler.setInputAction(function (event) {
            terminateShape();
            // console.log(viewer.entities);
            }, Cesium.ScreenSpaceEventType.RIGHT_CLICK);
            }
        )
 */
        
/*BBB GLTF模型加载部分被注释掉的内容*/
// viewer.camera.moveUp(3000);
                    // viewer.trackedEntity = Gltif.modelEntity;
                    // viewer.trackedEntity = null;
                    // Gltif.readyPromise.then(function (model) {
                    //     var boundingSphere = model.boundingSphere;
                    //     console.log(boundingSphere.radius); 
                    // });
                    // console.log(Gltif);

                    /* var height = -30;　　//根据地形设置调整高度
                     palaceTileset.readyPromise.then(function(argument) {
                         //贴地显示
                         var cartographic = Cesium.Cartographic.fromCartesian(dayantaTileset.boundingSphere.center);
                         var surface = Cesium.Cartesian3.fromRadians(cartographic.longitude, cartographic.latitude, cartographic.height);
                         var offset = Cesium.Cartesian3.fromRadians(cartographic.longitude, cartographic.latitude, cartographic.height + height);
                         var translation = Cesium.Cartesian3.subtract(offset, surface, new Cesium.Cartesian3());
                         palaceTileset.modelMatrix = Cesium.Matrix4.fromTranslation(translation);
                     })
                     /!*var gltf = new Gltf(dataUrl);*!/
                     break;*/
