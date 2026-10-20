"""Edit-and-rerun and deleting research from the home page."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import create_app
from app.config import get_settings
from app.db import repository as repo
from app.services.run_service import execute_run

Q = "What are the main risks of the battery market?"


def _client(monkeypatch, started: list | None = None, **env) -> TestClient:
    from app.services import run_service

    monkeypatch.setattr(run_service, "execute_run", lambda *a, **k: (started if started is not None else []).append(a))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    return TestClient(create_app())


def _done(run_id: str, question: str = Q, parent: str | None = None, files: list | None = None) -> str:
    repo.create_run(run_id, question, "quick", files or [], parent)
    execute_run(run_id, question, "quick", files or [], parent)
    return run_id


def test_rerun_starts_a_new_run_with_the_edited_question(fake_world, monkeypatch):
    _done("run_a", files=[])
    _done("run_b", "And what about supply?", parent="run_a")
    repo.update_run("run_b", file_ids_json=json.dumps(["doc_1"]))
    repo.create_run("run_busy", Q, "quick", [])
    started: list = []
    with _client(monkeypatch, started) as c:
        r = c.post("/api/runs/run_b/rerun", json={"question": "And what about battery supply in 2026?", "depth": "standard"})
        assert r.status_code == 202 and r.json()["replaces"] == "run_b"
        new = repo.get_run(r.json()["run_id"])
        assert new.question == "And what about battery supply in 2026?" and new.depth == "standard"
        assert new.parent_run_id == "run_a" and json.loads(new.file_ids_json) == ["doc_1"]  # same thread, same files
        assert repo.get_run("run_b") is not None  # the original stays
        assert c.post("/api/runs/run_busy/rerun", json={"question": Q}).status_code == 409
        assert c.post("/api/runs/run_b/rerun", json={"question": "short"}).status_code == 422
    assert started[0][4] == "run_a"


def test_delete_single_and_selected(fake_world, monkeypatch):
    for rid in ("run_1", "run_2", "run_3"):
        _done(rid)
    repo.create_run("run_busy", Q, "quick", [])
    with _client(monkeypatch) as c:
        assert c.delete("/api/runs/run_1").json() == {"deleted": ["run_1"]}
        assert c.get("/api/runs/run_1").status_code == 404 and not repo.list_events("run_1")
        assert c.delete("/api/runs/run_busy").status_code == 409
        r = c.post("/api/runs/delete", json={"run_ids": ["run_2", "run_3", "run_busy", "missing"]}).json()
        assert r == {"deleted": ["run_2", "run_3"], "skipped": ["run_busy"]}
        assert [x["id"] for x in c.get("/api/runs").json()] == ["run_busy"]
        assert c.post("/api/runs/delete", json={"run_ids": []}).status_code == 422


def test_follow_up_survives_deleting_its_parent(fake_world, monkeypatch):
    _done("run_p")
    _done("run_c", "And what about supply?", parent="run_p")
    with _client(monkeypatch) as c:
        c.delete("/api/runs/run_p")
        body = c.get("/api/runs/run_c").json()
        assert body["thread"] == [] and c.get("/api/runs/run_c/report").status_code == 200


def test_deleting_needs_the_access_code_when_set(fake_world, monkeypatch):
    _done("run_x")
    with _client(monkeypatch, RUN_ACCESS_CODE="judges-2026") as c:
        assert c.delete("/api/runs/run_x").status_code == 401
        assert c.post("/api/runs/delete", json={"run_ids": ["run_x"]}).status_code == 401
        assert c.post("/api/runs/run_x/rerun", json={"question": Q}).status_code == 401
        assert c.delete("/api/runs/run_x", headers={"X-Access-Code": "judges-2026"}).status_code == 200
