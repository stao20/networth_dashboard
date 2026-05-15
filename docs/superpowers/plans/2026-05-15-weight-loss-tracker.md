# Weight Loss Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new Streamlit page (`/weight_loss_tracker`) that lets users run an NHS-aligned weight-loss programme — plan with 3% cycles, daily weight log, food tracking (manual + Open Food Facts barcode), exercise tracking (MET-based kcal burn), and a code-defined badge system.

**Architecture:** Single Streamlit page file with four tabs (Today / History / Plan / Rewards). All cross-cutting logic in tested utility modules (`units.py`, `food_lookup.py`, `badges.py`). DB CRUD on `SupabaseHandler`. Data scoped per `user_id` (Google OAuth sub).

**Tech Stack:** Python 3.13, Streamlit 1.45+, Supabase (Postgres), Plotly, pandas, `requests` (new — Open Food Facts client), `pytest` (new — test runner), `zoneinfo` (stdlib).

**Spec:** [`docs/superpowers/specs/2026-05-15-weight-loss-tracker-design.md`](../specs/2026-05-15-weight-loss-tracker-design.md)

---

## File map

**Create:**
- `supabase/migrations/20260515000000_create_weight_loss_tables.sql` — 5 tables + 1 RPC
- `src/utils/units.py` — timezone helpers, MET kcal-burn, "on track" band, ISO-week helpers
- `src/utils/food_lookup.py` — Open Food Facts client, `compute_portion`
- `src/utils/badges.py` — `BADGES` catalog, `evaluate()` pure function
- `src/pages/weight_loss_tracker.py` — the page
- `tests/__init__.py`
- `tests/conftest.py` — pytest fixtures + supabase mock
- `tests/test_units.py`
- `tests/test_food_lookup.py`
- `tests/fixtures/off_tesco_bread.json` — Open Food Facts response fixture
- `tests/fixtures/off_no_kcal.json` — degenerate OFF response fixture
- `tests/test_badges.py`
- `tests/test_weight_loss_db.py`

**Modify:**
- `pyproject.toml` — add `requests`, `pytest`, `pytest-mock` to appropriate groups
- `src/utils/models.py` — add `Plan`, `WeightEntry`, `FoodEntry`, `ExerciseEntry`, `EarnedBadge` dataclasses
- `src/utils/db.py` — extend `SupabaseHandler` with weight-loss methods

---

## Task 1: Test infrastructure

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

### Steps

- [ ] **Step 1: Add dev dependencies**

Modify `pyproject.toml`:

```toml
[project]
name = "networth-dashboard"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "authlib>=1.6.0",
    "pandas>=2.2.3",
    "plotly>=6.0.0",
    "streamlit>=1.45.0",
    "supabase>=2.13.0",
    "requests>=2.32.0",
]

[dependency-groups]
dev = [
    "python-dotenv>=1.0.1",
    "pytest>=8.0.0",
    "pytest-mock>=3.12.0",
]
lint = [
    "ruff>=0.9.10",
]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Install new deps**

Run: `uv sync`
Expected: lockfile updates, `requests` / `pytest` / `pytest-mock` resolve cleanly.

- [ ] **Step 3: Create test package**

Create `tests/__init__.py` (empty file).

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


class FakeSupabaseQuery:
    """Chainable mock for the supabase-py builder API.

    Records the operation chain so tests can assert on it, then returns a
    canned response payload from `.execute()`.
    """

    def __init__(self, response_data=None):
        self._response_data = response_data if response_data is not None else []
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return _record

    def execute(self):
        self.calls.append(("execute", (), {}))
        resp = MagicMock()
        resp.data = self._response_data
        return resp


@pytest.fixture
def fake_supabase(mocker):
    """A MagicMock standing in for the supabase client.

    Returns a callable `set_table(name, response_data)` so each test can wire
    the rows that `.table(name)...execute()` should return.
    """
    client = MagicMock()
    tables: dict[str, FakeSupabaseQuery] = {}

    def set_table(name: str, response_data):
        tables[name] = FakeSupabaseQuery(response_data)
        return tables[name]

    def _table(name):
        return tables.setdefault(name, FakeSupabaseQuery([]))

    client.table.side_effect = _table
    client.set_table = set_table
    client._tables = tables
    return client


@pytest.fixture
def sample_user_id():
    return "google-sub-abc123"


@pytest.fixture
def sample_today():
    return date(2026, 5, 15)
```

- [ ] **Step 4: Add smoke test**

Create `tests/test_smoke.py`:

```python
def test_pytest_runs():
    assert 1 + 1 == 2
```

- [ ] **Step 5: Run smoke test**

Run: `uv run pytest -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py tests/conftest.py tests/test_smoke.py
git commit -F /dev/stdin <<MSG
chore(tests): add pytest infrastructure + supabase mock fixture

Adds pytest + pytest-mock as dev deps, configures pytest to discover
tests/ with src/ on pythonpath, and ships a reusable FakeSupabaseQuery
fixture so DB-handler tests can assert on the builder chain without a
real Supabase instance.
MSG
```

---

## Task 2: Database migration + RPC + dataclasses

**Files:**
- Create: `supabase/migrations/20260515000000_create_weight_loss_tables.sql`
- Modify: `src/utils/models.py`

### Steps

- [ ] **Step 1: Write the migration**

Create `supabase/migrations/20260515000000_create_weight_loss_tables.sql`:

```sql
-- Weight Loss Tracker: 5 tables + 1 RPC for atomic cycle completion.
-- See docs/superpowers/specs/2026-05-15-weight-loss-tracker-design.md §5.

CREATE TABLE IF NOT EXISTS weight_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_weight_kg DECIMAL(6,2) NOT NULL,
    target_weight_kg DECIMAL(6,2) NOT NULL,
    weekly_rate_kg DECIMAL(4,2) NOT NULL,
    daily_kcal_target INT NOT NULL,
    weekly_exercise_min_target INT NOT NULL DEFAULT 150,
    start_date DATE NOT NULL,
    target_date DATE NOT NULL,
    sex CHAR(1),
    previous_plan_id UUID REFERENCES weight_plans(id),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','completed','abandoned')),
    vlcd_acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weight_plans_one_active
    ON weight_plans(user_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_weight_plans_user ON weight_plans(user_id);

CREATE TABLE IF NOT EXISTS weight_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    weight_kg DECIMAL(6,2) NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, log_date)
);
CREATE INDEX IF NOT EXISTS idx_weight_entries_user_date
    ON weight_entries(user_id, log_date DESC);

CREATE TABLE IF NOT EXISTS food_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    log_time TIME,
    name TEXT NOT NULL,
    portion_g DECIMAL(8,2),
    kcal DECIMAL(7,1) NOT NULL,
    protein_g DECIMAL(6,2),
    carbs_g DECIMAL(6,2),
    fat_g DECIMAL(6,2),
    fibre_g DECIMAL(6,2),
    sugar_g DECIMAL(6,2),
    barcode TEXT,
    source TEXT NOT NULL DEFAULT 'manual'
        CHECK (source IN ('manual','barcode')),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_food_entries_user_date
    ON food_entries(user_id, log_date DESC);

CREATE TABLE IF NOT EXISTS exercise_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    activity TEXT NOT NULL,
    intensity TEXT NOT NULL CHECK (intensity IN ('moderate','vigorous')),
    duration_min INT NOT NULL CHECK (duration_min > 0),
    kcal_burned DECIMAL(7,1),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_exercise_entries_user_date
    ON exercise_entries(user_id, log_date DESC);

CREATE TABLE IF NOT EXISTS earned_badges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_key TEXT NOT NULL,
    earned_on DATE NOT NULL,
    points INT NOT NULL DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, badge_key, earned_on)
);
CREATE INDEX IF NOT EXISTS idx_earned_badges_user
    ON earned_badges(user_id, earned_on DESC);

-- RPC: atomically complete the active plan and create the next cycle.
-- Copies weekly_rate, sex, and weekly_exercise_min_target from the old plan.
-- daily_kcal_target is copied unless the old plan was VLCD (<800 kcal), in
-- which case it resets to the NHS-standard default for the user's sex.
CREATE OR REPLACE FUNCTION complete_and_start_next_plan(
    p_user_id TEXT,
    p_old_plan_id UUID,
    p_current_weight_kg DECIMAL,
    p_new_target_weight_kg DECIMAL,
    p_new_target_date DATE
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    new_id UUID;
    old_rate DECIMAL;
    old_kcal INT;
    old_sex CHAR(1);
    old_exercise_target INT;
    old_was_vlcd BOOLEAN;
    new_kcal INT;
BEGIN
    UPDATE weight_plans
    SET status = 'completed', updated_at = NOW()
    WHERE id = p_old_plan_id
      AND user_id = p_user_id
      AND status = 'active'
    RETURNING weekly_rate_kg,
              daily_kcal_target,
              sex,
              weekly_exercise_min_target,
              (daily_kcal_target < 800)
    INTO old_rate, old_kcal, old_sex, old_exercise_target, old_was_vlcd;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'No active plan found for user';
    END IF;

    new_kcal := CASE
        WHEN old_was_vlcd AND old_sex = 'M' THEN 1900
        WHEN old_was_vlcd AND old_sex = 'F' THEN 1400
        WHEN old_was_vlcd                   THEN 1500
        ELSE old_kcal
    END;

    INSERT INTO weight_plans (
        user_id, start_weight_kg, target_weight_kg, weekly_rate_kg,
        daily_kcal_target, weekly_exercise_min_target,
        start_date, target_date, sex, previous_plan_id, status
    ) VALUES (
        p_user_id, p_current_weight_kg, p_new_target_weight_kg, old_rate,
        new_kcal, old_exercise_target,
        CURRENT_DATE, p_new_target_date, old_sex, p_old_plan_id, 'active'
    )
    RETURNING id INTO new_id;

    RETURN new_id;
END;
$$;
```

