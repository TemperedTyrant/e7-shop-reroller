"""KWin-managed geometry setup for the Epic Seven Proton window.

All requested coordinates are *content* pixels, not titlebar/frame pixels.
Geometry is verified before callers may emit game input.
"""
import json
import shutil
import subprocess
import time

import cv2

from linux_shop import capture


def kwin(script):
    if not shutil.which("kdotool"):
        raise RuntimeError("kdotool is required for automatic window setup")
    result = subprocess.run(["kdotool", "kwinscript", "--inline", script],
                            capture_output=True, text=True, timeout=12)
    if result.returncode:
        raise RuntimeError(f"KWin script failed: {(result.stderr or result.stdout).strip()}")
    for line in reversed(result.stdout.splitlines()):
        try:
            value = json.loads(line.strip())
            if isinstance(value, dict) and "status" in value:
                return value
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"KWin returned no window geometry: {result.stdout.strip()}")


_FIND = r'''
var found = workspace.windowList().filter(function(w) {
    return /^Epic Seven$/i.test(String(w.captionNormal || w.caption).trim()) && w.normalWindow;
});
if (found.length !== 1) {
    output_result(JSON.stringify({status:"error", error:"Expected exactly one Epic Seven window, found " + found.length}));
} else {
    var w = found[0];
    var f = w.frameGeometry, c = w.clientGeometry;
    var screens = workspace.screens.map(function(s) {
        var g=s.geometry;
        return {x:g.x,y:g.y,width:g.width,height:g.height};
    });
    output_result(JSON.stringify({status:"ok", id:String(w.internalId), fullscreen:w.fullScreen,
        screens:screens,
        frame:{x:f.x,y:f.y,width:f.width,height:f.height},
        client:{x:c.x,y:c.y,width:c.width,height:c.height}}));
}
'''


def find_window():
    result = kwin(_FIND)
    if result["status"] != "ok":
        raise RuntimeError(result.get("error", "Epic Seven not found"))
    return result


def focus_window(window_id, stop_check=lambda: None):
    """Raise/focus Epic Seven and verify KWin actually granted activation."""
    kwin(_select(window_id, "workspace.activeWindow=w;"))
    for _ in range(8):
        stop_check()
        active = kwin("var a=workspace.activeWindow;"
                      "output_result(JSON.stringify({status:'ok',id:a?String(a.internalId):null}));")
        if active.get("id") == window_id:
            return
        time.sleep(0.15)
    raise RuntimeError("KWin did not focus Epic Seven; refusing to send game input")


def _select(window_id, actions):
    # JSON string encoding prevents untrusted window identifiers entering JS source.
    return ("var id=" + json.dumps(window_id) + ";"
            "var w=workspace.windowList().find(function(v){return String(v.internalId)===id;});"
            "if(!w){output_result(JSON.stringify({status:'error',error:'Epic Seven window disappeared'}));}"
            "else{" + actions + "output_result(JSON.stringify({status:'ok'}));}")


def choose_content_region(region, screens, decorations, current_client=None):
    """Fit a 16:9 client on the display currently holding the game."""
    if not screens:
        raise RuntimeError("KWin reported no displays; cannot choose a safe game position")
    x, y, width, height = region
    cx, cy = x + width / 2, y + height / 2
    # After a display-mode change saved coordinates can refer to a screen
    # that no longer exists. Prefer actual game-window overlap over those
    # stale coordinates, and use the saved center only as a fallback.
    def overlap(s):
        if current_client is None:
            return 0
        return (max(0, min(s["x"] + s["width"], current_client["x"] + current_client["width"])
                    - max(s["x"], current_client["x"])) *
                max(0, min(s["y"] + s["height"], current_client["y"] + current_client["height"])
                    - max(s["y"], current_client["y"])))
    screen = max(screens, key=overlap)
    if overlap(screen) == 0:
        screen = next((s for s in screens if s["x"] <= cx < s["x"] + s["width"]
                       and s["y"] <= cy < s["y"] + s["height"]), screens[0])
    left, top, extra_w, extra_h = decorations
    margin = 8
    available_w = screen["width"] - extra_w - 2 * margin
    available_h = screen["height"] - extra_h - 2 * margin
    target_w = min(width, int(available_w), int(available_h * 16 / 9))
    target_w = min(target_w, 1280)
    target_h = round(target_w * 9 / 16)
    if target_w < 960 or target_h < 540:
        raise RuntimeError("This display cannot fit the minimum safe 960x540 game content with window decorations")
    frame_x = screen["x"] + (screen["width"] - target_w - extra_w) // 2
    frame_y = screen["y"] + (screen["height"] - target_h - extra_h) // 2
    return (frame_x + left, frame_y + top, target_w, target_h)


