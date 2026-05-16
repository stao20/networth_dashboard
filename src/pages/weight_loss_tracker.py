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
from utils.db import WeightLossValidationError

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

if not Config.is_prod():
    st.error(
        "🚧 Weight Loss Tracker is Supabase-only in v1. "
        "Run with `ENV=prod` (or against a Supabase backend) to use this page."
    )
    st.stop()

tab_today, tab_history, tab_plan, tab_rewards = st.tabs(
    ["📅 Today", "📈 History", "🎯 Plan", "🏆 Rewards"]
)


@st.cache_data(ttl=60, show_spinner=False)
def _load_recent(user_id: str, since: date):
    return db.load_recent_logs(user_id, since)


@st.cache_data(ttl=60, show_spinner=False)
def _load_active_plan(user_id: str):
    return db.get_active_weight_plan(user_id)


@st.cache_data(ttl=60, show_spinner=False)
def _load_all_plans(user_id: str):
    return db.get_weight_plans(user_id)


def _invalidate_cache():
    _load_recent.clear()
    _load_active_plan.clear()
    _load_all_plans.clear()


# --- Plan tab is rendered first so other tabs can rely on the active plan. ---
active_plan = _load_active_plan(user_id)
plans = _load_all_plans(user_id)
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
                st.toast("Plan created.", icon="🎉")
                st.rerun()
            except WeightLossValidationError as exc:
                st.error(str(exc))


def _cycle_number(plan: dict, all_plans: list[dict]) -> int:
    """Walk previous_plan_id chain to figure out this plan's cycle ordinal."""
    by_id = {p["id"]: p for p in all_plans}
    n, current = 1, plan
    while current.get("previous_plan_id") and current["previous_plan_id"] in by_id:
        n += 1
        current = by_id[current["previous_plan_id"]]
    return n


def _render_active_cycle_card(plan: dict, weight_df: pd.DataFrame, all_plans: list[dict]):
    cycle_n = _cycle_number(plan, all_plans)
    st.subheader(f"Active cycle (Cycle #{cycle_n})")

    start_w = float(plan["start_weight_kg"])
    target_w = float(plan["target_weight_kg"])
    start_d = pd.to_datetime(plan["start_date"]).date()
    target_d = pd.to_datetime(plan["target_date"]).date()
    total_days = max((target_d - start_d).days, 1)
    elapsed_days = max((today_local() - start_d).days, 0)
    pct_done = min(elapsed_days / total_days, 1.0)

    current_w = None
    if not weight_df.empty:
        current_w = float(weight_df.sort_values("log_date").iloc[-1]["weight_kg"])

    col1, col2, col3 = st.columns(3)
    col1.metric("Start → Target",
                f"{start_w} → {target_w} kg",
                f"−{round(start_w - target_w, 1)} kg ({round((start_w - target_w)/start_w*100, 1)}%)")
    if current_w is not None:
        col2.metric("Current weight",
                    f"{current_w:.1f} kg",
                    f"{round(current_w - start_w, 1)} kg")
    else:
        col2.metric("Current weight", "—", "log your first weigh-in")
    col3.metric("Plan progress", f"{int(pct_done * 100)} %",
                f"{elapsed_days}/{total_days} days")

    if current_w is not None and elapsed_days > 0:
        weeks_elapsed = elapsed_days / 7
        pace = (start_w - current_w) / weeks_elapsed if weeks_elapsed > 0 else 0
        plan_target_today = start_w - (start_w - target_w) * (elapsed_days / total_days)
        status = on_track_status(actual_kg=current_w, plan_target_kg=plan_target_today)
        status_emoji = {"ahead": "🟢 ahead", "on_track": "🟢 on track", "behind": "🔴 behind"}[status]
        st.caption(
            f"Pace: **{pace:.2f} kg/wk** (NHS target 0.5–1.0 kg/wk). "
            f"Status: **{status_emoji}** vs plan line ({plan_target_today:.1f} kg today)."
        )

    st.caption(
        f"Daily kcal: **{plan['daily_kcal_target']}** · "
        f"Weekly exercise: **{plan['weekly_exercise_min_target']} min**"
    )

    with st.expander("✏️ Edit plan"):
        with st.form("edit_plan"):
            new_kcal = st.number_input(
                "Daily kcal target",
                min_value=400, max_value=5000,
                value=int(plan["daily_kcal_target"]), step=50,
            )
            new_ex = st.number_input(
                "Weekly exercise target (min)",
                min_value=0, max_value=2000,
                value=int(plan["weekly_exercise_min_target"]), step=10,
            )
            new_target = st.date_input("Target date", value=target_d)
            if st.form_submit_button("Save edits"):
                try:
                    db.update_weight_plan(
                        plan_id=plan["id"], user_id=user_id,
                        daily_kcal_target=new_kcal,
                        weekly_exercise_min_target=new_ex,
                        target_date=new_target,
                    )
                    _invalidate_cache()
                    st.toast("Plan updated.", icon="✅")
                    st.rerun()
                except WeightLossValidationError as exc:
                    st.error(str(exc))
        if st.button("Abandon this cycle", type="secondary"):
            db.abandon_weight_plan(plan_id=plan["id"], user_id=user_id)
            _invalidate_cache()
            st.toast("Cycle abandoned.", icon="🗑️")
            st.rerun()

    if current_w is not None and current_w <= target_w + 1.0:
        st.divider()
        next_target = round(current_w * 0.97, 1)
        next_target_date = target_date_for_rate(
            start_weight_kg=current_w,
            target_weight_kg=next_target,
            weekly_rate_kg=float(plan["weekly_rate_kg"]),
            start_date=today_local(),
        )
        st.subheader("Suggested next cycle")
        st.write(
            f"NHS recommends 3% per cycle. Next: **{current_w:.1f} → {next_target} kg** "
            f"by **{next_target_date.isoformat()}** at "
            f"{plan['weekly_rate_kg']} kg/wk."
        )
        if st.button("✅ Complete current & start next cycle", type="primary"):
            try:
                new_id = db.complete_and_start_next_plan(
                    user_id=user_id,
                    old_plan_id=plan["id"],
                    current_weight_kg=current_w,
                    new_target_weight_kg=next_target,
                    new_target_date=next_target_date,
                )
                _invalidate_cache()
                st.toast(f"Cycle completed; new plan {new_id[:8]}… is active.", icon="🎯")
                st.rerun()
            except WeightLossValidationError as exc:
                st.error(str(exc))


def _render_past_cycles(all_plans: list[dict]):
    past = [p for p in all_plans if p.get("status") != "active"]
    if not past:
        return
    st.subheader("Past cycles")
    rows = []
    for p in past:
        rows.append({
            "#": _cycle_number(p, all_plans),
            "Range": f"{p['start_date']} → {p.get('updated_at','')[:10]}",
            "Start→Target": f"{p['start_weight_kg']} → {p['target_weight_kg']} kg",
            "Status": p["status"],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


with tab_plan:
    if active_plan is None:
        _render_create_plan_form()
    else:
        plan_start = pd.to_datetime(active_plan["start_date"]).date()
        # Load from the plan's start so the "current weight" read covers the
        # whole cycle, not just the last few weeks.
        _, _, weight_df_plan = _load_recent(user_id, plan_start)
        _render_active_cycle_card(active_plan, weight_df_plan, plans)
        st.divider()
        _render_past_cycles(plans)


with tab_today:
    st.info("Today tab — implemented in Task 11.")

with tab_history:
    st.info("History tab — implemented in Task 16.")

with tab_rewards:
    st.info("Rewards tab — implemented in Task 17.")
