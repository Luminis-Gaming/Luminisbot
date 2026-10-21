"""
Every profession recipe that makes something sold on the auction house, from the game's own tables (wago.tools),
refreshed weekly like gamedata.py - the crafting page prices it all against the auction house as it is now.

  SkillLineAbility             recipe -> its spell, profession and expansion (the "Midnight Alchemy" skill line)
  SpellReagents                the plain reagents and how many: 4 Mote of Wild Magic
  ModifiedCraftingSpellSlot    the quality reagents (ReagentType 1, required) and how many: 6 Tranquility Bloom,
  + MCRSlotXMCRCategory          either rank. The optional ones - embellishments, finishing reagents, crests - are
  + CraftingReagentQuality       left out: nobody needs them to craft
  SpellEffect                  what the spell makes, and how many per craft:
                                 create item (24, 157, 296)  the item itself
                                 craft item (288)            CraftingData: one item, or one per quality rank
                                 craft enchant (301)         CraftingDataEnchantQuality: the scroll per rank

Stored in ah_recipes and ah_recipe_reagents (items of a quality slot or output in rank order, rank 1 first).
SpellEffect is big (~60 MB), so it's read a line at a time and only the recipes' rows are kept.
"""
import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone

import aiohttp

from . import db
from .gamedata import WAGO, _fetch, _int

logger = logging.getLogger(__name__)

META_KEY = 'crafting'
REFRESH_DAYS = 7
PROFESSIONS = {164: 'Blacksmithing', 165: 'Leatherworking', 171: 'Alchemy', 185: 'Cooking', 197: 'Tailoring',
               202: 'Engineering', 333: 'Enchanting', 755: 'Jewelcrafting', 773: 'Inscription'}
CREATE_ITEM = {24, 157, 296}
CRAFT_ITEM = 288
CRAFT_ENCHANT = 301
REQUIRED = 1           # ModifiedCraftingReagentSlot.ReagentType of a slot every craft must fill
QUALITY_SLOT = 100     # quality reagent slots are stored as 100 + their slot, after the plain reagents (0-7)
TABLES = ('SkillLine', 'SkillLineAbility', 'SpellReagents', 'ModifiedCraftingSpellSlot', 'ModifiedCraftingReagentSlot',
          'MCRSlotXMCRCategory', 'CraftingReagentQuality', 'CraftingData', 'CraftingDataItemQuality',
          'CraftingDataEnchantQuality')


def _rows(text):
    return csv.DictReader(io.StringIO(text))


def recipe_spells(texts):
    """
    -> ({spell: (recipe id, profession, tier skill line)}, {skill line: (name, tier index)}) for the professions
    that make things to sell. The tier is the expansion's own skill line ("Midnight Alchemy").
    """
    lines = {}
    for r in _rows(texts['SkillLine']):
        lines[_int(r['ID'])] = ((r.get('DisplayName_lang') or '').strip(), _int(r.get('ParentSkillLineID')),
                                _int(r.get('ParentTierIndex')))
    spells = {}
    for r in sorted(_rows(texts['SkillLineAbility']), key=lambda r: _int(r['ID'])):
        line, tier = _int(r['SkillLine']), _int(r.get('SkillupSkillLineID'))
        profession = line if line in PROFESSIONS else lines.get(line, ('', 0, 0))[1]
        if profession not in PROFESSIONS:
            continue
        if not (tier and lines.get(tier, ('', 0, 0))[1] == profession):
            tier = line if line != profession else 0
        spell = _int(r['Spell'])
        if tier and spell and spell not in spells:
            spells[spell] = (_int(r['ID']), profession, tier)
    return spells, {line: (name, index) for line, (name, _, index) in lines.items()}


def outputs(effects, texts):
    """effects: {spell: [(effect, item type, base points, misc value)]} -> {spell: ([items, rank 1 first], per craft)}"""
    crafting = {_int(r['ID']): _int(r.get('CraftedItemID')) for r in _rows(texts['CraftingData'])}
    ranked = {}
    for r in sorted(_rows(texts['CraftingDataItemQuality']), key=lambda r: _int(r['ID'])):
        ranked.setdefault(_int(r['CraftingDataID']), []).append(_int(r['ItemID']))
    scrolls = {}
    for r in sorted(_rows(texts['CraftingDataEnchantQuality']), key=lambda r: (_int(r['Rank']), _int(r['ID']))):
        scrolls.setdefault(_int(r['CraftingDataID']), []).append(_int(r['ItemID']))
    out = {}
    for spell, rows in effects.items():
        for effect, item, base, misc in rows:
            if effect in CREATE_ITEM:
                items = [item] if item > 0 else []
            elif effect == CRAFT_ITEM:
                items = [crafting[misc]] if crafting.get(misc) else ranked.get(misc, [])
            elif effect == CRAFT_ENCHANT:
                items = scrolls.get(misc, [])
            else:
                continue
            items = [i for i in items if i > 0]
            if items:
                out[spell] = (items, max(1, round(base)))
                break
    return out


