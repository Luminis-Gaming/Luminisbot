-- Migration: Add API keys table for WoW addon authentication
-- Created: 2025-11-08

-- API keys table for authenticating WoW addon requests
CREATE TABLE IF NOT EXISTS api_keys (
    id SERIAL PRIMARY KEY,
    guild_id VARCHAR(100) NOT NULL,
    key_hash VARCHAR(255) NOT NULL UNIQUE,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,
    request_count INTEGER DEFAULT 0,
    notes TEXT
);

-- Index for fast key lookup
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash) WHERE is_active = true;

-- Index for guild lookups
CREATE INDEX IF NOT EXISTS idx_api_keys_guild_id ON api_keys(guild_id);

-- Comments
COMMENT ON TABLE api_keys IS 'API keys for authenticating WoW addon requests to fetch raid events';
COMMENT ON COLUMN api_keys.key_hash IS 'The actual API key (stored as plain text for validation - consider hashing in production)';
COMMENT ON COLUMN api_keys.is_active IS 'Whether this key is currently active and can be used';
COMMENT ON COLUMN api_keys.request_count IS 'Total number of API requests made with this key';
COMMENT ON COLUMN api_keys.notes IS 'Optional notes about this key (e.g., who requested it, purpose)';
