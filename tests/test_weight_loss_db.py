from datetime import date

import pandas as pd
import pytest

from utils.db import SupabaseHandler


@pytest.fixture
def handler(fake_supabase, mocker):
    mocker.patch.object(SupabaseHandler, "__init__", lambda self: None)
    h = SupabaseHandler()
    h.supabase = fake_supabase
    return h


def test_create_weight_plan_inserts_and_returns_id(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("weight_plans", [{"id": "plan-1"}])
    plan_id = handler.create_weight_plan(
        user_id=sample_user_id,
        start_weight_kg=80.0,
        target_weight_kg=77.6,
        weekly_rate_kg=0.5,
        daily_kcal_target=1900,
        weekly_exercise_min_target=150,
        start_date=date(2026, 5, 15),
        target_date=date(2026, 7, 10),
        sex="M",
        vlcd_acknowledged=False,
    )
    assert plan_id == "plan-1"


def test_create_weight_plan_rejects_vlcd_without_ack(handler, sample_user_id):
    from utils.db import WeightLossValidationError
    with pytest.raises(WeightLossValidationError):
        handler.create_weight_plan(
            user_id=sample_user_id,
            start_weight_kg=80.0,
            target_weight_kg=77.6,
            weekly_rate_kg=0.5,
            daily_kcal_target=700,   # VLCD
            weekly_exercise_min_target=150,
            start_date=date(2026, 5, 15),
            target_date=date(2026, 7, 10),
            sex="M",
            vlcd_acknowledged=False,  # NOT acknowledged
        )


def test_create_weight_plan_rejects_vlcd_over_12_weeks(handler, sample_user_id):
    from utils.db import WeightLossValidationError
    with pytest.raises(WeightLossValidationError):
        handler.create_weight_plan(
            user_id=sample_user_id,
            start_weight_kg=80.0,
            target_weight_kg=77.6,
            weekly_rate_kg=0.5,
            daily_kcal_target=700,
            weekly_exercise_min_target=150,
            start_date=date(2026, 5, 15),
            target_date=date(2026, 11, 15),  # ~26 weeks
            sex="M",
            vlcd_acknowledged=True,
        )


def test_get_active_plan_returns_none_when_no_active(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("weight_plans", [])
    assert handler.get_active_weight_plan(sample_user_id) is None


def test_get_active_plan_returns_row(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("weight_plans", [
        {"id": "p1", "status": "active", "user_id": sample_user_id,
         "start_weight_kg": 80, "target_weight_kg": 77, "daily_kcal_target": 1900,
         "start_date": "2026-05-15", "target_date": "2026-07-10",
         "weekly_rate_kg": 0.5, "weekly_exercise_min_target": 150, "sex": "M"},
    ])
    plan = handler.get_active_weight_plan(sample_user_id)
    assert plan is not None
    assert plan["id"] == "p1"


def test_complete_and_start_next_plan_invokes_rpc(handler, fake_supabase, sample_user_id, mocker):
    mock_rpc_query = mocker.MagicMock()
    mock_rpc_query.execute.return_value.data = "plan-2"
    fake_supabase.rpc = mocker.MagicMock(return_value=mock_rpc_query)
    new_id = handler.complete_and_start_next_plan(
        user_id=sample_user_id,
        old_plan_id="plan-1",
        current_weight_kg=77.5,
        new_target_weight_kg=75.2,
        new_target_date=date(2026, 9, 1),
    )
    assert new_id == "plan-2"
    fake_supabase.rpc.assert_called_once_with(
        "complete_and_start_next_plan",
        {
            "p_user_id": sample_user_id,
            "p_old_plan_id": "plan-1",
            "p_current_weight_kg": 77.5,
            "p_new_target_weight_kg": 75.2,
            "p_new_target_date": "2026-09-01",
        },
    )


def test_abandon_plan(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("weight_plans", [{"id": "p1"}])
    handler.abandon_weight_plan(plan_id="p1", user_id=sample_user_id)
    chain = fake_supabase._tables["weight_plans"].calls
    op_names = [c[0] for c in chain]
    assert "update" in op_names
    update_args = next(c[1] for c in chain if c[0] == "update")
    assert update_args[0] == {"status": "abandoned", "updated_at": "now()"}
    eq_calls = [c for c in chain if c[0] == "eq"]
    eq_pairs = {c[1][0]: c[1][1] for c in eq_calls}
    assert eq_pairs.get("status") == "active"
    assert eq_pairs.get("id") == "p1"
    assert eq_pairs.get("user_id") == sample_user_id


def test_update_plan_no_op_when_no_fields(handler, fake_supabase, sample_user_id):
    handler.update_weight_plan(plan_id="p1", user_id=sample_user_id)
    # Empty patch should result in NO update being issued. The supabase
    # client may not be touched at all, so the table entry is optional.
    table = fake_supabase._tables.get("weight_plans")
    op_names = [c[0] for c in table.calls] if table is not None else []
    assert "update" not in op_names


def test_update_plan_rejects_dropping_below_vlcd_without_ack(handler, fake_supabase, sample_user_id):
    from utils.db import WeightLossValidationError
    fake_supabase.set_table("weight_plans", [{
        "start_date": "2026-05-15",
        "target_date": "2026-07-10",
        "daily_kcal_target": 1900,
        "vlcd_acknowledged": False,
    }])
    with pytest.raises(WeightLossValidationError):
        handler.update_weight_plan(
            plan_id="p1", user_id=sample_user_id, daily_kcal_target=700,
        )


def test_update_plan_rejects_extending_vlcd_past_12_weeks(handler, fake_supabase, sample_user_id):
    from utils.db import WeightLossValidationError
    fake_supabase.set_table("weight_plans", [{
        "start_date": "2026-05-15",
        "target_date": "2026-07-10",
        "daily_kcal_target": 700,
        "vlcd_acknowledged": True,
    }])
    with pytest.raises(WeightLossValidationError):
        handler.update_weight_plan(
            plan_id="p1", user_id=sample_user_id,
            target_date=date(2026, 11, 15),
        )


def test_save_weight_entry_validates_bounds(handler, sample_user_id):
    from utils.db import WeightLossValidationError
    with pytest.raises(WeightLossValidationError):
        handler.save_weight_entry(
            user_id=sample_user_id, log_date=date(2026, 5, 15), weight_kg=10.0
        )


def test_save_weight_entry_upserts(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("weight_entries", [{"id": "w1"}])
    handler.save_weight_entry(
        user_id=sample_user_id, log_date=date(2026, 5, 15), weight_kg=78.4
    )
    chain = fake_supabase._tables["weight_entries"].calls
    assert any(c[0] == "upsert" for c in chain)


def test_save_food_entry_validates_kcal(handler, sample_user_id):
    from utils.db import WeightLossValidationError
    with pytest.raises(WeightLossValidationError):
        handler.save_food_entry(
            user_id=sample_user_id, log_date=date(2026, 5, 15),
            name="X", kcal=99999, source="manual",
        )


def test_save_exercise_entry_validates_intensity(handler, sample_user_id):
    from utils.db import WeightLossValidationError
    with pytest.raises(WeightLossValidationError):
        handler.save_exercise_entry(
            user_id=sample_user_id, log_date=date(2026, 5, 15),
            activity="walking", intensity="warp_speed", duration_min=30,
        )


def test_load_recent_logs_returns_three_frames(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("food_entries", [
        {"log_date": "2026-05-14", "kcal": 1500, "protein_g": 80, "name": "Eggs"},
    ])
    fake_supabase.set_table("exercise_entries", [
        {"log_date": "2026-05-14", "duration_min": 30, "intensity": "moderate", "activity": "walking"},
    ])
    fake_supabase.set_table("weight_entries", [
        {"log_date": "2026-05-14", "weight_kg": 78.0},
    ])
    food, exercise, weight = handler.load_recent_logs(
        sample_user_id, since_date=date(2026, 5, 1)
    )
    assert isinstance(food, pd.DataFrame) and not food.empty
    assert isinstance(exercise, pd.DataFrame) and not exercise.empty
    assert isinstance(weight, pd.DataFrame) and not weight.empty


def test_delete_food_entry(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("food_entries", [])
    handler.delete_food_entry(entry_id="f1", user_id=sample_user_id)
    chain = fake_supabase._tables["food_entries"].calls
    assert any(c[0] == "delete" for c in chain)


def test_delete_exercise_entry(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("exercise_entries", [])
    handler.delete_exercise_entry(entry_id="e1", user_id=sample_user_id)
    chain = fake_supabase._tables["exercise_entries"].calls
    assert any(c[0] == "delete" for c in chain)
