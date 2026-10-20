"""Synthesizer agent: verified claims -> structured report whose sentences carry claim IDs.

It only ever sees KEPT (verified) claims. Every sentence it writes must list the claim
IDs it is based on; the deterministic citation check (app/core/citation_check.py)
removes any sentence that doesn't, so nothing unverified reaches the reader.
"""

from __future__ import annotations

import re

from app.agents.base import load_prompt
from app.config import get_settings
from app.core.coverage import Coverage
from app.core.schemas import (
    Claim,
    Contradiction,
    Report,
    ReportSection,
    ReportSentence,
    SectionOut,
    SubQuestion,
    SynthesisOut,
)
from app.llm.mesh_client import MeshError, get_mesh

_CLAIM_ID = re.compile(r"clm_[0-9a-f]+")


def _clean_ids(sentences: list[ReportSentence]) -> list[ReportSentence]:
    """Keep only well-formed claim ids. The model sometimes copies decoration from its input
    (benchmark 2: "clm_6bbef99ab8|official"), and the citation check then deletes the sentence.
    Extracting the id is parsing, not trust: the citation check still requires each id to be kept."""
    return [s.model_copy(update={"claim_ids": [m for cid in s.claim_ids for m in _CLAIM_ID.findall(cid)]})
            for s in sentences]

FALLBACK_NOTE = ("The writing step failed, so this report lists the verified claims as written by the "
                 "drafter, each cited to its source.")


def fallback_synthesis(sub_questions: list[SubQuestion], kept: list[Claim]) -> SynthesisOut:
    """Report built by code from verified claims only. Used when the model's reply stays invalid,
    so a paid run still ends with a report instead of failing. Every sentence is a kept claim."""
    sections = [
        SectionOut(sub_question_id=sq.id,
                   sentences=[ReportSentence(text=c.text, claim_ids=[c.id]) for c in kept if c.sub_question_id == sq.id])
        for sq in sub_questions
    ]
    summary = [sec.sentences[0] for sec in sections if sec.sentences][:5]
    return SynthesisOut(executive_summary=summary, sections=sections, limitations=[FALLBACK_NOTE])


class SynthesizerAgent:
    name = "synthesizer"

    def synthesize(
        self,
        question: str,
        sub_questions: list[SubQuestion],
        kept: list[Claim],
        contradictions: list[Contradiction],
        coverage: dict[str, Coverage],
        tiers: dict[str, str] | None = None,
        min_domains: int | None = None,
    ) -> Report:
        """`tiers`: claim id -> source tier ("official", "academic", "news", "other"), shown to the
        model as `[clm_x|official]` so it can prefer official sources when claims conflict."""
        s = get_settings()
        tiers = tiers or {}
        lines = []
        for sq in sub_questions:
            mark = " (PREMISE CHECK)" if sq.checks_premise else ""
            lines.append(f"\n### {sq.id}{mark}: {sq.text}")
            # documents first (document mode): the person asked about their documents
            sq_claims = sorted((c for c in kept if c.sub_question_id == sq.id), key=lambda c: tiers.get(c.id) != "document")
            lines += [f"[{c.id}] ({tiers.get(c.id, 'other')}) {c.text}" for c in sq_claims] or ["(no verified claims)"]
        disagreements = "\n".join(f"- {c.claim_a} vs {c.claim_b}: {c.explanation}" for c in contradictions) or "none"
        try:
            out = get_mesh().chat_json(
                model=s.model_synthesizer,
                system=load_prompt(self.name),
                user=(
                    f"QUESTION: {question}\n\nVERIFIED CLAIMS BY SUB-QUESTION:{''.join(chr(10) + x for x in lines)}"
                    f"\n\nSOURCES DISAGREE ON:\n{disagreements}"
                ),
                schema=SynthesisOut,
                temperature=0.2,
                max_tokens=1400,
            )
        except MeshError:
            out = fallback_synthesis(sub_questions, kept)
        by_id = {sec.sub_question_id: sec for sec in out.sections}
        sections = []
        for sq in sub_questions:  # keep plan order; add empty sections the model skipped
            sec = by_id.get(sq.id)
            cov = coverage.get(sq.id)
            limited = cov is None or not cov.passes(s.min_supported_claims, min_domains or s.min_distinct_domains)
            sections.append(
                ReportSection(
                    sub_question_id=sq.id,
                    heading=sq.text,  # code-set: a heading can't assert anything unverified
                    sentences=_clean_ids(sec.sentences) if sec else [],
                    limited_evidence=limited,
                )
            )
        return Report(
            question=question,
            executive_summary=_clean_ids(out.executive_summary),
            sections=sections,
            disagreements=contradictions,
            limitations=out.limitations,
        )
