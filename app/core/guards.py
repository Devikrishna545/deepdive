"""Deterministic verification guards. Code, not the LLM, has the final say here.

- `precheck_claim`: cheap, no-LLM hints (numbers/dates in the claim missing from the source).
- `apply_quote_guard`: if the verifier's evidence quote is not literally in the cited
  chunk text, a SUPPORTED/PARTIAL verdict is downgraded to UNSUPPORTED. This stops the
  verifier itself from hallucinating support.
"""

from __future__ import annotations

import re

from app.core.schemas import Verdict, VerdictLabel
from app.core.utils import clean_markdown, normalize

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
MIN_QUOTE_CHARS = 12


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUMBER.findall(text)}


def precheck_claim(claim_text: str, source_texts: list[str]) -> list[str]:
    """Return human-readable hints; empty list means nothing suspicious."""
    hints: list[str] = []
    if not source_texts:
        return ["no cited chunk text available"]
    source_numbers = set().union(*(_numbers(t) for t in source_texts))
    missing = sorted(n for n in _numbers(claim_text) if n not in source_numbers)
    if missing:
        hints.append(f"numbers not found in cited text: {', '.join(missing)}")
    return hints


_ELLIPSIS = re.compile(r"\s*(?:\.\.\.|…|\[\.\.\.\])\s*")
MIN_PART_CHARS = 4  # ignore crumbs like "a" between two ellipses


def _in_order(parts: list[str], text: str) -> bool:
    pos = 0
    for part in parts:
        found = text.find(part, pos)
        if found == -1:
            return False
        pos = found + len(part)
    return True


def quote_in_sources(quote: str, source_texts: list[str]) -> bool:
    """True when the quote's visible text is in one cited chunk.

    Both sides are compared without Markdown (links, footnote marks). A quote that skips text
    with "..." passes only if every piece is in the same chunk, in order, and one piece alone
    is at least MIN_QUOTE_CHARS long, so "..." can't be used to stitch a claim from fragments.
    """
    q = normalize(clean_markdown(quote)).strip(" .\"'")
    parts = [p.strip(" .\"'") for p in _ELLIPSIS.split(q)]
    parts = [p for p in parts if len(p) >= MIN_PART_CHARS]
    if not parts or max(len(p) for p in parts) < MIN_QUOTE_CHARS:
        return False
    return any(_in_order(parts, normalize(clean_markdown(t))) for t in source_texts)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text: str) -> set[str]:
    return {normalize(s).strip(" .\"'") for s in _SENTENCE_SPLIT.split(clean_markdown(text)) if s.strip()}


def verbatim_in_sources(claim_text: str, source_texts: list[str], min_chars: int = 25) -> bool:
    """True only when the claim equals a WHOLE sentence of a cited chunk.

    Whole-sentence equality (not substring) is what makes skipping the LLM safe: a fragment like
    "prices will rise" inside "analysts deny that prices will rise" does not qualify.
    """
    c = normalize(claim_text).strip(" .\"'")
    return len(c) >= min_chars and any(c in _sentences(t) for t in source_texts)


def apply_quote_guard(verdict: Verdict, source_texts: list[str]) -> Verdict:
    if verdict.label not in (VerdictLabel.SUPPORTED, VerdictLabel.PARTIAL):
        return verdict
    if quote_in_sources(verdict.evidence_quote, source_texts):
        return verdict
    return verdict.model_copy(
        update={
            "label": VerdictLabel.UNSUPPORTED,
            "reason": f"quote guard: evidence quote not found in cited source "
            f"(verifier said {verdict.label.value}: {verdict.reason})",
            "guard_downgraded": True,
        }
    )
