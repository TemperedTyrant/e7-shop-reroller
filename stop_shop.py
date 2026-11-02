#!/usr/bin/env python3
"""Toggle Pause/Resume for the active E7 shop run via KDE global shortcut.

The existing stop_shop.py pathname is preserved so the user's previously
configured KDE shortcut does not need to be changed. For a terminal-only
emergency stop, call this script with --stop.
"""
import json
import os
import sys
from pathlib import Path

from session_history import active_run_path, run_history_dir


ROOT = Path(__file__).resolve().parent
marker = active_run_path()
if not marker.exists():
    print("No active Secret Shop run")
    raise SystemExit(0)
try:
    data = json.loads(marker.read_text())
    pid = int(data["pid"])
    directory = Path(data["directory"]).resolve()
    if directory.parent != run_history_dir().resolve():
        raise ValueError("Invalid run directory")
    os.kill(pid, 0)  # Check that the registered process is still alive.
    if len(sys.argv) > 1 and sys.argv[1] == "--stop":
        (directory / "STOP").touch(exist_ok=True)
        print("Session STOP requested:", directory.name)
    elif (directory / "PAUSED").exists() or (directory / "PAUSE").exists():
        (directory / "PAUSE").unlink(missing_ok=True)
        (directory / "RESUME").touch(exist_ok=True)
        print("Resume requested for Secret Shop run", directory.name)
    else:
        (directory / "RESUME").unlink(missing_ok=True)
        (directory / "PAUSE").touch(exist_ok=True)
        print("Pause requested for Secret Shop run", directory.name)
except (OSError, ValueError, KeyError, json.JSONDecodeError) as err:
    print(f"No verifiable active run: {err}")
    raise SystemExit(1)
