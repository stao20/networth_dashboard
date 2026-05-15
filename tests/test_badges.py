from datetime import date, timedelta

import pandas as pd
import pytest

from utils import badges


@pytest.fixture
def empty_logs():
    return {
        "food_df": pd.DataFrame(columns=["log_date", "kcal", "protein_g"]),
        "exercise_df": pd.DataFrame(columns=["log_date", "duration_min", "intensity"]),
        "weight_df": pd.DataFrame(columns=["log_date", "weight_kg"]),
        "plan_df": pd.DataFrame(columns=["id", "start_weight_kg", "target_weight_kg", "daily_kcal_target", "status"]),
    }


def _kcal_row(d: date, kcal: float, protein: float = 0):
    return {"log_date": d, "kcal": kcal, "protein_g": protein}


def test_no_logs_no_badges(empty_logs, sample_today):
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(), **empty_logs
    )
    assert result == []


def test_first_log_badge_fires_once(sample_today):
    food = pd.DataFrame([_kcal_row(sample_today, 500)])
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(),
        food_df=food,
        exercise_df=pd.DataFrame(),
        weight_df=pd.DataFrame(),
        plan_df=pd.DataFrame(),
    )
    keys = [b.badge_key for b in result]
    assert "first_log" in keys


def test_first_log_not_re_fired_once_earned(sample_today):
    food = pd.DataFrame([_kcal_row(sample_today, 500)])
    result = badges.evaluate(
        user_id="u1", today=sample_today,
        already_earned={("first_log", date(2026, 1, 1))},
        food_df=food, exercise_df=pd.DataFrame(),
        weight_df=pd.DataFrame(), plan_df=pd.DataFrame(),
    )
    keys = [b.badge_key for b in result]
    assert "first_log" not in keys


def test_kcal_streak_7(sample_today):
    rows = [_kcal_row(sample_today - timedelta(days=i), 1500) for i in range(7)]
    food = pd.DataFrame(rows)
    plan = pd.DataFrame([{"id": "p1", "start_weight_kg": 80, "target_weight_kg": 77,
                          "daily_kcal_target": 1900, "status": "active"}])
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(),
        food_df=food, exercise_df=pd.DataFrame(),
        weight_df=pd.DataFrame(), plan_df=plan,
    )
    keys = [b.badge_key for b in result]
    assert "kcal_streak_7" in keys


def test_kcal_streak_breaks_on_over_target_day(sample_today):
    rows = [_kcal_row(sample_today - timedelta(days=i), 1500) for i in range(6)]
    rows.append(_kcal_row(sample_today - timedelta(days=3), 2500))  # over-target day
    food = pd.DataFrame(rows)
    plan = pd.DataFrame([{"id": "p1", "start_weight_kg": 80, "target_weight_kg": 77,
                          "daily_kcal_target": 1900, "status": "active"}])
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(),
        food_df=food, exercise_df=pd.DataFrame(),
        weight_df=pd.DataFrame(), plan_df=plan,
    )
    keys = [b.badge_key for b in result]
    assert "kcal_streak_7" not in keys


def test_exercise_week_150(sample_today):
    # 5 sessions of 30 min moderate = 150 min in the current ISO week
    week_dates = [sample_today - timedelta(days=i) for i in range(5)]
    rows = [{"log_date": d, "duration_min": 30, "intensity": "moderate"} for d in week_dates]
    ex = pd.DataFrame(rows)
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(),
        food_df=pd.DataFrame(), exercise_df=ex,
        weight_df=pd.DataFrame(), plan_df=pd.DataFrame(),
    )
    keys = [b.badge_key for b in result]
    assert "exercise_week_150" in keys
    # First workout badge should also fire as a side effect
    assert "first_workout" in keys


def test_vigorous_week_75_counts_double(sample_today):
    rows = [{"log_date": sample_today, "duration_min": 75, "intensity": "vigorous"}]
    ex = pd.DataFrame(rows)
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(),
        food_df=pd.DataFrame(), exercise_df=ex,
        weight_df=pd.DataFrame(), plan_df=pd.DataFrame(),
    )
    keys = [b.badge_key for b in result]
    assert "vigorous_week_75" in keys
    # And the moderate-equivalent total is 150 -> exercise_week_150 also fires
    assert "exercise_week_150" in keys


def test_lost_1kg_scoped_to_active_plan(sample_today):
    plan = pd.DataFrame([{"id": "p1", "start_weight_kg": 80, "target_weight_kg": 77,
                          "daily_kcal_target": 1900, "status": "active"}])
    weight = pd.DataFrame([
        {"log_date": sample_today, "weight_kg": 78.9},
    ])
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(),
        food_df=pd.DataFrame(), exercise_df=pd.DataFrame(),
        weight_df=weight, plan_df=plan,
    )
    new = [b for b in result if b.badge_key == "lost_1kg"]
    assert len(new) == 1
    assert new[0].metadata == {"plan_id": "p1"}


def test_lost_1kg_re_locks_on_new_plan(sample_today):
    # Already earned lost_1kg on a previous plan (p0).
    plan = pd.DataFrame([{"id": "p1", "start_weight_kg": 80, "target_weight_kg": 77,
                          "daily_kcal_target": 1900, "status": "active"}])
    weight = pd.DataFrame([{"log_date": sample_today, "weight_kg": 78.9}])
    # Earned on different plan should not block the new fire
    result = badges.evaluate(
        user_id="u1", today=sample_today,
        already_earned={("lost_1kg", date(2026, 3, 1), "p0")},
        food_df=pd.DataFrame(), exercise_df=pd.DataFrame(),
        weight_df=weight, plan_df=plan,
    )
    assert any(b.badge_key == "lost_1kg" for b in result)


def test_lost_5pct_body(sample_today):
    plan = pd.DataFrame([{"id": "p1", "start_weight_kg": 100, "target_weight_kg": 95,
                          "daily_kcal_target": 1900, "status": "active"}])
    weight = pd.DataFrame([{"log_date": sample_today, "weight_kg": 94.9}])
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(),
        food_df=pd.DataFrame(), exercise_df=pd.DataFrame(),
        weight_df=weight, plan_df=plan,
    )
    keys = [b.badge_key for b in result]
    # 5.1% loss; both 5kg and 5% should fire
    assert "lost_5kg" in keys
    assert "lost_5pct_body" in keys


def test_macro_balanced_week(sample_today):
    plan = pd.DataFrame([{"id": "p1", "start_weight_kg": 80, "target_weight_kg": 77,
                          "daily_kcal_target": 1900, "status": "active"}])
    weight = pd.DataFrame([{"log_date": sample_today, "weight_kg": 80.0}])
    # protein target: 0.8 * 80 = 64 g protein per day, 5 days in current week
    rows = []
    for i in range(5):
        rows.append({"log_date": sample_today - timedelta(days=i),
                     "kcal": 1500, "protein_g": 70})
    food = pd.DataFrame(rows)
    result = badges.evaluate(
        user_id="u1", today=sample_today, already_earned=set(),
        food_df=food, exercise_df=pd.DataFrame(),
        weight_df=weight, plan_df=plan,
    )
    keys = [b.badge_key for b in result]
    assert "macro_balanced_week" in keys


def test_badges_catalog_has_required_metadata():
    """Every badge must have name + emoji + points."""
    for key, info in badges.BADGES.items():
        assert "name" in info, key
        assert "emoji" in info, key
        assert "points" in info, key
        assert isinstance(info["points"], int)
