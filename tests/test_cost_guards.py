"""Guards that keep Mesh credit use low. They fail when a change quietly makes calls more expensive."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_PROMPT_CHARS = 800  # ~200 tokens; prompts are sent on every call


def test_prompts_stay_short():
    for prompt in (ROOT / "app" / "agents").glob("*/*prompt.md"):
        assert len(prompt.read_text()) <= MAX_PROMPT_CHARS, f"{prompt} is too long for a per-call prompt"


def test_every_model_call_caps_output_tokens():
    pattern = re.compile(r"chat_json\((.*?)\)\n", re.S)
    for path in list((ROOT / "app").rglob("*.py")) + list((ROOT / "evaluation").rglob("*.py")):
        if path.name == "mesh_client.py":
            continue
        for call in pattern.findall(path.read_text()):
            assert "max_tokens" in call, f"{path.relative_to(ROOT)}: chat_json call without max_tokens"


def test_run_stops_at_usd_budget(fake_world, monkeypatch):
    from app.config import get_settings
    from app.db import repository as repo
    from app.llm import billing
    from app.services.run_service import execute_run

    # Price the fake calls absurdly high so the very first node crosses the budget.
    monkeypatch.setattr(billing, "load_prices", lambda refresh=False: {"openai/gpt-4o-mini": (1e9, 1e9)})
    fake_world.chat_json = _with_usage(fake_world.chat_json)
    monkeypatch.setenv("RUN_BUDGET_USD", "0.01")
    get_settings.cache_clear()
    repo.create_run("run_budget", "What are the main risks of the battery market?", "quick", [])
    try:
        execute_run("run_budget", "What are the main risks of the battery market?", "quick", [])
    except Exception as exc:
        assert "RUN_BUDGET_USD" in str(exc)
    else:
        raise AssertionError("run should have stopped at the USD budget")
    assert repo.get_run("run_budget").status == "failed"


def _with_usage(chat_json):
    """FakeMesh doesn't report usage; wrap it so each call records 10 prompt tokens."""
    from app.llm.usage import record_usage

    def wrapped(**kw):
        record_usage(model=kw["model"], prompt_tokens=10, completion_tokens=0, latency_ms=0)
        return chat_json(**kw)

    return wrapped
