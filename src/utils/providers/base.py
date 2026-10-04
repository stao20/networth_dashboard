from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


class ProviderError(Exception):
    """Non-auth provider failure."""


class ProviderAuthError(ProviderError):
    """Credentials invalid or consent expired."""


class ProviderTransientError(ProviderError):
    """Timeout, rate limit or server error; retrying later may succeed."""


TRANSIENT_STATUS_CODES = frozenset({408, 425, 429})


def is_transient_status(status_code: int) -> bool:
    return status_code in TRANSIENT_STATUS_CODES or status_code >= 500


@dataclass(frozen=True)
class NormalizedBalance:
    external_account_id: str
    name: str
    currency: str
    amount: Decimal
    raw: dict[str, Any] | None = None


class BalanceProvider(Protocol):
    provider_name: str

    def list_balances(self, connection: dict) -> list[NormalizedBalance]:
        """Fetch current balances for a provider_connections row (decrypted creds attached)."""
        ...
