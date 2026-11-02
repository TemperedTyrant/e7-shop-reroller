#!/usr/bin/env python3
"""KDE Wayland pointer control and read-only shop scanning helpers.

The standalone CLI defaults to a dry run; the desktop controller uses these
helpers to perform supervised actions.
"""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import cv2

from linux_shop import capture, detect


def ydo(*args):
    subprocess.run(["ydotool", *map(str, args)], check=True, timeout=10)


def cursor_position():
    result = subprocess.run(["kdotool", "getmouselocation", "--shell"],
                            check=True, capture_output=True, text=True, timeout=10).stdout
    coords = dict(re.findall(r"\b([XY])=(-?\d+)", result))
    if "X" not in coords or "Y" not in coords:
        raise RuntimeError(f"Could not parse KWin mouse location: {result!r}")
    return int(coords["X"]), int(coords["Y"])


def position_cursor(target, tolerance=6, stop_check=None, gain=.30,
                    step_limit=40, step_pause=.045):
    """Closed-loop relative movement, verified by KWin after each step."""
    for _ in range(90):
        if stop_check:
            stop_check()
        current = cursor_position()
        dx, dy = target[0] - current[0], target[1] - current[1]
        if max(abs(dx), abs(dy)) <= tolerance:
            return current
        # KDE applies pointer acceleration to virtual relative input. Sending
        # the *entire* remaining error can overshoot by ~80px each way and
        # oscillate forever. Use a damped proportional controller with a
        # bounded step, then read back KWin's real pointer location.
        mx = max(-step_limit, min(step_limit, round(dx * gain)))
        my = max(-step_limit, min(step_limit, round(dy * gain)))
        if mx == 0 and abs(dx) > tolerance:
            mx = 1 if dx > 0 else -1
        if my == 0 and abs(dy) > tolerance:
            my = 1 if dy > 0 else -1
        ydo("mousemove", "--", mx, my)
        time.sleep(step_pause)
    raise RuntimeError(f"Pointer never reached {target}; final KWin position: {cursor_position()}. No click sent.")


def drag(start, end, stop_check=None):
    # Never press until KWin confirms cursor is inside the intended shop area.
    actual = position_cursor(start, stop_check=stop_check)
    print(f"Pointer positioned at {actual} (requested {start})")
    ydo("click", "0x40")
    try:
        # Drags need a smooth *trajectory*, not pixel-perfect positioning at
        # twelve intermediate points. Six segments, with looser intermediate
        # tolerance, reduce repeated KWin queries without relaxing verification
        # of the initial pressed location or the final released location.
        for step in range(1, 7):
            if stop_check:
                stop_check()
            target = (round(start[0] + (end[0] - start[0]) * step / 6),
                      round(start[1] + (end[1] - start[1]) * step / 6))
            position_cursor(target, tolerance=14 if step < 6 else 8,
                            stop_check=stop_check, gain=.43, step_limit=28,
                            step_pause=.018)
    finally:
        ydo("click", "0x80")


def scan(region, threshold, output, selected=None, scales=None, include_frame=False,
         shop_icon_column=False):
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="e7-scan-") as folder:
        path = Path(folder) / "desktop.png"
        capture(path)
        desktop = cv2.imread(str(path))
    capture_ms = round((time.perf_counter() - started) * 1000)
    if desktop is None:
        raise RuntimeError("Could not read desktop capture")
    x, y, w, h = region
    if x < 0 or y < 0 or min(w, h) <= 0 or x + w > desktop.shape[1] or y + h > desktop.shape[0]:
        raise ValueError("--region is outside the captured desktop")
    frame = desktop[y:y+h, x:x+w].copy()
    clean_frame = frame.copy() if include_frame else None
    matching_started = time.perf_counter()
    # On the calibrated PC client the item images occupy a narrow column.
    # Limit template matching to it; this does not change screenshot/dialog
    # data, returned coordinates, or the read-only diagnostic CLI behavior.
    search_box = None
    if shop_icon_column:
        search_box = (round(w * .36), round(h * .03),
                      round(w * .22), round(h * .93))
    hits, diagnostics = detect(frame, threshold, selected=selected, scales=scales,
                               search_box=search_box)
    match_ms = round((time.perf_counter() - matching_started) * 1000)
    for hit in hits:
        left, top = hit["x"], hit["y"]
        cv2.rectangle(frame, (left, top), (left + hit["width"], top + hit["height"]), (0, 255, 0), 2)
        hit["desktop_x"] = left + x
        hit["desktop_y"] = top + y
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(output), frame):
            raise RuntimeError(f"Cannot write {output}")
    result = {"hits": hits, "diagnostics": diagnostics,
              "output": str(output) if output is not None else None,
              "capture_ms": capture_ms, "match_ms": match_ms}
    if include_frame:
        result["frame"] = clean_frame
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", type=int, nargs=4, required=True, metavar=("X", "Y", "W", "H"),
                    help="Game CONTENT rectangle in desktop pixels (not outer window decorations)")
    ap.add_argument("--threshold", type=float, default=0.70)
    ap.add_argument("--execute-scroll", action="store_true", help="Actually drag upward to reveal lower items")
    ap.add_argument("--test-pointer", action="store_true", help="Move pointer to safe list location without clicking")
    ap.add_argument("--output-dir", type=Path, default=Path("cycle-diagnostics"))
    args = ap.parse_args()
    if not 0 < args.threshold <= 1:
        ap.error("threshold must be between 0 and 1")
    x, y, w, h = args.region
    sx, sy = x + round(w * 0.54), y + round(h * 0.72)
    ex, ey = sx, y + round(h * 0.38)
    print(f"Planned game-list drag: ({sx}, {sy}) -> ({ex}, {ey})")
    top = scan(args.region, args.threshold, args.output_dir / "top.png")
    print("Top scan:", json.dumps(top, indent=2))
    if not args.execute_scroll and not args.test_pointer:
        print("DRY RUN. Use --test-pointer to validate positioning before --execute-scroll.")
        return
    if not shutil.which("ydotool") or not shutil.which("kdotool"):
        ap.error("Both ydotool and kdotool are required for verified cursor control")
    print("Moving to list in 3 seconds; Ctrl+C cancels.")
    time.sleep(3)
    if args.test_pointer:
        print(f"Verified final pointer position: {position_cursor((sx, sy))}")
        print("POINTER TEST ONLY. No click, drag, purchase, or refresh.")
        return
    drag((sx, sy), (ex, ey))
    time.sleep(1.0)
    bottom = scan(args.region, args.threshold, args.output_dir / "bottom.png")
    print("Bottom scan:", json.dumps(bottom, indent=2))
    print("DONE. No purchases or refreshes. Shop remains scrolled down.")


if __name__ == "__main__":
    main()
