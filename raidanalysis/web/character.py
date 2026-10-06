"""
The character page: one character across every raid night we keep (character.profile).

    - the hero: their render (from the stored armory), name in class colour, the key numbers and a 📌 pin
      (kept in the browser - the front page shows pinned characters as quick links)
    - Improvement: execution score and WCL parse night by night, all bosses or one at a time, and early
      deaths / avoidable hits per pull underneath; every point opens that night
    - Bosses: progression per boss and difficulty - kills, best pull, best parse, both trends
    - Highlights: the fun facts
    - Every raid log they were in, newest first, each boss a link to their page for it that night
    - right under it: their gear and character sheet (web/armory.py); then raid tier / difficulty chips that
      everything below follows
"""
import json
from datetime import datetime, timezone
from urllib.parse import quote

from .. import armory
from .performance import parse_html
from .players import _band, _class_label
from .render import (CLASS_COLORS, DIFFICULTY_NAMES, ROLE_ICONS, boss_portrait, difficulty_pill, esc, section_head,
                     sparkline)

LOGS_SHOWN = 15          # raid logs listed before "Show all"
RECENT_NIGHTS = 3        # "lately" = the last this many nights, against the ones before
SCORE_COLOR = '#7484ec'  # render.SERIES_PULL
PARSE_COLOR = '#ff8000'
DEATH_COLOR = '#ff6b6b'
AVOID_COLOR = '#fcc419'
PARSE_STEPS = ((100, '#e5cc80'), (99, '#e268a8'), (95, '#ff8000'), (75, '#a335ee'), (50, '#0070ff'),
               (25, '#1eff00'), (0, '#9d9d9d'))
BAND_COLORS = {'good': '#51cf66', 'ok': '#fcc419', 'bad': '#ff6b6b'}


def url(name, realm=None):
    """The character page: /admin/raids/character/{realm slug}/{name} - just the name when the realm is unknown."""
    slug = armory.realm_slug(realm) if realm else ''
    return f'/admin/raids/character/{quote(slug)}/{quote(name)}' if slug else f'/admin/raids/character/{quote(name)}'


def player_href(code, name, key, fight_id=None):
    """Their page on one night (players.player_url)."""
    return (f'/admin/raids/report/{quote(code)}/player/{quote(name)}?boss={key[0]}-{key[1]}'
            + (f'&pull={fight_id}' if fight_id else ''))


def _parse_color(value):
    return next(c for t, c in PARSE_STEPS if value >= t)


def _date(ms, fmt='%d %b'):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(fmt).lstrip('0')


def _avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _night_point(night, name):
    """One raid night as a chart point: pull-weighted score, average of the bosses' best parses, mistakes per pull."""
    entries = night['entries']
    pulls = sum(e['pulls'] for e in entries) or 1
    main = max(entries, key=lambda e: (e['difficulty'], e['pulls']))  # the night's main boss: its page opens
    bosses = ', '.join(f"{e['boss']}{' ✔' if e['kills'] else ''}" for e in entries)
    return {'date': night['date'], 'score': sum(e['score'] * e['pulls'] for e in entries) / pulls,
            'parse': _avg([e['parse'] for e in entries]), 'deaths': sum(e['deaths'] for e in entries) / pulls,
            'avoidable': sum(e['avoidable'] for e in entries) / pulls, 'pulls': pulls,
            'href': player_href(night['code'], name, main['key']), 'title': night['title'], 'what': bosses}


def _entry_point(entry, name):
    pulls = entry['pulls'] or 1
    result = 'killed' if entry['kills'] else f"best pull {entry['best_pct']:.1f}%"
    return {'date': entry['date'], 'score': entry['score'], 'parse': entry['parse'],
            'deaths': entry['deaths'] / pulls, 'avoidable': entry['avoidable'] / pulls, 'pulls': entry['pulls'],
            'href': player_href(entry['code'], name, entry['key']), 'title': entry['title'],
            'what': f"{entry['pulls']} pull{'s' if entry['pulls'] != 1 else ''}, {result}"}


# ============================================================================
# Charts
# ============================================================================

