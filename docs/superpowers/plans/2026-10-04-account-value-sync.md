# Account Value Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-pull UK Open Banking and Trading 212 balances into `account_values` via mapped accounts, with Sync now, end-of-month schedule, sync log, and undo.

**Architecture:** Modular `BalanceProvider` adapters feed a sync orchestrator that upserts GBP values and records `sync_runs` / `sync_run_items`. Streamlit owns connect/map/trigger/undo UI. Month-end runs as a Python CLI under GitHub Actions cron (fits the Python orchestrator; equivalent to the spec’s scheduled entrypoint).

**Tech Stack:** Python 3.13, Streamlit, Supabase (Postgres), `requests`, `cryptography` (Fernet), pytest, GitHub Actions cron.

**Spec:** [`docs/superpowers/specs/2026-10-04-account-value-sync-design.md`](../specs/2026-10-04-account-value-sync-design.md)

## Global Constraints

- v1 Open Banking vendor is **GoCardless Bank Account Data** only.
- Trading 212 uses public REST API Basic auth (`API_KEY:API_SECRET`); Invest / Stocks ISA only (API limitation).
- Synced values are stored in **GBP** via existing `convert_currency` (injectable in orchestrator for tests).
- Unmapped external accounts are **skipped** (never auto-create tracker accounts).
- Same `(account_id, date)` on sync **overwrites**; missing provider account → leave existing value, log `not_returned`.
- One tracker account maps to at most one external source (`account_mappings.account_id` unique).
- Credentials never logged; stored only in `credentials_encrypted`.
- Handlers scope by `user_id` (no new RLS work in v1).
- Manual Account Values form stays; sync is additive UI under that tab.

---

## File map

**Create:**
- `supabase/migrations/20261004000000_create_account_sync_tables.sql`
- `src/utils/crypto.py` — Fernet encrypt/decrypt for provider credentials
- `src/utils/providers/__init__.py`
- `src/utils/providers/base.py` — `NormalizedBalance`, errors, protocol
- `src/utils/providers/trading212.py`
- `src/utils/providers/open_banking.py`
- `src/utils/sync/__init__.py`
- `src/utils/sync/dates.py` — previous-month last day helper
- `src/utils/sync/orchestrator.py`
- `src/utils/sync/undo.py`
- `src/utils/sync/month_end.py` — CLI entry for scheduled sync
- `.github/workflows/month-end-sync.yml`
- `tests/fixtures/t212_account_summary.json`
- `tests/fixtures/gocardless_balances.json`
- `tests/fixtures/gocardless_account_details.json`
- `tests/test_crypto.py`
- `tests/test_provider_trading212.py`
- `tests/test_provider_open_banking.py`
- `tests/test_sync_dates.py`
- `tests/test_sync_db.py`
- `tests/test_sync_orchestrator.py`
- `tests/test_sync_undo.py`

**Modify:**
- `pyproject.toml` — add `cryptography`
- `src/utils/models.py` — sync-related dataclasses
- `src/utils/db.py` — connection/mapping/run/value helpers
- `src/pages/networth_tracker.py` — Connections & Sync panel under Account Values

---

### Task 1: Migration — sync tables

**Files:**
- Create: `supabase/migrations/20261004000000_create_account_sync_tables.sql`

**Interfaces:**
- Produces: tables `provider_connections`, `account_mappings`, `sync_runs`, `sync_run_items` as specified in the design doc

- [ ] **Step 1: Write migration**

Create `supabase/migrations/20261004000000_create_account_sync_tables.sql`:

