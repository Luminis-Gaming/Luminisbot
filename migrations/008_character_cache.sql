-- Migration 008: Add character enrichment cache columns
-- Adds columns to store cached data from Blizzard API, Raider.IO, and Warcraft Logs

ALTER TABLE wow_characters 
ADD COLUMN IF NOT EXISTS mythic_plus_score DECIMAL(10,2),
ADD COLUMN IF NOT EXISTS mythic_plus_score_tank DECIMAL(10,2),
ADD COLUMN IF NOT EXISTS mythic_plus_score_healer DECIMAL(10,2),
ADD COLUMN IF NOT EXISTS mythic_plus_score_dps DECIMAL(10,2),
ADD COLUMN IF NOT EXISTS raid_progress_current TEXT,
ADD COLUMN IF NOT EXISTS achievement_points INTEGER,
ADD COLUMN IF NOT EXISTS active_spec TEXT,
ADD COLUMN IF NOT EXISTS covenant TEXT,
ADD COLUMN IF NOT EXISTS renown INTEGER,
ADD COLUMN IF NOT EXISTS raiderio_url TEXT,
ADD COLUMN IF NOT EXISTS warcraftlogs_url TEXT,
ADD COLUMN IF NOT EXISTS character_render_url TEXT,
ADD COLUMN IF NOT EXISTS last_enriched TIMESTAMP WITH TIME ZONE,
ADD COLUMN IF NOT EXISTS enrichment_cache JSONB;

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_wow_characters_mythic_score ON wow_characters(mythic_plus_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_wow_characters_last_enriched ON wow_characters(last_enriched);

-- Add comments
COMMENT ON COLUMN wow_characters.mythic_plus_score IS 'Overall Mythic+ rating from Raider.IO';
COMMENT ON COLUMN wow_characters.raid_progress_current IS 'JSON object with current raid progression';
COMMENT ON COLUMN wow_characters.enrichment_cache IS 'Full cached API responses for detailed character data';
COMMENT ON COLUMN wow_characters.last_enriched IS 'When character data was last fetched from external APIs';
