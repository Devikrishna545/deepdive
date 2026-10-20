"""Small shared helpers: IDs, text normalisation, context-preserving parallel map."""

from __future__ import annotations

import contextvars
import hashlib
import re
import unicodedata
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar
from urllib.parse import urlparse

A = TypeVar("A")
B = TypeVar("B")

_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


# PDF text is typeset: "ﬁ" ligatures, words hyphenated across line breaks ("repre-\nsentations"),
# and a space left where a citation mark was removed ("proposed in , with").
_HYPHEN_BREAK = re.compile(r"(?<![\w-])([A-Za-z]+)-[ \t]*\n[ \t]*([a-z]+)")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:)\]])")


def clean_document_text(text: str) -> str:
    """Undo PDF typesetting so text reads (and matches quotes) as written: ligatures to letters
    (NFKC), words re-joined across hyphenated line breaks (a compound such as "state-of-the-\nart"
    keeps its hyphen), no space before punctuation. Line breaks are otherwise kept."""
    text = unicodedata.normalize("NFKC", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("||".join(parts).encode()).hexdigest()[:10]
    return f"{prefix}_{digest}"


def normalize(text: str) -> str:
    """Lowercase, unify quotes and dashes, collapse whitespace. Used for quote matching."""
    return _WS.sub(" ", text.translate(_QUOTES)).strip().lower()


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def parallel_map(fn: Callable[[A], B], items: Iterable[A], workers: int) -> list[B]:
    """Thread-pool map that keeps contextvars (token accounting) in worker threads."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, fn, item) for item in items]
        return [f.result() for f in futures]


# Markdown left in page text (Tavily returns `[text](url)` links and `[8]` footnote marks).
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_FOOTNOTE_LINK = re.compile(r"\[\[?\s*(?:\d{1,3}|[a-z]|note \d+)\s*\]?\]\([^)]*\)", re.I)  # [[8]](#cite_note-8)
_LINK = re.compile(r"\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)")  # [text](url) -> text (urls may hold parens)
_FOOTNOTE = re.compile(r"\[(?:\d{1,3}|[a-z]|citation needed)\]", re.I)  # [8], [a]
_EMPHASIS = re.compile(r"(\*\*|__|(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w))")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+", re.M)
_ARROW = re.compile(r"[↑^]\s*(?=\s|$)")


def clean_markdown(text: str) -> str:
    """Visible text only: drop images, footnote marks and link URLs; keep link text."""
    text = _IMAGE.sub("", text)
    text = _FOOTNOTE_LINK.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _FOOTNOTE.sub("", text)
    text = _EMPHASIS.sub("", text)
    text = _HEADING.sub("", text)
    text = _ARROW.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text)
