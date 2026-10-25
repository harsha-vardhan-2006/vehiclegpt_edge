"""Answer and evidence data models (validated with pydantic)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    evidence_id: str
    kind: str                      # signal | event | aggregate | trip | parameter
    reference: str                 # signal name, event id, "agg:..." etc.
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    timestamp: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    text: Optional[str] = None
    source: str
    quality_status: str = "good"
    data_maturity: str             # simulated | replayed | real
    produced_by: str               # SQL or calculation that produced it


class TimeRange(BaseModel):
    start: str
    end: str


class ValidationReport(BaseModel):
    status: str = "pass"                    # pass | warn | fail
    issues: list[str] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)


class Answer(BaseModel):
    question: str
    category: str
    direct_answer: str
    time_range: TimeRange
    evidence: list[Evidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_maturity: str = "simulated"
    model_used: Optional[str] = None
    chart: Optional[dict] = None
    validation: ValidationReport = Field(default_factory=ValidationReport)
    retrieval_status: str = "ok"     # ok | empty | unsupported | ambiguous
    duration_ms: float = 0.0
