import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List

from config import Config
from utils.auth import GoogleAuth
from utils.currency import get_currency_list, convert_currency, format_currency, get_currency_display_name

db_handler = Config.DB_HANDLER
auth = GoogleAuth()

# Initialize session state for categories and accounts
if "categories" not in st.session_state:
    st.session_state.categories = []
if "accounts" not in st.session_state:
    st.session_state.accounts = []
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Overview"

def load_user_data(user_id: str):
    """Load user's categories and accounts"""
    st.session_state.categories = db_handler.get_user_categories(user_id)
    st.session_state.accounts = db_handler.get_user_accounts(user_id)

# Set page config for a wider layout
st.set_page_config(layout="wide", page_title="Net Worth Dashboard")

# Custom CSS
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 10px 20px;
        background-color: #f0f2f6;
    }
    .stTabs [aria-selected="true"] {
        background-color: #4CAF50 !important;
        color: white !important;
    }
    div[data-testid="stToolbar"] {
        display: none;
    }
    .st-emotion-cache-1y4p8pa {
        max-width: 100%;
    }
    /* Period toolbar styling */
    #period-toolbar [role="radiogroup"] {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        align-items: center;
    }
    #period-toolbar [role="radiogroup"] label {
        padding: 4px 10px;
        border: 1px solid #e3e6eb;
        border-radius: 10px;
        background: #f7f9fc;
        color: #5f6c7b;
        cursor: pointer;
        transition: all .15s ease;
        font-weight: 500;
        font-size: 0.9rem;
        text-transform: uppercase;
    }
    #period-toolbar [role="radiogroup"] label:hover {
        background: #eef2f7;
    }
    #period-toolbar [role="radiogroup"] label[data-checked="true"]{
        background: #e8f5ec;
        color: #2c7a4b;
        border-color: #bfe3cc;
    }
    #period-toolbar {
        display: flex;
        justify-content: flex-start;
        align-items: center;
        gap: 8px;
        padding: 4px 0 0 0;
    }
    </style>
