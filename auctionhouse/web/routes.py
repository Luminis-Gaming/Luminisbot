"""
The public auction house pages:

  GET /ah                       search every item on sale in EU (results from /ah/api/search)
  GET /ah/api/search            the results, as JSON
  GET /ah/item/{id}             one item: its stat rolls, where it sells best, every listing on your realm, history
  GET /ah/tooltip/{id}?bonus=   an item's tooltip for one roll (raidanalysis.items: Wowhead, sanitized)
  GET /ah/static/...            the stylesheet and script (static/), cached for a year under a content hash

Mounted by register_routes(app) from oauth_server.create_app(), so it can borrow the raid pages' banner, headers
and tooltip proxy. Everything is read-only; the collector (collector.py) is the only writer.
"""
import asyncio
import hashlib
import html
import json
import logging
import time
from pathlib import Path

from aiohttp import web

from .. import db

logger = logging.getLogger(__name__)

STATIC = Path(__file__).parent / 'static'
PAGE_SIZE = 100
CACHE_SECONDS = 300
PAIRS = ('Critical Strike/Haste', 'Critical Strike/Mastery', 'Critical Strike/Versatility', 'Haste/Mastery',
         'Haste/Versatility', 'Mastery/Versatility')
TERTIARY = ('Speed', 'Leech', 'Avoidance', 'Indestructible')
EXPANSIONS = ['Classic', 'The Burning Crusade', 'Wrath of the Lich King', 'Cataclysm', 'Mists of Pandaria',
              'Warlords of Draenor', 'Legion', 'Battle for Azeroth', 'Shadowlands', 'Dragonflight', 'The War Within',
              'Midnight']
SLOTS = {1: 'Head', 2: 'Neck', 3: 'Shoulder', 4: 'Shirt', 5: 'Chest', 6: 'Waist', 7: 'Legs', 8: 'Feet', 9: 'Wrist',
         10: 'Hands', 11: 'Finger', 12: 'Trinket', 13: 'One-Hand', 14: 'Off Hand', 15: 'Ranged', 16: 'Back',
         17: 'Two-Hand', 18: 'Bag', 19: 'Tabard', 20: 'Chest', 21: 'Main Hand', 22: 'Off Hand', 23: 'Held In Off-hand',
         25: 'Thrown', 26: 'Ranged', 28: 'Relic', 29: 'Profession Tool', 30: 'Profession Equipment'}
BINDING = {1: 'Binds when picked up', 2: 'Binds when equipped', 3: 'Binds when used', 4: 'Quest item',
           7: 'Binds to Blizzard account', 8: 'Binds to Blizzard account', 9: 'Warbound until equipped'}
SORTS = {'name': 'i.name', 'ilvl': 'r.ilvl_max', 'req': 'i.req_level', 'lo': 'r.lo', 'med': 'r.med', 'hi': 'r.hi',
         'realms': 'r.realms', 'spread': 'r.hi::float / GREATEST(r.lo, 1)', 'here': 'h.here',
         'vs': 'h.here::float / NULLIF(r.med, 0)', 'qty': 'h.here_n'}
NO_WALL = 'NOT EXISTS (SELECT 1 FROM ah_walls w WHERE w.item_id = l.item_id AND w.price = l.buyout)'


def _read(name):
    return (STATIC / name).read_text(encoding='utf-8')


def _assets():
    from raidanalysis.web import brand
    css, js = brand.CSS + _read('ah.css'), brand.JS + _read('ah.js')
    digest = lambda text: hashlib.sha256(text.encode()).hexdigest()[:12]  # noqa: E731
    return css, js, f'/ah/static/ah-{digest(css)}.css', f'/ah/static/ah-{digest(js)}.js'


CSS, JS, CSS_URL, JS_URL = _assets()


def register_routes(app):
    app.router.add_get('/ah', handle_search_page)
    app.router.add_get('/ah/api/search', handle_search_api)
    app.router.add_get('/ah/item/{item_id}', handle_item_page)
    app.router.add_get('/ah/tooltip/{item_id}', handle_tooltip)
    app.router.add_get(CSS_URL, handle_css)
    app.router.add_get(JS_URL, handle_js)


