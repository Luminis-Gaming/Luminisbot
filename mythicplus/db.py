"""
Mythic+ database layer: schema + all SQL helpers.

Schema is created idempotently by ensure_schema(), called from
run_migrations.py on every boot (house convention — migrations/011 is the
documentation copy).
"""
import os
import logging

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def get_db_connection():
    """Create database connection (same env vars as raid_system)."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'postgres'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'luminisbot'),
        user=os.getenv('DB_USER', 'luminisbot'),
        password=os.getenv('DB_PASSWORD', 'changeme123')
    )


# ============================================================================
# SCHEMA
# ============================================================================

def ensure_schema(cursor):
    """Create Mythic+ tables. Runs inside run_migrations()'s transaction."""
    cursor.execute("""
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
            status TEXT NOT NULL DEFAULT 'open',
            created_by BIGINT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_mplus_events_status
        ON mplus_events(status, signup_deadline);
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mplus_signups (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES mplus_events(id) ON DELETE CASCADE,
            discord_id TEXT NOT NULL,
            character_name TEXT NOT NULL,
            realm_slug TEXT NOT NULL,
            character_class TEXT NOT NULL,
            role TEXT NOT NULL,
            armor_type TEXT NOT NULL,
            signed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            UNIQUE(event_id, discord_id, character_name, realm_slug, role)
        );
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_mplus_signups_event
        ON mplus_signups(event_id);
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mplus_groups (
            id SERIAL PRIMARY KEY,
            event_id INTEGER NOT NULL REFERENCES mplus_events(id) ON DELETE CASCADE,
            group_number INTEGER NOT NULL,
            armor_type TEXT,
            UNIQUE(event_id, group_number)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mplus_group_members (
            group_id INTEGER NOT NULL REFERENCES mplus_groups(id) ON DELETE CASCADE,
            signup_id INTEGER NOT NULL REFERENCES mplus_signups(id) ON DELETE CASCADE,
            assigned_role TEXT NOT NULL,
            PRIMARY KEY (group_id, signup_id)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mplus_alternates (
            event_id INTEGER NOT NULL REFERENCES mplus_events(id) ON DELETE CASCADE,
            discord_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            reason TEXT NOT NULL,
            PRIMARY KEY (event_id, discord_id)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mplus_grace_points (
            guild_id BIGINT NOT NULL,
            discord_id TEXT NOT NULL,
            points INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (guild_id, discord_id)
        );
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mplus_grace_log (
            id SERIAL PRIMARY KEY,
            guild_id BIGINT NOT NULL,
            discord_id TEXT NOT NULL,
            event_id INTEGER,
            delta INTEGER NOT NULL,
            reason TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
    """)

    for table in ('mplus_events', 'mplus_signups', 'mplus_groups',
                  'mplus_group_members', 'mplus_alternates',
                  'mplus_grace_points', 'mplus_grace_log'):
        cursor.execute(f"GRANT ALL PRIVILEGES ON TABLE {table} TO luminisbot;")


# ============================================================================
# EVENTS
# ============================================================================

def create_event(guild_id, channel_id, message_id, title, event_date,
                 event_time, key_level_min, key_level_max, created_by,
                 signup_deadline=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO mplus_events (guild_id, channel_id, message_id, title,
            event_date, event_time, key_level_min, key_level_max,
            created_by, signup_deadline)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (guild_id, channel_id, message_id, title, event_date, event_time,
          key_level_min, key_level_max, created_by, signup_deadline))
    event_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return event_id


