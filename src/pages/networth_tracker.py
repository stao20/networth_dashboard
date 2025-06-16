import streamlit as st
import pandas as pd
import plotly.express as px
from typing import Dict, List

from config import Config
from utils.auth import GoogleAuth

db_handler = Config.DB_HANDLER
auth = GoogleAuth()

# Initialize session state for categories and accounts
if "categories" not in st.session_state:
    st.session_state.categories = []
if "accounts" not in st.session_state:
    st.session_state.accounts = []

def load_user_data(user_id: str):
    """Load user's categories and accounts"""
    st.session_state.categories = db_handler.get_user_categories(user_id)
    st.session_state.accounts = db_handler.get_user_accounts(user_id)

# Authentication
st.title(
    "Net Worth Tracking Dashboard"
    + (":money_with_wings: " if Config.is_prod() else ":dollar:")
)

user_info = auth.login_button()

if not user_info:
    st.warning("Please log in to access your net worth dashboard.")
    st.stop()

user_id, user_email, user_name = user_info
db_handler.get_or_create_user(user_id, user_email, user_name)
load_user_data(user_id)

# Show logout button in sidebar
with st.sidebar:
    st.write(f"Welcome, {user_name}!")
    if st.button("Logout"):
        auth.logout()

# Category Management
st.header("Category Management")
col1, col2 = st.columns(2)

with col1:
    new_category = st.text_input("New Category Name")
    if st.button("Add Category"):
        if new_category:
            db_handler.create_category(user_id, new_category)
            load_user_data(user_id)
            st.success(f"Category '{new_category}' added successfully!")

with col2:
    if st.session_state.categories:
        category_to_edit = st.selectbox(
            "Select Category to Edit/Delete",
            options=[cat["name"] for cat in st.session_state.categories],
            key="category_select"
        )
        selected_category = next(cat for cat in st.session_state.categories if cat["name"] == category_to_edit)
        
        new_name = st.text_input("New Category Name", value=category_to_edit)
        col3, col4 = st.columns(2)
        
        with col3:
            if st.button("Update Category"):
                db_handler.update_category(selected_category["id"], new_name)
                load_user_data(user_id)
                st.success(f"Category updated to '{new_name}'!")
        
        with col4:
            if st.button("Delete Category"):
                db_handler.delete_category(selected_category["id"])
                load_user_data(user_id)
                st.success(f"Category '{category_to_edit}' deleted!")

# Account Management
st.header("Account Management")
col5, col6 = st.columns(2)

with col5:
    if st.session_state.categories:
        new_account_category = st.selectbox(
            "Select Category",
            options=[cat["name"] for cat in st.session_state.categories],
            key="new_account_category"
        )
        selected_category = next(cat for cat in st.session_state.categories if cat["name"] == new_account_category)
        
        new_account_name = st.text_input("New Account Name")
        if st.button("Add Account"):
            if new_account_name:
                db_handler.create_account(user_id, selected_category["id"], new_account_name)
                load_user_data(user_id)
                st.success(f"Account '{new_account_name}' added successfully!")

with col6:
    if st.session_state.accounts:
        account_to_edit = st.selectbox(
            "Select Account to Edit/Delete",
            options=[acc["name"] for acc in st.session_state.accounts],
            key="account_select"
        )
        selected_account = next(acc for acc in st.session_state.accounts if acc["name"] == account_to_edit)
        
        new_account_name = st.text_input("New Account Name", value=account_to_edit)
        col7, col8 = st.columns(2)
        
        with col7:
            if st.button("Update Account"):
                db_handler.update_account(selected_account["id"], new_account_name)
                load_user_data(user_id)
                st.success(f"Account updated to '{new_account_name}'!")
        
        with col8:
            if st.button("Delete Account"):
                db_handler.delete_account(selected_account["id"])
                load_user_data(user_id)
                st.success(f"Account '{account_to_edit}' deleted!")

# Account Value Entry Form
st.header("Account Values")
date = st.date_input("Date")

if st.session_state.accounts:
    account = st.selectbox(
        "Select Account",
        options=[acc["name"] for acc in st.session_state.accounts]
    )
    selected_account = next(acc for acc in st.session_state.accounts if acc["name"] == account)
    
