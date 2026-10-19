"""Evaluation runner robustness: a failing judge call is counted, not fatal; reruns can reuse finished runs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.llm import mesh_client
from app.llm.mesh_client import MeshError
from evaluation import run_eval


class FailingJudge:
    def chat_json(self, **kwargs):
        raise MeshError("google/gemini-2.5-flash did not return valid VerdictOut")


def _report_and_snapshot():
    report = {"executive_summary": [{"text": "Sales rose 20% in 2024.", "claim_ids": ["clm_1"]}], "sections": []}
    snapshot = {"claims": [{"id": "clm_1", "cited_chunk_ids": ["ch1"]}], "chunks": {"ch1": {"text": "Sales rose 20% in 2024."}}}
    return report, snapshot


def test_judge_failure_is_counted_not_fatal():
    mesh_client.set_mesh(FailingJudge())
    report, snapshot = _report_and_snapshot()
    out = run_eval._judge_groundedness(report, snapshot, "google/gemini-2.5-flash")
    assert out["judge_errors"] == 1 and out["sentences"] == 1 and out["groundedness"] in (0, 0.0, None)
    assert run_eval._judge_coverage({"must_cover": ["a"]}, "report", "google/gemini-2.5-flash") is None


def test_balance_errors_still_stop_the_run():
    class NoCredit:
        def chat_json(self, **kwargs):
            raise MeshError("Mesh refused the call: balance is zero (402).")

    mesh_client.set_mesh(NoCredit())
    report, snapshot = _report_and_snapshot()
    with pytest.raises(MeshError):
        run_eval._judge_groundedness(report, snapshot, "judge")


def test_reuse_finds_only_matching_finished_runs(fake_world):
    from app.db import repository as repo

    repo.create_run("eval_aaa", "Q one?", "quick", [])
    repo.update_run("eval_aaa", status="done")
    repo.create_run("evalab_bbb", "Q one?", "quick", [])
    repo.update_run("evalab_bbb", status="done")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    assert repo.latest_done_run("Q one?", "quick", "eval_", since).id == "eval_aaa"
    assert repo.latest_done_run("Q one?", "quick", "evalab_", since).id == "evalab_bbb"
    assert repo.latest_done_run("Q one?", "standard", "eval_", since) is None
