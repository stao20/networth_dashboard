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
                _evaluate_and_record_badges(target_date=today_local())
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
                _evaluate_and_record_badges(target_date=today_local())
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


def _summary_metrics(
    *, plan: dict, food_df: pd.DataFrame, exercise_df: pd.DataFrame,
    weight_df: pd.DataFrame, target_date: date,
):
    """Compute today/this-week numbers for the three summary cards."""
    today = target_date
    week_start, _ = iso_week_bounds(today)

    today_food = food_df[food_df["log_date"] == today] if not food_df.empty else pd.DataFrame()
    today_ex = exercise_df[exercise_df["log_date"] == today] if not exercise_df.empty else pd.DataFrame()
    week_ex = (
        exercise_df[(exercise_df["log_date"] >= week_start) & (exercise_df["log_date"] <= today)]
        if not exercise_df.empty else pd.DataFrame()
    )

    kcal_in = float(today_food["kcal"].sum()) if not today_food.empty else 0.0
    kcal_burn = (
        float(today_ex["kcal_burned"].sum())
        if not today_ex.empty and "kcal_burned" in today_ex.columns
        else 0.0
    )
    today_min = int(today_ex["duration_min"].sum()) if not today_ex.empty else 0
    week_min_moderate = (
        int(week_ex.loc[week_ex["intensity"] == "moderate", "duration_min"].sum())
        if not week_ex.empty else 0
    )
    week_min_vigorous = (
        int(week_ex.loc[week_ex["intensity"] == "vigorous", "duration_min"].sum())
        if not week_ex.empty else 0
    )
    week_equiv_min = moderate_equivalent_minutes(
        moderate=week_min_moderate, vigorous=week_min_vigorous,
    )

    weight_today = None
    weight_delta_7d = None
    if not weight_df.empty:
        ws = weight_df.sort_values("log_date")
        today_rows = ws[ws["log_date"] == today]
        if not today_rows.empty:
            weight_today = float(today_rows.iloc[-1]["weight_kg"])
        ago_7 = today - pd.Timedelta(days=7)
        ago_rows = ws[ws["log_date"] <= ago_7.date()]
        if weight_today is not None and not ago_rows.empty:
            weight_delta_7d = round(
                weight_today - float(ago_rows.iloc[-1]["weight_kg"]), 1,
            )

    return {
        "kcal_in": kcal_in,
        "kcal_target": int(plan["daily_kcal_target"]),
        "kcal_burn": kcal_burn,
        "today_min": today_min,
        "week_equiv_min": week_equiv_min,
        "weekly_target_min": int(plan["weekly_exercise_min_target"]),
        "weight_today": weight_today,
        "weight_delta_7d": weight_delta_7d,
    }


