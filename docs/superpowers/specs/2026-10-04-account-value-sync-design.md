# Account Value Sync — Design Spec

| | |
|---|---|
| **Branch** | `cursor/account-sync-automation-f328` |
| **Status** | Approved (brainstorm). Awaiting implementation plan. |
| **Effort** | Large (sync engine, two providers, schema, UI, scheduler) |
| **Approach** | Modular provider adapters |

## 1. Goal

Stop the monthly manual loop of updating each account’s value one-by-one. Pull live balances from UK bank Open Banking and Trading 212, auto-write them into the existing `account_values` table for a chosen as-of date, and keep a sync log with undo.

Manual Account Values entry remains available for unmapped or unsupported accounts.

## 2. Scope

### In scope (v1)

1. **Sync orchestrator** — for a user + as-of date: fetch from connected providers, map to tracker accounts, convert to GBP, upsert `account_values`, record a sync run.
2. **Provider adapters**
   - UK Open Banking via **GoCardless Bank Account Data** for bank/cash balances (v1 vendor locked; swap later only behind the same provider interface).
   - Trading 212 public REST API for portfolio/cash totals exposed as syncable external accounts.
3. **Connections UI** — connect/disconnect providers, store credentials securely, show connection status (`active` / `needs_reauth` / `error`).
4. **Account mapping UI** — map each external account once to an existing tracker `accounts` row; unmapped accounts are skipped on sync.
5. **Manual Sync now** — button with as-of date (default today).
6. **Scheduled end-of-month sync** — cron/Edge Function; as-of date = last calendar day of the previous month; `trigger=scheduled`.
7. **Auto-save** — mapped balances write immediately (no confirmation step).
8. **Sync log + undo** — per-run summary and per-item detail; undo restores previous values for items that run wrote, without clobbering newer edits.
9. **Extensibility** — shared provider interface so additional brokers can be added later without changing the orchestrator.

### Out of scope (v1)

- Email or push notifications for success/failure.
- Commercial wealth aggregators (Moneyhub-class) as the primary integration.
- Auto-creating tracker accounts from external accounts (user maps to existing accounts only).
- Transaction import, categorisation, or spending analytics.
- Multi-currency display of synced values (storage stays GBP, same as today).
- Live Open Banking consent flows in CI.
- Supabase RLS changes — handlers continue to scope by `user_id`, matching the existing dashboard pattern.
- CFD vs Invest product nuance beyond whatever distinct accounts the Trading 212 API returns as separate external accounts.

## 3. Architecture

Sync is an alternative write path into the same `account_values` table used by the manual form.

```
[Streamlit UI]                    [Supabase cron / Edge Function]
  Sync now / Connections / Undo          End-of-month job
           \                            /
            \                          /
             v                        v
                    Sync Orchestrator
           (date → fetch → map → upsert → log)
                           |
        +------------------+------------------+
        |                                     |
  Open Banking provider                 Trading 212 provider
  (UK bank AIS)                         (portfolio cash + investments)
        |                                     |
        +------------------+------------------+
                           v
              account_mappings → account_values
              sync_runs / sync_run_items (audit + undo)
```

**Boundaries**

- **Providers** only fetch normalized balances (`external_account_id`, name, currency, amount, as-of metadata).
- **Orchestrator** owns mapping lookup, GBP conversion (reuse `utils.currency`), upsert, logging, and undo coordination.
- **UI** owns connect/disconnect, mapping, triggering sync, showing last run, and undo.

## 4. File layout

```
src/utils/providers/base.py           # Provider protocol + NormalizedBalance
src/utils/providers/open_banking.py   # GoCardless Bank Account Data client (v1)
src/utils/providers/trading212.py     # Trading 212 API client
src/utils/sync/orchestrator.py        # run_sync(user_id, as_of_date, trigger)
src/utils/sync/undo.py                # undo_sync_run(user_id, sync_run_id)
src/utils/db.py                       # extend SupabaseHandler: connections, mappings, runs
src/pages/networth_tracker.py         # Connections + Sync panel (Account Values area)

supabase/migrations/<ts>_create_account_sync_tables.sql
supabase/functions/month_end_sync/    # scheduled invoker (or equivalent cron entrypoint)

tests/test_sync_orchestrator.py
tests/test_sync_undo.py
tests/test_provider_trading212.py
tests/test_provider_open_banking.py
tests/test_sync_db.py
```

