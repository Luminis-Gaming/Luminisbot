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
SHEET_VERSION = 2  # a stored copy from before load() kept the stat sheet, set bonuses and raid order is fetched again
OUR_RAIDS_SECONDS = 600
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
    """
    {slot: {'slot', 'name', 'ilvl', 'quality' (0-7), 'icon', 'enchant' (text, True or None), 'gems', 'sockets',
    'item_id', 'tier', 'tooltip' (items.query() for its Wowhead tooltip: as worn, set pieces lit)}} - Blizzard's
    equipment, else Raider.IO's gear.
    """
    out = _items(data)
    from . import items as tooltips
    spec = tooltips.spec_id(*_class_spec(data))
    pcs = [it['item_id'] for it in out.values() if it.get('set_piece') and it['item_id']]
    for it in out.values():
        it['tooltip'] = tooltips.query(it.pop('bonus', ()), it['ilvl'], it.pop('ench_id', None), it.pop('gem_ids', ()),
                                       pcs if it.pop('set_piece', False) else (), spec)
    return out


def _class_spec(data):
    rio = _rio(data)
    return (data.get('character_class') or rio.get('class') or '',
            data.get('active_spec') or rio.get('active_spec_name') or '')


def _items(data):
    out = {}
    rio_items = (_rio(data).get('gear') or {}).get('items') or data.get('rio_gear') or {}
    # Blizzard's item icons each take a request of their own (character_enrichment) and some fail or time out -
    # Raider.IO's gear names the same item's icon: the fallback
    rio_icons = {it.get('item_id'): ICON_URL.format(icon=it['icon']) for it in rio_items.values()
                 if isinstance(it, dict) and it.get('item_id') and it.get('icon')}
    for it in data.get('equipped_items') or []:
        slot = (it.get('slot') or {}).get('type')
        if slot not in SLOT_NAMES:
            continue
        enchants = [e.get('display_string', '').replace('Enchanted: ', '').split('|')[0].strip()
                    for e in it.get('enchantments') or [] if e.get('display_string')]
        sockets = it.get('sockets') or []
        permanent = next((e for e in it.get('enchantments') or []
                          if (e.get('enchantment_slot') or {}).get('type') in (None, 'PERMANENT')), {})
        out[slot] = {'slot': slot, 'name': it.get('name') or '?', 'ilvl': (it.get('level') or {}).get('value'),
                     'quality': QUALITY.get((it.get('quality') or {}).get('type'), 4),
                     'icon': it.get('icon_url') or rio_icons.get((it.get('item') or {}).get('id')),
                     'enchant': ', '.join(enchants) or None,
                     'gems': [s['item'].get('name') for s in sockets if s.get('item')], 'sockets': len(sockets),
                     'item_id': (it.get('item') or {}).get('id'), 'tier': bool(it.get('set')),
                     'set_piece': bool(it.get('set')), 'bonus': it.get('bonus_list') or (),
                     'ench_id': permanent.get('enchantment_id'),
                     'gem_ids': [s['item']['id'] for s in sockets if (s.get('item') or {}).get('id')]}
    if out:
        return out
    for key, it in rio_items.items():
        slot = RIO_SLOTS.get(key)
        if not slot or not isinstance(it, dict):
            continue
        enchant = it.get('enchant') if isinstance(it.get('enchant'), int) else None
        names = [re.sub(r'^Enchant [^-]+ - ', '', e['name']) for e in it.get('enchants_detail') or []
                 if isinstance(e, dict) and e.get('name')]
        out[slot] = {'slot': slot, 'name': it.get('name') or '?', 'ilvl': it.get('item_level'),
                     'quality': it.get('item_quality') or 4,
                     'icon': ICON_URL.format(icon=it['icon']) if it.get('icon') else None,
                     'enchant': ', '.join(names) or (True if it.get('enchant') else None),
                     'gems': [g.get('name') for g in it.get('gems_detail') or [] if isinstance(g, dict)] or list(it.get('gems') or []),
                     'sockets': len(it.get('gems') or []), 'item_id': it.get('item_id'), 'tier': bool(it.get('tier')),
                     'set_piece': bool(it.get('tier')), 'bonus': [b for b in it.get('bonuses') or () if isinstance(b, int)],
                     'ench_id': enchant, 'gem_ids': [g for g in it.get('gems') or () if isinstance(g, int)]}
    return out


def render_url(data):
    """The full-body render: Blizzard's main-raw, else made from Raider.IO's avatar thumbnail."""
    if data.get('character_render_url'):
        return data['character_render_url']
    thumb = data.get('thumbnail_url') or _rio(data).get('thumbnail_url') or ''
    return thumb.split('?')[0].replace('-avatar.jpg', '-main-raw.png') if '-avatar.jpg' in thumb else None


