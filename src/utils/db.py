from abc import ABC, abstractmethod
import logging
import os
import streamlit as st

import pandas as pd
import sqlite3
import json
from supabase import create_client


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
                processed_data.append({
                    "date": record["date"],
                    "value": record["value"],
                    "account_name": account["name"],
                    "category_name": category["name"]
                })
            
            df = pd.DataFrame(processed_data)
            # Convert date strings to datetime
            df["date"] = pd.to_datetime(df["date"]).dt.date
            # Ensure value is numeric
            df["value"] = pd.to_numeric(df["value"])
            return df
        except Exception as e:
            logging.error(f"Error in load_account_data: {str(e)}")
            return pd.DataFrame()

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