- [ ] **Step 2: Push the migration to Supabase**

Run (from project root, with Supabase CLI / linked project):
```
npx supabase db push
```
Expected: migration listed and applied. Verify by inspecting tables in Supabase Studio or with `npx supabase db diff` (should report no further changes).

If running against a local Supabase instance, use `npx supabase migration up` instead.

- [ ] **Step 3: Add dataclasses**

Modify `src/utils/models.py` — append after the existing dataclasses:

```python
from datetime import date as _date


@dataclass
class WeightPlan:
    id: Optional[str]
    user_id: str
    start_weight_kg: float
    target_weight_kg: float
    weekly_rate_kg: float
    daily_kcal_target: int
    weekly_exercise_min_target: int
    start_date: _date
    target_date: _date
    sex: Optional[str] = None
    previous_plan_id: Optional[str] = None
    status: str = "active"
    vlcd_acknowledged: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class WeightEntry:
    id: Optional[str]
    user_id: str
    log_date: _date
    weight_kg: float
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class FoodEntry:
    id: Optional[str]
    user_id: str
    log_date: _date
    name: str
    kcal: float
    log_time: Optional[str] = None
    portion_g: Optional[float] = None
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None
    fibre_g: Optional[float] = None
    sugar_g: Optional[float] = None
    barcode: Optional[str] = None
    source: str = "manual"
    created_at: Optional[datetime] = None


@dataclass
class ExerciseEntry:
    id: Optional[str]
    user_id: str
    log_date: _date
    activity: str
    intensity: str
    duration_min: int
    kcal_burned: Optional[float] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


@dataclass
class EarnedBadge:
    id: Optional[str]
    user_id: str
    badge_key: str
    earned_on: _date
    points: int = 0
    metadata: Optional[dict] = None
    created_at: Optional[datetime] = None
```

- [ ] **Step 4: Verify the models import cleanly**

Run: `uv run python -c "from src.utils.models import WeightPlan, WeightEntry, FoodEntry, ExerciseEntry, EarnedBadge; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/20260515000000_create_weight_loss_tables.sql src/utils/models.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): add tables, RPC, and dataclasses

Five tables (weight_plans, weight_entries, food_entries,
exercise_entries, earned_badges) plus a single RPC
complete_and_start_next_plan() that atomically marks the current cycle
completed and inserts the next 3% cycle. Adds matching dataclasses to
utils.models.
MSG
```

---

## Task 3: `units.py` helper module

**Files:**
- Create: `src/utils/units.py`
- Create: `tests/test_units.py`

### Steps

- [ ] **Step 1: Write failing tests**

Create `tests/test_units.py`:

```python
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
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_units.py -v`
Expected: All tests fail with `ImportError: cannot import name 'units'` or attribute errors.

- [ ] **Step 3: Implement `units.py`**

Create `src/utils/units.py`:

```python
"""Units, time, and metric helpers for the weight-loss tracker.

All "today"/"this week" calculations route through here so the app has a
single source of truth for the day-boundary timezone.
"""
from __future__ import annotations

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
    the table. Labelled "est." in the UI; not nutrition-grade.
    """
    key = (activity.lower(), intensity.lower())
    met = _MET_TABLE.get(key) or _MET_TABLE[("other", intensity.lower())]
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
    days = int(round(weeks * 7))
    return start_date + timedelta(days=days)
```

- [ ] **Step 4: Run tests, confirm green**

Run: `uv run pytest tests/test_units.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add src/utils/units.py tests/test_units.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): add units.py with timezone, MET, and week helpers

today_local() returns the date in Europe/London. estimate_kcal_burned
uses a small MET table for the supported activity/intensity pairs.
on_track_status applies a ±0.3 kg tolerance band to compare actual
weight against the linear plan target. Plus ISO week bounds and a
target-date projection for the Plan tab.
MSG
```

---

## Task 4: `food_lookup.py` Open Food Facts client

**Files:**
- Create: `src/utils/food_lookup.py`
- Create: `tests/fixtures/off_tesco_bread.json`
- Create: `tests/fixtures/off_no_kcal.json`
- Create: `tests/test_food_lookup.py`

### Steps

- [ ] **Step 1: Add OFF fixtures**

Create `tests/fixtures/off_tesco_bread.json`:

```json
{
  "status": 1,
  "code": "5012345678900",
  "product": {
    "product_name": "Tesco Wholemeal Bread",
    "serving_size": "44 g",
    "image_small_url": "https://example.com/img.jpg",
    "nutriments": {
      "energy-kcal_100g": 238,
      "proteins_100g": 12,
      "carbohydrates_100g": 41,
      "fat_100g": 2.5,
      "fiber_100g": 6,
      "sugars_100g": 3
    }
  }
}
```

Create `tests/fixtures/off_no_kcal.json`:

```json
{
  "status": 1,
  "code": "0000000000000",
  "product": {
    "product_name": "Mystery Item",
    "nutriments": {
      "proteins_100g": 5
    }
  }
}
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_food_lookup.py`:

```python
import json
from pathlib import Path

import pytest

from utils import food_lookup

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text())


def test_fetch_product_success(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_tesco_bread.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("5012345678900")
    assert product is not None
    assert product.name == "Tesco Wholemeal Bread"
    assert product.serving_size_g == 44.0
    assert product.kcal_per_100g == 238
    assert product.protein_per_100g == 12


def test_fetch_product_not_found(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = {"status": 0}
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    assert food_lookup.fetch_product("9999999999999") is None


def test_fetch_product_http_error(mocker):
    mocker.patch("utils.food_lookup.requests.get", side_effect=Exception("boom"))
    assert food_lookup.fetch_product("5012345678900") is None


def test_fetch_product_missing_kcal_returns_partial(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_no_kcal.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("0000000000000")
    assert product is not None
    assert product.kcal_per_100g is None
    assert product.protein_per_100g == 5


def test_compute_portion_by_grams(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_tesco_bread.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("5012345678900")
    portion = food_lookup.compute_portion(product, grams=88.0, servings=None)
    # 238 * 0.88 = 209.44 -> 209.4 kcal
    assert portion["kcal"] == pytest.approx(209.4, abs=0.1)
    # 12 * 0.88 = 10.56 -> 10.6 g protein
    assert portion["protein_g"] == pytest.approx(10.6, abs=0.1)
    assert portion["fibre_g"] == pytest.approx(5.3, abs=0.1)
    assert portion["effective_grams"] == 88.0


def test_compute_portion_by_servings(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_tesco_bread.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("5012345678900")
    portion = food_lookup.compute_portion(product, grams=None, servings=2.0)
    # 2 servings * 44 g/serving = 88 g => same as the grams case
    assert portion["effective_grams"] == pytest.approx(88.0)
    assert portion["kcal"] == pytest.approx(209.4, abs=0.1)


def test_compute_portion_requires_grams_or_servings(mocker):
    mock_resp = mocker.MagicMock(status_code=200)
    mock_resp.json.return_value = _load("off_tesco_bread.json")
    mocker.patch("utils.food_lookup.requests.get", return_value=mock_resp)

    product = food_lookup.fetch_product("5012345678900")
    with pytest.raises(ValueError):
        food_lookup.compute_portion(product, grams=None, servings=None)


def test_parse_serving_size_handles_units():
    assert food_lookup._parse_serving_size_grams("44 g") == 44.0
    assert food_lookup._parse_serving_size_grams("250ml") is None   # ml ≠ g; skip
    assert food_lookup._parse_serving_size_grams("") is None
    assert food_lookup._parse_serving_size_grams(None) is None
```

- [ ] **Step 3: Run tests, confirm they fail**

Run: `uv run pytest tests/test_food_lookup.py -v`
Expected: All tests fail with `ImportError: cannot import name 'food_lookup'`.

- [ ] **Step 4: Implement `food_lookup.py`**

Create `src/utils/food_lookup.py`:

