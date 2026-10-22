"""
The public auction house pages:

  GET /ah                       search every item on sale in EU (results from /ah/api/search)
  GET /ah/api/search            the results, as JSON
  GET /ah/item/{id}             one item: its stat rolls, where it sells best, every listing on your realm, history
  GET /ah/deals                 rolls listed far below what they usually go for (/ah/api/deals)
  GET /ah/movers                what rose, fell or ran low in about a day (/ah/api/movers)
  GET /ah/crafting              every recipe's reagent cost against what it makes sells for (/ah/api/crafting)
  GET /ah/collection            a character's missing mounts, pets and toys that are on sale (/ah/api/collection)
  GET /ah/api/characters?q=     EU characters whose name starts so, for the collection page's name box (Raider.IO)
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
import re
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
SORTS = {'listings': 'r.listings', 'sold': 'r.sold_7d', 'name': 'i.name', 'ilvl': 'r.ilvl_max', 'req': 'i.req_level', 'lo': 'r.lo', 'med': 'r.med', 'hi': 'r.hi',
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


# The auction house's own tabs, under its title: (key, address, name)
SECTIONS = (('search', '/ah', 'Search'), ('deals', '/ah/deals', 'Deals'), ('movers', '/ah/movers', 'Market movers'),
            ('crafting', '/ah/crafting', 'Crafting'), ('collection', '/ah/collection', 'Collection'))


def register_routes(app):
    app.router.add_get('/ah', handle_search_page)
    app.router.add_get('/ah/api/search', handle_search_api)
    app.router.add_get('/ah/deals', handle_deals_page)
    app.router.add_get('/ah/api/deals', handle_deals_api)
    app.router.add_get('/ah/movers', handle_movers_page)
    app.router.add_get('/ah/api/movers', handle_movers_api)
    app.router.add_get('/ah/crafting', handle_crafting_page)
    app.router.add_get('/ah/api/crafting', handle_crafting_api)
    app.router.add_get('/ah/collection', handle_collection_page)
    app.router.add_get('/ah/api/collection', handle_collection_api)
    app.router.add_get('/ah/api/characters', handle_characters_api)
    app.router.add_get('/ah/item/{item_id}', handle_item_page)
    app.router.add_get('/ah/tooltip/{item_id}', handle_tooltip)
    app.router.add_get(CSS_URL, handle_css)
    app.router.add_get(JS_URL, handle_js)


def _headers():
    from raidanalysis.web.routes import SECURITY_HEADERS
    return SECURITY_HEADERS


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def _offer(pairs):
    """
    Tooltips a page is about to show: (item id, roll query) pairs. raidanalysis.items only fetches a tooltip that
    was offered (the endpoint is public), so every page with item icons offers its own. Battle pets need nothing:
    their tooltips are built from our own tables.
    """
    from raidanalysis import items
    for item_id, q in pairs:
        if item_id > 0:
            items.offer(item_id, q or '')


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
    return {str(r['cr']): {'names': r['names'], 'slugs': r['slugs'] or [], 'locale': r['locale'] or '',
                           'pop': r['population'] or ''} for r in db.realm_groups()}


def _class_names():
    return {(r['class_id'], r['subclass_id']): (r['class_name'], r['subclass_name'])
            for r in db.fetch_all('SELECT class_id, subclass_id, class_name, subclass_name FROM ah_item_classes')}


def _snapshot():
    from datetime import datetime, timezone
    s = db.snapshot()
    since = s.get('sales_since')
    return {'swept_at': s['swept_at'].isoformat() if s.get('swept_at') else None, 'groups': s.get('groups') or 0,
            'listings': int(s.get('listings') or 0), 'items': s.get('items') or 0,
            'history_since': s['history_since'].isoformat() if s.get('history_since') else None,
            # how long sales have been counted (the "sold per day" rates divide by min(7 days, this))
            'sales_hours': round((datetime.now(timezone.utc) - since).total_seconds() / 3600, 1) if since else 0}


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

def _section_tabs(active):
    tabs = []
    for key, href, name in SECTIONS:
        current = ' class="active" aria-current="page"' if key == active else ''
        tabs.append(f'<a href="{href}"{current}>{esc(name)}</a>')
    return f'<nav class="ah-tabs" aria-label="Auction house">{"".join(tabs)}</nav>'


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
        {_section_tabs(data.get('section', 'search'))}
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
    <div class="section-head"><h2 id="opp-title">Biggest realm gaps right now</h2>
      <p>The same item with the same stat roll: the cheapest listing in EU against what a typical realm asks, after the
      5% auction cut. Bot price walls and lottery listings at the price cap are left out.</p></div>
    <div class="opps" id="opps"></div>
  </section>
  <div class="search-layout">
    <details class="rail" id="rail" open>
      <summary><span class="eyebrow">Categories</span><span class="rail-current" id="cat-current">All categories</span></summary>
      <ul class="cat-list" id="cats"></ul>
    </details>
    <section class="panel" aria-label="Search results">
      <form class="search-head" id="search-form" role="search">
        <div class="search-bar">
          <input class="input big search-q" id="q" type="search" placeholder="Search every EU auction house, e.g. Greaves"
                 autocomplete="off" aria-label="Item name">
          <select class="select big" id="realm" aria-label="Realm"></select>
          <button type="button" class="btn-filters" id="filters-toggle" aria-expanded="false" aria-controls="filter-panel">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8"
                 stroke-linecap="round" aria-hidden="true"><path d="M2 4h12M4.5 8h7M7 12h2"/></svg>
            Filters<span class="filter-count" id="filter-count" hidden></span></button>
        </div>
        <div class="filter-panel" id="filter-panel" hidden>
        <div class="filters">
          <div class="field"><span>Item level</span>
            <div class="range"><input class="input" id="ilvl-min" type="number" min="0" placeholder="Min" aria-label="Minimum item level">
              <span class="faint">to</span><input class="input" id="ilvl-max" type="number" min="0" placeholder="Max" aria-label="Maximum item level"></div></div>
          <div class="field"><span>Required level</span>
            <div class="range"><input class="input" id="req-min" type="number" min="0" placeholder="Min" aria-label="Minimum required level">
              <span class="faint">to</span><input class="input" id="req-max" type="number" min="0" placeholder="Max" aria-label="Maximum required level"></div></div>
          <div class="field wide"><span>Rarity</span>
            <div class="range"><select class="select" id="q-min" aria-label="Lowest rarity"></select>
              <span class="faint">to</span><select class="select" id="q-max" aria-label="Highest rarity"></select></div></div>
          <label class="field"><span>Expansion</span><select class="select" id="exp"></select></label>
          <label class="field"><span>Secondary stats</span><select class="select" id="f-sec"></select></label>
          <label class="field"><span>Tertiary stat</span><select class="select" id="f-ter"></select></label>
        </div>
        <div class="filter-foot">
          <div class="checks">
            <label class="check"><input type="checkbox" id="f-sock"> Has a socket</label>
            <label class="check"><input type="checkbox" id="below-vendor"> Only below vendor price</label>
            <label class="check"><input type="checkbox" id="out-of-stock"> Include items not listed on this realm</label>
          </div>
          <button class="btn-ghost" type="reset" id="reset">Clear filters</button>
        </div>
        </div>
      </form>
      <div class="result-meta">
        <span><span id="result-count"></span><span id="filters-on"></span></span>
        <span class="result-tools"><span id="result-mode"></span>
          <label class="sort-by"><span>Sort by</span><select class="select" id="sort-by"></select></label></span>
      </div>
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
    _offer((o['item']['id'], o['roll']['tooltip'] if o['roll'] else '') for o in data['opps'])
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
    daily = [[r['day'].isoformat(), r['sold'], r['revenue']] for r in db.fetch_all(
        'SELECT day, sold, revenue FROM ah_commodity_sales WHERE item_id = %s ORDER BY day', (item['item_id'],))]
    return {'page': 'item', 'kind': 'commodity', 'realms': _cached('realms', _realms),
            'snapshot': _cached('snapshot', _snapshot), 'item': base,
            'commodity': {k: s[k] for k in ('lo', 'p05', 'market', 'p30', 'quantity', 'listings', 'levels', 'sold_7d')},
            'book': book, 'sales_daily': daily, 'history': _history(item['item_id']), 'variants': [], 'listings': [], 'realm_history': {}}


def _item_data(item_id):
    item = db.fetch_one('SELECT * FROM ah_items WHERE item_id = %s', (item_id,))
    if not item:
        return None
    names = _cached('classes', _class_names)
    cls, sub = names.get((item['class_id'], item['subclass_id']), ('', ''))
    if item_id > 0 and db.fetch_one('SELECT 1 AS ok FROM ah_commodity_summary WHERE item_id = %s', (item_id,)):
        return _commodity_data(item, {'id': item_id, 'name': item['name'], 'q': item['quality'], 'rank': item['craft_rank'],
                                      'ilvl': item['ilvl'],
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
    from datetime import date, timedelta
    sales = [[index[r['variant_id']], r['cr'], r['sold'], r['revenue']] for r in db.fetch_all(
        """SELECT variant_id, cr, sum(sold)::int AS sold, sum(revenue) AS revenue FROM ah_sales
           WHERE item_id = %s AND day > %s GROUP BY variant_id, cr""", (item_id, date.today() - timedelta(days=7)))
        if r['variant_id'] in index]
    realm_history = {}
    for r in db.fetch_all('SELECT cr, day, lo FROM ah_realm_history WHERE item_id = %s ORDER BY day', (item_id,)):
        realm_history.setdefault(str(r['cr']), []).append([r['day'].isoformat(), r['lo']])
    # what's on sale binds as its rolls say (a bonus id can make a "binds when picked up" item tradeable)
    overrides = [v['bind'] for v in variants if v['bind']]
    binding = max(set(overrides), key=overrides.count) if overrides else item['binding']
    pet = item_id < 0
    return {'page': 'item', 'kind': 'pet' if pet else 'item', 'realms': _cached('realms', _realms),
            'snapshot': _cached('snapshot', _snapshot),
            'item': {'id': item_id, 'name': item['name'], 'q': item['quality'], 'rank': item['craft_rank'], 'ilvl': item['ilvl'],
                     'req': item['req_level'], 'cls': cls, 'sub': sub,
                     'slot': '' if pet else SLOTS.get(item['inventory_type'], ''),
                     'bind': '' if pet else BINDING.get(binding, ''), 'vendor': item['vendor'], 'icon': icon_url(item),
                     'description': item.get('description') or ''},
            'variants': out, 'listings': listings, 'history': history, 'realm_history': realm_history, 'sales': sales}


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
                         x.ilvl_min, x.ilvl_max, x.rolls, FALSE AS walls_only, FALSE AS commodity,
                         (SELECT sold_7d FROM ah_item_summary s WHERE s.item_id = m.item_id)::bigint AS sold_7d
                  FROM m JOIN x USING (item_id) GROUP BY m.item_id, x.ilvl_min, x.ilvl_max, x.rolls)"""
        here_source = 'lf'
    else:
        # commodities (one auction house for all of EU) sit beside them: on every realm, at one price
        ctes = """r AS (SELECT item_id, realms, listings, lo, lo_cr, med, hi, hi_cr, ilvl_min, ilvl_max, rolls, walls_only,
                               FALSE AS commodity, sold_7d::bigint
                        FROM ah_item_summary
                        UNION ALL
                        SELECT item_id, (SELECT count(*) FROM ah_realm_groups)::smallint, listings, lo, NULL, market, NULL,
                               NULL, NULL, NULL, 1, FALSE, TRUE, sold_7d
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

    sort = args.get('sort') if args.get('sort') in SORTS else 'listings'
    if sort in ('here', 'vs', 'qty') and not realm:
        sort = 'listings'
    direction = 'ASC' if args.get('dir') == 'asc' else 'DESC'
    p['offset'] = _int(args, 'offset', 0, 100000) or 0
    sql = f"""
        WITH {ctes}
        SELECT i.item_id AS id, i.name, i.quality AS q, i.icon, i.icon_file, i.class_id, i.subclass_id, i.craft_rank,
               i.inventory_type, i.req_level AS req,
               r.realms, r.listings, r.lo, r.lo_cr, r.med, r.hi, r.hi_cr, r.ilvl_min, r.ilvl_max, r.rolls,
               r.commodity, r.sold_7d, i.ilvl AS base_ilvl, {here_cols}, count(*) OVER () AS total
        FROM r JOIN ah_items i USING (item_id) {join}
        WHERE {' AND '.join(where) or 'TRUE'}
        ORDER BY r.walls_only, {SORTS[sort]} {direction} NULLS LAST, i.name
        LIMIT {PAGE_SIZE} OFFSET %(offset)s"""
    rows = db.fetch_all(sql, p)
    names = _cached('classes', _class_names)
    out = []
    for r in rows:
        cls, sub = names.get((r['class_id'], r['subclass_id']), ('', ''))
        out.append({'id': r['id'], 'name': r['name'], 'q': r['q'], 'rank': r['craft_rank'], 'icon': icon_url(r), 'cls': cls, 'sub': sub,
                    'slot': SLOTS.get(r['inventory_type'], ''), 'req': r['req'], 'realms': r['realms'],
                    'listings': r['listings'], 'lo': r['lo'], 'lo_cr': r['lo_cr'], 'med': r['med'], 'hi': r['hi'],
                    'hi_cr': r['hi_cr'], 'ilvl_min': r['ilvl_min'] if r['ilvl_min'] is not None else r['base_ilvl'],
                    'ilvl_max': r['ilvl_max'] if r['ilvl_max'] is not None else r['base_ilvl'], 'rolls': r['rolls'],
                    'commodity': r['commodity'], 'sold_7d': r['sold_7d'] or 0, 'here': r['here'], 'here_n': r['here_n']})
    return out, (rows[0]['total'] if rows else 0)


def _base_data(section):
    return {'page': section, 'section': section, 'realms': _cached('realms', _realms),
            'snapshot': _cached('snapshot', _snapshot), 'categories': _cached('categories', _categories)}


DEALS_BODY = """
<main id="deals-view">
  <div class="section-head"><h2>Deals</h2>
    <p>Realms where an item - the same stat roll and item level - is listed for half of what it usually goes for, or
    less. "Usually" is its average sale price once we've seen it sell a few times this week (a proven deal), else
    the EU median of what's asked. Buy it there; sell it where it's worth more.</p></div>
  <section class="panel">
    <form class="search-head" id="deals-form">
      <div class="filters">
        <label class="field"><span>Realm</span><select class="select" id="d-realm"></select></label>
        <label class="field"><span>Category</span><select class="select" id="d-cat"></select></label>
        <label class="field"><span>Profit at least</span><select class="select" id="d-min"></select></label>
        <label class="field"><span>Sort by</span><select class="select" id="d-sort"></select></label>
      </div>
      <div class="filter-foot"><div class="checks">
        <label class="check"><input type="checkbox" id="d-proven"> Only proven deals (seen selling)</label></div></div>
    </form>
    <div class="result-meta"><span id="d-count"></span><span id="d-note"></span></div>
    <div class="table-wrap"><table id="deals"><thead></thead><tbody></tbody></table></div>
    <div class="more"><button type="button" class="btn-ghost" id="d-more" hidden>Show more</button></div>
  </section>
