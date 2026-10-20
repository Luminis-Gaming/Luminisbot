"""
Boss-specific pass/fail mechanics the generic analysis can't see. Each one is curated by hand and is its own
kind of thing - so each is a class that decides everything about itself: what to fetch from WCL for a pull, what
to keep of it, and what counts as failing it (who, when, in a sentence). The night summary (web/insights.py),
the player's coaching (coach.py) and the sync only deal in that contract:

    key, icon, title           its id in analysis['boss_mechanics'], and how it's named
    guide                      (spell id, name) of its Mythic Trap entry - its clip goes with the lines and tips
    fetches()                  [(name, WCL event data type, filter expression, positions?)] for one pull (both
                               hostilities; positions: the events carry x / y - in yards × 100)
    collect(events, ...)       {fetch name: its events} -> what's stored for the pull (any JSON); fight_end:
                               the pull's end (absolute ms, like fight_start)
    failures(data, analysis)   -> [{'t' (ms), 'players', 'detail' (what happened, after their names)}]
    notes(data, analysis)      the same shape: worth showing, but not on anyone (never counted as failing)
    uses(data, name)           how often a player did it right (for a "going well")
    fail_title, ok_title       the night summary's line
    you_failed(name, fails)    the player's coaching: fails = [(pull number, failure)] they're in
    you_ok(n)

Register a mechanic under its boss's encounter id in MECHANICS. Working one out from a real log: the officers'
/admin/raids/report/{code}/{fight}/events?abilities=... dump.
"""
import math

MIN_ALIVE = 8  # fewer alive than this: the pull was already lost - nothing to fail any more


def alive_at(analysis, t):
    """How many of the raid were alive at ms t into the pull."""
    return len(analysis.get('players') or []) - sum(1 for d in analysis.get('deaths') or [] if d['t'] < t)


def clock(ms):
    return f'{int(ms // 60000)}:{int(ms % 60000 // 1000):02d}'


def _plural(n, word):
    return f'{n} {word}{"s" if n != 1 else ""}'


def _player(e, names_by_id, roster, side):
    name = names_by_id.get(e.get(f'{side}ID'))
    return name if name in roster else None


class Mechanic:
    key = icon = title = fail_title = ok_title = ''
    guide = None

    def fetches(self):
        return []

    def collect(self, events, fight_start, names_by_id, roster, fight_end=None):
        return None

    def failures(self, data, analysis):
        return []

    def notes(self, data, analysis):
        return []

    def uses(self, data, name):
        return 0

    def you_failed(self, name, fails):
        pulls = len({n for n, _ in fails})
        return f'You failed {self.title.lower()} in {_plural(pulls, "pull")} ({when(fails)})'

    def you_ok(self, count):
        return f'{self.title}: done right every time ({count}×)'


def when(fails, limit=4):
    """'#3 at 1:21, #7 at 2:05 …' for [(pull number, failure)]."""
    return ', '.join(f"#{n} at {clock(f['t'])}" for n, f in fails[:limit]) + (' …' if len(fails) > limit else '')


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
    guide = (1297625, 'Explosive Surprise')  # Mythic Trap: "Dodge with Mushrooms"
    fail_title, ok_title = 'Failed the mushroom (went too early)', 'Mushroom bounce: nobody went too early'
    MIN_OK = 4              # fewer players bouncing on a mushroom than this: someone went too early
    SAME_SPAWN_MS = 2000    # mushrooms appearing this close together are one moment (they come in groups)
    MOMENT_GAP_MS = 15000   # no appearance logged: bounces this close together are one mushroom
    ENDS = ('removebuff', 'removedebuff', 'removebuffstack', 'removedebuffstack', 'refreshbuff', 'refreshdebuff')

    def fetches(self):
        return [('bounce', 'All', 'ability.name = "Bounce"', False)]

    def collect(self, events, fight_start, names_by_id, roster, fight_end=None):
        out, seen = [], set()
        for e in sorted(events.get('bounce') or [], key=lambda e: e.get('timestamp') or 0):
            if e.get('type') in self.ENDS:
                continue  # the bounce ending isn't another bounce
            key = (e.get('timestamp'), e.get('type'), e.get('sourceID'), e.get('targetID'))
            if key in seen:
                continue  # the same event from both hostility requests
            seen.add(key)
            t = e['timestamp'] - fight_start
            target, source = _player(e, names_by_id, roster, 'target'), _player(e, names_by_id, roster, 'source')
            if e.get('type') == 'cast' and not source:  # a mushroom appearing
                if not out or out[-1][0] is None or t - out[-1][0] > self.SAME_SPAWN_MS:
                    out.append([t, [], None])
                continue
            name = target or source
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

    def you_failed(self, name, fails):
        pulls = len({n for n, _ in fails})
        return (f'You bounced on the mushroom too early in {_plural(pulls, "pull")} ({when(fails)}) - it was gone '
                f'before the rest of the raid could. Wait for the raid.')

    def you_ok(self, count):
        return f'Mushroom bounce: with the raid every time ({count}×), never too early'


