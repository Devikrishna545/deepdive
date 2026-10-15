"""Source-quality weighting (bonus feature). Deliberately simple and visible.

score = tier_weight(domain) * recency_factor(published_at)

The score ranks which search results the Researcher fetches first and is shown next
to every reference. Edit the tables below, not the agents, to change trust policy.
"""

from __future__ import annotations

from datetime import date, datetime

# Order matters: the first matching rule wins.
TIER_RULES: list[tuple[str, float, str]] = [
    # (domain suffix or substring, weight, tier name)
    ("sec.gov", 1.0, "filing"),
    (".gov", 1.0, "government"),
    (".mil", 1.0, "government"),
    ("europa.eu", 1.0, "government"),
    ("iea.org", 1.0, "intergovernmental"),
    ("imf.org", 1.0, "intergovernmental"),
    ("worldbank.org", 1.0, "intergovernmental"),
    ("oecd.org", 1.0, "intergovernmental"),
    ("un.org", 1.0, "intergovernmental"),
    (".edu", 0.9, "academic"),
    (".ac.", 0.9, "academic"),
    ("arxiv.org", 0.9, "academic"),
    ("nature.com", 0.9, "academic"),
    ("sciencedirect.com", 0.9, "academic"),
    ("ncbi.nlm.nih.gov", 0.9, "academic"),
    ("reuters.com", 0.8, "major news"),
    ("bloomberg.com", 0.8, "major news"),
    ("ft.com", 0.8, "major news"),
    ("wsj.com", 0.8, "major news"),
    ("bbc.co.uk", 0.8, "major news"),
    ("bbc.com", 0.8, "major news"),
    ("apnews.com", 0.8, "major news"),
    ("economist.com", 0.8, "major news"),
    ("cnbc.com", 0.75, "major news"),
    ("medium.com", 0.3, "blog"),
    ("substack.com", 0.3, "blog"),
    ("reddit.com", 0.3, "forum"),
    ("quora.com", 0.3, "forum"),
    ("blogspot.", 0.3, "blog"),
    ("wordpress.", 0.3, "blog"),
]
DEFAULT_WEIGHT = 0.6  # industry sites, company pages, trade press
FILE_WEIGHT = 0.9  # user-uploaded documents are trusted primary material


def _matches(domain: str, pattern: str) -> bool:
    if pattern.startswith("."):  # label fragment, e.g. ".gov" matches x.gov and x.gov.uk
        return pattern.rstrip(".") + "." in "." + domain + "."
    if pattern.endswith("."):  # name prefix, e.g. "blogspot." matches x.blogspot.com
        return pattern in domain
    return domain == pattern or domain.endswith("." + pattern)


def tier_of(domain: str) -> tuple[float, str]:
    d = domain.lower()
    for pattern, weight, name in TIER_RULES:
        if _matches(d, pattern):
            return weight, name
    return DEFAULT_WEIGHT, "industry/other"


def recency_factor(published_at: str | None, today: date | None = None) -> float:
    if not published_at:
        return 0.8  # unknown date: mild penalty
    try:
        published = datetime.fromisoformat(published_at[:10]).date()
    except ValueError:
        return 0.8
    months = ((today or date.today()) - published).days / 30.44
    if months < 12:
        return 1.0
    if months < 36:
        return 0.8
    return 0.6


def quality_score(domain: str, published_at: str | None, kind: str = "web") -> float:
    weight = FILE_WEIGHT if kind == "file" else tier_of(domain)[0]
    return round(weight * recency_factor(published_at), 3)
