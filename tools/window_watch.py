"""Watches for any NEW visible top-level window until a stop file appears, then prints what it saw.
Usage: python -I tools/window_watch.py <stop-file> [<max seconds>]"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from window_probe import visible_windows

stop, limit = Path(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 3600
before, seen, t0 = visible_windows(), {}, time.time()
while not stop.exists() and time.time() - t0 < limit:
    for h, v in visible_windows().items():
        if h not in before and h not in seen:
            seen[h] = (round(time.time() - t0), v)
    time.sleep(0.05)
print("new visible windows seen:", len(seen))
for t, (cls, title) in sorted(seen.values()):
    print(f"  at {t:4d} s  class={cls}  title={title!r}")
