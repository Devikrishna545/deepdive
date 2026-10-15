"""`traced`: wraps every graph node to write the audit trail and enforce the token budget.

A node may include a private `_trail` key in its returned update:
    {"_trail": {"summary": "one line for the UI", "payload": {...details...}}}
`traced` removes it from the state update and stores it in the `events` table together
with latency, tokens, USD cost and the models used. Errors are recorded and re-raised.
The run stops (BudgetExceeded) once RUN_BUDGET_USD or RUN_TOKEN_BUDGET is crossed.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable

from app.config import get_settings
from app.db import repository as repo
from app.llm.usage import add_run_usage, start_collecting, stop_collecting

log = logging.getLogger("deepdive.trace")


def traced(node_name: str) -> Callable:
    def decorator(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        @functools.wraps(fn)
        def wrapper(state: dict) -> dict:
            run_id = state.get("run_id", "unknown")
            label = node_name
            if node_name == "research" and state.get("sub_question") is not None:
                label = f"research:{state['sub_question'].id}"
            repo.add_event(run_id, label, "start", summary=f"{node_name} started")
            collector, token = start_collecting()
            started = time.perf_counter()
            try:
                update = fn(state) or {}
            except Exception as exc:
                repo.add_event(
                    run_id,
                    label,
                    "error",
                    summary=f"{type(exc).__name__}: {exc}",
                    tokens=collector.tokens,
                    prompt_tokens=collector.prompt_tokens,
                    completion_tokens=collector.completion_tokens,
                    calls=collector.calls,
                    cost_usd=collector.cost_usd,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    models=collector.models,
                )
                raise
            finally:
                stop_collecting(token)
            trail = update.pop("_trail", {})
            latency = int((time.perf_counter() - started) * 1000)
            repo.add_event(
                run_id,
                label,
                "end",
                summary=trail.get("summary", f"{node_name} finished"),
                payload=trail.get("payload"),
                tokens=collector.tokens,
                prompt_tokens=collector.prompt_tokens,
                completion_tokens=collector.completion_tokens,
                calls=collector.calls,
                cost_usd=collector.cost_usd,
                latency_ms=latency,
                models=collector.models,
            )
            log.info(
                "node=%s run=%s tokens=%s cost_usd=%.5f latency_ms=%s",
                label, run_id, collector.tokens, collector.cost_usd, latency,
            )
            s = get_settings()
            add_run_usage(run_id, collector.tokens, collector.cost_usd, s.run_token_budget, s.run_budget_usd)
            return update

        return wrapper

    return decorator
