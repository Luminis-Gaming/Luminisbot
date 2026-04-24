-- Migration 010: Add posted_logs table for tracking all posted WCL reports
-- Replaces the single last_log_id approach with a history-based approach
-- to prevent re-posting when multiple people upload logs for the same raid.

CREATE TABLE IF NOT EXISTS posted_logs (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    log_code TEXT NOT NULL,
    posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(guild_id, log_code)
);

CREATE INDEX IF NOT EXISTS idx_posted_logs_guild ON posted_logs(guild_id);
CREATE INDEX IF NOT EXISTS idx_posted_logs_guild_code ON posted_logs(guild_id, log_code);

GRANT ALL PRIVILEGES ON TABLE posted_logs TO luminisbot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO luminisbot;

COMMENT ON TABLE posted_logs IS 'Tracks all WCL report codes that have been posted per guild to prevent duplicate posting';
