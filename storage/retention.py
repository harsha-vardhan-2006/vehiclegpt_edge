"""Retention policy for the warm (SQLite) tier.

Retention window is a configured engineering setting (60 days = "several weeks").
This module prunes only rows older than the window and reports what it removed,
so the behaviour is testable rather than assumed.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from storage.database import fmt, parse


def cutoff_timestamp(dataset_now: datetime, retention_days: int) -> str:
    return fmt(dataset_now - timedelta(days=retention_days))


def prune_older_than(conn: sqlite3.Connection, dataset_now: datetime, retention_days: int) -> dict:
    """Delete signal/event rows older than the retention window. Trips and
    ground truth are kept (small, needed for context)."""
    cut = cutoff_timestamp(dataset_now, retention_days)
    cur1 = conn.execute("DELETE FROM vehicle_signals WHERE timestamp < ?", (cut,))
    cur2 = conn.execute("DELETE FROM vehicle_events WHERE timestamp < ?", (cut,))
    conn.commit()
    return {"cutoff": cut, "signals_deleted": cur1.rowcount, "events_deleted": cur2.rowcount}


def history_span(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts, COUNT(*) AS n "
        "FROM vehicle_signals"
    ).fetchone()
    if not row or row["first_ts"] is None:
        return {"days": 0, "first_ts": None, "last_ts": None, "samples": 0}
    first, last = parse(row["first_ts"]), parse(row["last_ts"])
    return {
        "days": round((last - first).total_seconds() / 86400.0, 2),
        "first_ts": row["first_ts"],
        "last_ts": row["last_ts"],
        "samples": row["n"],
    }


def searchable_window_days(conn: sqlite3.Connection) -> float:
    return history_span(conn)["days"]
