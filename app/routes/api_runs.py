"""Runs API: start a run, stream progress (SSE), read report / claims / trail, export."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.core.schemas import Source
from app.core.scoring import source_label
from app.db import repository as repo
from app.export.exporters import to_html
from app.llm.billing import InsufficientBalance
from app.routes.deps import get_run_or_404
from app.routes.guards import require_access_code, require_daily_capacity
from app.services import run_service

router = APIRouter()


class RunRequest(BaseModel):
    question: str = Field(min_length=10, max_length=500)
    depth: str = Field(default="standard", pattern="^(quick|standard)$")
    file_ids: list[str] = Field(default_factory=list)


class FollowUpRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    depth: str | None = Field(default=None, pattern="^(quick|standard)$")


class RerunRequest(BaseModel):
    question: str = Field(min_length=10, max_length=500)
    depth: str = Field(default="standard", pattern="^(quick|standard)$")


class DeleteRequest(BaseModel):
    run_ids: list[str] = Field(min_length=1, max_length=200)


def _run_summary(run) -> dict:
    return {
        "id": run.id,
        "question": run.question,
        "depth": run.depth,
        "status": run.status,
        "error": run.error,
        "tokens": run.tokens,
        "cost_usd": run.cost_usd,
        "created_at": run.created_at,
        "finished_at": run.finished_at,
        "parent_run_id": run.parent_run_id,
    }


@router.post("", status_code=202, dependencies=[Depends(require_access_code), Depends(require_daily_capacity)])
def create_run(body: RunRequest) -> dict:
    try:
        run_id = run_service.start_run(body.question.strip(), body.depth, body.file_ids)
    except InsufficientBalance as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    return {"run_id": run_id, "status": "queued"}


@router.post("/delete", dependencies=[Depends(require_access_code)])
def delete_runs(body: DeleteRequest) -> dict:
    """Delete several runs (the home page's "Delete selected"). Runs still in progress are skipped."""
    deleted, skipped = repo.delete_runs(body.run_ids)
    return {"deleted": deleted, "skipped": skipped}


@router.get("")
def list_runs(limit: int = Query(20, le=100)) -> list[dict]:
    return [_run_summary(r) for r in repo.list_runs(limit)]


@router.get("/{run_id}")
def get_run(run_id: str) -> dict:
    """One run, plus the research thread it belongs to: the runs it follows from (oldest first)
    and the follow-ups started from it."""
    run = get_run_or_404(run_id)
    return _run_summary(run) | {
        "thread": [{"id": r.id, "question": r.question} for r in run_service.thread_of(run)],
        "followups": [{"id": r.id, "question": r.question, "status": r.status} for r in repo.list_followups(run_id)],
    }


@router.delete("/{run_id}", dependencies=[Depends(require_access_code)])
def delete_run(run_id: str) -> dict:
    """Delete one finished run with its report, claims and audit trail."""
    run = get_run_or_404(run_id)
    if run.status in repo.ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="This research is still running; delete it once it finishes.")
    deleted, _ = repo.delete_runs([run_id])
    return {"deleted": deleted}


@router.post("/{run_id}/stop", status_code=202, dependencies=[Depends(require_access_code)])
def stop(run_id: str) -> dict:
    """Stop a run in progress before its next step (calls already sent finish; no new ones start).
    The run ends as "stopped" with its audit trail so far; edit & run again works right away."""
    run = get_run_or_404(run_id)
    if not run_service.stop_run(run_id):
        raise HTTPException(status_code=409, detail=f"This research is {run.status}; only research in progress can be stopped.")
    return {"run_id": run_id, "status": "stopping"}


@router.post("/{run_id}/rerun", status_code=202,
             dependencies=[Depends(require_access_code), Depends(require_daily_capacity)])
def rerun(run_id: str, body: RerunRequest) -> dict:
    """Edit and run again: a new run with the corrected question (and depth), the same uploaded
    documents and, for a follow-up, the same earlier research. The original run is kept."""
    old = get_run_or_404(run_id)
    if old.status in ("queued", "running"):  # a stopping run may be edited: it ends at its next step
        raise HTTPException(status_code=409, detail="This research is still running; edit it once it finishes.")
    parent = repo.get_run(old.parent_run_id) if old.parent_run_id else None
    try:
        new_id = run_service.start_run(body.question.strip(), body.depth, json.loads(old.file_ids_json or "[]"),
                                       parent_run_id=parent.id if parent and parent.status == "done" else None)
    except InsufficientBalance as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    return {"run_id": new_id, "status": "queued", "replaces": run_id}