```python
"""Open Food Facts client + portion-based nutrition computation."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_TIMEOUT_S = 5.0
_NUTRIENTS_PER_100G = ("kcal", "protein", "carbs", "fat", "fibre", "sugar")


@dataclass
class OffProduct:
    barcode: str
    name: str
    serving_size_g: Optional[float]
    kcal_per_100g: Optional[float]
    protein_per_100g: Optional[float]
    carbs_per_100g: Optional[float]
    fat_per_100g: Optional[float]
    fibre_per_100g: Optional[float]
    sugar_per_100g: Optional[float]
    image_url: Optional[str]


def fetch_product(barcode: str) -> Optional[OffProduct]:
    """Look up a product by barcode on Open Food Facts.

    Returns ``None`` if the product isn't in OFF or the request fails.
    Missing nutrients are returned as ``None`` on the product (caller is
    expected to fall back to manual entry for those fields).
    """
    try:
        resp = requests.get(_OFF_URL.format(barcode=barcode), timeout=_TIMEOUT_S)
    except Exception:
        logging.exception("OFF lookup failed for %s", barcode)
        return None

    if resp.status_code != 200:
        return None

    payload = resp.json()
    if payload.get("status") != 1:
        return None

    product = payload.get("product") or {}
    nutriments = product.get("nutriments") or {}

    def _num(key: str) -> Optional[float]:
        value = nutriments.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    return OffProduct(
        barcode=barcode,
        name=product.get("product_name") or "Unknown product",
        serving_size_g=_parse_serving_size_grams(product.get("serving_size")),
        kcal_per_100g=_num("energy-kcal_100g"),
        protein_per_100g=_num("proteins_100g"),
        carbs_per_100g=_num("carbohydrates_100g"),
        fat_per_100g=_num("fat_100g"),
        fibre_per_100g=_num("fiber_100g"),
        sugar_per_100g=_num("sugars_100g"),
        image_url=product.get("image_small_url"),
    )


def compute_portion(
    product: OffProduct,
    *,
    grams: Optional[float],
    servings: Optional[float],
) -> dict:
    """Compute absolute nutrition for a portion of an OFF product.

    Exactly one of ``grams`` or ``servings`` must be provided. ``servings``
    requires the product to have a parsable ``serving_size_g``.
    """
    if grams is None and servings is None:
        raise ValueError("Provide either grams or servings")
    if grams is not None and servings is not None:
        raise ValueError("Provide grams OR servings, not both")
    # Contract: portions must be strictly positive, and the product must
    # carry kcal data (otherwise the saved row would silently be 0 kcal,
    # indistinguishable from a real 0-kcal product like water).
    if grams is not None and grams <= 0:
        raise ValueError("grams must be positive")
    if servings is not None and servings <= 0:
        raise ValueError("servings must be positive")
    if product.kcal_per_100g is None:
        raise ValueError(
            "Product has no kcal data; use manual entry instead"
        )

    if servings is not None:
        if product.serving_size_g is None:
            raise ValueError("Product has no serving size; use grams")
        effective_grams = float(servings) * product.serving_size_g
    else:
        effective_grams = float(grams)

    scale = effective_grams / 100.0

    def _scaled(per_100g: Optional[float]) -> Optional[float]:
        if per_100g is None:
            return None
        return round(per_100g * scale, 1)

    return {
        "effective_grams": round(effective_grams, 2),
        "kcal": _scaled(product.kcal_per_100g),
        "protein_g": _scaled(product.protein_per_100g),
        "carbs_g": _scaled(product.carbs_per_100g),
        "fat_g": _scaled(product.fat_per_100g),
        "fibre_g": _scaled(product.fibre_per_100g),
        "sugar_g": _scaled(product.sugar_per_100g),
    }


_SERVING_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*g\b", re.IGNORECASE)


def _parse_serving_size_grams(raw) -> Optional[float]:
    """Parse Open Food Facts' free-form ``serving_size`` (e.g. ``"44 g"``).

    Only accepts gram-denominated sizes; returns ``None`` for ``ml`` etc.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    match = _SERVING_RE.match(raw)
    return float(match.group(1)) if match else None
```

- [ ] **Step 5: Run tests, confirm green**

Run: `uv run pytest tests/test_food_lookup.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/utils/food_lookup.py tests/test_food_lookup.py tests/fixtures/off_tesco_bread.json tests/fixtures/off_no_kcal.json
git commit -F /dev/stdin <<MSG
feat(weight-loss): add food_lookup.py for Open Food Facts barcode lookup

fetch_product() returns an OffProduct dataclass with per-100g
nutrients. compute_portion() converts a user-entered portion (grams or
servings) into absolute kcal+macros for storage. Missing kcal returns
None so the UI can force manual entry of that field.
MSG
```

---

## Task 5: `badges.py` catalog + evaluator

**Files:**
- Create: `src/utils/badges.py`
- Create: `tests/test_badges.py`

### Steps

- [ ] **Step 1: Write failing tests**

Create `tests/test_badges.py`:

```python
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
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_badges.py -v`
Expected: All fail (`ImportError: cannot import name 'badges'`).

- [ ] **Step 3: Implement `badges.py`**

Create `src/utils/badges.py`:

```python
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
```

- [ ] **Step 4: Run tests, confirm green**

Run: `uv run pytest tests/test_badges.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add src/utils/badges.py tests/test_badges.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): add badges.py catalog + pure evaluator

BADGES dict is the source of truth for badge metadata (name, emoji,
points, hint). evaluate() is pure: takes log DataFrames + plan + the
already-earned set, returns NewBadge tuples to insert. Plan-scoped
weight milestones tag metadata.plan_id so the same badge re-locks for
the next cycle.
MSG
```

---

## Task 6: DB handler — weight plans CRUD + cycle RPC

**Files:**
- Modify: `src/utils/db.py`
- Create: `tests/test_weight_loss_db.py`

### Steps

- [ ] **Step 1: Write failing tests**

Create `tests/test_weight_loss_db.py`:

```python
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
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_weight_loss_db.py -v`
Expected: All fail with `AttributeError: ... has no attribute 'create_weight_plan'`.

- [ ] **Step 3: Implement DB methods**

Append to `src/utils/db.py` inside the `SupabaseHandler` class (and add the exception class at the top of the file, after the imports):

```python
class WeightLossValidationError(ValueError):
    """Raised when a write violates a weight-loss invariant."""
```

Then inside `SupabaseHandler`:

```python
    # =============================================================
    # Weight Loss Tracker
    # =============================================================

    _VLCD_KCAL_FLOOR = 800
    _VLCD_MAX_DAYS = 84  # 12 weeks per NHS guidance
    _KCAL_BOUNDS = (400, 5000)

    def create_weight_plan(
        self,
        *,
        user_id: str,
        start_weight_kg: float,
        target_weight_kg: float,
        weekly_rate_kg: float,
        daily_kcal_target: int,
        weekly_exercise_min_target: int,
        start_date,
        target_date,
        sex: str | None,
        vlcd_acknowledged: bool,
    ) -> str:
        """Insert a new active plan. Returns its id."""
        # Validate VLCD constraints up-front so the partial unique index
        # isn't the first thing the user sees.
        if daily_kcal_target < self._VLCD_KCAL_FLOOR:
            if not vlcd_acknowledged:
                raise WeightLossValidationError(
                    "VLCD plans (<800 kcal) require acknowledgement."
                )
            if (target_date - start_date).days > self._VLCD_MAX_DAYS:
                raise WeightLossValidationError(
                    "VLCD plans cannot exceed 12 weeks (NHS guidance)."
                )
        if not (self._KCAL_BOUNDS[0] <= daily_kcal_target <= self._KCAL_BOUNDS[1]):
            raise WeightLossValidationError(
                f"daily_kcal_target out of bounds {self._KCAL_BOUNDS}"
            )
        if target_weight_kg >= start_weight_kg:
            raise WeightLossValidationError("target_weight must be less than start_weight")

        payload = {
            "user_id": user_id,
            "start_weight_kg": float(start_weight_kg),
            "target_weight_kg": float(target_weight_kg),
            "weekly_rate_kg": float(weekly_rate_kg),
            "daily_kcal_target": int(daily_kcal_target),
            "weekly_exercise_min_target": int(weekly_exercise_min_target),
            "start_date": start_date.isoformat(),
            "target_date": target_date.isoformat(),
            "sex": sex,
            "status": "active",
            "vlcd_acknowledged": bool(vlcd_acknowledged),
        }
        resp = (
            self.supabase.table("weight_plans")
            .insert(payload)
            .execute()
        )
        return resp.data[0]["id"]

    def get_active_weight_plan(self, user_id: str) -> dict | None:
        resp = (
            self.supabase.table("weight_plans")
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None

    def get_weight_plans(self, user_id: str) -> list[dict]:
        resp = (
            self.supabase.table("weight_plans")
            .select("*")
            .eq("user_id", user_id)
            .order("start_date", desc=True)
            .execute()
        )
        return resp.data or []

    def update_weight_plan(
        self,
        *,
        plan_id: str,
        user_id: str,
        daily_kcal_target: int | None = None,
        weekly_exercise_min_target: int | None = None,
        target_date=None,
    ) -> None:
        patch: dict = {}
        if daily_kcal_target is not None:
            patch["daily_kcal_target"] = int(daily_kcal_target)
        if weekly_exercise_min_target is not None:
            patch["weekly_exercise_min_target"] = int(weekly_exercise_min_target)
        if target_date is not None:
            patch["target_date"] = target_date.isoformat()
        if not patch:
            return
        patch["updated_at"] = "now()"
        (
            self.supabase.table("weight_plans")
            .update(patch)
            .eq("id", plan_id)
            .eq("user_id", user_id)
            .execute()
        )

    def abandon_weight_plan(self, *, plan_id: str, user_id: str) -> None:
        (
            self.supabase.table("weight_plans")
            .update({"status": "abandoned", "updated_at": "now()"})
            .eq("id", plan_id)
            .eq("user_id", user_id)
            .execute()
        )

    def complete_and_start_next_plan(
        self,
        *,
        user_id: str,
        old_plan_id: str,
        current_weight_kg: float,
        new_target_weight_kg: float,
        new_target_date,
    ) -> str:
        """Call the atomic RPC; returns the id of the freshly-created plan."""
        resp = self.supabase.rpc(
            "complete_and_start_next_plan",
            {
                "p_user_id": user_id,
                "p_old_plan_id": old_plan_id,
                "p_current_weight_kg": float(current_weight_kg),
                "p_new_target_weight_kg": float(new_target_weight_kg),
                "p_new_target_date": new_target_date.isoformat(),
            },
        ).execute()
        return resp.data
```

