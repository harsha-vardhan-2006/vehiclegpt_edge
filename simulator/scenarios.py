"""Reproducible driving scenarios A-F with stored ground truth.

Every scenario stores its known answer in scenario_ground_truth so tests can
compare system output against ground truth instead of a hard-coded reply.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class ScenarioPlan:
    scenario_id: str
    name: str
    description: str
    ground_truth: dict = field(default_factory=dict)


def build_plans(end_time: datetime, days: int) -> list[ScenarioPlan]:
    start = end_time - timedelta(days=days)
    # Scenario A: driving-range reduction starts 14 days before the dataset end
    a_start = (end_time - timedelta(days=14)).replace(hour=7, minute=0, second=0)
    a = ScenarioPlan(
        "A_range_reduction",
        "Driving-range reduction",
        "Usable capacity fade + higher consumption from day -14",
        {
            "change_start": a_start.strftime("%Y-%m-%d %H:%M:%S"),
            "usable_capacity_fade_pct": "4.0",
            "consumption_increase_pct": "10.0",
            "usable_capacity_before_kwh": "58.0",
            "usable_capacity_after_kwh": "55.68",
        },
    )
    # Scenario B: one trip with the largest efficiency drop (day -12, morning)
    b_trip_day = start + timedelta(days=days - 12)
    b = ScenarioPlan(
        "B_efficiency_drop",
        "Largest efficiency drop",
        "One driving day with a 35% consumption spike (headwind + preconditioning)",
        {
            "trip_date": b_trip_day.strftime("%Y-%m-%d"),
            "trip_start": b_trip_day.replace(hour=7, minute=40).strftime("%Y-%m-%d %H:%M:%S"),
            "spike_multiplier": "1.35",
        },
    )
    # Scenario C: ADAS disengagements at known timestamps
    y = (end_time - timedelta(days=1)).date()
    c_times = [
        f"{y.isoformat()} 08:12:04",
        f"{y.isoformat()} 08:47:31",
        f"{y.isoformat()} 18:26:12",
        f"{(y - timedelta(days=3)).isoformat()} 09:03:55",
        f"{(y - timedelta(days=6)).isoformat()} 17:51:20",
    ]
    c = ScenarioPlan(
        "C_adas_disengagement",
        "ADAS disengagement history",
        "5 events, 3 of them yesterday",
        {"event_timestamps": ";".join(c_times), "count_yesterday": "3", "total": "5"},
    )
    # Scenario D: battery overheating warning with known preceding context
    d_day = start + timedelta(days=days - 11)
    d_warn = d_day.replace(hour=18, minute=40, second=0)
    d = ScenarioPlan(
        "D_battery_overheat_context",
        "Battery overheating warning context",
        "Temperature ramp + DC fast charge in the 30 min before the warning",
        {
            "warning_ts": d_warn.strftime("%Y-%m-%d %H:%M:%S"),
            "context_window_minutes": "30",
            "preceding_factors": "battery_temp ramp 38->54 C; fast charging at 120 kW; ambient 34 C",
        },
    )
    # Scenario E: city vs highway energy consumption
    e = ScenarioPlan(
        "E_city_vs_highway",
        "City vs highway comparison",
        "City 145 Wh/km baseline, highway 180 Wh/km baseline (drag dominates)",
        {"city_baseline_whkm": "145.0", "highway_baseline_whkm": "180.0"},
    )
    # Scenario F: missing / unreliable data
    f_day = start + timedelta(days=days - 10)
    f = ScenarioPlan(
        "F_data_quality",
        "Missing and unreliable data",
        "10-minute gap inside a trip, stale samples, implausible speed spike, unit mismatch in CSV import",
        {
            "gap_start": f_day.replace(hour=7, minute=50).strftime("%Y-%m-%d %H:%M:%S"),
            "gap_minutes": "10",
            "stale_samples": "4",
            "implausible_spike_ts": f_day.replace(hour=7, minute=45).strftime("%Y-%m-%d %H:%M:%S"),
            "unit_mismatch_file": "data/demo/sample_log_units.csv",
        },
    )
    return [a, b, c, d, e, f]
