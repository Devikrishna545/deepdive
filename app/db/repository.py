"""All reads and writes of the tables. Routes, services and graph code use these."""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import col, select

from app.db.models import CacheEntry, Event, Run, utcnow
from app.db.session import session_scope

# ---------------------------------------------------------------- runs


def create_run(run_id: str, question: str, depth: str, file_ids: list[str], parent_run_id: str | None = None,
               web_addon: bool = False) -> Run:
    run = Run(
        id=run_id,
        question=question,
        depth=depth,
        file_ids_json=json.dumps(file_ids),
        parent_run_id=parent_run_id,
        web_addon=web_addon,
    )
    with session_scope() as s:
        s.add(run)
        s.commit()
        s.refresh(run)
    return run


def get_run(run_id: str) -> Run | None:
    with session_scope() as s:
        return s.get(Run, run_id)


def list_runs(limit: int = 20) -> list[Run]:
    with session_scope() as s:
        return list(s.exec(select(Run).order_by(col(Run.created_at).desc()).limit(limit)))


def list_followups(run_id: str) -> list[Run]:
    with session_scope() as s:
        return list(s.exec(select(Run).where(Run.parent_run_id == run_id).order_by(Run.created_at)))


ACTIVE_STATUSES = ("queued", "running", "stopping")
FINAL_STATUSES = ("done", "failed", "stopped")


def request_stop(run_id: str) -> bool:
    """Ask a queued or running run to stop at its next step. False if it is not in progress."""
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None or run.status not in ("queued", "running"):
            return False
        run.status = "stopping"
        s.add(run)
        s.commit()
        return True


def stop_requested(run_id: str) -> bool:
    run = get_run(run_id)
    return run is not None and run.status == "stopping"


def mark_running(run_id: str) -> bool:
    """queued -> running, unless a stop was asked for before the run started. Returns False then."""
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None or run.status == "stopping":
            return False
        run.status = "running"
        s.add(run)
        s.commit()
        return True


def delete_runs(run_ids: list[str]) -> tuple[list[str], list[str]]:
    """Delete finished runs and their audit trails. Runs still in progress are skipped (their
    background thread is still writing to them). Returns (deleted ids, skipped ids). Follow-ups of
    a deleted run are kept; their link to it simply ends. Cached search results and uploaded
    documents are shared with other runs and stay."""
    deleted, skipped = [], []
    with session_scope() as s:
        for run_id in dict.fromkeys(run_ids):
            run = s.get(Run, run_id)
            if run is None:
                continue
            if run.status in ACTIVE_STATUSES:
                skipped.append(run_id)
                continue
            for ev in s.exec(select(Event).where(Event.run_id == run_id)):
                s.delete(ev)
            s.delete(run)
            deleted.append(run_id)
        s.commit()
    return deleted, skipped


def count_runs_since(since) -> int:
    with session_scope() as s:
        return len(list(s.exec(select(Run.id).where(Run.created_at >= since))))


def latest_done_run(question: str, depth: str, id_prefix: str, since) -> Run | None:
    """Newest finished run for this exact question/depth whose id starts with `id_prefix`, created after `since`."""
    with session_scope() as s:
        stmt = (select(Run).where(Run.question == question, Run.depth == depth, Run.status == "done",
                                  col(Run.id).startswith(id_prefix, autoescape=True), Run.created_at >= since)
                .order_by(col(Run.created_at).desc()).limit(1))
        return s.exec(stmt).first()


def update_run(run_id: str, **fields: Any) -> None:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        if fields.get("status") in FINAL_STATUSES:
            run.finished_at = utcnow()
        s.add(run)
        s.commit()


# ---------------------------------------------------------------- events (audit trail)


def add_event(
    run_id: str,
    node: str,
    phase: str,
    summary: str = "",
    payload: dict | None = None,
    tokens: int = 0,
    latency_ms: int = 0,
    models: list[str] | None = None,
    cost_usd: float = 0.0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    calls: list[dict] | None = None,
) -> None:
    with session_scope() as s:
        s.add(
            Event(
                run_id=run_id,
                node=node,
                phase=phase,
                summary=summary[:500],
                payload_json=json.dumps(payload or {}, default=str),
                tokens=tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                calls_json=json.dumps(calls or []),
                cost_usd=round(cost_usd, 6),
                latency_ms=latency_ms,
                models=",".join(models or []),
            )
        )
        s.commit()


def list_events(run_id: str, after_id: int = 0) -> list[Event]:
    with session_scope() as s:
        stmt = select(Event).where(Event.run_id == run_id, col(Event.id) > after_id).order_by(col(Event.id))
        return list(s.exec(stmt))


# ---------------------------------------------------------------- cache


def cache_get(key: str) -> Any | None:
    with session_scope() as s:
        entry = s.get(CacheEntry, key)
        return json.loads(entry.value_json) if entry else None


def cache_put(key: str, kind: str, value: Any) -> None:
    with session_scope() as s:
        s.merge(CacheEntry(key=key, kind=kind, value_json=json.dumps(value, default=str)))
        s.commit()
