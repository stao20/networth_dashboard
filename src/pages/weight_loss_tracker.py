"""Weight loss tracker — main Streamlit page.

Spec: docs/superpowers/specs/2026-05-15-weight-loss-tracker-design.md
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from config import Config
from utils.auth import GoogleAuth
from utils.units import (
    APP_TZ,
    NHS_WEEKLY_MODERATE_MIN,
    estimate_kcal_burned,
    iso_week_bounds,
    moderate_equivalent_minutes,
    on_track_status,
    target_date_for_rate,
    today_local,
)
from utils.food_lookup import compute_portion, fetch_product
from utils.badges import BADGES, evaluate as evaluate_badges

st.set_page_config(layout="wide", page_title="Weight Loss Tracker")
st.title("🏋️ Weight Loss Tracker")
st.caption(
    "Plan, food, exercise, and rewards. Targets follow "
    "[NHS obesity treatment guidance](https://www.nhs.uk/conditions/obesity/treatment/)."
)

auth = GoogleAuth()
user_tuple = auth.login_button()
if user_tuple is None:
    st.stop()
user_id, user_email, user_name = user_tuple

db = Config.DB_HANDLER

tab_today, tab_history, tab_plan, tab_rewards = st.tabs(
    ["📅 Today", "📈 History", "🎯 Plan", "🏆 Rewards"]
)


@st.cache_data(ttl=60, show_spinner=False)
def _load_recent(user_id: str, since: date):
    return db.load_recent_logs(user_id, since)


def _invalidate_cache():
    _load_recent.clear()


# --- Plan tab is rendered first so other tabs can rely on the active plan. ---
active_plan = db.get_active_weight_plan(user_id)
plans = db.get_weight_plans(user_id)
plans_df = pd.DataFrame(plans)


def _render_create_plan_form():
    st.subheader("Let's set up your plan")
    with st.form("create_plan"):
        col1, col2 = st.columns(2)
        with col1:
            current_weight = st.number_input(
                "Current weight (kg)", min_value=30.0, max_value=400.0,
                value=80.0, step=0.1, format="%.1f",
            )
            sex = st.radio(
                "Sex (for default kcal target)",
                options=["Prefer not to say", "Male", "Female"],
                horizontal=True,
            )
        with col2:
            mode = st.radio(
                "Target",
                options=["NHS-recommended 3%", "Custom"],
                horizontal=True,
            )
            if mode == "NHS-recommended 3%":
                target_weight = round(current_weight * 0.97, 1)
                st.metric("Target weight", f"{target_weight} kg")
            else:
                target_weight = st.number_input(
                    "Target weight (kg)", min_value=20.0, max_value=399.0,
                    value=max(current_weight - 3.0, 20.0), step=0.1, format="%.1f",
                )

        rate_choice = st.radio(
            "Weekly rate (kg/week)",
            options=["0.5", "0.75", "1.0", "Custom"],
            horizontal=True,
        )
        weekly_rate = (
            float(rate_choice) if rate_choice != "Custom"
            else st.number_input("Custom rate", min_value=0.1, max_value=2.0, value=0.5, step=0.05)
        )

        default_kcal = {"Male": 1900, "Female": 1400}.get(sex, 1500)
        kcal_target = st.number_input(
            "Daily kcal target", min_value=400, max_value=5000,
            value=default_kcal, step=50,
        )
        weekly_exercise = st.number_input(
            "Weekly exercise target (minutes)",
            min_value=0, max_value=2000,
            value=NHS_WEEKLY_MODERATE_MIN, step=10,
        )

        vlcd = kcal_target < 800
        vlcd_ack = False
        if vlcd:
            st.warning(
                "⚠️ Daily target below 800 kcal is a **Very Low Calorie Diet (VLCD)**. "
                "NHS guidance is max 12 weeks under medical supervision."
            )
            vlcd_ack = st.checkbox("I understand and accept the VLCD risks.")

        start = today_local()
        projected_target_date = target_date_for_rate(
            start_weight_kg=current_weight,
            target_weight_kg=target_weight,
            weekly_rate_kg=weekly_rate,
            start_date=start,
        )
        st.caption(f"Projected target date: **{projected_target_date.isoformat()}** "
                   f"({(projected_target_date - start).days} days)")

        submitted = st.form_submit_button("Start plan", type="primary")
        if submitted:
            sex_code = {"Male": "M", "Female": "F"}.get(sex)
            try:
                db.create_weight_plan(
                    user_id=user_id,
                    start_weight_kg=current_weight,
                    target_weight_kg=target_weight,
                    weekly_rate_kg=weekly_rate,
                    daily_kcal_target=kcal_target,
                    weekly_exercise_min_target=weekly_exercise,
                    start_date=start,
                    target_date=projected_target_date,
                    sex=sex_code,
                    vlcd_acknowledged=vlcd_ack,
                )
                _invalidate_cache()
                st.success("Plan created.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


with tab_plan:
    if active_plan is None:
        _render_create_plan_form()
    else:
        st.info("Active plan exists. Active-cycle card comes in the next task.")


with tab_today:
    st.info("Today tab — implemented in Task 11.")

with tab_history:
    st.info("History tab — implemented in Task 16.")

with tab_rewards:
    st.info("Rewards tab — implemented in Task 17.")
