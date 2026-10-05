"""
Focus over time for one pull: who a player was damaging, second by second, next to when each add was
up - so a priority add (the Venomous Heart that's up for 25 s) shows up as the window it was, and whether
the player was on it.

Data: WCL damage events, fetched when someone opens the pull's focus view - not during the sync - and kept
in raid_focus: the player's own (pets included, one request), and once per pull (shared by everyone's view)
the pull's RAID_SAMPLE top DPS's - "the raid" here: when each add appeared (their first hit), what share of
their damage it got, whether it died (the enemies' deaths) or just went away. All of the raid's events would
be far past WCL's budget on a long pull. Damage is summed into BIN_MS bins per target. (WCL's damage graph
was too coarse for this: about one point every 45 s.)

Filters go by name: in WCL's filter expressions source.id / target.id are game ids (NPC id, player GUID),
not the report's actor ids - filtering on those silently matches nothing (or everything).

Pure functions apart from load().
"""
import logging

logger = logging.getLogger(__name__)

BIN_MS = 1000
FOCUS_VERSION = 5
RAID_KEY = '*raid*'          # raid_focus row (as the player name) holding the raid sample's damage and deaths
RAID_SAMPLE = 5              # the pull's top DPS whose damage stands for the raid's
RAID_MAX_EVENTS = 250000      # their events on a long pull: ~10k a minute (each page of 10k costs about a WCL point)
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
MIN_STRETCH_BINS = 3         # shorter than this on a target (cleave, a DoT ticking elsewhere): not a switch
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


def first_hits(events, fight_start, names_by_id):
    """
    Damage events -> {target name: [ms into the pull]}: the exact moment of each first hit on a target after
    more than GAP_BINS seconds of nothing on it - when an add appeared (to the ms, not the bin: a potion 10 s
    or 12 s before it is the whole point).
    """
    out, last = {}, {}
    for e in sorted((e for e in events or [] if e.get('type') == 'damage'), key=lambda e: e['timestamp']):
        name = names_by_id.get(e.get('targetID'))
        if not name:
            continue
        t = e['timestamp'] - fight_start
        if name not in last or t - last[name] > GAP_BINS * BIN_MS:
            out.setdefault(name, []).append(t)
        last[name] = t
    return out


def deaths_by_target(events, fight_start, names_by_id):
    """Enemy death events -> {target name: [ms into the pull]}."""
    out = {}
    for e in events or []:
        name = names_by_id.get(e.get('targetID'))
        if name and e.get('type') == 'death':
            out.setdefault(name, []).append(e['timestamp'] - fight_start)
    return {k: sorted(v) for k, v in out.items()}


