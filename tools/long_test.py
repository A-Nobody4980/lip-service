"""Long single job test: one shot, a 12 s vocal segment, baseline preset, one ComfyUI job.

Uses the app's workflow builder and audio code, submits straight to ComfyUI (no proxy),
samples GPU memory, then trims to the audio and muxes the original audio into outputs.
Run: python -I tools/long_test.py
"""
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from app.media import cut_audio_to_wav, mux_original_audio
from app.presets import BASELINE
from app.workflow import TEMPLATE, build_single

HOST = "http://127.0.0.1:8188"
COMFY = Path(r"D:\Comfy-Desktop\ComfyUI-Shared")
JOB = "long_test_12s"
START_S, END_S = 6.0, 18.0

peak = {"mb": 0}
stop = threading.Event()


def sample_vram():
    while not stop.is_set():
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True).stdout.strip()
        try:
            peak["mb"] = max(peak["mb"], int(out.splitlines()[0]))
        except (ValueError, IndexError):
            pass
        time.sleep(2)


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def main():
    seg = PROJECT / "outputs" / "jobs" / JOB
    seg.mkdir(parents=True, exist_ok=True)
    original = seg / "original_audio.wav"
    dur = cut_audio_to_wav(str(PROJECT / "inputs" / "RingTheBell.wav"), str(original), START_S, END_S)
    shutil.copyfile(PROJECT / "inputs" / "shot_01.webp", COMFY / "input" / f"lipservice_{JOB}_shot.webp")
    shutil.copyfile(original, COMFY / "input" / f"lipservice_{JOB}_audio.wav")
    base = json.loads(Path(TEMPLATE).read_text(encoding="utf-8-sig"))
    wf = build_single(f"lipservice_{JOB}_shot.webp", f"lipservice_{JOB}_audio.wav", dur,
                      f"lipservice/{JOB}", BASELINE, prompt=base["13"]["inputs"]["positive_prompt"],
                      negative_prompt=base["13"]["inputs"]["negative_prompt"])
    threading.Thread(target=sample_vram, daemon=True).start()
    t0 = time.time()
    pid = call("/prompt", {"prompt": wf})["prompt_id"]
    print("submitted", pid, "audio seconds", round(dur, 2), flush=True)
    while pid not in (hist := call("/history/" + pid)):
        time.sleep(5)
    stop.set()
    entry = hist[pid]
    status = entry["status"].get("status_str")
    print("status", status, "seconds", round(time.time() - t0), "peak VRAM MB", peak["mb"], flush=True)
    if status != "success":
        print(json.dumps(entry["status"].get("messages", []), indent=1)[:3000])
        sys.exit(1)
    video = max((COMFY / "output" / "lipservice").glob(f"{JOB}*.mp4"), key=lambda p: p.stat().st_mtime)
    final = PROJECT / "outputs" / f"{JOB}.mp4"
    mux_original_audio(str(video), str(original), str(final))
    print("done", final, flush=True)


main()
