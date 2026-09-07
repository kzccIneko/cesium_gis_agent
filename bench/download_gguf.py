"""Download LLM weights reliably.

Why not plain curl:
  HF's /resolve/ endpoint 302-redirects to a CDN. With `curl -L -C -` the
  byte-range resume silently breaks and every retry restarts from zero -
  we watched the file go 1.26 GB -> 957 MB, i.e. backwards.

Why hf_hub_download:
  - proper resume via .incomplete files
  - honours HF_ENDPOINT so we can use the hf-mirror CDN (much faster from CN)
  - caches outside the repo

Cache dir is forced to D: on purpose - C: has ~14 GB free and a 2.6 GB
model plus cache would risk filling the system disk.
"""

import os
import sys
import time

# Must be set BEFORE importing huggingface_hub
os.environ.setdefault("HF_HOME", r"D:\HF_CACHE")
os.environ.setdefault("HF_HUB_CACHE", r"D:\HF_CACHE\hub")
# China mirror; comment out to use huggingface.co directly
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from huggingface_hub import hf_hub_download  # noqa: E402

REPO_ID = "unsloth/Qwen3.5-4B-GGUF"
FILENAME = "Qwen3.5-4B-Q4_K_M.gguf"
LOCAL_DIR = r"D:\VS_Code_Program\CesiumJS_Debug\models\llm"


def main() -> int:
    print(f"HF_ENDPOINT = {os.environ['HF_ENDPOINT']}")
    print(f"HF_HOME     = {os.environ['HF_HOME']}")
    print(f"target      = {LOCAL_DIR}\\{FILENAME}\n")

    t0 = time.perf_counter()
    path = hf_hub_download(
        repo_id=REPO_ID,
        filename=FILENAME,
        local_dir=LOCAL_DIR,
    )
    dt = time.perf_counter() - t0
    size = os.path.getsize(path)
    print(f"\n[DONE] {path}")
    print(f"       {size / 1024**3:.2f} GiB in {dt/60:.1f} min "
          f"({size / 1024**2 / max(dt, 1):.1f} MB/s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
