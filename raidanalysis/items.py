"""
Item tooltips for the character panels (web/armory.py): Wowhead's tooltip for the exact item a character
wears - its item level, bonus ids (stats, sockets, upgrade track), enchant and gems - drawn like the game's.

Wowhead's own script lights up an item set's pieces and bonuses in the browser (pcs=); we do that here
instead: the set's "(n/5)", the pieces they wear, the bonuses they have - for their spec only, like in game.
The HTML comes from a third party, so it's rebuilt from an allow-list (sanitize) before any page sees it.

Served by GET /raids/item/{id}?<query> (routes.handle_item): only for item / query pairs our pages showed
(offer), rate limited, and kept in memory.
"""
import logging
import re
import time
from html import escape
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

TOOLTIP_URL = 'https://nether.wowhead.com/tooltip/item/{id}'
HEADERS = {'User-Agent': 'LuminisBot raid analysis (item tooltips)'}
ICON_URL = 'https://wow.zamimg.com/images/wow/icons/large/{icon}.jpg'
CACHE_MAX = 3000
OFFERED_MAX = 20000
ON_DEMAND_PER_MINUTE = 60

# Wowhead / Blizzard specialization ids: (class, spec without spaces, lower case) -> id
SPEC_IDS = {
    ('deathknight', 'blood'): 250, ('deathknight', 'frost'): 251, ('deathknight', 'unholy'): 252,
    ('demonhunter', 'havoc'): 577, ('demonhunter', 'vengeance'): 581, ('demonhunter', 'devourer'): 1480,
    ('druid', 'balance'): 102, ('druid', 'feral'): 103, ('druid', 'guardian'): 104, ('druid', 'restoration'): 105,
    ('evoker', 'devastation'): 1467, ('evoker', 'preservation'): 1468, ('evoker', 'augmentation'): 1473,
    ('hunter', 'beastmastery'): 253, ('hunter', 'marksmanship'): 254, ('hunter', 'survival'): 255,
    ('mage', 'arcane'): 62, ('mage', 'fire'): 63, ('mage', 'frost'): 64,
    ('monk', 'brewmaster'): 268, ('monk', 'windwalker'): 269, ('monk', 'mistweaver'): 270,
    ('paladin', 'holy'): 65, ('paladin', 'protection'): 66, ('paladin', 'retribution'): 70,
    ('priest', 'discipline'): 256, ('priest', 'holy'): 257, ('priest', 'shadow'): 258,
    ('rogue', 'assassination'): 259, ('rogue', 'outlaw'): 260, ('rogue', 'subtlety'): 261,
    ('shaman', 'elemental'): 262, ('shaman', 'enhancement'): 263, ('shaman', 'restoration'): 264,
    ('warlock', 'affliction'): 265, ('warlock', 'demonology'): 266, ('warlock', 'destruction'): 267,
    ('warrior', 'arms'): 71, ('warrior', 'fury'): 72, ('warrior', 'protection'): 73,
}


# The primary stat by spec ("+167 [Agility or Intellect]" shows as theirs, like in game); the rest: Agility
INTELLECT_SPECS = {102, 105, 1467, 1468, 1473, 1480, 62, 63, 64, 270, 65, 256, 257, 258, 262, 264, 265, 266, 267}
STRENGTH_SPECS = {250, 251, 252, 66, 70, 71, 72, 73}
_PRIMARY = re.compile(r'\[((?:Agility|Strength|Intellect)(?: or (?:Agility|Strength|Intellect))+)\]')


def primary_stat(spec):
    if not spec:
        return None
    return 'Intellect' if spec in INTELLECT_SPECS else 'Strength' if spec in STRENGTH_SPECS else 'Agility'


def with_primary(html, spec):
    """'+167 [Agility or Intellect]' -> '+167 Agility' for an Agility spec (left alone when it isn't one of them)."""
    stat = primary_stat(spec)
    if not stat:
        return html
    return _PRIMARY.sub(lambda m: stat if stat in m.group(1).split(' or ') else m.group(0), html)


def spec_id(cls, spec):
    """'Hunter' / 'Death Knight', 'Marksmanship' / 'Beast Mastery' -> the spec id, or None."""
    key = (re.sub(r'\s+', '', cls or '').lower(), re.sub(r'\s+', '', spec or '').lower())
    return SPEC_IDS.get(key)