- [ ] **Step 4: Run tests, confirm green**

Run: `uv run pytest tests/test_weight_loss_db.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/utils/db.py tests/test_weight_loss_db.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): SupabaseHandler methods for weight_plans + cycle RPC

CRUD on weight_plans with VLCD validation (kcal<800 needs ack +
≤12 weeks). complete_and_start_next_plan delegates to the SQL RPC for
atomic cycle hand-off. Adds WeightLossValidationError for typed
handler errors.
MSG
```

---

## Task 7: DB handler — weight/food/exercise entry CRUD + `load_recent_logs`

**Files:**
- Modify: `src/utils/db.py`
- Modify: `tests/test_weight_loss_db.py`

### Steps

- [ ] **Step 1: Append failing tests**

Append to `tests/test_weight_loss_db.py`:

```python
import pandas as pd


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
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_weight_loss_db.py -v`
Expected: 7 new failures (`AttributeError: 'SupabaseHandler' has no attribute 'save_weight_entry'`).

- [ ] **Step 3: Implement the entry-CRUD methods**

Append to `SupabaseHandler` in `src/utils/db.py`:

```python
    # ---- entry CRUD -------------------------------------------------

    _WEIGHT_BOUNDS = (20.0, 400.0)
    _KCAL_ENTRY_BOUNDS = (0, 20000)
    _DURATION_MIN_BOUNDS = (1, 1440)
    _ALLOWED_INTENSITIES = ("moderate", "vigorous")
    _ALLOWED_SOURCES = ("manual", "barcode")

    def save_weight_entry(
        self, *, user_id: str, log_date, weight_kg: float, notes: str | None = None
    ) -> dict:
        if not (self._WEIGHT_BOUNDS[0] <= weight_kg <= self._WEIGHT_BOUNDS[1]):
            raise WeightLossValidationError(
                f"weight_kg must be in {self._WEIGHT_BOUNDS}"
            )
        payload = {
            "user_id": user_id,
            "log_date": log_date.isoformat(),
            "weight_kg": float(weight_kg),
            "notes": notes,
        }
        resp = (
            self.supabase.table("weight_entries")
            .upsert(payload, on_conflict="user_id,log_date")
            .execute()
        )
        return (resp.data or [{}])[0]

    def save_food_entry(
        self,
        *,
        user_id: str,
        log_date,
        name: str,
        kcal: float,
        portion_g: float | None = None,
        protein_g: float | None = None,
        carbs_g: float | None = None,
        fat_g: float | None = None,
        fibre_g: float | None = None,
        sugar_g: float | None = None,
        log_time=None,
        barcode: str | None = None,
        source: str = "manual",
    ) -> dict:
        if not (self._KCAL_ENTRY_BOUNDS[0] <= kcal <= self._KCAL_ENTRY_BOUNDS[1]):
            raise WeightLossValidationError(
                f"kcal must be in {self._KCAL_ENTRY_BOUNDS}"
            )
        if source not in self._ALLOWED_SOURCES:
            raise WeightLossValidationError(
                f"source must be one of {self._ALLOWED_SOURCES}"
            )
        if not name:
            raise WeightLossValidationError("name is required")

        payload = {
            "user_id": user_id,
            "log_date": log_date.isoformat(),
            "log_time": log_time.isoformat() if log_time else None,
            "name": name,
            "portion_g": float(portion_g) if portion_g is not None else None,
            "kcal": float(kcal),
            "protein_g": float(protein_g) if protein_g is not None else None,
            "carbs_g": float(carbs_g) if carbs_g is not None else None,
            "fat_g": float(fat_g) if fat_g is not None else None,
            "fibre_g": float(fibre_g) if fibre_g is not None else None,
            "sugar_g": float(sugar_g) if sugar_g is not None else None,
            "barcode": barcode,
            "source": source,
        }
        resp = self.supabase.table("food_entries").insert(payload).execute()
        return (resp.data or [{}])[0]

    def save_exercise_entry(
        self,
        *,
        user_id: str,
        log_date,
        activity: str,
        intensity: str,
        duration_min: int,
        kcal_burned: float | None = None,
        notes: str | None = None,
    ) -> dict:
        if intensity not in self._ALLOWED_INTENSITIES:
            raise WeightLossValidationError(
                f"intensity must be one of {self._ALLOWED_INTENSITIES}"
            )
        if not (self._DURATION_MIN_BOUNDS[0] <= duration_min <= self._DURATION_MIN_BOUNDS[1]):
            raise WeightLossValidationError(
                f"duration_min must be in {self._DURATION_MIN_BOUNDS}"
            )
        if not activity:
            raise WeightLossValidationError("activity is required")

        payload = {
            "user_id": user_id,
            "log_date": log_date.isoformat(),
            "activity": activity,
            "intensity": intensity,
            "duration_min": int(duration_min),
            "kcal_burned": float(kcal_burned) if kcal_burned is not None else None,
            "notes": notes,
        }
        resp = self.supabase.table("exercise_entries").insert(payload).execute()
        return (resp.data or [{}])[0]

    def delete_food_entry(self, *, entry_id: str, user_id: str) -> None:
        (
            self.supabase.table("food_entries")
            .delete()
            .eq("id", entry_id)
            .eq("user_id", user_id)
            .execute()
        )

    def delete_exercise_entry(self, *, entry_id: str, user_id: str) -> None:
        (
            self.supabase.table("exercise_entries")
            .delete()
            .eq("id", entry_id)
            .eq("user_id", user_id)
            .execute()
        )

    def update_food_entry(self, *, entry_id: str, user_id: str, **fields) -> dict:
        if not fields:
            return {}
        # Whitelist columns to prevent injection-by-typo.
        allowed = {
            "name", "portion_g", "kcal", "protein_g", "carbs_g", "fat_g",
            "fibre_g", "sugar_g", "log_time", "log_date",
        }
        patch = {k: v for k, v in fields.items() if k in allowed}
        for k in ("log_date", "log_time"):
            if k in patch and hasattr(patch[k], "isoformat"):
                patch[k] = patch[k].isoformat()
        resp = (
            self.supabase.table("food_entries")
            .update(patch)
            .eq("id", entry_id)
            .eq("user_id", user_id)
            .execute()
        )
        return (resp.data or [{}])[0]

    def update_exercise_entry(self, *, entry_id: str, user_id: str, **fields) -> dict:
        if not fields:
            return {}
        allowed = {
            "activity", "intensity", "duration_min", "kcal_burned", "notes", "log_date",
        }
        patch = {k: v for k, v in fields.items() if k in allowed}
        if "log_date" in patch and hasattr(patch["log_date"], "isoformat"):
            patch["log_date"] = patch["log_date"].isoformat()
        resp = (
            self.supabase.table("exercise_entries")
            .update(patch)
            .eq("id", entry_id)
            .eq("user_id", user_id)
            .execute()
        )
        return (resp.data or [{}])[0]

    def load_recent_logs(
        self, user_id: str, since_date
    ) -> tuple["pd.DataFrame", "pd.DataFrame", "pd.DataFrame"]:
        """Return (food_df, exercise_df, weight_df) since ``since_date``."""
        food_resp = (
            self.supabase.table("food_entries")
            .select("*")
            .eq("user_id", user_id)
            .gte("log_date", since_date.isoformat())
            .order("log_date", desc=False)
            .execute()
        )
        ex_resp = (
            self.supabase.table("exercise_entries")
            .select("*")
            .eq("user_id", user_id)
            .gte("log_date", since_date.isoformat())
            .order("log_date", desc=False)
            .execute()
        )
        weight_resp = (
            self.supabase.table("weight_entries")
            .select("*")
            .eq("user_id", user_id)
            .gte("log_date", since_date.isoformat())
            .order("log_date", desc=False)
            .execute()
        )

        def _df(rows, date_cols):
            df = pd.DataFrame(rows or [])
            for c in date_cols:
                if c in df.columns and not df.empty:
                    df[c] = pd.to_datetime(df[c]).dt.date
            return df

        return (
            _df(food_resp.data, ["log_date"]),
            _df(ex_resp.data, ["log_date"]),
            _df(weight_resp.data, ["log_date"]),
        )
```