account_value = st.number_input("Account Value", step=100.0)

if st.button("Add/Update Account Value"):
    db_handler.save_account_value(selected_account["id"], date.strftime("%Y-%m-%d"), account_value)
    st.success(f"Account {account} value for {date} saved successfully!")

# Remove Entries by Date
st.header("Remove Entries")
delete_date = st.date_input("Date to Remove")
if st.button("Remove All Entries for Date"):
    db_handler.delete_entries_by_date(delete_date.strftime("%Y-%m-%d"), user_id)
    st.success(f"All entries for {delete_date} have been removed.")

# Display Account Data
st.header("Account Value Records")
account_data = db_handler.load_account_data(user_id)

if not account_data.empty:
    net_worth_df = account_data.groupby("date")["value"].sum().reset_index()
    net_worth_df.columns = ["date", "net_worth"]
    
    edited_df = st.data_editor(
        account_data,
        num_rows="dynamic",
        column_config={
            "value": st.column_config.NumberColumn(
                "Value",
                help="Edit the account value",
                min_value=0,
                format="%.2f",
                step=100
            ),
            "date": st.column_config.DateColumn(
                "Date",
                help="Date of the entry"
            ),
            "account_name": st.column_config.TextColumn(
                "Account",
                help="Account name"
            ),
            "category_name": st.column_config.TextColumn(
                "Category",
                help="Category name"
            )
        },
        disabled=["date", "account_name", "category_name"],
        hide_index=True
    )
    
    # Check for changes and update the database
    if not edited_df.equals(account_data):
        for index, row in edited_df.iterrows():
            if row["value"] != account_data.loc[index, "value"]:
                db_handler.update_account_value(
                    account_name=row["account_name"],
                    date=row["date"].strftime("%Y-%m-%d"),
                    value=row["value"]
                )
        st.success("Updated the database with changes.")
    
    st.header("Net Worth Summary")
    st.dataframe(net_worth_df)
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
    for category in st.session_state.categories:
        category_name = category["name"]
        # Get accounts for this category using names
        category_accounts = [acc["name"] for acc in st.session_state.accounts if acc["category_name"] == category_name]
        
        if category_accounts:
            # Filter account data for this category
            category_df = account_data[account_data["account_name"].isin(category_accounts)]
            
            if not category_df.empty:
                # Sum values by date for this category
                category_df = category_df.groupby("date")["value"].sum().reset_index()
                category_df["date"] = pd.to_datetime(category_df["date"])
                
                # Add line to plot
                fig_category.add_scatter(
                    x=category_df["date"],
                    y=category_df["value"],
                    mode="lines+markers",
                    name=category_name,
                )
    
    st.plotly_chart(fig_category)
else:
    st.info("No data to display. Add some records!")

# Distribution Analysis
if not account_data.empty:
    st.header("Distribution Analysis")
    
    # Date selector for distribution analysis
    available_dates = sorted(account_data["date"].unique(), reverse=True)
    selected_date = st.selectbox("Select Date for Distribution Analysis", available_dates)
    
    # Get data for selected date
    selected_date_data = account_data[account_data["date"] == selected_date]
    
    col9, col10 = st.columns(2)
    
    with col9:
        st.subheader("Category Distribution")
        category_totals = selected_date_data.groupby("category_name")["value"].sum()
        if not category_totals.empty:
            fig_category_pie = px.pie(
                values=category_totals.values,
                names=category_totals.index,
                title=f"Category Distribution as of {selected_date}"
        )
            st.plotly_chart(fig_category_pie)
        else:
            st.info("No category data available for the selected date.")
    
    with col10:
        st.subheader("Account Distribution")
        account_totals = selected_date_data.groupby("account_name")["value"].sum()
        if not account_totals.empty:
            fig_account_pie = px.pie(
                values=account_totals.values,
                names=account_totals.index,
                title=f"Account Distribution as of {selected_date}"
            )
            st.plotly_chart(fig_account_pie)
        else:
            st.info("No account data available for the selected date.")
else:
    st.info("No data to display. Add some records!")

