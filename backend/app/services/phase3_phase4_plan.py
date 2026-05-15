"""
第三/四阶段占位服务。

当前说明：
- 第一阶段已提供 API 与 Cesium 格式输出。
- 第二阶段已提供地形分析与路径规划基础算法。
- 本文件用于后续扩展：
  1) 真实 DEM 读取（rasterio/GDAL）
  2) 任务队列（Celery/RQ）
  3) Redis 缓存与请求去重
  4) 大规模瓦片化导出（COG/3D Tiles）
"""

from __future__ import annotations


def placeholder() -> None:
    return
