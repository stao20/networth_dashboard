#!/usr/bin/env python3
"""Smoke-test a real Trading 212 API key without touching prod Supabase.

Uses in-memory DemoHandler only. Writes never leave this process.

Required env:
  TRADING212_API_KEY
  TRADING212_API_SECRET

Optional:
  TRADING212_DEMO=1          # use demo.trading212.com (default: live)
  SYNC_CREDENTIALS_KEY       # Fernet key; generated for this run if unset

Example:
  TRADING212_API_KEY=... TRADING212_API_SECRET=... \\
    uv run python scripts/smoke_trading212_sync.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

# Repo layout: scripts/ -> src/ on PYTHONPATH
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    api_key = os.environ.get("TRADING212_API_KEY", "").strip()
    api_secret = os.environ.get("TRADING212_API_SECRET", "").strip()
    if not api_key or not api_secret:
        print(
            "Set TRADING212_API_KEY and TRADING212_API_SECRET "
            "(Cursor secrets or env). Do not commit them.",
            file=sys.stderr,
        )
        return 1

    if not os.environ.get("SYNC_CREDENTIALS_KEY"):
        from cryptography.fernet import Fernet

        os.environ["SYNC_CREDENTIALS_KEY"] = Fernet.generate_key().decode()
        print("Generated ephemeral SYNC_CREDENTIALS_KEY for this process")

    # Ensure DemoHandler does not pre-wire DEMO/DEMO credentials.
    os.environ.pop("DEMO_SYNC", None)

    from utils.crypto import encrypt_secret
    from utils.demo_db import DemoHandler
    from utils.providers.trading212 import (
        DEFAULT_BASE,
        Trading212Provider,
    )
    from utils.sync.orchestrator import run_sync

    use_demo = os.environ.get("TRADING212_DEMO", "").strip() in ("1", "true", "yes")
    base_url = (
        "https://demo.trading212.com/api/v0" if use_demo else DEFAULT_BASE
    )
    print(f"Calling Trading 212 at {base_url}")

    db = DemoHandler()
    user_id = "demo-sync-user"
    accounts = db.get_user_accounts(user_id)
    if not accounts:
        print("DemoHandler seed missing accounts", file=sys.stderr)
        return 1
    tracker_account = accounts[0]

    creds = {
        "api_key": api_key,
        "api_secret": api_secret,
        "base_url": base_url,
    }
    conn = db.upsert_provider_connection(
        user_id,
        "trading212",
        "default",
        encrypt_secret(json.dumps(creds)),
        display_name="Trading 212 smoke",
    )

    # Probe API before mapping/sync.
    probe = dict(conn)
    probe["credentials"] = creds
    try:
        balances = Trading212Provider().list_balances(probe)
    except Exception as exc:
        print(f"Trading 212 list_balances failed: {type(exc).__name__}: {exc}")
        return 2

    if not balances:
        print("Trading 212 returned no balances")
        return 3

    for b in balances:
        print(
            f"  balance id={b.external_account_id} name={b.name} "
            f"amount={b.amount} {b.currency}"
        )

    primary = balances[0]
    db.upsert_account_mapping(
        user_id,
        conn["id"],
        primary.external_account_id,
        primary.name,
        tracker_account["id"],
    )
    print(
        f"Mapped {primary.external_account_id} -> tracker "
        f"{tracker_account['name']} ({tracker_account['id']})"
    )

    as_of = date.today()
    result = run_sync(db, user_id, as_of, trigger="manual")
    print(
        "Sync result:",
        {
            "status": result.get("status"),
            "written_count": result.get("written_count"),
            "skipped_count": result.get("skipped_count"),
            "error_count": result.get("error_count"),
            "notes": result.get("notes"),
        },
    )
    for item in db.list_sync_run_items(result["id"]):
        print(
            "  item:",
            {
                "outcome": item.get("outcome"),
                "external_amount": item.get("external_amount"),
                "external_currency": item.get("external_currency"),
                "new_value_gbp": item.get("new_value_gbp"),
                "reason": item.get("reason"),
            },
        )

    ok = result.get("status") == "success" and int(result.get("written_count") or 0) >= 1
    print("PASS" if ok else "FAIL (no successful write)")
    print("Note: in-memory only — prod Supabase was not modified.")
    return 0 if ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
