//用于构建应用程序的基础小部件
var viewer;

function earthInit() {
	//	viewer设置
	var options = {
		// terrainProvider: Cesium.createWorldTerrain({
        //     requestWaterMask: true,
        //     requestVertexNormals: true
        //   }),
		mapMode2D: Cesium.MapMode2D.INFINITE_SCROLL, //2D地图可以在水平方向无限滚动
		vrButton: false, //VR
		terrainExaggeration: 1, //地形高程比例
		shadows: false, //确定阴影是否由太阳投下
		terrainShadows: Cesium.ShadowMode.DISABLED, //确定地形是否投射或接收来自太阳的阴影
		timeline: false, //时间线
		navigationHelpButton: false, //使用帮助
		geocoder: true, //地理编码
		homeButton: false, //主页按键
		sceneModePicker: true,
		infoBox: true,
		baseLayerPicker: true,
		fullscreenButton: true,
		selectionIndicator: false,
		animation: false,
		shouldAnimate: false,
		navigationInstructionsInitiallyVisible: false,
		//requestRenderMode: true,
		contextOptions: {
			webgl: {
				alpha: true,
				depth: true,
				stencil: true,
				antialias: true,
				premultipliedAlpha: true,
				preserveDrawingBuffer: true,
				failIfMajorPerformanceCaveat: true
			}
		},
		// performanceDisplay: false,
		// shouldAnimate: false,
		//开启调试信息显示
		// showDebuggerPanel: false,
	}
	Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJkZTlkNjBmMi05NjdjLTQwMTgtOTBiOC04NDU1NWJjYmFkZWEiLCJpZCI6MzA2MzMzLCJpYXQiOjE3NDgyNDg4MTl9.r7m_tXkLjZOAcHKP_oI0BuCvE6xuaujzU3CL7f4TG9A';//使用cesium ion服务，需要在官网注册获取token

	//加载离线地图
	this.viewer = new Cesium.Viewer('cesiumContainer', options);
	this.viewer.scene.debugShowFramesPerSecond = true;console.log(999);
	// 加载地形  加载初始地图
	// var globalMap=new Cesium.WebMapServiceImageryProvider({
	// 	url:'http://localhost:8082/geoserver/GlobalMap/wms?service=WMS',
	// 	layers:'GlobalMap:NE1_HR_LC_SR_W_DR',
	// 	parameters:{
	// 		service: 'WMS',
	// 		format: 'image/png',
	// 		transparent:true,
	// 	}
	// })
	//叫项目的时候离线地图
	Cesium.Camera.DEFAULT_VIEW_RECTANGLE = Cesium.Rectangle.fromDegrees(95.0, -20.0, 120.0, 90.0);//设置初始视角为中国
	//初始化扩展插件
	viewer.extend(Cesium.viewerCesiumNavigationMixin,{				
                enableCompass:true,
				//罗盘组件true启用，false禁用，默认值为true。
				enableZoomControls:true,
				//缩放组件true启用，false禁用，默认值为true。
				enableDistanceLegend:true,
				//比例尺组件true启用，false禁用，默认值为true。
				enableCompassOuterRing:true,
				//指南针外环组件true启用，false禁用，默认值为true。
    });console.log(6);

/*三维坐标显示函数  显示高斯坐标*/
function showGaosiCoordinates() {
    console.log('显示高斯坐标');

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
        coordinatesDiv.style.position = "absolute";
        coordinatesDiv.style.overflow = "hidden";
        coordinatesDiv.style.textAlign = "center";
        coordinatesDiv.style.left = "5px";
        coordinatesDiv.style.lineHeight = "29px";
		coordinatesDiv.style.backgroundColor = "#303336";
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
                        var [Gaosi_latitude, Gaosi_longitude] = DadiPoint2ProjectPoint(point[1], point[0]);
                        coordinatesDiv.innerHTML = "<span id='cd_label' style='font-size:13px;text-align:center;font-family:微软雅黑;color:#edffff;'>" + "&nbsp" + " &nbsp;&nbsp;海拔:" + height.toFixed(2) + "米&nbsp;&nbsp;&nbsp;&nbsp;纬度：" + point[1].toFixed(6) + "&nbsp;&nbsp;经度：" + point[0].toFixed(6) + "&nbsp;&nbsp;</span>";
                    }
                }
            }
        }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
    }

}
	showGaosiCoordinates();

	viewer.camera.setView({
		destination: Cesium.Cartesian3.fromDegrees(119.196653, 26.031937, 27000000)
	});
	this.viewer.HomeButton.viewModel.command.beforeExecute.addEventListener((e) => {
		e.cancel = true;
		//你要飞的位置
		this.viewer.camera.flyTo({
			destination: Cesium.Cartesian3.fromDegrees(119.196653, 26.031937, 27000000),
		});console.log(66666);
	});
	
	var imageryProviderViewModels = viewer.baseLayerPicker.viewModel.imageryProviderViewModels;
	var terrainProviderViewModels = viewer.baseLayerPicker.viewModel.terrainProviderViewModels;
	viewer.baseLayerPicker.viewModel.selectedImagery = imageryProviderViewModels[imageryProviderViewModels.length - 1];
	viewer.baseLayerPicker.viewModel.selectedTerrain = terrainProviderViewModels[0];




	//加载离线地形
	/*var terrainProvider = new Cesium.CesiumTerrainProvider({
		url : 'data/terrain/ludingqiepian/'
	});
	viewer.terrainProvider=terrainProvider;
	viewer.camera.flyTo({
		destination:Cesium.Cartesian3.fromDegrees(102.231570, 29.911947, 30000)
		}
	)*/
	/*viewer.imageryLayers.addImageryProvider(globalMap);*/

	//	加载离线地球
	// viewer = new Cesium.Viewer('cesiumContainer', {
	// imageryProvider : Cesium.createTileMapServiceImageryProvider({
	//    url : Cesium.buildModuleUrl('Assets/Textures/NaturalEarthII')
	// }),
	// baseLayerPicker : false,
	// geocoder : false
	// });
	//初始化 CesiumToolbar
	CesiumToolbar.init();

	/*var homeview=window.setTimeout(function(){
		 MapStatic.flyTo({lon:113.544,lat:34.832,height:3000});
		 clearTimeout(homeview);
	},3000);*/
	$('.loadingIndicator').css('display', 'none');

	if (Login.IsLogin()) {
		return;
	} else {
		showMessageInfo('部分功能需要登陆后使用，请及时登录！！', 'danger');
	}
}

