"""The writer sometimes skips a sub-question that has verified claims; code fills that section."""

from __future__ import annotations

from app.core.key_claims import MAX_FILLED_PER_SECTION, fill_empty_sections
from app.core.schemas import Claim, Report, ReportSection, ReportSentence


def _claim(cid: str, sq: str, text: str) -> Claim:
    return Claim(id=cid, sub_question_id=sq, text=text, cited_chunk_ids=[f"chk_{cid}"])


def _report(sections: list[ReportSection], summary_ids: list[str]) -> Report:
    return Report(question="q", executive_summary=[ReportSentence(text="Summary.", claim_ids=summary_ids)],
                  sections=sections, disagreements=[], limitations=[])


def test_empty_section_with_kept_claims_is_filled_from_those_claims():
    kept = [_claim("clm_a1", "sq_a", "Background without numbers."),
            _claim("clm_a2", "sq_a", "Providers must publish a summary of training data by 2 August 2025."),
            _claim("clm_a3", "sq_a", "Fines reach 3% of global turnover."),
            _claim("clm_a4", "sq_a", "Another plain background sentence."),
            _claim("clm_a5", "sq_a", "Already in the summary."),
            _claim("clm_b1", "sq_b", "Written by the writer.")]
    report = _report([ReportSection(sub_question_id="sq_a", heading="A", sentences=[]),
                      ReportSection(sub_question_id="sq_b", heading="B",
                                    sentences=[ReportSentence(text="Written by the writer.", claim_ids=["clm_b1"])]),
                      ReportSection(sub_question_id="sq_c", heading="C", sentences=[])],
                     summary_ids=["clm_a5"])
    out, added = fill_empty_sections(report, kept)
    a, b, c = out.sections
    assert added == MAX_FILLED_PER_SECTION == len(a.sentences)
    assert [s.claim_ids for s in a.sentences] == [["clm_a2"], ["clm_a3"], ["clm_a1"]]  # figures first
    assert all(s.text == next(k.text for k in kept if k.id == s.claim_ids[0]) for s in a.sentences)  # verbatim
    assert "clm_a5" not in {i for s in a.sentences for i in s.claim_ids}  # not repeated
    assert b.sentences == report.sections[1].sentences  # sections the writer wrote are untouched
    assert c.sentences == []  # no kept claims: stays empty (the UI says none passed)