</main>"""

MOVERS_BODY = """
<main id="movers-view">
  <div class="section-head"><h2>Market movers</h2>
    <p>What changed most since about a day ago: prices that rose or fell, and goods running low. Commodities use
    their market price (the cheapest 15% on sale); everything else the EU median of each realm's cheapest listing.</p></div>
  <div class="mover-tools" id="m-kind"></div>
  <div class="movers" id="movers"></div>
</main>"""


async def handle_deals_page(request):
    data = await asyncio.to_thread(_base_data, 'deals')
    return _page('Deals · Luminis Auction House', DEALS_BODY, data, 'Items listed far below what they usually sell for.')


async def handle_movers_page(request):
    data = await asyncio.to_thread(_base_data, 'movers')
    return _page('Market movers · Luminis Auction House', MOVERS_BODY, data,
                 'The EU auction house prices that rose, fell or ran low in the last day.')


def deals(args):
    p, where = {}, []
    realm = _int(args, 'realm', 1, 10 ** 6)
    if realm:
        where.append('d.cr = %(realm)s')
        p['realm'] = realm
    cat = _int(args, 'cat', -1, 1000)
    if cat is not None:
        where.append('i.class_id = %(cat)s')
        p['cat'] = cat
    p['min'] = (_int(args, 'min', 0, 10 ** 9) or 0) * 10000
    where.append('d.profit >= %(min)s')
    if args.get('proven') == '1':
        where.append('d.proven')
    order = 'd.price::float / d.typical, d.profit DESC' if args.get('sort') == 'discount' else 'd.proven DESC, d.profit DESC'
    p['offset'] = _int(args, 'offset', 0, 100000) or 0
    rows = db.fetch_all(f"""
        SELECT d.cr, d.item_id, d.price, d.typical, d.realms, d.profit, d.proven, d.sold_7d,
               i.name, i.quality, i.icon, i.icon_file, i.class_id, i.subclass_id, i.craft_rank,
               v.sec, v.ter, v.sock, v.ilvl, v.tooltip, count(*) OVER () AS total
        FROM ah_deals d JOIN ah_items i USING (item_id) JOIN ah_variants v USING (variant_id)
        WHERE {' AND '.join(where)}
        ORDER BY {order} LIMIT {PAGE_SIZE} OFFSET %(offset)s""", p)
    names = _cached('classes', _class_names)
    out = [{'id': r['item_id'], 'name': r['name'], 'q': r['quality'], 'rank': r['craft_rank'], 'icon': icon_url(r),
            'sub': names.get((r['class_id'], r['subclass_id']), ('', ''))[1], 'cr': r['cr'], 'price': r['price'],
            'typical': r['typical'], 'realms': r['realms'], 'profit': r['profit'], 'proven': r['proven'],
            'sold_7d': r['sold_7d'], 'roll': {'sec': r['sec'], 'ter': r['ter'], 'sock': r['sock'], 'ilvl': r['ilvl'],
                                              'tooltip': r['tooltip']}} for r in rows]
    return out, (rows[0]['total'] if rows else 0)


async def handle_deals_api(request):
    rows, total = await asyncio.to_thread(deals, request.query)
    _offer((r['id'], r['roll']['tooltip']) for r in rows)
    return web.json_response({'rows': rows, 'total': total}, headers={'Cache-Control': 'no-store', **_headers()})


MOVER_LISTS = {
    # (kind, list) -> (extra condition, order)
    'up': ('m.change > 0', 'm.change DESC'),
    'down': ('m.change < 0', 'm.change ASC'),
    'low': ('m.supply_change < -0.2', 'm.supply_change ASC'),
}
MOVER_FLOOR = {  # what's too thin to mean anything: both prices and both supplies at least
    'commodity': (10000, 500),   # 1g, 500 on sale (thinner markets swing wildly on one bought-out stack)
    'item': (10000, 15),         # 1g, 15 listings
}


def movers(args):
    from datetime import datetime, timedelta, timezone
    kind = 'commodity' if args.get('kind') != 'item' else 'item'
    price_floor, supply_floor = MOVER_FLOOR[kind]
    summary = 'ah_commodity_summary' if kind == 'commodity' else 'ah_item_summary'
    out = {}
    for name, (condition, order) in MOVER_LISTS.items():
        out[name] = db.fetch_all(f"""
            SELECT m.item_id, m.now, m.was, m.change, m.supply_now, m.supply_was, m.supply_change, m.hours,
                   i.name, i.quality, i.icon, i.icon_file, i.class_id, i.subclass_id, i.craft_rank, s.sold_7d
            FROM ah_movers m JOIN ah_items i USING (item_id) LEFT JOIN {summary} s USING (item_id)
            WHERE m.kind = %s AND m.now >= %s AND m.was >= %s AND m.supply_now >= %s AND m.supply_was >= %s
              AND ABS(m.change) <= 10 AND {condition}
            ORDER BY {order} LIMIT 25""", (kind, price_floor, price_floor, supply_floor // (4 if name == 'low' else 1),
                                          supply_floor))
    ids = list({r['item_id'] for rows in out.values() for r in rows})
    lines = {}
    for r in db.fetch_all("""SELECT item_id, ts, med FROM ah_item_history WHERE item_id = ANY(%s) AND ts >= %s
                             ORDER BY item_id, ts""", (ids, datetime.now(timezone.utc) - timedelta(hours=48))):
        lines.setdefault(r['item_id'], []).append(r['med'])
    names = _cached('classes', _class_names)
    return {name: [{'id': r['item_id'], 'name': r['name'], 'q': r['quality'], 'rank': r['craft_rank'], 'icon': icon_url(r),
                    'sub': names.get((r['class_id'], r['subclass_id']), ('', ''))[1], 'now': r['now'], 'was': r['was'],
                    'change': r['change'], 'supply_now': r['supply_now'], 'supply_was': r['supply_was'],
                    'supply_change': r['supply_change'], 'hours': r['hours'], 'sold_7d': r['sold_7d'] or 0,
                    'line': lines.get(r['item_id'], [])} for r in rows] for name, rows in out.items()}


async def handle_movers_api(request):
    data = await asyncio.to_thread(movers, request.query)
    _offer((r['id'], '') for rows in data.values() for r in rows)
    return web.json_response(data, headers={'Cache-Control': 'no-store', **_headers()})


# ============================================================================
# Collection: what a character hasn't collected that's on sale
# ============================================================================

COLLECTION_BODY = """
<main id="collection-view">
  <div class="section-head"><h2>Collection</h2>
    <p>Look up a character to see the mounts, battle pets and toys they haven't collected that are for sale right now:
    on their own realm first, then wherever in EU it's cheapest. Collections come from the character's armory profile.</p></div>
  <section class="panel">
    <form class="search-head" id="c-form">
      <div class="search-row coll-lookup">
        <div class="field"><label for="c-name">Character</label>
          <div class="suggest">
            <input class="input big" id="c-name" type="text" placeholder="Start typing a name" autocomplete="off"
                   spellcheck="false" maxlength="12" required role="combobox" aria-autocomplete="list"
                   aria-expanded="false" aria-controls="c-suggest">
            <div class="suggest-pop" id="c-suggest-pop" hidden>
              <ul class="suggest-list" id="c-suggest" role="listbox" aria-label="Characters"></ul>
              <div class="suggest-foot" id="c-suggest-foot"></div>
            </div>
          </div></div>
        <label class="field"><span>Realm</span><select class="select big" id="c-realm" required></select></label>
        <button class="btn" type="submit" id="c-go">Look up</button>
      </div>
    </form>
    <div id="c-status" class="coll-status" role="status"></div>
    <div id="c-result" hidden>
      <div class="coll-summary" id="c-summary"></div>
      <div class="coll-tools">
        <div class="seg" role="group" aria-label="What to show" id="c-kind"></div>
        <label class="check"><input type="checkbox" id="c-here"> Only listed on their realm</label>
        <label class="field inline"><span>Sort by</span><select class="select" id="c-sort"></select></label>
      </div>
      <div class="result-meta"><span id="c-count"></span><span id="c-note"></span></div>
      <div class="table-wrap"><table id="coll"><thead></thead><tbody></tbody></table></div>
      <div class="more"><button type="button" class="btn-ghost" id="c-more" hidden>Show more</button></div>
    </div>
  </section>
