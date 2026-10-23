"""
Forms a spec goes into for its burst and comes out of again - a Devourer's Void Metamorphosis: no cooldown (Soul
Fragments open it), no cast in the log (only its buff), so the cooldown comparison never sees it. Kept per player
and pull as the stretches it was up plus their casts of what it's for (Collapsing Star): drawn as a bar on the
cooldown and focus timelines, with the spends in each window counted, next to the top players.

Stored as {form name: {'bands': [[start, end] ms into the fight], 'spends': [ms of each spender cast]}} - in a
pull's extras per player (throughput.build_extras), and on each top player (benchmarks.fetch_top_players).
"""

FORMS = {
    ('DemonHunter', 'Devourer'): {
        'name': 'Void Metamorphosis',
        # The form itself. Not 1225789: also "Void Metamorphosis", but that's the one up while it's ready to enter
        'buff_ids': (1217607,),
        'spender': 'Collapsing Star',
        'icon': 'inv_112_ability_demonhunter_metamorphasisvoid.jpg',
    },
}
SPEND_GRACE_MS = 500  # a spender cast this soon after the form drops was pressed inside it


def of_spec(class_name, spec):
    """The form a spec goes into, or None."""
    return FORMS.get((class_name, spec))


def buff_filter(names):
    """Buffs events: the forms going up and down on these players."""
    ids = sorted({i for f in FORMS.values() for i in f['buff_ids']})
    return (f'type in ("applybuff", "removebuff") and ability.id in ({",".join(map(str, ids))}) and target.name in ('
            + ', '.join(_quoted(n) for n in names) + ')')


def spend_filter(names):
    """Casts events: these players' form spenders."""
    spenders = sorted({f['spender'] for f in FORMS.values()})
    return (f'type = "cast" and ability.name in ({", ".join(_quoted(s) for s in spenders)}) and source.name in ('
            + ', '.join(_quoted(n) for n in names) + ')')


def _quoted(text):
    return '"' + text.replace('"', '') + '"'


def bands(events, fight_start, fight_end, buff_ids):
    """applybuff -> removebuff of buff_ids on one player: [[start, end] ms] (up from the pull's start when it only
    ends, until its end when it never does)."""
    out, since = [], None
    for e in sorted(events or [], key=lambda e: e['timestamp']):
        if e.get('abilityGameID') not in buff_ids:
            continue
        t = max(0, e['timestamp'] - fight_start)
        if e.get('type') == 'applybuff' and since is None:
            since = t
        elif e.get('type') == 'removebuff':
            out.append([0 if since is None else since, t])
            since = None
    if since is not None:
        out.append([since, fight_end - fight_start])
    return [b for b in out if b[1] > b[0]]


def from_events(roster, names_by_id, buff_events, cast_events, fight_start, fight_end):
    """{player: {form name: {'bands', 'spends'}}} for the roster's players whose spec has a form."""
    out = {}
    for p in roster:
        form = of_spec(p.get('class'), p.get('spec'))
        if not form:
            continue
        mine = [e for e in buff_events or [] if names_by_id.get(e.get('targetID')) == p['name']]
        spends = sorted(e['timestamp'] - fight_start for e in cast_events or []
                        if names_by_id.get(e.get('sourceID')) == p['name'] and e.get('type') == 'cast')
        out[p['name']] = {form['name']: {'bands': bands(mine, fight_start, fight_end, form['buff_ids']),
                                         'spends': spends}}
    return out


def from_tables(class_name, spec, buffs_table, casts_table, cast_events, fight_start, fight_end):
    """
    A top player's form from what's fetched for them anyway: their Buffs table (its bands), their Casts table (which
    ids the spender goes by) and their cast events. {} for a spec without one.
    """
    form = of_spec(class_name, spec)
    if not form:
        return {}
    found = []
    for a in (buffs_table or {}).get('auras') or []:
        if a.get('guid') in form['buff_ids']:
            found += [[max(0, b['startTime'] - fight_start), b['endTime'] - fight_start] for b in a.get('bands') or []
                      if b.get('startTime') is not None and b.get('endTime') is not None]
    entries = (casts_table or {}).get('entries') or []
    spender_ids = {e.get('guid') for e in entries if e.get('name') == form['spender']}
    spender_ids |= {s.get('guid') for e in entries for s in e.get('subentries') or [] if s.get('name') == form['spender']}
    spends = sorted(e['timestamp'] - fight_start for e in cast_events or []
                    if e.get('type') == 'cast' and (e.get('abilityGameID') in spender_ids))
    return {form['name']: {'bands': sorted(b for b in found if b[1] > b[0]), 'spends': spends}}


def windows(entry):
    """[{'start', 'end', 'spends': [ms]}] - each stretch in the form, with the spender casts inside it."""
    spends = (entry or {}).get('spends') or []
    return [{'start': a, 'end': b, 'spends': [t for t in spends if a <= t <= b + SPEND_GRACE_MS]}
            for a, b in (entry or {}).get('bands') or []]


def stats(entries):
    """
    Over several fights - [(entry or None, fight duration ms)] - how a form was used: {'fights', 'per_5min' (windows),
    'avg_ms' (a window's length), 'uptime' (share of the fights), 'per_window' (spends)} - None without any.
    """
    known = [(windows(e), d) for e, d in entries if e is not None and d]
    if not known:
        return None
    wins = [w for ws, _ in known for w in ws]
    total = sum(d for _, d in known)
    up = sum(w['end'] - w['start'] for w in wins)
    return {'fights': len(known), 'per_5min': len(wins) / (total / 300000), 'avg_ms': up / len(wins) if wins else 0,
            'uptime': up / total, 'per_window': sum(len(w['spends']) for w in wins) / len(wins) if wins else 0}


def median_stats(per_player):
    """The top players' stats() as one: the median of each number over those with any."""
    found = [s for s in per_player if s]
    if not found:
        return None

    def median(key):
        values = sorted(s[key] for s in found)
        return values[len(values) // 2]
    return {'fights': len(found), **{k: median(k) for k in ('per_5min', 'avg_ms', 'uptime', 'per_window')}}
