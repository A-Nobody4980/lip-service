"""Shows whether a background program pops up console windows.

A process started with DETACHED_PROCESS has no console at all, so every console program it starts (ffmpeg,
git, nvidia-smi...) gets a brand new VISIBLE console window. CREATE_NO_WINDOW alone gives it a hidden console
that its children share, so nothing appears. This starts a child that runs a console program both ways and
lists any new visible windows.  Usage: python -I tools/window_probe.py
"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

DETACHED_PROCESS, CREATE_NO_WINDOW = 0x00000008, 0x08000000
user32 = ctypes.windll.user32
ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def visible_windows():
    found = {}

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            cls, title = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            user32.GetWindowTextW(hwnd, title, 256)
            found[hwnd] = (cls.value, title.value)
        return True

    user32.EnumWindows(ENUM(cb), 0)
    return found


def trial(label, flags):
    before = visible_windows()
    child = "import subprocess; subprocess.run(['ping', '-n', '4', '127.0.0.1'], stdout=subprocess.DEVNULL)"
    p = subprocess.Popen([sys.executable, "-c", child], creationflags=flags, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    new = {}
    while p.poll() is None:
        for h, v in visible_windows().items():
            if h not in before:
                new[h] = v
        time.sleep(0.05)
    print(f"{label}: {len(new)} new visible window(s) {sorted(set(new.values()))}")
    return len(new)


if __name__ == "__main__":
    old = trial("old flags (DETACHED_PROCESS | CREATE_NO_WINDOW)", DETACHED_PROCESS | CREATE_NO_WINDOW)
    new = trial("new flags (CREATE_NO_WINDOW only)            ", CREATE_NO_WINDOW)
    sys.exit(0 if new == 0 else 1)
