"""Follow-up research: a new run that continues a finished one with its context and evidence."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import create_app
from app.db import repository as repo
from app.services.run_service import execute_run, follow_up_inputs
from tests.fakes import FABRICATED

Q = "What are the main risks of the battery market?"


def _parent(run_id: str = "run_parent") -> str:
    repo.create_run(run_id, Q, "standard", [])
    execute_run(run_id, Q, "standard", [])
    return run_id


def test_follow_up_carries_only_verified_context(fake_world):
    parent = repo.get_run(_parent())
    inputs = follow_up_inputs(parent)
    assert f"Previous question: {Q}" in inputs["context"]
    assert FABRICATED not in inputs["context"]  # a removed claim never comes back as context
    snap = json.loads(parent.snapshot_json)
    kept_chunks = {cid for c in snap["claims"] if c["kept"] for cid in c["cited_chunk_ids"]}
    assert inputs["prior_chunks"] and set(inputs["prior_chunks"]) <= kept_chunks
    assert {c.source_id for c in inputs["prior_chunks"].values()} <= set(inputs["prior_sources"])


def test_follow_up_run_reuses_evidence_and_verifies_again(fake_world):
    parent = _parent()
    repo.create_run("run_child", "And what about supply?", "standard", [], parent)
    state = execute_run("run_child", "And what about supply?", "standard", [], parent)

    plan_prompt = next(p for p in fake_world.prompts if "EARLIER RESEARCH:" in p)
    assert Q in plan_prompt and "Verified findings:" in plan_prompt
    assert state["question"] == "What are the battery market supply risks in 2026?"  # standalone
    # web search found nothing for the follow-up, so every passage came from the earlier research
    assert sum(e["chunks_from_earlier_research"] for e in state["research_log"]) > 0
    # every claim in the follow-up got its own verdict in this run, and the report is cited
    assert {v.claim_id for v in state["verdicts"]} >= {c.id for c in state["claims"]}
    sentences = state["report"].executive_summary + [s for sec in state["report"].sections for s in sec.sentences]
    assert sentences and all(s.claim_ids for s in sentences)
    plan_event = next(e for e in repo.list_events("run_child") if e.node == "plan" and e.phase == "end")
    assert json.loads(plan_event.payload_json)["researched_as"] == state["question"]


def test_follow_up_api(fake_world, monkeypatch):
    from app.services import run_service

    parent = _parent()
    started = []
    monkeypatch.setattr(run_service, "execute_run", lambda *a, **k: started.append(a))
    repo.create_run("run_busy", Q, "standard", [])
    with TestClient(create_app()) as c:
        assert c.post("/api/runs/run_busy/followup", json={"question": "What about recycling?"}).status_code == 409
        assert c.post("/api/runs/nope/followup", json={"question": "What about recycling?"}).status_code == 404
        r = c.post(f"/api/runs/{parent}/followup", json={"question": "What about recycling?"})
        assert r.status_code == 202 and r.json()["parent_run_id"] == parent
        child = r.json()["run_id"]
        body = c.get(f"/api/runs/{child}").json()
        assert body["parent_run_id"] == parent and body["thread"] == [{"id": parent, "question": Q}]
        assert c.get(f"/api/runs/{parent}").json()["followups"][0]["id"] == child
    assert started and started[0][4] == parent  # the background run gets the parent id
