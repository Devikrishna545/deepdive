"""Unit tests for the deterministic guards: quote guard, citation check, coverage, scoring, JSON parsing."""

from __future__ import annotations

from datetime import date

import pytest

from app.core.citation_check import enforce_citations
from app.core.coverage import coverage_by_subquestion, find_gaps
from app.core.guards import apply_quote_guard, precheck_claim
from app.core.schemas import (
    Chunk,
    Claim,
    Report,
    ReportSection,
    ReportSentence,
    Source,
    Verdict,
    VerdictLabel,
)
from app.core.scoring import quality_score, recency_factor, tier_of
from app.llm.mesh_client import extract_json

SOURCE = "Global EV battery demand rose to 750 GWh in 2023, up 40% on the year before."


def verdict(label, quote):
    return Verdict(claim_id="c1", label=label, reason="r", evidence_quote=quote)


def test_quote_guard_keeps_real_quote():
    v = apply_quote_guard(verdict(VerdictLabel.SUPPORTED, "battery demand rose to 750 GWh in 2023"), [SOURCE])
    assert v.label == VerdictLabel.SUPPORTED and not v.guard_downgraded


def test_quote_guard_downgrades_invented_quote():
    v = apply_quote_guard(verdict(VerdictLabel.SUPPORTED, "battery demand rose to 900 GWh in 2023"), [SOURCE])
    assert v.label == VerdictLabel.UNSUPPORTED and v.guard_downgraded


def test_quote_guard_ignores_whitespace_and_smart_quotes():
    v = apply_quote_guard(verdict(VerdictLabel.PARTIAL, "Global  EV battery\ndemand rose"), [SOURCE])
    assert v.label == VerdictLabel.PARTIAL


def test_quote_guard_rejects_tiny_quote():
    assert apply_quote_guard(verdict(VerdictLabel.SUPPORTED, "EV"), [SOURCE]).label == VerdictLabel.UNSUPPORTED


def test_precheck_flags_missing_number():
    assert precheck_claim("Demand reached 900 GWh", [SOURCE])
    assert precheck_claim("Demand reached 750 GWh in 2023", [SOURCE]) == []


def test_citation_check_drops_uncited_and_unverified():
    kept = [Claim(id="clm_a", sub_question_id="sq1", text="x", cited_chunk_ids=["k1"])]
    report = Report(
        question="q",
        executive_summary=[
            ReportSentence(text="good", claim_ids=["clm_a"]),
            ReportSentence(text="no cite", claim_ids=[]),
            ReportSentence(text="unverified cite", claim_ids=["clm_zzz"]),
        ],
        sections=[ReportSection(sub_question_id="sq1", heading="h", sentences=[ReportSentence(text="ok", claim_ids=["clm_a", "clm_bad"])])],
    )
    out = enforce_citations(report, kept)
    assert [s.text for s in out.executive_summary] == ["good"]
    assert len(out.dropped_sentences) == 2
    assert out.sections[0].sentences[0].claim_ids == ["clm_a"]


def test_coverage_requires_claims_and_domains():
    sources = {"s1": Source(id="s1", url="https://a.com", domain="a.com"), "s2": Source(id="s2", url="https://b.com", domain="b.com")}
    chunks = {"k1": Chunk(id="k1", source_id="s1", sub_question_id="sq1", text="t"),
              "k2": Chunk(id="k2", source_id="s2", sub_question_id="sq1", text="t")}
    claims = [Claim(id="c1", sub_question_id="sq1", text="a", cited_chunk_ids=["k1"]),
              Claim(id="c2", sub_question_id="sq1", text="b", cited_chunk_ids=["k1"])]
    verdicts = [Verdict(claim_id="c1", label=VerdictLabel.SUPPORTED, reason=""),
                Verdict(claim_id="c2", label=VerdictLabel.SUPPORTED, reason="")]
    cov = coverage_by_subquestion(["sq1"], claims, verdicts, chunks, sources)
    assert cov["sq1"].supported == 2 and cov["sq1"].domains == 1
    assert find_gaps(cov, {"sq1": 0}, 2, 2, 2) == ["sq1"]
    assert find_gaps(cov, {"sq1": 2}, 2, 2, 2) == []  # loop budget used up
    claims[1].cited_chunk_ids = ["k2"]
    cov = coverage_by_subquestion(["sq1"], claims, verdicts, chunks, sources)
    assert find_gaps(cov, {"sq1": 0}, 2, 2, 2) == []