def avatar_url(data):
    """The small head portrait (84 px, Blizzard's avatar.jpg) - pinned characters' chips. None when unknown."""
    url = data.get('avatar_url') or data.get('thumbnail_url') or _rio(data).get('thumbnail_url') or ''
    url = url.split('?')[0]  # Raider.IO adds ?alt= (a placeholder for missing ones)
    return url if url.endswith('-avatar.jpg') else None


PORTRAITS_SECONDS = 6 * 3600
_portraits = {'at': 0, 'data': None}  # kept a while; load() puts a fetched character's new face in by itself


def portraits():
    """
    {(lower-case name, realm slug): {'render', 'avatar'}} for every character we have pictures of (stored or
    linked) - the front page's character wall. One query, only the picture fields; kept PORTRAITS_SECONDS.
    """
    import time
    if _portraits['data'] is not None and time.time() - _portraits['at'] < PORTRAITS_SECONDS:
        return _portraits['data']
    from . import db
    out = {}
    for row in db.armory_images():
        data = {'character_render_url': row['render'], 'avatar_url': row['avatar'], 'thumbnail_url': row['thumb'],
                'raiderio': {'thumbnail_url': row['rio_thumb']} if row['rio_thumb'] else {}}
        _add_portrait(out, (row['name_key'], row['realm']), data)
    _portraits.update(at=time.time(), data=out)
    return out


def _add_portrait(out, key, data):
    found = {'render': render_url(data), 'avatar': avatar_url(data)}
    if found['render'] or found['avatar']:
        out[key] = {k: v or (out.get(key) or {}).get(k) for k, v in found.items()}


def summary(data):
    """What the header shows: {'ilvl', 'spec', 'class', 'race', 'realm', 'guild', 'mplus', 'raids', 'links'}."""
    rio = _rio(data)
    gear = rio.get('gear') or {}
    ilvl = data.get('equipped_item_level') or data.get('item_level_equipped') or gear.get('item_level_equipped')
    mplus = data.get('mythic_plus_score')
    if mplus is None:
        seasons = rio.get('mythic_plus_scores_by_season') or [{}]
        mplus = ((seasons[0] or {}).get('scores') or {}).get('all')
    progression = data.get('raid_progression') or rio.get('raid_progression') or {}
    raids = [(raid.replace('-', ' ').title(), progression[raid]['summary']) for raid in raid_order(data, progression)
             if isinstance(progression.get(raid), dict) and progression[raid].get('summary')]
    return {'ilvl': ilvl, 'spec': data.get('active_spec') or rio.get('active_spec_name'),
            'class': data.get('character_class') or rio.get('class'), 'race': data.get('race') or rio.get('race'),
            'realm': rio.get('realm') or data.get('realm'), 'guild': (rio.get('guild') or {}).get('name'),
            'mplus': mplus, 'raids': raids[:2], 'raiderio_url': data.get('raiderio_url') or rio.get('profile_url')}


def raid_order(data, progression):
    """
    Raider.IO's raids, the current ones first. The order it sends (newest first) doesn't survive being stored
    (Postgres JSONB sorts object keys - "sporefall" before "the-venomous-abyss"), so load() keeps it as a list
    ('raid_order'); and the raids we have logs of come first either way, the latest tier leading.
    """
    kept = [k for k in data.get('raid_order') or [] if k in progression]
    order = kept + [k for k in progression if k not in kept]
    ours = _our_raids()
    return sorted(order, key=lambda k: ours.index(k) if k in ours else len(ours))  # stable: the rest keep their order


_our_raids_cache = [0.0, []]


def _our_raids():
    """Our logs' raid tiers as Raider.IO slugs ('the-venomous-abyss'), newest first (kept OUR_RAIDS_SECONDS)."""
    import time
    if time.time() - _our_raids_cache[0] < OUR_RAIDS_SECONDS:
        return _our_raids_cache[1]
    try:
        from . import db
        slugs = [re.sub(r'[^a-z0-9]+', '-', (t['zone_name'] or '').lower().replace("'", '')).strip('-')
                 for t in db.list_tiers()]
    except Exception:
        slugs = []
    _our_raids_cache[:] = [time.time(), [s for s in slugs if s]]
    return _our_raids_cache[1]


RATING_OVERFLOW = 2 ** 31  # Blizzard's old 'rating' could overflow (4294967066): not a rating


def _rating(value):
    """
    A stat's rating from Blizzard's statistics: 'rating_normalized' - they replaced 'rating', which could overflow
    - else the old 'rating' (copies stored before the change); a plain number as is. 0 when unknown.
    """
    if isinstance(value, dict):
        value = value.get('rating_normalized', value.get('rating'))
    return value if isinstance(value, (int, float)) and 0 < value < RATING_OVERFLOW else 0


