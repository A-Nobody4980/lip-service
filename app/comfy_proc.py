"""Start, stop and restart the local ComfyUI server.

ComfyUI keeps GBs of models in memory between renders (11 GB of GPU memory plus about 27 GB of
committed memory after one job). The app restarts it after every render so each job starts clean.
Telemetry flags are never passed. Settings can be overridden with LIPSERVICE_COMFY_* environment variables.
"""
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

PROJECT = Path(__file__).resolve().parent.parent
COMFY_HOME = Path(os.environ.get("LIPSERVICE_COMFY_HOME", r"D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI"))
COMFY_SHARED = Path(os.environ.get("LIPSERVICE_COMFY_SHARED", r"D:\Comfy-Desktop\ComfyUI-Shared"))


def _find_model_paths_yaml() -> str:
    """The extra model paths file Comfy Desktop writes for its install, if there is one. Set
    LIPSERVICE_COMFY_MODEL_PATHS to use another file, or to an empty value for none."""
    if "LIPSERVICE_COMFY_MODEL_PATHS" in os.environ:
        return os.environ["LIPSERVICE_COMFY_MODEL_PATHS"]
    found = sorted(Path(os.environ.get("APPDATA", "")).glob("Comfy Desktop/instance-model-paths/*.yaml"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return str(found[0]) if found else ""


MODEL_PATHS_YAML = _find_model_paths_yaml()
LOG_FILE = PROJECT / "state" / "comfyui.log"


def default_command() -> list[str]:
    cmd = [str(COMFY_HOME / "ComfyUI" / ".venv" / "Scripts" / "python.exe"), "-s", r"ComfyUI\main.py",
           "--feature-flag", "show_signin_button=true", "--enable-assets", "--enable-manager",
           "--lowvram", "--disable-pinned-memory", "--disable-async-offload",
           "--input-directory", str(COMFY_SHARED / "input"), "--output-directory", str(COMFY_SHARED / "output")]
    if MODEL_PATHS_YAML and Path(MODEL_PATHS_YAML).exists():
        cmd += ["--extra-model-paths-config", MODEL_PATHS_YAML]
    return cmd


class ComfyManager:
    def __init__(self, url="http://127.0.0.1:8188", health_path="/system_stats", command=None,
                 cwd=None, marker=r"ComfyUI\main.py", log_file=LOG_FILE, start_timeout=300, stop_timeout=60):
        self.url = url.rstrip("/")
        self.health_path = health_path
        self.command = command or default_command()
        self.cwd = str(cwd or COMFY_HOME)
        self.marker = marker
        self.log_file = Path(log_file)
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout

    def is_up(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + self.health_path, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def _server_processes(self):
        procs = []
        for p in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(p.info["cmdline"] or [])
            if self.marker in cmd:
                procs.append(p)
        return procs

    def stop(self):
        procs = self._server_processes()
        for p in procs:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(procs, timeout=self.stop_timeout)
        end = time.time() + self.stop_timeout
        while self.is_up() and time.time() < end:
            time.sleep(1)
        if self.is_up():
            raise RuntimeError("ComfyUI is still answering after it was stopped")

    def start(self):
        if self.is_up():
            return
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_file, "ab")
        # CREATE_NO_WINDOW gives the program a hidden console that the programs it starts (ffmpeg, git, nvidia-smi)
        # share. Adding DETACHED_PROCESS would leave it with no console, and then every one of those would open
        # its own visible window. See tools/window_probe.py.
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(self.command, cwd=self.cwd, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                creationflags=flags, close_fds=True)
        end = time.time() + self.start_timeout
        while time.time() < end:
            if proc.poll() is not None:
                time.sleep(3)
                if self.is_up():  # another start won the race for the port: that is fine
                    return
                raise RuntimeError(f"ComfyUI exited at start (code {proc.returncode}). See {self.log_file}")
            if self.is_up():
                return
            time.sleep(2)
        raise RuntimeError(f"ComfyUI did not come up within {self.start_timeout} s. See {self.log_file}")

    def ensure_up(self):
        if not self.is_up():
            self.start()

    def restart(self):
        self.stop()
        self.start()


def _proxy_exe() -> str:
    import shutil
    import sys
    beside_python = Path(sys.executable).parent / "comfy-api-proxy.exe"
    return str(beside_python) if beside_python.exists() else (shutil.which("comfy-api-proxy") or "comfy-api-proxy")


class ProxyManager(ComfyManager):
    """The local comfy-api-proxy (port 8189) that the Comfy SDK talks to. Bound to 127.0.0.1 only."""

    def __init__(self, url="http://127.0.0.1:8189", health_path="/api/v2/jobs", command=None, cwd=None,
                 marker="comfy-api-proxy", log_file=PROJECT / "state" / "proxy.log", **kw):
        command = command or [_proxy_exe(), "run", "--comfyui", "http://127.0.0.1:8188",
                              "--state-dir", str(PROJECT / "state" / "proxy")]
        super().__init__(url=url, health_path=health_path, command=command, cwd=cwd or PROJECT,
                         marker=marker, log_file=log_file, start_timeout=60, **kw)

    def is_up(self) -> bool:
        """The proxy is up if it answers at all. When ComfyUI is down it answers 503 (upstream unreachable),
        which still means the proxy itself is running."""
        try:
            urllib.request.urlopen(self.url + self.health_path, timeout=3).close()
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            return False
