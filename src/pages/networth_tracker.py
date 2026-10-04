import json
import uuid
from datetime import date as date_cls

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, List

from config import Config
from utils.auth import GoogleAuth
from utils.crypto import decrypt_secret, encrypt_secret, load_fernet_key
from utils.providers.base import ProviderError
from utils.providers.open_banking import OpenBankingProvider, create_requisition, exchange_token
from utils.providers.trading212 import DEFAULT_BASE as TRADING212_LIVE_BASE, Trading212Provider
from utils.sync.orchestrator import run_sync
from utils.sync.undo import undo_sync_run
from utils.currency import get_currency_list, convert_currency, format_currency, get_currency_display_name
from utils.tracker_balances import custom_group_members, custom_group_name_error, normalize_custom_groups

db_handler = Config.DB_HANDLER
auth = GoogleAuth()

# Initialize session state for categories and accounts
if "categories" not in st.session_state:
    st.session_state.categories = []
if "accounts" not in st.session_state:
    st.session_state.accounts = []
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Overview"
if "analytics_custom_groups" not in st.session_state:
    st.session_state.analytics_custom_groups = []

def load_user_data(user_id: str):
    """Load user's categories and accounts"""
    st.session_state.categories = db_handler.get_user_categories(user_id)
    st.session_state.accounts = db_handler.get_user_accounts(user_id)


TRADING212_DEMO_BASE = "https://demo.trading212.com/api/v0"
STATUS_BADGES = {
    "active": "🟢 active",
    "needs_reauth": "🟠 needs re-authentication",
    "error": "🔴 error",
    "disabled": "⚪ disabled",
}
PROVIDER_LABELS = {"trading212": "Trading 212", "open_banking": "Open Banking"}


def _gocardless_secrets():
    """Return (secret_id, secret_key, redirect_url) or None when not configured."""
    try:
        section = st.secrets["gocardless"]
        return section["secret_id"], section["secret_key"], section.get("redirect_url", "")
    except Exception:
        return None


def _sync_key_error():
    try:
        load_fernet_key()
        return None
    except Exception as e:
        return str(e)


def _connection_label(conn: dict) -> str:
    provider = PROVIDER_LABELS.get(conn["provider"], conn["provider"])
    return f"{provider} - {conn.get('display_name') or conn['external_connection_id']}"


def _fetch_external_accounts(connections: list) -> tuple:
    """Read-only balance fetch across active connections. Returns (accounts, errors)."""
    providers = {"trading212": Trading212Provider(), "open_banking": OpenBankingProvider()}
    found, errors = [], []
    for conn in connections:
        if conn.get("status") != "active":
            continue
        provider = providers.get(conn["provider"])
        if provider is None:
            continue
        try:
            row = dict(conn)
            row["credentials"] = json.loads(decrypt_secret(conn["credentials_encrypted"]))
            for bal in provider.list_balances(row):
                found.append(
                    {
                        "connection_id": conn["id"],
                        "connection_label": _connection_label(conn),
                        "external_account_id": bal.external_account_id,
                        "name": bal.name,
                        "currency": bal.currency,
                        "amount": float(bal.amount),
                    }
                )
        except ProviderError as e:
            errors.append(f"{_connection_label(conn)}: {e}")
        except Exception as e:
            errors.append(f"{_connection_label(conn)}: {type(e).__name__}")
    return found, errors


def _render_trading212_connect(user_id: str) -> None:
    with st.expander("Connect Trading 212"):
        with st.form("trading212_connect_form", clear_on_submit=True):
            display_name = st.text_input("Display name", value="Trading 212")
            api_key = st.text_input("API key", type="password")
            api_secret = st.text_input("API secret", type="password")
            use_demo = st.checkbox("Use demo environment (demo.trading212.com)")
            submitted = st.form_submit_button("Save Trading 212 connection")
        if submitted:
            if not api_key.strip() or not api_secret.strip():
                st.warning("API key and secret are required.")
                return
            creds = {
                "api_key": api_key.strip(),
                "api_secret": api_secret.strip(),
                "base_url": TRADING212_DEMO_BASE if use_demo else TRADING212_LIVE_BASE,
            }
            try:
                db_handler.upsert_provider_connection(
                    user_id,
                    "trading212",
                    "default",
                    encrypt_secret(json.dumps(creds)),
                    display_name=display_name.strip() or "Trading 212",
                )
                st.success("Trading 212 connection saved.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save connection: {type(e).__name__}")


