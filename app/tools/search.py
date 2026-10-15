"""Web search tool. Tavily when TAVILY_API_KEY is set (returns page content), else DuckDuckGo.

Search is NOT an LLM call, so it does not go through Mesh. Do not enable Tavily's
`include_answer` (that is an AI-generated answer and would break the Mesh rule).
Results are cached in SQLite by query.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.config import get_settings
from app.core.utils import stable_id
from app.db import repository as repo

log = logging.getLogger(__name__)


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
        search_depth="advanced",
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


def _duckduckgo(query: str, max_results: int) -> list[SearchHit]:
    from ddgs import DDGS

    results = DDGS().text(query, max_results=max_results)
    return [
        SearchHit(url=r.get("href", ""), title=r.get("title", ""), snippet=r.get("body", ""))
        for r in results
        if r.get("href")
    ]


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
    repo.cache_put(key, "search", [h.model_dump() for h in hits])
    return hits
