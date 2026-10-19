"""Hybrid ranking: keyword overlap + meaning (embeddings via Mesh).

Keyword overlap alone cannot tell "transformer" the neural network from "transformer" the
power-grid device. Embeddings compare meaning, so a page about grid transformers scores low
for a question about AI. We combine both: keywords keep exact names, numbers and law titles
strong; meaning removes off-topic pages that share a word with the question.

Used twice per sub-question:
  1. search results (title + snippet) are scored BEFORE fetching, and clearly off-topic ones
     are skipped (saves fetches and keeps them out of the evidence);
  2. candidate passages are ranked by 0.5 x keyword score + 0.5 x meaning score.
Embeddings are cheap (text-embedding-3-small, about $0.02 per 1M tokens: a few hundredths of a
cent per sub-question). If the embedding call fails, ranking falls back to keywords only, so a
run never fails because of this step.
"""

from __future__ import annotations

import logging
import math

from app.llm.mesh_client import get_mesh

log = logging.getLogger(__name__)

# A search result is skipped when its meaning score is below this share of the best result's
# score for the same sub-question (relative, so it adapts to how well the query matched at all).
HIT_KEEP_RATIO = 0.7
MIN_HITS_KEPT = 2
KEYWORD_WEIGHT = 0.5  # passage score = KEYWORD_WEIGHT * keywords + (1 - KEYWORD_WEIGHT) * meaning
MAX_EMBED_CHARS = 2000  # a passage is ~700 chars; long snippets are trimmed


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def similarities(query: str, texts: list[str]) -> list[float] | None:
    """Cosine similarity of each text to the query, or None if embeddings are unavailable."""
    if not texts:
        return []
    try:
        vectors = get_mesh().embed([query[:MAX_EMBED_CHARS]] + [t[:MAX_EMBED_CHARS] for t in texts])
    except Exception as exc:  # noqa: BLE001 - ranking must never fail a run
        log.warning("embedding failed, ranking by keywords only: %s", str(exc)[:200])
        return None
    q, rest = vectors[0], vectors[1:]
    return [_cosine(q, v) for v in rest]


def keep_on_topic(sims: list[float] | None, n: int) -> list[bool]:
    """Which of n search results to keep, given their meaning scores (all kept if scores are missing)."""
    if not sims or max(sims) <= 0:
        return [True] * n
    best = max(sims)
    keep = [s >= best * HIT_KEEP_RATIO for s in sims]
    if sum(keep) < MIN_HITS_KEPT:  # never starve a sub-question: keep the best few
        for i in sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:MIN_HITS_KEPT]:
            keep[i] = True
    return keep


def hybrid_scores(keyword: list[float], meaning: list[float] | None) -> list[float]:
    """Combine keyword and meaning scores, each scaled to its own maximum first."""
    def scale(xs: list[float]) -> list[float]:
        top = max(xs) if xs else 0.0
        return [x / top if top > 0 else 0.0 for x in xs]

    if meaning is None:
        return keyword
    k, m = scale(keyword), scale(meaning)
    return [KEYWORD_WEIGHT * a + (1 - KEYWORD_WEIGHT) * b for a, b in zip(k, m, strict=False)]
