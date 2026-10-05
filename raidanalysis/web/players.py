"""
The "Players" view: a card per player with a 0-100 score, its three
sub-scores, contributions and plain-language feedback, plus a per-player page
with the pull-by-pull breakdown. Numbers come from analyzer.player_report.
"""
import re
from urllib.parse import quote

from .render import (ROLE_ICONS, SERIES_PULL, esc, fmt_duration, guide_button, per_pull_columns, player_name,
                     sparkline)

SUBSCORES = (('survival', 'Survival', 'Share of pull time alive until half the raid was dead'),
             ('mechanics', 'Mechanics', 'Avoidable hits compared to the raid — 100 = never hit, ~70 = raid average'),
             ('potions', 'Potions', 'Share of pulls with a combat potion'))


def _band(score):
    """Score band - always shown as text next to the color."""
    if score >= 80:
        return 'good', 'Great'
    if score >= 60:
        return 'ok', 'OK'
    return 'bad', 'Improve'


def _class_label(cls):
    """'DeathKnight' -> 'Death Knight'."""
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', cls or '')


def score_ring(score, size='md'):
    band, label = _band(score)
    return (f'<div class="score-ring {band} {size}" style="--p:{max(0, min(100, score))}" '
            f'title="{label} — {score}/100"><span>{score}</span><small>{label}</small></div>')


def _subscore_bars(scores):
    out = []
    for key, label, hint in SUBSCORES:
        if key not in scores:
            continue
        value = scores[key]
        out.append(f'<div class="subscore" title="{esc(hint)}"><span>{label}</span>'
                   f'<div class="subscore-track"><div class="subscore-fill {_component_band(value)}" '
                   f'style="width:{value:.0f}%"></div></div><b>{value:.0f}</b></div>')
    return ''.join(out)


def _component_band(value):
    """Breakdown bars: ~50 is raid-average for relative components, so it gets amber, not red."""
    if value >= 75:
        return 'good'
    if value >= 45:
        return 'ok'
    return 'bad'


def breakdown(p, guide_for):
    """Every component behind the score - Wipefest-style bars with the raw numbers."""
    rows = []
    for c in p.get('components') or []:
        band = 'neutral' if c['bonus'] else _component_band(c['value'])
        clip = guide_button(guide_for(c['ability']['id'], c['ability']['name']), c['label']) if c['ability'] else ''
        tag = ' <small class="muted">bonus</small>' if c['bonus'] else (
            ' <small class="muted">×2</small>' if c['weight'] >= 2 else
            ' <small class="muted">×½</small>' if c['weight'] < 1 else '')
        rows.append(f'<div class="comp"><div class="comp-head"><span>{esc(c["label"])}{clip}{tag}</span>'
                    f'<b>{c["value"]:.0f}</b></div>'
                    f'<div class="subscore-track"><div class="subscore-fill {band}" style="width:{c["value"]:.0f}%">'
                    f'</div></div><div class="comp-detail">{esc(c["detail"])}</div></div>')
    return f'<div class="breakdown">{"".join(rows)}</div>'


def _contributions(p):
    chips = []
    if p.get('contribution') is not None:
        chips.append(f'<span class="chip" title="Average of the bonus components (interrupts, dispels) - '
                     f'not part of the score">⭐ Contribution {p["contribution"]}</span>')
    if p['interrupts']:
        chips.append(f'<span class="chip">✋ {p["interrupts"]} interrupt{"s" if p["interrupts"] != 1 else ""}</span>')
    if p['dispels']:
        chips.append(f'<span class="chip">✨ {p["dispels"]} dispel{"s" if p["dispels"] != 1 else ""}</span>')
    if p['defensives']:
        chips.append(f'<span class="chip">❤️ {p["defensives"]} healthstone{"s" if p["defensives"] != 1 else ""}</span>')
    return ''.join(chips)


def _note(note, guide_for):
    icon = {'bad': '⚠️', 'good': '✅', 'info': 'ℹ️'}[note['tone']]
    clip = ''
    if note.get('ability'):
        clip = guide_button(guide_for(note['ability']['id'], note['ability']['name']), note['ability']['name'])
    return f'<li class="note {note["tone"]}"><span>{icon}</span><span>{esc(note["text"])}{clip}</span></li>'


