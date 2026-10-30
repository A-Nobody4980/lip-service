"""One Fast render per aspect ratio through the app's own queue (real ComfyUI and proxy), 3.24 s each.
Prints for each ratio: done or failed, wall time, output size and frame count, peak GPU memory, lowest free RAM.
Usage: python -I tools/aspect_test.py 9:16 1:1 4:3"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import av
import psutil

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from app.comfy_proc import ComfyManager, ProxyManager
from app.presets import ASPECTS
from app.queue import JobQueue
from app.workflow import TEMPLATE

SHOT = str(PROJECT / "inputs" / "shot_01.webp")
AUDIO = str(PROJECT / "inputs" / "RingTheBell.wav")
PROMPT = json.loads(Path(TEMPLATE).read_text(encoding="utf-8-sig"))["13"]["inputs"]["positive_prompt"]


def sample(stats, stop):
    while not stop.is_set():
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout.split()[0]
            stats["vram_mb"] = max(stats["vram_mb"], int(out))
        except Exception:
            pass
        stats["min_free_ram_gb"] = min(stats["min_free_ram_gb"], psutil.virtual_memory().available / 1e9)
        time.sleep(3)


q = JobQueue(state_file=PROJECT / "state" / "test_queue.json", comfy=ComfyManager(), proxy=ProxyManager())
for ratio in sys.argv[1:]:
    stats = {"vram_mb": 0, "min_free_ram_gb": 999.0}
    stop = threading.Event()
    threading.Thread(target=sample, args=(stats, stop), daemon=True).start()
    t0 = time.time()
    job_id = q.add(shot=SHOT, audio=AUDIO, audio_start=6.0, audio_end=6.0 + 81 / 25, seconds=3.24, prompt=PROMPT,
                   preset_name="fast", aspect=ratio)
    print(f"[{ratio}] queued {job_id}, expected {ASPECTS[ratio]}", flush=True)
    while True:
        job = next(j for j in q.snapshot() if j["id"] == job_id)
        if job["status"] in ("done", "failed"):
            break
        time.sleep(5)
    stop.set()
    info = ""
    if job["status"] == "done":
        with av.open(job["result"]) as c:
            v = c.streams.video[0]
            info = f"{v.width}x{v.height}, {v.frames} frames, audio streams {len(c.streams.audio)}"
    print(f"[{ratio}] {job['status']} in {time.time() - t0:.0f} s | {info} | result {job['result']} | error {job['error']}", flush=True)
    for line in job["log"]:
        if "quality" in line or "render status" in line or "notice" in line:
            print(f"[{ratio}]   {line}", flush=True)
    print(f"[{ratio}] peak GPU memory {stats['vram_mb']} MiB | lowest free RAM {stats['min_free_ram_gb']:.1f} GB", flush=True)
    while q.restarting:
        time.sleep(2)
    time.sleep(3)
print("finished", flush=True)
