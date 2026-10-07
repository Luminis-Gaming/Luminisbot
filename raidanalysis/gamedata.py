"""
Game data from the client's own tables (DB2), via wago.tools: which buffs WoW's Cooldown Manager tracks
for a spec - its "Tracked buffs" icons and "Tracked bars" (Strength of the Black Ox, Spiritfont,
Crimson Scourge...). Those are the procs and buffs the game itself thinks a player should watch, so
they're the ones the Rotation tab judges uptime and wasted procs on.

CooldownSetSpell lists each spec's entries with a category (0 essential cooldowns, 1 utility
cooldowns, 2 tracked buffs, 3 tracked bars, 4 more aura entries); CooldownSetLinkedSpell adds the aura
spell ids an entry shows (the buff often has another id than the talent). Refreshed weekly during the
sync; kept in raid_tracked_spells.

And the talent trees: each pull's combatantinfo lists a player's talents as trait node entry ids
(analysis['talents']); TraitNodeEntry -> TraitDefinition -> SpellName says which ability each gives (and
which one it replaces: Rushing Wind Kick takes Rising Sun Kick's place), TraitNodeXTraitNodeEntry ->
TraitNode which tree it's in. So an ability the top players use and you never pressed is "not talented"
only when your talents that pull say so - a baseline cooldown you never pressed is still a miss. Kept in
raid_talents, refreshed weekly.
"""
import csv
import io
import logging
import time
from typing import NamedTuple

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


async def _wago(session, *tables):
    texts = []
    for table in tables:
        async with session.get(WAGO.format(table=table)) as resp:
            if resp.status != 200:
                raise RuntimeError(f'wago.tools {table}: HTTP {resp.status}')
            texts.append(await resp.text())
    return texts


async def refresh_if_stale():
    """
    Fetch the Cooldown Manager and talent tables again when ours are a week old (or missing). Returns how
    many tracked ids (0 when they were fresh).
    """
    from . import db
    count = 0
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if db.tracked_spells_stale(REFRESH_DAYS):
            ids = tracked_spell_ids(*await _wago(session, 'CooldownSetSpell', 'CooldownSetLinkedSpell'))
            if len(ids) < 100:  # a changed format would empty it: keep what we had
                raise RuntimeError(f'wago.tools Cooldown Manager tables look wrong ({len(ids)} spells)')
            db.replace_tracked_spells(TRACKED, ids)
            logger.info(f'[RAIDS] Cooldown Manager: {len(ids)} tracked buff spells')
            count = len(ids)
        if db.talents_stale(REFRESH_DAYS):
            rows = talent_rows(*await _wago(session, 'TraitNodeEntry', 'TraitDefinition', 'TraitNodeXTraitNodeEntry',
                                            'TraitNode', 'SpellName'))
            if len(rows) < 1000:
                raise RuntimeError(f'wago.tools talent tables look wrong ({len(rows)} entries)')
            db.replace_talents(rows)
            _catalog.update(at=0)
            logger.info(f'[RAIDS] Talent trees: {len(rows)} entries')
    return count


# ============================================================================
# Talents
# ============================================================================

