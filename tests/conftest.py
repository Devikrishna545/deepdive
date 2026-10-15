"""Test setup: fresh SQLite DB per test session, no network, no real keys."""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.db import session as db_session
from app.graph.builder import get_graph
from app.llm import billing, mesh_client
from tests.fakes import FakeMesh, fake_fetch, fake_search

TEST_PRICES = {"openai/gpt-4o-mini": (0.15, 0.60), "anthropic/claude-haiku-4.5": (1.0, 5.0)}


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("MESH_API_KEY", "rsk_test_not_a_real_key")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    db_session.reset_engine()
    db_session.init_db()
    # Never touch the real Mesh account in tests: fixed balance and fixed prices.
    billing.reset_caches()
    monkeypatch.setattr(billing, "fetch_available_usd", lambda: 50.0)
    monkeypatch.setattr(billing, "load_prices", lambda refresh=False: TEST_PRICES)
    yield
    mesh_client.set_mesh(None)
    get_settings.cache_clear()
    get_graph.cache_clear()
    db_session.reset_engine()


@pytest.fixture
def fake_world(monkeypatch):
    """Fake Mesh + fake search/fetch wired into the researcher."""
    fake = FakeMesh()
    mesh_client.set_mesh(fake)
    monkeypatch.setattr("app.agents.researcher.agent.web_search", fake_search)
    monkeypatch.setattr("app.agents.researcher.agent.fetch_page", fake_fetch)
    return fake
