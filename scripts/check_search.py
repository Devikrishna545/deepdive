"""Free check that web search works (no model calls, no Mesh credits).

    python -m scripts.check_search
    python -m scripts.check_search "UAE corporate tax rate"

Exit code 1 when the search returns nothing, so scripts can stop before a paid run.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

DEFAULT_QUERY = "European Commission AI Act application timeline"


def check(query: str = DEFAULT_QUERY) -> int:
    from app.db.session import init_db
    from app.tools.search import search_provider, web_search

    init_db()
    try:
        hits = web_search(query)
    except Exception as exc:  # web_search already swallows errors; this is belt and braces
        hits, error = [], exc
    else:
        error = None
    print(f"provider: {search_provider()}  query: {query!r}  results: {len(hits)}")
    for h in hits[:5]:
        print(f"  - {h.url}  (page text: {'yes' if h.content else 'fetched later'})")
    if not hits:
        print("Search returned nothing" + (f": {error}" if error else "") + ".")
        if search_provider() == "duckduckgo":
            print("DuckDuckGo is rate-limiting or blocking this network. Get a free Tavily key at "
                  "https://app.tavily.com and set TAVILY_API_KEY in .env.")
        return 1
    return 0


if __name__ == "__main__":
    load_dotenv()
    sys.exit(check(" ".join(sys.argv[1:]) or DEFAULT_QUERY))