_IDS = re.compile(r'^\d{1,7}(:\d{1,7}){0,39}$')
_KEYS = ('bonus', 'ilvl', 'ench', 'gems', 'pcs', 'spec')
_WOWHEAD_KEYS = ('bonus', 'ilvl', 'ench', 'gems')  # what Wowhead's tooltip takes; pcs and spec are ours


def query(bonus=(), ilvl=None, ench=None, gems=(), pcs=(), spec=None):
    """The tooltip's query string, in one canonical order (it's also the cache and offer key)."""
    parts = {'bonus': ':'.join(str(int(b)) for b in bonus or ()), 'ilvl': str(int(ilvl)) if ilvl else '',
             'ench': str(int(ench)) if ench else '', 'gems': ':'.join(str(int(g)) for g in gems or ()),
             'pcs': ':'.join(str(int(p)) for p in sorted(set(pcs or ()))), 'spec': str(int(spec)) if spec else ''}
    return '&'.join(f'{k}={v}' for k, v in parts.items() if v)


def parse_query(args):
    """A request's query args -> the canonical query string, or None when something isn't a plain id list."""
    clean = {}
    for key in _KEYS:
        value = args.get(key)
        if value is None or value == '':
            continue
        if not _IDS.match(value):
            return None
        clean[key] = value
    return '&'.join(f'{k}={clean[k]}' for k in _KEYS if k in clean)


# ============================================================================
# Which tooltips may be fetched (the endpoint is public)
# ============================================================================

_offered = set()
_cache = {}
_fetch_times = []


def offer(item_id, q):
    """A page shows this item: its tooltip may be fetched on demand."""
    if len(_offered) >= OFFERED_MAX:
        _offered.clear()
    _offered.add((int(item_id), q))


def may_fetch(item_id, q):
    if (item_id, q) not in _offered:
        return False
    now = time.time()
    _fetch_times[:] = [t for t in _fetch_times if now - t < 60]
    if len(_fetch_times) >= ON_DEMAND_PER_MINUTE:
        return False
    _fetch_times.append(now)
    return True


def cached(item_id, q):
    return _cache.get((item_id, q))


