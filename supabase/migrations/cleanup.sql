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

-- Drop tables (in correct order due to foreign key constraints)
DROP TABLE IF EXISTS account_values;
DROP TABLE IF EXISTS accounts;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS users;

-- Drop extensions (only if you're sure no other applications are using them)
-- Note: Be careful with dropping extensions as other applications might depend on them
-- DROP EXTENSION IF EXISTS "uuid-ossp";
-- DROP EXTENSION IF EXISTS "pgcrypto"; 