</main>"""

# our kind -> Blizzard's name for the collection, and for each entry's id in it
COLLECTIONS = {'mount': ('mounts', 'mount'), 'pet': ('pets', 'species'), 'toy': ('toys', 'toy')}
CHARACTER_NAME = re.compile(r'^[^\W\d_]{2,12}$')
PROFILE_SECONDS = 600
PROFILES_KEPT = 500
_profiles = {}
_blizzard = None
_http = None
SUGGEST_URL = 'https://raider.io/api/search'
SUGGEST_SECONDS = 600
SUGGEST_KEPT = 2000
SUGGEST_SHOWN = 12
SUGGEST_AT_ONCE = asyncio.Semaphore(4)  # Raider.IO is doing us a favour: never more than a few questions at a time
USER_AGENT = 'LuminisAuctionHouse/1.0 (+https://luminisbot.flipflix.no/ah)'
_suggestions = {}


def _session():
    """One HTTP session for the pages' outside calls (Blizzard's profile API, Raider.IO's search)."""
    global _http
    if _http is None or _http.closed:
        import aiohttp
        _http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20), headers={'User-Agent': USER_AGENT})
    return _http


async def handle_collection_page(request):
    data = await asyncio.to_thread(_base_data, 'collection')
    return _page('Collection · Luminis Auction House', COLLECTION_BODY, data,
                 "The mounts, battle pets and toys a character hasn't collected that are for sale in EU right now.")


