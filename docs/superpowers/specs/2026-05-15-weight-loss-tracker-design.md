# Weight Loss Tracker — Design Spec

| | |
|---|---|
| **Branch** | `feature/weight-loss-tracker` |
| **Status** | Approved (brainstorm). Awaiting implementation plan. |
| **Effort** | Large (single coherent feature, multiple subsystems) |
| **Reference** | [NHS obesity treatment guidance](https://www.nhs.uk/conditions/obesity/treatment/) |

## 1. Goal

Add a new page to the dashboard that helps a user run a structured, NHS-aligned weight-loss programme: define a plan, log daily food and exercise, see weekly progress, and earn badges. All data is per-user (Google OAuth, same pattern as the existing tracker).

## 2. Scope

### In scope (v1)

1. **Plan** — set start weight, target weight, weekly rate, daily kcal target, weekly exercise minutes target. Sequential 3% cycles with cycle history. VLCD (<800 kcal) acknowledgement + 12-week cap.
2. **Weight log** — one entry per calendar day, trend chart on the History tab.
3. **Food tracking** — manual nutrition entry (absolute values) and barcode lookup via [Open Food Facts](https://world.openfoodfacts.org/). Captures kcal + protein + carbs + fat + fibre + sugar.
4. **Exercise tracking** — minutes + intensity (moderate/vigorous) + activity type + estimated kcal burned (MET-based). Vigorous minutes count 2× toward the NHS weekly moderate-equivalent total.
5. **Rewards** — system-defined badges (catalog in `badges.py`) earned by hitting kcal streaks, exercise targets, weight milestones, and plan-completion events. Points total displayed; no virtual currency or redemption.

### Out of scope (v1)

- Email or in-app reminders of any kind. Today tab already shows live progress; that is the entire reminder surface.
- Live camera barcode scanning. Only typed/pasted barcodes are supported.
- Forest-style growing visual / mini-game rewards.
- User-defined custom badges (could be added later as a `custom_goals` table on top of the system catalog).
- Macro trend charts, body-fat %, photos.
- Food search by name. Either barcode lookup or manual entry.
- Unit conversions (kg/lb, kcal/kJ). The app is kg + kcal only.
- Supabase RLS — handlers enforce row scoping by `user_id`, matching the existing dashboard's pattern.

## 3. Page architecture

Single Streamlit page with four tabs:

```
📅 Today   |   📈 History   |   🎯 Plan   |   🏆 Rewards
```

Layout B from the brainstorm session: **Today-first dashboard**. The most common action is "log what I just ate / did", so Today is the default tab and combines weight, food, and exercise in one place.

## 4. File layout

```
src/pages/weight_loss_tracker.py     # new — single Streamlit page with 4 tabs
src/utils/db.py                      # extend SupabaseHandler with weight-loss methods
src/utils/models.py                  # add Plan, WeightEntry, FoodEntry, ExerciseEntry, EarnedBadge dataclasses
src/utils/food_lookup.py             # new — Open Food Facts client + portion compute, session-scoped cache
src/utils/badges.py                  # new — pure functions: given recent logs, return earned badges
src/utils/units.py                   # new — MET kcal-burn, vigorous-minute conversion, "today_local", "on track" band

supabase/migrations/<ts>_create_weight_loss_tables.sql

tests/test_units.py
tests/test_badges.py
tests/test_food_lookup.py
tests/test_weight_loss_db.py
```

Mirrors the existing one-file-per-page convention. All cross-cutting helpers in `src/utils/*` so the page file stays thin (the bet: if the utilities are tested, the page is correct).

## 5. Data model

Five tables, all in one migration. Every table follows the existing pattern: `user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE`, UUID primary keys, indexes on `user_id`.

```sql
-- 1. Plans. Sequential cycles chain via previous_plan_id.
CREATE TABLE weight_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_weight_kg DECIMAL(6,2) NOT NULL,
    target_weight_kg DECIMAL(6,2) NOT NULL,
    weekly_rate_kg DECIMAL(4,2) NOT NULL,
    daily_kcal_target INT NOT NULL,
    weekly_exercise_min_target INT NOT NULL DEFAULT 150,
    start_date DATE NOT NULL,
    target_date DATE NOT NULL,
    sex CHAR(1),                                       -- 'M'/'F'/NULL, drives default kcal target
    previous_plan_id UUID REFERENCES weight_plans(id),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','completed','abandoned')),
    vlcd_acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_weight_plans_one_active
    ON weight_plans(user_id) WHERE status = 'active';
CREATE INDEX idx_weight_plans_user ON weight_plans(user_id);

-- 2. Weight log: one entry per day (upsert on conflict).
CREATE TABLE weight_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    weight_kg DECIMAL(6,2) NOT NULL,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, log_date)
);
CREATE INDEX idx_weight_entries_user_date ON weight_entries(user_id, log_date DESC);

-- 3. Food entries: many per day. Absolute values for the portion consumed.
CREATE TABLE food_entries (
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
CREATE INDEX idx_food_entries_user_date ON food_entries(user_id, log_date DESC);

-- 4. Exercise entries: many per day.
CREATE TABLE exercise_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date DATE NOT NULL,
    activity TEXT NOT NULL,
    intensity TEXT NOT NULL
        CHECK (intensity IN ('moderate','vigorous')),
    duration_min INT NOT NULL CHECK (duration_min > 0),
    kcal_burned DECIMAL(7,1),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_exercise_entries_user_date ON exercise_entries(user_id, log_date DESC);

-- 5. Earned badges. Streak/weekly badges re-earn on different dates.
CREATE TABLE earned_badges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    badge_key TEXT NOT NULL,
    earned_on DATE NOT NULL,
    points INT NOT NULL DEFAULT 0,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, badge_key, earned_on)
);
CREATE INDEX idx_earned_badges_user ON earned_badges(user_id, earned_on DESC);
```

### Key data-model decisions

- **`idx_weight_plans_one_active`** is a partial unique index. The database, not the app, enforces at-most-one-active-plan-per-user. No race conditions.
- **`vlcd_acknowledged`** records the user's explicit consent if `daily_kcal_target < 800` (very low calorie diet, NHS max 12 weeks). Both the form and the DB handler refuse to save a VLCD plan without this flag, and refuse `target_date − start_date > 84 days` for VLCD plans.
- **`earned_badges.badge_key` is a string, not an FK** to a catalog table. The catalog lives in `src/utils/badges.py` as a Python dict. Adding a badge is a code change anyway (the rule is code) — keeping the metadata next to the rule avoids two sources of truth.
- **`metadata JSONB`** lets streak/weight-milestone badges attach context (`{"streak_length": 14}`, `{"plan_id": "..."}`) without per-badge columns.
- **Weight loss is single-user-scope data**. No sharing, no RLS in v1 (consistent with the rest of the dashboard).

## 6. Tab specs

### 6.1 Today tab — `📅 Today`

Default tab. Goal: ≤ 10 seconds to log a meal or workout.

**Layout (top → bottom)**:

1. **Date picker** at the top. Defaults to `today_local()` (Europe/London). Lets the user backfill past dates; future dates disabled.
2. **VLCD warning banner** (top, if active plan has `daily_kcal_target < 800`): yellow `st.warning` with "Day X / 84 (max 12 weeks per NHS)".
3. **Three summary cards** in `st.columns(3)`:
   - **Weigh-in** — today's weight, delta from 7 days ago via `st.metric`. If no entry today, card shows `[ + Log weight ]` instead.
   - **Calories** — `consumed / target`, `st.progress` bar, "net kcal" (intake − exercise_burn) below. Green / amber / red text based on under / within 10% / over target.
   - **Exercise** — today's minutes + weekly cumulative (vigorous counted 2×) against the 150-min weekly target.
4. **Add food** — `st.form` with `st.tabs(["Manual", "Barcode"])`:
   - **Manual tab**: name, portion (g, optional), kcal, protein, carbs, fat, fibre, sugar — all absolute values. Fast path; portion-based compute is not offered here.
   - **Barcode tab**: text input "Scan or type barcode" + `[ Look up ]` button.
5. **Add exercise** — `st.form` with activity dropdown, intensity radio, duration. Estimated `kcal_burned` is shown live (recomputed as the user fills the form) using `MET × weight_kg × hours` from `units.py`. Uses today's weight if available, else plan start weight.
6. **Today's log** — single combined timeline showing food + exercise rows sorted by `log_time` then `created_at`. `st.dataframe` with a delete column.

**Barcode lookup flow** (Open Food Facts):

```
Barcode  [ 5012345678900    ] [ Look up ]
─────────────────────────────────────────
✓ Found: Tesco Wholemeal Bread             [image if available]
Per 100 g:   238 kcal • P 12 • C 41 • F 2.5 • Fibre 6 • Sug 3
Per serving (44 g):  105 kcal • P 5.3 • C 18 • F 1.1 …

How much did you have?
  ○ Grams     [ 88 ] g
  ○ Servings  [ 2.0 ] × 44 g = 88 g

Preview (computed):
  209 kcal • P 10.5 • C 36.1 • F 2.2 • Fibre 5.3 • Sug 2.6

[ Save food entry ]
```

What's stored on save:
- `name` from OFF `product_name`.
- `portion_g` = the user's input normalised to grams.
- `kcal, protein_g, …` = **absolute values** computed for the consumed portion (`per_100g_value × grams / 100`). The Today / History tabs sum these columns directly — no portion knowledge needed at read time.
- `barcode` = the looked-up barcode.
- `source = "barcode"`.

**Edge cases**:
- No active plan → all three cards collapse to a single CTA "Create a plan first" linking to the Plan tab. Forms below hidden.
- Open Food Facts: product not found → friendly error, "Try manual entry" link pre-fills the barcode. Server 5xx → toast "Lookup failed — fall back to manual entry"; barcode preserved.
- Product found but missing `energy-kcal_100g` → show what's available; force user to fill missing fields manually before save.
- Product has no `serving_size` → hide the "Servings" radio.
- All saves trigger `st.rerun()` so cards refresh. Badge evaluation runs after every save (see §6.4).

### 6.2 History tab — `📈 History`

**Components**:

1. **Range picker** (`st.radio` horizontal): `30d / 90d / Plan-to-date / All / Custom`. Persisted in `st.session_state["history_range"]`. Custom shows two `st.date_input`s.
2. **Weight trend chart** (Plotly line):
   - Solid line: actual `weight_entries` (gaps on missing days, no interpolation).
   - Dashed line: linear plan target from `start_weight_kg → target_weight_kg` over `start_date..target_date`.
   - Hover annotations for `weight_entries.notes`.
   - Caption: "Actual Δ • Plan target Δ • on track / behind / ahead" using the shared ±0.3 kg tolerance band.
3. **Weekly stats table** — ISO weeks within range, computed client-side:
   - `avg kcal` = mean of daily kcal sums.
   - `avg deficit` = mean of `(intake − exercise_burn − maintenance_estimate)`. Maintenance via Mifflin-St Jeor using current weight + plan `sex`. Column hidden when `sex` is unset.
   - `exercise min` = sum of weekly `duration_min` with vigorous × 2.
   - `Δ weight` = last weigh-in of week − last weigh-in of previous week.
   - `goals` = three icons: weekly avg kcal ≤ target, exercise ≥ target, rate within 0.25–1.0 kg.
   - For VLCD plans, add a `days on VLCD` running 12-week countdown column.
4. **Detail table** (`st.radio` Food / Exercise + filters): `st.data_editor` for inline edits + delete column. Edits go through `update_food_entry` / `update_exercise_entry`.
5. **CSV export**: `st.download_button` for the filtered range, two buttons (food / exercise).

**Performance**:
- Single `load_recent_logs(user_id, since_date)` call returning three DataFrames.
- `@st.cache_data(ttl=60)` keyed on `(user_id, since_date, tab)`. Explicit `clear()` after any write.

### 6.3 Plan tab — `🎯 Plan`

Manages the active plan + history of past cycles + creating new ones.

**Active cycle card** (shown when an active plan exists):
- Reads the row from `weight_plans WHERE status = 'active'`.
- Computes current weight, % done, pace (`(start − current) / weeks_elapsed`), and on-track status (±0.3 kg band) client-side from `weight_entries`.
- Edit button opens inline form to adjust `daily_kcal_target`, `weekly_exercise_min_target`, `target_date`. **`start_weight` is frozen** after cycle start.
- "Abandon this cycle" link sets `status = 'abandoned'` so users can restart cleanly.

**Past cycles table**: dataframe of completed/abandoned plans with `#`, range, start→end weight, target, actual delta, status.

**Suggested next cycle card** (visible when `current_weight ≤ target_weight_kg + 1.0`):
- Shows the NHS-recommended next 3% target (`round(current_weight × 0.97, 1)`) and the projected end date at the current pace.
- Single `[ Complete current & start next ]` button atomically:
  1. Marks current plan `status = 'completed'`.
  2. Inserts new plan with `previous_plan_id = old.id`, `start_weight_kg = current_weight`, new `target_weight_kg`, weekly rate copied, kcal target copied (unless previous was VLCD — then reset to NHS standard with a note).
- Implemented as a single Supabase RPC function `complete_and_start_next_plan(...)` so both writes succeed or fail together. The RPC is defined in the same migration as the tables.
- Triggers badge evaluation for `cycle_completed` and `cycle_streak_3` after the RPC returns.

**Create-plan form** (shown when no active plan exists):
- Inputs: current weight, sex (M/F/prefer not), target (NHS 3% or custom), weekly rate (0.5/0.75/1.0/custom), daily kcal target (defaults: 1900 male, 1400 female, 1500 unset), weekly exercise min target (default 150).
- VLCD block: if `daily_kcal_target < 800`, shows red warning, requires `vlcd_acknowledged` checkbox, refuses `target_date > start_date + 84 days`.
- Validations applied both client-side and in the DB handler:
  - `target_weight_kg < current_weight`.
  - `weekly_rate_kg ∈ [0.25, 1.0]` (warn but allow outside).
  - `target_weight_kg < current_weight × 0.97` → gentle warning "NHS recommends 3% per cycle (suggested X.X kg) — bigger goals are harder to sustain. Continue?" (allow).

**Cycle numbering**: derived at read time from the chain of `previous_plan_id` links. Not stored.

### 6.4 Rewards tab — `🏆 Rewards`

**Layout**:
- Header: `Total points: N` + `Current streak: D days 🔥`.
- **Earned** grid: tiles for each row in `earned_badges`, sorted newest first.
- **Locked** grid: tiles for every entry in the catalog the user hasn't earned, with hover tooltip showing the `rule` text.

**Badge catalog** (`src/utils/badges.py`):

```python
BADGES = {
  # Onboarding
  "first_log":           {"name": "First log",          "emoji": "📔", "points": 10},
  "first_weigh_in":      {"name": "First weigh-in",     "emoji": "⚖️", "points": 10},
  "first_plan":          {"name": "First plan",         "emoji": "🌱", "points": 30},

  # Kcal streaks
  "kcal_streak_7":       {"name": "7-day kcal streak",  "emoji": "🥇", "points": 50},
  "kcal_streak_14":      {"name": "14-day kcal streak", "emoji": "🥈", "points": 100},
  "kcal_streak_30":      {"name": "30-day kcal streak", "emoji": "🥉", "points": 250},

  # Exercise
  "first_workout":       {"name": "First workout logged", "emoji": "🏃", "points": 20},
  "exercise_week_150":   {"name": "NHS 150 min week",     "emoji": "🎯", "points": 50},
  "exercise_week_300":   {"name": "Double NHS week",      "emoji": "💪", "points": 100},
  "vigorous_week_75":    {"name": "75 min vigorous week", "emoji": "⚡", "points": 75},

  # Weight milestones (per active plan; locked again on new cycle)
  "lost_1kg":            {"name": "Lost 1 kg",            "emoji": "📉", "points": 100},
  "lost_3kg":            {"name": "Lost 3 kg",            "emoji": "📉", "points": 200},
  "lost_5kg":            {"name": "Lost 5 kg",            "emoji": "📉", "points": 350},
  "lost_5pct_body":      {"name": "5% body weight lost",  "emoji": "🏆", "points": 500},

  # Macro / quality (per ISO week, one win per week)
  "macro_balanced_week": {"name": "Balanced macros",      "emoji": "🥗", "points": 30,
                          "rule": "≥5 days with protein ≥0.8 g/kg body weight"},

  # Plan progress
  "cycle_completed":     {"name": "Cycle completed",      "emoji": "🥳", "points": 200},
  "cycle_streak_3":      {"name": "3 cycles in a row",    "emoji": "🔥", "points": 500},
}
```

**Award logic** — one pure function:

```python
def evaluate(user_id, *, food_df, exercise_df, weight_df, plan_df, already_earned) -> list[NewBadge]
```

- Pure — no DB access, no side effects. Returns `(badge_key, earned_on, metadata)` tuples to insert.
- Called from the Today tab after every save (food, exercise, weight) **and** from the Plan tab after `complete_and_start_next_plan` returns (so `cycle_completed` / `cycle_streak_3` fire). Newly earned badges trigger `st.toast("🥇 7-day kcal streak — +50 pts!")` and are inserted via `record_earned_badges`.
- `earned_on` = the date of the qualifying log (not `NOW()`). Backfills date correctly.
- "Already earned" is loaded once per page render so a single save can't double-fire.

**Plan-scoped milestone badges**: `lost_1kg`, `lost_3kg`, `lost_5kg`, `lost_5pct_body` are scoped to the **active plan** — the rule checks weight delta against the active plan's `start_weight_kg`, and `metadata` stores `{"plan_id": "..."}`. The Rewards tab considers a tile "locked again" for a new cycle if there's no row in `earned_badges` whose `metadata->>'plan_id'` matches the current plan id. The `UNIQUE(user_id, badge_key, earned_on)` constraint still allows the same badge to be earned again on a later date (different cycle).

**Points & streak**:
- `Total points` = `SUM(earned_badges.points)` per user.
- `Current streak` is derived live from `food_entries`: consecutive days (working backwards from `today_local()`) with `kcal sum ≤ daily_kcal_target` **and** ≥ 1 food entry. A day with zero entries breaks the streak (no entry = no commitment that day). The current day counts as "in progress" — it contributes to the streak only if today's logged kcal already exceeds zero **and** is under target; otherwise the streak is reported as ending yesterday. Not stored, so backfilling fixes drift automatically.

## 7. Cross-cutting concerns

### 7.1 Units and locale

- Weight: kg, 1 decimal in UI, 2 decimals in DB.
- Energy: kcal.
- Portions: grams. Exercise duration: minutes.
- Fixed app timezone `APP_TZ = "Europe/London"` in `src/utils/units.py`.
- `today_local()` returns `datetime.now(ZoneInfo(APP_TZ)).date()` — used by every "today" / "this week" / "current streak" computation.
- All log tables use `DATE` columns (not timestamps for day boundaries) so DST switches don't fragment a day.

### 7.2 Validation

Every DB-handler write validates server-side (not only in the form):
- `weight_kg ∈ (20, 400)`.
- `duration_min ∈ (0, 1440)`.
- `kcal ∈ (0, 20000)`.
- `daily_kcal_target ∈ (400, 5000)`. VLCD checkbox + 12-week cap as in §6.3.

Failures raise a typed `WeightLossValidationError` that the page catches and surfaces via `st.error`.

### 7.3 Auth & multi-user

- `user_id = st.user.email` (matches the existing pages' pattern).
- Every DB method takes `user_id` explicitly and `WHERE user_id = $1`'s every query.
- No RLS in scope — handlers enforce scoping. (Adding RLS is a separate, additive change to all migrations and is not part of v1.)

### 7.4 Error & empty states

- No active plan → Today / History / Rewards tabs render an empty state with a CTA to the Plan tab.
- No logs in range → empty placeholders, helpful copy.
- Open Food Facts unreachable → toast "Lookup failed — fall back to manual entry"; barcode preserved in the input.
- DB write fails → `st.error` with validation message; form values preserved.

### 7.5 Performance

- One query per tab render via `load_recent_logs(user_id, since_date) -> (food_df, exercise_df, weight_df)`.
- `@st.cache_data(ttl=60)` keyed on `(user_id, since_date, tab)`; explicit `cache_data.clear()` after writes.
- Open Food Facts results cached in `st.session_state["off_cache"][barcode]`.

## 8. Testing approach

Tests live next to the modules they cover:

```
tests/test_units.py            # MET kcal-burn math, today_local(), ±0.3 kg band, vigorous×2
tests/test_badges.py           # evaluate() — at least 1 positive + 1 boundary-fail per badge
tests/test_food_lookup.py      # OFF response parsing (fixture JSON), compute_portion()
tests/test_weight_loss_db.py   # write/read round trips via SQLiteHandler-compatible shim
```

**Test priorities**:

1. `badges.evaluate()` — pure, highest leverage.
2. `food_lookup.compute_portion()` — pure arithmetic.
3. Plan invariant: "at most one active plan per user" via the partial unique index (integration test inserting two and asserting the constraint fires).
4. VLCD enforcement on submit (`kcal < 800` requires ack; > 84 days rejected).
5. Time/date helpers and ISO-week boundaries.

UI tests are out of scope — Streamlit testing is poor and the page is a thin shell over the testable utilities.

## 9. Risks & open items

- **Open Food Facts UK coverage** is ~70% of major retailers. Manual entry is the documented fallback. v1 does not add a second API.
- **MET kcal-burn estimates** are ±20% typical. Numbers shown on exercise cards are labelled "est.".
- **±0.3 kg "on track" band** is a heuristic; day-to-day weight noise can exceed it. The chart's trend visualisation is the antidote.
- **No food-search** in v1. Barcode or manual only.
- **Plan auto-adjust**: if the user logs much faster/slower than planned, the app shows the discrepancy (e.g. "pace 1.4 kg/wk — above NHS max of 1.0") but does not auto-adjust the plan. Edit is manual.
- **Sequential cycle button** is single-click (auto-creates the next 3% cycle copying targets) per user choice in brainstorm. Users who want to review can always edit immediately after.

## 10. Decisions made during brainstorm

For traceability — these are the decisions captured from the brainstorm session that drive this design.

| Decision | Choice |
|---|---|
| Tab structure | Layout B — Today-first dashboard (Today / History / Plan / Rewards) |
| Barcode flow | Lookup → user enters portion (g or servings) → app computes absolute nutrition → save |
| Manual food entry | Straight absolute-value entry (fast path, no per-100g compute) |
| Nutrition detail | kcal + protein + carbs + fat + fibre + sugar |
| Plan structure | Sequential 3% cycles with auto-suggested next target + cycle history |
| Exercise detail | Minutes + intensity + activity type + estimated kcal burned |
| Reminders | None in v1 — no email, no in-app banners |
| Badge catalog | Code-only (`badges.py` dict). System-defined badges, no user-customisable catalog in v1 |
| Cycle completion | Single-button auto-creates next cycle |
| Live camera barcode scan | Excluded from v1 |
| Forest-style rewards | Excluded from v1 |
