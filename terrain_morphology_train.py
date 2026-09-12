"""
8 类地形形态分类 CNN 训练 + ONNX 导出

流程:
  1. 用 Perlin 噪声 + 高斯滤波器生成随机地形 DEM
  2. 计算坡度/曲率/TPI，运行规则分类器 → 伪标签
  3. 训练 ResNet18 (8 输出)
  4. 验证并导出 ONNX
"""

import os, sys, math, json
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend", "app", "services"))
from terrain_classifier import classify_terrain, TERRAIN_CLASSES, _tpi

PATCH_SIZE = 64
N_CLASSES = 8
N_SAMPLES = 20000
VAL_SPLIT = 0.15
BATCH_SIZE = 64
EPOCHS = 50
LR = 1e-3
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "models", "terrain_morphology")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def perlin_noise_2d(size, scale=50, octaves=4, seed=None):
    """Simplified multi-octave terrain generation using FFT-based filtering."""
    if seed is not None:
        np.random.seed(seed)
    noise = np.random.randn(size, size)
    freqs = np.fft.fftfreq(size)
    fx, fy = np.meshgrid(freqs, freqs)
    f = np.sqrt(fx**2 + fy**2)
    f[0, 0] = 1
    pink = 1.0 / (f ** (octaves / 2))
    pink[0, 0] = 0
    fft = np.fft.fft2(noise)
    fft *= pink
    result = np.fft.ifft2(fft).real
    result = (result - result.min()) / (result.max() - result.min() + 1e-10)
    return result


def add_local_relief(dem, amplitude=0.2, freq=8):
    """Add ridges/valleys using sinusoidal modulations."""
    x = np.linspace(0, 2 * math.pi * freq, dem.shape[0])
    y = np.linspace(0, 2 * math.pi * freq, dem.shape[1])
    xx, yy = np.meshgrid(x, y)
    ridge = np.sin(xx) * np.cos(yy) * amplitude
    return dem + ridge


def generate_terrain_patch(size, seed=None):
    """Generate a single terrain patch with realistic morphology."""
    if seed is not None:
        rng = np.random.RandomState(seed)
    else:
        rng = np.random.RandomState()
    scale = rng.uniform(20, 80)
    octaves = rng.uniform(2, 5)
    dem = perlin_noise_2d(size, scale, octaves, seed if seed else rng.randint(0, 10000))
    if rng.random() > 0.5:
        dem = add_local_relief(dem, amplitude=rng.uniform(0.1, 0.4), freq=rng.uniform(4, 15))
    dem = dem * rng.uniform(50, 500) + rng.uniform(0, 200)
    return dem.astype(np.float64)


def compute_features(dem, cell_size=30.0):
    """Compute slope (deg), curvature from a DEM patch."""
    grad_y, grad_x = np.gradient(dem, cell_size, cell_size)
    slope = np.degrees(np.arctan(np.sqrt(grad_x**2 + grad_y**2)))
    prof_curv = -(np.gradient(grad_x / np.sqrt(1 + grad_x**2 + grad_y**2), cell_size, axis=1) +
                  np.gradient(grad_y / np.sqrt(1 + grad_x**2 + grad_y**2), cell_size, axis=0))
    return slope, prof_curv