def players_view(players, guide_for, player_href):
    """The grid. player_href(name) -> link to that player's page."""
    if not players:
        return '<div class="card"><p class="muted">No players in these pulls.</p></div>'
    counts = {role: sum(1 for p in players if p['role'] == role) for role in ('tank', 'healer', 'dps')}
    filters = ''.join(
        f'<button type="button" class="pull-chip role-filter{" active" if role == "all" else ""}" data-role="{role}">'
        f'{label}</button>'
        for role, label in (('all', f'Everyone ({len(players)})'), ('tank', f'🛡️ Tanks ({counts["tank"]})'),
                            ('healer', f'💚 Healers ({counts["healer"]})'), ('dps', f'⚔️ DPS ({counts["dps"]})')))
    cards = []
    for p in players:
        notes = ''.join(_note(n, guide_for) for n in p['feedback'][:3])
        more = len(p['feedback']) - 3
        spec = f'{esc(p["spec"])} ' if p['spec'] else ''
        cards.append(f"""
        <article class="player-card" data-role="{esc(p['role'])}">
            <header>
                {score_ring(p['score'])}
                <div>
                    <h3>{player_name(p['name'], p['class'])}</h3>
                    <p class="muted small">{ROLE_ICONS.get(p['role'], '')} {spec}{esc(_class_label(p['class']))}{_other_specs(p)} ·
                       {p['pulls']} pull{'s' if p['pulls'] != 1 else ''}</p>
                </div>
            </header>
            <div class="subscores">{_subscore_bars(p['scores'])}</div>
            <div class="chips">{_contributions(p)}</div>
            <ul class="notes">{notes or '<li class="note info"><span>👍</span><span>Nothing stands out.</span></li>'}</ul>
            <details class="breakdown-toggle"><summary>Score breakdown ({len(p.get('components') or [])})</summary>
                {breakdown(p, guide_for)}</details>
            <a class="card-link" href="{esc(player_href(p['name']))}">
                {f'+{more} more · ' if more > 0 else ''}Pull-by-pull details →</a>
        </article>""")
    return f"""
    <div class="card">
        <div class="sec-head"><div class="sec-title"><span class="sec-icon">👥</span><div><h2>Players</h2></div></div></div>
        <p class="muted small">Score = weighted average of 0–100 components: Survival (×2), Deaths, one per avoidable
           mechanic, Potions and Healthstones (×½). Mechanics and deaths are compared with the raid — 100 means never hit,
           about 50 means raid average. Interrupts and dispels are shown as contributions and don't lower anyone's score.
           Open <strong>Score breakdown</strong> on a card to see every number.</p>
        <div class="pull-chips">{filters}</div>
    </div>
    <div class="player-grid">{''.join(cards)}</div>"""


def _other_specs(p):
    """' (also Havoc on 1 pull)' when they swapped spec during the night."""
    others = [(s, n) for s, n in (p.get('spec_pulls') or {}).items() if s != p.get('spec')]
    if not others:
        return ''
    text = ', '.join(f'{s} on {n} pull{"s" if n != 1 else ""}' for s, n in others)
    return f' <span class="muted">(also {esc(text)})</span>'


PLAYER_TABS = (('execution', '🧮', 'Execution'), ('damage', '📈', 'Damage & focus'),
               ('cooldowns', '⚔️', 'Cooldowns'), ('rotation', '🔁', 'Rotation'))


def player_hero(p, tab_href, active):
    """The player page's header - score, sub-scores, contributions - and its section tabs. tab_href(key) -> link."""
    tabs = ''.join(f'<a class="ptab{" active" if key == active else ""}" href="{esc(tab_href(key))}">{icon} {label}</a>'
                   for key, icon, label in PLAYER_TABS)
    return f"""
    <div class="card">
        <div class="player-hero">
            {score_ring(p['score'], 'lg')}
            <div>
                <h2>{player_name(p['name'], p['class'])}</h2>
                <p class="muted">{ROLE_ICONS.get(p['role'], '')} {esc(p['spec'])} {esc(_class_label(p['class']))} ·
                   {p['pulls']} pulls · {p['deaths']} early death{'s' if p['deaths'] != 1 else ''} by mistake</p>
                <div class="subscores wide">{_subscore_bars(p['scores'])}</div>
                <div class="chips">{_contributions(p)}</div>
            </div>
        </div>
    </div>
    <nav class="ptabs">{tabs}</nav>"""


