"""Vocal isolation test with a real full mix and the song's own lead vocal stem.

1. Picks a 3.24 s window where the lead vocal and the rest of the band are both loud.
2. Runs only the MelBandRoFormer nodes on the mix window and compares the two outputs with the real stem.
3. Renders one shot through the app's queue with "Isolate the vocal" on, using the full mix as the audio.

Usage: python -I tools/isolation_test.py <full_mix.wav> <lead_vocal_stem.wav> <shot image>
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import av
import numpy as np

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from app.comfy_proc import ComfyManager, ProxyManager
from app.media import cut_audio_to_wav
from app.queue import JobQueue
from app.workflow import MELBAND_MODEL

MIX, STEM, SHOT = sys.argv[1:4]
COMFY = Path(r"D:\Comfy-Desktop\ComfyUI-Shared")
HOST = "http://127.0.0.1:8188"
SECONDS = 3.24
SP = Path(r"D:\Cache\temp\iso_test")
SP.mkdir(parents=True, exist_ok=True)


def mono8k(path):
    r = av.AudioResampler(format="s16", layout="mono", rate=8000)
    out = []
    with av.open(path) as c:
        for f in c.decode(audio=0):
            for rf in r.resample(f):
                out.append(rf.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32)


def call(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + path, data=data, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def corr(a, b):
    n = min(len(a), len(b))
    a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def main():
    print("reading mix and stem...", flush=True)
    mix, lead = mono8k(MIX), mono8k(STEM)
    n = min(len(mix), len(lead))
    mix, lead = mix[:n], lead[:n]
    other = mix - lead
    win, hop = int(SECONDS * 8000), 4000
    best, start = -1.0, 0
    for i in range(8000 * 5, n - win, hop):
        score = min(np.sqrt((lead[i:i + win] ** 2).mean()), np.sqrt((other[i:i + win] ** 2).mean()))
        if score > best:
            best, start = score, i
    t0 = start / 8000
    print(f"chosen window {t0:.2f} s to {t0 + SECONDS:.2f} s", flush=True)

    mix_clip = COMFY / "input" / "lipservice_iso_mix.wav"
    cut_audio_to_wav(MIX, str(mix_clip), t0, t0 + SECONDS)
    cut_audio_to_wav(STEM, str(SP / "stem.wav"), t0, t0 + SECONDS)
    ref = mono8k(str(SP / "stem.wav"))
    mixc = mono8k(str(mix_clip))

    comfy, proxy = ComfyManager(), ProxyManager()
    comfy.ensure_up()
    wf = {
        "1": {"class_type": "LoadAudio", "inputs": {"audio": "lipservice_iso_mix.wav"}},
        "2": {"class_type": "MelBandRoFormerModelLoader", "inputs": {"model_name": MELBAND_MODEL}},
        "3": {"class_type": "MelBandRoFormerSampler", "inputs": {"model": ["2", 0], "audio": ["1", 0]}},
        "4": {"class_type": "SaveAudio", "inputs": {"audio": ["3", 0], "filename_prefix": "lipservice/iso_out0"}},
        "5": {"class_type": "SaveAudio", "inputs": {"audio": ["3", 1], "filename_prefix": "lipservice/iso_out1"}},
    }
    pid = call("/prompt", {"prompt": wf})["prompt_id"]
    while pid not in (hist := call("/history/" + pid)):
        time.sleep(3)
    entry = hist[pid]
    print("isolation only:", entry["status"].get("status_str"), flush=True)
    if entry["status"].get("status_str") != "success":
        print(json.dumps(entry["status"].get("messages", []))[:1500])
        return
    files = {}
    for node, out in entry["outputs"].items():
        for a in out.get("audio", []):
            files[node] = COMFY / "output" / a.get("subfolder", "") / a["filename"]
    o0, o1 = mono8k(str(files["4"])), mono8k(str(files["5"]))
    print(f"correlation with the real lead vocal stem:  mix {corr(mixc, ref):.2f} | output 1 {corr(o0, ref):.2f} | output 2 {corr(o1, ref):.2f}", flush=True)
    rms = lambda x: float(np.sqrt((x ** 2).mean()))
    print(f"loudness (rms): stem {rms(ref):.0f} | mix {rms(mixc):.0f} | output 1 {rms(o0):.0f} | output 2 {rms(o1):.0f}", flush=True)

    print("rendering through the app with isolation ON...", flush=True)
    q = JobQueue(state_file=PROJECT / "state" / "test_queue.json", comfy=comfy, proxy=proxy)
    job_id = q.add(shot=SHOT, audio=MIX, audio_start=t0, audio_end=t0 + SECONDS, seconds=SECONDS,
                   prompt="a woman in a black hooded cloak sings with raw emotion in a colonial market square",
                   isolate_vocals=True, preset_name="baseline")
    while True:
        job = next(j for j in q.snapshot() if j["id"] == job_id)
        if job["status"] in ("done", "failed"):
            break
        time.sleep(5)
    print("status", job["status"], "| result", job["result"], "| error", job["error"], flush=True)
    for line in job["log"]:
        print(" log:", line, flush=True)
    while q.restarting:
        time.sleep(2)
    time.sleep(3)
    print("finished", flush=True)


main()
