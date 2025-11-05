    let contourMaterial = null;    
    
    class ContourMaterial {
    constructor(viewer) {
        if (!viewer) throw new Error("no viewer object!");
        this.viewer = viewer;
        this.contourMaterial = null;
        // this.spacing = 200;
        // this.lineWidth = 2;
        // this.minHeight = 800;
        // this.maxHeight = 4000;
        // this.lowColor = Cesium.Color.fromCssColorString("#2e8b57");
        // this.midColor = Cesium.Color.fromCssColorString("#ffa500");
        // this.highColor = Cesium.Color.fromCssColorString("#dc143c");
        // this.gradientIntensity = 70;
        // this.useSmoothGradient = true;
        // this.showLabels = false;
        // this.enableContour = true;
        //this.onload = init;
        //this.create();
    }

    createContourMaterial() {
      let viewer = this.viewer;
        const contourShader = `
            uniform float spacing;
            uniform float width;
            uniform vec4 lowColor;
            uniform vec4 midColor;
            uniform vec4 highColor;
            uniform float minHeight;
            uniform float maxHeight;
            uniform float gradientIntensity;
            uniform bool useSmoothGradient;
            uniform bool showLabels;
            uniform bool enableContour;

            czm_material czm_getMaterial(czm_materialInput materialInput)
            {
                czm_material material = czm_getDefaultMaterial(materialInput);

                float height = materialInput.height;
                float t = clamp((height - minHeight) / (maxHeight - minHeight), 0.0, 1.0);

                float modulo = mod(height, spacing);
                float halfWidth = width * 0.5;
                float contour = smoothstep(spacing - halfWidth, spacing, modulo);

                vec4 color;
                if (t < 0.5) {
                    color = mix(lowColor, midColor, t * 2.0);
                } else {
                    color = mix(midColor, highColor, (t - 0.5) * 2.0);
                }

                if (useSmoothGradient) {
                    float gradient = pow(1.0 - abs(t - 0.5) * 2.0, gradientIntensity / 10.0);
                    color = mix(color, vec4(1.0), gradient * 0.3);
                }

                material.diffuse = color.rgb;
                material.alpha = enableContour ? color.a * contour : 0.0;

                if (showLabels && contour < 0.1) {
                    material.diffuse = mix(vec3(1.0), color.rgb, 0.3);
                }

                return material;
            }
        `;

      contourMaterial = new Cesium.Material({
        fabric: {
          type: 'ElevationContour',
          uniforms: {
            spacing: 200,
            width: 2,
            lowColor: new Cesium.Color(0.18, 0.545, 0.34, 1),
            midColor: new Cesium.Color(1, 0.647, 0, 1),
            highColor: new Cesium.Color(0.86, 0.08, 0.21, 1),
            minHeight: 800,
            maxHeight: 4000,
            gradientIntensity: 70,
            useSmoothGradient: true,
            showLabels: false,
            enableContour: true
          },
          source: contourShader
        }
      });

      // 应用到 globe 上
      viewer.scene.globe.material = contourMaterial;console.log(viewer.scene);  

      
      
      return contourMaterial;
    }

    // 更新材质参数
    updateContours() {
      let viewer = this.viewer;
      console.log(viewer);
      contourMaterial.uniforms.spacing = parseInt(document.getElementById("contourInterval").value);
      contourMaterial.uniforms.width = parseFloat(document.getElementById("lineWidth").value);
      contourMaterial.uniforms.lowColor = Cesium.Color.fromCssColorString(document.getElementById("lowColor").value);
      contourMaterial.uniforms.midColor = Cesium.Color.fromCssColorString(document.getElementById("midColor").value);
      contourMaterial.uniforms.highColor = Cesium.Color.fromCssColorString(document.getElementById("highColor").value);
      contourMaterial.uniforms.minHeight = parseInt(document.getElementById("visibleRangeMin").value);
      contourMaterial.uniforms.maxHeight = parseInt(document.getElementById("visibleRangeMax").value);
      contourMaterial.uniforms.gradientIntensity = parseInt(document.getElementById("gradientIntensity").value);
      contourMaterial.uniforms.useSmoothGradient = document.getElementById("useSmoothGradient").checked;
      contourMaterial.uniforms.showLabels = document.getElementById("showLabels").checked;
      contourMaterial.uniforms.enableContour = document.getElementById("showContour").checked;

      viewer.scene.requestRender();

      if(contourMaterial.uniforms.maxHeight <= contourMaterial.uniforms.minHeight){
              contourMaterial.uniforms.maxHeight = contourMaterial.uniforms.minHeight + 100;
              document.getElementById('visibleRangeMax').value = contourMaterial.uniforms.minHeight + 100;  
            }
            
      // 更新UI显示
      document.getElementById("contourIntervalLabel").innerText = contourMaterial.uniforms.spacing;
      document.getElementById("minHeight").innerText = contourMaterial.uniforms.minHeight;
      document.getElementById("maxHeight").innerText = contourMaterial.uniforms.maxHeight;

      
 
    }


    // 绑定事件监听器
    bindEvents() {
      const inputs = [
        "contourInterval", "lineWidth",
        "visibleRangeMin", "visibleRangeMax",
        "gradientIntensity", "useSmoothGradient", "showLabels", "showContour",
        "lowColor", "midColor", "highColor"
      ];

      inputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
          el.addEventListener("input", this.createContourMaterial());
          el.addEventListener("change", this.updateContours);
        }
      });

    }

    // 初始化
    init() {
      this.bindEvents();
      this.createContourMaterial();
    }

   
} 

        // this.material = new Cesium.Material({
        //     fabric: {
        //         type: 'ElevationContour',
        //         uniforms: {
        //             spacing: this.spacing,
        //             width: this.lineWidth,
        //             lowColor: this.lowColor,
        //             midColor: this.midColor,
        //             highColor: this.highColor,
        //             minHeight: this.minHeight,
        //             maxHeight: this.maxHeight,
        //             gradientIntensity: this.gradientIntensity,
        //             useSmoothGradient: this.useSmoothGradient,
        //             showLabels: this.showLabels,
        //             enableContour: this.enableContour
        //         },
        //         source: contourShader
        //     }
        // });

    // let viewer = null;
    // let contourMaterial = null;

    // // 如果已有 viewer 则复用，否则新建
    // if (this.viewer) {
    //   viewer = this.viewer;
    // } else {
    //   Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJkZTlkNjBmMi05NjdjLTQwMTgtOTBiOC04NDU1NWJjYmFkZWEiLCJpZCI6MzA2MzMzLCJpYXQiOjE3NDgyNDg4MTl9.r7m_tXkLjZOAcHKP_oI0BuCvE6xuaujzU3CL7f4TG9A';

    //   viewer = new Cesium.Viewer('cesium-viewer', {
    //     terrainProvider: Cesium.createWorldTerrain({
    //       requestWaterMask: true,
    //       requestVertexNormals: true
    //     }),
    //     baseLayerPicker: false,
    //     animation: false,
    //     timeline: false,
    //     infoBox: false,
    //     navigationHelpButton: false,
    //     sceneModePicker: false,
    //     geocoder: false,
    //     homeButton: false,
    //     fullscreenButton: false
    //   });

    //   // 设置初始视图
    //   viewer.camera.flyTo({
    //     destination: Cesium.Rectangle.fromDegrees(-180, -90, 180, 90)
    //   });
    // }

    // // 创建自定义等高线材质
    // function createContourMaterial() {
    //   const contourShader = `
    //     uniform float spacing;
    //     uniform float width;
    //     uniform vec4 lowColor;
    //     uniform vec4 midColor;
    //     uniform vec4 highColor;
    //     uniform float minHeight;
    //     uniform float maxHeight;
    //     uniform float gradientIntensity;
    //     uniform bool useSmoothGradient;
    //     uniform bool showLabels;
    //     uniform bool enableContour;

    //     czm_material czm_getMaterial(czm_materialInput materialInput)
    //     {
    //       czm_material material = czm_getDefaultMaterial(materialInput);

    //       float height = materialInput.height;
    //       float t = clamp((height - minHeight) / (maxHeight - minHeight), 0.0, 1.0);

    //       float modulo = mod(height, spacing);
    //       float halfWidth = width * 0.5;
    //       float contour = smoothstep(spacing - halfWidth, spacing, modulo);

    //       vec4 color;
    //       if (t < 0.5) {
    //         color = mix(lowColor, midColor, t * 2.0);
    //       } else {
    //         color = mix(midColor, highColor, (t - 0.5) * 2.0);
    //       }

    //       if (useSmoothGradient) {
    //         float gradient = pow(1.0 - abs(t - 0.5) * 2.0, gradientIntensity / 10.0);
    //         color = mix(color, vec4(1.0), gradient * 0.3);
    //       }

    //       material.diffuse = color.rgb;
    //       material.alpha = enableContour ? color.a * contour : 0.0;

    //       if (showLabels && contour < 0.1) {
    //         material.diffuse = mix(vec3(1.0), color.rgb, 0.3);
    //       }

    //       return material;
    //     }
    //   `;

    //   contourMaterial = new Cesium.Material({
    //     fabric: {
    //       type: 'ElevationContour',
    //       uniforms: {
    //         spacing: 200,
    //         width: 2,
    //         lowColor: new Cesium.Color(0.18, 0.545, 0.34, 1),
    //         midColor: new Cesium.Color(1, 0.647, 0, 1),
    //         highColor: new Cesium.Color(0.86, 0.08, 0.21, 1),
    //         minHeight: 800,
    //         maxHeight: 4000,
    //         gradientIntensity: 70,
    //         useSmoothGradient: true,
    //         showLabels: false,
    //         enableContour: true
    //       },
    //       source: contourShader
    //     }
    //   });

    //   viewer.scene.globe.material = contourMaterial;
    // }

    // // 更新材质参数
    // function updateContours() {
    //   contourMaterial.uniforms.spacing = parseInt(document.getElementById("contourInterval").value);
    //   contourMaterial.uniforms.width = parseFloat(document.getElementById("lineWidth").value);
    //   contourMaterial.uniforms.lowColor = Cesium.Color.fromCssColorString(document.getElementById("lowColor").value);
    //   contourMaterial.uniforms.midColor = Cesium.Color.fromCssColorString(document.getElementById("midColor").value);
    //   contourMaterial.uniforms.highColor = Cesium.Color.fromCssColorString(document.getElementById("highColor").value);
    //   contourMaterial.uniforms.minHeight = parseInt(document.getElementById("visibleRangeMin").value);
    //   contourMaterial.uniforms.maxHeight = parseInt(document.getElementById("visibleRangeMax").value);
    //   contourMaterial.uniforms.gradientIntensity = parseInt(document.getElementById("gradientIntensity").value);
    //   contourMaterial.uniforms.useSmoothGradient = document.getElementById("useSmoothGradient").checked;
    //   contourMaterial.uniforms.showLabels = document.getElementById("showLabels").checked;
    //   contourMaterial.uniforms.enableContour = document.getElementById("showContour").checked;

    //   viewer.scene.requestRender();

    //   // 更新UI显示
    //   document.getElementById("contourIntervalLabel").innerText = contourMaterial.uniforms.spacing;
    //   document.getElementById("minHeight").innerText = contourMaterial.uniforms.minHeight;
    //   document.getElementById("maxHeight").innerText = contourMaterial.uniforms.maxHeight;
    // }

    // // 更新相机位置信息
    // function updatePosition() {
    //   const pos = Cesium.Cartographic.fromCartesian(viewer.camera.position);
    //   document.getElementById("longitude").innerText = Cesium.Math.toDegrees(pos.longitude).toFixed(5);
    //   document.getElementById("latitude").innerText = Cesium.Math.toDegrees(pos.latitude).toFixed(5);
    //   document.getElementById("height").innerText = Math.round(pos.height);
    // }

    // // 计算视域大小
    // function updateViewSize() {
    //   const frustum = viewer.camera.frustum;
    //   if (frustum instanceof Cesium.PerspectiveFrustum) {
    //     const tanPhi = Math.tan(frustum.fovy / 2);
    //     const tanTheta = frustum.aspectRatio * tanPhi;
    //     const dist = Cesium.Math.toDegrees(Cesium.Cartographic.fromCartesian(viewer.camera.position).height);

    //     document.getElementById("viewWidth").innerText = Math.round(2 * dist * tanTheta / 1000);
    //     document.getElementById("viewHeight").innerText = Math.round(2 * dist * tanPhi / 1000);
    //   }
    // }

    // // 绑定事件监听器
    // function bindEvents() {
    //   const inputs = [
    //     "contourInterval", "lineWidth",
    //     "visibleRangeMin", "visibleRangeMax",
    //     "gradientIntensity", "useSmoothGradient", "showLabels", "showContour",
    //     "lowColor", "midColor", "highColor"
    //   ];

    //   inputs.forEach(id => {
    //     const el = document.getElementById(id);
    //     if (el) {
    //       el.addEventListener("input", updateContours);
    //       el.addEventListener("change", updateContours);
    //     }
    //   });

    //   viewer.camera.changed.addEventListener(updatePosition);
    //   viewer.scene.postRender.addEventListener(updateViewSize);

    //   updatePosition();
    //   updateViewSize();
    // }

    // // 初始化
    // function init() {
    //   createContourMaterial();
    //   bindEvents();
    // }

    // window.onload = init;