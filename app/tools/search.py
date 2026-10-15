"""Web search tool. Tavily when TAVILY_API_KEY is set (returns page content), else DuckDuckGo.

Tavily is the reliable choice (free tier: 1,000 credits a month). DuckDuckGo needs no key but
rate-limits bursts of queries and then answers "No results found"; to soften that, DDG calls are
made one at a time with a short gap and one retry. Empty results are never cached.

Search is NOT an LLM call, so it does not go through Mesh. Do not enable Tavily's
`include_answer` (that is an AI-generated answer and would break the Mesh rule).
Results are cached in SQLite by query.
"""

from __future__ import annotations

import logging
import threading
import time

from pydantic import BaseModel

from app.config import get_settings
from app.core.utils import stable_id
from app.db import repository as repo

log = logging.getLogger(__name__)


class NoEvidence(RuntimeError):
    """Raised when a run found no sources at all, so it stops before paying for drafting."""


class SearchHit(BaseModel):
    url: str
    title: str = ""
    snippet: str = ""
    content: str | None = None  # full page text when the provider returns it
    published_at: str | None = None


def _tavily(query: str, max_results: int) -> list[SearchHit]:
    from tavily import TavilyClient

    client = TavilyClient(api_key=get_settings().tavily_api_key)
    resp = client.search(
        query=query,
        max_results=max_results,
        search_depth=get_settings().tavily_search_depth,
        include_answer=False,  # keep: AI answers would bypass Mesh
        include_raw_content=True,
    )
    return [
        SearchHit(
            url=r["url"],
            title=r.get("title", ""),
            snippet=r.get("content", ""),
            content=r.get("raw_content"),
            published_at=r.get("published_date"),
        )
        for r in resp.get("results", [])
    ]


_DDG_LOCK = threading.Lock()
_DDG_GAP_S = 1.5  # minimum gap between DDG calls (parallel sub-questions burst otherwise)
_DDG_RETRY_WAIT_S = 4.0
_ddg_last = 0.0


def _duckduckgo(query: str, max_results: int) -> list[SearchHit]:
    global _ddg_last
    from ddgs import DDGS

    last_exc: Exception | None = None
    for attempt in range(2):
        with _DDG_LOCK:
            wait = _DDG_GAP_S - (time.monotonic() - _ddg_last)
            if wait > 0:
                time.sleep(wait)
            try:
                results = DDGS().text(query, max_results=max_results)
            except Exception as exc:  # usually rate limiting, reported as "No results found"
                results, last_exc = [], exc
            finally:
                _ddg_last = time.monotonic()
        hits = [SearchHit(url=r.get("href", ""), title=r.get("title", ""), snippet=r.get("body", ""))
                for r in results or [] if r.get("href")]
        if hits:
            return hits
        if attempt == 0:
            time.sleep(_DDG_RETRY_WAIT_S)
    if last_exc:
        raise last_exc
    return []


def web_search(query: str, max_results: int | None = None) -> list[SearchHit]:
    max_results = max_results or get_settings().results_per_query
    provider = "tavily" if get_settings().tavily_api_key else "ddg"
    key = stable_id("search", provider, query, str(max_results))
    cached = repo.cache_get(key)
    if cached is not None:
        return [SearchHit(**h) for h in cached]
    try:
        hits = _tavily(query, max_results) if provider == "tavily" else _duckduckgo(query, max_results)
    except Exception as exc:  # a failed search must never fail the run
        log.warning("search failed for %r via %s: %s", query, provider, exc)
        return []
    if hits:  # never cache an empty answer: it is usually a temporary block, not a real "nothing"
        repo.cache_put(key, "search", [h.model_dump() for h in hits])
    return hits


def search_provider() -> str:
    return "tavily" if get_settings().tavily_api_key else "duckduckgo"
