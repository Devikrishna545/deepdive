"""Final deterministic citation check and reference numbering.

Every sentence in the report must point to at least one kept (verified) claim ID.
Sentences that don't are removed and logged in `dropped_sentences`. References are
numbered in order of first use, and rendered into Markdown.
"""

from __future__ import annotations

from app.core.schemas import Chunk, Claim, Reference, Report, ReportSentence, Source


def _filter(sentences: list[ReportSentence], kept_ids: set[str]) -> tuple[list, list]:
    keep, drop = [], []
    for s in sentences:
        valid = [cid for cid in s.claim_ids if cid in kept_ids]
        if valid and s.text.strip():
            keep.append(s.model_copy(update={"claim_ids": valid}))
        else:
            drop.append(s)
    return keep, drop


def enforce_citations(report: Report, kept: list[Claim]) -> Report:
    kept_ids = {c.id for c in kept}
    dropped: list[ReportSentence] = []
    summary, d = _filter(report.executive_summary, kept_ids)
    dropped += d
    sections = []
    for section in report.sections:
        sentences, d = _filter(section.sentences, kept_ids)
        dropped += d
        sections.append(section.model_copy(update={"sentences": sentences}))
    return report.model_copy(
        update={
            "executive_summary": summary,
            "sections": sections,
            "dropped_sentences": report.dropped_sentences + dropped,
        }
    )


def build_references(
    report: Report, kept: list[Claim], chunks: dict[str, Chunk], sources: dict[str, Source]
) -> tuple[list[Reference], dict[str, list[int]]]:
    """Number sources in order of first citation. Returns refs and claim_id -> ref numbers."""
    claim_by_id = {c.id: c for c in kept}
    numbers: dict[str, int] = {}
    refs: list[Reference] = []
    claim_refs: dict[str, list[int]] = {}
    ordered = report.executive_summary + [s for sec in report.sections for s in sec.sentences]
    for sentence in ordered:
        for cid in sentence.claim_ids:
            claim = claim_by_id.get(cid)
            if not claim or cid in claim_refs:
                continue
            nums = []
            for chunk_id in claim.cited_chunk_ids:
                chunk = chunks.get(chunk_id)
                src = sources.get(chunk.source_id) if chunk else None
                if not src:
                    continue
                if src.id not in numbers:
                    numbers[src.id] = len(numbers) + 1
                    refs.append(
                        Reference(
                            number=numbers[src.id],
                            source_id=src.id,
                            url=src.url,
                            title=src.title or src.url,
                            domain=src.domain,
                            quality_score=src.quality_score,
                            page=chunk.page,
                        )
                    )
                nums.append(numbers[src.id])
            claim_refs[cid] = sorted(set(nums))
    return refs, claim_refs


def _cite(sentence: ReportSentence, claim_refs: dict[str, list[int]]) -> str:
    nums = sorted({n for cid in sentence.claim_ids for n in claim_refs.get(cid, [])})
    marks = "".join(f"[{n}]" for n in nums)
    return f"{sentence.text.rstrip()} {marks}".strip()


def render_markdown(report: Report, claim_refs: dict[str, list[int]]) -> str:
    lines = [f"# {report.question}", "", "## Executive summary", ""]
    lines += [f"- {_cite(s, claim_refs)}" for s in report.executive_summary] or ["_No verified summary._"]
    for section in report.sections:
        lines += ["", f"## {section.heading}", ""]
        if section.limited_evidence:
            lines.append("> Limited evidence: this sub-question did not reach the coverage bar.")
            lines.append("")
        lines.append(" ".join(_cite(s, claim_refs) for s in section.sentences) or "_No verified claims._")
    if report.disagreements:
        lines += ["", "## Where sources disagree", ""]
        lines += [f"- {c.explanation} (claims {c.claim_a} vs {c.claim_b})"
                  + (f"; {c.superseded_claim} removed: an official source contradicts it" if c.superseded_claim else "")
                  for c in report.disagreements]
    if report.limitations:
        lines += ["", "## Limitations", ""] + [f"- {item}" for item in report.limitations]
    lines += ["", "## References", ""]
    for ref in report.references:
        page = f", p.{ref.page}" if ref.page else ""
        lines.append(f"{ref.number}. [{ref.title}]({ref.url}) ({ref.domain}{page}, quality {ref.quality_score})")
    return "\n".join(lines) + "\n"
