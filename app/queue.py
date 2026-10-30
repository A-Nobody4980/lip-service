"""A simple one-at-a-time job queue. State lives in state/queue.json so it survives a restart."""
import dataclasses
import json
import threading
import time
import uuid
from pathlib import Path

from .presets import PRESETS
from .runner import JobSpec, run_job

STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "queue.json"


class JobQueue:
    def __init__(self, run_fn=run_job, state_file: Path = STATE_FILE, comfy=None, proxy=None):
        self.run_fn = run_fn
        self.restarting = False  # true while ComfyUI is being restarted between renders
        self.proxy = proxy  # the comfy-api-proxy: started before a job if it is down
        self.comfy = comfy  # a ComfyManager: started before a job, restarted after it to free memory
        self.state_file = Path(state_file)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.jobs: list[dict] = []
        self._load()
        threading.Thread(target=self._worker, daemon=True).start()

    # persistence
    def _load(self):
        if self.state_file.exists():
            self.jobs = json.loads(self.state_file.read_text(encoding="utf-8"))
        for j in self.jobs:
            if j["status"] == "running":
                j["status"] = "failed"
                j["error"] = "interrupted by a restart"
        self._save()

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.jobs, indent=1), encoding="utf-8")

    # public
    def add(self, **fields) -> str:
        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        preset = fields.pop("preset_name", "baseline")
        job = {"id": job_id, "status": "queued", "preset": preset, "spec": fields,
               "added": time.time(), "log": [], "result": None, "error": None}
        with self.lock:
            self.jobs.append(job)
            self._save()
        self.wake.set()
        return job_id

    def cancel(self, job_id: str) -> bool:
        with self.lock:
            for j in self.jobs:
                if j["id"] == job_id and j["status"] == "queued":
                    j["status"] = "cancelled"
                    self._save()
                    return True
        return False

    def remove(self, job_id: str) -> bool:
        """Takes one row out of the list. A queued row is cancelled and removed. A running row cannot be removed.
        Only the row goes: the finished video file is never touched."""
        with self.lock:
            for j in self.jobs:
                if j["id"] == job_id:
                    if j["status"] == "running":
                        return False
                    self.jobs.remove(j)
                    self._save()
                    return True
        return False

    def clear_finished(self) -> int:
        """Removes every done, failed and cancelled row. Queued and running rows stay. Returns how many went."""
        with self.lock:
            keep = [j for j in self.jobs if j["status"] in ("queued", "running")]
            removed = len(self.jobs) - len(keep)
            if removed:
                self.jobs[:] = keep
                self._save()
            return removed

    def snapshot(self) -> list[dict]:
        with self.lock:
            return json.loads(json.dumps(self.jobs))

    # worker
    def _next(self):
        with self.lock:
            for j in self.jobs:
                if j["status"] == "queued":
                    j["status"] = "running"
                    j["started"] = time.time()
                    self._save()
                    return j
        return None

    def _worker(self):
        while True:
            job = self._next()
            if job is None:
                self.wake.wait(timeout=2)
                self.wake.clear()
                continue
            log = lambda msg, j=job: self._log(j, msg)
            try:
                if self.comfy:
                    log("making sure ComfyUI is running")
                    self.comfy.ensure_up()
                if self.proxy:
                    log("making sure the proxy is running")
                    self.proxy.ensure_up()
                spec = JobSpec(job_id=job["id"], preset=PRESETS[job["preset"]], **job["spec"])
                result = self.run_fn(spec, log=log)
                with self.lock:
                    job["status"], job["result"] = "done", str(result)
            except Exception as e:  # keep the queue moving
                with self.lock:
                    job["status"], job["error"] = "failed", f"{type(e).__name__}: {e}"
            if self.comfy:
                self.restarting = True
                try:
                    log("restarting ComfyUI to free memory")
                    self.comfy.restart()
                    log("ComfyUI restarted")
                except Exception as e:
                    log(f"ComfyUI restart failed: {type(e).__name__}: {e}")
                finally:
                    self.restarting = False
            with self.lock:
                job["finished"] = time.time()
                self._save()

    def _log(self, job, msg):
        with self.lock:
            job["log"].append(msg)
            self._save()
