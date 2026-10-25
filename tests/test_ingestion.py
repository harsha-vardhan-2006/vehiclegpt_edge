"""Ingestion: normalisation, units, timestamps, plausibility, batch validation."""
from __future__ import annotations

import pytest

from ingestion.normalizer import normalize_record, parse_timestamp
from ingestion.validators import validate_batch
from storage.database import load_signal_dictionary

DICT = load_signal_dictionary()
ING = "2026-10-25 12:00:00"


def test_valid_record_normalised():
    rec = normalize_record({"signal_name": "vehicle_speed",
                            "timestamp": "2026-10-24 08:00:00", "value": "55.5",
                            "unit": "km/h"}, DICT, "simulated", "test", ING)
    assert rec[2] == "vehicle_speed" and rec[4] == 55.5 and rec[5] == "km/h"
    assert rec[7] == "good" and rec[8] == "simulated"


def test_unit_conversion_wh_to_kwh():
    rec = normalize_record({"signal_name": "regen_energy",
                            "timestamp": "2026-10-24 08:00:00", "value": "2000",
                            "unit": "Wh"}, DICT, "simulated", "test", ING)
    assert rec[4] == pytest.approx(2.0)        # converted Wh -> kWh
    assert rec[5] == "kWh" and rec[7] == "unit_converted"


def test_invalid_timestamp_rejected():
    with pytest.raises(ValueError):
        normalize_record({"signal_name": "vehicle_speed",
                          "timestamp": "not-a-date", "value": "10"}, DICT, "simulated", "test", ING)


def test_unknown_signal_rejected():
    with pytest.raises(ValueError):
        normalize_record({"signal_name": "made_up_signal",
                          "timestamp": "2026-10-24 08:00:00", "value": "1"},
                         DICT, "simulated", "test", ING)


def test_missing_value_is_none_not_zero():
    rec = normalize_record({"signal_name": "vehicle_speed",
                            "timestamp": "2026-10-24 08:00:00", "value": ""},
                           DICT, "simulated", "test", ING)
    assert rec[4] is None and rec[7] == "missing"


def test_implausible_value_flagged_not_dropped():
    rec = normalize_record({"signal_name": "vehicle_speed",
                            "timestamp": "2026-10-24 08:00:00", "value": "400"},
                           DICT, "simulated", "test", ING)
    assert rec[7] == "implausible" and rec[4] == 400.0


def test_duplicate_and_ordering_handling():
    rows = [
        ("v", None, "vehicle_speed", "2026-10-24 08:00:02", 10.0, "km/h", "t", "good", "simulated", ING),
        ("v", None, "vehicle_speed", "2026-10-24 08:00:01", 9.0, "km/h", "t", "good", "simulated", ING),
        ("v", None, "vehicle_speed", "2026-10-24 08:00:02", 10.0, "km/h", "t", "good", "simulated", ING),
        ("v", None, "soc", "2026-10-24 08:00:01", None, "%", "t", "missing", "simulated", ING),
    ]
    clean, stats = validate_batch(rows)
    assert stats["duplicates"] == 1
    assert stats["missing_values"] == 1
    assert len(clean) == 3
    assert clean[0][3] <= clean[1][3]           # sorted by timestamp


def test_timestamp_formats():
    assert parse_timestamp("2026-10-24T08:00:00").hour == 8
    assert parse_timestamp("24/10/2026 08:00:00").day == 24


def test_csv_log_rejects_corrupt_lines(tmp_path):
    from ingestion.adapters.csv_log import CsvLogAdapter
    # path must stay inside ./data
    with pytest.raises(PermissionError):
        list(CsvLogAdapter(tmp_path / "x.csv").read())

    import storage.database as dbmod
    target = dbmod.ROOT / "data" / "demo" / "test_corrupt.csv"
    target.write_text(
        "signal_name,timestamp,value,unit\n"
        "vehicle_speed,2026-10-24 08:00:00,50,km/h\n"
        "vehicle_speed,bad-timestamp,50,km/h\n"
        ",2026-10-24 08:00:01,60,km/h\n"
        "unknown_sig,2026-10-24 08:00:02,1,x\n", encoding="utf-8")
    rows = list(CsvLogAdapter(target).read())
    assert len(rows) == 4                       # adapter yields; normalizer rejects
    from simulator.replay import replay_file
    from storage.database import connect, init_db
    dbp = dbmod.ROOT / "data" / "database" / "replay_test.db"
    if dbp.exists():
        dbp.unlink()
    c = connect(dbp); init_db(c)
    res = replay_file(target, c, DICT, maturity="replayed")
    assert res["inserted"] == 1                 # only the valid row survives
    assert res["rejected"] == 3
    mat = c.execute("SELECT DISTINCT data_maturity FROM vehicle_signals").fetchall()
    assert [m[0] for m in mat] == ["replayed"]
    c.close(); dbp.unlink()
    target.unlink()
