"""Month-end scheduled sync CLI (GitHub Actions / cron)."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from utils.db import SupabaseHandler
from utils.sync.dates import previous_month_end
from utils.sync.orchestrator import default_credential_refreshers, run_sync

logger = logging.getLogger(__name__)

_REQUIRED_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SYNC_CREDENTIALS_KEY")


def _run_is_clean(result: dict | None) -> bool:
    result = result or {}
    return result.get("status") == "success" and not result.get("error_count")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        return 1

    secret_id = os.environ.get("GOCARDLESS_SECRET_ID") or None
    secret_key = os.environ.get("GOCARDLESS_SECRET_KEY") or None
    if not (secret_id and secret_key):
        logger.info(
            "GOCARDLESS_SECRET_ID/GOCARDLESS_SECRET_KEY not set; Open Banking can only "
            "use stored refresh tokens"
        )
    refreshers = default_credential_refreshers(secret_id, secret_key)

    try:
        db = SupabaseHandler.from_env()
        user_ids = db.list_user_ids_for_scheduled_sync()
    except Exception as exc:
        logger.error("Could not load users to sync: %s", type(exc).__name__)
        return 1

    as_of = previous_month_end(datetime.now(timezone.utc).date())
    logger.info(
        "Month-end sync as_of=%s for %d user(s)", as_of.isoformat(), len(user_ids)
    )

    any_failed = False
    for user_id in user_ids:
        try:
            result = run_sync(
                db, user_id, as_of, trigger="scheduled", credential_refreshers=refreshers
            )
        except Exception as exc:
            any_failed = True
            logger.error("Sync crashed for user %s: %s", user_id, type(exc).__name__)
            continue
        result = result or {}
        if _run_is_clean(result):
            logger.info("Sync success for user %s", user_id)
        else:
            any_failed = True
            logger.error(
                "Sync %s for user %s (%s error(s))",
                result.get("status", "unknown"),
                user_id,
                result.get("error_count", "?"),
            )

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
