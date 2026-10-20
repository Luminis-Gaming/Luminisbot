"""
Auction house tables. Created idempotently by ensure_schema(), called from run_migrations.py on every boot
(house convention).

Sizes, measured on EU (October 2026): ~3.1M listings across 92 realm groups at any time (ah_listings, replaced per
realm as Blizzard updates it), ~19k different items, ~200k rolls. History stays small on purpose:
  ah_item_history   one row per item per hour for 14 days, then one per day (the noon row), kept for good
  ah_realm_history  each realm's cheapest price per item per day, for 60 days
"""
import io
import logging
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

HOURLY_DAYS = 14
REALM_HISTORY_DAYS = 60


def ensure_schema(cursor):
    """Create the auction house tables. Runs inside run_migrations()'s transaction."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ah_meta (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS ah_realm_groups (
            cr INTEGER PRIMARY KEY,
            names TEXT[] NOT NULL,
            locale TEXT,
            population TEXT,
            last_modified TEXT,
            swept_at TIMESTAMP WITH TIME ZONE,
            listings INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS ah_items (
            item_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            quality SMALLINT NOT NULL DEFAULT 1,
            ilvl SMALLINT NOT NULL DEFAULT 0,
            req_level SMALLINT NOT NULL DEFAULT 0,
            class_id SMALLINT NOT NULL DEFAULT -1,
            subclass_id SMALLINT NOT NULL DEFAULT -1,
            inventory_type SMALLINT NOT NULL DEFAULT 0,
            expansion SMALLINT NOT NULL DEFAULT 0,
            vendor BIGINT NOT NULL DEFAULT 0,
            binding SMALLINT NOT NULL DEFAULT 0,
            icon_file INTEGER NOT NULL DEFAULT 0,
            icon TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_ah_items_name ON ah_items (lower(name));

        CREATE TABLE IF NOT EXISTS ah_item_classes (
            class_id SMALLINT NOT NULL,
            subclass_id SMALLINT NOT NULL,
            class_name TEXT NOT NULL,
            subclass_name TEXT NOT NULL,
            PRIMARY KEY (class_id, subclass_id)
        );

        CREATE TABLE IF NOT EXISTS ah_bonus (
            bonus_id INTEGER PRIMARY KEY,
            effects JSONB NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ah_curve_levels (
            curve INTEGER PRIMARY KEY,
            ilvl SMALLINT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ah_variants (
            variant_id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            roll_key TEXT NOT NULL,
            sec TEXT NOT NULL DEFAULT '',
            heavy TEXT NOT NULL DEFAULT '',
            ter TEXT NOT NULL DEFAULT '',
            sock SMALLINT NOT NULL DEFAULT 0,
            curve INTEGER NOT NULL DEFAULT 0,
            ilvl SMALLINT NOT NULL DEFAULT 0,
            bind SMALLINT NOT NULL DEFAULT 0,
            tooltip TEXT NOT NULL DEFAULT '',
            UNIQUE (item_id, roll_key)
        );
        CREATE INDEX IF NOT EXISTS idx_ah_variants_curve ON ah_variants (curve) WHERE curve <> 0;

        CREATE UNLOGGED TABLE IF NOT EXISTS ah_listings (
            cr INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            variant_id INTEGER NOT NULL,
            buyout BIGINT NOT NULL,
            time_left SMALLINT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ah_listings_cr ON ah_listings (cr);
        CREATE INDEX IF NOT EXISTS idx_ah_listings_item ON ah_listings (item_id);
        CREATE INDEX IF NOT EXISTS idx_ah_listings_variant ON ah_listings (variant_id);

        CREATE TABLE IF NOT EXISTS ah_walls (
            item_id INTEGER NOT NULL,
            price BIGINT NOT NULL,
            seen INTEGER NOT NULL,
            PRIMARY KEY (item_id, price)
        );

        CREATE TABLE IF NOT EXISTS ah_item_summary (
            item_id INTEGER PRIMARY KEY,
            realms SMALLINT NOT NULL,
            listings INTEGER NOT NULL,
            lo BIGINT NOT NULL, lo_cr INTEGER NOT NULL,
            p25 BIGINT NOT NULL, med BIGINT NOT NULL, p75 BIGINT NOT NULL,
            hi BIGINT NOT NULL, hi_cr INTEGER NOT NULL,
            flagged SMALLINT NOT NULL DEFAULT 0,
            walls_only BOOLEAN NOT NULL DEFAULT FALSE,
            rolls SMALLINT NOT NULL DEFAULT 1,
            ilvl_min SMALLINT NOT NULL DEFAULT 0, ilvl_max SMALLINT NOT NULL DEFAULT 0,
            typical BIGINT,
            gap BIGINT, gap_variant INTEGER, gap_buy_cr INTEGER, gap_buy BIGINT, gap_sell_cr INTEGER, gap_sell BIGINT
        );

        CREATE TABLE IF NOT EXISTS ah_item_history (
            item_id INTEGER NOT NULL,
            ts TIMESTAMP WITH TIME ZONE NOT NULL,
            lo BIGINT NOT NULL, p25 BIGINT NOT NULL, med BIGINT NOT NULL, p75 BIGINT NOT NULL,
            realms SMALLINT NOT NULL, listings INTEGER NOT NULL,
            PRIMARY KEY (item_id, ts)
        );

        CREATE TABLE IF NOT EXISTS ah_realm_history (
            item_id INTEGER NOT NULL,
            cr INTEGER NOT NULL,
            day DATE NOT NULL,
            lo BIGINT NOT NULL,
            listings INTEGER NOT NULL,
            PRIMARY KEY (item_id, cr, day)
        );

        -- columns added after the first version
        ALTER TABLE ah_variants ADD COLUMN IF NOT EXISTS bind SMALLINT NOT NULL DEFAULT 0;
        ALTER TABLE ah_item_summary ADD COLUMN IF NOT EXISTS walls_only BOOLEAN NOT NULL DEFAULT FALSE;
    """)


