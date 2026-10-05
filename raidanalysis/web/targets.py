"""
Damage by target: for every target of a boss, everyone's damage on it ranked - WCL-style bars in class
colors, a gold star for whoever did the most. On the night's Players view (all the boss's pulls, or one),
and inline under a row of a player's "Where your damage went" (you highlighted, your rank).

Data: throughput.target_ranking() - the pulls' DamageDone tables, no extra WCL request.
"""
from .render import CLASS_COLORS, ROLE_ICONS, esc, fmt_amount

ROWS_SHOWN = 8  # per target card; the rest behind "Show all"


def _row(p, rank, top, highlight=None):
    color = CLASS_COLORS.get(p['class'], '#9aa1b9')
    star = '<span class="dt-star" title="Most damage to it">★</span>' if rank == 1 else f'<span class="dt-rank">{rank}</span>'
    you = ' you' if p['name'] == highlight else ''
    healer = ' heal' if p['role'] == 'healer' else ''
    pulls = f' · {p["pulls"]} pull{"s" if p["pulls"] != 1 else ""}' if p.get('pulls', 1) > 1 else ''
    return (f'<div class="dt-row{you}{healer}" title="{esc(p["name"])}: {fmt_amount(p["damage"])} '
            f'({100 * p["share"]:.1f}% of it){pulls}">{star}'
            f'<span class="dt-name" style="color:{color}">{ROLE_ICONS.get(p["role"], "")} {esc(p["name"])}</span>'
            f'<div class="dt-bar" style="--c:{color};--w:{100 * p["damage"] / top:.1f}%">'
            f'<span>{fmt_amount(p["damage"])}</span><b>{100 * p["share"]:.0f}%</b></div></div>')


def ranking(target, highlight=None, shown=ROWS_SHOWN):
    """One target's players ranked. highlight: always shown (with a gap) and marked, with its rank."""
    players = target['players']
    if not players:
        return '<p class="muted small">Nobody hit it.</p>'
    top = players[0]['damage'] or 1
    rows = [_row(p, i, top, highlight) for i, p in enumerate(players, 1)]
    mine = next((i for i, p in enumerate(players) if p['name'] == highlight), None)
    head, rest = rows[:shown], rows[shown:]
    if mine is not None and mine >= shown:  # you're further down: shown under the top, the gap marked
        head = head + ['<div class="dt-gap">⋯</div>', rows[mine]]
        rest = [r for i, r in enumerate(rows[shown:], shown) if i != mine]
    more = (f'<details class="dt-more"><summary>Show all {len(rows)}</summary>{"".join(rest)}</details>'
            if rest and highlight is None else '')
    return f'<div class="dt-rows">{"".join(head)}{more}</div>'


def your_rank(target, name):
    """'#4 of 14' for a player on a target, or ''."""
    players = target['players']
    i = next((i for i, p in enumerate(players, 1) if p['name'] == name), None)
    return f'#{i} of {len(players)}' if i else ''


def _order(ranked, priority):
    """Priority adds first, then the main boss, then by the raid's damage."""
    return sorted(ranked, key=lambda t: (t['name'] not in priority, not t['main'], -t['total']))


def section(ranked, priority=(), scope='', loading=''):
    """The Players view's card: one ranking per target (healers behind a toggle); loading: a cast bar while
    everyone's damage still comes from WCL (the cards show the top-5 lists meanwhile)."""
    if not ranked:
        return ''
    cards = []
    for t in _order(ranked, set(priority)):
        pills = ('<span class="pill pill-kill">priority</span>' if t['name'] in priority else '') + \
                ('<span class="pill pill-muted">boss</span>' if t['main'] or t['type'] == 'Boss' else '')
        cards.append(f"""
            <div class="dt-card">
                <div class="dt-head"><b>{esc(t['name'])}</b>{pills}
                    <span class="muted small">{fmt_amount(t['total'])} · {len(t['players'])} players</span></div>
                {ranking(t)}
            </div>""")
    return f"""
    <div class="card dt-wrap" id="damage-by-target">
        <div class="sec-head"><div class="sec-title"><span class="sec-icon">🎯</span><div><h2>Damage by target</h2>
            <p class="sec-sub">Who did the damage to each target{f' - {esc(scope)}' if scope else ''}: priority adds
               first, then the boss and the rest. ★ = the most damage to it. Hover a row for the exact numbers.</p>
            </div></div>
            <div class="sec-action"><label class="small"><input type="checkbox" class="dt-heal-toggle"> Show healers</label></div>
        </div>
        {loading}
        <div class="dt-cards">{''.join(cards)}</div>
    </div>"""
