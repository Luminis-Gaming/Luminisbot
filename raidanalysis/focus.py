"""
Focus over time for one pull: who a player was damaging, moment by moment, next to the rest of the raid -
so a priority add (the Venomous Heart that's up for 25 s) shows up as the window it was, and whether the
player was on it.

Data: WCL's damage-done graph by target for the raid and for the player (one request, v2 only), fetched
when someone opens the pull's focus view - not during the sync - and kept in raid_focus. The graph's
points are put into BUCKET_MS buckets and scaled so each target adds up to the damage the pull's
DamageDone table says (analysis['extras']), whatever unit WCL's points come in.

Pure functions apart from load().
"""
import logging

logger = logging.getLogger(__name__)

BUCKET_MS = 5000
FOCUS_VERSION = 1
MAX_TARGETS = 5              # colored targets; the rest fold into "Other"
OTHER = 'Other'
WINDOW_MIN_BUCKETS = 2       # an add the raid hit for less than this many buckets isn't a window
WINDOW_GAP_BUCKETS = 1       # quieter buckets than this inside a window don't split it
WINDOW_MIN_SHARE = 0.02      # an add taking less of the raid's damage over the pull isn't worth a window
PRIORITY_SHARE = 0.4         # the raid put this much of its damage into the add while it was up: a priority
LOW_FOCUS = 0.6              # ...and you put less than this × the raid's share into it: off target
GOOD_FOCUS = 0.85


# ============================================================================
# WCL graph -> buckets
# ============================================================================

def _points(series):
    """A graph series' points as (absolute ms, value): [[t, v]] pairs, {x, y} dicts or values on an interval."""
    data = series.get('data') or []
    if data and isinstance(data[0], (list, tuple)):
        return [(p[0], p[1] or 0) for p in data if len(p) >= 2 and p[0] is not None]
    if data and isinstance(data[0], dict):
        return [(p.get('x'), p.get('y') or 0) for p in data if p.get('x') is not None]
    start, step = series.get('pointStart'), series.get('pointInterval')
    if start is None or not step:
        return []
    return [(start + i * step, v or 0) for i, v in enumerate(data)]