class SyntheticTerrainDataset(Dataset):
    def __init__(self, n_samples, patch_size, seed_offset=0):
        self.n_samples = n_samples
        self.patch_size = patch_size
        self.seed_offset = seed_offset
        self._precompute = False

    def __len__(self):
        return self.n_samples

    def __getitem__(self, idx):
        seed = idx + self.seed_offset
        dem = generate_terrain_patch(self.patch_size, seed=seed)
        slope, curv = compute_features(dem)
        class_ids, _, _ = classify_terrain(dem, slope, curv, cell_size_m=30.0)
        dem_tensor = torch.from_numpy(dem).unsqueeze(0).float()
        dem_tensor = (dem_tensor - dem_tensor.mean()) / (dem_tensor.std() + 1e-8)
        label = class_ids[self.patch_size // 2, self.patch_size // 2]
        label_tensor = torch.tensor(label, dtype=torch.long)
        return dem_tensor, label_tensor


class SimpleCNN(nn.Module):
    def __init__(self, n_classes=8):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, 3, padding=1)
        self.bn1 = nn.BatchNorm2d(32)
        self.conv2 = nn.Conv2d(32, 64, 3, padding=1)
        self.bn2 = nn.BatchNorm2d(64)
        self.conv3 = nn.Conv2d(64, 128, 3, padding=1)
        self.bn3 = nn.BatchNorm2d(128)
        self.pool = nn.MaxPool2d(2)
        self.dropout = nn.Dropout(0.3)
        feature_size = 128 * (PATCH_SIZE // 8) * (PATCH_SIZE // 8)
        self.fc = nn.Linear(feature_size, n_classes)

    def forward(self, x):
        x = self.pool(F.relu(self.bn1(self.conv1(x))))
        x = self.pool(F.relu(self.bn2(self.conv2(x))))
        x = self.pool(F.relu(self.bn3(self.conv3(x))))
        x = x.view(x.size(0), -1)
        x = self.dropout(x)
        return self.fc(x)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Device: {DEVICE}")
    print(f"Generating {N_SAMPLES} synthetic terrain patches...")

    n_val = int(N_SAMPLES * VAL_SPLIT)
    n_train = N_SAMPLES - n_val
    train_ds = SyntheticTerrainDataset(n_train, PATCH_SIZE, seed_offset=0)
    val_ds = SyntheticTerrainDataset(n_val, PATCH_SIZE, seed_offset=n_train)

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    model = SimpleCNN(N_CLASSES).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    criterion = nn.CrossEntropyLoss()

    best_acc = 0.0
    for epoch in range(EPOCHS):
        model.train()
        train_loss, train_correct, train_total = 0, 0, 0
        for x, y in tqdm(train_loader, desc=f"Epoch {epoch+1}/{EPOCHS}"):
            x, y = x.to(DEVICE), y.to(DEVICE)
            optimizer.zero_grad()
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * x.size(0)
            preds = logits.argmax(dim=1)
            train_correct += (preds == y).sum().item()
            train_total += x.size(0)
        scheduler.step()

        model.eval()
        val_loss, val_correct, val_total = 0, 0, 0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(DEVICE), y.to(DEVICE)
                logits = model(x)
                loss = criterion(logits, y)
                val_loss += loss.item() * x.size(0)
                preds = logits.argmax(dim=1)
                val_correct += (preds == y).sum().item()
                val_total += x.size(0)

        train_acc = train_correct / train_total * 100
        val_acc = val_correct / val_total * 100
        print(f"  Train Loss: {train_loss/train_total:.4f} Acc: {train_acc:.2f}% | Val Loss: {val_loss/val_total:.4f} Acc: {val_acc:.2f}%")

        if val_acc > best_acc:
            best_acc = val_acc
            torch.save(model.state_dict(), os.path.join(OUTPUT_DIR, "best_model.pth"))

    model.load_state_dict(torch.load(os.path.join(OUTPUT_DIR, "best_model.pth"), map_location=DEVICE))

    model.eval()
    dummy = torch.randn(1, 1, PATCH_SIZE, PATCH_SIZE, device=DEVICE)
    torch.onnx.export(
        model,
        dummy,
        os.path.join(OUTPUT_DIR, "terrain_morphology.onnx"),
        input_names=["dem_patch"],
        output_names=["logits"],
        dynamic_axes={"dem_patch": {0: "batch_size"}, "logits": {0: "batch_size"}},
        opset_version=17,
    )

    legend = []
    for cid in sorted(TERRAIN_CLASSES.keys()):
        meta = TERRAIN_CLASSES[cid]
        legend.append({"id": cid, "name": meta["name"], "label_cn": meta["label_cn"], "color": meta["color"]})
    with open(os.path.join(OUTPUT_DIR, "legend.json"), "w") as f:
        json.dump(legend, f, ensure_ascii=False, indent=2)

    with open(os.path.join(OUTPUT_DIR, "model_params.json"), "w") as f:
        json.dump({"patch_size": PATCH_SIZE, "n_classes": N_CLASSES, "best_val_acc": round(best_acc, 2)}, f, indent=2)

    print(f"\nDone! Best Val Acc: {best_acc:.2f}%")
    print(f"ONNX: {os.path.join(OUTPUT_DIR, 'terrain_morphology.onnx')}")
    print(f"Legend: {os.path.join(OUTPUT_DIR, 'legend.json')}")


if __name__ == "__main__":
    main()
