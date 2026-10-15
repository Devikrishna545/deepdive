"""CI guard for the hackathon's hard rule: every LLM/AI call must go through Mesh API.

Fails if any Python file outside app/llm/ imports an LLM SDK, or if any file mentions a
direct provider endpoint or provider API key variable.
Run: python scripts/check_mesh_only.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_DIR = ROOT / "app" / "llm"
SKIP_DIRS = {".venv", "venv", ".git", "node_modules", "data", "__pycache__"}

SDK_IMPORT = re.compile(
    r"^\s*(from|import)\s+(openai|anthropic|google\.generativeai|google\.genai|langchain_openai|"
    r"langchain_anthropic|langchain_google_genai|cohere|mistralai|groq|litellm)\b",
    re.M,
)
FORBIDDEN_TEXT = re.compile(
    r"api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|"
    r"OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|GEMINI_API_KEY|include_answer\s*=\s*True"
)


def main() -> int:
    problems = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts) or path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(ROOT)
        if not path.is_relative_to(ALLOWED_DIR) and SDK_IMPORT.search(text):
            problems.append(f"{rel}: imports an LLM SDK outside app/llm/ (use get_mesh())")
        if FORBIDDEN_TEXT.search(text):
            problems.append(f"{rel}: references a direct provider endpoint/key")
    mesh = (ALLOWED_DIR / "mesh_client.py").read_text()
    if "base_url" not in mesh:
        problems.append("app/llm/mesh_client.py: OpenAI client must be created with the Mesh base_url")
    if problems:
        print("Mesh-only check FAILED:\n  " + "\n  ".join(problems))
        return 1
    print("Mesh-only check passed: all model calls go through app/llm/mesh_client.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
