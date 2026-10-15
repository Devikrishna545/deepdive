"""Shared route helpers."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.templating import Jinja2Templates

from app import BASE_DIR
from app.config import get_settings
from app.db import repository as repo
from app.db.models import Run

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["settings"] = get_settings  # templates read settings().dev_mode


def get_run_or_404(run_id: str) -> Run:
    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run
