from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

import requests

from utils.providers.base import (
    NormalizedBalance,
    ProviderAuthError,
    ProviderError,
    ProviderTransientError,
    is_transient_status,
)

DEFAULT_BASE = "https://bankaccountdata.gocardless.com/api/v2"

# Net worth wants what the account actually holds, so settled ("booked") balances win,
# then "expected" (booked plus pending), and only then "available" balances, which can
# include overdraft headroom. closingBooked comes first because the scheduled job runs
# just after month end, when it is the balance at the end of the as-of day. Entries with
# creditLimitIncluded=true are ignored entirely: they add the credit limit to the balance.
_BALANCE_TYPE_PREFERENCE = (
    "closingBooked",
    "interimBooked",
    "expected",
    "openingBooked",
    "interimAvailable",
    "forwardAvailable",
)

# Refresh slightly before the stored expiry so a token cannot lapse mid-sync.
_TOKEN_EXPIRY_MARGIN_SECONDS = 300


class OpenBankingProvider:
    provider_name = "open_banking"

    def list_balances(self, connection: dict) -> list[NormalizedBalance]:
        creds = connection["credentials"]
        access_token = creds["access_token"]
        requisition_id = creds["requisition_id"]
        base = creds.get("base_url", DEFAULT_BASE).rstrip("/")
        headers = _bearer_headers(access_token)

        req_data = _get_json(
            f"{base}/requisitions/{requisition_id}/",
            headers=headers,
            auth_label="GoCardless",
        )
        account_ids = req_data.get("accounts") or []
        results: list[NormalizedBalance] = []

        for account_id in account_ids:
            details = _get_json(
                f"{base}/accounts/{account_id}/details/",
                headers=headers,
                auth_label="GoCardless",
            )
            balances_payload = _get_json(
                f"{base}/accounts/{account_id}/balances/",
                headers=headers,
                auth_label="GoCardless",
            )
            balance_entry = _pick_balance(balances_payload)
            amount_info = balance_entry.get("balanceAmount") or {}
            currency = amount_info.get("currency") or _account_currency(details) or "GBP"
            amount = Decimal(str(amount_info.get("amount", "0")))
            name = _account_display_name(details, str(account_id))
            results.append(
                NormalizedBalance(
                    external_account_id=str(account_id),
                    name=name,
                    currency=currency,
                    amount=amount,
                    raw={
                        "details": details,
                        "balances": balances_payload,
                        "selected_balance": balance_entry,
                    },
                )
            )
        return results


def create_requisition(
    secret_id: str,
    secret_key: str,
    institution_id: str,
    redirect_url: str,
    reference: str,
    *,
    base_url: str = DEFAULT_BASE,
) -> dict[str, Any]:
    """Create a bank link requisition; returns link and requisition id for the UI."""
    base = base_url.rstrip("/")
    token_data = exchange_token(secret_id, secret_key, base_url=base)
    access = token_data["access"]
    headers = _bearer_headers(access)
    payload = {
        "redirect": redirect_url,
        "institution_id": institution_id,
        "reference": reference,
    }
    data = _post_json(f"{base}/requisitions/", headers=headers, json=payload, auth_label="GoCardless")
    return {
        "link": data.get("link"),
        "requisition_id": data.get("id"),
        "raw": data,
    }


def exchange_token(
    secret_id: str,
    secret_key: str,
    *,
    base_url: str = DEFAULT_BASE,
) -> dict[str, Any]:
    """Exchange app secret credentials for access and refresh tokens."""
    base = base_url.rstrip("/")
    return _post_json(
        f"{base}/token/new/",
        json={"secret_id": secret_id, "secret_key": secret_key},
        auth_label="GoCardless",
    )


def refresh_access_token(
    refresh_token: str,
    *,
    base_url: str = DEFAULT_BASE,
) -> dict[str, Any]:
    """Exchange a refresh token for a new access token."""
    base = base_url.rstrip("/")
    return _post_json(
        f"{base}/token/refresh/",
        json={"refresh": refresh_token},
        auth_label="GoCardless",
    )


