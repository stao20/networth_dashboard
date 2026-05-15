-- Drop all RLS policies
-- Drop users table policies
DROP POLICY IF EXISTS "Users can view their own data" ON users;
DROP POLICY IF EXISTS "Users can insert their own data" ON users;
DROP POLICY IF EXISTS "Users can update their own data" ON users;
DROP POLICY IF EXISTS "Users can delete their own data" ON users;

-- Drop categories table policies
DROP POLICY IF EXISTS "Users can view their own categories" ON categories;
DROP POLICY IF EXISTS "Users can insert their own categories" ON categories;
DROP POLICY IF EXISTS "Users can update their own categories" ON categories;
DROP POLICY IF EXISTS "Users can delete their own categories" ON categories;

-- Drop accounts table policies
DROP POLICY IF EXISTS "Users can view their own accounts" ON accounts;
DROP POLICY IF EXISTS "Users can insert their own accounts" ON accounts;
DROP POLICY IF EXISTS "Users can update their own accounts" ON accounts;
DROP POLICY IF EXISTS "Users can delete their own accounts" ON accounts;

-- Drop account_values table policies
DROP POLICY IF EXISTS "Users can view their own account values" ON account_values;
DROP POLICY IF EXISTS "Users can insert their own account values" ON account_values;
DROP POLICY IF EXISTS "Users can update their own account values" ON account_values;
DROP POLICY IF EXISTS "Users can delete their own account values" ON account_values;

-- Drop indexes
DROP INDEX IF EXISTS idx_categories_user_id;
DROP INDEX IF EXISTS idx_accounts_user_id;
DROP INDEX IF EXISTS idx_accounts_category_id;
DROP INDEX IF EXISTS idx_account_values_account_id;
DROP INDEX IF EXISTS idx_account_values_date;

-- Weight loss tracker objects (added 2026-05-15)
DROP FUNCTION IF EXISTS complete_and_start_next_plan(TEXT, UUID, DECIMAL, DECIMAL, DATE);
DROP INDEX IF EXISTS idx_earned_badges_user;
DROP INDEX IF EXISTS idx_exercise_entries_user_date;
DROP INDEX IF EXISTS idx_food_entries_user_date;
DROP INDEX IF EXISTS idx_weight_entries_user_date;
DROP INDEX IF EXISTS idx_weight_plans_user;
DROP INDEX IF EXISTS idx_weight_plans_one_active;
DROP TABLE IF EXISTS earned_badges;
DROP TABLE IF EXISTS exercise_entries;
DROP TABLE IF EXISTS food_entries;
DROP TABLE IF EXISTS weight_entries;
DROP TABLE IF EXISTS weight_plans;

-- Drop tables (in correct order due to foreign key constraints)
DROP TABLE IF EXISTS account_values;
DROP TABLE IF EXISTS accounts;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS users;

-- Drop extensions (only if you're sure no other applications are using them)
-- Note: Be careful with dropping extensions as other applications might depend on them
-- DROP EXTENSION IF EXISTS "uuid-ossp";
-- DROP EXTENSION IF EXISTS "pgcrypto"; 