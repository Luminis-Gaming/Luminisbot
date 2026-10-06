"""
Portraits for enemies (adds, bosses) on the timelines and the damage-by-target cards: Wowhead's render of
the NPC's model (the picture on its NPC page), from their CDN by display id -
wow.zamimg.com/modelviewer/live/webthumbs/npc/{display id % 256}/{display id}.webp (300 px, transparent).

NPCs have no icon in the game files, only a model, so the step that matters is NPC id (the log's actors'
gameID) -> display id: the client's own Creature table via wago.tools (bosses and some adds - the table
is sparse, most creatures are server-side), else the data-mv-display-id on the NPC's Wowhead page.
(Blizzard's creature API was tried first: it has no entry for most raid adds.)

Looked up in the background the first time a page shows the enemy (ensure()), cached for good in
raid_npcs by name; a miss is kept as NULL (retried daily) and VERSION re-tries every row.
"""
import asyncio
import csv
import io
import logging
import re
import time

logger = logging.getLogger(__name__)

VERSION = 2            # bump when the lookup changes: older rows (misses included) are looked up again
PER_RUN = 20
CREATURE_TABLE = 'https://wago.tools/db2/Creature/csv'
NPC_PAGE = 'https://www.wowhead.com/npc={id}'
THUMB = 'https://wow.zamimg.com/modelviewer/live/webthumbs/npc/{bucket}/{id}.webp'
HEADERS = {'User-Agent': 'LuminisBot raid analysis (npc portraits)', 'Accept': 'text/html,application/xhtml+xml'}
_DISPLAY = re.compile(r'data-mv-display-id="(\d+)"')
TABLE_MAX_AGE_S = 24 * 3600

_table = {'at': 0, 'displays': {}}  # the Creature table, kept in memory: {npc id: display id}
_in_flight = set()
_tasks = set()  # running fills, kept so they aren't garbage collected mid-way


def thumb_url(display_id):
    return THUMB.format(bucket=int(display_id) % 256, id=int(display_id))


def icons(names):
    """{name: portrait url} for the enemies with one cached (no lookups here)."""
    from . import db
    try:
        return {n: url for n, url in db.get_npcs(sorted(set(names)), VERSION).items() if url}
    except Exception:
        logger.exception('[RAIDS] Reading NPC portraits failed')
        return {}


def ensure(code, names):
    """Look up the portraits of these enemies (from report `code`'s actors) not cached yet, in the background."""
    from . import db
    names = sorted({n for n in names if n})
    try:
        known = db.get_npcs(names, VERSION)
    except Exception:
        return
    missing = [n for n in names if n not in known and n not in _in_flight][:PER_RUN]
    if not missing:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # not in the web server's loop (tests, scripts): the next page view does it
    _in_flight.update(missing)
    task = loop.create_task(fill(code, missing))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def fill(code, names):
    import aiohttp
    from . import db, wcl
    try:
        async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as session:
            actors = await wcl.get_report_actors(session, code)
            ids = {}
            for a in actors:
                if a.get('type') not in ('Player', 'Pet') and a.get('gameID') and a['name'] not in ids:
                    ids[a['name']] = a['gameID']
            for name in names:
                game_id = ids.get(name)
                url = await _portrait(session, game_id) if game_id else None
                if not url:
                    logger.info('[RAIDS] No portrait for %s (NPC %s)', name, game_id)
                db.save_npc(name, game_id, url, 'ok' if url else 'missing', VERSION)
    except Exception:
        logger.exception('[RAIDS] NPC portraits for %s failed', code)
    finally:
        _in_flight.difference_update(names)


async def _portrait(session, game_id):
    """The NPC's model thumbnail URL, or None: its display id from the Creature table, else its Wowhead page."""
    display = (await _creature_table(session)).get(int(game_id)) or await _display_from_wowhead(session, game_id)
    if not display:
        return None
    url = thumb_url(display)
    async with session.head(url) as resp:  # not every model has a render
        return url if resp.status == 200 else None


async def _creature_table(session):
    if _table['displays'] and time.time() - _table['at'] < TABLE_MAX_AGE_S:
        return _table['displays']
    try:
        async with session.get(CREATURE_TABLE) as resp:
            resp.raise_for_status()
            text = await resp.text()
        _table.update(at=time.time(), displays=parse_creature_table(text))
    except Exception as e:
        logger.warning(f'[RAIDS] wago.tools Creature table: {e}')
        _table['at'] = time.time()  # don't hammer it: the Wowhead pages still work meanwhile
    return _table['displays']


def parse_creature_table(text):
    """The Creature DB2 as CSV -> {npc id: its first display id}."""
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            display = int(row.get('DisplayID_0') or 0)
            if display:
                out[int(row['ID'])] = display
        except (KeyError, ValueError):
            continue
    return out


async def _display_from_wowhead(session, game_id):
    try:
        async with session.get(NPC_PAGE.format(id=int(game_id))) as resp:
            if resp.status != 200:
                logger.info('[RAIDS] Wowhead NPC %s: HTTP %s', game_id, resp.status)
                return None
            html = await resp.text()
    except Exception as e:
        logger.info(f'[RAIDS] Wowhead NPC {game_id}: {e}')
        return None
    return display_from_page(html)


def display_from_page(html):
    """The model's display id on a Wowhead NPC page (its model viewer button), or None."""
    m = _DISPLAY.search(html or '')
    return int(m.group(1)) if m else None
