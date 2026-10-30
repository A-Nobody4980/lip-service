"""Plumbing test: 2 singers, same vocal, through the app's own queue and runner (real ComfyUI and proxy).
Run: python -I tools/app_multi_test.py <picture> <vocal.wav>
The two marked faces below are the first two people of the TownChoir1 test picture; change the numbers for another."""
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from app.comfy_proc import ComfyManager, ProxyManager
from app.queue import JobQueue

SHOT, VOCAL = sys.argv[1], sys.argv[2]  # a picture with a few people in it, and a vocal

q = JobQueue(state_file=PROJECT / "state" / "test_queue.json", comfy=ComfyManager(), proxy=ProxyManager())
job_id = q.add(shot=SHOT, audio=VOCAL, audio_start=0.5, audio_end=0.5 + 81 / 25, seconds=3.24,
               prompt="two people in colonial market clothes sing together, mouths open, expressive faces",
               singers=[{"x": 635 / 1376, "y": 235 / 768, "r": 0.026}, {"x": 830 / 1376, "y": 300 / 768, "r": 0.020}],
               unison=True, preset_name="baseline")
print("queued", job_id, flush=True)
while True:
    job = next(j for j in q.snapshot() if j["id"] == job_id)
    if job["status"] in ("done", "failed"):
        break
    time.sleep(5)
print("status", job["status"], "| result", job["result"], "| error", job["error"], flush=True)
for line in job["log"]:
    print(" log:", line, flush=True)
# let the post-job ComfyUI restart finish before exiting
while q.restarting:
    time.sleep(2)
time.sleep(3)
print("finished", flush=True)
