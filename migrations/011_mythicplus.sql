-- Migration 011: Mythic+ event system (armor-stacking groups)
-- DOCUMENTATION COPY — the effective schema is created idempotently by
-- mythicplus/db.py ensure_schema(), called from run_migrations.py on boot.
-- See MYTHICPLUS_PLAN.md for the full design.

CREATE TABLE IF NOT EXISTS mplus_events (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    message_id BIGINT UNIQUE,
    title TEXT NOT NULL,
    event_type TEXT NOT NULL DEFAULT 'armor_stacking',
    event_date DATE NOT NULL,
    event_time TIME NOT NULL,
    key_level_min INTEGER NOT NULL,
    key_level_max INTEGER NOT NULL,
    signup_deadline TIMESTAMP WITH TIME ZONE,
    status TEXT NOT NULL DEFAULT 'open',  -- open | finalized | completed | cancelled
    created_by BIGINT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mplus_events_status ON mplus_events(status, signup_deadline);

-- One row per (character, role) offering; a player may have many rows
CREATE TABLE IF NOT EXISTS mplus_signups (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES mplus_events(id) ON DELETE CASCADE,
    discord_id TEXT NOT NULL,
    character_name TEXT NOT NULL,
    realm_slug TEXT NOT NULL,
    character_class TEXT NOT NULL,
    role TEXT NOT NULL,        -- tank | healer | dps
    armor_type TEXT NOT NULL,  -- cloth | leather | mail | plate (denormalized from class)
    signed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(event_id, discord_id, character_name, realm_slug, role)
);
CREATE INDEX IF NOT EXISTS idx_mplus_signups_event ON mplus_signups(event_id);

CREATE TABLE IF NOT EXISTS mplus_groups (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES mplus_events(id) ON DELETE CASCADE,
    group_number INTEGER NOT NULL,
    armor_type TEXT,           -- the group's modal armor type
    UNIQUE(event_id, group_number)
);

CREATE TABLE IF NOT EXISTS mplus_group_members (
    group_id INTEGER NOT NULL REFERENCES mplus_groups(id) ON DELETE CASCADE,
    signup_id INTEGER NOT NULL REFERENCES mplus_signups(id) ON DELETE CASCADE,
    assigned_role TEXT NOT NULL,
    PRIMARY KEY (group_id, signup_id)
);

CREATE TABLE IF NOT EXISTS mplus_alternates (
    event_id INTEGER NOT NULL REFERENCES mplus_events(id) ON DELETE CASCADE,
    discord_id TEXT NOT NULL,
    rank INTEGER NOT NULL,     -- internal promotion order (grace desc, signup asc)
    reason TEXT NOT NULL,      -- 'unlucky' (grace awarded) | 'composition'
    PRIMARY KEY (event_id, discord_id)
);

CREATE TABLE IF NOT EXISTS mplus_grace_points (
    guild_id BIGINT NOT NULL,
    discord_id TEXT NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (guild_id, discord_id)
);

-- Audit trail: every grace award and reset, for dispute resolution
CREATE TABLE IF NOT EXISTS mplus_grace_log (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    discord_id TEXT NOT NULL,
    event_id INTEGER,
    delta INTEGER NOT NULL,
    reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

GRANT ALL PRIVILEGES ON TABLE mplus_events, mplus_signups, mplus_groups,
    mplus_group_members, mplus_alternates, mplus_grace_points,
    mplus_grace_log TO luminisbot;
