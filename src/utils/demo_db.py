"""In-memory DB for local Connections & Sync demos (DEMO_SYNC=1)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pandas as pd


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DemoHandler:
    """Enough of the SupabaseHandler surface for the net-worth + sync UI."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.categories: list[dict] = []
        self.accounts: list[dict] = []
        self.values: dict[tuple[str, str], float] = {}
        self.connections: list[dict] = []
        self.mappings: list[dict] = []
        self.runs: list[dict] = []
        self.items: list[dict] = []
        self._seed()

    def _seed(self) -> None:
        import json
        import os

        from utils.crypto import encrypt_secret

        uid = "demo-sync-user"
        self.users[uid] = {
            "id": uid,
            "email": "demo@example.com",
            "name": "Demo User",
        }
        cat_id = str(uuid.uuid4())
        self.categories.append(
            {"id": cat_id, "user_id": uid, "name": "Investments", "created_at": _now()}
        )
        acc_id = str(uuid.uuid4())
        self.accounts.append(
            {
                "id": acc_id,
                "user_id": uid,
                "category_id": cat_id,
                "name": "Trading 212 ISA",
                "created_at": _now(),
            }
        )
        # Pre-wire Trading 212 DEMO credentials so UI demos can Sync now without flaky forms.
        if os.environ.get("DEMO_SYNC") == "1":
            enc = encrypt_secret(json.dumps({"api_key": "DEMO", "api_secret": "DEMO"}))
            conn_id = str(uuid.uuid4())
            self.connections.append(
                {
                    "id": conn_id,
                    "user_id": uid,
                    "provider": "trading212",
                    "status": "active",
                    "display_name": "T212 Demo",
                    "credentials_encrypted": enc,
                    "external_connection_id": "default",
                    "last_synced_at": None,
                    "last_error": None,
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            )
            self.mappings.append(
                {
                    "id": str(uuid.uuid4()),
                    "user_id": uid,
                    "provider_connection_id": conn_id,
                    "external_account_id": "12345678",
                    "external_account_name": "Trading 212 (12345678)",
                    "account_id": acc_id,
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            )

    # --- users / categories / accounts ---

    def get_or_create_user(self, google_id: str, email: str, name: str) -> dict:
        if google_id not in self.users:
            self.users[google_id] = {"id": google_id, "email": email, "name": name}
        return self.users[google_id]

    def get_user_categories(self, user_id: str) -> list:
        return [c for c in self.categories if c["user_id"] == user_id]

    def create_category(self, user_id: str, name: str) -> dict:
        for c in self.categories:
            if c["user_id"] == user_id and c["name"] == name:
                return c
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "name": name,
            "created_at": _now(),
        }
        self.categories.append(row)
        return row

    def update_category(self, category_id: str, name: str) -> dict:
        for c in self.categories:
            if c["id"] == category_id:
                c["name"] = name
                return c
        raise ValueError("category not found")

    def delete_category(self, category_id: str) -> None:
        self.categories = [c for c in self.categories if c["id"] != category_id]
        self.accounts = [a for a in self.accounts if a["category_id"] != category_id]

    def get_user_accounts(self, user_id: str) -> list:
        cats = {c["id"]: c["name"] for c in self.categories}
        return [
            {
                "id": a["id"],
                "name": a["name"],
                "category_name": cats.get(a["category_id"], ""),
            }
            for a in self.accounts
            if a["user_id"] == user_id
        ]

    def create_account(self, user_id: str, category_id: str, name: str) -> dict:
        for a in self.accounts:
            if a["user_id"] == user_id and a["name"] == name:
                return a
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "category_id": category_id,
            "name": name,
            "created_at": _now(),
        }
        self.accounts.append(row)
        return row

    def update_account(self, account_id: str, name: str) -> dict:
        for a in self.accounts:
            if a["id"] == account_id:
                a["name"] = name
                return a
        raise ValueError("account not found")

    def delete_account(self, account_id: str) -> None:
        self.accounts = [a for a in self.accounts if a["id"] != account_id]
        self.values = {k: v for k, v in self.values.items() if k[0] != account_id}

    def load_account_data(self, user_id: str) -> pd.DataFrame:
        acc_by_id = {a["id"]: a for a in self.accounts if a["user_id"] == user_id}
        cats = {c["id"]: c["name"] for c in self.categories}
        rows = []
        for (account_id, date_str), value in self.values.items():
            acc = acc_by_id.get(account_id)
            if not acc:
                continue
            rows.append(
                {
                    "date": date.fromisoformat(date_str)
                    if isinstance(date_str, str)
                    else date_str,
                    "value": float(value),
                    "account_name": acc["name"],
                    "category_name": cats.get(acc["category_id"], ""),
                }
            )
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df.sort_values("date", ascending=False).reset_index(drop=True)

    def save_account_value(self, account_id: str, date: str, value: float) -> dict:
        self.values[(account_id, str(date))] = float(value)
        return {"account_id": account_id, "date": str(date), "value": float(value)}

    def get_account_value(self, account_id: str, date: str) -> float | None:
        return self.values.get((account_id, str(date)))

    def delete_account_value(self, account_id: str, date: str) -> None:
        self.values.pop((account_id, str(date)), None)

    def delete_entries_by_date(self, date: str, user_id: str) -> None:
        owned = {a["id"] for a in self.accounts if a["user_id"] == user_id}
        self.values = {
            k: v
            for k, v in self.values.items()
            if not (k[0] in owned and str(k[1]) == str(date))
        }

    def update_account_value(self, account_name: str, date: str, value: float) -> dict:
        for a in self.accounts:
            if a["name"] == account_name:
                return self.save_account_value(a["id"], date, value)
        raise ValueError(f"Account {account_name} not found")

    def get_latest_balances(self, user_id: str, group_by: str = "category", as_of_date=None):
        return []

    # --- sync tables ---

    def list_provider_connections(self, user_id: str, *, strict: bool = False) -> list[dict]:
        return [dict(c) for c in self.connections if c["user_id"] == user_id]

    def upsert_provider_connection(
        self,
        user_id: str,
        provider: str,
        external_connection_id: str,
        credentials_encrypted: str,
        display_name=None,
        status: str = "active",
    ) -> dict:
        for c in self.connections:
            if (
                c["user_id"] == user_id
                and c["provider"] == provider
                and c["external_connection_id"] == external_connection_id
            ):
                c["credentials_encrypted"] = credentials_encrypted
                c["status"] = status
                c["display_name"] = display_name
                c["updated_at"] = _now()
                c["last_error"] = None
                return dict(c)
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "provider": provider,
            "status": status,
            "display_name": display_name,
            "credentials_encrypted": credentials_encrypted,
            "external_connection_id": external_connection_id,
            "last_synced_at": None,
            "last_error": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.connections.append(row)
        return dict(row)

    def update_provider_connection_status(
        self, connection_id: str, status: str, last_error=None
    ) -> dict:
        for c in self.connections:
            if c["id"] == connection_id:
                c["status"] = status
                c["last_error"] = last_error
                c["updated_at"] = _now()
                return dict(c)
        raise ValueError("connection not found")

    def touch_provider_connection_synced(self, connection_id: str) -> None:
        for c in self.connections:
            if c["id"] == connection_id:
                c["last_synced_at"] = _now()
                c["status"] = "active"
                c["last_error"] = None
                c["updated_at"] = _now()
                return

    def update_provider_connection_credentials(
        self, connection_id: str, credentials_encrypted: str
    ) -> None:
        for c in self.connections:
            if c["id"] == connection_id:
                c["credentials_encrypted"] = credentials_encrypted
                c["updated_at"] = _now()
                return

    def delete_provider_connection(self, connection_id: str) -> None:
        self.connections = [c for c in self.connections if c["id"] != connection_id]
        self.mappings = [
            m for m in self.mappings if m["provider_connection_id"] != connection_id
        ]

    def list_account_mappings(self, user_id: str, *, strict: bool = False) -> list[dict]:
        return [dict(m) for m in self.mappings if m["user_id"] == user_id]

    def upsert_account_mapping(
        self,
        user_id: str,
        provider_connection_id: str,
        external_account_id: str,
        external_account_name: str,
        account_id: str,
    ) -> dict:
        for m in self.mappings:
            if (
                m["provider_connection_id"] == provider_connection_id
                and m["external_account_id"] == external_account_id
            ):
                m["external_account_name"] = external_account_name
                m["account_id"] = account_id
                m["updated_at"] = _now()
                return dict(m)
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "provider_connection_id": provider_connection_id,
            "external_account_id": external_account_id,
            "external_account_name": external_account_name,
            "account_id": account_id,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.mappings.append(row)
        return dict(row)

    def delete_account_mapping(self, mapping_id: str) -> None:
        self.mappings = [m for m in self.mappings if m["id"] != mapping_id]

    def create_sync_run(self, user_id: str, trigger: str, as_of_date) -> dict:
        as_of = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)
        row = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "trigger": trigger,
            "as_of_date": as_of,
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "written_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "notes": None,
            "undone_at": None,
        }
        self.runs.append(row)
        return dict(row)

    def finalize_sync_run(
        self,
        run_id: str,
        status: str,
        written_count: int,
        skipped_count: int,
        error_count: int,
        notes=None,
    ) -> dict:
        for r in self.runs:
            if r["id"] == run_id:
                r["status"] = status
                r["written_count"] = written_count
                r["skipped_count"] = skipped_count
                r["error_count"] = error_count
                r["notes"] = notes
                r["finished_at"] = _now()
                return dict(r)
        raise ValueError("run not found")

    def add_sync_run_item(self, sync_run_id: str, provider: str, outcome: str, **kwargs) -> dict:
        row = {
            "id": str(uuid.uuid4()),
            "sync_run_id": sync_run_id,
            "provider": provider,
            "outcome": outcome,
            **kwargs,
        }
        self.items.append(row)
        return dict(row)

    def list_sync_runs(self, user_id: str, limit: int = 20) -> list[dict]:
        rows = [dict(r) for r in self.runs if r["user_id"] == user_id]
        rows.sort(key=lambda r: r.get("started_at") or "", reverse=True)
        return rows[:limit]

    def get_sync_run(self, run_id: str) -> dict | None:
        for r in self.runs:
            if r["id"] == run_id:
                return dict(r)
        return None

    def list_sync_run_items(self, run_id: str, *, strict: bool = False) -> list[dict]:
        return [dict(i) for i in self.items if i["sync_run_id"] == run_id]

    def list_later_written_account_ids(
        self, user_id: str, as_of_date, after_started_at: str
    ) -> set[str]:
        as_of = as_of_date.isoformat() if hasattr(as_of_date, "isoformat") else str(as_of_date)
        later_run_ids = {
            r["id"]
            for r in self.runs
            if r["user_id"] == user_id
            and r.get("as_of_date") == as_of
            and r.get("undone_at") is None
            and (r.get("started_at") or "") > after_started_at
        }
        return {
            i["account_id"]
            for i in self.items
            if i["sync_run_id"] in later_run_ids
            and i.get("outcome") == "written"
            and i.get("account_id")
        }

    def mark_sync_run_undone(self, run_id: str, notes: str | None = None) -> dict:
        for r in self.runs:
            if r["id"] == run_id:
                r["undone_at"] = _now()
                if notes is not None:
                    r["notes"] = notes
                return dict(r)
        raise ValueError("run not found")

    def list_user_ids_with_active_connections(self) -> list[str]:
        return sorted(
            {
                c["user_id"]
                for c in self.connections
                if c["status"] in ("active", "needs_reauth", "error")
            }
        )