def talent_rows(entry_csv, definition_csv, node_entry_csv, node_csv, spell_name_csv):
    """The DB2 tables -> [(entry id, tree id, ability name, name of the ability it replaces or None)]."""
    definitions = {}
    for row in csv.DictReader(io.StringIO(definition_csv)):
        if row.get('ID', '').isdigit():
            definitions[row['ID']] = (int(row.get('SpellID') or 0), int(row.get('OverridesSpellID') or 0),
                                      row.get('OverrideName_lang') or '')
    tree_of_node = {row['ID']: int(row['TraitTreeID']) for row in csv.DictReader(io.StringIO(node_csv))
                    if row.get('TraitTreeID', '').isdigit()}
    tree_of_entry = {}
    for row in csv.DictReader(io.StringIO(node_entry_csv)):
        if row.get('TraitNodeID') in tree_of_node:
            tree_of_entry.setdefault(row['TraitNodeEntryID'], tree_of_node[row['TraitNodeID']])
    entries = {}  # entry id -> (tree, spell id, overridden spell id, display name)
    for row in csv.DictReader(io.StringIO(entry_csv)):
        tree, definition = tree_of_entry.get(row.get('ID')), definitions.get(row.get('TraitDefinitionID'))
        if tree and definition and (definition[0] or definition[2]):
            entries[int(row['ID'])] = (tree, *definition)
    wanted = {i for _, spell, over, _ in entries.values() for i in (spell, over) if i}
    names = {}
    for row in csv.DictReader(io.StringIO(spell_name_csv)):  # every spell in the game: keep the talents' only
        if row.get('ID', '').isdigit() and int(row['ID']) in wanted:
            names[int(row['ID'])] = row.get('Name_lang') or ''
    out = []
    for entry, (tree, spell, over, display) in sorted(entries.items()):
        name = names.get(spell) or display
        if name:
            out.append((entry, tree, name, names.get(over) or None))
    return out


def catalog_from(rows):
    """raid_talents rows -> {'entries': {entry id: (tree, name, replaces)}, 'trees': {tree: {ability names}}}."""
    entries, trees = {}, {}
    for r in rows:
        entries[r['entry_id']] = (r['tree_id'], r['name'], r['overrides'])
        trees.setdefault(r['tree_id'], set()).add(r['name'])
    return {'entries': entries, 'trees': trees}


class Talents(NamedTuple):
    """What a player's talents say: missing - abilities they didn't have; known - every ability of their trees."""
    missing: frozenset
    known: frozenset


def missing_abilities(entries, catalog):
    """
    Talents(missing, known) for one pull's talents (its analysis['talents'] entry): missing - every talent of
    their trees they didn't take, plus whatever a talent they took replaces - or None when the entries mean
    nothing to the catalog (no data to go on).
    """
    found = [catalog['entries'][e] for e in entries or () if e in catalog['entries']]
    if not found:
        return None
    taken = {name for _, name, _ in found}
    # Replaced is gone even when its own node was taken too (Rushing Wind Kick sits on Rising Sun Kick's)
    replaced = {over for _, _, over in found if over}
    offered = set().union(*(catalog['trees'].get(tree, set()) for tree, _, _ in found))
    return Talents(frozenset((offered - taken) | replaced), frozenset(offered | replaced))


CATALOG_SECONDS = 3600
_catalog = {'at': 0, 'data': None}


def _talent_catalog():
    from . import db
    if time.time() - _catalog['at'] > CATALOG_SECONDS:
        try:
            _catalog['data'] = catalog_from(db.get_talents())
        except Exception as e:
            logger.warning(f'[RAIDS] Talent trees unavailable: {e}')
            _catalog['data'] = None
        _catalog['at'] = time.time()
    return _catalog['data']


def not_taken(numbered, name, catalog=None):
    """
    Talents(missing, known) over these pulls - missing: the abilities a character didn't have in any of them
    (talents can change between pulls: one they had in some pull isn't missing) - or None when no pull has
    their talents (analysed before talents were kept): callers then fall back to "never used, so most likely
    not talented".
    """
    catalog = catalog if catalog is not None else _talent_catalog()
    if not catalog or not catalog['entries']:
        return None
    out = None
    for _, pull in numbered:
        entries = ((pull.get('analysis') or {}).get('talents') or {}).get(name)
        found = missing_abilities(entries, catalog) if entries else None
        if found is not None:
            out = found if out is None else Talents(out.missing & found.missing, out.known | found.known)
    return out


def tracked_ids():
    """The tracked buff spell ids (empty if never fetched - callers fall back to a rule of thumb)."""
    from . import db
    try:
        return db.get_tracked_spells(TRACKED)
    except Exception:
        logger.warning('[RAIDS] Tracked spells unavailable', exc_info=True)
        return frozenset()
