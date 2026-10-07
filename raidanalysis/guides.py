"""
Mechanic video guides from Mythic Trap (mythictrap.com).

For each boss we raid, find its Mythic Trap page through their sitemap, read
the ability list from the page's Next.js data (spell ID, name, clip, one-line
tip) and cache it in raid_guide_abilities. The admin pages then show a ▶ clip
next to any logged ability that matches - by spell ID, or by name when the
logged damage spell differs from the cast spell Mythic Trap lists.

Clips are shown through Mythic Trap's own embed pages (their branding, ads
and consent dialog intact), never by hot-linking their video files.
"""
import asyncio
import json
import logging
import re
import time

import aiohttp

logger = logging.getLogger(__name__)

SITE = 'https://www.mythictrap.com'
VIDEO_HOST = 'https://assets2.mythictrap.com/'
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; LuminisBot raid tools; guild admin pages)'}
RESCAN_AFTER_DAYS = 3        # Mythic Trap adds clips through the tier
SITEMAP_TTL_SECONDS = 86400

_sitemap_cache = {'at': 0.0, 'boss_urls': []}
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TAG_RE = re.compile(r'<[^>]+>')


def slugify(name):
    """"Nek'zali the Soulcoiler" -> "nekzali-the-soulcoiler" (Mythic Trap's URL style)."""
    name = name.lower().replace("'", '').replace('’', '')
    return re.sub(r'[^a-z0-9]+', '-', name).strip('-')


def name_key(name):
    """Loose ability-name key for matching ("Serpent's Bite" == "serpents bite")."""
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


def _text(html_fragment):
    return re.sub(r'\s+', ' ', _TAG_RE.sub(' ', html_fragment or '')).strip()


async def _get(session, url):
    async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        if resp.status != 200:
            raise RuntimeError(f"Mythic Trap returned {resp.status} for {url}")
        return await resp.text()


async def _boss_urls(session):
    """Every English boss page URL (/en/<raid>/<boss>) listed in the sitemaps, cached for a day."""
    if _sitemap_cache['boss_urls'] and time.time() - _sitemap_cache['at'] < SITEMAP_TTL_SECONDS:
        return _sitemap_cache['boss_urls']
    index = await _get(session, f'{SITE}/sitemap.xml')
    urls = []
    for sitemap in re.findall(r'<loc>([^<]+)</loc>', index):
        page = await _get(session, sitemap)
        urls += re.findall(r'<loc>(https://www\.mythictrap\.com/en/[^/<]+/[^/<]+)</loc>', page)
    urls = [u for u in urls if '/embed' not in u]
    _sitemap_cache.update(at=time.time(), boss_urls=urls)
    return urls


async def find_boss_page(session, encounter_name, zone_name=None):
    """The Mythic Trap page for a boss, matched on the boss slug (raid slugs aren't predictable)."""
    boss_slug = slugify(encounter_name)
    matches = [u for u in await _boss_urls(session) if u.rstrip('/').rsplit('/', 1)[-1] == boss_slug]
    if len(matches) > 1 and zone_name:
        zone_slug = slugify(re.sub(r'^the\s+', '', zone_name, flags=re.I))
        matches = [u for u in matches if f'/{zone_slug}/' in u] or matches
    return matches[0] if matches else None


async def fetch_boss_guide(session, page_url):
    """Abilities on a Mythic Trap boss page: spell ID, name, clip, one-line tip."""
    html = await _get(session, page_url)
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise RuntimeError("Mythic Trap page layout changed (no __NEXT_DATA__)")
    boss = json.loads(match.group(1))['props']['pageProps']['boss']
    raid_slug, boss_slug = boss['raidID'], boss['id']

    abilities, seen = [], set()
    for phase in boss.get('bossPhases') or []:
        for entry in (phase.get('bossAbilitiesWithVideos') or []) + (phase.get('bossAbilities') or []):
            if entry['id'] in seen:
                continue
            seen.add(entry['id'])
            video = entry.get('associatedVideo') or {}
            tip = ' — '.join(filter(None, (
                _text(item.get('titleHTML')) + ': ' + _text(item.get('textHTML'))
                for item in video.get('items') or [])))
            abilities.append({
                'guide_id': entry['id'],
                'spell_id': entry.get('spellID'),
                'name': entry.get('name') or '',
                'category': entry.get('category') or '',
                'subtitle': entry.get('subtitle') or '',
                'tip': tip,
                'description': _text(entry.get('descriptionHTML'))[:600],
                'video_url': VIDEO_HOST + video['videoURL'] if video.get('videoURL') else None,
                'embed_url': f'{SITE}/en/embed-ability/{raid_slug}/{boss_slug}/{entry["id"]}',
            })
    return abilities


