import sys
import time

import psutil

from app.comfy_proc import ComfyManager
from app.queue import JobQueue

def _free_port():
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


PORT = _free_port()  # never the real ComfyUI port, and never one another program is using


def fake_manager(tmp_path):
    cmd = [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1", "--directory", str(tmp_path)]
    return ComfyManager(url=f"http://127.0.0.1:{PORT}", health_path="/", command=cmd, cwd=tmp_path,
                        marker=f"http.server {PORT}", log_file=tmp_path / "srv.log", start_timeout=30, stop_timeout=20)


def server_pids():
    return {p.pid for p in psutil.process_iter(["cmdline"]) if f"http.server {PORT}" in " ".join(p.info["cmdline"] or [])}


def test_start_restart_stop(tmp_path):
    m = fake_manager(tmp_path)
    try:
        assert not m.is_up()
        m.ensure_up()
        assert m.is_up()
        first = server_pids()
        m.ensure_up()                      # already up: must not restart
        assert server_pids() == first
        m.restart()                        # new process, old one gone
        assert m.is_up() and server_pids() and server_pids().isdisjoint(first)
        m.stop()
        assert not m.is_up() and not server_pids()
    finally:
        for pid in server_pids():
            psutil.Process(pid).kill()


def test_queue_restarts_after_every_job(tmp_path):
    calls = []

    class FakeComfy:
        def ensure_up(self): calls.append("up")
        def restart(self): calls.append("restart")

    def fake_run(spec, log):
        calls.append("run")
        if spec.prompt == "boom":
            raise RuntimeError("nope")
        return "x.mp4"

    q = JobQueue(run_fn=fake_run, state_file=tmp_path / "q.json", comfy=FakeComfy())
    q.add(shot="s", audio="a", prompt="boom")
    q.add(shot="s", audio="a", prompt="ok")
    end = time.time() + 15
    while time.time() < end and calls.count("restart") < 2:
        time.sleep(0.1)
    assert calls == ["up", "run", "restart", "up", "run", "restart"]
    assert [j["status"] for j in q.snapshot()] == ["failed", "done"]


def test_queue_starts_proxy_before_job(tmp_path):
    calls = []

    class Fake:
        def __init__(self, name): self.name = name
        def ensure_up(self): calls.append(self.name + " up")
        def restart(self): calls.append(self.name + " restart")

    q = JobQueue(run_fn=lambda s, log: calls.append("run") or "x.mp4", state_file=tmp_path / "q.json",
                 comfy=Fake("comfy"), proxy=Fake("proxy"))
    q.add(shot="s", audio="a")
    end = time.time() + 15
    while time.time() < end and "comfy restart" not in calls:
        time.sleep(0.1)
    assert calls == ["comfy up", "proxy up", "run", "comfy restart"]   # the proxy is never restarted


def test_proxy_manager_defaults():
    from app.comfy_proc import ProxyManager
    m = ProxyManager()
    assert m.url == "http://127.0.0.1:8189" and "run" in m.command and m.command[0].endswith("comfy-api-proxy.exe")
    assert "--listen" not in m.command and "0.0.0.0" not in " ".join(m.command)


def test_proxy_counts_as_up_even_when_it_answers_503():
    """With ComfyUI down the proxy answers 503 on /api/v2/jobs. It is still running."""
    import http.server
    import threading

    from app.comfy_proc import ProxyManager

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers()
        def log_message(self, *a): pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8795), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert ProxyManager(url="http://127.0.0.1:8795").is_up()
    finally:
        srv.shutdown()
    assert not ProxyManager(url="http://127.0.0.1:8795").is_up()