```sql
-- Account value sync: provider connections, mappings, sync audit

CREATE TABLE IF NOT EXISTS provider_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('open_banking', 'trading212')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'needs_reauth', 'error', 'disabled')),
    display_name TEXT,
    credentials_encrypted TEXT NOT NULL,
    external_connection_id TEXT NOT NULL,
    last_synced_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    UNIQUE (user_id, provider, external_connection_id)
);

CREATE TABLE IF NOT EXISTS account_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_connection_id UUID NOT NULL REFERENCES provider_connections(id) ON DELETE CASCADE,
    external_account_id TEXT NOT NULL,
    external_account_name TEXT NOT NULL,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    UNIQUE (provider_connection_id, external_account_id),
    UNIQUE (account_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
    as_of_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'success', 'partial', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    finished_at TIMESTAMPTZ,
    written_count INT NOT NULL DEFAULT 0,
    skipped_count INT NOT NULL DEFAULT 0,
    error_count INT NOT NULL DEFAULT 0,
    notes TEXT,
    undone_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE TABLE IF NOT EXISTS sync_run_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sync_run_id UUID NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    external_account_id TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('written', 'skipped', 'error')),
    reason TEXT,
    external_amount DECIMAL(15, 2),
    external_currency TEXT,
    previous_value_gbp DECIMAL(15, 2),
    new_value_gbp DECIMAL(15, 2),
    had_previous BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX IF NOT EXISTS idx_provider_connections_user_id ON provider_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_account_mappings_user_id ON account_mappings(user_id);
CREATE INDEX IF NOT EXISTS idx_account_mappings_connection ON account_mappings(provider_connection_id);
CREATE INDEX IF NOT EXISTS idx_sync_runs_user_id ON sync_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_sync_runs_as_of_date ON sync_runs(as_of_date);
CREATE INDEX IF NOT EXISTS idx_sync_run_items_run_id ON sync_run_items(sync_run_id);
```

- [ ] **Step 2: Commit**

```bash
git add supabase/migrations/20261004000000_create_account_sync_tables.sql
git commit -m "feat(sync): add account sync tables migration"
```

---

### Task 2: Credential encryption helper

**Files:**
- Modify: `pyproject.toml`
- Create: `src/utils/crypto.py`
- Test: `tests/test_crypto.py`

**Interfaces:**
- Produces: `encrypt_secret(plaintext: str, key: bytes | None = None) -> str`, `decrypt_secret(token: str, key: bytes | None = None) -> str`, `load_fernet_key() -> bytes`

- [ ] **Step 1: Add dependency**

Add to `pyproject.toml` dependencies:

```toml
"cryptography>=44.0.0",
```

Run: `uv sync`  
Expected: lockfile updates; `cryptography` installed.

- [ ] **Step 2: Write failing tests**

Create `tests/test_crypto.py`:

```python
from utils.crypto import decrypt_secret, encrypt_secret, load_fernet_key


def test_round_trip(monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    monkeypatch.setenv("SYNC_CREDENTIALS_KEY", key.decode())
    token = encrypt_secret('{"api_key":"x","api_secret":"y"}')
    assert token != '{"api_key":"x","api_secret":"y"}'
    assert decrypt_secret(token) == '{"api_key":"x","api_secret":"y"}'


def test_load_fernet_key_requires_env(monkeypatch):
    monkeypatch.delenv("SYNC_CREDENTIALS_KEY", raising=False)
    try:
        load_fernet_key()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "SYNC_CREDENTIALS_KEY" in str(e)
```

- [ ] **Step 3: Run tests — expect FAIL**

Run: `uv run pytest tests/test_crypto.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'utils.crypto'` (or import error).

- [ ] **Step 4: Implement**

Create `src/utils/crypto.py`:

```python
"""Fernet helpers for provider credential storage."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet


def load_fernet_key() -> bytes:
    raw = os.environ.get("SYNC_CREDENTIALS_KEY")
    if not raw:
        # Streamlit secrets fallback for interactive app
        try:
            import streamlit as st

            raw = st.secrets.get("sync", {}).get("credentials_key")
        except Exception:
            raw = None
    if not raw:
        raise RuntimeError(
            "SYNC_CREDENTIALS_KEY env var (or secrets.sync.credentials_key) is required"
        )
    return raw.encode() if isinstance(raw, str) else raw


def encrypt_secret(plaintext: str, key: bytes | None = None) -> str:
    f = Fernet(key or load_fernet_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str, key: bytes | None = None) -> str:
    f = Fernet(key or load_fernet_key())
    return f.decrypt(token.encode()).decode()
```

- [ ] **Step 5: Run tests — expect PASS**

Run: `uv run pytest tests/test_crypto.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/utils/crypto.py tests/test_crypto.py
git commit -m "feat(sync): add Fernet credential encryption helper"
```

