"""
What each collectible on sale teaches, so the collection page can hold a character's mounts, pets and toys (Blizzard's
profile API) against the auction house:

  toys    Blizzard's toy documents name their item
  mounts  a mount item's "use" spell carries its mount's name (Ashes of Al'ar teaches the mount Ashes of Al'ar)
  pets    a caged battle pet is item -species already; a companion item is named after its pet (or its spell is)

Stored in ah_collectibles (item -> kind and mount, toy or species id) and looked up twice a day, only what's new:
a toy document once, a mount or companion item until we can tell what it teaches.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import orjson
from psycopg2.extras import execute_values

from . import blizzard, db

logger = logging.getLogger(__name__)

REFRESH_HOURS = 12
AT_ONCE = 8
MISC_CLASS, PET_SUBCLASS, MOUNT_SUBCLASS = 15, 2, 5


def _norm(name):
    return ' '.join((name or '').lower().replace('’', "'").split())


def _stale():
    row = db.get_meta('collectibles')
    return not row or row[1] < datetime.now(timezone.utc) - timedelta(hours=REFRESH_HOURS)


async def refresh_if_stale(bz):
    """-> how many items were newly mapped (0 when it wasn't time yet)."""
    if not await asyncio.to_thread(_stale):
        return 0
    sem = asyncio.Semaphore(AT_ONCE)

    async def doc(path):
        async with sem:
            st, body, _ = await bz.get(path, blizzard.STATIC)
        return orjson.loads(body) if st == 200 else None

    async def index(path, key):
        d = await doc(path)
        if not d:
            raise RuntimeError(f'{path}: not available')
        return d[key]

    known_toys = {r['ref_id'] for r in await asyncio.to_thread(
        db.fetch_all, "SELECT ref_id FROM ah_collectibles WHERE kind = 'toy'")}
    rows = []
    toys = await index('/data/wow/toy/index', 'toys')
    for d in await asyncio.gather(*(doc(f'/data/wow/toy/{t["id"]}') for t in toys if t['id'] not in known_toys),
                                  return_exceptions=True):
        if isinstance(d, dict) and (d.get('item') or {}).get('id'):
            rows.append((d['item']['id'], 'toy', d['id']))

    names = {'mount': {}, 'pet': {}}
    for m in await index('/data/wow/mount/index', 'mounts'):
        names['mount'].setdefault(_norm(m['name']), m['id'])
    for p in await index('/data/wow/pet/index', 'pets'):
        names['pet'].setdefault(_norm(p['name']), p['id'])
    todo = await asyncio.to_thread(db.fetch_all, f"""
        SELECT i.item_id, i.name, i.subclass_id FROM ah_items i
        WHERE i.class_id = {MISC_CLASS} AND i.subclass_id IN ({PET_SUBCLASS}, {MOUNT_SUBCLASS}) AND i.item_id > 0
          AND i.item_id IN (SELECT item_id FROM ah_item_summary UNION SELECT item_id FROM ah_commodity_summary)
          AND NOT EXISTS (SELECT 1 FROM ah_collectibles c WHERE c.item_id = i.item_id)""")

    async def teaches(item):
        kind = 'mount' if item['subclass_id'] == MOUNT_SUBCLASS else 'pet'
        ref = names[kind].get(_norm(item['name']))
        if not ref:
            d = await doc(f'/data/wow/item/{item["item_id"]}')
            for s in ((d or {}).get('preview_item') or {}).get('spells') or []:
                ref = names[kind].get(_norm((s.get('spell') or {}).get('name')))
                if ref:
                    break
        return (item['item_id'], kind, ref) if ref else None

    found = await asyncio.gather(*(teaches(item) for item in todo), return_exceptions=True)
    rows += [r for r in found if r and not isinstance(r, Exception)]

    def store():
        with db.transaction() as cur:
            if rows:
                execute_values(cur, """INSERT INTO ah_collectibles (item_id, kind, ref_id) VALUES %s
                                       ON CONFLICT (item_id) DO UPDATE SET kind = EXCLUDED.kind, ref_id = EXCLUDED.ref_id""",
                               rows)
        db.set_meta('collectibles', str(len(rows)))
    await asyncio.to_thread(store)
    if rows:
        new_toys = sum(1 for r in rows if r[1] == 'toy')
        logger.info(f'[AH] Collectibles: {new_toys} toys; {len(rows) - new_toys} of {len(todo)} new mount and '
                    f'companion items on sale matched to what they teach')
    return len(rows)