def reagents(spells, texts):
    """-> {spell: [(slot, [items, rank 1 first], how many)]}; a spell with a required slot we can't fill is left out."""
    out = {}
    for r in _rows(texts['SpellReagents']):
        spell = _int(r['SpellID'])
        if spell in spells:
            for i in range(8):
                item, count = _int(r.get(f'Reagent_{i}')), _int(r.get(f'ReagentCount_{i}'))
                if item > 0 and count > 0:
                    out.setdefault(spell, []).append((i, [item], count))
    required = {_int(r['ID']) for r in _rows(texts['ModifiedCraftingReagentSlot']) if _int(r.get('ReagentType')) == REQUIRED}
    categories = {}
    for r in sorted(_rows(texts['MCRSlotXMCRCategory']), key=lambda r: (_int(r.get('_Order')), _int(r['ID']))):
        categories.setdefault(_int(r['ModifiedCraftingReagentSlotID']), []).append(_int(r['ModifiedCraftingCategoryID']))
    qualities = {}
    for r in sorted(_rows(texts['CraftingReagentQuality']), key=lambda r: (_int(r.get('OrderIndex')), _int(r['ID']))):
        if _int(r.get('ItemID')) > 0:
            qualities.setdefault(_int(r['ModifiedCraftingCategoryID']), []).append(_int(r['ItemID']))
    unfillable = set()
    for r in _rows(texts['ModifiedCraftingSpellSlot']):
        spell, slot = _int(r['SpellID']), _int(r['ModifiedCraftingReagentSlotID'])
        if spell not in spells or slot not in required or _int(r.get('ReagentCount')) <= 0:
            continue
        items = next((qualities[c] for c in categories.get(slot, []) if qualities.get(c)), None)
        if items:
            out.setdefault(spell, []).append((QUALITY_SLOT + _int(r.get('Slot')), items, _int(r['ReagentCount'])))
        else:
            unfillable.add(spell)
    return {spell: slots for spell, slots in out.items() if spell not in unfillable}


async def _spell_effects(session, spells):
    """SpellEffect, a line at a time: {spell: [(effect, item type, base points, misc value)]} for these spells."""
    wanted = CREATE_ITEM | {CRAFT_ITEM, CRAFT_ENCHANT}
    out, header = {}, None
    async with session.get(WAGO.format(table='SpellEffect')) as resp:
        if resp.status != 200:
            raise RuntimeError(f'wago.tools SpellEffect: HTTP {resp.status}')
        async for raw in resp.content:
            row = next(csv.reader([raw.decode('utf-8', 'replace')]), None)
            if not row:
                continue
            if header is None:
                header = {name: i for i, name in enumerate(row)}
                cols = [header[c] for c in ('SpellID', 'Effect', 'EffectItemType', 'EffectBasePointsF', 'EffectMiscValue_0')]
                continue
            try:
                spell, effect = int(row[cols[0]]), int(row[cols[1]])
            except (ValueError, IndexError):
                continue
            if spell in spells and effect in wanted:
                out.setdefault(spell, []).append((effect, _int(row[cols[2]]), float(row[cols[3]] or 0), _int(row[cols[4]])))
    return out


def stale():
    row = db.get_meta(META_KEY)
    return not row or row[1] < datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)


async def refresh_if_stale():
    """The recipe book again when ours is a week old (or missing). Returns how many recipes, or 0 when not due."""
    if not await asyncio.to_thread(stale):
        return 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=600)) as session:
        texts = {t: await _fetch(session, t) for t in TABLES}
        spells, lines = recipe_spells(texts)
        effects = await _spell_effects(session, spells)

    def work():
        made = outputs(effects, texts)
        needs = reagents(spells, texts)
        recipes, slots = [], []
        for spell, (items, per_craft) in made.items():
            if spell not in needs:
                continue
            recipe, profession, tier = spells[spell]
            name, index = lines.get(tier, ('', 0))
            recipes.append((recipe, spell, profession, tier, name, index, items, per_craft))
            slots += [(recipe, slot, items_, count) for slot, items_, count in needs[spell]]
        if len(recipes) < 1000:  # a changed format would empty it: keep what we had
            raise RuntimeError(f'wago.tools recipe tables look wrong ({len(recipes)} recipes)')
        with db.transaction() as cur:
            cur.execute('DELETE FROM ah_recipe_reagents')
            cur.execute('DELETE FROM ah_recipes')
            db.copy_rows(cur, 'ah_recipes', ('recipe_id', 'spell_id', 'profession', 'tier', 'tier_name', 'tier_index',
                                             'outputs', 'per_craft'), recipes)
            db.copy_rows(cur, 'ah_recipe_reagents', ('recipe_id', 'slot', 'items', 'qty'), slots)
        db.set_meta(META_KEY, f'{len(recipes)} recipes')
        return len(recipes)

    n = await asyncio.to_thread(work)
    logger.info(f'[AH] Recipe book refreshed: {n} recipes')
    return n
