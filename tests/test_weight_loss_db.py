from datetime import date

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
    # Find the update payload
    op_names = [c[0] for c in chain]
    assert "update" in op_names
