-- Migration 007: Add raid reminders table
-- This table stores user preferences for receiving reminders about raid events

CREATE TABLE IF NOT EXISTS raid_reminders (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES raid_events(id) ON DELETE CASCADE,
    discord_id TEXT NOT NULL,
    reminder_time TIMESTAMP WITH TIME ZONE NOT NULL,
    sent BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure each user can only have one reminder per event
    UNIQUE(event_id, discord_id)
);

-- Index for efficient querying of pending reminders
CREATE INDEX IF NOT EXISTS idx_raid_reminders_pending 
    ON raid_reminders(reminder_time, sent) 
    WHERE sent = FALSE;

-- Index for event_id lookups
CREATE INDEX IF NOT EXISTS idx_raid_reminders_event 
    ON raid_reminders(event_id);

-- Index for discord_id lookups
CREATE INDEX IF NOT EXISTS idx_raid_reminders_discord 
    ON raid_reminders(discord_id);

COMMENT ON TABLE raid_reminders IS 'Stores user preferences for receiving reminders about raid events';
COMMENT ON COLUMN raid_reminders.event_id IS 'Reference to the raid event';
COMMENT ON COLUMN raid_reminders.discord_id IS 'Discord user ID who wants to be reminded';
COMMENT ON COLUMN raid_reminders.reminder_time IS 'When to send the reminder (typically 1 hour before event)';
COMMENT ON COLUMN raid_reminders.sent IS 'Whether the reminder has been sent';
COMMENT ON COLUMN raid_reminders.sent_at IS 'When the reminder was actually sent';

GRANT ALL PRIVILEGES ON TABLE raid_reminders TO luminisbot;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO luminisbot;
