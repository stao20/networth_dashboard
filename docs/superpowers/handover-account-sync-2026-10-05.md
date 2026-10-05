# Handover: Account value sync (PR #3)

**Date:** 2026-10-05  
**PR:** https://github.com/stao20/networth_dashboard/pull/3  
**Branch:** `cursor/account-sync-automation-f328` (base: `main`)  
**Supabase project:** `udknsadmksuynwzjdizd` (`https://udknsadmksuynwzjdizd.supabase.co`)

---

## Goal

Pull live balances from Trading 212 and UK banks (GoCardless Open Banking) into `account_values`, with Sync now, month-end GitHub Action, mapping UI, encrypted credentials, audit log, and undo — **without breaking Streamlit Cloud prod** during testing.

---

## Done

### Product / code (on branch)

- Design + plan under `docs/superpowers/`
- Migration: `supabase/migrations/20261004000000_create_account_sync_tables.sql`  
  Tables: `provider_connections`, `account_mappings`, `sync_runs`, `sync_run_items`
- Providers: Trading 212 + GoCardless Open Banking
- Orchestrator, undo, month-end CLI + workflow
- Streamlit **Connections & Sync** panel (under **Account Values** tab)
- `DEMO_SYNC=1` in-memory demo mode for UI demos
- Smoke script (safe for agent): `scripts/smoke_trading212_sync.py`  
  Real Trading 212 API → in-memory `DemoHandler` only (no Supabase writes)

### Remote / ops already completed in this agent

| Item | Status |
|------|--------|
| `SUPABASE_ACCESS_TOKEN` runtime secret | Present |
| Sync migration applied to `udknsadmksuynwzjdizd` | Done (`20261004000000` marked applied) |
| Tables REST-queryable | Yes (empty for existing user) |
| Sync pytest subset | 120 passed |
| UI demo Sync now → Undo (`DEMO_SYNC=1`) | Passed (1 written → undone) |
| Trading 212 live smoke with user API keys | **Not run** — secrets not injected yet |

### Artifacts (this agent)

- `/opt/cursor/artifacts/account_sync_sync_now_undo.mp4`
- `/opt/cursor/artifacts/sync_ui_04_after_sync.png`
- `/opt/cursor/artifacts/sync_ui_06_after_undo.png`
- `/opt/cursor/artifacts/account_sync_supabase_verification.log`

---

## Do not do (prod safety)

- Do **not** merge/push to `main` or republish Streamlit Cloud just to try sync.
- Do **not** run sync against prod Supabase with real credentials until intentionally ready — that writes `account_values` for the real user.
- Do **not** paste Trading 212 API key/secret into chat; use Cursor secrets / env only.
- Google OAuth `redirect_uri` points at `https://networth-dashboard.streamlit.app/oauth2callback`, so this VM cannot easily drive the **real** logged-in Connections UI without OAuth/local redirect changes.

---

## How to resume: real Trading 212 test (recommended next)

Safe path — live API, **no** prod DB writes:

1. Add Cursor / cloud-agent secrets:
   - `TRADING212_API_KEY`
   - `TRADING212_API_SECRET`
   - Optional: `TRADING212_DEMO=1` if keys are from Trading 212 **demo** (else omit for live)
2. On branch `cursor/account-sync-automation-f328`:

```bash
uv run python scripts/smoke_trading212_sync.py
```

3. Expect: printed balances from T212, sync `status=success`, `written_count >= 1`, note that Supabase was not modified.

UI alternative on this VM (also no Supabase): keep `DEMO_SYNC=1`, open `http://127.0.0.1:8501/networth_tracker` → Account Values → Connections & Sync → disconnect/replace T212 connection with real keys → Sync now. Agent Streamlit may already be running with `DEMO_SYNC=1`.

---

## How to connect in the real app (later, when publishing)

Requires Streamlit secrets (Cloud or local):

```toml
[sync]
credentials_key = "<Fernet.generate_key()>"

# Banks only:
[gocardless]
secret_id = "..."
secret_key = "..."
```

Then: Google login → **networth tracker** → **Account Values** → **Connections & Sync** → **Connect Trading 212** → Refresh → map → **Sync now**.

Banks: GoCardless institution ID → Start bank link → authorise → I've finished linking → map → Sync now.

---

## Prod / Streamlit Cloud still needed before users sync

1. `[sync] credentials_key` (or `SYNC_CREDENTIALS_KEY`) on Streamlit Cloud  
2. Optional `[gocardless]` for banks  
3. GitHub Actions secrets for month-end: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SYNC_CREDENTIALS_KEY` (+ optional GoCardless)  
4. Migration is already on remote project `udknsadmksuynwzjdizd`

---

## Known caveats

- Migration history mismatch remains: local `20240320000000` / `20260515000000` vs remote-only `20260516211612`. Prefer `supabase db query` for one-off SQL; repair carefully before `db push`.
- Only Trading 212 + GoCardless Open Banking providers exist; other brokers need new provider modules.
- Trading 212 API coverage is Invest / Stocks ISA (product limitation noted in plan).
- `cleanup.sql` in `supabase/migrations/` is skipped by CLI (naming pattern).

---

## Suggested next agent prompt

```
Continue from PR #3 / branch cursor/account-sync-automation-f328.
TRADING212_API_KEY and TRADING212_API_SECRET are (or will be) Cursor secrets.
Run: uv run python scripts/smoke_trading212_sync.py
Confirm live T212 balances + in-memory sync write; do not write to prod Supabase.
Report PASS/FAIL with redacted output (no secrets).
```

---

## Key paths

| Path | Role |
|------|------|
| `src/pages/networth_tracker.py` | Connections & Sync UI |
| `src/utils/sync/orchestrator.py` | Sync now / scheduled core |
| `src/utils/providers/trading212.py` | T212 client (`DEMO`/`DEMO` stub + live) |
| `src/utils/providers/open_banking.py` | GoCardless |
| `src/utils/demo_db.py` | In-memory DB for `DEMO_SYNC` / smoke |
| `scripts/smoke_trading212_sync.py` | Safe real-API smoke test |
| `supabase/migrations/20261004000000_create_account_sync_tables.sql` | Sync schema |
