"""Researcher agent: one sub-question -> stored evidence (sources + chunks) + findings.

Pipeline (one instance per sub-question, run in parallel by the graph):
  search each query -> skip off-topic results by meaning (embeddings) and rank the rest by
  meaning + source quality -> fetch and extract text -> chunk -> keyword pre-filter per page ->
  hybrid ranking (keywords + meaning) across pages (+ uploaded-document chunks) ->
  LLM extracts atomic findings that cite chunk IDs.
Every chunk is stored with its source BEFORE any LLM sees it, so every later claim
can be traced back to a URL (or file + page).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.agents.base import chunk_block, load_prompt
from app.config import get_settings
from app.core.schemas import Chunk, Finding, FindingsOut, Source, SubQuestion
from app.core.scoring import quality_score
from app.core.utils import domain_of, new_id, parallel_map, stable_id
from app.llm.mesh_client import get_mesh
from app.tools import documents
from app.tools.chunker import relevance, split_text, top_chunks
from app.tools.fetch import fetch_page
from app.tools.search import SearchHit, web_search
from app.tools.semantic import hybrid_scores, keep_on_topic, similarities

log = logging.getLogger(__name__)

CHUNKS_PER_PAGE = 3  # was 2: the first benchmark lost fetched facts at this cut
CANDIDATES_PER_PAGE = 8  # keyword pre-filter per page; the hybrid ranking then picks the best
MAX_FINDINGS = 10


@dataclass
class ResearchResult:
    sources: dict[str, Source] = field(default_factory=dict)
    chunks: dict[str, Chunk] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    urls_fetched: list[str] = field(default_factory=list)
    urls_failed: list[str] = field(default_factory=list)
    urls_skipped: list[str] = field(default_factory=list)  # search results judged off-topic by meaning


class ResearcherAgent:
    name = "researcher"

    # ------------------------------------------------------------ evidence
    def _collect_hits(self, queries: list[str], topic: str, result: ResearchResult) -> list[SearchHit]:
        seen: dict[str, SearchHit] = {}
        for q in queries:
            for hit in web_search(q):
                seen.setdefault(hit.url, hit)
        hits = list(seen.values())
        # Meaning check before fetching: "transformer" the grid device is skipped for an AI question.
        sims = similarities(topic, [f"{h.title}. {h.snippet or (h.content or '')[:500]}" for h in hits])
        keep = keep_on_topic(sims, len(hits))
        result.urls_skipped = [h.url for h, k in zip(hits, keep, strict=False) if not k]
        meaning = {h.url: s for h, s in zip(hits, sims or [], strict=False)}
        best = max(meaning.values(), default=0.0) or 1.0
        hits = [h for h, k in zip(hits, keep, strict=False) if k]

        def rank(h: SearchHit) -> float:
            quality = quality_score(domain_of(h.url), h.published_at)
            return 0.7 * meaning[h.url] / best + 0.3 * quality if meaning else quality

        hits.sort(key=rank, reverse=True)
        return hits[: get_settings().max_pages_per_subquestion]

    def _page_chunks(self, hit: SearchHit, sq: SubQuestion, result: ResearchResult, focus: str) -> None:
        text, title, published = hit.content, hit.title, hit.published_at
        if not text:
            page = fetch_page(hit.url)
            if page is None:
                result.urls_failed.append(hit.url)
                return
            text, title, published = page.text, page.title or title, page.published_at or published
        result.urls_fetched.append(hit.url)
        domain = domain_of(hit.url)
        source = Source(
            id=stable_id("src", hit.url),
            url=hit.url,
            title=title or hit.url,
            domain=domain,
            published_at=published,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            kind="web",
            quality_score=quality_score(domain, published),
        )
        result.sources[source.id] = source
        for piece in top_chunks(split_text(text), focus, CANDIDATES_PER_PAGE):
            chunk = Chunk(id=stable_id("chk", hit.url, piece[:200]), source_id=source.id, sub_question_id=sq.id, text=piece)
            result.chunks[chunk.id] = chunk

    def _document_chunks(self, sq: SubQuestion, file_ids: list[str], result: ResearchResult) -> None:
        if not file_ids:
            return
        docs = documents.get_documents(file_ids)
        for row in documents.retrieve(file_ids, sq.text, k=4):
            doc = docs.get(row.document_id)
            name = doc.filename if doc else row.document_id
            source = Source(
                id=stable_id("src", "file", row.document_id),
                url=f"file://{name}",
                title=name,
                domain=name,
                kind="file",
                quality_score=quality_score(name, None, kind="file"),
            )
            result.sources[source.id] = source
            chunk = Chunk(id=stable_id("chk", row.id), source_id=source.id, sub_question_id=sq.id, text=row.text, page=row.page)
            result.chunks[chunk.id] = chunk

    def _select_chunks(self, chunks: list[Chunk], topic: str, focus: str, limit: int) -> dict[str, Chunk]:
        """Hybrid ranking across pages (token control): best `limit` chunks, at most
        CHUNKS_PER_PAGE from one source so a single page cannot fill the evidence."""
        scores = hybrid_scores([relevance(c.text, focus) for c in chunks], similarities(topic, [c.text for c in chunks]))
        ranked = [c for _, c in sorted(zip(scores, chunks, strict=False), key=lambda x: x[0], reverse=True)]
        picked: dict[str, Chunk] = {}
        per_source: dict[str, int] = {}
        for c in ranked:
            if len(picked) >= limit:
                break
            if per_source.get(c.source_id, 0) >= CHUNKS_PER_PAGE:
                continue
            per_source[c.source_id] = per_source.get(c.source_id, 0) + 1
            picked[c.id] = c
        return picked

    # ------------------------------------------------------------ main entry
    def research(
        self, question: str, sq: SubQuestion, queries: list[str], round_no: int, file_ids: list[str]
    ) -> ResearchResult:
        s = get_settings()
        result = ResearchResult(queries=list(queries))
        topic = f"{question} {sq.text}"  # meaning: what the person asked, not the query wording
        hits = self._collect_hits(queries, topic, result)
        # keywords: rank passages against the main question too, not only the sub-question wording
        focus = f"{question} {sq.text} {' '.join(queries)}"
        parallel_map(lambda h: self._page_chunks(h, sq, result, focus), hits, workers=s.max_concurrency)
        self._document_chunks(sq, file_ids, result)
        result.chunks = self._select_chunks(list(result.chunks.values()), topic, focus, s.chunks_per_subquestion)
        if not result.chunks:
            return result

        blocks = "\n\n".join(
            chunk_block(c.id, c.text) for c in result.chunks.values()
        )
        out = get_mesh().chat_json(
            model=s.model_researcher,
            system=load_prompt(self.name),
            user=f"MAIN QUESTION: {question}\nSUB-QUESTION: {sq.text}\n\nEVIDENCE:\n{blocks}",
            schema=FindingsOut,
            temperature=0.0,
            max_tokens=800,  # up to 10 findings
        )
        valid_ids = set(result.chunks)
        for f in out.findings[:MAX_FINDINGS]:
            ids = [cid for cid in f.chunk_ids if cid in valid_ids]
            if ids and f.text.strip():  # a finding without a real chunk is discarded
                result.findings.append(
                    Finding(id=new_id("fnd"), sub_question_id=sq.id, text=f.text.strip(), chunk_ids=ids, round=round_no)
                )
        return result
