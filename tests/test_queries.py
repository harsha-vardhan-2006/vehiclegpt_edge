"""The five official case-study questions + variations + follow-ups."""
from __future__ import annotations

import pytest

from query_engine.pipeline import answer_question, reset_context


@pytest.fixture(autouse=True)
def _ctx():
    reset_context()
    yield
    reset_context()


def gt(db, scenario, key):
    row = db.execute(
        "SELECT gt_value FROM scenario_ground_truth WHERE scenario_id=? AND gt_key=?",
        (scenario, key)).fetchone()
    assert row is not None, f"missing ground truth {scenario}.{key}"
    return row[0]


def ev_by_ref(answer, ref_prefix):
    return [e for e in answer.evidence if e.reference.startswith(ref_prefix)]


# ---------------------------------------------------------------- official 5
def test_q1_range_reduction(db, test_settings):
    q = "Why has my driving range reduced over the last two weeks?"
    a = answer_question(db, q, test_settings)
    assert a.category == "trend_analysis" and a.retrieval_status == "ok"
    assert a.validation.status == "pass", a.validation.issues
    assert a.evidence and "associated with" in a.direct_answer
    # computed from data, not hard-coded: range down, consumption up, capacity faded
    rng = ev_by_ref(a, "range_change_pct")[0].value
    con = ev_by_ref(a, "consumption_change_pct")[0].value
    cap = ev_by_ref(a, "capacity_change_pct")[0].value
    assert rng < 0 and con > 0 and cap < 0
    # scenario A ground truth: ~4% usable-capacity fade injected
    fade_gt = float(gt(db, "A_range_reduction", "usable_capacity_fade_pct"))
    assert abs(abs(cap) - fade_gt) < 3.0, (cap, fade_gt)
    assert "synthetic" in " ".join(a.limitations).lower()


def test_q2_largest_efficiency_drop(db, test_settings):
    q = "When did fuel efficiency show the largest drop?"
    a = answer_question(db, q, test_settings)
    assert a.category == "anomaly_explanation" and a.retrieval_status == "ok"
    assert a.validation.status == "pass", a.validation.issues
    expect_day = gt(db, "B_efficiency_drop", "trip_date")
    assert expect_day in a.direct_answer, (expect_day, a.direct_answer)


def test_q3_adas_events_yesterday(db, test_settings):
    q = "Show all ADAS disengagement events from yesterday."
    a = answer_question(db, q, test_settings)
    assert a.category == "event_history" and a.retrieval_status == "ok"
    assert a.validation.status == "pass", a.validation.issues
    known = gt(db, "C_adas_disengagement", "event_timestamps").split(";")
    yesterday = [t for t in known if t.startswith("2026-10-24")]
    assert len(yesterday) == int(gt(db, "C_adas_disengagement", "count_yesterday"))
    for ts in yesterday:
        assert ts in a.direct_answer
    assert len(ev_by_ref(a, "event:")) == len(yesterday)


def test_q4_battery_warning_context(db, test_settings):
    q = "What happened before the battery overheating warning?"
    a = answer_question(db, q, test_settings)
    assert a.category == "temporal_reconstruction" and a.retrieval_status == "ok"
    assert a.validation.status == "pass", a.validation.issues
    warn_ts = gt(db, "D_battery_overheat_context", "warning_ts")
    assert warn_ts in a.direct_answer
    temp_ev = ev_by_ref(a, "battery_temp:max")
    assert temp_ev and temp_ev[0].value >= 50          # ramp reached warning level
    assert any("not a proven cause" in l for l in a.limitations) or \
        "not a proven cause" in a.direct_answer


def test_q5_city_vs_highway(db, test_settings):
    q = "Compare energy consumption between city and highway driving."
    a = answer_question(db, q, test_settings)
    assert a.category == "comparison" and a.retrieval_status == "ok"
    assert a.validation.status == "pass", a.validation.issues
    city = ev_by_ref(a, "city:whkm")[0].value
    hwy = ev_by_ref(a, "highway:whkm")[0].value
    city_gt = float(gt(db, "E_city_vs_highway", "city_baseline_whkm"))
    hwy_gt = float(gt(db, "E_city_vs_highway", "highway_baseline_whkm"))
    assert hwy_gt > city_gt and hwy > city            # same ordering as ground truth
    assert abs(city - city_gt) / city_gt < 0.35


