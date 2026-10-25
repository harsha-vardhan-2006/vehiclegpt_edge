"""Shared fixtures.

The test database is generated once per session with a fixed seed (30 days so
both the 14-day analysis window and the previous comparison window exist).
"""
from __future__ import annotations

import pytest

from storage.database import connect, init_db, load_settings


@pytest.fixture(scope="session")
def settings() -> dict:
    s = load_settings()
    s["llm"]["enabled"] = False
    return s


@pytest.fixture(scope="session")
def testdb_path(tmp_path_factory):
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "data" / "database" / "test_vehiclegpt.db"
    if path.exists():
        path.unlink()
    conn = connect(path)
    init_db(conn)
    s = load_settings()
    s["simulation"]["days"] = 30
    from simulator.generate_vehicle_data import generate
    generate(s, conn)
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    yield path
    # keep the file for inspection; it is git-ignored


@pytest.fixture(scope="session")
def db(testdb_path):
    conn = connect(testdb_path)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def test_settings(settings, db) -> dict:
    """Settings whose clock matches the generated test dataset."""
    from datetime import datetime
    s = dict(settings)
    end = db.execute("SELECT MAX(timestamp) t FROM vehicle_signals").fetchone()["t"]
    sim = dict(settings["simulation"])
    sim["end_time"] = datetime.strptime(end, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    s["simulation"] = sim
    return s
