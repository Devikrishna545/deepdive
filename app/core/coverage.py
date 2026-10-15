"""Coverage gate: decides whether a sub-question has enough verified evidence.

A sub-question passes when it has at least MIN_SUPPORTED_CLAIMS kept claims drawn
from at least MIN_DISTINCT_DOMAINS distinct source domains. Thin sub-questions loop
back to research until MAX_LOOPS is reached, then are marked "limited evidence".
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.schemas import Chunk, Claim, Source, Verdict, VerdictLabel


@dataclass
class Coverage:
    sub_question_id: str
    supported: int
    domains: int

    def passes(self, min_claims: int, min_domains: int) -> bool:
        return self.supported >= min_claims and self.domains >= min_domains


def kept_claims(claims: list[Claim], verdicts: list[Verdict]) -> list[Claim]:
    """Claims whose latest verdict is SUPPORTED (narrowed children included)."""
    latest = {v.claim_id: v for v in verdicts}
    return [c for c in claims if (v := latest.get(c.id)) and v.label == VerdictLabel.SUPPORTED]


def coverage_by_subquestion(
    sub_question_ids: list[str],
    claims: list[Claim],
    verdicts: list[Verdict],
    chunks: dict[str, Chunk],
    sources: dict[str, Source],
) -> dict[str, Coverage]:
    result = {sq: Coverage(sq, 0, 0) for sq in sub_question_ids}
    domains: dict[str, set[str]] = {sq: set() for sq in sub_question_ids}
    for claim in kept_claims(claims, verdicts):
        if claim.sub_question_id not in result:
            continue
        result[claim.sub_question_id].supported += 1
        for cid in claim.cited_chunk_ids:
            chunk = chunks.get(cid)
            if chunk and (src := sources.get(chunk.source_id)):
                domains[claim.sub_question_id].add(src.domain or src.url)
    for sq, doms in domains.items():
        result[sq].domains = len(doms)
    return result


def find_gaps(
    coverage: dict[str, Coverage],
    loops: dict[str, int],
    min_claims: int,
    min_domains: int,
    max_loops: int,
) -> list[str]:
    """Sub-questions that are thin AND still have loop budget left."""
    return [
        sq
        for sq, cov in coverage.items()
        if not cov.passes(min_claims, min_domains) and loops.get(sq, 0) < max_loops
    ]
