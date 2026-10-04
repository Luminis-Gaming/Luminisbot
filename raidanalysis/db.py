"""
Raid analysis database layer: schema + SQL helpers.

Schema is created idempotently by ensure_schema(), called from
run_migrations.py on every boot (migrations/012 is the documentation copy).
"""
import logging
import re

from psycopg2.extras import Json, RealDictCursor

from mythicplus.db import get_db_connection

from . import teams
from .analyzer import TAG_AVOIDABLE, TAG_AVOIDABLE_NON_TANK, TAG_IGNORE

logger = logging.getLogger(__name__)

TAGS = (TAG_AVOIDABLE, TAG_AVOIDABLE_NON_TANK, TAG_IGNORE)


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
    # Top parses per (boss, difficulty, spec) for the cooldown comparison (benchmarks.py)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS raid_benchmarks (
            encounter_id INTEGER NOT NULL,
            difficulty INTEGER NOT NULL,
            class TEXT NOT NULL,
            spec TEXT NOT NULL,
            metric TEXT,
            players JSONB NOT NULL DEFAULT '[]',
            status TEXT NOT NULL,
            error TEXT,
            fetched_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (encounter_id, difficulty, class, spec)
        );
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


def _run(sql, params=(), fetch=None):
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            result = None
            if fetch == 'one':
                result = cur.fetchone()
            elif fetch == 'all':
                result = cur.fetchall()
        conn.commit()
        return result
    finally:
        conn.close()


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
            zone_id = EXCLUDED.zone_id, zone_name = EXCLUDED.zone_name,
            phase_names = EXCLUDED.phase_names, synced_at = NOW()
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
    """, (code, version), fetch='all')
    return {r['fight_id'] for r in rows}


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

def benchmarks_needed(limit, refresh_days, difficulties, recent_days=30):
    """
    (boss, difficulty, class, spec) combos our raiders played in the last recent_days that have no
    benchmark yet, a stale one, or a failed one from over a day ago - most recently played first.
    """
    return _run("""
        SELECT c.* FROM (
            SELECT p.encounter_id, p.difficulty, x->>'class' AS class, x->>'spec' AS spec,
                   MAX(x->>'role') AS role, MAX(r.start_time + p.start_ms) AS last_played
            FROM raid_pulls p JOIN raid_reports r ON r.code = p.report_code,
                 jsonb_array_elements(COALESCE(p.analysis->'players', '[]'::jsonb)) x
            WHERE r.start_time > EXTRACT(EPOCH FROM NOW() - make_interval(days => %s)) * 1000
              AND p.difficulty = ANY(%s) AND COALESCE(x->>'spec', '') <> '' AND COALESCE(x->>'class', '') <> ''
            GROUP BY 1, 2, 3, 4
        ) c
        WHERE NOT EXISTS (
            SELECT 1 FROM raid_benchmarks b
            WHERE b.encounter_id = c.encounter_id AND b.difficulty = c.difficulty
              AND b.class = c.class AND b.spec = c.spec
              AND b.fetched_at > NOW() - CASE WHEN b.status = 'error' THEN INTERVAL '1 day'
                                              ELSE make_interval(days => %s) END
        )
        ORDER BY c.last_played DESC
        LIMIT %s
    """, (recent_days, list(difficulties), refresh_days, limit), fetch='all')


def save_benchmark(encounter_id, difficulty, class_name, spec, metric, players, status, error=None):
    """A failed refresh keeps the previous top players (only the status changes)."""
    _run("""
        INSERT INTO raid_benchmarks (encounter_id, difficulty, class, spec, metric, players, status, error, fetched_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (encounter_id, difficulty, class, spec) DO UPDATE SET metric = EXCLUDED.metric,
            players = CASE WHEN EXCLUDED.status = 'error' THEN raid_benchmarks.players ELSE EXCLUDED.players END,
            status = EXCLUDED.status, error = EXCLUDED.error, fetched_at = NOW()
    """, (encounter_id, difficulty, class_name, spec, metric, Json(players), status, error))


def get_benchmark(encounter_id, difficulty, class_name, spec):
    return _run("""
        SELECT * FROM raid_benchmarks WHERE encounter_id = %s AND difficulty = %s AND class = %s AND spec = %s
    """, (encounter_id, difficulty, class_name, spec), fetch='one')


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
