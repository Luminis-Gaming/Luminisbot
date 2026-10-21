"""
The collector: every EU auction house, as Blizzard updates it (about once an hour each, at its own time).

Every CHECK_MINUTES (run by worker.py, in its own container) it asks each of the 92 realm groups for its auctions with
If-Modified-Since - an unchanged one costs a 304 - and for each new dump:
  1. parses it (~25 MB of JSON for the biggest) and decodes every listing's roll (rolls.py),
  2. replaces that realm's rows in ah_listings, adds any roll it hasn't seen to ah_variants,
  3. keeps the realm's cheapest price per item for the day (ah_realm_history).
Then, when anything changed, summarize() recomputes every item's EU numbers - price walls, cheapest, median,
highest, the best same-roll gap (prices.py) - into ah_item_summary and this hour's ah_item_history row.

Battle pets are in the realm dumps as cages; each species is stored as an item of its own (rolls.decode_pet).
Commodities - herbs, ore, flasks and other stackable goods - sell on one auction house for the whole region: its
dump (process_commodities) becomes each item's price ladder, summary and hourly history.

Parsing and the database run in a worker thread, one dump at a time, so nothing else waits on them.
Afterwards a few lookups fill gaps, rate limited: item levels of new level curves (one Wowhead tooltip per curve,
ever), icons the game tables lack, items newer than them, and battle pet species' names, families and icons
(Blizzard).
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import aiohttp
import orjson
from psycopg2.extras import execute_values

from . import blizzard, db, gamedata, prices, rolls

logger = logging.getLogger(__name__)

CONCURRENCY = 4              # dumps downloading at once (stored one at a time)
REALM_INDEX_HOURS = 24
LEVELS_PER_RUN = 200         # new level curves looked up per run (Wowhead, 2 a second), most listed first
ICONS_PER_RUN = 6000         # all of a fresh install's ~4,300 in one run (Blizzard allows 100 requests a second)
ITEMS_PER_RUN = 1000
PETS_PER_RUN = 3000          # every species on sale in one run (~2,200 exist)
LOOKUPS_AT_ONCE = 8
TIME_LEFT = {'SHORT': 0, 'MEDIUM': 1, 'LONG': 2, 'VERY_LONG': 3}
QUALITY = {'POOR': 0, 'COMMON': 1, 'UNCOMMON': 2, 'RARE': 3, 'EPIC': 4, 'LEGENDARY': 5, 'ARTIFACT': 6, 'HEIRLOOM': 7}

status = {'running': False, 'last_run': None, 'last_changed': 0, 'last_error': None, 'seconds': None}
_lock = asyncio.Lock()


class Context:
    """What decoding needs, loaded once per run: bonus effects, item levels, level curves, known rolls."""

    def __init__(self):
        with db.transaction() as cur:
            cur.execute('SELECT bonus_id, effects FROM ah_bonus')
            self.bonus = {b: [tuple(e) for e in effects] for b, effects in cur}
            cur.execute('SELECT item_id, ilvl FROM ah_items')
            self.base = dict(cur)
            cur.execute('SELECT curve, ilvl FROM ah_curve_levels')
            self.curves = dict(cur)
            cur.execute('SELECT item_id, roll_key, variant_id FROM ah_variants')
            self.variants = {(i, k): v for i, k, v in cur}
        self.decoded = {}

    def roll(self, item):
        if 'pet_species_id' in item:
            key = ('pet', item.get('pet_breed_id'), item.get('pet_level'), item.get('pet_quality_id'))
            roll = self.decoded.get(key)
            if roll is None:
                roll = self.decoded[key] = rolls.decode_pet(item)
            return roll
        key = (tuple(item.get('bonus_lists') or ()),
               tuple(sorted((m.get('type'), m.get('value')) for m in item.get('modifiers') or ())))
        roll = self.decoded.get(key)
        if roll is None:
            roll = self.decoded[key] = rolls.decode(item, self.bonus)
        return roll


# ============================================================================
# One realm
# ============================================================================

def process_realm(cr, body, last_modified, ctx):
    """Parse one realm's dump and store it. Runs in a worker thread. Returns how many listings it kept."""
    data = orjson.loads(body)
    del body
    listings, new = [], {}
    for a in data.get('auctions', ()):
        item = a.get('item') or {}
        buyout = a.get('buyout')
        if not buyout:  # bids only
            continue
        # a pet cage is one item id for every pet: the species is the item
        item_id = rolls.pet_item_id(item['pet_species_id']) if 'pet_species_id' in item else item.get('id')
        roll = ctx.roll(item)
        key = (item_id, roll.key)
        if key not in ctx.variants and key not in new:
            new[key] = roll
        listings.append((item_id, key, buyout // max(1, a.get('quantity') or 1), TIME_LEFT.get(a.get('time_left'), 3)))
    del data

    with db.transaction() as cur:
        if new:
            execute_values(cur, """INSERT INTO ah_variants (item_id, roll_key, sec, heavy, ter, sock, curve, ilvl, bind, tooltip)
                                   VALUES %s ON CONFLICT (item_id, roll_key) DO NOTHING""",
                           [(i, k, r.sec, r.heavy, r.ter, r.sock, r.curve,
                             rolls.item_level(r, ctx.base.get(i), ctx.curves), r.bind,
                             r.tooltip or rolls.tooltip_query(r.bonus, r.crafted))
                            for (i, k), r in new.items()], page_size=1000)
            found = execute_values(cur, """SELECT v.item_id, v.roll_key, v.variant_id FROM ah_variants v
                                           JOIN (VALUES %s) AS n (item_id, roll_key) USING (item_id, roll_key)""",
                                   list(new), page_size=5000, fetch=True)
            for i, k, v in found:
                ctx.variants[(i, k)] = v
        rows = [(cr, item_id, ctx.variants[key], price, tl) for item_id, key, price, tl in listings
                if key in ctx.variants]
        cur.execute('DELETE FROM ah_listings WHERE cr = %s', (cr,))
        db.copy_rows(cur, 'ah_listings', ('cr', 'item_id', 'variant_id', 'buyout', 'time_left'), rows)
        cur.execute("""INSERT INTO ah_realm_history (item_id, cr, day, lo, listings)
                       SELECT item_id, cr, CURRENT_DATE, min(buyout), count(*) FROM ah_listings WHERE cr = %s
                       GROUP BY item_id, cr
                       ON CONFLICT (item_id, cr, day) DO UPDATE
                       SET lo = LEAST(ah_realm_history.lo, EXCLUDED.lo), listings = EXCLUDED.listings""", (cr,))
        cur.execute('UPDATE ah_realm_groups SET last_modified = %s, swept_at = NOW(), listings = %s WHERE cr = %s',
                    (last_modified, len(rows), cr))
    return len(rows)


# ============================================================================
# Commodities: one auction house for the whole region
# ============================================================================

def process_commodities(body, last_modified):
    """
    Parse the region's commodity dump (~30 MB) into each item's price ladder and numbers, and this hour's history
    row. Runs in a worker thread. Returns how many items are on sale.
    """
    data = orjson.loads(body)
    del body
    book, listings = {}, {}
    for a in data.get('auctions', ()):
        item_id = (a.get('item') or {}).get('id')
        price, quantity = a.get('unit_price'), a.get('quantity') or 0
        if not item_id or not price or quantity <= 0:
            continue
        key = (item_id, price)
        book[key] = book.get(key, 0) + quantity
        listings[item_id] = listings.get(item_id, 0) + 1
    del data
    ladders = {}
    for (item_id, price), quantity in book.items():
        ladders.setdefault(item_id, []).append((price, quantity))
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()
    book_rows, summaries, history = [], [], []
    for item_id, levels in ladders.items():
        levels.sort()
        book_rows.extend((item_id, p, q) for p, q in levels)
        s = prices.commodity_stats(levels)
        if not s:
            continue
        summaries.append((item_id, s['lo'], s['p05'], s['market'], s['p30'], s['quantity'], listings[item_id], s['levels']))
        history.append((item_id, hour, s['lo'], s['p05'], s['market'], s['p30'], 0, min(s['quantity'], 2_000_000_000)))
    with db.transaction() as cur:
        cur.execute('DELETE FROM ah_commodity_book')
        db.copy_rows(cur, 'ah_commodity_book', ('item_id', 'price', 'quantity'), book_rows)
        cur.execute('DELETE FROM ah_commodity_summary')
        db.copy_rows(cur, 'ah_commodity_summary', ('item_id', 'lo', 'p05', 'market', 'p30', 'quantity', 'listings', 'levels'),
                     summaries)
        cur.execute('CREATE TEMP TABLE ah_history_new (LIKE ah_item_history) ON COMMIT DROP')
        db.copy_rows(cur, 'ah_history_new', ('item_id', 'ts', 'lo', 'p25', 'med', 'p75', 'realms', 'listings'), history)
        cur.execute("""INSERT INTO ah_item_history SELECT * FROM ah_history_new
                       ON CONFLICT (item_id, ts) DO UPDATE SET lo = EXCLUDED.lo, p25 = EXCLUDED.p25,
                           med = EXCLUDED.med, p75 = EXCLUDED.p75, realms = EXCLUDED.realms,
                           listings = EXCLUDED.listings""")
    db.set_meta('commodities', last_modified or '')
    return len(summaries)


# ============================================================================
# Every item's numbers
# ============================================================================

def summarize():
    """Recompute every item's EU numbers from the current listings. Runs in a worker thread."""
    started = time.monotonic()
    summaries, walls_out, history = [], [], []
    hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    def finish(item_id, cells, levels):
        if not cells:
            return
        walls = prices.find_walls([lo for _, _, lo, _ in cells])
        cheapest = {}
        for vid, cr, lo, n in cells:
            c = cheapest.get(cr)
            cheapest[cr] = (min(c[0], lo), c[1] + n) if c else (lo, n)
        ref = prices.typical_price([lo for lo, _ in cheapest.values()], walls)
        s = prices.stats([(cr, lo, n) for cr, (lo, n) in cheapest.items()], walls, ref)
        by_variant = {}
        for vid, cr, lo, n in cells:
            by_variant.setdefault(vid, []).append((cr, lo, n))
        gap = None
        for vid, rows in by_variant.items():
            if len(rows) < prices.GAP_MIN_REALMS:
                continue
            vs = prices.stats(rows, walls, ref)
            if vs and not vs['fell_back'] and vs['sane'] >= prices.GAP_MIN_REALMS and vs['gain'] > 0 and (not gap or vs['gain'] > gap[1]['gain']):
                gap = (vid, vs)
        ilvls = [levels.get(v, 0) for v in by_variant]
        summaries.append((item_id, s['realms'], s['listings'], s['lo'], s['lo_realm'], s['p25'], s['med'], s['p75'],
                          s['hi'], s['hi_realm'], s['flagged'], s['fell_back'], len(by_variant), min(ilvls), max(ilvls),
                          round(ref) if ref else None,
                          gap[1]['gain'] if gap else None, gap[0] if gap else None,
                          gap[1]['lo_realm'] if gap else None, gap[1]['lo'] if gap else None,
                          gap[1]['target_realm'] if gap else None, gap[1]['target'] if gap else None))
        walls_out.extend((item_id, p, c) for p, c in walls.items())
        history.append((item_id, hour.isoformat(), s['lo'], s['p25'], s['med'], s['p75'], s['realms'], s['listings']))

    conn = db.get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT variant_id, ilvl FROM ah_variants')
            levels = dict(cur)
        with conn.cursor(name='ah_cells') as cur:  # server side: ~1.4M rows, streamed
            cur.itersize = 50000
            cur.execute("""SELECT item_id, variant_id, cr, min(buyout), count(*) FROM ah_listings
                           GROUP BY item_id, variant_id, cr ORDER BY item_id""")
            current, cells = None, []
            for item_id, vid, cr, lo, n in cur:
                if item_id != current:
                    finish(current, cells, levels)
                    current, cells = item_id, []
                cells.append((vid, cr, lo, n))
            finish(current, cells, levels)
        conn.commit()
    finally:
        conn.close()

    with db.transaction() as cur:
        cur.execute('DELETE FROM ah_item_summary')
        db.copy_rows(cur, 'ah_item_summary', (
            'item_id', 'realms', 'listings', 'lo', 'lo_cr', 'p25', 'med', 'p75', 'hi', 'hi_cr', 'flagged', 'walls_only', 'rolls',
            'ilvl_min', 'ilvl_max', 'typical', 'gap', 'gap_variant', 'gap_buy_cr', 'gap_buy', 'gap_sell_cr',
            'gap_sell'), summaries)
        cur.execute('DELETE FROM ah_walls')
        db.copy_rows(cur, 'ah_walls', ('item_id', 'price', 'seen'), walls_out)
        cur.execute('CREATE TEMP TABLE ah_history_new (LIKE ah_item_history) ON COMMIT DROP')
        db.copy_rows(cur, 'ah_history_new', ('item_id', 'ts', 'lo', 'p25', 'med', 'p75', 'realms', 'listings'), history)
        cur.execute("""INSERT INTO ah_item_history SELECT * FROM ah_history_new
                       ON CONFLICT (item_id, ts) DO UPDATE SET lo = EXCLUDED.lo, p25 = EXCLUDED.p25,
                           med = EXCLUDED.med, p75 = EXCLUDED.p75, realms = EXCLUDED.realms,
                           listings = EXCLUDED.listings""")
    logger.info(f'[AH] Summarized {len(summaries)} items ({len(walls_out)} wall prices) '
                f'in {time.monotonic() - started:.1f}s')


# ============================================================================
# Realm list and gap filling
# ============================================================================

def _realms_stale():
    row = db.get_meta('realms')
    return not row or row[1] < datetime.now(timezone.utc) - timedelta(hours=REALM_INDEX_HOURS)


async def refresh_realms(bz):
    status_, body, _ = await bz.get('/data/wow/connected-realm/index', blizzard.DYNAMIC)
    if status_ != 200:
        raise RuntimeError(f'connected realm index: HTTP {status_}')
    ids = [int(c['href'].split('/connected-realm/')[1].split('?')[0]) for c in orjson.loads(body)['connected_realms']]
    sem = asyncio.Semaphore(8)

    async def one(cr):
        async with sem:
            st, b, _ = await bz.get(f'/data/wow/connected-realm/{cr}', blizzard.DYNAMIC)
        if st != 200:
            return None
        d = orjson.loads(b)
        realms = d.get('realms') or []
        names = sorted((r.get('name') or r.get('slug') or '?' for r in realms), key=str.lower)
        locale = ((realms[0].get('locale') or '')[:2].lower()) if realms else ''
        return cr, names, locale, (d.get('population') or {}).get('type')

    groups = [g for g in await asyncio.gather(*(one(cr) for cr in ids)) if g]

    def store():
        with db.transaction() as cur:
            execute_values(cur, """INSERT INTO ah_realm_groups (cr, names, locale, population) VALUES %s
                                   ON CONFLICT (cr) DO UPDATE SET names = EXCLUDED.names, locale = EXCLUDED.locale,
                                       population = EXCLUDED.population""", groups)
            cur.execute('DELETE FROM ah_realm_groups WHERE NOT (cr = ANY(%s))', ([g[0] for g in groups],))
            cur.execute('DELETE FROM ah_listings WHERE NOT (cr = ANY(%s))', ([g[0] for g in groups],))
        db.set_meta('realms', str(len(groups)))
    await asyncio.to_thread(store)
    logger.info(f'[AH] {len(groups)} EU realm groups')


ILVL_RE = re.compile(r'Item Level (?:<!--ilvl-->)?(\d+)')


async def resolve_levels(session):
    """
    Item levels for level curves we haven't seen: one Wowhead tooltip per curve (the most listed first), then every
    roll with it. A curve Wowhead can't answer is kept as 0 (unknown: its rolls show the item's own level).
    """
    from raidanalysis.items import HEADERS, TOOLTIP_URL
    todo = await asyncio.to_thread(db.fetch_all, f"""
        SELECT v.curve, (array_agg(v.item_id ORDER BY c.n DESC))[1] AS item_id,
               (array_agg(v.tooltip ORDER BY c.n DESC))[1] AS tooltip
        FROM ah_variants v JOIN (SELECT variant_id, count(*) AS n FROM ah_listings GROUP BY variant_id) c USING (variant_id)
        WHERE v.curve <> 0 AND v.curve NOT IN (SELECT curve FROM ah_curve_levels)
        GROUP BY v.curve ORDER BY sum(c.n) DESC LIMIT {LEVELS_PER_RUN}""")
    found = []
    for row in todo:
        params = {'dataEnv': 1, 'locale': 0}
        params.update(part.split('=', 1) for part in row['tooltip'].split('&') if '=' in part)
        try:
            async with session.get(TOOLTIP_URL.format(id=row['item_id']), params=params, headers=HEADERS) as resp:
                data = await resp.json(content_type=None) if resp.status == 200 else None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            data = None
        if data is None:
            await asyncio.sleep(0.5)
            continue  # Wowhead didn't answer: try again next run
        m = ILVL_RE.search(data.get('tooltip') or '')
        found.append((row['curve'], int(m.group(1)) if m else 0))
        await asyncio.sleep(0.5)
    if found:
        def store():
            with db.transaction() as cur:
                execute_values(cur, 'INSERT INTO ah_curve_levels (curve, ilvl) VALUES %s ON CONFLICT DO NOTHING', found)
                cur.execute("""UPDATE ah_variants v SET ilvl = c.ilvl FROM ah_curve_levels c
                               WHERE v.curve = c.curve AND c.ilvl > 0 AND v.ilvl <> c.ilvl""")
        await asyncio.to_thread(store)
        logger.info(f'[AH] Item levels for {len(found)} new level curves')
    return len(found)


async def resolve_icons(bz):
    """Icons for items on sale that the game tables give none (Blizzard's media endpoint)."""
    todo = await asyncio.to_thread(db.fetch_all, f"""
        SELECT i.item_id FROM ah_items i
        JOIN (SELECT item_id FROM ah_item_summary UNION SELECT item_id FROM ah_commodity_summary) s USING (item_id)
        WHERE i.item_id > 0 AND i.icon_file = 0 AND i.icon IS NULL LIMIT {ICONS_PER_RUN}""")
    sem = asyncio.Semaphore(LOOKUPS_AT_ONCE)

    async def one(item_id):
        async with sem:
            st, body, _ = await bz.get(f'/data/wow/media/item/{item_id}', blizzard.STATIC)
        icon = ''
        if st == 200:
            assets = orjson.loads(body).get('assets') or []
            icon = next((a.get('value') for a in assets if a.get('key') == 'icon'), '') or ''
        return icon if icon.startswith('https://render.worldofwarcraft.com/') else '', item_id

    found = [r for r in await asyncio.gather(*(one(row['item_id']) for row in todo), return_exceptions=True)
             if not isinstance(r, Exception)]
    if found:
        def store():
            with db.transaction() as cur:
                cur.executemany('UPDATE ah_items SET icon = %s WHERE item_id = %s', found)
        await asyncio.to_thread(store)
    return len(found)


async def resolve_items(bz):
    """Items on sale that the game tables don't have yet (newer than wago's copy): their basics from Blizzard."""
    todo = await asyncio.to_thread(db.fetch_all, f"""
        SELECT s.item_id FROM (SELECT item_id FROM ah_item_summary UNION SELECT item_id FROM ah_commodity_summary) s
        LEFT JOIN ah_items i USING (item_id)
        WHERE s.item_id > 0 AND i.item_id IS NULL LIMIT {ITEMS_PER_RUN}""")
    sem = asyncio.Semaphore(LOOKUPS_AT_ONCE)

    async def one(item_id):
        async with sem:
            st, body, _ = await bz.get(f'/data/wow/item/{item_id}', blizzard.STATIC)
        if st != 200:
            return None
        d = orjson.loads(body)
        return (item_id, d.get('name') or f'Item {item_id}', QUALITY.get((d.get('quality') or {}).get('type'), 1),
                d.get('level') or 0, d.get('required_level') or 0, (d.get('item_class') or {}).get('id', -1),
                (d.get('item_subclass') or {}).get('id', -1), d.get('sell_price') or 0)

    rows = [r for r in await asyncio.gather(*(one(row['item_id']) for row in todo), return_exceptions=True)
            if r and not isinstance(r, Exception)]
    if rows:
        def store():
            with db.transaction() as cur:
                execute_values(cur, """INSERT INTO ah_items (item_id, name, quality, ilvl, req_level, class_id,
                                       subclass_id, vendor) VALUES %s ON CONFLICT (item_id) DO NOTHING""", rows)
        await asyncio.to_thread(store)
    return len(rows)


async def resolve_pets(bz):
    """
    Battle pet species on sale that we know nothing about yet: name, family, description and icon from Blizzard,
    stored as item -species in the "Battle Pets" category, one subcategory per family.
    """
    from .gamedata import PET_CLASS
    todo = await asyncio.to_thread(db.fetch_all, f"""
        SELECT DISTINCT l.item_id FROM ah_listings l LEFT JOIN ah_items i USING (item_id)
        WHERE l.item_id < 0 AND i.item_id IS NULL LIMIT {PETS_PER_RUN}""")
    sem = asyncio.Semaphore(LOOKUPS_AT_ONCE)

    async def one(item_id):
        async with sem:
            st, body, _ = await bz.get(f'/data/wow/pet/{-item_id}', blizzard.STATIC)
        if st != 200:
            return None
        d = orjson.loads(body)
        family = d.get('battle_pet_type') or {}
        icon = d.get('icon') or ''
        return (item_id, d.get('name') or f'Pet {-item_id}', 3, 0, 0, PET_CLASS, family.get('id', -1), 0, 0, 0, 0, 0,
                icon if icon.startswith('https://render.worldofwarcraft.com/') else '', (d.get('description') or '')[:1000],
                family.get('name') or '')

    rows = [r for r in await asyncio.gather(*(one(row['item_id']) for row in todo), return_exceptions=True)
            if r and not isinstance(r, Exception)]
    if rows:
        def store():
            with db.transaction() as cur:
                execute_values(cur, """INSERT INTO ah_items (item_id, name, quality, ilvl, req_level, class_id, subclass_id,
                                       inventory_type, expansion, vendor, binding, icon_file, icon, description)
                                       VALUES %s ON CONFLICT (item_id) DO NOTHING""", [r[:14] for r in rows])
                families = {(PET_CLASS, r[6], 'Battle Pets', r[14]) for r in rows if r[14]}
                execute_values(cur, """INSERT INTO ah_item_classes (class_id, subclass_id, class_name, subclass_name)
                                       VALUES %s ON CONFLICT (class_id, subclass_id) DO NOTHING""", sorted(families))
        await asyncio.to_thread(store)
        logger.info(f'[AH] Details for {len(rows)} battle pet species')
    return len(rows)


# ============================================================================
# A run
# ============================================================================

async def run_once():
    """Check every realm group and store what changed. Skips when the previous run is still going."""
    if _lock.locked():
        return
    async with _lock:
        status.update(running=True)
        started = time.monotonic()
        try:
            await _run()
            status['last_error'] = None
        except Exception as e:
            status['last_error'] = str(e)
            raise
        finally:
            status.update(running=False, last_run=datetime.now(timezone.utc), seconds=round(time.monotonic() - started))


async def _run():
    try:
        await gamedata.refresh_if_stale()
    except Exception:
        logger.exception('[AH] Game data refresh failed (keeping what we have)')
    if not await asyncio.to_thread(db.fetch_one, 'SELECT 1 AS ok FROM ah_bonus LIMIT 1'):
        logger.warning('[AH] No game data yet: not collecting')
        return
    timeout = aiohttp.ClientTimeout(total=300, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        bz = blizzard.Blizzard(session)
        if await asyncio.to_thread(_realms_stale):
            await refresh_realms(bz)
        ctx = await asyncio.to_thread(Context)
        groups = await asyncio.to_thread(db.realm_groups)
        sem, store_lock = asyncio.Semaphore(CONCURRENCY), asyncio.Lock()
        changed = []

        async def one(group):
            async with sem:
                st, body, last_modified = await bz.get(f'/data/wow/connected-realm/{group["cr"]}/auctions',
                                                       blizzard.DYNAMIC, since=group['last_modified'])
            if st != 200 or not body:
                return
            async with store_lock:
                kept = await asyncio.to_thread(process_realm, group['cr'], body, last_modified, ctx)
            changed.append((group['cr'], kept))

        async def commodities():
            row = await asyncio.to_thread(db.get_meta, 'commodities')
            st, body, last_modified = await bz.get('/data/wow/auctions/commodities', blizzard.DYNAMIC,
                                                   since=(row[0] or None) if row else None)
            if st != 200 or not body:
                return 0
            async with store_lock:
                return await asyncio.to_thread(process_commodities, body, last_modified)

        results = await asyncio.gather(commodities(), *(one(g) for g in groups), return_exceptions=True)
        commodity_items = results[0] if isinstance(results[0], int) else 0
        if isinstance(results[0], Exception):
            logger.warning(f'[AH] Commodities failed: {results[0]}')
        for group, result in zip(groups, results[1:]):
            if isinstance(result, Exception):
                logger.warning(f'[AH] Realm group {group["cr"]} failed: {result}')
        status['last_changed'] = len(changed)
        if commodity_items:
            logger.info(f'[AH] Commodities updated ({commodity_items} items)')
        if changed:
            logger.info(f'[AH] {len(changed)} realm groups updated ({sum(k for _, k in changed)} listings)')
            await asyncio.to_thread(summarize)
        looked_up = {}
        for name, step in (('levels', lambda: resolve_levels(session)), ('items', lambda: resolve_items(bz)),
                           ('pets', lambda: resolve_pets(bz)), ('icons', lambda: resolve_icons(bz))):
            try:
                looked_up[name] = await step()
            except Exception:
                logger.exception(f'[AH] Looking up {name} failed')
        if looked_up.get('levels'):  # the summaries' item level ranges follow the new levels now, not at the next update
            await asyncio.to_thread(summarize)
    extra = ', '.join(f'{n} {name}' for name, n in looked_up.items() if n)
    logger.info(f'[AH] Run done: {len(changed)} of {len(groups)} realm groups had new listings'
                + ('; commodities updated' if commodity_items else '') + (f'; looked up {extra}' if extra else ''))
    row = await asyncio.to_thread(db.get_meta, 'pruned')
    if not row or row[1] < datetime.now(timezone.utc) - timedelta(days=1):
        await asyncio.to_thread(db.prune_history)
        await asyncio.to_thread(db.set_meta, 'pruned', 'ok')
