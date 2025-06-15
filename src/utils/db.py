from abc import ABC, abstractmethod
import logging
import os

import pandas as pd
import sqlite3
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
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
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
            response = self.supabase.table("accounts").select("*").eq("user_id", user_id).execute()
            return response.data
        except Exception as e:
            logging.error(f"Error in get_user_accounts: {str(e)}")
            return []

    def create_account(self, user_id: str, category_id: str, name: str) -> dict:
        """Create a new account"""
        try:
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
            response = self.supabase.table("account_values").select(
                "account_values.id",
                "account_values.date",
                "account_values.value",
                "accounts.name:account_name",
                "accounts.id:account_id",
                "categories.name:category_name"
            ).eq("accounts.user_id", user_id).execute()
            
            if not response.data:
                return pd.DataFrame()
            
            return pd.DataFrame(response.data)
        except Exception as e:
            logging.error(f"Error in load_account_data: {str(e)}")
            return pd.DataFrame()

    def save_account_value(self, account_id: str, date: str, value: float) -> dict:
        """Save an account value"""
        try:
            response = self.supabase.table("account_values").insert({
                "account_id": account_id,
                "date": date,
                "value": value
            }, returning='minimal').execute()
            
            # Fetch the value after creation
            response = self.supabase.table("account_values").select("*").eq("account_id", account_id).eq("date", date).execute()
            return response.data[0]
        except Exception as e:
            logging.error(f"Error in save_account_value: {str(e)}")
            raise

    def update_account_value(self, value_id: str, value: float) -> dict:
        """Update an account value"""
        try:
            response = self.supabase.table("account_values").update({
                "value": value
            }).eq("id", value_id).execute()
            return response.data[0]
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