@router.get("/{run_id}/events")
async def stream_events(run_id: str, after: int = 0):
    """Server-Sent Events: one `trail` event per audit-trail row, then `done`."""
    get_run_or_404(run_id)

    async def generator():
        last = after
        while True:
            for ev in repo.list_events(run_id, last):
                last = ev.id
                yield {"event": "trail", "id": str(ev.id), "data": json.dumps(_event_dict(ev), default=str)}
            run = repo.get_run(run_id)
            if run and run.status in repo.FINAL_STATUSES:
                yield {"event": "done", "data": json.dumps({"status": run.status, "error": run.error})}
                return
            await asyncio.sleep(0.7)

    return EventSourceResponse(generator())


def _event_dict(ev) -> dict:
    return {
        "id": ev.id,
        "node": ev.node,
        "phase": ev.phase,
        "summary": ev.summary,
        "tokens": ev.tokens,
        "prompt_tokens": ev.prompt_tokens,
        "completion_tokens": ev.completion_tokens,
        "cost_usd": ev.cost_usd,
        "latency_ms": ev.latency_ms,
        "models": ev.models,
        "ts": ev.ts,
        "payload": json.loads(ev.payload_json or "{}"),
    }


@router.get("/{run_id}/trail")
def get_trail(run_id: str) -> dict:
    run = get_run_or_404(run_id)
    snap = json.loads(run.snapshot_json) if run.snapshot_json else {}
    return {
        "run": _run_summary(run),
        "events": [_event_dict(e) for e in repo.list_events(run_id)],
        "research_log": snap.get("research_log", []),
        "loops": snap.get("loops", {}),
    }


def _require_done(run):
    if run.status != "done" or not run.report_json:
        raise HTTPException(status_code=409, detail=f"run is {run.status}; report not ready")


@router.get("/{run_id}/report")
def get_report(run_id: str) -> dict:
    run = get_run_or_404(run_id)
    _require_done(run)
    return json.loads(run.report_json)


def _with_tier(source: dict | None) -> dict | None:
    """Add the source tier (official / academic / news / other) the UI shows as a badge."""
    if not source:
        return None
    return source | {"tier": source_label(Source.model_validate(source))}


@router.get("/{run_id}/claims")
def get_claims(run_id: str) -> dict:
    """Every claim with its verdict, cited chunks and sources: the evidence behind the report."""
    run = get_run_or_404(run_id)
    if not run.snapshot_json:
        raise HTTPException(status_code=409, detail=f"run is {run.status}; claims not ready")
    snap = json.loads(run.snapshot_json)
    latest = {v["claim_id"]: v for v in snap["verdicts"]}
    chunks, sources = snap["chunks"], snap["sources"]
    claims = []
    for c in snap["claims"]:
        cited = [chunks[cid] | {"source": _with_tier(sources.get(chunks[cid]["source_id"]))} for cid in c["cited_chunk_ids"] if cid in chunks]
        claims.append(c | {"verdict": latest.get(c["id"]), "chunks": cited})
    return {
        "sub_questions": snap["sub_questions"],
        "claims": claims,
        "contradictions": snap["contradictions"],
    }


@router.get("/{run_id}/export")
def export_report(run_id: str, fmt: str = Query("md", pattern="^(md|html)$")):
    run = get_run_or_404(run_id)
    _require_done(run)
    markdown_text = json.loads(run.report_json).get("markdown", "")
    filename = f"deepdive-{run_id}.{fmt}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if fmt == "md":
        return PlainTextResponse(markdown_text, media_type="text/markdown", headers=headers)
    return HTMLResponse(to_html(markdown_text, run.question))


@router.post("/{run_id}/followup", status_code=202,
             dependencies=[Depends(require_access_code), Depends(require_daily_capacity)])
def follow_up(run_id: str, body: FollowUpRequest) -> dict:
    """Continue a finished run: a new run whose planner sees the earlier questions and verified
    findings, and whose researcher can reuse the passages the earlier report cited. Every claim
    is verified again; the follow-up is its own run with its own report and audit trail."""
    parent = get_run_or_404(run_id)
    _require_done(parent)
    try:
        new_id = run_service.start_run(body.question.strip(), body.depth or parent.depth,
                                       json.loads(parent.file_ids_json or "[]"), parent_run_id=parent.id)
    except InsufficientBalance as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    return {"run_id": new_id, "status": "queued", "parent_run_id": parent.id}
