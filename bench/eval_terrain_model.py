#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地形形态分类模型完整评测脚本

产出简历可直接引用的全部量化指标：
  1. 整体指标：Overall Accuracy / Macro-F1 / Weighted-F1 / Cohen's Kappa / Top-2 Acc
  2. 每类指标：Precision / Recall / F1 / Support
  3. 混淆矩阵（数值 + 热力图）
  4. 推理速度：PyTorch vs ONNX Runtime（CPU）
  5. ONNX 与 PyTorch 输出一致性校验
  6. 与规则分类器 / Geomorphons 的速度对比（可选）

运行：
  D:/VS_Code_Program/CesiumJS_Debug/earthscape/.venv/Scripts/python.exe bench/eval_terrain_model.py
"""

from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

BASE = Path(__file__).resolve().parent.parent
CACHE = BASE / "models" / "terrain_morphology"
OUT_DIR = BASE / "bench" / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(BASE / "backend" / "app" / "services"))
from terrain_classifier import TERRAIN_CLASSES  # noqa: E402

PATCH_SIZE = 64
N_CLASSES = 8
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ── 模型定义：必须与 train_morphology.py 完全一致 ────────────────────
class SimpleCNN(nn.Module):
    def __init__(self, n_classes: int = 8):
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


def class_names_cn() -> List[str]:
    return [TERRAIN_CLASSES[i]["label_cn"] for i in sorted(TERRAIN_CLASSES)]


# ── 指标计算（不依赖 sklearn，纯 numpy，避免环境问题）────────────────
def compute_metrics(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int) -> Dict:
    """计算完整分类指标。"""
    # 混淆矩阵：行=真值，列=预测
    cm = np.zeros((n_classes, n_classes), dtype=np.int64)
    for t, p in zip(y_true, y_pred):
        cm[int(t), int(p)] += 1

    support = cm.sum(axis=1)                      # 每类真实样本数
    total = int(cm.sum())
    overall_acc = float(np.trace(cm) / total) if total else 0.0

    # 每类 Precision / Recall / F1
    per_class = []
    f1s, recalls, precs = [], [], []
    for c in range(n_classes):
        tp = int(cm[c, c])
        fp = int(cm[:, c].sum() - tp)
        fn = int(cm[c, :].sum() - tp)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        precs.append(prec); recalls.append(rec); f1s.append(f1)
        per_class.append({
            "class_id": c,
            "name": TERRAIN_CLASSES[c]["name"],
            "label_cn": TERRAIN_CLASSES[c]["label_cn"],
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": int(support[c]),
        })

    macro_f1 = float(np.mean(f1s))
    weighted_f1 = float(np.average(f1s, weights=support)) if support.sum() else 0.0

    # Cohen's Kappa
    po = overall_acc
    pe = float(np.sum((cm.sum(axis=0) / total) * (cm.sum(axis=1) / total))) if total else 0.0
    kappa = (po - pe) / (1 - pe) if pe < 1 else 0.0

    return {
        "overall_accuracy": round(overall_acc, 4),
        "macro_f1": round(macro_f1, 4),
        "weighted_f1": round(weighted_f1, 4),
        "cohens_kappa": round(kappa, 4),
        "mean_precision": round(float(np.mean(precs)), 4),
        "mean_recall": round(float(np.mean(recalls)), 4),
        "total_samples": total,
        "per_class": per_class,
        "confusion_matrix": cm.tolist(),
    }


def top_k_accuracy(logits: np.ndarray, y_true: np.ndarray, k: int = 2) -> float:
    topk = np.argsort(logits, axis=1)[:, -k:]
    hit = sum(1 for i, t in enumerate(y_true) if int(t) in topk[i])
    return round(hit / len(y_true), 4)


def main() -> None:
    print(f"[env] torch={torch.__version__}  device={DEVICE}")
    print(f"[data] cache={CACHE}")

    # ── 1. 加载验证集 ────────────────────────────────────────────────
    t0 = time.perf_counter()
    val = torch.load(CACHE / "val_data.pt", weights_only=True, map_location="cpu")
    dems, labels = val["dems"], val["labels"]
    print(f"[data] val: dems={tuple(dems.shape)} labels={tuple(labels.shape)} "
          f"({time.perf_counter()-t0:.1f}s)")

    y_true = labels.numpy().astype(np.int64)
    n = len(y_true)

    # 类别分布
    dist = {TERRAIN_CLASSES[i]["label_cn"]: int((y_true == i).sum()) for i in range(N_CLASSES)}
    print("\n[类别分布]")
    for k, v in dist.items():
        print(f"  {k:<6} {v:>5}  ({v/n*100:.1f}%)")

    # ── 2. PyTorch 模型推理 ──────────────────────────────────────────
    model = SimpleCNN(N_CLASSES)
    state = torch.load(CACHE / "best_model.pth", weights_only=True, map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    print(f"\n[model] best_model.pth 已加载 (params={sum(p.numel() for p in model.parameters()):,})")

    logits_list = []
    B = 128
    t0 = time.perf_counter()
    with torch.no_grad():
        for i in range(0, n, B):
            logits_list.append(model(dems[i:i + B]))
    logits = torch.cat(logits_list, dim=0)
    pt_time = time.perf_counter() - t0
    print(f"[infer] PyTorch ({DEVICE if DEVICE=='cpu' else 'cpu'}) 全量 {n} 样本: {pt_time:.2f}s "
          f"({pt_time/n*1000:.2f} ms/sample)")

    logits_np = logits.numpy()
    y_pred = logits_np.argmax(axis=1)

    # ── 3. 指标 ──────────────────────────────────────────────────────
    m = compute_metrics(y_true, y_pred, N_CLASSES)
    m["top2_accuracy"] = top_k_accuracy(logits_np, y_true, k=2)
    m["pytorch_infer_ms_per_sample"] = round(pt_time / n * 1000, 3)

    # 记录训练时保存的 best_val_acc，做交叉校验
    params_file = CACHE / "model_params.json"
    if params_file.exists():
        saved = json.loads(params_file.read_text(encoding="utf-8"))
        m["saved_best_val_acc"] = saved.get("best_val_acc")
        m["patch_size"] = saved.get("patch_size")
        m["n_classes"] = saved.get("n_classes")

    # ── 4. ONNX Runtime 推理 + 一致性 ────────────────────────────────
    onnx_path = CACHE / "terrain_morphology.onnx"
    if onnx_path.exists():
        try:
            import onnxruntime as ort
            sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
            inp = sess.get_inputs()[0].name
            x_np = dems.numpy()

            # 预热
            sess.run(None, {inp: x_np[:16]})
            t0 = time.perf_counter()
            onnx_logits = []
            for i in range(0, n, B):
                onnx_logits.append(sess.run(None, {inp: x_np[i:i + B]})[0])
            onnx_time = time.perf_counter() - t0
            onnx_logits = np.concatenate(onnx_logits, axis=0)

            onnx_pred = onnx_logits.argmax(axis=1)
            agree = float((onnx_pred == y_pred).mean())
            max_diff = float(np.abs(onnx_logits - logits_np).max())

            m["onnx_infer_ms_per_sample"] = round(onnx_time / n * 1000, 3)
            m["onnx_vs_pytorch_speedup"] = round(pt_time / onnx_time, 2) if onnx_time else None
            m["onnx_pytorch_agreement"] = round(agree, 4)
            m["onnx_pytorch_max_logit_diff"] = round(max_diff, 6)
            m["onnx_accuracy"] = round(float((onnx_pred == y_true).mean()), 4)
            print(f"[infer] ONNX Runtime 全量 {n} 样本: {onnx_time:.2f}s "
                  f"({onnx_time/n*1000:.2f} ms/sample)  加速比 {pt_time/onnx_time:.2f}x  一致性 {agree:.4f}")
        except Exception as e:
            print(f"[warn] ONNX 评测失败: {e}")
            m["onnx_error"] = str(e)

    # ── 5. 与规则分类器 / Geomorphons 的速度对比（大栅格场景）────────
    try:
        from terrain_classifier import GeomorphonsClassifier, classify_terrain
        import math

        rng = np.random.default_rng(42)
        # 构造 256x256 的起伏地形（模拟真实 DEM 片段）
        grid = rng.normal(0, 1, (256, 256))
        for _ in range(30):
            grid = (grid + np.roll(grid, 1, 0) + np.roll(grid, -1, 0)
                    + np.roll(grid, 1, 1) + np.roll(grid, -1, 1)) / 5
        grid = grid * 300 + 1500          # 缩放到米级高程
        cell = 30.0

        gy, gx = np.gradient(grid, cell, cell)
        slope = np.degrees(np.arctan(np.sqrt(gx ** 2 + gy ** 2)))
        curv = -(np.gradient(gx / np.sqrt(1 + gx ** 2 + gy ** 2), cell, axis=1)
                 + np.gradient(gy / np.sqrt(1 + gx ** 2 + gy ** 2), cell, axis=0))

        t0 = time.perf_counter()
        _geo = GeomorphonsClassifier()
        geo_ids, _, _ = _geo.classify(dem=grid, slope_deg=slope, curvature=curv, cell_size_m=cell)
        geo_time = time.perf_counter() - t0

        t0 = time.perf_counter()
        _rules = classify_terrain(dem=grid, slope_deg=slope, curvature=curv, cell_size_m=cell)
        rule_time = time.perf_counter() - t0

        n_patches = (256 // PATCH_SIZE) ** 2
        m["baseline_256x256"] = {
            "grid": "256x256 (65536 cells)",
            "geomorphons_ms": round(geo_time * 1000, 1),
            "rules_ms": round(rule_time * 1000, 1),
            "onnx_ms_estimate": round(n_patches * (m.get("onnx_infer_ms_per_sample", 0)), 1),
            "geomorphons_vs_onnx_speedup": (
                round(geo_time * 1000 / (n_patches * m["onnx_infer_ms_per_sample"]), 2)
                if m.get("onnx_infer_ms_per_sample") else None
            ),
        }
        print(f"[baseline] 256x256: Geomorphons {geo_time*1000:.1f}ms | "
              f"Rules {rule_time*1000:.1f}ms | ONNX(估) "
              f"{n_patches * m.get('onnx_infer_ms_per_sample', 0):.1f}ms")
    except Exception as e:
        print(f"[warn] 基线速度对比失败: {e}")
        m["baseline_error"] = str(e)

    # ── 6. 输出 ──────────────────────────────────────────────────────
    (OUT_DIR / "metrics.json").write_text(
        json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")

    names = class_names_cn()
    lines = [
        "# 地形形态分类模型 · 评测报告",
        "",
        f"- 模型：`models/terrain_morphology/terrain_morphology.onnx`（SimpleCNN，输入 64×64 DEM patch）",
        f"- 验证集：`val_data.pt`，{n} 个样本，来源为全球 42 个地点的真实 SRTM DEM",
        f"- 标签：Geomorphons 算法生成的伪标签（Jasiewicz & Stepinski 2013）",
        f"- 类别数：{N_CLASSES}",
        "",
        "## 整体指标",
        "",
        "| 指标 | 数值 |",
        "|---|---|",
        f"| Overall Accuracy | **{m['overall_accuracy']*100:.2f}%** |",
        f"| Macro-F1 | **{m['macro_f1']*100:.2f}%** |",
        f"| Weighted-F1 | {m['weighted_f1']*100:.2f}% |",
        f"| Cohen's Kappa | {m['cohens_kappa']:.4f} |",
        f"| Top-2 Accuracy | {m['top2_accuracy']*100:.2f}% |",
        f"| 平均 Precision | {m['mean_precision']*100:.2f}% |",
        f"| 平均 Recall | {m['mean_recall']*100:.2f}% |",
        "",
        "## 每类指标",
        "",
        "| 类别 | Precision | Recall | F1 | 样本数 |",
        "|---|---|---|---|---|",
    ]
    for pc in m["per_class"]:
        lines.append(f"| {pc['label_cn']} | {pc['precision']*100:.1f}% | "
                     f"{pc['recall']*100:.1f}% | {pc['f1']*100:.1f}% | {pc['support']} |")

    lines += ["", "## 混淆矩阵（行=真值，列=预测）", ""]
    header = "| 真值\\预测 | " + " | ".join(names) + " |"
    lines += [header, "|" + "---|" * (N_CLASSES + 1)]
    for i, row in enumerate(m["confusion_matrix"]):
        lines.append(f"| **{names[i]}** | " + " | ".join(str(v) for v in row) + " |")

    if "onnx_infer_ms_per_sample" in m:
        lines += [
            "", "## 推理性能", "",
            "| 推理方式 | 单样本耗时 | 加速比 |",
            "|---|---|---|",
            f"| PyTorch (CPU) | {m['pytorch_infer_ms_per_sample']} ms | 1.0x |",
            f"| ONNX Runtime (CPU) | {m['onnx_infer_ms_per_sample']} ms | "
            f"{m.get('onnx_vs_pytorch_speedup', '-')}x |",
            "",
            f"ONNX 与 PyTorch 输出一致性：**{m['onnx_pytorch_agreement']*100:.2f}%**"
            f"（最大 logits 差异 {m['onnx_pytorch_max_logit_diff']:.2e}）",
        ]

    if "baseline_256x256" in m:
        b = m["baseline_256x256"]
        lines += [
            "", "## 与传统算法的效率对比（256×256 栅格）", "",
            "| 方法 | 耗时 |",
            "|---|---|",
            f"| Geomorphons | {b['geomorphons_ms']} ms |",
            f"| 规则分类器 | {b['rules_ms']} ms |",
            f"| ONNX CNN（{int(256/PATCH_SIZE)**2} 个 patch） | {b['onnx_ms_estimate']} ms |",
            "",
            f"→ Geomorphons 相对 ONNX 的耗时比：**{b['geomorphons_vs_onnx_speedup']}x**",
        ]

    (OUT_DIR / "eval_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 62)
    print(f"  Overall Accuracy : {m['overall_accuracy']*100:.2f}%")
    print(f"  Macro-F1         : {m['macro_f1']*100:.2f}%")
    print(f"  Weighted-F1      : {m['weighted_f1']*100:.2f}%")
    print(f"  Cohen's Kappa    : {m['cohens_kappa']:.4f}")
    print(f"  Top-2 Accuracy   : {m['top2_accuracy']*100:.2f}%")
    print("=" * 62)
    print("\n  每类 F1：")
    for pc in sorted(m["per_class"], key=lambda x: x["f1"]):
        bar = "█" * int(pc["f1"] * 30)
        print(f"    {pc['label_cn']:<4} {pc['f1']*100:5.1f}%  {bar}")
    print(f"\n[out] {OUT_DIR / 'metrics.json'}")
    print(f"[out] {OUT_DIR / 'eval_report.md'}")


if __name__ == "__main__":
    main()
