"""End-to-end run of the real LangGraph with fake Mesh and fake search.

Proves the judged behaviours without network: distinct agents run, a fabricated claim
is rejected, a thin sub-question loops back to research, uncited sentences are removed,
and every step is in the audit trail.
"""

from __future__ import annotations

import json

from app.core.schemas import VerdictLabel
from app.core.utils import new_id
from app.db import repository as repo
from app.services.run_service import execute_run
from tests.fakes import FABRICATED


def test_full_run_rejects_fabrication_and_loops(fake_world):
    run_id = "run_test"
    repo.create_run(run_id, "What are the main risks of the battery market?", "standard", [])
    state = execute_run(run_id, "What are the main risks of the battery market?", "standard", [])

    # 1. verification removed the fabricated claim
    fabricated = [c for c in state["claims"] if c.text == FABRICATED]
    assert fabricated, "fake drafter should have produced a fabricated claim"
    verdicts = {v.claim_id: v for v in state["verdicts"]}
    assert all(verdicts[c.id].label == VerdictLabel.UNSUPPORTED for c in fabricated)

    # 2. the thin sub-question triggered a loop back to research
    assert any(n > 0 for n in state["loops"].values())
    assert any(entry["round"] > 0 for entry in state["research_log"])

    # 3. the final report has no uncited sentences and no fabricated text
    report = state["report"]
    assert report.dropped_sentences, "citation check should have removed the uncited sentence"
    all_sentences = report.executive_summary + [s for sec in report.sections for s in sec.sentences]
    assert all(s.claim_ids for s in all_sentences)
    assert FABRICATED not in report.markdown
    assert report.references and "[1]" in report.markdown

    # 4. the audit trail recorded every stage and the run is stored
    nodes = {e.node.split(":")[0] for e in repo.list_events(run_id)}
    assert {"plan", "research", "draft", "verify", "coverage_gate", "gap_plan", "synthesize", "cite_check"} <= nodes
    run = repo.get_run(run_id)
    assert run.status == "done"
    snap = json.loads(run.snapshot_json)
    assert any(not c["kept"] for c in snap["claims"])


def test_ablation_mode_skips_verification(fake_world, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("VERIFY_ENABLED", "false")
    get_settings.cache_clear()
    run_id = "run_ablation"
    repo.create_run(run_id, "What are the main risks of the battery market?", "standard", [])
    state = execute_run(run_id, "What are the main risks of the battery market?", "standard", [])
    assert all(v.label == VerdictLabel.SUPPORTED for v in state["verdicts"])
    assert FABRICATED in state["report"].markdown  # without the verifier, fabrication gets through


def test_repeated_question_reuses_the_plan(fake_world):
    q = "What are the main risks of the battery market?"
    run_a, run_b = new_id("run"), new_id("run")
    repo.create_run(run_a, q, "standard", [])
    first = execute_run(run_a, q, "standard", [])
    planner_calls = fake_world.calls.count("PlanOut")
    repo.create_run(run_b, q, "standard", [])
    second = execute_run(run_b, q, "standard", [])
    assert fake_world.calls.count("PlanOut") == planner_calls  # no new planner call
    assert [s.text for s in second["sub_questions"]] == [s.text for s in first["sub_questions"]]
    assert {s.id for s in second["sub_questions"]}.isdisjoint({s.id for s in first["sub_questions"]})
