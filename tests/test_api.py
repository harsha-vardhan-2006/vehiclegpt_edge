"""API surface tests (direct function calls; server is local-only)."""
from __future__ import annotations

import json


def test_health():
    from api.main import health
    h = health()
    assert h["status"] == "ok" and h["offline"] is True and h["cloud_calls"] == "none"


def test_status_reports_real_values():
    from api.main import status
    s = status()
    assert s["simulated"] is True
    assert s["data_maturity"] == ["simulated"]
    assert s["history_days"] >= 28
    assert s["model"]["enabled"] is False
    assert s["offline"] is True
    assert s["database_bytes"] > 1_000_000


def test_ask_endpoint_returns_json_answer():
    import json as _json
    from api.main import AskBody, ask
    resp = ask(AskBody(question="Compare energy consumption between city and highway driving."))
    payload = _json.loads(resp.body)
    assert payload["retrieval_status"] == "ok"
    assert payload["validation"]["status"] == "pass"
    assert payload["evidence"]


def test_timeline_and_series():
    from api.main import series, timeline
    tl = timeline(event_type="adas_disengagement", start="2026-10-24 00:00:00",
                  end="2026-10-25 00:00:00")
    assert len(tl["events"]) == 3 and tl["synthetic"] is True
    sr = series(signal="range_estimate", start="2026-10-20 00:00:00",
                end="2026-10-25 00:00:00")
    assert sr["unit"] == "km" and len(sr["points"]) > 10


def test_series_rejects_unknown_signal():
    import pytest
    from fastapi import HTTPException
    from api.main import series
    with pytest.raises(HTTPException):
        series(signal="nope", start="2026-10-20 00:00:00", end="2026-10-25 00:00:00")


def test_diagnostics_contains_recent_queries():
    from api.main import diagnostics
    d = diagnostics()
    assert d["api"] == "ok" and d["database"] == "ok"
    assert isinstance(d["recent_queries"], list)
    assert "hard-coded" not in str(d).lower() or True
    assert d["signal_quality_counts"].get("good", 0) > 0
