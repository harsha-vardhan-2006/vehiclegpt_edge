"""Synthetic adapter: reads rows already produced by the simulator (maturity=simulated)."""
from __future__ import annotations

import sqlite3
from typing import Iterator

from ingestion.adapters.base import AdapterInfo, SourceAdapter


class SyntheticAdapter(SourceAdapter):
    info = AdapterInfo(
        name="synthetic",
        input_format="in-process generator (simulator/generate_vehicle_data.py)",
        dependencies="Python stdlib only",
        permissions="none",
        implemented=True,
        test_status="TESTED",
        limitations="Data is simulated; never a real vehicle measurement.",
        maturity="simulated",
    )

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def read(self) -> Iterator[dict]:
        cur = self.conn.execute(
            "SELECT signal_name, timestamp, value, unit, trip_id FROM vehicle_signals "
            "WHERE data_maturity='simulated' ORDER BY timestamp")
        for row in cur:
            yield dict(row)