def stats(data):
    """
    The character sheet's stats, from Blizzard's armory (statistics), or None without them:
    {'primary': (name, value), 'stamina', 'health', 'armor', 'power': (name, value) or None,
     'secondary': [(name, percent, rating)], 'tertiary': [(name, percent, rating)]} - tertiary only when > 0.
    """
    st = data.get('statistics')
    if not isinstance(st, dict) or not st.get('health'):
        return None

    def eff(key):
        v = st.get(key)
        return (v.get('effective') or 0) if isinstance(v, dict) else (v or 0)

    def rated(key):
        v = st.get(key) or {}
        return (v.get('value') or 0, _rating(v)) if isinstance(v, dict) else (0, 0)

    primary = max((('Strength', eff('strength')), ('Agility', eff('agility')), ('Intellect', eff('intellect'))),
                  key=lambda p: p[1])
    caster = primary[0] == 'Intellect'
    crit, haste = rated('spell_crit' if caster else 'melee_crit'), rated('spell_haste' if caster else 'melee_haste')
    secondary = [('Critical Strike', *crit), ('Haste', *haste), ('Mastery', *rated('mastery')),
                 ('Versatility', st.get('versatility_damage_done_bonus') or 0, _rating(st.get('versatility')))]
    tertiary = []
    for name, key in (('Leech', 'lifesteal'), ('Avoidance', 'avoidance'), ('Speed', 'speed')):
        v = st.get(key) or {}
        pct = (v.get('value') or v.get('rating_bonus') or 0) if isinstance(v, dict) else 0
        if pct > 0:
            tertiary.append((name, pct, _rating(v)))
    power = (st.get('power_type') or {}).get('name')
    return {'primary': primary, 'stamina': eff('stamina'), 'health': st.get('health') or 0, 'armor': eff('armor'),
            'power': (power, st.get('power') or 0) if power and st.get('power') else None,
            'secondary': secondary, 'tertiary': tertiary}


def tier_set(data):
    """
    The item set they wear: {'name', 'worn', 'size', 'bonuses': [{'count', 'text', 'active'}]} or None -
    Blizzard's equipment says it all; otherwise the Wowhead copy kept at load() ('tier_set').
    """
    for it in data.get('equipped_items') or []:
        s = it.get('set')
        if not s or not s.get('effects'):
            continue
        pieces = s.get('items') or []
        bonuses = []
        for e in s['effects']:
            # Blizzard: "Set: Rising Sun Kick deals..." (sometimes "(2) Set: ...") - the count is shown on its own
            text = re.sub(r'^(\(\d+\)\s*)?Set\s*:?\s*', '', e.get('display_string') or '').strip()
            bonuses.append({'count': e.get('required_count') or 0, 'text': text, 'active': bool(e.get('is_active'))})
        return {'name': (s.get('item_set') or {}).get('name') or 'Tier set',
                'worn': sum(1 for p in pieces if p.get('is_equipped')), 'size': len(pieces), 'bonuses': bonuses}
    kept = data.get('tier_set')
    return kept if isinstance(kept, dict) and kept.get('bonuses') else None


_WH_SET_NAME = re.compile(r'<a href="/item-set=\d+[^"]*"[^>]*>([^<]+)</a> \((\d+)/(\d+)\)')
_WH_BONUS = re.compile(r'<span(?: class="q\d")?>\((\d+)\) Set(?: [^:<]*)?: (.*?)</span>(?:<!--itemeffectspec-->)?<br', re.S)


def _set_from_wowhead(raw, worn, spec):
    """The set block of a Wowhead item tooltip -> tier_set()'s shape (their spec's bonuses only), or None."""
    from . import items as tooltips
    name = _WH_SET_NAME.search(raw)
    if not name:
        return None
    lines = tooltips._SPEC_LINE.findall(raw)
    if lines:
        bodies = [body for s, body in lines if spec and int(s) == spec] or [body for _, body in lines]
        block = ''.join(body + '<br' for body in bodies)
    else:
        block = raw
    bonuses = []
    for count, text in _WH_BONUS.findall(block):
        clean = re.sub(r'<[^>]+>', '', text)
        clean = re.sub(r'<!--.*?-->', '', clean).strip()
        bonuses.append({'count': int(count), 'text': clean, 'active': int(count) <= worn})
    return {'name': name.group(1), 'worn': worn, 'size': int(name.group(3)), 'bonuses': bonuses} if bonuses else None