Keep provider HTTP/parsing and orchestrator logic out of the Streamlit page so they stay unit-testable.

## 5. Data model

Four new tables in one migration. Follow existing conventions: UUID PKs, `user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE`, indexes on `user_id`.

### 5.1 `provider_connections`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | TEXT | FK → users |
| `provider` | TEXT | `open_banking` \| `trading212` |
| `status` | TEXT | `active` \| `needs_reauth` \| `error` \| `disabled` |
| `display_name` | TEXT | Optional label in UI |
| `credentials_encrypted` | TEXT | Encrypted token/API key payload; never plaintext |
| `external_connection_id` | TEXT NOT NULL | Provider-side requisition/connection id; Trading 212 uses the fixed sentinel `default` (one API-key connection per user) |
| `last_synced_at` | TIMESTAMPTZ NULL | |
| `last_error` | TEXT NULL | Short safe message |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

Unique: `(user_id, provider, external_connection_id)`.  
Open Banking may have multiple rows (one per bank requisition). Trading 212 is limited to one row via `external_connection_id = 'default'`.

### 5.2 `account_mappings`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | TEXT | FK → users |
| `provider_connection_id` | UUID | FK → provider_connections |
| `external_account_id` | TEXT | Stable id from provider |
| `external_account_name` | TEXT | Last seen name for UI |
| `account_id` | UUID | FK → accounts (tracker account) |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

Unique: `(provider_connection_id, external_account_id)`.  
Unique: `(account_id)` — one external source per tracker account in v1 (avoids double-counting).

### 5.3 `sync_runs`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | TEXT | |
| `trigger` | TEXT | `manual` \| `scheduled` |
| `as_of_date` | DATE | Date written into `account_values` |
| `status` | TEXT | `running` \| `success` \| `partial` \| `failed` |
| `started_at` / `finished_at` | TIMESTAMPTZ | |
| `written_count` / `skipped_count` / `error_count` | INT | Summary |
| `notes` | TEXT NULL | Optional short summary |
| `undone_at` | TIMESTAMPTZ NULL | Set when user successfully undoes this run (partial undo still sets it and notes skipped items) |

### 5.4 `sync_run_items`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `sync_run_id` | UUID | FK → sync_runs ON DELETE CASCADE |
| `account_id` | UUID NULL | Tracker account when known |
| `provider` | TEXT | |
| `external_account_id` | TEXT NULL | |
| `outcome` | TEXT | `written` \| `skipped` \| `error` |
| `reason` | TEXT NULL | e.g. `unmapped`, `not_returned`, `needs_reauth` |
| `external_amount` | DECIMAL NULL | |
| `external_currency` | TEXT NULL | |
| `previous_value_gbp` | DECIMAL NULL | Prior `account_values.value` if any |
| `new_value_gbp` | DECIMAL NULL | Value written (GBP) |
| `had_previous` | BOOLEAN | Whether a prior row existed for undo semantics |

## 6. Provider interface

```python
@dataclass(frozen=True)
class NormalizedBalance:
    external_account_id: str
    name: str
    currency: str          # ISO code as returned by provider
    amount: Decimal        # in that currency
    raw: dict | None = None

class BalanceProvider(Protocol):
    provider_name: str

    def list_balances(self, connection: ProviderConnection) -> list[NormalizedBalance]:
        """Fetch current balances. Raises ProviderAuthError / ProviderError."""
```

### 6.1 Open Banking

- Connect flow creates/reuses a bank connection (requisition) and stores provider tokens/ids encrypted.
- `list_balances` returns one `NormalizedBalance` per linked bank account with an available/current balance (prefer available when both exist; document choice in adapter).
- Consent expiry → mark connection `needs_reauth`, raise `ProviderAuthError`, orchestrator continues other providers.

### 6.2 Trading 212

- User pastes API key (and secret if required by API) into Connections UI; stored encrypted.
- `list_balances` maps each distinct account/pot the API exposes (e.g. Invest vs CFD if both exist) to its own `external_account_id`.
- Portfolio value should reflect total equity/cash the API reports for that account so net worth matches what the user sees in T212 for that pot.
- Invalid credentials → `needs_reauth`.

## 7. Data flow

### 7.1 Manual Sync now

