from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol


class ProviderError(Exception):
    """Non-auth provider failure."""


class ProviderAuthError(ProviderError):
    """Credentials invalid or consent expired."""


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
