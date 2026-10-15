"""Contradiction detection across sources (bonus feature).

1. Embed kept claims per sub-question through Mesh.
2. Pairs with cosine similarity >= threshold that cite DIFFERENT sources are candidates.
3. The verifier model judges each candidate pair: agree / disagree / unrelated.
Disagreements are kept with both citations and surfaced in "Where sources disagree".
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
    "Different wording of the same fact counts as agree."
)

MAX_PAIRS_PER_SUBQUESTION = 3
# Real disagreements between sources are almost always about figures or dates; checking
# only those claims keeps embeddings and pair judgements cheap.
CHECKED_TYPES = {"number", "date"}


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


def detect_contradictions(
    kept: list[Claim], chunks: dict[str, Chunk], mesh, judge_model: str, threshold: float
) -> list[Contradiction]:
    kept = [c for c in kept if getattr(c.claim_type, "value", c.claim_type) in CHECKED_TYPES]
    if len(kept) < 2:
        return []
    try:
        vectors = mesh.embed([c.text for c in kept])
    except Exception as exc:  # embeddings are optional; never fail the run
        log.warning("contradiction detection skipped: %s", exc)
        return []
    found: list[Contradiction] = []
    per_sq: dict[str, int] = {}
    for a, b, _sim in candidate_pairs(kept, vectors, chunks, threshold):
        if per_sq.get(a.sub_question_id, 0) >= MAX_PAIRS_PER_SUBQUESTION:
            continue
        per_sq[a.sub_question_id] = per_sq.get(a.sub_question_id, 0) + 1
        judgement = mesh.chat_json(
            model=judge_model,
            system=PAIR_SYSTEM,
            user=f"CLAIM A: {a.text}\nCLAIM B: {b.text}",
            schema=PairJudgementOut,
            max_tokens=120,
        )
        if judgement.relation == "disagree":
            found.append(
                Contradiction(
                    sub_question_id=a.sub_question_id,
                    claim_a=a.id,
                    claim_b=b.id,
                    explanation=judgement.explanation or f'"{a.text}" vs "{b.text}"',
                )
            )
    return found
