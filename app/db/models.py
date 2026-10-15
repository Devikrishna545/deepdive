"""SQLite tables (SQLModel).

runs        one row per research run, with the final report and a JSON snapshot of the
            evidence (sources, chunks, claims, verdicts) for the API and the eval.
events      the audit trail: one row per node start/finish, written by `traced`.
cache       search and fetch results, so eval reruns are cheap and comparable.
documents / doc_chunks   user uploads and their embedded chunks (local vector store).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(SQLModel, table=True):
    __tablename__ = "runs"
    id: str = Field(primary_key=True)
    question: str
    depth: str = "standard"
    status: str = "queued"  # queued | running | done | failed
    error: str | None = None
    parent_run_id: str | None = None
    file_ids_json: str = "[]"
    tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    report_json: str | None = None
    snapshot_json: str | None = None


class Event(SQLModel, table=True):
    __tablename__ = "events"
    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    node: str
    phase: str  # start | end | error | info
    summary: str = ""
    payload_json: str = "{}"
    tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls_json: str = "[]"  # per-call model / in / out / cost, for the dev token view
    cost_usd: float = 0.0
    latency_ms: int = 0
    models: str = ""
    ts: datetime = Field(default_factory=utcnow)


class CacheEntry(SQLModel, table=True):
    __tablename__ = "cache"
    key: str = Field(primary_key=True)
    kind: str  # search | fetch
    value_json: str
    created_at: datetime = Field(default_factory=utcnow)


class Document(SQLModel, table=True):
    __tablename__ = "documents"
    id: str = Field(primary_key=True)
    filename: str
    pages: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class DocChunk(SQLModel, table=True):
    __tablename__ = "doc_chunks"
    id: str = Field(primary_key=True)
    document_id: str = Field(index=True)
    page: int | None = None
    text: str
    embedding_json: str = "[]"
