"""
A player's character - gear, render, item level, M+ score, raid progress - for the player page's
Character tab (web/armory.py draws it).

Same sources as the admin site's character view (character_enrichment.py: Blizzard's API and Raider.IO).
A linked character (wow_characters) reuses that page's cache while it's fresh; anyone else is fetched the
first time someone opens the tab and kept in raid_armory. Raider.IO's gear stands in for Blizzard's when
that isn't there (no API credentials, Blizzard down), and its thumbnail gives the full-body render too.

The realm comes from the linked character, else from the log (WCL's actor list: 'TarrenMill' -> 'tarren-mill').
"""
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REGION = 'eu'
FRESH_HOURS = 6
ICON_URL = 'https://wow.zamimg.com/images/wow/icons/large/{icon}.jpg'

# The in-game character panel: gear down both sides of the model, weapons underneath
LEFT = ('HEAD', 'NECK', 'SHOULDER', 'BACK', 'CHEST', 'WRIST')
RIGHT = ('HANDS', 'WAIST', 'LEGS', 'FEET', 'FINGER_1', 'FINGER_2', 'TRINKET_1', 'TRINKET_2')
WEAPONS = ('MAIN_HAND', 'OFF_HAND')
SLOT_NAMES = {'HEAD': 'Head', 'NECK': 'Neck', 'SHOULDER': 'Shoulders', 'BACK': 'Back', 'CHEST': 'Chest',
              'WRIST': 'Wrists', 'HANDS': 'Hands', 'WAIST': 'Waist', 'LEGS': 'Legs', 'FEET': 'Feet',
              'FINGER_1': 'Ring', 'FINGER_2': 'Ring', 'TRINKET_1': 'Trinket', 'TRINKET_2': 'Trinket',
              'MAIN_HAND': 'Main hand', 'OFF_HAND': 'Off hand'}
RIO_SLOTS = {'head': 'HEAD', 'neck': 'NECK', 'shoulder': 'SHOULDER', 'back': 'BACK', 'chest': 'CHEST', 'wrist': 'WRIST',
             'hands': 'HANDS', 'waist': 'WAIST', 'legs': 'LEGS', 'feet': 'FEET', 'finger1': 'FINGER_1',
             'finger2': 'FINGER_2', 'trinket1': 'TRINKET_1', 'trinket2': 'TRINKET_2', 'mainhand': 'MAIN_HAND',
             'offhand': 'OFF_HAND'}
QUALITY = {'POOR': 0, 'COMMON': 1, 'UNCOMMON': 2, 'RARE': 3, 'EPIC': 4, 'LEGENDARY': 5, 'ARTIFACT': 6, 'HEIRLOOM': 7}


def realm_slug(server):
    """A realm name as WCL / Raider.IO spell it -> Blizzard's slug: 'TarrenMill' / 'Tarren Mill' -> 'tarren-mill'."""
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', '-', server or '')
    return re.sub(r'\s+', '-', s.replace("'", '')).lower()


def _rio(data):
    return ((data.get('sources') or {}).get('raiderio') or data.get('raiderio') or {})


def items(data):
    """{slot: {'slot', 'name', 'ilvl', 'quality' (0-7), 'icon', 'enchant' (text, True or None), 'gems', 'sockets',
    'item_id', 'tier'}} - Blizzard's equipment, else Raider.IO's gear."""
    out = {}
    for it in data.get('equipped_items') or []:
        slot = (it.get('slot') or {}).get('type')
        if slot not in SLOT_NAMES:
            continue
        enchants = [e.get('display_string', '').replace('Enchanted: ', '').split('|')[0].strip()
                    for e in it.get('enchantments') or [] if e.get('display_string')]
        sockets = it.get('sockets') or []
        out[slot] = {'slot': slot, 'name': it.get('name') or '?', 'ilvl': (it.get('level') or {}).get('value'),
                     'quality': QUALITY.get((it.get('quality') or {}).get('type'), 4), 'icon': it.get('icon_url'),
                     'enchant': ', '.join(enchants) or None,
                     'gems': [s['item'].get('name') for s in sockets if s.get('item')], 'sockets': len(sockets),
                     'item_id': (it.get('item') or {}).get('id'), 'tier': bool(it.get('set'))}
    if out:
        return out
    for key, it in ((_rio(data).get('gear') or {}).get('items') or data.get('rio_gear') or {}).items():
        slot = RIO_SLOTS.get(key)
        if not slot or not isinstance(it, dict):
            continue
        out[slot] = {'slot': slot, 'name': it.get('name') or '?', 'ilvl': it.get('item_level'),
                     'quality': it.get('item_quality') or 4,
                     'icon': ICON_URL.format(icon=it['icon']) if it.get('icon') else None,
                     'enchant': True if it.get('enchant') else None, 'gems': list(it.get('gems') or []),
                     'sockets': len(it.get('gems') or []), 'item_id': it.get('item_id'), 'tier': bool(it.get('tier'))}
    return out


