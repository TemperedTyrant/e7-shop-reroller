"""Offline image matching against bundled templates (requires runtime OpenCV)."""
import unittest
import json
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


@unittest.skipUnless(cv2 is not None, "Install python-opencv and python-numpy to test recognition")
class RecognitionTest(unittest.TestCase):
    def setUp(self):
        from linux_shop import detect, prepared_template
        self.detect = detect
        self.prepared_template = prepared_template

    def frame_with(self, positions):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        for item, x, y in positions:
            filename = {"covenant": "cov.png", "mystic": "mys.png",
                        "friendship": "fb.png"}[item]
            template = self.prepared_template(filename, 1.5)
            h, w = template.shape[:2]
            frame[y:y+h, x:x+w] = template
        return frame

    def test_one_currency_offer(self):
        hits, _ = self.detect(self.frame_with([("covenant", 550, 100)]), .8,
                              selected={"covenant"}, scales=(1.5,))
        self.assertEqual([(h["item"], h["y"]) for h in hits], [("covenant", 100)])

    def test_two_offers_of_same_currency(self):
        hits, _ = self.detect(self.frame_with([
            ("friendship", 550, 100), ("friendship", 550, 350)]), .8,
            selected={"friendship"}, scales=(1.5,))
        self.assertEqual(sorted(h["y"] for h in hits), [100, 350])

    def test_different_currencies_on_same_half(self):
        hits, _ = self.detect(self.frame_with([
            ("mystic", 550, 100), ("covenant", 550, 350)]), .8,
            selected={"mystic", "covenant"}, scales=(1.5,))
        self.assertEqual({h["item"] for h in hits}, {"mystic", "covenant"})

    def test_available_sold_and_ambiguous_buy_labels(self):
        from secret_shop_gui import Runner
        from types import SimpleNamespace
        runner = SimpleNamespace(s={"region": (0, 0, 1280, 720)})
        for brightness, expected in ((255, "available"), (100, "sold"),
                                     (160, "uncertain")):
            frame = np.full((720, 1280, 3), brightness, dtype=np.uint8)
            state, _ = Runner.buy_button_state(runner, frame, (1152, 360))
            self.assertEqual(state, expected)

    def test_final_shop_is_scanned_with_no_extra_refresh(self):
        import secret_shop_gui as gui

        for mode, budget in (("refreshes", 10), ("skystones", 30),
                             ("skystones", 31)):
            with self.subTest(mode=mode, budget=budget), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                settings = {"region": (0, 0, 1280, 720), "items": {"friendship"},
                            "auto_window": False, "continuous": False,
                            "live": True, "limit_mode": mode, "limit_value": budget,
                            "threshold": .7, "scales": (1.5,), "delay": 0,
                            "speed": "fast", "detailed": False}
                with patch.object(gui, "run_history_dir", return_value=root), \
                        patch.object(gui, "active_run_path", return_value=root / "active.json"), \
                        patch.object(gui, "record_session"):
                    runner = gui.Runner(settings, lambda _: None, threading.Event(), lambda _: None)
                    visited = []
                    runner.shop_half = lambda half: visited.append((runner.cycle_id, half))
                    runner.scroll = lambda _: None
                    runner.wait_for_shop_still = lambda _: None
                    runner.pause = lambda _: None
                    runner.refresh = lambda: runner.counts.__setitem__(
                        "refreshes", runner.counts["refreshes"] + 1)
                    runner.run()
                    summary = json.loads((runner.folder / "summary.json").read_text())
                    self.assertEqual(summary["refreshes"], 10)
                    self.assertEqual(summary["shops_reviewed"], 11)
                    self.assertEqual(len(visited), 22)
                    self.assertEqual(visited[-1], (11, "bottom"))


if __name__ == "__main__":
    unittest.main()
