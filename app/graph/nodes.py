"""Graph nodes. Each node: read state -> call ONE agent (or pure code) -> return a state update.

Nodes contain orchestration only. Prompts and LLM logic live in app/agents/<name>/,
deterministic checks in app/core/. Every node returns a `_trail` entry for the audit log.
"""

from __future__ import annotations

from app.agents import DrafterAgent, PlannerAgent, ResearcherAgent, SynthesizerAgent, VerifierAgent
from app.config import get_settings
from app.core.citation_check import build_references, enforce_citations, render_markdown
from app.core.contradictions import detect_contradictions
from app.core.coverage import coverage_by_subquestion, find_gaps, kept_claims
from app.core.key_claims import fill_key_claims
from app.core.schemas import SubQuestion, Verdict, VerdictLabel
from app.core.scoring import source_label
from app.core.utils import new_id, parallel_map
from app.db import repository as repo
from app.graph.state import ResearchState, ResearchTask
from app.llm.mesh_client import get_mesh
from app.llm.usage import run_usage
from app.tools import documents
from app.tools.search import NoEvidence, search_provider

# Stop looping once a run has spent this share of RUN_BUDGET_USD, so it finishes with a
# report instead of being cut off by the hard budget stop.
LOOP_BUDGET_SHARE = 0.6

planner = PlannerAgent()
researcher = ResearcherAgent()
drafter = DrafterAgent()
verifier = VerifierAgent()
synthesizer = SynthesizerAgent()


def _min_domains(state: ResearchState) -> int:
    """Independent domains a sub-question needs. In document mode the attached document is the
    source being asked about, so one is enough (a second domain would mean the web, which the
    question did not ask for)."""
    return 1 if state.get("doc_only") else get_settings().min_distinct_domains


def _coverage(state: ResearchState):
    return coverage_by_subquestion(
        [sq.id for sq in state["sub_questions"]],
        state.get("claims", []),
        state.get("verdicts", []),
        state.get("chunks", {}),
        state.get("sources", {}),
    )


# ------------------------------------------------------------------ plan
def plan(state: ResearchState) -> dict:
    if state.get("context"):
        return _plan_followup(state)
    if state.get("doc_only"):
        return _plan_documents(state)
    depth = state.get("depth", "standard")
    key = planner.plan_key(state["question"], depth) if get_settings().cache_plans else None
    cached = repo.cache_get(key) if key else None
    if cached:  # same plan, fresh ids (ids are per run)
        sub_questions = [SubQuestion(**(sq | {"id": new_id("sq")})) for sq in cached]
    else:
        sub_questions = planner.plan(state["question"], depth)
        if key:
            repo.cache_put(key, "plan", [sq.model_dump(exclude={"id"}) for sq in sub_questions])
    return {
        "sub_questions": sub_questions,
        "loops": {sq.id: 0 for sq in sub_questions},
        "round": 0,
        "_trail": {
            "summary": f"planned {len(sub_questions)} sub-questions" + (" (reused cached plan)" if cached else ""),
            "payload": {"sub_questions": [sq.model_dump() for sq in sub_questions]},
        },
    }


def _plan_followup(state: ResearchState) -> dict:
    """Follow-up: plan with the earlier research as context (never cached: the context is part of
    the plan). The rest of the run researches the standalone question."""
    docs = documents.document_preview(state.get("file_ids", [])) if state.get("doc_only") else ""
    sub_questions, standalone = planner.plan_followup(state["question"], state.get("depth", "standard"), state["context"], docs)
    reused = len(state.get("prior_chunks", {}))
    return {
        "question": standalone,
        "sub_questions": sub_questions,
        "loops": {sq.id: 0 for sq in sub_questions},
        "round": 0,
        "_trail": {
            "summary": f"follow-up: planned {len(sub_questions)} sub-questions for \"{standalone[:90]}\"; "
            f"{reused} verified passage(s) from the earlier research can be reused"
            + ("; answering from your documents only" if docs else ""),
            "payload": {"follow_up_of": state["question"], "researched_as": standalone,
                        "sub_questions": [sq.model_dump() for sq in sub_questions]},
        },
    }


def _plan_documents(state: ResearchState) -> dict:
    """Document mode: plan from the documents' opening text; never cached (the documents are part
    of the plan), no premise check, no web search."""
    file_ids = state.get("file_ids", [])
    sub_questions = planner.plan_documents(state["question"], state.get("depth", "standard"),
                                           documents.document_preview(file_ids))
    names = sorted(d.filename for d in documents.get_documents(file_ids).values())
    return {
        "sub_questions": sub_questions,
        "loops": {sq.id: 0 for sq in sub_questions},
        "round": 0,
        "_trail": {
            "summary": f"planned {len(sub_questions)} sub-questions; answering from your documents only "
            f"({', '.join(names)}), no web search",
            "payload": {"document_mode": True, "documents": names,
                        "sub_questions": [sq.model_dump() for sq in sub_questions]},
        },
    }


