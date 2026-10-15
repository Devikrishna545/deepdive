"""Benchmark data and scorer: offline, no model calls."""

from __future__ import annotations

from evaluation.benchmark import fact_in, score_question, summarize
from evaluation.run_benchmark import load_benchmark, run_benchmark, to_markdown


def test_benchmark_file_is_well_formed():
    qs = load_benchmark()
    assert len(qs) == 10 and len({q["id"] for q in qs}) == 10
    for q in qs:
        assert q["key_facts"] and q["must_not_claim"] and q["sources"]
        for f in q["key_facts"]:
            assert f["anchors"] and all(isinstance(g, list) and g for g in f["anchors"])
        if q["false_premise"]:
            assert q["premise"]


def test_anchor_boundaries():
    nine = [["9%"]]
    assert fact_in(nine, "A 9% rate applies")
    assert not fact_in(nine, "a 19% rate") and not fact_in(nine, "only 0.9% of power")
    assert fact_in([["375,000"], ["0%"]], "0 % on income up to AED 375 000")
    assert fact_in([["alumin"]], "Aluminum imports")
    assert not fact_in([["375,000"], ["0%"]], "income above AED 375,000 is taxed at 9%")


def _question():
    return {"id": "t1", "question": "q", "must_not_claim": ["x"], "false_premise": False,
            "key_facts": [{"fact": "9% rate", "anchors": [["9%"]]},
                          {"fact": "threshold", "anchors": [["375,000"]]},
                          {"fact": "law 47", "anchors": [["47 of 2022"]]},
                          {"fact": "free zone", "anchors": [["free zone"]]}]}


def _run():
    chunks = {"c1": {"text": "Income above AED 375,000 is taxed at 9%."},
              "c2": {"text": "Federal Decree-Law No. 47 of 2022 introduced corporate tax."},
              "c3": {"text": "Free zone persons may qualify for 0%."}}
    claims = [
        {"id": "k1", "text": "Income above AED 375,000 is taxed at 9%.", "cited_chunk_ids": ["c1"], "kept": True},
        {"id": "k2", "text": "Federal Decree-Law No. 47 of 2022 applies to all income.", "cited_chunk_ids": ["c2"], "kept": False},
    ]
    snapshot = {"chunks": chunks, "claims": claims, "sources": {"s1": {"domain": "mof.gov.ae"}},
                "findings": [{"text": "Income above AED 375,000 is taxed at 9%."},
                             {"text": "Federal Decree-Law No. 47 of 2022 introduced corporate tax."}],
                "verdicts": [{"claim_id": "k2", "label": "PARTIAL", "reason": "source does not say all income"}]}
    report = {"executive_summary": [{"text": "Income above AED 375,000 is taxed at 9%.", "claim_ids": ["k1"]}],
              "sections": [{"sentences": [{"text": "Rates are new.", "claim_ids": []}]}]}
    return report, snapshot


def test_facts_are_traced_to_the_stage_that_lost_them():
    report, snapshot = _run()
    row = score_question(_question(), report, snapshot,
                         {"covered": [True, True, False, False], "must_not": [False], "premise_corrected": None})
    by = {f["fact"]: f for f in row["facts"]}
    assert by["9% rate"]["stages"]["reported"] and by["9% rate"]["citation_ok"]
    assert by["law 47"]["lost_at"] == "verified"  # drafted, then removed by the verifier
    assert by["law 47"]["rejections"][0]["reason"] == "source does not say all income"
    assert by["free zone"]["lost_at"] == "extracted"  # retrieved but never extracted
    assert row["fact_coverage"] == 0.5 and row["judge_fact_coverage"] == 0.5
    assert row["citation_accuracy"] == 1.0 and row["uncited_sentences"] == 1
    s = summarize([row | {"cost_usd": 0.01, "seconds": 3}, {"id": "t2", "error": "boom", "cost_usd": 0.002}])
    assert s["failed"] == 1 and s["facts_lost_at"]["verified"] == 1 and s["total_cost_usd"] == 0.012


def test_benchmark_runs_end_to_end_offline(fake_world):
    rows, stopped = run_benchmark(load_benchmark(["b01"]), "quick", 1.0, judge=None)
    assert stopped is None and len(rows) == 1 and "error" not in rows[0]
    r = rows[0]
    assert r["usage"]["totals"]["calls"] > 0 and r["cost_usd"] > 0
    assert set(r["lost_at"]) == {"retrieved", "extracted", "drafted", "verified", "reported"}
    md = to_markdown({"timestamp": "t", "depth": "quick", "judge_model": None, "stopped_early": None,
                      "summary": summarize(rows), "rows": rows})
    assert "Where missing facts were lost" in md and "Tokens by agent" in md


def test_benchmark_stops_at_budget(fake_world):
    rows, stopped = run_benchmark(load_benchmark(["b01", "b02"]), "quick", 0.0, judge=None)
    assert rows == [] and "budget" in stopped


def test_run_with_no_sources_stops_before_drafting(fake_world, monkeypatch):
    monkeypatch.setattr("app.agents.researcher.agent.web_search", lambda q, max_results=None: [])
    rows, stopped = run_benchmark(load_benchmark(["b01", "b02"]), "quick", 1.0, judge=None)
    assert len(rows) == 1 and "NoEvidence" in rows[0]["error"]  # b02 never started
    assert "search returned nothing" in stopped
    assert not {"ClaimsOut", "VerdictOut", "SynthesisOut"} & set(fake_world.calls)  # nothing paid after research


def test_ddg_retries_once_and_never_caches_empty(monkeypatch):
    import ddgs

    from app.tools import search

    monkeypatch.setattr(search, "_DDG_GAP_S", 0)
    monkeypatch.setattr(search, "_DDG_RETRY_WAIT_S", 0)
    replies = [Exception("No results found."), [{"href": "https://a.gov/x", "title": "t", "body": "b"}]]

    class FakeDDGS:
        def text(self, query, max_results):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

    monkeypatch.setattr(ddgs, "DDGS", FakeDDGS)
    assert [h.url for h in search.web_search("q1")] == ["https://a.gov/x"]  # second attempt worked

    monkeypatch.setattr(ddgs, "DDGS", lambda: type("E", (), {"text": lambda self, q, max_results: []})())
    assert search.web_search("q2") == []
    calls = []
    monkeypatch.setattr(ddgs, "DDGS", lambda: type("O", (), {"text": lambda self, q, max_results: calls.append(q) or
                                                              [{"href": "https://b.org", "title": "", "body": ""}]})())
    assert search.web_search("q2") and calls == ["q2"]  # the empty answer was not cached


def test_reuse_scores_the_stored_run_instead_of_running_again(fake_world):
    first, _ = run_benchmark(load_benchmark(["b01"]), "quick", 1.0, judge=None)
    calls = len(fake_world.calls)
    again, _ = run_benchmark(load_benchmark(["b01"]), "quick", 1.0, judge=None, reuse=True)
    assert again[0]["run_id"] == first[0]["run_id"] and again[0]["reused"]
    assert len(fake_world.calls) == calls  # no model calls at all


def test_anchor_ignores_leading_zero_in_day():
    assert fact_in([["2 august 2026"]], "The majority of rules apply from 02 August 2026.")
    assert not fact_in([["2 august 2026"]], "from 12 August 2026")
