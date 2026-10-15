"""Split text into retrievable chunks and rank them against a sub-question.

Chunks are paragraph-aware windows of roughly CHUNK_CHARS characters. Ranking is a
cheap lexical overlap score so the researcher only sends the most relevant chunks to
the LLM (keeps tokens and cost down).
"""

from __future__ import annotations

import re

CHUNK_CHARS = 700
OVERLAP_CHARS = 100
MIN_CHUNK_CHARS = 120

_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = set(
    "the and for with that this from are was were has have had not but its into than then "
    "their there what which who will would about over under more most also been being".split()
)


def split_text(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 1 <= CHUNK_CHARS:
            current = f"{current}\n{para}".strip()
            continue
        if current:
            chunks.append(current)
        if len(para) > CHUNK_CHARS:  # hard-split very long paragraphs
            step = CHUNK_CHARS - OVERLAP_CHARS
            chunks += [para[i : i + CHUNK_CHARS] for i in range(0, len(para), step)]
            current = ""
        else:
            current = (current[-OVERLAP_CHARS:] + "\n" + para).strip() if current else para
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS]


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def relevance(chunk: str, query: str) -> float:
    q = _terms(query)
    if not q:
        return 0.0
    return len(q & _terms(chunk)) / len(q)


def top_chunks(chunks: list[str], query: str, k: int) -> list[str]:
    ranked = sorted(chunks, key=lambda c: relevance(c, query), reverse=True)
    return [c for c in ranked[:k] if relevance(c, query) > 0]
