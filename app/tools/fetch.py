"""Fetch a URL and extract clean main text (HTML via trafilatura, PDF via PyMuPDF).

Fetched pages are UNTRUSTED DATA: they are stored and quoted, never followed as
instructions. A failed fetch returns None and is logged; it never fails the run.
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.core.utils import stable_id
from app.db import repository as repo

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; DeepDiveResearchBot/0.1; +https://github.com/)"
MAX_CHARS = 60_000


class Page(BaseModel):
    url: str
    title: str = ""
    text: str
    published_at: str | None = None
    pages: list[tuple[int, str]] | None = None  # PDF: (page number, text)


def _from_pdf(url: str, data: bytes) -> Page:
    import fitz  # PyMuPDF

    with fitz.open(stream=data, filetype="pdf") as doc:
        pages = [(i + 1, p.get_text()) for i, p in enumerate(doc)]
        title = doc.metadata.get("title") or url
    return Page(url=url, title=title, text="\n".join(t for _, t in pages)[:MAX_CHARS], pages=pages)


def _from_html(url: str, html: str) -> Page | None:
    import trafilatura

    text = trafilatura.extract(html, include_comments=False, include_tables=True, favor_precision=True)
    if not text:
        return None
    meta = trafilatura.extract_metadata(html)
    return Page(
        url=url,
        title=(meta.title if meta else "") or "",
        text=text[:MAX_CHARS],
        published_at=(meta.date if meta else None),
    )


def fetch_page(url: str) -> Page | None:
    key = stable_id("fetch", url)
    cached = repo.cache_get(key)
    if cached is not None:
        return Page(**cached) if cached else None
    try:
        with httpx.Client(
            timeout=get_settings().fetch_timeout_s,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
        if "pdf" in resp.headers.get("content-type", "") or url.lower().endswith(".pdf"):
            page = _from_pdf(url, resp.content)
        else:
            page = _from_html(url, resp.text)
    except Exception as exc:
        log.info("fetch failed for %s: %s", url, exc)
        page = None
    repo.cache_put(key, "fetch", page.model_dump() if page else {})
    return page
