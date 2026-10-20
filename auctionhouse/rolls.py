"""
What makes one listing of an item different from another, in the terms a buyer uses: its secondary stats, a
tertiary stat, a socket and its item level - its "roll".

A listing names its item with bonus ids (bonus_lists) and modifiers. The game's own ItemBonus table (gamedata.py,
from wago.tools) says what each bonus id does:
  type 2   a stat: 32 Critical Strike, 36 Haste, 40 Versatility, 49 Mastery; 61-64 the tertiary stats
  type 6   a socket
  type 16  a binding override (the base item binds when picked up; the copies that drop as tradeable say 2,
           binds when equipped)
  type 1   an item level change; type 49 a level curve that sets the item level outright (the same curve gives the
           same item level on every item, so one lookup per curve is enough: collector.resolve_levels)
Newer gear (Midnight) keeps its two random secondary stats in modifiers 29 and 30 instead (stat ids, the larger
one first) - and so does Wowhead's tooltip, as crafted-stats=29:30.

Pure functions: no database, no network (tests/test_auctionhouse.py).
"""
from typing import NamedTuple

SECONDARY = {32: 'Critical Strike', 36: 'Haste', 40: 'Versatility', 49: 'Mastery'}
TERTIARY = {61: 'Speed', 62: 'Leech', 63: 'Avoidance', 64: 'Indestructible'}
STAT, SOCKET, LEVEL_DELTA, BINDING, LEVEL_CURVE = 2, 6, 1, 16, 49
MOD_DROP_LEVEL, MOD_STAT_1, MOD_STAT_2 = 9, 29, 30


class Roll(NamedTuple):
    sec: str            # 'Critical Strike/Haste' (sorted), '' when the item has no random secondaries
    heavy: str          # the larger of the two secondaries ('' when they're equal or there are none)
    ter: str            # 'Speed', 'Leech', 'Avoidance', 'Indestructible' or ''
    sock: int           # sockets added by the roll
    curve: int          # the level curve (type 49), 0 when there's none
    delta: int          # item level change (type 1), used when there's no curve
    level_key: str      # what decides the item level: 'c<curve>' or 'd<delta>/<drop level>'
    bonus: str          # the listing's bonus ids, sorted, ':'-joined (for its tooltip)
    crafted: str        # '36:49' from modifiers 29 / 30, or ''
    bind: int = 0       # binding override (ItemSparse codes: 1 picked up, 2 equipped, 3 used), 0 for none

    @property
    def key(self):
        """One row per roll a buyer can tell apart: the same stats, socket and item level."""
        return f'{self.sec}|{self.ter}|{self.sock}|{self.level_key}'


def decode(item, bonus_effects):
    """
    A listing's item ({'id', 'bonus_lists', 'modifiers'}) -> its Roll. bonus_effects: bonus id -> [(type, v0, v1)].
    """
    bonus_ids = sorted(item.get('bonus_lists') or ())
    mods = {m.get('type'): m.get('value') for m in item.get('modifiers') or ()}
    stats, ter, sock, curve, delta, bind = [], '', 0, 0, 0, 0
    for b in bonus_ids:
        for kind, v0, v1 in bonus_effects.get(b, ()):
            if kind == STAT and v0 in SECONDARY:
                stats.append((SECONDARY[v0], v1))
            elif kind == STAT and v0 in TERTIARY:
                ter = TERTIARY[v0]
            elif kind == SOCKET:
                sock += v0
            elif kind == LEVEL_CURVE:
                curve = v0
            elif kind == LEVEL_DELTA:
                delta += v0
            elif kind == BINDING:
                bind = v0
    crafted = ''
    if MOD_STAT_1 in mods and MOD_STAT_2 in mods:
        first, second = mods[MOD_STAT_1], mods[MOD_STAT_2]
        crafted = f'{first}:{second}'
        if first in SECONDARY and second in SECONDARY:
            stats = [(SECONDARY[first], 2), (SECONDARY[second], 1)]
    stats.sort(key=lambda s: (-s[1], s[0]))
    names = sorted({name for name, _ in stats})
    heavy = stats[0][0] if len(stats) > 1 and stats[0][1] > stats[1][1] else ''
    level_key = f'c{curve}' if curve else f'd{delta}/{mods.get(MOD_DROP_LEVEL, "")}'
    return Roll('/'.join(names), heavy, ter, sock, curve, delta, level_key,
                ':'.join(str(b) for b in bonus_ids), crafted, bind)


def item_level(roll, base_level, curve_levels):
    """The roll's item level: its curve's (when known), else the item's own plus the roll's change."""
    if roll.curve and curve_levels.get(roll.curve):  # 0: a curve Wowhead couldn't tell us
        return curve_levels[roll.curve]
    return max(1, (base_level or 0) + roll.delta)


def tooltip_query(bonus, crafted):
    """The query string raidanalysis.items (Wowhead) takes for this roll's tooltip, in its canonical order."""
    parts = []
    if bonus:
        parts.append(f'bonus={bonus}')
    if crafted:
        parts.append(f'crafted-stats={crafted}')
    return '&'.join(parts)
