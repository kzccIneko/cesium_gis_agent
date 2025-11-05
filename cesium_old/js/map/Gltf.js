/**
 * Gltf 加载类
 */
class Gltf {
    /**
     * Gltf 构造函数
     * @param {url} url Modelurl
     * @param {double} lat 加载到的经度 默认 -123.0744619
     * @param {double} lot 加载到的纬度度 默认 44.0503706
     * @param {double} height 加载到的高度 默认0
     */
    constructor(url, lot = 29.558062, lat = 101.668102, height = 3810.86) {
        this.url = url;
        this.lat = lat;
        this.lot = lot;
        this.height = height;
        this.modelEntity = this.init();
    }
    init() {
        return Gltf.createModel(this.url, this.lat, this.lot, this.height);
    }
    static createModel(url, lat, lot, height) {
        var position = Cesium.Cartesian3.fromDegrees(lat, lot, height);
        var heading = Cesium.Math.toRadians(135);
        var pitch = 0;
        var roll = 0;
        var hpr = new Cesium.HeadingPitchRoll(heading, pitch, roll);
        var orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);

        var modelEntity = viewer.entities.add({
            name: url,
            position: position,
            orientation: orientation,
            model: {
                uri: url,
                minimumPixelSize: 1,
                maximumScale: 1000,
                shadows: Cesium.ShadowMode.ENABLED,
                scale: 2
            },
            clampToGround: true   // 自动将模型贴合地形
        });
        // viewer.trackedEntity = modelEntity;

        return modelEntity

    }
    // 模型在屏幕上最小保持128像素大小
    //如果摄像机无限靠近模型，模型最多会放大到原始大小的 20000 倍。
}