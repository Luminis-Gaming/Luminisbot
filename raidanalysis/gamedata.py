"""
Game data from the client's own tables (DB2), via wago.tools: which buffs WoW's Cooldown Manager tracks
for a spec - its "Tracked buffs" icons and "Tracked bars" (Strength of the Black Ox, Spiritfont,
Crimson Scourge...). Those are the procs and buffs the game itself thinks a player should watch, so
they're the ones the Rotation tab judges uptime and wasted procs on.

CooldownSetSpell lists each spec's entries with a category (0 essential cooldowns, 1 utility
cooldowns, 2 tracked buffs, 3 tracked bars, 4 more aura entries); CooldownSetLinkedSpell adds the aura
spell ids an entry shows (the buff often has another id than the talent). Refreshed weekly during the
sync; kept in raid_tracked_spells.
"""
import csv
import io
import logging

import aiohttp

logger = logging.getLogger(__name__)

WAGO = 'https://wago.tools/db2/{table}/csv'
TRACKED_CATEGORIES = {'2', '3', '4'}
REFRESH_DAYS = 7
TRACKED = 'tracked'


def tracked_spell_ids(set_spells_csv, linked_csv):
    """The two CSVs -> every spell id the Cooldown Manager tracks as a buff (entries and their linked auras)."""
    entries = {}
    for row in csv.DictReader(io.StringIO(set_spells_csv)):
        if row.get('Category') in TRACKED_CATEGORIES and row.get('SpellID', '').isdigit():
            entries[row['ID']] = int(row['SpellID'])
    ids = set(entries.values())
    for row in csv.DictReader(io.StringIO(linked_csv)):
        if row.get('CooldownSetSpellID') in entries and row.get('SpellID', '').isdigit():
            ids.add(int(row['SpellID']))
    ids.discard(0)
    return ids


async def refresh_if_stale():
    """Fetch the Cooldown Manager tables again when ours are a week old (or missing). Returns how many ids."""
    from . import db
    if not db.tracked_spells_stale(REFRESH_DAYS):
        return 0
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        texts = []
        for table in ('CooldownSetSpell', 'CooldownSetLinkedSpell'):
            async with session.get(WAGO.format(table=table)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f'wago.tools {table}: HTTP {resp.status}')
                texts.append(await resp.text())
    ids = tracked_spell_ids(*texts)
    if len(ids) < 100:  # a changed format would empty it: keep what we had
        raise RuntimeError(f'wago.tools Cooldown Manager tables look wrong ({len(ids)} spells)')
    db.replace_tracked_spells(TRACKED, ids)
    logger.info(f'[RAIDS] Cooldown Manager: {len(ids)} tracked buff spells')
    return len(ids)


def tracked_ids():
    """The tracked buff spell ids (empty if never fetched - callers fall back to a rule of thumb)."""
    from . import db
    try:
        return db.get_tracked_spells(TRACKED)
    except Exception:
        logger.warning('[RAIDS] Tracked spells unavailable', exc_info=True)
        return frozenset()