async def _collected(slug, name):
    """
    -> ({kind: set of mount, species or toy ids}, None), or (None, why not). From Blizzard's profile API with the
    site's client credentials (public profiles only), kept ten minutes so flipping filters and reloads cost nothing.
    """
    global _blizzard
    hit = _profiles.get((slug, name))
    if hit and time.monotonic() - hit[0] < PROFILE_SECONDS:
        return hit[1], None
    if _blizzard is None:
        from ..blizzard import Blizzard
        _blizzard = Blizzard(_session())

    async def one(kind):
        plural, entry = COLLECTIONS[kind]
        st, body, _ = await _blizzard.get(f'/profile/wow/character/{slug}/{name}/collections/{plural}', 'profile-eu')
        if st != 200:
            return kind, st
        return kind, {(e.get(entry) or {}).get('id') for e in json.loads(body).get(plural) or []} - {None}

    try:
        results = dict(await asyncio.gather(*(one(kind) for kind in COLLECTIONS)))
    except Exception as e:
        logger.warning(f'[AH] Collection lookup for {name}-{slug} failed: {e}')
        return None, 'unavailable'
    failed = [v for v in results.values() if not isinstance(v, set)]
    if failed:
        return None, 'not found' if 404 in failed or 403 in failed else 'unavailable'
    if len(_profiles) >= PROFILES_KEPT:
        _profiles.clear()
    _profiles[(slug, name)] = (time.monotonic(), results)
    return results, None


