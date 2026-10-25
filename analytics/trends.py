"""Trend helpers: windowed aggregates, daily series, trip efficiency."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from storage.database import fmt


def window_stats(conn: sqlite3.Connection, signal: str, start: datetime, end: datetime) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) n, AVG(value) avg_v, MIN(value) min_v, MAX(value) max_v, MIN(unit) unit "
        "FROM vehicle_signals WHERE signal_name=? AND timestamp>=? AND timestamp<? "
        "AND value IS NOT NULL AND quality_status IN ('good','unit_converted')",
        (signal, fmt(start), fmt(end))).fetchone()
    return {"signal": signal, "n": row["n"], "mean": row["avg_v"], "min": row["min_v"],
            "max": row["max_v"], "unit": row["unit"],
            "start": fmt(start), "end": fmt(end)}


def daily_mean(conn: sqlite3.Connection, signal: str, start: datetime, end: datetime) -> list[dict]:
    rows = conn.execute(
        "SELECT substr(timestamp,1,10) d, AVG(value) v, COUNT(*) n FROM vehicle_signals "
        "WHERE signal_name=? AND timestamp>=? AND timestamp<? AND value IS NOT NULL "
        "AND quality_status IN ('good','unit_converted') GROUP BY d ORDER BY d",
        (signal, fmt(start), fmt(end))).fetchall()
    return [{"date": r["d"], "mean": r["v"], "n": r["n"]} for r in rows]


def trip_efficiency(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[dict]:
    """Wh/km per trip from the trips table (exact, not from the model)."""
    rows = conn.execute(
        "SELECT trip_id, date(start_time) d, start_time, road_type, distance, energy_used, "
        "CASE WHEN distance>0 THEN energy_used*1000.0/distance ELSE NULL END whkm "
        "FROM trips WHERE start_time>=? AND start_time<? ORDER BY start_time",
        (fmt(start), fmt(end))).fetchall()
    return [dict(r) for r in rows]


def daily_efficiency(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[dict]:
    rows = conn.execute(
        "SELECT date(start_time) d, AVG(energy_used*1000.0/distance) whkm, COUNT(*) trips, "
        "SUM(distance) km FROM trips WHERE distance>0 AND start_time>=? AND start_time<? "
        "GROUP BY d ORDER BY d", (fmt(start), fmt(end))).fetchall()
    return [{"date": r["d"], "whkm": r["whkm"], "trips": r["trips"], "km": r["km"]} for r in rows]


def largest_daily_efficiency_drop(series: list[dict]) -> dict | None:
    """Biggest day-over-day increase in Wh/km (= efficiency drop)."""
    worst = None
    for prev, cur in zip(series, series[1:]):
        delta = cur["whkm"] - prev["whkm"]
        pct = 100.0 * delta / prev["whkm"] if prev["whkm"] else 0.0
        if worst is None or pct > worst["pct"]:
            worst = {"from_date": prev["date"], "to_date": cur["date"],
                     "from_whkm": prev["whkm"], "to_whkm": cur["whkm"],
                     "delta_whkm": delta, "pct": pct}
    return worst


def road_type_comparison(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[dict]:
    rows = conn.execute(
        "SELECT road_type, COUNT(*) trips, SUM(distance) km, SUM(energy_used) kwh, "
        "SUM(energy_used)*1000.0/NULLIF(SUM(distance),0) whkm FROM trips "
        "WHERE start_time>=? AND start_time<? GROUP BY road_type ORDER BY road_type",
        (fmt(start), fmt(end))).fetchall()
    return [dict(r) for r in rows if r["km"]]
