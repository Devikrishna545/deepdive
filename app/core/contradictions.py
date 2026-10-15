"""Contradiction detection across sources (bonus feature).

1. Embed kept claims per sub-question through Mesh.
2. Pairs with cosine similarity >= threshold that cite DIFFERENT sources are candidates.
3. The verifier model judges each candidate pair: agree / disagree / unrelated.
Disagreements are kept with both citations and surfaced in "Where sources disagree".

Premise-check sub-questions get a wider net: every claim type, and each pair is an OFFICIAL
claim against a non-official one (no similarity threshold, top MAX_PREMISE_PAIRS by similarity).
Status conflicts ("the EU abandoned the ban" vs the Commission page) are prose, not numbers,
and are exactly where a false premise hides. When an official claim disagrees with a claim
whose best source is tier "other" (blogs, industry sites), code supersedes the "other" claim:
it is removed from the report with a logged reason. News sources are never superseded, only
flagged, because a recent news report can be right about a change an official page predates.
"""

from __future__ import annotations

import logging
from itertools import combinations

import numpy as np

from app.core.schemas import Chunk, Claim, Contradiction, PairJudgementOut

log = logging.getLogger(__name__)

PAIR_SYSTEM = (
    "You compare two factual claims taken from different sources. Decide whether they "
    "AGREE, DISAGREE (cannot both be true, e.g. different numbers for the same measure "
    "and period, or opposite directions), or are UNRELATED (different topics or periods). "
    "Different wording of the same fact counts as agree. A change described as decided or done "
    "versus a rule the other claim shows still applies, or only proposed, counts as disagree."
)

MAX_PAIRS_PER_SUBQUESTION = 3
# Real disagreements between sources are almost always about figures or dates; checking
# only those claims keeps embeddings and pair judgements cheap.
CHECKED_TYPES = {"number", "date"}
MAX_PREMISE_PAIRS = 3
MIN_PREMISE_SIMILARITY = 0.3  # skip pairs about plainly different things


def _cosine_matrix(vectors: list[list[float]]) -> np.ndarray:
    m = np.asarray(vectors, dtype=float)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    m = m / np.where(norms == 0, 1, norms)
    return m @ m.T


def _source_ids(claim: Claim, chunks: dict[str, Chunk]) -> set[str]:
    return {chunks[c].source_id for c in claim.cited_chunk_ids if c in chunks}


def candidate_pairs(
    claims: list[Claim], vectors: list[list[float]], chunks: dict[str, Chunk], threshold: float
) -> list[tuple[Claim, Claim, float]]:
    if len(claims) < 2:
        return []
    sims = _cosine_matrix(vectors)
    pairs = []
    for i, j in combinations(range(len(claims)), 2):
        a, b = claims[i], claims[j]
        if a.sub_question_id != b.sub_question_id:
            continue
        if _source_ids(a, chunks) & _source_ids(b, chunks):
            continue  # same source cannot contradict itself here
        if sims[i, j] >= threshold:
            pairs.append((a, b, float(sims[i, j])))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs


def _judge(mesh, judge_model: str, a: Claim, b: Claim) -> PairJudgementOut:
    return mesh.chat_json(
        model=judge_model,
        system=PAIR_SYSTEM,
        user=f"CLAIM A: {a.text}\nCLAIM B: {b.text}",
        schema=PairJudgementOut,
        max_tokens=120,
    )


def premise_pairs(
    claims: list[Claim], vectors: list[list[float]], chunks: dict[str, Chunk], tiers: dict[str, str]
) -> list[tuple[Claim, Claim, float]]:
    """(official, non-official) pairs from different sources, most similar first."""
    if len(claims) < 2:
        return []
    sims = _cosine_matrix(vectors)
    pairs = []
    for i, j in combinations(range(len(claims)), 2):
        a, b = claims[i], claims[j]
        if (tiers.get(a.id) == "official") == (tiers.get(b.id) == "official"):
            continue
        if _source_ids(a, chunks) & _source_ids(b, chunks) or sims[i, j] < MIN_PREMISE_SIMILARITY:
            continue
        official, other = (a, b) if tiers.get(a.id) == "official" else (b, a)
        pairs.append((official, other, float(sims[i, j])))
    pairs.sort(key=lambda p: p[2], reverse=True)
    return pairs[:MAX_PREMISE_PAIRS]


def detect_contradictions(
    kept: list[Claim],
    chunks: dict[str, Chunk],
    mesh,
    judge_model: str,
    threshold: float,
    premise_sq_ids: set[str] | None = None,
    tiers: dict[str, str] | None = None,
) -> list[Contradiction]:
    premise_sq_ids, tiers = premise_sq_ids or set(), tiers or {}
    typed = [c for c in kept if getattr(c.claim_type, "value", c.claim_type) in CHECKED_TYPES
             and c.sub_question_id not in premise_sq_ids]
    premise = [c for c in kept if c.sub_question_id in premise_sq_ids]
    if len(typed) < 2 and len(premise) < 2:
        return []
    try:
        vectors = mesh.embed([c.text for c in typed + premise])
    except Exception as exc:  # embeddings are optional; never fail the run
        log.warning("contradiction detection skipped: %s", exc)
        return []
    found: list[Contradiction] = []
    per_sq: dict[str, int] = {}
    for a, b, _sim in candidate_pairs(typed, vectors[: len(typed)], chunks, threshold):
        if per_sq.get(a.sub_question_id, 0) >= MAX_PAIRS_PER_SUBQUESTION:
            continue
        per_sq[a.sub_question_id] = per_sq.get(a.sub_question_id, 0) + 1
        judgement = _judge(mesh, judge_model, a, b)
        if judgement.relation == "disagree":
            found.append(Contradiction(sub_question_id=a.sub_question_id, claim_a=a.id, claim_b=b.id,
                                       explanation=judgement.explanation or f'"{a.text}" vs "{b.text}"'))
    for official, other, _sim in premise_pairs(premise, vectors[len(typed):], chunks, tiers):
        judgement = _judge(mesh, judge_model, official, other)
        if judgement.relation == "disagree":
            found.append(Contradiction(
                sub_question_id=official.sub_question_id, claim_a=official.id, claim_b=other.id,
                explanation=judgement.explanation or f'"{official.text}" vs "{other.text}"',
                superseded_claim=other.id if tiers.get(other.id) == "other" else None,
            ))
    return found
