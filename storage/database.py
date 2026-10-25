"""Shared helpers: settings, paths, connection handling."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "database" / "vehiclegpt.db"
SCHEMA_PATH = ROOT / "storage" / "schema.sql"

TS_FMT = "%Y-%m-%d %H:%M:%S"


def load_settings() -> dict:
    """Minimal YAML subset loader (no PyYAML dependency). Supports the
    nested mapping style used in config/settings.yaml with scalars."""
    text = (CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8")
    data: dict = {}
    stack: list[tuple[int, dict]] = [(-1, data)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        if line.startswith("- "):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith('"'):                      # keep quoted string, drop trailing comment
            end = val.find('"', 1)
            val = val[: end + 1] if end > 0 else val
        elif "#" in val:
            val = val.split("#")[0].strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(val)
    return data


def _scalar(v: str):
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def load_signal_dictionary() -> dict:
    raw = json.loads((CONFIG_DIR / "signal_dictionary.json").read_text(encoding="utf-8"))
    return {s["signal_name"]: s for s in raw["signals"]}


def connect(db_path: Path | str | None = None, read_only: bool = False) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fmt(dt: datetime) -> str:
    return dt.strftime(TS_FMT)


def parse(ts: str) -> datetime:
    return datetime.strptime(ts, TS_FMT)


def relative_day(dataset_end: datetime, word: str) -> tuple[datetime, datetime]:
    """Resolve simple English day words against the dataset clock (deterministic,
    does not use the real wall clock). Returns (start, end) inclusive/exclusive."""
    day = dataset_end.date()
    if word == "today":
        s, e = datetime(day.year, day.month, day.day), dataset_end
    elif word == "yesterday":
        s = datetime(day.year, day.month, day.day) - timedelta(days=1)
        e = s + timedelta(days=1)
    else:
        raise ValueError(f"unsupported day word: {word}")
    return s, e
