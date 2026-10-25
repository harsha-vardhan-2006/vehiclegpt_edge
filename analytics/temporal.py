"""Temporal reconstruction: what happened before/after an event."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from storage.database import fmt


def events_between(conn: sqlite3.Connection, start: datetime, end: datetime,
                   event_types: list[str] | None = None, severity: str | None = None) -> list[dict]:
    sql = ("SELECT id, event_type, severity, timestamp, source, description, trip_id, "
           "data_maturity FROM vehicle_events WHERE timestamp>=? AND timestamp<?")
    params: list = [fmt(start), fmt(end)]
    if event_types:
        sql += " AND event_type IN (%s)" % ",".join("?" * len(event_types))
        params.extend(event_types)
    if severity:
        sql += " AND severity=?"
        params.append(severity)
    sql += " ORDER BY timestamp"
    return [dict(r) for r in conn.execute(sql, params)]


def first_event(conn: sqlite3.Connection, event_type: str, start: datetime | None = None,
                end: datetime | None = None) -> dict | None:
    sql = "SELECT id, event_type, severity, timestamp, source, description FROM vehicle_events " \
          "WHERE event_type=?"
    params: list = [event_type]
    if start:
        sql += " AND timestamp>=?"
        params.append(fmt(start))
    if end:
        sql += " AND timestamp<?"
        params.append(fmt(end))
    sql += " ORDER BY timestamp LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def signal_before(conn: sqlite3.Connection, signal: str, when: datetime,
                  window_minutes: int) -> dict:
    start = when - timedelta(minutes=window_minutes)
    rows = conn.execute(
        "SELECT timestamp, value, unit, quality_status FROM vehicle_signals "
        "WHERE signal_name=? AND timestamp>=? AND timestamp<? AND value IS NOT NULL "
        "ORDER BY timestamp", (signal, fmt(start), fmt(when))).fetchall()
    vals = [r["value"] for r in rows]
    return {"signal": signal, "unit": rows[0]["unit"] if rows else None,
            "n": len(vals), "first": vals[0] if vals else None,
            "last": vals[-1] if vals else None, "min": min(vals) if vals else None,
            "max": max(vals) if vals else None,
            "start": fmt(start), "end": fmt(when),
            "quality": sorted({r["quality_status"] for r in rows})}


def trip_of(conn: sqlite3.Connection, when: datetime) -> dict | None:
    row = conn.execute(
        "SELECT trip_id, start_time, end_time, road_type, distance, energy_used FROM trips "
        "WHERE start_time<=? AND end_time>=? ORDER BY start_time LIMIT 1",
        (fmt(when), fmt(when))).fetchone()
    return dict(row) if row else None
