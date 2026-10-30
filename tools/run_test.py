"""Quick test runner: submit an API-format workflow to local ComfyUI, time it, sample GPU memory.

Usage: python -I tools/run_test.py workflows/baseline_single_api.json
This is a test harness, not the comfy-sdk runner (plan step 5).
"""
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HOST = "http://127.0.0.1:8188"
COMFY_OUTPUT = Path(r"D:\Comfy-Desktop\ComfyUI-Shared\output")
OUTPUTS = Path(r"D:\Project_lip_service\outputs")
peak = {"mb": 0}
stop = threading.Event()


def sample_vram():
    while not stop.is_set():
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True,
        ).stdout.strip()
        try:
            peak["mb"] = max(peak["mb"], int(out.splitlines()[0]))
        except (ValueError, IndexError):
            pass
        time.sleep(1.5)


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data, headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req))
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, e.read().decode()[:3000])
        sys.exit(1)


def main():
    workflow = json.load(open(sys.argv[1], encoding="utf-8-sig"))
    threading.Thread(target=sample_vram, daemon=True).start()
    start = time.time()
    pid = call("/prompt", {"prompt": workflow})["prompt_id"]
    print("submitted", pid)
    while True:
        hist = call("/history/" + pid)
        if pid in hist:
            break
        time.sleep(3)
    stop.set()
    entry = hist[pid]
    print("status:", entry["status"].get("status_str"), "| seconds:", round(time.time() - start, 1),
          "| peak VRAM MB (whole GPU):", peak["mb"])
    for m in entry["status"].get("messages", []):
        if m[0] == "execution_error":
            print(json.dumps(m[1], indent=1)[:3000])
    for node, out in entry.get("outputs", {}).items():
        print(node, json.dumps(out)[:400])
        for item in out.get("gifs", []):
            src = COMFY_OUTPUT / item.get("subfolder", "") / item["filename"]
            if src.suffix == ".mp4":
                dst = OUTPUTS / (sys.argv[1].replace("\\", "/").split("/")[-1].replace("_api.json", "") + ".mp4")
                shutil.copy2(src, dst)
                print("copied", dst)
    if entry["status"].get("status_str") != "success":
        sys.exit(1)


main()