- [ ] **Step 4: Run tests, confirm green**

Run: `uv run pytest tests/test_weight_loss_db.py -v`
Expected: 14 passed (7 new + 7 from Task 6).

- [ ] **Step 5: Commit**

```bash
git add src/utils/db.py tests/test_weight_loss_db.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): SupabaseHandler methods for weight/food/exercise entries

save/delete/update for each entry type with server-side validation,
plus load_recent_logs() returning a (food, exercise, weight) tuple of
DataFrames for the Today/History tabs.
MSG
```

---

## Task 8: DB handler — badges CRUD

**Files:**
- Modify: `src/utils/db.py`
- Modify: `tests/test_weight_loss_db.py`

### Steps

- [ ] **Step 1: Append failing tests**

Append to `tests/test_weight_loss_db.py`:

```python
def test_record_earned_badges_inserts_rows(handler, fake_supabase, sample_user_id):
    from utils.badges import NewBadge
    fake_supabase.set_table("earned_badges", [{"id": "b1"}])
    new = [NewBadge("first_log", date(2026, 5, 15), 10),
           NewBadge("kcal_streak_7", date(2026, 5, 15), 50, {"streak_length": 7})]
    handler.record_earned_badges(sample_user_id, new)
    chain = fake_supabase._tables["earned_badges"].calls
    inserts = [c for c in chain if c[0] == "insert"]
    assert len(inserts) == 1
    rows = inserts[0][1][0]
    assert len(rows) == 2
    assert rows[0]["badge_key"] == "first_log"
    assert rows[1]["metadata"] == {"streak_length": 7}


def test_record_earned_badges_noop_when_empty(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("earned_badges", [])
    handler.record_earned_badges(sample_user_id, [])
    chain = fake_supabase._tables["earned_badges"].calls
    assert not any(c[0] == "insert" for c in chain)


def test_get_earned_badges(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("earned_badges", [
        {"badge_key": "first_log", "earned_on": "2026-05-15", "points": 10, "metadata": None},
        {"badge_key": "lost_1kg", "earned_on": "2026-05-15", "points": 100,
         "metadata": {"plan_id": "p1"}},
    ])
    rows = handler.get_earned_badges(sample_user_id)
    assert len(rows) == 2
    assert rows[1]["metadata"]["plan_id"] == "p1"


def test_already_earned_set_includes_plan_ids(handler, fake_supabase, sample_user_id):
    fake_supabase.set_table("earned_badges", [
        {"badge_key": "first_log", "earned_on": "2026-05-15", "metadata": None},
        {"badge_key": "lost_1kg", "earned_on": "2026-05-10",
         "metadata": {"plan_id": "p1"}},
    ])
    already = handler.already_earned_keys(sample_user_id)
    assert ("first_log", date(2026, 5, 15)) in already
    assert ("lost_1kg", date(2026, 5, 10), "p1") in already
```

- [ ] **Step 2: Run tests, confirm they fail**

Run: `uv run pytest tests/test_weight_loss_db.py -v`
Expected: 4 new failures (`AttributeError: ... 'record_earned_badges'`).

- [ ] **Step 3: Implement badge persistence**

Append to `SupabaseHandler`:

```python
    # ---- badges ----------------------------------------------------

    def record_earned_badges(self, user_id: str, new_badges: list) -> None:
        """Insert NewBadge rows. No-op for empty input.

        Uses ``upsert(..., ignore_duplicates=True)`` to absorb races against
        the UNIQUE(user_id, badge_key, earned_on) constraint.
        """
        if not new_badges:
            return
        rows = [
            {
                "user_id": user_id,
                "badge_key": b.badge_key,
                "earned_on": b.earned_on.isoformat(),
                "points": b.points,
                "metadata": b.metadata,
            }
            for b in new_badges
        ]
        (
            self.supabase.table("earned_badges")
            .insert(rows)
            .execute()
        )

    def get_earned_badges(self, user_id: str) -> list[dict]:
        resp = (
            self.supabase.table("earned_badges")
            .select("*")
            .eq("user_id", user_id)
            .order("earned_on", desc=True)
            .execute()
        )
        return resp.data or []

    def already_earned_keys(self, user_id: str) -> set:
        """Return the set understood by badges.evaluate's ``already_earned``.

        For plan-scoped badges (those with metadata.plan_id), produces
        3-tuples (key, earned_on, plan_id). Otherwise 2-tuples (key, earned_on).
        """
        from datetime import date as _date

        out = set()
        for row in self.get_earned_badges(user_id):
            key = row["badge_key"]
            earned_on = row["earned_on"]
            if isinstance(earned_on, str):
                earned_on = pd.to_datetime(earned_on).date()
            elif not isinstance(earned_on, _date):
                earned_on = pd.to_datetime(earned_on).date()
            meta = row.get("metadata") or {}
            plan_id = meta.get("plan_id")
            if plan_id is not None:
                out.add((key, earned_on, plan_id))
            else:
                out.add((key, earned_on))
        return out
```

- [ ] **Step 4: Run tests, confirm green**

Run: `uv run pytest tests/test_weight_loss_db.py -v`
Expected: 18 passed.

- [ ] **Step 5: Commit**

```bash
git add src/utils/db.py tests/test_weight_loss_db.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): SupabaseHandler methods for earned_badges

record_earned_badges inserts NewBadge rows. already_earned_keys
returns the (key, earned_on[, plan_id]) tuple set that
badges.evaluate() consumes, so plan-scoped milestone badges re-lock
on new cycles.
MSG
```

---

## Task 9: Page skeleton + Plan tab (create-plan form)

**Files:**
- Create: `src/pages/weight_loss_tracker.py`

### Steps

- [ ] **Step 1: Create the page skeleton with the 4 tabs + auth gate**

Create `src/pages/weight_loss_tracker.py`:

```python
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
```

- [ ] **Step 2: Smoke-test the page imports cleanly**

Run: `uv run python -c "import importlib.util,sys; spec=importlib.util.spec_from_file_location('p','src/pages/weight_loss_tracker.py'); m=importlib.util.module_from_spec(spec); sys.path.insert(0,'src'); print('module loads' if spec else 'no spec')"`
Expected: `module loads`. (We don't execute it — Streamlit needs its runtime — we just confirm imports resolve.)

Alternatively run `uv run streamlit run src/pages/weight_loss_tracker.py` and confirm the page renders the auth gate (then the form once logged in). Stop the server with Ctrl-C.

- [ ] **Step 3: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): page skeleton + Plan tab create-plan form

Four tabs (Today / History / Plan / Rewards) with auth gate. The Plan
tab renders the create-plan form when no active plan exists, with
NHS-3% or custom target, rate radio, VLCD acknowledgement, and a
projected target date. Other tabs are placeholders pending later
tasks.
MSG
```

---

## Task 10: Plan tab — active cycle card + past cycles + next-cycle suggestion

**Files:**
- Modify: `src/pages/weight_loss_tracker.py`

### Steps

- [ ] **Step 1: Replace the Plan tab body**

Replace the `with tab_plan:` block in `src/pages/weight_loss_tracker.py` with:

```python
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

    # Pace + on-track status
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

    # Edit / abandon
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
                db.update_weight_plan(
                    plan_id=plan["id"], user_id=user_id,
                    daily_kcal_target=new_kcal,
                    weekly_exercise_min_target=new_ex,
                    target_date=new_target,
                )
                _invalidate_cache()
                st.rerun()
        if st.button("Abandon this cycle", type="secondary"):
            db.abandon_weight_plan(plan_id=plan["id"], user_id=user_id)
            _invalidate_cache()
            st.rerun()

    # Suggested next cycle
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
                # Badge eval after cycle completion is wired in Task 15.
                st.success(f"Cycle completed; new plan {new_id[:8]}… is active.")
                st.rerun()
            except Exception as exc:
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
```

- [ ] **Step 2: Smoke-run the page**

Run: `uv run streamlit run src/pages/weight_loss_tracker.py` (then Ctrl-C).
Expected: no traceback on startup; with an active plan, the active card renders; with no plan, the form from Task 9 renders.

- [ ] **Step 3: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): Plan tab active-cycle card + past cycles + next cycle

Active-cycle card shows start→target, current weight, progress, pace,
and on-track status. Edit expander adjusts kcal/exercise/target date,
or abandons. When current weight is within 1 kg of target, a
"complete current & start next" button invokes the RPC to chain the
next 3% cycle. Past cycles render as a small table below.
MSG
```

---

## Task 11: Today tab — date picker, summary cards, weight entry

**Files:**
- Modify: `src/pages/weight_loss_tracker.py`

### Steps

- [ ] **Step 1: Add helper for summary metrics**

Inside `src/pages/weight_loss_tracker.py`, above the `tab_today` block, add:

