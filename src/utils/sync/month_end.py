"""Month-end scheduled sync CLI (GitHub Actions / cron)."""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from utils.db import SupabaseHandler
from utils.sync.dates import previous_month_end
from utils.sync.orchestrator import run_sync

logger = logging.getLogger(__name__)

_REQUIRED_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SYNC_CREDENTIALS_KEY")
_OPTIONAL_ENV = ("GOCARDLESS_SECRET_ID", "GOCARDLESS_SECRET_KEY")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        return 1

    for name in _OPTIONAL_ENV:
        if os.environ.get(name):
            logger.debug("Using optional env %s", name)

    db = SupabaseHandler.from_env()
    as_of = previous_month_end(datetime.now(timezone.utc).date())
    user_ids = db.list_user_ids_with_active_connections()
    logger.info(
        "Month-end sync as_of=%s for %d user(s)", as_of.isoformat(), len(user_ids)
    )

    any_failed = False
    for user_id in user_ids:
        result = run_sync(db, user_id, as_of, trigger="scheduled")
        status = (result or {}).get("status", "failed")
        if status == "failed":
            any_failed = True
            logger.error("Sync failed for user %s", user_id)
        else:
            logger.info("Sync %s for user %s", status, user_id)

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
