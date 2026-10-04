from __future__ import annotations

import json
import logging
from datetime import date
from typing import Callable

from utils.providers.base import BalanceProvider, ProviderAuthError, ProviderError

ConvertToGbp = Callable[[float, str], "float | None"]
DecryptCredentials = Callable[[str], str]


def default_providers() -> dict[str, BalanceProvider]:
    from utils.providers.open_banking import OpenBankingProvider
    from utils.providers.trading212 import Trading212Provider

    return {
        "trading212": Trading212Provider(),
        "open_banking": OpenBankingProvider(),
    }


def _default_convert_to_gbp(amount: float, currency: str) -> float | None:
    from utils.currency import convert_currency

    return convert_currency(amount, currency, "GBP")


def _default_decrypt(token: str) -> str:
    from utils.crypto import decrypt_secret

    return decrypt_secret(token)


def run_sync(
    db,
    user_id: str,
    as_of_date: date,
    trigger: str,
    *,
    providers: dict[str, BalanceProvider] | None = None,
    convert_to_gbp: ConvertToGbp | None = None,
    decrypt_credentials: DecryptCredentials | None = None,
) -> dict:
    providers = providers if providers is not None else default_providers()
    convert = convert_to_gbp or _default_convert_to_gbp
    decrypt = decrypt_credentials or _default_decrypt
    date_str = as_of_date.isoformat()

    run = db.create_sync_run(user_id, trigger, as_of_date)
    run_id = run["id"]

    connections = db.list_provider_connections(user_id)
    mappings = db.list_account_mappings(user_id)
    mapped_external = {
        (m["provider_connection_id"], m["external_account_id"]): m for m in mappings
    }
    seen_mapped: set[tuple[str, str]] = set()
    fetched_connections: dict[str, dict] = {}

    counts = {"written": 0, "skipped": 0, "error": 0}

    def add_item(provider_name: str, outcome: str, **kwargs) -> None:
        counts[outcome] += 1
        db.add_sync_run_item(run_id, provider_name, outcome, **kwargs)

    for connection in connections:
        if connection.get("status") != "active":
            continue
        connection_id = connection["id"]
        provider_name = connection.get("provider", "")

        provider = providers.get(provider_name)
        if provider is None:
            add_item(provider_name, "error", reason=f"unknown_provider:{provider_name}")
            continue

        try:
            connection = dict(connection)
            connection["credentials"] = json.loads(
                decrypt(connection["credentials_encrypted"])
            )
        except Exception:
            logging.exception("Could not decrypt credentials for %s", connection_id)
            db.update_provider_connection_status(
                connection_id, "error", "credentials could not be decrypted"
            )
            add_item(provider_name, "error", reason="credentials_decrypt_failed")
            continue

        try:
            balances = provider.list_balances(connection)
        except ProviderAuthError as exc:
            db.update_provider_connection_status(connection_id, "needs_reauth", str(exc))
            add_item(provider_name, "error", reason=f"auth_error: {exc}")
            continue
        except ProviderError as exc:
            db.update_provider_connection_status(connection_id, "error", str(exc))
            add_item(provider_name, "error", reason=f"provider_error: {exc}")
            continue
        except Exception as exc:
            logging.exception("Unexpected failure fetching %s", connection_id)
            db.update_provider_connection_status(connection_id, "error", str(exc))
            add_item(provider_name, "error", reason=f"provider_error: {exc}")
            continue

        fetched_connections[connection_id] = connection

        for balance in balances:
            key = (connection_id, balance.external_account_id)
            mapping = mapped_external.get(key)
            amount = float(balance.amount)

            if mapping is None:
                add_item(
                    provider_name,
                    "skipped",
                    external_account_id=balance.external_account_id,
                    reason="unmapped",
                    external_amount=amount,
                    external_currency=balance.currency,
                )
                continue

            seen_mapped.add(key)
            account_id = mapping["account_id"]

            gbp = convert(amount, balance.currency)
            if gbp is None:
                add_item(
                    provider_name,
                    "error",
                    account_id=account_id,
                    external_account_id=balance.external_account_id,
                    reason="conversion_failed",
                    external_amount=amount,
                    external_currency=balance.currency,
                )
                continue

            previous = db.get_account_value(account_id, date_str)
            db.save_account_value(account_id, date_str, gbp)
            add_item(
                provider_name,
                "written",
                account_id=account_id,
                external_account_id=balance.external_account_id,
                external_amount=amount,
                external_currency=balance.currency,
                previous_value_gbp=previous,
                new_value_gbp=gbp,
                had_previous=previous is not None,
            )

        db.touch_provider_connection_synced(connection_id)

    for key, mapping in mapped_external.items():
        connection = fetched_connections.get(key[0])
        if connection is None or key in seen_mapped:
            continue
        add_item(
            connection.get("provider", ""),
            "skipped",
            account_id=mapping["account_id"],
            external_account_id=key[1],
            reason="not_returned",
        )

    if counts["error"] and counts["written"]:
        status = "partial"
    elif counts["error"]:
        status = "failed"
    else:
        status = "success"

    return db.finalize_sync_run(
        run_id,
        status,
        counts["written"],
        counts["skipped"],
        counts["error"],
    )