---

### Task 3: Provider base types + models

**Files:**
- Create: `src/utils/providers/__init__.py`
- Create: `src/utils/providers/base.py`
- Modify: `src/utils/models.py`

**Interfaces:**
- Produces:
  - `NormalizedBalance(external_account_id, name, currency, amount: Decimal, raw=None)`
  - `ProviderAuthError`, `ProviderError`
  - `BalanceProvider` protocol with `provider_name` and `list_balances(connection: dict) -> list[NormalizedBalance]`
  - Dataclasses: `ProviderConnection`, `AccountMapping`, `SyncRun`, `SyncRunItem`

- [ ] **Step 1: Create provider package**

Create `src/utils/providers/__init__.py` (empty).

Create `src/utils/providers/base.py`:

```python
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
```

- [ ] **Step 2: Add models**

Append to `src/utils/models.py`:

```python
@dataclass
class ProviderConnection:
    id: Optional[str]
    user_id: str
    provider: str
    status: str
    credentials_encrypted: str
    external_connection_id: str
    display_name: Optional[str] = None
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None


@dataclass
class AccountMapping:
    id: Optional[str]
    user_id: str
    provider_connection_id: str
    external_account_id: str
    external_account_name: str
    account_id: str


@dataclass
class SyncRun:
    id: Optional[str]
    user_id: str
    trigger: str
    as_of_date: _date
    status: str = "running"
    written_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    notes: Optional[str] = None
    undone_at: Optional[datetime] = None


@dataclass
class SyncRunItem:
    id: Optional[str]
    sync_run_id: str
    provider: str
    outcome: str
    account_id: Optional[str] = None
    external_account_id: Optional[str] = None
    reason: Optional[str] = None
    external_amount: Optional[float] = None
    external_currency: Optional[str] = None
    previous_value_gbp: Optional[float] = None
    new_value_gbp: Optional[float] = None
    had_previous: bool = False
```

- [ ] **Step 3: Commit**

```bash
git add src/utils/providers/__init__.py src/utils/providers/base.py src/utils/models.py
git commit -m "feat(sync): add provider base types and sync models"
```

---

### Task 4: DB handlers for sync tables

**Files:**
- Modify: `src/utils/db.py`
- Test: `tests/test_sync_db.py`

**Interfaces:**
- Produces on `SupabaseHandler`:
  - `list_provider_connections(user_id: str) -> list[dict]`
  - `upsert_provider_connection(user_id, provider, external_connection_id, credentials_encrypted, display_name=None, status="active") -> dict`
  - `update_provider_connection_status(connection_id, status, last_error=None) -> dict`
  - `delete_provider_connection(connection_id: str) -> None`
  - `list_account_mappings(user_id: str) -> list[dict]`
  - `upsert_account_mapping(user_id, provider_connection_id, external_account_id, external_account_name, account_id) -> dict`
  - `delete_account_mapping(mapping_id: str) -> None`
  - `get_account_value(account_id: str, date: str) -> float | None`
  - `delete_account_value(account_id: str, date: str) -> None`
  - `create_sync_run(user_id, trigger, as_of_date) -> dict`
  - `finalize_sync_run(run_id, status, written_count, skipped_count, error_count, notes=None) -> dict`
  - `add_sync_run_item(...) -> dict`
  - `list_sync_runs(user_id, limit=20) -> list[dict]`
  - `get_sync_run(run_id: str) -> dict | None`
  - `list_sync_run_items(run_id: str) -> list[dict]`
  - `mark_sync_run_undone(run_id: str, notes: str | None = None) -> dict`
  - `list_user_ids_with_active_connections() -> list[str]`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sync_db.py` covering at least:

```python
from utils.db import SupabaseHandler


