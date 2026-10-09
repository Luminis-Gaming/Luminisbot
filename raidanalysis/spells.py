"""
Spell names, icons, cooldowns and descriptions for the timeline tooltips, from
Wowhead's tooltip API (the JSON behind their hover tooltips), cached for good in
raid_spells - spell text barely changes and the timeline only needs the gist.

After each sync, fill_missing() looks up spells that analyses mention (boss
abilities, cooldowns, potions, killing blows) and that we don't have yet, a few
hundred per run.
"""
import asyncio
import html
import logging
import re

import aiohttp

logger = logging.getLogger(__name__)

TOOLTIP_URL = 'https://nether.wowhead.com/tooltip/spell/{id}?dataEnv=1&locale=0'
ICON_URL = 'https://wow.zamimg.com/images/wow/icons/medium/{icon}.jpg'
PER_RUN = 400
PARSER = 2           # bump when parse() learns something new: older rows get looked up again
CONCURRENCY = 4
HEADERS = {'User-Agent': 'LuminisBot raid analysis (spell tooltips)'}
# Ids the logs use that aren't the spell Wowhead has under them: 1 is Warcraft Logs' melee swing ("Melee"), Wowhead's
# spell 1 an old unused one ("Word of Recall (OLD)"). Never looked up - the log's own name and icon stand.
NOT_SPELLS = {1}

_COMMENTS = re.compile(r'<!--.*?-->', re.S)
_TAGS = re.compile(r'<[^>]+>')
_FORMULA = re.compile(r'\[[^\]]*\]')   # scaled values Wowhead computes client-side: "[Total Health * 30 / 100 ...]"
_DESCRIPTION = re.compile(r'<div class="q">(.*?)</div>', re.S)
_CAST_LINE = re.compile(r'<table width="100%"><tr><td>(.*?)</td><th>(.*?)</th></tr></table>', re.S)


def _text(fragment):
    fragment = _COMMENTS.sub('', fragment)
    fragment = re.sub(r'<br\s*/?>', '\n', fragment)
    text = html.unescape(_TAGS.sub('', fragment))
    text = _FORMULA.sub('X', text)
    return re.sub(r'[ \t]+', ' ', re.sub(r'\n\s*\n+', '\n', text)).strip()


def parse(data):
    """Wowhead tooltip JSON -> {'name', 'icon', 'meta', 'description'}."""
    tooltip = data.get('tooltip') or ''
    parts = [_text(p) for p in _DESCRIPTION.findall(tooltip)]
    description = '\n'.join(p for p in parts if p)
    # Cost / range / cast time / cooldown rows, e.g. "40 yd range · Channeled · 3 min cooldown"
    cells = [_text(c) for row in _CAST_LINE.findall(tooltip) for c in row]
    name = data.get('name') or ''
    meta = ' · '.join(c for c in cells if c and c != name and not c.lower().startswith('level')
                      and c != 'Item Effect')
    if 'Item Effect' in tooltip:  # on-use trinkets, potions, other items
        meta = 'Item effect' + (' · ' + meta if meta else '')
    return {'name': name, 'icon': data.get('icon') or '', 'meta': meta[:120],
            'description': description[:600]}


async def _fetch(session, spell_id):
    url = TOOLTIP_URL.format(id=spell_id)
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
        if resp.status == 404:
            return None
        resp.raise_for_status()
        data = await resp.json(content_type=None)
    if not data or data.get('error') or not data.get('name'):
        return None
    return parse(data)


async def fill_missing(limit=PER_RUN):
    """Look up spells our analyses mention that aren't cached yet. Returns how many were looked up."""
    from . import db
    return await fetch_ids(db.spells_missing(limit))


_in_flight = set()

# Spells our pages have shown (ability cells, timelines): the only ones /raids/spell may look up on
# Wowhead, so the public endpoint can't be used to make us fetch (and store) arbitrary ids.
OFFERED_MAX = 50000
_offered = set()
# And at most this many on-demand Wowhead lookups per minute, whoever asks.
ON_DEMAND_PER_MINUTE = 60
_on_demand = []


def offer(spell_ids):
    """Remember spells a page showed (bounded; cleared when full - pages re-offer as they render)."""
    if len(_offered) > OFFERED_MAX:
        _offered.clear()
    _offered.update(int(i) for i in spell_ids if i and int(i) not in NOT_SPELLS)


def may_fetch(spell_id):
    """Whether the public tooltip endpoint may look this spell up on Wowhead right now."""
    import time
    now = time.time()
    _on_demand[:] = [t for t in _on_demand if now - t < 60]
    if int(spell_id) not in _offered or len(_on_demand) >= ON_DEMAND_PER_MINUTE:
        return False
    _on_demand.append(now)
    return True


def lookup(spell_ids):
    """
    Cached tooltip text for these spells ({id: row}). Spells never looked up are fetched in the
    background right away (when called from the web server's event loop), so a reload shows them -
    pages don't have to wait for the next sync.
    """
    from . import db
    ids = {int(i) for i in spell_ids if i} - NOT_SPELLS
    if not ids:
        return {}
    found = db.get_spells(ids)
    missing = sorted(ids - db.attempted_spell_ids(ids) - _in_flight)[:PER_RUN]
    if missing:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop:
            _in_flight.update(missing)

            async def run():
                try:
                    await fetch_ids(missing)
                finally:
                    _in_flight.difference_update(missing)
            loop.create_task(run())
    return found


async def fetch_ids(spell_ids):
    """Look these spells up on Wowhead and cache the result (also not-found / failed). Returns how many."""
    from . import db
    missing = [i for i in spell_ids if int(i) not in NOT_SPELLS]
    if not missing:
        return 0
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(session, spell_id):
        async with gate:
            try:
                info = await _fetch(session, spell_id)
                db.save_spell(spell_id, info, 'ok' if info else 'not_found')
            except Exception as e:  # retried after an hour
                logger.warning(f"[RAIDS] Spell {spell_id} lookup failed: {e}")
                db.save_spell(spell_id, None, 'error')

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(one(session, spell_id) for spell_id in missing))
    logger.info(f"[RAIDS] Looked up {len(missing)} spell tooltip(s) on Wowhead")
    return len(missing)


def icon_url(icon):
    return ICON_URL.format(icon=icon) if icon else None
