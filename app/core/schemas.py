"""Pydantic contracts for everything that moves between agents.

Two kinds of model live here:
- *Output models (suffix `Out`): what an LLM must return. Kept small and flat so
  every Mesh model can produce them in JSON mode.
- Domain models: what the graph stores, with IDs assigned by code, never by the LLM.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- domain models


class SubQuestion(BaseModel):
    id: str
    text: str
    queries: list[str]
    rationale: str = ""


class Source(BaseModel):
    id: str
    url: str
    title: str = ""
    domain: str = ""
    published_at: str | None = None  # ISO date if known
    fetched_at: str | None = None
    kind: Literal["web", "file"] = "web"
    quality_score: float = 0.5


class Chunk(BaseModel):
    id: str
    source_id: str
    sub_question_id: str
    text: str
    page: int | None = None


class Finding(BaseModel):
    id: str
    sub_question_id: str
    text: str
    chunk_ids: list[str]
    round: int = 0


class ClaimType(str, Enum):
    FACT = "fact"
    NUMBER = "number"
    DATE = "date"
    OPINION = "opinion"


class Claim(BaseModel):
    id: str
    sub_question_id: str
    text: str
    cited_chunk_ids: list[str]
    claim_type: ClaimType = ClaimType.FACT
    parent_claim_id: str | None = None  # set when narrowed from a PARTIAL claim
    round: int = 0


class VerdictLabel(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class Verdict(BaseModel):
    claim_id: str
    label: VerdictLabel
    reason: str
    evidence_quote: str = ""
    narrowed_claim: str | None = None
    model: str = ""
    guard_downgraded: bool = False  # True when code overruled the LLM (quote not found)
    precheck_hints: list[str] = Field(default_factory=list)


class Contradiction(BaseModel):
    sub_question_id: str
    claim_a: str
    claim_b: str
    explanation: str


class ReportSentence(BaseModel):
    text: str
    claim_ids: list[str] = Field(default_factory=list)


class ReportSection(BaseModel):
    sub_question_id: str
    heading: str
    sentences: list[ReportSentence]
    limited_evidence: bool = False


class Reference(BaseModel):
    number: int
    source_id: str
    url: str
    title: str
    domain: str
    quality_score: float
    page: int | None = None


class Report(BaseModel):
    question: str
    executive_summary: list[ReportSentence]
    sections: list[ReportSection]
    disagreements: list[Contradiction] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    dropped_sentences: list[ReportSentence] = Field(default_factory=list)
    markdown: str = ""


# ------------------------------------------------------------- LLM output models


class SubQuestionOut(BaseModel):
    text: str
    queries: list[str] = Field(min_length=1, max_length=4)
    rationale: str = ""


class PlanOut(BaseModel):
    sub_questions: list[SubQuestionOut] = Field(min_length=1, max_length=8)


class GapQueriesOut(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=4)


class FindingOut(BaseModel):
    text: str
    chunk_ids: list[str] = Field(min_length=1)


class FindingsOut(BaseModel):
    findings: list[FindingOut] = Field(default_factory=list)


class ClaimOut(BaseModel):
    text: str
    cited_chunk_ids: list[str] = Field(min_length=1)
    claim_type: ClaimType = ClaimType.FACT


class ClaimsOut(BaseModel):
    claims: list[ClaimOut] = Field(default_factory=list)


class VerdictOut(BaseModel):
    label: VerdictLabel
    reason: str
    evidence_quote: str = ""
    narrowed_claim: str | None = None


class PairJudgementOut(BaseModel):
    relation: Literal["agree", "disagree", "unrelated"]
    explanation: str = ""


class SectionOut(BaseModel):
    sub_question_id: str
    heading: str
    sentences: list[ReportSentence]


class SynthesisOut(BaseModel):
    executive_summary: list[ReportSentence]
    sections: list[SectionOut]
    limitations: list[str] = Field(default_factory=list)
