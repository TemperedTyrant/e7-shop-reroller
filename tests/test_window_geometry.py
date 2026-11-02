"""Exercise actual geometry selection without importing graphical dependencies."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def geometry_function():
    # Only the pure planner is tested; no KWin script or screenshot is run.
    path = Path(__file__).resolve().parents[1] / "window_setup.py"
    spec = importlib.util.spec_from_file_location("_e7_geometry_test", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
            "cv2": types.ModuleType("cv2"),
            "linux_shop": types.SimpleNamespace(capture=lambda _: None)}):
        spec.loader.exec_module(module)
    return module.choose_content_region


class WindowGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fit = staticmethod(geometry_function())

    @staticmethod
    def monitor(x, y, w, h):
        return {"x": x, "y": y, "width": w, "height": h}

    def test_1080p_preserves_720p_content(self):
        rect = self.fit((100, 50, 1280, 720), [self.monitor(0, 0, 1920, 1080)],
                        (0, 28, 0, 28))
        self.assertEqual(rect[2:], (1280, 720))
        self.assertGreaterEqual(rect[1], 28)

    def test_steam_deck_size_fits(self):
        x, y, w, h = self.fit((100, 50, 1280, 720),
                              [self.monitor(0, 0, 1280, 800)], (0, 28, 0, 28))
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y - 28, 0)
        self.assertLessEqual(x + w, 1280)
        self.assertLessEqual(y + h, 800)

    def test_saved_coordinates_do_not_override_game_monitor(self):
        screens = [self.monitor(0, 360, 1920, 1080),
                   self.monitor(1920, 0, 1024, 768)]
        current = self.monitor(1954, 58, 1020, 562)
        x, y, w, h = self.fit((2560, 374, 1280, 720), screens,
                              (0, 28, 0, 28), current)
        self.assertGreaterEqual(x, 1920)
        self.assertLessEqual(x + w, 2944)
        self.assertLessEqual(y + h, 768)

    def test_small_display_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "minimum safe"):
            self.fit((0, 0, 1280, 720), [self.monitor(0, 0, 800, 480)],
                     (0, 28, 0, 28))

    def test_missing_display_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "no displays"):
            self.fit((0, 0, 1280, 720), [], (0, 28, 0, 28))


if __name__ == "__main__":
    unittest.main()