def buckets(graph, fight_start, duration):
    """WCL graph JSON -> {target: {'type', 'b': [value per BUCKET_MS bucket]}} (unscaled)."""
    graph = (graph or {}).get('data', graph) or {}
    n = max(1, -(-duration // BUCKET_MS))
    out = {}
    for s in graph.get('series') or []:
        name = s.get('name')
        if not name or name in ('Total', 'Raid', 'All'):
            continue
        row = out.setdefault(name, {'type': s.get('type') or '', 'b': [0.0] * n})
        for t, v in _points(s):
            i = int((t - fight_start) // BUCKET_MS)
            if 0 <= i < n:
                row['b'][i] += max(0.0, float(v))
    return out


def calibrate(rows, totals):
    """Scale each target's buckets to its real damage (totals: {target: damage}); unknown targets are dropped."""
    out = {}
    for name, row in rows.items():
        raw = sum(row['b'])
        if not raw or not totals.get(name):
            continue
        k = totals[name] / raw
        out[name] = {'type': row['type'], 'b': [round(v * k) for v in row['b']]}
    return out


def from_graphs(raid_graph, player_graph, fight_start, duration, raid_totals, player_totals, types=None):
    """
    The cached shape: {'v', 'bucket_ms', 'n', 'raid': {target: {'type', 'b'}}, 'you': {...}}. types:
    {target: 'Boss' / 'NPC'} from the pull's DamageDone table - so a boss is never taken for an add even
    if the graph doesn't say.
    """
    raid = calibrate(buckets(raid_graph, fight_start, duration), raid_totals)
    you = calibrate(buckets(player_graph, fight_start, duration), player_totals)
    for side in (raid, you):
        for target, row in side.items():
            row['type'] = (types or {}).get(target) or row['type']
    return {'v': FOCUS_VERSION, 'bucket_ms': BUCKET_MS, 'n': max(1, -(-duration // BUCKET_MS)),
            'raid': raid, 'you': you}


# ============================================================================
# What it says (render time)
# ============================================================================

def palette_order(data):
    """Targets in color order: most raid damage first, MAX_TARGETS of them (the rest is OTHER)."""
    totals = {t: sum(r['b']) for t, r in (data.get('raid') or {}).items()}
    for t, r in (data.get('you') or {}).items():
        totals.setdefault(t, sum(r['b']))
    return [t for t, _ in sorted(totals.items(), key=lambda kv: -kv[1])][:MAX_TARGETS]


def folded(side, order):
    """{target or OTHER: buckets} for one side ('raid' / 'you'), the targets past the palette folded in."""
    out = {}
    for name, row in (side or {}).items():
        key = name if name in order else OTHER
        acc = out.setdefault(key, [0] * len(row['b']))
        for i, v in enumerate(row['b']):
            acc[i] += v
    return out


def _runs(active, gap=WINDOW_GAP_BUCKETS):
    """Index runs [(first, last)] where active is true, bridging gaps of up to `gap` buckets."""
    runs, start, quiet = [], None, 0
    for i, on in enumerate(active + [False] * (gap + 1)):
        if on:
            if start is None:
                start = i
            quiet, last = 0, i
        elif start is not None:
            quiet += 1
            if quiet > gap:
                runs.append((start, last))
                start, quiet = None, 0
    return runs


def windows(data):
    """
    When each add was up (the raid was hitting it) and what everyone did then (data['peers']: how many
    DPS and tanks the raid had, for its average per player):
    [{'target', 'type', 'start', 'end' (ms), 'raid_share', 'you_share', 'you_dps', 'raid_dps' (per player),
      'priority', 'verdict'}] - bosses aren't windows (they're up all pull).
    """
    raid, you = data.get('raid') or {}, data.get('you') or {}
    step = data.get('bucket_ms') or BUCKET_MS
    n = data.get('n') or 0
    raid_total = sum(sum(r['b']) for r in raid.values()) or 1
    raid_per_bucket = [sum(r['b'][i] for r in raid.values()) for i in range(n)]
    you_per_bucket = [sum(r['b'][i] for r in you.values()) for i in range(n)]
    out = []
    for target, row in raid.items():
        if row['type'] == 'Boss' or sum(row['b']) < WINDOW_MIN_SHARE * raid_total:
            continue
        for first, last in _runs([v > 0 for v in row['b']]):
            if last - first + 1 < WINDOW_MIN_BUCKETS:
                continue
            span = range(first, last + 1)
            seconds = len(span) * step / 1000
            raid_on, raid_all = sum(row['b'][i] for i in span), sum(raid_per_bucket[i] for i in span)
            mine = (you.get(target) or {}).get('b') or [0] * n
            you_on, you_all = sum(mine[i] for i in span), sum(you_per_bucket[i] for i in span)
            raid_share = raid_on / raid_all if raid_all else 0
            you_share = you_on / you_all if you_all else 0
            priority = raid_share >= PRIORITY_SHARE
            verdict = None
            if priority and you_all:
                verdict = ('good' if you_share >= GOOD_FOCUS * raid_share else
                           'off' if you_share < LOW_FOCUS * raid_share else 'ok')
            out.append({'target': target, 'type': row['type'], 'start': first * step, 'end': (last + 1) * step,
                        'raid_share': raid_share, 'you_share': you_share, 'you_dps': you_on / seconds,
                        'raid_dps': raid_on / seconds / max(1, data.get('peers') or 1), 'priority': priority,
                        'verdict': verdict})
    return sorted(out, key=lambda w: w['start'])


def target_rows(data):
    """Per target over the pull: your damage, its share, your DPS on it while it was up (raid hitting it)."""
    raid, you = data.get('raid') or {}, data.get('you') or {}
    step = data.get('bucket_ms') or BUCKET_MS
    mine_total = sum(sum(r['b']) for r in you.values()) or 0
    rows = []
    for target in set(raid) | set(you):
        alive = sum(1 for v in (raid.get(target) or {}).get('b') or [] if v > 0) * step / 1000
        mine = sum((you.get(target) or {}).get('b') or [])
        rows.append({'target': target, 'type': (raid.get(target) or you.get(target) or {}).get('type') or '',
                     'damage': mine, 'share': mine / mine_total if mine_total else 0,
                     'up_s': alive, 'dps': mine / alive if alive else 0})
    return sorted(rows, key=lambda r: -r['damage'])


# ============================================================================
# Loading (on demand, cached)
# ============================================================================

async def load(code, pull, name, extras):
    """
    The focus data for one player in one pull: cached in raid_focus, else fetched from WCL now (one v2
    request). Returns (data or None, why-not message or None).
    """
    import aiohttp
    from . import db, sync, wcl
    fight_id = pull['fight_id']
    cached = db.get_focus(code, fight_id, name)
    if cached and cached.get('v') == FOCUS_VERSION:
        return cached, None
    if sync._paused() or wcl.v2_blocked():
        return None, "Warcraft Logs' hourly budget is used up - the focus timeline loads once it resets."
    me = (extras.get('players') or {}).get(name) or {}
    raid_totals = {t['name']: t['total'] for t in extras.get('targets') or []}
    player_totals = {t: d for t, d, _ in me.get('targets') or []}
    try:
        async with aiohttp.ClientSession() as session:
            actor = (await wcl.get_actor_ids(session, code)).get(name)
            if not actor:
                return None, f"{name} isn't in this log's player list."
            graphs = await wcl.get_focus_graphs(session, code, fight_id, actor)
    except wcl.WCLError as e:
        logger.warning(f'[RAIDS] Focus graphs for {code}#{fight_id} {name} failed: {e}')
        return None, "Couldn't load the timeline from Warcraft Logs right now - try again in a bit."
    duration = pull['end_ms'] - pull['start_ms']
    types = {t['name']: t.get('type') for t in extras.get('targets') or []}
    data = from_graphs(graphs.get('raid'), graphs.get('you'), pull['start_ms'], duration, raid_totals, player_totals,
                       types)
    if not data['raid'] and not data['you']:
        return None, 'Warcraft Logs had no damage graph for this pull.'
    db.save_focus(code, fight_id, name, data)
    return data, None