def _headers():
    from raidanalysis.web.routes import SECURITY_HEADERS
    return SECURITY_HEADERS


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def icon_url(row):
    if row.get('icon'):
        return row['icon']
    return f'https://render.worldofwarcraft.com/eu/icons/56/{row["icon_file"]}.jpg' if row.get('icon_file') else None


# ============================================================================
# Shared, slow-changing data (cached a few minutes: the collector changes it hourly)
# ============================================================================

_cache = {}


def _cached(key, build):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = build()
    _cache[key] = (time.monotonic(), value)
    return value


def _realms():
    return {str(r['cr']): {'names': r['names'], 'locale': r['locale'] or '', 'pop': r['population'] or ''}
            for r in db.realm_groups()}


def _class_names():
    return {(r['class_id'], r['subclass_id']): (r['class_name'], r['subclass_name'])
            for r in db.fetch_all('SELECT class_id, subclass_id, class_name, subclass_name FROM ah_item_classes')}


def _snapshot():
    s = db.snapshot()
    return {'swept_at': s['swept_at'].isoformat() if s.get('swept_at') else None, 'groups': s.get('groups') or 0,
            'listings': int(s.get('listings') or 0), 'items': s.get('items') or 0,
            'history_since': s['history_since'].isoformat() if s.get('history_since') else None}


def _categories():
    names = _cached('classes', _class_names)
    rows = db.fetch_all("""SELECT i.class_id, i.subclass_id, count(*) AS n
                           FROM (SELECT item_id FROM ah_item_summary UNION ALL SELECT item_id FROM ah_commodity_summary) s
                           JOIN ah_items i USING (item_id) GROUP BY i.class_id, i.subclass_id""")
    cats = {}
    for r in rows:
        cls_name, sub_name = names.get((r['class_id'], r['subclass_id']), (None, None))
        if not cls_name:
            continue
        c = cats.setdefault(r['class_id'], {'id': r['class_id'], 'name': cls_name, 'n': 0, 'subs': []})
        c['n'] += r['n']
        c['subs'].append({'id': r['subclass_id'], 'name': sub_name, 'n': r['n']})
    out = sorted(cats.values(), key=lambda c: -c['n'])
    for c in out:
        c['subs'].sort(key=lambda s: -s['n'])
    return out


def _opps():
    names = _cached('classes', _class_names)
    rows = db.fetch_all("""
        SELECT s.item_id, s.gap, s.gap_buy_cr, s.gap_buy, s.gap_sell_cr, s.gap_sell, s.realms, s.rolls,
               i.name, i.quality, i.icon, i.icon_file, i.class_id, i.subclass_id,
               v.sec, v.ter, v.sock, v.ilvl, v.tooltip
        FROM ah_item_summary s JOIN ah_items i USING (item_id)
        LEFT JOIN ah_variants v ON v.variant_id = s.gap_variant
        WHERE s.gap IS NOT NULL AND s.realms >= 25 AND NOT s.walls_only
        ORDER BY s.gap DESC LIMIT 3""")
    return [{'item': {'id': r['item_id'], 'name': r['name'], 'q': r['quality'], 'icon': icon_url(r),
                      'sub': names.get((r['class_id'], r['subclass_id']), ('', ''))[1]},
             'roll': ({'sec': r['sec'], 'ter': r['ter'], 'sock': r['sock'], 'ilvl': r['ilvl'], 'tooltip': r['tooltip']}
                      if r['rolls'] > 1 and r['sec'] is not None else None),
             'buy_cr': r['gap_buy_cr'], 'buy': r['gap_buy'], 'sell_cr': r['gap_sell_cr'], 'sell': r['gap_sell'],
             'gain': r['gap'], 'realms': r['realms']} for r in rows]


# ============================================================================
# Pages
# ============================================================================

