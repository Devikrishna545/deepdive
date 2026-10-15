"""Developer-only views (DEV_MODE=true): token use per agent while testing.

GET /dev/usage                 page: per-agent input/output tokens across recent runs
GET /api/dev/usage             JSON for that page
GET /api/runs/{id}/usage       JSON: per-agent and per-step breakdown of one run (run page tab)
All return 404 when DEV_MODE=false, so the demo shows none of it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.routes.deps import get_run_or_404, templates
from app.services.usage_service import recent_usage, run_usage_breakdown

router = APIRouter(tags=["dev"])


def _require_dev() -> None:
    if not get_settings().dev_mode:
        raise HTTPException(status_code=404, detail="not found")


@router.get("/dev/usage", response_class=HTMLResponse, include_in_schema=False)
def usage_page(request: Request):
    _require_dev()
    return templates.TemplateResponse(request, "dev_usage.html", {})


@router.get("/api/dev/usage")
def usage_recent(limit: int = Query(15, ge=1, le=100)) -> dict:
    _require_dev()
    return recent_usage(limit)


@router.get("/api/runs/{run_id}/usage")
def usage_for_run(run_id: str) -> dict:
    _require_dev()
    get_run_or_404(run_id)
    return run_usage_breakdown(run_id)
