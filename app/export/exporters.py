"""Report export. Markdown is produced by the citation check; HTML is a print-ready page
(the browser's "Save as PDF" gives a clean PDF without native PDF dependencies)."""

from __future__ import annotations

import html

import markdown as md

PRINT_CSS = """
body{font-family:Georgia,serif;max-width:760px;margin:40px auto;padding:0 16px;line-height:1.55;color:#1f2933}
h1{font-size:1.7rem}h2{font-size:1.2rem;margin-top:1.6em;border-bottom:1px solid #ddd;padding-bottom:4px}
blockquote{color:#8a5a00;border-left:3px solid #e0a800;margin:0;padding-left:12px}
a{color:#1f5fbf}@media print{a{color:inherit;text-decoration:none}}
"""


def to_html(markdown_text: str, title: str) -> str:
    # Source titles and text come from the web: neutralise raw HTML before rendering.
    body = md.markdown(markdown_text.replace("<", "&lt;"), extensions=["extra"])
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"<style>{PRINT_CSS}</style></head><body>{body}</body></html>"
    )