def render_url(data):
    """The full-body render: Blizzard's main-raw, else made from Raider.IO's avatar thumbnail."""
    if data.get('character_render_url'):
        return data['character_render_url']
    thumb = data.get('thumbnail_url') or _rio(data).get('thumbnail_url') or ''
    return thumb.split('?')[0].replace('-avatar.jpg', '-main-raw.png') if '-avatar.jpg' in thumb else None


def summary(data):
    """What the header shows: {'ilvl', 'spec', 'class', 'race', 'realm', 'guild', 'mplus', 'raids', 'links'}."""
    rio = _rio(data)
    gear = rio.get('gear') or {}
    ilvl = data.get('equipped_item_level') or data.get('item_level_equipped') or gear.get('item_level_equipped')
    mplus = data.get('mythic_plus_score')
    if mplus is None:
        seasons = rio.get('mythic_plus_scores_by_season') or [{}]
        mplus = ((seasons[0] or {}).get('scores') or {}).get('all')
    raids = []
    for raid, prog in (data.get('raid_progression') or rio.get('raid_progression') or {}).items():
        if isinstance(prog, dict) and prog.get('summary'):
            raids.append((raid.replace('-', ' ').title(), prog['summary']))
    return {'ilvl': ilvl, 'spec': data.get('active_spec') or rio.get('active_spec_name'),
            'class': data.get('character_class') or rio.get('class'), 'race': data.get('race') or rio.get('race'),
            'realm': rio.get('realm') or data.get('realm'), 'guild': (rio.get('guild') or {}).get('name'),
            'mplus': mplus, 'raids': raids[:2], 'raiderio_url': data.get('raiderio_url') or rio.get('profile_url')}


# ============================================================================
# Where it comes from
# ============================================================================

def _fresh(when):
    if not when:
        return False
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() < FRESH_HOURS * 3600


def _linked(name, slug=None):
    """The linked character of that name (on that realm slug) (wow_characters), most recently refreshed first, or None."""
    from . import db
    return db._run("""
        SELECT id, realm_slug, enrichment_cache, last_enriched FROM wow_characters
        WHERE lower(character_name) = lower(%s) AND (%s::text IS NULL OR realm_slug = %s)
        ORDER BY last_enriched DESC NULLS LAST LIMIT 1
    """, (name, slug, slug), fetch='one')


def cached(name, realm=None):
    """
    (data, stale) for a character - the linked character's cache, else ours - or (None, True).
    realm (WCL's spelling or a slug): that realm's character of the name only.
    """
    from . import db
    slug = realm_slug(realm) if realm else None
    linked = _linked(name, slug)
    if linked and linked.get('enrichment_cache') and items(linked['enrichment_cache']):
        return linked['enrichment_cache'], not _fresh(linked.get('last_enriched'))
    row = db.get_armory(name, slug)
    if row:
        return row['data'], not _fresh(row['fetched_at'])
    return None, True


async def load(code, name, realm=None):
    """
    Fetch a character now (Blizzard + Raider.IO) and keep it: (data or None, why-not message or None).
    The realm: the one given, else the linked character's, else the log's (recorded at sync, else asked of WCL).
    """
    import aiohttp
    from character_enrichment import CharacterEnricher
    from . import db, wcl
    realm = realm_slug(realm or (db.realm_in(code, name) if code else None)) or None
    if not realm:
        realm = (_linked(name) or {}).get('realm_slug')
    if not realm and code:
        try:
            async with aiohttp.ClientSession() as session:
                actor = next((a for a in await wcl.get_report_actors(session, code)
                              if a['name'] == name and a.get('type') == 'Player'), None)
        except wcl.WCLError as e:
            logger.warning(f'[RAIDS] Realm of {name} from {code} failed: {e}')
            actor = None
        realm = realm_slug((actor or {}).get('server'))
    if not realm:
        return None, f"Don't know {name}'s realm - link the character with /connectwow to show it here."
    try:
        data = await CharacterEnricher().enrich_character(realm, name, REGION)
    except Exception:
        logger.exception(f'[RAIDS] Character {name}-{realm} failed')
        data = None
    if not data or not items(data):
        return None, f"Couldn't find {name}-{realm} on Blizzard's armory or Raider.IO right now."
    rio = (data.get('sources') or {}).get('raiderio') or {}
    keep = {k: v for k, v in data.items() if k != 'sources'}
    keep['raiderio'] = {k: rio.get(k) for k in ('gear', 'thumbnail_url', 'profile_url', 'realm', 'guild', 'class',
                                                'race', 'active_spec_name', 'raid_progression',
                                                'mythic_plus_scores_by_season') if rio.get(k) is not None}
    db.save_armory(name, realm, keep)
    return keep, None