def player_page(p, guide_for, pull_href):
    """
    The Execution section of a player's page: score breakdown, feedback, avoidable hits and the pull-by-pull
    table (the header with the score is player_hero). pull_href(number) -> link to that pull.
    """
    rows = []
    for pp in p['per_pull']:
        if pp['died_at'] is not None:
            status = (f'<span class="{"bad-text" if pp.get("mistake") else "muted"}">died {fmt_duration(pp["died_at"])}</span> '
                      f'<span class="muted small">to {esc(pp["died_to"])}{" · first" if pp["first"] else ""}'
                      f'{" · " + esc(pp["death_note"]) if pp.get("death_note") else ""}</span>')
        else:
            status = '<span class="good-text">alive until the end</span>' if pp['kill'] else \
                '<span class="good-text">alive until half the raid was dead</span>'
        rows.append(f"""
            <tr onclick="location='{esc(pull_href(pp['number']))}'" style="cursor:pointer">
                <td class="num">#{pp['number']}</td>
                <td>{'<span class="pill pill-kill">✔ Kill</span>' if pp['kill'] else ''}</td>
                <td>{status}</td>
                <td class="num{' bad' if pp['avoidable_hits'] else ''}">{pp['avoidable_hits'] or ''}</td>
                <td class="num">{'✓' if pp['potion'] else '<span class="bad-text">✗</span>'}</td>
                <td class="num">{pp['defensive'] or ''}</td>
            </tr>""")
    mechanics = ''.join(
        f'<li class="note bad"><span>🎯</span><span>{esc(a["name"])}{guide_button(guide_for(a["id"], a["name"]), a["name"])}'
        f' — {a["hits"]} hit{"s" if a["hits"] != 1 else ""}</span></li>'
        for a in sorted(p['avoidable'].values(), key=lambda a: -a['hits']))
    chart = per_pull_columns([(pp['number'], pp['avoidable_hits']) for pp in p['per_pull']], 'Avoidable hits per pull')
    return f"""
    <div class="card">
        <div class="sec-head"><div class="sec-title"><span class="sec-icon">🧮</span><div><h2>Score breakdown</h2></div></div></div>
        <p class="muted small">Every number behind the score. 100 = best; relative components compare with the rest of
           the raid on the same pulls (about 50 = raid average).</p>
        {breakdown(p, guide_for)}
    </div>
    <div class="grid-2">
        <div class="card"><div class="sec-head"><div class="sec-title"><span class="sec-icon">📝</span><div><h2>Feedback</h2></div></div></div>
            <ul class="notes">{''.join(_note(n, guide_for) for n in p['feedback']) or
                               '<li class="note info"><span>👍</span><span>Nothing stands out.</span></li>'}</ul></div>
        <div class="card"><div class="sec-head"><div class="sec-title"><span class="sec-icon">🎯</span><div><h2>Avoidable hits</h2></div></div></div>
            {f'<ul class="notes">{mechanics}</ul>' if mechanics else '<p class="muted">Never hit by an avoidable mechanic.</p>'}
            {f'<h4>Per pull</h4>{chart}' if chart and p['avoidable_hits'] else ''}</div>
    </div>
    <div class="card">
        <div class="sec-head"><div class="sec-title"><span class="sec-icon">📋</span><div><h2>Pull by pull</h2></div></div></div>
        <div class="table-wrapper"><table class="compact">
            <tr><th class="num">Pull</th><th></th><th>Outcome</th><th class="num">Avoidable hits</th>
                <th class="num">Potion</th><th class="num">Healthstones</th></tr>
            {''.join(rows)}
        </table></div>
    </div>"""


