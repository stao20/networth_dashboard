from datetime import date, datetime
from zoneinfo import ZoneInfo

from utils import units


def test_today_local_returns_london_date(monkeypatch):
    fixed_utc = datetime(2026, 5, 15, 23, 30, tzinfo=ZoneInfo("UTC"))

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_utc.astimezone(tz) if tz else fixed_utc

    monkeypatch.setattr(units, "datetime", _FixedDatetime)
    assert units.today_local() == date(2026, 5, 16)  # London is UTC+1 in May


def test_estimate_kcal_burned_moderate_walking():
    # MET ~3.5 for moderate walking, 70 kg, 30 min => ~122 kcal
    result = units.estimate_kcal_burned(
        activity="walking", intensity="moderate", duration_min=30, weight_kg=70.0
    )
    assert 110 <= result <= 135


def test_estimate_kcal_burned_vigorous_running():
    # MET ~9.8 for vigorous running, 70 kg, 30 min => ~343 kcal
    result = units.estimate_kcal_burned(
        activity="running", intensity="vigorous", duration_min=30, weight_kg=70.0
    )
    assert 320 <= result <= 370


def test_estimate_kcal_unknown_activity_falls_back():
    result = units.estimate_kcal_burned(
        activity="zumba_underwater", intensity="moderate", duration_min=30, weight_kg=70.0
    )
    # Fallback to "other"; just ensure non-zero positive
    assert result > 0


def test_moderate_equivalent_minutes_doubles_vigorous():
    assert units.moderate_equivalent_minutes(moderate=60, vigorous=30) == 120


def test_on_track_status_within_band():
    assert units.on_track_status(actual_kg=78.5, plan_target_kg=78.3) == "on_track"


def test_on_track_status_behind():
    assert units.on_track_status(actual_kg=79.0, plan_target_kg=78.3) == "behind"


def test_on_track_status_ahead():
    assert units.on_track_status(actual_kg=77.8, plan_target_kg=78.3) == "ahead"


def test_iso_week_bounds_for_thursday():
    start, end = units.iso_week_bounds(date(2026, 5, 14))  # Thursday
    assert start == date(2026, 5, 11)
    assert end == date(2026, 5, 17)


def test_target_date_for_rate():
    # Need to lose 4 kg at 0.5 kg/week => 8 weeks = 56 days
    target = units.target_date_for_rate(
        start_weight_kg=82.0, target_weight_kg=78.0, weekly_rate_kg=0.5,
        start_date=date(2026, 5, 15),
    )
    assert target == date(2026, 7, 10)