# ============================================================================
# Helpers
# ============================================================================

def get_db_connection():
    """A new connection (the same settings as the bot's; the worker container gets them too)."""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'postgres'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'luminisbot'),
        user=os.getenv('DB_USER', 'luminisbot'),
        password=os.getenv('DB_PASSWORD', 'changeme123'))


@contextmanager
def transaction(dict_rows=False):
    """A cursor in its own connection: committed when the block ends (rolled back on an error), then closed."""
    conn = get_db_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor if dict_rows else None) as cur:
            yield cur
    finally:
        conn.close()


def get_meta(key):
    with transaction() as cur:
        cur.execute('SELECT value, updated_at FROM ah_meta WHERE key = %s', (key,))
        return cur.fetchone()


def set_meta(key, value):
    with transaction() as cur:
        cur.execute("""INSERT INTO ah_meta (key, value, updated_at) VALUES (%s, %s, NOW())
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""", (key, value))


def _copy_value(v):
    if v is None:
        return '\\N'
    return str(v).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')


def copy_rows(cur, table, columns, rows):
    """COPY rows (tuples of plain values) into a table."""
    buf = io.StringIO()
    for row in rows:
        buf.write('\t'.join(_copy_value(v) for v in row))
        buf.write('\n')
    buf.seek(0)
    cur.copy_from(buf, table, columns=columns)


def fetch_all(sql, params=()):
    with transaction(dict_rows=True) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fetch_one(sql, params=()):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def realm_groups():
    return fetch_all('SELECT cr, names, locale, population, last_modified, swept_at, listings FROM ah_realm_groups ORDER BY cr')


def snapshot():
    """What the pages say about the data: when it was last updated, how many realms, listings and items."""
    row = fetch_one("""SELECT max(swept_at) AS swept_at, count(*) FILTER (WHERE swept_at IS NOT NULL) AS groups,
                              coalesce(sum(listings), 0) AS listings,
                              (SELECT count(*) FROM ah_item_summary) AS items,
                              (SELECT min(ts) FROM ah_item_history) AS history_since
                       FROM ah_realm_groups""")
    return row or {}


def prune_history():
    """Hourly rows past HOURLY_DAYS become one per day (the noon one); realm history past REALM_HISTORY_DAYS goes."""
    with transaction() as cur:
        cur.execute(f"""DELETE FROM ah_item_history
                        WHERE ts < NOW() - INTERVAL '{HOURLY_DAYS} days'
                          AND EXTRACT(HOUR FROM ts AT TIME ZONE 'UTC') <> 12""")
        cur.execute(f"DELETE FROM ah_realm_history WHERE day < CURRENT_DATE - {REALM_HISTORY_DAYS}")
