"""
Defensives used well (or not) - for healers and DPS; tanks press them all the time, so they're left out.

At sync, every enemy hit on a player in the pull (one events request, ~5 WCL points) is boiled down into
analysis['incoming']:
    {'v', 'step' (ms per bucket), 'players': {name: [thousands per bucket, ...]},
     'top': {name: {bucket: ability id}} (heavy buckets only), 'spans': {name: {spell id: [[start ms, end ms], ...]}}}
'players' is what came at each player, bucket by bucket - the damage *before* armour, defensives and absorbs
(unmitigatedAmount), so what a defensive soaked still counts as coming at you. 'spans' is when each of their
own buffs was up, read off the hits themselves (WCL lists the target's buffs on every hit) - exact, no
duration tables.

From that, per pull (moments()):
    - each personal defensive pressed: what it was up for - damage aimed at you (yours several times your
      normal rate, a bigger share of the raid's than usual), a raid-wide burst (everyone's well above normal),
      or a quiet moment;
    - spikes with no defensive up: a few seconds that brought a big part of your pull's damage.
coach.defensive_insights() turns those into stars and, for a clear pattern only, a gentle tip.
"""
VERSION = 1
STEP_MS = 2000
TOP_BUCKET_RATE = 2.0  # buckets this many times a player's average keep the ability behind them
SPAN_GAP_MS = 3000         # hits with the buff this close together are one span
DEFAULT_ACTIVE_MS = 8000   # a defensive with no hits while it was up: measured over this long
MAX_ACTIVE_MS = 20000
INCOMING_MIN_PULL_MS = 20000
EVENTS_MAX = 60000
EVENTS_FILTER = "source.disposition = 'enemy' and target.type = 'Player'"

HEAVY_FOR_YOU = 2.5        # your incoming over your pull's average rate: heavy for you...
AIMED_SHARE = 1.8          # ...with this many times your usual share of the raid's: aimed at you
RAID_BURST = 1.8           # the raid's incoming over its average rate: a raid-wide burst
SPIKE_WINDOW_S = 5
SPIKE_SHARE = 0.10         # a spike: this much of your pull's incoming damage in SPIKE_WINDOW_S...
SPIKE_RATE = 4.0           # ...at this many times your average rate


# Instant self-heals: nothing to be "up" for - not judged
REACTIVE = {'Exhilaration', 'Crimson Vial', 'Renewal', 'Alter Time', 'Desperate Prayer', 'Lichborne'}
# Immunities are often pressed for a mechanic (soak, clear a debuff) the damage doesn't show: stars, never "quiet"
IMMUNITIES = {'Ice Block', 'Divine Shield', 'Aspect of the Turtle', 'Cloak of Shadows', 'Netherwalk'}
# ...and these are pressed for other things too (reflecting a cast, damage, getting out of something)
NOT_ONLY_DEFENSIVE = IMMUNITIES | {'Spell Reflection', 'Mirror Image', 'Greater Invisibility'}


def presses(analysis, name):
    """Their personal defensives pressed in a pull (cooldowns.py's 'personal'): [(t ms, spell id, name)]."""
    return [(u['t'], u['ability_id'], u['ability']) for u in analysis.get('cooldowns') or []
            if u.get('name') == name and u.get('category') == 'personal' and u.get('ability') not in REACTIVE]


