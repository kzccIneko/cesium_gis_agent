"""模型优化层测试。

运行::

    python backend/app/optimization/tests/test_optimization.py

必须用 backend 虚拟环境。不需要真实 DEM，合成地形即可覆盖全部断言。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import numpy as np  # noqa: E402

from app.optimization import OptimizedONNXClassifier  # noqa: E402
from app.optimization.benchmark import synthetic_dem  # noqa: E402
from app.optimization.classifier import PATCH_SIZE  # noqa: E402
from app.optimization.patches import (  # noqa: E402
    estimate_chunk_rows,
    fill_from_samples,
    iter_patch_batches,
)
from app.optimization.validate import (  # noqa: E402
    boundary_density,
    class_distribution,
    compare_classifications,
    per_class_iou,
    total_variation_distance,
)

_PASSED = 0
_FAILED = 0
_FAILURES: list = []


def _run(fn):
    global _PASSED, _FAILED
    try:
        fn()
        _PASSED += 1
        print(f"  PASS  {fn.__name__}")
    except AssertionError as exc:
        _FAILED += 1
        _FAILURES.append((fn.__name__, str(exc) or "断言失败"))
        print(f"  FAIL  {fn.__name__}\n        {exc}")
    except Exception as exc:  # noqa: BLE001
        _FAILED += 1
        _FAILURES.append((fn.__name__, f"{type(exc).__name__}: {exc}"))
        print(f"  ERROR {fn.__name__}\n        {type(exc).__name__}: {exc}")


def test(fn):
    globals()[fn.__name__] = fn
    return fn


# ---------------------------------------------------------------------------
# patches
# ---------------------------------------------------------------------------


@test
def test_patch_count_matches_grid():
    dem = synthetic_dem(80, seed=0)
    total = 0
    for batch, rr, cc in iter_patch_batches(dem, patch_size=64, stride=1):
        assert batch.shape == (batch.shape[0], 1, 64, 64)
        assert len(rr) == batch.shape[0] == len(cc)
        total += batch.shape[0]
    assert total == dem.shape[0] * dem.shape[1], total


@test
def test_patch_normalization_is_per_patch_zscore():
    """每个 patch 必须独立 z-score：均值≈0、标准差≈1。"""
    dem = synthetic_dem(70, seed=1)
    for batch, _, _ in iter_patch_batches(dem, patch_size=64, stride=4, batch_size=8):
        for i in range(batch.shape[0]):
            mu = float(batch[i].mean())
            sd = float(batch[i].std())
            assert abs(mu) < 1e-3, f"均值不为 0: {mu}"
            assert abs(sd - 1.0) < 1e-3, f"标准差不为 1: {sd}"
        break  # 只验第一批，足够


@test
def test_stride_reduces_patch_count_quadratically():
    dem = synthetic_dem(96, seed=2)

    def count(stride):
        return sum(
            b.shape[0]
            for b, _, _ in iter_patch_batches(dem, patch_size=64, stride=stride)
        )

    n1, n2, n4 = count(1), count(2), count(4)
    assert n2 < n1 and n4 < n2
    # stride=k 时采样数约为 1/k²
    assert abs(n4 / n1 - 0.0625) < 0.02, n4 / n1


@test
def test_chunking_bounds_memory():
    """分块必须让单块大小受预算控制 —— 这是修复 1GB 峰值内存的关键。"""
    rows = estimate_chunk_rows(n_cols=256, patch_size=64, max_chunk_mb=32)
    budget = 32 * 1024 * 1024
    per_row = 256 * 64 * 64 * 4
    assert rows * per_row <= budget * 1.01, (rows, rows * per_row / 1024 / 1024)
    assert rows >= 1


@test
def test_fill_from_samples_stride1_is_exact():
    vals = np.arange(12, dtype=np.float32)
    out = fill_from_samples(vals, (3, 4), stride=1)
    assert out.shape == (3, 4)
    assert np.array_equal(out, vals.reshape(3, 4))


@test
def test_fill_from_samples_stride2_expands():
    vals = np.arange(4, dtype=np.float32)
    out = fill_from_samples(vals, (4, 4), stride=2)
    assert out.shape == (4, 4)
    # 最近邻：每个采样值覆盖 2×2
    assert out[0, 0] == 0 and out[1, 1] == 0
    assert out[2, 2] == 3


@test
def test_patch_extraction_rejects_small_dem():
    dem = synthetic_dem(32, seed=3)
    try:
        next(iter_patch_batches(dem, patch_size=64))
    except ValueError as exc:
        assert "太小" in str(exc)
    else:
        raise AssertionError("小栅格应当报错而不是静默产出错误结果")


# ---------------------------------------------------------------------------
# classifier
# ---------------------------------------------------------------------------


@test
def test_optimized_matches_legacy_exactly():
    """优化版必须与原版逐像素一致 —— 否则就是改坏了，不是优化。

    这条是整套优化的安全底线：向量化与分块只是换了实现方式，
    数值上不允许有任何偏差。
    """
    from app.services.terrain_classifier import ONNXTerrainClassifier

    dem = synthetic_dem(80, seed=4)
    legacy = ONNXTerrainClassifier()
    opt = OptimizedONNXClassifier(stride=1, batch_size=64)

    ids_a, cost_a, conf_a = legacy.classify(dem)
    ids_b, cost_b, conf_b = opt.classify(dem)

    assert ids_a.shape == ids_b.shape
    agree = float((ids_a == ids_b).mean())
    assert agree == 1.0, f"与原版一致率 {agree}，应为 1.0"
    assert np.allclose(conf_a, conf_b, atol=1e-4), "置信度出现偏差"
    assert np.allclose(cost_a, cost_b, atol=1e-6), "cost surface 出现偏差"


@test
def test_classifier_rejects_small_dem():
    dem = synthetic_dem(32, seed=5)
    c = OptimizedONNXClassifier()
    try:
        c.classify(dem)
    except ValueError as exc:
        assert "太小" in str(exc)
    else:
        raise AssertionError("小栅格应明确报错")


@test
def test_classifier_output_shapes_and_ranges():
    dem = synthetic_dem(96, seed=6)
    c = OptimizedONNXClassifier(stride=2)
    ids, cost, conf = c.classify(dem)
    assert ids.shape == dem.shape
    assert conf.shape == dem.shape
    assert cost.shape == dem.shape
    assert ids.min() >= 0 and ids.max() <= 7, (ids.min(), ids.max())
    assert conf.min() >= 0.0 and conf.max() <= 1.0
    assert (cost > 0).all(), "cost 必须为正"


@test
def test_stats_recorded():
    dem = synthetic_dem(72, seed=7)
    c = OptimizedONNXClassifier(stride=2)
    c.classify(dem)
    st = c.last_stats
    assert st is not None
    d = st.to_dict()
    assert d["patches"] > 0 and d["batches"] > 0
    assert d["total_ms"] > 0
    assert d["throughput_patches_per_s"] > 0


@test
def test_stride2_is_faster_than_stride1():
    """加速必须真实存在，否则不值得引入精度损失。"""
    dem = synthetic_dem(96, seed=8)
    c1 = OptimizedONNXClassifier(stride=1)
    c2 = OptimizedONNXClassifier(stride=2)
    c1.classify(dem)
    c2.classify(dem)

    t = time.perf_counter()
    c1.classify(dem)
    t1 = time.perf_counter() - t
    t = time.perf_counter()
    c2.classify(dem)
    t2 = time.perf_counter() - t

    assert t2 < t1, f"stride=2 未提速：{t1:.3f}s vs {t2:.3f}s"


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


@test
def test_identical_inputs_pass():
    rng = np.random.default_rng(0)
    ids = rng.integers(0, 8, (32, 32))
    cost = np.ones((32, 32))
    conf = rng.random((32, 32)).astype(np.float32)
    res = compare_classifications(ids, ids, conf, conf, cost, cost)
    assert res["passed"], res["checks"]
    assert res["metrics"]["overall_agreement"] == 1.0


@test
def test_salt_and_pepper_is_caught_by_boundary_density():
    """椒盐噪声对一致率影响很小，但边界密度会暴涨 —— 必须能抓到。"""
    rng = np.random.default_rng(1)
    base = np.zeros((64, 64), dtype=np.int64)
    base[32:, :] = 1  # 干净的两块

    noisy = base.copy()
    mask = rng.random((64, 64)) < 0.02
    noisy[mask] = 1 - noisy[mask]

    agreement = float((base == noisy).mean())
    assert agreement > 0.97, "构造前提：一致率应当很高"

    res = compare_classifications(base, noisy)
    assert not res["passed"], "椒盐噪声必须被判定为不可接受"
    assert res["checks"]["boundary_density"]["value"] > 1.3


@test
def test_rare_class_erasure_is_caught():
    """整体一致率很高但稀有类被抹平 —— 这是地理场景最危险的失败模式。"""
    base = np.zeros((64, 64), dtype=np.int64)
    base[0:4, 0:4] = 7  # 悬崖，占比 0.39%，稀有但关键

    erased = base.copy()
    erased[0:4, 0:4] = 0  # 全抹成平地

    res = compare_classifications(base, erased)
    agreement = res["metrics"]["overall_agreement"]
    assert agreement > 0.99, f"构造前提：一致率应极高，实际 {agreement}"
    assert not res["passed"], "稀有类被抹平必须被判定为不可接受"

    cliff = [c for c in res["per_class"] if c["id"] == 7][0]
    assert cliff["rare"] is True
    assert cliff["iou"] == 0.0


@test
def test_per_class_iou_values():
    a = np.array([[0, 0], [1, 1]])
    b = np.array([[0, 0], [1, 0]])
    ious = per_class_iou(a, b, n_classes=2)
    assert abs(ious[0] - (2 / 3)) < 1e-9, ious[0]  # inter=2, union=3
    assert abs(ious[1] - 0.5) < 1e-9, ious[1]  # inter=1, union=2


@test
def test_class_distribution_and_tvd():
    a = np.array([0] * 50 + [1] * 50)
    b = np.array([0] * 60 + [1] * 40)
    da, db = class_distribution(a, 2), class_distribution(b, 2)
    assert abs(da[0] - 0.5) < 1e-9
    assert abs(total_variation_distance(da, db) - 0.1) < 1e-9


@test
def test_boundary_density_on_known_pattern():
    half = np.zeros((16, 16), dtype=np.int64)
    half[:, 8:] = 1
    d = boundary_density(half)
    # 竖向一条边界：行方向无差异，列方向 1/15 的差异
    assert abs(d - (1 / 15) / 2) < 1e-6, d
    assert boundary_density(np.zeros((8, 8), dtype=np.int64)) == 0.0


@test
def test_report_is_json_serializable():
    """验证报告必须能直接 JSON 序列化 —— 它要进 MCP 响应和 CI 报告。

    numpy 标量（np.bool_ / np.float64）混进 dict 会让 json.dumps 直接抛
    TypeError，而这类泄漏在没有这条测试时极难发现。
    """
    import json

    rng = np.random.default_rng(2)
    a = rng.integers(0, 8, (32, 32))
    b = a.copy()
    b[::7, ::7] = (b[::7, ::7] + 1) % 8
    conf = rng.random((32, 32)).astype(np.float32)
    cost = np.ones((32, 32))

    res = compare_classifications(a, b, conf, conf * 0.9, cost, cost * 1.01)
    payload = json.dumps(res, ensure_ascii=False)  # 不应抛异常
    assert payload

    # 逐字段确认没有 numpy 标量漏出
    def _check(obj, path="root"):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert not hasattr(v, "dtype") or np.ndim(v) == 0 and not isinstance(
                    v, (np.bool_, np.floating, np.integer)
                ), f"{path}.{k} 是 numpy 标量: {type(v)}"
                _check(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _check(v, f"{path}[{i}]")

    _check(res)


@test
def test_shape_mismatch_raises():
    try:
        compare_classifications(np.zeros((4, 4)), np.zeros((5, 5)))
    except ValueError as exc:
        assert "形状不一致" in str(exc)
    else:
        raise AssertionError("形状不一致必须报错")


@test
def test_memory_is_bounded_by_chunk_budget():
    """峰值内存由 chunk 预算决定，不随输入面积平方增长。

    朴素实现会一次性分配 N²·64²·4 字节（128² 即 268 MB，256² 近 1 GB）。
    这里断言：把预算压到 16 MB 时，峰值显著低于朴素实现，
    且 64 → 96 的输入放大不会引起同比例的内存放大。
    """
    import tracemalloc

    def peak_mb(n: int, budget: float) -> float:
        dem = synthetic_dem(n, seed=0)
        clf = OptimizedONNXClassifier(stride=1, max_chunk_mb=budget)
        tracemalloc.start()
        clf.classify(dem)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return peak / 1e6

    p64 = peak_mb(64, 16.0)
    p96 = peak_mb(96, 16.0)
    naive96 = 96 * 96 * 64 * 64 * 4 / 1e6

    assert p96 < naive96 * 0.5, f"96² 峰值 {p96:.1f} MB 未显著低于朴素 {naive96:.1f} MB"
    # 面积放大 2.25 倍，峰值放大应远小于该比例（分块生效则几乎持平）
    assert p96 < p64 * 1.8, f"内存未收敛：64²={p64:.1f} MB → 96²={p96:.1f} MB"


@test
def test_chunk_rows_respects_budget():
    """estimate_chunk_rows 按预算换算行数，且至少为 1。"""
    assert estimate_chunk_rows(128, 64, max_chunk_mb=16.0) >= 1
    assert estimate_chunk_rows(128, 64, max_chunk_mb=1024.0) >= estimate_chunk_rows(
        128, 64, max_chunk_mb=16.0
    )
    # 极窄的列数下也不应退化成 0
    assert estimate_chunk_rows(1, 64, max_chunk_mb=1.0) >= 1


def main() -> int:
    print("=" * 62)
    print("模型优化层测试")
    print("=" * 62)
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in sorted(names):
        fn = globals()[n]
        if callable(fn):
            _run(fn)

    print()
    print("=" * 62)
    print(f"通过 {_PASSED} / {_PASSED + _FAILED}")
    if _FAILURES:
        print()
        print("失败明细：")
        for name, msg in _FAILURES:
            print(f"  - {name}: {msg}")
    print("=" * 62)
    return 0 if _FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
