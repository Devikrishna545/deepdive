"""Offline stand-ins for Mesh and web search, so the whole graph runs in CI without keys.

FakeMesh behaves like a small, honest model: it extracts findings from the chunks it
is shown, drafts claims from them, and also drafts ONE fabricated claim per batch so the
verifier has something to reject. Its synthesizer adds one uncited sentence so the
citation check has something to remove.
"""

from __future__ import annotations

import hashlib
import re

from app.core.schemas import (
    ClaimOut,
    ClaimsOut,
    FindingOut,
    FindingsOut,
    GapQueriesOut,
    PairJudgementOut,
    PlanOut,
    ReportSentence,
    SectionOut,
    SubQuestionOut,
    SynthesisOut,
    VerdictLabel,
    VerdictOut,
)
from app.core.utils import normalize
from app.llm.usage import record_usage
from app.tools.search import SearchHit

CHUNK_RE = re.compile(r"<CHUNK id=([^\s|>]+)[^>]*>\n(.*?)\n</CHUNK>", re.S)
FINDING_RE = re.compile(r"^- (.*) \(chunks: ([^)]*)\)$", re.M)
CLAIM_RE = re.compile(r"^\[(clm_[0-9a-f]+)\] (?:\([a-z]+\) )?(.*)$", re.M)
SQ_RE = re.compile(r"^### (sq_[0-9a-f]+)(?: \(PREMISE CHECK\))?: ", re.M)

FABRICATED = "Battery prices will fall by 99 percent next year"


class FakeMesh:
    def __init__(self):
        self.calls: list[str] = []
        self.prompts: list[str] = []

    def chat_json(self, *, model, system, user, schema, temperature=0.0, max_tokens=800, fallback_model=None,
                  reasoning_effort=None):
        self.calls.append(schema.__name__)
        self.prompts.append(user)
        # report plausible usage so token/cost accounting is exercised offline
        record_usage(model=model, prompt_tokens=(len(system) + len(user)) // 4, completion_tokens=40, latency_ms=1)
        if schema is PlanOut:
            return PlanOut(
                sub_questions=[
                    SubQuestionOut(text="What is the battery market size", queries=["battery market size 2026"]),
                    SubQuestionOut(text="What are the battery supply risks", queries=["battery supply risks"]),
                ]
            )
        if schema is GapQueriesOut:
            return GapQueriesOut(queries=["battery supply risks report"])
        if schema is FindingsOut:
            findings = [
                FindingOut(text=text.split(". ")[0].strip().rstrip(".") + ".", chunk_ids=[cid])
                for cid, text in CHUNK_RE.findall(user)
            ]
            return FindingsOut(findings=findings)
        if schema is ClaimsOut:
            rows = FINDING_RE.findall(user)
            claims = [ClaimOut(text=t, cited_chunk_ids=[ids.split(", ")[0]]) for t, ids in rows]
            if rows:
                claims.append(ClaimOut(text=FABRICATED, cited_chunk_ids=[rows[0][1].split(", ")[0]]))
            return ClaimsOut(claims=claims)
        if schema is VerdictOut:
            claim = user.split("\n", 1)[0].removeprefix("CLAIM: ")
            sources = " ".join(t for _, t in CHUNK_RE.findall(user))
            if normalize(claim.rstrip(".")) in normalize(sources):
                return VerdictOut(label=VerdictLabel.SUPPORTED, reason="stated", evidence_quote=claim.rstrip("."))
            return VerdictOut(label=VerdictLabel.UNSUPPORTED, reason="not in source")
        if schema is PairJudgementOut:
            return PairJudgementOut(relation="unrelated")
        if schema is SynthesisOut:
            claims = CLAIM_RE.findall(user)
            sq_ids = SQ_RE.findall(user)
            summary = [ReportSentence(text=t, claim_ids=[cid]) for cid, t in claims[:2]]
            summary.append(ReportSentence(text="An unsupported flourish with no citation.", claim_ids=[]))
            sections = [SectionOut(sub_question_id=sq, sentences=[]) for sq in sq_ids]
            for cid, text in claims:
                sections[0].sentences.append(ReportSentence(text=text, claim_ids=[cid]))
            return SynthesisOut(executive_summary=summary, sections=sections, limitations=["Offline test data."])
        raise AssertionError(f"unexpected schema {schema}")

    def embed(self, texts, model=None):
        out = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            out.append([b / 255 for b in h[:16]])
        return out


def _page(domain: str, topic: str, n: int) -> SearchHit:
    sentences = [
        f"The {topic} reached {n} units according to {domain} analysts in 2026",
        f"Analysts at {domain} describe {topic} trends and battery market supply risks in detail",
        f"Further context on the {topic} from {domain} covers pricing and regional demand",
    ]
    return SearchHit(url=f"https://{domain}/{topic.replace(' ', '-')}", title=f"{topic} - {domain}", content=". ".join(sentences) + ".")


SEARCH_RESULTS = {
    "battery market size 2026": [_page("iea.org", "battery market size", 120), _page("reuters.com", "battery market size", 130)],
    # first pass for the risk sub-question: a single domain -> coverage gate must loop back
    "battery supply risks": [_page("example-blog.com", "battery supply risks", 3)],
    "battery supply risks report": [_page("worldbank.org", "battery supply risks", 7)],
}


def fake_search(query: str, max_results: int | None = None) -> list[SearchHit]:
    return SEARCH_RESULTS.get(query, [])


def fake_fetch(url: str):
    return None
