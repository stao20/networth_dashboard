-- Account value sync: provider connections, mappings, sync audit

CREATE TABLE IF NOT EXISTS provider_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('open_banking', 'trading212')),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'needs_reauth', 'error', 'disabled')),
    display_name TEXT,
    credentials_encrypted TEXT NOT NULL,
    external_connection_id TEXT NOT NULL,
    last_synced_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    UNIQUE (user_id, provider, external_connection_id)
);

CREATE TABLE IF NOT EXISTS account_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_connection_id UUID NOT NULL REFERENCES provider_connections(id) ON DELETE CASCADE,
    external_account_id TEXT NOT NULL,
    external_account_name TEXT NOT NULL,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    UNIQUE (provider_connection_id, external_account_id),
    UNIQUE (account_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
    as_of_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'success', 'partial', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW()),
    finished_at TIMESTAMPTZ,
    written_count INT NOT NULL DEFAULT 0,
    skipped_count INT NOT NULL DEFAULT 0,
    error_count INT NOT NULL DEFAULT 0,
    notes TEXT,
    undone_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE TABLE IF NOT EXISTS sync_run_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sync_run_id UUID NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    external_account_id TEXT,
    outcome TEXT NOT NULL CHECK (outcome IN ('written', 'skipped', 'error')),
    reason TEXT,
    external_amount DECIMAL(15, 2),
    external_currency TEXT,
    previous_value_gbp DECIMAL(15, 2),
    new_value_gbp DECIMAL(15, 2),
    had_previous BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT TIMEZONE('utc', NOW())
);

CREATE INDEX IF NOT EXISTS idx_provider_connections_user_id ON provider_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_account_mappings_user_id ON account_mappings(user_id);
CREATE INDEX IF NOT EXISTS idx_account_mappings_connection ON account_mappings(provider_connection_id);
CREATE INDEX IF NOT EXISTS idx_sync_runs_user_id ON sync_runs(user_id);
CREATE INDEX IF NOT EXISTS idx_sync_runs_as_of_date ON sync_runs(as_of_date);
CREATE INDEX IF NOT EXISTS idx_sync_run_items_run_id ON sync_run_items(sync_run_id);