def collection(cr, owned):
    """The collectibles on sale that the character doesn't have, with the cheapest on their realm and in EU."""
    from ..prices import PRICE_CAP
    rows = db.fetch_all(f"""
        WITH c AS (SELECT item_id, kind, ref_id FROM ah_collectibles
                   UNION ALL SELECT item_id, 'pet', -item_id FROM ah_item_summary WHERE item_id < 0),
             here AS (SELECT l.item_id, min(l.buyout) AS price, count(*) AS n FROM ah_listings l
                      WHERE l.cr = %(cr)s AND l.buyout < %(cap)s AND {NO_WALL} GROUP BY l.item_id)
        SELECT c.item_id, c.kind, s.lo, s.lo_cr, s.med, s.realms, s.sold_7d, h.price AS here, h.n AS here_n,
               i.name, i.quality, i.icon, i.icon_file
        FROM c JOIN ah_item_summary s USING (item_id) JOIN ah_items i USING (item_id) LEFT JOIN here h USING (item_id)
        WHERE NOT s.walls_only
          AND NOT ((c.kind = 'mount' AND c.ref_id = ANY(%(mount)s)) OR (c.kind = 'pet' AND c.ref_id = ANY(%(pet)s))
                   OR (c.kind = 'toy' AND c.ref_id = ANY(%(toy)s)))""",
                        {'cr': cr, 'cap': PRICE_CAP, **{kind: sorted(ids) for kind, ids in owned.items()}})
    return [{'id': r['item_id'], 'kind': r['kind'], 'name': r['name'], 'q': r['quality'], 'icon': icon_url(r),
             'lo': r['lo'], 'lo_cr': r['lo_cr'], 'med': r['med'], 'realms': r['realms'], 'sold_7d': r['sold_7d'],
             'here': r['here'], 'here_n': r['here_n'] or 0} for r in rows]