def _render_open_banking_connect(user_id: str) -> None:
    with st.expander("Connect a bank (Open Banking via GoCardless)"):
        gc = _gocardless_secrets()
        if gc is None:
            st.info(
                "Open Banking is not configured. Add `[gocardless]` with `secret_id` and "
                "`secret_key` to the app secrets to enable it."
            )
            return
        secret_id, secret_key, default_redirect = gc

        institution_id = st.text_input(
            "Institution ID", placeholder="e.g. SANDBOXFINANCE_SFIN0000", key="ob_institution_id"
        )
        bank_name = st.text_input("Display name", value="Bank", key="ob_display_name")
        redirect_url = st.text_input(
            "Redirect URL (where the bank sends you back)",
            value=default_redirect or "http://localhost:8501",
            key="ob_redirect_url",
        )
        if st.button("Start bank link", key="ob_start_link"):
            if not institution_id.strip():
                st.warning("Enter an institution ID.")
            else:
                try:
                    req = create_requisition(
                        secret_id,
                        secret_key,
                        institution_id.strip(),
                        redirect_url.strip(),
                        reference=uuid.uuid4().hex,
                    )
                    if not req.get("link") or not req.get("requisition_id"):
                        st.error("GoCardless did not return a link.")
                    else:
                        st.session_state.ob_pending_requisition = req["requisition_id"]
                        st.session_state.ob_pending_link = req["link"]
                except ProviderError as e:
                    st.error(f"Could not start bank link: {e}")
                except Exception as e:
                    st.error(f"Could not start bank link: {type(e).__name__}")

        pending_link = st.session_state.get("ob_pending_link")
        if pending_link:
            st.link_button("1. Open bank authorisation page", pending_link)
            st.caption("Authorise access at your bank, then come back here and finish linking.")

        requisition_id = st.text_input(
            "Requisition ID",
            value=st.session_state.get("ob_pending_requisition", ""),
            key="ob_requisition_id",
        )
        if st.button("2. I've finished linking", key="ob_finish_link"):
            if not requisition_id.strip():
                st.warning("Enter the requisition ID from the link step.")
            else:
                try:
                    tokens = exchange_token(secret_id, secret_key)
                    creds = {
                        "access_token": tokens["access"],
                        "refresh_token": tokens.get("refresh"),
                        "requisition_id": requisition_id.strip(),
                    }
                    db_handler.upsert_provider_connection(
                        user_id,
                        "open_banking",
                        requisition_id.strip(),
                        encrypt_secret(json.dumps(creds)),
                        display_name=bank_name.strip() or "Bank",
                    )
                    st.session_state.pop("ob_pending_link", None)
                    st.session_state.pop("ob_pending_requisition", None)
                    st.success("Bank connection saved.")
                    st.rerun()
                except ProviderError as e:
                    st.error(f"Could not finish linking: {e}")
                except Exception as e:
                    st.error(f"Could not finish linking: {type(e).__name__}")


def _render_connections(connections: list) -> None:
    if not connections:
        st.caption("No connections yet.")
        return
    for conn in connections:
        info_col, button_col = st.columns([5, 1])
        status = STATUS_BADGES.get(conn.get("status"), conn.get("status", "unknown"))
        info_col.markdown(f"**{_connection_label(conn)}** — {status}")
        details = []
        if conn.get("last_synced_at"):
            details.append(f"last synced {conn['last_synced_at']}")
        if conn.get("last_error"):
            details.append(f"last error: {conn['last_error']}")
        if details:
            info_col.caption("; ".join(details))
        if button_col.button("Disconnect", key=f"disconnect_{conn['id']}"):
            try:
                db_handler.delete_provider_connection(conn["id"])
                st.session_state.pop("sync_external_accounts", None)
                st.rerun()
            except Exception as e:
                st.error(f"Could not disconnect: {type(e).__name__}")


