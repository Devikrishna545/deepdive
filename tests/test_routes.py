"""API and page smoke tests (no network)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import create_app
from app.db import repository as repo
from app.services.run_service import execute_run


def client() -> TestClient:
    return TestClient(create_app())


def test_health_never_leaks_key():
    with client() as c:
        body = c.get("/api/health").json()
    assert body["status"] == "ok" and body["mesh_key_configured"] is True
    assert "rsk_test" not in str(body)


def test_pages_render():
    with client() as c:
        assert c.get("/").status_code == 200
        assert c.get("/runs/does-not-exist").status_code == 404
        # installable app: manifest and service worker at the root scope; icon sprite is local
        assert c.get("/manifest.webmanifest").json()["short_name"] == "DeepDive"
        sw = c.get("/sw.js")
        assert sw.status_code == 200 and '"/api"' in sw.text  # the worker must skip research data
        assert c.get("/static/icons/sprite.svg").status_code == 200


def test_validation_rejects_short_question():
    with client() as c:
        assert c.post("/api/runs", json={"question": "hi"}).status_code == 422


def test_report_endpoints_after_offline_run(fake_world):
    run_id = "run_api"
    q = "What are the main risks of the battery market?"
    repo.create_run(run_id, q, "standard", [])
    execute_run(run_id, q, "standard", [])
    with client() as c:
        assert c.get(f"/runs/{run_id}").status_code == 200
        report = c.get(f"/api/runs/{run_id}/report").json()
        assert report["sections"]
        claims = c.get(f"/api/runs/{run_id}/claims").json()
        assert any(cl["verdict"]["label"] == "UNSUPPORTED" for cl in claims["claims"])
        tiers = {ch["source"]["tier"] for cl in claims["claims"] for ch in cl["chunks"] if ch["source"]}
        assert tiers and tiers <= {"official", "academic", "news", "other"}  # badge in the evidence panel
        trail = c.get(f"/api/runs/{run_id}/trail").json()
        assert len(trail["events"]) > 5
        md = c.get(f"/api/runs/{run_id}/export?fmt=md")
        assert md.status_code == 200 and md.text.startswith("# ")
        assert c.get(f"/api/runs/{run_id}/export?fmt=html").status_code == 200


def test_low_balance_is_reported(monkeypatch):
    from app.llm import billing

    billing.reset_caches()
    monkeypatch.setattr(billing, "fetch_available_usd", lambda: 3.2)
    with client() as c:
        bal = c.get("/api/health").json()["balance"]
    assert bal["level"] == "low" and bal["available_usd"] == 3.2


def test_runs_blocked_below_floor(monkeypatch):
    from app.llm import billing

    billing.reset_caches()
    monkeypatch.setattr(billing, "fetch_available_usd", lambda: 0.4)
    with client() as c:
        resp = c.post("/api/runs", json={"question": "What are the main risks of the battery market?"})
    assert resp.status_code == 402 and "balance" in resp.json()["detail"].lower()


def test_dev_token_usage_per_agent(fake_world):
    run_id = "run_tokens"
    q = "What are the main risks of the battery market?"
    repo.create_run(run_id, q, "standard", [])
    execute_run(run_id, q, "standard", [])
    with client() as c:
        usage = c.get(f"/api/runs/{run_id}/usage").json()
        agents = {a["agent"]: a for a in usage["agents"]}
        for name in ("planner", "researcher", "drafter", "verifier", "synthesizer"):
            assert agents[name]["prompt_tokens"] > 0 and agents[name]["completion_tokens"] > 0, name
        assert usage["totals"]["prompt_tokens"] == sum(a["prompt_tokens"] for a in usage["agents"])
        assert c.get("/dev/usage").status_code == 200
        recent = c.get("/api/dev/usage").json()
        assert recent["done_runs"] == 1 and recent["average_per_done_run"][0]["prompt_tokens"] > 0
        page = c.get(f"/runs/{run_id}").text
        assert "Tokens (dev)" in page


def test_dev_views_hidden_when_dev_mode_off(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("DEV_MODE", "false")
    get_settings.cache_clear()
    with client() as c:
        assert c.get("/dev/usage").status_code == 404
        assert c.get("/api/dev/usage").status_code == 404
        assert "Token usage (dev)" not in c.get("/").text
