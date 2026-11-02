#!/usr/bin/env python3
"""KDE Wayland prototype for Solunium's Epic Seven shop templates.

Detection is read-only by default. No purchases or refreshes are automated.
"""
import argparse
import json
import subprocess
import tempfile
import time
from functools import lru_cache
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parent
ITEMS = {"covenant": "cov.png", "mystic": "mys.png", "friendship": "fb.png"}


def capture(path: Path) -> None:
    # KDE Spectacle supports noninteractive full-screen grabs in its X11 and
    # Wayland backends when screenshot permissions permit it.
    command = ["spectacle", "--background", "--nonotify", "--fullscreen", "--output", str(path)]
    problems = []
    for attempt in range(1, 4):
        # Spectacle can delegate a capture to its already-running D-Bus service;
        # a successful subprocess exit may precede the output becoming visible.
        if path.exists():
            path.unlink()
        try:
            result = subprocess.run(command, text=True, capture_output=True,
                                    timeout=30, check=False)
            for _ in range(40):
                if path.exists() and path.stat().st_size > 1000:
                    return
                time.sleep(0.1)
            problems.append(f"attempt {attempt}: exit={result.returncode}, "
                            f"stdout={result.stdout.strip()!r}, stderr={result.stderr.strip()!r}, "
                            f"file_exists={path.exists()}")
        except (OSError, subprocess.TimeoutExpired) as err:
            problems.append(f"attempt {attempt}: {type(err).__name__}: {err}")
        time.sleep(0.5 * attempt)
    raise RuntimeError("Spectacle capture failed after 3 attempts: " + " | ".join(problems))


@lru_cache(maxsize=64)
def prepared_template(filename, scale):
    """Load/resize each source template once per process, not per screenshot."""
    template = cv2.imread(str(ROOT / "assets" / filename))
    if template is None:
        raise FileNotFoundError(filename)
    return cv2.resize(template, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)


def detect(frame, threshold: float, selected=None, scales=None, search_box=None):
    """Find shop items; an optional (x,y,w,h) box constrains matching.

    Box coordinates are within `frame`; returned hits remain in full-frame
    coordinates so downstream click calculations do not change.
    """
    hits = []
    diagnostics = []
    if search_box is not None:
        ox, oy, sw, sh = search_box
        if ox < 0 or oy < 0 or sw <= 0 or sh <= 0 or ox+sw > frame.shape[1] or oy+sh > frame.shape[0]:
            raise ValueError("Invalid template search region")
        search_frame = frame[oy:oy+sh, ox:ox+sw]
    else:
        ox = oy = 0
        search_frame = frame
    for label, filename in ITEMS.items():
        if selected is not None and label not in selected:
            continue
        best = (-1.0, (0, 0), 0, 0, 1.0)
        row_hits = []
        # Original template sizes correspond to a small Windows game window.
        # Steam/Proton can render the same icons larger (or smaller).
        for scale in (scales if scales is not None else [0.5 + i * 0.2 for i in range(11)]):
            resized = prepared_template(filename, scale)
            h, w = resized.shape[:2]
            if h > search_frame.shape[0] or w > search_frame.shape[1]:
                continue
            scores = cv2.matchTemplate(search_frame, resized, cv2.TM_CCOEFF_NORMED)
            _, score, _, xy = cv2.minMaxLoc(scores)
            if score > best[0]:
                best = (float(score), (xy[0] + ox, xy[1] + oy), w, h, scale)
            # Multiple offers of the same currency must remain separate hits.
            # Suppress nearby template peaks before collecting another row.
            for _ in range(12):
                if score < threshold:
                    break
                row_hits.append((float(score), xy[0] + ox, xy[1] + oy, w, h, scale))
                px, py = xy
                x0, x1 = max(0, px - w // 2), min(scores.shape[1], px + w // 2 + 1)
                y0, y1 = max(0, py - h // 2), min(scores.shape[0], py + h // 2 + 1)
                scores[y0:y1, x0:x1] = -1
                _, score, _, xy = cv2.minMaxLoc(scores)
        score, xy, w, h, scale = best
        diagnostics.append({"item": label, "best_confidence": round(score, 3),
                            "scale": round(scale, 2), "x": xy[0], "y": xy[1]})
        # Non-maximum suppression across scales: one result per shop row.
        for confidence, hx, hy, hw, hh, hs in sorted(row_hits, reverse=True):
            if any(v["item"] == label and abs(v["y"] - hy) < hh * .65
                   and abs(v["x"] - hx) < hw * .65 for v in hits):
                continue
            hits.append({"item": label, "confidence": round(confidence, 3),
                         "x": hx, "y": hy, "scale": round(hs, 2),
                         "width": hw, "height": hh})
    return hits, diagnostics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", type=int, nargs=4, metavar=("X", "Y", "W", "H"),
                        help="Epic Seven CONTENT bounds on the full desktop screenshot")
    parser.add_argument("--threshold", type=float, default=0.80)
    parser.add_argument("--image", type=Path, help="Analyze a saved screenshot instead of capturing")
    parser.add_argument("--output", type=Path, default=Path("shop-detection.png"))
    args = parser.parse_args()
    if not 0 < args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")

    if args.image:
        original = cv2.imread(str(args.image))
    else:
        with tempfile.TemporaryDirectory(prefix="e7-wayland-") as directory:
            screenshot = Path(directory) / "screen.png"
            capture(screenshot)
            original = cv2.imread(str(screenshot))
    if original is None:
        parser.error("Could not decode screenshot")

    if args.region:
        x, y, w, h = args.region
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > original.shape[1] or y + h > original.shape[0]:
            parser.error("Region is outside screenshot bounds")
        frame = original[y:y+h, x:x+w].copy()
    else:
        frame = original.copy()

    hits, diagnostics = detect(frame, args.threshold)
    for hit in hits:
        p1 = (hit["x"], hit["y"])
        p2 = (hit["x"] + hit["width"], hit["y"] + hit["height"])
        cv2.rectangle(frame, p1, p2, (0, 255, 0), 2)
        cv2.putText(frame, f'{hit["item"]} {hit["confidence"]:.2f}',
                    (p1[0], max(15, p1[1] - 5)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 0), 1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), frame):
        raise RuntimeError("Could not save annotated image")
    print(json.dumps({"hits": hits, "diagnostics": diagnostics, "output": str(args.output),
                      "image_size": [frame.shape[1], frame.shape[0]]}, indent=2))
    print("READ-ONLY: no mouse input or purchases were performed")


if __name__ == "__main__":
    main()
