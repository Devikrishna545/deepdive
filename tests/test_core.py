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


def test_cut_off_reply_is_retried_with_bigger_cap_not_repaired():
    from app.core.schemas import GapQueriesOut
    from app.llm.mesh_client import THINKING_MIN_TOKENS, MeshClient

    client = MeshClient(api_key="rsk_test", base_url="http://unused")
    caps = []

    def fake_complete(model, messages, temperature, max_tokens):
        caps.append(max_tokens)
        if max_tokens < THINKING_MIN_TOKENS:
            return '{"queries": ["battery rep', "length"  # half-written JSON at the cap
        return '{"queries": ["battery report 2026"]}', "stop"

    client._complete = fake_complete
    out = client.chat_json(model="openai/gpt-4o-mini", system="s", user="u", schema=GapQueriesOut, max_tokens=60)
    assert out.queries == ["battery report 2026"] and caps == [60, THINKING_MIN_TOKENS]
    assert "openai/gpt-4o-mini" not in client._thinking_models  # it did answer, so not a thinking model


def test_synthesis_drops_stray_fragments():
    from app.core.schemas import SynthesisOut

    out = SynthesisOut.model_validate({
        "executive_summary": [{"text": "A.", "claim_ids": ["clm_1"]}],
        "sections": [{"sub_question_id": "sq_1", "heading": "H", "sentences": []}, "limitations:["],
        "limitations": ["x"],
    })
    assert len(out.sections) == 1


def test_synthesizer_falls_back_to_verified_claims_when_output_stays_invalid():
    from app.agents.synthesizer.agent import FALLBACK_NOTE, SynthesizerAgent
    from app.core.schemas import Claim, SubQuestion
    from app.llm import mesh_client

    class BrokenMesh:
        def chat_json(self, **kwargs):
            raise mesh_client.MeshError("openai/gpt-4o-mini did not return valid SynthesisOut")

    mesh_client.set_mesh(BrokenMesh())
    sq = SubQuestion(id="sq_1", text="Rates?", queries=["q"])
    kept = [Claim(id="clm_1", sub_question_id="sq_1", text="The rate is 9%.", cited_chunk_ids=["chk_1"])]
    report = SynthesizerAgent().synthesize("Q?", [sq], kept, [], {})
    assert report.sections[0].sentences[0].claim_ids == ["clm_1"]
    assert report.executive_summary[0].text == "The rate is 9%."
    assert report.limitations == [FALLBACK_NOTE]


def test_quote_guard_ignores_markdown_links_and_footnotes():
    from app.core.guards import quote_in_sources

    chunk = ("UAE Corporate Tax is a direct federal tax introduced under "
             "[Federal Decree-Law No. 47 of 2022](https://mof.gov.ae/law_(1).pdf) on the Taxation.[[8]](#cite_note-8)")
    assert quote_in_sources("introduced under Federal Decree-Law No. 47 of 2022 on the Taxation", [chunk])
    assert not quote_in_sources("introduced under Federal Decree-Law No. 48 of 2022", [chunk])


def test_quote_guard_accepts_elided_quote_only_in_order_in_one_chunk():
    from app.core.guards import quote_in_sources

    chunk = 'The rate will be 9% for income above AED 375,000, "to support small businesses," the ministry said.'
    assert quote_in_sources("The rate will be 9% for income above AED 375,000... the ministry said", [chunk])
    assert not quote_in_sources("the ministry said ... The rate will be 9% for income", [chunk])  # wrong order
    assert not quote_in_sources("The rate will be 9%... the ministry said", ["The rate will be 9%.", "the ministry said"])
    assert not quote_in_sources("rate ... said", [chunk])  # no piece is long enough to prove anything


def test_chunks_are_cleaned_and_figures_rank_higher():
    from app.tools.chunker import relevance, split_text

    page = "Intro text about corporate tax in the UAE. " * 3 + "\n[Read the law](https://x.gov/a.pdf) here, see [3]."
    assert all("http" not in c and "[3]" not in c for c in split_text(page))
    q = "corporate tax rate UAE"
    assert relevance("The corporate tax rate in the UAE is 9%.", q) > relevance("The corporate tax rate in the UAE is low.", q)


def test_source_labels():
    from app.core.schemas import Source
    from app.core.scoring import source_label

    assert source_label(Source(id="s", url="u", domain="climate.ec.europa.eu")) == "official"
    assert source_label(Source(id="s", url="u", domain="bbc.com")) == "news"
    assert source_label(Source(id="s", url="u", domain="electrifying.com")) == "other"
    assert source_label(Source(id="s", url="file://a.pdf", domain="a.pdf", kind="file")) == "official"


