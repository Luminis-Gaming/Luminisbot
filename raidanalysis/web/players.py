"""
The "Players" view: a card per player with a 0-100 score, its three
sub-scores, contributions and plain-language feedback, plus a per-player page
with the pull-by-pull breakdown. Numbers come from analyzer.player_report.
"""
import re
from urllib.parse import quote

from .render import (ROLE_ICONS, esc, fmt_duration, guide_button, per_pull_columns, player_name)

SUBSCORES = (('survival', 'Survival', 'Share of pull time alive until the wipe was called'),
             ('mechanics', 'Mechanics', 'Avoidable hits compared to the raid — 100 = never hit, ~70 = raid average'),
             ('potions', 'Potions', 'Share of pulls with a combat potion'))


def _band(score):
    """Score band - always shown as text next to the color."""
    if score >= 85:
        return 'good', 'Great'
    if score >= 70:
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
                   f'<div class="subscore-track"><div class="subscore-fill {_band(value)[0]}" '
                   f'style="width:{value:.0f}%"></div></div><b>{value:.0f}</b></div>')
    return ''.join(out)


def _contributions(p):
    chips = []
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
                    <p class="muted small">{ROLE_ICONS.get(p['role'], '')} {spec}{esc(_class_label(p['class']))} ·
                       {p['pulls']} pull{'s' if p['pulls'] != 1 else ''}</p>
                </div>
            </header>
            <div class="subscores">{_subscore_bars(p['scores'])}</div>
            <div class="chips">{_contributions(p)}</div>
            <ul class="notes">{notes or '<li class="note info"><span>👍</span><span>Nothing stands out.</span></li>'}</ul>
            <a class="card-link" href="{esc(player_href(p['name']))}">
                {f'+{more} more · ' if more > 0 else ''}Pull-by-pull details →</a>
        </article>""")
    return f"""
    <div class="card">
        <h2>👥 Players</h2>
        <p class="muted small">Score = Survival 40% + Mechanics 45% + Potions 15% (Survival 70% + Potions 30% while no
           avoidable mechanics are known for this boss). Mechanics compares avoidable hits to the raid: 100 = never hit,
           about 70 = raid average.</p>
        <div class="pull-chips">{filters}</div>
    </div>
    <div class="player-grid">{''.join(cards)}</div>"""


def player_page(p, guide_for, pull_href):
    """One player across the selected pulls. pull_href(number) -> link to that pull."""
    rows = []
    for pp in p['per_pull']:
        if pp['died_at'] is not None:
            status = (f'<span class="bad-text">died {fmt_duration(pp["died_at"])}</span> '
                      f'<span class="muted small">to {esc(pp["died_to"])}{" · first" if pp["first"] else ""}</span>')
        else:
            status = '<span class="good-text">alive until the end</span>' if pp['kill'] else \
                '<span class="good-text">alive until the wipe call</span>'
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
        <div class="player-hero">
            {score_ring(p['score'], 'lg')}
            <div>
                <h2>{player_name(p['name'], p['class'])}</h2>
                <p class="muted">{ROLE_ICONS.get(p['role'], '')} {esc(p['spec'])} {esc(_class_label(p['class']))} ·
                   {p['pulls']} pulls · {p['deaths']} deaths before the wipe call</p>
                <div class="subscores wide">{_subscore_bars(p['scores'])}</div>
                <div class="chips">{_contributions(p)}</div>
            </div>
        </div>
    </div>
    <div class="grid-2">
        <div class="card"><h2>📝 Feedback</h2>
            <ul class="notes">{''.join(_note(n, guide_for) for n in p['feedback']) or
                               '<li class="note info"><span>👍</span><span>Nothing stands out.</span></li>'}</ul></div>
        <div class="card"><h2>🎯 Avoidable hits</h2>
            {f'<ul class="notes">{mechanics}</ul>' if mechanics else '<p class="muted">Never hit by an avoidable mechanic.</p>'}
            {f'<h4>Per pull</h4>{chart}' if chart and p['avoidable_hits'] else ''}</div>
    </div>
    <div class="card">
        <h2>📋 Pull by pull</h2>
        <div class="table-wrapper"><table class="compact">
            <tr><th class="num">Pull</th><th></th><th>Outcome</th><th class="num">Avoidable hits</th>
                <th class="num">Potion</th><th class="num">Healthstones</th></tr>
            {''.join(rows)}
        </table></div>
    </div>"""


def player_url(code, name, boss_key, fight_id=None):
    base = f'/admin/raids/report/{code}/player/{quote(name)}?boss={boss_key[0]}-{boss_key[1]}'
    return base + (f'&pull={fight_id}' if fight_id else '')