class ProtovenomCollision(Mechanic):
    """
    Entombed Sentinels' Shifting Protovenom: 6-8 players get a red ring (the debuff, which also ticks every 2 s).
    Two red rings bumping into each other clear both (the debuff leaves both at the same moment). A red ring
    touching someone without one sets off Protovenom Eruption - everyone within 10 yards takes it - and that's on
    both of them: the ring for running into people, the other for not making way.

    In the log, each eruption is a burst of Protovenom Eruption hits at one moment, every hit carrying where that
    player stood. A burst that hit someone with a red ring is a collision, with the player without a ring nearest
    to them (within COLLIDE_YD) - the rest of the burst just stood within 10 yards. A burst no red ring was in
    (something left on the ground after a pile-up) isn't anyone running into anyone. Pile-ups set off several
    at once: each ring in the burst gets its own nearest.

    Stored: {'rings': [[player, ms on, ms off or None]], 'collisions': [[ms, ring, bumped, yards, players hit]]}.
    """
    key, icon, title = 'protovenom', '🔴', 'Protovenom rings'
    guide = (1296878, 'Shifting Protovenom')  # Mythic Trap: "Debuffed players should touch"
    fail_title = 'Red ring ran into someone without one (Protovenom Eruption)'
    ok_title = 'Protovenom rings: nobody ran into anyone'
    BURST_MS = 150          # eruption hits this close together are one burst
    SAME_MS = 1000          # the same two again this soon: the same collision logged twice
    COLLIDE_YD = 5          # the ring and the one they ran into stand closer than this (seen: 0.8-4.5)

    def fetches(self):
        return [('rings', 'All', 'ability.name = "Shifting Protovenom" and type in ("applydebuff", "removedebuff")',
                 False),
                ('eruptions', 'All', 'ability.name = "Protovenom Eruption" and type = "damage"', True)]

    def collect(self, events, fight_start, names_by_id, roster, fight_end=None):
        rings, seen = [], set()
        for e in sorted(events.get('rings') or [], key=lambda e: e.get('timestamp') or 0):
            name = _player(e, names_by_id, roster, 'target')
            key = (e.get('timestamp'), e.get('type'), name)
            if not name or key in seen:
                continue
            seen.add(key)
            t = e['timestamp'] - fight_start
            if e.get('type') == 'applydebuff':
                rings.append([name, t, None])
            elif e.get('type') == 'removedebuff':
                ring = next((r for r in reversed(rings) if r[0] == name and r[2] is None), None)
                if ring:
                    ring[2] = t

        def ringed(name, t):
            return any(r[0] == name and r[1] <= t and (r[2] is None or r[2] >= t) for r in rings)
        bursts = []
        for e in sorted(events.get('eruptions') or [], key=lambda e: e.get('timestamp') or 0):
            name = _player(e, names_by_id, roster, 'target')
            if not name or e.get('x') is None or e.get('y') is None:
                continue
            t = e['timestamp'] - fight_start
            if not bursts or t - bursts[-1]['last'] > self.BURST_MS:
                bursts.append({'t': t, 'last': t, 'at': {}})
            bursts[-1]['last'] = t
            bursts[-1]['at'].setdefault(name, (e['x'], e['y']))  # where they stood when it hit
        collisions = []
        for burst in bursts:
            at, t = burst['at'], burst['t']
            red = [n for n in at if ringed(n, t)]
            clear = [n for n in at if n not in red]
            for ring in red:
                if not clear:
                    break
                bumped = min(clear, key=lambda n: math.dist(at[n], at[ring]))
                yards = math.dist(at[bumped], at[ring]) / 100
                if yards > self.COLLIDE_YD:
                    continue  # nobody close enough: they were only near the blast
                if any(c[1] == ring and c[2] == bumped and t - c[0] <= self.SAME_MS for c in collisions):
                    continue
                collisions.append([t, ring, bumped, round(yards, 1), len(at)])
        return {'rings': rings, 'collisions': collisions}

    def failures(self, data, analysis):
        out = []
        for t, ring, bumped, yards, hit in (data or {}).get('collisions') or []:
            if alive_at(analysis, t) < MIN_ALIVE:
                continue
            out.append({'t': t, 'players': [ring, bumped], 'ring': ring, 'bumped': bumped,
                        'detail': f'collided - {ring} had the red ring, {bumped} didn\'t '
                                  f'({_plural(hit, "player")} caught in the eruption)'})
        return out

    def uses(self, data, name):
        """Red rings this player cleared without running into anyone."""
        bumped_into = {(c[1], c[0]) for c in (data or {}).get('collisions') or []}
        return sum(1 for r in (data or {}).get('rings') or [] if r[0] == name
                   and not any(who == name and r[1] <= t and (r[2] is None or t <= r[2]) for who, t in bumped_into))

    def you_failed(self, name, fails):
        ran = [(n, f) for n, f in fails if f['ring'] == name]
        hit = [(n, f) for n, f in fails if f['bumped'] == name]
        parts = []
        if ran:
            into = ', '.join(sorted({f['bumped'] for _, f in ran}))
            parts.append(f"With the red ring you ran into players without one {_plural(len(ran), 'time')} "
                         f"({when(ran)}: {into}) - calm down, don't run people over: find another red ring and bump "
                         f"into them instead")
        if hit:
            by = ', '.join(sorted({f['ring'] for _, f in hit}))
            parts.append(f"{'You also' if ran else 'You'} got run into by a red ring {_plural(len(hit), 'time')} "
                         f"({when(hit)}: {by}) - without a ring, make way for the red rings: part the sea")
        return '. '.join(parts)

    def you_ok(self, count):
        return f'Protovenom: cleared your red ring with another ring every time ({count}×), nobody run over'