1. User chooses as-of date (default: today) and clicks Sync now.
2. Orchestrator creates `sync_runs` row (`trigger=manual`, `status=running`).
3. Load active connections + mappings for the user.
4. For each connection, call `list_balances` (isolate failures per provider).
5. For each returned balance:
   - No mapping → `skipped` / `unmapped`.
   - Mapped → convert to GBP if needed → read existing `account_values` for `(account_id, as_of_date)` → upsert new value → `written` item with `previous_value_gbp`.
6. External accounts that were mapped but not returned → `skipped` / `not_returned` (do **not** delete existing values).
7. Finalize run status: all written/skipped with no errors → `success`; mix of writes and provider/item errors → `partial`; nothing written and errors → `failed`.
8. UI shows summary; user may Undo.

### 7.2 Scheduled end-of-month

1. Cron invokes the same orchestrator for each user with at least one `active` connection.
2. `trigger=scheduled`.
3. `as_of_date` = last calendar day of the **previous** month.
4. Overwrite rule: if a value already exists for that account+date (prior sync or manual edit), sync **overwrites** it. The previous value is stored on the run item for undo.
5. Schedule target: shortly after month close (e.g. 1st of month ~00:30 UTC). Exact cron expression is an implementation detail; document it next to the function.

### 7.3 Undo

1. Load `sync_run_items` with `outcome=written` for the selected run.
2. For each item, load current `account_values` for `(account_id, as_of_date)`.
3. If current value equals `new_value_gbp` from the run item:
   - If `had_previous`: restore `previous_value_gbp`.
   - Else: delete the `account_values` row created by that sync.
4. If current value differs from `new_value_gbp`: **skip** that item (newer sync or manual edit); report in undo summary.
5. Set `sync_runs.undone_at` and show undo summary in UI. Do not mutate historical `sync_run_items` amounts/outcomes.

## 8. Error handling & security

- **Per-provider isolation** — one failure does not abort others.
- **Zero balances** are valid and are written.
- **Secrets** — never log API keys/tokens; store only encrypted payloads; secrets for encryption live in Streamlit/Supabase secrets.
- **Idempotent re-sync** — re-running the same date creates a new `sync_run` and upserts values again.
- **MVP notifications** — in-app last-run status only.

## 9. UI placement

Add a **Connections & Sync** section under the existing Account Values tab (or an adjacent sub-panel) on `networth_tracker.py`:

1. Provider cards: connect Open Banking, add Trading 212 API key, status badges.
2. Mapping table: external account → tracker account select; save mappings.
3. Sync now: date picker + button + last run summary.
4. Recent runs list with Undo for runs that still have restorable `written` items.

Do not remove the existing one-account form or data editor.

## 10. Testing

### Automated

- Orchestrator with fake providers: mapped write, unmapped skip, partial failure, GBP conversion, overwrite same date, zero value write, `not_returned` skip.
- Undo: restore previous; delete if no previous; skip when current ≠ run’s new value.
- Provider parsers: fixture JSON → `NormalizedBalance` for Trading 212 and Open Banking.
- DB handlers: connection/mapping CRUD scoped by `user_id`; run/item persistence; upsert respects `(account_id, date)` uniqueness.

### Manual smoke (credentials available)

- Connect Trading 212 → map → Sync now → value appears → Undo.
- Open Banking connect + one bank account mapped → Sync now.
- Invoke scheduled function once with a forced as-of date (do not wait for real month-end).

### Not in CI

Live bank consent UI / real institution login.

## 11. Success criteria

- User can connect Trading 212 and at least one UK bank, map accounts, and replace the monthly manual entry loop for those accounts with Sync now or the month-end job.
- Every auto-write is attributable to a `sync_run` and reversible when no newer edit exists.
- Adding a future broker means a new provider module + UI connect path, not a redesign of the orchestrator.

## 12. Decisions locked in brainstorm

| Topic | Decision |
|---|---|
| Automation style | Live sync (not bulk form / CSV-first) |
| Coverage | UK banks + investments |
| Write policy | Auto-save |
| Triggers | End-of-month scheduled + manual Sync now |
| Geography | UK only |
| Investments | Extensible; Trading 212 first |
| Approach | Modular provider adapters |
| Unmapped accounts | Skip (do not auto-create) |
| Existing same-date value | Overwrite on sync |
| Missing from provider response | Leave existing value; log skipped |
