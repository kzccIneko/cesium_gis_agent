"""Debug: start uvicorn, call classify, capture all output."""
import subprocess, time, json, urllib.request, sys, os

os.chdir(os.path.join(os.path.dirname(__file__), "..", "backend"))
proc = subprocess.Popen(
    [".venv/Scripts/python.exe", "-m", "uvicorn", "app.main:app",
     "--host", "127.0.0.1", "--port", "8006", "--log-level", "debug"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)

# Wait for startup
for _ in range(100):
    time.sleep(0.3)
    line = proc.stderr.readline()
    print("[SRV]", line.decode("utf-8", errors="replace").rstrip())
    if b"Uvicorn running" in line:
        break

# Send request
body = json.dumps({
    "bbox": {"west": 113.3, "south": 22.9, "east": 113.35, "north": 22.95},
    "resolution": 60,
    "output_formats": ["geojson"]
}).encode()

req = urllib.request.Request(
    "http://127.0.0.1:8006/api/v1/analyze/classify",
    data=body, headers={"Content-Type": "application/json"}
)

try:
    resp = urllib.request.urlopen(req, timeout=30)
    print("HTTP", resp.status)
    print(json.loads(resp.read()))
except urllib.error.HTTPError as e:
    print("HTTP ERROR", e.code)
    # Read all remaining stderr
    time.sleep(1)
    remaining = proc.stderr.read()
    print("STDERR:", remaining.decode("utf-8", errors="replace"))
except Exception as e:
    print("EXCEPTION:", e)
finally:
    proc.terminate()
    proc.wait(timeout=5)
