"""Start, stop and restart the local ComfyUI server.

ComfyUI keeps GBs of models in memory between renders (11 GB of GPU memory plus about 27 GB of
committed memory after one job). The app restarts it after every render so each job starts clean.
Telemetry flags are never passed. Settings can be overridden with LIPSERVICE_COMFY_* environment variables.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psutil

PROJECT = Path(__file__).resolve().parent.parent


def comfy_desktop_folders(appdata=None):
    """Where Comfy Desktop says it put ComfyUI, from its own settings files: (install folder, shared folder with
    input, output and models). Either is "" when Comfy Desktop is not installed or does not say."""
    base = Path(appdata if appdata is not None else os.environ.get("APPDATA", "")) / "Comfy Desktop"

    def load(name):
        try:
            return json.loads((base / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    home = ""
    installs = load("installations.json")
    if isinstance(installs, list) and installs:
        last = (load("last-session.json") or {}).get("installationId")
        pick = next((i for i in installs if isinstance(i, dict) and i.get("id") == last), installs[0])
        home = str(pick.get("installPath") or "") if isinstance(pick, dict) else ""
    shared = ""
    settings = load("settings.json") or {}
    models = (settings.get("modelsDirs") or [""])[0]
    if models and settings.get("inputDir") and settings.get("outputDir"):
        parents = {str(Path(p).parent) for p in (models, settings["inputDir"], settings["outputDir"])}
        shared = parents.pop() if len(parents) == 1 else ""
    return home, shared


_DESKTOP_HOME, _DESKTOP_SHARED = comfy_desktop_folders()
# The folder that holds ComfyUI. Set LIPSERVICE_COMFY_HOME for anything but Comfy Desktop. Empty when not found.
COMFY_HOME = Path(os.environ.get("LIPSERVICE_COMFY_HOME") or _DESKTOP_HOME or "")


def _default_shared() -> str:
    """The folder with input, output and models. Comfy Desktop keeps it apart from the install; every other layout
    keeps it inside the ComfyUI folder."""
    if _DESKTOP_SHARED:
        return _DESKTOP_SHARED
    return str(COMFY_HOME / "ComfyUI" if (COMFY_HOME / "ComfyUI" / "main.py").is_file() else COMFY_HOME)


COMFY_SHARED = Path(os.environ.get("LIPSERVICE_COMFY_SHARED") or _default_shared())


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


def comfy_layout(home=None):
    """Finds python and main.py inside a ComfyUI folder. Returns (python, script, desktop). Three layouts work:
    Comfy Desktop (home\\ComfyUI\\main.py with home\\ComfyUI\\.venv), the Windows portable build
    (home\\ComfyUI\\main.py with home\\python_embeded) and a plain checkout (home\\main.py with a .venv or venv).
    `script` is what ComfyUI is started with and also what the app looks for to find its own process."""
    home = Path(home or COMFY_HOME)
    if not str(home) or str(home) == ".":
        raise RuntimeError("No ComfyUI was found. Set LIPSERVICE_COMFY_HOME to the folder that holds ComfyUI "
                           "(see the README, Setup).")
    nested = (home / "ComfyUI" / "main.py").is_file()
    plain = (home / "main.py").is_file()
    if not (nested or plain):
        raise RuntimeError(f"No ComfyUI found in {home}. Set LIPSERVICE_COMFY_HOME to the folder that holds "
                           "ComfyUI (see the README, Setup).")
    base = home / "ComfyUI" if nested else home
    candidates = [base / ".venv" / "Scripts" / "python.exe", base / "venv" / "Scripts" / "python.exe",
                  home / ".venv" / "Scripts" / "python.exe", home / "python_embeded" / "python.exe"]
    python = next((c for c in candidates if c.is_file()), None)
    if python is None:
        raise RuntimeError(f"No Python environment found for the ComfyUI in {home}. Looked for "
                           + ", ".join(str(c) for c in candidates))
    desktop = nested and python == base / ".venv" / "Scripts" / "python.exe"
    script = r"ComfyUI\main.py" if nested else str(home / "main.py")
    return str(python), script, desktop


def default_command() -> list[str]:
    python, script, desktop = comfy_layout()
    cmd = [python, "-s", script]
    if desktop:  # these three flags exist in the Comfy Desktop build of ComfyUI
        cmd += ["--feature-flag", "show_signin_button=true", "--enable-assets", "--enable-manager"]
    cmd += ["--lowvram", "--disable-pinned-memory", "--disable-async-offload",
            "--input-directory", str(COMFY_SHARED / "input"), "--output-directory", str(COMFY_SHARED / "output")]
    if MODEL_PATHS_YAML and Path(MODEL_PATHS_YAML).exists():
        cmd += ["--extra-model-paths-config", MODEL_PATHS_YAML]
    return cmd


def default_marker() -> str:
    try:
        return comfy_layout()[1]
    except RuntimeError:
        return r"ComfyUI\main.py"


class ComfyManager:
    def __init__(self, url="http://127.0.0.1:8188", health_path="/system_stats", command=None,
                 cwd=None, marker=None, log_file=LOG_FILE, start_timeout=300, stop_timeout=60):
        self.url = url.rstrip("/")
        self.health_path = health_path
        self._command = command
        self.cwd = str(cwd or COMFY_HOME)
        self._marker = marker
        self.log_file = Path(log_file)
        self.pid_file = self.log_file.with_suffix(".pid")  # the process this app started, so stop() leaves others alone
        self.start_timeout = start_timeout
        self.stop_timeout = stop_timeout

    @property
    def command(self):
        # Worked out when it is needed, so a missing ComfyUI is reported at the first render, not at launch.
        return self._command or default_command()

    @property
    def marker(self):
        return self._marker or default_marker()

    @property
    def port(self):
        return urllib.parse.urlparse(self.url).port

    def is_up(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + self.health_path, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def _recorded_pid(self):
        try:
            return int(self.pid_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def _listening_pids(self):
        try:
            return {c.pid for c in psutil.net_connections(kind="tcp")
                    if c.status == psutil.CONN_LISTEN and c.laddr and c.laddr.port == self.port and c.pid}
        except (psutil.AccessDenied, OSError):
            return set()

    def _server_processes(self):
        """Only this app's server: a process that looks like it (the marker is in its command line) AND either
        listens on this server's port or is the one the app started. A ComfyUI that runs on another port (for
        example Comfy Desktop's own) is not touched."""
        mine = self._listening_pids()
        recorded = self._recorded_pid()
        if recorded:
            mine.add(recorded)
        procs = []
        for p in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(p.info["cmdline"] or [])
            if self.marker in cmd and p.info["pid"] in mine:
                procs.append(p)
        # A launcher process and the real server it started are both ours.
        for p in list(procs):
            try:
                for child in p.children(recursive=True):
                    if self.marker in " ".join(child.cmdline() or []) and child not in procs:
                        procs.append(child)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
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
        self.pid_file.write_text(str(proc.pid))
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
