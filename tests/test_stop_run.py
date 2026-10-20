"""Stopping research in progress: no further steps run, the run ends as "stopped", and it can be
edited and run again straight away."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import create_app
from app.db import repository as repo
from app.graph import nodes
from app.graph.tracing import RunStopped
from app.services.run_service import execute_run

Q = "What are the main risks of the battery market?"


def test_stop_during_a_run_skips_the_remaining_steps(fake_world, monkeypatch):
    real_draft = nodes.draft

    def draft_then_stop(state):  # the person presses Stop while drafting
        update = real_draft(state)
        assert repo.request_stop(state["run_id"])
        return update

    monkeypatch.setattr(nodes, "draft", draft_then_stop)
    repo.create_run("run_s", Q, "quick", [])
    calls_before_verify = None
    with pytest.raises(RunStopped):
        execute_run("run_s", Q, "quick", [])
    calls_before_verify = list(fake_world.calls)
    run = repo.get_run("run_s")
    assert run.status == "stopped" and run.finished_at is not None and run.report_json is None
    steps = [e.node.split(":")[0] for e in repo.list_events("run_s") if e.phase == "start"]
    assert "draft" in steps and "verify" not in steps and "synthesize" not in steps
    assert "VerdictOut" not in calls_before_verify  # no verifier call was made after Stop
    assert any("stopped by you" in e.summary for e in repo.list_events("run_s"))
    assert run.tokens > 0  # what was spent before stopping is still recorded


def test_stop_before_the_run_starts(fake_world):
    repo.create_run("run_q", Q, "quick", [])
    assert repo.request_stop("run_q")
    with pytest.raises(RunStopped):
        execute_run("run_q", Q, "quick", [])
    assert repo.get_run("run_q").status == "stopped" and fake_world.calls == []


def test_stop_api_and_edit_while_stopping(fake_world, monkeypatch):
    from app.services import run_service

    monkeypatch.setattr(run_service, "execute_run", lambda *a, **k: None)
    repo.create_run("run_live", Q, "quick", [])
    repo.update_run("run_live", status="running")
    repo.create_run("run_done", Q, "quick", [])
    repo.update_run("run_done", status="done")
    with TestClient(create_app()) as c:
        assert c.post("/api/runs/run_done/stop").status_code == 409
        r = c.post("/api/runs/run_live/stop")
        assert r.status_code == 202 and repo.get_run("run_live").status == "stopping"
        assert c.post("/api/runs/run_live/stop").status_code == 409  # already stopping
        assert c.delete("/api/runs/run_live").status_code == 409  # still finishing its step
        edited = c.post("/api/runs/run_live/rerun", json={"question": "What are the main risks of the lithium battery market?"})
        assert edited.status_code == 202
        repo.update_run("run_live", status="stopped")
        assert c.get("/api/runs/run_live/events").text.count("event: done") == 1  # the stream ends
