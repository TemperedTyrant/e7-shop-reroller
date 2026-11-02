"""Session-detail persistence and portable exports without game dependencies."""
import csv
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from session_history import (record_session, sessions, session_shops,
                             export_sessions, export_shop_details, clear_sessions,
                             history_path)


class SessionHistoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        override = patch.dict(os.environ, {"XDG_STATE_HOME": self.directory.name})
        override.start()
        self.addCleanup(override.stop)

    def save(self, session_id="run-1", shops=None):
        record_session(session_id, "2026-11-02T01:00:00+00:00", "complete",
                       {"items": {"covenant", "friendship"},
                        "limit_mode": "refreshes", "limit_value": 1},
                       {"counts": {"covenant": 1, "mystic": 0,
                                   "friendship": 1, "refreshes": 1},
                        "shops_reviewed": 2,
                        "expected": {"covenant": .08, "mystic": .02, "friendship": 1.44},
                        "performance": {"elapsed": 21, "rate": 2.8, "frames": 45,
                                        "timings": {k: 1.0 for k in
                                                    ("capture", "matching", "cursor", "scroll", "waiting")}},
                        "shops": shops or []})

    def test_shop_details_and_exports(self):
        shops = [{"shop_number": 1, "paid_refreshes_before": 0,
                  "elapsed_seconds": 9.0, "duration_seconds": 9.0,
                  "purchased": {"covenant": 1, "mystic": 0, "friendship": 1},
                  "refresh_duration_seconds": 2.1, "refresh_outcome": "completed",
                  "offers": [{"phase": "top", "item": "covenant", "confidence": .91,
                              "outcome": "purchased"},
                             {"phase": "bottom", "item": "friendship", "confidence": .94,
                              "outcome": "purchased"}]},
                 {"shop_number": 2, "paid_refreshes_before": 1,
                  "elapsed_seconds": 21.0, "duration_seconds": 10.0,
                  "purchased": {"covenant": 0, "mystic": 0, "friendship": 0},
                  "refresh_duration_seconds": None, "refresh_outcome": "not_requested",
                  "offers": []}]
        self.save(shops=shops)
        self.assertEqual(len(session_shops("run-1")), 2)
        self.assertEqual(session_shops("run-1")[0]["offers"][0]["outcome"], "purchased")

        summary_csv = Path(self.directory.name) / "summary.csv"
        self.assertEqual(export_sessions(summary_csv, "csv"), 1)
        with summary_csv.open(newline="") as handle:
            self.assertEqual(list(csv.DictReader(handle))[0]["friendship_expected"], "1.44")

        details_csv = Path(self.directory.name) / "details.csv"
        self.assertEqual(export_shop_details(details_csv, "csv"), 1)
        with details_csv.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)  # Two offers plus one empty shop.
        self.assertEqual(rows[-1]["shop_number"], "2")
        self.assertEqual(rows[-1]["item"], "")
        self.assertEqual(rows[0]["refresh_duration_seconds"], "2.1")

        details_json = Path(self.directory.name) / "details.json"
        export_shop_details(details_json, "json", session_id="run-1")
        payload = json.loads(details_json.read_text())
        self.assertEqual(payload["format_version"], 2)
        self.assertEqual(payload["sessions"][0]["shops"][0]["offers"][1]["item"],
                         "friendship")

        self.assertEqual(clear_sessions(), 1)
        self.assertEqual(sessions(), [])
        self.assertEqual(session_shops("run-1"), [])

    def test_old_sessions_survive_additive_details_migration(self):
        self.save(session_id="old-run")
        # Simulate a pre-v1.1 database that has only the original sessions table.
        connection = sqlite3.connect(history_path())
        connection.execute("DROP TABLE shop_details")
        connection.commit()
        connection.close()

        self.assertEqual(len(sessions()), 1)
        self.assertEqual(session_shops("old-run"), [])
        output = Path(self.directory.name) / "legacy.json"
        export_shop_details(output, "json")
        self.assertEqual(json.loads(output.read_text())["sessions"][0]["shops"], [])
        csv_output = Path(self.directory.name) / "legacy.csv"
        export_shop_details(csv_output, "csv")
        with csv_output.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["outcome"], "no_shop_details_recorded")


if __name__ == "__main__":
    unittest.main()
