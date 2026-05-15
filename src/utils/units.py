"""Units, time, and metric helpers for the weight-loss tracker.

All "today"/"this week" calculations route through here so the app has a
single source of truth for the day-boundary timezone.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Europe/London")

# Coarse MET values per (activity, intensity). Source: 2011 Compendium of
# Physical Activities, rounded. Used only for "est. kcal burned" hints.
_MET_TABLE: dict[tuple[str, str], float] = {
    ("walking", "moderate"): 3.5,
    ("walking", "vigorous"): 6.3,   # brisk / hill walking
    ("running", "moderate"): 7.0,
    ("running", "vigorous"): 9.8,
    ("cycling", "moderate"): 6.8,
    ("cycling", "vigorous"): 10.0,
    ("swimming", "moderate"): 5.8,
    ("swimming", "vigorous"): 9.5,
    ("gym", "moderate"): 5.0,
    ("gym", "vigorous"): 8.0,
    ("other", "moderate"): 4.0,
    ("other", "vigorous"): 7.0,
}

ON_TRACK_BAND_KG = 0.3
NHS_WEEKLY_MODERATE_MIN = 150
NHS_WEEKLY_VIGOROUS_MIN = 75


def today_local() -> date:
    """Return today's date in the app's display timezone."""
    return datetime.now(APP_TZ).date()


def estimate_kcal_burned(
    *, activity: str, intensity: str, duration_min: int, weight_kg: float
) -> float:
    """Estimate kcal burned via MET formula: kcal = MET * weight_kg * hours.

    Falls back to the ``"other"`` activity if the named activity isn't in
    the table. Raises ``ValueError`` for unknown intensities. Labelled
    "est." in the UI; not nutrition-grade.
    """
    intensity_lc = intensity.lower()
    if intensity_lc not in {"moderate", "vigorous"}:
        raise ValueError(
            f"intensity must be 'moderate' or 'vigorous', got {intensity!r}"
        )
    key = (activity.lower(), intensity_lc)
    met = _MET_TABLE.get(key)
    if met is None:
        met = _MET_TABLE[("other", intensity_lc)]
    hours = duration_min / 60.0
    return round(met * weight_kg * hours, 1)


def moderate_equivalent_minutes(*, moderate: int, vigorous: int) -> int:
    """NHS rule: 1 minute of vigorous exercise == 2 minutes of moderate."""
    return moderate + 2 * vigorous


def on_track_status(*, actual_kg: float, plan_target_kg: float) -> Literal["ahead", "on_track", "behind"]:
    """Compare actual weight to the linear plan target at the same date.

    Uses a ``ON_TRACK_BAND_KG`` (=0.3 kg) tolerance to avoid daily-water-weight
    flicker. "Ahead" means losing faster than the plan line.
    """
    delta = actual_kg - plan_target_kg
    if delta > ON_TRACK_BAND_KG:
        return "behind"
    if delta < -ON_TRACK_BAND_KG:
        return "ahead"
    return "on_track"


def iso_week_bounds(d: date) -> tuple[date, date]:
    """Return (Monday, Sunday) ISO-week bounds containing ``d``."""
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def target_date_for_rate(
    *, start_weight_kg: float, target_weight_kg: float, weekly_rate_kg: float, start_date: date
) -> date:
    """Project the target date given a constant weekly loss rate.

    Rounds up to whole days.
    """
    kg_to_lose = start_weight_kg - target_weight_kg
    if kg_to_lose <= 0 or weekly_rate_kg <= 0:
        return start_date
    weeks = kg_to_lose / weekly_rate_kg
    days = math.ceil(weeks * 7)
    return start_date + timedelta(days=days)
