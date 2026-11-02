#!/usr/bin/env python3
"""E7 Shop Reroller: KDE Wayland desktop controller."""
import base64
import json
import os
import shlex
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import cv2
import numpy as np

from wayland_cycle import drag, position_cursor, scan, ydo
from linux_shop import capture, detect
from window_setup import setup_window
from run_policy import (DROP_RATES, SLOTS_PER_SHOP, can_refresh,
                        expected_appearances, recognition_scale)
from session_history import (load_settings, save_settings, record_session, totals,
                             sessions, export_sessions, clear_sessions,
                             run_history_dir, active_run_path)


class Cancelled(Exception):
    pass

ROOT = Path(__file__).resolve().parent


class HoverTip:
    """Small delayed tooltip attached to a question-mark label."""

    def __init__(self, root, widget, description):
        self.root, self.widget, self.description = root, widget, description
        self.job = None
        self.popup = None
        widget.bind("<Enter>", self.schedule)
        widget.bind("<Leave>", self.hide)
        widget.bind("<ButtonPress>", self.hide)

    def schedule(self, _event=None):
        self.cancel()
        self.job = self.root.after(350, self.show)

    def cancel(self):
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None

    def show(self):
        self.job = None
        if self.popup is not None or not self.widget.winfo_exists():
            return
        popup = tk.Toplevel(self.root)
        popup.wm_overrideredirect(True)
        label = tk.Label(popup, text=self.description, justify="left", wraplength=360,
                         background="#233647", foreground="#f0f1ee",
                         borderwidth=1, relief="solid", padx=12, pady=11,
                         font=("Sans", 10))
        label.pack()
        popup.update_idletasks()
        x = self.widget.winfo_rootx() + 15
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        x = min(x, max(0, self.root.winfo_screenwidth() - popup.winfo_reqwidth() - 8))
        y = min(y, max(0, self.root.winfo_screenheight() - popup.winfo_reqheight() - 8))
        popup.geometry(f"+{x}+{y}")
        self.popup = popup

    def hide(self, _event=None):
        self.cancel()
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None


