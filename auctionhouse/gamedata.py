"""
The game's own item tables, from wago.tools (like raidanalysis/gamedata.py), refreshed weekly:
  ItemSparse + Item        name, item level, required level, quality, expansion, slot, vendor price, binding,
                           category and icon of every item (~180k) -> ah_items
  ItemClass + ItemSubClass the category names -> ah_item_classes
  ItemBonus                what every bonus id does (stats, sockets, item level) -> ah_bonus (rolls.py reads it)

Some items have no icon in these tables; collector.resolve_icons asks Blizzard for the ones on sale.
"""
import asyncio
import csv
import io
import json
import logging

import aiohttp

from . import db

logger = logging.getLogger(__name__)

WAGO = 'https://wago.tools/db2/{table}/csv'
REFRESH_DAYS = 7
PET_CLASS = 17  # "Battle Pets": its families come from Blizzard's pet data, not these tables
META_KEY = 'gamedata'
FETCH_TRIES = 3  # wago.tools has the odd hiccup (and maintenance windows, which the next run simply tries again)


async def _fetch(session, table):
    for attempt in range(FETCH_TRIES):
        try:
            async with session.get(WAGO.format(table=table)) as resp:
                if resp.status == 200:
                    return await resp.text()
                error = f'HTTP {resp.status}'
                if resp.status < 500 and resp.status != 429:
                    break
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            error = str(e) or type(e).__name__
        if attempt + 1 < FETCH_TRIES:
            await asyncio.sleep(5 * (attempt + 1))
    raise RuntimeError(f'wago.tools {table}: {error}')


def stale():
    row = db.get_meta(META_KEY)
    if not row:
        return True
    from datetime import datetime, timedelta, timezone
    return row[1] < datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_items(sparse_csv, item_csv):
    """
    -> rows for ah_items (without the icon url column). A reagent that comes in crafting quality ranks is several
    items with one name (Mycobloom x3); each gets its rank (1, 2, 3 - by the item table's CraftingQualityID, in
    order among the items sharing its name), so the pages can tell them apart.
    """
    base = {}
    for r in csv.DictReader(io.StringIO(item_csv)):
        base[r['ID']] = (_int(r.get('ClassID'), -1), _int(r.get('SubclassID'), -1), _int(r.get('IconFileDataID')),
                         _int(r.get('CraftingQualityID')))
    rows = []
    for r in csv.DictReader(io.StringIO(sparse_csv)):
        name = (r.get('Display_lang') or '').strip()
        if not name:
            continue
        cls, sub, icon, quality_id = base.get(r['ID'], (-1, -1, 0, 0))
        rows.append([_int(r['ID']), name, _int(r.get('OverallQualityID'), 1), _int(r.get('ItemLevel')),
                     _int(r.get('RequiredLevel')), cls, sub, _int(r.get('InventoryType')), _int(r.get('ExpansionID')),
                     _int(r.get('SellPrice')), _int(r.get('Bonding')), icon, quality_id])
    ranked = {}
    for row in rows:
        if row[12]:
            ranked.setdefault(row[1], []).append(row)
    for same in ranked.values():
        for rank, row in enumerate(sorted(same, key=lambda r: (r[12], r[0])), 1):
            row[12] = rank if len(same) > 1 else 0
    for row in rows:
        if row[1] not in ranked:
            row[12] = 0
    return [tuple(r) for r in rows]


def parse_classes(class_csv, subclass_csv):
    names = {_int(r['ClassID']): r['ClassName_lang'] for r in csv.DictReader(io.StringIO(class_csv))}
    rows = []
    for r in csv.DictReader(io.StringIO(subclass_csv)):
        cls = _int(r['ClassID'])
        if cls in names and cls != PET_CLASS:  # battle pets: one category per pet family (collector.resolve_pets)
            sub = (r.get('VerboseName_lang') or '').strip() or (r.get('DisplayName_lang') or '').strip()
            rows.append((cls, _int(r['SubClassID']), names[cls], sub or names[cls]))
    return rows


def parse_bonus(bonus_csv):
    effects = {}
    for r in csv.DictReader(io.StringIO(bonus_csv)):
        effects.setdefault(_int(r['ParentItemBonusListID']), []).append(
            [_int(r['Type']), _int(r['Value_0']), _int(r['Value_1'])])
    return [(b, json.dumps(e)) for b, e in effects.items()]


def _store(items, classes, bonus):
    with db.transaction() as cur:
        cur.execute('CREATE TEMP TABLE ah_items_new (LIKE ah_items) ON COMMIT DROP')
        db.copy_rows(cur, 'ah_items_new', ('item_id', 'name', 'quality', 'ilvl', 'req_level', 'class_id',
                                           'subclass_id', 'inventory_type', 'expansion', 'vendor', 'binding',
                                           'icon_file', 'craft_rank'), items)
        cur.execute("""INSERT INTO ah_items (item_id, name, quality, ilvl, req_level, class_id, subclass_id,
                                             inventory_type, expansion, vendor, binding, icon_file, craft_rank)
                       SELECT item_id, name, quality, ilvl, req_level, class_id, subclass_id, inventory_type,
                              expansion, vendor, binding, icon_file, craft_rank FROM ah_items_new
                       ON CONFLICT (item_id) DO UPDATE SET
                           name = EXCLUDED.name, quality = EXCLUDED.quality, ilvl = EXCLUDED.ilvl,
                           req_level = EXCLUDED.req_level, class_id = EXCLUDED.class_id,
                           subclass_id = EXCLUDED.subclass_id, inventory_type = EXCLUDED.inventory_type,
                           expansion = EXCLUDED.expansion, vendor = EXCLUDED.vendor, binding = EXCLUDED.binding,
                           icon_file = EXCLUDED.icon_file, craft_rank = EXCLUDED.craft_rank""")
        cur.execute('DELETE FROM ah_item_classes WHERE class_id <> %s', (PET_CLASS,))
        db.copy_rows(cur, 'ah_item_classes', ('class_id', 'subclass_id', 'class_name', 'subclass_name'), classes)
        cur.execute('DELETE FROM ah_bonus')
        db.copy_rows(cur, 'ah_bonus', ('bonus_id', 'effects'), bonus)


async def refresh_if_stale():
    """Fetch the tables again when ours are a week old (or missing). Returns True when it refreshed."""
    import asyncio
    if not await asyncio.to_thread(stale):
        return False
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        texts = {t: await _fetch(session, t) for t in ('ItemSparse', 'Item', 'ItemClass', 'ItemSubClass', 'ItemBonus')}

    def work():
        items = parse_items(texts['ItemSparse'], texts['Item'])
        classes = parse_classes(texts['ItemClass'], texts['ItemSubClass'])
        bonus = parse_bonus(texts['ItemBonus'])
        if len(items) < 100000 or len(bonus) < 5000:  # a changed format would empty them: keep what we had
            raise RuntimeError(f'wago.tools item tables look wrong ({len(items)} items, {len(bonus)} bonus lists)')
        _store(items, classes, bonus)
        db.set_meta(META_KEY, f'{len(items)} items, {len(bonus)} bonus lists')
        return len(items), len(bonus)

    items, bonus = await asyncio.to_thread(work)
    logger.info(f'[AH] Game data refreshed: {items} items, {bonus} bonus lists')
    return True