def _render_mappings(user_id: str, connections: list) -> None:
    st.markdown("#### Account mapping")
    mappings = db_handler.list_account_mappings(user_id)
    accounts = st.session_state.accounts
    account_by_id = {acc["id"]: acc for acc in accounts}
    conn_by_id = {c["id"]: c for c in connections}

    if st.button("Refresh external accounts", key="refresh_external_accounts", disabled=not connections):
        with st.spinner("Fetching balances (read-only)..."):
            found, errors = _fetch_external_accounts(connections)
        st.session_state.sync_external_accounts = found
        st.session_state.sync_external_errors = errors

    for err in st.session_state.get("sync_external_errors", []):
        st.warning(err)

    if mappings:
        st.caption("Current mappings")
        for m in mappings:
            conn = conn_by_id.get(m["provider_connection_id"])
            acc = account_by_id.get(m["account_id"])
            text_col, button_col = st.columns([5, 1])
            text_col.write(
                f"{_connection_label(conn) if conn else 'Unknown connection'}: "
                f"{m['external_account_name']} → {acc['name'] if acc else 'Unknown account'}"
            )
            if button_col.button("Unmap", key=f"unmap_{m['id']}"):
                try:
                    db_handler.delete_account_mapping(m["id"])
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not remove mapping: {type(e).__name__}")

    external = st.session_state.get("sync_external_accounts")
    if external is None:
        st.caption("Click 'Refresh external accounts' to list accounts from your connections.")
        return
    if not external:
        st.info("No external accounts found.")
        return

    st.caption("External accounts")
    for ext in external:
        key = (ext["connection_id"], ext["external_account_id"])
        current = next(
            (
                m
                for m in mappings
                if (m["provider_connection_id"], m["external_account_id"]) == key
            ),
            None,
        )
        taken = {
            m["account_id"]
            for m in mappings
            if (m["provider_connection_id"], m["external_account_id"]) != key
        }
        options = [acc for acc in accounts if acc["id"] not in taken]
        label = (
            f"{ext['connection_label']}: {ext['name']} "
            f"({ext['amount']:,.2f} {ext['currency']})"
        )
        if not options:
            st.write(label)
            st.caption("No unmapped tracker accounts available.")
            continue
        ids = [acc["id"] for acc in options]
        index = ids.index(current["account_id"]) if current and current["account_id"] in ids else None
        widget_key = f"map_{ext['connection_id']}_{ext['external_account_id']}"
        sel_col, save_col = st.columns([4, 1])
        selected_id = sel_col.selectbox(
            label,
            options=ids,
            index=index,
            format_func=lambda i: account_by_id[i]["name"],
            placeholder="Choose tracker account",
            key=widget_key,
        )
        save_col.write("")
        if save_col.button("Save", key=f"save_{widget_key}", disabled=selected_id is None):
            try:
                db_handler.upsert_account_mapping(
                    user_id,
                    ext["connection_id"],
                    ext["external_account_id"],
                    ext["name"],
                    selected_id,
                )
                st.success(f"Mapped {ext['name']} to {account_by_id[selected_id]['name']}.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not save mapping: {type(e).__name__}")