class Runner:
    def __init__(self, settings, log, stopped, on_stats, on_region=lambda region: None):
        self.s = settings
        self.log = log
        self.stopped = stopped
        self.on_stats = on_stats
        self.on_region = on_region
        self.folder = run_history_dir() / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.counts = {"covenant": 0, "mystic": 0, "refreshes": 0}
        self.counts["friendship"] = 0
        self.cycle_id = 0
        self.latest_frame = None
        self.shops_reviewed = 0
        self.stream = None
        self.pause_requested = threading.Event()
        self.resume_requested = threading.Event()
        self.paused = threading.Event()
        self.pause_reason = ""
        self.started_at = None
        self.loop_started_at = None
        self.ended_at = None
        self.timings = {"capture": 0.0, "matching": 0.0, "cursor": 0.0,
                        "scroll": 0.0, "waiting": 0.0}
        self.frames_captured = 0
        self.history_id = uuid.uuid4().hex
        self.started_utc = None

    def publish_stats(self):
        self.on_stats({"shops": self.shops_reviewed, "counts": self.counts.copy(),
                       "expected": expected_appearances(self.shops_reviewed)})

    def performance_snapshot(self):
        end = self.ended_at or time.monotonic()
        elapsed = max(0.0, end - self.started_at) if self.started_at else 0.0
        loop_time = max(0.0, end - self.loop_started_at) if self.loop_started_at else 0.0
        paid = self.counts["refreshes"]
        limit = self.s["limit_value"] if self.s["limit_mode"] == "refreshes" else self.s["limit_value"] // 3
        rate = (paid * 60 / loop_time) if loop_time > 0 and paid else 0.0
        remaining = ((limit-paid) * loop_time / paid) if paid else None
        return {"elapsed": elapsed, "rate": rate, "remaining": remaining,
                "refreshes": paid, "limit": limit,
                "frames": self.frames_captured, "timings": self.timings.copy()}

    def save_frame(self, name, frame):
        if self.s["detailed"]:
            cv2.imwrite(str(self.folder / f"cycle-{self.cycle_id:04d}-{name}.png"), frame)

    def check(self):
        if self.stopped.is_set() or (self.folder / "STOP").exists():
            raise Cancelled("Stopped by user")

    def checkpoint(self):
        """Pause only between atomic UI operations, never with a drag held."""
        self.check()
        if self.pause_requested.is_set() or (self.folder / "PAUSE").exists():
            self.intervene("Paused by user. Resume to continue, or Stop to end the run.")

    def intervene(self, reason):
        self.pause_reason = reason
        self.resume_requested.clear()
        resume_marker = self.folder / "RESUME"
        paused_marker = self.folder / "PAUSED"
        # Drop a stale pending resume before advertising PAUSED. The global
        # shortcut checks this state to decide which action to request.
        resume_marker.unlink(missing_ok=True)
        self.paused.set()
        paused_marker.touch(exist_ok=True)
        self.log(f"PAUSED: {reason}")
        try:
            while not (self.resume_requested.is_set() or resume_marker.exists()):
                self.check()
                self.resume_requested.wait(.1)
            self.check()
        finally:
            paused_marker.unlink(missing_ok=True)
            resume_marker.unlink(missing_ok=True)
            (self.folder / "PAUSE").unlink(missing_ok=True)
            self.pause_requested.clear()
            self.paused.clear()
            self.resume_requested.clear()
        self.log("RESUMED: validating current game state before further input")

    def counter_region(self, frame, target):
        """Crop the shop row's availability counter (1/1 -> 0/1)."""
        x, y, w, h = self.s["region"]
        cy = target[1] - y
        xa, xb = round(w*.844), round(w*.901)
        ya, yb = cy - round(h*.031), cy + round(h*.031)
        if ya < 0 or yb > frame.shape[0] or xb > frame.shape[1]:
            raise RuntimeError("Availability counter outside game capture")
        return frame[ya:yb, xa:xb]

    def shop_overlay_closed(self, before, after):
        _, _, w, h = self.s["region"]
        roi = (slice(round(h*.19), round(h*.38)),
               slice(round(w*.07), round(w*.24)))
        pre = float(cv2.mean(cv2.cvtColor(before[roi], cv2.COLOR_BGR2GRAY))[0])
        post = float(cv2.mean(cv2.cvtColor(after[roi], cv2.COLOR_BGR2GRAY))[0])
        return pre > 15 and post >= pre * .78

    def verify_sold(self, before, target, item, phase, timeout=2.5):
        """Require both the row counter to change and Buy to become disabled."""
        reference = self.counter_region(before, target)
        deadline = time.monotonic() + timeout
        best_change = 0.0
        while time.monotonic() < deadline:
            self.check()
            after = self.raw(f"sold-{phase}-{item}")
            state, brightness = self.buy_button_state(after, target)
            difference = float(np.mean(cv2.absdiff(reference, self.counter_region(after, target))))
            best_change = max(best_change, difference)
            if state == "sold" and difference >= 8.0 and self.shop_overlay_closed(before, after):
                self.log(f"{item}: verified sold-row transition (counter change={difference:.1f}, "
                         f"Buy brightness={brightness:.0f})")
                return True
            self.pause(.08)
        self.log(f"{item}: sale unverified (counter change at most {best_change:.1f})")
        return False

    def pause(self, seconds):
        started = time.perf_counter()
        until = time.monotonic() + seconds
        try:
            while time.monotonic() < until:
                self.check()
                time.sleep(min(0.1, max(0, until - time.monotonic())))
        finally:
            self.timings["waiting"] += time.perf_counter() - started

    def click(self, point):
        self.check()
        self.log(f"Click target {point}")
        if self.s["live"]:
            started = time.perf_counter()
            try:
                position_cursor(point, stop_check=self.check)
                self.check()
                ydo("click", "0xC0")
            finally:
                self.timings["cursor"] += time.perf_counter() - started
            self.pause(self.s["delay"])

    def screen(self, name):
        self.check()
        if self.stream is not None:
            start = time.perf_counter()
            frame = self.stream.frame()
            capture_ms = round((time.perf_counter() - start) * 1000)
            x, y, w, h = self.s["region"]
            start = time.perf_counter()
            hits, diagnostics = detect(frame, self.s["threshold"],
                                       selected=self.s["items"], scales=self.s["scales"],
                                       search_box=(round(w*.36), round(h*.03),
                                                   round(w*.22), round(h*.93)))
            for hit in hits:
                hit["desktop_x"] = hit["x"] + x
                hit["desktop_y"] = hit["y"] + y
            result = {"hits": hits, "diagnostics": diagnostics, "frame": frame,
                      "capture_ms": capture_ms,
                      "match_ms": round((time.perf_counter()-start)*1000)}
            self.latest_frame = frame
            self.timings["capture"] += capture_ms / 1000
            self.timings["matching"] += result["match_ms"] / 1000
            self.frames_captured += 1
            self.log(f"Timing {name}: capture={capture_ms}ms, matching={result['match_ms']}ms")
            return result
        path = self.folder / f"cycle-{self.cycle_id:04d}-{name}.png" if self.s["detailed"] else None
        result = scan(self.s["region"], self.s["threshold"],
                      path, selected=self.s["items"], scales=self.s["scales"],
                      include_frame=True, shop_icon_column=True)
        self.latest_frame = result["frame"]
        self.timings["capture"] += result["capture_ms"] / 1000
        self.timings["matching"] += result["match_ms"] / 1000
        self.frames_captured += 1
        self.log(f"Timing {name}: capture={result['capture_ms']}ms, matching={result['match_ms']}ms")
        return result

    def raw(self, name):
        # This is for detecting UI transitions, without annotation rectangles.
        started = time.perf_counter()
        if self.stream is not None:
            cropped = self.stream.frame()
            self.timings["capture"] += time.perf_counter() - started
            self.frames_captured += 1
            self.save_frame(name, cropped)
            self.latest_frame = cropped
            return cropped
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="e7-state-") as folder:
            path = Path(folder) / "s.png"
            capture(path)
            frame = cv2.imread(str(path))
        x, y, w, h = self.s["region"]
        if frame is None or x + w > frame.shape[1] or y + h > frame.shape[0]:
            raise RuntimeError("Captured game bounds changed; stopping")
        cropped = frame[y:y+h, x:x+w]
        self.timings["capture"] += time.perf_counter() - started
        self.frames_captured += 1
        self.save_frame(name, cropped)
        self.latest_frame = cropped
        return cropped

    def changed(self, before, after):
        h, w = before.shape[:2]
        # Compare center area, where the original game presents confirmations.
        roi = (slice(round(h * .35), round(h * .80)),
               slice(round(w * .30), round(w * .75)))
        diff = cv2.absdiff(before[roi], after[roi])
        return float(cv2.mean(diff)[0] + cv2.mean(diff)[1] + cv2.mean(diff)[2]) / 3

    def wait_for_change(self, before, label, timeout=2.5):
        """Wait for the visual transition instead of sampling an early frame.

        Fast PipeWire frames expose intermediate animation states that were
        previously hidden by Spectacle's ~440ms capture overhead.
        """
        deadline = time.monotonic() + timeout
        strongest = 0.0
        while True:
            self.check()
            after = self.raw(label)
            score = self.changed(before, after)
            strongest = max(strongest, score)
            if score >= self.s["min_change"]:
                self.log(f"{label}: screen-change score={score:.1f}")
                return after
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Expected {label} change not detected within "
                                   f"{timeout:.1f}s (best score={strongest:.1f})")
            self.pause(.06)

    def wait_for_shop_still(self, phase, timeout=1.5):
        """Let item rows settle after refresh/drag before trusting matching.

        PipeWire may deliver a new frame within ~7ms while the shop's list is
        still moving. Inspect just the item/icon column, where we match.
        """
        if self.stream is None:
            return
        _, _, w, h = self.s["region"]
        ys = slice(round(h*.10), round(h*.91))
        xs = slice(round(w*.39), round(w*.56))
        previous = cv2.cvtColor(self.raw(f"{phase}-settle-0")[ys, xs], cv2.COLOR_BGR2GRAY)
        deadline = time.monotonic() + timeout
        stable = 0
        while time.monotonic() < deadline:
            self.pause(.10)
            current = cv2.cvtColor(self.raw(f"{phase}-settle")[ys, xs], cv2.COLOR_BGR2GRAY)
            motion = float(np.mean(cv2.absdiff(previous, current)))
            stable = stable + 1 if motion < 2.5 else 0
            if stable >= 2:
                return
            previous = current
        self.log(f"{phase}: item column did not settle within {timeout:.1f}s; retrying scan rather than assuming no items")

    def buy_button_state(self, frame, target):
        """Read the brightness of the Buy label: white=available, dim=0/1.

        This is an explicit guard for the PC client's disabled Buy button;
        undecidable screenshots fail closed instead of blindly clicking.
        """
        x, y, w, h = self.s["region"]
        cx = round(w * .9375)  # Center of the Buy text, not the 1/1 counter.
        cy = target[1] - y
        half_w, half_h = round(w * .024), round(h * .022)
        if not (0 <= cy-half_h and cy+half_h < frame.shape[0] and
                0 <= cx-half_w and cx+half_w < frame.shape[1]):
            return "uncertain", 0.0
        gray = cv2.cvtColor(frame[cy-half_h:cy+half_h, cx-half_w:cx+half_w], cv2.COLOR_BGR2GRAY)
        brightness = float(np.percentile(gray, 95))
        if brightness >= 175:
            return "available", brightness
        if brightness <= 150:
            return "sold", brightness
        return "uncertain", brightness

    def purchase(self, hit, phase, before):
        self.check()
        x, y, w, h = self.s["region"]
        item = hit["item"]
        # Retain upstream's icon-row-to-Buy-button mapping.
        target = (x + round(w * .90), hit["desktop_y"] + round(h * .085))
        if not (x + .82 * w < target[0] < x + .98 * w and y + .06*h < target[1] < y + .94*h):
            raise RuntimeError(f"Unsafe Buy position for {item}: {target}")
        self.log(f"{phase}: {item} confidence={hit['confidence']} at {target}")
        if not self.s["live"]:
            return False
        # Check every shop, including after a manual Resume. This prevents
        # accidentally buying a row that the user purchased while paused.
        state, brightness = self.buy_button_state(before, target)
        self.log(f"{item}: Buy state={state} (label brightness={brightness:.0f})")
        if state == "sold":
            self.log(f"{item}: already purchased (0/1); skipping")
            return False
        if state == "uncertain":
            raise RuntimeError(f"Unable to verify Buy button availability for {item}")
        self.save_frame(f"before-buy-{phase}-{item}", before)
        self.click(target)
        try:
            after = self.wait_for_change(before, f"dialog-{phase}-{item}")
        except RuntimeError:
            state, brightness = self.buy_button_state(self.latest_frame, target)
            if state == "sold":
                self.log(f"{item}: no dialog and disabled Buy button detected (brightness={brightness:.0f}); skipping")
                return False
            raise
        # Candidate confirmation coordinates from the upstream program.
        # These are experimental on Steam/Proton; run live only while supervised.
        self.click((x + round(w*.55), y + round(h*.70)))
        # Poll for the actual sold row; the old dialog-dismissal change score
        # could fire early during a reward animation.
        while not self.verify_sold(before, target, item, phase):
            self.intervene(
                f"{item} purchase not verified as 0/1. Inspect the shop. "
                "Complete or dismiss any dialog manually; Resume rechecks this SAME row, "
                "Stop ends the run. No extra purchase will be attempted automatically.")
            measured = setup_window(self.s["region"], stop_check=self.check, log=self.log)
            if measured != self.s["region"]:
                raise RuntimeError("Window geometry changed during purchase intervention")
        self.counts[item] += 1
        self.publish_stats()
        self.log(f"{item}: purchase counted only after row sold verification")
        return True

    def shop_half(self, name):
        x, y, w, h = self.s["region"]
        self.check()
        result = self.screen(f"{name}-pass-0")
        candidates = [hit for hit in result["hits"]
                      if .40*w < hit["x"] < .54*w and .05*h < hit["y"] < .90*h]
        self.log(f"{name} pass 0: {json.dumps(candidates)}")
        if not candidates:
            if self.stream is None:
                return
            # One cheap delayed retry protects against a fleeting animation
            # frame, especially immediately after refresh/scroll transitions.
            self.pause(.15)
            result = self.screen(f"{name}-empty-recheck")
            candidates = [hit for hit in result["hits"]
                          if .40*w < hit["x"] < .54*w and .05*h < hit["y"] < .90*h]
            self.log(f"{name} empty recheck: {json.dumps(candidates)}")
            if not candidates:
                return

        # Confirm the whole set in a single second screenshot. Keep the
        # visible row coordinates, then visit the Buy buttons one by one.
        self.pause(0.15)
        verified = self.screen(f"{name}-batch-recheck")
        targets = []
        for hit in sorted(candidates, key=lambda v: v["desktop_y"]):
            match = next((v for v in verified["hits"] if v["item"] == hit["item"]
                          and abs(v["desktop_y"] - hit["desktop_y"]) <= 15
                          and .40*w < v["x"] < .54*w), None)
            if match is None:
                self.log(f"{name}: {hit['item']} not stable on batch recheck; skipping unverified row")
                continue
            targets.append(match)
        self.log(f"{name}: {len(targets)} verified item(s) queued")

        for index, hit in enumerate(targets):
            self.checkpoint()
            before = verified["frame"] if index == 0 else self.raw(f"{name}-next-item-{index}")
            if index:
                # Prior purchase may animate over another item. Revalidate
                # its icon *at the same row* against this fresh screenshot.
                # Retry only if necessary; no unconditional animation wait.
                for retry in range(3):
                    found, _ = detect(before, self.s["threshold"],
                                      selected={hit["item"]}, scales=self.s["scales"],
                                      search_box=(round(w*.36), round(h*.03), round(w*.22), round(h*.93)))
                    if any(abs(v["y"] - hit["y"]) <= 15 and
                           .40*w < v["x"] < .54*w for v in found):
                        break
                    self.log(f"{name}: {hit['item']} temporarily obscured; retry {retry+1}/3")
                    self.pause(0.25)
                    before = self.raw(f"{name}-retry-{index}-{retry}")
                else:
                    raise RuntimeError(f"{hit['item']} row not visible before queued purchase; stopped safely")
            self.purchase(hit, name, before=before)

    def scroll(self, downward):
        x, y, w, h = self.s["region"]
        low = (x + round(w*.54), y + round(h*.72))
        high = (x + round(w*.54), y + round(h*.38))
        self.log("Scroll shop down" if downward else "Scroll shop up")
        if self.s["live"]:
            self.check()
            started = time.perf_counter()
            try:
                drag(low, high, stop_check=self.check) if downward else drag(high, low, stop_check=self.check)
            finally:
                self.timings["scroll"] += time.perf_counter() - started
            self.pause(0.5 if self.s["speed"] == "balanced" else 0.3)

    def refresh(self):
        x, y, w, h = self.s["region"]
        if not self.s["live"]:
            self.log("DRY RUN: would refresh once")
            return
        if not can_refresh(self.counts["refreshes"], self.s["limit_mode"], self.s["limit_value"]):
            raise Cancelled("Skystone limit reached before refreshing")
        before = self.latest_frame if self.latest_frame is not None else self.raw("before-refresh")
        self.save_frame("before-refresh", before)
        self.click((x + round(w*.20), y + round(h*.90)))
        after = self.wait_for_change(before, "refresh-dialog")
        self.click((x + round(w*.58), y + round(h*.65)))
        done = self.wait_for_change(after, "after-refresh", timeout=3.0)
        self.counts["refreshes"] += 1
        self.publish_stats()

    def run(self):
        self.started_at = time.monotonic()
        self.started_utc = datetime.now(timezone.utc).isoformat()
        status = "error"
        try:
            marker = active_run_path()
            if marker.exists():
                try:
                    previous = json.loads(marker.read_text())
                    os.kill(int(previous["pid"]), 0)
                    if int(previous["pid"]) != os.getpid():
                        raise RuntimeError("Another Secret Shop process is already active")
                except ProcessLookupError:
                    pass  # Stale marker from an exited process.
                except (ValueError, KeyError, json.JSONDecodeError):
                    pass
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({"pid": os.getpid(), "directory": str(self.folder)}))
            self.publish_stats()
            self.log(f"Mode: {'LIVE' if self.s['live'] else 'TEST (READ-ONLY)'}; "
                     f"items={sorted(self.s['items'])}; "
                     f"limit={self.s['limit_mode']}:{self.s['limit_value']}")
            if self.s["auto_window"]:
                self.log("Preparing Epic Seven window (no game input yet)")
                measured = setup_window(self.s["region"], stop_check=self.check, log=self.log)
                self.s["region"] = measured
                self.s["scales"] = (recognition_scale(measured[2]),)
                self.on_region(measured)
            if self.s.get("continuous"):
                from continuous_capture import ContinuousCapture
                self.log("Opening KDE PipeWire sharing picker; select the Epic Seven window")
                self.stream = ContinuousCapture(self.s["region"], self.log, self.check)
                # The sharing picker may have changed focus. Restore and
                # revalidate geometry before any automated game interaction.
                measured = setup_window(self.s["region"], stop_check=self.check, log=self.log)
                if measured != self.s["region"]:
                    raise RuntimeError("Epic Seven geometry changed after PipeWire calibration")
                self.log("CONTINUOUS CAPTURE ACTIVE (verified Epic Seven stream)")
            if not self.s["live"]:
                self.cycle_id = 1
                self.shop_half("top")
                self.log("READ-ONLY TEST: top shop scanned; no scrolling, clicking, buying, or refreshing")
                status = "test"
                return
            # Scan the initial shop AND the shop revealed by the final paid
            # refresh. A run capped at N refreshes examines N+1 shops.
            while True:
                self.checkpoint()
                if self.loop_started_at is None:
                    self.loop_started_at = time.monotonic()
                self.cycle_id += 1
                self.log(f"Shop {self.cycle_id} scan started (paid refreshes: {self.counts['refreshes']})")
                while True:
                    self.checkpoint()
                    try:
                        if self.cycle_id > 1:
                            self.wait_for_shop_still("after-refresh")
                        self.shop_half("top")
                        self.checkpoint()
                        self.scroll(True)
                        self.wait_for_shop_still("after-scroll")
                        self.shop_half("bottom")
                        self.checkpoint()
                        break
                    except Cancelled:
                        raise
                    except Exception as err:
                        if self.latest_frame is not None:
                            cv2.imwrite(str(self.folder / "intervention-shop.png"), self.latest_frame)
                        self.intervene(
                            f"Shop scan/input error: {type(err).__name__}: {err}. "
                            "Manually close all dialogs and return THIS shop to its TOP. "
                            "Resume will recheck the window and restart THIS shop's scans; "
                            "Stop ends the run.")
                        measured = setup_window(self.s["region"], stop_check=self.check, log=self.log)
                        if measured != self.s["region"]:
                            raise RuntimeError("Window geometry changed during shop recovery")
                        self.log("Rescanning current shop after manual intervention (no refresh sent)")
                self.shops_reviewed += 1
                self.publish_stats()
                self.log(f"Shop {self.cycle_id} fully reviewed")
                if self.s["limit_mode"] == "refreshes" and not can_refresh(
                        self.counts["refreshes"], "refreshes", self.s["limit_value"]):
                    self.log("Refresh count reached; final shop reviewed without another refresh")
                    break
                if self.s["limit_mode"] == "skystones" and not can_refresh(
                        self.counts["refreshes"], "skystones", self.s["limit_value"]):
                    self.log("Skystone budget reached; final shop reviewed without another refresh")
                    break
                try:
                    self.checkpoint()
                    self.refresh()
                except Cancelled:
                    raise
                except Exception as err:
                    self.intervene(
                        f"Refresh outcome uncertain: {type(err).__name__}: {err}. "
                        "Check the game manually. Resume ONLY after ensuring the refresh "
                        "completed and the NEW shop is at its TOP. "
                        "Resume conservatively counts one paid refresh; Stop ends the run.")
                    measured = setup_window(self.s["region"], stop_check=self.check, log=self.log)
                    if measured != self.s["region"]:
                        raise RuntimeError("Window geometry changed during refresh recovery")
                    self.counts["refreshes"] += 1
                    self.publish_stats()
                    self.log("Manually acknowledged refresh counted (3 Skystones); no retry click sent")
                self.log(f"Refresh {self.counts['refreshes']} completed; "
                         f"spent {self.counts['refreshes']*3} Skystones")
                self.pause(self.s["delay"])
            self.log(f"Run complete: {self.cycle_id} shops scanned, "
                     f"{self.counts['refreshes']} paid refreshes; no further refreshes")
            status = "complete"
        except Cancelled as err:
            status = "stopped"
            self.log(str(err))
        except Exception as err:
            self.log(f"STOPPED ON ERROR: {type(err).__name__}: {err}")
            if self.latest_frame is not None:
                cv2.imwrite(str(self.folder / "error-last-screen.png"), self.latest_frame)
        finally:
            self.ended_at = time.monotonic()
            perf = self.performance_snapshot()
            self.log(f"Performance: elapsed={perf['elapsed']:.1f}s, "
                     f"refreshes/min={perf['rate']:.2f}, frames={perf['frames']}; "
                     + ", ".join(f"{name}={seconds:.1f}s" for name, seconds in perf["timings"].items()))
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            summary = {**self.counts, "shops_reviewed": self.shops_reviewed,
                       "expected": {item: round(value, 3)
                                    for item, value in expected_appearances(self.shops_reviewed).items()},
                       "performance": perf}
            (self.folder / "summary.json").write_text(json.dumps(summary, indent=2))
            try:
                record_session(self.history_id, self.started_utc, status, self.s,
                               {"counts": self.counts, "shops_reviewed": self.shops_reviewed,
                                "expected": expected_appearances(self.shops_reviewed),
                                "performance": perf})
            except Exception as err:
                self.log(f"Session history could not be saved: {err}")
            marker = active_run_path()
            if marker.exists():
                try:
                    if json.loads(marker.read_text()).get("directory") == str(self.folder):
                        marker.unlink()
                except (OSError, json.JSONDecodeError):
                    pass
            self.log(f"Saved diagnostics: {self.folder}")


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("E7 Shop Reroller")
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        compact = screen_w < 1100 or screen_h < 850
        self.compact_layout = compact
        self.root.geometry(f"{min(1160, max(760, screen_w - 32))}x"
                           f"{min(800, max(570, screen_h - 64))}")
        self.root.minsize(min(980, max(760, screen_w - 32)),
                          min(650, max(570, screen_h - 64)))
        self.root.configure(background="#101923")
        self.stopped = threading.Event()
        self.worker = None
        self.active_runner = None
        self.region = [tk.StringVar(value=v) for v in ("100", "50", "1280", "720")]
        self.threshold = tk.StringVar(value="0.70")
        self.delay = tk.StringVar(value="0.35")
        self.change = tk.StringVar(value="8.0")
        self.continuous = tk.BooleanVar(value=False)
        self.max_refreshes = tk.StringVar(value="10")
        self.skystone_cap = tk.StringVar(value="30")
        self.limit_mode = tk.StringVar(value="refreshes")
        self.items = {name: tk.BooleanVar(value=(name != "friendship"))
                      for name in ("covenant", "mystic", "friendship")}
        self._settings_save_job = None
        self._apply_preferences(load_settings())
        self.stat_updates = []
        self.region_updates = []
        self.stat_labels = {}
        self.window_dialog = None
        self.window_test = None
        self.hover_tips = []
        self._setup_theme()
        self.icons = {}
        for name in ("covenant", "mystic", "friendship", "skystone"):
            source = ROOT / "assets" / "gui" / f"{name}.png"
            # Normalize actual nontransparent artwork instead of source-canvas
            # dimensions: these assets have very different transparent margins.
            icon_size = 26 if name == "skystone" else (44 if compact else 60)
            self.icons[name] = self._load_icon(source, icon_size)

        shell = ttk.Frame(self.root, padding=10 if compact else 18)
        shell.pack(fill="both", expand=True)
        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 7 if compact else 14))
        ttk.Label(header, text="E7 SHOP REROLLER", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="KDE Plasma · Wayland", style="Muted.TLabel").pack(side="right")

        body = ttk.Frame(shell)
        body.pack(fill="both", expand=True)
        # Every run option is visible across the top. The log alone expands
        # vertically, so no important controls live inside a scrolling pane.
        options = ttk.Frame(body)
        options.pack(fill="x", pady=(0, 5 if compact else 10))
        for column in range(3):
            options.grid_columnconfigure(column, weight=1, uniform="options")

        purchases = ttk.LabelFrame(options, text="ITEMS TO PURCHASE", padding=9)
        purchases.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        for name in ("covenant", "mystic", "friendship"):
            row = ttk.Frame(purchases)
            row.pack(fill="x", pady=2)
            icon_cell = ttk.Frame(row, width=50 if compact else 68,
                                  height=46 if compact else 62)
            icon_cell.pack(side="left")
            icon_cell.pack_propagate(False)
            ttk.Label(icon_cell, image=self.icons[name]).pack(expand=True)
            ttk.Checkbutton(row, text={"covenant":"Covenant Bookmarks", "mystic":"Mystic Medals",
                                        "friendship":"Friendship Points"}[name],
                            variable=self.items[name]).pack(side="left")

        limits = ttk.LabelFrame(options, text="RUN LIMIT", padding=9)
        limits.grid(row=0, column=1, sticky="nsew", padx=4)
        r1 = ttk.Frame(limits)
        r1.pack(fill="x", pady=4)
        ttk.Radiobutton(r1, text="Paid refreshes", variable=self.limit_mode,
                        value="refreshes").pack(side="left")
        self.help_icon(r1, "Stop after this many paid 3-Skystone refreshes.\n\n"
                            "The starting shop and the final refreshed shop are both reviewed.")
        ttk.Entry(r1, textvariable=self.max_refreshes, width=12).pack(side="right")
        r2 = ttk.Frame(limits)
        r2.pack(fill="x", pady=4)
        ttk.Radiobutton(r2, text="Skystones spent", variable=self.limit_mode,
                        value="skystones").pack(side="left")
        self.help_icon(r2, "The maximum number of Skystones the app is allowed to spend on refreshes.")
        ttk.Entry(r2, textvariable=self.skystone_cap, width=12).pack(side="right")
        currency_note = ttk.Frame(limits)
        currency_note.pack(anchor="w", pady=(8, 0))
        ttk.Label(currency_note, image=self.icons["skystone"]).pack(side="left", padx=(0, 6))
        ttk.Label(currency_note, text="Each refresh costs 3 Skystones", style="Muted.TLabel").pack(side="left")

        advanced = ttk.LabelFrame(options, text="RECOGNITION & INPUT", padding=9)
        advanced.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        for label, variable, tip in (
            ("Match threshold", self.threshold,
             "Minimum confidence required to recognize an item (0 to 1).\n\n"
             "Lower values may detect more items but risk false positives. "
             "Higher values may miss items.\n\nDefault: 0.70."),
            ("Input delay (seconds)", self.delay,
             "Time the app waits after each mouse click.\n\n"
             "Lower is faster but may outpace game animations.\n\n"
             "Allowed: 0.20–10 seconds. 0.20 has been tested successfully."),
            ("Dialog-change score", self.change,
             "Visual change required to recognize a Buy or Refresh dialog.\n\n"
             "Too low may accept other animations; too high may miss a real dialog. "
             "The app retries when no change is detected.\n\nDefault: 8.0.")):
            row = ttk.Frame(advanced)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=label).pack(side="left")
            self.help_icon(row, tip)
            ttk.Entry(row, textvariable=variable, width=12).pack(side="right")
        capture_row = ttk.Frame(advanced)
        capture_row.pack(anchor="w", pady=(5, 0))
        ttk.Checkbutton(capture_row, text="Continuous capture",
                        variable=self.continuous).pack(side="left")
        self.help_icon(capture_row, "Checked: PipeWire window video stream (fast, requires "
                       "selecting Epic Seven in KDE's sharing dialog).\n\n"
                       "Unchecked: individual Spectacle screenshots (slower, no stream picker).")
        self.window_settings_button = ttk.Button(advanced, text="Window setup & calibration…",
                                                  command=self.open_window_settings)
        self.window_settings_button.pack(fill="x", pady=(6, 0))

        console = self.section_frame(body, "ACTIVITY LOG",
                       "Shows what the app is doing during a run: detected items, "
                       "purchases, refreshes, timing information, and errors.\n\n"
                       "Use these messages to understand a pause or troubleshoot a failed run.", padding=8)
        console.pack(fill="both", expand=True)
        log_frame = ttk.Frame(console)
        log_frame.pack(fill="both", expand=True)
        self.logbox = tk.Text(log_frame, state="disabled", wrap="word", font=("Monospace", 10),
                              background="#0a1119", foreground="#cbd6de", insertbackground="#e6d4a5",
                              borderwidth=0, highlightthickness=0, padx=10, pady=10)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)

        footer = ttk.Frame(shell)
        # Reserve the bottom controls before allocating the flexible middle
        # area. Tk packers otherwise give the tall log/settings area priority,
        # hiding Start/Pause/End Session below the window at launch.
        footer.pack(side="bottom", fill="x", pady=(5 if compact else 10, 0), before=body)
        stats = self.section_frame(footer, "SHOP STATISTICS  ·  PURCHASED / EXPECTED",
                       "Compares purchased items with statistically expected appearances.\n\n"
                       "Per item slot at Secret Shop Level 13:\n"
                       "Covenant: 0.6602509%\n"
                       "Mystic: 0.1700646%\n"
                       "Friendship: 19.1772874%\n\n"
                       "Expected = fully reviewed shops × 6 slots × item chance.\n"
                       "These are averages, not guaranteed results.", padding=7)
        stats.pack(fill="x", pady=(0, 6))
        for column in range(3):
            stats.grid_columnconfigure(column, weight=1)
        for col, item in enumerate(("covenant", "mystic", "friendship")):
            cell = ttk.Frame(stats)
            cell.grid(row=0, column=col, sticky="w", padx=(5, 24))
            icon_cell = ttk.Frame(cell, width=50 if compact else 66,
                                  height=46 if compact else 62)
            icon_cell.pack(side="left")
            icon_cell.pack_propagate(False)
            ttk.Label(icon_cell, image=self.icons[item]).pack(expand=True)
            textcol = ttk.Frame(cell)
            textcol.pack(side="left")
            ttk.Label(textcol, text=item.title(), style="Muted.TLabel").pack(anchor="w")
            figures = ttk.Frame(textcol)
            figures.pack(anchor="w")
            actual = ttk.Label(figures, text="0", style="Count.TLabel")
            actual.pack(side="left")
            ttk.Label(figures, text=" / ", style="Muted.TLabel").pack(side="left")
            expected = ttk.Label(figures, text="0.00", style="Muted.TLabel")
            expected.pack(side="left")
            self.stat_labels[item] = (actual, expected)
        self.shop_label = ttk.Label(stats, text="Fully reviewed shops: 0  ·  Paid refreshes: 0", style="Muted.TLabel")
        self.shop_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        performance = self.section_frame(footer, "PERFORMANCE  ·  CURRENT RUN",
                       "Measures how fast the app is running.\n\n"
                       "Refreshes/min shows completed paid refreshes per minute; ETA estimates "
                       "time remaining.\n\n"
                       "The breakdown shows time spent capturing frames, recognizing items, "
                       "moving the cursor, scrolling, and waiting.", padding=6)
        performance.pack(fill="x", pady=(0, 6))
        self.perf_main = ttk.Label(performance, text="Elapsed: —  ·  Refreshes/min: —  ·  ETA: —",
                                   style="Muted.TLabel")
        self.perf_main.pack(anchor="w")
        self.perf_breakdown = ttk.Label(performance,
                                         text="Capture: —  ·  Recognition: —  ·  Cursor: —  ·  Scroll: —  ·  Waiting: —",
                                         style="Muted.TLabel")
        self.perf_breakdown.pack(anchor="w", pady=(2, 0))
        history_bar = ttk.Frame(footer)
        history_bar.pack(fill="x", pady=(0, 6))
        self.lifetime_label = ttk.Label(history_bar, text="Lifetime totals: loading…", style="Muted.TLabel")
        self.lifetime_label.pack(side="left")
        ttk.Button(history_bar, text="Export JSON", command=lambda: self.export_history("json")).pack(side="right")
        ttk.Button(history_bar, text="Export CSV", command=lambda: self.export_history("csv")).pack(side="right", padx=(0, 8))
        ttk.Button(history_bar, text="Session history…", command=self.open_session_history).pack(side="right", padx=(0, 8))
        controls = ttk.Frame(footer)
        controls.pack(fill="x")
        self.start = ttk.Button(controls, text="▶  Start run", style="Start.TButton", command=self.start_run)
        self.start.pack(side="left", padx=(0, 8))
        self.test_run = ttk.Button(controls, text="Test scan (read-only)", command=lambda: self.start_run(test=True))
        self.test_run.pack(side="left", padx=(0, 8))
        self.pause_button = ttk.Button(controls, text="Ⅱ  PAUSE", style="Stop.TButton",
                                       command=self.toggle_pause_run, state="disabled")
        self.pause_button.pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="■  End session", command=self.stop_run).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Setup Global PAUSE/RESUME Shortcut",
                   command=self.copy_stop_command).pack(side="right")
        ttk.Label(footer, text="Expected = reviewed shops × 6 slots × in-game odds. Purchases require sold-row confirmation, not inventory OCR.",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        for variable in [*self.region, self.threshold, self.delay, self.change,
                         self.continuous, self.max_refreshes, self.skystone_cap,
                         self.limit_mode, *self.items.values()]:
            variable.trace_add("write", self._schedule_preferences)
        self._refresh_history_totals()
        self.root.after(200, self.poll)

    def _apply_preferences(self, data):
        if not isinstance(data, dict):
            return
        values = data.get("region")
        if isinstance(values, list) and len(values) == 4:
            try:
                measured = tuple(int(value) for value in values)
                self.validate_region(measured)
                for variable, value in zip(self.region, measured):
                    variable.set(str(value))
            except (ValueError, TypeError):
                pass
        for key, variable in (("threshold", self.threshold), ("delay", self.delay),
                              ("change", self.change), ("max_refreshes", self.max_refreshes),
                              ("skystone_cap", self.skystone_cap)):
            value = data.get(key)
            if isinstance(value, (str, int, float)) and len(str(value)) < 32:
                variable.set(str(value))
        if isinstance(data.get("continuous"), bool):
            self.continuous.set(data["continuous"])
        if data.get("limit_mode") in ("refreshes", "skystones"):
            self.limit_mode.set(data["limit_mode"])
        if isinstance(data.get("items"), dict):
            for name, variable in self.items.items():
                value = data["items"].get(name)
                if isinstance(value, bool):
                    variable.set(value)

    def _collect_preferences(self):
        return {"version": 1, "region": [v.get() for v in self.region],
                "threshold": self.threshold.get(), "delay": self.delay.get(),
                "change": self.change.get(), "continuous": self.continuous.get(),
                "max_refreshes": self.max_refreshes.get(),
                "skystone_cap": self.skystone_cap.get(),
                "limit_mode": self.limit_mode.get(),
                "items": {name: value.get() for name, value in self.items.items()}}

    def _schedule_preferences(self, *_args):
        if self._settings_save_job is not None:
            self.root.after_cancel(self._settings_save_job)
        self._settings_save_job = self.root.after(500, self._persist_preferences)

    def _persist_preferences(self):
        self._settings_save_job = None
        try:
            save_settings(self._collect_preferences())
        except OSError as err:
            self.log(f"Preferences could not be saved: {err}")

    def _refresh_history_totals(self):
        try:
            data = totals()
            self.lifetime_label.configure(
                text=f'Lifetime: {data["runs"]} runs  ·  {data["refreshes"]} refreshes  ·  '
                     f'{data["skystones"]} Skystones  ·  '
                     f'C {data["covenant"]} / M {data["mystic"]} / F {data["friendship"]}')
        except Exception as err:
            self.lifetime_label.configure(text=f"Session history unavailable: {err}")

    def export_history(self, fmt):
        extension = ".csv" if fmt == "csv" else ".json"
        path = filedialog.asksaveasfilename(
            parent=self.root, title=f"Export session history ({fmt.upper()})",
            defaultextension=extension, initialfile=f"e7-shop-history{extension}",
            filetypes=[("CSV files", "*.csv")] if fmt == "csv" else [("JSON files", "*.json")])
        if not path:
            return
        try:
            count = export_sessions(path, fmt)
        except Exception as err:
            messagebox.showerror("Export failed", str(err), parent=self.root)
        else:
            messagebox.showinfo("Export complete", f"Exported {count} sessions to:\n{path}", parent=self.root)

    def open_session_history(self):
        try:
            records = sessions()
        except Exception as err:
            messagebox.showerror("Session history", str(err), parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("E7 Shop Reroller · Session history")
        dialog.geometry("1060x460")
        dialog.configure(background="#101923")
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        columns = ("started_utc", "status", "shops_reviewed", "paid_refreshes",
                   "skystones_spent", "covenant_bought", "mystic_bought",
                   "friendship_bought", "elapsed_seconds")
        table = ttk.Treeview(frame, columns=columns, show="headings", height=14)
        labels = ("Started (UTC)", "Result", "Shops", "Refreshes", "Skystones",
                  "Covenant", "Mystic", "Friendship", "Seconds")
        for column, label in zip(columns, labels):
            table.heading(column, text=label)
            table.column(column, width=190 if column == "started_utc" else 90,
                         anchor="w" if column in ("started_utc", "status") else "center")
        for row in records:
            table.insert("", "end", values=[f'{row[column]:.1f}' if column == "elapsed_seconds"
                                                 else row[column] for column in columns])
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        table.pack(fill="both", expand=True)
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Label(controls, text=f"{len(records)} saved sessions (including stopped and test runs)",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(controls, text="Export CSV", command=lambda: self.export_history("csv")).pack(side="right", padx=(8, 0))
        ttk.Button(controls, text="Export JSON", command=lambda: self.export_history("json")).pack(side="right")
        ttk.Button(controls, text="Clear history & data…", command=lambda: self.open_clear_data(dialog)).pack(side="right", padx=(0, 8))

    def section_frame(self, parent, title, description, padding):
        # A labelframe's labelwidget occupies the existing border/title slot.
        # Packing a separate header above the frame added an unwanted blank
        # row and could squeeze the activity log to almost zero height.
        heading = ttk.Frame(parent)
        ttk.Label(heading, text=title, style="Section.TLabel").pack(side="left")
        self.help_icon(heading, description)
        return ttk.LabelFrame(parent, labelwidget=heading, padding=padding)

    def help_icon(self, parent, description):
        label = tk.Label(parent, text="?", cursor="question_arrow", foreground="#efc977",
                         background="#101923", font=("Sans", 10, "bold"), padx=5)
        label.pack(side="left")
        tip = HoverTip(self.root, label, description)
        self.hover_tips.append(tip)
        return label

    def open_clear_data(self, history_dialog=None):
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Session active", "End the current session before clearing data.",
                                   parent=self.root)
            return
        marker = active_run_path()
        if marker.exists():
            try:
                pid = int(json.loads(marker.read_text(encoding="utf-8"))["pid"])
                os.kill(pid, 0)
            except (ValueError, KeyError, OSError):
                pass
            else:
                messagebox.showwarning("Session active", "Another Secret Shop session may be running. "
                                       "End it before clearing data.", parent=self.root)
                return

        dialog = tk.Toplevel(self.root)
        dialog.title("E7 Shop Reroller · Clear stored data")
        dialog.geometry("490x295")
        dialog.resizable(False, False)
        dialog.configure(background="#101923")
        panel = ttk.Frame(dialog, padding=18)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="CLEAR STORED DATA", style="Title.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Choose what to remove. This cannot be undone. Export first if needed.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 12))
        erase_sessions = tk.BooleanVar(value=True)
        erase_diagnostics = tk.BooleanVar(value=False)
        reset_preferences = tk.BooleanVar(value=False)
        ttk.Checkbutton(panel, text="Session database (history and lifetime statistics)",
                        variable=erase_sessions).pack(anchor="w", pady=3)
        ttk.Checkbutton(panel, text="Run diagnostic folders (screenshots and summaries)",
                        variable=erase_diagnostics).pack(anchor="w", pady=3)
        ttk.Checkbutton(panel, text="Reset saved preferences to defaults",
                        variable=reset_preferences).pack(anchor="w", pady=3)
        buttons = ttk.Frame(panel)
        buttons.pack(side="bottom", fill="x", pady=(12, 0))

        def confirm_clear():
            choices = [description for selected, description in (
                (erase_sessions.get(), "session history and lifetime totals"),
                (erase_diagnostics.get(), "run diagnostic folders"),
                (reset_preferences.get(), "saved settings")) if selected]
            if not choices:
                return
            if not messagebox.askyesno("Confirm permanent deletion",
                                       "Permanently clear:\n\n• " + "\n• ".join(choices) +
                                       "\n\nExport any records you want to keep first. Continue?",
                                       icon="warning", parent=dialog):
                return
            try:
                if erase_sessions.get():
                    clear_sessions()
                if erase_diagnostics.get():
                    directory = run_history_dir()
                    # Never recurse into a symlink or an unexpected directory.
                    if directory.is_symlink() or directory.resolve().parent != directory.parent.resolve():
                        raise RuntimeError("Unexpected diagnostics directory; refusing to delete")
                    if directory.is_dir():
                        shutil.rmtree(directory)
                if reset_preferences.get():
                    self.reset_preferences()
                self._refresh_history_totals()
            except Exception as err:
                messagebox.showerror("Clear failed", str(err), parent=dialog)
                return
            dialog.destroy()
            if history_dialog is not None and history_dialog.winfo_exists():
                history_dialog.destroy()
            messagebox.showinfo("Stored data cleared", "Selected data was cleared successfully.",
                                parent=self.root)

        ttk.Button(buttons, text="Clear selected…", style="Stop.TButton",
                   command=confirm_clear).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right")
        dialog.transient(self.root)
        dialog.grab_set()

    def reset_preferences(self):
        if self._settings_save_job is not None:
            self.root.after_cancel(self._settings_save_job)
            self._settings_save_job = None
        for variable, value in zip(self.region, ("100", "50", "1280", "720")):
            variable.set(value)
        for variable, value in ((self.threshold, "0.70"), (self.delay, "0.35"),
                                (self.change, "8.0"), (self.max_refreshes, "10"),
                                (self.skystone_cap, "30"), (self.limit_mode, "refreshes")):
            variable.set(value)
        self.continuous.set(False)
        for name, variable in self.items.items():
            variable.set(name != "friendship")
        if self._settings_save_job is not None:
            self.root.after_cancel(self._settings_save_job)
            self._settings_save_job = None
        self._persist_preferences()

    def _load_icon(self, path, size):
        """Fit transparent artwork into a uniform square without stretching.

        Recognition still uses the untouched assets/*.png templates.
        """
        picture = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if picture is None or picture.ndim != 3:
            raise RuntimeError(f"Missing GUI icon: {path}")
        if picture.shape[2] == 3:
            picture = cv2.cvtColor(picture, cv2.COLOR_BGR2BGRA)
        # Transparent margins differ substantially: Covenant's art occupies
        # ~79% of its source width, while Mystic reaches every edge. Crop only
        # the transparent padding, then fit each visible silhouette equally.
        visible = cv2.findNonZero((picture[:, :, 3] > 0).astype(np.uint8))
        if visible is None:
            raise RuntimeError(f"Empty GUI icon: {path}")
        x, y, width, height = cv2.boundingRect(visible)
        artwork = picture[y:y+height, x:x+width]
        scale = min((size - 6) / width, (size - 6) / height)
        new_width = max(1, round(width * scale))
        new_height = max(1, round(height * scale))
        resized = cv2.resize(artwork, (new_width, new_height), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((size, size, 4), dtype=np.uint8)
        top, left = (size - new_height) // 2, (size - new_width) // 2
        canvas[top:top+new_height, left:left+new_width] = resized
        ok, encoded = cv2.imencode(".png", canvas)
        if not ok:
            raise RuntimeError(f"Failed to prepare GUI icon: {path}")
        return tk.PhotoImage(data=base64.b64encode(encoded.tobytes()).decode("ascii"), format="png")

    def _setup_theme(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#101923")
        style.configure("TLabel", background="#101923", foreground="#e1e6e9", font=("Sans", 10))
        style.configure("Title.TLabel", foreground="#ebca83", font=("Sans", 21, "bold"))
        style.configure("Section.TLabel", foreground="#dbc085", font=("Sans", 10, "bold"))
        style.configure("Muted.TLabel", foreground="#99a9b8", font=("Sans", 9))
        style.configure("Count.TLabel", foreground="#efd498", font=("Sans", 16, "bold"))
        style.configure("TLabelframe", background="#101923", bordercolor="#354655", relief="solid")
        style.configure("TLabelframe.Label", background="#101923", foreground="#dbc085",
                        font=("Sans", 10, "bold"))
        style.configure("TCheckbutton", background="#101923", foreground="#e1e6e9", font=("Sans", 10))
        style.configure("TRadiobutton", background="#101923", foreground="#e1e6e9")
        style.map("TCheckbutton", background=[("active", "#101923")], foreground=[("active", "#ffffff")])
        style.map("TRadiobutton", background=[("active", "#101923")], foreground=[("active", "#ffffff")])
        style.configure("TEntry", fieldbackground="#182736", foreground="#f4f5f7", bordercolor="#435364", padding=5)
        style.configure("TButton", background="#283b4b", foreground="#f0f2f3", padding=(12, 9), borderwidth=0)
        style.map("TButton", background=[("active", "#3a5365"), ("disabled", "#25313a")])
        style.configure("Start.TButton", background="#22654c", foreground="#ffffff", font=("Sans", 10, "bold"))
        style.map("Start.TButton", background=[("active", "#328866"), ("disabled", "#25313a")])
        style.configure("Stop.TButton", background="#783b3e", foreground="#ffffff", font=("Sans", 10, "bold"))
        style.map("Stop.TButton", background=[("active", "#985055")])

    def open_window_settings(self):
        if self.window_dialog is not None and self.window_dialog.winfo_exists():
            self.window_dialog.lift()
            self.window_dialog.focus_force()
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("E7 Shop Reroller · Window setup")
        dialog.geometry("460x285")
        dialog.resizable(False, False)
        dialog.configure(background="#101923")
        self.window_dialog = dialog
        panel = ttk.Frame(dialog, padding=18)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="WINDOW CALIBRATION", style="Title.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Content rectangle in desktop screenshot pixels", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        fields = ttk.Frame(panel)
        fields.pack(fill="x")
        geometry_help = (
            "Left edge of the game content in desktop screenshot coordinates. "
            "Normally detected and corrected automatically.",
            "Top edge of the game content in desktop screenshot coordinates. "
            "Normally detected and corrected automatically.",
            "Desired game content width in pixels. Tested at 1280; changing "
            "resolution may affect item matching and click coordinates.",
            "Desired game content height in pixels. Tested at 720; the game "
            "may enforce its own 16:9 size.",
        )
        for i, (label, variable) in enumerate(zip(("X", "Y", "Width", "Height"), self.region)):
            cell = ttk.Frame(fields)
            cell.grid(row=0, column=i, sticky="w", padx=(0, 10))
            heading = ttk.Frame(cell)
            heading.pack(anchor="w")
            ttk.Label(heading, text=label).pack(side="left")
            self.help_icon(heading, geometry_help[i])
            ttk.Entry(cell, textvariable=variable, width=9).pack(pady=(4, 0))
        ttk.Label(panel, text="The game is automatically moved and resized at startup.",
                  style="Muted.TLabel").pack(anchor="w", pady=(15, 3))
        ttk.Label(panel, text="A verified 1280×720 result is accepted if the game adjusts 1280×710.",
                  style="Muted.TLabel").pack(anchor="w")
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", side="bottom", pady=(15, 0))
        self.window_test = ttk.Button(buttons, text="Test Window Setup", command=self.test_window_setup)
        self.window_test.pack(side="left")
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="right")
        if self.worker:
            self.window_test.configure(state="disabled")

    def log(self, line):
        self.lines.append(line)

    def poll(self):
        active = bool(self.worker and self.worker.is_alive() and self.active_runner is not None)
        paused = active and self.active_runner.paused.is_set()
        self.pause_button.configure(state="normal" if active else "disabled",
                                    text="▶  RESUME" if paused else "Ⅱ  PAUSE")
        if self.active_runner is not None:
            perf = self.active_runner.performance_snapshot()
            eta = (f'{perf["remaining"]:.0f}s' if perf["remaining"] is not None else
                   ('—' if perf['refreshes'] == 0 else '0s'))
            self.perf_main.configure(
                text=f'Elapsed: {perf["elapsed"]:.0f}s  ·  '
                     f'Refreshes/min: {perf["rate"]:.2f}  ·  '
                     f'ETA: {eta}  ·  Frames: {perf["frames"]}')
            timings = perf["timings"]
            self.perf_breakdown.configure(
                text='  ·  '.join(f'{name.title()}: {timings[name]:.1f}s' for name in
                                 ('capture', 'matching', 'cursor', 'scroll', 'waiting')))
        while self.region_updates:
            geometry = self.region_updates.pop(0)
            for variable, value in zip(self.region, geometry):
                variable.set(str(value))
        while self.stat_updates:
            stats = self.stat_updates.pop(0)
            for item, (actual, expected) in self.stat_labels.items():
                actual.configure(text=str(stats["counts"].get(item, 0)))
                expected.configure(text=f'{stats["expected"][item]:.2f}')
            self.shop_label.configure(text=f'Fully reviewed shops: {stats["shops"]} · '
                                           f'Paid refreshes: {stats["counts"]["refreshes"]}')
        while self.lines:
            line = self.lines.pop(0)
            self.logbox.configure(state="normal")
            self.logbox.insert("end", line + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")
        if self.worker and not self.worker.is_alive():
            self._refresh_history_totals()
            self.start.configure(state="normal")
            self.test_run.configure(state="normal")
            self.window_settings_button.configure(state="normal")
            if self.window_test is not None and self.window_test.winfo_exists():
                self.window_test.configure(state="normal")
            self.worker = None
        self.root.after(200, self.poll)

    def start_run(self, test=False):
        if self.worker:
            return
        try:
            region = tuple(int(v.get()) for v in self.region)
            threshold = float(self.threshold.get())
            delay = float(self.delay.get())
            change = float(self.change.get())
            limit_mode = self.limit_mode.get()
            limit_value = int(self.max_refreshes.get() if limit_mode == "refreshes" else self.skystone_cap.get())
            selected = {name for name, enabled in self.items.items() if enabled.get()}
            if not (0 < threshold <= 1 and .2 <= delay <= 10 and 1 <= change <= 100):
                raise ValueError("Invalid threshold, delay, or change score")
            self.validate_region(region)
            if not selected:
                raise ValueError("Select at least one item")
            if limit_mode not in ("refreshes", "skystones"):
                raise ValueError("Choose a run limit")
            if limit_mode == "refreshes" and not (1 <= limit_value <= 1000000):
                raise ValueError("Refresh count must be between 1 and 1,000,000")
            if limit_mode == "skystones" and not (3 <= limit_value <= 1000000000):
                raise ValueError("Skystone budget must be between 3 and 1,000,000,000")
        except ValueError as err:
            messagebox.showerror("Invalid settings", str(err))
            return
        estimated_refreshes = limit_value if limit_mode == "refreshes" else limit_value // 3
        if not test and not messagebox.askyesno(
            "Confirm LIVE mode",
            f"This may buy {', '.join(sorted(selected))} and spend up to "
            f"{estimated_refreshes * 3:,} Skystones across "
            f"{estimated_refreshes:,} refreshes.\n\n"
            "Purchases require a visible 1/1 → 0/1 transition, but inventory "
            "and currency totals are not independently verified. "
            "Keep the Pause/Resume shortcut accessible. Continue?"):
            return
        self.stopped.clear()
        self._persist_preferences()
        self.start.configure(state="disabled")
        self.test_run.configure(state="disabled")
        self.window_settings_button.configure(state="disabled")
        if self.window_test is not None and self.window_test.winfo_exists():
            self.window_test.configure(state="disabled")
        runner = Runner({"region": region, "threshold": threshold, "delay": delay,
                         "min_change": change, "live": not test,
                         "continuous": self.continuous.get(),
                         "limit_mode": limit_mode, "limit_value": limit_value,
                         "items": selected, "speed": "fast",
                         "auto_window": True,
                         "detailed": False,
                         "scales": (recognition_scale(region[2]),)},
                        self.log, self.stopped, self.stat_updates.append,
                        self.region_updates.append)
        self.active_runner = runner
        self.worker = threading.Thread(target=runner.run, daemon=True)
        self.worker.start()

    @staticmethod
    def validate_region(region):
        if region[0] < 0 or region[1] < 0 or region[2] < 300 or region[3] < 300:
            raise ValueError("Invalid game content region")

    def test_window_setup(self):
        if self.worker:
            return
        try:
            region = tuple(int(v.get()) for v in self.region)
            self.validate_region(region)
        except ValueError as err:
            messagebox.showerror("Invalid region", str(err))
            return
        self.stopped.clear()
        self.start.configure(state="disabled")
        self.test_run.configure(state="disabled")
        self.window_settings_button.configure(state="disabled")
        if self.window_test is not None and self.window_test.winfo_exists():
            self.window_test.configure(state="disabled")

        def task():
            try:
                self.log("Testing window setup only: no mouse input, buys, or refreshes")
                def check():
                    if self.stopped.is_set():
                        raise Cancelled("Window setup test stopped")
                measured = setup_window(region, stop_check=check, log=self.log)
                self.region_updates.append(measured)
                self.log("WINDOW SETUP TEST PASSED. Ready to scan the shop.")
            except Exception as err:
                self.log(f"WINDOW SETUP TEST FAILED: {type(err).__name__}: {err}")
        self.worker = threading.Thread(target=task, daemon=True)
        self.worker.start()

    def stop_run(self):
        self.stopped.set()
        if self.active_runner is not None:
            self.active_runner.resume_requested.set()
        self.log("Stop requested")

    def pause_run(self):
        if self.worker and self.worker.is_alive() and self.active_runner is not None:
            self.active_runner.pause_requested.set()
            self.log("Pause requested; waiting for the next safe checkpoint")

    def toggle_pause_run(self):
        if self.active_runner is None:
            return
        if (self.active_runner.paused.is_set() or self.active_runner.pause_requested.is_set()
                or (self.active_runner.folder / "PAUSE").exists()):
            self.resume_run()
        else:
            self.pause_run()

    def resume_run(self):
        if self.worker and self.worker.is_alive() and self.active_runner is not None:
            if self.active_runner.paused.is_set():
                self.active_runner.resume_requested.set()
            else:
                self.active_runner.pause_requested.clear()
                (self.active_runner.folder / "PAUSE").unlink(missing_ok=True)
                self.log("Pending pause cancelled")

    def copy_stop_command(self):
        installed_command = shutil.which("e7-shop-reroller-toggle")
        command = (shlex.quote(installed_command) if installed_command else
                   f"{shlex.quote(sys.executable)} {shlex.quote(str(ROOT / 'stop_shop.py'))}")
        dialog = tk.Toplevel(self.root)
        dialog.title("E7 Shop Reroller · Global shortcut setup")
        dialog.geometry("640x460")
        dialog.resizable(False, False)
        dialog.configure(background="#101923")
        panel = ttk.Frame(dialog, padding=18)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="GLOBAL PAUSE / RESUME SHORTCUT",
                  style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        steps = (
            "1. Click Copy Command below.\n\n"
            "2. Open KDE System Settings → Keyboard → Shortcuts.\n\n"
            "3. Click Add New → Command or Script.\n\n"
            "4. Name it E7 Shop Reroller - Pause/Resume and paste the command.\n\n"
            "5. Assign a free shortcut (for example Ctrl+Alt+Shift+F12).\n\n"
            "6. Click Apply. Start a run and test the shortcut."
        )
        ttk.Label(panel, text=steps, justify="left", wraplength=590).pack(anchor="w")
        ttk.Label(panel, text="Command to run:", style="Muted.TLabel").pack(anchor="w", pady=(12, 4))
        command_field = ttk.Entry(panel, width=78)
        command_field.insert(0, command)
        command_field.configure(state="readonly")
        command_field.pack(fill="x")
        ttk.Label(panel, text="Toggles Pause/Resume for an active session; it does not start a run.",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))
        buttons = ttk.Frame(panel)
        buttons.pack(side="bottom", fill="x", pady=(10, 0))
        status = ttk.Label(buttons, text="", style="Muted.TLabel")
        status.pack(side="left", padx=(12, 0))

        def copy_command():
            self.root.clipboard_clear()
            self.root.clipboard_append(command)
            self.root.update_idletasks()
            status.configure(text="Command copied to clipboard")

        ttk.Button(buttons, text="Copy Command", command=copy_command).pack(side="left")
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side="right")

    def close(self):
        if self.worker:
            self.stop_run()
            messagebox.showinfo("Stopping", "Stop requested. Wait for the run to finish before closing.")
            return
        self._persist_preferences()
        self.root.destroy()

    def run(self):
        self.lines = []
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
