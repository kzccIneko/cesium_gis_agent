"""Phase C: Download real DEM tiles worldwide → Geomorphons pseudo-labels → 64×64 patches."""

import os, sys, json, math
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np
import torch
from tqdm import tqdm

BASE = Path(__file__).resolve().parent
CACHE = BASE / "models" / "terrain_morphology"
CACHE.mkdir(parents=True, exist_ok=True)

# ── 30 globally diverse sampling locations (west, south, east, north) ──
LOCATIONS = [
    # ── Plains / Flat ──
    (113.5, 35.5, 113.9, 35.9),  # North China Plain
    (115.5, 36.0, 115.9, 36.4),  # Yellow River Delta
    (120.0, 32.5, 120.4, 32.9),  # Yangtze Delta
    (126.0, 37.0, 126.4, 37.4),  # Korean west coast plain
    (-90.0, 30.0, -89.6, 30.4),  # Mississippi Delta
    (-60.5, -34.0, -60.1, -33.6),# Pampas, Argentina
    (13.0, 52.0, 13.4, 52.4),    # North German Plain
    (106.0, 10.5, 106.4, 10.9),  # Mekong Delta

    # ── Peaks / Volcanoes ──
    (138.7, 35.2, 139.1, 35.6),  # Mt. Fuji, Japan
    (37.3, -3.0, 37.7, -2.6),    # Kilimanjaro, Tanzania
    (7.8, 45.9, 8.2, 46.3),      # Matterhorn, Swiss Alps
    (15.0, 37.7, 15.4, 38.1),    # Mt. Etna, Sicily
    (13.5, -2.9, 13.9, -2.5),    # Mt. Kenya
    (155.2, 19.4, 155.6, 19.8),  # Mauna Kea, Hawaii

    # ── Ridges / Mountains ──
    (86.6, 27.8, 87.0, 28.2),    # Everest, Nepal
    (109.0, 35.5, 109.4, 35.9),  # Loess Plateau ridges, China
    (-111.8, 36.0, -111.4, 36.4),# Grand Canyon, USA
    (-105.4, 39.8, -105.0, 40.2),# Rocky Mountains, USA
    (-119.3, 37.7, -118.9, 38.1),# Yosemite, USA
    (-110.8, 43.7, -110.4, 44.1),# Teton Range, USA
    (74.6, 37.0, 75.0, 37.4),    # Pamir Mountains
    (7.0, 46.0, 7.4, 46.4),      # Swiss Alps
    (144.0, -37.6, 144.4, -37.2),# Great Dividing Range, Australia
    (170.5, -43.6, 170.9, -43.2),# Southern Alps, NZ
    (150.8, -33.8, 151.2, -33.4),# Blue Mountains, Australia

    # ── Steep slopes / Canyons ──
    (100.4, 26.8, 100.8, 27.2),  # Tiger Leaping Gorge, China
    (-72.0, -15.5, -71.6, -15.1),# Colca Canyon, Peru
    (-111.4, 36.2, -111.0, 36.6),# Grand Canyon north rim
    (103.8, 30.4, 104.2, 30.8),  # Chengdu basin edge
    (110.0, 30.8, 110.4, 31.2),  # Three Gorges, China

    # ── Valleys ──
    (106.5, 28.5, 106.9, 28.9),  # Guizhou karst valleys
    (85.2, 28.0, 85.6, 28.4),    # Kathmandu valley, Nepal
    (77.0, 32.0, 77.4, 32.4),    # Himachal valleys, India
    (8.5, 47.2, 8.9, 47.6),      # Swiss plateau valleys
    (-122.5, 37.7, -122.1, 38.1),# SF Bay valleys

    # ── Depressions / Sinkholes ──
    (35.3, 31.4, 35.7, 31.8),    # Dead Sea, Israel/Jordan
    (27.0, 30.0, 27.4, 30.4),    # Qattara Depression, Egypt
    (-116.8, 36.2, -116.4, 36.6),# Badwater Basin, Death Valley
    (-117.8, 36.4, -117.4, 36.8),# Panamint Valley, USA

    # ── Cliffs / Coastal ──
    (1.3, 51.1, 1.7, 51.5),      # White Cliffs of Dover, UK
    (-117.3, 32.8, -116.9, 33.2),# La Jolla cliffs, CA
    (-122.7, 37.8, -122.3, 38.2),# SF coastal cliffs
    (-157.8, 21.2, -157.4, 21.6),# Oahu sea cliffs, Hawaii
]