async def handle_collection_api(request):
    headers = {'Cache-Control': 'no-store', **_headers()}
    slug = (request.query.get('realm') or '').strip().lower()
    name = (request.query.get('name') or '').strip().lower()
    groups = await asyncio.to_thread(_cached, 'realms', _realms)
    cr = next((int(c) for c, g in groups.items() if slug in g['slugs']), None)
    if not cr or not CHARACTER_NAME.match(name):
        return web.json_response({'error': 'Enter a character name and pick their realm.'}, status=400, headers=headers)
    owned, error = await _collected(slug, name)
    if error == 'not found':
        return web.json_response({'error': "We couldn't find that character. Check the name and realm: characters "
                                           "under level 10, or not played in a long while, don't show up."},
                                 status=404, headers=headers)
    if error:
        return web.json_response({'error': "Blizzard's armory didn't answer. Try again in a moment."}, status=502,
                                 headers=headers)
    rows = await asyncio.to_thread(collection, cr, owned)
    _offer((r['id'], '') for r in rows)
    return web.json_response({'cr': cr, 'owned': {kind: len(ids) for kind, ids in owned.items()}, 'rows': rows},
                             headers=headers)


async def _suggest(prefix):
    """
    -> [{name, realm, slug, cls, faction, avatar}]: EU characters on realms we know whose name starts with prefix,
    from Raider.IO's site search (the one raider.io's own search box uses - it isn't in their documented API, so
    it may change: then this is just empty and the page works as before). Kept ten minutes per prefix.
    """
    import aiohttp
    hit = _suggestions.get(prefix)
    if hit and time.monotonic() - hit[0] < SUGGEST_SECONDS:
        return hit[1]
    groups = await asyncio.to_thread(_cached, 'realms', _realms)
    known = {slug: name for g in groups.values() for name, slug in zip(g['names'], g['slugs'])}
    try:
        async with SUGGEST_AT_ONCE:
            async with _session().get(SUGGEST_URL, params={'term': prefix},
                                      timeout=aiohttp.ClientTimeout(total=6)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f'HTTP {resp.status}')
                matches = (await resp.json(content_type=None)).get('matches') or []
    except Exception as e:
        logger.info(f'[AH] Character suggestions for {prefix!r} unavailable: {e}')
        return None
    out, seen = [], set()
    for m in matches:
        d = m.get('data') or {}
        realm = d.get('realm') or {}
        slug = next((s for s in (realm.get('slug'), realm.get('altSlug')) if s in known), None)
        name = m.get('name') or d.get('name') or ''
        if m.get('type') != 'character' or (d.get('region') or {}).get('slug') != 'eu' or not slug:
            continue
        if not name.lower().startswith(prefix) or (name.lower(), slug) in seen:
            continue
        seen.add((name.lower(), slug))
        avatar = (d.get('thumbnail_url') or '').split('?')[0]
        out.append({'name': name, 'realm': known[slug], 'slug': slug, 'cls': (d.get('class') or {}).get('name') or '',
                    'faction': d.get('faction') or '',
                    'avatar': 'https:' + avatar if avatar.startswith('//render.worldofwarcraft.com/') else ''})
        if len(out) >= SUGGEST_SHOWN:
            break
    if len(_suggestions) >= SUGGEST_KEPT:
        _suggestions.clear()
    _suggestions[prefix] = (time.monotonic(), out)
    return out


