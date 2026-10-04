from __future__ import annotations

import json
import logging
from datetime import date
from typing import Callable

from utils.providers.base import BalanceProvider, ProviderAuthError, ProviderError

logger = logging.getLogger(__name__)

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


def _reason(code: str, exc: BaseException | None = None) -> str:
    return f"{code}: {type(exc).__name__}" if exc is not None else code


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

    counts = {"written": 0, "skipped": 0, "error": 0}
    notes: str | None = None

    def add_item(provider_name: str, outcome: str, **kwargs) -> None:
        counts[outcome] += 1
        try:
            db.add_sync_run_item(run_id, provider_name, outcome, **kwargs)
        except Exception as exc:
            logger.error(
                "Could not record sync item for run %s: %s", run_id, type(exc).__name__
            )

    def set_status(connection_id: str, status: str, last_error: str) -> None:
        try:
            db.update_provider_connection_status(connection_id, status, last_error)
        except Exception as exc:
            logger.error(
                "Could not update status of connection %s: %s",
                connection_id,
                type(exc).__name__,
            )

    try:
        connections = db.list_provider_connections(user_id)
        mappings = db.list_account_mappings(user_id)
        mapped_external = {
            (m["provider_connection_id"], m["external_account_id"]): m for m in mappings
        }
        seen_mapped: set[tuple[str, str]] = set()
        fetched_connections: dict[str, dict] = {}

        def sync_balance(provider_name: str, connection_id: str, balance) -> None:
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
                return

            seen_mapped.add(key)
            account_id = mapping["account_id"]
            try:
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
                    return

                previous = db.get_account_value(account_id, date_str)
                db.save_account_value(account_id, date_str, gbp)
            except Exception as exc:
                logger.error(
                    "Failed to convert or write balance for account %s: %s",
                    account_id,
                    type(exc).__name__,
                )
                add_item(
                    provider_name,
                    "error",
                    account_id=account_id,
                    external_account_id=balance.external_account_id,
                    reason=_reason("write_failed", exc),
                    external_amount=amount,
                    external_currency=balance.currency,
                )
                return

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

        def sync_connection(connection: dict) -> None:
            connection_id = connection["id"]
            provider_name = connection.get("provider", "")

            provider = providers.get(provider_name)
            if provider is None:
                add_item(
                    provider_name, "error", reason=f"unknown_provider:{provider_name}"
                )
                return

            try:
                connection = dict(connection)
                connection["credentials"] = json.loads(
                    decrypt(connection["credentials_encrypted"])
                )
            except Exception as exc:
                logger.error(
                    "Could not decrypt credentials for connection %s: %s",
                    connection_id,
                    type(exc).__name__,
                )
                reason = _reason("decrypt_failed", exc)
                set_status(connection_id, "error", reason)
                add_item(provider_name, "error", reason=reason)
                return

            try:
                balances = provider.list_balances(connection)
            except ProviderAuthError as exc:
                reason = _reason("provider_auth_error", exc)
                set_status(connection_id, "needs_reauth", reason)
                add_item(provider_name, "error", reason=reason)
                return
            except ProviderError as exc:
                reason = _reason("provider_error", exc)
                set_status(connection_id, "error", reason)
                add_item(provider_name, "error", reason=reason)
                return
            except Exception as exc:
                logger.error(
                    "Unexpected failure fetching connection %s: %s",
                    connection_id,
                    type(exc).__name__,
                )
                reason = _reason("unexpected_provider_error", exc)
                set_status(connection_id, "error", reason)
                add_item(provider_name, "error", reason=reason)
                return

            fetched_connections[connection_id] = connection

            for balance in balances:
                try:
                    sync_balance(provider_name, connection_id, balance)
                except Exception as exc:
                    logger.error(
                        "Unexpected failure syncing a balance of connection %s: %s",
                        connection_id,
                        type(exc).__name__,
                    )
                    add_item(
                        provider_name,
                        "error",
                        external_account_id=getattr(balance, "external_account_id", None),
                        reason=_reason("write_failed", exc),
                    )

            try:
                db.touch_provider_connection_synced(connection_id)
            except Exception as exc:
                logger.error(
                    "Could not mark connection %s synced: %s",
                    connection_id,
                    type(exc).__name__,
                )

        for connection in connections:
            if connection.get("status") != "active":
                continue
            try:
                sync_connection(connection)
            except Exception as exc:
                logger.error(
                    "Unexpected failure syncing connection %s: %s",
                    connection.get("id"),
                    type(exc).__name__,
                )
                fetched_connections.pop(connection.get("id"), None)
                add_item(
                    connection.get("provider", ""),
                    "error",
                    reason=_reason("unexpected_provider_error", exc),
                )

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
    except Exception as exc:
        logger.error("Sync run %s aborted: %s", run_id, type(exc).__name__)
        counts["error"] += 1
        notes = _reason("run_aborted", exc)
    finally:
        if counts["error"] and counts["written"]:
            status = "partial"
        elif counts["error"]:
            status = "failed"
        else:
            status = "success"

        result = db.finalize_sync_run(
            run_id,
            status,
            counts["written"],
            counts["skipped"],
            counts["error"],
            notes,
        )
    return result
