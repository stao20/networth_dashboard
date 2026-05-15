"""Badge catalog and evaluator for the weight-loss tracker.

The catalog (``BADGES``) is the source of truth for badge metadata. Each
badge's earning rule is implemented inline in ``evaluate()``. Adding a
new badge means appending to ``BADGES`` and adding the corresponding
branch to ``evaluate()``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Optional

import pandas as pd

from utils.units import iso_week_bounds, moderate_equivalent_minutes


BADGES: dict[str, dict[str, Any]] = {
    # Onboarding
    "first_log":           {"name": "First log",            "emoji": "📔", "points": 10},
    "first_weigh_in":      {"name": "First weigh-in",       "emoji": "⚖️", "points": 10},
    "first_plan":          {"name": "First plan",           "emoji": "🌱", "points": 30},

    # Kcal streaks (under target, ≥1 food entry that day)
    "kcal_streak_7":       {"name": "7-day kcal streak",    "emoji": "🥇", "points": 50,
                            "rule": "Stay under your kcal target 7 days in a row."},
    "kcal_streak_14":      {"name": "14-day kcal streak",   "emoji": "🥈", "points": 100,
                            "rule": "Stay under your kcal target 14 days in a row."},
    "kcal_streak_30":      {"name": "30-day kcal streak",   "emoji": "🥉", "points": 250,
                            "rule": "Stay under your kcal target 30 days in a row."},

    # Exercise
    "first_workout":       {"name": "First workout logged", "emoji": "🏃", "points": 20},
    "exercise_week_150":   {"name": "NHS 150 min week",     "emoji": "🎯", "points": 50,
                            "rule": "Hit 150 moderate-equivalent minutes in one ISO week."},
    "exercise_week_300":   {"name": "Double NHS week",      "emoji": "💪", "points": 100,
                            "rule": "Hit 300 moderate-equivalent minutes in one ISO week."},
    "vigorous_week_75":    {"name": "75 min vigorous week", "emoji": "⚡", "points": 75,
                            "rule": "Log 75+ minutes of vigorous exercise in one ISO week."},

    # Weight milestones (per active plan)
    "lost_1kg":            {"name": "Lost 1 kg",            "emoji": "📉", "points": 100,
                            "rule": "Drop 1 kg below your plan's start weight."},
    "lost_3kg":            {"name": "Lost 3 kg",            "emoji": "📉", "points": 200,
                            "rule": "Drop 3 kg below your plan's start weight."},
    "lost_5kg":            {"name": "Lost 5 kg",            "emoji": "📉", "points": 350,
                            "rule": "Drop 5 kg below your plan's start weight."},
    "lost_5pct_body":      {"name": "5% body weight lost",  "emoji": "🏆", "points": 500,
                            "rule": "Lose 5% of your plan's starting body weight."},

    # Macro / quality
    "macro_balanced_week": {"name": "Balanced macros",      "emoji": "🥗", "points": 30,
                            "rule": "≥5 days with protein ≥0.8 g/kg body weight in one ISO week."},

    # Plan progress
    "cycle_completed":     {"name": "Cycle completed",      "emoji": "🥳", "points": 200,
                            "rule": "Reach the target weight of a cycle."},
    "cycle_streak_3":      {"name": "3 cycles in a row",    "emoji": "🔥", "points": 500,
                            "rule": "Complete three cycles back-to-back."},
}


@dataclass(frozen=True)
class NewBadge:
    badge_key: str
    earned_on: date
    points: int
    metadata: Optional[dict] = None


# ``already_earned`` is a set of (badge_key, earned_on) for non-plan-scoped
# badges, and (badge_key, earned_on, plan_id) for plan-scoped milestone badges.
EarnedKey = tuple


def evaluate(
    *,
    user_id: str,
    today: date,
    food_df: pd.DataFrame,
    exercise_df: pd.DataFrame,
    weight_df: pd.DataFrame,
    plan_df: pd.DataFrame,
    already_earned: Iterable[EarnedKey],
) -> list[NewBadge]:
    """Decide which badges should be awarded given the user's logs.

    Pure: returns the list to insert; does not write anything. Callers are
    expected to dedupe against ``already_earned`` themselves at insert time
    in case of races (the function does that filtering too).
    """
    earned: set[EarnedKey] = set(already_earned)
    new: list[NewBadge] = []

    active_plan = _active_plan(plan_df)
    daily_kcal_target = int(active_plan["daily_kcal_target"]) if active_plan is not None else None
    start_weight = float(active_plan["start_weight_kg"]) if active_plan is not None else None
    active_plan_id = str(active_plan["id"]) if active_plan is not None else None

    food_df = _ensure_columns(food_df, ["log_date", "kcal", "protein_g"])
    exercise_df = _ensure_columns(exercise_df, ["log_date", "duration_min", "intensity"])
    weight_df = _ensure_columns(weight_df, ["log_date", "weight_kg"])

    # Onboarding ------------------------------------------------------
    if not food_df.empty:
        _try_add_one_shot(new, earned, "first_log", today, food_df["log_date"].min())
    if not weight_df.empty:
        _try_add_one_shot(new, earned, "first_weigh_in", today, weight_df["log_date"].min())
    if active_plan is not None:
        _try_add_one_shot(new, earned, "first_plan", today,
                          active_plan.get("start_date") or today)

    # Kcal streaks ---------------------------------------------------
    if daily_kcal_target is not None and not food_df.empty:
        streak = _kcal_streak_length(food_df, daily_kcal_target, today)
        for n_days, key in ((7, "kcal_streak_7"), (14, "kcal_streak_14"), (30, "kcal_streak_30")):
            if streak >= n_days:
                _try_add_streak(new, earned, key, today, n_days)

    # Exercise --------------------------------------------------------
    if not exercise_df.empty:
        _try_add_one_shot(new, earned, "first_workout", today, exercise_df["log_date"].min())
        week_min, week_vig = _weekly_exercise_minutes(exercise_df, today)
        equiv = moderate_equivalent_minutes(moderate=week_min, vigorous=week_vig)
        if equiv >= 150:
            _try_add_weekly(new, earned, "exercise_week_150", today)
        if equiv >= 300:
            _try_add_weekly(new, earned, "exercise_week_300", today)
        if week_vig >= 75:
            _try_add_weekly(new, earned, "vigorous_week_75", today)

    # Plan-scoped weight milestones -----------------------------------
    if active_plan_id is not None and start_weight is not None and not weight_df.empty:
        latest_weight = float(weight_df.sort_values("log_date").iloc[-1]["weight_kg"])
        lost = start_weight - latest_weight
        pct_lost = (lost / start_weight) * 100 if start_weight > 0 else 0
        for threshold, key in ((1.0, "lost_1kg"), (3.0, "lost_3kg"), (5.0, "lost_5kg")):
            if lost >= threshold:
                _try_add_plan_scoped(new, earned, key, today, active_plan_id)
        if pct_lost >= 5:
            _try_add_plan_scoped(new, earned, "lost_5pct_body", today, active_plan_id)

    # Macro balanced week --------------------------------------------
    if start_weight is not None and not food_df.empty:
        protein_target_per_day = 0.8 * start_weight
        if _balanced_macro_days(food_df, today, protein_target_per_day) >= 5:
            _try_add_weekly(new, earned, "macro_balanced_week", today)

    return new


# ---------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------

def _ensure_columns(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Return a copy with missing columns added as empty."""
    out = df.copy() if not df.empty else pd.DataFrame(columns=cols)
    for c in cols:
        if c not in out.columns:
            out[c] = None
    if "log_date" in out.columns and not out.empty:
        out["log_date"] = pd.to_datetime(out["log_date"]).dt.date
    return out