# ------------------------------------------------------------------ research (parallel)
def research(task: ResearchTask) -> dict:
    sq = task["sub_question"]
    result = researcher.research(task["question"], sq, task["queries"], task["round"], task.get("file_ids", []),
                                 task.get("prior_chunks", []), task.get("prior_sources", {}), task.get("doc_only", False))
    log_entry = {
        "sub_question_id": sq.id,
        "round": task["round"],
        "queries": result.queries,
        "urls_fetched": result.urls_fetched,
        "urls_failed": result.urls_failed,
        "urls_skipped_off_topic": result.urls_skipped,
        "chunks": len(result.chunks),
        "chunks_from_earlier_research": result.reused,
        "findings": len(result.findings),
    }
    return {
        "sources": result.sources,
        "chunks": result.chunks,
        "findings": result.findings,
        "research_log": [log_entry],
        "_trail": {
            "summary": f"{sq.text[:60]}: {len(result.urls_fetched)} pages"
            + (f" ({len(result.urls_skipped)} off-topic results skipped)" if result.urls_skipped else "")
            + f", {len(result.chunks)} chunks"
            + (f" ({result.reused} from the earlier research)" if result.reused else "")
            + f", {len(result.findings)} findings",
            "payload": log_entry | {"findings_text": [f.text for f in result.findings]},
        },
    }


# ------------------------------------------------------------------ draft
def draft(state: ResearchState) -> dict:
    round_no = state.get("round", 0)
    chunks = state.get("chunks", {})
    if round_no == 0 and not chunks:
        # Nothing was retrieved for any sub-question: almost always a search outage or block.
        # Stop now instead of paying for gap planning and an empty report.
        if state.get("doc_only"):
            raise NoEvidence("no sources found: the attached documents had no passages for this question")
        raise NoEvidence(f"no sources found for any sub-question (search provider: {search_provider()}). "
                         "Run `python -m scripts.check_search`; set TAVILY_API_KEY if DuckDuckGo is blocked.")
    jobs = []
    for sq in state["sub_questions"]:
        findings = [f for f in state.get("findings", []) if f.sub_question_id == sq.id and f.round == round_no]
        if findings:
            jobs.append((sq, findings))
    batches = parallel_map(lambda j: drafter.draft(j[0], j[1], chunks, round_no), jobs, get_settings().max_concurrency)
    claims = [c for batch in batches for c in batch]
    return {
        "claims": claims,
        "_trail": {
            "summary": f"drafted {len(claims)} atomic claims (round {round_no})",
            "payload": {"claims": [c.model_dump() for c in claims]},
        },
    }


# ------------------------------------------------------------------ verify
def verify(state: ResearchState) -> dict:
    s = get_settings()
    done = {v.claim_id for v in state.get("verdicts", [])}
    pending = [c for c in state.get("claims", []) if c.id not in done]
    chunks, sources = state.get("chunks", {}), state.get("sources", {})
    if not s.verify_enabled:
        pairs = [(c, verifier.passthrough(c)) for c in pending]
    else:
        nested = parallel_map(lambda c: verifier.verify(c, chunks, sources), pending, s.max_concurrency)
        pairs = [p for group in nested for p in group]
    children = [c for c, _ in pairs if c.parent_claim_id]
    verdicts = [v for _, v in pairs]
    counts = {label.value: sum(v.label == label for v in verdicts) for label in VerdictLabel}
    claim_text = {c.id: c.text for c, _ in pairs}
    return {
        "claims": children,
        "verdicts": verdicts,
        "_trail": {
            "summary": "verified {n}: {SUPPORTED} supported, {PARTIAL} partial, {UNSUPPORTED} unsupported, "
            "{CONTRADICTED} contradicted".format(n=len(verdicts), **counts),
            "payload": {
                "counts": counts,
                "verdicts": [v.model_dump() | {"claim_text": claim_text.get(v.claim_id, "")} for v in verdicts],
            },
        },
    }


# ------------------------------------------------------------------ coverage gate (router)
def coverage_gate(state: ResearchState) -> str:
    s = get_settings()
    coverage = _coverage(state)
    gaps = find_gaps(coverage, state.get("loops", {}), s.min_supported_claims, _min_domains(state), s.max_loops)
    spent = run_usage(state["run_id"])["cost_usd"]
    budget_stop = bool(gaps) and s.run_budget_usd > 0 and spent >= LOOP_BUDGET_SHARE * s.run_budget_usd
    if budget_stop:
        gaps = []
    repo.add_event(
        state["run_id"],
        "coverage_gate",
        "info",
        summary=(
            f"loop back for {len(gaps)} thin sub-question(s)" if gaps
            else f"skip loop-back: run already spent ${spent:.4f} of ${s.run_budget_usd:.2f} budget" if budget_stop
            else "coverage ok, continue to report"
        ),
        payload={
            "coverage": {k: vars(v) for k, v in coverage.items()},
            "gaps": gaps,
            "loops": state.get("loops", {}),
        },
    )
    return "gaps" if gaps else "ok"


