from app.services.analysis_service import get_dem_metadata
p=r'F:/CZ/VS_Code_Programs/CesiumJS_Debug/cesium_old/data/Terrain/cite19.tif'
m=get_dem_metadata(p)
print('crs=',m['crs'])
print('size=',m['width'],m['height'])
print('bounds_wgs84=',m['bounds_wgs84'])
print('bounds_dataset=',m['bounds_dataset'])