async def handle_characters_api(request):
    headers = {'Cache-Control': 'public, max-age=300', **_headers()}
    prefix = (request.query.get('q') or '').strip().lower()
    if not CHARACTER_NAME.match(prefix):  # 2 to 12 letters, like a name
        return web.json_response({'rows': []}, headers=headers)
    rows = await _suggest(prefix)
    if rows is None:
        return web.json_response({'rows': [], 'unavailable': True}, headers={**headers, 'Cache-Control': 'no-store'})
    return web.json_response({'rows': rows}, headers=headers)


# ============================================================================
# Crafting: every recipe's reagent cost against what it makes sells for
# ============================================================================

CRAFTING_BODY = """
<main id="crafting-view">
  <div class="section-head"><h2>Crafting</h2>
    <p>Every recipe priced against the auction house right now: what its reagents cost to buy, what it makes sells
    for after the 5% auction cut, and whether it actually sells. Quality reagents and results come in ranks - pick
    rank 1 throughout, or the best rank of each. Commodities at their market price; gear at what it sold for this
    week, or what's asked until we've seen it sell. Before multicraft, resourcefulness and concentration.</p></div>
  <section class="panel">
    <form class="search-head" id="cr-form">
      <div class="filters">
        <label class="field"><span>Profession</span><select class="select" id="cr-prof"></select></label>
        <label class="field"><span>Expansion</span><select class="select" id="cr-exp"></select></label>
        <label class="field"><span>Sort by</span><select class="select" id="cr-sort"></select></label>
      </div>
      <div class="filter-foot">
        <div class="seg" role="group" aria-label="Reagent and result quality" id="cr-mode"></div>
        <div class="checks">
          <label class="check"><input type="checkbox" id="cr-sells"> Only what sells (seen selling this week)</label>
          <label class="check"><input type="checkbox" id="cr-profit"> Only profitable</label>
        </div>
      </div>
    </form>
    <div class="result-meta"><span id="cr-count"></span><span id="cr-note"></span></div>
    <div class="table-wrap"><table id="crafts"><thead></thead><tbody></tbody></table></div>
    <div class="more"><button type="button" class="btn-ghost" id="cr-more" hidden>Show more</button></div>
  </section>
</main>"""

CRAFT_SORTS = {'profit': lambda r: -r['profit'], 'margin': lambda r: -r['profit'] / max(r['cost'], 1),
               'sold': lambda r: (-r['sold_7d'], -r['profit'])}
TIER_FIRST = 4  # the recipe tables' tier index of Classic: tier index - 4 = the expansion (EXPANSIONS)


def _craft_prices():
    """
    item -> (unit price, sold in 7 days, only asked): commodities at their market price; other items at what they
    sold for this week once seen selling a few times, else the EU median of what's asked (old gear can ask millions)
    """
    from datetime import date, timedelta
    from ..prices import DEAL_PROVEN_SALES
    out = {r['item_id']: (r['market'], r['sold_7d'], False) for r in db.fetch_all(
        'SELECT item_id, market, sold_7d FROM ah_commodity_summary WHERE market > 0')}
    sold = {r['item_id']: r for r in db.fetch_all(
        'SELECT item_id, sum(sold) AS n, sum(revenue) AS revenue FROM ah_sales WHERE day > %s GROUP BY item_id',
        (date.today() - timedelta(days=7),))}
    for r in db.fetch_all('SELECT item_id, med, sold_7d FROM ah_item_summary WHERE item_id > 0 AND NOT walls_only'):
        s = sold.get(r['item_id'])
        if s and s['n'] >= DEAL_PROVEN_SALES:
            out.setdefault(r['item_id'], (round(s['revenue'] / s['n']), r['sold_7d'], False))
        else:
            out.setdefault(r['item_id'], (r['med'], r['sold_7d'], True))
    return out