# ------------------------------------------------------------------ gap planning (loop back)
def gap_plan(state: ResearchState) -> dict:
    s = get_settings()
    coverage = _coverage(state)
    loops = dict(state.get("loops", {}))
    gaps = find_gaps(coverage, loops, s.min_supported_claims, _min_domains(state), s.max_loops)
    latest = {v.claim_id: v for v in state.get("verdicts", [])}
    sub_questions, gap_queries = [], {}
    for sq in state["sub_questions"]:
        if sq.id in gaps:
            reasons = [
                v.reason
                for c in state.get("claims", [])
                if c.sub_question_id == sq.id and (v := latest.get(c.id)) and v.label != VerdictLabel.SUPPORTED
            ]
            cov = coverage[sq.id]
            reasons.append(f"only {cov.supported} supported claims from {cov.domains} distinct domains")
            queries = planner.gap_queries(state["question"], sq, reasons)
            loops[sq.id] = loops.get(sq.id, 0) + 1
            if queries:
                gap_queries[sq.id] = queries
                sq = sq.model_copy(update={"queries": sq.queries + queries})
            else:  # nothing new to search: stop looping on this one
                loops[sq.id] = s.max_loops
        sub_questions.append(sq)
    return {
        "sub_questions": sub_questions,
        "loops": loops,
        "round": state.get("round", 0) + 1,
        "gaps": list(gap_queries),
        "gap_queries": gap_queries,
        "_trail": {
            "summary": f"loop-back: new queries for {len(gap_queries)} sub-question(s)",
            "payload": {"gap_queries": gap_queries, "loops": loops},
        },
    }


# ------------------------------------------------------------------ contradictions
def cross_check(state: ResearchState) -> dict:
    s = get_settings()
    kept = kept_claims(state.get("claims", []), state.get("verdicts", []))
    chunks, sources = state.get("chunks", {}), state.get("sources", {})
    premise_ids = {sq.id for sq in state.get("sub_questions", []) if sq.checks_premise}
    found = (
        detect_contradictions(kept, chunks, get_mesh(), s.model_verifier, s.contradiction_similarity,
                              premise_ids, _claim_tiers(kept, chunks, sources))
        if s.verify_enabled
        else []
    )
    # Code supersedes a blog/industry claim that an official source contradicts: the latest
    # verdict wins, so this removes it from the report and shows the reason in the Claims tab.
    by_id = {c.id: c for c in kept}
    superseded = [
        Verdict(claim_id=c.superseded_claim, label=VerdictLabel.CONTRADICTED, model="code:official-source",
                reason=f"contradicted by an official source: {by_id[c.claim_a].text[:160]}")
        for c in found if c.superseded_claim in by_id
    ]
    return {
        "contradictions": found,
        "verdicts": superseded,
        "_trail": {
            "summary": f"{len(found)} disagreement(s) across sources"
            + (f", {len(superseded)} claim(s) superseded by an official source" if superseded else ""),
            "payload": {"contradictions": [c.model_dump() for c in found]},
        },
    }


# ------------------------------------------------------------------ synthesize
def _claim_tiers(claims, chunks, sources) -> dict[str, str]:
    """Best source tier behind each claim, as a short label for the synthesizer."""
    rank = {"official": 0, "academic": 1, "news": 2, "other": 3}
    out = {}
    for c in claims:
        labels = [source_label(sources[chunks[cid].source_id])
                  for cid in c.cited_chunk_ids if cid in chunks and chunks[cid].source_id in sources]
        out[c.id] = min(labels, key=rank.get) if labels else "other"
    return out


def synthesize(state: ResearchState) -> dict:
    kept = kept_claims(state.get("claims", []), state.get("verdicts", []))
    tiers = _claim_tiers(kept, state.get("chunks", {}), state.get("sources", {}))
    report = synthesizer.synthesize(
        state["question"], state["sub_questions"], kept, state.get("contradictions", []), _coverage(state), tiers,
        min_domains=_min_domains(state),
    )
    report, added = fill_key_claims(report, kept)
    n = len(report.executive_summary) + sum(len(sec.sentences) for sec in report.sections)
    note = f"; code added {added} verified key claim(s) the writer left out" if added else ""
    return {"report": report, "_trail": {"summary": f"drafted report with {n} sentences from {len(kept)} claims{note}"}}


# ------------------------------------------------------------------ citation check (code only)
def cite_check(state: ResearchState) -> dict:
    kept = kept_claims(state.get("claims", []), state.get("verdicts", []))
    report = enforce_citations(state["report"], kept)
    refs, claim_refs = build_references(report, kept, state.get("chunks", {}), state.get("sources", {}))
    report = report.model_copy(update={"references": refs})
    report = report.model_copy(update={"markdown": render_markdown(report, claim_refs)})
    return {
        "report": report,
        "_trail": {
            "summary": f"citation check: removed {len(report.dropped_sentences)} uncited sentence(s), "
            f"{len(refs)} references",
            "payload": {"dropped_sentences": [d.model_dump() for d in report.dropped_sentences]},
        },
    }
