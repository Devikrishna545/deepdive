"""Spend guards for public hosting: access code and daily run cap (see config: RUN_ACCESS_CODE,
MAX_RUNS_PER_DAY). Both are off by default, so local use is unchanged."""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException

from app.config import get_settings
from app.db import repository as repo

ACCESS_HEADER = "X-Access-Code"


def require_access_code(x_access_code: str | None = Header(default=None)) -> None:
    """401 when an access code is configured and the request does not carry it."""
    code = get_settings().run_access_code
    if code and not hmac.compare_digest((x_access_code or "").encode(), code.encode()):
        raise HTTPException(status_code=401, detail="This demo needs a valid access code to start research. Check the code and try again.")


def require_daily_capacity() -> None:
    """429 when MAX_RUNS_PER_DAY runs were started in the last 24 hours."""
    cap = get_settings().max_runs_per_day
    if cap > 0 and repo.count_runs_since(datetime.now(timezone.utc) - timedelta(hours=24)) >= cap:
        raise HTTPException(status_code=429, detail=f"This demo has reached its limit of {cap} research runs per 24 hours. Please try again later.")
