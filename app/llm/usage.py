"""Token and cost accounting per graph node and per run.

`traced` (app/graph/tracing.py) opens a `UsageCollector` around each node. The Mesh
client calls `record_usage`, which prices the call with live Mesh prices and appends it
to the collector of the current context. Run totals are enforced against RUN_BUDGET_USD
(and RUN_TOKEN_BUDGET as a fallback when prices are unavailable).
"""

from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class UsageCollector:
    calls: list[dict] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(c["prompt_tokens"] + c["completion_tokens"] for c in self.calls)

    @property
    def prompt_tokens(self) -> int:
        return sum(c["prompt_tokens"] for c in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c["completion_tokens"] for c in self.calls)

    @property
    def cost_usd(self) -> float:
        return sum(c["cost_usd"] for c in self.calls)

    @property
    def models(self) -> list[str]:
        return sorted({c["model"] for c in self.calls})


_current: ContextVar[UsageCollector | None] = ContextVar("usage_collector", default=None)

# run_id -> {"tokens": int, "cost_usd": float} (shared across threads of one run)
_run_totals: dict[str, dict] = {}
_lock = threading.Lock()


def start_collecting() -> tuple[UsageCollector, object]:
    collector = UsageCollector()
    token = _current.set(collector)
    return collector, token


def stop_collecting(token) -> None:
    _current.reset(token)


def record_usage(*, model: str, prompt_tokens: int, completion_tokens: int, latency_ms: int) -> None:
    from app.llm.billing import cost_usd

    collector = _current.get()
    if collector is not None:
        collector.calls.append(
            {
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost_usd(model, prompt_tokens, completion_tokens),
                "latency_ms": latency_ms,
            }
        )


def add_run_usage(run_id: str, tokens: int, cost: float, token_budget: int, usd_budget: float) -> dict:
    """Add a node's usage to the run; raise BudgetExceeded once a budget is crossed."""
    with _lock:
        totals = _run_totals.setdefault(run_id, {"tokens": 0, "cost_usd": 0.0})
        totals["tokens"] += tokens
        totals["cost_usd"] += cost
        snapshot = dict(totals)
    if usd_budget and snapshot["cost_usd"] > usd_budget:
        raise BudgetExceeded(f"run cost ${snapshot['cost_usd']:.4f} passed RUN_BUDGET_USD ${usd_budget:.2f}")
    if token_budget and snapshot["tokens"] > token_budget:
        raise BudgetExceeded(f"run used {snapshot['tokens']} tokens (RUN_TOKEN_BUDGET {token_budget})")
    return snapshot


def run_usage(run_id: str) -> dict:
    with _lock:
        return dict(_run_totals.get(run_id, {"tokens": 0, "cost_usd": 0.0}))
