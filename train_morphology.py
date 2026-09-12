"""Train 8-class terrain morphology classifier from pre-cached data + export ONNX."""
import os, sys, json
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import TensorDataset, DataLoader
from tqdm import tqdm

BASE_DIR = os.path.dirname(__file__)
CACHE_DIR = os.path.join(BASE_DIR, "models", "terrain_morphology")
sys.path.insert(0, os.path.join(BASE_DIR, "backend", "app", "services"))
from terrain_classifier import TERRAIN_CLASSES

PATCH_SIZE = 64
N_CLASSES = 8
BATCH_SIZE = 64
EPOCHS = 150
LR = 1e-3
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


class SimpleCNN(nn.Module):
    def __init__(self, n_classes=8):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 64, 3, padding=1)
        self.bn1 = nn.BatchNorm2d(64)
        self.conv2 = nn.Conv2d(64, 128, 3, padding=1)
        self.bn2 = nn.BatchNorm2d(128)
        self.conv3 = nn.Conv2d(128, 256, 3, padding=1)
        self.bn3 = nn.BatchNorm2d(256)
        self.conv4 = nn.Conv2d(256, 256, 3, padding=1)
        self.bn4 = nn.BatchNorm2d(256)
        self.pool = nn.MaxPool2d(2)
        self.dropout = nn.Dropout(0.4)
        feat_size = 256 * (PATCH_SIZE // 16) * (PATCH_SIZE // 16)
        self.fc = nn.Linear(feat_size, n_classes)

    def forward(self, x):
        x = self.pool(F.relu(self.bn1(self.conv1(x))))
        x = self.pool(F.relu(self.bn2(self.conv2(x))))
        x = self.pool(F.relu(self.bn3(self.conv3(x))))
        x = self.pool(F.relu(self.bn4(self.conv4(x))))
        x = x.view(x.size(0), -1)
        x = self.dropout(x)
        return self.fc(x)


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    print(f"Device: {DEVICE}")

    train_data = torch.load(os.path.join(CACHE_DIR, "train_data.pt"), weights_only=True)
    val_data = torch.load(os.path.join(CACHE_DIR, "val_data.pt"), weights_only=True)

    train_ds = TensorDataset(train_data["dems"], train_data["labels"])
    val_ds = TensorDataset(val_data["dems"], val_data["labels"])

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    model = SimpleCNN(N_CLASSES).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    criterion = nn.CrossEntropyLoss()  # balanced dataset, no weighting

    best_acc = 0.0
    for epoch in range(EPOCHS):
        model.train()
        tl, tc, tt = 0, 0, 0
        for x, y in tqdm(train_loader, desc=f"Ep {epoch+1}/{EPOCHS}", leave=False):
            x, y = x.to(DEVICE), y.to(DEVICE)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            tl += loss.item() * x.size(0)
            tc += (model(x).argmax(1) == y).sum().item()
            tt += x.size(0)
        scheduler.step()

        model.eval()
        vl, vc, vt = 0, 0, 0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(DEVICE), y.to(DEVICE)
                loss = criterion(model(x), y)
                vl += loss.item() * x.size(0)
                vc += (model(x).argmax(1) == y).sum().item()
                vt += x.size(0)

        ta = tc / tt * 100
        va = vc / vt * 100
        print(f"  Train: {tl/tt:.4f} {ta:.2f}% | Val: {vl/vt:.4f} {va:.2f}%")
        if va > best_acc:
            best_acc = va
            torch.save(model.state_dict(), os.path.join(CACHE_DIR, "best_model.pth"))

    model.load_state_dict(torch.load(os.path.join(CACHE_DIR, "best_model.pth"), map_location=DEVICE))
    model.eval()

    dummy = torch.randn(1, 1, PATCH_SIZE, PATCH_SIZE, device=DEVICE)
    onnx_path = os.path.join(CACHE_DIR, "terrain_morphology.onnx")
    torch.onnx.export(
        model, dummy, onnx_path,
        input_names=["dem_patch"], output_names=["logits"],
        dynamic_axes={"dem_patch": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )

    legend = []
    for cid in sorted(TERRAIN_CLASSES.keys()):
        m = TERRAIN_CLASSES[cid]
        legend.append({"id": cid, "name": m["name"], "label_cn": m["label_cn"], "color": m["color"]})
    with open(os.path.join(CACHE_DIR, "legend.json"), "w", encoding="utf-8") as f:
        json.dump(legend, f, ensure_ascii=False, indent=2)
    with open(os.path.join(CACHE_DIR, "model_params.json"), "w") as f:
        json.dump({"patch_size": PATCH_SIZE, "n_classes": N_CLASSES, "best_val_acc": round(best_acc, 2)}, f, indent=2)

    print(f"\nDone! Best Val Acc: {best_acc:.2f}%")
    print(f"ONNX: {onnx_path}")


if __name__ == "__main__":
    main()
