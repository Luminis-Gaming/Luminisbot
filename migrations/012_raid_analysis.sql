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

-- Wowhead tooltip text for the timeline tooltips (raidanalysis/spells.py),
-- looked up once per spell after a sync.
CREATE TABLE IF NOT EXISTS raid_spells (
    spell_id BIGINT PRIMARY KEY,
    name TEXT,
    icon TEXT,                                   -- Wowhead icon name (wow.zamimg.com)
    meta TEXT,                                   -- 'Instant · 1 min cooldown'
    description TEXT,                            -- plain text, scaled numbers shown as X
    status TEXT NOT NULL,                        -- 'ok', 'not_found' or 'error' (retried after an hour)
    parser INTEGER NOT NULL DEFAULT 1,           -- spells.PARSER when looked up; older rows are looked up again
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Top parses per boss / difficulty / spec for the cooldown comparison
-- (raidanalysis/benchmarks.py), refreshed weekly for the specs we play.
CREATE TABLE IF NOT EXISTS raid_benchmarks (
    encounter_id INTEGER NOT NULL,
    difficulty INTEGER NOT NULL,
    class TEXT NOT NULL,                         -- WCL slug, e.g. 'DemonHunter'
    spec TEXT NOT NULL,                          -- WCL slug, e.g. 'Havoc'
    metric TEXT,                                 -- 'dps' or 'hps'
    players JSONB NOT NULL DEFAULT '[]',         -- [{rank, name, amount, code, fight_id, duration, phases, casts: [[t, id]]}]
    status TEXT NOT NULL,                        -- 'ok', 'empty' or 'error' (retried after a day)
    error TEXT,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (encounter_id, difficulty, class, spec)
);

-- Officers' calls on a spec's abilities for the top-player comparison (benchmarks.ability_kind):
-- 'major' (timed), 'rotational' (pressed on cooldown, judged on casts / min) or 'hide'.
CREATE TABLE IF NOT EXISTS raid_spec_abilities (
    class TEXT NOT NULL,                         -- WCL class name, e.g. 'DeathKnight'
    spec TEXT NOT NULL,                          -- WCL spec name, e.g. 'Blood'
    ability_name TEXT NOT NULL,
    kind TEXT NOT NULL,
    updated_by TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (class, spec, ability_name)
);

-- Buffs the game's Cooldown Manager tracks (raidanalysis/gamedata.py, from wago.tools, refreshed weekly):
-- the auras the Rotation tab judges for uptime and wasted procs.
CREATE TABLE IF NOT EXISTS raid_tracked_spells (
    spell_id BIGINT NOT NULL,
    kind TEXT NOT NULL,                          -- 'tracked'
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (spell_id, kind)
);

-- Talent tree entries (gamedata.py): the ability each gives, its tree, the ability it replaces
CREATE TABLE IF NOT EXISTS raid_talents (
    entry_id BIGINT PRIMARY KEY,                 -- TraitNodeEntry id, as in combatantinfo's talentTree
    tree_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    overrides TEXT,                              -- Rushing Wind Kick: 'Rising Sun Kick'
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- When a report first came in: the 10 latest raid nights are kept, imports for 7 days (db.prune_reports).
ALTER TABLE raid_reports ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();

-- Focus over time for one player in one pull (raidanalysis/focus.py): WCL's damage graphs by target,
-- fetched when someone opens the pull's Focus view, bucketed and scaled.
CREATE TABLE IF NOT EXISTS raid_focus (
    report_code TEXT NOT NULL REFERENCES raid_reports(code) ON DELETE CASCADE,
    fight_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    data JSONB NOT NULL,
    fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (report_code, fight_id, name)
);
