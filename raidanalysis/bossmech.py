"""
Boss-specific pass/fail mechanics the generic analysis can't see. Each one is curated by hand and is its own
kind of thing - so each is a class that decides everything about itself: what to fetch from WCL for a pull, what
to keep of it, and what counts as failing it (who, when, in a sentence). The night summary (web/insights.py),
the player's coaching (coach.py) and the sync only deal in that contract:

    key, icon, title           its id in analysis['boss_mechanics'], and how it's named
    fetches()                  [(WCL event data type, filter expression)] for one pull (both hostilities)
    collect(events, ...)       those events -> what's stored for the pull (any JSON)
    failures(data, analysis)   -> [{'t' (ms), 'players', 'detail' (what they did, after their names)}]
    uses(data, name)           how often a player took part (for a "going well")
    fail_title, ok_title       the night summary's line
    you_failed(n, when), you_ok(n)   the player's coaching

Register a mechanic under its boss's encounter id in MECHANICS.
"""

MIN_ALIVE = 8  # fewer alive than this: the pull was already lost - nothing to fail any more


def alive_at(analysis, t):
    """How many of the raid were alive at ms t into the pull."""
    return len(analysis.get('players') or []) - sum(1 for d in analysis.get('deaths') or [] if d['t'] < t)


class Mechanic:
    key = icon = title = fail_title = ok_title = ''

    def fetches(self):
        return []

    def collect(self, events, fight_start, names_by_id, roster):
        return None

    def failures(self, data, analysis):
        return []

    def uses(self, data, name):
        return 0

    def you_failed(self, count, when):
        return f'You failed {self.title.lower()} in {count} pull{"s" if count != 1 else ""} ({when})'

    def you_ok(self, count):
        return f'{self.title}: done right every time ({count}×)'


class MushroomBounce(Mechanic):
    """
    The Lost Explorers' Bouncy Mushroom: everyone bounces on it together to get over the wave. Touching it makes
    it disappear 5 s later, so one to three people bouncing on their own (too early) doom the rest. In the log
    (ability "Bounce"): the mushroom appearing is the mushroom casting Bounce (it also gains it itself - neither
    is a bounce), each player bouncing is Bounce landing on them ("is afflicted by Bounce from Bouncy
    Mushroom"). A bounce belongs to the last mushroom that appeared before it; one only a few players bounced on
    is failed, by them - and how soon after it appeared they went says how early (half a second: they ran into
    it; twenty: the raid used it together).

    Stored: [[ms it appeared (None if not logged), [players], ms of the first bounce], ...] - one per mushroom.
    """
    key, icon, title = 'mushroom', '🍄', 'Mushroom bounce'
    fail_title, ok_title = 'Failed the mushroom (went too early)', 'Mushroom bounce: nobody went too early'
    MIN_OK = 4              # fewer players bouncing on a mushroom than this: someone went too early
    SAME_SPAWN_MS = 2000    # mushrooms appearing this close together are one moment (they come in groups)
    MOMENT_GAP_MS = 15000   # no appearance logged: bounces this close together are one mushroom
    ENDS = ('removebuff', 'removedebuff', 'removebuffstack', 'removedebuffstack', 'refreshbuff', 'refreshdebuff')

    def fetches(self):
        return [('All', 'ability.name = "Bounce"')]

    def collect(self, events, fight_start, names_by_id, roster):
        out, seen = [], set()
        for e in sorted(events or [], key=lambda e: e.get('timestamp') or 0):
            if e.get('type') in self.ENDS:
                continue  # the bounce ending isn't another bounce
            key = (e.get('timestamp'), e.get('type'), e.get('sourceID'), e.get('targetID'))
            if key in seen:
                continue  # the same event from both hostility requests
            seen.add(key)
            t = e['timestamp'] - fight_start
            target, source = names_by_id.get(e.get('targetID')), names_by_id.get(e.get('sourceID'))
            if e.get('type') == 'cast' and source not in roster:  # a mushroom appearing
                if not out or out[-1][0] is None or t - out[-1][0] > self.SAME_SPAWN_MS:
                    out.append([t, [], None])
                continue
            name = target if target in roster else source if source in roster else None
            if not name:
                continue  # the mushroom gaining it itself
            if not out or (out[-1][0] is None and t - (out[-1][2] or t) > self.MOMENT_GAP_MS):
                out.append([None, [], None])
            if out[-1][2] is None:
                out[-1][2] = t
            if name not in out[-1][1]:
                out[-1][1].append(name)
        return out

    def failures(self, data, analysis):
        out = []
        for appeared, players, first in data or []:
            if not players or first is None or len(players) >= self.MIN_OK or alive_at(analysis, first) < MIN_ALIVE:
                continue
            early = f' {(first - appeared) / 1000:.1f} s after the mushroom appeared' if appeared is not None else ''
            alone = 'alone' if len(players) == 1 else f'only {len(players)} of you'
            out.append({'t': first, 'players': list(players),
                        'detail': f'bounced{early}, {alone} - it was gone before the rest could'})
        return out

    def uses(self, data, name):
        return sum(1 for _, players, _ in data or [] if name in players)

    def you_failed(self, count, when):
        return (f'You bounced on the mushroom too early in {count} pull{"s" if count != 1 else ""} ({when}) - it '
                f'was gone before the rest of the raid could. Wait for the raid.')

    def you_ok(self, count):
        return f'Mushroom bounce: with the raid every time ({count}×), never too early'


MECHANICS = {
    3497: [MushroomBounce()],  # The Lost Explorers
}


def for_encounter(encounter_id):
    """The curated mechanics checked on a boss."""
    return MECHANICS.get(encounter_id) or []


def every():
    return [m for ms in MECHANICS.values() for m in ms]


def failures(analysis, mechanic):
    """A pull's failures of a mechanic ([{'t', 'players', 'detail'}]), None when it has no data (analyzed before)."""
    data = (analysis.get('boss_mechanics') or {}).get(mechanic.key)
    return None if data is None else mechanic.failures(data, analysis)


def uses(analysis, mechanic, name):
    return mechanic.uses((analysis.get('boss_mechanics') or {}).get(mechanic.key), name)