def compact_table(report, href):
    """
    The Players card on the Mechanics tab: a short version of the Players tab - score, sub-scores, the
    key numbers and each player's top improvement point - one row per player, linking to their page.
    report: analyzer.player_report rows; href(name) -> the player's page for these pulls.
    """
    if not report:
        return '<p class="muted">No players.</p>'
    rows = []
    for p in sorted(report, key=lambda r: ({'tank': 0, 'healer': 1}.get(r.get('role'), 2), -r['score'])):
        band, label = _band(p['score'])
        subs = ''.join(
            f'<td class="num" data-v="{p["scores"][key]:.0f}"><span class="sub-val {_component_band(p["scores"][key])}" '
            f'title="{esc(hint)}">{p["scores"][key]:.0f}</span></td>' if key in p['scores'] else '<td></td>'
            for key, _, hint in SUBSCORES)
        tip = next((n for n in p.get('feedback') or [] if n['tone'] == 'bad'), None)
        tip_html = (f'<span class="tip-line" title="{esc(tip["text"])}">⚠️ {esc(tip["text"])}</span>' if tip else
                    '<span class="muted">Nothing stands out 👍</span>')
        link = esc(href(p['name']))
        spec = f'{esc(p["spec"])} ' if p.get('spec') else ''
        rows.append(f"""
            <tr class="click-row" onclick="location='{link}'" title="Open {esc(p['name'])}'s page for these pulls">
                <td data-v="{p['score']}"><span class="score-badge {band}" title="{label}">{p['score']}</span></td>
                <td data-v="{esc(p['name'])}"><a href="{link}" class="plain-link">{player_name(p['name'], p['class'])}</a>
                    <div class="muted small">{ROLE_ICONS.get(p.get('role'), '')} {spec}{esc(_class_label(p['class']))}</div></td>
                {subs}
                <td class="num {'bad' if p['deaths'] else 'good-text'}">{p['deaths']}</td>
                <td class="num {'bad' if p['avoidable_hits'] else 'good-text'}">{p['avoidable_hits']}</td>
                <td class="num{'' if p['interrupts'] else ' muted'}">{p['interrupts']}</td>
                <td class="num{'' if p['dispels'] else ' muted'}">{p['dispels']}</td>
                <td class="small tip-cell">{tip_html}</td>
            </tr>""")
    sub_heads = ''.join(f'<th data-sort class="num" title="{esc(hint)}">{label}</th>' for _, label, hint in SUBSCORES)
    return f"""<div class="table-wrapper"><table class="compact players-compact">
        <tr><th data-sort>Score</th><th data-sort>Player</th>{sub_heads}
            <th data-sort class="num" title="Early deaths by mistake">Deaths</th>
            <th data-sort class="num" title="Hits from avoidable mechanics">Avoidable</th>
            <th data-sort class="num">Interrupts</th><th data-sort class="num">Dispels</th>
            <th>Top thing to work on</th></tr>
        {''.join(rows)}</table></div>"""


def player_url(code, name, boss_key, fight_id=None):
    base = f'/admin/raids/report/{code}/player/{quote(name)}?boss={boss_key[0]}-{boss_key[1]}'
    return base + (f'&pull={fight_id}' if fight_id else '')


# ============================================================================
# Trends across nights (boss page)
# ============================================================================

def person_key(character, owners):
    """Who plays this character: their Discord id when we know it, else the character itself."""
    owner = (owners or {}).get(character.lower())
    return owner['key'] if owner else character


def player_history(night_data, owners=None):
    """
    {person_key: {'key', 'display', 'characters', 'nights': [(night_label, report_code, player_row)]}}
    in night order. Characters belonging to the same person (linked Battle.net characters or
    raid signups) are one history; if they played two characters in one night, the one with
    more pulls counts.
    """
    history = {}
    for nd in night_data:
        tonight = {}
        for p in nd['players']:
            key = person_key(p['name'], owners)
            if key not in tonight or p['pulls'] > tonight[key]['pulls']:
                tonight[key] = p
        for key, p in tonight.items():
            entry = history.setdefault(key, {'key': key, 'characters': [], 'nights': [],
                                             'display': ((owners or {}).get(p['name'].lower()) or {}).get('display')})
            if p['name'] not in entry['characters']:
                entry['characters'].append(p['name'])
            entry['nights'].append((nd['label'], nd['code'], p))
    return history


def _person_label(entry, show_discord=True):
    """
    Latest character (class-colored), plus the Discord name and other characters for alt-hoppers.
    The public pages leave the Discord name out (show_discord=False): no tying accounts to characters.
    """
    last = entry['nights'][-1][2]
    chars = entry['characters']
    name = player_name(chars[-1], last['class'], last['role'])
    if len(chars) == 1:
        return name
    lead = f'{esc(entry["display"])} · ' if entry.get('display') and show_discord else ''
    return f'{lead}{name} <span class="muted small">(also {" / ".join(esc(c) for c in chars[:-1])})</span>'


