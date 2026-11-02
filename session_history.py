"""Persistent local statistics and portable exports (stdlib only)."""
import csv
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


APP_NAME = "e7-shop-reroller"


def config_path():
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME / "settings.json"


def history_path():
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / APP_NAME / "history.sqlite3"


def state_dir():
    """User-writable runtime artifacts; never write into /usr/share."""
    return history_path().parent


def run_history_dir():
    return state_dir() / "run-history"


def active_run_path():
    return state_dir() / "active-run.json"


def load_settings():
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(values):
    """Atomic replacement prevents a crash mid-write from corrupting settings."""
    import tempfile
    destination = config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".settings-", suffix=".json", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(values, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _connect():
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            started_utc TEXT NOT NULL,
            ended_utc TEXT NOT NULL,
            status TEXT NOT NULL,
            items_json TEXT NOT NULL,
            limit_mode TEXT NOT NULL,
            limit_value INTEGER NOT NULL,
            shops_reviewed INTEGER NOT NULL,
            paid_refreshes INTEGER NOT NULL,
            skystones_spent INTEGER NOT NULL,
            covenant_bought INTEGER NOT NULL,
            mystic_bought INTEGER NOT NULL,
            friendship_bought INTEGER NOT NULL,
            covenant_expected REAL NOT NULL,
            mystic_expected REAL NOT NULL,
            friendship_expected REAL NOT NULL,
            elapsed_seconds REAL NOT NULL,
            refreshes_per_minute REAL NOT NULL,
            frames_captured INTEGER NOT NULL,
            capture_seconds REAL NOT NULL,
            matching_seconds REAL NOT NULL,
            cursor_seconds REAL NOT NULL,
            scroll_seconds REAL NOT NULL,
            waiting_seconds REAL NOT NULL
        )
    """)
    # Additive migration: existing v1.0 sessions remain intact. They simply
    # have no per-shop records because those events were not stored before 1.1.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS shop_details (
            session_id TEXT NOT NULL,
            shop_number INTEGER NOT NULL,
            paid_refreshes_before INTEGER NOT NULL,
            elapsed_seconds REAL NOT NULL,
            duration_seconds REAL NOT NULL,
            covenant_bought INTEGER NOT NULL,
            mystic_bought INTEGER NOT NULL,
            friendship_bought INTEGER NOT NULL,
            refresh_duration_seconds REAL,
            refresh_outcome TEXT NOT NULL,
            offers_json TEXT NOT NULL,
            PRIMARY KEY (session_id, shop_number),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)
    return connection


def record_session(session_id, started_utc, status, settings, summary):
    counts = summary["counts"]
    perf = summary["performance"]
    expected = summary["expected"]
    timing = perf["timings"]
    columns = ["session_id", "started_utc", "ended_utc", "status", "items_json",
               "limit_mode", "limit_value", "shops_reviewed", "paid_refreshes",
               "skystones_spent", "covenant_bought", "mystic_bought", "friendship_bought",
               "covenant_expected", "mystic_expected", "friendship_expected",
               "elapsed_seconds", "refreshes_per_minute", "frames_captured",
               "capture_seconds", "matching_seconds", "cursor_seconds", "scroll_seconds",
               "waiting_seconds"]
    values = [session_id, started_utc, datetime.now(timezone.utc).isoformat(), status,
              json.dumps(sorted(settings["items"])), settings["limit_mode"], settings["limit_value"],
              summary["shops_reviewed"], counts["refreshes"], counts["refreshes"] * 3,
              counts["covenant"], counts["mystic"], counts["friendship"],
              expected["covenant"], expected["mystic"], expected["friendship"],
              perf["elapsed"], perf["rate"], perf["frames"], timing["capture"],
              timing["matching"], timing["cursor"], timing["scroll"], timing["waiting"]]
    with closing(_connect()) as connection, connection:
        connection.execute(f'INSERT OR REPLACE INTO sessions ({", ".join(columns)}) '
                           f'VALUES ({", ".join("?" for _ in columns)})', values)
        connection.execute("DELETE FROM shop_details WHERE session_id = ?", (session_id,))
        for shop in summary.get("shops", []):
            connection.execute("""
                INSERT INTO shop_details
                (session_id, shop_number, paid_refreshes_before, elapsed_seconds,
                 duration_seconds, covenant_bought, mystic_bought,
                 friendship_bought, refresh_duration_seconds, refresh_outcome,
                 offers_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (session_id, shop["shop_number"], shop["paid_refreshes_before"],
                  shop["elapsed_seconds"], shop["duration_seconds"],
                  shop["purchased"]["covenant"], shop["purchased"]["mystic"],
                  shop["purchased"]["friendship"], shop.get("refresh_duration_seconds"),
                  shop.get("refresh_outcome", "not_requested"), json.dumps(shop["offers"])))