def _active_plan(plan_df: pd.DataFrame):
    if plan_df is None or plan_df.empty:
        return None
    active = plan_df[plan_df["status"] == "active"] if "status" in plan_df.columns else plan_df
    if active.empty:
        return None
    return active.iloc[0]


def _kcal_streak_length(food_df: pd.DataFrame, kcal_target: int, today: date) -> int:
    """Consecutive days ending today (or yesterday) under target + ≥1 entry."""
    daily = food_df.groupby("log_date")["kcal"].sum()
    # Start from today if today already has a log; else start from yesterday.
    if today not in daily.index:
        cursor = today - timedelta(days=1)
    else:
        cursor = today
    streak = 0
    while cursor in daily.index and daily.loc[cursor] <= kcal_target:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _weekly_exercise_minutes(exercise_df: pd.DataFrame, today: date) -> tuple[int, int]:
    """Return (moderate_minutes, vigorous_minutes) for the ISO week of ``today``."""
    week_start, week_end = iso_week_bounds(today)
    mask = (exercise_df["log_date"] >= week_start) & (exercise_df["log_date"] <= week_end)
    in_week = exercise_df[mask]
    moderate = int(in_week.loc[in_week["intensity"] == "moderate", "duration_min"].sum())
    vigorous = int(in_week.loc[in_week["intensity"] == "vigorous", "duration_min"].sum())
    return moderate, vigorous


def _balanced_macro_days(food_df: pd.DataFrame, today: date, protein_target: float) -> int:
    week_start, week_end = iso_week_bounds(today)
    mask = (food_df["log_date"] >= week_start) & (food_df["log_date"] <= week_end)
    in_week = food_df[mask]
    if in_week.empty:
        return 0
    daily_protein = in_week.groupby("log_date")["protein_g"].sum(min_count=1)
    return int((daily_protein >= protein_target).sum())


def _try_add_one_shot(new, earned, key: str, today: date, earned_on):
    """Add a badge if no row with this badge_key exists in already_earned."""
    if any(e[0] == key for e in earned):
        return
    info = BADGES[key]
    earned_date = _coerce_date(earned_on, today)
    badge = NewBadge(key, earned_date, info["points"])
    new.append(badge)
    earned.add((key, earned_date))


def _try_add_weekly(new, earned, key: str, today: date):
    """One-per-ISO-week badge keyed on the week's Sunday."""
    info = BADGES[key]
    _, sunday = iso_week_bounds(today)
    if any(e[0] == key and e[1] == sunday for e in earned):
        return
    badge = NewBadge(key, sunday, info["points"])
    new.append(badge)
    earned.add((key, sunday))


def _try_add_streak(new, earned, key: str, today: date, streak_length: int):
    """One-per-day streak badge (re-earnable on later dates)."""
    if any(e[0] == key and e[1] == today for e in earned):
        return
    info = BADGES[key]
    badge = NewBadge(key, today, info["points"], metadata={"streak_length": streak_length})
    new.append(badge)
    earned.add((key, today))


def _try_add_plan_scoped(new, earned, key: str, today: date, plan_id: str):
    """One-per-plan milestone badge."""
    # already-earned tuples for plan-scoped badges are (key, earned_on, plan_id)
    if any(len(e) >= 3 and e[0] == key and e[2] == plan_id for e in earned):
        return
    info = BADGES[key]
    badge = NewBadge(key, today, info["points"], metadata={"plan_id": plan_id})
    new.append(badge)
    earned.add((key, today, plan_id))


def _coerce_date(value, fallback: date) -> date:
    """Best-effort coerce pandas/np/datetime values to a python ``date``."""
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return fallback
