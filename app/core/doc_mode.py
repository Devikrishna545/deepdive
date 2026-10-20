"""Document mode: a question about the attached documents is answered from those documents only.

"What are the optimizations in this attached paper?" cannot be answered by web search: the web
does not know which paper "this" is, so searching "paper title" returns other papers. When files
are attached and the question points at them, the researcher skips web search, the planner sees
the documents' opening text, and one document counts as enough independent sources for a section.
"""

from __future__ import annotations

import re

_DOC_NOUN = r"(?:research\s+)?(?:paper|document|doc|file|pdf|report|article|study|manuscript|thesis|memo|contract|notes?|slides?|deck|attachment|upload)s?"
DOC_REFERENCE = re.compile(
    rf"\b(?:this|the|these|those|my|our|given|provided|enclosed|attached|uploaded)\s+(?:attached\s+|uploaded\s+|enclosed\s+)?{_DOC_NOUN}\b"
    r"|\battach(?:ed|ment)\b|\buploaded\b",
    re.IGNORECASE,
)


def is_document_question(question: str, file_ids: list[str] | None) -> bool:
    """True when documents are attached and the question refers to them."""
    return bool(file_ids) and bool(DOC_REFERENCE.search(question or ""))
