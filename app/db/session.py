"""Engine and session helpers. `init_db()` runs once at app start-up."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event as sa_event
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, connect_args={"check_same_thread": False})
        if url.startswith("sqlite"):

            @sa_event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _record):  # WAL lets the SSE reader and the run writer coexist
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=5000")
                cur.close()

    return _engine


def reset_engine() -> None:
    """Used by tests to point at a fresh database."""
    global _engine
    _engine = None


def init_db() -> None:
    from app.db import models  # noqa: F401  (register tables)

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine) -> None:
    """Tiny SQLite migration: add columns introduced after a local DB was created.

    create_all() never alters existing tables, so an older data/deepdive.db would crash on new
    columns. Only additive changes are handled; that is all this project needs.
    """
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info('{table.name}')")}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
                default_sql = f" DEFAULT {default!r}" if isinstance(default, (int, float, str)) else ""
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}{default_sql}')


@contextmanager
def session_scope():
    with Session(get_engine(), expire_on_commit=False) as session:
        yield session
