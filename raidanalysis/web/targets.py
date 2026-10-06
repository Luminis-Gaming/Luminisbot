"""
Damage by target: for every target of a boss, everyone's damage on it ranked - WCL-style bars in class
colors, a gold star for whoever did the most. On the Mechanics tab (all the boss's pulls tonight, or one),
and inline under a row of a player's "Where your damage went" (you highlighted, your rank).

Data: throughput.target_ranking() - everyone's damage per target (focus.load_by_target), else the pulls'
DamageDone tables.
"""
from .render import CLASS_COLORS, ROLE_ICONS, esc, fmt_amount, npc_zoom

ROWS_SHOWN = 8  # per target card; the rest behind "Show all"


def _row(p, rank, top, highlight=None, extra=False, of_pulls=None):
    """
    One player's bar: their DPS on the target (the bar, against the best) and total damage on it. extra:
    past the top shown, until the card's button opens it; of_pulls: how many pulls had the target.
    """
    color = CLASS_COLORS.get(p['class'], '#9aa1b9')
    badge = ('<span class="dt-star" title="Highest DPS on it">★</span>' if rank == 1 else
             f'<span class="dt-num">{rank}</span>')
    classes = 'dt-row' + (' you' if p['name'] == highlight else '') + (' extra' if extra else '')
    pulls = f' in {p["pulls"]} of {of_pulls} pulls' if of_pulls and of_pulls > 1 else ''
    return (f'<div class="{classes}" title="{esc(p["name"])}: {fmt_amount(p["dps"])} DPS on it{pulls} · '
            f'{fmt_amount(p["damage"])} damage ({100 * p["share"]:.1f}% of all damage to it)">'
            f'<span class="dt-rank">{badge}</span>'
            f'<span class="dt-name" style="color:{color}">{ROLE_ICONS.get(p["role"], "")} {esc(p["name"])}</span>'
            f'<div class="dt-bar" style="--c:{color};--w:{100 * p["dps"] / top:.1f}%">'
            f'<span>{fmt_amount(p["dps"])}</span><b>{fmt_amount(p["damage"])}</b></div></div>')


def ranking(target, highlight=None, shown=ROWS_SHOWN):
    """
    Everyone who hit one target, ranked (0 damage: left out). With highlight (a player's page): the top
    `shown` and that player, marked (with a gap when further down). Without (the Mechanics card): the top
    `shown`, the rest behind a button at the bottom ("Show all N" / "Show top N").
    """
    players = [p for p in target['players'] if p['damage'] > 0]
    if not players:
        return '<p class="muted small">Nobody hit it.</p>'
    top = max(p['dps'] for p in players) or 1
    of_pulls = target.get('pulls')
    if highlight is not None:
        rows = [_row(p, i, top, highlight, of_pulls=of_pulls) for i, p in enumerate(players, 1)]
        mine = next((i for i, p in enumerate(players) if p['name'] == highlight), None)
        head = rows[:shown]
        if mine is not None and mine >= shown:  # you're further down: shown under the top, the gap marked
            head += ['<div class="dt-gap">⋯</div>', rows[mine]]
        return f'<div class="dt-rows">{"".join(head)}</div>'
    rows = ''.join(_row(p, i, top, extra=i > shown, of_pulls=of_pulls) for i, p in enumerate(players, 1))
    button = (f'<button type="button" class="dt-toggle"><span class="l-more">Show all {len(players)}</span>'
              f'<span class="l-less">Show top {shown}</span></button>' if len(players) > shown else '')
    return f'<div class="dt-rows">{rows}{button}</div>'


def your_rank(target, name):
    """'#4 of 14' for a player on a target, or ''."""
    players = [p for p in target['players'] if p['damage'] > 0]
    i = next((i for i, p in enumerate(players, 1) if p['name'] == name), None)
    return f'#{i} of {len(players)}' if i else ''


def _order(ranked, priority):
    """Priority adds first, then the main boss, then by the raid's damage."""
    return sorted(ranked, key=lambda t: (t['name'] not in priority, not t['main'], -t['total']))


def section(ranked, priority=(), scope='', loading='', npc_icons=None, npc_links=None):
    """The Mechanics tab's card: one ranking per target; loading: a cast bar while everyone's damage still
    comes from WCL (the cards show the top-5 lists meanwhile); npc_icons: {target: portrait url} (npcs.icons),
    npc_links: {target: Wowhead URL} (npcs.wowhead_links) - the name opens it in a new tab."""
    if not ranked:
        return ''
    npc_icons, npc_links = npc_icons or {}, npc_links or {}
    cards = []
    for t in _order(ranked, set(priority)):
        pills = ('<span class="pill pill-kill">priority</span>' if t['name'] in priority else '') + \
                ('<span class="pill pill-muted">boss</span>' if t['main'] or t['type'] == 'Boss' else '')
        cards.append(f"""
            <div class="dt-card">
                <div class="dt-head">{npc_zoom(t['name'], npc_icons.get(t['name']), npc_links.get(t['name']))}
                    {_name(t['name'], npc_links.get(t['name']))}{pills}
                    <span class="muted small">{fmt_amount(t['total'])} · {sum(1 for p in t['players'] if p['damage'] > 0)} players</span></div>
                {ranking(t)}
            </div>""")
    return f"""
    <div class="card dt-wrap" id="damage-by-target">
        <div class="sec-head"><div class="sec-title"><span class="sec-icon">🎯</span><div><h2>Damage by target</h2>
            <p class="sec-sub">Who did the damage to each target{f' - {esc(scope)}' if scope else ''}: priority adds
               first, then the boss and the rest. Ranked by DPS on it while it was up, over the pulls each player was in
               that had it, so missing a few pulls doesn't count against you: the bar is DPS, the number on the right total damage.
               ★ = the highest DPS on it. Hover a row for the details.</p>
            </div></div>
        </div>
        {loading}
        <div class="dt-cards">{''.join(cards)}</div>
    </div>"""


def _name(name, href):
    """The target's name - a link to its Wowhead page (new tab) when there is one."""
    if not href or not href.startswith('https://www.wowhead.com/'):
        return f'<b>{esc(name)}</b>'
    return (f'<a class="dt-npc" href="{esc(href)}" target="_blank" rel="noopener" title="{esc(name)} on Wowhead">'
            f'<b>{esc(name)}</b><span aria-hidden="true">↗</span></a>')