# Mythic Trap's "what to do" categories are written for players ("Dodge waves",
# "Help soak", "Use defensives"); these keywords turn them into tags.
_AVOID_RE = re.compile(r"\b(dodge|avoid|move out|move away|run from|run away|stay away|"
                       r"don'?t be too close|safe spot|safe space)\b")
_NON_TANK_RE = re.compile(r'\b(tank|frontal|tail|cone|breath|cleave)')
_AIMED_AWAY_RE = re.compile(r'\b(face|aim)\b.*\baway\b')
_EXPECTED_RE = re.compile(r'\b(soak|heal|defensive|interrupt|dispel|kill|focus|taunt|tank ?swap|'
                          r'break|pick up|put|hit the|burn|match|stay in range)')
# "Move away" from these just means taking less of it - everyone still gets hit.
_DISTANCE_RE = re.compile(r'\b(fall ?off|knockback|boss buff|damage reduction)')
EXPECTED = 'expected'  # taking it is part of the mechanic - never a mistake


def classify(guide):
    """
    Tag for a mechanic from its Mythic Trap category/subtitle:
    'avoidable', 'avoidable_nontank', EXPECTED (soaks, tankbusters, raid damage)
    or None when the wording doesn't say (left to suggestions / officers).
    """
    if not guide:
        return None
    from .analyzer import TAG_AVOIDABLE, TAG_AVOIDABLE_NON_TANK
    category = (guide.get('category') or '').lower()
    subtitle = (guide.get('subtitle') or '').lower()
    if _DISTANCE_RE.search(subtitle):
        return EXPECTED
    if _AVOID_RE.search(category):
        # Frontals, tail swipes and tank soaks are aimed at the tank on purpose.
        return TAG_AVOIDABLE_NON_TANK if _NON_TANK_RE.search(subtitle) else TAG_AVOIDABLE
    if _AIMED_AWAY_RE.search(category) and 'tank' in subtitle:
        return TAG_AVOIDABLE_NON_TANK  # tankbuster the tank points away from the raid
    if _EXPECTED_RE.search(category) or _EXPECTED_RE.search(subtitle) or 'raid' in subtitle \
            or 'tank' in subtitle or 'tank' in category:
        return EXPECTED  # soaks, raid damage, tank debuffs and busters
    return None


# An "avoidable" mechanic that lands on nearly everyone, pull after pull, is
# really raid-wide (or the guide's wording misled us) - don't auto-blame it.
RAID_WIDE_SHARE = 0.9


def auto_tags(guides, abilities):
    """
    {ability_id: tag} from Mythic Trap for the logged abilities of one boss - decided once per ability *name*
    and given to all its spell ids (a mechanic is often logged under several: Evil Eyes' cast and its damage).

    abilities: {ability_id: {'name', 'share'}} where share is the average part
    of the raid hit per pull (None when unknown).
    """
    from .analyzer import AVOIDABLE_TAGS
    by_name = {}
    for ability_id, info in abilities.items():
        by_name.setdefault(info.get('name') or ability_id, []).append(ability_id)
    out = {}
    for name, ids in by_name.items():
        guide = next((g for g in guides if g.get('spell_id') in ids), None) or \
            match_guide(guides, ids[0], name if isinstance(name, str) else '')  # none by id: by name
        tag = classify(guide)
        share = max((abilities[i].get('share') or 0 for i in ids), default=0)
        if tag in AVOIDABLE_TAGS and share >= RAID_WIDE_SHARE:
            continue
        if tag:
            out.update({i: tag for i in ids})
    return out


def match_guide(guides, ability_id, ability_name):
    """Best guide for a logged ability: same spell ID first, then same name; clips preferred."""
    def best(candidates):
        candidates = list(candidates)
        return next((g for g in candidates if g.get('video_url')), candidates[0] if candidates else None)
    by_spell = best(g for g in guides if g.get('spell_id') == ability_id)
    if by_spell:
        return by_spell
    key = name_key(ability_name)
    return best(g for g in guides if key and name_key(g['name']) == key)


async def scan_boss(session, encounter_id, encounter_name, zone_name):
    """Find + cache one boss's guide. Returns the number of abilities stored."""
    from . import db
    try:
        url = await find_boss_page(session, encounter_name, zone_name)
        if not url:
            db.save_guide_scan(encounter_id, None, 'not_found', 0)
            return 0
        abilities = await fetch_boss_guide(session, url)
        db.replace_guide_abilities(encounter_id, abilities)
        db.save_guide_scan(encounter_id, url, 'ok', len(abilities))
        logger.info(f"[RAIDS] Mythic Trap: {len(abilities)} abilities for {encounter_name} ({url})")
        return len(abilities)
    except Exception as e:
        logger.warning(f"[RAIDS] Mythic Trap scan failed for {encounter_name}: {e}")
        db.save_guide_scan(encounter_id, None, 'error', 0, str(e)[:300])
        return 0