# ------------------------------------------------------------- variations
def test_q1_paraphrase(db, test_settings):
    a = answer_question(db, "Why did my range drop over the past 2 weeks?", test_settings)
    assert a.category == "trend_analysis" and a.retrieval_status == "ok"
    assert a.validation.status == "pass", a.validation.issues


def test_q3_paraphrase(db, test_settings):
    a = answer_question(db, "list ADAS disengagement events yesterday", test_settings)
    assert a.category == "event_history" and a.retrieval_status == "ok"


def test_explicit_date_range(db, test_settings):
    a = answer_question(db, "Show all events from 2026-10-24 to 2026-10-24", test_settings)
    assert a.retrieval_status == "ok"
    assert a.time_range.start.startswith("2026-10-24")


def test_incomplete_question_is_ambiguous(db, test_settings):
    a = answer_question(db, "temperature", test_settings)
    assert a.category == "ambiguous" and a.retrieval_status == "ambiguous"
    assert a.limitations and "time anchor" in a.limitations[0]


def test_unsupported_question_disclosed(db, test_settings):
    a = answer_question(db, "Tell me a joke about racing", test_settings)
    assert a.category == "unsupported" and a.direct_answer == ""
    assert a.limitations and "outside the supported categories" in a.limitations[0]


def test_no_data_window_yields_empty_not_fabrication(db, test_settings):
    a = answer_question(db, "Show all ADAS disengagement events from 2020-01-01 to 2020-01-02",
                        test_settings)
    assert a.retrieval_status == "empty" and a.direct_answer == ""
    assert a.limitations


# ------------------------------------------------------------- follow-ups
def test_followup_show_evidence(db, test_settings):
    first = answer_question(db, "Compare energy consumption between city and highway driving.",
                            test_settings)
    a = answer_question(db, "Show the evidence.", test_settings)
    assert a.retrieval_status == "ok"
    assert len(a.evidence) == len(first.evidence)
    assert a.validation.status == "pass", a.validation.issues


def test_followup_missing_readings(db, test_settings):
    a = answer_question(db, "Were there any missing sensor readings?", test_settings)
    assert a.retrieval_status == "ok" and a.validation.status == "pass", a.validation.issues
    gaps = ev_by_ref(a, "gap_count")
    assert gaps and gaps[0].value >= 1           # scenario F gap is in the window


def test_followup_top_trips(db, test_settings):
    answer_question(db, "Compare energy consumption between city and highway driving.",
                    test_settings)
    a = answer_question(db, "Which trips contributed most to the difference?", test_settings)
    assert a.retrieval_status == "ok" and a.validation.status == "pass", a.validation.issues
    assert "median baseline" in a.direct_answer


def test_followup_change_start(db, test_settings):
    answer_question(db, "Why has my driving range reduced over the last two weeks?",
                    test_settings)
    a = answer_question(db, "When did the change start?", test_settings)
    assert a.retrieval_status == "ok" and a.validation.status == "pass", a.validation.issues


def test_exact_lookup(db, test_settings):
    a = answer_question(db, "What is the vehicle speed now?", test_settings)
    assert a.category == "exact_lookup" and a.retrieval_status == "ok"
    assert a.validation.status == "pass", a.validation.issues


def test_input_length_is_bounded(db, test_settings):
    a = answer_question(db, "why " + "range " * 200, test_settings)
    assert len(a.question) <= 400


def test_audit_rows_written(db, test_settings):
    answer_question(db, "Show all ADAS disengagement events from yesterday.", test_settings)
    row = db.execute("SELECT COUNT(*) FROM query_audit").fetchone()[0]
    assert row >= 1
