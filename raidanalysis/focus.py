"""
Focus over time for one pull: who a player was damaging, second by second, next to when each add was
up - so a priority add (the Venomous Heart that's up for 25 s) shows up as the window it was, and whether
the player was on it.

Data: WCL damage events, fetched when someone opens the pull's focus view - not during the sync - and kept
in raid_focus: the player's own (pets included, one request) and the raid's on everything but the main
boss plus the enemies' deaths (once per pull, shared by everyone's view: when each add appeared - the
raid's first hit - how hard the raid hit it, and whether it died or just went away). Damage is summed
into BIN_MS bins per target. (WCL's damage graph was too coarse for this: about one point
every 45 s.)

Pure functions apart from load().
"""
import logging

logger = logging.getLogger(__name__)

BIN_MS = 1000
FOCUS_VERSION = 3
RAID_KEY = '*raid*'          # raid_focus row (as the player name) holding the raid's damage on the adds
MAX_TARGETS = 6              # colored targets; the rest fold into "Other"
OTHER = 'Other'
GAP_BINS = 3                 # no damage on a target for up to this long: still the same stretch on it
WINDOW_MIN_BINS = 3          # an add the raid hit for less than this isn't a window
WINDOW_MIN_SHARE = 0.01      # an add taking less of the raid's damage over the pull isn't worth a window
ALWAYS_UP = 0.9              # a target the raid hit for this much of the pull is up all fight (a second boss)
PRIORITY_SHARE = 0.4         # the raid put this much of its usual damage into the add while it was up: a priority
LOW_FOCUS = 0.6              # ...and you put less than this × the raid's share into it: off target
GOOD_FOCUS = 0.85
SMOOTH_BINS = 3              # "your target" at a moment: who got most of your damage over this many seconds
DEATH_SLACK_MS = 3000        # a death this close after the raid's last hit on an add: the window ended with it dying


# ============================================================================
# Events -> bins
# ============================================================================