async def scan_missing(encounter_ids=None):
    """Scan every boss without a fresh guide (or the given encounters, regardless of age)."""
    from . import db
    bosses = db.bosses_needing_guides(RESCAN_AFTER_DAYS, only=encounter_ids)
    if not bosses:
        return 0
    async with aiohttp.ClientSession() as session:
        total = 0
        for boss in bosses:
            total += await scan_boss(session, boss['encounter_id'], boss['name'], boss['zone_name'])
            await asyncio.sleep(1)  # one page per boss, spaced out
        return total


# A boss's tags are read for every night and character page that shows it, and working them out reads every pull
# of the boss: kept per boss until the data changes (the data version: pulls, guide scans) - or an officer tags
# something (forget(), with the page caches).
_kept = {}


def _data_version():
    from . import sync
    return sync.status.get('data_version') or sync.status.get('last_finished')


def forget():
    """An officer changed tags or rescanned a guide: work them out anew."""
    _kept.clear()


def _cached(kind, encounter_id, make):
    key = (kind, encounter_id, _data_version())
    if key not in _kept:
        if len(_kept) > 500:
            _kept.clear()
        _kept[key] = make()
    return _kept[key]


def tag_rows(encounter_id):
    """db.get_tag_rows, kept like the tags."""
    from . import db
    return _cached('rows', encounter_id, lambda: db.get_tag_rows(encounter_id))


def effective_tags(encounter_id, fresh=False):
    """
    ({ability_id: tag}, {ability_id: 'auto'|'manual'}) for a boss: tags derived
    from Mythic Trap's mechanic categories, with officers' overrides on top - both per ability name, so
    every spell id a mechanic is logged under gets the same tag (an officer's newest call wins).
    Kept until the data changes; fresh: worked out now (the sync, deciding what to fetch).
    """
    from . import db

    def make():
        shares = db.ability_shares(encounter_id)
        return name_tags(auto_tags(db.get_guides(encounter_id), shares),
                         {i: info.get('name') for i, info in shares.items()}, db.get_tag_rows(encounter_id))
    tags, sources = make() if fresh else _cached('tags', encounter_id, make)
    return dict(tags), dict(sources)  # callers' own copies


def apply_death_only(encounter_id, tags, analyses):
    """
    Mark the deaths to this boss's "deaths only" mechanics in these analyses (analyzer.mark_death_only) - by id, and
    by name for an id we haven't seen it logged under (the death itself can be another spell than the damage).
    """
    from . import db
    from .analyzer import TAG_DEATH_ONLY, mark_death_only
    ids = {i for i, t in tags.items() if t == TAG_DEATH_ONLY}
    if not ids:
        return
    names, decided = set(), set()
    if ids:
        for row in tag_rows(encounter_id):  # newest first: the officer's latest call per name
            name = row.get('ability_name')
            if name and name not in decided:
                decided.add(name)
                if row['tag'] == TAG_DEATH_ONLY:
                    names.add(name)
    for analysis in analyses:
        if analysis:
            mark_death_only(analysis, ids, names)


def name_tags(auto, names, overrides):
    """
    Officers' overrides (newest first: [{'ability_id', 'ability_name', 'tag'}]) on top of the automatic tags,
    each one covering every id of its ability's name (names: {ability_id: name} of the logged abilities).
    """
    from . import db
    names = dict(names)
    for row in overrides:
        names.setdefault(row['ability_id'], row.get('ability_name'))
    ids_of = {}
    for ability_id, name in names.items():
        ids_of.setdefault(name or ability_id, set()).add(ability_id)
    tags, sources, decided = dict(auto), {ability_id: 'auto' for ability_id in auto}, set()
    for row in overrides:
        key = names.get(row['ability_id']) or row['ability_id']
        if key in decided:
            continue  # an older call on the same mechanic
        decided.add(key)
        for ability_id in ids_of.get(key, {row['ability_id']}):
            sources[ability_id] = 'manual'
            if row['tag'] in db.TAGS:
                tags[ability_id] = row['tag']
            else:
                tags.pop(ability_id, None)
    return tags, sources


def guide_lookup(encounter_id):
    """(ability_id, name) -> cached Mythic Trap guide for this boss, or None."""
    from . import db
    boss_guides = db.get_guides(encounter_id)
    cache = {}

    def guide_for(ability_id, name):
        key = (ability_id, name)
        if key not in cache:
            cache[key] = match_guide(boss_guides, ability_id, name)
        return cache[key]
    return guide_for