""", unsafe_allow_html=True)

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

# Load account data before creating tabs
account_data = db_handler.load_account_data(user_id)

# Main navigation tabs
tabs = st.tabs([
    "📊 Overview",
    "🗂️ Categories & Accounts",
    "💰 Account Values",
    "📈 Analytics"
])

# Overview Tab
with tabs[0]:
    if not account_data.empty:
        # Summary metrics
        # Prepare net worth time series and change periods
        latest_date = account_data["date"].max()

        # Build daily forward-filled net worth series for change calculations (extend to today)
        net_worth_df = account_data.groupby("date")["value"].sum().reset_index()
        net_worth_df.columns = ["date", "net_worth"]
        net_worth_df["date"] = pd.to_datetime(net_worth_df["date"]).dt.normalize()
        net_worth_series = net_worth_df.set_index("date")["net_worth"].sort_index()
        if not net_worth_series.empty:
            today = pd.Timestamp("today").normalize()
            full_index = pd.date_range(net_worth_series.index.min(), today, freq="D")
            net_worth_series = net_worth_series.reindex(full_index).ffill()

        # Latest for metrics should be today's value (ffilled if missing)
        latest_total = float(net_worth_series.loc[pd.Timestamp("today").normalize()]) if not net_worth_series.empty else 0.0

        def compute_pct_change(period_key: str):
            if net_worth_series.empty:
                return None
            latest_idx = pd.Timestamp("today").normalize()
            latest_val = float(net_worth_series.loc[latest_idx])
            # Determine comparison start date
            if period_key == "YTD":
                start_idx = latest_idx.replace(month=1, day=1)
            elif period_key == "1d":
                start_idx = latest_idx - pd.DateOffset(days=1)
            elif period_key == "1w":
                start_idx = latest_idx - pd.DateOffset(weeks=1)
            elif period_key == "1m":
                start_idx = latest_idx - pd.DateOffset(months=1)
            elif period_key == "3m":
                start_idx = latest_idx - pd.DateOffset(months=3)
            elif period_key == "1y":
                start_idx = latest_idx - pd.DateOffset(years=1)
            elif period_key == "3y":
                start_idx = latest_idx - pd.DateOffset(years=3)
            elif period_key == "5y":
                start_idx = latest_idx - pd.DateOffset(years=5)
            elif period_key == "MAX":
                start_idx = net_worth_series.index.min()
            else:
                return None
            # Clamp to available range
            if start_idx < net_worth_series.index.min():
                start_idx = net_worth_series.index.min()
            if start_idx > latest_idx:
                start_idx = latest_idx
            prior_val = float(net_worth_series.loc[start_idx])
            if prior_val == 0:
                return None
            return (latest_val - prior_val) / prior_val * 100.0

        # Period selector driving the metric and initial chart window
        period_options = ["1d", "1w", "1m", "3m", "YTD", "1y", "3y", "5y", "MAX"]
        current_period = st.session_state.get("networth_change_period_overview", "1m")
        st.radio(
            "",
            options=period_options,
            index=period_options.index(current_period) if current_period in period_options else 2,
            key="networth_change_period_overview",
            horizontal=True,
        )
        current_period = st.session_state.get("networth_change_period_overview", "1m")
        pct_change = compute_pct_change(current_period)

        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric(
                "Current Net Worth (GBP)",
                f"£{latest_total:,.2f}",
                delta=(f"{pct_change:.2f}%" if pct_change is not None else "N/A")
            )
        
        with col2:
            num_accounts = len(st.session_state.accounts)
            st.metric("Total Accounts", num_accounts)
        
        with col3:
            num_categories = len(st.session_state.categories)
            st.metric("Total Categories", num_categories)
        
        # Net Worth Chart
        st.subheader("Net Worth Trend")
        # Determine start date for chart range based on selection
        def get_start_date_for_chart(period_key: str):
            if net_worth_series.empty:
                return None
            latest_idx = net_worth_series.index.max()
            if period_key == "MAX":
                return None
            if period_key == "YTD":
                return latest_idx.replace(month=1, day=1)
            if period_key == "1d":
                return latest_idx - pd.DateOffset(days=1)
            if period_key == "1w":
                return latest_idx - pd.DateOffset(weeks=1)
            if period_key == "1m":
                return latest_idx - pd.DateOffset(months=1)
            if period_key == "3m":
                return latest_idx - pd.DateOffset(months=3)
            if period_key == "1y":
                return latest_idx - pd.DateOffset(years=1)
            if period_key == "3y":
                return latest_idx - pd.DateOffset(years=3)
            if period_key == "5y":
                return latest_idx - pd.DateOffset(years=5)
            return None

        # Always plot full history using the forward-filled series extended to today
        plot_df = net_worth_series.reset_index()
        plot_df.columns = ["date", "net_worth"]

        # Area chart for a look similar to stock charts
        fig_networth = px.area(
            plot_df,
            x="date",
            y="net_worth",
            title="Net Worth Over Time",
            markers=True,
        )
        fig_networth.update_layout(
            xaxis_title="Date",
            yaxis_title="Net Worth (GBP £)",
            hovermode="x unified"
        )
        fig_networth.update_traces(line=dict(width=2.5), marker=dict(size=5))
        # Highlight the latest data point
        latest_idx_for_plot = pd.Timestamp("today").normalize()
        if not net_worth_series.empty and latest_idx_for_plot in net_worth_series.index:
            latest_val_for_plot = float(net_worth_series.loc[latest_idx_for_plot])
            fig_networth.add_trace(go.Scatter(
                x=[latest_idx_for_plot],
                y=[latest_val_for_plot],
                mode="markers",
                marker=dict(size=10, color="#2E86AB", line=dict(color="#ffffff", width=2)),
                name="Latest",
                showlegend=False,
            ))
        # In-chart period selector (rangeselector)
        fig_networth.update_xaxes(
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1d", step="day", stepmode="backward"),
                    dict(count=7, label="1w", step="day", stepmode="backward"),
                    dict(count=1, label="1m", step="month", stepmode="backward"),
                    dict(count=3, label="3m", step="month", stepmode="backward"),
                    dict(step="year", stepmode="todate", label="YTD"),
                    dict(count=1, label="1y", step="year", stepmode="backward"),
                    dict(count=3, label="3y", step="year", stepmode="backward"),
                    dict(count=5, label="5y", step="year", stepmode="backward"),
                    dict(step="all", label="MAX"),
                ],
                bgcolor="#ffffff",
                activecolor="#e8f5ec",
                font=dict(color="#5f6c7b"),
            ),
            rangeslider=dict(visible=False),
        )
        # Set initial visible range to match the selected period
        start_visible = get_start_date_for_chart(current_period)
        if start_visible is not None:
            fig_networth.update_xaxes(range=[pd.to_datetime(start_visible), net_worth_series.index.max()])
        st.plotly_chart(fig_networth, use_container_width=True)

        
        # Distribution Analysis
        st.subheader("Current Distribution")
        latest_data = account_data[account_data["date"] == latest_date]
        
        col4, col5 = st.columns(2)
        with col4:
            category_totals = latest_data.groupby("category_name")["value"].sum()
            if not category_totals.empty:
                fig_category_pie = px.pie(
                    values=category_totals.values,
                    names=category_totals.index,
                    title="Category Distribution"
                )
                st.plotly_chart(fig_category_pie, use_container_width=True)
        
        with col5:
            account_totals = latest_data.groupby("account_name")["value"].sum()
            if not account_totals.empty:
                fig_account_pie = px.pie(
                    values=account_totals.values,
                    names=account_totals.index,
                    title="Account Distribution"
                )
                st.plotly_chart(fig_account_pie, use_container_width=True)
    else:
        st.info("No data available yet. Start by adding some accounts and their values!")

# Categories & Accounts Tab
with tabs[1]:
    st.subheader("Category Management")
    cat_col1, cat_col2 = st.columns(2)
    
    with cat_col1:
        with st.form("add_category_form"):
            new_category = st.text_input("New Category Name")
            submit_category = st.form_submit_button("Add Category")
            if submit_category and new_category:
                db_handler.create_category(user_id, new_category)
                load_user_data(user_id)
                st.success(f"Category '{new_category}' added successfully!")
    
    with cat_col2:
        if st.session_state.categories:
            with st.form("edit_category_form"):
                category_to_edit = st.selectbox(
                    "Select Category to Edit/Delete",
                    options=[cat["name"] for cat in st.session_state.categories],
                    key="category_select"
                )
                selected_category = next(cat for cat in st.session_state.categories if cat["name"] == category_to_edit)
                new_name = st.text_input("New Category Name", value=category_to_edit)
                
                col1, col2 = st.columns(2)
                with col1:
                    update_cat = st.form_submit_button("Update Category")
                with col2:
                    delete_cat = st.form_submit_button("Delete Category", type="secondary")
                
                if update_cat:
                    db_handler.update_category(selected_category["id"], new_name)
                    load_user_data(user_id)
                    st.success(f"Category updated to '{new_name}'!")
                elif delete_cat:
                    db_handler.delete_category(selected_category["id"])
                    load_user_data(user_id)
                    st.success(f"Category '{category_to_edit}' deleted!")
    
    st.divider()
    
    st.subheader("Account Management")
    acc_col1, acc_col2 = st.columns(2)
    
    with acc_col1:
        if st.session_state.categories:
            with st.form("add_account_form"):
                new_account_category = st.selectbox(
                    "Select Category",
                    options=[cat["name"] for cat in st.session_state.categories],
                    key="new_account_category"
                )
                selected_category = next(cat for cat in st.session_state.categories if cat["name"] == new_account_category)
                new_account_name = st.text_input("New Account Name")
                
                # Currency selection
                currency_options = get_currency_list()
                default_currency = 'GBP'
                selected_currency = st.selectbox(
                    "Currency",
                    options=currency_options,
                    index=currency_options.index(default_currency) if default_currency in currency_options else 0,
                    format_func=lambda x: f"{x} - {get_currency_display_name(x)}",
                    key="new_account_currency"
                )
                
                submit_account = st.form_submit_button("Add Account")
                
                if submit_account and new_account_name:
                    db_handler.create_account(user_id, selected_category["id"], new_account_name)
                    load_user_data(user_id)
                    st.success(f"Account '{new_account_name}' added successfully!")
    
    with acc_col2:
        if st.session_state.accounts:
            with st.form("edit_account_form"):
                account_to_edit = st.selectbox(
                    "Select Account to Edit/Delete",
                    options=[acc["name"] for acc in st.session_state.accounts],
                    key="account_select"
                )
                selected_account = next(acc for acc in st.session_state.accounts if acc["name"] == account_to_edit)
                new_account_name = st.text_input("New Account Name", value=account_to_edit)
                
                col1, col2 = st.columns(2)
                with col1:
                    update_acc = st.form_submit_button("Update Account")
                with col2:
                    delete_acc = st.form_submit_button("Delete Account", type="secondary")
                
                if update_acc:
                    db_handler.update_account(selected_account["id"], new_account_name)
                    load_user_data(user_id)
                    st.success(f"Account updated to '{new_account_name}'!")
                elif delete_acc:
                    db_handler.delete_account(selected_account["id"])
                    load_user_data(user_id)
                    st.success(f"Account '{account_to_edit}' deleted!")

# Account Values Tab
with tabs[2]:
    st.subheader("Add/Update Account Values")
    st.info("💱 **Currency Support**: You can enter account values in any currency. They will be automatically converted to GBP (British Pounds) and stored in the database. All charts and displays show values in GBP.")
    with st.form("account_value_form"):
        val_col1, val_col2, val_col3, val_col4 = st.columns(4)
        
        with val_col1:
            date = st.date_input("Date")
        
        with val_col2:
            if st.session_state.accounts:
                account = st.selectbox(
                    "Select Account",
                    options=[acc["name"] for acc in st.session_state.accounts]
                )
                selected_account = next(acc for acc in st.session_state.accounts if acc["name"] == account)
        
        with val_col3:
            # Currency selection for the value
            currency_options = get_currency_list()
            default_currency = 'GBP'
            value_currency = st.selectbox(
                "Currency",
                options=currency_options,
                index=currency_options.index(default_currency) if default_currency in currency_options else 0,
                format_func=lambda x: f"{x} - {get_currency_display_name(x)}",
                key="value_currency"
            )
        
        with val_col4:
            account_value = st.number_input(
                f"Account Value ({value_currency})",
                min_value=0.0,
                max_value=1e12,
                value=0.0,
                step=0.01,
                format="%.2f",
                help=f"Enter the account value in {value_currency}"
            )
        
        # Show conversion preview
        if account_value > 0 and value_currency != 'GBP':
            converted_value = convert_currency(account_value, value_currency, 'GBP')
            if converted_value is not None:
                st.info(f"💱 **Conversion Preview**: {format_currency(account_value, value_currency)} = {format_currency(converted_value, 'GBP')}")
            else:
                st.warning("⚠️ Could not convert currency. Please check your internet connection or try again later.")
        
        submit_value = st.form_submit_button("Add/Update Account Value")
        if submit_value:
            try:
                # Convert to GBP if needed
                final_value = account_value
                if value_currency != 'GBP':
                    converted_value = convert_currency(account_value, value_currency, 'GBP')
                    if converted_value is not None:
                        final_value = converted_value
                        st.info(f"✅ Converted {format_currency(account_value, value_currency)} to {format_currency(final_value, 'GBP')} and saved to database.")
                    else:
                        st.error("❌ Currency conversion failed. Please try again or use GBP.")
                        st.stop()
                
                db_handler.save_account_value(selected_account["id"], date.strftime("%Y-%m-%d"), final_value)
                st.success(f"Account {account} value for {date} saved successfully!")
                # Refresh the page to show the new data
                st.rerun()
            except Exception as e:
                st.error(f"Error saving account value: {str(e)}")
    
    st.divider()
    
    # Remove Entries Section
    st.subheader("Remove Entries")
    with st.form("remove_entries_form"):
        delete_date = st.date_input("Select Date to Remove")
        submit_delete = st.form_submit_button("Remove All Entries for Date")
        if submit_delete:
            db_handler.delete_entries_by_date(delete_date.strftime("%Y-%m-%d"), user_id)
            st.success(f"All entries for {delete_date} have been removed.")
    
    st.divider()
    
    # Account Value Records
    st.subheader("Account Value Records")
    account_data = db_handler.load_account_data(user_id)
    
    if not account_data.empty:
        edited_df = st.data_editor(
            account_data,
            num_rows="dynamic",
            column_config={
                "value": st.column_config.NumberColumn(
                    "Value",
                    help="Edit the account value",
                    min_value=0,
                    max_value=1e12,  # Set a reasonable maximum
                    format="%.2f",
                    step=0.01,  # Allow finer control
                    default=0.00
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
            hide_index=True,
            key="account_values_editor"  # Add a unique key
        )
        
        # Check for changes and update the database
        if not edited_df.equals(account_data):
            try:
                for index, row in edited_df.iterrows():
                    if row["value"] != account_data.loc[index, "value"]:
                        # Format the value before updating
                        formatted_value = float(row["value"])
                        db_handler.update_account_value(
                            account_name=row["account_name"],
                            date=row["date"].strftime("%Y-%m-%d"),
                            value=formatted_value
                        )
                st.success("Updated the database with changes.")
                # Refresh the data
                st.rerun()
            except Exception as e:
                st.error(f"Error updating values: {str(e)}")
    else:
        st.info("No account data to display. Add some records!")

# Analytics Tab
with tabs[3]:
    if not account_data.empty:
        # Category Trends
        st.subheader("Category Trends")
        fig_category = px.line(title="Category Trends Over Time")
        for category in st.session_state.categories:
            category_name = category["name"]
            category_accounts = [acc["name"] for acc in st.session_state.accounts if acc["category_name"] == category_name]
            
            if category_accounts:
                category_df = account_data[account_data["account_name"].isin(category_accounts)]
                
                if not category_df.empty:
                    category_df = category_df.groupby("date")["value"].sum().reset_index()
                    category_df["date"] = pd.to_datetime(category_df["date"])
                    
                    fig_category.add_scatter(
                        x=category_df["date"],
                        y=category_df["value"],
                        mode="lines+markers",
                        name=category_name,
                    )
        
        fig_category.update_layout(
            xaxis_title="Date",
            yaxis_title="Value (GBP £)",
            hovermode="x unified"
        )
        st.plotly_chart(fig_category, use_container_width=True)
        
        # Historical Distribution Analysis
        st.subheader("Historical Distribution Analysis")
        available_dates = sorted(account_data["date"].unique(), reverse=True)
        selected_date = st.selectbox("Select Date for Distribution Analysis", available_dates)
        
        selected_date_data = account_data[account_data["date"] == selected_date]
        
        col1, col2 = st.columns(2)
        
        with col1:
            category_totals = selected_date_data.groupby("category_name")["value"].sum()
            if not category_totals.empty:
                fig_category_pie = px.pie(
                    values=category_totals.values,
                    names=category_totals.index,
                    title=f"Category Distribution as of {selected_date}"
                )
                st.plotly_chart(fig_category_pie, use_container_width=True)
            else:
                st.info("No category data available for the selected date.")
        
        with col2:
            account_totals = selected_date_data.groupby("account_name")["value"].sum()
            if not account_totals.empty:
                fig_account_pie = px.pie(
                    values=account_totals.values,
                    names=account_totals.index,
                    title=f"Account Distribution as of {selected_date}"
                )
                st.plotly_chart(fig_account_pie, use_container_width=True)
            else:
                st.info("No account data available for the selected date.")
    else:
        st.info("No data available for analysis. Add some records to see insights!")

