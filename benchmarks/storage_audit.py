"""Storage audit: measure, then calculate. Nothing is assumed.

Usage:  py -m benchmarks.storage_audit

Produces benchmarks/results/storage_audit.json and .md with:
  - measured bytes per sample in SQLite (row + index overhead)
  - measured raw CSV bytes per sample, and measured gzip ratio
  - the official 60 signals @ 10 Hz calculation (51,840,000 samples/day)
  - the actually generated demo dataset size and daily growth
"""
from __future__ import annotations

import gzip
import io
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "benchmarks" / "results"

N_SAMPLES = 500_000
SIGNALS_PER_DAY_10HZ = 60 * 10 * 86400          # 51,840,000 samples/day


def measure_sqlite(path: Path) -> dict:
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(str(path))
    conn.executescript((ROOT / "storage" / "schema.sql").read_text(encoding="utf-8"))
    base = path.stat().st_size

    signals = ["vehicle_speed", "soc", "range_estimate", "energy_rate", "battery_temp",
               "ambient_temp", "consumption_running", "motor_temp"]
    t0 = datetime(2026, 8, 26)
    rows = []
    for i in range(N_SAMPLES):
        ts = (t0 + timedelta(seconds=i // 8)).strftime("%Y-%m-%d %H:%M:%S")
        rows.append(("DEMO-EV-001", 1000 + i % 120, signals[i % len(signals)], ts,
                     round((i % 1000) / 10.0, 2), "km/h", "sim.can", "good", "simulated", ts))
    conn.executemany(
        "INSERT INTO vehicle_signals(vehicle_id, trip_id, signal_name, timestamp, value, unit,"
        " source, quality_status, data_maturity, ingestion_timestamp) VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows)
    conn.commit()
    total = path.stat().st_size - base
    wal = path.with_name(path.name + "-wal")
    if wal.exists():
        total += wal.stat().st_size
    conn.close()
    return {"rows": N_SAMPLES, "bytes_total": total,
            "bytes_per_row_incl_indexes": round(total / N_SAMPLES, 1)}


def measure_csv_gzip(sample_rows: int = 100_000) -> dict:
    from storage.database import connect, load_settings
    settings = load_settings()
    conn = connect(ROOT / settings["storage"]["db_path"], read_only=True)
    cur = conn.execute(
        "SELECT vehicle_id, trip_id, signal_name, timestamp, value, unit, source, "
        "quality_status, data_maturity FROM vehicle_signals LIMIT ?", (sample_rows,))
    buf = io.StringIO()
    header = "vehicle_id,trip_id,signal_name,timestamp,value,unit,source,quality,data_maturity\n"
    buf.write(header)
    n = 0
    for r in cur:
        buf.write(",".join("" if v is None else str(v) for v in r) + "\n")
        n += 1
    conn.close()
    raw = buf.getvalue().encode()
    gz = gzip.compress(raw, compresslevel=6)
    return {"rows": n, "csv_bytes": len(raw), "gzip_bytes": len(gz),
            "bytes_per_sample_csv": round(len(raw) / n, 1),
            "bytes_per_sample_gzip": round(len(gz) / n, 1),
            "gzip_ratio": round(len(raw) / len(gz), 2)}


def main() -> None:
    from storage.database import load_settings
    settings = load_settings()
    db_path = ROOT / settings["storage"]["db_path"]

    sqlite_m = measure_sqlite(ROOT / "data" / "database" / "_storage_audit.db")
    csv_m = measure_csv_gzip()

    per_day_raw = SIGNALS_PER_DAY_10HZ
    demo_days = 60
    demo_bytes = db_path.stat().st_size
    demo_mb_per_day = demo_bytes / 1e6 / demo_days

    report = {
        "official_rate_calculation": {
            "signals": 60, "rate_hz": 10,
            "samples_per_day": per_day_raw,
            "note": "60 x 10 x 86400 = 51,840,000 samples/day (calculation, not a measurement)",
        },
        "measured": {
            "sqlite_bytes_per_row_incl_indexes": sqlite_m["bytes_per_row_incl_indexes"],
            "sqlite_rows_tested": sqlite_m["rows"],
            "csv_bytes_per_sample": csv_m["bytes_per_sample_csv"],
            "gzip_bytes_per_sample": csv_m["bytes_per_sample_gzip"],
            "gzip_ratio": csv_m["gzip_ratio"],
            "note": "measured by inserting/selecting real rows in this environment",
        },
        "extrapolation_full_10hz_sqlite": {
            "gb_per_day": round(per_day_raw * sqlite_m["bytes_per_row_incl_indexes"] / 1e9, 1),
            "gb_30_days": round(30 * per_day_raw * sqlite_m["bytes_per_row_incl_indexes"] / 1e9, 1),
            "gb_60_days": round(60 * per_day_raw * sqlite_m["bytes_per_row_incl_indexes"] / 1e9, 1),
            "label": "ESTIMATE from measured bytes/row",
        },
        "extrapolation_full_10hz_csv_gzip": {
            "gb_per_day": round(per_day_raw * csv_m["bytes_per_sample_gzip"] / 1e9, 2),
            "gb_60_days": round(60 * per_day_raw * csv_m["bytes_per_sample_gzip"] / 1e9, 1),
            "label": "ESTIMATE from measured gzip bytes/sample (columnar/on-disk would differ)",
        },
        "actual_demo_dataset": {
            "path": str(db_path.name),
            "days": demo_days,
            "size_mb": round(demo_bytes / 1e6, 1),
            "mb_per_day": round(demo_mb_per_day, 1),
            "representation": "mixed rate: 1 Hz primary signals during trips, 0.2 Hz secondary, "
                              "ambient every 5 min - i.e. the WARM (decimated) tier, not raw 10 Hz",
            "label": "MEASUREMENT",
        },
        "design_conclusion": (
            "Full-rate 10 Hz x 60 signals cannot live in SQLite for weeks: the measured "
            f"row cost gives ~{round(per_day_raw * sqlite_m['bytes_per_row_incl_indexes'] / 1e9, 1)} GB/day. "
            "The architecture therefore keeps raw frames only for the hot window (48 h, not part of "
            "this prototype's persistence) and stores a decimated warm tier, which the demo dataset "
            f"measures at {round(demo_mb_per_day, 1)} MB/day ({round(demo_mb_per_day*60/1024,1)} GB for 60 days)."
        ),
        "labels": {
            "samples_per_day": "CALCULATION",
            "bytes_per_row": "MEASUREMENT",
            "gb_per_day": "ESTIMATE from measurement",
            "demo_dataset": "MEASUREMENT",
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "storage_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    md = ["# Storage audit", "", "## Calculation (official rate)", "",
          f"60 signals x 10 Hz x 86,400 s = **{per_day_raw:,} samples/day** (CALCULATION).", "",
          "## Measured representations", "",
          "| representation | measured | label |", "|---|---|---|",
          f"| SQLite row incl. indexes | {sqlite_m['bytes_per_row_incl_indexes']} bytes/row "
          f"(over {sqlite_m['rows']:,} rows) | MEASUREMENT |",
          f"| CSV dump | {csv_m['bytes_per_sample_csv']} bytes/sample | MEASUREMENT |",
          f"| gzip of that CSV | {csv_m['bytes_per_sample_gzip']} bytes/sample "
          f"(ratio {csv_m['gzip_ratio']}x) | MEASUREMENT |", "",
          "## Extrapolations at the official 10 Hz rate", "",
          "| scenario | per day | 30 days | 60 days | label |",
          "|---|---|---|---|---|",
          f"| SQLite, raw 10 Hz | {report['extrapolation_full_10hz_sqlite']['gb_per_day']} GB "
          f"| {report['extrapolation_full_10hz_sqlite']['gb_30_days']} GB "
          f"| {report['extrapolation_full_10hz_sqlite']['gb_60_days']} GB | ESTIMATE |",
          f"| gzip CSV, raw 10 Hz | {report['extrapolation_full_10hz_csv_gzip']['gb_per_day']} GB "
          f"| - | {report['extrapolation_full_10hz_csv_gzip']['gb_60_days']} GB | ESTIMATE |", "",
          "## Actually generated demo dataset", "",
          f"- size: **{report['actual_demo_dataset']['size_mb']} MB** over "
          f"{demo_days} days = **{report['actual_demo_dataset']['mb_per_day']} MB/day** (MEASUREMENT)",
          f"- representation: {report['actual_demo_dataset']['representation']}", "",
          "## Conclusion", "", report["design_conclusion"], ""]
    (OUT / "storage_audit.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