def get_event(event_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM mplus_events WHERE id = %s", (event_id,))
    event = cursor.fetchone()
    cursor.close()
    conn.close()
    return event


def get_event_by_message(message_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM mplus_events WHERE message_id = %s", (message_id,))
    event = cursor.fetchone()
    cursor.close()
    conn.close()
    return event


def set_event_status(event_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE mplus_events SET status = %s WHERE id = %s",
                   (status, event_id))
    conn.commit()
    cursor.close()
    conn.close()


# ============================================================================
# SIGNUPS
# ============================================================================

def add_signup(event_id, discord_id, character_name, realm_slug,
               character_class, role, armor_type):
    """UPSERT one (character, role) offering. Returns False if signups closed."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Guard inside the write: the unattended finalize pipeline may close the
    # event between the button click and this insert
    cursor.execute("SELECT status FROM mplus_events WHERE id = %s FOR UPDATE",
                   (event_id,))
    row = cursor.fetchone()
    if not row or row[0] != 'open':
        conn.rollback()
        cursor.close()
        conn.close()
        return False
    cursor.execute("""
        INSERT INTO mplus_signups (event_id, discord_id, character_name,
            realm_slug, character_class, role, armor_type)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (event_id, discord_id, character_name, realm_slug, role)
        DO NOTHING
    """, (event_id, discord_id, character_name, realm_slug, character_class,
          role, armor_type))
    conn.commit()
    cursor.close()
    conn.close()
    return True


def remove_signup(signup_id, discord_id):
    """Remove one offering; discord_id guards against removing others' rows."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM mplus_signups WHERE id = %s AND discord_id = %s",
                   (signup_id, discord_id))
    conn.commit()
    cursor.close()
    conn.close()


def remove_all_signups(event_id, discord_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM mplus_signups WHERE event_id = %s AND discord_id = %s",
                   (event_id, discord_id))
    conn.commit()
    cursor.close()
    conn.close()


def get_user_signups(event_id, discord_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT * FROM mplus_signups
        WHERE event_id = %s AND discord_id = %s
        ORDER BY character_name, role
    """, (event_id, discord_id))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_signup_rows(event_id):
    """All signups for matchmaking: role-specific RIO score + grace points.

    Score preference: role-specific score → overall score → 0. A missing
    score never disqualifies anyone (plan §5).
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT s.id AS signup_id, s.discord_id, s.character_name, s.realm_slug,
               s.character_class, s.role, s.armor_type, s.signed_at,
               COALESCE(
                   CASE s.role
                       WHEN 'tank' THEN wc.mythic_plus_score_tank
                       WHEN 'healer' THEN wc.mythic_plus_score_healer
                       ELSE wc.mythic_plus_score_dps
                   END,
                   wc.mythic_plus_score, 0) AS score,
               COALESCE(gp.points, 0) AS grace_points
        FROM mplus_signups s
        JOIN mplus_events e ON e.id = s.event_id
        LEFT JOIN wow_characters wc
            ON wc.discord_id = s.discord_id
            AND wc.character_name = s.character_name
            AND wc.realm_slug = s.realm_slug
        LEFT JOIN mplus_grace_points gp
            ON gp.guild_id = e.guild_id AND gp.discord_id = s.discord_id
        WHERE s.event_id = %s
        ORDER BY s.signed_at
    """, (event_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_signup_summary(event_id):
    """Distinct characters with their offered roles, for the event embed."""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT discord_id, character_name, realm_slug, character_class,
               armor_type, array_agg(role ORDER BY role) AS roles
        FROM mplus_signups
        WHERE event_id = %s
        GROUP BY discord_id, character_name, realm_slug, character_class, armor_type
        ORDER BY armor_type, character_name
    """, (event_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ============================================================================
# ROSTER PERSISTENCE
# ============================================================================

def save_roster(event_id, roster, reasons_by_id):
    """Persist groups + alternates and mark the event finalized. Atomic."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM mplus_groups WHERE event_id = %s", (event_id,))
        cursor.execute("DELETE FROM mplus_alternates WHERE event_id = %s", (event_id,))

        for number, group in enumerate(roster.groups, start=1):
            cursor.execute("""
                INSERT INTO mplus_groups (event_id, group_number, armor_type)
                VALUES (%s, %s, %s) RETURNING id
            """, (event_id, number, group.modal_armor()))
            group_id = cursor.fetchone()[0]
            for slot in group.slots:
                cursor.execute("""
                    INSERT INTO mplus_group_members (group_id, signup_id, assigned_role)
                    VALUES (%s, %s, %s)
                """, (group_id, slot.option.signup_id, slot.role))

        for rank, person in enumerate(roster.benched, start=1):
            cursor.execute("""
                INSERT INTO mplus_alternates (event_id, discord_id, rank, reason)
                VALUES (%s, %s, %s, %s)
            """, (event_id, person.discord_id, rank,
                  reasons_by_id.get(person.discord_id, 'composition')))

        cursor.execute("UPDATE mplus_events SET status = 'finalized' WHERE id = %s",
                       (event_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()


def get_roster(event_id):
    """Groups with member details, for embeds/DMs. Returns list of dicts."""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT g.group_number, g.armor_type AS group_armor,
               m.assigned_role, s.discord_id, s.character_name, s.realm_slug,
               s.character_class, s.armor_type,
               COALESCE(wc.realm_name, s.realm_slug) AS realm_name
        FROM mplus_groups g
        JOIN mplus_group_members m ON m.group_id = g.id
        JOIN mplus_signups s ON s.id = m.signup_id
        LEFT JOIN wow_characters wc
            ON wc.discord_id = s.discord_id
            AND wc.character_name = s.character_name
            AND wc.realm_slug = s.realm_slug
        WHERE g.event_id = %s
        ORDER BY g.group_number,
                 CASE m.assigned_role WHEN 'tank' THEN 0 WHEN 'healer' THEN 1 ELSE 2 END,
                 s.character_name
    """, (event_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    groups = {}
    for r in rows:
        groups.setdefault(r['group_number'], {
            'group_number': r['group_number'],
            'armor_type': r['group_armor'],
            'members': [],
        })['members'].append(r)
    return [groups[n] for n in sorted(groups)]


def get_alternates(event_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT discord_id, rank, reason FROM mplus_alternates
        WHERE event_id = %s ORDER BY rank
    """, (event_id,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


# ============================================================================
# GRACE POINTS
# ============================================================================

def get_grace_points(guild_id, discord_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT points FROM mplus_grace_points
        WHERE guild_id = %s AND discord_id = %s
    """, (guild_id, discord_id))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else 0


def apply_grace_changes(guild_id, event_id, changes):
    """Apply GraceChanges from matchmaking atomically, with audit log."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        for discord_id in changes.awards:
            cursor.execute("""
                INSERT INTO mplus_grace_points (guild_id, discord_id, points)
                VALUES (%s, %s, 1)
                ON CONFLICT (guild_id, discord_id)
                DO UPDATE SET points = mplus_grace_points.points + 1,
                              updated_at = NOW()
            """, (guild_id, discord_id))
            cursor.execute("""
                INSERT INTO mplus_grace_log (guild_id, discord_id, event_id, delta, reason)
                VALUES (%s, %s, %s, 1, 'benched by the draw despite matching armor/role')
            """, (guild_id, discord_id, event_id))

        for discord_id in changes.resets:
            cursor.execute("""
                UPDATE mplus_grace_points SET points = 0, updated_at = NOW()
                WHERE guild_id = %s AND discord_id = %s AND points > 0
                RETURNING points
            """, (guild_id, discord_id))
            cursor.execute("""
                INSERT INTO mplus_grace_log (guild_id, discord_id, event_id, delta, reason)
                VALUES (%s, %s, %s, 0, 'placed in a group - priority spent')
            """, (guild_id, discord_id, event_id))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
