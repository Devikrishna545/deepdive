"""Small shared helpers: IDs, text normalisation, context-preserving parallel map."""

from __future__ import annotations

import contextvars
import hashlib
import re
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar
from urllib.parse import urlparse

A = TypeVar("A")
B = TypeVar("B")

_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


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
