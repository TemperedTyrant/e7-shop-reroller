"""Offline accounting rules, without a game, GUI, or mouse access."""
import unittest

from run_policy import can_refresh, expected_appearances, recognition_scale


class RefreshLimitsTest(unittest.TestCase):
    def test_ten_refreshes(self):
        self.assertTrue(can_refresh(9, "refreshes", 10))
        self.assertFalse(can_refresh(10, "refreshes", 10))

    def test_skystone_limits_round_down(self):
        for budget in (30, 31, 32):
            self.assertTrue(can_refresh(9, "skystones", budget))
            self.assertFalse(can_refresh(10, "skystones", budget))
        self.assertTrue(can_refresh(10, "skystones", 33))

    def test_zero_limits(self):
        self.assertFalse(can_refresh(0, "refreshes", 0))
        self.assertFalse(can_refresh(0, "skystones", 2))

    def test_invalid_limits_fail_closed(self):
        for mode, value in (("refreshes", -1), ("skystones", -3), ("unknown", 10)):
            with self.subTest(mode=mode, value=value), self.assertRaises(ValueError):
                can_refresh(0, mode, value)


class ExpectedAndScaleTest(unittest.TestCase):
    def test_expected_slot_counts(self):
        self.assertEqual(expected_appearances(0), {
            "covenant": 0.0, "mystic": 0.0, "friendship": 0.0})
        rates = {"covenant": .006602509, "mystic": .001700646,
                 "friendship": .191772874}
        for name, rate in rates.items():
            self.assertAlmostEqual(expected_appearances(11)[name], 11 * 6 * rate)

    def test_scales_follow_content_width(self):
        self.assertEqual(recognition_scale(1280), 1.5)
        self.assertEqual(recognition_scale(1024), 1.2)
        self.assertEqual(recognition_scale(960), 1.125)
        self.assertEqual(recognition_scale(1008), 1.1812)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            recognition_scale(0)
        with self.assertRaises(ValueError):
            expected_appearances(-1)


if __name__ == "__main__":
    unittest.main()
