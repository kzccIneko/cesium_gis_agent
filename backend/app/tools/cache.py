"""TerrainResult 缓存层。

为什么需要：
    analyze_terrain() 是一次性计算「坡度/坡向/曲率/代价/方向代价/流水线强度」
    全部指标的函数。Agent 在单轮任务中常连续调用多个指标工具
    （如「算坡度」→「再算坡向」→「再做通行性分析」），
    若无缓存则同一份 DEM 会被重复解析与计算 N 次。

    本缓存按 (bbox, resolution, dem_path, decode 参数, start/end) 复用分析结果，
    使一次典型的多指标任务从 O(N × 全量计算) 降为 O(1 × 全量计算)。

实现要点：
    - LRU + TTL 双重淘汰，避免长时间驻留占用内存
    - 线程安全（FastAPI / onnxruntime 推理可能在多线程下调用）
    - 暴露命中率统计，便于在 README 与面试中给出量化收益
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..services.analysis_service import TerrainResult, analyze_terrain


class TerrainResultCache:
    """线程安全的 TerrainResult LRU 缓存。"""

    def __init__(self, max_size: int = 32, ttl_seconds: float = 1800.0):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._store: "OrderedDict[str, Tuple[float, TerrainResult]]" = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    # ── 缓存键 ──────────────────────────────────────────────────────
    @staticmethod
    def _make_key(
        bbox: Tuple[float, float, float, float],
        resolution: int,
        dem_path: Optional[str],
        dem_decode_mode: Optional[str],
        dem_decode_band: Optional[int],
        dem_decode_scale: Optional[float],
        dem_decode_offset: Optional[float],
        dem_decode_nodata: Optional[float],
        start_lon: Optional[float],
        start_lat: Optional[float],
        end_lon: Optional[float],
        end_lat: Optional[float],
    ) -> str:
        payload: Dict[str, Any] = {
            "bbox": [round(float(v), 6) for v in bbox],
            "resolution": int(resolution),
            "dem_path": str(dem_path or ""),
            "mode": str(dem_decode_mode or "none"),
            "band": int(dem_decode_band or 1),
            "scale": float(dem_decode_scale or 1.0),
            "offset": float(dem_decode_offset or 0.0),
            "nodata": None if dem_decode_nodata is None else float(dem_decode_nodata),
            # 方向性代价依赖起终点，必须纳入缓存键，否则会串味
            "start": None if start_lon is None else [round(float(start_lon), 6), round(float(start_lat), 6)],
            "end": None if end_lon is None else [round(float(end_lon), 6), round(float(end_lat), 6)],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    # ── 获取 / 计算 ─────────────────────────────────────────────────
    def get_or_compute(
        self,
        bbox: Tuple[float, float, float, float],
        resolution: int,
        dem_path: Optional[str] = None,
        dem_decode_mode: Optional[str] = None,
        dem_decode_band: Optional[int] = None,
        dem_decode_scale: Optional[float] = None,
        dem_decode_offset: Optional[float] = None,
        dem_decode_nodata: Optional[float] = None,
        start_lon: Optional[float] = None,
        start_lat: Optional[float] = None,
        end_lon: Optional[float] = None,
        end_lat: Optional[float] = None,
    ) -> Tuple[TerrainResult, bool]:
        """返回 (TerrainResult, cache_hit)。cache_hit=True 表示命中缓存。"""
        key = self._make_key(
            bbox, resolution, dem_path, dem_decode_mode, dem_decode_band,
            dem_decode_scale, dem_decode_offset, dem_decode_nodata,
            start_lon, start_lat, end_lon, end_lat,
        )

        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                ts, result = entry
                if now - ts <= self.ttl:
                    # 命中：移到队尾（LRU）
                    self._store.move_to_end(key)
                    self._store[key] = (now, result)
                    self._hits += 1
                    return result, True
                # 过期
                del self._store[key]
            self._misses += 1

        # 未命中：在锁外计算（避免长耗时操作阻塞其他线程）
        west, south, east, north = bbox
        result = analyze_terrain(
            west=west, south=south, east=east, north=north,
            resolution=resolution,
            dem_path=dem_path,
            dem_decode_mode=dem_decode_mode,
            dem_decode_band=dem_decode_band,
            dem_decode_scale=dem_decode_scale,
            dem_decode_offset=dem_decode_offset,
            dem_decode_nodata=dem_decode_nodata,
            start_lon=start_lon,
            start_lat=start_lat,
            end_lon=end_lon,
            end_lat=end_lat,
        )

        with self._lock:
            self._store[key] = (time.monotonic(), result)
            self._store.move_to_end(key)
            # LRU 淘汰
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)

        return result, False

    # ── 统计与运维 ──────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._store),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
                "ttl_seconds": self.ttl,
            }

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0


# 全局单例
terrain_cache = TerrainResultCache()
