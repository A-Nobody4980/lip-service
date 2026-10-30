"""Local API for the Electron screen. The contract is docs/api.md. Bound to 127.0.0.1, token required."""
import json
import os
import secrets
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import av
import numpy as np

from .comfy_proc import ComfyManager, ProxyManager
from .media import audio_duration, cut_audio_to_wav
from .hardware import ram_status
from .presets import ASPECTS, BEST_MODEL, DEFAULT_PRESET, QUALITY_POSITIONS, QUALITY_PRESET, quality_id
from .queue import JobQueue
from .runner import COMFY_ROOT, OUTPUTS
from .workflow import DEFAULT_NEGATIVE, DEFAULT_PROMPT, MAX_SINGERS

HOST, PORT = "127.0.0.1", 8780
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
WARN_SECONDS = 12
DEFAULT_QUALITY = 0.5
MODELS_DIR = COMFY_ROOT / "models" / "diffusion_models" / "WanVideo"


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def model_list():
    models = []
    for p in sorted(MODELS_DIR.glob("*.gguf")):
        models.append({"id": "WanVideo\\" + p.name, "label": p.stem.replace("wan2.1", "Wan 2.1").replace("-", " "),
                       "default": "Q4_K_M" in p.name})
    if models and not any(m["default"] for m in models):
        models[0]["default"] = True
    return models


