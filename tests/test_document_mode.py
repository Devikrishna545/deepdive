"""Document mode: questions about the attached documents are answered from them only."""

from __future__ import annotations

import pytest

from app.core.doc_mode import is_document_question
from app.db import repository as repo
from app.services.run_service import execute_run
from app.tools import documents

_FILL = " ".join(["The section continues with further detail on data sets, evaluation and training setup."] * 7)
PAPER = "\n\n".join([
    "Efficient Estimation of Word Representations in Vector Space. Tomas Mikolov, Kai Chen, Greg Corrado, "
    "Jeffrey Dean. Google Inc. 2013. " + _FILL,
    "We propose two novel model architectures for computing continuous vector representations of words. " + _FILL,
    "The training speed is in the order of billions of words per hour for typical hyperparameter choices. " + _FILL,
    "To reduce computational complexity we remove the non-linear hidden layer of the model. " + _FILL,
    "Hierarchical softmax with a Huffman tree reduces the cost of the output layer. " + _FILL,
    "The battery market size and battery supply risks are discussed in an unrelated appendix. " + _FILL,
])


@pytest.mark.parametrize("question,expected", [
    ("What are the computational optimizations done in this attached paper?", True),
    ("Summarize the uploaded document", True),
    ("What do our documents say about battery supply?", True),
    ("What is this paper about?", True),
    ("How much electricity do data centres use worldwide?", False),
])
def test_detects_questions_about_the_attachments(question, expected):
    assert is_document_question(question, ["doc_1"]) is expected
    assert is_document_question(question, []) is False  # nothing attached: never document mode


@pytest.fixture
def paper(fake_world, tmp_path):
    path = tmp_path / "paper.txt"
    path.write_text(PAPER)
    return documents.ingest_document(path, "word2vec.txt").id


def test_document_question_uses_only_the_document(fake_world, paper, monkeypatch):
    searched = []
    monkeypatch.setattr("app.agents.researcher.agent.web_search", lambda q, max_results=None: searched.append(q) or [])
    q = "What are the computational optimizations done in this attached paper?"
    repo.create_run("run_doc", q, "quick", [paper])
    state = execute_run("run_doc", q, "quick", [paper])

    assert searched == []  # no web search at all
    plan_prompt = next(p for p in fake_world.prompts if "MAX_SUB_QUESTIONS" in p)
    assert "DOCUMENTS:" in plan_prompt and "Efficient Estimation of Word Representations" in plan_prompt
    assert not any(sq.checks_premise for sq in state["sub_questions"])
    assert {s.kind for s in state["sources"].values()} == {"file"}
    # the title page is always a candidate, so title/authors can be answered
    title_chunk = next(c for c in state["chunks"].values() if "Tomas Mikolov" in c.text)
    assert title_chunk
    # one document is enough independent sources: a sub-question with 2+ verified claims from the
    # single document never loops back hunting for a second domain
    import json
    gate = next(e for e in repo.list_events("run_doc") if e.node == "coverage_gate")
    info = json.loads(gate.payload_json)
    for sq_id, cov in info["coverage"].items():
        if cov["supported"] >= 2:
            assert cov["domains"] == 1 and sq_id not in info["gaps"]
    assert any(c["supported"] >= 2 for c in info["coverage"].values())
    assert not any(sec.limited_evidence for sec in state["report"].sections if sec.sentences)
    plan_event = next(e for e in repo.list_events("run_doc") if e.node == "plan" and e.phase == "end")
    assert "documents only" in plan_event.summary


def test_general_question_with_files_still_searches_the_web(fake_world, paper):
    q = "What are the main risks of the battery market?"
    repo.create_run("run_mix", q, "standard", [paper])
    state = execute_run("run_mix", q, "standard", [paper])
    kinds = {s.kind for s in state["sources"].values()}
    assert kinds == {"web", "file"}  # unchanged behaviour: web plus the documents
    assert "DOCUMENTS:" not in next(p for p in fake_world.prompts if "MAX_SUB_QUESTIONS" in p)


def test_web_addon_searches_only_for_parts_the_document_leaves_thin(fake_world, paper, monkeypatch):
    from app.config import get_settings
    from tests.fakes import fake_search

    searched = []
    monkeypatch.setattr("app.agents.researcher.agent.web_search",
                        lambda q, max_results=None: searched.append(q) or fake_search(q))
    monkeypatch.setenv("MIN_SUPPORTED_CLAIMS", "50")  # every part counts as thin
    get_settings.cache_clear()
    q = "What are the computational optimizations done in this attached paper?"
    repo.create_run("run_web", q, "quick", [paper], web_addon=True)
    state = execute_run("run_web", q, "quick", [paper])

    first_pass = [e for e in state["research_log"] if e["round"] == 0]
    assert all(not e["urls_fetched"] for e in first_pass) and first_pass  # documents first: no web
    assert searched and set(searched) <= {qq for e in state["research_log"] if e["round"] > 0 for qq in e["queries"]}
    kinds = {s.kind for s in state["sources"].values()}
    assert kinds == {"file", "web"}  # the web filled the thin parts; the document is still there
    plan_event = next(e for e in repo.list_events("run_web") if e.node == "plan" and e.phase == "end")
    assert "documents first" in plan_event.summary


def test_web_addon_is_skipped_when_the_document_answers_everything(fake_world, paper, monkeypatch):
    searched = []
    monkeypatch.setattr("app.agents.researcher.agent.web_search", lambda q, max_results=None: searched.append(q) or [])
    monkeypatch.setattr("app.graph.nodes.find_gaps", lambda *a, **k: [])  # every part well covered
    q = "Summarize the attached paper"
    repo.create_run("run_full", q, "quick", [paper], web_addon=True)
    execute_run("run_full", q, "quick", [paper])
    assert searched == []


def test_web_search_choice_is_stored_and_carried_over(fake_world, paper, monkeypatch):
    from fastapi.testclient import TestClient

    from app import create_app
    from app.services import run_service

    monkeypatch.setattr(run_service, "execute_run", lambda *a, **k: None)
    with TestClient(create_app()) as c:
        body = {"question": "What does this attached paper propose?", "depth": "quick", "file_ids": [paper], "web_search": True}
        rid = c.post("/api/runs", json=body).json()["run_id"]
        assert c.get(f"/api/runs/{rid}").json()["web_search"] is True
        no_files = c.post("/api/runs", json=body | {"file_ids": []}).json()["run_id"]
        assert c.get(f"/api/runs/{no_files}").json()["web_search"] is False  # meaningless without documents
        repo.update_run(rid, status="done", report_json="{}")
        kept = c.post(f"/api/runs/{rid}/rerun", json={"question": "What does this attached paper propose exactly?"}).json()["run_id"]
        assert repo.get_run(kept).web_addon is True  # edit & run again keeps the choice
        off = c.post(f"/api/runs/{rid}/rerun", json={"question": "What does this attached paper propose exactly?", "web_search": False}).json()["run_id"]
        assert repo.get_run(off).web_addon is False
        follow = c.post(f"/api/runs/{rid}/followup", json={"question": "And who are the authors?"}).json()["run_id"]
        assert repo.get_run(follow).web_addon is True  # follow-ups inherit it
