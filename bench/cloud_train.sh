#!/usr/bin/env bash
# ============================================================
# GeoAgent 意图路由 SFT —— 云端一键训练脚本
#
# 用途：在带 NVIDIA GPU 的 Linux 实例上（AutoDL / 阿里云 PAI-DSW 等）
#       一条命令完成「装依赖 → 下模型 → 训练 → 评测 → 打包」。
#
# 前置：① 实例镜像是「PyTorch 2.x + CUDA 12」（框架已装好）
#       ② 已把整个 bench/ 目录传上实例
#
# 用法：
#   bash cloud_train.sh                       # 默认 Qwen3.5-4B，2 轮
#   bash cloud_train.sh Qwen/Qwen3.5-4B 3     # 指定模型与轮数
#
# 产物：bench/geoagent_lora.tar.gz
#       （含 LoRA adapter、评测结果 JSON、训练前/后对比）
# ============================================================
set -euo pipefail

MODEL="${1:-Qwen/Qwen3.5-4B}"
EPOCHS="${2:-2}"

# 切到脚本所在目录（即 bench/）—— 脚本假设数据在 ./sft_data/
cd "$(dirname "${BASH_SOURCE[0]}")"
BENCH_DIR="$(pwd)"

echo "=========================================="
echo " 模型    : $MODEL"
echo " 轮数    : $EPOCHS"
echo " 工作目录: $BENCH_DIR"
echo "=========================================="

# ---------- 0. 环境自检 ----------
echo
echo "[0/5] GPU 与 PyTorch 自检"
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "❌ 未找到 nvidia-smi —— 实例可能没挂 GPU，或驱动未装。"
    exit 1
fi
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
python - <<'PY'
import sys
try:
    import torch
except ImportError:
    print("❌ 未装 PyTorch —— 请选带 PyTorch 的镜像，或先 pip install torch")
    sys.exit(1)
if not torch.cuda.is_available():
    print("❌ torch 能看到，但 CUDA 不可用 —— 可能装的是 CPU 版 torch。")
    sys.exit(1)
print(f"  torch {torch.__version__} / CUDA {torch.version.cuda} / "
      f"{torch.cuda.get_device_name(0)}")
PY

# ---------- 1. 依赖 ----------
echo
echo "[1/5] 安装依赖（约 1–2 分钟）"
pip install -q --upgrade transformers peft datasets accelerate bitsandbytes modelscope

# 显存 < 16 GB 自动切到 4-bit（QLoRA），避免 OOM 白跑
VRAM_GB=$(python -c "import torch;print(round(torch.cuda.get_device_properties(0).total_memory/1024**3))")
EXTRA=""
if [ "$VRAM_GB" -lt 16 ]; then
    EXTRA="--load-4bit"
    echo "  检测到 ${VRAM_GB} GB 显存 → 自动启用 4-bit（QLoRA）"
else
    echo "  检测到 ${VRAM_GB} GB 显存 → 使用 bf16 加载"
fi

# ---------- 2. 模型 ----------
echo
echo "[2/5] 下载模型（走 ModelScope，国内速度稳定）"
export MODELSCOPE_CACHE="$BENCH_DIR/.ms_cache"
MODEL_PATH=$(python - <<PY
from modelscope import snapshot_download
print(snapshot_download("$MODEL", cache_dir="$MODELSCOPE_CACHE"))
PY
)
echo "  模型路径: $MODEL_PATH"

# ---------- 3. 数据自检 ----------
echo
echo "[3/5] 训练数据自检"
if [ ! -f sft_data/train.json ]; then
    echo "❌ 缺 sft_data/train.json —— 请把整个 bench/ 目录都传上来（不要只传脚本）"
    exit 1
fi
python -c "
import json
tr = json.load(open('sft_data/train.json', encoding='utf-8'))
ev = json.load(open('sft_data/eval.json', encoding='utf-8'))
print(f'  训练 {len(tr)} 条 / 留出集 {len(ev)} 条')
"

# ---------- 4. 训练 ----------
echo
echo "[4/5] 开始训练（脚本会先测训练前基线，再训练，最后在留出集上复测）"
# shellcheck disable=SC2086
python train_intent_lora.py \
    --model "$MODEL_PATH" \
    --device cuda \
    $EXTRA \
    --epochs "$EPOCHS" \
    --eval-limit 80 \
    --save "lora_out/intent_cloud"

# ---------- 5. 打包 ----------
echo
echo "[5/5] 打包产物"
tar czf geoagent_lora.tar.gz -C "$BENCH_DIR" lora_out/intent_cloud
ls -lh geoagent_lora.tar.gz

echo
echo "=========================================="
echo "✅ 训练完成"
echo "   产物: $BENCH_DIR/geoagent_lora.tar.gz"
echo
echo "   取回本机的两种方式："
echo "   ① JupyterLab 左侧文件树 → 右键该文件 → Download"
echo "   ② 在本机执行（把 <实例SSH> 换成你的连接串）："
echo "      scp -P <端口> root@<主机>:$BENCH_DIR/geoagent_lora.tar.gz ."
echo
echo "   ⚠ 取回后请立刻到控制台关机，避免持续计费。"
echo "=========================================="
