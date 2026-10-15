"""Developer view of token use: input/output tokens, calls and cost per AGENT, per step and per run.

Built from the audit trail (`events`), which `traced` fills for every graph node with the
prompt/completion split and the individual Mesh calls. Nothing here calls a model.
"""

from __future__ import annotations

import json

from app.db import repository as repo

# Graph node -> the agent that spends tokens in it. Ordered as the pipeline runs.
AGENT_OF_NODE = {
    "plan": "planner",
    "gap_plan": "planner",
    "research": "researcher",
    "draft": "drafter",
    "verify": "verifier",
    "cross_check": "verifier",  # contradiction pairs use the verifier model (+ embeddings)
    "synthesize": "synthesizer",
}
AGENTS = ["planner", "researcher", "drafter", "verifier", "synthesizer"]


def _empty(name: str) -> dict:
    return {"agent": name, "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "cost_usd": 0.0, "models": [], "max_prompt_tokens_per_call": 0}


def run_usage_breakdown(run_id: str) -> dict:
    """Per-agent and per-step token use for one run (works while the run is still going)."""
    agents = {name: _empty(name) for name in AGENTS}
    steps = []
    for ev in repo.list_events(run_id):
        if ev.phase not in ("end", "error"):
            continue
        node = ev.node.split(":")[0]
        agent = AGENT_OF_NODE.get(node)
        calls = json.loads(ev.calls_json or "[]")
        if agent is None or not (ev.tokens or calls):
            continue
        a = agents[agent]
        a["calls"] += len(calls)
        a["prompt_tokens"] += ev.prompt_tokens
        a["completion_tokens"] += ev.completion_tokens
        a["total_tokens"] += ev.prompt_tokens + ev.completion_tokens
        a["cost_usd"] += ev.cost_usd
        a["models"] = sorted(set(a["models"]) | {c["model"] for c in calls})
        a["max_prompt_tokens_per_call"] = max([a["max_prompt_tokens_per_call"]] + [c["prompt_tokens"] for c in calls])
        steps.append({
            "node": ev.node, "agent": agent, "calls": len(calls),
            "prompt_tokens": ev.prompt_tokens, "completion_tokens": ev.completion_tokens,
            "cost_usd": ev.cost_usd, "latency_ms": ev.latency_ms, "summary": ev.summary,
        })
    rows = list(agents.values())
    for a in rows:
        a["cost_usd"] = round(a["cost_usd"], 6)
        a["avg_prompt_tokens_per_call"] = round(a["prompt_tokens"] / a["calls"]) if a["calls"] else 0
    totals = {k: sum(a[k] for a in rows) for k in ("calls", "prompt_tokens", "completion_tokens", "total_tokens")}
    totals["cost_usd"] = round(sum(a["cost_usd"] for a in rows), 6)
    return {"run_id": run_id, "agents": rows, "steps": steps, "totals": totals}


def recent_usage(limit: int = 15) -> dict:
    """Per-agent token use for the most recent runs, plus the average per finished run."""
    runs = []
    for run in repo.list_runs(limit):
        b = run_usage_breakdown(run.id)
        runs.append({"run_id": run.id, "question": run.question, "depth": run.depth, "status": run.status,
                     "created_at": run.created_at, "agents": b["agents"], "totals": b["totals"]})
    done = [r for r in runs if r["status"] == "done"]
    average = []
    for name in AGENTS:
        rows = [next(a for a in r["agents"] if a["agent"] == name) for r in done]
        n = len(rows) or 1
        average.append({
            "agent": name,
            "calls": round(sum(a["calls"] for a in rows) / n, 1),
            "prompt_tokens": round(sum(a["prompt_tokens"] for a in rows) / n),
            "completion_tokens": round(sum(a["completion_tokens"] for a in rows) / n),
            "cost_usd": round(sum(a["cost_usd"] for a in rows) / n, 6),
        })
    return {"runs": runs, "average_per_done_run": average, "done_runs": len(done)}
