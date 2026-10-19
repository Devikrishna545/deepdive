"""HTML pages. The pages are thin shells; static/js/*.js fetches data from /api."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.db import repository as repo
from app.routes.deps import get_run_or_404, templates

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"runs": repo.list_runs(limit=10)})


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: str):
    run = get_run_or_404(run_id)
    return templates.TemplateResponse(request, "run.html", {"run": run})


STATIC = Path(__file__).resolve().parent.parent / "static"


@router.get("/manifest.webmanifest")
def manifest():
    """Installable app (PWA) manifest."""
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/sw.js")
def service_worker():
    """Served from the root so it may cache the app shell for every page; it never caches /api."""
    return FileResponse(STATIC / "js" / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})
