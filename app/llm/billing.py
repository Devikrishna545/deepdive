"""Mesh account guards: live balance and live model prices.

- Balance: GET {MESH_BASE_URL}/balance (works with the normal rsk_ key). Checked before every
  run; below LOW_BALANCE_ALERT_USD we warn, below MIN_BALANCE_STOP_USD we refuse to start.
- Prices: GET {MESH_BASE_URL}/models (prompt/completion USD per 1M tokens), cached on disk for
  24 h, used to put a USD cost on every call, node and run.

These are account/metadata calls, not model calls, so they never spend credits.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

PRICE_CACHE = Path("data/mesh_prices.json")
PRICE_TTL_S = 24 * 3600
BALANCE_TTL_S = 60


class InsufficientBalance(RuntimeError):
    """Raised when the Mesh balance is below MIN_BALANCE_STOP_USD."""


@dataclass
class BalanceStatus:
    available_usd: float | None  # None = could not read (network/key problem)
    level: str  # ok | low | stop | unknown
    message: str


_balance_cache: tuple[float, BalanceStatus] | None = None


def _get(path: str, params: dict | None = None) -> dict:
    s = get_settings()
    resp = httpx.get(
        f"{s.mesh_base_url.rstrip('/')}/{path.lstrip('/')}",
        params=params,
        headers={"Authorization": f"Bearer {s.mesh_api_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_available_usd() -> float:
    data = _get("balance")
    return float(data.get("available_usd") or data.get("balance_usd") or 0)


def balance_status(force: bool = False) -> BalanceStatus:
    """Cached for 60 s. Never raises: an unreadable balance is reported as 'unknown'."""
    global _balance_cache
    now = time.monotonic()
    if not force and _balance_cache and now - _balance_cache[0] < BALANCE_TTL_S:
        return _balance_cache[1]
    s = get_settings()
    try:
        available = fetch_available_usd()
    except Exception as exc:
        status = BalanceStatus(None, "unknown", f"Could not read Mesh balance ({type(exc).__name__}).")
    else:
        if available < s.min_balance_stop_usd:
            status = BalanceStatus(available, "stop", f"Mesh balance ${available:.2f} is below the "
                                   f"${s.min_balance_stop_usd:.2f} floor. New runs are blocked; top up credits.")
        elif available < s.low_balance_alert_usd:
            status = BalanceStatus(available, "low", f"Low Mesh balance: ${available:.2f} left "
                                   f"(alert level ${s.low_balance_alert_usd:.2f}). Use quick runs.")
        else:
            status = BalanceStatus(available, "ok", f"Mesh balance ${available:.2f}.")
    if status.level in ("low", "stop"):
        log.warning(status.message)
    _balance_cache = (now, status)
    return status


def require_balance() -> BalanceStatus:
    """Gate for starting paid work. Raises InsufficientBalance below the floor."""
    status = balance_status(force=True)
    if status.level == "stop":
        raise InsufficientBalance(status.message)
    return status


# ------------------------------------------------------------------ prices
_prices: dict[str, tuple[float, float]] | None = None


def _parse_prices(models: list[dict]) -> dict[str, tuple[float, float]]:
    out = {}
    for m in models:
        pricing = m.get("discounted") or m.get("pricing") or m
        try:
            p_in = float(pricing.get("prompt_usd_per_1m") or 0)
            p_out = float(pricing.get("completion_usd_per_1m") or 0)
        except (TypeError, ValueError):
            continue
        if m.get("id"):
            out[m["id"]] = (p_in, p_out)
    return out


def load_prices(refresh: bool = False) -> dict[str, tuple[float, float]]:
    """model id -> (USD per 1M prompt tokens, USD per 1M completion tokens). Empty if unavailable."""
    global _prices
    if _prices is not None and not refresh:
        return _prices
    if not refresh and PRICE_CACHE.exists() and time.time() - PRICE_CACHE.stat().st_mtime < PRICE_TTL_S:
        _prices = {k: tuple(v) for k, v in json.loads(PRICE_CACHE.read_text()).items()}
        return _prices
    try:
        data = _get("models")
        models = data.get("data", data) if isinstance(data, dict) else data
        _prices = _parse_prices(models)
        PRICE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PRICE_CACHE.write_text(json.dumps(_prices))
    except Exception as exc:
        log.warning("model prices unavailable (%s); costs will show as 0 and the token budget applies", exc)
        _prices = {}
    return _prices


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p_in, p_out = load_prices().get(model, (0.0, 0.0))
    return (prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000


def reset_caches() -> None:
    """Tests use this to drop cached balance/prices."""
    global _balance_cache, _prices
    _balance_cache, _prices = None, None
