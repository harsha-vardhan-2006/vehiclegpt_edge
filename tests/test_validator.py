"""Evidence validator: each spec check is exercised with a bad answer."""
from __future__ import annotations

from llm.answer_validator import validate
from query_engine.query_models import Answer, Evidence, TimeRange


def _ev(**kw):
    base = dict(evidence_id=kw.pop("evidence_id", "E1"), kind="aggregate",
                reference="range:mean", source="sqlite", quality_status="good",
                data_maturity="simulated", produced_by="AVG(value)")
    base.update(kw)
    return Evidence(**base)


def _ans(**kw):
    base = dict(question="q", category="trend_analysis",
                direct_answer="mean range 40 km associated with the change "
                              "(synthetic data)",
                time_range=TimeRange(start="2026-10-11 00:00:00",
                                     end="2026-10-25 00:00:00"),
                evidence=[_ev(value=40.0, unit="km", time_start="2026-10-11 00:00:00",
                              time_end="2026-10-25 00:00:00")],
                limitations=["Synthetic data."], data_maturity="simulated",
                retrieval_status="ok")
    base.update(kw)
    return Answer(**base)


def test_correct_answer_passes():
    r = validate(_ans())
    assert r.status == "pass", r.issues
    assert "numeric_claims_traceable" in r.checks_run


def test_unbacked_number_fails():
    r = validate(_ans(direct_answer="mean range is 93 km (synthetic, associated with x)"))
    assert r.status == "fail"
    assert any("unbacked numeric claim: 93" in i for i in r.issues)


def test_value_without_unit_flagged():
    r = validate(_ans(evidence=[_ev(value=40.0, unit=None,
                                    time_start="2026-10-11 00:00:00",
                                    time_end="2026-10-25 00:00:00")]))
    assert any("without a unit" in i for i in r.issues)


def test_bad_timestamp_flagged():
    r = validate(_ans(evidence=[_ev(value=40.0, unit="km",
                                    time_start="2026-10-11 00:00:00",
                                    time_end="2026-10-25 00:00:00",
                                    timestamp="garbage")]))
    assert any("interval" in i or "unparseable" in i for i in r.issues)


def test_evidence_outside_interval_flagged():
    r = validate(_ans(evidence=[_ev(value=40.0, unit="km",
                                    time_start="2020-01-01 00:00:00",
                                    time_end="2020-01-02 00:00:00")]))
    assert any("outside requested interval" in i for i in r.issues)


def test_causal_claim_rejected():
    r = validate(_ans(direct_answer="The range drop was caused by the battery "
                                    "(40 km, synthetic data, associated with x)"))
    assert any("causal phrasing" in i for i in r.issues)
    assert r.status == "fail"


def test_association_language_required_for_analysis():
    r = validate(_ans(direct_answer="Range fell to 40 km. Data: synthetic."))
    assert any("association vs causation" in i for i in r.issues)


def test_synthetic_not_disclosed_flagged():
    r = validate(_ans(limitations=["No gaps found."]))
    assert any("not disclosed" in i for i in r.issues)


def test_missing_quality_not_disclosed_flagged():
    r = validate(_ans(evidence=[_ev(value=40.0, unit="km", quality_status="missing",
                                    time_start="2026-10-11 00:00:00",
                                    time_end="2026-10-25 00:00:00")],
                      limitations=["Synthetic data."]))
    assert any("not disclosed" in i for i in r.issues)


def test_empty_answer_without_limitation_flagged():
    r = validate(_ans(direct_answer="", retrieval_status="unsupported", limitations=[]))
    assert any("explicit limitation" in i for i in r.issues)
    assert r.status != "pass"


def test_malformed_event_citation_flagged():
    r = validate(_ans(evidence=[_ev(kind="event", reference="event:abc",
                                    text="x", timestamp="2026-10-12 00:00:00")]))
    assert any("malformed event reference" in i for i in r.issues)


def test_inverted_time_range_flagged():
    r = validate(_ans(time_range=TimeRange(start="2026-10-25 00:00:00",
                                           end="2026-10-11 00:00:00")))
    assert any("not before end" in i for i in r.issues)