```python
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
    kcal_burn = float(today_ex["kcal_burned"].sum()) if not today_ex.empty and "kcal_burned" in today_ex else 0.0
    today_min = int(today_ex["duration_min"].sum()) if not today_ex.empty else 0
    week_min_moderate = int(week_ex.loc[week_ex["intensity"] == "moderate", "duration_min"].sum()) if not week_ex.empty else 0
    week_min_vigorous = int(week_ex.loc[week_ex["intensity"] == "vigorous", "duration_min"].sum()) if not week_ex.empty else 0
    week_equiv_min = moderate_equivalent_minutes(moderate=week_min_moderate, vigorous=week_min_vigorous)

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
            weight_delta_7d = round(weight_today - float(ago_rows.iloc[-1]["weight_kg"]), 1)

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
```

- [ ] **Step 2: Replace the `tab_today` block**

Replace `with tab_today: st.info("...")` with:

```python
with tab_today:
    if active_plan is None:
        st.info("Create a plan first on the 🎯 Plan tab.")
    else:
        col_date, _ = st.columns([2, 5])
        with col_date:
            log_date = st.date_input(
                "Date", value=today_local(), max_value=today_local(), key="today_date",
            )

        if int(active_plan["daily_kcal_target"]) < 800:
            day_n = (log_date - pd.to_datetime(active_plan["start_date"]).date()).days + 1
            st.warning(
                f"⚠️ VLCD plan — day {day_n} of 84 (NHS max 12 weeks)."
            )

        # Load 14-day window for the cards (covers the 7-day delta look-back).
        since = log_date - pd.Timedelta(days=21)
        food_df, ex_df, weight_df = _load_recent(user_id, since.date() if hasattr(since, "date") else since)

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
                            _invalidate_cache()
                            st.success("Weight saved.")
                            st.rerun()
                        except Exception as exc:
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
            st.progress(min(m["week_equiv_min"] / max(m["weekly_target_min"], 1), 1.0))

        st.divider()
        st.info("Food and exercise forms come in Tasks 12–14.")
```

- [ ] **Step 3: Smoke-run**

Run: `uv run streamlit run src/pages/weight_loss_tracker.py` (Ctrl-C to stop). With an active plan, the three metric cards should render; without one, the "Create a plan first" CTA should show. Saving a weight via the popover should refresh the card.

- [ ] **Step 4: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): Today tab summary cards + weight logging

