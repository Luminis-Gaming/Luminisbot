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
PER_RUN = 200
CONCURRENCY = 4
HEADERS = {'User-Agent': 'LuminisBot raid analysis (spell tooltips)'}

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
    meta = ' · '.join(c for c in cells if c and c != name and not c.lower().startswith('level'))
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
    missing = db.spells_missing(limit)
    if not missing:
        return 0
    gate = asyncio.Semaphore(CONCURRENCY)

    async def one(session, spell_id):
        async with gate:
            try:
                info = await _fetch(session, spell_id)
                db.save_spell(spell_id, info, 'ok' if info else 'not_found')
            except Exception as e:  # retried on a later run
                logger.warning(f"[RAIDS] Spell {spell_id} lookup failed: {e}")
                db.save_spell(spell_id, None, 'error')

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(one(session, spell_id) for spell_id in missing))
    logger.info(f"[RAIDS] Looked up {len(missing)} spell tooltip(s) on Wowhead")
    return len(missing)


def icon_url(icon):
    return ICON_URL.format(icon=icon) if icon else None
