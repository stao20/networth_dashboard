import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
from enum import StrEnum

# Set the database file path
DB_PATH = "net_worth.db"

st.title("Net Worth Tracking Dashboard")


class Account(StrEnum):
    TRADING212_INVEST_STOCK = "Trading212 Invest Stock"
    TRADING212_INVEST_CASH = "Trading212 Invest Cash"
    TRADING212_STOCK_ISA = "Trading212 Stock ISA"
    TRADING212_CASH_ISA = "Trading212 Cash ISA"
    TRADING212_CFD = "Trading212 CFD"
    CLUB_LLOYDS_MONTHLY_SAVER = "Club Lloyds Monthly Saver"
    LLOYDS_MONTHLY_SAVER = "Lloyds Monthly Saver"
    CHASE_SAVER = "Chase Saver"
    CHASE_CURRENT_ACCOUNT = "Chase Current Account"
    CHASE_ROUND_UP_ACCOUNT = "Chase Round Up Account"
    NS_AND_I = "NS&I"
    L_AND_G = "L&G"


# Account categories and accounts
def get_accounts():
    return {
        "Invest": [
            Account.TRADING212_INVEST_STOCK,
            Account.TRADING212_STOCK_ISA,
            Account.TRADING212_CFD,
        ],
        "Cash": [
            Account.TRADING212_INVEST_CASH,
            Account.TRADING212_CASH_ISA,
            Account.CLUB_LLOYDS_MONTHLY_SAVER,
            Account.LLOYDS_MONTHLY_SAVER,
            Account.CHASE_CURRENT_ACCOUNT,
            Account.CHASE_ROUND_UP_ACCOUNT,
            Account.NS_AND_I,
        ],
        "Pension": [Account.L_AND_G],
    }


# Create database connection and tables
def create_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS account_values (date TEXT, account TEXT, value REAL, PRIMARY KEY (date, account))"""
    )
    return conn


# Load account values data
def load_account_data():
    conn = create_connection()
    data = pd.read_sql_query(
        "SELECT * FROM account_values ORDER BY date, account", conn
    )
    conn.close()
    return data


# Save an account value to SQLite
def save_account_value(date, account, value):
    conn = create_connection()
    conn.execute(
        "INSERT OR REPLACE INTO account_values (date, account, value) VALUES (?, ?, ?)",
        (date, account, value),
    )
    conn.commit()
    conn.close()


# Update an existing account value
def update_account_value(date, account, value):
    conn = create_connection()
    conn.execute(
        "UPDATE account_values SET value = ? WHERE date = ? AND account = ?",
        (value, date, account),
    )
    conn.commit()
    conn.close()


# Delete all entries for a specific date
def delete_entries_by_date(date):
    conn = create_connection()
    conn.execute("DELETE FROM account_values WHERE date = ?", (date,))
    conn.commit()
    conn.close()


# Load existing account data
account_data = load_account_data()
accounts = get_accounts()

# Account Value Entry Form
st.header("Account Values")
date = st.date_input("Date")
category = st.selectbox("Select Category", list(accounts.keys()))
account = st.selectbox("Select Account", accounts[category])
account_value = st.number_input("Account Value", step=100.0)

if st.button("Add/Update Account Value"):
    save_account_value(date.strftime("%Y-%m-%d"), account, account_value)
    st.success(f"Account {account} value for {date} saved successfully!")
    account_data = load_account_data()

# Remove Entries by Date
st.header("Remove Entries")
delete_date = st.date_input("Date to Remove")
if st.button("Remove All Entries for Date"):
    delete_entries_by_date(delete_date.strftime("%Y-%m-%d"))
    st.success(f"All entries for {delete_date} have been removed.")
    account_data = load_account_data()

# Display Account Data
st.header("Account Value Records")
if not account_data.empty:
    net_worth_df = account_data.groupby("date")["value"].sum().reset_index()
    net_worth_df.columns = ["date", "net_worth"]
    edited_df = st.data_editor(
        account_data,
        num_rows="dynamic",
        disabled=["account", "date"],
        hide_index=True,
    )
    # Check for changes and update the database
    if not edited_df.equals(account_data):
        for index, row in edited_df.iterrows():
            update_account_value(row["date"], row["account"], row["value"])
        st.success("Updated the database with changes.")
    st.header("Net Worth Summary")
    st.dataframe(net_worth_df, hide_index=True)
else:
    st.info("No account data to display. Add some records!")

# Plotting Line Charts
st.header("Net Worth Over Time")
if not account_data.empty:
    net_worth_df["date"] = pd.to_datetime(net_worth_df["date"])
    fig_networth = px.line(
        net_worth_df, x="date", y="net_worth", title="Net Worth Over Time", markers=True
    )
    st.plotly_chart(fig_networth)

    # Combined category plot
    fig_category = px.line(title="Category Trends Over Time")
    for category, acc_list in accounts.items():
        category_df = account_data[account_data["account"].isin(acc_list)]
        if not category_df.empty:
            category_df = category_df.groupby("date")["value"].sum().reset_index()
            category_df["date"] = pd.to_datetime(category_df["date"])
            fig_category.add_scatter(
                x=category_df["date"],
                y=category_df["value"],
                mode="lines+markers",
                name=category,
            )
    st.plotly_chart(fig_category)
else:
    st.info("No data to display. Add some records!")
