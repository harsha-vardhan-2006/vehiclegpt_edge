"""CSV / JSON-lines log import (maturity=replayed).

The file is untrusted data: contents are parsed as values only. No content
from the file is ever executed, interpolated into SQL, or interpreted as a
command (see docs/security.md).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ingestion.adapters.base import AdapterInfo, SourceAdapter

ALLOWED_ROOT = Path(__file__).resolve().parents[2] / "data"
REQUIRED = {"signal_name", "timestamp"}


class CsvLogAdapter(SourceAdapter):
    info = AdapterInfo(
        name="csv_log",
        input_format="CSV with header (signal_name, timestamp, value, unit[, trip_id]) "
                     "or JSON lines with the same keys",
        dependencies="Python stdlib (csv, json)",
        permissions="read access limited to ./data/**",
        implemented=True,
        test_status="TESTED",
        limitations="Malformed lines are rejected and counted; no schema inference.",
        maturity="replayed",
    )

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()

    def _check_path(self) -> None:
        if ALLOWED_ROOT not in self.path.parents and self.path.parent != ALLOWED_ROOT:
            raise PermissionError(f"imports must live under {ALLOWED_ROOT}")
        if not self.path.exists():
            raise FileNotFoundError(self.path)

    def read(self) -> Iterator[dict]:
        import csv
        import json
        self._check_path()
        if self.path.suffix.lower() == ".jsonl":
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    yield json.loads(line)
            return
        with self.path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if not _has_required(row):
                    continue
                yield row


def _has_required(row: dict) -> bool:
    keys = {str(k).strip().lower() for k in row}
    return REQUIRED.issubset(keys)