async def _wowhead_set(data):
    """No Blizzard set info: read the set from one worn tier piece's Wowhead tooltip."""
    import aiohttp
    from . import items as tooltips
    gear = _items(data)
    pieces = [it for it in gear.values() if it.get('set_piece') and it.get('item_id')]
    if not pieces:
        return None
    try:
        async with aiohttp.ClientSession(headers=tooltips.HEADERS) as session:
            async with session.get(tooltips.TOOLTIP_URL.format(id=int(pieces[0]['item_id'])),
                                   params={'dataEnv': 1, 'locale': 0}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                raw = (await resp.json(content_type=None)).get('tooltip') or '' if resp.status == 200 else ''
    except Exception as e:
        logger.warning(f'[RAIDS] Tier set from Wowhead failed: {e}')
        return None
    return _set_from_wowhead(raw, len(pieces), tooltips.spec_id(*_class_spec(data)))


def blizzard_configured():
    try:
        from character_enrichment import BLIZZARD_CLIENT_ID, BLIZZARD_CLIENT_SECRET
        return bool(BLIZZARD_CLIENT_ID and BLIZZARD_CLIENT_SECRET)
    except Exception:
        return False


async def _statistics(realm, name):
    """Blizzard's character statistics (the stat sheet), or None - e.g. without API credentials."""
    import aiohttp
    try:
        from character_enrichment import BLIZZARD_CLIENT_ID, CharacterEnricher
        if not BLIZZARD_CLIENT_ID:
            return None
        token = await CharacterEnricher().get_blizzard_token()
        if not token:
            return None
        url = f'https://{REGION}.api.blizzard.com/profile/wow/character/{realm}/{name.lower()}/statistics'
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={'Authorization': f'Bearer {token}'},
                                   params={'namespace': f'profile-{REGION}', 'locale': 'en_US'},
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return await resp.json() if resp.status == 200 else None
    except Exception as e:
        logger.warning(f'[RAIDS] Statistics of {name}-{realm} failed: {e}')
        return None


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
    (data, stale) for a character - the newer of the linked character's cache (the admin site's character
    view) and ours - or (None, True). realm (WCL's spelling or a slug): that realm's character of the name only.
    Stale: older than FRESH_HOURS, or our copy (which brings the stat sheet and set bonuses) missing or old.
    """
    from . import db
    slug = realm_slug(realm) if realm else None
    linked = _linked(name, slug)
    own = db.get_armory(name, slug)
    own_ok = bool(own and isinstance(own['data'], dict) and items(own['data']))
    linked_ok = bool(linked and linked.get('enrichment_cache') and items(linked['enrichment_cache']))
    if not own_ok and not linked_ok:
        return None, True
    if own_ok and (not linked_ok or _when(own['fetched_at']) >= _when(linked.get('last_enriched'))):
        data, fetched = own['data'], own['fetched_at']
    else:  # a linked character refreshed on the admin site since we last fetched it
        data, fetched = dict(linked['enrichment_cache']), linked.get('last_enriched')
        if own_ok:
            for key in ('statistics', 'tier_set', 'raid_order'):
                if own['data'].get(key) and not data.get(key):
                    data[key] = own['data'][key]
    stale = (not _fresh(fetched) or not own_ok or not _fresh(own['fetched_at'])
             or own['data'].get('sheet_v') != SHEET_VERSION)
    return data, stale


def _when(dt):
    """A stored time, comparable: naive ones are UTC; none is the oldest."""
    if not dt:
        return datetime.min.replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
    import asyncio
    try:
        data, statistics = await asyncio.gather(CharacterEnricher().enrich_character(realm, name, REGION),
                                                _statistics(realm, name))
    except Exception:
        logger.exception(f'[RAIDS] Character {name}-{realm} failed')
        data = statistics = None
    if not data or not items(data):
        return None, f"Couldn't find {name}-{realm} on Blizzard's armory or Raider.IO right now."
    rio = (data.get('sources') or {}).get('raiderio') or {}
    keep = {k: v for k, v in data.items() if k != 'sources'}
    keep['raiderio'] = {k: rio.get(k) for k in ('gear', 'thumbnail_url', 'profile_url', 'realm', 'guild', 'class',
                                                'race', 'active_spec_name', 'raid_progression',
                                                'mythic_plus_scores_by_season') if rio.get(k) is not None}
    if statistics:
        keep['statistics'] = statistics
    keep['sheet_v'] = SHEET_VERSION
    keep['raid_order'] = list((rio.get('raid_progression') or {}).keys())  # Raider.IO's order: newest first
    if not tier_set(keep):
        keep['tier_set'] = await _wowhead_set(keep)
    db.save_armory(name, realm, keep)
    if _portraits['data'] is not None:  # their (new) face on the character wall, without reading everyone again
        _add_portrait(_portraits['data'], (name.lower(), realm), keep)
    return keep, None