PATCH_SIZE = 64
STRIDE = 32
VAL_RATIO = 0.2

# Geomorphons form → our class mapping (same as terrain_classifier.py)
GEOMORPHON_MAP = {
    1: 0, 2: 1, 3: 2, 4: 4, 5: 2,
    7: 5, 8: 4, 9: 5, 10: 6,
}


# Temporary codes before final mapping
CLIFF_MARKER = 99
# Geomorphons form 6 (Slope) needs slope-based split → store as a unique temp code
SLOPE_TO_SPLIT = 88


def _map_geo_labels(raw, slope_deg):
    """Map Geomorphons + cliff + slope override to 0-7. Returns array where
    SLOPE_TO_SPLIT marks pixels that need steep/gentle splitting."""
    out = np.full_like(raw, -1, dtype=np.int32)
    # Flat override: slope < 2° → flat (class 0)
    flat_mask = (slope_deg < 2.0) & (raw > 0)
    out[flat_mask] = 0
    # Geomorphons mapping for non-flat areas
    for g, c in GEOMORPHON_MAP.items():
        if g == 6:
            continue  # handled separately below
        mask = (raw == g) & ~flat_mask
        out[mask] = c
    # Geomorphons form 6 (Slope) → mark for splitting
    out[(raw == 6) & ~flat_mask] = SLOPE_TO_SPLIT
    # Geomorphons form 10 (Pit) → depression (class 6)
    out[(raw == 10) & ~flat_mask] = 6
    # Cliff override
    out[raw == CLIFF_MARKER] = 7
    return out


def download_dem(west, south, east, north):
    from dem_stitcher import stitch_dem
    import rasterio
    from rasterio.transform import from_bounds
    cache_dir = Path(os.environ.get("TEMP", "/tmp")) / "cesiumjs_dem_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = f"{west:.4f}_{south:.4f}_{east:.4f}_{north:.4f}"
    out = str(cache_dir / f"dem_{key}.tif")
    if Path(out).exists():
        return out
    X, p = stitch_dem(bounds=(west, south, east, north), dem_name="glo_30")
    rows, cols = X.shape
    t = from_bounds(west, south, east, north, cols, rows)
    with rasterio.open(out, "w", driver="GTiff", height=rows, width=cols,
                       count=1, dtype=np.float64, crs="EPSG:4326",
                       transform=t, nodata=np.nan) as dst:
        dst.write(X, 1)
    return out


def run_geomorphons(dem_path, cell_size_m, dem_full, slope_deg):
    """Run Geomorphons on a DEM file, return labels (0-10)."""
    import rasterio
    from whitebox import WhiteboxTools
    wbt = WhiteboxTools()
    wbt.set_verbose_mode(False)
    search = max(5, 500 // max(1, cell_size_m))
    with TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "geo.tif")
        # threshold=2.0°: classify more areas as flat
        wbt.geomorphons(dem=dem_path, output=out, search=search,
                        threshold=2.0, forms=True)
        with rasterio.open(out) as src:
            raw = src.read(1).astype(np.int32)
    # Post-process: override with cliff (slope >= 45°)
    raw[(slope_deg >= 45.0) & (raw > 0)] = CLIFF_MARKER
    return raw


def extract_patches(dem, labels_mapped, slope_deg=None):
    """Extract 64×64 patches; label = center pixel class (0-7)."""
    rows, cols = dem.shape
    half = PATCH_SIZE // 2
    dems, lbls = [], []
    for r in range(0, rows - PATCH_SIZE + 1, STRIDE):
        for c in range(0, cols - PATCH_SIZE + 1, STRIDE):
            dp = dem[r:r+PATCH_SIZE, c:c+PATCH_SIZE]
            if np.isnan(dp).any():
                continue
            mu, sd = dp.mean(), dp.std()
            if sd < 1e-6:
                continue
            # Center pixel label
            center_lb = labels_mapped[r + half, c + half]
            if center_lb < 0:
                continue  # background
            if center_lb == SLOPE_TO_SPLIT:
                if slope_deg is not None:
                    center_sl = slope_deg[r + half, c + half]
                    center_lb = 3 if center_sl >= 25.0 else 4
                else:
                    center_lb = 4
            dems.append(((dp - mu) / sd).astype(np.float32))
            lbls.append(center_lb)
    return dems, lbls


