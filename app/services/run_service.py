"""Bridges the API and the graph: creates runs, executes them in the background, stores results."""

from __future__ import annotations

import json
import logging
import threading

from app.core.coverage import kept_claims
from app.core.utils import new_id
from app.db import repository as repo
from app.graph.builder import RECURSION_LIMIT, get_graph
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


def execute_run(run_id: str, question: str, depth: str, file_ids: list[str]) -> dict:
    """Run the graph synchronously (used by the background thread, CLI and evaluation)."""
    repo.update_run(run_id, status="running")
    status = balance_status()
    if status.level in ("low", "unknown"):
        repo.add_event(run_id, "balance", "info", summary=status.message,
                       payload={"available_usd": status.available_usd, "level": status.level})
    try:
        state = get_graph().invoke(
            {"run_id": run_id, "question": question, "depth": depth, "file_ids": file_ids},
            config={"recursion_limit": RECURSION_LIMIT},
        )
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


def start_run(question: str, depth: str = "standard", file_ids: list[str] | None = None) -> str:
    """Create a run row and execute it on a background thread. Returns the run id.

    Raises InsufficientBalance (-> HTTP 402) when the Mesh balance is below MIN_BALANCE_STOP_USD.
    """
    require_balance()
    run_id = new_id("run")
    file_ids = file_ids or []
    repo.create_run(run_id, question, depth, file_ids)

    def _target() -> None:
        try:
            execute_run(run_id, question, depth, file_ids)
        except Exception:
            pass  # already recorded on the run and in the trail

    threading.Thread(target=_target, name=f"run-{run_id}", daemon=True).start()
    return run_id
