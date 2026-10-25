"""Security and safety-boundary tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from query_engine.intent_router import classify
from storage.database import load_settings

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"tests", ".venv", "venv", "__pycache__", "node_modules"}


def _walk_py():
    for p in ROOT.rglob("*.py"):
        if set(p.relative_to(ROOT).parts) & SKIP:
            continue
        if "__pycache__" in p.parts:
            continue
        yield p


def test_sql_injection_question_is_harmless(db, settings):
    evil = "'; DROP TABLE trips; --"
    a_cl = classify(evil, __import__("datetime").datetime(2026, 10, 25, 18, 0))
    assert a_cl.category in ("unsupported", "ambiguous")
    from query_engine.pipeline import answer_question
    ans = answer_question(db, evil, settings)
    assert ans.retrieval_status in ("unsupported", "ambiguous", "empty")
    assert db.execute("SELECT COUNT(*) FROM trips").fetchone()[0] > 0


def test_input_is_truncated():
    end = __import__("datetime").datetime(2026, 10, 25, 18, 0)
    intent = classify("why " + "x" * 1000, end)
    assert len(intent.question) <= 400


def test_api_input_model_bounds():
    from api.main import AskBody
    with pytest.raises(Exception):
        AskBody(question="y" * 401)


def test_no_shell_or_eval_in_application_code():
    banned = ("subprocess", "os.system", "os.popen", "eval(", "exec(",
              "shell=True", "__import__(")
    for p in _walk_py():
        src = p.read_text(encoding="utf-8")
        for b in banned:
            assert b not in src, f"{p} contains banned construct {b!r}"


def test_no_actuator_or_can_write_path():
    """The application must not expose any vehicle-control/write capability."""
    for p in _walk_py():
        src = p.read_text(encoding="utf-8").lower()
        assert "send_reply_frame" not in src
        assert "can.send" not in src and ".send_periodic" not in src
        assert "set_actuator" not in src
    from ingestion.adapters.socketcan import SocketCanAdapter
    with pytest.raises(NotImplementedError):
        list(SocketCanAdapter().read())
    info = SocketCanAdapter.info
    assert info.implemented is False and "NOT used" in info.permissions


def test_imports_restricted_to_data_directory(tmp_path):
    from ingestion.adapters.csv_log import CsvLogAdapter
    with pytest.raises(PermissionError):
        list(CsvLogAdapter(tmp_path / "evil.csv").read())


def test_query_path_is_offline_even_with_model_enabled(db, settings):
    """LLM endpoint unreachable -> deterministic answer still returned."""
    s = dict(settings)
    s["llm"] = dict(settings["llm"], enabled=True, backend="llama_server",
                    endpoint="http://127.0.0.1:9", timeout_s=1)
    from query_engine.pipeline import answer_question, reset_context
    reset_context()
    ans = answer_question(db, "Show all ADAS disengagement events from yesterday.", s)
    assert ans.retrieval_status == "ok"
    assert ans.model_used.startswith("none")
    assert ans.validation.status == "pass"


def test_no_external_network_calls_in_query_path():
    """Only the optional LLM backend may open a socket; API binds to localhost."""
    offenders = []
    for p in _walk_py():
        if p.name == "local_model.py":
            continue
        src = p.read_text(encoding="utf-8")
        for needle in ("urllib.request", "requests.", "httpx.", "socket."):
            if needle in src:
                offenders.append((p.name, needle))
    assert not offenders, offenders
    src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    assert 'settings["api"]["host"]' in src
    assert load_settings()["api"]["host"] == "127.0.0.1"


def test_logs_and_imports_treated_as_data():
    """Imported file content never reaches exec/eval and is only stored as values."""
    from ingestion.normalizer import normalize_record
    from storage.database import load_signal_dictionary
    d = load_signal_dictionary()
    # non-numeric value is rejected as data, never executed
    with pytest.raises(ValueError):
        normalize_record({"signal_name": "vehicle_speed",
                          "timestamp": "2026-10-24 08:00:00",
                          "value": "50; rm -rf /"}, d, "simulated", "t", "now")
