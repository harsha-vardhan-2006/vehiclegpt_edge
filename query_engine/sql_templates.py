"""Predefined, parameterised SQL templates.

Natural-language text is NEVER interpolated into SQL. Callers pass typed
parameters only; every statement uses bound parameters.
"""
from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "signal_range": (
        "SELECT timestamp, value, unit, quality_status, source, data_maturity, id "
        "FROM vehicle_signals WHERE signal_name=:name AND timestamp>=:start AND timestamp<? "
        "AND value IS NOT NULL ORDER BY timestamp"
    ).replace("timestamp<?", "timestamp<:end"),
    "signal_range_q": (
        "SELECT timestamp, value, unit, quality_status, source, data_maturity, id "
        "FROM vehicle_signals WHERE signal_name=:name AND timestamp>=:start AND timestamp<:end "
        "AND value IS NOT NULL ORDER BY timestamp"
    ),
    "signal_aggregate_q": (
        "SELECT COUNT(*) n, AVG(value) avg_v, MIN(value) min_v, MAX(value) max_v, MIN(unit) unit "
        "FROM vehicle_signals WHERE signal_name=:name AND timestamp>=:start AND timestamp<:end "
        "AND value IS NOT NULL AND quality_status IN ('good','unit_converted')"
    ),
    "events_in_window": (
        "SELECT id, event_type, severity, timestamp, source, description, data_maturity "
        "FROM vehicle_events WHERE timestamp>=:start AND timestamp<:end "
        "AND event_type=:etype ORDER BY timestamp"
    ),
    "events_any_window": (
        "SELECT id, event_type, severity, timestamp, source, description, data_maturity "
        "FROM vehicle_events WHERE timestamp>=:start AND timestamp<:end ORDER BY timestamp"
    ),
    "trips_in_window": (
        "SELECT trip_id, start_time, end_time, distance, road_type, energy_used "
        "FROM trips WHERE start_time>=:start AND start_time<:end ORDER BY start_time"
    ),
    "trips_by_road": (
        "SELECT road_type, COUNT(*) trips, SUM(distance) km, SUM(energy_used) kwh "
        "FROM trips WHERE start_time>=:start AND start_time<:end GROUP BY road_type"
    ),
    "quality_counts": (
        "SELECT quality_status, COUNT(*) n FROM vehicle_signals "
        "WHERE timestamp>=:start AND timestamp<:end GROUP BY quality_status"
    ),
}


def run(conn, name: str, params: dict) -> list[dict]:
    sql = TEMPLATES[name]                     # fixed strings only
    return [dict(r) for r in conn.execute(sql, params)]