class HelicalToxins(Mechanic):
    """
    Entombed Sentinels' Helical Toxins: everyone gets 1, 2 or 3 stacks (the orbs over their head) and has to bump
    into someone so the two make 4 - a 2 with a 2, a 1 with a 3. Then both lose it at the same moment. Bumping into
    the wrong one adds the two up into something else (2 + 3 = 5): both are locked on that and explode when it
    runs out (~28 s) - and bumping into more people adds those up too (5, 7, 12, 19...).

    In the log: the stacks given at first aren't logged (only changes are), but a wrong bump is - both players'
    stacks change at the same moment to the same total, which also says who bumped whom. A right pair is two
    losing it at the same moment with no change before. Running out alone after ~28 s is never having paired -
    shown, but not on them: their match may have gone into someone else's wrong pair, and with the numbers never
    logged there's no telling. Losing it early on your own (an immunity, a death) says nothing; a wipe with it
    still up neither.

    Stored: [[player, ms applied, ms gone or None, [[ms, stacks], ...]], ...] - one per toxin.
    """
    key, icon, title = 'helical', '🧬', 'Helical Toxins'
    guide = (1284590, 'Helical Toxins')  # Mythic Trap: "Match correctly"
    fail_title, ok_title = 'Helical Toxins: matched wrong', 'Helical Toxins: nobody matched wrong'
    SAME_MS = 15            # two changes / two losses this close together are one bump
    RAN_OUT_MS = 27000      # lost alone after this long: it ran out - never paired

    def fetches(self):
        return [('toxins', 'All', 'ability.name = "Helical Toxins" and '
                                  'type in ("applydebuff", "applydebuffstack", "removedebuff")', False)]

    def collect(self, events, fight_start, names_by_id, roster, fight_end=None):
        toxins, current, seen = [], {}, set()
        for e in sorted(events.get('toxins') or [], key=lambda e: e.get('timestamp') or 0):
            name = _player(e, names_by_id, roster, 'target')
            key = (e.get('timestamp'), e.get('type'), name, e.get('stack'))
            if not name or key in seen:
                continue
            seen.add(key)
            t = e['timestamp'] - fight_start
            if e.get('type') == 'applydebuff':
                current[name] = [name, t, None, []]
                toxins.append(current[name])
            elif e.get('type') == 'applydebuffstack' and name in current:
                current[name][3].append([t, e.get('stack')])
            elif e.get('type') == 'removedebuff' and name in current:
                current.pop(name)[2] = t
        return toxins

    def _outcomes(self, data):
        """(wrong bumps [(ms, a, b, total, a's count before or None, b's)], ran out [(ms, player, seconds)], paired)."""
        toxins = data or []
        changes = [(t, s, tox) for tox in toxins for t, s in tox[3]]
        wrong, done = [], set()
        for t, total, tox in changes:
            other = next((o for t2, s2, o in changes if o is not tox and s2 == total and abs(t2 - t) <= self.SAME_MS
                          and (t2, id(o)) not in done), None)
            if (t, id(tox)) in done or not other:
                continue
            done |= {(t, id(tox)), (next(t2 for t2, s2 in other[3] if s2 == total and abs(t2 - t) <= self.SAME_MS),
                                    id(other))}

            def before(x):  # their stacks just before this bump, when an earlier bump logged them
                earlier = [s for t2, s in x[3] if t2 < t - self.SAME_MS]
                return earlier[-1] if earlier else None
            wrong.append((t, tox[0], other[0], total, before(tox), before(other)))
        ran_out, paired = [], 0
        for tox in toxins:
            name, on, off, stacks = tox
            if off is None:
                continue  # still up when the pull ended
            if not stacks and any(o is not tox and not o[3] and o[2] is not None and abs(o[2] - off) <= self.SAME_MS
                                  for o in toxins):
                paired += 1
            elif not stacks and off - on >= self.RAN_OUT_MS:
                ran_out.append((off, name, (off - on) / 1000))
        return sorted(wrong), sorted(ran_out), paired

    def failures(self, data, analysis):
        wrong, ran_out, _ = self._outcomes(data)
        out = []
        for t, a, b, total, a_was, b_was in wrong:
            if alive_at(analysis, t) < MIN_ALIVE:
                continue
            # A known count before the bump gives the other one's too (a locked 5 + them = 7: they were a 2)
            if a_was is None and b_was is not None:
                a_was = total - b_was
            elif b_was is None and a_was is not None:
                b_was = total - a_was
            sums = f' ({a_was} + {b_was})' if a_was is not None and b_was is not None else ''
            out.append({'t': t, 'players': [a, b], 'kind': 'wrong', 'with': {a: b, b: a}, 'total': total,
                        'detail': f'matched wrong - made {total}{sums}, not 4: locked, and both exploded later'})
        return out

    def notes(self, data, analysis):
        """Toxins that ran out without a match: not on them - their match may have gone into a wrong pair."""
        _, ran_out, _ = self._outcomes(data)
        return [{'t': t, 'players': [name], 'detail': f'had no match left - it ran out after {seconds:.0f} s '
                                                         f'(not counted: their match may have gone into a wrong pair)'}
                for t, name, seconds in ran_out if alive_at(analysis, t) >= MIN_ALIVE]

    def uses(self, data, name):
        """Toxins this player matched right."""
        toxins = data or []
        return sum(1 for tox in toxins if tox[0] == name and not tox[3] and tox[2] is not None
                   and any(o is not tox and not o[3] and o[2] is not None and abs(o[2] - tox[2]) <= self.SAME_MS
                           for o in toxins))

    def you_failed(self, name, fails):
        whom = ', '.join(f"{f['with'][name]} ({f['total']})" for _, f in fails[:4])
        return (f"You matched wrong on Helical Toxins {_plural(len(fails), 'time')} ({when(fails)}: with {whom}) - "
                f"count your orbs: a 2 goes with a 2, a 1 with a 3, so the two make 4")

    def you_ok(self, count):
        return f'Helical Toxins: matched right every time ({count}×)'


