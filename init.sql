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

-- Display setup completion message
DO $$
BEGIN
    RAISE NOTICE 'LuminisBot database initialization completed successfully!';
END $$;
