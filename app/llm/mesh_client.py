"""The ONLY place in the codebase that talks to a language or embedding model.

Every LLM/AI call must route through Mesh API (hackathon rule). Mesh is
OpenAI-compatible, so we point the official OpenAI SDK at it. Agents never import
`openai` themselves: they call `get_mesh().chat_json(...)` or `get_mesh().embed(...)`.

Structured output strategy (works across model families on the gateway):
1. ask for JSON (response_format=json_object when the model accepts it),
2. extract the JSON object from the reply and validate it with Pydantic,
3. on a validation error, send the error back once and ask for a repaired object.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.llm.schema_hint import schema_hint
from app.llm.usage import record_usage

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class MeshError(RuntimeError):
    """Raised when Mesh cannot produce a valid response after retries."""


# Output cap used for "thinking" models whose hidden reasoning counts against max_tokens.
THINKING_MIN_TOKENS = 1200

# Retry only transient failures. Never retry 402 (no credit / spend cap) or 4xx input errors.
TRANSIENT = (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (handles code fences and chatter)."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model reply")
    return json.loads(cleaned[start : end + 1])


@dataclass
class MeshClient:
    api_key: str
    base_url: str
    _json_mode_unsupported: set[str] = field(default_factory=set)
    _thinking_models: set[str] = field(default_factory=set)
    _effort_unsupported: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        if not self.api_key:
            raise MeshError("MESH_API_KEY is not set. Add it to .env (see .env.example).")
        self._client = OpenAI(base_url=self.base_url, api_key=self.api_key, max_retries=0, timeout=90)

    # ------------------------------------------------------------------ chat
    @retry(
        retry=retry_if_exception_type(TRANSIENT),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _complete(self, model: str, messages: list[dict], temperature: float, max_tokens: int,
                  reasoning_effort: str | None = None) -> tuple[str, str]:
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,  # completion tokens cost more than prompt tokens: always cap
        }
        if model not in self._json_mode_unsupported:
            kwargs["response_format"] = {"type": "json_object"}
        if reasoning_effort and model not in self._effort_unsupported:
            kwargs["reasoning_effort"] = reasoning_effort  # limits hidden thinking on reasoning models
        started = time.perf_counter()
        resp = None
        for _ in range(4):  # adapt to models that reject a parameter (a rejected call is not billed)
            try:
                resp = self._client.chat.completions.create(**kwargs)
                break
            except BadRequestError as exc:
                text = str(exc).lower()
                if "response_format" in kwargs and ("response_format" in text or "json" in text):
                    self._json_mode_unsupported.add(model)
                    kwargs.pop("response_format")
                elif "reasoning_effort" in kwargs and "reasoning" in text:
                    self._effort_unsupported.add(model)
                    kwargs.pop("reasoning_effort")
                elif "max_tokens" in kwargs and "max_tokens" in text:  # newer reasoning models
                    kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                elif "temperature" in kwargs and "temperature" in text:
                    kwargs.pop("temperature")
                else:
                    raise
            except APIStatusError as exc:
                if exc.status_code == 402:
                    raise MeshError("Mesh refused the call: balance is zero or the key's spend cap is reached (402).") from exc
                raise
        if resp is None:
            raise MeshError(f"{model} rejected the request parameters")
        usage = resp.usage
        record_usage(
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        choice = resp.choices[0]
        return choice.message.content or "", choice.finish_reason or ""

    def _complete_text(self, model: str, messages: list[dict], temperature: float, max_tokens: int,
                       reasoning_effort: str | None = None) -> str:
        """Like _complete, but survives "thinking" models (e.g. gemini-2.5-flash).

        Those spend hidden reasoning tokens inside max_tokens; with a tight cap they can stop
        with finish_reason="length" before writing any answer. In that case retry ONCE with a
        larger cap, and remember the model so later calls start with the larger cap.
        """
        extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
        if model in self._thinking_models:
            max_tokens = max(max_tokens, THINKING_MIN_TOKENS)
        text, finish = self._complete(model, messages, temperature, max_tokens, **extra)
        if finish == "length" and max_tokens < THINKING_MIN_TOKENS:
            # Cut off at the cap: an empty or half-written JSON reply is useless, so one retry with
            # a larger cap is cheaper than a repair round. Empty text = hidden reasoning used the cap.
            if not text.strip():
                self._thinking_models.add(model)
            log.info("%s hit its %s-token cap (%s); retrying with %s", model, max_tokens,
                     "no answer yet" if not text.strip() else "reply cut off", THINKING_MIN_TOKENS)
            text, finish = self._complete(model, messages, temperature, THINKING_MIN_TOKENS, **extra)
        if finish == "length" and not text.strip():
            log.warning("%s spent its whole %s-token cap on hidden reasoning and wrote no answer", model,
                        max(max_tokens, THINKING_MIN_TOKENS))
        return text

    def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 800,
        fallback_model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> T:
        """Return a validated `schema` instance produced by `model` via Mesh.

        The output format is described with a compact one-line shape (see schema_hint.py)
        instead of a full JSON Schema dump: same information, a fraction of the tokens.
        `fallback_model`: if `model` errors or stays invalid after its repair round, the same
        request is sent once to this model (never on a 402: no model can be paid for then).
        `reasoning_effort` ("minimal" / "low" / ...): sent to reasoning models so hidden thinking
        leaves room for the answer; dropped automatically for a model that rejects it.
        """
        try:
            return self._chat_json(model, system, user, schema, temperature, max_tokens, reasoning_effort)
        except (MeshError, APIStatusError) as exc:
            if not fallback_model or fallback_model == model or "402" in str(exc):
                raise
            log.warning("%s failed (%s); falling back to %s", model, str(exc)[:200], fallback_model)
            return self._chat_json(fallback_model, system, user, schema, temperature, max_tokens, reasoning_effort)

    def _chat_json(self, model: str, system: str, user: str, schema: type[T], temperature: float,
                   max_tokens: int, reasoning_effort: str | None = None) -> T:
        messages = [
            {"role": "system", "content": f"{system}\n\nReply with ONLY this JSON shape:\n{schema_hint(schema)}"},
            {"role": "user", "content": user},
        ]
        reply = self._complete_text(model, messages, temperature, max_tokens, reasoning_effort)
        if not reply.strip():  # nothing to repair (e.g. all tokens spent thinking); let the caller fall back
            raise MeshError(f"{model} returned an empty reply")
        try:
            return schema.model_validate(extract_json(reply))
        except (ValueError, ValidationError) as first_error:
            log.warning("invalid JSON from %s, asking for a repair: %s | reply starts: %r", model,
                        str(first_error)[:300], reply[:160])
            messages += [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": f"That reply was invalid: {first_error}. "
                    "Return only the corrected JSON object.",
                },
            ]
            repaired = self._complete_text(model, messages, temperature, max_tokens, reasoning_effort)
            try:
                return schema.model_validate(extract_json(repaired))
            except (ValueError, ValidationError) as second_error:
                raise MeshError(f"{model} did not return valid {schema.__name__}") from second_error

    # ------------------------------------------------------------- embeddings
    @retry(
        retry=retry_if_exception_type(TRANSIENT),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        model = model or get_settings().embedding_model
        started = time.perf_counter()
        resp = self._client.embeddings.create(model=model, input=texts)
        record_usage(
            model=model,
            prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
            completion_tokens=0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return [item.embedding for item in resp.data]


_mesh: MeshClient | None = None


def get_mesh() -> MeshClient:
    """Process-wide Mesh client. Tests replace it with `set_mesh(fake)`."""
    global _mesh
    if _mesh is None:
        s = get_settings()
        _mesh = MeshClient(api_key=s.mesh_api_key, base_url=s.mesh_base_url)
    return _mesh


def set_mesh(client) -> None:
    """Swap the client (used by tests and the offline demo). Pass None to reset."""
    global _mesh
    _mesh = client
