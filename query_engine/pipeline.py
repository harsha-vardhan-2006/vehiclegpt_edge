"""Query pipeline: validate input -> route -> retrieve -> optional SLM -> validate -> audit."""
from __future__ import annotations

import time

from llm import local_model
from llm.answer_validator import validate
from query_engine import retrieval
from query_engine.intent_router import MAX_INPUT_CHARS, classify
from query_engine.query_models import Answer, TimeRange
from storage.database import fmt, now_utc

# conversation context (single-user localhost app)
_CONTEXT: dict = {}
_CONTEXT_EVIDENCE: list = []


def get_context() -> dict:
    return dict(_CONTEXT, evidence=list(_CONTEXT_EVIDENCE))


def reset_context() -> None:
    _CONTEXT.clear()
    _CONTEXT_EVIDENCE.clear()


def answer_question(conn, question: str, settings: dict) -> Answer:
    global _CONTEXT, _CONTEXT_EVIDENCE
    t0 = time.perf_counter()
    retrieval.reset_ids()

    q = (question or "").strip()[:MAX_INPUT_CHARS]
    if not q:
        ans = Answer(question=q, category="ambiguous", direct_answer="",
                     time_range=TimeRange(start="", end=""),
                     limitations=["Empty question received."],
                     retrieval_status="ambiguous")
        ans.validation = validate(ans)
        return ans

    ds_end = _dataset_end(conn, settings)
    intent = classify(q, ds_end, int(settings["query"]["default_lookback_days"]))
    plan = retrieval.PLANS.get(intent.category, retrieval.unsupported)

    if intent.category in ("evidence_request", "compare_previous_period", "change_start", "contribution"):
        result = plan(conn, intent, settings, get_context())
    else:
        result = plan(conn, intent, settings)

    ts = TimeRange(start=intent.entities.get("start", ""),
                   end=intent.entities.get("end", ""))

    if result["answer"] is None:
        ans = Answer(question=q, category=intent.category, direct_answer="",
                     time_range=ts, evidence=result.get("evidence", []),
                     limitations=result.get("limitations", []),
                     retrieval_status=result["status"])
        ans.validation = validate(ans)
        _audit(conn, intent.category, ans, 0.0, "none")
        ans.duration_ms = (time.perf_counter() - t0) * 1000
        return ans

    model_used = "none (deterministic answer engine)"
    answer_text = result["answer"]
    if settings.get("llm", {}).get("enabled"):
        reframed = local_model.explain(result["answer"], result.get("evidence", []), settings)
        if reframed:
            answer_text, model_used = reframed, f"local:{settings['llm'].get('model_name')}"

    ans = Answer(question=q, category=intent.category, direct_answer=answer_text,
                 time_range=ts, evidence=result.get("evidence", []),
                 limitations=result.get("limitations", []),
                 data_maturity="simulated", model_used=model_used,
                 retrieval_status=result["status"])
    ans.validation = validate(ans)

    duration_ms = (time.perf_counter() - t0) * 1000
    ans.duration_ms = round(duration_ms, 2)
    _audit(conn, intent.category, ans, duration_ms, model_used)

    if ans.retrieval_status == "ok" and intent.category not in ("evidence_request",):
        _CONTEXT.clear()
        _CONTEXT.update(result.get("context") or {"start": ans.time_range.start,
                                                  "end": ans.time_range.end})
        _CONTEXT_EVIDENCE.clear()
        _CONTEXT_EVIDENCE.extend([e.model_dump() for e in ans.evidence])
    return ans


def _dataset_end(conn, settings: dict):
    from datetime import datetime
    row = conn.execute("SELECT MAX(timestamp) t FROM vehicle_signals").fetchone()
    if row and row[0]:
        return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    return datetime.strptime(settings["simulation"]["end_time"], "%Y-%m-%d %H:%M:%S")


def _audit(conn, category: str, ans: Answer, duration_ms: float, model_used: str) -> None:
    import sqlite3
    try:
        conn.execute(
            "INSERT INTO query_audit(timestamp, query_category, retrieval_status, duration_ms,"
            " evidence_count, model_used, validation_status) VALUES (?,?,?,?,?,?,?)",
            (fmt(now_utc()), category, ans.retrieval_status, duration_ms,
             len(ans.evidence), model_used, ans.validation.status))
        conn.commit()
    except sqlite3.Error:
        # read-only connections (benchmarks) must not break answering
        pass