def test_planner_puts_a_premise_check_first_within_the_limit():
    from app.agents.planner.agent import PlannerAgent
    from app.core.schemas import PlanOut, SubQuestionOut
    from app.llm import mesh_client

    class PremiseMesh:
        def chat_json(self, **kwargs):
            return PlanOut(sub_questions=[SubQuestionOut(text=f"Why {i}", queries=["q"]) for i in range(3)],
                           premise="The EU banned petrol cars in 2024.", premise_queries=["EU petrol car ban 2024 status"])

    mesh_client.set_mesh(PremiseMesh())
    plan = PlannerAgent().plan("Why did the EU ban petrol cars in 2024?", depth="quick")
    assert len(plan) == 3 and plan[0].checks_premise
    assert plan[0].text == "Is it true that the EU banned petrol cars in 2024?"
    assert plan[0].queries == ["EU petrol car ban 2024 status"] and not plan[1].checks_premise


def test_synthesizer_headings_come_from_code_and_claims_carry_tiers():
    from app.agents.synthesizer.agent import SynthesizerAgent
    from app.core.schemas import Claim, ReportSentence, SectionOut, SubQuestion, SynthesisOut
    from app.llm import mesh_client

    seen = {}

    class Mesh:
        def chat_json(self, **kwargs):
            seen["user"] = kwargs["user"]
            return SynthesisOut(executive_summary=[ReportSentence(text="No ban in 2024.", claim_ids=["clm_1|official"])],
                                sections=[SectionOut(sub_question_id="sq_1", sentences=[])])

    mesh_client.set_mesh(Mesh())
    sq = SubQuestion(id="sq_1", text="Is it true that the EU banned petrol cars in 2024?", queries=["q"], checks_premise=True)
    kept = [Claim(id="clm_1", sub_question_id="sq_1", text="The 100% target applies from 2035.", cited_chunk_ids=["c"])]
    report = SynthesizerAgent().synthesize("Why did the EU ban petrol cars in 2024?", [sq], kept, [], {}, {"clm_1": "official"})
    assert report.sections[0].heading == sq.text
    assert report.executive_summary[0].claim_ids == ["clm_1"]  # decoration copied by the model is stripped
    assert "### sq_1 (PREMISE CHECK):" in seen["user"] and "[clm_1] (official)" in seen["user"]


def test_premise_claims_are_checked_against_official_sources():
    from app.core.contradictions import detect_contradictions
    from app.core.schemas import Chunk, Claim, PairJudgementOut

    chunks = {f"c{i}": Chunk(id=f"c{i}", source_id=f"s{i}", sub_question_id="sq_p", text="t") for i in range(3)}
    official = Claim(id="clm_off", sub_question_id="sq_p", text="From 2035 all new cars must be zero-emission.", cited_chunk_ids=["c0"])
    blog = Claim(id="clm_blog", sub_question_id="sq_p", text="The EU abandoned its 2035 ban.", cited_chunk_ids=["c1"])
    news = Claim(id="clm_news", sub_question_id="sq_p", text="The Commission proposed a 90% target.", cited_chunk_ids=["c2"])
    judged = []

    class Mesh:
        def embed(self, texts):
            return [[1.0, 0.2 * i] for i, _ in enumerate(texts)]

        def chat_json(self, **kw):
            judged.append(kw["user"])
            return PairJudgementOut(relation="disagree", explanation="status differs")

    found = detect_contradictions([official, blog, news], chunks, Mesh(), "m", 0.99,
                                  premise_sq_ids={"sq_p"},
                                  tiers={"clm_off": "official", "clm_blog": "other", "clm_news": "news"})
    assert len(judged) == 2  # official vs blog, official vs news; never blog vs news
    superseded = {c.claim_b: c.superseded_claim for c in found}
    assert superseded == {"clm_blog": "clm_blog", "clm_news": None}  # news is flagged, never removed
    assert all(c.claim_a == "clm_off" for c in found)


def test_typed_check_unchanged_outside_premise_questions():
    from app.core.contradictions import detect_contradictions
    from app.core.schemas import Chunk, Claim

    chunks = {"c0": Chunk(id="c0", source_id="s0", sub_question_id="sq", text="t")}
    plain = [Claim(id=f"clm_{i}", sub_question_id="sq", text="x", cited_chunk_ids=["c0"]) for i in range(3)]

    class Mesh:
        def embed(self, texts):
            raise AssertionError("no embedding needed: fact claims outside premise checks are skipped")

    assert detect_contradictions(plain, chunks, Mesh(), "m", 0.8) == []
