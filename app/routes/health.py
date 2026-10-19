"""Health check. Reports whether config is present, never the values."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.llm.billing import balance_status

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    s = get_settings()
    bal = balance_status()
    return {
        "status": "ok",
        "balance": {
            "available_usd": bal.available_usd,
            "level": bal.level,
            "message": bal.message,
            "alert_below_usd": s.low_balance_alert_usd,
            "runs_blocked_below_usd": s.min_balance_stop_usd,
        },
        "run_budget_usd": s.run_budget_usd,
        "mesh_key_configured": s.mesh_api_key.startswith("rsk_"),
        "mesh_base_url": s.mesh_base_url,
        "search_provider": "tavily" if s.tavily_api_key else "duckduckgo",
        "verify_enabled": s.verify_enabled,
        "access_code_required": bool(s.run_access_code),
        "max_runs_per_day": s.max_runs_per_day,
        "models": {
            "planner": s.model_planner,
            "researcher": s.model_researcher,
            "drafter": s.model_drafter,
            "verifier": s.model_verifier,
            "synthesizer": s.model_synthesizer,
        },
    }