def test_upsert_provider_connection_trading212(fake_supabase, sample_user_id, mocker):
    mocker.patch("utils.db.create_client", return_value=fake_supabase)
    # after insert, select returns the row
    row = {
        "id": "conn-1",
        "user_id": sample_user_id,
        "provider": "trading212",
        "status": "active",
        "credentials_encrypted": "enc",
        "external_connection_id": "default",
        "display_name": "T212",
    }
    fake_supabase.set_table("provider_connections", [row])
    handler = SupabaseHandler.__new__(SupabaseHandler)
    handler.supabase = fake_supabase
    result = handler.upsert_provider_connection(
        sample_user_id, "trading212", "default", "enc", display_name="T212"
    )
    assert result["provider"] == "trading212"
    assert any(c[0] == "upsert" for c in fake_supabase._tables["provider_connections"].calls)


def test_get_account_value_none_when_missing(fake_supabase, mocker):
    mocker.patch("utils.db.create_client", return_value=fake_supabase)
    fake_supabase.set_table("account_values", [])
    handler = SupabaseHandler.__new__(SupabaseHandler)
    handler.supabase = fake_supabase
    assert handler.get_account_value("acc-1", "2026-09-30") is None
```

Add parallel tests for `create_sync_run`, `add_sync_run_item`, `list_account_mappings`, `mark_sync_run_undone` following the same FakeSupabase pattern used in `tests/test_weight_loss_db.py`.

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/test_sync_db.py -v`  
Expected: FAIL (`AttributeError: ... upsert_provider_connection`).

- [ ] **Step 3: Implement methods on `SupabaseHandler`**

Implement each method listed in Interfaces using the same try/except + logging style as existing CRUD. Key details:

- `upsert_provider_connection`: upsert on conflict `(user_id, provider, external_connection_id)`, set `updated_at` via DB default or explicit ISO timestamp; return selected row.
- `get_account_value`: `select value where account_id and date`; return `float` or `None`.
- `delete_account_value`: delete matching row.
- `create_sync_run`: insert with `status='running'`, return row.
- `finalize_sync_run`: update counts/status/`finished_at`.
- `list_user_ids_with_active_connections`: select distinct `user_id` where `status='active'`.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/test_sync_db.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/utils/db.py tests/test_sync_db.py
git commit -m "feat(sync): add SupabaseHandler methods for connections and runs"
```

---

### Task 5: Trading 212 provider

**Files:**
- Create: `src/utils/providers/trading212.py`
- Create: `tests/fixtures/t212_account_summary.json`
- Test: `tests/test_provider_trading212.py`

**Interfaces:**
- Consumes: `NormalizedBalance`, `ProviderAuthError`, `ProviderError` from `providers.base`
- Produces: `Trading212Provider` with `provider_name = "trading212"`, `list_balances(connection: dict) -> list[NormalizedBalance]`
- Connection dict must include decrypted credentials JSON: `{"api_key": "...", "api_secret": "...", "base_url": "https://live.trading212.com/api/v0"}` (`base_url` optional; default live)

- [ ] **Step 1: Add fixture**

Create `tests/fixtures/t212_account_summary.json`:

```json
{
  "id": 12345678,
  "currency": "GBP",
  "totalValue": 15432.5,
  "cash": {
    "availableToTrade": 200.0,
    "inPies": 50.0,
    "reservedForOrders": 0.0
  },
  "investments": {
    "currentValue": 15182.5,
    "totalCost": 14000.0,
    "realizedProfitLoss": 100.0,
    "unrealizedProfitLoss": 1182.5
  }
}
```

- [ ] **Step 2: Write failing tests**

```python
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from utils.providers.base import ProviderAuthError
from utils.providers.trading212 import Trading212Provider

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "t212_account_summary.json").read_text()
)


def test_list_balances_uses_total_value(mocker):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = FIXTURE
    mocker.patch("utils.providers.trading212.requests.get", return_value=resp)

    provider = Trading212Provider()
    balances = provider.list_balances(
        {
            "credentials": {
                "api_key": "k",
                "api_secret": "s",
                "base_url": "https://live.trading212.com/api/v0",
            }
        }
    )
    assert len(balances) == 1
    assert balances[0].external_account_id == "12345678"
    assert balances[0].currency == "GBP"
    assert balances[0].amount == Decimal("15432.5")
    assert "Trading 212" in balances[0].name


