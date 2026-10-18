"""Show your Mesh balance, the live price of every configured model, and a rough cost per run.

    python -m scripts.mesh_account            # free: reads account data, makes no model calls
    python -m scripts.mesh_account --refresh  # re-download prices

Use it before changing models in .env: a model id missing from the price list does not exist
on your account (or has another name).
"""

from __future__ import annotations

import argparse

from dotenv import load_dotenv

from app.config import get_settings
from app.llm.billing import balance_status, cost_usd, load_prices

# Rough token use per call, measured from the prompt sizes in app/agents (input, output).
PER_CALL = {
    "planner": (450, 1200),  # reasoning model: ~300 visible + hidden thinking
    "researcher": (2200, 450),  # per sub-question
    "drafter": (700, 450),  # per sub-question
    "verifier": (550, 90),  # per claim that is not verbatim
    "synthesizer": (1600, 900),
}


def estimate(subquestions: int, claims_per_sq: int = 5, loop_share: float = 0.3) -> dict[str, float]:
    s = get_settings()
    rounds = 1 + loop_share  # some sub-questions loop back once
    plan = cost_usd(s.model_planner, *PER_CALL["planner"])
    research = subquestions * rounds * cost_usd(s.model_researcher, *PER_CALL["researcher"])
    draft = subquestions * rounds * cost_usd(s.model_drafter, *PER_CALL["drafter"])
    verify = subquestions * rounds * claims_per_sq * cost_usd(s.model_verifier, *PER_CALL["verifier"])
    synth = cost_usd(s.model_synthesizer, *PER_CALL["synthesizer"])
    return {"planner": plan, "researcher": research, "drafter": draft, "verifier": verify,
            "synthesizer": synth, "total": plan + research + draft + verify + synth}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    s = get_settings()

    status = balance_status(force=True)
    print(f"\nBalance: {status.message}")
    print(f"Alert below ${s.low_balance_alert_usd:.2f}; new runs blocked below ${s.min_balance_stop_usd:.2f}; "
          f"per-run cap ${s.run_budget_usd:.2f}\n")

    prices = load_prices(refresh=args.refresh)
    if not prices:
        print("Could not load prices from Mesh (check MESH_API_KEY / network).")
        return
    roles = {
        "planner": s.model_planner, "planner fallback": s.model_planner_fallback,
        "researcher": s.model_researcher, "drafter": s.model_drafter,
        "verifier": s.model_verifier, "synthesizer": s.model_synthesizer, "judge (eval)": s.model_judge,
        "embeddings": s.embedding_model,
    }
    print(f"{'role':16} {'model':40} {'$/1M in':>9} {'$/1M out':>9}")
    for role, model in roles.items():
        if model in prices:
            p_in, p_out = prices[model]
            print(f"{role:16} {model:40} {p_in:9.3f} {p_out:9.3f}")
        else:
            print(f"{role:16} {model:40} {'NOT FOUND on your account':>19}")

    for label, n in (("quick (3 sub-questions)", 3), (f"standard ({s.max_subquestions} sub-questions)", s.max_subquestions)):
        e = estimate(n)
        parts = ", ".join(f"{k} ${v:.4f}" for k, v in e.items() if k != "total")
        print(f"\nEstimated cost per {label}: ${e['total']:.4f}  ({parts})")
        if status.available_usd:
            print(f"  -> about {int(status.available_usd // max(e['total'], 1e-6))} runs with the current balance")
    print("\nEstimates assume ~5 claims per sub-question and 30% loop-backs; the run page shows real costs.")


if __name__ == "__main__":
    main()
