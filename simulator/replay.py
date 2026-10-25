"""Replay a recorded CSV/JSON log file through the ingestion adapter.

Maturity of anything read here is 'replayed' (a recorded file), never 'real'.
The file content is treated strictly as data - no evaluation, no commands.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ingestion.normalizer import normalize_record
from storage.database import fmt, now_utc

ALLOWED_ROOT = Path(__file__).resolve().parent.parent / "data"


def replay_file(path: str | Path, conn, dictionary: dict, maturity: str = "replayed") -> dict:
    p = Path(path).resolve()
    if ALLOWED_ROOT not in p.parents and p.parent != ALLOWED_ROOT:
        raise PermissionError(f"imports must live under {ALLOWED_ROOT}")
    if not p.exists():
        raise FileNotFoundError(p)

    inserted = rejected = 0
    errors: list[str] = []
    ing_ts = fmt(now_utc())
    if p.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        with p.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

    for i, raw in enumerate(rows):
        try:
            rec = normalize_record(raw, dictionary, maturity=maturity,
                                    source=f"file:{p.name}", ingestion_ts=ing_ts)
        except Exception as exc:            # malformed input -> reject, never crash
            rejected += 1
            errors.append(f"line {i + 1}: {exc}")
            continue
        if rec is None:
            rejected += 1
            continue
        conn.execute(
            "INSERT INTO vehicle_signals(vehicle_id, trip_id, signal_name, timestamp, value, unit,"
            " source, quality_status, data_maturity, ingestion_timestamp)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", rec)
        inserted += 1
    conn.commit()
    return {"inserted": inserted, "rejected": rejected, "errors": errors[:10]}
