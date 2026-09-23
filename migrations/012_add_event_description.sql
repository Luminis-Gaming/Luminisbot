-- Migration 012: Add optional description to raid events
-- Shown below the title in the event embed (e.g. which bosses to kill)
-- Length is capped in the bot (MAX_EVENT_DESCRIPTION_LENGTH in raid_system.py)

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'raid_events' AND column_name = 'description'
    ) THEN
        ALTER TABLE raid_events ADD COLUMN description TEXT;
    END IF;
END $$;
