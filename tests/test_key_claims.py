"""Code safety net: corroborated verified figures the writer skipped are added to their section."""

from __future__ import annotations

from app.core.key_claims import MAX_ADDED_PER_SECTION, corroborated, figures, fill_key_claims
from app.core.schemas import Claim, Report, ReportSection, ReportSentence


def claim(cid, text, chunk="ch1", sq="sq1"):
    return Claim(id=cid, sub_question_id=sq, text=text, cited_chunk_ids=[chunk])


def report(sentences, sq="sq1"):
    return Report(question="q", executive_summary=[],
                  sections=[ReportSection(sub_question_id=sq, heading="h", sentences=sentences)])


US = claim("clm_a", "US data centres used 176 TWh in 2023.", "ch0")
GLOBAL = claim("clm_b", "Data centres used about 415 TWh worldwide in 2024.", "ch1")
GLOBAL_2 = claim("clm_c", "Global data centre demand was 415 TWh in 2024.", "ch2")


def test_adds_corroborated_figure_cited_to_itself():
    rep = report([ReportSentence(text=US.text, claim_ids=["clm_a"])])
    out, added = fill_key_claims(rep, [US, GLOBAL, GLOBAL_2])
    assert added == 1  # the second 415 TWh claim is a duplicate of the first added one
    assert out.sections[0].sentences[-1].claim_ids == ["clm_b"]
    assert out.sections[0].sentences[-1].text == GLOBAL.text


def test_skips_uncorroborated_cited_and_merged_claims():
    lone = claim("clm_d", "A single source says 33 plants opened.", "ch3")
    same_chunk = claim("clm_e", "Data centres used 415 TWh.", "ch1")  # same passage: no corroboration
    assert not corroborated(lone, [US, lone]) and not corroborated(same_chunk, [GLOBAL, same_chunk])
    rep = report([ReportSentence(text="Use was 415 TWh in 2024.", claim_ids=["clm_a"])])
    out, added = fill_key_claims(rep, [US, GLOBAL, GLOBAL_2, lone])
    assert added == 0 and out == rep


def test_years_are_not_figures_and_cap_holds():
    assert figures("In 2024 sales hit 17 million, up 375,000.") == {"17", "375000"}
    kept = [c for i in range(1, 5) for c in (claim(f"clm_{i}a", f"Figure {i * 11} units.", f"x{i}"),
                                              claim(f"clm_{i}b", f"Also {i * 11} units.", f"y{i}"))]
    _, added = fill_key_claims(report([]), kept)
    assert added == MAX_ADDED_PER_SECTION