@pytest.mark.parametrize(
    "domain,expected",
    [("data.gov.uk", 1.0), ("sec.gov", 1.0), ("mit.edu", 0.9), ("reuters.com", 0.8),
     ("someone.medium.com", 0.3), ("acme-batteries.com", 0.6), ("sun.org", 0.6)],
)
def test_tier_weights(domain, expected):
    assert tier_of(domain)[0] == expected


def test_recency_and_score():
    today = date(2026, 10, 15)
    assert recency_factor("2026-03-01", today) == 1.0
    assert recency_factor("2024-06-01", today) == 0.8
    assert recency_factor("2019-01-01", today) == 0.6
    assert quality_score("x.pdf", None, kind="file") == round(0.9 * 0.8, 3)


@pytest.mark.parametrize(
    "reply",
    ['{"a": 1}', '```json\n{"a": 1}\n```', 'Sure! Here it is: {"a": 1} hope that helps'],
)
def test_extract_json(reply):
    assert extract_json(reply) == {"a": 1}


def test_schema_hint_is_compact_and_complete():
    from app.core.schemas import VerdictOut
    from app.llm.schema_hint import schema_hint

    hint = schema_hint(VerdictOut)
    assert '"label":"SUPPORTED|PARTIAL|UNSUPPORTED|CONTRADICTED"' in hint
    assert '"narrowed_claim":str|null' in hint
    assert len(hint) < 150


def test_cost_uses_live_prices():
    from app.llm.billing import cost_usd

    # 1M prompt + 1M completion on gpt-4o-mini test prices = 0.15 + 0.60
    assert abs(cost_usd("openai/gpt-4o-mini", 1_000_000, 1_000_000) - 0.75) < 1e-9
    assert cost_usd("unknown/model", 1000, 1000) == 0.0


def test_verbatim_fast_path_needs_a_whole_sentence():
    from app.core.guards import verbatim_in_sources

    src = "Analysts deny that battery prices will rise next year. Demand rose to 750 GWh in 2023."
    assert verbatim_in_sources("Demand rose to 750 GWh in 2023.", [src])
    assert not verbatim_in_sources("battery prices will rise next year", [src])  # fragment of a denial
    assert not verbatim_in_sources("Demand rose", [src])  # too short to trust


def test_thinking_model_empty_reply_gets_one_bigger_retry():
    from app.core.schemas import GapQueriesOut
    from app.llm.mesh_client import THINKING_MIN_TOKENS, MeshClient

    client = MeshClient(api_key="rsk_test", base_url="http://unused")
    caps = []

    def fake_complete(model, messages, temperature, max_tokens):
        caps.append(max_tokens)
        if max_tokens < THINKING_MIN_TOKENS:
            return "", "length"  # all tokens spent on hidden reasoning
        return '{"queries": ["battery report 2026"]}', "stop"

    client._complete = fake_complete
    out = client.chat_json(model="google/gemini-2.5-flash", system="s", user="u", schema=GapQueriesOut, max_tokens=60)
    assert out.queries == ["battery report 2026"]
    assert caps == [60, THINKING_MIN_TOKENS]
    # next call starts with the larger cap straight away (no wasted call)
    client.chat_json(model="google/gemini-2.5-flash", system="s", user="u", schema=GapQueriesOut, max_tokens=60)
    assert caps[-1] == THINKING_MIN_TOKENS and len(caps) == 3
