"""
Raid analysis database layer: schema + SQL helpers.

Schema is created idempotently by ensure_schema(), called from
run_migrations.py on every boot (migrations/012 is the documentation copy).
"""
import contextvars
import logging
import os
import re
import threading
import time

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from psycopg2.pool import PoolError, ThreadedConnectionPool

from mythicplus.db import get_db_connection

from . import teams
from .analyzer import TAG_AVOIDABLE, TAG_AVOIDABLE_NON_TANK, TAG_DEATH_ONLY, TAG_IGNORE

logger = logging.getLogger(__name__)

TAGS = (TAG_AVOIDABLE, TAG_AVOIDABLE_NON_TANK, TAG_DEATH_ONLY, TAG_IGNORE)


def _use_fast_json():
    """
    Reading JSON out of the database with orjson - about twice as fast as the standard library, the same results;
    turning a night's analyses into Python is most of what its pages cost. Anything orjson won't read (an integer
    past 64 bits) goes to the standard one.
    """
    import json
    try:
        import orjson
    except ImportError:
        return

    def loads(text):
        try:
            return orjson.loads(text)
        except orjson.JSONDecodeError:
            return json.loads(text)
    from psycopg2.extras import register_default_json, register_default_jsonb
    register_default_json(loads=loads, globally=True)
    register_default_jsonb(loads=loads, globally=True)


_use_fast_json()