def build(you_bins, raid_part, n, targets, you_in_sample=False, you_firsts=None):
    """
    The cached shape: {'v', 'bin_ms', 'n', 'main', 'sample', 'deaths', 'you': {target: {'type', 'b'}},
    'raid': {target: {'type', 'b'}}} - raid: the sample's damage on every target, the main boss included.
    targets: the pull's DamageDone table by target ([{'name', 'total', 'type'}]), for their types. You're
    part of the raid: unless you're in the sample already, your damage is added to its (an add only you hit
    was still up). 'appear' / 'you_first': first_hits() of the raid (you included) and of you.
    """
    you_firsts = you_firsts or {}
    appear = {t: list(v) for t, v in (raid_part.get('appear') or {}).items()}
    if not you_in_sample:
        for t, v in you_firsts.items():
            appear[t] = sorted(appear.get(t, []) + v)
    types = {t['name']: t.get('type') or '' for t in targets or []}
    raid_bins = {t: list(b) for t, b in (raid_part.get('b') or {}).items()}
    if not you_in_sample:
        for t, b in you_bins.items():
            row = raid_bins.setdefault(t, [0] * n)
            for i, v in enumerate(b):
                row[i] += v
    return {'v': FOCUS_VERSION, 'bin_ms': BIN_MS, 'n': n, 'main': raid_part.get('main'),
            'sample': raid_part.get('sample') or [], 'deaths': raid_part.get('deaths') or {},
            'appear': appear, 'you_first': you_firsts,
            'you': {t: {'type': types.get(t, ''), 'b': b} for t, b in you_bins.items()},
            'raid': {t: {'type': types.get(t, ''), 'b': b} for t, b in raid_bins.items()}}


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
    most of your damage over the last SMOOTH_BINS seconds, runs of the same one merged, quiet stretches of up
    to GAP_BINS bridged, and anything shorter than MIN_STRETCH_BINS folded into the stretch before it (cleave
    and DoTs ticking elsewhere aren't switches). Targets past the palette count as OTHER.
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
    steady = []
    for r in out:
        prev = steady[-1] if steady else None
        if prev and (r['last'] - r['first'] + 1 < MIN_STRETCH_BINS or prev['target'] == r['target']) \
                and r['first'] - prev['last'] - 1 <= GAP_BINS:
            prev['last'] = r['last']  # a blip (or the same target again): still on the one before
        else:
            steady.append(dict(r))
    out = steady
    return [{'target': r['target'], 'start': r['first'] * step, 'end': (r['last'] + 1) * step,
             'damage': sum(rows[r['target']][r['first']:r['last'] + 1])} for r in out]


def windows(data):
    """
    When each add was up (the raid sample was hitting it) and what everyone did then:
    [{'target', 'type', 'start', 'end' (ms), 'raid_share', 'you_share', 'you_dps', 'raid_dps' (per sampled
      player), 'priority', 'verdict', 'died_at' (ms, None when it just stopped being hit), 'first_hit' (ms
      after it appeared that you first hit it, None if you never did)}] - start is the raid's first hit (when
    it could be attacked), to the ms; raid_share / you_share: of all the raid's / your damage in the window.
    The main boss and anything up all pull aren't windows.
    """
    raid, you = data.get('raid') or {}, data.get('you') or {}
    step, n = data.get('bin_ms') or BIN_MS, data.get('n') or 0
    raid_per_bin = [sum(r['b'][i] for r in raid.values()) for i in range(n)]
    raid_total = sum(raid_per_bin) or 1
    you_per_bin = [sum(r['b'][i] for r in you.values()) for i in range(n)]
    sampled = max(1, len(data.get('sample') or []))
    out = []
    for target, row in raid.items():
        if target == data.get('main') or sum(row['b']) < WINDOW_MIN_SHARE * raid_total or always_up(row, n):
            continue
        for first, last in runs(row['b'], min_len=WINDOW_MIN_BINS):
            span = range(first, last + 1)
            seconds = len(span) * step / 1000
            raid_on, raid_all = sum(row['b'][i] for i in span), sum(raid_per_bin[i] for i in span)
            mine = (you.get(target) or {}).get('b') or [0] * n
            you_on, you_all = sum(mine[i] for i in span), sum(you_per_bin[i] for i in span)
            raid_share = raid_on / raid_all if raid_all else 0
            you_share = you_on / you_all if you_all else 0
            priority = raid_share >= PRIORITY_SHARE
            verdict = None
            if priority and you_all:
                verdict = ('good' if you_share >= GOOD_FOCUS * raid_share else
                           'off' if you_share < LOW_FOCUS * raid_share else 'ok')
            end = (last + 1) * step
            # To the ms: the first hit on it in this window's first second (else the bin's start)
            start = next((t for t in (data.get('appear') or {}).get(target) or []
                          if first * step <= t < (first + 1) * step), first * step)
            died = next((t for t in (data.get('deaths') or {}).get(target) or []
                         if start - step <= t <= end + DEATH_SLACK_MS), None)
            yours = next((t for t in (data.get('you_first') or {}).get(target) or [] if start <= t < end), None)
            if yours is None:  # cached before exact times, or your first hit wasn't after a pause on it
                hit = next((i for i in span if mine[i] > 0), None)
                yours = max(start, hit * step) if hit is not None else None
            out.append({'target': target, 'type': row['type'], 'start': start, 'end': end,
                        'died_at': died, 'first_hit': yours - start if yours is not None else None,
                        'raid_share': raid_share, 'you_share': you_share, 'you_dps': you_on / seconds,
                        'raid_dps': raid_on / seconds / sampled, 'priority': priority,
                        'verdict': verdict})
    return sorted(out, key=lambda w: w['start'])


def up_ms(data, target):
    """How long a target was up: the pull for the main boss (and anything the raid hit all fight), else
    the stretches the raid was hitting it."""
    n, step = data.get('n') or 0, data.get('bin_ms') or BIN_MS
    row = (data.get('raid') or {}).get(target)
    if target == data.get('main') or row is None or always_up(row, n):
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

def raid_sample(pull, extras):
    """The pull's RAID_SAMPLE top damage dealers (not healers or tanks), from its DamageDone table."""
    roles = {p['name']: p.get('role') for p in (pull.get('analysis') or {}).get('players') or []}
    dealers = [(n, r.get('damage') or 0) for n, r in (extras.get('players') or {}).items()
               if roles.get(n) not in ('healer', 'tank')]
    return [n for n, _ in sorted(dealers, key=lambda kv: -kv[1])[:RAID_SAMPLE]]


def _sources_filter(names):
    """Damage done by these players and their pets."""
    names = [n.replace('"', '') for n in names]
    who = ' or '.join(f'source.name = "{n}" or source.owner.name = "{n}"' for n in names)
    return f'type = "damage" and ({who})'


async def load(code, pull, name, extras):
    """
    The focus data for one player in one pull: cached in raid_focus, else fetched from WCL now (the player's
    damage events; the raid sample's and the enemies' deaths once per pull). Returns (data or None, why-not
    message or None).
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
            mine = await wcl.get_events(session, code, fight_id, 'DamageDone', _sources_filter([name]))
            raid = db.get_focus(code, fight_id, RAID_KEY)
            if not raid or raid.get('v') != FOCUS_VERSION:
                sample = raid_sample(pull, extras)
                events = await wcl.get_events(session, code, fight_id, 'DamageDone', _sources_filter(sample),
                                              max_events=RAID_MAX_EVENTS) if sample else []
                deaths = await wcl.get_events(session, code, fight_id, 'Deaths', 'type = "death"', hostility='Enemies')
                raid = {'v': FOCUS_VERSION, 'main': targets[0]['name'] if targets else None, 'sample': sample,
                        'b': bin_damage(events, start, n, enemies), 'appear': first_hits(events, start, enemies),
                        'deaths': deaths_by_target(deaths, start, enemies)}
                db.save_focus(code, fight_id, RAID_KEY, raid)
    except wcl.WCLError as e:
        logger.warning(f'[RAIDS] Focus events for {code}#{fight_id} {name} failed: {e}')
        return None, "Couldn't load the timeline from Warcraft Logs right now - try again in a bit."
    data = build(bin_damage(mine, start, n, enemies), raid, n, targets, name in (raid.get('sample') or []),
                 first_hits(mine, start, enemies))
    if not data['you']:
        # Which step lost it: no events at all, events on actors we don't know as enemies, or outside the pull
        hits = [e for e in mine or [] if e.get('type') == 'damage']
        known = [e for e in hits if e.get('targetID') in enemies]
        inside = [e for e in known if 0 <= e['timestamp'] - start < n * BIN_MS]
        stats = (f'{len(mine or [])} event(s) from WCL, {len(hits)} damage, {len(known)} on a known enemy, '
                 f'{len(inside)} inside the pull')
        sample = {k: (mine or [{}])[0].get(k) for k in ('type', 'timestamp', 'sourceID', 'targetID', 'amount')}
        logger.warning(f'[RAIDS] Focus for {code}#{fight_id} {name} came back empty: {stats}; '
                       f'pull {start}-{pull["end_ms"]}, {len(enemies)} enemies known, first event {sample}')
        return None, f'Warcraft Logs has no damage from {name} on any enemy in this pull ({stats}).'
    db.save_focus(code, fight_id, name, data)
    return data, None
