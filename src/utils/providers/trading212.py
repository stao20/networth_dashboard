from __future__ import annotations

import base64
from decimal import Decimal

import requests

from utils.providers.base import NormalizedBalance, ProviderAuthError, ProviderError

DEFAULT_BASE = "https://live.trading212.com/api/v0"


class Trading212Provider:
    provider_name = "trading212"

    def list_balances(self, connection: dict) -> list[NormalizedBalance]:
        creds = connection["credentials"]
        api_key = creds["api_key"]
        api_secret = creds["api_secret"]
        base = creds.get("base_url", DEFAULT_BASE).rstrip("/")
        token = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        url = f"{base}/equity/account/summary"
        try:
            resp = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as e:
            raise ProviderError(f"Trading 212 request failed: {e}") from e

        if resp.status_code in (401, 403):
            raise ProviderAuthError("Trading 212 credentials rejected")
        if resp.status_code != 200:
            raise ProviderError(f"Trading 212 HTTP {resp.status_code}")

        data = resp.json()
        account_id = str(data["id"])
        currency = data.get("currency") or "GBP"
        amount = Decimal(str(data["totalValue"]))
        return [
            NormalizedBalance(
                external_account_id=account_id,
                name=f"Trading 212 ({account_id})",
                currency=currency,
                amount=amount,
                raw=data,
            )
        ]
