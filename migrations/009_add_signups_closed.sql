-- Migration 009: Add signup closing functionality to raid events
-- Adds signups_closed flag and optional signup_deadline

DO $$
BEGIN
    -- Add signups_closed boolean (default false = signups open)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'raid_events' AND column_name = 'signups_closed'
    ) THEN
        ALTER TABLE raid_events ADD COLUMN signups_closed BOOLEAN DEFAULT FALSE;
    END IF;

    -- Add optional signup_deadline (auto-close signups at this time)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'raid_events' AND column_name = 'signup_deadline'
    ) THEN
        ALTER TABLE raid_events ADD COLUMN signup_deadline TIMESTAMP WITH TIME ZONE;
    END IF;
END $$;