def main():
    print(f"Generating real DEM training data from {len(LOCATIONS)} locations...")
    class_counts = np.zeros(8, dtype=np.int64)

    def process_location(i, loc):
        west, south, east, north = loc
        cell_size_deg = (east - west) / 500
        cell_size_m = cell_size_deg * 111320.0
        try:
            dem_path = download_dem(west, south, east, north)
            with rasterio.open(dem_path) as src:
                dem_full = src.read(1).astype(np.float64)
            # Compute slope
            dy, dx = np.gradient(dem_full, cell_size_m, cell_size_m)
            slope_deg = np.degrees(np.arctan(np.sqrt(dx*dx + dy*dy)))
            # Geomorphons (with cliff override)
            raw_labels = run_geomorphons(dem_path, cell_size_m, dem_full, slope_deg)
            mapped = _map_geo_labels(raw_labels, slope_deg)
            dems, lbls = extract_patches(dem_full, mapped, slope_deg)
            return dems, lbls, f"OK ({west:.1f},{south:.1f}) {len(dems)} patches"
        except Exception as e:
            import traceback
            return [], [], f"FAIL ({west:.1f},{south:.1f}) {e}"

    results = []
    for i, loc in enumerate(LOCATIONS):
        dems, lbls, msg = process_location(i, loc)
        results.append((dems, lbls, msg))

    # Collect results
    all_dems_list = []
    all_labels_list = []
    for dems, lbls, msg in results:
        if dems:
            all_dems_list.extend(dems)
            all_labels_list.extend(lbls)
            for lb in lbls:
                class_counts[lb] += 1
            print(f"  {msg}: {len(dems)} patches")
        else:
            print(f"  {msg}")
    print(f"\nTotal raw patches: {len(all_dems_list)}")
    print(f"Class distribution: {class_counts.tolist()}")

    np.set_printoptions(precision=1, suppress=True)

    # Resample to target count per class (20k total, ~2500 per class)
    target_per_class = 2500
    indices_by_class = [[] for _ in range(8)]
    for idx, lb in enumerate(all_labels_list):
        indices_by_class[lb].append(idx)

    selected_indices = []
    for c in range(8):
        pool = indices_by_class[c]
        n = len(pool)
        if n == 0:
            print(f"  Class {c}: no samples, skipping")
            continue
        if n < target_per_class:
            # oversample with replacement
            sampled = np.random.choice(pool, target_per_class, replace=True).tolist()
        else:
            sampled = np.random.choice(pool, target_per_class, replace=False).tolist()
        selected_indices.extend(sampled)

    np.random.shuffle(selected_indices)
    n_total = len(selected_indices)
    n_val = int(n_total * VAL_RATIO)

    dems_arr = np.array([all_dems_list[i] for i in selected_indices], dtype=np.float32)
    labels_arr = np.array([all_labels_list[i] for i in selected_indices], dtype=np.int64)
    print(f"\nAfter balancing: {n_total} patches ({n_total - n_val} train, {n_val} val)")
    for c in range(8):
        cnt = int((labels_arr == c).sum())
        print(f"  Class {c}: {cnt} ({cnt/n_total*100:.1f}%)")

    dems_t = torch.from_numpy(dems_arr).unsqueeze(1)  # (N,1,64,64)
    labels_t = torch.from_numpy(labels_arr)

    perm = torch.randperm(n_total)
    dems_t = dems_t[perm]
    labels_t = labels_t[perm]

    train_data = {"dems": dems_t[:-n_val], "labels": labels_t[:-n_val]}
    val_data = {"dems": dems_t[-n_val:], "labels": labels_t[-n_val:]}

    torch.save(train_data, str(CACHE / "train_data.pt"))
    torch.save(val_data, str(CACHE / "val_data.pt"))
    print(f"\nSaved train_data.pt ({len(train_data['dems'])} samples)")
    print(f"Saved val_data.pt ({len(val_data['dems'])} samples)")


if __name__ == "__main__":
    import rasterio
    main()
