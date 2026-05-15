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
    )
    -- start_date pinned to Europe/London (matches src/utils/units.py APP_TZ;
    -- avoids the UTC-vs-BST off-by-one on cycle-completion taps near midnight).
    VALUES (
        p_user_id, p_current_weight_kg, p_new_target_weight_kg, old_rate,
        new_kcal, old_exercise_target,
        (NOW() AT TIME ZONE 'Europe/London')::DATE, p_new_target_date, old_sex, p_old_plan_id, 'active'
    )
    RETURNING id INTO new_id;

    RETURN new_id;
END;
$$;