//中心位置经纬度显示
    //   function updatePosition() {
		// let center = viewer.camera.pickEllipsoid(
		// 	new Cesium.Cartesian2(
		// 		viewer.canvas.clientWidth / 2,
		// 		viewer.canvas.clientHeight / 2,
		// 	),
		// )     
	//   let position = Cesium.Ellipsoid.WGS84.cartesianToCartographic(center);
    //   document.getElementById("longitude1").innerText = ((position.longitude * 180) / Math.PI).toFixed(5);
    //   document.getElementById("latitude1").innerText = ((position.latitude * 180) / Math.PI).toFixed(5);
	//   const pos = Cesium.Cartographic.fromCartesian(this.viewer.camera.position);
    //   document.getElementById("longitude").innerText = Cesium.Math.toDegrees(pos.longitude).toFixed(5);
    //   document.getElementById("latitude").innerText = Cesium.Math.toDegrees(pos.latitude).toFixed(5);
    //   document.getElementById("height").innerText = Math.round(pos.height);
	//   }
	  
	//   function updateViewSize() {
	// 	const frustum = this.viewer.camera.frustum;
    //   if (frustum instanceof Cesium.PerspectiveFrustum) {
    //     const tanPhi = Math.tan(frustum.fovy / 2);
    //     const tanTheta = frustum.aspectRatio * tanPhi;
    //     const dist = Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(viewer.camera.position).height);

    //     // document.getElementById("viewWidth").innerText = Math.round(2 * dist * tanTheta / 1000);
    //     // document.getElementById("viewHeight").innerText = Math.round(2 * dist * tanPhi / 1000);
     
    // 	}
	//   }

	// viewer.camera.changed.addEventListener(updatePosition);
    // viewer.scene.postRender.addEventListener(updateViewSize);