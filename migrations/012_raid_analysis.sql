-- Raid analysis (Wipefest-style pull breakdowns on the admin site).
-- Documentation copy: the live schema is created idempotently by
-- raidanalysis/db.py ensure_schema(), called from run_migrations.py on boot.

CREATE TABLE IF NOT EXISTS raid_reports (
    code TEXT PRIMARY KEY,                       -- WCL report code
    title TEXT NOT NULL,
    owner TEXT,
    zone_id INTEGER,
    zone_name TEXT,
    start_time BIGINT NOT NULL,                  -- epoch ms
    end_time BIGINT NOT NULL,                    -- epoch ms (moves while live logging)
    phase_names JSONB NOT NULL DEFAULT '{}',     -- {encounterID: {phaseID: {name, intermission}}}
    source TEXT NOT NULL DEFAULT 'guild',        -- 'guild' (auto) or 'manual' (imported by URL)
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- One row per raid boss pull; `analysis` is the tag-independent breakdown
-- built by raidanalysis/analyzer.py (deaths, damage taken per ability and
-- player, interrupts, dispels, potions, healthstones).
CREATE TABLE IF NOT EXISTS raid_pulls (
    report_code TEXT NOT NULL REFERENCES raid_reports(code) ON DELETE CASCADE,
    fight_id INTEGER NOT NULL,
    encounter_id INTEGER NOT NULL,
    encounter_name TEXT NOT NULL,
    difficulty INTEGER NOT NULL,                 -- 1 LFR, 3 Normal, 4 Heroic, 5 Mythic
    kill BOOLEAN NOT NULL DEFAULT FALSE,
    size INTEGER,
    start_ms BIGINT NOT NULL,                    -- relative to report start
    end_ms BIGINT NOT NULL,
    fight_pct REAL,                              -- % of the encounter remaining (0 on kill)
    boss_pct REAL,
    last_phase INTEGER,
    last_phase_intermission BOOLEAN DEFAULT FALSE,
    phases JSONB NOT NULL DEFAULT '[]',          -- [{id, start (ms into pull)}]
    analysis JSONB,
    analyzed_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (report_code, fight_id)
);
CREATE INDEX IF NOT EXISTS idx_raid_pulls_boss ON raid_pulls(encounter_id, difficulty);

-- Officer-maintained mechanic tags per boss: 'avoidable' (any hit is a
-- mistake) or 'ignore' (hide from tables). Applied at render time.
CREATE TABLE IF NOT EXISTS raid_ability_tags (
    encounter_id INTEGER NOT NULL,
    ability_id BIGINT NOT NULL,
    ability_name TEXT,
    tag TEXT NOT NULL,
    updated_by TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (encounter_id, ability_id)
);

-- Mechanic clips/tips scraped from each boss's Mythic Trap page (raidanalysis/guides.py).
-- One scan row per boss; re-scanned every few days or from the boss page.
CREATE TABLE IF NOT EXISTS raid_guide_scans (
    encounter_id INTEGER PRIMARY KEY,
    page_url TEXT,
    status TEXT NOT NULL,                        -- 'ok', 'not_found' or 'error'
    ability_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    scanned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Abilities from the boss page; matched to logged abilities at render time
-- by spell ID, then by name.
CREATE TABLE IF NOT EXISTS raid_guide_abilities (
    encounter_id INTEGER NOT NULL,
    guide_id TEXT NOT NULL,                      -- Mythic Trap's ability slug, e.g. 'ulatekSerBit'
    spell_id BIGINT,
    name TEXT NOT NULL,
    category TEXT,                               -- 'Help soak', 'Use defensives', ...
    subtitle TEXT,
    tip TEXT,
    description TEXT,
    video_url TEXT,                              -- NULL when Mythic Trap has no clip yet
    embed_url TEXT NOT NULL,                     -- shown in an iframe on the admin pages
    PRIMARY KEY (encounter_id, guide_id)
);