def bin_damage(events, fight_start, n, names_by_id):
    """Damage events -> {target name: [damage per BIN_MS bin]} (amount + absorbed, as WCL's tables count it)."""
    out = {}
    for e in events or []:
        if e.get('type') != 'damage':
            continue
        name = names_by_id.get(e.get('targetID'))
        if not name:
            continue  # a player or pet (friendly fire), or an actor the log doesn't name
        i = int((e['timestamp'] - fight_start) // BIN_MS)
        if 0 <= i < n:
            row = out.setdefault(name, [0] * n)
            row[i] += (e.get('amount') or 0) + (e.get('absorbed') or 0)
    return out


def deaths_by_target(events, fight_start, names_by_id):
    """Enemy death events -> {target name: [ms into the pull]}."""
    out = {}
    for e in events or []:
        name = names_by_id.get(e.get('targetID'))
        if name and e.get('type') == 'death':
            out.setdefault(name, []).append(e['timestamp'] - fight_start)
    return {k: sorted(v) for k, v in out.items()}


def build(you_bins, raid_part, n, targets):
    """
    The cached shape: {'v', 'bin_ms', 'n', 'main', 'raid_dps', 'you': {target: {'type', 'b'}}, 'raid': {add:
    {'type', 'b'}}}. targets: the pull's DamageDone table by target ([{'name', 'total', 'type'}], biggest
    first) - their types, and the raid's average DPS over the pull.
    """
    types = {t['name']: t.get('type') or '' for t in targets or []}
    seconds = max(1, n * BIN_MS / 1000)
    return {'v': FOCUS_VERSION, 'bin_ms': BIN_MS, 'n': n, 'main': raid_part.get('main'),
            'deaths': raid_part.get('deaths') or {},
            'raid_dps': sum(t.get('total') or 0 for t in targets or []) / seconds,
            'you': {t: {'type': types.get(t, ''), 'b': b} for t, b in you_bins.items()},
            'raid': {t: {'type': types.get(t, ''), 'b': b} for t, b in (raid_part.get('b') or {}).items()}}


# ============================================================================
# What it says (render time)
# ============================================================================

def runs(values, gap=GAP_BINS, min_len=1):
    """Index runs [(first, last)] where values are > 0, bridging quiet stretches of up to `gap` bins."""
    out, start, last = [], None, None
    for i, v in enumerate(values):
        if v > 0:
            if start is not None and i - last - 1 > gap:
                out.append((start, last))
                start = None
            if start is None:
                start = i
            last = i
    if start is not None:
        out.append((start, last))
    return [(a, b) for a, b in out if b - a + 1 >= min_len]


def always_up(row, n):
    return sum(b - a + 1 for a, b in runs(row['b'])) >= ALWAYS_UP * n


def palette_order(data):
    """Targets in color order: most of your damage first, then the adds the raid hit - MAX_TARGETS of them."""
    totals = {t: sum(r['b']) for t, r in (data.get('you') or {}).items()}
    order = [t for t, v in sorted(totals.items(), key=lambda kv: -kv[1]) if v]
    adds = sorted(((t, sum(r['b'])) for t, r in (data.get('raid') or {}).items() if t not in totals),
                  key=lambda kv: -kv[1])
    return (order + [t for t, _ in adds])[:MAX_TARGETS]


def folded(side, order):
    """{target or OTHER: bins} for one side ('raid' / 'you'), the targets past the palette folded in."""
    out = {}
    for name, row in (side or {}).items():
        key = name if name in order else OTHER
        acc = out.setdefault(key, [0] * len(row['b']))
        for i, v in enumerate(row['b']):
            acc[i] += v
    return out


def your_targets(data, order):
    """
    Who you were hitting, moment by moment: [{'target', 'start', 'end' (ms), 'damage'}] - the target that got
    most of your damage over the last SMOOTH_BINS seconds (so DoTs and cleave don't flicker), runs of the
    same one merged, quiet stretches of up to GAP_BINS bridged. Targets past the palette count as OTHER.
    """
    rows = folded(data.get('you'), order)
    n, step = data.get('n') or 0, data.get('bin_ms') or BIN_MS
    if not rows or not n:
        return []
    picks = []
    for i in range(n):
        lo = max(0, i - SMOOTH_BINS + 1)
        here = {t: b[i] for t, b in rows.items() if b[i] > 0}
        if not here:
            picks.append(None)
            continue
        recent = {t: sum(rows[t][lo:i + 1]) for t in here}
        picks.append(max(recent, key=recent.get))
    out = []
    for i, target in enumerate(picks):
        if target is None:
            continue
        cur = out[-1] if out else None
        if cur and cur['target'] == target and i - cur['last'] - 1 <= GAP_BINS:
            cur['last'] = i
        else:
            out.append({'target': target, 'first': i, 'last': i})
    return [{'target': r['target'], 'start': r['first'] * step, 'end': (r['last'] + 1) * step,
             'damage': sum(rows[r['target']][r['first']:r['last'] + 1])} for r in out]


def windows(data):
    """
    When each add was up (the raid was hitting it) and what everyone did then (data['peers']: how many
    DPS and tanks the raid had, for its average per player):
    [{'target', 'type', 'start', 'end' (ms), 'raid_share', 'you_share', 'you_dps', 'raid_dps' (per player),
      'priority', 'verdict', 'died_at' (ms, None when it just stopped being hit), 'first_hit' (ms after it
      appeared that you first hit it, None if you never did)}] - start is the raid's first hit (when it
    could be attacked), raid_share against the raid's average DPS over the pull. Bosses aren't windows
    (they're up all pull).
    """
    raid, you = data.get('raid') or {}, data.get('you') or {}
    step, n = data.get('bin_ms') or BIN_MS, data.get('n') or 0
    raid_dps = data.get('raid_dps') or 0
    raid_total = raid_dps * n * step / 1000 or 1
    you_per_bin = [sum(r['b'][i] for r in you.values()) for i in range(n)]
    out = []
    for target, row in raid.items():
        if sum(row['b']) < WINDOW_MIN_SHARE * raid_total or always_up(row, n):
            continue
        for first, last in runs(row['b'], min_len=WINDOW_MIN_BINS):
            span = range(first, last + 1)
            seconds = len(span) * step / 1000
            raid_on = sum(row['b'][i] for i in span)
            mine = (you.get(target) or {}).get('b') or [0] * n
            you_on, you_all = sum(mine[i] for i in span), sum(you_per_bin[i] for i in span)
            raid_share = min(1.0, raid_on / (raid_dps * seconds)) if raid_dps else 0
            you_share = you_on / you_all if you_all else 0
            priority = raid_share >= PRIORITY_SHARE
            verdict = None
            if priority and you_all:
                verdict = ('good' if you_share >= GOOD_FOCUS * raid_share else
                           'off' if you_share < LOW_FOCUS * raid_share else 'ok')
            start, end = first * step, (last + 1) * step
            died = next((t for t in (data.get('deaths') or {}).get(target) or []
                         if start - step <= t <= end + DEATH_SLACK_MS), None)
            hit = next((i for i in span if mine[i] > 0), None)
            out.append({'target': target, 'type': row['type'], 'start': start, 'end': end,
                        'died_at': died, 'first_hit': (hit - first) * step if hit is not None else None,
                        'raid_share': raid_share, 'you_share': you_share, 'you_dps': you_on / seconds,
                        'raid_dps': raid_on / seconds / max(1, data.get('peers') or 1), 'priority': priority,
                        'verdict': verdict})
    return sorted(out, key=lambda w: w['start'])


def up_ms(data, target):
    """How long a target was up: the pull for the main boss (and anything the raid hit all fight), else
    the stretches the raid was hitting it."""
    n, step = data.get('n') or 0, data.get('bin_ms') or BIN_MS
    row = (data.get('raid') or {}).get(target)
    if row is None or always_up(row, n):
        return n * step
    return sum(b - a + 1 for a, b in runs(row['b'])) * step


def target_rows(data):
    """Per target over the pull: your damage, its share, how long it was up and your DPS on it while up."""
    you = data.get('you') or {}
    mine_total = sum(sum(r['b']) for r in you.values()) or 0
    rows = []
    for target, row in you.items():
        mine = sum(row['b'])
        up = up_ms(data, target) / 1000
        rows.append({'target': target, 'type': row.get('type') or '', 'damage': mine,
                     'share': mine / mine_total if mine_total else 0, 'up_s': up, 'dps': mine / up if up else 0})
    return sorted(rows, key=lambda r: -r['damage'])


# ============================================================================
# Loading (on demand, cached)
# ============================================================================

async def load(code, pull, name, extras):
    """
    The focus data for one player in one pull: cached in raid_focus, else fetched from WCL now (the player's
    damage events; the raid's on the adds once per pull). Returns (data or None, why-not message or None).
    """
    import aiohttp
    from . import db, sync, wcl
    fight_id = pull['fight_id']
    cached = db.get_focus(code, fight_id, name)
    if cached and cached.get('v') == FOCUS_VERSION:
        return cached, None
    if sync._paused() or wcl.v2_blocked():
        return None, "Warcraft Logs' hourly budget is used up - the focus timeline loads once it resets."
    start, n = pull['start_ms'], max(1, -(-(pull['end_ms'] - pull['start_ms']) // BIN_MS))
    targets = extras.get('targets') or []
    try:
        async with aiohttp.ClientSession() as session:
            actors = await wcl.get_report_actors(session, code)
            me = next((a for a in actors if a['name'] == name and a.get('type') == 'Player'), None)
            if not me:
                return None, f"{name} isn't in this log's player list."
            enemies = {a['id']: a['name'] for a in actors if a.get('type') not in ('Player', 'Pet')}
            sources = [me['id']] + [a['id'] for a in actors if a.get('petOwner') == me['id']]
            mine = await wcl.get_events(session, code, fight_id, 'DamageDone',
                                        f"type = \"damage\" and source.id in ({','.join(map(str, sources))})")
            raid = db.get_focus(code, fight_id, RAID_KEY)
            if not raid or raid.get('v') != FOCUS_VERSION:
                # Everything but the main boss: up all fight, and most of the raid's events
                main = targets[0]['name'] if targets else None
                skip = [i for i, n_ in enemies.items() if n_ == main]
                where = 'type = "damage"' + (f" and target.id not in ({','.join(map(str, skip))})" if skip else '')
                events = await wcl.get_events(session, code, fight_id, 'DamageDone', where, max_events=80000)
                deaths = await wcl.get_events(session, code, fight_id, 'Deaths', 'type = "death"', hostility='Enemies')
                raid = {'v': FOCUS_VERSION, 'main': main, 'b': bin_damage(events, start, n, enemies),
                        'deaths': deaths_by_target(deaths, start, enemies)}
                db.save_focus(code, fight_id, RAID_KEY, raid)
    except wcl.WCLError as e:
        logger.warning(f'[RAIDS] Focus events for {code}#{fight_id} {name} failed: {e}')
        return None, "Couldn't load the timeline from Warcraft Logs right now - try again in a bit."
    data = build(bin_damage(mine, start, n, enemies), raid, n, targets)
    if not data['you']:
        return None, f'Warcraft Logs has no damage from {name} on any enemy in this pull.'
    db.save_focus(code, fight_id, name, data)
    return data, None
