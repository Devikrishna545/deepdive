"""Bridges the API and the graph: creates runs, executes them in the background, stores results."""

from __future__ import annotations

import json
import logging
import threading

from app.core.coverage import kept_claims
from app.core.doc_mode import is_document_question
from app.core.schemas import Chunk, Source
from app.core.utils import new_id
from app.db import repository as repo
from app.graph.builder import RECURSION_LIMIT, get_graph
from app.graph.tracing import RunStopped
from app.llm.billing import balance_status, require_balance
from app.llm.usage import run_usage

log = logging.getLogger(__name__)


def snapshot(state: dict) -> dict:
    """JSON-safe copy of the evidence, kept for the API, the UI and the evaluation."""
    kept_ids = {c.id for c in kept_claims(state.get("claims", []), state.get("verdicts", []))}
    return {
        "sub_questions": [sq.model_dump() for sq in state.get("sub_questions", [])],
        "sources": {k: v.model_dump() for k, v in state.get("sources", {}).items()},
        "chunks": {k: v.model_dump() for k, v in state.get("chunks", {}).items()},
        "findings": [f.model_dump() for f in state.get("findings", [])],
        "claims": [c.model_dump() | {"kept": c.id in kept_ids} for c in state.get("claims", [])],
        "verdicts": [v.model_dump() for v in state.get("verdicts", [])],
        "contradictions": [c.model_dump() for c in state.get("contradictions", [])],
        "research_log": state.get("research_log", []),
        "loops": state.get("loops", {}),
    }


# Follow-up context sent to the planner: enough to resolve "it"/"they" and to skip what is known,
# small enough to keep the planner call cheap (~600 tokens).
CONTEXT_CLAIMS = 12
CONTEXT_CLAIM_CHARS = 220
THREAD_QUESTIONS = 3


def thread_of(run) -> list:
    """The earlier runs this one follows from, oldest first (at most THREAD_QUESTIONS)."""
    chain, seen = [], {run.id}
    parent_id = run.parent_run_id
    while parent_id and parent_id not in seen and len(chain) < THREAD_QUESTIONS:
        parent = repo.get_run(parent_id)
        if parent is None:
            break
        chain.append(parent)
        seen.add(parent.id)
        parent_id = parent.parent_run_id
    return chain[::-1]


def follow_up_inputs(parent) -> dict:
    """What a follow-up run carries over from the run it continues: the questions so far and the
    verified findings (planner context), plus the passages the earlier report cited, which the
    researcher ranks alongside new results. Only kept claims are used: nothing removed by the
    verifier can come back through a follow-up, and every claim is verified again in the new run."""
    snap = json.loads(parent.snapshot_json or "{}")
    kept = [c for c in snap.get("claims", []) if c.get("kept")]
    chunks, sources = snap.get("chunks", {}), snap.get("sources", {})
    cited = {cid for c in kept for cid in c.get("cited_chunk_ids", []) if cid in chunks}
    prior_chunks = {cid: Chunk.model_validate(chunks[cid]) for cid in cited}
    prior_sources = {c.source_id: Source.model_validate(sources[c.source_id])
                     for c in prior_chunks.values() if c.source_id in sources}
    earlier = [r.question for r in thread_of(parent)]
    lines = [f"Earlier question: {q}" for q in earlier] + [f"Previous question: {parent.question}", "Verified findings:"]
    lines += [f"- {c['text'][:CONTEXT_CLAIM_CHARS]}" for c in kept[:CONTEXT_CLAIMS]] or ["- (none)"]
    return {"context": "\n".join(lines), "prior_chunks": prior_chunks, "prior_sources": prior_sources}


def execute_run(run_id: str, question: str, depth: str, file_ids: list[str], parent_run_id: str | None = None) -> dict:
    """Run the graph synchronously (used by the background thread, CLI and evaluation)."""
    if not repo.mark_running(run_id):  # stopped while it was still queued
        _finish_stopped(run_id)
        raise RunStopped("stopped by the user before it started")
    status = balance_status()
    if status.level in ("low", "unknown"):
        repo.add_event(run_id, "balance", "info", summary=status.message,
                       payload={"available_usd": status.available_usd, "level": status.level})
    inputs = {"run_id": run_id, "question": question, "depth": depth, "file_ids": file_ids}
    try:
        parent = repo.get_run(parent_run_id) if parent_run_id else None
        # Document mode when the question (or the question it follows up) points at the attachments.
        inputs["doc_only"] = is_document_question(question, file_ids) or (
            parent is not None and is_document_question(parent.question, file_ids))
        run_row = repo.get_run(run_id)
        # Documents first, web as an add-on: the first pass reads only the documents; sub-questions
        # they leave thin get web search in the loop-back round.
        inputs["doc_web"] = bool(inputs["doc_only"] and run_row is not None and run_row.web_addon)
        if parent is not None:
            inputs |= follow_up_inputs(parent)
        state = get_graph().invoke(
            inputs,
            config={"recursion_limit": RECURSION_LIMIT},
        )
    except RunStopped:
        _finish_stopped(run_id)
        raise
    except Exception as exc:
        log.exception("run %s failed", run_id)
        repo.add_event(run_id, "run", "error", summary=f"{type(exc).__name__}: {exc}")
        usage = run_usage(run_id)
        repo.update_run(run_id, status="failed", error=str(exc), tokens=usage["tokens"], cost_usd=usage["cost_usd"])
        raise
    report = state.get("report")
    usage = run_usage(run_id)
    repo.update_run(
        run_id,
        status="done",
        tokens=usage["tokens"],
        cost_usd=round(usage["cost_usd"], 6),
        report_json=report.model_dump_json() if report else None,
        snapshot_json=json.dumps(snapshot(state), default=str),
    )
    repo.add_event(run_id, "run", "info", summary=f"run finished: {usage['tokens']} tokens, ${usage['cost_usd']:.4f}")
    after = balance_status(force=True)
    if after.level in ("low", "stop"):
        repo.add_event(run_id, "balance", "info", summary=after.message, payload={"available_usd": after.available_usd})
    return state


def _finish_stopped(run_id: str) -> None:
    usage = run_usage(run_id)
    repo.add_event(run_id, "run", "info", summary="stopped by you: no further steps were run "
                   f"(spent {usage['tokens']} tokens, ${usage['cost_usd']:.4f})")
    repo.update_run(run_id, status="stopped", tokens=usage["tokens"], cost_usd=round(usage["cost_usd"], 6))


def stop_run(run_id: str) -> bool:
    """Stop a queued or running run before its next step. Searches and fetched pages it already
    made stay in the cache, so a corrected rerun reuses them where its queries overlap."""
    return repo.request_stop(run_id)


def start_run(question: str, depth: str = "standard", file_ids: list[str] | None = None,
              parent_run_id: str | None = None, web_addon: bool = False) -> str:
    """Create a run row and execute it on a background thread. Returns the run id.
    With `parent_run_id` the run is a follow-up that continues that run's research. `web_addon`
    (document mode only): answer from the documents first, then search the web for the parts they
    don't answer.

    Raises InsufficientBalance (-> HTTP 402) when the Mesh balance is below MIN_BALANCE_STOP_USD.
    """
    require_balance()
    run_id = new_id("run")
    file_ids = file_ids or []
    repo.create_run(run_id, question, depth, file_ids, parent_run_id, web_addon)

    def _target() -> None:
        try:
            execute_run(run_id, question, depth, file_ids, parent_run_id)
        except Exception:
            pass  # already recorded on the run and in the trail

    threading.Thread(target=_target, name=f"run-{run_id}", daemon=True).start()
    return run_id
