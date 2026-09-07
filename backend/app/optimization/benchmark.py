"""基准测试：延迟、吞吐、内存峰值。

只报加速比不报内存和绝对耗时是没有意义的 —— 分块优化的主要收益就在内存，
而「快了 3 倍」在 20ms 和 20s 两个量级上的工程含义完全不同。
"""

from __future__ import annotations

import gc
import statistics
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np


def _rss_mb() -> Optional[float]:
    """当前进程 RSS（MB）。psutil 不可用时返回 None。"""
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            ctypes.windll.psapi.GetProcessMemoryInfo(
                ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
                counters.cb,
            )
            return counters.WorkingSetSize / (1024 * 1024)
        except Exception:
            return None


def measure(
    fn: Callable[..., Any],
    *args,
    repeats: int = 3,
    warmup: int = 1,
    **kwargs,
) -> Dict[str, Any]:
    """多次执行 fn 并统计耗时与内存峰值。

    Args:
        fn: 被测函数
        repeats: 计入统计的执行次数
        warmup: 预热次数（不计入统计），用于消除首次加载/编译开销
    """
    for _ in range(max(0, warmup)):
        fn(*args, **kwargs)
    gc.collect()

    times: List[float] = []
    peak_delta = 0.0
    for _ in range(max(1, repeats)):
        gc.collect()
        before = _rss_mb()
        t0 = time.perf_counter()
        fn(*args, **kwargs)
        times.append((time.perf_counter() - t0) * 1000.0)
        after = _rss_mb()
        if before is not None and after is not None:
            peak_delta = max(peak_delta, after - before)

    return {
        "mean_ms": round(statistics.mean(times), 2),
        "min_ms": round(min(times), 2),
        "max_ms": round(max(times), 2),
        "std_ms": round(statistics.pstdev(times), 2) if len(times) > 1 else 0.0,
        "repeats": len(times),
        "peak_rss_delta_mb": round(peak_delta, 1) if peak_delta else None,
    }


def synthetic_dem(
    n: int = 128, base: float = 1500.0, relief: float = 300.0, seed: int = 0
) -> np.ndarray:
    """生成带空间自相关的合成地形，用于基准测试。

    用平滑随机场而不是纯噪声：纯噪声会让 64×64 patch 全变成高频，
    既不真实也会让分类结果退化成一团乱麻，测出来的时间没有参考价值。
    """
    rng = np.random.default_rng(seed)
    g = rng.normal(0, 1, (n, n))
    for _ in range(20):
        g = (
            g
            + np.roll(g, 1, 0)
            + np.roll(g, -1, 0)
            + np.roll(g, 1, 1)
            + np.roll(g, -1, 1)
        ) / 5
    return (g * relief + base).astype(np.float32)


def compare_variants(
    dem: np.ndarray,
    variants: Sequence[Tuple[str, Callable[[np.ndarray], Any]]],
    repeats: int = 3,
    warmup: int = 1,
) -> List[Dict[str, Any]]:
    """对比多个实现在同一份 DEM 上的表现。

    Args:
        variants: [(名称, 接受 dem 的可调用对象), ...]
    """
    results: List[Dict[str, Any]] = []
    baseline_ms: Optional[float] = None

    for name, fn in variants:
        stat = measure(fn, dem, repeats=repeats, warmup=warmup)
        if baseline_ms is None:
            baseline_ms = stat["mean_ms"]
            speedup = 1.0
        else:
            speedup = baseline_ms / stat["mean_ms"] if stat["mean_ms"] > 0 else 0.0
        stat["variant"] = name
        stat["speedup_vs_baseline"] = round(speedup, 2)
        results.append(stat)

    return results