def summarize(events, fight_start, names_by_id, roles, casts):
    """
    analysis['incoming'] from the pull's enemy damage events. roles: {name: role} (tanks left out);
    casts: analysis['casts'] - whose buffs to follow on the hits (each player's own cast spells).
    Compact (it's stored with every pull): damage in thousands per STEP_MS bucket, and the ability behind it only
    for the heavy buckets (TOP_BUCKET_RATE times their average and up).
    """
    totals, by_ability, spans = {}, {}, {}
    own = {name: {sid for _, sid in casts.get(name) or []} for name in roles}
    last = 0
    for e in events:
        if e.get('type') != 'damage':
            continue
        name = names_by_id.get(e.get('targetID'))
        if name not in roles or roles[name] == 'tank':
            continue
        t = e['timestamp'] - fight_start
        last = max(last, t)
        amount = e.get('unmitigatedAmount')
        if amount is None:
            amount = (e.get('amount') or 0) + (e.get('absorbed') or 0)
        b = int(t // STEP_MS)
        totals.setdefault(name, {})[b] = totals.setdefault(name, {}).get(b, 0) + amount
        cell = by_ability.setdefault(name, {}).setdefault(b, {})
        ability = e.get('abilityGameID')
        cell[ability] = cell.get(ability, 0) + amount
        mine = own.get(name)
        if mine and e.get('buffs'):
            for part in str(e['buffs']).split('.'):
                if part.isdigit() and int(part) in mine:
                    runs = spans.setdefault(name, {}).setdefault(str(int(part)), [])
                    if runs and t - runs[-1][1] <= SPAN_GAP_MS:
                        runs[-1][1] = t
                    else:
                        runs.append([t, t])
    count = int(last // STEP_MS) + 1
    players, tops = {}, {}
    for name, buckets in totals.items():
        players[name] = [round(buckets.get(b, 0) / 1000) for b in range(count)]
        mean = sum(buckets.values()) / max(1, count)
        tops[name] = {str(b): max(by_ability[name][b], key=by_ability[name][b].get)
                      for b, v in buckets.items() if v >= TOP_BUCKET_RATE * mean and by_ability[name].get(b)}
    return {'v': VERSION, 'step': STEP_MS, 'players': players, 'top': tops, 'spans': spans}


# ============================================================================
# Reading it back: one player's pull
# ============================================================================

def _series(incoming, name):
    """[thousands per bucket] for one player (index = bucket)."""
    return (incoming.get('players') or {}).get(name) or []


def _raid(incoming):
    rows = list((incoming.get('players') or {}).values())
    return [sum(r[i] for r in rows if i < len(r)) for i in range(max((len(r) for r in rows), default=0))]


def _sum(series, b0, b1):
    return sum(series[max(0, b0):max(0, b1)])


def _top_ability(incoming, name, b0, b1, series):
    """The ability behind the heaviest bucket in [b0, b1) that has one recorded."""
    top = (incoming.get('top') or {}).get(name) or {}
    best = max((b for b in range(max(0, b0), b1) if str(b) in top), key=lambda b: series[b] if b < len(series) else 0,
               default=None)
    return top[str(best)] if best is not None else None


def active_window(incoming, name, sid, t):
    """When a defensive pressed at t (ms) was up: its span from the hits, else DEFAULT_ACTIVE_MS. (start, end) ms."""
    for start, end in ((incoming.get('spans') or {}).get(name) or {}).get(str(sid)) or \
            ((incoming.get('spans') or {}).get(name) or {}).get(sid) or []:
        if start - 2000 <= t <= end:
            return t, max(t + 1000, min(end + STEP_MS, t + MAX_ACTIVE_MS))
    return t, t + DEFAULT_ACTIVE_MS


def moments(analysis, name, defensives, duration_ms):
    """
    One player's pull: {'presses': [{'t', 'sid', 'name', 'kind', 'ability', 'taken'}],
    kind: 'aimed' (damage aimed at you), 'raid' (a raid-wide burst), 'heavy' (heavy for you) or 'quiet';
    'spikes': [{'t', 'ability', 'share'}] (no defensive up)} - or None without incoming data (older pulls).
    defensives: [(t ms, spell id, name)] - their personal defensives pressed this pull.
    """
    incoming = analysis.get('incoming')
    if not incoming or name not in (incoming.get('players') or {}):
        return None
    step = incoming.get('step') or STEP_MS
    mine, raid = _series(incoming, name), _raid(incoming)
    buckets = max(1.0, duration_ms / step)
    my_total, raid_total = sum(mine), sum(raid)
    if not my_total or not raid_total:
        return None
    my_rate, raid_rate, my_share = my_total / buckets, raid_total / buckets, my_total / raid_total
    presses, covered = [], []
    for t, sid, spell in defensives:
        start, end = active_window(incoming, name, sid, t)
        b0, b1 = int(start // step), max(int(start // step) + 1, int(end // step) + 1)
        length = b1 - b0
        taken, raid_in = _sum(mine, b0, b1), _sum(raid, b0, b1)
        heavy = taken / length >= HEAVY_FOR_YOU * my_rate
        aimed = heavy and raid_in and (taken / raid_in) >= AIMED_SHARE * my_share
        burst = raid_in / length >= RAID_BURST * raid_rate and taken / length >= 1.2 * my_rate
        kind = 'aimed' if aimed else 'raid' if burst else 'heavy' if heavy else 'quiet'
        presses.append({'t': t, 'sid': sid, 'name': spell, 'kind': kind, 'taken': taken * 1000,
                        'ability': _top_ability(incoming, name, b0, b1, mine) if kind != 'quiet' else None})
        covered.append((b0, b1))
    spikes, width = [], max(1, int(SPIKE_WINDOW_S * 1000 // step))
    b = 0
    while b < len(mine):
        got = _sum(mine, b, b + width)
        if got >= SPIKE_SHARE * my_total and got / width >= SPIKE_RATE * my_rate                 and not any(a < b + width and b < c for a, c in covered):
            if spikes and b <= spikes[-1]['_end']:  # the same heavy stretch going on: one spike
                spikes[-1]['_end'] = b + width
            else:
                spikes.append({'_start': b, '_end': b + width})
            b += width
        else:
            b += 1
    return {'presses': presses,
            'spikes': [{'t': sp['_start'] * step, 'ability': _top_ability(incoming, name, sp['_start'], sp['_end'], mine),
                        'share': _sum(mine, sp['_start'], sp['_end']) / my_total} for sp in spikes]}
