"""
Boss-specific pass/fail mechanics the generic analysis can't see - a mechanic that's about *when* people
used something together, not about damage taken.

The Lost Explorers' Bouncy Mushroom: everyone bounces on it together to get over the wave. Touching it makes
it disappear 5 s later, so one to three people bouncing on their own (too early) doom the rest. In the log
(ability "Bounce", fetched per pull by sync): the mushroom appearing is the mushroom casting Bounce (it also
gains it itself - neither is a bounce), and each player bouncing is Bounce landing on them ("is afflicted by
Bounce from Bouncy Mushroom"). Each bounce belongs to the last mushroom that appeared before it; a mushroom only
a few players bounced on is a failed one, those players the ones who went too early - and how soon after it
appeared they went says how early (half a second: they ran into it; twenty: the raid used it together).

Data: analysis['boss_mechanics'] = {key: [[ms the mushroom appeared (None if not logged), [players],
ms of the first bounce], ...]} - one entry per mushroom.
"""

MOMENT_GAP_MS = 15000   # no mushroom appearing logged: bounces this close together are one mushroom
SAME_SPAWN_MS = 2000    # mushrooms appearing this close together are one moment (they come in groups)
MIN_ALIVE = 8           # fewer alive than this: the pull was already lost - nothing to fail any more
ENDS = ('removebuff', 'removedebuff', 'removebuffstack', 'removedebuffstack', 'refreshbuff', 'refreshdebuff')

MECHANICS = {
    3497: [{  # The Lost Explorers
        'key': 'mushroom', 'ability': 'Bounce', 'icon': '🍄', 'title': 'Mushroom bounce',
        'thing': 'the mushroom', 'verb': 'bounced',
        'min_ok': 4,  # fewer players bouncing on a mushroom than this: someone went too early
    }],
}


def for_encounter(encounter_id):
    """The special mechanics checked on a boss: [{'key', 'ability', 'icon', 'title', 'thing', 'min_ok'}]."""
    return MECHANICS.get(encounter_id) or []


def filter_expression(mechanic):
    return f'ability.name = "{mechanic["ability"].replace(chr(34), "")}"'


def moments(events, fight_start, names_by_id, roster):
    """
    A mechanic's events -> [[ms it appeared or None, [players], ms of the first use]], one per mushroom (or
    group of them appearing together). Appearing: the ability cast by something that isn't one of us. A use:
    the ability landing on one of us (else cast by one of us); each player once per mushroom. Without
    appearances logged, uses MOMENT_GAP_MS apart start a new one.
    """
    out, seen = [], set()
    for e in sorted(events or [], key=lambda e: e.get('timestamp') or 0):
        if e.get('type') in ENDS:
            continue  # the bounce ending isn't another bounce
        key = (e.get('timestamp'), e.get('type'), e.get('sourceID'), e.get('targetID'))
        if key in seen:
            continue  # the same event from both hostility requests
        seen.add(key)
        t = e['timestamp'] - fight_start
        target, source = names_by_id.get(e.get('targetID')), names_by_id.get(e.get('sourceID'))
        if e.get('type') == 'cast' and source not in roster:
            if not out or out[-1][0] is None or t - out[-1][0] > SAME_SPAWN_MS:
                out.append([t, [], None])
            continue
        name = target if target in roster else source if source in roster else None
        if not name:
            continue  # the mushroom gaining it itself
        last = out[-1] if out else None
        if last is None or (last[0] is None and t - (last[2] or t) > MOMENT_GAP_MS):
            out.append([None, [], None])
        if out[-1][2] is None:
            out[-1][2] = t
        if name not in out[-1][1]:
            out[-1][1].append(name)
    return out


def failures(analysis, mechanic):
    """
    The failed mushrooms of one pull: [{'t' (first use), 'appeared' (ms or None), 'players'}] - fewer than
    mechanic['min_ok'] players on it while the raid was still standing (MIN_ALIVE). None when the pull has no
    data for it (analyzed before the check).
    """
    data = (analysis.get('boss_mechanics') or {}).get(mechanic['key'])
    if data is None:
        return None
    raid = len(analysis.get('players') or [])
    deaths = sorted(d['t'] for d in analysis.get('deaths') or [])
    out = []
    for appeared, players, first in data:
        if not players or first is None:
            continue  # nobody touched it
        alive = raid - sum(1 for d in deaths if d < first)
        if len(players) < mechanic['min_ok'] and alive >= MIN_ALIVE:
            out.append({'t': first, 'appeared': appeared, 'players': list(players)})
    return out
