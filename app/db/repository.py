"""All reads and writes of the tables. Routes, services and graph code use these."""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import col, select

from app.db.models import CacheEntry, Event, Run, utcnow
from app.db.session import session_scope

# ---------------------------------------------------------------- runs


def create_run(run_id: str, question: str, depth: str, file_ids: list[str], parent_run_id: str | None = None) -> Run:
    run = Run(
        id=run_id,
        question=question,
        depth=depth,
        file_ids_json=json.dumps(file_ids),
        parent_run_id=parent_run_id,
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


def update_run(run_id: str, **fields: Any) -> None:
    with session_scope() as s:
        run = s.get(Run, run_id)
        if run is None:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        if fields.get("status") in ("done", "failed"):
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
