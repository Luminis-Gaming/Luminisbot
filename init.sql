-- init.sql
-- Database initialization script for LuminisBot

-- Create the database if it doesn't exist (this runs automatically via POSTGRES_DB)
-- The database 'luminisbot' will be created by the postgres Docker image

-- Connect to the luminisbot database
\c luminisbot;

-- Create the guild_channels table
CREATE TABLE IF NOT EXISTS guild_channels (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    last_log_id TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_guild_channels_channel_id ON guild_channels(channel_id);
CREATE INDEX IF NOT EXISTS idx_guild_channels_last_log_id ON guild_channels(last_log_id);

-- Insert a comment about the table
COMMENT ON TABLE guild_channels IS 'Stores Discord guild configurations for automatic Warcraft Logs posting';
COMMENT ON COLUMN guild_channels.guild_id IS 'Discord guild (server) ID';
COMMENT ON COLUMN guild_channels.channel_id IS 'Discord channel ID where logs should be posted';
COMMENT ON COLUMN guild_channels.last_log_id IS 'Last processed Warcraft Logs report code';

-- Grant permissions to the luminisbot user
GRANT ALL PRIVILEGES ON TABLE guild_channels TO luminisbot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO luminisbot;

-- ============================================================================
-- WoW Character Connection Tables
-- ============================================================================

-- Table to store OAuth state tokens for security
CREATE TABLE IF NOT EXISTS oauth_states (
    id SERIAL PRIMARY KEY,
    state_token TEXT UNIQUE NOT NULL,
    discord_id TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_token ON oauth_states(state_token);
CREATE INDEX IF NOT EXISTS idx_oauth_states_created ON oauth_states(created_at);

COMMENT ON TABLE oauth_states IS 'Temporary storage for OAuth state tokens during authorization flow';

-- Table to store Discord-to-Battle.net account connections
CREATE TABLE IF NOT EXISTS wow_connections (
    discord_id TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

COMMENT ON TABLE wow_connections IS 'Links Discord users to their Battle.net accounts via OAuth tokens';
COMMENT ON COLUMN wow_connections.discord_id IS 'Discord user ID (primary identifier)';
COMMENT ON COLUMN wow_connections.access_token IS 'Battle.net OAuth access token for API calls';

-- Table to store WoW character information
CREATE TABLE IF NOT EXISTS wow_characters (
    id SERIAL PRIMARY KEY,
    discord_id TEXT NOT NULL REFERENCES wow_connections(discord_id) ON DELETE CASCADE,
    character_name TEXT NOT NULL,
    realm_name TEXT NOT NULL,
    realm_slug TEXT NOT NULL,
    character_class TEXT,
    character_race TEXT,
    faction TEXT,
    level INTEGER,
    character_id BIGINT,
    item_level INTEGER,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(discord_id, character_name, realm_slug)
);

CREATE INDEX IF NOT EXISTS idx_wow_characters_discord ON wow_characters(discord_id);
CREATE INDEX IF NOT EXISTS idx_wow_characters_name ON wow_characters(character_name);
CREATE INDEX IF NOT EXISTS idx_wow_characters_realm ON wow_characters(realm_slug);

COMMENT ON TABLE wow_characters IS 'Stores World of Warcraft character data for connected Discord users';
COMMENT ON COLUMN wow_characters.character_id IS 'Blizzard character ID from API';
COMMENT ON COLUMN wow_characters.item_level IS 'Character average item level (ilvl)';

-- Grant permissions for WoW tables
GRANT ALL PRIVILEGES ON TABLE oauth_states TO luminisbot;
GRANT ALL PRIVILEGES ON TABLE wow_connections TO luminisbot;
GRANT ALL PRIVILEGES ON TABLE wow_characters TO luminisbot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO luminisbot;

-- Display setup completion message
DO $$
BEGIN
    RAISE NOTICE 'LuminisBot database initialization completed successfully!';
    RAISE NOTICE 'WoW character connection tables created.';
END $$;
