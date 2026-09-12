"""Generate synthetic terrain training data with deterministic 8-class labels.

Instead of relying on a rule-based teacher classifier that has inconsistent
peak/ridge vs depression/valley thresholds, we directly assign labels based
on the geometric terrain we generate. The model learns to associate DEM
patterns with ground-truth morphological classes.
"""
import sys, os, math, time
import numpy as np
import torch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend", "app", "services"))
from terrain_classifier import TERRAIN_CLASSES

PATCH_SIZE = 64
HALF = 32
N_CLASSES = 8
SAMPLES_PER_CLASS = 2000
VAL_SPLIT = 0.15
cache_dir = os.path.join(os.path.dirname(__file__), "models", "terrain_morphology")
os.makedirs(cache_dir, exist_ok=True)


def perlin(size, scale, octaves, seed):
    np.random.seed(seed)
    n = np.random.randn(size, size)
    f = np.fft.fftfreq(size)
    fx, fy = np.meshgrid(f, f)
    f = np.sqrt(fx**2 + fy**2)
    f[0, 0] = 1
    pink = 1.0 / (f ** (octaves / 2))
    pink[0, 0] = 0
    r = np.fft.ifft2(np.fft.fft2(n) * pink).real
    return (r - r.min()) / (r.max() - r.min() + 1e-10)


def gauss_2d(amp, sig, cx, cy):
    y, x = np.ogrid[:PATCH_SIZE, :PATCH_SIZE]
    return amp * np.exp(-((x - cx)**2 + (y - cy)**2) / (2 * sig**2))


def ridge_2d(amp, sig):
    """Gaussian ridge along x-axis at y=HALF. Shape (64,64)."""
    y = np.arange(PATCH_SIZE).reshape(-1, 1)
    profile = amp * np.exp(-(y - HALF)**2 / (2 * sig**2))
    return np.tile(profile, (1, PATCH_SIZE))


def _normalize(dem):
    t = torch.from_numpy(dem).unsqueeze(0).float()
    return (t - t.mean()) / (t.std() + 1e-8)


# ── Deterministic generators: each generates (dem_2d, label) ────────

def gen_flat(rng: np.random.RandomState):
    dem = perlin(PATCH_SIZE, rng.uniform(80, 150), rng.uniform(1.0, 1.8), rng.randint(0, 2**31))
    dem = dem * rng.uniform(1, 8)  # very low relief
    return _normalize(dem), 0


def gen_peak(rng: np.random.RandomState):
    # Small base + strong Gaussian peak at center
    dem = perlin(PATCH_SIZE, 80, 1.5, rng.randint(0, 2**31)) * 5
    sig = rng.uniform(2.0, 7.0)
    amp = rng.uniform(50, 400)
    cx = HALF + rng.randint(-3, 4)
    cy = HALF + rng.randint(-3, 4)
    dem += gauss_2d(amp, sig, cx, cy)
    return _normalize(dem), 1


def gen_ridge(rng: np.random.RandomState):
    # Low base + Gaussian ridge along the horizontal axis through center
    dem = perlin(PATCH_SIZE, 80, 1.5, rng.randint(0, 2**31)) * 5
    sig = rng.uniform(2.0, 8.0)
    amp = rng.uniform(30, 300)
    dem += ridge_2d(amp, sig)
    return _normalize(dem), 2


def gen_steep_slope(rng: np.random.RandomState):
    angle_deg = rng.uniform(10, 40)
    height = PATCH_SIZE * 30.0 * math.tan(math.radians(angle_deg))
    grad = np.linspace(0, height, PATCH_SIZE).reshape(-1, 1)
    dem = grad + rng.randn(PATCH_SIZE, PATCH_SIZE) * rng.uniform(0.5, 5)
    return _normalize(dem), 3


def gen_gentle_slope(rng: np.random.RandomState):
    angle_deg = rng.uniform(3.0, 8.0)
    height = PATCH_SIZE * 30.0 * math.tan(math.radians(angle_deg))
    grad = np.linspace(0, height, PATCH_SIZE).reshape(-1, 1)
    dem = grad + rng.randn(PATCH_SIZE, PATCH_SIZE) * rng.uniform(0.2, 2)
    return _normalize(dem), 4


def gen_valley(rng: np.random.RandomState):
    dem = perlin(PATCH_SIZE, 80, 1.5, rng.randint(0, 2**31)) * 5
    sig = rng.uniform(2.0, 8.0)
    amp = rng.uniform(30, 300)
    dem -= ridge_2d(amp, sig)  # negative ridge = valley
    return _normalize(dem), 5


def gen_depression(rng: np.random.RandomState):
    dem = perlin(PATCH_SIZE, 80, 1.5, rng.randint(0, 2**31)) * 5
    sig = rng.uniform(2.0, 7.0)
    amp = rng.uniform(50, 400)
    cx = HALF + rng.randint(-3, 4)
    cy = HALF + rng.randint(-3, 4)
    dem -= gauss_2d(amp, sig, cx, cy)
    return _normalize(dem), 6


def gen_cliff(rng: np.random.RandomState):
    dem = perlin(PATCH_SIZE, 80, 2.0, rng.randint(0, 2**31)) * 5
    step_h = rng.uniform(80, 300)
    step_pos = HALF + rng.randint(-5, 6)
    dem[:, step_pos:] += step_h
    return _normalize(dem), 7


GENERATORS = [gen_flat, gen_peak, gen_ridge, gen_steep_slope,
              gen_gentle_slope, gen_valley, gen_depression, gen_cliff]


def main():
    t0 = time.time()
    all_dems, all_labels = [], []

    total = SAMPLES_PER_CLASS * N_CLASSES
    print(f"Deterministic generation: {SAMPLES_PER_CLASS} per class x {N_CLASSES} = {total}")
    print("Classes:", [TERRAIN_CLASSES[c]["name"] for c in range(N_CLASSES)])
    sys.stdout.flush()

    for cid in range(N_CLASSES):
        gen_fn = GENERATORS[cid]
        for i in range(SAMPLES_PER_CLASS):
            rng = np.random.RandomState(cid * 1000000 + i + 42)
            t, label = gen_fn(rng)
            all_dems.append(t)
            all_labels.append(label)

        print(f"  {TERRAIN_CLASSES[cid]['name']}: {SAMPLES_PER_CLASS}")
        sys.stdout.flush()

    # Shuffle
    shuffle_idx = np.random.RandomState(42).permutation(len(all_dems))
    all_dems = [all_dems[i] for i in shuffle_idx]
    all_labels = [all_labels[i] for i in shuffle_idx]

    n_train = int(len(all_dems) * (1 - VAL_SPLIT))
    train_data = {
        "dems": torch.stack(all_dems[:n_train]),
        "labels": torch.tensor(all_labels[:n_train], dtype=torch.long),
    }
    val_data = {
        "dems": torch.stack(all_dems[n_train:]),
        "labels": torch.tensor(all_labels[n_train:], dtype=torch.long),
    }

    torch.save(train_data, os.path.join(cache_dir, "train_data.pt"))
    torch.save(val_data, os.path.join(cache_dir, "val_data.pt"))

    elapsed = time.time() - t0
    print(f"\nDone! {elapsed:.1f}s")
    print(f"Train: {len(train_data['labels'])}, Val: {len(val_data['labels'])}")
    dist_str = ", ".join(f"{TERRAIN_CLASSES[c]['name']}={SAMPLES_PER_CLASS}" for c in range(N_CLASSES))
    print(f"Distribution: {dist_str}")


if __name__ == "__main__":
    main()