def apply_tokens(
    credentials: dict[str, Any],
    tokens: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Merge a GoCardless token response into stored credentials (returns a new dict)."""
    now_ts = time.time() if now is None else now
    updated = dict(credentials)
    updated["access_token"] = tokens["access"]
    if tokens.get("access_expires") is not None:
        updated["access_expires_at"] = int(now_ts + int(tokens["access_expires"]))
    else:
        updated.pop("access_expires_at", None)
    if tokens.get("refresh"):
        updated["refresh_token"] = tokens["refresh"]
        if tokens.get("refresh_expires") is not None:
            updated["refresh_expires_at"] = int(now_ts + int(tokens["refresh_expires"]))
        else:
            updated.pop("refresh_expires_at", None)
    return updated


def ensure_access_token(
    credentials: dict[str, Any],
    secret_id: str | None = None,
    secret_key: str | None = None,
    *,
    force: bool = False,
    now: float | None = None,
) -> dict[str, Any]:
    """Return credentials holding a usable access token, refreshing when needed.

    Refreshes when ``force`` is set, the access token is missing, or its stored expiry
    has passed. Tries the stored refresh token first, then (if app secrets are given)
    requests a brand-new token pair. Never mutates ``credentials``; callers persist the
    result when it differs from the input.

    Raises ProviderTransientError when every attempt failed transiently, otherwise
    ProviderAuthError (the user must reconnect).
    """
    now_ts = time.time() if now is None else now
    access = credentials.get("access_token")
    access_expires_at = credentials.get("access_expires_at")
    if (
        not force
        and access
        and (
            access_expires_at is None
            or now_ts < float(access_expires_at) - _TOKEN_EXPIRY_MARGIN_SECONDS
        )
    ):
        return dict(credentials)

    base_kwargs = {"base_url": credentials["base_url"]} if credentials.get("base_url") else {}
    failures: list[ProviderError] = []

    refresh = credentials.get("refresh_token")
    refresh_expires_at = credentials.get("refresh_expires_at")
    refresh_usable = bool(refresh) and (
        refresh_expires_at is None
        or now_ts < float(refresh_expires_at) - _TOKEN_EXPIRY_MARGIN_SECONDS
    )
    if refresh_usable:
        try:
            tokens = refresh_access_token(refresh, **base_kwargs)
            if tokens.get("access"):
                return apply_tokens(credentials, tokens, now=now_ts)
            failures.append(ProviderAuthError("GoCardless refresh returned no access token"))
        except ProviderError as e:
            failures.append(e)

    if secret_id and secret_key:
        try:
            tokens = exchange_token(secret_id, secret_key, **base_kwargs)
            if tokens.get("access"):
                return apply_tokens(credentials, tokens, now=now_ts)
            failures.append(ProviderAuthError("GoCardless returned no access token"))
        except ProviderError as e:
            failures.append(e)

    if failures and all(isinstance(f, ProviderTransientError) for f in failures):
        raise ProviderTransientError("GoCardless token refresh failed temporarily")
    raise ProviderAuthError("GoCardless token refresh failed; reconnect required")


def _bearer_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _pick_balance(balances_payload: dict[str, Any]) -> dict[str, Any]:
    balances = [
        entry
        for entry in balances_payload.get("balances") or []
        if entry.get("creditLimitIncluded") is not True
    ]
    for preferred in _BALANCE_TYPE_PREFERENCE:
        for entry in balances:
            if entry.get("balanceType") == preferred:
                return entry
    if balances:
        return balances[0]
    raise ProviderError("GoCardless returned no usable balances")


def _account_currency(details: dict[str, Any]) -> str | None:
    account = details.get("account") or {}
    return account.get("currency")


def _account_display_name(details: dict[str, Any], account_id: str) -> str:
    account = details.get("account") or {}
    name = account.get("name")
    if name:
        return str(name)
    iban = str(account.get("iban") or "")
    if len(iban) >= 4:
        return iban[-4:]
    return iban or account_id


def _get_json(url: str, *, headers: dict[str, str], auth_label: str) -> dict[str, Any]:
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except (requests.Timeout, requests.ConnectionError) as e:
        raise ProviderTransientError(f"{auth_label} request failed: {e}") from e
    except requests.RequestException as e:
        raise ProviderError(f"{auth_label} request failed: {e}") from e
    return _parse_response(resp, auth_label)


def _post_json(
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str] | None = None,
    auth_label: str,
) -> dict[str, Any]:
    hdrs = {"Accept": "application/json", **(headers or {})}
    try:
        resp = requests.post(url, headers=hdrs, json=json, timeout=30)
    except (requests.Timeout, requests.ConnectionError) as e:
        raise ProviderTransientError(f"{auth_label} request failed: {e}") from e
    except requests.RequestException as e:
        raise ProviderError(f"{auth_label} request failed: {e}") from e
    return _parse_response(resp, auth_label)


def _parse_response(resp: requests.Response, auth_label: str) -> dict[str, Any]:
    if resp.status_code in (401, 403):
        raise ProviderAuthError(f"{auth_label} credentials rejected or consent expired")
    if is_transient_status(resp.status_code):
        raise ProviderTransientError(f"{auth_label} HTTP {resp.status_code}")
    if resp.status_code not in (200, 201):
        raise ProviderError(f"{auth_label} HTTP {resp.status_code}")
    return resp.json()
