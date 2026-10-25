"""Normalisation: canonical timestamps (UTC ISO), canonical units, quality flags.

Never turns a missing value into zero. Never raises on plausibility - it flags.
"""
from __future__ import annotations

from datetime import datetime, timezone

TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S",
              "%Y-%m-%d %H:%M:%S.%f", "%Y%m%d%H%M%S")

UNIT_ALIASES = {"degc": "C", "celsius": "C", "°c": "C", "kmh": "km/h", "kph": "km/h"}

UNIT_CONVERSIONS = {  # (from, to): factor  (target unit comes from the dictionary)
    ("Wh", "kWh"): 0.001,
    ("kWh", "Wh"): 1000.0,
    ("Wh/km", "Wh/km"): 1.0,
    ("mph", "km/h"): 1.60934,
    ("psi", "bar"): 0.0689476,
    ("F", "C"): None,  # handled specially
    ("K", "C"): None,
}


def canonical_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    u = str(unit).strip()
    return UNIT_ALIASES.get(u.lower(), u)


def parse_timestamp(value: str) -> datetime:
    v = str(value).strip()
    for fmt in TS_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
            return dt.replace(tzinfo=None) if dt.tzinfo is None else dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            continue
    raise ValueError(f"unparseable timestamp: {value!r}")


def convert(value: float, src_unit: str, dst_unit: str) -> float:
    if src_unit == dst_unit:
        return value
    if (src_unit, dst_unit) == ("F", "C"):
        return (value - 32.0) * 5.0 / 9.0
    if (src_unit, dst_unit) == ("K", "C"):
        return value - 273.15
    factor = UNIT_CONVERSIONS.get((src_unit, dst_unit))
    if factor is None:
        raise ValueError(f"unsupported unit conversion {src_unit} -> {dst_unit}")
    return value * factor


def normalize_record(raw: dict, dictionary: dict, maturity: str, source: str,
                     ingestion_ts: str, vehicle_id: str = "DEMO-EV-001"):
    """Return an insert tuple for vehicle_signals, or None if the row is unusable."""
    name = str(raw.get("signal_name", "")).strip()
    if not name:
        raise ValueError("missing signal_name")
    if name not in dictionary:
        raise ValueError(f"unknown signal: {name}")
    spec = dictionary[name]

    ts = parse_timestamp(raw["timestamp"])

    raw_value = raw.get("value")
    if raw_value is None or str(raw_value).strip() == "":
        value, quality = None, "missing"
    else:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise ValueError(f"non-numeric value for {name}: {raw_value!r}")
        src_unit = canonical_unit(raw.get("unit")) or spec["unit"]
        dst_unit = spec["unit"]
        if src_unit != dst_unit:
            value = convert(value, src_unit, dst_unit)
            quality = "unit_converted"
        else:
            quality = str(raw.get("quality_status") or "good")
        if value is not None and not (float(spec["valid_min"]) <= value <= float(spec["valid_max"])):
            quality = "implausible"

    trip_id = raw.get("trip_id")
    try:
        trip_id = int(trip_id) if trip_id not in (None, "") else None
    except ValueError:
        trip_id = None

    return (vehicle_id, trip_id, name, ts.strftime("%Y-%m-%d %H:%M:%S"), value,
            spec["unit"], source, quality, maturity, ingestion_ts)
