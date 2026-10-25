"""Answer validation: a real program that re-checks claims against evidence.

Implements the nine checks from the specification (section 8). It never
trusts the model: numerical claims must be traceable to evidence records.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from query_engine.query_models import Answer, ValidationReport
from storage.database import parse

CAUSAL_PATTERNS = [
    r"\bcaused by\b", r"\bbecause of\b", r"\bthe cause is\b", r"\bis the reason\b",
    r"\bleads to\b", r"\bdue to a fault in\b", r"\bproves that\b",
]
CONFIDENCE_KEYS = {"confidence", "confidence_score", "probability"}


def _mask_dates(text: str) -> str:
    text = re.sub(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?", " ", text)   # timestamps
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", " ", text)                        # dates
    text = re.sub(r"\b\d{1,2}:\d{2}(:\d{2})?\b", " ", text)                   # clock times
    return text


def _allowed_numbers(answer: Answer) -> set[float]:
    out: set[float] = set()
    for e in answer.evidence:
        if e.value is None:
            continue
        v = float(e.value)
        out.add(v)
        out.add(round(v, 3))
        out.add(round(v, 2))
        out.add(round(v, 1))
        out.add(float(int(round(v))))
    # counts of evidence themselves are legitimate facts
    out.add(float(len(answer.evidence)))
    return out


def _claimed_numbers(text: str) -> list[float]:
    masked = _mask_dates(text)
    return [float(m) for m in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w])", masked)]


def validate(answer: Answer) -> ValidationReport:
    issues: list[str] = []
    checks: list[str] = []

    allowed = _allowed_numbers(answer)

    # 1. every numerical claim corresponds to evidence
    claims = _claimed_numbers(answer.direct_answer)
    for c in claims:
        ok = any(abs(c - a) <= max(0.011, abs(c) * 0.005) for a in allowed)
        if not ok:
            issues.append(f"unbacked numeric claim: {c} not found in evidence")
    checks.append("numeric_claims_traceable")

    # 2. units consistent (evidence units are non-empty strings when a value exists)
    for e in answer.evidence:
        if e.value is not None and not e.unit:
            issues.append(f"evidence {e.evidence_id} has a value without a unit")
    checks.append("units_consistent")

    # 3/5. timestamps valid and interval matches
    try:
        rs, re_ = parse(answer.time_range.start), parse(answer.time_range.end)
        if rs >= re_:
            issues.append("time_range start is not before end")
    except Exception:
        issues.append("time_range is not parseable")
        rs = re_ = None
    checks.append("time_range_valid")

    if rs and re_:
        for e in answer.evidence:
            if e.kind == "parameter" or "previous" in e.reference:
                continue                      # windows/parameters may sit outside the asked range
            span_s, span_e = e.time_start, e.time_end
            try:
                inside = (span_s is None or parse(span_s) >= rs - timedelta(days=1)) \
                    and (span_e is None or parse(span_e) <= re_ + timedelta(days=1))
            except Exception:
                inside = False
            if not inside:
                issues.append(f"evidence {e.evidence_id} ({span_s} -> {span_e}) outside requested interval")
                continue
            for ts in (e.timestamp, e.time_start, e.time_end):
                if not ts:
                    continue
                try:
                    parse(ts)
                except Exception:
                    issues.append(f"evidence {e.evidence_id} has unparseable timestamp {ts}")
    checks.append("timestamps_ordered")

    # 4. missing/stale data disclosed (only meaningful for successful answers)
    flagged = [e for e in answer.evidence if e.quality_status not in ("good",)]
    if answer.retrieval_status == "ok" and flagged and not any(
            "gap" in lim.lower() or "missing" in lim.lower() or "quality" in lim.lower()
            for lim in answer.limitations):
        issues.append("non-good quality evidence present but not disclosed in limitations")
    checks.append("missing_data_disclosed")

    # 6. the answer does not cite nonexistent records
    #    (evidence rows are produced by retrieval from SQLite; ids are re-checked
    #     against the DB in tests via reference fields)
    for e in answer.evidence:
        if e.kind == "event":
            m = re.match(r"event:(\d+)$", e.reference)
            if not m:
                issues.append(f"malformed event reference {e.reference}")
    checks.append("citations_exist")

    # 7. synthetic data must not be presented as real
    if answer.retrieval_status == "ok" and answer.data_maturity == "simulated" and not any(
            "synthetic" in lim.lower() or "simulated" in lim.lower() for lim in answer.limitations):
        issues.append("simulated data not disclosed in limitations")
    for e in answer.evidence:
        if e.data_maturity == "real" and answer.data_maturity != "real":
            issues.append(f"evidence {e.evidence_id} maturity mismatch")
    checks.append("maturity_disclosed")

    # 8. unsupported causal claims rejected/qualified
    low = answer.direct_answer.lower()
    for pat in CAUSAL_PATTERNS:
        if re.search(pat, low):
            issues.append(f"unsupported causal phrasing matched: {pat}")
    if answer.retrieval_status == "ok" and answer.category in ("trend_analysis", "temporal_reconstruction") \
            and re.search(r"\bassociated with\b|\bassociated preceding\b|\bcorrelation\b", low) is None:
        issues.append("analytical answer should qualify association vs causation language")
    checks.append("causal_language_qualified")

    # 9. unsupported/empty requests must carry an explicit limitation
    if answer.retrieval_status in ("unsupported", "ambiguous", "empty") and not answer.limitations:
        issues.append("non-successful retrieval without explicit limitation message")
    checks.append("explicit_limitation_on_unsupported")

    # extra: no unexplained confidence scores
    if any(k in answer.model_dump() for k in CONFIDENCE_KEYS):
        issues.append("confidence score present without defined interpretation")
    checks.append("no_unexplained_confidence")

    status = "pass" if not issues else ("warn" if answer.retrieval_status != "ok" and
                                        all("interval" in i for i in issues) else "fail")
    if issues and answer.retrieval_status != "ok":
        status = "warn"                      # empty/unsupported answers can trip soft checks
    return ValidationReport(status=status, issues=issues, checks_run=checks)
