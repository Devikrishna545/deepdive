"""Planner on a reasoning model (gpt-5-nano) with gpt-oss-120b as the fallback."""

from __future__ import annotations

import pytest

from app.agents.planner.agent import PLAN_MAX_TOKENS, PlannerAgent
from app.config import get_settings
from app.core.schemas import GapQueriesOut, PlanOut, SubQuestionOut
from app.llm import mesh_client
from app.llm.mesh_client import MeshClient, MeshError


def test_invalid_reply_falls_back_to_the_second_model():
    client = MeshClient(api_key="rsk_test", base_url="http://unused")
    models = []

    def fake_complete(model, messages, temperature, max_tokens):
        models.append(model)
        return ("not json", "stop") if model == "openai/gpt-5-nano" else ('{"queries": ["q2"]}', "stop")

    client._complete = fake_complete
    out = client.chat_json(model="openai/gpt-5-nano", fallback_model="openai/gpt-oss-120b",
                           system="s", user="u", schema=GapQueriesOut, max_tokens=1000)
    assert out.queries == ["q2"]
    assert models == ["openai/gpt-5-nano", "openai/gpt-5-nano", "openai/gpt-oss-120b"]  # reply + repair, then fallback


def test_no_fallback_when_balance_is_exhausted():
    client = MeshClient(api_key="rsk_test", base_url="http://unused")
    models = []

    def fake_complete(model, messages, temperature, max_tokens):
        models.append(model)
        raise MeshError("Mesh refused the call: balance is zero or the key's spend cap is reached (402).")

    client._complete = fake_complete
    with pytest.raises(MeshError):
        client.chat_json(model="openai/gpt-5-nano", fallback_model="openai/gpt-oss-120b",
                         system="s", user="u", schema=GapQueriesOut)
    assert models == ["openai/gpt-5-nano"]


def test_planner_uses_reasoning_model_with_fallback_and_room_to_think(monkeypatch):
    monkeypatch.delenv("MODEL_PLANNER", raising=False)  # check the code defaults, not a local .env
    monkeypatch.delenv("MODEL_PLANNER_FALLBACK", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert s.model_planner == "openai/gpt-5-nano" and s.model_planner_fallback == "openai/gpt-oss-120b"
    calls = []

    class Mesh:
        def chat_json(self, **kw):
            calls.append((kw["model"], kw.get("fallback_model"), kw["max_tokens"]))
            return PlanOut(sub_questions=[SubQuestionOut(text=f"Part {i}", queries=["q"]) for i in range(3)])

    mesh_client.set_mesh(Mesh())
    assert len(PlannerAgent().plan("How many electric cars were sold globally in 2024?", depth="quick")) == 3
    assert calls == [(s.model_planner, s.model_planner_fallback, PLAN_MAX_TOKENS)]
    get_settings.cache_clear()


def test_reasoning_effort_is_sent_and_empty_reply_falls_back_without_repair():
    client = MeshClient(api_key="rsk_test", base_url="http://unused")
    seen = []

    def fake_complete(model, messages, temperature, max_tokens, reasoning_effort=None):
        seen.append((model, reasoning_effort))
        return ("", "length") if model == "openai/gpt-5-nano" else ('{"queries": ["q2"]}', "stop")

    client._complete = fake_complete
    out = client.chat_json(model="openai/gpt-5-nano", fallback_model="openai/gpt-oss-120b", system="s", user="u",
                           schema=GapQueriesOut, max_tokens=2500, reasoning_effort="low")
    assert out.queries == ["q2"]
    assert seen == [("openai/gpt-5-nano", "low"), ("openai/gpt-oss-120b", "low")]  # no repair of an empty reply


def test_planner_asks_for_low_reasoning_effort(monkeypatch):
    monkeypatch.delenv("PLANNER_REASONING_EFFORT", raising=False)
    get_settings.cache_clear()
    seen = {}

    class Mesh:
        def chat_json(self, **kw):
            seen.update(kw)
            return PlanOut(sub_questions=[SubQuestionOut(text="Part", queries=["q"])])

    mesh_client.set_mesh(Mesh())
    PlannerAgent().plan("How many electric cars were sold globally in 2024?", depth="quick")
    assert seen["reasoning_effort"] == "low"
    get_settings.cache_clear()


def test_premise_heading_keeps_acronyms():
    from app.agents.planner.agent import _lower_first
    assert _lower_first("EU banned petrol cars in 2024") == "EU banned petrol cars in 2024"
    assert _lower_first("IPCC's latest report exists") == "IPCC's latest report exists"
    assert _lower_first("The EU banned petrol cars") == "the EU banned petrol cars"
