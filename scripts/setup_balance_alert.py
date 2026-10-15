"""Optional: register Mesh's own `balance.low` alert at $5, delivered to a webhook.

The app already warns you below LOW_BALANCE_ALERT_USD (UI banner, /api/health, logs, run
trail) and blocks runs below MIN_BALANCE_STOP_USD. This script adds Mesh's server-side alert,
which fires even when DeepDive is not running.

Mesh limits (Notifications docs): threshold alerts go to WEBHOOKS only (email recipients cannot
take threshold events yet), and creating them needs an ADMIN key (`mak_...`, permission
`alerts:write`), not your normal `rsk_` key. Put it in your shell, never in the repo:

    export MESH_ADMIN_KEY=mak_...
    python -m scripts.setup_balance_alert --webhook-url https://your-endpoint.example/mesh --threshold 5

The response includes a signing secret shown ONCE: store it in a password manager.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

API = "https://api.meshapi.ai"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook-url", required=True, help="public HTTPS endpoint that receives the alert")
    parser.add_argument("--threshold", type=float, default=5.0, help="alert when balance drops below this (USD)")
    args = parser.parse_args()
    admin_key = os.environ.get("MESH_ADMIN_KEY", "")
    if not admin_key.startswith("mak_"):
        print("Set MESH_ADMIN_KEY (an admin key starting with mak_) in your shell first.")
        return 1
    headers = {"Authorization": f"Bearer {admin_key}"}
    with httpx.Client(base_url=API, headers=headers, timeout=15) as client:
        channel = client.post("/alerts/channels", json={
            "channel_type": "webhook", "destination": args.webhook_url, "is_enabled": True})
        channel.raise_for_status()
        body = channel.json()
        policy = client.post("/alerts/policies", json={
            "channel_id": body["id"], "alert_type": "balance.low", "threshold_usd": args.threshold})
        policy.raise_for_status()
    print(f"balance.low alert created at ${args.threshold:.2f} -> {args.webhook_url}")
    if body.get("signing_secret"):
        print("Signing secret (shown once, store it safely):", body["signing_secret"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