def test_401_raises_auth_error(mocker):
    resp = MagicMock()
    resp.status_code = 401
    resp.text = "Bad API key"
    mocker.patch("utils.providers.trading212.requests.get", return_value=resp)
    with pytest.raises(ProviderAuthError):
        Trading212Provider().list_balances(
            {"credentials": {"api_key": "k", "api_secret": "s"}}
        )
```

- [ ] **Step 3: Run — expect FAIL**

Run: `uv run pytest tests/test_provider_trading212.py -v`  
Expected: FAIL (module missing).

- [ ] **Step 4: Implement provider**

Create `src/utils/providers/trading212.py`:

```python
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
```

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest tests/test_provider_trading212.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/utils/providers/trading212.py tests/fixtures/t212_account_summary.json tests/test_provider_trading212.py
git commit -m "feat(sync): add Trading 212 balance provider"
```

---

### Task 6: Open Banking (GoCardless) provider

**Files:**
- Create: `src/utils/providers/open_banking.py`
- Create: `tests/fixtures/gocardless_balances.json`
- Create: `tests/fixtures/gocardless_account_details.json`
- Test: `tests/test_provider_open_banking.py`

**Interfaces:**
- Produces: `OpenBankingProvider` with `provider_name = "open_banking"`
- Connection credentials JSON shape:
  `{"access_token": "...", "refresh_token": "...", "requisition_id": "..."}`
- Also expose helpers used by UI connect flow:
  - `create_requisition(secret_id, secret_key, institution_id, redirect_url, reference) -> dict` (link + requisition id)
  - `exchange_token(secret_id, secret_key) -> dict` (access token)
  - Prefer `interimAvailable` / `expected` balance type, else first balance in list

- [ ] **Step 1: Fixtures**

`tests/fixtures/gocardless_balances.json`:

```json
{
  "balances": [
    {
      "balanceAmount": {"amount": "1250.55", "currency": "GBP"},
      "balanceType": "interimAvailable"
    },
    {
      "balanceAmount": {"amount": "1300.00", "currency": "GBP"},
      "balanceType": "closingBooked"
    }
  ]
}
```

`tests/fixtures/gocardless_account_details.json`:

```json
{
  "account": {
    "iban": "GB00TEST123",
    "name": "Main Current",
    "currency": "GBP"
  }
}
```

- [ ] **Step 2: Failing tests**

Test that `list_balances` for a connection with one account id:
1. GETs requisition → accounts list
2. GETs details + balances per account
3. Returns `NormalizedBalance` with amount `1250.55` GBP and name from details
4. 401 → `ProviderAuthError`

Mock `requests.get` with a side_effect keyed by URL path.

- [ ] **Step 3: Run — expect FAIL**

Run: `uv run pytest tests/test_provider_open_banking.py -v`  
Expected: FAIL (module missing).

- [ ] **Step 4: Implement**

Create `src/utils/providers/open_banking.py` against base URL `https://bankaccountdata.gocardless.com/api/v2`.

Core `list_balances`:
1. `GET /requisitions/{requisition_id}/` with Bearer `access_token`
2. For each account id: `GET /accounts/{id}/details/` and `GET /accounts/{id}/balances/`
3. Pick balance: first of types `interimAvailable`, `expected`, `forwardAvailable`, else `balances[0]`
4. `external_account_id` = account UUID; `name` = details name or IBAN last 4

Include `refresh_access_token` helper that POSTs to `/token/refresh/` when UI/orchestrator marks `needs_reauth` — v1 orchestrator treats auth errors as `needs_reauth` and does not auto-refresh (keep refresh as a UI reconnect action calling the helper).

- [ ] **Step 5: Run — expect PASS**

Run: `uv run pytest tests/test_provider_open_banking.py -v`  
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/utils/providers/open_banking.py tests/fixtures/gocardless_*.json tests/test_provider_open_banking.py
git commit -m "feat(sync): add GoCardless Open Banking balance provider"
```

---

### Task 7: Month-end date helper

**Files:**
- Create: `src/utils/sync/__init__.py`
- Create: `src/utils/sync/dates.py`
- Test: `tests/test_sync_dates.py`

**Interfaces:**
- Produces: `previous_month_end(today: date) -> date`

- [ ] **Step 1: Failing test**

```python
from datetime import date
from utils.sync.dates import previous_month_end

