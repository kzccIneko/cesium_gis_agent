"""云端训练远程控制 —— 上传 → 执行 → 下载产物，全程无需手工操作。

用途：本机 6 GB 显存不适合训 4B，需在云端 GPU 实例上训练。
本脚本通过 SSH/SFTP 把代码与数据送上去、启动训练、再把 adapter 拉回来，
让"本机推理 + 云端训练"这条分工链路可以一条命令走完。

用法（密码建议走环境变量，避免出现在进程列表里）：

    # 全流程
    export CLOUD_SSH_PASSWORD='******'
    python bench/cloud_remote.py --host region-1.autodl.com --port 38672 --action all

    # 分步
    python bench/cloud_remote.py --host ... --port ... --action upload
    python bench/cloud_remote.py --host ... --port ... --action train
    python bench/cloud_remote.py --host ... --port ... --action fetch

    # 用密钥代替密码
    python bench/cloud_remote.py --host ... --port ... --key ~/.ssh/id_rsa --action all

默认远端工作目录：~/geoagent_train/bench
"""
from __future__ import annotations

import argparse
import getpass
import os
import posixpath
import sys
import time
from pathlib import Path

import paramiko

# 需要上传的最小集合（本机 → 远端），共约 700 KB
UPLOAD_FILES = [
    "bench/cloud_train.sh",
    "bench/train_intent_lora.py",
    "bench/sft_data/train.json",
    "bench/sft_data/eval.json",
]

REMOTE_ARTIFACT = "geoagent_lora.tar.gz"


def connect(args) -> paramiko.SSHClient:
    """建立 SSH 连接。密码优先取环境变量 CLOUD_SSH_PASSWORD。"""
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    pwd = os.environ.get("CLOUD_SSH_PASSWORD")
    kw: dict = {
        "hostname": args.host,
        "port": args.port,
        "username": args.user,
        "timeout": 30,
        "banner_timeout": 30,
        "auth_timeout": 30,
    }
    if args.key:
        kw["key_filename"] = str(Path(args.key).expanduser())
    elif pwd:
        kw["password"] = pwd
    else:
        kw["password"] = getpass.getpass(f"{args.user}@{args.host} 的密码: ")

    print(f"→ 连接 {args.user}@{args.host}:{args.port} …")
    cli.connect(**kw)
    print("  ✅ 已连接")
    return cli


def run_stream(cli: paramiko.SSHClient, cmd: str, label: str = "") -> int:
    """执行远端命令并实时打印输出。

    用低层 channel 而不是 exec_command 的 file 对象 —— 训练要跑十几分钟，
    必须边跑边看，不能等结束才一次性吐出。
    """
    if label:
        print(f"\n{'=' * 62}\n{label}\n{'=' * 62}")
    print(f"$ {cmd}\n", flush=True)

    chan = cli.get_transport().open_session()
    chan.get_pty()                     # 分配伪终端：否则很多工具会因非 tty 而关闭缓冲
    chan.exec_command(cmd)

    while True:
        if chan.recv_ready():
            data = chan.recv(65536)
            sys.stdout.write(data.decode("utf-8", errors="replace"))
            sys.stdout.flush()
        elif chan.exit_status_ready() and not chan.recv_ready():
            break
        else:
            time.sleep(0.2)

    rc = chan.recv_exit_status()
    print(f"\n[退出码 {rc}]", flush=True)
    return rc


def do_upload(cli: paramiko.SSHClient, local_root: Path, remote_dir: str) -> None:
    """把训练所需文件上传到远端（自动建目录）。"""
    print(f"\n→ 上传到 {remote_dir}")
    sftp = cli.open_sftp()

    def mkdirs(path: str) -> None:
        parts, cur = [p for p in path.split("/") if p], ""
        for p in parts:
            cur = f"{cur}/{p}"
            try:
                sftp.stat(cur)
            except IOError:
                sftp.mkdir(cur)

    mkdirs(posixpath.join(remote_dir, "sft_data"))

    total = 0
    for rel in UPLOAD_FILES:
        src = local_root / rel
        if not src.exists():
            raise SystemExit(f"❌ 本机缺少 {src} —— 请先确认训练数据已生成")
        # rel 形如 "bench/cloud_train.sh" / "bench/sft_data/train.json"，
        # 去掉前缀保持远端目录结构与本机一致
        sub = rel[len("bench/"):] if rel.startswith("bench/") else rel
        dst = posixpath.join(remote_dir, sub)
        sftp.put(str(src), dst)
        size = src.stat().st_size
        total += size
        print(f"  ✅ {rel}  ({size / 1024:.0f} KB)")
    sftp.close()
    print(f"  合计 {total / 1024:.0f} KB")


def do_fetch(cli: paramiko.SSHClient, remote_dir: str, local_out: Path) -> Path:
    """把产物 tar.gz 拉回本机。"""
    remote_path = posixpath.join(remote_dir, REMOTE_ARTIFACT)
    local_out.parent.mkdir(parents=True, exist_ok=True)
    print(f"\n→ 下载 {remote_path}  →  {local_out}")
    sftp = cli.open_sftp()
    sftp.get(remote_path, str(local_out))
    sftp.close()
    mb = local_out.stat().st_size / 1024 / 1024
    print(f"  ✅ 已保存（{mb:.1f} MB）")
    return local_out


def main() -> None:
    ap = argparse.ArgumentParser(description="云端 GPU 训练远程控制")
    ap.add_argument("--host", required=True, help="SSH 主机（如 region-1.autodl.com）")
    ap.add_argument("--port", type=int, required=True, help="SSH 端口")
    ap.add_argument("--user", default="root")
    ap.add_argument("--key", default="", help="私钥路径（与密码二选一）")
    # 默认放数据盘：AutoDL 的系统盘只有约 30 GB，装不下 8.8 GB 模型 + 依赖，
    # 而 /root/autodl-tmp 是 50 GB 独立数据盘。非 AutoDL 平台请用 --remote-dir 覆盖。
    ap.add_argument(
        "--remote-dir",
        default="/root/autodl-tmp/geoagent_train/bench",
        help="远端工作目录（务必落在数据盘，系统盘通常只有 30 GB）",
    )
    ap.add_argument("--local-out", default="bench/geoagent_lora.tar.gz")
    ap.add_argument("--epochs", default="2")
    ap.add_argument("--model", default="Qwen/Qwen3.5-4B")
    ap.add_argument(
        "--action", choices=["all", "upload", "train", "fetch"], default="all"
    )
    args = ap.parse_args()

    local_root = Path(__file__).resolve().parent.parent
    remote_dir = args.remote_dir

    cli = connect(args)
    try:
        if args.action in ("all", "upload"):
            do_upload(cli, local_root, remote_dir)

        if args.action in ("all", "train"):
            # 远端 home 里的 ~ 不会被 shell 展开到 exec_command（非交互），
            # 交给 shell 处理：整条命令再套一层 bash -lc
            cmd = (
                f"bash -lc 'cd {remote_dir} && "
                f"bash cloud_train.sh {args.model} {args.epochs}'"
            )
            run_stream(cli, cmd, "云端训练（预计 5–15 分钟，取决于显卡）")

        if args.action in ("all", "fetch"):
            do_fetch(cli, remote_dir, local_root / args.local_out)
            print(
                "\n⚠ 训练已结束，请到云平台控制台【关机】—— 按量计费按开机时长算。"
            )
    finally:
        cli.close()


if __name__ == "__main__":
    main()