def audio_peaks(path, bins=500):
    resampler = av.AudioResampler(format="s16", layout="mono", rate=8000)
    chunks = []
    with av.open(str(path)) as c:
        for frame in c.decode(audio=0):
            for rf in resampler.resample(frame):
                chunks.append(rf.to_ndarray().reshape(-1))
    if not chunks:
        return [0.0] * bins
    data = np.abs(np.concatenate(chunks).astype(np.float32))
    edges = np.linspace(0, len(data), bins + 1).astype(int)
    peaks = np.array([data[a:b].max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    top = peaks.max()
    return [round(float(v / top), 3) if top > 0 else 0.0 for v in peaks]


class Api:
    def __init__(self, queue, comfy, proxy, token, outputs=OUTPUTS):
        self.queue, self.comfy, self.proxy, self.token, self.outputs = queue, comfy, proxy, token, Path(outputs)
        # Asking a closed port on Windows can take seconds, so the answers are gathered in the background and
        # /status replies at once. (Asking inside the request made the first launch time out and never open.)
        self._up = {"comfyui": False, "proxy": False}
        threading.Thread(target=self._poll_services, daemon=True).start()

    def _poll_services(self):
        while True:
            self._up = {"comfyui": bool(self.comfy.is_up()), "proxy": bool(self.proxy.is_up())}
            time.sleep(3)

    def ping(self):
        return {"ok": True}

    def status(self):
        jobs = self.queue.snapshot()
        return {"comfyui": self._up["comfyui"], "proxy": self._up["proxy"],
                "restarting": bool(self.queue.restarting), "busy": any(j["status"] == "running" for j in jobs),
                **ram_status()}

    def options(self):
        # Only ratios that work are listed (see presets.ASPECTS), so every button on the screen is live.
        aspects = [{"id": key, "label": key, "width": size["width"], "height": size["height"], "enabled": True,
                    **({"default": True} if key == "16:9" else {})} for key, size in ASPECTS.items()]
        return {"models": model_list(), "aspects": aspects,
                "quality": {"default": DEFAULT_QUALITY, "enabled": True, "positions": self._quality_positions()},
                "limits": {"warn_seconds": WARN_SECONDS}, "max_singers": MAX_SINGERS}

    @staticmethod
    def _best_installed():
        return (MODELS_DIR / BEST_MODEL.split("\\")[-1]).is_file()

    def _quality_positions(self):
        out = []
        for key, value, label in QUALITY_POSITIONS:
            item = {"id": key, "value": value, "label": label, "enabled": True}
            if key == "best" and not self._best_installed():
                item["enabled"] = False
                item["note"] = "The Q6_K base file is not installed (see the README)."
            out.append(item)
        return out

    def audio_info(self, body):
        path = self._file(body.get("path"), "audio")
        return {"duration": round(audio_duration(path), 3), "peaks": audio_peaks(path)}

    def audio_segment(self, query):
        path = self._file(query.get("path", [""])[0], "audio")
        start = float(query.get("start", ["0"])[0] or 0)
        end = float(query.get("end", ["0"])[0] or 0) or None
        tmp = Path(tempfile.mkdtemp(prefix="seg_")) / "segment.wav"
        cut_audio_to_wav(path, str(tmp), start, end)
        return tmp.read_bytes()

    def add_job(self, body):
        shot = self._file(body.get("shot"), "image")
        if Path(shot).suffix.lower() not in IMAGE_TYPES:
            raise ApiError(400, "The shot has to be a png, jpg, webp or bmp image.")
        audio = self._file(body.get("audio"), "audio")
        start = float(body.get("start") or 0)
        end = float(body.get("end") or 0)
        total = audio_duration(audio)
        if start < 0 or (end and end <= start) or start >= total:
            raise ApiError(400, "The audio end has to be after the start.")
        seconds = round((min(end, total) if end else total) - start, 3)
        if seconds < 0.5:
            raise ApiError(400, "Pick at least half a second of audio.")
        aspect = body.get("aspect") or "16:9"
        if aspect not in ASPECTS:
            raise ApiError(400, "That aspect ratio is not available.")
        models = {m["id"]: m for m in model_list()}
        model = body.get("model") or next((m["id"] for m in models.values() if m["default"]), None)
        if model not in models:
            raise ApiError(400, "That model is not in the ComfyUI models folder.")
        raw_quality = body.get("quality")
        quality = quality_id(DEFAULT_QUALITY if raw_quality is None else raw_quality)
        quality_value = {k: v for k, v, _ in QUALITY_POSITIONS}[quality]
        if quality == "best" and not self._best_installed():
            raise ApiError(400, "Best needs the Q6_K base file, and it is not installed.")
        singers = self._singers(body.get("singers") or [])
        unison = body.get("unison", True) is not False
        singer_audios = []
        if singers and not unison:
            singer_audios = [self._file(p, "audio") for p in (body.get("singer_audios") or [])]
            if len(singer_audios) != len(singers):
                raise ApiError(400, "Give one audio track for each marked singer.")
        job_id = self.queue.add(
            shot=shot, audio=audio, audio_start=start, audio_end=end or None,
            prompt=(body.get("prompt") or "").strip() or DEFAULT_PROMPT,
            negative_prompt=(body.get("negative_prompt") or "").strip() or DEFAULT_NEGATIVE,
            isolate_vocals=bool(body.get("isolate_vocals")), aspect=aspect, model=model,
            quality=quality_value, seconds=seconds,
            singers=singers, unison=unison, singer_audios=singer_audios,
            sing_along=bool(body.get("sing_along", False)),
            preset_name=QUALITY_PRESET[quality])
        return {"id": job_id}

    def jobs(self):
        out = []
        for j in reversed(self.queue.snapshot()):
            s = j["spec"]
            began = j.get("started")
            ended = j.get("finished") or time.time()
            out.append({"id": j["id"], "status": j["status"], "added": j["added"], "shot": s.get("shot", ""),
                        "audio": s.get("audio", ""), "seconds": s.get("seconds", 0),
                        "note": j["error"] or (j["log"][-1] if j["log"] else ""), "result": j["result"],
                        "elapsed": round(ended - began, 1) if began else 0})
        return {"jobs": out}

    def cancel(self, job_id):
        if not self.queue.cancel(job_id):
            raise ApiError(409, "Only a queued job can be cancelled.")
        return {"ok": True}

    def remove(self, job_id):
        if not self.queue.remove(job_id):
            raise ApiError(409, "That job is running or does not exist, so it cannot be removed.")
        return {"ok": True}

    def clear(self):
        return {"removed": self.queue.clear_finished()}

    def open_folder(self, body):
        path = Path(str(body.get("path") or "")).resolve()
        if not (path == self.outputs.resolve() or self.outputs.resolve() in path.parents):
            raise ApiError(400, "Only the outputs folder can be opened.")
        folder = path if path.is_dir() else path.parent
        os.startfile(str(folder))
        return {"ok": True}

    @staticmethod
    def _singers(raw):
        if len(raw) > MAX_SINGERS:
            raise ApiError(400, f"Up to {MAX_SINGERS} singers.")
        out = []
        for s in raw:
            try:
                x, y, r = float(s["x"]), float(s["y"]), float(s["r"])
            except (KeyError, TypeError, ValueError):
                raise ApiError(400, "Each singer needs x, y and r.")
            if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < r <= 0.5):
                raise ApiError(400, "A marked face is outside the picture.")
            out.append({"x": x, "y": y, "r": r})
        return out

    @staticmethod
    def _file(value, kind):
        p = Path(str(value or ""))
        if not value or not p.is_absolute() or not p.is_file():
            raise ApiError(400, f"The {kind} file was not found.")
        return str(p)


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # no request logging to the console
            pass

        def _send(self, status, payload, ctype="application/json"):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Access-Control-Allow-Headers", "X-Lip-Token, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self._send(204, b"")

        def _handle(self, method):
            try:
                if not secrets.compare_digest(self.headers.get("X-Lip-Token", ""), api.token):
                    raise ApiError(401, "bad token")
                url = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(url.query)
                body = {}
                if method == "POST":
                    length = int(self.headers.get("Content-Length") or 0)
                    body = json.loads(self.rfile.read(length) or b"{}")
                route = (method, url.path)
                if route == ("GET", "/ping"):
                    return self._send(200, api.ping())
                if route == ("GET", "/status"):
                    return self._send(200, api.status())
                if route == ("GET", "/options"):
                    return self._send(200, api.options())
                if route == ("POST", "/audio/info"):
                    return self._send(200, api.audio_info(body))
                if route == ("GET", "/audio/segment"):
                    return self._send(200, api.audio_segment(query), "audio/wav")
                if route == ("POST", "/jobs"):
                    return self._send(200, api.add_job(body))
                if route == ("GET", "/jobs"):
                    return self._send(200, api.jobs())
                if route == ("POST", "/jobs/clear"):
                    return self._send(200, api.clear())
                if method == "POST" and url.path.startswith("/jobs/") and url.path.endswith("/remove"):
                    return self._send(200, api.remove(url.path[len("/jobs/"):-len("/remove")]))
                if method == "POST" and url.path.startswith("/jobs/") and url.path.endswith("/cancel"):
                    return self._send(200, api.cancel(url.path[len("/jobs/"):-len("/cancel")]))
                if route == ("POST", "/open-folder"):
                    return self._send(200, api.open_folder(body))
                raise ApiError(404, "not found")
            except ApiError as e:
                self._send(e.status, {"error": e.message})
            except json.JSONDecodeError:
                self._send(400, {"error": "The request was not valid JSON."})
            except Exception as e:  # never leak a traceback to the page
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


def serve(queue, comfy, proxy, token, host=HOST, port=PORT):
    server = ThreadingHTTPServer((host, port), make_handler(Api(queue, comfy, proxy, token)))
    return server


def main():
    token = os.environ.get("LIPSERVICE_TOKEN")
    if not token:
        raise SystemExit("Set LIPSERVICE_TOKEN first. The screen and the backend must share it.")
    comfy, proxy = ComfyManager(), ProxyManager()
    queue = JobQueue(comfy=comfy, proxy=proxy)
    server = serve(queue, comfy, proxy, token, port=int(os.environ.get("LIPSERVICE_PORT", PORT)))
    port = int(os.environ.get("LIPSERVICE_PORT", PORT))
    print(f"Lip Service backend on http://{HOST}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
