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


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_layout_comfy_desktop(tmp_path):
    from app.comfy_proc import comfy_layout
    _touch(tmp_path / "ComfyUI" / "main.py")
    py = _touch(tmp_path / "ComfyUI" / ".venv" / "Scripts" / "python.exe")
    assert comfy_layout(tmp_path) == (str(py), r"ComfyUI\main.py", True)


def test_layout_portable_and_plain(tmp_path):
    from app.comfy_proc import comfy_layout
    portable = tmp_path / "portable"
    _touch(portable / "ComfyUI" / "main.py")
    py = _touch(portable / "python_embeded" / "python.exe")
    assert comfy_layout(portable) == (str(py), r"ComfyUI\main.py", False)
    plain = tmp_path / "plain"
    _touch(plain / "main.py")
    py = _touch(plain / "venv" / "Scripts" / "python.exe")
    assert comfy_layout(plain) == (str(py), str(plain / "main.py"), False)


def test_layout_says_what_is_missing(tmp_path):
    import pytest
    from app.comfy_proc import comfy_layout
    with pytest.raises(RuntimeError, match="LIPSERVICE_COMFY_HOME"):
        comfy_layout(tmp_path)
    _touch(tmp_path / "main.py")
    with pytest.raises(RuntimeError, match="Python environment"):
        comfy_layout(tmp_path)


def test_a_missing_comfyui_is_reported_at_start_not_at_creation(tmp_path, monkeypatch):
    import pytest
    from app import comfy_proc
    monkeypatch.setattr(comfy_proc, "COMFY_HOME", tmp_path)
    m = comfy_proc.ComfyManager(url=f"http://127.0.0.1:{_free_port()}", log_file=tmp_path / "c.log")  # must not raise
    with pytest.raises(RuntimeError, match="No ComfyUI found"):
        m.start()


def test_stop_leaves_a_server_on_another_port_alone(tmp_path):
    """Two servers with the same command line: stop() on one port must not touch the other (Comfy Desktop's own
    ComfyUI looks just like ours)."""
    other_port = _free_port()
    marker = "http.server"
    def spawn(port):
        return __import__("subprocess").Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                                               "--directory", str(tmp_path)])
    mine, theirs = spawn(PORT), spawn(other_port)
    m = ComfyManager(url=f"http://127.0.0.1:{PORT}", health_path="/", command=["x"], cwd=tmp_path,
                     marker=marker, log_file=tmp_path / "s.log", start_timeout=5, stop_timeout=20)
    try:
        end = time.time() + 20
        while time.time() < end and not (m.is_up() and ComfyManager(url=f"http://127.0.0.1:{other_port}", health_path="/").is_up()):
            time.sleep(0.3)
        m.stop()
        assert mine.wait(timeout=10) is not None
        assert theirs.poll() is None   # still running
    finally:
        for p in (mine, theirs):
            if p.poll() is None:
                p.kill()


def test_comfy_desktop_folders_are_read_from_its_own_settings(tmp_path):
    import json
    from app.comfy_proc import comfy_desktop_folders
    base = tmp_path / "Comfy Desktop"
    base.mkdir()
    (base / "installations.json").write_text(json.dumps([{"id": "a", "installPath": r"X:\one"},
                                                          {"id": "b", "installPath": r"X:\two\ComfyUI"}]))
    (base / "last-session.json").write_text(json.dumps({"installationId": "b"}))
    (base / "settings.json").write_text(json.dumps({"modelsDirs": [r"X:\shared\models"], "inputDir": r"X:\shared\input",
                                                     "outputDir": r"X:\shared\output"}))
    assert comfy_desktop_folders(str(tmp_path)) == (r"X:\two\ComfyUI", r"X:\shared")
    (base / "settings.json").write_text(json.dumps({"modelsDirs": [r"X:\shared\models"], "inputDir": r"Y:\other\input",
                                                     "outputDir": r"X:\shared\output"}))
    assert comfy_desktop_folders(str(tmp_path))[1] == ""   # the folders do not share a parent: do not guess


def test_comfy_desktop_folders_when_it_is_not_installed(tmp_path):
    from app.comfy_proc import comfy_desktop_folders
    assert comfy_desktop_folders(str(tmp_path)) == ("", "")


def test_no_comfyui_anywhere_says_to_set_the_folder():
    import pytest
    from pathlib import Path
    from app.comfy_proc import comfy_layout
    with pytest.raises(RuntimeError, match="LIPSERVICE_COMFY_HOME"):
        comfy_layout(Path(""))