def _crafts():
    """Every recipe priced twice - rank 1 reagents for a rank 1 result, and the best of each - for the crafting page."""
    from ..prices import AH_CUT
    slots = {}
    for r in db.fetch_all('SELECT recipe_id, slot, items, qty FROM ah_recipe_reagents ORDER BY recipe_id, slot'):
        slots.setdefault(r['recipe_id'], []).append((r['items'], r['qty']))
    price = _craft_prices()
    out = {'basic': [], 'top': []}
    skipped = {}
    for r in db.fetch_all('SELECT recipe_id, profession, tier_index, outputs, per_craft FROM ah_recipes'):
        if not any(i in price for i in r['outputs']):
            continue  # makes nothing that's on sale: nothing to compare with
        for mode, pick in (('basic', 0), ('top', -1)):
            made = r['outputs'][pick]
            parts = [(items[pick], qty) for items, qty in slots.get(r['recipe_id'], [])]
            if made not in price or not parts:
                continue
            if any(item not in price for item, _ in parts):
                key = (mode, r['profession'], r['tier_index'])
                skipped[key] = skipped.get(key, 0) + 1
                continue
            cost = sum(price[item][0] * qty for item, qty in parts)
            sell, sold, asked = price[made]
            out[mode].append({'recipe': r['recipe_id'], 'prof': r['profession'], 'tier': r['tier_index'],
                              'id': made, 'per': r['per_craft'], 'sell': sell, 'cost': cost, 'sold_7d': sold, 'asked': asked,
                              'profit': round(sell * r['per_craft'] * AH_CUT - cost),
                              'reagents': [(item, qty, price[item][0]) for item, qty in parts]})
    return out, skipped


def crafting(args):
    from ..crafting import PROFESSIONS
    rows, skipped = _cached('crafts', _crafts)
    mode = 'top' if args.get('mode') == 'top' else 'basic'
    tiers = sorted({r['tier'] for r in rows[mode]}, reverse=True)
    prof = _int(args, 'prof', 1, 10 ** 5)
    tier = _int(args, 'tier', 0, 100)
    if tier is None and tiers:
        tier = tiers[0]  # the newest expansion unless asked
    picked = [r for r in rows[mode] if (not prof or r['prof'] == prof) and (not tier or r['tier'] == tier)
              and (args.get('sells') != '1' or r['sold_7d'] > 0) and (args.get('profit') != '1' or r['profit'] > 0)]
    picked.sort(key=CRAFT_SORTS.get(args.get('sort'), CRAFT_SORTS['profit']))
    offset = _int(args, 'offset', 0, 100000) or 0
    page = picked[offset:offset + PAGE_SIZE]
    ids = {r['id'] for r in page} | {item for r in page for item, _, _ in r['reagents']}
    items = {i['item_id']: i for i in db.fetch_all(
        'SELECT item_id, name, quality, icon, icon_file, craft_rank FROM ah_items WHERE item_id = ANY(%s)', (list(ids),))}

    def describe(item_id):
        i = items.get(item_id) or {'name': f'Item {item_id}', 'quality': 1, 'craft_rank': 0}
        return {'id': item_id, 'name': i['name'], 'q': i['quality'], 'rank': i['craft_rank'], 'icon': icon_url(i)}

    out = [{**describe(r['id']), 'recipe': r['recipe'], 'prof': PROFESSIONS.get(r['prof'], ''), 'per': r['per'],
            'sell': r['sell'], 'cost': r['cost'], 'profit': r['profit'], 'sold_7d': r['sold_7d'], 'asked': r['asked'],
            'reagents': [{**describe(item), 'qty': qty, 'price': p} for item, qty, p in r['reagents']]} for r in page]
    names = {t: EXPANSIONS[t - TIER_FIRST] if 0 <= t - TIER_FIRST < len(EXPANSIONS) else f'Tier {t}' for t in tiers}
    missing = sum(n for (m, p, t), n in skipped.items() if m == mode and (not prof or p == prof) and (not tier or t == tier))
    return {'rows': out, 'total': len(picked), 'tier': tier, 'tiers': [[t, names[t]] for t in tiers],
            'professions': sorted(PROFESSIONS.items(), key=lambda p: p[1]), 'skipped': missing}


async def handle_crafting_page(request):
    data = await asyncio.to_thread(_base_data, 'crafting')
    return _page('Crafting · Luminis Auction House', CRAFTING_BODY, data,
                 'What every profession recipe costs to craft and what it sells for on the EU auction house.')


async def handle_crafting_api(request):
    data = await asyncio.to_thread(crafting, request.query)
    _offer((i['id'], '') for r in data['rows'] for i in [r] + r['reagents'])
    return web.json_response(data, headers={'Cache-Control': 'no-store', **_headers()})


async def handle_search_api(request):
    rows, total = await asyncio.to_thread(search, request.query)
    _offer((r['id'], '') for r in rows)
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