def test_previous_month_end_from_first():
    assert previous_month_end(date(2026, 10, 1)) == date(2026, 9, 30)

def test_previous_month_end_january():
    assert previous_month_end(date(2026, 1, 15)) == date(2025, 12, 31)
```

- [ ] **Step 2: Implement**

```python
from __future__ import annotations
from datetime import date, timedelta

def previous_month_end(today: date) -> date:
    first_of_month = today.replace(day=1)
    return first_of_month - timedelta(days=1)
```

- [ ] **Step 3: Run — PASS, then commit**

```bash
uv run pytest tests/test_sync_dates.py -v
git add src/utils/sync/__init__.py src/utils/sync/dates.py tests/test_sync_dates.py
git commit -m "feat(sync): add previous_month_end helper"
```

---

### Task 8: Sync orchestrator

**Files:**
- Create: `src/utils/sync/orchestrator.py`
- Test: `tests/test_sync_orchestrator.py`

**Interfaces:**
- Consumes: providers, db handler methods from Task 4, `convert_currency` (injectable)
- Produces:
  ```python
  def run_sync(
      db,
      user_id: str,
      as_of_date: date,
      trigger: str,  # "manual" | "scheduled"
      *,
      providers: dict[str, BalanceProvider] | None = None,
      convert_to_gbp=None,
      decrypt_credentials=None,
  ) -> dict:  # finalized sync_runs row
  ```

- [ ] **Step 1: Write failing tests with fake provider + fake db**

Cover:
1. Mapped balance → `save_account_value` called with GBP amount; item `written`; run `success`
2. Unmapped → item `skipped`/`unmapped`; no save
3. Provider raises `ProviderAuthError` → connection status `needs_reauth`; run `failed` or `partial` if another provider wrote
4. Currency conversion via injectable `convert_to_gbp(amount, currency) -> float`
5. Zero amount is written
6. Mapped but not returned → `skipped`/`not_returned`
7. Existing value overwritten; `had_previous=True` and `previous_value_gbp` set

Use a tiny in-memory fake db object (not Supabase) implementing only the methods orchestrator calls.

- [ ] **Step 2: Run — expect FAIL**

Run: `uv run pytest tests/test_sync_orchestrator.py -v`  
Expected: FAIL (module missing).

- [ ] **Step 3: Implement orchestrator**

Algorithm (must match spec §7):

1. `run = db.create_sync_run(...)`
2. Load connections + mappings for user
3. Build `mapped_external = {(connection_id, external_account_id): mapping}`
4. `seen_mapped: set[tuple[str, str]] = set()`
5. Default providers registry: `{"trading212": Trading212Provider(), "open_banking": OpenBankingProvider()}`
6. For each connection with `status == "active"`:
   - decrypt credentials JSON onto `connection["credentials"]`
   - `balances = provider.list_balances(connection)`
   - on `ProviderAuthError`: update status `needs_reauth`, add error item, continue
   - on `ProviderError`: update status `error`, add error item, continue
   - for each balance: if unmapped → skipped; else convert, `get_account_value`, `save_account_value`, written item; add to `seen_mapped`
7. For each mapping whose connection was successfully fetched but key not in `seen_mapped` → skipped/`not_returned`
8. `finalize_sync_run` with status rules: errors and writes → `partial`; only errors → `failed`; else `success`
9. Update `last_synced_at` on successful connection fetches
10. Return finalized run dict

Default `convert_to_gbp`: wrap `utils.currency.convert_currency`; if conversion returns `None`, item `error`/`conversion_failed`.

- [ ] **Step 4: Run — expect PASS**

Run: `uv run pytest tests/test_sync_orchestrator.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/utils/sync/orchestrator.py tests/test_sync_orchestrator.py
git commit -m "feat(sync): implement sync orchestrator with provider isolation"
```

---

### Task 9: Undo sync run

**Files:**
- Create: `src/utils/sync/undo.py`
- Test: `tests/test_sync_undo.py`

**Interfaces:**
- Produces:
  ```python
  def undo_sync_run(db, user_id: str, sync_run_id: str) -> dict:
      """Returns {"restored": int, "deleted": int, "skipped": int, "run": dict}"""
  ```

- [ ] **Step 1: Failing tests**

1. Written item with `had_previous=True` and current == `new_value_gbp` → restore previous via `save_account_value`
2. Written item with `had_previous=False` and current == new → `delete_account_value`
3. Current ≠ new → skip (no write/delete)
4. Wrong `user_id` on run → raise `PermissionError`
5. Sets `undone_at` via `mark_sync_run_undone`

- [ ] **Step 2: Implement**

```python
def undo_sync_run(db, user_id: str, sync_run_id: str) -> dict:
    run = db.get_sync_run(sync_run_id)
    if not run or run["user_id"] != user_id:
        raise PermissionError("Sync run not found for user")
    as_of = run["as_of_date"]
    if hasattr(as_of, "isoformat"):
        as_of_str = as_of.isoformat()
    else:
        as_of_str = str(as_of)

    restored = deleted = skipped = 0
    for item in db.list_sync_run_items(sync_run_id):
        if item["outcome"] != "written" or not item.get("account_id"):
            continue
        current = db.get_account_value(item["account_id"], as_of_str)
        new_val = float(item["new_value_gbp"]) if item["new_value_gbp"] is not None else None
        if current is None or new_val is None or abs(current - new_val) > 0.001:
            skipped += 1
            continue
        if item.get("had_previous"):
            db.save_account_value(item["account_id"], as_of_str, float(item["previous_value_gbp"]))
            restored += 1
        else:
            db.delete_account_value(item["account_id"], as_of_str)
            deleted += 1

    notes = f"Undo: restored={restored}, deleted={deleted}, skipped={skipped}"
    run = db.mark_sync_run_undone(sync_run_id, notes=notes)
    return {"restored": restored, "deleted": deleted, "skipped": skipped, "run": run}