def ensure_schema(cursor):
    """Create raid analysis tables. Runs inside run_migrations()'s transaction."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_reports (
            code TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            owner TEXT,
            zone_id INTEGER,
            zone_name TEXT,
            start_time BIGINT NOT NULL,
            end_time BIGINT NOT NULL,
            phase_names JSONB NOT NULL DEFAULT '{}',
            source TEXT NOT NULL DEFAULT 'guild',
            synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_pulls (
            report_code TEXT NOT NULL REFERENCES raid_reports(code) ON DELETE CASCADE,
            fight_id INTEGER NOT NULL,
            encounter_id INTEGER NOT NULL,
            encounter_name TEXT NOT NULL,
            difficulty INTEGER NOT NULL,
            kill BOOLEAN NOT NULL DEFAULT FALSE,
            size INTEGER,
            start_ms BIGINT NOT NULL,
            end_ms BIGINT NOT NULL,
            fight_pct REAL,
            boss_pct REAL,
            last_phase INTEGER,
            last_phase_intermission BOOLEAN DEFAULT FALSE,
            phases JSONB NOT NULL DEFAULT '[]',
            analysis JSONB,
            analyzed_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (report_code, fight_id)
        );
    """)
    # When a report first came in: imported logs are kept for a week (prune_reports)
    cursor.execute("ALTER TABLE raid_reports ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_raid_pulls_boss
        ON raid_pulls(encounter_id, difficulty);
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_ability_tags (
            encounter_id INTEGER NOT NULL,
            ability_id BIGINT NOT NULL,
            ability_name TEXT,
            tag TEXT NOT NULL,
            updated_by TEXT,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (encounter_id, ability_id)
        );
    """)
    ensure_guide_schema(cursor)


def ensure_guide_schema(cursor):
    """Mythic Trap guide cache (see raidanalysis/guides.py)."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_guide_scans (
            encounter_id INTEGER PRIMARY KEY,
            page_url TEXT,
            status TEXT NOT NULL,
            ability_count INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            scanned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_guide_abilities (
            encounter_id INTEGER NOT NULL,
            guide_id TEXT NOT NULL,
            spell_id BIGINT,
            name TEXT NOT NULL,
            category TEXT,
            subtitle TEXT,
            tip TEXT,
            description TEXT,
            video_url TEXT,
            embed_url TEXT NOT NULL,
            PRIMARY KEY (encounter_id, guide_id)
        );
    """)
    # Top parses per (boss, difficulty, spec, hero tree) for the cooldown comparison (benchmarks.py). hero '': the
    # whole spec's top players (pulls whose talents don't say, and every benchmark from before hero trees)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_benchmarks (
            encounter_id INTEGER NOT NULL,
            difficulty INTEGER NOT NULL,
            class TEXT NOT NULL,
            spec TEXT NOT NULL,
            hero TEXT NOT NULL DEFAULT '',
            metric TEXT,
            players JSONB NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            error TEXT,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (encounter_id, difficulty, class, spec, hero)
        );
    """)
    cursor.execute("ALTER TABLE raid_benchmarks ADD COLUMN IF NOT EXISTS hero TEXT NOT NULL DEFAULT ''")
    cursor.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_index i
                           JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                           WHERE i.indrelid = 'raid_benchmarks'::regclass AND i.indisprimary AND a.attname = 'hero') THEN
                ALTER TABLE raid_benchmarks DROP CONSTRAINT IF EXISTS raid_benchmarks_pkey;
                ALTER TABLE raid_benchmarks ADD PRIMARY KEY (encounter_id, difficulty, class, spec, hero);
            END IF;
        END $$
    """)
    # Wowhead tooltip text for the timeline (spells.py)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_spells (
            spell_id BIGINT PRIMARY KEY,
            name TEXT,
            icon TEXT,
            meta TEXT,
            description TEXT,
            status TEXT NOT NULL,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    cursor.execute("ALTER TABLE raid_spells ADD COLUMN IF NOT EXISTS parser INTEGER NOT NULL DEFAULT 1")
    # Focus over time for one player in one pull (focus.py), fetched when someone opens it
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_focus (
            report_code TEXT NOT NULL REFERENCES raid_reports(code) ON DELETE CASCADE,
            fight_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            data JSONB NOT NULL,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (report_code, fight_id, name)
        );
    """)
    # Each player's realm per log (WCL's actor list): two characters of one name on different realms are two
    # people - character pages go by realm and name
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_realms (
            report_code TEXT NOT NULL REFERENCES raid_reports(code) ON DELETE CASCADE,
            name TEXT NOT NULL,
            realm TEXT NOT NULL,
            PRIMARY KEY (report_code, name)
        );
    """)
    # Each raid tier's bosses in raid order (WCL's zone, as its encounter journal lists them): the coach weighs
    # later bosses over earlier ones (coach.boss_weights) - encounter ids don't follow the raid's order
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_zones (
            zone_id INTEGER PRIMARY KEY,
            encounters JSONB NOT NULL,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    # Characters for the player page's Character tab (armory.py): Blizzard + Raider.IO, by name and realm
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_armory (
            name_key TEXT NOT NULL,
            realm TEXT NOT NULL,
            data JSONB NOT NULL,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (name_key, realm)
        );
    """)
    # Enemies' portraits for the timelines (npcs.py): Blizzard's creature render, by name (NULL: none found)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_npcs (
            name TEXT PRIMARY KEY,
            game_id BIGINT,
            icon TEXT,
            status TEXT NOT NULL,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    cursor.execute("ALTER TABLE raid_npcs ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1")
    # Spells the game's Cooldown Manager tracks as buffs (gamedata.py), from wago.tools
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_tracked_spells (
            spell_id BIGINT NOT NULL,
            kind TEXT NOT NULL,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (spell_id, kind)
        );
    """)
    # Every talent tree's entries (gamedata.py), from wago.tools: which ability each talent entry gives, in
    # which tree, and which ability it replaces (Rushing Wind Kick -> Rising Sun Kick)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_talents (
            entry_id BIGINT PRIMARY KEY,
            tree_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            overrides TEXT,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    # ...and the choice node it's an option of (Revival / Restoral: one row in the cooldown comparison)
    cursor.execute("ALTER TABLE raid_talents ADD COLUMN IF NOT EXISTS choice BIGINT")
    # Which hero tree each talent entry belongs to (gamedata.hero_rows): the choice node's entries and the tree's talents
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_hero_trees (
            entry_id BIGINT PRIMARY KEY,
            name TEXT NOT NULL,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    # Each pull's player list on its own (a trigger keeps it equal to analysis->'players'): who was in which pull is
    # asked a lot (the Players tab, character pages, benchmarks), and reading it out of the analysis means
    # unpacking every pull's whole analysis - every cast, aura and hit - for a list of names.
    # ...and when its analysis last changed (re-analyzed, detail fetched later): data_version() - the page caches
    # keep a page until the data under it changes.
    # ...and everyone's talents (analysis->'talents'): which hero trees we play, for the benchmarks to fetch.
    cursor.execute("ALTER TABLE raid_pulls ADD COLUMN IF NOT EXISTS players JSONB")
    cursor.execute("ALTER TABLE raid_pulls ADD COLUMN IF NOT EXISTS changed_at TIMESTAMP WITH TIME ZONE")
    cursor.execute("ALTER TABLE raid_pulls ADD COLUMN IF NOT EXISTS talents JSONB")
    cursor.execute("""
        CREATE OR REPLACE FUNCTION raid_pulls_players() RETURNS trigger AS $$
        BEGIN
            NEW.players := COALESCE(NEW.analysis->'players', '[]'::jsonb);
            NEW.talents := COALESCE(NEW.analysis->'talents', '{}'::jsonb);
            NEW.changed_at := NOW();
            RETURN NEW;
        END $$ LANGUAGE plpgsql
    """)
    cursor.execute("DROP TRIGGER IF EXISTS raid_pulls_players ON raid_pulls")
    cursor.execute("""
        CREATE TRIGGER raid_pulls_players BEFORE INSERT OR UPDATE OF analysis ON raid_pulls
        FOR EACH ROW EXECUTE FUNCTION raid_pulls_players()
    """)
    cursor.execute("UPDATE raid_pulls SET players = COALESCE(analysis->'players', '[]'::jsonb) WHERE players IS NULL")
    cursor.execute("UPDATE raid_pulls SET talents = COALESCE(analysis->'talents', '{}'::jsonb) WHERE talents IS NULL")
    cursor.execute("CREATE INDEX IF NOT EXISTS raid_pulls_players_gin ON raid_pulls USING gin (players jsonb_path_ops)")
    # A stored character's picture links as columns of their own (Postgres fills them in from the stored JSON on
    # every write): the Players tab needs four short links per character, not every character's whole armory.
    for table, column in (('raid_armory', 'data'), ('wow_characters', 'enrichment_cache')):
        for name, path in (('pic_render', "->>'character_render_url'"), ('pic_avatar', "->>'avatar_url'"),
                           ('pic_thumb', "->>'thumbnail_url'"), ('pic_rio_thumb', "->'raiderio'->>'thumbnail_url'")):
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} TEXT "
                           f"GENERATED ALWAYS AS ({column}{path}) STORED")
    # Officers' calls on a spec's abilities: a major cooldown (timed), rotational (pressed on cooldown)
    # or hidden - overriding benchmarks.ability_kind(). Class / spec as WCL names them ('DeathKnight').
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_spec_abilities (
            class TEXT NOT NULL,
            spec TEXT NOT NULL,
            ability_name TEXT NOT NULL,
            kind TEXT NOT NULL,
            updated_by TEXT,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (class, spec, ability_name)
        );
    """)
    # Who uses the raid pages (analytics.py): page views (an anonymous browser id - never an IP) and "My performance"
    # clicks in Discord. src: how a view came in - 'full' (a Full analysis link), 'mine' (the recap's own link).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_analytics (
            id BIGSERIAL PRIMARY KEY,
            at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            kind TEXT NOT NULL,
            src TEXT,
            visitor TEXT,
            discord_id BIGINT,
            discord_name TEXT,
            admin_user TEXT,
            report_code TEXT,
            path TEXT
        );
        CREATE INDEX IF NOT EXISTS raid_analytics_at ON raid_analytics (at);
        CREATE INDEX IF NOT EXISTS raid_analytics_report ON raid_analytics (report_code);
    """)
    # A browser's id -> the Discord user it belongs to: learned when someone opens a link from their own private
    # "My performance" recap (signed with their Discord id), so their other views count as theirs too.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_visitors (
            visitor TEXT PRIMARY KEY,
            discord_id BIGINT NOT NULL,
            linked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)


# Connections are kept and reused (a pool): opening one - connecting and logging in - for every query added up to
# a lot on pages that make dozens. Thread-safe (the Discord recap queries from a worker thread). A pool that's all
# in use, or a kept connection that went stale (the database restarted), falls back to a fresh one.
POOL_MAX = 10
_pool = None
_pool_lock = threading.Lock()

# The queries of the page being built (web/routes.py's _timed): set per request, so slow pages are logged with
# where the time went. None outside a request.
QUERY_LOG = contextvars.ContextVar('raid_query_log', default=None)


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(1, POOL_MAX, host=os.getenv('DB_HOST', 'postgres'),
                                               port=os.getenv('DB_PORT', '5432'),
                                               database=os.getenv('DB_NAME', 'luminisbot'),
                                               user=os.getenv('DB_USER', 'luminisbot'),
                                               password=os.getenv('DB_PASSWORD', 'changeme123'))
    return _pool


def _query(conn, sql, params, fetch):
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        result = None
        if fetch == 'one':
            result = cur.fetchone()
        elif fetch == 'all':
            result = cur.fetchall()
    conn.commit()
    return result


def _run(sql, params=(), fetch=None):
    started = time.perf_counter()
    try:
        try:
            pool = _get_pool()
            conn = pool.getconn()
        except PoolError:  # every kept connection in use: a one-off
            pool, conn = None, get_db_connection()
        try:
            return _query(conn, sql, params, fetch)
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            if pool is None or not conn.closed:
                raise  # a real error, not a dropped connection
            pool.putconn(conn, close=True)  # stale (the database restarted): once more on a fresh one
            pool, conn = None, get_db_connection()
            return _query(conn, sql, params, fetch)
        except Exception:
            if not conn.closed:
                conn.rollback()
            raise
        finally:
            if pool is not None:
                pool.putconn(conn, close=bool(conn.closed))
            else:
                conn.close()
    finally:
        log = QUERY_LOG.get()
        if log is not None:
            log.append((time.perf_counter() - started, ' '.join(sql.split())[:100]))


# ============================================================================
# WRITES (sync)
# ============================================================================

def upsert_report(report, phase_names, source='guild'):
    _run("""
        INSERT INTO raid_reports (code, title, owner, zone_id, zone_name, start_time, end_time,
                                  phase_names, source, synced_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (code) DO UPDATE SET
            title = EXCLUDED.title, end_time = EXCLUDED.end_time,
            -- imported by hand first, then seen in the guild's own list: it's a guild log (kept by prune_reports)
            source = CASE WHEN EXCLUDED.source = 'guild' THEN 'guild' ELSE raid_reports.source END,
            zone_id = EXCLUDED.zone_id, zone_name = EXCLUDED.zone_name,
            phase_names = EXCLUDED.phase_names, synced_at = NOW(),
            -- an archived night fetched again (import, Discord recap): kept in full for a week, like an import
            created_at = CASE WHEN EXISTS (SELECT 1 FROM raid_pulls p WHERE p.report_code = raid_reports.code
                                                AND p.analysis ? 'archived')
                              THEN NOW() ELSE raid_reports.created_at END
    """, (report['code'], report.get('title') or report['code'], (report.get('owner') or {}).get('name'),
          (report.get('zone') or {}).get('id'), (report.get('zone') or {}).get('name'),
          report['startTime'], report['endTime'], Json(phase_names), source))


def upsert_pull(code, fight, analysis):
    transitions = fight.get('phaseTransitions') or []
    # The last transition's id matches the report's phase names (intermissions included);
    # WCL's lastPhase numbers phases differently, so it's only a fallback.
    last_phase = transitions[-1]['id'] if transitions else fight.get('lastPhase')
    _run("""
        INSERT INTO raid_pulls (report_code, fight_id, encounter_id, encounter_name, difficulty, kill,
                                size, start_ms, end_ms, fight_pct, boss_pct, last_phase,
                                last_phase_intermission, phases, analysis, analyzed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (report_code, fight_id) DO UPDATE SET
            kill = EXCLUDED.kill, end_ms = EXCLUDED.end_ms, fight_pct = EXCLUDED.fight_pct,
            boss_pct = EXCLUDED.boss_pct, last_phase = EXCLUDED.last_phase,
            last_phase_intermission = EXCLUDED.last_phase_intermission, phases = EXCLUDED.phases,
            analysis = EXCLUDED.analysis, analyzed_at = NOW()
    """, (code, fight['id'], fight['encounterID'], fight['name'], fight['difficulty'], bool(fight.get('kill')),
          fight.get('size'), fight['startTime'], fight['endTime'],
          0.0 if fight.get('kill') else fight.get('fightPercentage'),
          0.0 if fight.get('kill') else fight.get('bossPercentage'),
          last_phase, bool(fight.get('lastPhaseIsIntermission')),
          Json([{'id': p['id'], 'start': p['startTime'] - fight['startTime']} for p in transitions]),
          Json(analysis)))


def analyzed_fight_ids(code, version):
    rows = _run("""
        SELECT fight_id FROM raid_pulls
        WHERE report_code = %s AND (analysis->>'version')::int >= %s
          AND NOT analysis ? 'archived'  -- fetched again: analyzed in full again
    """, (code, version), fetch='all')
    return {r['fight_id'] for r in rows}


def fight_ids_missing_extras(code, version):
    """Pulls of a report whose throughput / uptime (analysis->'extras', throughput.py) is missing or older."""
    rows = _run("""
        SELECT fight_id FROM raid_pulls
        WHERE report_code = %s AND analysis IS NOT NULL AND NOT analysis ? 'archived'
          AND COALESCE((analysis->'extras'->>'v')::int, 0) < %s
    """, (code, version), fetch='all')
    return {r['fight_id'] for r in rows}


def players_missing_detail(code, min_ms):
    """
    Whether someone in a report has throughput but no pull with the per-player detail on a boss (sync.
    detail_fight_ids: a late joiner gets their own furthest pull) - counting pulls of min_ms or more only, the
    ones that can get it, so a player only in short wipes doesn't keep the night coming back.
    """
    row = _run("""
        WITH p AS (
            SELECT encounter_id, difficulty, analysis->'players' AS players, kill,
                   COALESCE((analysis->'extras'->>'detail')::boolean, TRUE) AS detail
            FROM raid_pulls
            WHERE report_code = %s AND analysis ? 'extras' AND NOT analysis ? 'archived'
              AND (kill OR end_ms - start_ms >= %s)
        )
        SELECT EXISTS (
            SELECT 1 FROM p, jsonb_array_elements(COALESCE(p.players, '[]'::jsonb)) x
            GROUP BY p.encounter_id, p.difficulty, x->>'name'
            HAVING NOT bool_or(p.detail)
        ) AS missing
    """, (code, min_ms), fetch='one')
    return bool(row and row['missing'])


def get_focus(code, fight_id, name):
    row = _run("SELECT data FROM raid_focus WHERE report_code = %s AND fight_id = %s AND name = %s",
               (code, fight_id, name), fetch='one')
    return row['data'] if row else None


def save_focus(code, fight_id, name, data):
    _run("""
        INSERT INTO raid_focus (report_code, fight_id, name, data) VALUES (%s, %s, %s, %s)
        ON CONFLICT (report_code, fight_id, name) DO UPDATE SET data = EXCLUDED.data, fetched_at = NOW()
    """, (code, fight_id, name, Json(data)))


def extras_state(code, version):
    """{fight id: None (no current extras) / True (with the per-player detail) / False (the cheap part only)}."""
    rows = _run("""
        SELECT fight_id,
               COALESCE((analysis->'extras'->>'v')::int, 0) >= %s AS current,
               COALESCE((analysis->'extras'->>'detail')::boolean, TRUE) AS detail
        FROM raid_pulls WHERE report_code = %s AND analysis IS NOT NULL
    """, (version, code), fetch='all')
    return {r['fight_id']: (r['detail'] if r['current'] else None) for r in rows}


_NEEDS_HEALER_PARSES = """
    p.kill AND NOT (p.analysis ? 'healer_parses')
    AND NOT COALESCE((p.analysis->'extras'->>'healer_parses')::boolean, false)
    AND (p.analysis ? 'extras' OR p.analysis ? 'slim_extras')
    AND p.analysis->'players' @> '[{"role": "healer"}]'::jsonb
"""


def pulls_missing_healer_parses(limit):
    """Kills with healers whose stored parses are still their damage ones (healer_parses), newest first."""
    rows = _run(f"""
        SELECT p.report_code, p.fight_id, p.analysis->'players' AS players
        FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code
        WHERE {_NEEDS_HEALER_PARSES}
        ORDER BY r.start_time DESC, p.fight_id LIMIT %s
    """, (limit,), fetch='all')
    return rows or []


def save_healer_parses(code, fight_id, parses):
    """
    Healers' healing parses into a stored kill - its extras, or an archived pull's slim_extras - and the pull
    marked done (healer_parses), with or without any (WCL may not rank it).
    """
    row = _run("SELECT analysis FROM raid_pulls WHERE report_code = %s AND fight_id = %s", (code, fight_id),
               fetch='one')
    if not row or not isinstance(row['analysis'], dict):
        return
    analysis = row['analysis']
    players = ((analysis.get('extras') or {}).get('players')
               if isinstance((analysis.get('extras') or {}).get('players'), dict) else analysis.get('slim_extras'))
    healers = {p['name'] for p in analysis.get('players') or [] if p.get('role') == 'healer'}
    for name in healers:
        if isinstance(players, dict) and isinstance(players.get(name), dict):
            players[name]['parse'] = parses.get(name)  # none: no healing parse - better than the damage one
    analysis['healer_parses'] = True
    _run("UPDATE raid_pulls SET analysis = %s WHERE report_code = %s AND fight_id = %s",
         (Json(analysis), code, fight_id))


_BEFORE_HOT_COUNTS = """
    p.analysis ? 'extras' AND NOT p.analysis ? 'archived'
    AND COALESCE(p.analysis->'extras'->>'hots_counted', '') <> %(counted)s
"""


def pulls_missing_hot_counts(limit):
    """
    Kept pulls synced before the HoTs on others were counted from the buff events (throughput.hots_out), where
    someone has them (a healer's buffs-on-others): {'report_code', 'fight_id', 'start_ms', 'end_ms', 'extras'},
    newest first. The ones where nobody does are just marked done, so they aren't looked through again.
    """
    from .throughput import HOTS_COUNTED
    counted = {'counted': str(HOTS_COUNTED), 'limit': limit}
    _run(f"""
        UPDATE raid_pulls p SET analysis = jsonb_set(p.analysis, '{{extras,hots_counted}}', to_jsonb(%(counted)s::int))
        WHERE {_BEFORE_HOT_COUNTS} AND NOT EXISTS (
            SELECT 1 FROM jsonb_each(COALESCE(p.analysis->'extras'->'players', '{{}}'::jsonb)) x
            WHERE jsonb_typeof(x.value->'on_others') = 'array')
    """, counted)
    return _run(f"""
        SELECT p.report_code, p.fight_id, p.start_ms, p.end_ms, p.analysis->'extras' AS extras
        FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code
        WHERE {_BEFORE_HOT_COUNTS}
        ORDER BY r.start_time DESC, p.fight_id LIMIT %(limit)s
    """, counted, fetch='all') or []


_BEFORE_PREPULL_BUFFS = """
    p.analysis ? 'extras' AND NOT p.analysis ? 'archived'
    AND NOT COALESCE((p.analysis->'extras'->>'prepull_buffs')::boolean, false)
"""


def pulls_missing_prepull_buffs(limit):
    """
    Kept pulls synced before self-buffs cast before the pull were kept (throughput.up_at_start), with the per-player
    detail: {'report_code', 'fight_id', 'start_ms', 'end_ms', 'extras'}, newest first. The ones without the detail
    (no auras stored at all) are just marked done.
    """
    _run(f"""
        UPDATE raid_pulls p SET analysis = jsonb_set(p.analysis, '{{extras,prepull_buffs}}', 'true'::jsonb)
        WHERE {_BEFORE_PREPULL_BUFFS} AND NOT COALESCE((p.analysis->'extras'->>'detail')::boolean, TRUE)
    """)
    return _run(f"""
        SELECT p.report_code, p.fight_id, p.start_ms, p.end_ms, p.analysis->'extras' AS extras
        FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code
        WHERE {_BEFORE_PREPULL_BUFFS}
        ORDER BY r.start_time DESC, p.fight_id LIMIT %s
    """, (limit,), fetch='all') or []


def set_pull_extras(code, fight_id, extras):
    _run("""
        UPDATE raid_pulls SET analysis = jsonb_set(analysis, '{extras}', %s)
        WHERE report_code = %s AND fight_id = %s
    """, (Json(extras), code, fight_id))


KEEP_LATEST_LOGS = 10   # the guild's latest raid logs are kept in full...
KEEP_IMPORTED_DAYS = 7  # ...plus anything imported (or re-fetched for a Discord recap) this week
KEEP_EMPTY_DAYS = 30    # logs without raid pulls (M+, trash) are remembered this long so they're checked once
# What an archived pull drops: the per-player timelines and throughput behind a night's pull, focus and
# comparison pages - most of its size. The rest (roster, deaths, mechanics, interrupts, consumables)
# stays for the boss pages, night-by-night and player trends.
ARCHIVE_DROP = ('casts', 'cooldowns', 'boss_casts', 'extras', 'cast_ids', 'casts_seen', 'incoming')
# ...but each player's totals and parse stay, as analysis['slim_extras'] ({name: {'damage', 'healing', 'active_ms',
# 'parse'}}), so the character pages keep their parse history
_SLIM_EXTRAS = """COALESCE((
    SELECT jsonb_object_agg(e.key, jsonb_strip_nulls(jsonb_build_object(
               'damage', e.value->'damage', 'healing', e.value->'healing', 'active_ms', e.value->'active_ms',
               'parse', e.value->'parse')))
    FROM jsonb_each(CASE WHEN jsonb_typeof(p.analysis->'extras'->'players') = 'object'
                         THEN p.analysis->'extras'->'players' ELSE '{}'::jsonb END) e), '{}'::jsonb)"""

_PAST_KEEP = """
    WITH raid AS (
        SELECT r.code, r.source, r.start_time, r.created_at,
               EXISTS (SELECT 1 FROM raid_pulls p WHERE p.report_code = r.code) AS has_pulls
        FROM raid_reports r
    ), latest AS (
        SELECT code FROM raid WHERE has_pulls AND source <> 'manual' ORDER BY start_time DESC LIMIT %s
    ), old AS (
        SELECT * FROM raid
        WHERE code NOT IN (SELECT code FROM latest)
          AND COALESCE(created_at, NOW()) < NOW() - make_interval(days => %s)
    )
"""


def prune_reports():
    """
    Past the KEEP_LATEST_LOGS latest guild / raid-event logs (and KEEP_IMPORTED_DAYS after a log came in):
    a guild night is archived - its pulls stay for the boss pages and player trends, minus ARCHIVE_DROP -
    and an import is deleted (it may be anyone's raid). Logs without raid pulls go after KEEP_EMPTY_DAYS.
    Fetching a night again (import its link) brings it back in full. Returns (deleted, archived) codes.
    """
    deleted = _run(_PAST_KEEP + """
        DELETE FROM raid_reports r USING old
        WHERE r.code = old.code
          AND CASE WHEN old.has_pulls THEN old.source = 'manual'
                   ELSE COALESCE(old.created_at, NOW()) < NOW() - make_interval(days => %s) END
        RETURNING r.code
    """, (KEEP_LATEST_LOGS, KEEP_IMPORTED_DAYS, KEEP_EMPTY_DAYS), fetch='all')
    archived = _run(_PAST_KEEP + f"""
        UPDATE raid_pulls p SET analysis = (p.analysis - %s::text[]) || jsonb_build_object('archived', NOW(),
               'slim_extras', {_SLIM_EXTRAS})
        FROM old
        WHERE p.report_code = old.code AND old.source <> 'manual'
          AND p.analysis IS NOT NULL AND NOT p.analysis ? 'archived'
        RETURNING p.report_code
    """, (KEEP_LATEST_LOGS, KEEP_IMPORTED_DAYS, list(ARCHIVE_DROP)), fetch='all')
    archived = sorted({r['report_code'] for r in archived or []})
    if archived:
        _run("DELETE FROM raid_focus WHERE report_code = ANY(%s)", (archived,))
    return [r['code'] for r in deleted or []], archived


def report_archived(code):
    """Whether a night's pulls were archived (prune_reports): no timelines or comparisons until fetched again."""
    row = _run("SELECT 1 FROM raid_pulls WHERE report_code = %s AND analysis ? 'archived' LIMIT 1",
               (code,), fetch='one')
    return bool(row)


def delete_report(code):
    _run("DELETE FROM raid_reports WHERE code = %s", (code,))


# How long after a report's last logged event a sync must have happened before
# we treat the report as finished (live logs keep moving end_time forward).
FINAL_AFTER = '2 hours'


def report_is_final(code):
    """True once we've synced the report well after its last pull - nothing new can appear."""
    row = _run(f"""
        SELECT synced_at > to_timestamp(end_time / 1000.0) + INTERVAL '{FINAL_AFTER}' AS final
        FROM raid_reports WHERE code = %s
    """, (code,), fetch='one')
    return bool(row and row['final'])


_REPORT_CODE_RE = re.compile(r'reports/([A-Za-z0-9]{16})')


def event_report_codes(since_days=None):
    """
    WCL report codes attached to raid events (raid_system's auto-linker), newest event first.
    since_days limits it to recent events, so the automatic backlog never wanders into old tiers.
    """
    where, params = '', ()
    if since_days:
        where, params = 'AND event_date >= CURRENT_DATE - %s', (since_days,)
    rows = _run(f"""
        SELECT log_url FROM raid_events
        WHERE log_url IS NOT NULL {where}
        ORDER BY event_date DESC, event_time DESC
    """, params, fetch='all')
    codes = []
    for row in rows:
        match = _REPORT_CODE_RE.search(row['log_url'] or '')
        if match and match.group(1) not in codes:
            codes.append(match.group(1))
    return codes


# ============================================================================
# READS (web)
# ============================================================================

# The raid event (raid_system) a report is attached to, if any.
_EVENT_JOIN = """
    LEFT JOIN LATERAL (
        SELECT e.id AS event_id, e.title AS event_title, e.channel_id AS event_channel_id FROM raid_events e
        WHERE e.log_url LIKE '%%' || r.code || '%%'
        ORDER BY e.event_date DESC LIMIT 1
    ) ev ON TRUE
"""


def _filters(zone_id=None, difficulty=None, report='r', pull='p'):
    clauses, params = [], []
    if zone_id is not None:
        clauses.append(f'{report}.zone_id = %s')
        params.append(zone_id)
    if difficulty is not None:
        clauses.append(f'{pull}.difficulty = %s')
        params.append(difficulty)
    return (' AND ' + ' AND '.join(clauses)) if clauses else '', params


def list_tiers():
    """Raid tiers (WCL zones) we have pulls for, newest first: [{'zone_id', 'zone_name', 'nights', 'last'}]."""
    return _run("""
        SELECT r.zone_id, MAX(r.zone_name) AS zone_name, COUNT(DISTINCT r.code) AS nights,
               MAX(r.start_time) AS last
        FROM raid_reports r JOIN raid_pulls p ON p.report_code = r.code
        GROUP BY r.zone_id
        ORDER BY MAX(r.start_time) DESC
    """, fetch='all')


def list_reports(limit=50, zone_id=None, difficulty=None, team=None):
    """Raid nights, newest first. A team narrows it to that team's nights; all teams lists every night."""
    where, params = _filters(zone_id, difficulty)
    if team:
        team_where, team_params = teams.sql_filter(team)
        where, params = where + team_where, params + team_params
    return _run(f"""
        SELECT r.code, r.title, r.owner, r.zone_name, r.start_time, r.end_time, r.synced_at, r.source,
               MAX(ev.event_id) AS event_id, MAX(ev.event_title) AS event_title,
               MAX(ev.event_channel_id) AS event_channel_id,
               COUNT(p.fight_id) AS pulls,
               COUNT(p.fight_id) FILTER (WHERE p.kill) AS kills,
               COALESCE(SUM(p.end_ms - p.start_ms), 0) AS combat_ms,
               MIN(p.start_ms) AS first_pull_ms, MAX(p.end_ms) AS last_pull_ms,
               ARRAY_AGG(DISTINCT p.difficulty) FILTER (WHERE p.difficulty IS NOT NULL) AS difficulties
        FROM raid_reports r
        JOIN raid_pulls p ON p.report_code = r.code
        {_EVENT_JOIN}
        WHERE TRUE {where}
        GROUP BY r.code
        ORDER BY r.start_time DESC
        LIMIT %s
    """, (*params, limit), fetch='all')


def get_report(code):
    return _run(f"SELECT r.*, ev.* FROM raid_reports r {_EVENT_JOIN} WHERE r.code = %s",
                (code,), fetch='one')


def analyzed_codes(codes):
    """Which of these report codes have at least one analyzed raid pull."""
    if not codes:
        return set()
    rows = _run("SELECT DISTINCT report_code FROM raid_pulls WHERE report_code = ANY(%s)",
                (list(codes),), fetch='all')
    return {r['report_code'] for r in rows}


def get_pulls(code, with_analysis=True):
    cols = '*' if with_analysis else ', '.join(_SUMMARY_COLS)
    return _run(f"""
        SELECT {cols} FROM raid_pulls WHERE report_code = %s ORDER BY start_ms
    """, (code,), fetch='all')


def get_pull(code, fight_id):
    return _run("""
        SELECT p.*, r.title AS report_title, r.start_time AS report_start, r.phase_names
        FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code
        WHERE p.report_code = %s AND p.fight_id = %s
    """, (code, fight_id), fetch='one')


_SUMMARY_COLS = ('report_code', 'fight_id', 'encounter_id', 'encounter_name', 'difficulty', 'kill', 'size',
                 'start_ms', 'end_ms', 'fight_pct', 'boss_pct', 'last_phase', 'last_phase_intermission',
                 'phases')


def get_boss_pulls(encounter_id, difficulty, with_analysis=False, team=None):
    """Every pull of a boss, oldest first - one team's, or all teams' (never for-fun raids)."""
    cols = 'p.*' if with_analysis else ', '.join(f'p.{c}' for c in _SUMMARY_COLS)
    team_where, team_params = teams.sql_filter(team)
    return _run(f"""
        SELECT {cols}, r.title AS report_title, r.start_time AS report_start, r.phase_names
        FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code
        {_EVENT_JOIN}
        WHERE p.encounter_id = %s AND p.difficulty = %s {team_where}
        ORDER BY r.start_time + p.start_ms
    """, (encounter_id, difficulty, *team_params), fetch='all')


def list_bosses(zone_id=None, difficulty=None, team=None):
    """
    One row per boss+difficulty we have pulls for, with progression summary. Hardest difficulty
    first, then roughly raid order (when we first pulled each boss). One team's, or all teams'
    (never for-fun raids - see teams.py).
    """
    where, params = _filters(zone_id, difficulty)
    team_where, team_params = teams.sql_filter(team)
    where, params = where + team_where, params + team_params
    return _run(f"""
        SELECT p.encounter_id, MAX(p.encounter_name) AS name, p.difficulty, MAX(r.zone_name) AS zone_name,
               COUNT(*) AS pulls,
               COUNT(*) FILTER (WHERE p.kill) AS kills,
               MIN(p.fight_pct) FILTER (WHERE NOT p.kill) AS best_pct,
               MIN(r.start_time + p.start_ms) FILTER (WHERE p.kill) AS first_kill,
               MIN(r.start_time) AS first_seen, MAX(r.start_time) AS last_seen,
               COUNT(DISTINCT r.code) AS nights
        FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code
        {_EVENT_JOIN}
        WHERE TRUE {where}
        GROUP BY p.encounter_id, p.difficulty
        ORDER BY p.difficulty DESC, MIN(r.start_time + p.start_ms)
    """, params, fetch='all')


def get_tags(encounter_id):
    rows = _run("SELECT ability_id, tag FROM raid_ability_tags WHERE encounter_id = %s",
                (encounter_id,), fetch='all')
    return {r['ability_id']: r['tag'] for r in rows}


def get_tag_rows(encounter_id):
    """Officers' overrides for a boss, newest first: [{'ability_id', 'ability_name', 'tag'}]."""
    return _run("""
        SELECT ability_id, ability_name, tag FROM raid_ability_tags WHERE encounter_id = %s
        ORDER BY updated_at DESC NULLS LAST
    """, (encounter_id,), fetch='all') or []


TAG_NONE = 'none'   # officer cleared the automatic tag - remembered so it doesn't come back
TAG_AUTO = 'auto'   # request: drop the officer's override and go back to the automatic tag


def set_tag(encounter_id, ability_id, ability_name, tag, username):
    """Officer override for one ability. Rows only exist for overrides; auto tags aren't stored."""
    if tag == TAG_AUTO:
        _run("DELETE FROM raid_ability_tags WHERE encounter_id = %s AND ability_id = %s",
             (encounter_id, ability_id))
        return
    if tag not in TAGS:
        tag = TAG_NONE
    _run("""
        INSERT INTO raid_ability_tags (encounter_id, ability_id, ability_name, tag, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (encounter_id, ability_id) DO UPDATE SET
            tag = EXCLUDED.tag, ability_name = EXCLUDED.ability_name,
            updated_by = EXCLUDED.updated_by, updated_at = NOW()
    """, (encounter_id, ability_id, ability_name, tag, username))


# ============================================================================
# MYTHIC TRAP GUIDES
# ============================================================================

def bosses_needing_guides(max_age_days, only=None):
    """Bosses we have pulls for whose guide was never fetched or is stale (or `only`, forced)."""
    if only:
        where, params = "p.encounter_id = ANY(%s)", [list(only)]
    else:
        where = ("s.encounter_id IS NULL OR s.scanned_at < NOW() - make_interval(days => %s)")
        params = [max_age_days]
    return _run(f"""
        SELECT p.encounter_id, MAX(p.encounter_name) AS name, MAX(r.zone_name) AS zone_name
        FROM raid_pulls p
        JOIN raid_reports r ON r.code = p.report_code
        LEFT JOIN raid_guide_scans s ON s.encounter_id = p.encounter_id
        WHERE {where}
        GROUP BY p.encounter_id
    """, params, fetch='all')


def save_guide_scan(encounter_id, page_url, status, ability_count, error=None):
    _run("""
        INSERT INTO raid_guide_scans (encounter_id, page_url, status, ability_count, error, scanned_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (encounter_id) DO UPDATE SET
            page_url = COALESCE(EXCLUDED.page_url, raid_guide_scans.page_url),
            status = EXCLUDED.status, error = EXCLUDED.error, scanned_at = NOW(),
            ability_count = CASE WHEN EXCLUDED.status = 'ok' THEN EXCLUDED.ability_count
                                 ELSE raid_guide_scans.ability_count END
    """, (encounter_id, page_url, status, ability_count, error))


def replace_guide_abilities(encounter_id, abilities):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raid_guide_abilities WHERE encounter_id = %s", (encounter_id,))
            for a in abilities:
                cur.execute("""
                    INSERT INTO raid_guide_abilities (encounter_id, guide_id, spell_id, name, category,
                                                      subtitle, tip, description, video_url, embed_url)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (encounter_id, a['guide_id'], a['spell_id'], a['name'], a['category'], a['subtitle'],
                      a['tip'], a['description'], a['video_url'], a['embed_url']))
        conn.commit()
    finally:
        conn.close()


def get_guides(encounter_id):
    return _run("SELECT * FROM raid_guide_abilities WHERE encounter_id = %s ORDER BY guide_id",
                (encounter_id,), fetch='all')


def get_guide_scan(encounter_id):
    return _run("SELECT * FROM raid_guide_scans WHERE encounter_id = %s", (encounter_id,), fetch='one')


def ability_shares(encounter_id):
    """
    {ability_id: {'name', 'share'}} for every enemy ability logged on a boss:
    the average share of the raid it hit per pull (complete pulls only), for
    guides.auto_tags' raid-wide check. Computed in SQL so pages don't have to
    load every pull's analysis.
    """
    rows = _run("""
        SELECT (ab->>'id')::bigint AS id, MAX(ab->>'name') AS name,
               AVG((SELECT COUNT(*) FROM jsonb_object_keys(ab->'players'))::float
                   / GREATEST(jsonb_array_length(p.analysis->'players'), 1))
                   FILTER (WHERE (ab->>'complete')::boolean) AS share
        FROM raid_pulls p, jsonb_array_elements(p.analysis->'abilities') ab
        WHERE p.encounter_id = %s AND jsonb_typeof(ab->'players') = 'object'
        GROUP BY 1
    """, (encounter_id,), fetch='all')
    return {r['id']: {'name': r['name'], 'share': r['share']} for r in rows}


def character_owners():
    """
    {lower-case character: {'key', 'discord_id', 'display'}} - who plays which character
    (raid signups first, then linked Battle.net characters; see raidanalysis/people.py).
    """
    from .people import resolve_owners
    try:
        signups = _run("""
            SELECT character_name, discord_id, COUNT(*) AS n FROM raid_signups
            GROUP BY character_name, discord_id
        """, fetch='all')
        linked = _run("SELECT character_name, discord_id FROM wow_characters", fetch='all')
        displays = _run("""
            SELECT discord_id, COALESCE(discord_display_name, discord_username) AS display FROM wow_connections
        """, fetch='all')
    except Exception as e:  # character / signup tables missing (fresh install)
        logger.warning(f"[RAIDS] Character owners unavailable: {e}")
        return {}
    return resolve_owners([(r['character_name'], r['discord_id'], r['n']) for r in signups],
                          [(r['character_name'], r['discord_id']) for r in linked],
                          {r['discord_id']: r['display'] for r in displays})


# ============================================================================
# CHARACTER PAGES (character.py)
# ============================================================================

# What a character's page needs of each pull: everything scoring uses, without the per-player timelines
# and throughput (most of a pull's size) - apart from this character's own throughput row.


def list_characters(zone_id=None, difficulty=None, team=None, names=None):
    """
    Everyone in our own logs (imports left out - they may be anyone's raid), most nights first:
    [{'name', 'class', 'spec', 'role', 'pulls', 'kills', 'nights', 'last_seen', 'night_starts' (when each of those
    nights began: who's been in the latest ones)}] - spec / role as last played.
    names: only these characters (lower case) - a player's characters on the character page.
    """
    where, params = _filters(zone_id, difficulty)
    if team:
        team_where, team_params = teams.sql_filter(team)
        where, params = where + team_where, params + team_params
    if names is not None:
        where, params = where + " AND lower(x->>'name') = ANY(%s)", params + [list(names)]
    rows = _run(f"""
        SELECT x->>'name' AS name, rr.realm, MAX(x->>'class') AS class,
               (array_agg(x->>'spec' ORDER BY r.start_time DESC))[1] AS spec,
               (array_agg(x->>'role' ORDER BY r.start_time DESC))[1] AS role,
               COUNT(*) AS pulls, COUNT(*) FILTER (WHERE p.kill) AS kills,
               COUNT(DISTINCT r.code) AS nights, MAX(r.start_time) AS last_seen,
               array_agg(DISTINCT r.start_time) AS night_starts
        FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code
        {_EVENT_JOIN}
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(p.players, '[]'::jsonb)) x
        LEFT JOIN raid_realms rr ON rr.report_code = r.code AND rr.name = x->>'name'
        WHERE r.source <> 'manual' AND COALESCE(x->>'name', '') <> '' {where}
        GROUP BY x->>'name', rr.realm
    """, params, fetch='all')
    return _merge_unknown_realms(rows)


def _merge_unknown_realms(rows):
    """
    Logs whose realms aren't recorded yet (backfilled a few per sync) count toward the realm we know for that
    name - the one with the most nights when there are several. Most nights first.
    """
    by_name = {}
    for r in rows:
        by_name.setdefault(r['name'], []).append(dict(r))
    out = []
    for name, group in by_name.items():
        known = [g for g in group if g['realm']]
        unknown = [g for g in group if not g['realm']]
        if known and unknown:
            into = max(known, key=lambda g: g['nights'])
            for u in unknown:
                for key in ('pulls', 'kills', 'nights'):
                    into[key] += u[key]
                if into.get('night_starts') is not None:
                    into['night_starts'] = sorted(set(into['night_starts']) | set(u.get('night_starts') or ()))
                    into['nights'] = len(into['night_starts'])
                if u['last_seen'] > into['last_seen']:
                    into.update(last_seen=u['last_seen'], spec=u['spec'], role=u['role'])
            group = known
        out += group
    return sorted(out, key=lambda r: (-r['nights'], r['name'], r['realm'] or ''))


def character_pull_index(name, realm=None):
    """
    Every pull of our own logs a character was in, night by night - without the analysis (character.profile
    narrows them to a tier and difficulty first, then loads only those nights' bosses - group_pulls): pull rows
    with the night's title, start and zone. realm (WCL's spelling): only that realm's character - logs whose
    realms aren't recorded yet count too.
    """
    realm_where = 'AND (rr.realm = %s OR rr.realm IS NULL)' if realm else ''
    return _run(f"""
        SELECT p.report_code, p.fight_id, p.encounter_id, p.encounter_name, p.difficulty, p.kill, p.start_ms,
               p.end_ms, p.fight_pct, r.title AS report_title, r.start_time AS report_start, r.zone_name, r.zone_id
        FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code
        LEFT JOIN raid_realms rr ON rr.report_code = r.code AND rr.name = %s
        WHERE r.source <> 'manual' AND p.players @> %s::jsonb {realm_where}
        ORDER BY r.start_time, p.start_ms
    """, (name, Json([{'name': name}])) + ((realm,) if realm else ()), fetch='all')


# What scoring a night's boss needs of each pull - deaths, mechanics, consumables, everyone's parse and output - and
# not the per-player casts, auras and the like: most of a stored analysis, read here for nothing.
_GROUP_ANALYSIS = """
    (p.analysis - '{casts,cooldowns,boss_casts,cast_ids,casts_seen,extras,slim_extras,incoming}'::text[])
    || jsonb_build_object('extras', jsonb_build_object(
           'duration', p.analysis->'extras'->'duration',
           'players', (SELECT COALESCE(jsonb_object_agg(e.key, jsonb_build_object(
                                'parse', e.value->'parse', 'damage', e.value->'damage', 'healing', e.value->'healing')),
                                '{}'::jsonb)
                       FROM jsonb_each(CASE WHEN jsonb_typeof(COALESCE(p.analysis->'extras'->'players',
                                                                       p.analysis->'slim_extras')) = 'object'
                                            THEN COALESCE(p.analysis->'extras'->'players', p.analysis->'slim_extras')
                                            ELSE '{}'::jsonb END) e)))
"""


def group_pulls(groups):
    """
    Every pull of these (report code, encounter, difficulty) groups - a night's boss, the whole raid - in order,
    with the analysis as scoring needs it (_GROUP_ANALYSIS).
    """
    if not groups:
        return []
    return _run(f"""
        SELECT p.report_code, p.fight_id, p.encounter_id, p.difficulty, p.kill, p.start_ms, p.end_ms, p.fight_pct,
               {_GROUP_ANALYSIS} AS analysis
        FROM raid_pulls p
        WHERE (p.report_code, p.encounter_id, p.difficulty) IN %s
        ORDER BY p.report_code, p.encounter_id, p.difficulty, p.start_ms
    """, (tuple(tuple(g) for g in groups),), fetch='all')


def zone_order(zone_id):
    """{encounter id: its place in the raid (0 = first boss)} for a raid tier, or {} when it isn't known yet."""
    if zone_id is None:
        return {}
    row = _run("SELECT encounters FROM raid_zones WHERE zone_id = %s", (zone_id,), fetch='one')
    return {int(e): i for i, e in enumerate(row['encounters'])} if row else {}


def save_zone(zone_id, encounter_ids):
    _run("""
        INSERT INTO raid_zones (zone_id, encounters) VALUES (%s, %s)
        ON CONFLICT (zone_id) DO UPDATE SET encounters = EXCLUDED.encounters, fetched_at = NOW()
    """, (zone_id, Json([int(e) for e in encounter_ids])))


def zones_missing(limit):
    """Raid tiers in our logs whose boss order we haven't fetched (or not for a week: a tier may get bosses added)."""
    rows = _run("""
        SELECT DISTINCT r.zone_id FROM raid_reports r
        LEFT JOIN raid_zones z ON z.zone_id = r.zone_id
        WHERE r.zone_id IS NOT NULL AND (z.zone_id IS NULL OR z.fetched_at < NOW() - INTERVAL '7 days')
        LIMIT %s
    """, (limit,), fetch='all')
    return [r['zone_id'] for r in rows or []]


def realms_for(name):
    """The realms a character name is known on in our logs, most nights first: [{'realm', 'nights'}]."""
    return _run("""
        SELECT realm, COUNT(*) AS nights FROM raid_realms WHERE lower(name) = lower(%s)
        GROUP BY realm ORDER BY COUNT(*) DESC
    """, (name,), fetch='all')


def save_realms(code, realms):
    """{player name: realm} for one log (WCL's actor list)."""
    rows = [(code, n, r) for n, r in realms.items() if n and r]
    if not rows:
        return
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO raid_realms (report_code, name, realm) VALUES (%s, %s, %s)
                ON CONFLICT (report_code, name) DO UPDATE SET realm = EXCLUDED.realm
            """, rows)
        conn.commit()
    finally:
        conn.close()


def reports_missing_realms(limit):
    """Our logs with raid pulls whose players' realms aren't recorded yet, newest first."""
    rows = _run("""
        SELECT r.code FROM raid_reports r
        WHERE r.source <> 'manual' AND EXISTS (SELECT 1 FROM raid_pulls p WHERE p.report_code = r.code)
          AND NOT EXISTS (SELECT 1 FROM raid_realms rr WHERE rr.report_code = r.code)
        ORDER BY r.start_time DESC LIMIT %s
    """, (limit,), fetch='all')
    return [r['code'] for r in rows]


# ============================================================================
# CHARACTERS (armory.py)
# ============================================================================

def get_armory(name, realm=None):
    """
    The most recently fetched character of that name (on that realm - Blizzard's slug - when given):
    {'realm', 'data', 'fetched_at'} or None.
    """
    return _run("""
        SELECT realm, data, fetched_at FROM raid_armory WHERE name_key = lower(%s) AND (%s::text IS NULL OR realm = %s)
        ORDER BY fetched_at DESC LIMIT 1
    """, (name, realm, realm), fetch='one')


def data_version():
    """
    A fingerprint of what the raid pages show - pulls (how many, the last analysis change), top players, reports:
    the page caches keep a page until it changes, instead of starting over at every sync whether or not it
    brought anything.
    """
    row = _run("""
        SELECT (SELECT COUNT(*) FROM raid_pulls) AS pulls, (SELECT MAX(changed_at) FROM raid_pulls) AS changed,
               (SELECT MAX(fetched_at) FROM raid_benchmarks) AS benchmarks, (SELECT MAX(synced_at) FROM raid_reports) AS reports,
               (SELECT MAX(scanned_at) FROM raid_guide_scans) AS guides
    """, fetch='one')
    return f"{row['pulls']}|{row['changed']}|{row['benchmarks']}|{row['reports']}|{row['guides']}"


def armory_images():
    """
    Every stored character's picture links - ours (raid_armory) and linked characters' (wow_characters):
    [{'name_key' (lower case), 'realm' (slug), 'render', 'avatar', 'thumb', 'rio_thumb'}] - only the few fields,
    not the whole stored character.
    """
    return _run("""
        SELECT name_key, realm, pic_render AS render, pic_avatar AS avatar, pic_thumb AS thumb, pic_rio_thumb AS rio_thumb
        FROM raid_armory
        UNION ALL
        SELECT lower(character_name), realm_slug, pic_render, pic_avatar, pic_thumb, NULL
        FROM wow_characters WHERE pic_render IS NOT NULL OR pic_avatar IS NOT NULL OR pic_thumb IS NOT NULL
    """, fetch='all')


def realm_in(code, name):
    """A character's realm in one log (WCL's spelling), or None when it isn't recorded."""
    row = _run("SELECT realm FROM raid_realms WHERE report_code = %s AND name = %s", (code, name), fetch='one')
    return row['realm'] if row else None


def save_armory(name, realm, data):
    _run("""
        INSERT INTO raid_armory (name_key, realm, data, fetched_at) VALUES (lower(%s), %s, %s, NOW())
        ON CONFLICT (name_key, realm) DO UPDATE SET data = EXCLUDED.data, fetched_at = NOW()
    """, (name, realm, Json(data)))


# ============================================================================
# ENEMY PORTRAITS (npcs.py)
# ============================================================================

def get_npcs(names, version):
    """
    {name: icon url or None} for the enemies looked up already by this version of the lookup (failed
    lookups retried after a day).
    """
    if not names:
        return {}
    rows = _run("""
        SELECT name, icon FROM raid_npcs
        WHERE name = ANY(%s) AND version >= %s AND (status = 'ok' OR fetched_at > NOW() - INTERVAL '1 day')
    """, (list(names), version), fetch='all')
    return {r['name']: r['icon'] for r in rows}


def get_npc_ids(names):
    """{name: NPC id} for the enemies whose id a portrait lookup found (npcs.py)."""
    if not names:
        return {}
    rows = _run("SELECT name, game_id FROM raid_npcs WHERE name = ANY(%s) AND game_id IS NOT NULL",
                (list(names),), fetch='all')
    return {r['name']: r['game_id'] for r in rows}


def save_npc(name, game_id, icon, status, version):
    _run("""
        INSERT INTO raid_npcs (name, game_id, icon, status, version, fetched_at) VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (name) DO UPDATE SET game_id = EXCLUDED.game_id, icon = EXCLUDED.icon, status = EXCLUDED.status,
            version = EXCLUDED.version, fetched_at = NOW()
    """, (name, game_id, icon, status, version))


# ============================================================================
# SPELL TOOLTIPS (spells.py)
# ============================================================================

def spells_missing(limit):
    """Spell IDs our analyses mention without a cached tooltip (failed lookups retried after an hour)."""
    rows = _run("""
        WITH mentioned AS (
            SELECT DISTINCT (c->>1)::bigint AS id, 0 AS priority FROM raid_benchmarks,
                   jsonb_array_elements(players) p, jsonb_array_elements(p->'casts') c
            UNION SELECT DISTINCT (x->>'id')::bigint, 1 FROM raid_pulls,
                   jsonb_array_elements(COALESCE(analysis->'boss_abilities', '[]'::jsonb)) x
            UNION SELECT DISTINCT (x->>'ability_id')::bigint, 1 FROM raid_pulls,
                   jsonb_array_elements(COALESCE(analysis->'cooldowns', '[]'::jsonb)) x
            UNION SELECT DISTINCT (x->>'ability_id')::bigint, 1 FROM raid_pulls,
                   jsonb_array_elements(COALESCE(analysis->'consumables', '[]'::jsonb)) x
            UNION SELECT DISTINCT (x->>'ability_id')::bigint, 1 FROM raid_pulls,
                   jsonb_array_elements(COALESCE(analysis->'deaths', '[]'::jsonb)) x
        )
        SELECT m.id FROM (SELECT id, MIN(priority) AS priority FROM mentioned GROUP BY id) m
        LEFT JOIN raid_spells s ON s.spell_id = m.id
        WHERE m.id IS NOT NULL AND m.id > 0
          AND (s.spell_id IS NULL OR s.parser < %s
               OR (s.status = 'error' AND s.fetched_at < NOW() - INTERVAL '1 hour'))
        ORDER BY m.priority
        LIMIT %s
    """, (_spell_parser(), limit), fetch='all')
    return [r['id'] for r in rows]


def _spell_parser():
    from .spells import PARSER
    return PARSER


def save_spell(spell_id, info, status):
    info = info or {}
    _run("""
        INSERT INTO raid_spells (spell_id, name, icon, meta, description, status, parser, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (spell_id) DO UPDATE SET name = EXCLUDED.name, icon = EXCLUDED.icon, meta = EXCLUDED.meta,
            description = EXCLUDED.description, status = EXCLUDED.status, parser = EXCLUDED.parser, fetched_at = NOW()
    """, (spell_id, info.get('name'), info.get('icon'), info.get('meta'), info.get('description'), status,
          _spell_parser()))


def get_spells(spell_ids):
    """{spell id: {'name', 'icon', 'meta', 'description'}} for the cached ones."""
    if not spell_ids:
        return {}
    rows = _run("""
        SELECT spell_id, name, icon, meta, description FROM raid_spells
        WHERE status = 'ok' AND spell_id = ANY(%s)
    """, ([int(i) for i in spell_ids],), fetch='all')
    return {r['spell_id']: r for r in rows}


# ============================================================================
# TOP-PLAYER BENCHMARKS (benchmarks.py)
# ============================================================================

# The hero tree a player (x, of raid_pulls.players) played in pull p: the one most of their hero talents are in -
# '' when their talents weren't kept or don't say (gamedata.hero_tree, in SQL).
_HERO_SQL = """COALESCE((
    SELECT h.name FROM jsonb_array_elements_text(CASE WHEN jsonb_typeof(p.talents -> (x->>'name')) = 'array'
                                                      THEN p.talents -> (x->>'name') ELSE '[]'::jsonb END) e
    JOIN raid_hero_trees h ON h.entry_id = e::bigint
    GROUP BY h.name ORDER BY COUNT(*) DESC, h.name LIMIT 1), '')"""


def benchmarks_needed(limit, refresh_days, difficulties):
    """
    (boss, difficulty, class, spec, hero tree) combos played in the logs we keep (prune_reports: the latest
    KEEP_LATEST_LOGS guild / raid-event logs, plus imports from the last KEEP_IMPORTED_DAYS) that have no
    benchmark yet, a stale one, or a failed one from a while ago - most recently played first. And the whole
    spec's (hero '') wherever a hero tree has no top players: its pages fall back on that one (benchmarks.py).
    """
    from .throughput import HOTS_COUNTED
    return _run("""
        WITH latest AS (
            SELECT r.code FROM raid_reports r
            WHERE r.source <> 'manual' AND EXISTS (SELECT 1 FROM raid_pulls p WHERE p.report_code = r.code)
            ORDER BY r.start_time DESC LIMIT %s
        ), played AS (
            SELECT encounter_id, difficulty, class, spec, hero, MAX(role) AS role, MAX(played) AS last_played
            FROM (
                SELECT p.encounter_id, p.difficulty, x->>'class' AS class, x->>'spec' AS spec, x->>'role' AS role,
                       r.start_time + p.start_ms AS played, """ + _HERO_SQL + """ AS hero
                FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code,
                     jsonb_array_elements(COALESCE(p.players, '[]'::jsonb)) x
                -- imports by source, not created_at alone: the column was added with every older night
                -- getting the migration's time
                WHERE (r.code IN (SELECT code FROM latest)
                       OR (r.source = 'manual' AND COALESCE(r.created_at, NOW()) >= NOW() - make_interval(days => %s)))
                  AND p.difficulty = ANY(%s) AND COALESCE(x->>'spec', '') <> '' AND COALESCE(x->>'class', '') <> ''
            ) pulls
            GROUP BY 1, 2, 3, 4, 5
        ), c AS (
            SELECT * FROM played
            UNION ALL
            -- a hero tree without top players (its fetch failed, or WCL ranks none of it): the whole spec's
            SELECT h.encounter_id, h.difficulty, h.class, h.spec, '' AS hero, MAX(h.role), MAX(h.last_played)
            FROM played h JOIN raid_benchmarks b
                 ON b.encounter_id = h.encounter_id AND b.difficulty = h.difficulty AND b.class = h.class
                AND b.spec = h.spec AND b.hero = h.hero
            WHERE h.hero <> '' AND jsonb_array_length(b.players) = 0
              AND NOT EXISTS (SELECT 1 FROM played w WHERE w.encounter_id = h.encounter_id
                              AND w.difficulty = h.difficulty AND w.class = h.class AND w.spec = h.spec AND w.hero = '')
            GROUP BY 1, 2, 3, 4
        )
        SELECT c.* FROM c
        WHERE NOT EXISTS (
            SELECT 1 FROM raid_benchmarks b
            WHERE b.encounter_id = c.encounter_id AND b.difficulty = c.difficulty
              AND b.class = c.class AND b.spec = c.spec AND b.hero = c.hero
              AND (
                  -- failed lately: wait a few hours, whatever top players it kept (otherwise a failing combo
                  -- with old-format players would top this list again right away, every batch) - WCL being down
                  -- for a while is the usual reason. Empty: a day - a new boss (or difficulty) gets ranked
                  -- parses within a day, not a week.
                  (b.status = 'error' AND b.fetched_at > NOW() - INTERVAL '3 hours')
                  OR (b.status = 'empty' AND b.fetched_at > NOW() - INTERVAL '1 day')
                  OR (b.status NOT IN ('error', 'empty') AND b.fetched_at > NOW() - make_interval(days => %s)
                      -- fetched before every top parse's spec was checked, or before their auras and
                      -- casts were kept (uptime / casts per minute), or the lust on them (the cooldowns
                      -- timeline), or - healers' HoTs on others - before they were counted from the buff events
                      -- (throughput.hots_out): fetch again
                      AND (jsonb_array_length(b.players) = 0
                           OR (b.players -> 0 ? 'spec' AND b.players -> 0 ? 'auras' AND b.players -> 0 ? 'lust'
                               AND (jsonb_typeof(b.players -> 0 -> 'on_others') IS DISTINCT FROM 'array'
                                    OR b.players -> 0 ->> 'hots_counted' = %s)))))
        )
        ORDER BY c.last_played DESC
        LIMIT %s
    """, (KEEP_LATEST_LOGS, KEEP_IMPORTED_DAYS, list(difficulties), refresh_days, str(HOTS_COUNTED), limit),
                fetch='all')


def boss_benchmarks(encounter_id, difficulty):
    """
    Every spec + hero tree we ever played on one boss + difficulty (any team, any night) with its benchmark's
    state, whatever its age: [{'encounter_id', 'difficulty', 'class', 'spec', 'hero', 'role', 'status', 'error',
    'fetched_at', 'top'}] - status None when never fetched. The boss page's re-fetch button. Like benchmarks_needed,
    the whole spec's (hero '') too wherever a hero tree has no top players: its pages fall back on that one.
    """
    return _run("""
        WITH played AS (
            SELECT encounter_id, difficulty, class, spec, hero, MAX(role) AS role
            FROM (
                SELECT p.encounter_id, p.difficulty, x->>'class' AS class, x->>'spec' AS spec, x->>'role' AS role,
                       """ + _HERO_SQL + """ AS hero
                FROM raid_pulls p, jsonb_array_elements(COALESCE(p.players, '[]'::jsonb)) x
                WHERE p.encounter_id = %s AND p.difficulty = %s
                  AND COALESCE(x->>'spec', '') <> '' AND COALESCE(x->>'class', '') <> ''
            ) pulls
            GROUP BY 1, 2, 3, 4, 5
        ), c AS (
            SELECT * FROM played
            UNION ALL
            SELECT h.encounter_id, h.difficulty, h.class, h.spec, '' AS hero, MAX(h.role)
            FROM played h JOIN raid_benchmarks b
                 ON b.encounter_id = h.encounter_id AND b.difficulty = h.difficulty AND b.class = h.class
                AND b.spec = h.spec AND b.hero = h.hero
            WHERE h.hero <> '' AND jsonb_array_length(b.players) = 0
              AND NOT EXISTS (SELECT 1 FROM played w WHERE w.encounter_id = h.encounter_id
                              AND w.difficulty = h.difficulty AND w.class = h.class AND w.spec = h.spec AND w.hero = '')
            GROUP BY 1, 2, 3, 4
        )
        SELECT c.*, b.status, b.error, b.fetched_at, jsonb_array_length(COALESCE(b.players, '[]'::jsonb)) AS top
        FROM c
        LEFT JOIN raid_benchmarks b ON b.encounter_id = c.encounter_id AND b.difficulty = c.difficulty
                                    AND b.class = c.class AND b.spec = c.spec AND b.hero = c.hero
        ORDER BY c.class, c.spec, c.hero
    """, (encounter_id, difficulty), fetch='all')


def save_benchmark(encounter_id, difficulty, class_name, spec, hero, metric, players, status, error=None):
    """A failed refresh keeps the previous top players (only the status changes). hero '': the whole spec's."""
    _run("""
        INSERT INTO raid_benchmarks (encounter_id, difficulty, class, spec, hero, metric, players, status, error,
                                     fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (encounter_id, difficulty, class, spec, hero) DO UPDATE SET metric = EXCLUDED.metric,
            players = CASE WHEN EXCLUDED.status = 'error' THEN raid_benchmarks.players ELSE EXCLUDED.players END,
            status = EXCLUDED.status, error = EXCLUDED.error, fetched_at = NOW()
    """, (encounter_id, difficulty, class_name, spec, hero or '', metric, Json(players), status, error))


def get_benchmark(encounter_id, difficulty, class_name, spec, hero=''):
    return _run("""
        SELECT * FROM raid_benchmarks
        WHERE encounter_id = %s AND difficulty = %s AND class = %s AND spec = %s AND hero = %s
    """, (encounter_id, difficulty, class_name, spec, hero or ''), fetch='one')


def benchmark_spell_ids(encounter_id):
    """Every spell the top players cast on this boss (any spec) - fetched for our players too."""
    rows = _run("""
        SELECT DISTINCT (c->>1)::bigint AS id FROM raid_benchmarks,
               jsonb_array_elements(players) p, jsonb_array_elements(p->'casts') c
        WHERE encounter_id = %s
    """, (encounter_id,), fetch='all')
    return [r['id'] for r in rows]


def attempted_spell_ids(spell_ids):
    """Which of these spells were looked up already (failures count again after an hour)."""
    rows = _run("""
        SELECT spell_id FROM raid_spells
        WHERE spell_id = ANY(%s) AND parser >= %s
          AND (status <> 'error' OR fetched_at > NOW() - INTERVAL '1 hour')
    """, ([int(i) for i in spell_ids], _spell_parser()), fetch='all')
    return {r['spell_id'] for r in rows}


def tracked_spells_stale(days):
    row = _run("SELECT MAX(fetched_at) > NOW() - make_interval(days => %s) AS fresh FROM raid_tracked_spells",
               (days,), fetch='one')
    return not (row and row['fresh'])


def replace_tracked_spells(kind, spell_ids):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raid_tracked_spells WHERE kind = %s", (kind,))
            cur.executemany("INSERT INTO raid_tracked_spells (spell_id, kind) VALUES (%s, %s)",
                            [(int(i), kind) for i in sorted(spell_ids)])
        conn.commit()
    finally:
        conn.close()


def get_tracked_spells(kind):
    return frozenset(r['spell_id'] for r in _run("SELECT spell_id FROM raid_tracked_spells WHERE kind = %s",
                                                 (kind,), fetch='all'))


def talents_stale(days):
    """A week old - or without the hero trees or the choice nodes (kept since): fetched again."""
    row = _run("""
        SELECT MAX(fetched_at) > NOW() - make_interval(days => %s) AND EXISTS (SELECT 1 FROM raid_hero_trees)
               AND bool_or(choice IS NOT NULL) AS fresh
        FROM raid_talents
    """, (days,), fetch='one')
    return not (row and row['fresh'])


def replace_talents(rows, heroes):
    """
    rows: [(entry id, tree id, ability name, name of the ability it replaces or None, choice node or None)];
    heroes: [(entry id, hero tree)].
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM raid_talents")
            cur.executemany("INSERT INTO raid_talents (entry_id, tree_id, name, overrides, choice) "
                            "VALUES (%s, %s, %s, %s, %s)", rows)
            cur.execute("DELETE FROM raid_hero_trees")
            cur.executemany("INSERT INTO raid_hero_trees (entry_id, name) VALUES (%s, %s)", heroes)
        conn.commit()
    finally:
        conn.close()


def get_talents():
    return _run("SELECT entry_id, tree_id, name, overrides, choice FROM raid_talents", fetch='all')


def get_hero_trees():
    """{talent entry id: hero tree name}."""
    return {r['entry_id']: r['name'] for r in _run("SELECT entry_id, name FROM raid_hero_trees", fetch='all')}


def get_spec_overrides():
    """{(class, spec): {ability name: kind}} - officers' major / rotational / hide calls."""
    out = {}
    for r in _run("SELECT class, spec, ability_name, kind FROM raid_spec_abilities", fetch='all'):
        out.setdefault((r['class'], r['spec']), {})[r['ability_name']] = r['kind']
    return out


def set_spec_override(class_name, spec, ability_name, kind, username):
    """kind '' (or unknown) removes the override: back to the automatic call."""
    from .benchmarks import SPEC_KINDS
    if kind not in SPEC_KINDS:
        _run("DELETE FROM raid_spec_abilities WHERE class = %s AND spec = %s AND ability_name = %s",
             (class_name, spec, ability_name))
        return
    _run("""
        INSERT INTO raid_spec_abilities (class, spec, ability_name, kind, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (class, spec, ability_name) DO UPDATE SET kind = EXCLUDED.kind,
            updated_by = EXCLUDED.updated_by, updated_at = NOW()
    """, (class_name, spec, ability_name, kind, username))


def get_benchmarks(encounter_id, difficulty):
    """Every spec's (and hero tree's) top players on one boss + difficulty."""
    return _run("""
        SELECT class, spec, hero, players FROM raid_benchmarks
        WHERE encounter_id = %s AND difficulty = %s AND status <> 'empty'
    """, (encounter_id, difficulty), fetch='all')


# ============================================================================
# Analytics (analytics.py): page views and "My performance" clicks
# ============================================================================

def record_analytics(kind, src=None, visitor=None, discord_id=None, discord_name=None, admin_user=None,
                     report_code=None, path=None):
    _run("""
        INSERT INTO raid_analytics (kind, src, visitor, discord_id, discord_name, admin_user, report_code, path)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (kind, src, visitor, discord_id, discord_name, admin_user, report_code, path))


def link_visitor(visitor, discord_id):
    """This browser is that Discord user's (they opened their own recap's link) - the latest link wins."""
    _run("""
        INSERT INTO raid_visitors (visitor, discord_id) VALUES (%s, %s)
        ON CONFLICT (visitor) DO UPDATE SET discord_id = EXCLUDED.discord_id, linked_at = NOW()
    """, (visitor, discord_id))


def prune_analytics(days):
    _run("DELETE FROM raid_analytics WHERE at < NOW() - make_interval(days => %s)", (days,))


def _since(days, column='a.at'):
    return (f' AND {column} >= NOW() - make_interval(days => %s)', [days]) if days else ('', [])


# Every row with who it was (the Discord user: clicked as them, or a view from a browser tied to them) and, for a
# night's page, that night's event (the event's channel says the team).
_ANALYTICS = """
    SELECT a.*, COALESCE(a.discord_id, v.discord_id) AS who, ev.event_id, ev.event_title, ev.event_channel_id,
           r.title AS report_title, r.start_time AS report_start
    FROM raid_analytics a
    LEFT JOIN raid_visitors v ON v.visitor = a.visitor
    LEFT JOIN raid_reports r ON r.code = a.report_code
""" + _EVENT_JOIN

_COUNTS = """
    COUNT(*) FILTER (WHERE kind = 'view') AS views,
    COUNT(DISTINCT visitor) FILTER (WHERE kind = 'view') AS visitors,
    COUNT(*) FILTER (WHERE kind = 'my_performance') AS my_performance,
    COUNT(DISTINCT discord_id) FILTER (WHERE kind = 'my_performance') AS my_performance_users,
    COUNT(*) FILTER (WHERE kind = 'view' AND src = 'full') AS full_analysis,
    COUNT(*) FILTER (WHERE kind = 'view' AND src = 'mine') AS own_analysis
"""


def analytics_totals(days):
    where, params = _since(days)
    return _run(f"SELECT {_COUNTS}, COUNT(DISTINCT who) AS discord_users FROM ({_ANALYTICS} WHERE TRUE {where}) x",
                params, fetch='one')


def analytics_daily(days):
    """[{'day', 'visitors', 'views'}] oldest first - days without a view left out."""
    where, params = _since(days)
    return _run(f"""
        SELECT date_trunc('day', at)::date AS day, COUNT(DISTINCT visitor) AS visitors, COUNT(*) AS views
        FROM raid_analytics a WHERE kind = 'view' {where}
        GROUP BY 1 ORDER BY 1
    """, params, fetch='all') or []


def analytics_nights(days):
    """Per raid night that had any: the counts, its title / date and event, newest night first."""
    where, params = _since(days)
    return _run(f"""
        SELECT report_code, MAX(report_title) AS title, MAX(report_start) AS start_time, MAX(event_id) AS event_id,
               MAX(event_title) AS event_title, MAX(event_channel_id) AS event_channel_id, {_COUNTS}
        FROM ({_ANALYTICS} WHERE a.report_code IS NOT NULL {where}) x
        GROUP BY report_code
        ORDER BY MAX(report_start) DESC NULLS LAST, report_code
    """, params, fetch='all') or []


def analytics_by_channel(days, team_channels):
    """
    The counts per group of pages: 'team' (one row per team channel), 'other' (events outside them - for fun),
    'no_event' (a night without an event), 'not_a_night' (the front page, boss and character pages).
    """
    where, params = _since(days)
    return _run(f"""
        SELECT bucket, channel_id, {_COUNTS} FROM (
            SELECT x.*, CASE WHEN report_code IS NULL THEN 'not_a_night' WHEN event_channel_id IS NULL THEN 'no_event'
                             WHEN event_channel_id = ANY(%s) THEN 'team' ELSE 'other' END AS bucket,
                        CASE WHEN event_channel_id = ANY(%s) THEN event_channel_id END AS channel_id
            FROM ({_ANALYTICS} WHERE TRUE {where}) x
        ) y
        GROUP BY bucket, channel_id
        ORDER BY bucket, channel_id
    """, [team_channels, team_channels] + params, fetch='all') or []


def analytics_users(days):
    """
    Per Discord user we know: their clicks, views and nights looked at, and their name (what Discord called them
    when they clicked, else their linked Battle.net connection's). Most active first.
    """
    where, params = _since(days)
    return _run(f"""
        SELECT who AS discord_id,
               COALESCE((SELECT a2.discord_name FROM raid_analytics a2 WHERE a2.discord_id = x.who
                         AND a2.discord_name IS NOT NULL ORDER BY a2.at DESC LIMIT 1),
                        (SELECT COALESCE(c.discord_display_name, c.discord_username) FROM wow_connections c
                         WHERE c.discord_id = x.who::text LIMIT 1)) AS name,
               {_COUNTS},
               COUNT(DISTINCT report_code) FILTER (WHERE kind = 'view') AS nights,
               MAX(at) AS last_seen,
               EXISTS (SELECT 1 FROM raid_visitors v2 WHERE v2.discord_id = x.who) AS linked
        FROM ({_ANALYTICS} WHERE TRUE {where}) x
        WHERE who IS NOT NULL
        GROUP BY who
        ORDER BY COUNT(*) FILTER (WHERE kind = 'my_performance') DESC, COUNT(*) DESC
    """, params, fetch='all') or []


def analytics_officers(days):
    """Views by officers logged in to the admin site (their admin login - not a Discord user): most first."""
    where, params = _since(days)
    return _run(f"""
        SELECT admin_user, COUNT(*) AS views, COUNT(DISTINCT report_code) AS nights, MAX(at) AS last_seen
        FROM raid_analytics a WHERE kind = 'view' AND admin_user IS NOT NULL {where}
        GROUP BY admin_user ORDER BY COUNT(*) DESC
    """, params, fetch='all') or []
