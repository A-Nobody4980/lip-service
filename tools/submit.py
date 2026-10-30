"""Submit API-format workflows to local ComfyUI in order, wait for each, and copy the video into outputs.

ComfyUI always writes to its own output folder. The copy into D:\\Project_lip_service\\outputs is what
puts every test render where the project owner expects it. Name: the workflow file name without _api.json.
"""
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = "http://127.0.0.1:8188"
COMFY_OUTPUT = Path(r"D:\Comfy-Desktop\ComfyUI-Shared\output")
OUTPUTS = Path(r"D:\Project_lip_service\outputs")


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def copy_videos(entry, name):
    for out in entry.get("outputs", {}).values():
        for item in out.get("gifs", []):
            src = COMFY_OUTPUT / item.get("subfolder", "") / item["filename"]
            if src.suffix == ".mp4":
                dst = OUTPUTS / (name + src.suffix)
                shutil.copy2(src, dst)
                print("copied", dst)


def main():
    ids = []
    for path in sys.argv[1:]:
        wf = json.load(open(path, encoding="utf-8-sig"))
        try:
            ids.append((call("/prompt", {"prompt": wf})["prompt_id"], Path(path).name.replace("_api.json", "")))
            print(path, ids[-1][0])
        except urllib.error.HTTPError as e:
            print(path, "REJECTED", e.code, e.read().decode()[:2500])
            sys.exit(1)
    for pid, name in ids:
        while True:
            hist = call("/history/" + pid)
            if pid in hist:
                break
            time.sleep(5)
        status = hist[pid]["status"].get("status_str")
        print(name, status)
        if status == "success":
            copy_videos(hist[pid], name)


main()