Date picker (defaults to today, no future dates). Three summary cards
(weight/kcal/exercise) showing today's intake vs target and weekly
exercise vs the plan target. Weight popover saves via save_weight_entry
and re-renders. VLCD plans show a "day X/84" banner.
MSG
```

---

## Task 12: Today tab — manual food form

**Files:**
- Modify: `src/pages/weight_loss_tracker.py`

### Steps

- [ ] **Step 1: Add the food-entry section**

Replace `st.info("Food and exercise forms come in Tasks 12–14.")` in the `tab_today` block with a section heading and the manual/barcode sub-tabs scaffold (we'll fill the barcode branch in Task 13):

```python
        st.subheader("+ Add food")
        food_tab_manual, food_tab_barcode = st.tabs(["Manual", "Barcode"])

        with food_tab_manual:
            with st.form("manual_food"):
                col_a, col_b = st.columns([2, 1])
                name = col_a.text_input("Name", placeholder="e.g. Tuna salad")
                portion = col_b.number_input(
                    "Portion (g, optional)", min_value=0.0, max_value=5000.0,
                    value=0.0, step=10.0,
                )
                col_c1, col_c2, col_c3, col_c4 = st.columns(4)
                kcal = col_c1.number_input("kcal", min_value=0.0, max_value=20000.0, value=0.0, step=10.0)
                protein = col_c2.number_input("protein (g)", min_value=0.0, max_value=500.0, value=0.0, step=1.0)
                carbs = col_c3.number_input("carbs (g)", min_value=0.0, max_value=2000.0, value=0.0, step=1.0)
                fat = col_c4.number_input("fat (g)", min_value=0.0, max_value=500.0, value=0.0, step=1.0)
                col_d1, col_d2 = st.columns(2)
                fibre = col_d1.number_input("fibre (g)", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
                sugar = col_d2.number_input("sugar (g)", min_value=0.0, max_value=500.0, value=0.0, step=1.0)

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
                        _invalidate_cache()
                        st.success("Food entry saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

        with food_tab_barcode:
            st.info("Barcode lookup — implemented in Task 13.")
```

- [ ] **Step 2: Smoke-run**

Run: `uv run streamlit run src/pages/weight_loss_tracker.py`. Verify the Manual tab renders, accepts entries, and that submitting updates the "Calories" card.

- [ ] **Step 3: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): Today tab manual food entry form

Single st.form for name + optional portion + kcal + macros (protein/
carbs/fat/fibre/sugar) — absolute values, fast path. Save invokes
save_food_entry with source='manual' and triggers cache invalidation
+ rerun so the summary cards refresh.
MSG
```

---

## Task 13: Today tab — barcode food flow

**Files:**
- Modify: `src/pages/weight_loss_tracker.py`

> Note: the page-side `if product.kcal_per_100g is None: st.warning(...)`
> guard below short-circuits the portion form for kcal-less products.
> `compute_portion` ALSO raises `ValueError` in that case (post-review
> hardening) — so the page guard is now belt-and-suspenders. Either layer
> alone would prevent a phantom 0-kcal row; we keep both for clearer UX
> on the page and a hard contract in the helper.

### Steps

- [ ] **Step 1: Replace the barcode placeholder with the lookup UI**

Replace `with food_tab_barcode: st.info("Barcode lookup — implemented in Task 13.")` with:

```python
        with food_tab_barcode:
            if "off_cache" not in st.session_state:
                st.session_state.off_cache = {}

            col_bc, col_btn = st.columns([3, 1])
            barcode_input = col_bc.text_input(
                "Scan or type barcode", key="barcode_input", placeholder="e.g. 5012345678900"
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
                        "No kcal data on the product. Use Manual entry for this one."
                    )
                else:
                    use_serving = (
                        product.serving_size_g is not None
                        and st.radio(
                            "Portion mode",
                            options=["Grams", f"Servings ({product.serving_size_g:.0f} g each)"],
                            horizontal=True,
                            key="portion_mode",
                        ).startswith("Servings")
                    )
                    if use_serving:
                        n = st.number_input("Servings", min_value=0.1, max_value=20.0,
                                            value=1.0, step=0.1, key="portion_servings")
                        preview = compute_portion(product, grams=None, servings=float(n))
                    else:
                        g = st.number_input("Grams", min_value=1.0, max_value=5000.0,
                                            value=product.serving_size_g or 100.0,
                                            step=10.0, key="portion_grams")
                        preview = compute_portion(product, grams=float(g), servings=None)

                    preview_caption = (
                        f"**Preview ({preview['effective_grams']} g):** "
                        f"{preview['kcal']} kcal · P {preview['protein_g']} · "
                        f"C {preview['carbs_g']} · F {preview['fat_g']} · "
                        f"Fibre {preview['fibre_g']} · Sug {preview['sugar_g']}"
                    )
                    st.markdown(preview_caption)

                    if st.button("Save barcode entry", type="primary", key="save_barcode"):
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
                            _invalidate_cache()
                            st.success("Food entry saved from barcode.")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))
```

- [ ] **Step 2: Smoke-run**

Run: `uv run streamlit run src/pages/weight_loss_tracker.py`. In the Barcode tab, enter a real barcode (e.g. one from a product in your kitchen) → look up → confirm preview computes → save. Verify the row appears in the cards.

If you have no real barcode handy, use Open Food Facts' demo `737628064502` (Petit Filous-style snack) — known to be present.

- [ ] **Step 3: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): Today tab barcode food lookup

Uses fetch_product against Open Food Facts; on hit, previews per-100g
nutrients and computes the absolute consumed nutrition from a
portion (grams or, when available, servings). Saves with
source='barcode' and the OFF product name. Cached per session_state.
MSG
```

---

## Task 14: Today tab — exercise form + today's combined log table

**Files:**
- Modify: `src/pages/weight_loss_tracker.py`

### Steps

- [ ] **Step 1: Add exercise form**

Inside the `tab_today` block, after the food-tabs section, add:

```python
        st.divider()
        st.subheader("+ Add exercise")
        with st.form("exercise_form"):
            cols = st.columns([2, 2, 1])
            activity = cols[0].selectbox(
                "Activity",
                options=["walking", "running", "cycling", "swimming", "gym", "other"],
            )
            intensity = cols[1].radio(
                "Intensity", options=["moderate", "vigorous"], horizontal=True,
            )
            duration = cols[2].number_input(
                "Minutes", min_value=1, max_value=600, value=30, step=5,
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
                    _invalidate_cache()
                    st.success("Exercise saved.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
```

- [ ] **Step 2: Add today's combined log table**

Append to the `tab_today` block:

```python
        st.divider()
        st.subheader("Today's log")
        today_food = food_df[food_df["log_date"] == log_date] if not food_df.empty else pd.DataFrame()
        today_ex = ex_df[ex_df["log_date"] == log_date] if not ex_df.empty else pd.DataFrame()

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
                    "macros (P/C/F)": f"{int(r.get('protein_g') or 0)}/"
                                     f"{int(r.get('carbs_g') or 0)}/"
                                     f"{int(r.get('fat_g') or 0)}",
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
            log_df = log_df.sort_values("time", kind="stable")
            st.dataframe(
                log_df.drop(columns=["id", "kind"]),
                use_container_width=True, hide_index=True,
            )
            with st.expander("Delete an entry"):
                pick = st.selectbox(
                    "Pick entry",
                    options=log_df.index,
                    format_func=lambda i: f"[{log_df.loc[i,'kind']}] {log_df.loc[i,'item']}",
                )
                if st.button("Delete selected", type="secondary"):
                    row = log_df.loc[pick]
                    if row["kind"] == "food":
                        db.delete_food_entry(entry_id=row["id"], user_id=user_id)
                    else:
                        db.delete_exercise_entry(entry_id=row["id"], user_id=user_id)
                    _invalidate_cache()
                    st.rerun()
```

- [ ] **Step 3: Smoke-run**

Run: `uv run streamlit run src/pages/weight_loss_tracker.py`. Log an exercise; confirm the burn estimate is shown live; the entry appears in "Today's log"; delete it via the expander and confirm it disappears.

- [ ] **Step 4: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): Today tab exercise form + combined today's log

Exercise form shows a live MET-based kcal-burn estimate from
units.estimate_kcal_burned (using today's weight if known, else the
plan's start weight). Today's log fuses food + exercise rows into one
table sorted by time, with a delete expander that hits the right CRUD
method per row kind.
MSG
```

---

## Task 15: Wire badge evaluation into every save

**Files:**
- Modify: `src/pages/weight_loss_tracker.py`

### Steps

- [ ] **Step 1: Add a helper that re-evaluates badges and toasts new ones**

Above the tabs in `src/pages/weight_loss_tracker.py`, add:

```python
def _evaluate_and_record_badges(*, target_date: date) -> list:
    """Pull recent logs, evaluate, persist new badges, toast each one.

    Returns the list of newly-inserted NewBadge instances (mainly for tests
    / future telemetry).
    """
    # 60-day window is enough for streaks up to 30 + macros and current-week math.
    since = target_date - pd.Timedelta(days=60)
    food_df, ex_df, weight_df = db.load_recent_logs(user_id, since.date() if hasattr(since, "date") else since)
    plans = db.get_weight_plans(user_id)
    plan_df = pd.DataFrame(plans)
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
```

- [ ] **Step 2: Call the helper after every successful save**

Edit the following locations in `src/pages/weight_loss_tracker.py` — immediately *before* `_invalidate_cache()` in each save handler — and add a call to `_evaluate_and_record_badges(target_date=log_date)` (use `today_local()` instead of `log_date` for the cycle-completion path and the create-plan path):

- `with st.form("log_weight")` → save weight handler
- `with st.form("manual_food")` → save manual food handler
- `with st.form("exercise_form")` → save exercise handler
- `if st.button("Save barcode entry", ...)` → barcode save handler
- `db.create_weight_plan(...)` in `_render_create_plan_form` → use `_evaluate_and_record_badges(target_date=today_local())` after `_invalidate_cache()`
- `db.complete_and_start_next_plan(...)` in `_render_active_cycle_card` → call after `_invalidate_cache()`

Example diff for the weight handler:

```python
                if st.form_submit_button("Save weight"):
                    try:
                        db.save_weight_entry(
                            user_id=user_id, log_date=log_date,
                            weight_kg=float(w), notes=note or None,
                        )
                        _evaluate_and_record_badges(target_date=log_date)
                        _invalidate_cache()
                        st.success("Weight saved.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
```

Apply the same pattern to the other five save points.

- [ ] **Step 3: Smoke-test**

Run: `uv run streamlit run src/pages/weight_loss_tracker.py`. Save your first food entry — expect a `📔 First log — +10 pts!` toast. Save your first weigh-in — expect `⚖️ First weigh-in`. Save 7 consecutive under-target food entries — expect `🥇 7-day kcal streak`.

- [ ] **Step 4: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): wire badge evaluation into every save

After each save (weight/food/exercise/plan/cycle-complete), reload a
60-day window, run badges.evaluate, insert any new earnings, and
st.toast() each one. Plan creation and cycle completion also trigger
evaluation so first_plan / cycle_completed fire.
MSG
```

---

## Task 16: History tab — chart + weekly stats + detail table + CSV

**Files:**
- Modify: `src/pages/weight_loss_tracker.py`

### Steps

- [ ] **Step 1: Replace the History placeholder**

Replace `with tab_history: st.info(...)` with:

```python
with tab_history:
    if active_plan is None and not plans:
        st.info("Create a plan first on the 🎯 Plan tab.")
    else:
        range_label = st.radio(
            "Range",
            options=["30d", "90d", "Plan-to-date", "All", "Custom"],
            horizontal=True, key="history_range",
        )
        today = today_local()
        if range_label == "30d":
            since = today - pd.Timedelta(days=30)
        elif range_label == "90d":
            since = today - pd.Timedelta(days=90)
        elif range_label == "Plan-to-date" and active_plan is not None:
            since = pd.to_datetime(active_plan["start_date"]).date()
        elif range_label == "All":
            since = date(2000, 1, 1)
        else:
            c1, c2 = st.columns(2)
            since = c1.date_input("From", value=today - pd.Timedelta(days=30).to_pytimedelta())
            until_input = c2.date_input("To", value=today)
            today = until_input  # narrow upper bound

        since_date = since if isinstance(since, date) else since.date()
        food_df, ex_df, weight_df = db.load_recent_logs(user_id, since_date)

        # --- Weight chart ---------------------------------------------
        import plotly.graph_objects as go
        fig = go.Figure()
        if not weight_df.empty:
            ws = weight_df.sort_values("log_date")
            fig.add_trace(go.Scatter(
                x=ws["log_date"], y=ws["weight_kg"],
                mode="lines+markers", name="Actual",
            ))
        if active_plan is not None:
            start_d = pd.to_datetime(active_plan["start_date"]).date()
            target_d = pd.to_datetime(active_plan["target_date"]).date()
            fig.add_trace(go.Scatter(
                x=[start_d, target_d],
                y=[float(active_plan["start_weight_kg"]),
                   float(active_plan["target_weight_kg"])],
                mode="lines", name="Plan target",
                line=dict(dash="dash"),
            ))
        fig.update_layout(
            title="Weight trend", xaxis_title="Date", yaxis_title="kg",
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

        # --- Weekly stats --------------------------------------------
        if not (food_df.empty and ex_df.empty and weight_df.empty):
            st.subheader("Weekly stats")
            week_rows = _weekly_stats(
                food_df=food_df, ex_df=ex_df, weight_df=weight_df,
                plan=active_plan,
            )
            st.dataframe(pd.DataFrame(week_rows), use_container_width=True, hide_index=True)

        # --- Detail table + CSV --------------------------------------
        st.subheader("Detail")
        which = st.radio("Show", options=["Food", "Exercise"], horizontal=True)
        detail_df = food_df if which == "Food" else ex_df
        if detail_df.empty:
            st.caption("No entries in range.")
        else:
            st.dataframe(detail_df, use_container_width=True, hide_index=True)
            csv = detail_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                f"Download {which.lower()} CSV",
                data=csv,
                file_name=f"{which.lower()}_{since_date}_{today}.csv",
                mime="text/csv",
            )
```

- [ ] **Step 2: Add the `_weekly_stats` helper**

Above the tabs, add:

```python
def _weekly_stats(*, food_df, ex_df, weight_df, plan) -> list[dict]:
    if food_df.empty and ex_df.empty and weight_df.empty:
        return []
    # Union of week starts across all three frames.
    all_dates = pd.concat([
        food_df["log_date"] if "log_date" in food_df else pd.Series(dtype="object"),
        ex_df["log_date"] if "log_date" in ex_df else pd.Series(dtype="object"),
        weight_df["log_date"] if "log_date" in weight_df else pd.Series(dtype="object"),
    ]).dropna().unique()
    if len(all_dates) == 0:
        return []

    weeks = sorted({iso_week_bounds(pd.to_datetime(d).date())[0] for d in all_dates}, reverse=True)
    daily_kcal_target = int(plan["daily_kcal_target"]) if plan else None
    weekly_min_target = int(plan["weekly_exercise_min_target"]) if plan else None
    rows = []
    for mon in weeks:
        sun = mon + pd.Timedelta(days=6)
        week_food = food_df[(food_df["log_date"] >= mon) & (food_df["log_date"] <= sun.date())] if not food_df.empty else pd.DataFrame()
        week_ex = ex_df[(ex_df["log_date"] >= mon) & (ex_df["log_date"] <= sun.date())] if not ex_df.empty else pd.DataFrame()
        week_w = weight_df[(weight_df["log_date"] >= mon) & (weight_df["log_date"] <= sun.date())] if not weight_df.empty else pd.DataFrame()

        avg_kcal = (
            int(week_food.groupby("log_date")["kcal"].sum().mean())
            if not week_food.empty else None
        )
        mod = int(week_ex.loc[week_ex["intensity"] == "moderate", "duration_min"].sum()) if not week_ex.empty else 0
        vig = int(week_ex.loc[week_ex["intensity"] == "vigorous", "duration_min"].sum()) if not week_ex.empty else 0
        equiv_min = moderate_equivalent_minutes(moderate=mod, vigorous=vig)
        delta_w = None
        if not week_w.empty:
            delta_w = round(float(week_w.sort_values("log_date").iloc[-1]["weight_kg"])
                            - float(week_w.sort_values("log_date").iloc[0]["weight_kg"]), 2)
        goals = []
        if daily_kcal_target is not None and avg_kcal is not None:
            goals.append("✓" if avg_kcal <= daily_kcal_target else "✗")
        if weekly_min_target is not None:
            goals.append("✓" if equiv_min >= weekly_min_target else "✗")
        rows.append({
            "Week": f"{mon} → {sun.date()}",
            "Avg kcal": avg_kcal,
            "Exercise (mod-eq min)": equiv_min,
            "Δ weight (kg)": delta_w,
            "Goals": " ".join(goals) or "—",
        })
    return rows
```

- [ ] **Step 3: Smoke-run**

Run: `uv run streamlit run src/pages/weight_loss_tracker.py`. Switch the range radio, confirm chart + table update. Check the CSV download produces a file with expected columns.

- [ ] **Step 4: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): History tab — chart, weekly stats, detail table, CSV

Range picker (30d/90d/plan/all/custom) drives all three components.
Weight trend chart overlays the linear plan-target line. Weekly stats
aggregate ISO-week kcal averages, moderate-equivalent minutes,
weight delta, and goal ticks. Food/exercise detail table exports to
CSV via st.download_button.
MSG
```

---

## Task 17: Rewards tab — header + earned/locked grids

**Files:**
- Modify: `src/pages/weight_loss_tracker.py`

### Steps

- [ ] **Step 1: Replace the Rewards placeholder**

Replace `with tab_rewards: st.info(...)` with:

```python
with tab_rewards:
    earned = db.get_earned_badges(user_id)
    total_points = sum(int(r.get("points") or 0) for r in earned)

    # Streak — derive on the fly from food_df.
    food_df_all, _, _ = db.load_recent_logs(user_id, today_local() - pd.Timedelta(days=60))
    streak_len = 0
    if active_plan is not None and not food_df_all.empty:
        daily = food_df_all.groupby("log_date")["kcal"].sum()
        cursor = today_local()
        if cursor not in daily.index:
            cursor = cursor - pd.Timedelta(days=1).to_pytimedelta()
            cursor = cursor if isinstance(cursor, date) else cursor.date()
        target = int(active_plan["daily_kcal_target"])
        while cursor in daily.index and daily.loc[cursor] <= target:
            streak_len += 1
            cursor -= pd.Timedelta(days=1).to_pytimedelta()
            if not isinstance(cursor, date):
                cursor = cursor.date()

    hcol1, hcol2 = st.columns(2)
    hcol1.metric("Total points", total_points)
    hcol2.metric("Current streak", f"{streak_len} days 🔥" if streak_len else "—")

    earned_keys = {r["badge_key"] for r in earned}
    # Plan-scoped milestones may legitimately appear "locked" if they were
    # earned only in a previous plan; we use the same heuristic as the
    # already_earned_keys logic in db.py.
    earned_keys_with_plan = {(r["badge_key"], (r.get("metadata") or {}).get("plan_id"))
                             for r in earned}
    active_plan_id = active_plan["id"] if active_plan else None

    def _is_earned(key: str) -> bool:
        # Plan-scoped badges: only count as "earned" if earned in current plan.
        if key in ("lost_1kg", "lost_3kg", "lost_5kg", "lost_5pct_body"):
            return (key, active_plan_id) in earned_keys_with_plan
        # Streak badges and one-shots: any earning counts.
        return key in earned_keys

    earned_list = [r for r in earned if _is_earned(r["badge_key"])]
    locked_list = [(k, info) for k, info in BADGES.items() if not _is_earned(k)]

    st.subheader(f"Earned ({len(earned_list)})")
    if not earned_list:
        st.caption("No badges yet — log your first meal or weigh-in to start.")
    else:
        for chunk_start in range(0, len(earned_list), 6):
            cols = st.columns(6)
            for col, row in zip(cols, earned_list[chunk_start:chunk_start + 6]):
                meta = BADGES.get(row["badge_key"], {})
                col.markdown(
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:36px'>{meta.get('emoji','🏅')}</div>"
                    f"<div style='font-weight:600'>{meta.get('name', row['badge_key'])}</div>"
                    f"<div style='color:#666'>{row['earned_on']} · +{row['points']} pts</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    st.subheader(f"Locked ({len(locked_list)})")
    if not locked_list:
        st.caption("All badges earned. 🏆")
    else:
        for chunk_start in range(0, len(locked_list), 6):
            cols = st.columns(6)
            for col, (key, info) in zip(cols, locked_list[chunk_start:chunk_start + 6]):
                col.markdown(
                    f"<div style='text-align:center; opacity:0.55'>"
                    f"<div style='font-size:36px'>🔒</div>"
                    f"<div style='font-weight:600'>{info['name']}</div>"
                    f"<div style='color:#666'>+{info['points']} pts</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if info.get("rule"):
                    col.caption(info["rule"])
```

- [ ] **Step 2: Smoke-run**

Run: `uv run streamlit run src/pages/weight_loss_tracker.py`. Verify:
- Total points equals the sum of earned points.
- Streak counter shows the right number when you have consecutive under-target days.
- Earned grid lists awarded badges; Locked grid lists everything else with the "rule" tooltip below each tile.

- [ ] **Step 3: Commit**

```bash
git add src/pages/weight_loss_tracker.py
git commit -F /dev/stdin <<MSG
feat(weight-loss): Rewards tab — earned/locked badge grids + streak

Header shows total points + current under-target kcal streak (derived
live from food_entries, scoped to the active plan's kcal target).
Earned grid lists awarded badges with earned_on/points. Locked grid
shows the catalog's remaining badges with their unlock-rule captions.
Plan-scoped milestones re-lock when a new cycle starts.
MSG
```

---

## Task 18: End-to-end manual verification

**Files:** none changed; a checklist to run through.

### Steps

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -v`
Expected: all 30+ tests pass.

- [ ] **Step 2: Confirm the migration applies cleanly**

Run against an empty Supabase: `npx supabase db reset` then `npx supabase db push`. No errors. Inspect the five tables in Supabase Studio.

- [ ] **Step 3: Run the app and walk the happy path**

```bash
uv run streamlit run src/homepage.py
```

Walk:
1. Log in with Google.
2. Open **Weight Loss Tracker** from the sidebar.
3. Create a plan with default 3% target. Confirm `first_plan` toast.
4. Today tab: log a weigh-in. Confirm `first_weigh_in` toast + Weigh-in card updates.
5. Today tab → Manual food: enter a 600 kcal meal. Confirm `first_log` toast + Calories card updates.
6. Today tab → Barcode food: look up a real barcode, save. Confirm row in Today's log with `source = barcode`.
7. Today tab → Exercise: log 30 min moderate walking. Confirm `first_workout` toast.
8. History tab: confirm chart + weekly stats render with the one week of data.
9. Rewards tab: confirm 4–5 badges earned, others locked with hints.
10. Plan tab → Edit plan: change kcal target, save. Refresh; confirm change persists.
11. (Optional) Manually update your weight low enough to be within 1 kg of target → confirm "Suggested next cycle" appears → click "Complete current & start next" → confirm new active plan.

- [ ] **Step 4: Final commit / nothing to commit**

If any small fixes came up during the walkthrough, commit them. Otherwise no commit needed.

---

## Spec coverage check

| Spec section | Task(s) |
|---|---|
| §3 Page architecture (4 tabs) | Task 9 |
| §5.1 weight_plans + RPC | Task 2 (table+RPC), 6 (handler), 9-10 (UI) |
| §5.2 weight_entries | Task 2, 7, 11 |
| §5.3 food_entries | Task 2, 7, 12, 13 |
| §5.4 exercise_entries | Task 2, 7, 14 |
| §5.5 earned_badges | Task 2, 8, 15 |
| §6.1 Today tab (cards, manual food, barcode food, exercise, log table) | Tasks 11–14 |
| §6.2 History tab (chart, weekly stats, detail, CSV) | Task 16 |
| §6.3 Plan tab (create form, active card, past cycles, next cycle) | Tasks 9–10 |
| §6.4 Rewards tab (header, earned/locked, streak) | Task 17 |
| Badge evaluation on saves | Task 15 |
| §7.1 Units/locale (Europe/London, kg, kcal) | Task 3 |
| §7.2 Validation (server-side bounds, VLCD) | Task 6, 7 |
| §7.3 Auth (st.user.sub) | Task 9 |
| §7.4 Empty states | Tasks 9, 11, 16 |
| §7.5 Performance (load_recent_logs + cache_data) | Task 7, 9 |
| §8 Testing (units, badges, food_lookup, db) | Tasks 1, 3, 4, 5, 6, 7, 8 |