async def tooltip(item_id, q):
    """{'name', 'quality', 'icon', 'html'} for one item as worn (q: query()), or None. Kept in memory."""
    import aiohttp
    key = (item_id, q)
    if key in _cache:
        return _cache[key]
    args = dict(part.split('=', 1) for part in q.split('&') if '=' in part)
    params = {'dataEnv': 1, 'locale': 0, **{k: v for k, v in args.items() if k in _WOWHEAD_KEYS}}
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get(TOOLTIP_URL.format(id=int(item_id)), params=params,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning(f'[RAIDS] Item tooltip {item_id} failed: HTTP {resp.status}')
                    return None
                data = await resp.json(content_type=None)
    except Exception as e:
        logger.warning(f'[RAIDS] Item tooltip {item_id} failed: {e}')
        return None
    pcs = set(args['pcs'].split(':')) if args.get('pcs') else set()
    spec = int(args['spec']) if args.get('spec') else None
    html = sanitize(with_primary(with_set(data.get('tooltip') or '', pcs, spec), spec))
    icon = data.get('icon')
    result = {'name': data.get('name') or '', 'quality': data.get('quality'), 'html': html,
              'icon': ICON_URL.format(icon=icon) if icon and re.match(r'^[\w.-]+$', icon) else None}
    if len(_cache) >= CACHE_MAX:
        _cache.clear()
    _cache[key] = result
    return result


# ============================================================================
# Item sets: what Wowhead's script would do in the browser
# ============================================================================

_SET_PIECE = re.compile(r'<span><!--si(\d+)-->')
_SET_COUNT = re.compile(r'\((\d+)/(\d+)\)</span>')
_SPEC_LINE = re.compile(r'<!--itemeffectspec(\d+):\d+-->(.*?)<!--itemeffectspec-->(?:<br ?/?>)?', re.S)
_BONUS = re.compile(r'<span>\((\d+)\) Set')


def with_set(html, pcs, spec=None):
    """
    The tooltip's item set as the game shows it: "(worn/size)", the pieces they wear in yellow, the bonuses
    they have in green (the rest grey) - and only their spec's bonuses when we know it (Wowhead lists every spec's).
    pcs: the item ids (strings) of the set pieces they wear.
    """
    if '<!--si' not in html:
        return html
    pieces = set(_SET_PIECE.findall(html))
    worn = len(pieces & pcs)
    html = _SET_PIECE.sub(lambda m: '<span class="q8">' if m.group(1) in pcs else '<span>', html)
    html = _SET_COUNT.sub(lambda m: f'({worn}/{m.group(2)})</span>', html, count=1)
    lines = _SPEC_LINE.findall(html)
    if lines:
        ours = [body for s, body in lines if spec and int(s) == spec] or [body for _, body in lines]
        block = ''.join(_BONUS.sub(lambda m: f'<span class="{"q2" if int(m.group(1)) <= worn else "q0"}">'
                                             f'({m.group(1)}) Set', body, count=1) + '<br>' for body in ours)
        first = _SPEC_LINE.search(html)
        html = html[:first.start()] + block + _SPEC_LINE.sub('', html[first.start():])
    else:
        html = _BONUS.sub(lambda m: f'<span class="{"q2" if int(m.group(1)) <= worn else "q0"}">({m.group(1)}) Set', html)
    return html


# ============================================================================
# Sanitizing: rebuild the tooltip from an allow-list
# ============================================================================

_TAGS = {'table', 'tr', 'td', 'th', 'b', 'span', 'br', 'div', 'a', 'img', 'small'}
_CLASS = re.compile(r'^(q\d?|socket-[a-z-]+|indent|c\d{1,2}|money(gold|silver|copper)|whtt-[a-z-]+)$')
_DROP_CLASSES = {'whtt-sellprice', 'whtt-extra'}       # sell price, "Dropped by", drop chance: not in game
_IMG_HOST = 'https://wow.zamimg.com/'
_BG = re.compile(r'background-image:\s*url\((https://wow\.zamimg\.com/[\w./-]+)\)')
_COLOR = re.compile(r'(?<![-\w])color:\s*(#[0-9a-fA-F]{3,6})')


class _Clean(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0  # depth inside a dropped element

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag not in ('br', 'img'):
                self.skip += 1
            return
        attrs = dict(attrs)
        classes = (attrs.get('class') or '').split()
        if _DROP_CLASSES & set(classes):
            if tag not in ('br', 'img'):
                self.skip = 1
            return
        if tag not in _TAGS:
            return
        if tag == 'img':
            src = attrs.get('src') or ''
            if src.startswith(_IMG_HOST) and re.match(r'^[\w:/.-]+$', src):
                self.out.append(f'<img src="{escape(src)}" alt="" class="tt-img">')
            return
        if tag == 'br':
            self.out.append('<br>')
            return
        tag = 'span' if tag == 'a' else tag  # Wowhead's links point at Wowhead-relative pages
        keep = [c for c in classes if _CLASS.match(c)]
        style = []
        bg = _BG.search(attrs.get('style') or '')
        if bg:
            style.append(f'background-image:url({bg.group(1)})')
        color = _COLOR.search(attrs.get('style') or '')
        if color:
            style.append(f'color:{color.group(1)}')
        attr = (f' class="{escape(" ".join(keep))}"' if keep else '') + (f' style="{escape(";".join(style))}"' if style else '')
        if tag == 'table' and attrs.get('width') == '100%':
            attr += ' width="100%"'
        self.out.append(f'<{tag}{attr}>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= 1
            return
        if tag in _TAGS and tag not in ('br', 'img'):
            self.out.append(f'</{"span" if tag == "a" else tag}>')

    def handle_data(self, data):
        if not self.skip:
            self.out.append(escape(data))


def sanitize(html):
    """Wowhead's tooltip HTML, rebuilt from an allow-list: layout tags, quality classes, zamimg images."""
    parser = _Clean()
    parser.feed(html)
    parser.close()
    out = ''.join(parser.out)
    return re.sub(r'(<br>\s*){3,}', '<br><br>', out)