def _page(title, body, data, description):
    from raidanalysis.web import brand
    from raidanalysis.web.routes import FAVICON
    favicon = '<link rel="icon" type="image/png" href="/raids/favicon.png">' if FAVICON.is_file() else ''
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=str).replace('<', '\\u003c')
    response = web.Response(text=f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{esc(title)}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="{esc(description)}">
    {favicon}
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Marcellus&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="{CSS_URL}">
</head>
<body>
<div class="page">
    {brand.markup('/ah')}
    {brand.site_tabs('ah')}
    <div class="market-bar">
        <div class="market-title"><h1><a href="/ah">Auction House</a></h1><span class="region">EU</span></div>
        <div class="market-stats" id="market-stats"></div>
    </div>
    {body}
    <footer>Buyout listings from Blizzard's auction API for every EU realm, updated about once an hour. Tooltips from
    Wowhead. Prices are what sellers ask, not what items sold for.</footer>
</div>
<div id="tip" hidden></div>
<div id="itemtip" hidden></div>
<script type="application/json" id="ah-data">{payload}</script>
<script src="{JS_URL}"></script>
</body>
</html>""", content_type='text/html', headers=_headers())
    response.enable_compression()
    return response


SEARCH_BODY = """
<main id="search-view">
  <section id="opps-section" aria-labelledby="opp-title" hidden>
    <div class="card-head"><h2 id="opp-title">Biggest realm gaps right now</h2>
      <p>The same item with the same stat roll: the cheapest listing in EU against what a typical realm asks, after the
      5% auction cut. Bot price walls and lottery listings at the price cap are left out.</p></div>
    <div class="opps" id="opps"></div>
  </section>
  <div class="search-layout">
    <details class="rail" id="rail" open>
      <summary class="eyebrow">Categories</summary>
      <ul class="cat-list" id="cats"></ul>
    </details>
    <section class="panel" aria-label="Search results">
      <form class="search-head" id="search-form" role="search">
        <div class="search-row">
          <label class="field"><span>Item name</span>
            <input class="input big" id="q" type="search" placeholder="Search items, e.g. Greaves" autocomplete="off"></label>
          <label class="field"><span>Realm</span><select class="select big" id="realm"></select></label>
        </div>
        <div class="filters">
          <div class="field"><span>Item level</span>
            <div class="range"><input class="input" id="ilvl-min" type="number" min="0" placeholder="Min" aria-label="Minimum item level">
              <span class="faint">to</span><input class="input" id="ilvl-max" type="number" min="0" placeholder="Max" aria-label="Maximum item level"></div></div>
          <div class="field"><span>Required level</span>
            <div class="range"><input class="input" id="req-min" type="number" min="0" placeholder="Min" aria-label="Minimum required level">
              <span class="faint">to</span><input class="input" id="req-max" type="number" min="0" placeholder="Max" aria-label="Maximum required level"></div></div>
          <div class="field"><span>Rarity</span>
            <div class="range"><select class="select" id="q-min" aria-label="Lowest rarity"></select>
              <span class="faint">to</span><select class="select" id="q-max" aria-label="Highest rarity"></select></div></div>
          <label class="field"><span>Secondary stats</span><select class="select solo" id="f-sec"></select></label>
          <label class="field"><span>Tertiary stat</span><select class="select solo" id="f-ter"></select></label>
          <label class="field"><span>Expansion</span><select class="select solo" id="exp"></select></label>
          <button class="btn-ghost" type="reset" id="reset">Clear filters</button>
          <div class="checks">
            <label class="check"><input type="checkbox" id="f-sock"> Has a socket</label>
            <label class="check"><input type="checkbox" id="below-vendor"> Only below vendor price</label>
            <label class="check"><input type="checkbox" id="out-of-stock"> Include items not listed on this realm</label>
            <label class="check"><input type="checkbox" id="median-col" checked> EU median column</label>
          </div>
        </div>
      </form>
      <div class="result-meta"><span id="result-count"></span><span id="result-mode"></span></div>
      <div class="table-wrap"><table id="results"><thead></thead><tbody></tbody></table></div>
      <div class="more"><button type="button" class="btn-ghost" id="more" hidden>Show more</button></div>
    </section>
  </div>
</main>"""


def _search_page_data():
    return {'page': 'search', 'realms': _cached('realms', _realms), 'snapshot': _cached('snapshot', _snapshot),
            'categories': _cached('categories', _categories), 'opps': _cached('opps', _opps),
            'expansions': EXPANSIONS}


async def handle_search_page(request):
    data = await asyncio.to_thread(_search_page_data)
    return _page('Luminis Auction House · EU', SEARCH_BODY, data,
                 'Search every EU auction house and compare prices across all realms.')


def _history(item_id):
    return [[r['ts'].isoformat(), r['lo'], r['p25'], r['med'], r['p75'], r['realms']]
            for r in db.fetch_all('SELECT ts, lo, p25, med, p75, realms FROM ah_item_history WHERE item_id = %s ORDER BY ts',
                                  (item_id,))]


def _commodity_data(item, base):
    """A commodity's page: one auction house for all of EU, so its numbers, price ladder and history."""
    s = db.fetch_one('SELECT * FROM ah_commodity_summary WHERE item_id = %s', (item['item_id'],))
    book = [[r['price'], r['quantity']] for r in db.fetch_all(
        'SELECT price, quantity FROM ah_commodity_book WHERE item_id = %s ORDER BY price LIMIT 400', (item['item_id'],))]
    return {'page': 'item', 'kind': 'commodity', 'realms': _cached('realms', _realms),
            'snapshot': _cached('snapshot', _snapshot), 'item': base,
            'commodity': {k: s[k] for k in ('lo', 'p05', 'market', 'p30', 'quantity', 'listings', 'levels')},
            'book': book, 'history': _history(item['item_id']), 'variants': [], 'listings': [], 'realm_history': {}}


def _item_data(item_id):
    item = db.fetch_one('SELECT * FROM ah_items WHERE item_id = %s', (item_id,))
    if not item:
        return None
    names = _cached('classes', _class_names)
    cls, sub = names.get((item['class_id'], item['subclass_id']), ('', ''))
    if item_id > 0 and db.fetch_one('SELECT 1 AS ok FROM ah_commodity_summary WHERE item_id = %s', (item_id,)):
        return _commodity_data(item, {'id': item_id, 'name': item['name'], 'q': item['quality'], 'ilvl': item['ilvl'],
                                      'req': item['req_level'], 'cls': cls, 'sub': sub,
                                      'slot': SLOTS.get(item['inventory_type'], ''), 'bind': '',
                                      'vendor': item['vendor'], 'icon': icon_url(item)})
    variants = db.fetch_all("""SELECT v.variant_id, v.sec, v.heavy, v.ter, v.sock, v.ilvl, v.bind, v.tooltip FROM ah_variants v
                               WHERE v.item_id = %s AND EXISTS (SELECT 1 FROM ah_listings l WHERE l.variant_id = v.variant_id)
                               ORDER BY v.variant_id""", (item_id,))
    index = {v['variant_id']: i for i, v in enumerate(variants)}
    out = [{'sec': v['sec'], 'heavy': v['heavy'], 'ter': v['ter'], 'sock': v['sock'], 'ilvl': v['ilvl'],
            'q': v['tooltip'], 'realms': []} for v in variants]
    for r in db.fetch_all("""SELECT variant_id, cr, min(buyout) AS lo, count(*) AS n FROM ah_listings
                             WHERE item_id = %s GROUP BY variant_id, cr""", (item_id,)):
        if r['variant_id'] in index:
            out[index[r['variant_id']]]['realms'].append([r['cr'], r['lo'], r['n']])
    listings = [[r['cr'], index[r['variant_id']], r['buyout'], r['time_left']]
                for r in db.fetch_all("""SELECT cr, variant_id, buyout, time_left FROM ah_listings WHERE item_id = %s
                                         ORDER BY buyout LIMIT 5000""", (item_id,)) if r['variant_id'] in index]
    history = _history(item_id)
    realm_history = {}
    for r in db.fetch_all('SELECT cr, day, lo FROM ah_realm_history WHERE item_id = %s ORDER BY day', (item_id,)):
        realm_history.setdefault(str(r['cr']), []).append([r['day'].isoformat(), r['lo']])
    # what's on sale binds as its rolls say (a bonus id can make a "binds when picked up" item tradeable)
    overrides = [v['bind'] for v in variants if v['bind']]
    binding = max(set(overrides), key=overrides.count) if overrides else item['binding']
    pet = item_id < 0
    return {'page': 'item', 'kind': 'pet' if pet else 'item', 'realms': _cached('realms', _realms),
            'snapshot': _cached('snapshot', _snapshot),
            'item': {'id': item_id, 'name': item['name'], 'q': item['quality'], 'ilvl': item['ilvl'],
                     'req': item['req_level'], 'cls': cls, 'sub': sub,
                     'slot': '' if pet else SLOTS.get(item['inventory_type'], ''),
                     'bind': '' if pet else BINDING.get(binding, ''), 'vendor': item['vendor'], 'icon': icon_url(item),
                     'description': item.get('description') or ''},
            'variants': out, 'listings': listings, 'history': history, 'realm_history': realm_history}


async def handle_item_page(request):
    from raidanalysis import items
    try:
        item_id = int(request.match_info['item_id'])
    except ValueError:
        raise web.HTTPNotFound()
    data = await asyncio.to_thread(_item_data, item_id)
    if not data:
        raise web.HTTPNotFound(text='No such item')
    if item_id > 0:  # Wowhead tooltips (pets' are ours: _pet_tooltip)
        items.offer(item_id, '')
        for v in data['variants']:
            items.offer(item_id, v['q'])
    name = data['item']['name']
    return _page(f'{name} · Luminis Auction House', '<main id="item-view"></main>', data,
                 f'{name}: prices on every EU realm, each stat roll, and where it sells best.')


# ============================================================================
# Search
# ============================================================================

def _int(args, key, lo=0, hi=10 ** 7):
    try:
        value = int(args.get(key, ''))
    except ValueError:
        return None
    return value if lo <= value <= hi else None


def _like(text):
    return '%' + text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def search(args):
    """The search page's results: (rows, total)."""
    p, where, vconds = {}, [], []
    text = (args.get('q') or '').strip()[:100]
    if text:
        where.append('i.name ILIKE %(like)s')
        p['like'] = _like(text)
    for key, column in (('cat', 'i.class_id'), ('sub', 'i.subclass_id'), ('exp', 'i.expansion')):
        value = _int(args, key, -1, 1000)
        if value is not None:
            where.append(f'{column} = %({key})s')
            p[key] = value
    for key, column, op in (('req_min', 'i.req_level', '>='), ('req_max', 'i.req_level', '<='),
                            ('q_min', 'i.quality', '>='), ('q_max', 'i.quality', '<=')):
        value = _int(args, key)
        if value is not None:
            where.append(f'{column} {op} %({key})s')
            p[key] = value
    sec, ter = args.get('sec') or '', args.get('ter') or ''
    if sec in PAIRS:
        vconds.append('v.sec = %(sec)s')
        p['sec'] = sec
    if ter == 'any':
        vconds.append("v.ter <> ''")
    elif ter == 'none':
        vconds.append("v.ter = ''")
    elif ter in TERTIARY:
        vconds.append('v.ter = %(ter)s')
        p['ter'] = ter
    if args.get('sock') == '1':
        vconds.append('v.sock > 0')
    for key, op in (('ilvl_min', '>='), ('ilvl_max', '<=')):
        value = _int(args, key)
        if value is not None:
            vconds.append(f'v.ilvl {op} %({key})s')
            p[key] = value

    if vconds:
        # stat or item level filters: computed from the matching listings (price walls left out)
        ctes = f"""
            vf AS (SELECT v.variant_id, v.ilvl FROM ah_variants v WHERE {' AND '.join(vconds)}),
            lf AS (SELECT l.item_id, l.cr, l.buyout, l.variant_id, vf.ilvl FROM ah_listings l JOIN vf USING (variant_id)
                   WHERE {NO_WALL}),
            m AS (SELECT item_id, cr, min(buyout) AS lo, count(*) AS n FROM lf GROUP BY item_id, cr),
            x AS (SELECT item_id, min(ilvl) AS ilvl_min, max(ilvl) AS ilvl_max, count(DISTINCT variant_id)::int AS rolls
                  FROM lf GROUP BY item_id),
            r AS (SELECT m.item_id, count(*)::int AS realms, sum(n)::int AS listings, min(lo) AS lo,
                         (array_agg(cr ORDER BY lo))[1] AS lo_cr,
                         percentile_disc(0.5) WITHIN GROUP (ORDER BY lo) AS med,
                         max(lo) AS hi, (array_agg(cr ORDER BY lo DESC))[1] AS hi_cr,
                         x.ilvl_min, x.ilvl_max, x.rolls, FALSE AS walls_only, FALSE AS commodity
                  FROM m JOIN x USING (item_id) GROUP BY m.item_id, x.ilvl_min, x.ilvl_max, x.rolls)"""
        here_source = 'lf'
    else:
        # commodities (one auction house for all of EU) sit beside them: on every realm, at one price
        ctes = """r AS (SELECT item_id, realms, listings, lo, lo_cr, med, hi, hi_cr, ilvl_min, ilvl_max, rolls, walls_only,
                               FALSE AS commodity
                        FROM ah_item_summary
                        UNION ALL
                        SELECT item_id, (SELECT count(*) FROM ah_realm_groups)::smallint, listings, lo, NULL, market, NULL,
                               NULL, NULL, NULL, 1, FALSE, TRUE
                        FROM ah_commodity_summary)"""
        here_source = f'(SELECT l.item_id, l.cr, l.buyout FROM ah_listings l WHERE {NO_WALL})'

    realm = _int(args, 'realm', 1, 10 ** 6)
    if realm:
        p['realm'] = realm
        # commodities are on every realm's auction house, at the one EU price
        commodities_here = '' if vconds else ' UNION ALL SELECT item_id, lo, listings FROM ah_commodity_summary'
        ctes += f""",
            h AS (SELECT hs.item_id, min(hs.buyout) AS here, count(*)::int AS here_n FROM {here_source} hs
                  WHERE hs.cr = %(realm)s GROUP BY hs.item_id{commodities_here})"""
        join = 'LEFT JOIN h USING (item_id)' if args.get('oos') == '1' else 'JOIN h USING (item_id)'
        here_cols = 'h.here, h.here_n'
    else:
        join, here_cols = '', 'NULL::bigint AS here, NULL::int AS here_n'
    if args.get('below') == '1':
        where.append(f"i.vendor > 0 AND {'COALESCE(h.here, r.lo)' if realm else 'r.lo'} < i.vendor")

    sort = args.get('sort') if args.get('sort') in SORTS else 'realms'
    if sort in ('here', 'vs', 'qty') and not realm:
        sort = 'realms'
    direction = 'ASC' if args.get('dir') == 'asc' else 'DESC'
    p['offset'] = _int(args, 'offset', 0, 100000) or 0
    sql = f"""
        WITH {ctes}
        SELECT i.item_id AS id, i.name, i.quality AS q, i.icon, i.icon_file, i.class_id, i.subclass_id,
               i.inventory_type, i.req_level AS req,
               r.realms, r.listings, r.lo, r.lo_cr, r.med, r.hi, r.hi_cr, r.ilvl_min, r.ilvl_max, r.rolls,
               r.commodity, i.ilvl AS base_ilvl, {here_cols}, count(*) OVER () AS total
        FROM r JOIN ah_items i USING (item_id) {join}
        WHERE {' AND '.join(where) or 'TRUE'}
        ORDER BY r.walls_only, {SORTS[sort]} {direction} NULLS LAST, i.name
        LIMIT {PAGE_SIZE} OFFSET %(offset)s"""
    rows = db.fetch_all(sql, p)
    names = _cached('classes', _class_names)
    out = []
    for r in rows:
        cls, sub = names.get((r['class_id'], r['subclass_id']), ('', ''))
        out.append({'id': r['id'], 'name': r['name'], 'q': r['q'], 'icon': icon_url(r), 'cls': cls, 'sub': sub,
                    'slot': SLOTS.get(r['inventory_type'], ''), 'req': r['req'], 'realms': r['realms'],
                    'listings': r['listings'], 'lo': r['lo'], 'lo_cr': r['lo_cr'], 'med': r['med'], 'hi': r['hi'],
                    'hi_cr': r['hi_cr'], 'ilvl_min': r['ilvl_min'] if r['ilvl_min'] is not None else r['base_ilvl'],
                    'ilvl_max': r['ilvl_max'] if r['ilvl_max'] is not None else r['base_ilvl'], 'rolls': r['rolls'],
                    'commodity': r['commodity'], 'here': r['here'], 'here_n': r['here_n']})
    return out, (rows[0]['total'] if rows else 0)


async def handle_search_api(request):
    from raidanalysis import items
    rows, total = await asyncio.to_thread(search, request.query)
    for r in rows:
        if r['id'] > 0:
            items.offer(r['id'], '')
    return web.json_response({'rows': rows, 'total': total}, headers={'Cache-Control': 'no-store', **_headers()})


# ============================================================================
# Tooltips and assets
# ============================================================================

BREED_NAMES = {'B': 'Balanced', 'P': 'Power', 'S': 'Speed', 'H': 'Health'}


def _pet_tooltip(item_id, args):
    """A battle pet's tooltip, built here from Blizzard's pet data: Wowhead's item tooltips don't cover pet cages."""
    from .. import rolls
    row = db.fetch_one("""SELECT i.name, i.icon, i.description, c.subclass_name AS family FROM ah_items i
                          LEFT JOIN ah_item_classes c ON c.class_id = i.class_id AND c.subclass_id = i.subclass_id
                          WHERE i.item_id = %s""", (item_id,))
    if not row:
        return None
    breed, level, quality = _int(args, 'breed', 0, 30), _int(args, 'level', 1, 25), _int(args, 'quality', 0, 5)
    shown = quality if quality is not None else 3
    lines = [f'<b class="q{shown}">{esc(row["name"])}</b>',
             'Battle Pet' + (f' · {esc(row["family"])}' if row['family'] else '')]
    if level:
        lines.append(f'<span class="q">Level {level}</span>')
    if quality is not None:
        lines.append(f'<span class="q{quality}">{esc(rolls.PET_QUALITY[quality])}</span>')
    code = rolls.PET_BREEDS.get(breed if breed is None or breed < 13 else breed - 10) if breed else None
    if code:
        words = ' / '.join(dict.fromkeys(BREED_NAMES[c] for c in code.split('/')))
        lines.append(f'Breed {esc(code)} ({esc(words)})')
    if row['description']:
        lines.append(f'<span class="q">"{esc(row["description"])}"</span>')
    return {'name': row['name'], 'quality': shown, 'icon': row['icon'] or None,
            'html': '<table><tr><td>' + '<br>'.join(lines) + '</td></tr></table>'}


async def handle_tooltip(request):
    """An item's tooltip for one roll (bonus ids, crafted stats) - only for items and rolls our pages showed."""
    from raidanalysis import items
    try:
        item_id = int(request.match_info['item_id'])
    except ValueError:
        raise web.HTTPNotFound()
    if item_id < 0:  # a battle pet species
        info = await asyncio.to_thread(_pet_tooltip, item_id, request.query)
        if not info:
            raise web.HTTPNotFound()
        return web.json_response(info, headers={'Cache-Control': 'public, max-age=86400', **_headers()})
    q = items.parse_query(request.query)
    if q is None:
        raise web.HTTPBadRequest()
    info = items.cached(item_id, q)
    if info is None and items.may_fetch(item_id, q):
        info = await items.tooltip(item_id, q)
    if not info:
        raise web.HTTPNotFound()
    return web.json_response(info, headers={'Cache-Control': 'public, max-age=86400', **_headers()})


async def handle_css(request):
    from raidanalysis.web.routes import STATIC_HEADERS
    response = web.Response(text=CSS, content_type='text/css', headers=STATIC_HEADERS)
    response.enable_compression()
    return response


async def handle_js(request):
    from raidanalysis.web.routes import STATIC_HEADERS
    response = web.Response(text=JS, content_type='application/javascript', headers=STATIC_HEADERS)
    response.enable_compression()
    return response
