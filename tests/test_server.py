import json
import threading
import time
import urllib.error
import urllib.request
import wave

import pytest

from app.queue import JobQueue
from app.server import serve

PORT = 8792
TOKEN = "t0ken"


class FakeMgr:
    def __init__(self, up=True): self.up = up
    def is_up(self): return self.up
    def ensure_up(self): pass
    def restart(self): pass


@pytest.fixture()
def api(tmp_path):
    def fake_run(spec, log):
        log("fake render")
        time.sleep(0.3)
        return str(tmp_path / "x.mp4")

    q = JobQueue(run_fn=fake_run, state_file=tmp_path / "q.json", comfy=FakeMgr(), proxy=FakeMgr())
    server = serve(q, FakeMgr(), FakeMgr(False), TOKEN, port=PORT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield q
    server.shutdown()


def call(method, path, body=None, token=TOKEN):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Lip-Token": token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if r.headers["Content-Type"] == "application/json" else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_token_required(api):
    assert call("GET", "/status", token="wrong")[0] == 401


def test_status_and_options(api):
    for _ in range(40):  # the service check runs in the background; give it a moment
        s = call("GET", "/status")[1]
        if s["comfyui"]:
            break
        time.sleep(0.1)
    flags = {k: s[k] for k in ("comfyui", "proxy", "restarting", "busy")}
    assert flags == {"comfyui": True, "proxy": False, "restarting": False, "busy": False}
    assert {"ram_free_gb", "ram_needed_gb", "ram_ok"} <= set(s)
    o = call("GET", "/options")[1]
    assert any(m["default"] for m in o["models"]) and o["max_singers"] == 4
    a = {x["id"]: x for x in o["aspects"]}
    assert set(a) == {"16:9", "9:16", "1:1", "4:3"} and all(x["enabled"] for x in a.values())  # no dimmed buttons
    assert (a["4:3"]["width"], a["4:3"]["height"]) == (704, 528) and a["16:9"]["default"]
    assert o["quality"]["enabled"] is True and o["quality"]["default"] == 0.5 and o["limits"]["warn_seconds"] == 12


def test_audio_info_and_segment(api, sample_wav):
    info = call("POST", "/audio/info", {"path": sample_wav})[1]
    assert abs(info["duration"] - 20.0) < 0.1 and len(info["peaks"]) == 500 and max(info["peaks"]) == 1.0
    status, data = call("GET", f"/audio/segment?path={urllib.request.quote(sample_wav)}&start=1&end=3.5")
    assert status == 200 and data[:4] == b"RIFF"


def test_job_flow_and_errors(api, sample_wav, sample_shot):
    body = {"shot": sample_shot, "audio": sample_wav, "start": 6, "end": 9.24, "prompt": "p", "aspect": "16:9"}
    status, out = call("POST", "/jobs", body)
    assert status == 200
    for _ in range(50):
        jobs = call("GET", "/jobs")[1]["jobs"]
        if jobs[0]["status"] == "done":
            break
        time.sleep(0.1)
    j = jobs[0]
    assert j["status"] == "done" and abs(j["seconds"] - 3.24) < 0.01 and j["result"].endswith("x.mp4")
    assert call("POST", "/jobs", {**body, "end": 5})[0] == 400                       # end before start
    assert call("POST", "/jobs", {**body, "shot": r"D:\nope.png"})[0] == 400         # missing file
    assert call("POST", "/jobs", {**body, "aspect": "21:9"})[0] == 400               # not enabled
    assert call("POST", "/jobs", {**body, "singers": [{"x": 2, "y": .5, "r": .05}]})[0] == 400   # outside the image
    assert call("POST", "/jobs", {**body, "singers": [{"x": .5, "y": .5, "r": .05}] * 5})[0] == 400  # too many
    assert call("POST", "/jobs", {**body, "unison": False,
                                  "singers": [{"x": .5, "y": .5, "r": .05}] * 2, "singer_audios": [sample_wav]})[0] == 400
    ok = call("POST", "/jobs", {**body, "singers": [{"x": .4, "y": .3, "r": .05}, {"x": .6, "y": .3, "r": .05}]})
    assert ok[0] == 200
    assert call("POST", "/jobs/nope/cancel")[0] == 409


def test_open_folder_only_outputs(api):
    assert call("POST", "/open-folder", {"path": r"C:\Windows"})[0] == 400


def test_wait_for_job_survives_proxy_timeouts():
    import httpx
    from app.runner import wait_for_job

    class Job:
        def __init__(self): self.calls = 0
        def wait(self, timeout=None):
            self.calls += 1
            if self.calls == 1: raise httpx.ReadTimeout("timed out")
            if self.calls == 2: raise TimeoutError("still running")
            return self

    import app.runner as r
    r.time_sleep = None
    j = Job()
    assert wait_for_job(j, log=lambda m: None) is j and j.calls == 3


def test_status_and_ping_answer_fast_even_when_services_are_slow(tmp_path):
    """Regression: a closed port on Windows takes seconds to answer. /status must not wait for it, or the
    launcher's check times out and the window never opens."""
    class Slow(FakeMgr):
        def is_up(self):
            time.sleep(3)
            return False

    q = JobQueue(run_fn=lambda s, log: "x", state_file=tmp_path / "q.json")
    server = serve(q, Slow(), Slow(), TOKEN, port=8794)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for path in ("/ping", "/status"):
            req = urllib.request.Request(f"http://127.0.0.1:8794{path}", headers={"X-Lip-Token": TOKEN})
            began = time.time()
            with urllib.request.urlopen(req, timeout=5) as r:
                assert r.status == 200
            assert time.time() - began < 1.0, path
    finally:
        server.shutdown()


def test_remove_one_row_and_clear_finished(api, sample_wav, sample_shot):
    body = {"shot": sample_shot, "audio": sample_wav, "start": 6, "end": 9.24}
    ids = [call("POST", "/jobs", body)[1]["id"] for _ in range(3)]
    for _ in range(100):  # the fake render takes 0.3 s each, so wait for all three to finish
        rows = call("GET", "/jobs")[1]["jobs"]
        if all(r["status"] == "done" for r in rows):
            break
        time.sleep(0.1)
    assert call("POST", f"/jobs/{ids[0]}/remove")[1] == {"ok": True}
    assert ids[0] not in [r["id"] for r in call("GET", "/jobs")[1]["jobs"]]
    assert call("POST", "/jobs/nope/remove")[0] == 409
    assert call("POST", "/jobs/clear")[1] == {"removed": 2}
    assert call("GET", "/jobs")[1]["jobs"] == []


def test_clear_and_remove_never_touch_running_or_queued_rows(tmp_path):
    release = threading.Event()

    def slow(spec, log):
        release.wait(10)
        return "x.mp4"

    q = JobQueue(run_fn=slow, state_file=tmp_path / "q.json")
    a = q.add(shot="s", audio="a")      # becomes running
    b = q.add(shot="s", audio="a")      # stays queued
    c = q.add(shot="s", audio="a")
    q.cancel(c)                         # cancelled row
    for _ in range(50):
        if next(j for j in q.snapshot() if j["id"] == a)["status"] == "running":
            break
        time.sleep(0.05)
    assert q.clear_finished() == 1                          # only the cancelled row
    assert {j["id"] for j in q.snapshot()} == {a, b}
    assert q.remove(a) is False                             # running: refused
    assert q.remove(b) is True                              # queued: removed
    release.set()
    for _ in range(100):
        if q.snapshot() and q.snapshot()[0]["status"] == "done":
            break
        time.sleep(0.05)
    assert q.snapshot()[0]["status"] == "done"
    assert q.clear_finished() == 1 and q.snapshot() == []
