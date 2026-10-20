"""Shared LangGraph state. Reducers let parallel researchers write without clobbering."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from app.core.schemas import (
    Chunk,
    Claim,
    Contradiction,
    Finding,
    Report,
    Source,
    SubQuestion,
    Verdict,
)


def merge_dicts(left: dict, right: dict) -> dict:
    return {**(left or {}), **(right or {})}


class ResearchState(TypedDict, total=False):
    # inputs
    run_id: str
    question: str
    depth: str
    file_ids: list[str]
    # follow-up runs: the earlier research (questions + verified findings) for the planner, and the
    # earlier run's cited passages, which compete with new search results in the researcher's ranking
    context: str
    prior_chunks: dict[str, Chunk]
    prior_sources: dict[str, Source]
    doc_only: bool  # document mode: answer from the attached documents (app/core/doc_mode.py)
    doc_web: bool  # document mode with the web as an add-on for parts the documents leave thin

    # planning
    sub_questions: list[SubQuestion]
    loops: dict[str, int]  # sub_question_id -> number of extra research rounds used
    round: int  # 0 = first pass, 1.. = loop-back rounds
    gaps: list[str]  # sub_question_ids sent back for more research
    gap_queries: dict[str, list[str]]

    # evidence (merged from parallel researchers)
    sources: Annotated[dict[str, Source], merge_dicts]
    chunks: Annotated[dict[str, Chunk], merge_dicts]
    findings: Annotated[list[Finding], operator.add]
    research_log: Annotated[list[dict], operator.add]

    # claims and verification
    claims: Annotated[list[Claim], operator.add]
    verdicts: Annotated[list[Verdict], operator.add]
    contradictions: list[Contradiction]

    # output
    report: Report | None


class ResearchTask(TypedDict):
    """Payload sent to one parallel `research` node via LangGraph `Send`."""

    run_id: str
    question: str
    sub_question: SubQuestion
    queries: list[str]
    round: int
    file_ids: list[str]
    prior_chunks: list[Chunk]
    prior_sources: dict[str, Source]
    doc_only: bool
    doc_web: bool