class BloodAndAcid(Mechanic):
    """
    Entombed Sentinels' Mark of Blood (the Blood of Ula'tek) and Mark of Acid (the Breath of Ula'tek): every 5 s
    each boss marks everyone within 40 yards - a stack more, each stack ticking for 40 s. The bosses are kept apart
    and everyone stays on their own boss's side: in range of both, both stack on you at once.

    Having both is normal: a mark keeps ticking for 40 s after you leave its boss, so moving from one side to the
    other carries a few stacks across (median: about 5 of the other one at worst). Being in range of both is what
    goes wrong - each boss's mark landing on you at the same tick. On four nights of our pulls (786 player-pulls)
    nobody was for most pulls, one tick at the 90th percentile: crossing the middle. Staying there - BAD_RUN ticks in
    a row, 10 s+ - is failing it (7% of player-pulls; one-off crossings are only on the chart).
    Ticks where RAID_WIDE+ of the raid were in range of both at once aren't on anyone: the bosses were too close
    together (the tanks), or the pull was falling apart - mostly its last seconds, also left out (END_MS).

    In the log: applydebuff / applydebuffstack / refreshdebuff each mean that boss's tick landed on you (in range),
    removedebuff the mark running out. Stored: {'end': ms, 'players': {name: {'b': [[ms, stacks], ...], 'a': [...]}}}
    - Mark of Blood ('b') and Mark of Acid ('a'), stacks 0 when it ran out.
    """
    key, icon, title = 'marks', '🩸', 'Mark of Blood & Acid'
    guide = (1284506, 'Mark of Blood')
    fail_title, ok_title = 'Stood in range of both Sentinels (Mark of Blood + Mark of Acid)', \
        'Mark of Blood & Acid: everyone kept to one side'
    MARKS = (('b', 'Mark of Blood'), ('a', 'Mark of Acid'))
    TICK_MS = 5000
    SAME_TICK_MS = 2500     # the two bosses' ticks this close: the same tick (seen: 0-100 ms apart)
    RAID_WIDE = 6           # this many in range of both at the same tick: the bosses' spot, not anyone's
    BAD_RUN = 2             # own ticks in a row in range of both (standing in the middle, 10 s+): failing it
    BAD_STACKS = 8          # carrying this many of both at once: the chart's "bad" (worst 10%; normal: about 5)
    END_MS = 15000          # the pull's last seconds: everyone running anywhere, not counted

    def fetches(self):
        return [(k, 'Debuffs', f'ability.name = "{name}" and type in '
                               f'("applydebuff", "applydebuffstack", "refreshdebuff", "removedebuff")', False)
                for k, name in self.MARKS]

    def collect(self, events, fight_start, names_by_id, roster, fight_end=None):
        players = {}
        for k, _ in self.MARKS:
            for e in sorted(events.get(k) or [], key=lambda e: e.get('timestamp') or 0):
                name = _player(e, names_by_id, roster, 'target')
                if not name:
                    continue
                t, kind = e['timestamp'] - fight_start, e.get('type')
                rows = players.setdefault(name, {'b': [], 'a': []})[k]
                last = rows[-1][1] if rows else 0
                stacks = (0 if kind == 'removedebuff' else 1 if kind == 'applydebuff'
                          else e.get('stack') or last if kind == 'applydebuffstack' else last or 1)
                if rows and abs(rows[-1][0] - t) <= 50 and (stacks == 0) == (rows[-1][1] == 0):
                    rows[-1][1] = max(rows[-1][1], stacks) if stacks else 0  # a stack and its refresh: one tick
                else:
                    rows.append([t, stacks])
        return {'end': fight_end - fight_start if fight_end else None, 'players': players}

    def both_ticks(self, data):
        """{name: [ms]}: the ticks each player was in range of both bosses (both marks landing on them)."""
        out = {}
        for name, marks in ((data or {}).get('players') or {}).items():
            acid = [t for t, s in marks['a'] if s]
            hits = [t for t, s in marks['b'] if s and any(abs(t - u) <= self.SAME_TICK_MS for u in acid)]
            if hits:
                out[name] = hits
        return out

    def crowded(self, data):
        """Ticks (ms) RAID_WIDE+ players were in range of both at once - the bosses' spot, nobody's fault."""
        times = sorted(t for hits in self.both_ticks(data).values() for t in hits)
        return sorted({t for t in times if sum(1 for u in times if abs(u - t) <= 1000) >= self.RAID_WIDE})

    def own_ticks(self, data, analysis, name=None):
        """
        {name: [ms]}: in range of both on their own - not a crowded tick, not the pull's end, not a lost pull
        (analysis None: not checked).
        """
        end = (data or {}).get('end')
        crowd = self.crowded(data)
        out = {}
        for who, hits in self.both_ticks(data).items():
            if name and who != name:
                continue
            mine = [t for t in hits if not any(abs(t - c) <= 1000 for c in crowd)
                    and (end is None or t < end - self.END_MS)
                    and (analysis is None or alive_at(analysis, t) >= MIN_ALIVE)]
            if mine:
                out[who] = mine
        return out

    @staticmethod
    def stacks_at(marks, t):
        """(Blood, Acid) stacks on a player at ms t."""
        def one(rows):
            now = 0
            for at, s in rows:
                if at > t:
                    break
                now = s
            return now
        return one(marks['b']), one(marks['a'])

    def failures(self, data, analysis):
        out = []
        for name, ticks in self.own_ticks(data, analysis).items():
            stays = [t for run in _runs(ticks, self.TICK_MS) if len(run) >= self.BAD_RUN for t in run]
            if not stays:
                continue
            marks = data['players'][name]
            blood, acid = max((self.stacks_at(marks, t) for t in stays), key=lambda ba: min(ba))
            out.append({'t': stays[0], 'players': [name], 'ticks': len(stays),
                        'detail': f'stood in range of both bosses for {len(stays) * self.TICK_MS // 1000} s '
                                  f'({_spans(stays, self.TICK_MS)}) - up to {blood} Mark of Blood and {acid} Mark of '
                                  f'Acid stacking at once'})
        return sorted(out, key=lambda f: f['t'])

    def notes(self, data, analysis):
        """The bosses too close together: most of the raid in range of both at once - on nobody."""
        end = (data or {}).get('end')
        crowd = [t for t in self.crowded(data) if (end is None or t < end - self.END_MS)
                 and alive_at(analysis, t) >= MIN_ALIVE]
        out = []
        for group in _runs(crowd, self.TICK_MS):
            most = max(sum(1 for hits in self.both_ticks(data).values() if any(abs(u - t) <= 1000 for u in hits))
                       for t in group)
            out.append({'t': group[0], 'players': [],
                        'detail': f'{most} of you were in range of both bosses at once '
                                  f'({len(group) * self.TICK_MS // 1000} s) - the bosses were too close together, '
                                  f'not counted on anyone'})
        return out

    def uses(self, data, name):
        """1 for a pull they had the marks in and kept to one side (crossing the middle at most)."""
        if not data or name not in (data.get('players') or {}):
            return 0
        runs = _runs(self.own_ticks(data, None, name).get(name) or [], self.TICK_MS)
        return int(all(len(run) < self.BAD_RUN for run in runs))

    def you_failed(self, name, fails):
        pulls = len({n for n, _ in fails})
        return (f"You stood in range of both Sentinels in {_plural(pulls, 'pull')} ({when(fails)}) - Mark of Blood "
                f"and Mark of Acid stacked on you at once. Stay on your own boss's side, more than 40 yards from "
                f"the other one; cross the middle quickly")

    def you_ok(self, count):
        return f'Mark of Blood & Acid: kept to one side in every pull ({count}×)'


def _runs(times, step):
    """Sorted ms -> runs of consecutive ticks ([[ms, ...]]): a gap over 1.5 ticks starts a new one."""
    out = []
    for t in times:
        if out and t - out[-1][-1] <= step * 1.5:
            out[-1].append(t)
        else:
            out.append([t])
    return out


def _spans(times, step):
    """'1:20-1:35, 2:05' for tick times: each run from its first tick to its last."""
    return ', '.join(clock(r[0]) if len(r) == 1 else f'{clock(r[0])}-{clock(r[-1])}' for r in _runs(times, step))


MECHANICS = {
    3497: [MushroomBounce()],                                          # The Lost Explorers
    3445: [ProtovenomCollision(), HelicalToxins(), BloodAndAcid()],    # Entombed Sentinels
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


def notes(analysis, mechanic):
    """A pull's notes on a mechanic - shown, never counted ([{'t', 'players', 'detail'}])."""
    data = (analysis.get('boss_mechanics') or {}).get(mechanic.key)
    return [] if data is None else mechanic.notes(data, analysis)


def uses(analysis, mechanic, name):
    return mechanic.uses((analysis.get('boss_mechanics') or {}).get(mechanic.key), name)
