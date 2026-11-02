"""Opt-in persistent PipeWire frame source with strict visual calibration."""
import select
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

from linux_shop import capture


class ContinuousCapture:
    def __init__(self, region, log, stop_check=lambda: None):
        self.region = region
        self.log = log
        self.stop_check = stop_check
        self.previous_stamp = -1
        # KDE's window screencast can include decorations (e.g. a 28px
        # title bar). Calibrate its content offset against Spectacle first.
        self.crop_top = None
        helper = Path(__file__).with_name("pipewire_helper.py")
        self.process = subprocess.Popen(["/usr/bin/python", str(helper)],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, bufsize=0)
        try:
            response = self._line(90)
            if response != b"READY\n":
                raise RuntimeError("PipeWire portal did not establish a stream (check Arch packages and KDE share prompt)")
            self.log("PipeWire stream connected; validating Epic Seven content")
            self._verify()
        except BaseException:
            self.close()
            raise

    def _line(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.stop_check()
            if self.process.poll() is not None:
                raise RuntimeError("PipeWire capture helper exited")
            ready, _, _ = select.select([self.process.stdout], [], [], .2)
            if ready:
                return self.process.stdout.readline()
        raise RuntimeError("Timed out waiting for PipeWire frame")

    def frame(self):
        deadline = time.monotonic() + 5
        while True:
            frame = self._frame_once()
            if frame is not None:
                return frame
            if time.monotonic() > deadline:
                raise RuntimeError("PipeWire is not delivering new frames")
            self.stop_check()
            time.sleep(.015)

    def _frame_once(self):
        self.process.stdin.write(b"FRAME\n")
        header = self._line(5)
        if header == b"WAIT\n":
            raise RuntimeError("PipeWire stream has no frames yet")
        parts = header.split()
        if len(parts) != 5 or parts[0] != b"FRAME":
            raise RuntimeError(f"Unexpected PipeWire frame header: {header[:100]!r}")
        w, h, length, stamp = map(int, parts[1:])
        expected_w, expected_h = self.region[2:]
        if (w != expected_w or h < expected_h or h > expected_h + 80
                or length != w*h*3):
            raise RuntimeError(f"PipeWire captured {w}x{h}, but game content is "
                               f"{expected_w}x{expected_h}; expected game content plus up to 80px of title bar")
        data = bytearray()
        while len(data) < length:
            self.stop_check()
            ready, _, _ = select.select([self.process.stdout], [], [], 5)
            if not ready:
                raise RuntimeError("PipeWire stream stalled")
            chunk = self.process.stdout.read(length-len(data))
            if not chunk:
                raise RuntimeError("PipeWire stream disconnected")
            data.extend(chunk)
        if stamp <= self.previous_stamp:
            return None
        self.previous_stamp = stamp
        image = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3).copy()
        if self.crop_top is not None:
            return image[self.crop_top:self.crop_top + expected_h].copy()
        return image

    def _verify(self):
        from tempfile import TemporaryDirectory
        # Some portal backends start delivering video shortly after READY.
        for _ in range(30):
            try:
                stream = self.frame()
                break
            except RuntimeError as err:
                if "no frames yet" not in str(err):
                    raise
                time.sleep(.1)
        else:
            raise RuntimeError("PipeWire never produced a video frame")
        with TemporaryDirectory(prefix="e7-portal-verify-") as folder:
            path = Path(folder) / "desktop.png"
            capture(path)
            desktop = cv2.imread(str(path))
        x, y, w, h = self.region
        if desktop is None or x+w > desktop.shape[1] or y+h > desktop.shape[0]:
            raise RuntimeError("Cannot verify PipeWire against Spectacle game crop")
        reference = desktop[y:y+h, x:x+w]
        # Downsample and blur: tolerant of small animation differences, but
        # rejects capturing a different window with identical dimensions.
        a = cv2.GaussianBlur(cv2.resize(reference, (160, 90)), (7, 7), 0)
        # Try each possible vertical content offset: a window stream may
        # include KWin's title bar while Spectacle's measured content does not.
        excess = stream.shape[0] - h
        scores = []
        for top in range(excess + 1):
            candidate = stream[top:top+h]
            b = cv2.GaussianBlur(cv2.resize(candidate, (160, 90)), (7, 7), 0)
            scores.append(float(np.mean(cv2.absdiff(a, b))))
        best_top = int(np.argmin(scores))
        difference = scores[best_top]
        self.log(f"PipeWire content crop: top={best_top}px, bottom={excess-best_top}px "
                 f"(stream {stream.shape[1]}x{stream.shape[0]})")
        self.log(f"PipeWire/Spectacle game-frame difference: {difference:.1f}")
        if difference > 24:
            raise RuntimeError("PipeWire frame differs from Epic Seven; select the game window in KDE's picker")
        self.crop_top = best_top

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write(b"QUIT\n")
            except (OSError, ValueError):
                pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
