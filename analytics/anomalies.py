"""Anomaly helpers: spikes, missing windows, change points."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from statistics import pstdev

from storage.database import fmt, parse


def zscore_spikes(points: list[tuple[str, float]], threshold: float = 3.0) -> list[dict]:
    vals = [v for _, v in points]
    if len(vals) < 8:
        return []
    mu, sd = sum(vals) / len(vals), pstdev(vals)
    if sd == 0:
        return []
    return [{"timestamp": ts, "value": v, "z": (v - mu) / sd}
            for ts, v in points if abs((v - mu) / sd) >= threshold]


def missing_windows(conn: sqlite3.Connection, signal: str, start: datetime, end: datetime,
                    expected_gap_s: int = 300, within_trips_only: bool = True) -> list[dict]:
    """Gaps where consecutive samples are further apart than expected_gap_s.

    With within_trips_only (default) the lag is computed per trip: the vehicle
    being parked overnight is *not* missing data.
    """
    trip_clause = ("AND trip_id IS NOT NULL" if within_trips_only else "")
    partition = "PARTITION BY trip_id" if within_trips_only else ""
    rows = conn.execute(
        f"WITH s AS (SELECT timestamp, trip_id, "
        f"LAG(timestamp) OVER ({partition} ORDER BY timestamp) prev "
        f"FROM vehicle_signals WHERE signal_name=? AND timestamp>=? AND timestamp<? "
        f"AND value IS NOT NULL {trip_clause}) "
        f"SELECT prev, timestamp, ROUND((julianday(timestamp)-julianday(prev))*86400.0) gap "
        f"FROM s WHERE prev IS NOT NULL "
        f"AND (julianday(timestamp)-julianday(prev))*86400.0 > ? ORDER BY prev",
        (signal, fmt(start), fmt(end), float(expected_gap_s))).fetchall()
    return [{"from": r["prev"], "to": r["timestamp"], "seconds": int(r["gap"])}
            for r in rows]


def quality_summary(conn: sqlite3.Connection, start: datetime, end: datetime) -> dict:
    rows = conn.execute(
        "SELECT quality_status, COUNT(*) n FROM vehicle_signals WHERE timestamp>=? "
        "AND timestamp<? GROUP BY quality_status", (fmt(start), fmt(end))).fetchall()
    return {r["quality_status"]: r["n"] for r in rows}


def change_point(series: list[dict], key: str, min_pct: float = 5.0) -> dict | None:
    """First date where the level shifts persistently by >= min_pct."""
    for prev, cur in zip(series, series[1:]):
        a, b = prev.get(key), cur.get(key)
        if a and b and abs(b - a) / abs(a) * 100 >= min_pct:
            return {"from_date": prev["date"], "to_date": cur["date"],
                    "from": a, "to": b, "pct": (b - a) / abs(a) * 100}
    return None