def _delta(first, last):
    change = last - first
    if abs(change) < 3:
        return '<span class="muted">±0</span>'
    arrow = '▲' if change > 0 else '▼'
    return f'<span class="{"trend-up" if change > 0 else "trend-down"}">{arrow} {abs(change):.0f}</span>'


def trends_card(night_data, trend_href, owners=None, show_discord=True):
    """
    Score trend per person across nights. trend_href(key) links each row; without show_discord
    (public pages) rows link by their latest character instead of the Discord-based person key.
    """
    if len(night_data) < 2:
        return ('<div class="card"><div class="sec-head"><div class="sec-title"><span class="sec-icon">📈</span><div><h2>Player trends</h2></div></div></div><p class="muted">Trends show up once this boss has been '
                'pulled on two or more nights.</p></div>')
    rows = []
    for key, entry in player_history(night_data, owners).items():
        nights = entry['nights']
        if len(nights) < 2:
            continue
        scores = [row['score'] for _, _, row in nights]
        hits = [row['avoidable_hits'] / row['pulls'] for _, _, row in nights]
        rows.append((scores[-1] - scores[0], f"""
            <tr onclick="location='{esc(trend_href(key if show_discord else entry['characters'][-1]))}'" style="cursor:pointer">
                <td data-v="{esc((entry.get('display') if show_discord else None) or entry['characters'][-1])}">{_person_label(entry, show_discord)}</td>
                <td class="num">{len(nights)}</td>
                <td>{sparkline(scores)}</td>
                <td class="num" data-v="{scores[-1]}">{scores[0]} → <b>{scores[-1]}</b></td>
                <td class="num" data-v="{scores[-1] - scores[0]}">{_delta(scores[0], scores[-1])}</td>
                <td class="num" data-v="{hits[-1]:.2f}">{hits[0]:.1f} → {hits[-1]:.1f}</td>
            </tr>"""))
    if not rows:
        return ''
    body = ''.join(r for _, r in sorted(rows, key=lambda r: -r[0]))
    return f"""
    <div class="card">
        <div class="sec-head"><div class="sec-title"><span class="sec-icon">📈</span><div><h2>Player trends</h2></div></div></div>
        <p class="muted small">Each player's score on this boss, night by night (most improved first). Alts are
           combined per person through their linked characters and signups. Click a player for the full picture.</p>
        <div class="table-wrapper"><table class="compact">
            <tr><th data-sort>Player</th><th data-sort class="num">Nights</th><th>Score per night</th>
                <th data-sort class="num">First → latest</th><th data-sort class="num">Change</th>
                <th data-sort class="num" title="Avoidable hits per pull, first night → latest">Avoidable hits / pull</th></tr>
            {body}
        </table></div>
    </div>"""