def _evaluate_and_record_badges(*, target_date: date) -> list:
    """Pull recent logs, evaluate, persist new badges, toast each one.

    Reads directly (not via the cached wrappers) so the just-saved row is
    visible to the evaluator. ``_invalidate_cache()`` is what callers run
    afterwards to flush the page-side cache.

    Returns the list of newly-inserted NewBadge instances (mainly for
    tests / future telemetry).
    """
    # 60-day window covers streaks up to 30, current-week math, and the
    # 7-day weight delta look-back used for some milestone badges.
    since = target_date - pd.Timedelta(days=60)
    since_d = since.date() if hasattr(since, "date") else since
    food_df, ex_df, weight_df = db.load_recent_logs(user_id, since_d)
    all_plans = db.get_weight_plans(user_id)
    plan_df = pd.DataFrame(all_plans)
    already = db.already_earned_keys(user_id)

    new_badges = evaluate_badges(
        user_id=user_id, today=target_date,
        food_df=food_df, exercise_df=ex_df,
        weight_df=weight_df, plan_df=plan_df,
        already_earned=already,
    )
    if new_badges:
        db.record_earned_badges(user_id, new_badges)
        for b in new_badges:
            meta = BADGES[b.badge_key]
            st.toast(f"{meta['emoji']} {meta['name']} — +{b.points} pts!")
    return new_badges


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
    if active_plan is None:
        st.info("Create a plan first on the 🎯 Plan tab.")
    else:
        col_date, _ = st.columns([2, 5])
        with col_date:
            log_date = st.date_input(
                "Date", value=today_local(), max_value=today_local(),
                key="today_date",
            )

        if int(active_plan["daily_kcal_target"]) < 800:
            day_n = (log_date - pd.to_datetime(active_plan["start_date"]).date()).days + 1
            st.warning(
                f"⚠️ VLCD plan — day {day_n} of 84 (NHS max 12 weeks)."
            )

        # Load 21-day window: covers the 7-day weight-delta look-back plus
        # margin so the upcoming history view can reuse this cache slot.
        since = log_date - pd.Timedelta(days=21)
        food_df, ex_df, weight_df = _load_recent(
            user_id, since.date() if hasattr(since, "date") else since,
        )

        m = _summary_metrics(
            plan=active_plan, food_df=food_df, exercise_df=ex_df,
            weight_df=weight_df, target_date=log_date,
        )

        c1, c2, c3 = st.columns(3)
        with c1:
            if m["weight_today"] is None:
                st.metric("⚖️ Weigh-in", "—", "log today")
            else:
                delta_text = (
                    f"{m['weight_delta_7d']:+.1f} kg / 7d"
                    if m["weight_delta_7d"] is not None else "—"
                )
                st.metric("⚖️ Weigh-in", f"{m['weight_today']:.1f} kg", delta_text)
            with st.popover("Log weight"):
                with st.form("log_weight"):
                    w = st.number_input(
                        "Weight (kg)",
                        min_value=20.0, max_value=400.0,
                        value=m["weight_today"] or 70.0,
                        step=0.1, format="%.1f",
                    )
                    note = st.text_input("Note (optional)")
                    if st.form_submit_button("Save weight"):
                        try:
                            db.save_weight_entry(
                                user_id=user_id, log_date=log_date,
                                weight_kg=float(w), notes=note or None,
                            )
                            _evaluate_and_record_badges(target_date=log_date)
                            _invalidate_cache()
                            st.toast("Weight saved.", icon="⚖️")
                            st.rerun()
                        except WeightLossValidationError as exc:
                            st.error(str(exc))

        with c2:
            net = m["kcal_in"] - m["kcal_burn"]
            st.metric(
                "🍽️ Calories", f"{int(m['kcal_in'])} / {m['kcal_target']}",
                f"net {int(net)} kcal",
            )
            st.progress(min(m["kcal_in"] / max(m["kcal_target"], 1), 1.0))

        with c3:
            st.metric(
                "🏃 Exercise (today)",
                f"{m['today_min']} min",
                f"week {m['week_equiv_min']}/{m['weekly_target_min']} min",
            )
            st.progress(
                min(m["week_equiv_min"] / max(m["weekly_target_min"], 1), 1.0)
            )

        st.divider()
        st.subheader("+ Add food")
        food_tab_manual, food_tab_barcode = st.tabs(["Manual", "Barcode"])

        with food_tab_manual:
            with st.form("manual_food"):
                col_a, col_b = st.columns([2, 1])
                name = col_a.text_input("Name", placeholder="e.g. Tuna salad")
                portion = col_b.number_input(
                    "Portion (g, optional)",
                    min_value=0.0, max_value=5000.0,
                    value=0.0, step=10.0,
                )
                col_c1, col_c2, col_c3, col_c4 = st.columns(4)
                kcal = col_c1.number_input(
                    "kcal", min_value=0.0, max_value=20000.0,
                    value=0.0, step=10.0,
                )
                protein = col_c2.number_input(
                    "protein (g)", min_value=0.0, max_value=500.0,
                    value=0.0, step=1.0,
                )
                carbs = col_c3.number_input(
                    "carbs (g)", min_value=0.0, max_value=2000.0,
                    value=0.0, step=1.0,
                )
                fat = col_c4.number_input(
                    "fat (g)", min_value=0.0, max_value=500.0,
                    value=0.0, step=1.0,
                )
                col_d1, col_d2 = st.columns(2)
                fibre = col_d1.number_input(
                    "fibre (g)", min_value=0.0, max_value=200.0,
                    value=0.0, step=0.5,
                )
                sugar = col_d2.number_input(
                    "sugar (g)", min_value=0.0, max_value=500.0,
                    value=0.0, step=1.0,
                )

                if st.form_submit_button("Save food", type="primary"):
                    try:
                        db.save_food_entry(
                            user_id=user_id,
                            log_date=log_date,
                            name=name,
                            kcal=kcal,
                            portion_g=portion or None,
                            protein_g=protein or None,
                            carbs_g=carbs or None,
                            fat_g=fat or None,
                            fibre_g=fibre or None,
                            sugar_g=sugar or None,
                            source="manual",
                        )
                        _evaluate_and_record_badges(target_date=log_date)
                        _invalidate_cache()
                        st.toast("Food entry saved.", icon="🍽️")
                        st.rerun()
                    except WeightLossValidationError as exc:
                        st.error(str(exc))

        with food_tab_barcode:
            if "off_cache" not in st.session_state:
                st.session_state.off_cache = {}

            col_bc, col_btn = st.columns([3, 1])
            barcode_input = col_bc.text_input(
                "Scan or type barcode",
                key="barcode_input",
                placeholder="e.g. 5012345678900",
            )
            if col_btn.button("Look up"):
                if not barcode_input.strip():
                    st.error("Enter a barcode first.")
                else:
                    product = st.session_state.off_cache.get(barcode_input)
                    if product is None:
                        with st.spinner("Looking up…"):
                            product = fetch_product(barcode_input.strip())
                        if product is None:
                            st.error(
                                "Product not found on Open Food Facts. "
                                "Switch to the Manual tab to enter it yourself."
                            )
                        else:
                            st.session_state.off_cache[barcode_input] = product

            product = st.session_state.off_cache.get(barcode_input)
            if product is not None:
                cols = st.columns([1, 3])
                if product.image_url:
                    cols[0].image(product.image_url, width=80)
                cols[1].markdown(f"**{product.name}**")
                per_100g = (
                    f"{product.kcal_per_100g or '?'} kcal · "
                    f"P {product.protein_per_100g or '?'} · "
                    f"C {product.carbs_per_100g or '?'} · "
                    f"F {product.fat_per_100g or '?'} · "
                    f"Fibre {product.fibre_per_100g or '?'} · "
                    f"Sug {product.sugar_per_100g or '?'}"
                )
                cols[1].caption(f"Per 100 g: {per_100g}")

                if product.kcal_per_100g is None:
                    st.warning(
                        "No kcal data on the product. "
                        "Use Manual entry for this one."
                    )
                else:
                    use_serving = (
                        product.serving_size_g is not None
                        and st.radio(
                            "Portion mode",
                            options=[
                                "Grams",
                                f"Servings ({product.serving_size_g:.0f} g each)",
                            ],
                            horizontal=True,
                            key="portion_mode",
                        ).startswith("Servings")
                    )
                    if use_serving:
                        n = st.number_input(
                            "Servings",
                            min_value=0.1, max_value=20.0,
                            value=1.0, step=0.1,
                            key="portion_servings",
                        )
                        preview = compute_portion(
                            product, grams=None, servings=float(n),
                        )
                    else:
                        g = st.number_input(
                            "Grams",
                            min_value=1.0, max_value=5000.0,
                            value=product.serving_size_g or 100.0,
                            step=10.0,
                            key="portion_grams",
                        )
                        preview = compute_portion(
                            product, grams=float(g), servings=None,
                        )

                    preview_caption = (
                        f"**Preview ({preview['effective_grams']} g):** "
                        f"{preview['kcal']} kcal · P {preview['protein_g']} · "
                        f"C {preview['carbs_g']} · F {preview['fat_g']} · "
                        f"Fibre {preview['fibre_g']} · Sug {preview['sugar_g']}"
                    )
                    st.markdown(preview_caption)

                    if st.button(
                        "Save barcode entry",
                        type="primary", key="save_barcode",
                    ):
                        try:
                            db.save_food_entry(
                                user_id=user_id,
                                log_date=log_date,
                                name=product.name,
                                kcal=preview["kcal"],
                                portion_g=preview["effective_grams"],
                                protein_g=preview["protein_g"],
                                carbs_g=preview["carbs_g"],
                                fat_g=preview["fat_g"],
                                fibre_g=preview["fibre_g"],
                                sugar_g=preview["sugar_g"],
                                barcode=product.barcode,
                                source="barcode",
                            )
                            _evaluate_and_record_badges(target_date=log_date)
                            _invalidate_cache()
                            st.toast(
                                "Food entry saved from barcode.",
                                icon="🛒",
                            )
                            st.rerun()
                        except WeightLossValidationError as exc:
                            st.error(str(exc))

        st.divider()
        st.subheader("+ Add exercise")
        with st.form("exercise_form"):
            cols = st.columns([2, 2, 1])
            activity = cols[0].selectbox(
                "Activity",
                options=[
                    "walking", "running", "cycling",
                    "swimming", "gym", "other",
                ],
            )
            intensity = cols[1].radio(
                "Intensity",
                options=["moderate", "vigorous"],
                horizontal=True,
            )
            duration = cols[2].number_input(
                "Minutes",
                min_value=1, max_value=600, value=30, step=5,
            )
            ref_weight = m["weight_today"] or float(active_plan["start_weight_kg"])
            est = estimate_kcal_burned(
                activity=activity, intensity=intensity,
                duration_min=int(duration), weight_kg=ref_weight,
            )
            st.caption(f"Estimated burn: **{est} kcal** (MET-based, ±20%).")
            notes = st.text_input("Note (optional)")

            if st.form_submit_button("Save exercise", type="primary"):
                try:
                    db.save_exercise_entry(
                        user_id=user_id,
                        log_date=log_date,
                        activity=activity,
                        intensity=intensity,
                        duration_min=int(duration),
                        kcal_burned=est,
                        notes=notes or None,
                    )
                    _evaluate_and_record_badges(target_date=log_date)
                    _invalidate_cache()
                    st.toast("Exercise saved.", icon="🏃")
                    st.rerun()
                except WeightLossValidationError as exc:
                    st.error(str(exc))

        st.divider()
        st.subheader("Today's log")
        today_food = (
            food_df[food_df["log_date"] == log_date]
            if not food_df.empty else pd.DataFrame()
        )
        today_ex = (
            ex_df[ex_df["log_date"] == log_date]
            if not ex_df.empty else pd.DataFrame()
        )

        if today_food.empty and today_ex.empty:
            st.caption("Nothing logged yet today.")
        else:
            rows = []
            for _, r in today_food.iterrows():
                rows.append({
                    "id": r["id"], "kind": "food",
                    "time": r.get("log_time") or "",
                    "item": r["name"],
                    "kcal": f"{int(r['kcal'])}",
                    "macros (P/C/F)": (
                        f"{int(r.get('protein_g') or 0)}/"
                        f"{int(r.get('carbs_g') or 0)}/"
                        f"{int(r.get('fat_g') or 0)}"
                    ),
                    "source": r.get("source", ""),
                })
            for _, r in today_ex.iterrows():
                rows.append({
                    "id": r["id"], "kind": "exercise",
                    "time": "",
                    "item": f"{r['activity']} · {r['intensity']}",
                    "kcal": f"−{int(r.get('kcal_burned') or 0)}",
                    "macros (P/C/F)": f"{int(r['duration_min'])} min",
                    "source": "",
                })
            log_df = pd.DataFrame(rows)
            log_df = log_df.sort_values("time", kind="stable").reset_index(drop=True)
            st.dataframe(
                log_df.drop(columns=["id", "kind"]),
                use_container_width=True, hide_index=True,
            )
            with st.expander("Delete an entry"):
                pick = st.selectbox(
                    "Pick entry",
                    options=log_df.index,
                    format_func=lambda i: (
                        f"[{log_df.loc[i, 'kind']}] {log_df.loc[i, 'item']}"
                    ),
                )
                if st.button("Delete selected", type="secondary"):
                    row = log_df.loc[pick]
                    if row["kind"] == "food":
                        db.delete_food_entry(
                            entry_id=row["id"], user_id=user_id,
                        )
                    else:
                        db.delete_exercise_entry(
                            entry_id=row["id"], user_id=user_id,
                        )
                    _invalidate_cache()
                    st.toast("Entry deleted.", icon="🗑️")
                    st.rerun()

with tab_history:
    st.info("History tab — implemented in Task 16.")

with tab_rewards:
    st.info("Rewards tab — implemented in Task 17.")
