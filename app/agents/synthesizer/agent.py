"""Synthesizer agent: verified claims -> structured report whose sentences carry claim IDs.

It only ever sees KEPT (verified) claims. Every sentence it writes must list the claim
IDs it is based on; the deterministic citation check (app/core/citation_check.py)
removes any sentence that doesn't, so nothing unverified reaches the reader.
"""

from __future__ import annotations

from app.agents.base import load_prompt
from app.config import get_settings
from app.core.coverage import Coverage
from app.core.schemas import Claim, Contradiction, Report, ReportSection, SubQuestion, SynthesisOut
from app.llm.mesh_client import get_mesh


class SynthesizerAgent:
    name = "synthesizer"

    def synthesize(
        self,
        question: str,
        sub_questions: list[SubQuestion],
        kept: list[Claim],
        contradictions: list[Contradiction],
        coverage: dict[str, Coverage],
    ) -> Report:
        s = get_settings()
        lines = []
        for sq in sub_questions:
            lines.append(f"\n### {sq.id}: {sq.text}")
            sq_claims = [c for c in kept if c.sub_question_id == sq.id]
            lines += [f"[{c.id}] {c.text}" for c in sq_claims] or ["(no verified claims)"]
        disagreements = "\n".join(f"- {c.claim_a} vs {c.claim_b}: {c.explanation}" for c in contradictions) or "none"
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
        by_id = {sec.sub_question_id: sec for sec in out.sections}
        sections = []
        for sq in sub_questions:  # keep plan order; add empty sections the model skipped
            sec = by_id.get(sq.id)
            cov = coverage.get(sq.id)
            limited = cov is None or not cov.passes(s.min_supported_claims, s.min_distinct_domains)
            sections.append(
                ReportSection(
                    sub_question_id=sq.id,
                    heading=sec.heading if sec else sq.text,
                    sentences=sec.sentences if sec else [],
                    limited_evidence=limited,
                )
            )
        return Report(
            question=question,
            executive_summary=out.executive_summary,
            sections=sections,
            disagreements=contradictions,
            limitations=out.limitations,
        )