def _x_labels(points, x, y_text):
    step = max(1, -(-len(points) // 12))  # at most ~12 dates along the bottom
    shown = [i for i in range(len(points)) if i % step == 0]
    last = len(points) - 1
    if shown[-1] != last:  # the last night always - in place of the one before when they'd overlap
        if last - shown[-1] < max(2, step * 0.7) and len(shown) > 1:
            shown[-1] = last
        else:
            shown.append(last)
    return ''.join(f'<text x="{x(i):.1f}" y="{y_text}" text-anchor="middle">{_date(points[i]["date"])}</text>'
                   for i in shown)


def _segments(points, key, x, y):
    """Polyline(s) through a series, broken where a night has no value."""
    out, run = [], []
    for i, p in enumerate(points):
        if p[key] is None:
            if len(run) > 1:
                out.append(run)
            run = []
        else:
            run.append(f'{x(i):.1f},{y(p[key]):.1f}')
    if len(run) > 1:
        out.append(run)
    return out


def trend_chart(points, first_kills=()):
    """
    Score (blue) and parse (WCL colours on an orange line) per night, 0-100; a gold ★ over nights with a
    first kill. points: _night_point / _entry_point dicts in night order. Every night is a link to its page.
    """
    if not points:
        return ''
    width, height, left, right, top, bottom = 900, 250, 34, 14, 26, 26
    inner_w, inner_h = width - left - right, height - top - bottom
    n = len(points)

    def x(i):
        return left + (inner_w / 2 if n == 1 else i * inner_w / (n - 1))

    def y(v):
        return top + inner_h * (1 - max(0.0, min(100.0, v)) / 100)

    parts = [f'<svg class="chart ch-chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Execution score and parse per raid night">']
    for v in (0, 25, 50, 75, 100):
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text class="axis-label" x="{left - 8}" y="{y(v) + 4:.1f}" text-anchor="end">{v}</text>')
    kills = dict(first_kills)
    for i, p in enumerate(points):
        if p['date'] in kills:
            parts.append(f'<line class="ch-kill-line" x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{top}" y2="{top + inner_h}"/>'
                         f'<text class="ch-star" x="{x(i):.1f}" y="{top - 8}" text-anchor="middle">★'
                         f'<title>First kill: {esc(kills[p["date"]])}</title></text>')
    for key, color, dash in (('parse', PARSE_COLOR, ' stroke-dasharray="5 4"'), ('score', SCORE_COLOR, '')):
        for run in _segments(points, key, x, y):
            parts.append(f'<polyline points="{" ".join(run)}" fill="none" stroke="{color}" stroke-width="2.5" '
                         f'stroke-linejoin="round" stroke-linecap="round" opacity="0.9"{dash}/>')
    for i, p in enumerate(points):
        tip = [f"{_date(p['date'], '%d %b %Y')} - {p['title']}", p['what'], f"Score {p['score']:.0f}"]
        if p['parse'] is not None:
            tip.append(f"Parse {p['parse']:.0f}")
        dots = f'<rect class="ch-hit" x="{x(i) - 9:.1f}" y="{top}" width="18" height="{inner_h}"/>'
        dots += (f'<circle class="mark" cx="{x(i):.1f}" cy="{y(p["score"]):.1f}" r="5" '
                 f'fill="{BAND_COLORS[_band(round(p["score"]))[0]]}" stroke="{SCORE_COLOR}" stroke-width="2"/>')
        if p['parse'] is not None:
            dots += (f'<rect class="mark" x="{x(i) - 4.5:.1f}" y="{y(p["parse"]) - 4.5:.1f}" width="9" height="9" '
                     f'transform="rotate(45 {x(i):.1f} {y(p["parse"]):.1f})" fill="{_parse_color(p["parse"])}"/>')
        parts.append(f'<a href="{esc(p["href"])}"><title>{esc(chr(10).join(tip))}</title>{dots}</a>')
    parts.append(_x_labels(points, x, height - 6))
    parts.append('</svg>')
    return ''.join(parts)


def mistakes_chart(points):
    """Early deaths (red) and avoidable hits (yellow) per pull, night by night - lower is better."""
    if not points:
        return ''
    width, height, left, right, top, bottom = 900, 150, 34, 14, 12, 24
    inner_w, inner_h = width - left - right, height - top - bottom
    n = len(points)
    peak = max([p['deaths'] for p in points] + [p['avoidable'] for p in points] + [0.5])
    slot = inner_w / n
    bar = max(2.0, min(14.0, slot * 0.32))

    def y(v):
        return top + inner_h * (1 - v / peak)

    parts = [f'<svg class="chart ch-chart small" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Early deaths and avoidable hits per pull, per raid night">',
             f'<line class="grid" x1="{left}" x2="{width - right}" y1="{top + inner_h}" y2="{top + inner_h}"/>',
             f'<line class="grid" x1="{left}" x2="{width - right}" y1="{top:.1f}" y2="{top:.1f}"/>',
             f'<text class="axis-label" x="{left - 8}" y="{top + 4:.1f}" text-anchor="end">{peak:.1f}</text>',
             f'<text class="axis-label" x="{left - 8}" y="{top + inner_h + 4:.1f}" text-anchor="end">0</text>']
    for i, p in enumerate(points):
        cx = left + slot * (i + 0.5)
        tip = (f"{_date(p['date'], '%d %b %Y')}: {p['deaths']:.2f} early deaths and {p['avoidable']:.2f} avoidable "
               f"hits per pull ({p['pulls']} pull{'s' if p['pulls'] != 1 else ''})")
        bars = ''
        for k, (key, color) in enumerate((('deaths', DEATH_COLOR), ('avoidable', AVOID_COLOR))):
            h = inner_h * p[key] / peak
            bars += (f'<rect x="{cx - bar - 1 + k * (bar + 2):.1f}" y="{top + inner_h - h:.1f}" width="{bar:.1f}" '
                     f'height="{max(h, 0):.1f}" rx="2" fill="{color}"/>')
        parts.append(f'<a href="{esc(p["href"])}"><title>{esc(tip)}</title>'
                     f'<rect class="ch-hit" x="{cx - slot / 2:.1f}" y="{top}" width="{slot:.1f}" height="{inner_h}"/>{bars}</a>')
    parts.append(_x_labels(points, lambda i: left + slot * (i + 0.5), height - 5))
    parts.append('</svg>')
    return ''.join(parts)


def _lately(points, key, label, higher_better=True):
    """'Score lately 78 ▲ +6' - the last RECENT_NIGHTS against the ones before."""
    values = [p[key] for p in points if p[key] is not None]
    if not values:
        return ''
    recent = sum(values[-RECENT_NIGHTS:]) / len(values[-RECENT_NIGHTS:])
    before = values[:-RECENT_NIGHTS][-RECENT_NIGHTS:]
    change = ''
    if before:
        delta = recent - sum(before) / len(before)
        good = delta >= 0 if higher_better else delta <= 0
        arrow = '▲' if delta > 0 else '▼' if delta < 0 else '■'
        fmt = f'{abs(delta):.0f}' if key in ('score', 'parse') else f'{abs(delta):.2f}'
        change = (f' <span class="ch-delta {"good" if good else "bad"}" title="Against the {len(before)} night'
                  f'{"s" if len(before) != 1 else ""} before">{arrow} {fmt}</span>')
    fmt = f'{recent:.0f}' if key in ('score', 'parse') else f'{recent:.2f}'
    return f'<div class="ch-lately"><span>{label}</span><b>{fmt}</b>{change}</div>'


# ============================================================================
# The page
# ============================================================================

def _scope(prof):
    """'Liberation of Undermine · Mythic' - what the numbers below the filters cover."""
    from ..character import ALL
    tier = 'All tiers' if prof['tier'] == ALL else next(
        (t['zone_name'] for t in prof['tiers'] if t['zone_id'] == prof['tier']), '')
    diff = 'all difficulties' if prof['difficulty'] == ALL else DIFFICULTY_NAMES.get(prof['difficulty'], '')
    return f'{tier} · {diff}'


def hero(prof, data, back_href, with_model=True):
    """
    Name, class / spec / realm, the pin button, key numbers (of the chosen tier and difficulty) and links -
    and their render, unless the gear panel right under it shows it.
    """
    color = CLASS_COLORS.get(prof['class'], '#9aa1b9')
    info = armory.summary(data) if data else {}
    render = armory.render_url(data) if data else None
    t = prof['totals']
    model = (f'<img class="ch-render" src="{esc(render)}" alt="" loading="lazy">' if render else
             f'<div class="ch-initial">{esc(prof["name"][:1])}</div>')
    who = ' · '.join(esc(x) for x in (f"{ROLE_ICONS.get(prof['role'], '')} {prof['spec']}".strip(),
                                      _class_label(prof['class']), prof['realm'] and _realm_label(prof['realm'])) if x)
    guild = f'<span class="ch-guild">&lt;{esc(info["guild"])}&gt;</span>' if info.get('guild') else ''
    tiles = [(f'{t["nights"]}', 'Raid nights'), (f'{t["pulls"]}', 'Pulls'),
             (f'{t["bosses_killed"]}', 'Bosses killed'),
             (f'<span class="score-badge {_band(t["score"])[0]}">{t["score"]}</span>', 'Avg score'),
             (parse_html(t['avg_parse']), 'Avg parse'), (parse_html(t['best_parse']), 'Best parse')]
    if info.get('ilvl') and with_model:
        tiles.append((f'{float(info["ilvl"]):.0f}', 'Item level'))
    tiles_html = ''.join(f'<div class="ch-tile"><b>{v}</b><span>{label}</span></div>' for v, label in tiles)
    pin = json.dumps({'name': prof['name'], 'realm': armory.realm_slug(prof['realm']) if prof['realm'] else '',
                      'cls': prof['class'], 'spec': prof['spec']})
    slug = armory.realm_slug(prof['realm']) if prof['realm'] else ''
    links = [f'<a class="btn btn-primary btn-sm" href="{esc(back_href)}">Latest night →</a>']
    if slug:
        links.append(f'<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener" href="https://www.warcraftlogs.com'
                     f'/character/{armory.REGION}/{esc(slug)}/{esc(prof["name"].lower())}">Warcraft Logs ↗</a>')
        links.append(f'<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener" href="https://raider.io/characters/'
                     f'{armory.REGION}/{esc(slug)}/{esc(prof["name"])}">Raider.IO ↗</a>')
    return f"""
    <div class="card ch-hero{'' if with_model else ' no-model'}" style="--c:{color}">
        {f'<div class="ch-model">{model}</div>' if with_model else ''}
        <div class="ch-main">
            <div class="ch-top">
                <div><h1 class="ch-name" style="color:{color}">{esc(prof['name'])}</h1>
                    <p class="ch-who">{who} {guild}</p></div>
                <button type="button" class="btn btn-secondary btn-sm pin-btn" data-pin="{esc(pin)}"
                        title="Pin to the front page - kept in this browser only">📌 Pin</button>
            </div>
            <div class="ch-scope">📊 {esc(_scope(prof))}</div>
            <div class="ch-tiles">{tiles_html}</div>
            <div class="ch-links">{''.join(links)}</div>
        </div>
    </div>"""


def _realm_label(realm):
    """'TarrenMill' -> 'Tarren Mill'."""
    return armory.realm_slug(realm).replace('-', ' ').title()


def improvement(prof):
    """The charts card: all bosses together, or one boss at a time (chips)."""
    name = prof['name']
    first_kills = {}
    for b in prof['bosses']:
        if b['first_kill']:
            first_kills.setdefault(b['first_kill'], []).append(f"{b['name']} ({DIFFICULTY_NAMES.get(b['difficulty'], '')})")
    views = [('all', 'All bosses', '', [_night_point(n, name) for n in prof['nights']],
              {d: ', '.join(v) for d, v in first_kills.items()})]
    for b in prof['bosses']:
        if len(b['nights']) < 2:
            continue
        kill = {b['first_kill']: b['name']} if b['first_kill'] else {}
        views.append((f"{b['key'][0]}-{b['key'][1]}", b['name'], boss_portrait(b['key'][0]),
                      [_entry_point(e, name) for e in b['nights']], kill))
    chips, panes = [], []
    for i, (key, label, portrait, points, kills) in enumerate(views):
        diff = '' if key == 'all' else f' <small>{esc(DIFFICULTY_NAMES.get(int(key.split("-")[1]), ""))}</small>'
        chips.append(f'<button type="button" class="ch-chip" data-view="{key}" aria-pressed="{"true" if not i else "false"}">'
                     f'{portrait}{esc(label)}{diff}</button>')
        lately = (_lately(points, 'score', 'Score lately') + _lately(points, 'parse', 'Parse lately')
                  + _lately(points, 'deaths', 'Early deaths / pull', higher_better=False))
        panes.append(f"""
            <div class="ch-pane" data-pane="{key}"{'' if not i else ' hidden'}>
                <div class="ch-latelies">{lately}</div>
                {trend_chart(points, kills.items())}
                <h3 class="sub-title">Mistakes per pull <span class="muted small">- lower is better</span></h3>
                {mistakes_chart(points)}
            </div>""")
    legend = (f'<div class="ch-legend"><span><i style="background:{SCORE_COLOR}"></i>Execution score (ours, 0-100)</span>'
              f'<span><i class="dashed" style="border-color:{PARSE_COLOR}"></i>WCL parse (best per boss)</span>'
              f'<span><b class="ch-star">★</b>First kill</span>'
              f'<span><i style="background:{DEATH_COLOR}"></i>Early deaths</span>'
              f'<span><i style="background:{AVOID_COLOR}"></i>Avoidable hits</span></div>')
    sub = ('Night by night - hover a night for the details, click it to open their page for it. "Lately" is the '
           f'last {RECENT_NIGHTS} nights against the {RECENT_NIGHTS} before.')
    return f"""
    <div class="card" data-ch-views>
        {section_head('📈', 'Improvement', sub)}
        <div class="ch-chips">{''.join(chips)}</div>
        {legend}
        {''.join(panes)}
    </div>"""


def bosses(prof):
    """Progression per boss: kills or best pull, best parse, score and parse trends; a row opens the boss trend."""
    name = prof['name']
    rows = []
    for b in prof['bosses']:
        enc, diff = b['key']
        scores = [e['score'] for e in b['nights']]
        parses = [e['parse'] for e in b['nights']]
        if b['kills']:
            status = (f'<span class="pill pill-kill">✔ {b["kills"]} kill{"s" if b["kills"] != 1 else ""}</span>'
                      f'<span class="muted small"> first {_date(b["first_kill"], "%d %b %Y")}</span>')
        else:
            status = (f'<div class="ch-prog" title="Best pull: {b["best_pct"]:.1f}% left">'
                      f'<i style="width:{100 - b["best_pct"]:.0f}%"></i><span>{b["best_pct"]:.1f}%</span></div>')
        change = ''
        if len(scores) >= 2:
            delta = scores[-1] - scores[0]
            change = (f'<span class="ch-delta {"good" if delta >= 0 else "bad"}" title="First night {scores[0]} → '
                      f'latest {scores[-1]}">{"▲" if delta > 0 else "▼" if delta < 0 else "■"} {abs(delta):.0f}</span>')
        last = b['nights'][-1]
        trend = f'/admin/raids/boss/{enc}/{diff}/player/{quote(name)}'
        rows.append(f"""
            <tr data-href="{trend}">
                <td><div class="ch-bosscell"><a href="{trend}" class="ch-boss">{boss_portrait(enc, 'sm', killed=bool(b['kills']))}
                    <strong>{esc(b['name'])}</strong></a>{difficulty_pill(diff)}</div></td>
                <td>{status}</td>
                <td class="num">{b['pulls']}<span class="muted small"> / {len(b['nights'])}n</span></td>
                <td class="num">{parse_html(b['best_parse'])}</td>
                <td><span class="score-badge {_band(last['score'])[0]}">{last['score']}</span> {change}</td>
                <td class="ch-sparks">{sparkline(scores) or '<span class="muted small">one night</span>'}
                    {_parse_spark(parses)}</td>
                <td><a class="small" href="{player_href(last['code'], name, b['key'])}">Latest night →</a></td>
            </tr>""")
    sub = ('Hardest difficulty first. A row opens their trend on that boss, night by night; the score is the latest '
           "night's. Blue line: score per night, orange: parse.")
    return f"""
    <div class="card">
        {section_head('🐉', 'Bosses', sub)}
        <div class="table-wrapper"><table class="compact ch-table">
            <tr><th>Boss</th><th>Progress</th><th class="num">Pulls</th><th class="num">Best parse</th>
                <th>Score</th><th>Trend</th><th></th></tr>
            {''.join(rows)}
        </table></div>
    </div>"""


def _parse_spark(parses):
    spark = sparkline(parses)
    return spark.replace('#7484ec', PARSE_COLOR) if spark else ''


def highlights(prof):
    items = ''.join(f'<div class="ch-hl {esc(h["tone"])}"><span class="ch-hl-icon">{h["icon"]}</span>'
                    f'<div><b>{esc(h["title"])}</b><p>{esc(h["text"])}</p></div></div>' for h in prof['highlights'])
    if not items:
        return ''
    return f'<div class="card">{section_head("🏅", "Highlights")}<div class="ch-hls">{items}</div></div>'


def logs(prof):
    """Every raid log they were in, newest first - each boss a link to their page for it that night."""
    name = prof['name']
    rows = []
    for i, night in enumerate(reversed(prof['nights'])):
        point = _night_point(night, name)
        chips = ''.join(_boss_chip(e, name) for e in night['entries'])
        kills = sum(e['kills'] for e in night['entries'])
        zone = night['zone'] or ''
        diffs = ' '.join(difficulty_pill(d) for d in sorted({e['difficulty'] for e in night['entries']}, reverse=True))
        rows.append(f"""
            <tr data-href="{esc(point['href'])}"{' class="ch-extra"' if i >= LOGS_SHOWN else ''}>
                <td class="nowrap">{_date(night['date'], '%d %b %Y')}</td>
                <td><a href="/admin/raids/report/{quote(night['code'])}"><strong>{esc(night['title'])}</strong></a>
                    <br><span class="muted small">{esc(zone)}</span> {diffs}</td>
                <td><div class="ch-bchips">{chips}</div></td>
                <td class="num">{point['pulls']}</td>
                <td class="num">{kills or '<span class="muted">0</span>'}</td>
                <td><span class="score-badge {_band(round(point['score']))[0]}">{round(point['score'])}</span></td>
                <td class="num">{parse_html(point['parse'])}</td>
                <td class="num">{_per_pull(point['deaths'])}</td>
                <td class="num">{_per_pull(point['avoidable'])}</td>
            </tr>""")
    more = (f'<button type="button" class="dt-toggle ch-more"><span class="l-more">Show all {len(rows)} logs</span>'
            f'<span class="l-less">Show the latest {LOGS_SHOWN}</span></button>' if len(rows) > LOGS_SHOWN else '')
    sub = ('Every log of ours they were in, newest first. A row opens their page for the night\'s main boss; a boss '
           'portrait opens that boss. Score and parse: the night\'s average; deaths and avoidable hits: per pull.')
    return f"""
    <div class="card">
        {section_head('📜', f'Raid logs <span class="muted small">({len(rows)})</span>', sub)}
        <div class="ch-logs dt-rows"><div class="table-wrapper"><table class="compact ch-table">
            <tr><th>Date</th><th>Log</th><th>Bosses</th><th class="num">Pulls</th><th class="num">Kills</th>
                <th>Score</th><th class="num">Parse</th><th class="num" title="Early deaths per pull">Deaths</th>
                <th class="num" title="Avoidable hits per pull">Avoidable</th></tr>
            {''.join(rows)}
        </table></div>{more}</div>
    </div>"""


def _boss_chip(entry, name):
    """A boss's portrait in the logs list (dim until killed), linking to their page for it that night."""
    result = 'killed' if entry['kills'] else f"best pull {entry['best_pct']:.1f}%"
    tip = (f"{entry['boss']} ({DIFFICULTY_NAMES.get(entry['difficulty'], '')}) - {entry['pulls']} "
           f"pull{'s' if entry['pulls'] != 1 else ''}, {result} · score {entry['score']}")
    return (f'<a class="ch-bchip{" kill" if entry["kills"] else ""}" href="{player_href(entry["code"], name, entry["key"])}" '
            f'title="{esc(tip)}">{boss_portrait(entry["key"][0], killed=bool(entry["kills"]))}</a>')


def _per_pull(value):
    return '<span class="muted">0</span>' if not value else f'{value:.2f}'


def filter_href(prof, tier, difficulty):
    """This page for another raid tier / difficulty (their defaults left out of the address)."""
    query = []
    if tier is not None:
        query.append(f'tier={tier}')
    if difficulty is not None:
        query.append(f'difficulty={difficulty}')
    return url(prof['name'], prof['realm']) + ('?' + '&'.join(query) if query else '')


def filters(prof):
    """Raid tier and difficulty chips: everything under them follows (the gear doesn't - it's what they wear now)."""
    from ..character import ALL
    if not prof['tiers']:
        return ''
    tier_chips = [f'<a class="ch-chip" data-swap="page" aria-pressed="{"true" if t["zone_id"] == prof["tier"] else "false"}" '
                  f'href="{esc(filter_href(prof, t["zone_id"], None))}">{esc(t["zone_name"])} '
                  f'<small>{t["nights"]} night{"s" if t["nights"] != 1 else ""}</small></a>' for t in prof['tiers']]
    if len(prof['tiers']) > 1:
        tier_chips.append(f'<a class="ch-chip" data-swap="page" aria-pressed="{"true" if prof["tier"] == ALL else "false"}" '
                          f'href="{esc(filter_href(prof, ALL, None))}">All tiers</a>')
    tier_q = None if prof['tier'] == (prof['tiers'][0]['zone_id']) else prof['tier']
    diff_chips = [f'<a class="ch-chip" data-swap="page" aria-pressed="{"true" if d == prof["difficulty"] else "false"}" '
                  f'href="{esc(filter_href(prof, tier_q, d))}">{esc(DIFFICULTY_NAMES.get(d, str(d)))} '
                  f'<small>{n} pull{"s" if n != 1 else ""}</small></a>' for d, n in prof['difficulties']]
    if len(prof['difficulties']) > 1:
        diff_chips.append(f'<a class="ch-chip" data-swap="page" aria-pressed="{"true" if prof["difficulty"] == ALL else "false"}" '
                          f'href="{esc(filter_href(prof, tier_q, ALL))}">All difficulties</a>')
    return (f'<div class="night-bar ch-filters"><span class="ch-flabel">Raid tier</span><div class="ch-chips">{"".join(tier_chips)}</div>'
            f'<span class="ch-flabel">Difficulty</span><div class="ch-chips">{"".join(diff_chips)}</div></div>')


def page(prof, data, armory_html):
    latest = prof['nights'][-1]
    main = max(latest['entries'], key=lambda e: (e['difficulty'], e['pulls']))
    return (hero(prof, data, player_href(latest['code'], prof['name'], main['key']), with_model=not data)
            + armory_html + filters(prof)
            + highlights(prof) + improvement(prof) + bosses(prof) + logs(prof))


def picker(name, realms):
    """Several characters of the name on different realms: which one?"""
    links = ''.join(f'<a class="ch-pick" href="{url(name, r["realm"])}"><b>{esc(name)}</b>'
                    f'<span>{esc(_realm_label(r["realm"]))}</span><small>{r["nights"]} night'
                    f'{"s" if r["nights"] != 1 else ""}</small></a>' for r in realms)
    return (f'<div class="card">{section_head("🔎", f"Which {esc(name)}?", "There are characters of that name on more than one realm in our logs.")}'
            f'<div class="ch-picks">{links}</div></div>')