def trend_chart(points):
    """Score per night (single series, 0-100) with each value printed beside its point."""
    if len(points) < 2:
        return ''
    width, height, left, right, top, bottom = 900, 220, 40, 20, 20, 30
    inner_w, inner_h = width - left - right, height - top - bottom
    step = inner_w / (len(points) - 1)

    def y(v):
        return top + inner_h * (1 - v / 100)

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Score per night">']
    for v in (0, 50, 70, 85, 100):
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{v}</text>')
    line = ' '.join(f'{left + i * step:.1f},{y(v):.1f}' for i, (_, v) in enumerate(points))
    parts.append(f'<polyline points="{line}" fill="none" stroke="{SERIES_PULL}" stroke-width="2" '
                 f'stroke-linejoin="round"/>')
    for i, (label, v) in enumerate(points):
        cx = left + i * step
        parts.append(f'<circle cx="{cx:.1f}" cy="{y(v):.1f}" r="5" fill="{SERIES_PULL}" stroke="#161a2c" '
                     f'stroke-width="2"><title>{esc(label)}: {v}</title></circle>'
                     f'<text x="{cx:.1f}" y="{y(v) - 10:.1f}" text-anchor="middle">{v}</text>'
                     f'<text x="{cx:.1f}" y="{height - 8}" text-anchor="middle">{esc(label)}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def _subscore_cells(row):
    return ''.join(f'<td class="num">{row["scores"][key]:.0f}</td>' if key in row['scores']
                   else '<td class="num muted">—</td>' for key, _, _ in SUBSCORES)


def _mechanics_heat(nights, guide_for):
    """Avoidable hits per pull for each mechanic, per night - lighter to the right = learning it."""
    mechanics = {}
    for _, _, row in nights:
        for ability_id, a in row['avoidable'].items():
            mechanics.setdefault(ability_id, a)
    if not mechanics:
        return ''
    peak = max((row['avoidable'].get(aid, {}).get('hits', 0) / row['pulls']
                for _, _, row in nights for aid in mechanics), default=0) or 1
    head = ''.join(f'<th class="num">{esc(label)}</th>' for label, _, _ in nights)
    body = []
    for ability_id, a in sorted(mechanics.items(), key=lambda kv: kv[1]['name']):
        cells = []
        for _, _, row in nights:
            per_pull = row['avoidable'].get(ability_id, {}).get('hits', 0) / row['pulls']
            cells.append(f'<td class="num heat" style="--a:{0.06 + 0.74 * per_pull / peak:.2f}" '
                         f'title="{per_pull:.2f} hits per pull">{per_pull:.1f}</td>')
        clip = guide_button(guide_for(ability_id, a['name']), a['name'])
        body.append(f'<tr><td>{esc(a["name"])}{clip}</td>{"".join(cells)}</tr>')
    return (f'<h3>Avoidable hits per pull, night by night</h3>'
            f'<p class="muted small">Darker = hit more often. Getting lighter to the right = learning the mechanic.</p>'
            f'<div class="table-wrapper"><table class="compact heatmap"><tr><th>Mechanic</th>{head}</tr>'
            f'{"".join(body)}</table></div>')


def trend_page(entry, guide_for, night_href, show_discord=True):
    """One person on one boss across nights (all their characters). entry: from player_history."""
    nights = entry['nights']
    last = nights[-1][2]
    alts = len(entry['characters']) > 1
    rows = []
    for label, code, row in reversed(nights):
        top_issue = next((n['text'] for n in row['feedback'] if n['tone'] == 'bad'), '')
        character = f'<td>{player_name(row["name"], row["class"])}</td>' if alts else ''
        rows.append(f"""
            <tr onclick="location='{esc(night_href(code, row['name']))}'" style="cursor:pointer">
                <td>{esc(label)}</td>{character}<td class="num">{row['pulls']}</td>
                <td class="num"><b>{row['score']}</b></td>{_subscore_cells(row)}
                <td class="num">{row['deaths']}</td>
                <td class="num">{row['avoidable_hits'] / row['pulls']:.1f}</td>
                <td class="small">{esc(top_issue)}</td>
            </tr>""")
    sub_heads = ''.join(f'<th class="num" title="{esc(hint)}">{label}</th>' for _, label, hint in SUBSCORES)
    return f"""
    <div class="card">
        <div class="player-hero">
            {score_ring(last['score'], 'lg')}
            <div>
                <h2>{_person_label(entry, show_discord)}</h2>
                <p class="muted">{ROLE_ICONS.get(last['role'], '')} {esc(last['spec'])} {esc(_class_label(last['class']))} ·
                   {len(nights)} night{'s' if len(nights) != 1 else ''} on this boss · latest score {last['score']}
                   ({_delta(nights[0][2]['score'], last['score'])} since the first night)</p>
            </div>
        </div>
        {f'<h3 style="margin-top:18px">Score per night</h3>{trend_chart([(label, row["score"]) for label, _, row in nights])}'
         if len(nights) > 1 else ''}
    </div>
    <div class="card">
        <div class="sec-head"><div class="sec-title"><span class="sec-icon">🗓️</span><div><h2>Night by night</h2></div></div></div>
        <div class="table-wrapper"><table class="compact">
            <tr><th>Night</th>{'<th>Character</th>' if alts else ''}<th class="num">Pulls</th><th class="num">Score</th>{sub_heads}
                <th class="num">Deaths</th><th class="num">Avoidable hits / pull</th><th>Biggest issue</th></tr>
            {''.join(rows)}
        </table></div>
        {_mechanics_heat(nights, guide_for)}
    </div>"""
