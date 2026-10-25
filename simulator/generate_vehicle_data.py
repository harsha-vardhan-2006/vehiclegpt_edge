"""Deterministic synthetic vehicle-data generator (fixed seed).

Rates follow config/settings.yaml. Everything written is labelled
data_maturity='simulated' - never presented as a real vehicle measurement.
"""
from __future__ import annotations

import argparse
import math
import random
from datetime import datetime, timedelta

from simulator.scenarios import build_plans
from storage.database import (DB_PATH, connect, fmt, init_db, load_settings,
                              load_signal_dictionary)

PRIMARY = ["vehicle_speed", "soc", "range_estimate", "energy_rate",
           "consumption_running", "battery_temp", "motor_temp", "ambient_temp"]
SECONDARY = ["tyre_pressure_fl", "tyre_pressure_fr", "tyre_pressure_rl",
             "tyre_pressure_rr", "dc_bus_voltage", "aux_battery_voltage",
             "motor_rpm", "cabin_temp", "hvac_power", "regen_energy",
             "odo_vehicle", "inverter_temp"]
AMBIENT_ONLY = ["ambient_temp"]

EV_CAPACITY_KWH = 58.0
CITY_BASE = 145.0     # Wh/km
HIGHWAY_BASE = 180.0  # Wh/km


def _ambient(day: datetime, hour: float) -> float:
    seasonal = 26.0 - 6.0 * math.sin((day.timetuple().tm_yday / 365.0) * 2 * math.pi)
    diurnal = 6.0 * math.sin(((hour - 9.0) / 24.0) * 2 * math.pi)
    return seasonal + diurnal