def _render_sync(user_id: str) -> None:
    st.markdown("#### Sync")
    sync_col, button_col = st.columns([2, 1])
    as_of = sync_col.date_input("Sync as-of date", value=date_cls.today(), key="sync_as_of_date")
    button_col.write("")
    if button_col.button("Sync now", key="sync_now", type="primary"):
        with st.spinner("Syncing..."):
            try:
                result = run_sync(db_handler, user_id, as_of, trigger="manual")
            except Exception as e:
                st.error(f"Sync failed: {type(e).__name__}")
                result = None
        if result:
            counts = (
                f"{result.get('written_count', 0)} written, "
                f"{result.get('skipped_count', 0)} skipped, "
                f"{result.get('error_count', 0)} errors"
            )
            status = result.get("status")
            if status == "success":
                st.success(f"Sync complete: {counts}.")
            elif status == "partial":
                st.warning(f"Sync partially succeeded: {counts}.")
            else:
                st.error(f"Sync failed: {counts}. {result.get('notes') or ''}")

    runs = db_handler.list_sync_runs(user_id, limit=10)
    if not runs:
        st.caption("No sync runs yet.")
        return
    st.caption("Recent runs")
    runs_df = pd.DataFrame(
        [
            {
                "Started": r.get("started_at"),
                "As of": r.get("as_of_date"),
                "Trigger": r.get("trigger"),
                "Status": "undone" if r.get("undone_at") else r.get("status"),
                "Written": r.get("written_count"),
                "Skipped": r.get("skipped_count"),
                "Errors": r.get("error_count"),
            }
            for r in runs
        ]
    )
    st.dataframe(runs_df, hide_index=True, use_container_width=True)

    for r in runs:
        title = f"{r.get('started_at')} — {r.get('as_of_date')} — {r.get('status')}"
        with st.expander(title):
            if r.get("notes"):
                st.caption(r["notes"])
            items = db_handler.list_sync_run_items(r["id"])
            if items:
                st.dataframe(
                    pd.DataFrame(items)[
                        [
                            c
                            for c in (
                                "provider",
                                "external_account_id",
                                "outcome",
                                "reason",
                                "external_amount",
                                "external_currency",
                                "previous_value_gbp",
                                "new_value_gbp",
                            )
                            if c in items[0]
                        ]
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.caption("No items recorded.")
            if r.get("undone_at"):
                st.caption(f"Undone at {r['undone_at']}.")
            elif st.button("Undo this sync", key=f"undo_{r['id']}"):
                try:
                    outcome = undo_sync_run(db_handler, user_id, r["id"])
                    st.success(
                        f"Undone: {outcome['restored']} restored, {outcome['deleted']} deleted, "
                        f"{outcome['skipped']} skipped (edited since sync)."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Undo failed: {type(e).__name__}")


def render_connections_and_sync(user_id: str) -> None:
    st.subheader("Connections & Sync")
    st.caption(
        "Connect Trading 212 or a bank, map external accounts to tracker accounts, and "
        "pull balances into Account Values."
    )
    key_error = _sync_key_error()
    if key_error:
        st.warning(
            f"Account sync is unavailable: {key_error}. Set `SYNC_CREDENTIALS_KEY` or "
            "`[sync] credentials_key` in the app secrets (a Fernet key)."
        )
        return

    try:
        connections = db_handler.list_provider_connections(user_id)
    except Exception as e:
        st.error(f"Could not load connections: {type(e).__name__}")
        return

    _render_connections(connections)
    _render_trading212_connect(user_id)
    _render_open_banking_connect(user_id)
    _render_mappings(user_id, connections)
    _render_sync(user_id)

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

        def compute_change(period_key: str):
            """Compute both percentage and absolute value change"""
            if net_worth_series.empty:
                return None, None
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
                return None, None
            # Clamp to available range
            if start_idx < net_worth_series.index.min():
                start_idx = net_worth_series.index.min()
            if start_idx > latest_idx:
                start_idx = latest_idx
            prior_val = float(net_worth_series.loc[start_idx])
            if prior_val == 0:
                return None, None
            value_change = latest_val - prior_val
            pct_change = (value_change / prior_val) * 100.0
            return value_change, pct_change

        # Period selector driving the metric and initial chart window
        period_options = ["1d", "1w", "1m", "3m", "YTD", "1y", "3y", "5y", "MAX"]
        current_period = st.session_state.get("networth_change_period_overview", "1m")
        st.radio(
            "Period",
            options=period_options,
            index=period_options.index(current_period) if current_period in period_options else 2,
            key="networth_change_period_overview",
            horizontal=True,
            label_visibility="hidden",
        )
        current_period = st.session_state.get("networth_change_period_overview", "1m")
        value_change, pct_change = compute_change(current_period)

        col1, col2, col3 = st.columns(3)
        
        with col1:
            if value_change is not None and pct_change is not None:
                sign = "+" if value_change >= 0 else "-"
                delta_text = f"{sign}£{abs(value_change):,.2f} ({pct_change:+.2f}%)"
            else:
                delta_text = "N/A"
            st.metric(
                "Current Net Worth (GBP)",
                f"£{latest_total:,.2f}",
                delta=delta_text
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

    render_connections_and_sync(user_id)

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
        # "fixed" = only rows from the DB (dynamic adds blank rows and looks like extra records)
        edited_df = st.data_editor(
            account_data,
            num_rows="fixed",
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

        # Account Trends — each account is its own line, unless the user
        # combines chosen accounts into a session-only custom group.
        st.subheader("Account Trends")
        st.caption(
            "Each account is its own line. Add a custom group to combine chosen accounts into one line for this session. Groups are not saved."
        )

        accounts = st.session_state.accounts
        account_names = list(dict.fromkeys(acc["name"] for acc in accounts))
        name_to_id = {acc["name"]: acc["id"] for acc in accounts}
        custom_groups = normalize_custom_groups(st.session_state.analytics_custom_groups, accounts)
        st.session_state.analytics_custom_groups = custom_groups

        with st.expander("Add a custom group"):
            with st.form("add_analytics_custom_group"):
                group_name = st.text_input("Group name")
                group_accounts = st.multiselect(
                    "Accounts",
                    options=account_names,
                    disabled=not account_names,
                )
                add_group = st.form_submit_button("Add group")
            if add_group:
                cleaned_name = group_name.strip()
                selected_ids = []
                for selected_name in group_accounts:
                    account_id = name_to_id.get(selected_name)
                    if account_id is not None and account_id not in selected_ids:
                        selected_ids.append(account_id)
                name_error = custom_group_name_error(
                    cleaned_name,
                    [group["name"] for group in custom_groups],
                    account_names,
                )
                if name_error:
                    st.warning(name_error)
                elif not selected_ids:
                    st.warning("Select at least one account.")
                else:
                    custom_groups.append({"name": cleaned_name, "account_ids": selected_ids})
                    st.success(f"Added group '{cleaned_name}'.")

        group_series = custom_group_members(custom_groups, accounts)
        grouped_names = {name for _, members in group_series for name in members}

        remove_index = None
        for index, (group_name, members) in enumerate(group_series):
            label = ", ".join(members) if members else "no current accounts"
            group_col, remove_col = st.columns([5, 1])
            group_col.text(f"{group_name} — {label}")
            if remove_col.button("Remove", key=f"remove_analytics_group_{index}_{group_name}"):
                remove_index = index
        if remove_index is not None:
            custom_groups.pop(remove_index)
            st.rerun()

        fig_account = px.line(title="Account Trends Over Time")
        for group_name, members in group_series:
            if not members:
                continue
            group_df = account_data[account_data["account_name"].isin(members)]
            if group_df.empty:
                continue
            group_df = group_df.groupby("date")["value"].sum().reset_index()
            group_df["date"] = pd.to_datetime(group_df["date"])
            fig_account.add_scatter(
                x=group_df["date"],
                y=group_df["value"],
                mode="lines+markers",
                name=group_name,
            )
        for account in accounts:
            account_name = account["name"]
            if account_name in grouped_names:
                continue
            account_df = account_data[account_data["account_name"] == account_name]
            if account_df.empty:
                continue
            account_df = account_df.sort_values("date")
            account_df["date"] = pd.to_datetime(account_df["date"])
            fig_account.add_scatter(
                x=account_df["date"],
                y=account_df["value"],
                mode="lines+markers",
                name=account_name,
            )
        fig_account.update_layout(
            xaxis_title="Date",
            yaxis_title="Value (GBP £)",
            hovermode="x unified"
        )
        st.plotly_chart(fig_account, use_container_width=True)
        
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

