"""Intent classification + entity/time-range extraction (deterministic).

Nine explicit categories; ambiguous input is disclosed rather than guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from storage.database import parse

MAX_INPUT_CHARS = 400

RULES: list[tuple[str, str]] = [
    (r"\bwhy\b.*\brange\b|\brange\b.*\breduc|\bconsumption\b.*\b(up|increas)", "trend_analysis"),
    (r"\blargest drop\b|\bbiggest drop\b|\bwhen did .* drop\b|efficiency.*drop", "anomaly_explanation"),
    (r"\bshow (all )?.*\bevents?\b|\badas\b.*\bdisengag|\bhistory of\b", "event_history"),
    (r"\bwhat happened before\b|\bbefore the\b.*\bwarning\b|\bleading to\b", "temporal_reconstruction"),
    (r"\bcompare\b.*\b(city|highway)\b|\bcity .* highway\b|\bdifference between\b", "comparison"),
    (r"\bmissing (sensor )?(readings|data)\b|\bstale\b|\bgaps?\b|unreliable data", "missing_data_investigation"),
    (r"\bshow the evidence\b|\bprove it\b|\bwhat is the evidence\b", "evidence_request"),
    (r"\bprevious week\b|\blast week\b|\bcompare .* last (week|month)\b", "compare_previous_period"),
    (r"\bwhen did the change start\b|\bwhen did (it|this) start\b|\bchange point\b", "change_start"),
    (r"\bwhich trips?\b.*\b(contribut|difference)\b|\btop trips\b", "contribution"),
    (r"\bwhat is the (speed|soc|temperature|range) now\b|\b(speed|range|soc|temperature) now\b|\blast value of\b|\bshow .* value\b", "exact_lookup"),
]


@dataclass
class Intent:
    category: str
    confidence: str = "high"          # high | low | ambiguous
    entities: dict = field(default_factory=dict)
    question: str = ""


def _extract_time(question: str, dataset_end: datetime, default_days: int) -> tuple[str, str, dict]:
    q = question.lower()
    notes: dict = {}
    m = re.search(r"from (\d{4}-\d{2}-\d{2}) to (\d{4}-\d{2}-\d{2})", q)
    if m:
        return m.group(1) + " 00:00:00", m.group(2) + " 23:59:59", {"explicit_range": True}
    m = re.search(r"on (\d{4}-\d{2}-\d{2})", q)
    if m:
        d = parse(m.group(1) + " 00:00:00")
        return m.group(1) + " 00:00:00", (d + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"), {"explicit_date": m.group(1)}
    if "yesterday" in q:
        d = (dataset_end - timedelta(days=1)).date()
        return f"{d.isoformat()} 00:00:00", (datetime(d.year, d.month, d.day) + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00"), {"day": "yesterday"}
    if "today" in q:
        d = dataset_end.date()
        return f"{d.isoformat()} 00:00:00", dataset_end.strftime("%Y-%m-%d %H:%M:%S"), {"day": "today"}
    m = re.search(r"last (\d+) (day|week|month)s?", q)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = n * (7 if unit == "week" else 30 if unit == "month" else 1)
        return (dataset_end - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S"), \
               dataset_end.strftime("%Y-%m-%d %H:%M:%S"), {"lookback_days": days}
    if "two weeks" in q or "2 weeks" in q or ("last" in q and "week" in q):
        return (dataset_end - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S"), \
               dataset_end.strftime("%Y-%m-%d %H:%M:%S"), {"lookback_days": 14}
    # default documented lookback (disclosed in the answer)
    return (dataset_end - timedelta(days=default_days)).strftime("%Y-%m-%d %H:%M:%S"), \
           dataset_end.strftime("%Y-%m-%d %H:%M:%S"), {"lookback_days": default_days, "default_used": True}


def classify(question: str, dataset_end: datetime, default_days: int = 14) -> Intent:
    q_raw = question.strip()
    if not q_raw:
        return Intent("unsupported", "ambiguous", {}, question)
    q = q_raw[:MAX_INPUT_CHARS]
    lower = q.lower()

    start, end, ents = _extract_time(lower, dataset_end, default_days)

    category = None
    for pattern, cat in RULES:
        if re.search(pattern, lower):
            category = cat
            break

    ents.update({"start": start, "end": end})

    if category is None:
        if len(lower.split()) < 3:
            return Intent("ambiguous", "low", ents, q)
        return Intent("unsupported", "low", ents, q)

    # ambiguity: relative period words with no anchor
    if ents.get("default_used") and category in ("trend_analysis", "comparison") \
            and not any(w in lower for w in ("week", "month", "since", "over", "last")):
        return Intent(category, "low", ents, q)
    return Intent(category, "high", ents, q)
