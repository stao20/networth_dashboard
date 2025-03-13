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
        query = """CREATE TABLE IF NOT EXISTS account_values (
            date TEXT,
            account TEXT,
            value REAL,
            PRIMARY KEY (date, account)
        )"""
        self.conn.execute(query)
        self.conn.commit()

    def load_account_data(self):
        query = "SELECT * FROM account_values"
        return pd.read_sql(query, self.conn)

    def save_account_value(self, date, account, value):
        query = """INSERT OR REPLACE INTO account_values (date, account, value)
                   VALUES (?, ?, ?)"""
        self.conn.execute(query, (date, account, value))
        self.conn.commit()

    def update_account_value(self, date, account, value):
        query = """UPDATE account_values SET value = ? WHERE date = ? AND account = ?"""
        self.conn.execute(query, (value, date, account))
        self.conn.commit()

    def delete_entries_by_date(self, date):
        query = "DELETE FROM account_values WHERE date = ?"
        self.conn.execute(query, (date,))
        self.conn.commit()


class SupabaseHandler(DatabaseHandler):
    def __init__(self):
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        if not SUPABASE_URL or not SUPABASE_KEY:
            from dotenv import load_dotenv

            load_dotenv()
            logging.info("Loading environment variables")
            SUPABASE_URL = os.getenv("SUPABASE_URL")
            SUPABASE_KEY = os.getenv("SUPABASE_KEY")

        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    def load_account_data(self):
        response = self.supabase.table("account_values").select("*").execute()
        return pd.DataFrame(response.data)

    def save_account_value(self, date, account, value):
        self.supabase.table("account_values").upsert(
            {"date": date, "account": account, "value": value}
        ).execute()

    def update_account_value(self, date, account, value):
        self.supabase.table("account_values").update({"value": value}).match(
            {"date": date, "account": account}
        ).execute()

    def delete_entries_by_date(self, date):
        self.supabase.table("account_values").delete().match({"date": date}).execute()
