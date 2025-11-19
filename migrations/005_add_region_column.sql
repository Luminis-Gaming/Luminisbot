-- Migration: Add region column to wow_characters table
-- Date: 2025-11-19
-- Description: Support multi-region Battle.net accounts

-- Add region column with default 'eu' for existing records
ALTER TABLE wow_characters
ADD COLUMN IF NOT EXISTS region VARCHAR(5) DEFAULT 'eu';

-- Create index for region queries
CREATE INDEX IF NOT EXISTS idx_wow_characters_region ON wow_characters(region);

-- Update any NULL regions to 'eu' (for safety)
UPDATE wow_characters SET region = 'eu' WHERE region IS NULL;
