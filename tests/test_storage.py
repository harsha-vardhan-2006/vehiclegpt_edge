"""Storage: creation, persistence, indexed queries, retention, history span."""
from __future__ import annotations

from datetime import datetime, timedelta

from storage import retention
from storage.database import connect, fmt, init_db


def test_db_tables_exist(db):
    names = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"vehicle_signals", "vehicle_events", "trips", "signal_dictionary",
            "query_audit", "scenario_ground_truth"} <= names


def test_persistence_across_reconnect(db, testdb_path):
    n1 = db.execute("SELECT COUNT(*) n FROM vehicle_signals").fetchone()["n"]
    c2 = connect(testdb_path, read_only=True)
    n2 = c2.execute("SELECT COUNT(*) n FROM vehicle_signals").fetchone()["n"]
    c2.close()
    assert n1 == n2 and n1 > 100_000


def test_indexes_present(db):
    idx = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_signals_name_ts" in idx and "idx_events_type_ts" in idx and "idx_trips_start" in idx


def test_time_range_query_uses_index(db):
    plan = [r[3] for r in db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM vehicle_signals "
        "WHERE signal_name=? AND timestamp>=? AND timestamp<?",
        ("range_estimate", "2026-10-01 00:00:00", "2026-10-02 00:00:00"))]
    assert any("USING INDEX" in p for p in plan)


def test_event_query_by_type_and_window(db):
    rows = db.execute(
        "SELECT timestamp FROM vehicle_events WHERE event_type=? AND timestamp>=? AND timestamp<? "
        "ORDER BY timestamp", ("adas_disengagement", "2026-10-24 00:00:00",
                               "2026-10-25 00:00:00")).fetchall()
    assert len(rows) == 3


def test_history_spans_at_least_several_weeks(db):
    span = retention.history_span(db)
    assert span["days"] >= 28, span            # >= 4 weeks of searchable history
    assert retention.searchable_window_days(db) >= 28


def test_retention_prune_keeps_window(tmp_path, testdb_path):
    """Pruning to N days must keep exactly the last N days searchable."""
    copy = tmp_path / "ret.db"
    src = connect(testdb_path, read_only=True)
    dst = connect(copy)
    src.backup(dst)
    src.close()
    init_db(dst)
    end = datetime.strptime(dst.execute("SELECT MAX(timestamp) t FROM vehicle_signals")
                            .fetchone()["t"], "%Y-%m-%d %H:%M:%S")
    res = retention.prune_older_than(dst, end, 20)
    assert res["signals_deleted"] > 0
    span = retention.history_span(dst)
    assert 19.0 <= span["days"] <= 21.0, span
    dst.close()


def test_parameterised_sql_only(db):
    """Raw question text can never reach SQL - templates use bound params."""
    from query_engine import sql_templates
    evil = "x'; DROP TABLE trips; --"
    rows = sql_templates.run(db, "events_any_window",
                             {"start": "2026-10-01 00:00:00", "end": "2026-10-02 00:00:00"})
    assert isinstance(rows, list)
    rows2 = sql_templates.run(db, "signal_aggregate_q",
                              {"name": evil, "start": "2026-10-01 00:00:00",
                               "end": "2026-10-02 00:00:00"})
    assert rows2[0]["n"] == 0                   # unknown signal name, no SQL execution
    assert db.execute("SELECT COUNT(*) FROM trips").fetchone()[0] > 0