def sessions():
    with closing(_connect()) as connection:
        return [dict(row) for row in connection.execute(
            "SELECT * FROM sessions ORDER BY started_utc DESC")]


def session_shops(session_id):
    with closing(_connect()) as connection:
        records = [dict(row) for row in connection.execute(
            "SELECT * FROM shop_details WHERE session_id = ? ORDER BY shop_number",
            (session_id,))]
    for shop in records:
        shop["offers"] = json.loads(shop.pop("offers_json"))
    return records


def totals():
    with closing(_connect()) as connection:
        return dict(connection.execute("""
            SELECT count(*) AS runs, coalesce(sum(shops_reviewed),0) AS shops,
                   coalesce(sum(paid_refreshes),0) AS refreshes,
                   coalesce(sum(skystones_spent),0) AS skystones,
                   coalesce(sum(covenant_bought),0) AS covenant,
                   coalesce(sum(mystic_bought),0) AS mystic,
                   coalesce(sum(friendship_bought),0) AS friendship
            FROM sessions WHERE status <> 'test'
        """).fetchone())


def clear_sessions():
    """Remove stored session records; leave the SQLite schema and settings intact."""
    with closing(_connect()) as connection, connection:
        count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        connection.execute("DELETE FROM shop_details")
        connection.execute("DELETE FROM sessions")
    return count


def export_sessions(destination, fmt):
    rows = sessions()
    if fmt == "csv":
        with open(destination, "w", newline="", encoding="utf-8") as handle:
            if rows:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            else:
                handle.write("session_id,started_utc,ended_utc,status\n")
    elif fmt == "json":
        for row in rows:
            row["items"] = json.loads(row.pop("items_json"))
        Path(destination).write_text(json.dumps({"format_version": 1, "sessions": rows}, indent=2) + "\n",
                                     encoding="utf-8")
    else:
        raise ValueError(f"Unsupported export format: {fmt}")
    return len(rows)


def export_shop_details(destination, fmt, session_id=None):
    """Export a detailed session (or all sessions) including shop/offer events.

    CSV uses one record per detected offer, with a placeholder record for an
    empty shop. JSON preserves each shop's nested list of detected offers.
    Existing sessions with no details remain visible with an empty shops list.
    """
    records = [row for row in sessions() if session_id is None or row["session_id"] == session_id]
    if fmt == "json":
        for row in records:
            row["items"] = json.loads(row.pop("items_json"))
            row["shops"] = session_shops(row["session_id"])
        Path(destination).write_text(
            json.dumps({"format_version": 2, "sessions": records}, indent=2) + "\n",
            encoding="utf-8")
    elif fmt == "csv":
        columns = ("session_id", "started_utc", "status", "shop_number",
                   "paid_refreshes_before", "shop_elapsed_seconds", "shop_duration_seconds",
                   "covenant_bought", "mystic_bought", "friendship_bought",
                   "refresh_duration_seconds", "refresh_outcome",
                   "phase", "item", "confidence", "outcome")
        with open(destination, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in records:
                shops = session_shops(row["session_id"])
                if not shops:
                    writer.writerow({"session_id": row["session_id"],
                                     "started_utc": row["started_utc"],
                                     "status": row["status"],
                                     "outcome": "no_shop_details_recorded"})
                for shop in shops:
                    common = {"session_id": row["session_id"],
                              "started_utc": row["started_utc"], "status": row["status"],
                              "shop_number": shop["shop_number"],
                              "paid_refreshes_before": shop["paid_refreshes_before"],
                              "shop_elapsed_seconds": shop["elapsed_seconds"],
                              "shop_duration_seconds": shop["duration_seconds"],
                              "covenant_bought": shop["covenant_bought"],
                              "mystic_bought": shop["mystic_bought"],
                              "friendship_bought": shop["friendship_bought"],
                              "refresh_duration_seconds": shop["refresh_duration_seconds"],
                              "refresh_outcome": shop["refresh_outcome"]}
                    for offer in shop["offers"] or [{}]:
                        writer.writerow({**common, **{k: offer.get(k, "") for k in
                                                      ("phase", "item", "confidence", "outcome")}})
    else:
        raise ValueError(f"Unsupported export format: {fmt}")
    return len(records)