def setup_window(region, stop_check=lambda: None, log=lambda line: None):
    """Set content rect, then verify KWin client geometry and screenshot pixels.

    Requires 1:1 compositor logical-to-screenshot coordinates; fail closed if
    fractional display scaling makes the geometry systems incomparable.
    """
    requested = region
    x, y, width, height = region
    stop_check()
    window = find_window()
    window_id = window["id"]
    log(f"Found Epic Seven ({window_id}); fullscreen={window['fullscreen']}")
    kwin(_select(window_id, "w.fullScreen=false;w.setMaximize(false,false);w.minimized=false;"))
    time.sleep(0.4)
    stop_check()
    # A titlebar's size varies by theme; measure the actual frame-to-client gap.
    window = find_window()
    frame, client = window["frame"], window["client"]
    left = client["x"] - frame["x"]
    top = client["y"] - frame["y"]
    extra_w = frame["width"] - client["width"]
    extra_h = frame["height"] - client["height"]
    x, y, width, height = choose_content_region(region, window.get("screens", []),
                                                 (left, top, extra_w, extra_h), client)
    if (x, y, width, height) != tuple(requested):
        log(f"Auto-fit game content to display: {(x, y, width, height)}")
    desired_frame = {"x": x - left, "y": y - top,
                     "width": width + extra_w, "height": height + extra_h}
    if desired_frame["x"] < 0 or desired_frame["y"] < 0:
        raise RuntimeError("Desired game content is too close to desktop edge for its window decorations")
    geometry_js = json.dumps(desired_frame)
    kwin(_select(window_id, "w.frameGeometry=" + geometry_js + ";"))
    previous = None
    stable = 0
    for _ in range(8):
        stop_check()
        time.sleep(0.25)
        actual = find_window()
        c = actual["client"]
        geometry = tuple(round(c[k]) for k in ("x", "y", "width", "height"))
        stable = stable + 1 if geometry == previous else 0
        previous = geometry
        # The Proton client constrains 1280x710 to 1280x720 (16:9).
        # KWin can shift a window slightly to keep decorations inside the
        # usable area. Accept small stable adjustments; downstream uses the
        # measured client geometry, never the requested click coordinates.
        if (not actual["fullscreen"] and stable >= 1 and
                abs(geometry[0] - x) <= 24 and abs(geometry[1] - y) <= 24 and
                abs(geometry[2] - width) <= 20 and abs(geometry[3] - height) <= 24):
            break
    else:
        raise RuntimeError(f"Epic Seven did not reach content rectangle {(x, y, width, height)}; "
                           f"KWin reports {actual['client']}. Check scaling or in-game window mode.")
    x, y, width, height = geometry
    if not any(s["x"] <= x and s["y"] <= y and
               x + width <= s["x"] + s["width"] and
               y + height <= s["y"] + s["height"]
               for s in actual.get("screens", [])):
        raise RuntimeError("Epic Seven content does not fit entirely on one display; "
                           "check window constraints and display layout")
    stop_check()
    # Ensure the configured rectangle maps into the screenshot and contains
    # actual rendered pixels, rather than a black/fullscreen/other-monitor area.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="e7-window-setup-") as folder:
        from pathlib import Path
        picture = Path(folder) / "screen.png"
        capture(picture)
        screenshot = cv2.imread(str(picture))
    if screenshot is None or x < 0 or y < 0 or x + width > screenshot.shape[1] or y + height > screenshot.shape[0]:
        raise RuntimeError("Verified window rectangle is outside screenshot bounds")
    crop = screenshot[y:y+height, x:x+width]
    if float(cv2.meanStdDev(crop)[1].mean()) < 8:
        raise RuntimeError("Game content screenshot is blank or obscured; refusing to start")
    focus_window(window_id, stop_check=stop_check)
    log("Epic Seven activated and verified as the foreground window")
    log(f"Window setup verified: actual content {geometry}; capture {screenshot.shape[1]}x{screenshot.shape[0]}")
    if geometry != tuple(region):
        log(f"Game adjusted content size from {tuple(region)} to {geometry}; using measured coordinates")
    return geometry
