"""Fast and Best on a 3.24 s clip through the app's own queue (real ComfyUI and proxy), one after the other.
Prints, for each: wall time, the render time the runner logged, peak GPU memory, lowest free RAM, ComfyUI's peak RAM.
Usage: python -I tools/quality_test.py [fast] [best]   (default: both)"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from app.comfy_proc import ComfyManager, ProxyManager
from app.queue import JobQueue
from app.workflow import TEMPLATE

SHOT = str(PROJECT / "inputs" / "shot_01.webp")
AUDIO = str(PROJECT / "inputs" / "RingTheBell.wav")
PROMPT = json.loads(Path(TEMPLATE).read_text(encoding="utf-8-sig"))["13"]["inputs"]["positive_prompt"]
modes = sys.argv[1:] or ["fast", "best"]


def comfy_rss_gb():
    best = 0.0
    for c in psutil.net_connections(kind="tcp"):
        if c.laddr and c.laddr.port == 8188 and c.status == "LISTEN" and c.pid:
            try:
                best = max(best, psutil.Process(c.pid).memory_info().rss / 1e9)
            except psutil.Error:
                pass
    return best


def sample(stats, stop):
    while not stop.is_set():
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout.split()[0]
            stats["vram_mb"] = max(stats["vram_mb"], int(out))
        except Exception:
            pass
        stats["min_free_ram_gb"] = min(stats["min_free_ram_gb"], psutil.virtual_memory().available / 1e9)
        stats["comfy_rss_gb"] = max(stats["comfy_rss_gb"], comfy_rss_gb())
        time.sleep(3)


comfy, proxy = ComfyManager(), ProxyManager()
q = JobQueue(state_file=PROJECT / "state" / "test_queue.json", comfy=comfy, proxy=proxy)
for mode in modes:
    stats = {"vram_mb": 0, "min_free_ram_gb": 999.0, "comfy_rss_gb": 0.0}
    stop = threading.Event()
    threading.Thread(target=sample, args=(stats, stop), daemon=True).start()
    t0 = time.time()
    job_id = q.add(shot=SHOT, audio=AUDIO, audio_start=6.0, audio_end=6.0 + 81 / 25, seconds=3.24, prompt=PROMPT,
                   preset_name=mode)
    print(f"[{mode}] queued {job_id}", flush=True)
    while True:
        job = next(j for j in q.snapshot() if j["id"] == job_id)
        if job["status"] in ("done", "failed"):
            break
        time.sleep(5)
    wall = time.time() - t0
    stop.set()
    logs = [l for l in job["log"] if "quality" in l or "render status" in l or "warning" in l]
    print(f"[{mode}] {job['status']} in {wall:.0f} s | result {job['result']} | error {job['error']}", flush=True)
    for l in logs:
        print(f"[{mode}]   {l}", flush=True)
    print(f"[{mode}] peak GPU memory {stats['vram_mb']} MiB | lowest free RAM {stats['min_free_ram_gb']:.1f} GB | "
          f"ComfyUI peak RAM {stats['comfy_rss_gb']:.1f} GB", flush=True)
    while q.restarting:
        time.sleep(2)
    time.sleep(3)
print("finished", flush=True)