def generate(settings: dict, conn, rng_seed: int | None = None) -> dict:
    sim = settings["simulation"]
    days = int(sim["days"])
    end = datetime.strptime(sim["end_time"], "%Y-%m-%d %H:%M:%S")
    start = end - timedelta(days=days)
    seed = rng_seed if rng_seed is not None else int(sim["random_seed"])
    rng = random.Random(seed)
    vehicle_id = sim["vehicle_id"]
    r_pri = float(sim["rates_hz"]["primary_during_trip"])
    r_sec = float(sim["rates_hz"]["secondary_during_trip"])
    r_amb = float(sim["rates_hz"]["ambient_continuous"])

    plans = {p.scenario_id: p for p in build_plans(end, days)}
    a_start = datetime.strptime(plans["A_range_reduction"].ground_truth["change_start"],
                                "%Y-%m-%d %H:%M:%S")
    fade = float(plans["A_range_reduction"].ground_truth["consumption_increase_pct"]) / 100.0
    b_day = datetime.strptime(plans["B_efficiency_drop"].ground_truth["trip_date"], "%Y-%m-%d")
    d_warn = datetime.strptime(plans["D_battery_overheat_context"].ground_truth["warning_ts"],
                               "%Y-%m-%d %H:%M:%S")
    adas_times = plans["C_adas_disengagement"].ground_truth["event_timestamps"].split(";")
    f_gap_start = datetime.strptime(plans["F_data_quality"].ground_truth["gap_start"],
                                    "%Y-%m-%d %H:%M:%S")
    f_spike = datetime.strptime(plans["F_data_quality"].ground_truth["implausible_spike_ts"],
                                "%Y-%m-%d %H:%M:%S")

    sig_rows: list[tuple] = []
    event_rows: list[tuple] = []
    trips: list[tuple] = []
    gt_rows: list[tuple] = []
    ing = fmt(end)
    trip_id = 1000
    odo = 12500.0
    ground = {"capacity_pct": 100.0, "consumption_factor": 1.0}

    # ---- continuous ambient stream (24/7, low rate) --------------------
    t = start
    while t < end:
        sig_rows.append((vehicle_id, None, "ambient_temp", fmt(t),
                         round(_ambient(t, t.hour + t.minute / 60), 2), "C",
                         "sim.ambient", "good", "simulated", ing))
        t += timedelta(seconds=1.0 / r_amb)

    # ---- trips ---------------------------------------------------------
    road_cycle = ["city", "highway", "mixed"]
    n = int(sim["trips_per_day"])
    for d in range(days):
        day = start + timedelta(days=d)
        for k in range(n):
            dep = day.replace(hour=7, minute=40) + timedelta(hours=10 * k, minutes=rng.randint(0, 15))
            # Scenario D day: pin the evening trip so it covers the warning time
            if day.date() == d_warn.date() and k == 1:
                dep = day.replace(hour=17, minute=40)
            if day.date() == f_gap_start.date() and k == 0:
                dep = day.replace(hour=7, minute=40)   # Scenario F: pinned morning trip
            road = road_cycle[(d + k) % 3]
            base = CITY_BASE if road == "city" else HIGHWAY_BASE if road == "highway" else (CITY_BASE + HIGHWAY_BASE) / 2
            dur_min = rng.randint(16, 34) if road != "highway" else rng.randint(22, 40)
            if day.date() == d_warn.date() and k == 1:
                dur_min = 70                    # Scenario D: trip spans the warning (18:40)
            if day.date() == f_gap_start.date() and k == 0:
                dur_min = 40                    # Scenario F: trip spans the 10-minute gap
            trip_id += 1

            # scenario modifiers
            factor = 1.0
            if dep >= a_start:
                factor *= 1.0 + fade          # Scenario A: +10% consumption
            spike_trip = (dep.date() == b_day.date())   # Scenario B: whole-day spike
            if spike_trip:
                factor *= 1.35                # Scenario B
            whkm = base * factor * rng.uniform(0.96, 1.04)
            dist = round(rng.uniform(8, 15) if road == "city" else rng.uniform(22, 42) if road == "highway"
                         else rng.uniform(12, 24), 2)
            energy_kwh = round(whkm * dist / 1000.0, 3)
            # Scenario A also fades usable capacity after a_start
            usable = EV_CAPACITY_KWH * (0.96 if dep >= a_start else 1.0)
            soc0 = rng.uniform(0.55, 0.92)
            end_ts = dep + timedelta(minutes=dur_min)

            trips.append((trip_id, vehicle_id, fmt(dep), fmt(end_ts), dist, road,
                          energy_kwh, "A_range_reduction" if dep >= a_start else None))

            # events: trip start / end
            event_rows.append((vehicle_id, trip_id, "trip_start", "info", fmt(dep),
                               "sim.trip", f"Trip {trip_id} start ({road})", "simulated", None))
            event_rows.append((vehicle_id, trip_id, "trip_end", "info", fmt(end_ts),
                               "sim.trip", f"Trip {trip_id} end ({road})", "simulated", None))

            steps = int(dur_min * 60 * r_pri)
            whkm_run = whkm
            for s in range(steps):
                ts = dep + timedelta(seconds=s / r_pri)
                frac = s / max(steps - 1, 1)
                speed = max(0.0, 55 * math.sin(math.pi * min(1.0, frac * 1.15)) +
                            (18 if road == "city" else 42) + rng.uniform(-4, 4))
                if road == "highway":
                    speed = max(0.0, 92 * math.sin(math.pi * min(1.0, frac * 1.1)) + rng.uniform(-6, 6))
                # Scenario F: implausible spike (validator must catch it)
                spike_hit = ts.strftime("%Y-%m-%d %H:%M:%S") == f_spike.strftime("%Y-%m-%d %H:%M:%S")
                if spike_hit:
                    speed = 262.0
                energy_w = speed * (whkm_run / 3600.0) * (1.0 if road != "city" else 1.05) * 10
                soc = max(0.02, soc0 - (energy_kwh * frac) / usable)
                rng_km = soc * usable
                amb = _ambient(ts, ts.hour + ts.minute / 60)
                # Scenario D: battery temp ramp on the trip ending near the warning
                if abs((ts - d_warn).total_seconds()) < 2400:
                    batt = 38 + 16 * (1 - abs((ts - d_warn).total_seconds()) / 2400)
                    charge = 120.0 if (d_warn - timedelta(minutes=12)) < ts < d_warn else 0.0
                else:
                    batt = amb + 8 + 6 * abs(math.sin(frac * 3))
                    charge = 0.0
                # Scenario F: 10-minute data gap -> no fresh rows (missing, not zero)
                in_gap = day.date() == f_gap_start.date() and \
                    f_gap_start <= ts < f_gap_start + timedelta(minutes=10)
                if not in_gap:
                    sig_rows.append((vehicle_id, trip_id, "vehicle_speed", fmt(ts),
                                     round(speed, 2), "km/h", "sim.can",
                                     "implausible" if spike_hit else "good", "simulated", ing))
                    sig_rows.append((vehicle_id, trip_id, "soc", fmt(ts),
                                     round(soc * 100, 2), "%", "sim.can", "good", "simulated", ing))
                    sig_rows.append((vehicle_id, trip_id, "range_estimate", fmt(ts),
                                     round(rng_km, 2), "km", "sim.can", "good", "simulated", ing))
                    sig_rows.append((vehicle_id, trip_id, "energy_rate", fmt(ts),
                                     round(energy_w / 1000, 3), "kW", "sim.can", "good", "simulated", ing))
                    sig_rows.append((vehicle_id, trip_id, "consumption_running", fmt(ts),
                                     round(whkm_run * (1 + 0.02 * math.sin(frac * 5)), 2),
                                     "Wh/km", "sim.can", "good", "simulated", ing))
                    sig_rows.append((vehicle_id, trip_id, "battery_temp", fmt(ts),
                                     round(batt, 2), "C", "sim.can", "good", "simulated", ing))
                    sig_rows.append((vehicle_id, trip_id, "motor_temp", fmt(ts),
                                     round(amb + 30 + 25 * abs(math.sin(frac * 2)), 2),
                                     "C", "sim.can", "good", "simulated", ing))
                    sig_rows.append((vehicle_id, trip_id, "ambient_temp", fmt(ts),
                                     round(amb, 2), "C", "sim.can", "good", "simulated", ing))
                    if charge:
                        sig_rows.append((vehicle_id, trip_id, "charging_power", fmt(ts),
                                         charge, "kW", "sim.obc", "good", "simulated", ing))

                if in_gap:
                    # Scenario F: exactly 4 stale duplicates (old value re-sent)
                    if s in (600, 640, 680, 720):
                        sig_rows.append((vehicle_id, trip_id, "aux_battery_voltage", fmt(ts),
                                         12.60, "V", "sim.can", "stale", "simulated", ing))
                    continue
                # secondary signals at lower rate
                if s % max(1, int(round(r_pri / r_sec))) == 0:
                    for nm, val, unit in [
                        ("tyre_pressure_fl", 2.35 + rng.uniform(-0.05, 0.05), "bar"),
                        ("tyre_pressure_fr", 2.35 + rng.uniform(-0.05, 0.05), "bar"),
                        ("tyre_pressure_rl", 2.30 + rng.uniform(-0.05, 0.05), "bar"),
                        ("tyre_pressure_rr", 2.30 + rng.uniform(-0.05, 0.05), "bar"),
                        ("dc_bus_voltage", 398 + rng.uniform(-6, 6), "V"),
                        ("aux_battery_voltage", 12.6 + rng.uniform(-0.3, 0.5), "V"),
                        ("motor_rpm", speed * 72, "rpm"),
                        ("cabin_temp", amb + rng.uniform(2, 6), "C"),
                        ("hvac_power", max(0.0, rng.gauss(1.2, 0.4)), "kW"),
                        ("regen_energy", round(frac * energy_kwh * 0.12, 3), "kWh"),
                        ("odo_vehicle", round(odo + dist * frac, 3), "km"),
                        ("inverter_temp", amb + 25 + 20 * abs(math.sin(frac * 2)), "C"),
                    ]:
                        sig_rows.append((vehicle_id, trip_id, nm, fmt(ts), round(val, 3), unit,
                                         "sim.can", "good", "simulated", ing))
            odo += dist
            ground["capacity_pct"] = 96.0 if dep >= a_start else 100.0

            # Scenario D warning fires exactly once, at the pinned time
            if day.date() == d_warn.date() and k == 1:
                event_rows.append((vehicle_id, trip_id, "battery_overtemp_warning", "critical",
                                   fmt(d_warn), "sim.bms",
                                   "Battery temperature above warning threshold",
                                   "simulated", "battery_temp"))
                event_rows.append((vehicle_id, trip_id, "thermal_derating", "warning",
                                   fmt(d_warn + timedelta(seconds=45)), "sim.mcu",
                                   "Power derate active after thermal warning",
                                   "simulated", "motor_temp"))

    # Scenario C events
    for i, ts in enumerate(adas_times):
        event_rows.append((vehicle_id, 1000 + 1 + (i * 7) % (trip_id - 1000), "adas_disengagement",
                           "warning", ts, "sim.adas",
                           "ADAS lateral/longitudinal control handed back to driver",
                           "simulated", None))
    # Additional event types required by the brief
    event_rows.append((vehicle_id, None, "diagnostic_trouble_code", "warning",
                       fmt(f_gap_start + timedelta(hours=3)), "sim.uds",
                       "P0562 - system voltage low (stored, historical)",
                       "simulated", "aux_battery_voltage"))
    event_rows.append((vehicle_id, None, "diagnostic_trouble_code", "info",
                       fmt(start + timedelta(days=20, hours=9)), "sim.uds",
                       "U0126 - lost communication with sensor ECU (intermittent)",
                       "simulated", None))
    event_rows.append((vehicle_id, None, "energy_consumption_spike", "warning",
                       plans["B_efficiency_drop"].ground_truth["trip_start"], "sim.bms",
                       "Energy consumption sharply above the rolling baseline",
                       "simulated", "consumption_running"))
    event_rows.append((vehicle_id, None, "stale_sensor_data", "warning",
                       fmt(f_gap_start), "sim.ingest",
                       "4 stale samples: last value re-sent without update",
                       "simulated", "aux_battery_voltage"))
    # Scenario F events
    event_rows.append((vehicle_id, None, "missing_sensor_data", "warning",
                       fmt(f_gap_start), "sim.ingest",
                       "10-minute gap: no samples received (missing, not zero)",
                       "simulated", None))
    event_rows.append((vehicle_id, None, "implausible_signal_value", "warning",
                       fmt(f_spike), "sim.ingest",
                       "vehicle_speed=262 km/h rejected by plausibility rule",
                       "simulated", "vehicle_speed"))
    event_rows.append((vehicle_id, None, "ingestion_interrupted", "warning",
                       fmt(f_gap_start), "sim.ingest",
                       "Adapter reported interrupted read window", "simulated", None))

    # persist -----------------------------------------------------------
    conn.executemany(
        "INSERT INTO vehicle_signals(vehicle_id, trip_id, signal_name, timestamp, value, unit,"
        " source, quality_status, data_maturity, ingestion_timestamp)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)", sig_rows)
    conn.executemany(
        "INSERT INTO vehicle_events(vehicle_id, trip_id, event_type, severity, timestamp, source,"
        " description, data_maturity, signal_ref) VALUES (?,?,?,?,?,?,?,?,?)", event_rows)
    conn.executemany(
        "INSERT INTO trips(trip_id, vehicle_id, start_time, end_time, distance, road_type,"
        " energy_used, scenario_id) VALUES (?,?,?,?,?,?,?,?)", trips)

    for sid, p in plans.items():
        for k, v in p.ground_truth.items():
            gt_rows.append((sid, k, v, p.description))
    gt_rows.append(("meta", "generator_seed", str(seed), "fixed seed -> reproducible dataset"))
    gt_rows.append(("meta", "dataset_end", fmt(end), "dataset clock for relative queries"))
    gt_rows.append(("meta", "data_maturity", "simulated", "all generated rows are synthetic"))
    conn.executemany(
        "INSERT OR REPLACE INTO scenario_ground_truth(scenario_id, gt_key, gt_value, notes)"
        " VALUES (?,?,?,?)", gt_rows)

    # signal dictionary
    dic = load_signal_dictionary()
    conn.executemany(
        "INSERT OR REPLACE INTO signal_dictionary(signal_name, unit, description, valid_min,"
        " valid_max, source_mapping, conversion_rules) VALUES (?,?,?,?,?,?,?)",
        [(d["signal_name"], d["unit"], d["description"], d["valid_min"], d["valid_max"],
          d["source_mapping"], d["conversion_rules"]) for d in dic.values()])
    conn.commit()
    return {"signal_rows": len(sig_rows), "event_rows": len(event_rows),
            "trips": len(trips), "days": days}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic vehicle history")
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--db", default=None)
    ap.add_argument("--reset", action="store_true", help="delete existing database first")
    args = ap.parse_args()

    settings = load_settings()
    if args.days:
        settings["simulation"]["days"] = args.days
    db_path = args.db or settings["storage"]["db_path"]
    from pathlib import Path
    db_path = Path(db_path)
    if not db_path.is_absolute():
        from storage.database import ROOT
        db_path = ROOT / db_path
    if args.reset and db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    init_db(conn)
    stats = generate(settings, conn)
    size_mb = db_path.stat().st_size / 1e6
    print(f"generated: {stats}  db={db_path}  size={size_mb:.1f} MB")


if __name__ == "__main__":
    main()
