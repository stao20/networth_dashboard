import streamlit as st
import pandas as pd
import plotly.express as px
from enum import StrEnum

from config import Config

db_handler = Config.DB_HANDLER

st.title(
    "Net Worth Tracking Dashboard"
    + (":money_with_wings: " if Config.is_prod() else ":dollar:")
)


class Account(StrEnum):
    TRADING212_INVEST_CASH = "Trading212 Invest Cash"
    TRADING212_INVEST_INVEST = "Trading212 Invest Investments"
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
    REVOLUT_SAVER = "Revolut Saver"
    Q4U = "Q4U"


# Account categories and accounts
def get_accounts():
    return {
        "Invest": [
            Account.TRADING212_INVEST_INVEST,
            Account.TRADING212_STOCK_ISA,
            Account.TRADING212_CFD,
            Account.Q4U,
        ],
        "Cash": [
            Account.TRADING212_INVEST_CASH,
            Account.TRADING212_CASH_ISA,
            Account.CLUB_LLOYDS_MONTHLY_SAVER,
            Account.LLOYDS_MONTHLY_SAVER,
            Account.CHASE_SAVER,
            Account.CHASE_CURRENT_ACCOUNT,
            Account.CHASE_ROUND_UP_ACCOUNT,
            Account.REVOLUT_SAVER,
            Account.NS_AND_I,
        ],
        "Pension": [Account.L_AND_G],
    }


# Load existing account data
account_data = db_handler.load_account_data()
accounts = get_accounts()

# Account Value Entry Form
st.header("Account Values")
date = st.date_input("Date")
category = st.selectbox("Select Category", list(accounts.keys()))
account = st.selectbox("Select Account", accounts[category])
account_value = st.number_input("Account Value", step=100.0)

if st.button("Add/Update Account Value"):
    db_handler.save_account_value(date.strftime("%Y-%m-%d"), account, account_value)
    st.success(f"Account {account} value for {date} saved successfully!")
    account_data = db_handler.load_account_data()

# Remove Entries by Date
st.header("Remove Entries")
delete_date = st.date_input("Date to Remove")
if st.button("Remove All Entries for Date"):
    db_handler.delete_entries_by_date(delete_date.strftime("%Y-%m-%d"))
    st.success(f"All entries for {delete_date} have been removed.")
    account_data = db_handler.load_account_data()

# Display Account Data
st.header("Account Value Records")
if not account_data.empty:
    net_worth_df = account_data.groupby("date")["value"].sum().reset_index()
    net_worth_df.columns = ["date", "net_worth"]
    edited_df = st.data_editor(
        account_data,
        num_rows="dynamic",
        column_config={"value": {"editable": True}},
        disabled=["account", "date"],
    )
    # Check for changes and update the database
    if not edited_df.equals(account_data):
        for index, row in edited_df.iterrows():
            db_handler.update_account_value(row["date"], row["account"], row["value"])
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

# Distribution Analysis
if not account_data.empty:
    st.header("Distribution Analysis")
    
    # Date selector for distribution analysis
    available_dates = sorted(account_data['date'].unique(), reverse=True)
    selected_date = st.selectbox("Select Date for Distribution Analysis", available_dates)
    
    # Get data for selected date
    selected_date_data = account_data[account_data['date'] == selected_date]
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Category Distribution")
        # Calculate category totals
        category_totals = {}
        for category, acc_list in accounts.items():
            category_total = selected_date_data[selected_date_data['account'].isin(acc_list)]['value'].sum()
            if category_total != 0:  # Only include non-zero categories
                category_totals[category] = category_total
        
        if category_totals:
            fig_category_pie = px.pie(
                values=list(category_totals.values()),
                names=list(category_totals.keys()),
                title=f"Category Distribution as of {selected_date}"
            )
            st.plotly_chart(fig_category_pie)
        else:
            st.info("No category data available for the selected date.")
    
    with col2:
        st.subheader("Account Distribution")
        # Get account totals
        account_totals = selected_date_data.groupby('account')['value'].sum()
        account_totals = account_totals[account_totals != 0]  # Filter out zero values
        
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

