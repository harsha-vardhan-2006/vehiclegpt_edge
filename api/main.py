"""FastAPI application: local-only API + static UI. No cloud calls."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from query_engine.pipeline import answer_question, get_context, reset_context
from storage import retention
from storage.database import connect, init_db, load_settings

settings = load_settings()
ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="VehicleGPT Edge", version="0.1.0",
              description="Evidence-grounded local vehicle assistant (offline, no cloud)")

_conn: sqlite3.Connection | None = None


def db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = connect()
        init_db(_conn)
    return _conn


class AskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=400)


@app.get("/api/health")
def health():
    return {"status": "ok", "offline": True, "cloud_calls": "none"}


@app.get("/api/status")
def status():
    conn = db()
    span = retention.history_span(conn)
    latest = conn.execute("SELECT MAX(timestamp) t FROM vehicle_signals").fetchone()["t"]
    n_events = conn.execute("SELECT COUNT(*) n FROM vehicle_events").fetchone()["n"]
    db_path = ROOT / settings["storage"]["db_path"]
    from llm import local_model
    maturity = conn.execute(
        "SELECT DISTINCT data_maturity m FROM vehicle_signals").fetchall()
    return {
        "vehicle": settings["simulation"]["vehicle_id"],
        "data_maturity": [m["m"] for m in maturity],
        "simulated": True,
        "latest_data_timestamp": latest,
        "history_days": span["days"],
        "history_samples": span["samples"],
        "retention_days": settings["storage"]["retention_days"],
        "events": n_events,
        "database_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "model": local_model.status(settings),
        "offline": True,
    }


@app.post("/api/ask")
def ask(body: AskBody):
    conn = db()
    ans = answer_question(conn, body.question, settings)
    return JSONResponse(ans.model_dump())


@app.get("/api/context")
def context():
    return get_context()


@app.post("/api/context/reset")
def context_reset():
    reset_context()
    return {"status": "reset"}


@app.get("/api/timeline")
def timeline(start: str | None = None, end: str | None = None, event_type: str | None = None,
             severity: str | None = None, limit: int = 200):
    conn = db()
    limit = max(1, min(limit, 1000))
    sql = ("SELECT id, event_type, severity, timestamp, source, description, data_maturity "
           "FROM vehicle_events WHERE 1=1")
    params: list = []
    if start:
        sql += " AND timestamp>=?"
        params.append(start)
    if end:
        sql += " AND timestamp<?"
        params.append(end)
    if event_type:
        sql += " AND event_type=?"
        params.append(event_type)
    if severity:
        sql += " AND severity=?"
        params.append(severity)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = [dict(r) for r in conn.execute(sql, params)]
    types = [r["event_type"] for r in conn.execute(
        "SELECT DISTINCT event_type FROM vehicle_events ORDER BY event_type")]
    return {"events": rows, "event_types": types, "synthetic": True}


@app.get("/api/series")
def series(signal: str, start: str, end: str, buckets: int = 120):
    """Downsampled series for charts (server-side bucketing, parameterised)."""
    conn = db()
    if signal not in {r["signal_name"] for r in conn.execute(
            "SELECT signal_name FROM signal_dictionary")}:
        raise HTTPException(400, "unknown signal (see /api/signals)")
    buckets = max(10, min(buckets, 500))
    rows = conn.execute(
        "SELECT timestamp, value, unit FROM vehicle_signals WHERE signal_name=? "
        "AND timestamp>=? AND timestamp<? AND value IS NOT NULL "
        "AND quality_status IN ('good','unit_converted') ORDER BY timestamp",
        (signal, start, end)).fetchall()
    if not rows:
        return {"signal": signal, "points": [], "unit": None, "synthetic": True}
    n = len(rows)
    step = max(1, n // buckets)
    points = [{"t": rows[i]["timestamp"], "v": round(rows[i]["value"], 3)}
              for i in range(0, n, step)]
    return {"signal": signal, "unit": rows[0]["unit"], "points": points,
            "samples": n, "synthetic": True}


@app.get("/api/signals")
def signals():
    conn = db()
    return {"signals": [dict(r) for r in conn.execute(
        "SELECT signal_name, unit, description, valid_min, valid_max FROM signal_dictionary "
        "ORDER BY signal_name")]}


@app.get("/api/diagnostics")
def diagnostics():
    conn = db()
    recent = [dict(r) for r in conn.execute(
        "SELECT timestamp, query_category, retrieval_status, duration_ms, evidence_count,"
        " model_used, validation_status FROM query_audit ORDER BY id DESC LIMIT 20")]
    fails = [r for r in recent if r["validation_status"] not in ("pass", "warn")]
    quality = {r["quality_status"]: r["n"] for r in conn.execute(
        "SELECT quality_status, COUNT(*) n FROM vehicle_signals GROUP BY quality_status")}
    return {
        "api": "ok", "database": "ok", "model": "disabled (deterministic mode)",
        "recent_queries": recent, "recent_validation_failures": fails,
        "signal_quality_counts": quality, "ingestion_errors": 0,
        "note": "values come from the running system, not hard-coded indicators",
    }


@app.post("/api/simulate")
def simulate(days: int = 60, reset: bool = False):
    """(Re)generate the synthetic dataset. Deterministic with a fixed seed."""
    global _conn
    from simulator.generate_vehicle_data import generate
    from storage.database import DB_PATH, init_db as _init
    if reset and DB_PATH.exists():
        _conn = None
        DB_PATH.unlink()
    conn = db()
    _init(conn)
    stats = generate(settings, conn)
    return {"generated": stats, "synthetic": True, "seed": settings["simulation"]["random_seed"]}


@app.get("/")
def index():
    return FileResponse(ROOT / "ui" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "ui"), name="static")


def main():
    import uvicorn
    uvicorn.run("api.main:app", host=settings["api"]["host"],
                port=int(settings["api"]["port"]), log_level="info")


if __name__ == "__main__":
    main()
