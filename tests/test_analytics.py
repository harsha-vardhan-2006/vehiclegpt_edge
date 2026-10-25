"""Analytics: trends, anomalies, temporal ordering, missing-data disclosure."""
from __future__ import annotations

from datetime import datetime

from analytics import anomalies, temporal, trends

END = datetime(2026, 10, 25, 18, 0)


def test_daily_efficiency_and_largest_drop(db):
    start = datetime(2026, 9, 25, 18, 0)
    ser = trends.daily_efficiency(db, start, END)
    assert len(ser) >= 25
    worst = trends.largest_daily_efficiency_drop(ser)
    assert worst is not None
    assert worst["pct"] > 5                       # scenario B spike is clearly visible
    assert worst["to_date"] == "2026-10-13"       # ground truth day


def test_window_stats_and_daily_mean(db):
    st = trends.window_stats(db, "range_estimate", datetime(2026, 10, 11, 18, 0), END)
    assert st["n"] > 1000 and st["mean"] > 0
    dm = trends.daily_mean(db, "range_estimate", datetime(2026, 10, 11, 18, 0), END)
    assert len(dm) >= 13


def test_road_type_comparison(db):
    rows = trends.road_type_comparison(db, datetime(2026, 1, 1), END)
    types = {r["road_type"] for r in rows}
    assert {"city", "highway"} <= types
    hwy = next(r for r in rows if r["road_type"] == "highway")
    city = next(r for r in rows if r["road_type"] == "city")
    assert hwy["whkm"] > city["whkm"]


def test_temporal_events_before_window(db):
    warn = temporal.first_event(db, "battery_overtemp_warning")
    assert warn is not None
    when = datetime.strptime(warn["timestamp"], "%Y-%m-%d %H:%M:%S")
    bt = temporal.signal_before(db, "battery_temp", when, 30)
    assert bt["n"] > 0 and bt["max"] >= 50
    evs = temporal.events_between(db, when.replace(hour=17, minute=0), when)
    assert any(e["event_type"] == "trip_start" for e in evs)


def test_scenario_f_gap_detected_inside_trip(db):
    row = db.execute(
        "SELECT gt_value FROM scenario_ground_truth WHERE scenario_id='F_data_quality'"
        " AND gt_key='gap_start'").fetchone()
    from storage.database import parse
    gap_start = parse(row[0])
    gaps = anomalies.missing_windows(db, "vehicle_speed",
                                     gap_start.replace(hour=0), gap_start.replace(hour=23),
                                     300)
    assert len(gaps) >= 1
    assert 550 <= gaps[0]["seconds"] <= 700       # ~10-minute injected gap


def test_quality_flags_present(db):
    q = anomalies.quality_summary(db, datetime(2026, 1, 1), END)
    assert q.get("stale", 0) == 4
    assert q.get("implausible", 0) == 1
    assert q["good"] > 100_000


def test_zscore_spikes_and_change_point():
    pts = [(f"t{i:03d}", 10.0) for i in range(50)] + [("t999", 60.0)]
    spikes = anomalies.zscore_spikes(pts, 3.0)
    assert any(s["timestamp"] == "t999" for s in spikes)
    series = [{"date": f"d{i}", "mean": 10.0 if i < 10 else 14.0} for i in range(20)]
    cp = anomalies.change_point(series, "mean", 5.0)
    assert cp and cp["to_date"] == "d10"


def test_trip_efficiency_rows(db):
    rows = trends.trip_efficiency(db, datetime(2026, 1, 1), END)
    expected = db.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    assert len(rows) == expected and expected >= 60
    assert all(r["whkm"] > 0 for r in rows)
