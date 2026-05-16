from abc import ABC, abstractmethod
from datetime import date
import logging
import os
import streamlit as st

import pandas as pd
import sqlite3
import json
from supabase import create_client

from utils.tracker_balances import latest_balances_from_account_df


class WeightLossValidationError(ValueError):
    """Raised when a write violates a weight-loss invariant."""


class DatabaseHandler(ABC):
    @abstractmethod
    def load_account_data(self):
        pass

    @abstractmethod
    def save_account_value(self, date, account, value):
        pass

    @abstractmethod
    def update_account_value(self, date, account, value):
        pass

    @abstractmethod
    def delete_entries_by_date(self, date):
        pass


class SQLiteHandler(DatabaseHandler):
    _instance = None

    def __new__(cls, db_path="net_worth.db"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.conn = sqlite3.connect(db_path, check_same_thread=False)
            cls._instance.create_table()
        return cls._instance

    def create_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS account_values (
                date TEXT,
                account TEXT,
                value REAL,
                PRIMARY KEY (date, account)
            )
        """)
        self.conn.commit()

    def load_account_data(self):
        return pd.read_sql_query("SELECT * FROM account_values", self.conn)

    def save_account_value(self, date, account, value):
        self.conn.execute("""
            INSERT OR REPLACE INTO account_values (date, account, value)
            VALUES (?, ?, ?)
        """, (date, account, value))
        self.conn.commit()

    def update_account_value(self, date, account, value):
        self.conn.execute("""
            UPDATE account_values
            SET value = ?
            WHERE date = ? AND account = ?
        """, (value, date, account))
        self.conn.commit()

    def delete_entries_by_date(self, date):
        self.conn.execute("DELETE FROM account_values WHERE date = ?", (date,))
        self.conn.commit()


class SupabaseHandler(DatabaseHandler):
    def __init__(self):
        """Initialize Supabase client"""
        supabase_url = st.secrets["supabase"]["url"]
        supabase_key = st.secrets["supabase"]["key"]
        self.supabase = create_client(supabase_url, supabase_key)

    def get_or_create_user(self, google_id: str, email: str, name: str) -> dict:
        """Get or create a user in the database"""
        try:
            # Try to get existing user
            response = self.supabase.table("users").select("*").eq("id", google_id).execute()
            if response.data:
                return response.data[0]

            # Create new user if not exists
            response = self.supabase.table("users").insert({
                "id": google_id,
                "email": email,
                "name": name
            }, returning='minimal').execute()
            
            # Fetch the user after creation
            response = self.supabase.table("users").select("*").eq("id", google_id).execute()
            return response.data[0]
        except Exception as e:
            logging.error(f"Error in get_or_create_user: {str(e)}")
            raise

    def get_user_categories(self, user_id: str) -> list:
        """Get all categories for a user"""
        try:
            response = self.supabase.table("categories").select("*").eq("user_id", user_id).execute()
            return response.data
        except Exception as e:
            logging.error(f"Error in get_user_categories: {str(e)}")
            return []

    def create_category(self, user_id: str, name: str) -> dict:
        """Create a new category"""
        try:
            # Check if category already exists
            existing = self.supabase.table("categories").select("*").eq("user_id", user_id).eq("name", name).execute()
            if existing.data:
                return existing.data[0]

            # Create new category if not exists
            response = self.supabase.table("categories").insert({
                "user_id": user_id,
                "name": name
            }, returning='minimal').execute()
            
            # Fetch the category after creation
            response = self.supabase.table("categories").select("*").eq("user_id", user_id).eq("name", name).execute()
            return response.data[0]
        except Exception as e:
            logging.error(f"Error in create_category: {str(e)}")
            raise

    def update_category(self, category_id: str, name: str) -> dict:
        """Update a category"""
        try:
            response = self.supabase.table("categories").update({
                "name": name
            }).eq("id", category_id).execute()
            return response.data[0]
        except Exception as e:
            logging.error(f"Error in update_category: {str(e)}")
            raise

    def delete_category(self, category_id: str):
        """Delete a category"""
        try:
            self.supabase.table("categories").delete().eq("id", category_id).execute()
        except Exception as e:
            logging.error(f"Error in delete_category: {str(e)}")
            raise

    def get_user_accounts(self, user_id: str) -> list:
        """Get all accounts for a user"""
        try:
            response = self.supabase.table("accounts") \
                .select(
                    "id, name, categories!inner(name)"
                ) \
                .eq("user_id", user_id) \
                .execute()
            
            return [{
                "id": acc["id"],
                "name": acc["name"],
                "category_name": acc["categories"]["name"]
            } for acc in response.data]
        except Exception as e:
            logging.error(f"Error in get_user_accounts: {str(e)}")
            return []

    def create_account(self, user_id: str, category_id: str, name: str) -> dict:
        """Create a new account"""
        try:
            # Check if account already exists
            existing = self.supabase.table("accounts").select("*").eq("user_id", user_id).eq("name", name).execute()
            if existing.data:
                return existing.data[0]

            # Create new account if not exists
            response = self.supabase.table("accounts").insert({
                "user_id": user_id,
                "category_id": category_id,
                "name": name
            }, returning='minimal').execute()
            
            # Fetch the account after creation
            response = self.supabase.table("accounts").select("*").eq("user_id", user_id).eq("name", name).execute()
            return response.data[0]
        except Exception as e:
            logging.error(f"Error in create_account: {str(e)}")
            raise

    def update_account(self, account_id: str, name: str) -> dict:
        """Update an account"""
        try:
            response = self.supabase.table("accounts").update({
                "name": name
            }).eq("id", account_id).execute()
            return response.data[0]
        except Exception as e:
            logging.error(f"Error in update_account: {str(e)}")
            raise

    def delete_account(self, account_id: str):
        """Delete an account"""
        try:
            self.supabase.table("accounts").delete().eq("id", account_id).execute()
        except Exception as e:
            logging.error(f"Error in delete_account: {str(e)}")
            raise

    def load_account_data(self, user_id: str) -> pd.DataFrame:
        """Load all account values with account and category names"""
        try:
            response = self.supabase.table("account_values") \
                .select(
                    "*, accounts!inner(id, name, categories(id, name))"
                ) \
                .eq("accounts.user_id", user_id) \
                .order("date", desc=True) \
                .execute()
            
            if not response.data:
                return pd.DataFrame()
            
            # Process the nested response into a flat DataFrame
            processed_data = []
            for record in response.data:
                account = record["accounts"]
                category = account["categories"]
                processed_data.append(
                    {
                        "account_id": record["account_id"],
                        "date": record["date"],
                        "value": record["value"],
                        "account_name": account["name"],
                        "category_name": category["name"],
                    }
                )

            df = pd.DataFrame(processed_data)
            # Convert date strings to datetime
            df["date"] = pd.to_datetime(df["date"]).dt.date
            # Ensure value is numeric
            df["value"] = pd.to_numeric(df["value"])
            # One row per (account, date); nested embeds can occasionally duplicate rows
            df = df.drop_duplicates(subset=["account_id", "date"], keep="last")
            return df.drop(columns=["account_id"])
        except Exception as e:
            logging.error(f"Error in load_account_data: {str(e)}")
            return pd.DataFrame()

    def get_latest_balances(
        self,
        user_id: str,
        group_by: str = "category",
        as_of_date: date | None = None,
    ) -> list[dict]:
        """Balance per account from tracker data (delegates to latest_balances_from_account_df)."""
        try:
            df = self.load_account_data(user_id)
            return latest_balances_from_account_df(df, group_by, as_of_date)
        except Exception as e:
            logging.error(f"Error in get_latest_balances: {str(e)}")
            return []

    def save_account_value(self, account_id: str, date: str, value: float) -> dict:
        """Save or update an account value"""
        try:
            # Format the value as a string with 2 decimal places
            formatted_value = "{:.2f}".format(value)
            
            response = self.supabase.table("account_values").upsert(
                {
                    "account_id": account_id,
                    "date": date,
                    "value": formatted_value
                },
                on_conflict="account_id,date",
                returning='minimal'
            ).execute()
            
            # Fetch the value after creation/update
            response = self.supabase.table("account_values").select("*").eq("account_id", account_id).eq("date", date).execute()
            return response.data[0]
        except Exception as e:
            logging.error(f"Error in save_account_value: {str(e)}")
            raise

    def update_account_value(self, account_name: str, date: str, value: float) -> dict:
        """Update an account value using account name and date"""
        try:
            # First get the account_id using the account name
            account_response = self.supabase.table("accounts").select("id").eq("name", account_name).single().execute()
            if not account_response.data:
                raise ValueError(f"Account {account_name} not found")
            
            account_id = account_response.data["id"]
            
            # Format the value as a string with 2 decimal places
            formatted_value = "{:.2f}".format(value)
            
            # Then update the value using account_id and date
            response = self.supabase.table("account_values") \
                .update({"value": formatted_value}) \
                .eq("account_id", account_id) \
                .eq("date", date) \
                .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            logging.error(f"Error in update_account_value: {str(e)}")
            raise

    def delete_entries_by_date(self, date: str, user_id: str):
        """Delete all entries for a specific date"""
        try:
            # First get all account IDs for the user
            accounts_response = self.supabase.table("accounts").select("id").eq("user_id", user_id).execute()
            account_ids = [acc["id"] for acc in accounts_response.data]
            
            # Then delete account values for those accounts on the specified date
            self.supabase.table("account_values").delete().eq("date", date).in_("account_id", account_ids).execute()
        except Exception as e:
            logging.error(f"Error in delete_entries_by_date: {str(e)}")
            raise

    def save_simulation_report(self, user_id: str, name: str, report_data: dict) -> dict:
        """Save or update a simulation report"""
        try:
            # Serialize report_data to JSON string
            report_json = json.dumps(report_data)
            
            # Check if report with same name exists for this user
            existing = self.supabase.table("simulation_reports") \
                .select("id") \
                .eq("user_id", user_id) \
                .eq("name", name) \
                .execute()
            
            if existing.data:
                # Update existing report
                response = self.supabase.table("simulation_reports") \
                    .update({
                        "report_data": report_json,
                        "updated_at": "now()"
                    }) \
                    .eq("id", existing.data[0]["id"]) \
                    .execute()
            else:
                # Insert new report
                response = self.supabase.table("simulation_reports") \
                    .insert({
                        "user_id": user_id,
                        "name": name,
                        "report_data": report_json
                    }) \
                    .execute()
            
            return response.data[0] if response.data else None
        except Exception as e:
            logging.error(f"Error in save_simulation_report: {str(e)}")
            raise

    def get_user_simulation_reports(self, user_id: str) -> list:
        """Get all simulation reports for a user (metadata only)"""
        try:
            response = self.supabase.table("simulation_reports") \
                .select("id, name, created_at, updated_at") \
                .eq("user_id", user_id) \
                .order("created_at", desc=True) \
                .execute()
            
            return response.data if response.data else []
        except Exception as e:
            logging.error(f"Error in get_user_simulation_reports: {str(e)}")
            return []

    def load_simulation_report(self, report_id: str, user_id: str) -> dict:
        """Load a full simulation report with data"""
        try:
            response = self.supabase.table("simulation_reports") \
                .select("*") \
                .eq("id", report_id) \
                .eq("user_id", user_id) \
                .single() \
                .execute()
            
            if not response.data:
                raise ValueError("Report not found or access denied")
            
            # Deserialize report_data from JSON
            report = response.data
            report["report_data"] = json.loads(report["report_data"])
            
            return report
        except Exception as e:
            logging.error(f"Error in load_simulation_report: {str(e)}")
            raise

    def delete_simulation_report(self, report_id: str, user_id: str):
        """Delete a simulation report"""
        try:
            # Verify ownership before deleting
            response = self.supabase.table("simulation_reports") \
                .delete() \
                .eq("id", report_id) \
                .eq("user_id", user_id) \
                .execute()
            
            if not response.data:
                raise ValueError("Report not found or access denied")
        except Exception as e:
            logging.error(f"Error in delete_simulation_report: {str(e)}")
            raise

    def rename_simulation_report(self, report_id: str, user_id: str, new_name: str) -> dict:
        """Rename a simulation report"""
        try:
            # Update report name, verifying ownership
            response = self.supabase.table("simulation_reports") \
                .update({
                    "name": new_name,
                    "updated_at": "now()"
                }) \
                .eq("id", report_id) \
                .eq("user_id", user_id) \
                .execute()
            
            if not response.data:
                raise ValueError("Report not found or access denied")
            
            return response.data[0]
        except Exception as e:
            logging.error(f"Error in rename_simulation_report: {str(e)}")
            raise

    # =============================================================
    # Weight Loss Tracker
    # =============================================================

    _VLCD_KCAL_FLOOR = 800
    _VLCD_MAX_DAYS = 84  # 12 weeks per NHS guidance
    _KCAL_BOUNDS = (400, 5000)

    def create_weight_plan(
        self,
        *,
        user_id: str,
        start_weight_kg: float,
        target_weight_kg: float,
        weekly_rate_kg: float,
        daily_kcal_target: int,
        weekly_exercise_min_target: int,
        start_date,
        target_date,
        sex: str | None,
        vlcd_acknowledged: bool,
    ) -> str:
        """Insert a new active plan. Returns its id."""
        if daily_kcal_target < self._VLCD_KCAL_FLOOR:
            if not vlcd_acknowledged:
                raise WeightLossValidationError(
                    "VLCD plans (<800 kcal) require acknowledgement."
                )
            if (target_date - start_date).days > self._VLCD_MAX_DAYS:
                raise WeightLossValidationError(
                    "VLCD plans cannot exceed 12 weeks (NHS guidance)."
                )
        if not (self._KCAL_BOUNDS[0] <= daily_kcal_target <= self._KCAL_BOUNDS[1]):
            raise WeightLossValidationError(
                f"daily_kcal_target out of bounds {self._KCAL_BOUNDS}"
            )
        if target_weight_kg >= start_weight_kg:
            raise WeightLossValidationError("target_weight must be less than start_weight")

        payload = {
            "user_id": user_id,
            "start_weight_kg": float(start_weight_kg),
            "target_weight_kg": float(target_weight_kg),
            "weekly_rate_kg": float(weekly_rate_kg),
            "daily_kcal_target": int(daily_kcal_target),
            "weekly_exercise_min_target": int(weekly_exercise_min_target),
            "start_date": start_date.isoformat(),
            "target_date": target_date.isoformat(),
            "sex": sex,
            "status": "active",
            "vlcd_acknowledged": bool(vlcd_acknowledged),
        }
        resp = (
            self.supabase.table("weight_plans")
            .insert(payload)
            .execute()
        )
        return resp.data[0]["id"]

    def get_active_weight_plan(self, user_id: str) -> dict | None:
        resp = (
            self.supabase.table("weight_plans")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def get_weight_plans(self, user_id: str) -> list[dict]:
        resp = (
            self.supabase.table("weight_plans")
            .select("*")
            .eq("user_id", user_id)
            .order("start_date", desc=True)
            .execute()
        )
        return resp.data or []

    def update_weight_plan(
        self,
        *,
        plan_id: str,
        user_id: str,
        daily_kcal_target: int | None = None,
        weekly_exercise_min_target: int | None = None,
        target_date=None,
    ) -> None:
        patch: dict = {}
        if daily_kcal_target is not None:
            patch["daily_kcal_target"] = int(daily_kcal_target)
        if weekly_exercise_min_target is not None:
            patch["weekly_exercise_min_target"] = int(weekly_exercise_min_target)
        if target_date is not None:
            patch["target_date"] = target_date.isoformat()
        if not patch:
            return

        # Re-validate post-edit invariants. Uses the stored plan to fill in any
        # field the caller didn't change.
        if daily_kcal_target is not None or target_date is not None:
            existing_resp = (
                self.supabase.table("weight_plans")
                .select("start_date, target_date, daily_kcal_target, vlcd_acknowledged")
                .eq("id", plan_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = existing_resp.data or []
            if not rows:
                raise WeightLossValidationError("plan not found")
            existing = rows[0]
            effective_kcal = (
                int(daily_kcal_target)
                if daily_kcal_target is not None
                else int(existing["daily_kcal_target"])
            )
            effective_target_date = (
                target_date
                if target_date is not None
                else date.fromisoformat(existing["target_date"])
            )
            existing_start_date = date.fromisoformat(existing["start_date"])
            vlcd_acknowledged = bool(existing.get("vlcd_acknowledged"))

            if effective_kcal < self._VLCD_KCAL_FLOOR:
                if not vlcd_acknowledged:
                    raise WeightLossValidationError(
                        "VLCD plans (<800 kcal) require acknowledgement."
                    )
                if (effective_target_date - existing_start_date).days > self._VLCD_MAX_DAYS:
                    raise WeightLossValidationError(
                        "VLCD plans cannot exceed 12 weeks (NHS guidance)."
                    )
            if not (self._KCAL_BOUNDS[0] <= effective_kcal <= self._KCAL_BOUNDS[1]):
                raise WeightLossValidationError(
                    f"daily_kcal_target out of bounds {self._KCAL_BOUNDS}"
                )

        patch["updated_at"] = "now()"
        (
            self.supabase.table("weight_plans")
            .update(patch)
            .eq("id", plan_id)
            .eq("user_id", user_id)
            .execute()
        )

    def abandon_weight_plan(self, *, plan_id: str, user_id: str) -> None:
        (
            self.supabase.table("weight_plans")
            .update({"status": "abandoned", "updated_at": "now()"})
            .eq("id", plan_id)
            .eq("user_id", user_id)
            .eq("status", "active")
            .execute()
        )

    def complete_and_start_next_plan(
        self,
        *,
        user_id: str,
        old_plan_id: str,
        current_weight_kg: float,
        new_target_weight_kg: float,
        new_target_date,
    ) -> str:
        """Call the atomic RPC; returns the id of the freshly-created plan."""
        resp = self.supabase.rpc(
            "complete_and_start_next_plan",
            {
                "p_user_id": user_id,
                "p_old_plan_id": old_plan_id,
                "p_current_weight_kg": float(current_weight_kg),
                "p_new_target_weight_kg": float(new_target_weight_kg),
                "p_new_target_date": new_target_date.isoformat(),
            },
        ).execute()
        return resp.data

    # ---- entry CRUD -------------------------------------------------

    _WEIGHT_BOUNDS = (20.0, 400.0)
    _KCAL_ENTRY_BOUNDS = (0, 20000)
    _DURATION_MIN_BOUNDS = (1, 1440)
    _ALLOWED_INTENSITIES = ("moderate", "vigorous")
    _ALLOWED_SOURCES = ("manual", "barcode")

    def save_weight_entry(
        self, *, user_id: str, log_date, weight_kg: float, notes: str | None = None
    ) -> dict:
        if not (self._WEIGHT_BOUNDS[0] <= weight_kg <= self._WEIGHT_BOUNDS[1]):
            raise WeightLossValidationError(
                f"weight_kg must be in {self._WEIGHT_BOUNDS}"
            )
        payload = {
            "user_id": user_id,
            "log_date": log_date.isoformat(),
            "weight_kg": float(weight_kg),
            "notes": notes,
        }
        resp = (
            self.supabase.table("weight_entries")
            .upsert(payload, on_conflict="user_id,log_date")
            .execute()
        )
        return (resp.data or [{}])[0]

    def save_food_entry(
        self,
        *,
        user_id: str,
        log_date,
        name: str,
        kcal: float,
        portion_g: float | None = None,
        protein_g: float | None = None,
        carbs_g: float | None = None,
        fat_g: float | None = None,
        fibre_g: float | None = None,
        sugar_g: float | None = None,
        log_time=None,
        barcode: str | None = None,
        source: str = "manual",
    ) -> dict:
        if not (self._KCAL_ENTRY_BOUNDS[0] <= kcal <= self._KCAL_ENTRY_BOUNDS[1]):
            raise WeightLossValidationError(
                f"kcal must be in {self._KCAL_ENTRY_BOUNDS}"
            )
        if source not in self._ALLOWED_SOURCES:
            raise WeightLossValidationError(
                f"source must be one of {self._ALLOWED_SOURCES}"
            )
        if not name:
            raise WeightLossValidationError("name is required")

        payload = {
            "user_id": user_id,
            "log_date": log_date.isoformat(),
            "log_time": log_time.isoformat() if log_time else None,
            "name": name,
            "portion_g": float(portion_g) if portion_g is not None else None,
            "kcal": float(kcal),
            "protein_g": float(protein_g) if protein_g is not None else None,
            "carbs_g": float(carbs_g) if carbs_g is not None else None,
            "fat_g": float(fat_g) if fat_g is not None else None,
            "fibre_g": float(fibre_g) if fibre_g is not None else None,
            "sugar_g": float(sugar_g) if sugar_g is not None else None,
            "barcode": barcode,
            "source": source,
        }
        resp = self.supabase.table("food_entries").insert(payload).execute()
        return (resp.data or [{}])[0]

    def save_exercise_entry(
        self,
        *,
        user_id: str,
        log_date,
        activity: str,
        intensity: str,
        duration_min: int,
        kcal_burned: float | None = None,
        notes: str | None = None,
    ) -> dict:
        if intensity not in self._ALLOWED_INTENSITIES:
            raise WeightLossValidationError(
                f"intensity must be one of {self._ALLOWED_INTENSITIES}"
            )
        if not (self._DURATION_MIN_BOUNDS[0] <= duration_min <= self._DURATION_MIN_BOUNDS[1]):
            raise WeightLossValidationError(
                f"duration_min must be in {self._DURATION_MIN_BOUNDS}"
            )
        if not activity:
            raise WeightLossValidationError("activity is required")

        payload = {
            "user_id": user_id,
            "log_date": log_date.isoformat(),
            "activity": activity,
            "intensity": intensity,
            "duration_min": int(duration_min),
            "kcal_burned": float(kcal_burned) if kcal_burned is not None else None,
            "notes": notes,
        }
        resp = self.supabase.table("exercise_entries").insert(payload).execute()
        return (resp.data or [{}])[0]

    def delete_food_entry(self, *, entry_id: str, user_id: str) -> None:
        (
            self.supabase.table("food_entries")
            .delete()
            .eq("id", entry_id)
            .eq("user_id", user_id)
            .execute()
        )

    def delete_exercise_entry(self, *, entry_id: str, user_id: str) -> None:
        (
            self.supabase.table("exercise_entries")
            .delete()
            .eq("id", entry_id)
            .eq("user_id", user_id)
            .execute()
        )

    def update_food_entry(self, *, entry_id: str, user_id: str, **fields) -> dict:
        if not fields:
            return {}
        # Whitelist columns to prevent injection-by-typo.
        allowed = {
            "name", "portion_g", "kcal", "protein_g", "carbs_g", "fat_g",
            "fibre_g", "sugar_g", "log_time", "log_date",
        }
        patch = {k: v for k, v in fields.items() if k in allowed}
        if not patch:
            return {}
        for k in ("log_date", "log_time"):
            if k in patch and hasattr(patch[k], "isoformat"):
                patch[k] = patch[k].isoformat()

        # Re-validate post-edit invariants (spec §7.2).
        if "kcal" in patch:
            kcal = patch["kcal"]
            if not (self._KCAL_ENTRY_BOUNDS[0] <= kcal <= self._KCAL_ENTRY_BOUNDS[1]):
                raise WeightLossValidationError(
                    f"kcal must be in {self._KCAL_ENTRY_BOUNDS}"
                )
        if "name" in patch and not patch["name"]:
            raise WeightLossValidationError("name is required")

        resp = (
            self.supabase.table("food_entries")
            .update(patch)
            .eq("id", entry_id)
            .eq("user_id", user_id)
            .execute()
        )
        return (resp.data or [{}])[0]

    def update_exercise_entry(self, *, entry_id: str, user_id: str, **fields) -> dict:
        if not fields:
            return {}
        allowed = {
            "activity", "intensity", "duration_min", "kcal_burned", "notes", "log_date",
        }
        patch = {k: v for k, v in fields.items() if k in allowed}
        if not patch:
            return {}
        if "log_date" in patch and hasattr(patch["log_date"], "isoformat"):
            patch["log_date"] = patch["log_date"].isoformat()

        # Re-validate post-edit invariants (spec §7.2).
        if "intensity" in patch and patch["intensity"] not in self._ALLOWED_INTENSITIES:
            raise WeightLossValidationError(
                f"intensity must be one of {self._ALLOWED_INTENSITIES}"
            )
        if "duration_min" in patch:
            d = patch["duration_min"]
            if not (self._DURATION_MIN_BOUNDS[0] <= d <= self._DURATION_MIN_BOUNDS[1]):
                raise WeightLossValidationError(
                    f"duration_min must be in {self._DURATION_MIN_BOUNDS}"
                )
        if "activity" in patch and not patch["activity"]:
            raise WeightLossValidationError("activity is required")

        resp = (
            self.supabase.table("exercise_entries")
            .update(patch)
            .eq("id", entry_id)
            .eq("user_id", user_id)
            .execute()
        )
        return (resp.data or [{}])[0]

    def load_recent_logs(
        self, user_id: str, since_date
    ) -> tuple["pd.DataFrame", "pd.DataFrame", "pd.DataFrame"]:
        """Return (food_df, exercise_df, weight_df) since ``since_date``."""
        food_resp = (
            self.supabase.table("food_entries")
            .select("*")
            .eq("user_id", user_id)
            .gte("log_date", since_date.isoformat())
            .order("log_date", desc=False)
            .execute()
        )
        ex_resp = (
            self.supabase.table("exercise_entries")
            .select("*")
            .eq("user_id", user_id)
            .gte("log_date", since_date.isoformat())
            .order("log_date", desc=False)
            .execute()
        )
        weight_resp = (
            self.supabase.table("weight_entries")
            .select("*")
            .eq("user_id", user_id)
            .gte("log_date", since_date.isoformat())
            .order("log_date", desc=False)
            .execute()
        )

        def _df(rows, date_cols):
            df = pd.DataFrame(rows or [])
            for c in date_cols:
                if c in df.columns and not df.empty:
                    df[c] = pd.to_datetime(df[c]).dt.date
            return df

        return (
            _df(food_resp.data, ["log_date"]),
            _df(ex_resp.data, ["log_date"]),
            _df(weight_resp.data, ["log_date"]),
        )

    # ---- badges ----------------------------------------------------

    def record_earned_badges(self, user_id: str, new_badges: list) -> None:
        """Insert NewBadge rows. No-op for empty input.

        Uses upsert with ignore_duplicates=True to absorb races against
        the UNIQUE(user_id, badge_key, earned_on) constraint.
        """
        if not new_badges:
            return
        rows = [
            {
                "user_id": user_id,
                "badge_key": b.badge_key,
                "earned_on": b.earned_on.isoformat(),
                "points": b.points,
                "metadata": b.metadata,
            }
            for b in new_badges
        ]
        (
            self.supabase.table("earned_badges")
            .upsert(rows, on_conflict="user_id,badge_key,earned_on", ignore_duplicates=True)
            .execute()
        )

    def get_earned_badges(self, user_id: str) -> list[dict]:
        resp = (
            self.supabase.table("earned_badges")
            .select("*")
            .eq("user_id", user_id)
            .order("earned_on", desc=True)
            .execute()
        )
        return resp.data or []

    def already_earned_keys(self, user_id: str) -> set:
        """Return the set understood by badges.evaluate's ``already_earned``.

        For plan-scoped badges (those with metadata.plan_id), produces
        3-tuples (key, earned_on, plan_id). Otherwise 2-tuples (key, earned_on).
        """
        from datetime import date as _date

        out = set()
        for row in self.get_earned_badges(user_id):
            key = row["badge_key"]
            earned_on = row["earned_on"]
            if isinstance(earned_on, str):
                earned_on = pd.to_datetime(earned_on).date()
            elif not isinstance(earned_on, _date):
                earned_on = pd.to_datetime(earned_on).date()
            meta = row.get("metadata") or {}
            plan_id = meta.get("plan_id")
            if plan_id is not None:
                out.add((key, earned_on, plan_id))
            else:
                out.add((key, earned_on))
        return out