```

- [ ] **Step 3: PASS + commit**

```bash
uv run pytest tests/test_sync_undo.py -v
git add src/utils/sync/undo.py tests/test_sync_undo.py
git commit -m "feat(sync): add undo for sync runs"
```

---

### Task 10: Month-end CLI + GitHub Action

**Files:**
- Create: `src/utils/sync/month_end.py`
- Create: `.github/workflows/month-end-sync.yml`

**Interfaces:**
- Produces: `main()` CLI that loads service Supabase client from env, lists users with active connections, runs `run_sync(..., trigger="scheduled", as_of_date=previous_month_end(utc_today))`
- Schedule: `0 0 1 * *` (00:00 UTC on the 1st) → as-of = last day of previous month

**Note:** Spec allowed Edge Function *or equivalent cron*. This repo’s orchestrator is Python, so v1 uses GitHub Actions + CLI instead of a Deno Edge Function.

- [ ] **Step 1: Implement CLI**

`src/utils/sync/month_end.py` must:
1. Read `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SYNC_CREDENTIALS_KEY`, optional `GOCARDLESS_SECRET_ID` / `GOCARDLESS_SECRET_KEY` from env
2. Construct a `SupabaseHandler`-like client **without Streamlit** — add `SupabaseHandler.from_client(client)` classmethod (or a thin `SyncDatabase` wrapper) in this task if `__init__` requires `st.secrets`. Prefer:

```python
@classmethod
def from_env(cls):
    handler = cls.__new__(cls)
    handler.supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    return handler
```

3. For each user id from `list_user_ids_with_active_connections()`, call `run_sync`
4. Exit non-zero if any run status is `failed`

- [ ] **Step 2: Workflow**

Create `.github/workflows/month-end-sync.yml`:

```yaml
name: Month-end account sync
on:
  schedule:
    - cron: "30 0 1 * *"
  workflow_dispatch:
jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run python -m utils.sync.month_end
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          SYNC_CREDENTIALS_KEY: ${{ secrets.SYNC_CREDENTIALS_KEY }}
```

Ensure `python -m utils.sync.month_end` works with `pythonpath=src` (set `PYTHONPATH=src` in the workflow env).

- [ ] **Step 3: Smoke import**

Run: `PYTHONPATH=src uv run python -c "from utils.sync.month_end import main; print(main.__name__)"`  
Expected: prints `main`

- [ ] **Step 4: Commit**

```bash
git add src/utils/sync/month_end.py src/utils/db.py .github/workflows/month-end-sync.yml
git commit -m "feat(sync): add month-end CLI and GitHub Actions schedule"
```

---

### Task 11: Streamlit Connections & Sync UI

**Files:**
- Modify: `src/pages/networth_tracker.py` (Account Values tab)

**Interfaces:**
- Consumes: db sync methods, `run_sync`, `undo_sync_run`, providers’ connect helpers, `encrypt_secret`
- Produces: UI section **Connections & Sync** below the existing add/update form (before Remove Entries is fine)

- [ ] **Step 1: Trading 212 connect form**

- Inputs: API key, API secret, optional demo checkbox (`base_url` demo vs live), display name
- On submit: encrypt JSON credentials, `upsert_provider_connection(..., provider="trading212", external_connection_id="default")`
- Show status badge from connection row

- [ ] **Step 2: Open Banking connect**

- Requires `st.secrets["gocardless"]["secret_id"]` and `secret_key` (app-level, not per-user)
- Institution id text input + “Start bank link” → `create_requisition` → `st.link_button` / show link
- After redirect back (query param or manual “I’ve finished linking” + requisition id field), store encrypted tokens + requisition id as `external_connection_id`
- List each active bank connection with disconnect

- [ ] **Step 3: Mapping UI**

- Button “Refresh external accounts” → call each provider `list_balances` (read-only) and show external accounts
- For each external account: selectbox of tracker accounts + Save → `upsert_account_mapping`
- Prevent selecting an account_id already mapped to another external account (filter options)

- [ ] **Step 4: Sync now + history**

- Date input default today; button Sync now → `run_sync(..., trigger="manual")` → success/partial/failed message with counts
- Table of recent `list_sync_runs`; expander for items
- Undo button when `undone_at` is null → `undo_sync_run`

- [ ] **Step 5: Manual smoke checklist (document in commit message / PR)**

When credentials available:
1. Connect T212 → map → Sync now → value in Account Value Records → Undo
2. Optional: one GoCardless sandbox bank

- [ ] **Step 6: Commit**

```bash
git add src/pages/networth_tracker.py
git commit -m "feat(sync): add Connections and Sync panel to net worth tracker"
```

---

### Task 12: Full test suite + README secrets note

**Files:**
- Modify: `README.md` (short “Account sync” subsection under Setup)

- [ ] **Step 1: Run full suite**

Run: `uv run pytest -v`  
Expected: all tests PASS (existing + new).

- [ ] **Step 2: README secrets**

Document:

```markdown
### Account value sync (optional)

Add to `.streamlit/secrets.toml`:

[sync]
credentials_key = "<fernet-key-from-cryptography.fernet.Fernet.generate_key()>"

[gocardless]
secret_id = "..."
secret_key = "..."

GitHub Actions month-end job needs repository secrets:
`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SYNC_CREDENTIALS_KEY`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document account sync secrets and month-end job"
```

---

## Plan self-review

**Spec coverage**
| Spec item | Task |
|---|---|
| Sync orchestrator | 8 |
| GoCardless Open Banking adapter | 6 |
| Trading 212 adapter | 5 |
| Connections UI | 11 |
| Mapping UI | 11 |
| Sync now | 11 |
| Scheduled EOM | 7, 10 |
| Auto-save | 8 |
| Sync log + undo | 4, 8, 9, 11 |
| Extensible provider interface | 3 |
| Encrypted credentials | 2, 4, 11 |
| Migration / data model | 1 |
| Tests | 2, 4–9, 12 |
| Manual form retained | 11 (additive only) |

**Scheduler adaptation:** Spec mentioned Supabase Edge Function; plan uses Python CLI + GitHub Actions because the orchestrator and providers are Python. Behavior (1st-of-month, previous month-end as-of) matches the spec.

**Placeholder scan:** No TBD/TODO left in task steps.

**Type consistency:** `NormalizedBalance.amount` is `Decimal`; DB layer continues to use float/`Decimal` string formatting consistent with `save_account_value`. Orchestrator converts with `float(...)` only at the DB boundary.
