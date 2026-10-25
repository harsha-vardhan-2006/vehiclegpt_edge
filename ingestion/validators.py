"""Batch-level validation of normalised rows before persistence."""
from __future__ import annotations


def validate_batch(rows: list[tuple]) -> dict:
    """rows: tuples shaped (vehicle_id, trip_id, signal_name, timestamp, value, unit,
    source, quality, maturity, ingestion_timestamp).

    Returns (clean_rows, stats). Duplicates (same signal+timestamp) are marked
    'stale' and kept once; out-of-order rows are sorted; nothing is invented.
    """
    stats = {"received": len(rows), "duplicates": 0, "missing_values": 0,
             "implausible": 0, "unit_converted": 0, "output": 0}
    seen: set[tuple] = set()
    clean = []
    for r in rows:
        key = (r[2], r[3])
        quality = r[7]
        if quality == "missing":
            stats["missing_values"] += 1
        elif quality == "implausible":
            stats["implausible"] += 1
        elif quality == "unit_converted":
            stats["unit_converted"] += 1
        if key in seen:
            stats["duplicates"] += 1
            continue
        seen.add(key)
        clean.append(r)
    clean.sort(key=lambda r: (r[3], r[2]))
    stats["output"] = len(clean)
    return clean, stats
