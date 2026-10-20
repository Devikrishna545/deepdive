"""Code safety net for the writer: corroborated figures the synthesizer left out are added to
their section, as written in the verified claim.

Benchmark 3 lost 6 of 13 missing facts at this step: the claims were verified and kept, but the
writer chose background claims instead (b05 kept the US figure and dropped the global one).
A candidate must be a kept claim whose figure (not just a year) is also stated by another kept
claim citing different passages: two passages agreeing on a number marks it as central to the
topic. Replayed on benchmark 3's stored runs: 9 sentences added over 10 reports, recovering both lost
b05 facts (one sentence: "1.5% ... in 2024, or 415 TWh"). Adding every uncited figure added 46.
The added sentence IS the kept claim, cited to itself, so no unverified text enters; the
citation check still runs after it.
"""

from __future__ import annotations

import re

from app.core.schemas import Claim, Report, ReportSentence

MAX_ADDED_PER_SECTION = 2
_NUMBER = re.compile(r"\d[\d,.]*")
_YEAR = re.compile(r"^(19|20)\d\d$")


def figures(text: str) -> set[str]:
    """Numbers in a text, without years and thousands separators ("375,000" -> "375000")."""
    found = {n.strip(".,").replace(",", "") for n in _NUMBER.findall(text)}
    return {n for n in found if n and not _YEAR.match(n)}


def corroborated(claim: Claim, kept: list[Claim]) -> bool:
    own = figures(claim.text)
    return bool(own) and any(
        o.id != claim.id and own & figures(o.text) and set(o.cited_chunk_ids) != set(claim.cited_chunk_ids)
        for o in kept
    )


def fill_key_claims(report: Report, kept: list[Claim]) -> tuple[Report, int]:
    """Returns the report with missing corroborated claims appended per section, and how many.
    Skipped: claims already cited anywhere, and claims whose figures all appear in the report
    already (the writer merged them, or another added claim says the same)."""
    sentences = report.executive_summary + [s for sec in report.sections for s in sec.sentences]
    cited = {cid for s in sentences for cid in s.claim_ids}
    present = set().union(*(figures(s.text) for s in sentences)) if sentences else set()
    added = 0
    sections = []
    for sec in report.sections:
        extra = []
        for c in kept:
            if len(extra) >= MAX_ADDED_PER_SECTION:
                break
            if c.sub_question_id != sec.sub_question_id or c.id in cited:
                continue
            own = figures(c.text)
            if not own or own <= present or not corroborated(c, kept):
                continue
            extra.append(ReportSentence(text=c.text, claim_ids=[c.id]))
            present |= own
            cited.add(c.id)
        added += len(extra)
        sections.append(sec.model_copy(update={"sentences": sec.sentences + extra}) if extra else sec)
    return report.model_copy(update={"sections": sections}), added


MAX_FILLED_PER_SECTION = 3


def fill_empty_sections(report: Report, kept: list[Claim]) -> tuple[Report, int]:
    """A section the writer left empty although its sub-question has verified claims gets up to
    MAX_FILLED_PER_SECTION of them, as written in the claim (claims with figures first, then in
    drafting order), each cited to itself. The coverage gate had counted these claims ("coverage
    ok"), so an empty section contradicted the audit trail. Stored runs: 11 of the last 40 reports
    had a section left empty with 3-10 verified claims behind it (gpt-4o-mini skipped it).
    Claims already cited elsewhere in the report are not repeated."""
    sentences = report.executive_summary + [s for sec in report.sections for s in sec.sentences]
    cited = {cid for s in sentences for cid in s.claim_ids}
    added = 0
    sections = []
    for sec in report.sections:
        if sec.sentences:
            sections.append(sec)
            continue
        own = [c for c in kept if c.sub_question_id == sec.sub_question_id and c.id not in cited]
        own.sort(key=lambda c: not figures(c.text))  # stable: figures first, drafting order kept
        extra = [ReportSentence(text=c.text, claim_ids=[c.id]) for c in own[:MAX_FILLED_PER_SECTION]]
        cited.update(c.id for c in own[:MAX_FILLED_PER_SECTION])
        added += len(extra)
        sections.append(sec.model_copy(update={"sentences": extra}) if extra else sec)
    return report.model_copy(update={"sections": sections}), added
