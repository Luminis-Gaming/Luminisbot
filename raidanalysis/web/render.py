"""HTML building blocks for the raid analysis pages (charts, tables, formatting)."""
import html

DIFFICULTY_NAMES = {1: 'LFR', 3: 'Normal', 4: 'Heroic', 5: 'Mythic'}

CLASS_COLORS = {
    'DeathKnight': '#C41E3A', 'DemonHunter': '#A330C9', 'Druid': '#FF7C0A', 'Evoker': '#33937F',
    'Hunter': '#AAD372', 'Mage': '#3FC7EB', 'Monk': '#00FF98', 'Paladin': '#F48CBA',
    'Priest': '#FFFFFF', 'Rogue': '#FFF468', 'Shaman': '#0070DD', 'Warlock': '#8788EE',
    'Warrior': '#C69B6D',
}
ROLE_ICONS = {'tank': '🛡️', 'healer': '💚', 'dps': '⚔️'}

# Chart series colors - validated (dataviz validate_palette.js, dark mode) on the card surface.
SERIES_PULL = '#7484ec'
SERIES_BEST = '#cc7f3c'
STATUS_GOOD = '#51cf66'

ICON_BASE = 'https://assets.rpglogs.com/img/warcraft/abilities/'

PAGE_CSS = """
a { color: #8b9cff; }
.muted { color: rgba(255,255,255,0.6); }
.ability-cell { white-space: nowrap; }
.small { font-size: 13px; }
.pill { padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.pill-kill { background: rgba(81,207,102,0.2); color: #51cf66; }
.pill-wipe { background: rgba(255,255,255,0.12); }
.pill-diff { background: rgba(88,101,242,0.35); }
.pill-avoidable { background: rgba(255,107,107,0.2); color: #ff8787; }
.pill-ignore { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.5); }
.pill-suggest { background: rgba(255,193,7,0.15); color: #ffd43b; }
.ability-icon { width: 20px; height: 20px; border-radius: 4px; vertical-align: middle; margin-right: 6px; }
.boss-section { border-top: 1px solid rgba(255,255,255,0.12); padding-top: 24px; margin-top: 24px; }
.boss-section:first-of-type { border-top: none; margin-top: 0; padding-top: 0; }
.chart { width: 100%; height: auto; display: block; margin: 10px 0 20px; }
.chart text { fill: rgba(255,255,255,0.65); font-size: 11px; font-family: inherit; }
.chart .grid { stroke: rgba(255,255,255,0.08); }
.chart .axis-label { fill: rgba(255,255,255,0.5); }
.chart a:hover circle.mark { stroke: #fff; stroke-width: 2; }
.legend { display: flex; gap: 18px; font-size: 13px; color: rgba(255,255,255,0.75); flex-wrap: wrap; }
.legend span::before { content: ''; display: inline-block; width: 14px; height: 3px; border-radius: 2px;
    background: var(--c); vertical-align: middle; margin-right: 6px; }
.grid-2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr)); gap: 20px; }
.grid-2 > * { min-width: 0; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
td.bad { color: #ff8787; font-weight: 600; }
td.good { color: #51cf66; }
th[data-sort] { cursor: pointer; user-select: none; }
th[data-sort]:hover { background: rgba(88,101,242,0.5); }
table.compact th, table.compact td { padding: 8px 10px; }
.tag-form { display: inline-flex; gap: 4px; }
.tag-form button { padding: 4px 10px; font-size: 12px; border-radius: 6px; border: none; cursor: pointer;
    background: rgba(255,255,255,0.1); color: #fff; white-space: nowrap; }
.tag-form button.on-avoidable, .tag-form button.on-avoidable_nontank { background: #c92a2a; }
.tag-form button.on-ignore { background: rgba(255,255,255,0.35); }
.inline-form { display: inline-flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.inline-form input[type=text], .inline-form input[type=number] { width: auto; margin: 0; padding: 8px 12px; font-size: 14px; }
.clip-btn { margin-left: 6px; padding: 1px 8px; font-size: 11px; border: none; border-radius: 10px;
    background: #c92a2a; color: #fff; cursor: pointer; vertical-align: middle; }
.clip-btn:hover { background: #e03131; }
.guide-info { margin-left: 4px; cursor: help; font-size: 13px; }
.clip-modal { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: flex; align-items: center;
    justify-content: center; z-index: 100; padding: 16px; }
.clip-modal[hidden] { display: none; }
.clip-box { background: #23263d; border-radius: 14px; padding: 18px; width: min(680px, 100%);
    max-height: 100%; overflow: auto; box-shadow: 0 12px 40px rgba(0,0,0,0.5); }
.clip-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.clip-head h3 { margin: 0; }
.clip-close { background: rgba(255,255,255,0.1); border: none; color: #fff; border-radius: 8px;
    padding: 6px 10px; cursor: pointer; }
.clip-box iframe { width: 100%; height: 620px; max-height: 70vh; border: 0; border-radius: 8px; background: #000; }
@media (max-width: 600px) { .grid-2 { grid-template-columns: 1fr; } body { padding: 10px; } .card { padding: 16px; } }
"""

# Sortable tables + local timestamps. Kept dependency-free.
PAGE_JS = """
document.querySelectorAll('[data-ts]').forEach(el => {
  const d = new Date(+el.dataset.ts);
  el.textContent = el.dataset.fmt === 'time'
    ? d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
    : d.toLocaleDateString([], {weekday: 'short', year: 'numeric', month: 'short', day: 'numeric'})
      + (el.dataset.fmt === 'date' ? '' : ' ' + d.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}));
});
document.querySelectorAll('th[data-sort]').forEach(th => th.addEventListener('click', () => {
  const table = th.closest('table'), idx = [...th.parentNode.children].indexOf(th);
  const rows = [...table.querySelectorAll('tr')].filter(r => r.querySelector('td'));
  const asc = th.dataset.dir !== 'asc'; th.dataset.dir = asc ? 'asc' : 'desc';
  const val = r => { const c = r.children[idx]; const v = c.dataset.v ?? c.textContent.trim();
                     return isNaN(+v) || v === '' ? v.toLowerCase() : +v; };
  rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * (asc ? 1 : -1));
  rows.forEach(r => r.parentNode.appendChild(r));
}));
// Mechanic clip pop-up: the Mythic Trap iframe only loads when someone opens it.
document.addEventListener('click', e => {
  const btn = e.target.closest('.clip-btn');
  const modal = document.getElementById('clip-modal');
  if (btn) {
    e.preventDefault(); e.stopPropagation();
    modal.querySelector('h3').textContent = btn.dataset.title;
    modal.querySelector('.clip-tip').textContent = btn.dataset.tip || '';
    modal.querySelector('iframe').src = btn.dataset.embed;
    modal.querySelector('.clip-link').href = btn.dataset.embed.replace('/embed-ability/', '/').replace(/\\/[^/]+$/, '');
    modal.hidden = false;
  } else if (modal && !modal.hidden && (e.target === modal || e.target.closest('.clip-close'))) {
    modal.hidden = true; modal.querySelector('iframe').src = 'about:blank';
  }
});
document.addEventListener('keydown', e => {
  const modal = document.getElementById('clip-modal');
  if (e.key === 'Escape' && modal && !modal.hidden) { modal.hidden = true; modal.querySelector('iframe').src = 'about:blank'; }
});
"""

CLIP_MODAL = """
<div id="clip-modal" class="clip-modal" hidden>
  <div class="clip-box" role="dialog" aria-modal="true">
    <div class="clip-head"><h3></h3><button class="clip-close" aria-label="Close">✕</button></div>
    <p class="clip-tip muted small"></p>
    <iframe title="Mechanic clip" loading="lazy" allow="autoplay; fullscreen"></iframe>
    <p class="muted small">Clip by <a class="clip-link" target="_blank" rel="noopener">Mythic Trap ↗</a></p>
  </div>
</div>
"""


def esc(value):
    return html.escape(str(value if value is not None else ''))


def fmt_duration(ms):
    seconds = int((ms or 0) / 1000)
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
    return f"{seconds // 60}:{seconds % 60:02d}"


def fmt_amount(n):
    n = n or 0
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(int(n))


def ts(epoch_ms, fmt='datetime'):
    """Rendered client-side in the viewer's timezone (see PAGE_JS)."""
    return f'<span data-ts="{int(epoch_ms)}" data-fmt="{fmt}"></span>'


def difficulty_pill(difficulty):
    return f'<span class="pill pill-diff">{esc(DIFFICULTY_NAMES.get(difficulty, difficulty))}</span>'


def player_name(name, cls='', role=None):
    color = CLASS_COLORS.get(cls, '#ddd')
    icon = f'{ROLE_ICONS.get(role, "")} ' if role else ''
    return f'{icon}<span style="color:{color};font-weight:600">{esc(name)}</span>'


def ability(name, icon=None, ability_id=None, guide=None):
    img = f'<img class="ability-icon" src="{ICON_BASE}{esc(icon)}" alt="" loading="lazy">' if icon else ''
    label = esc(name)
    if ability_id and ability_id > 1:
        label = (f'<a href="https://www.wowhead.com/spell={int(ability_id)}" target="_blank" '
                 f'style="color:inherit">{label}</a>')
    return f'<span class="ability-cell">{img}{label}{guide_button(guide, name)}</span>'


def guide_button(guide, name=''):
    """▶ opens the Mythic Trap clip; abilities without a clip get their tip as a hover ℹ️."""
    if not guide:
        return ''
    tip = guide.get('tip') or guide.get('description') or ''
    if guide.get('video_url'):
        return (f' <button class="clip-btn" data-embed="{esc(guide["embed_url"])}" '
                f'data-title="{esc(guide["name"] or name)}" data-tip="{esc(tip)}" '
                f'title="Watch how {esc(guide["name"] or name)} works">▶</button>')
    if tip:
        return f' <span class="guide-info" title="{esc(tip)}">ℹ️</span>'
    return ''


def tag_pill(tag, source=None):
    """source 'auto' = from the boss's Mythic Trap guide; 'manual' = set by an officer."""
    auto = ' <small style="opacity:.7">auto</small>' if source == 'auto' else ''
    why = ' (from the Mythic Trap guide)' if source == 'auto' else ' (set by an officer)'
    if tag == 'avoidable':
        return f'<span class="pill pill-avoidable" title="Every hit is a mistake{why}">avoidable{auto}</span>'
    if tag == 'avoidable_nontank':
        return (f'<span class="pill pill-avoidable" title="Avoidable for everyone except tanks{why}">'
                f'avoidable (non-tanks){auto}</span>')
    if tag == 'expected':
        return (f'<span class="pill pill-ignore" title="Part of the mechanic - soak, tankbuster or raid damage{why}">'
                f'expected{auto}</span>')
    if tag == 'ignore':
        return '<span class="pill pill-ignore">ignored</span>'
    return ''


def phase_label(pull, phase_names):
    phase = pull.get('last_phase')
    if not phase:
        return ''
    info = (phase_names or {}).get(str(pull['encounter_id']), {}).get(str(phase))
    if info:
        return esc(info['name'])
    return f"{'Intermission' if pull.get('last_phase_intermission') else 'Phase'} {phase}"


def result_pill(pull):
    if pull['kill']:
        return '<span class="pill pill-kill">✔ Kill</span>'
    return f'<span class="pill pill-wipe">{pull["fight_pct"] or 0:.1f}%</span>'


# ============================================================================
# Charts
# ============================================================================

def progress_chart(points, separators=()):
    """
    Boss % remaining per pull (0 = kill) with a best-so-far step line.

    points: [{'pct', 'kill', 'tip', 'href'}] in pull order.
    separators: [(index, label)] - vertical dividers (e.g. between raid nights).
    """
    if len(points) < 2:
        return ''  # a single pull says nothing a chart can show better than the table
    width, height = 900, 240
    left, right, top, bottom = 44, 16, 22, 26
    inner_w, inner_h = width - left - right, height - top - bottom
    n = len(points)

    def x(i):
        return left + (inner_w / 2 if n == 1 else i * inner_w / (n - 1))

    def y(pct):
        return top + inner_h * (1 - max(0.0, min(100.0, pct)) / 100)

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Boss health remaining per pull">']
    for pct in (0, 25, 50, 75, 100):
        parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(pct):.1f}" y2="{y(pct):.1f}"/>'
                     f'<text x="{left - 8}" y="{y(pct) + 4:.1f}" text-anchor="end">{pct}%</text>')
    for index, label in separators:
        sx = (x(index - 1) + x(index)) / 2 if index > 0 else x(0)
        parts.append(f'<line class="grid" x1="{sx:.1f}" x2="{sx:.1f}" y1="{top}" y2="{top + inner_h}" '
                     f'stroke-dasharray="3 4"/>'
                     f'<text class="axis-label" x="{sx + 4:.1f}" y="{top - 8}">{esc(label)}</text>')

    pcts = [0.0 if p['kill'] else float(p['pct'] or 0) for p in points]
    line = ' '.join(f'{x(i):.1f},{y(v):.1f}' for i, v in enumerate(pcts))
    parts.append(f'<polyline points="{line}" fill="none" stroke="{SERIES_PULL}" stroke-width="2" '
                 f'stroke-linejoin="round" opacity="0.55"/>')
    best, step = 100.0, []
    for i, v in enumerate(pcts):
        if i:
            step.append(f'{x(i):.1f},{y(best):.1f}')
        best = min(best, v)
        step.append(f'{x(i):.1f},{y(best):.1f}')
    parts.append(f'<polyline points="{" ".join(step)}" fill="none" stroke="{SERIES_BEST}" '
                 f'stroke-width="2" stroke-linejoin="round"/>')

    for i, (point, v) in enumerate(zip(points, pcts)):
        color = STATUS_GOOD if point['kill'] else SERIES_PULL
        mark = (f'<circle class="mark" cx="{x(i):.1f}" cy="{y(v):.1f}" r="5" fill="{color}" '
                f'stroke="#23263d" stroke-width="2"/>'
                f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="12" fill="transparent"/>'
                f'<title>{esc(point["tip"])}</title>')
        if point['kill']:
            mark += f'<text x="{x(i):.1f}" y="{y(v) - 10:.1f}" text-anchor="middle" fill="{STATUS_GOOD}">Kill</text>'
        if point.get('href'):
            mark = f'<a href="{esc(point["href"])}">{mark}</a>'
        parts.append(mark)
        if n <= 40 or i % max(1, n // 20) == 0:
            parts.append(f'<text x="{x(i):.1f}" y="{height - 8}" text-anchor="middle">{i + 1}</text>')
    parts.append('</svg>')

    legend = (f'<div class="legend" title="WCL fight %: how much of the encounter was left, accounting for '
              f'phases (0% = kill)"><span style="--c:{SERIES_PULL}">Fight % remaining (each pull)</span>'
              f'<span style="--c:{SERIES_BEST}">Best so far</span></div>')
    return legend + ''.join(parts)


def pull_timeline(pull, analysis, phase_names):
    """One pull on a time axis: phase bands, death ticks and the wipe moment."""
    duration = max(1, pull['end_ms'] - pull['start_ms'])
    width, height, left, right = 900, 74, 10, 10
    inner_w = width - left - right

    def x(t):
        return left + inner_w * max(0, min(t, duration)) / duration

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Pull timeline">']
    phases = pull.get('phases') or []
    names = (phase_names or {}).get(str(pull['encounter_id']), {})
    for i, phase in enumerate(phases):
        end = phases[i + 1]['start'] if i + 1 < len(phases) else duration
        shade = 0.10 if i % 2 == 0 else 0.05
        label = (names.get(str(phase['id'])) or {}).get('name') or f"Phase {phase['id']}"
        band = max(1, x(end) - x(phase['start']))
        fits = int((band - 12) / 6.2)  # ~6.2px per char at 11px
        short = label if len(label) <= fits else (label[:fits - 1] + '…' if fits >= 6 else '')
        parts.append(f'<rect x="{x(phase["start"]):.1f}" y="4" width="{band:.1f}" '
                     f'height="26" fill="rgba(255,255,255,{shade})"><title>{esc(label)} '
                     f'({fmt_duration(phase["start"])}–{fmt_duration(end)})</title></rect>')
        if short:
            parts.append(f'<text x="{x(phase["start"]) + 6:.1f}" y="21">{esc(short)}</text>')
    if not phases:
        parts.append(f'<rect x="{left}" y="4" width="{inner_w}" height="26" fill="rgba(255,255,255,0.08)"/>')

    for death in analysis.get('deaths') or []:
        color = 'rgba(255,255,255,0.3)' if death.get('after_wipe') else '#ff6b6b'
        parts.append(f'<line x1="{x(death["t"]):.1f}" x2="{x(death["t"]):.1f}" y1="34" y2="52" '
                     f'stroke="{color}" stroke-width="2"><title>{fmt_duration(death["t"])} '
                     f'{esc(death["name"])} died to {esc(death["ability"])}</title></line>'
                     f'<line x1="{x(death["t"]):.1f}" x2="{x(death["t"]):.1f}" y1="30" y2="56" '
                     f'stroke="transparent" stroke-width="8"><title>{fmt_duration(death["t"])} '
                     f'{esc(death["name"])} died to {esc(death["ability"])}</title></line>')
    end_label = f'<text x="{width - right}" y="68" text-anchor="end">{fmt_duration(duration)}</text>'
    if analysis.get('wipe_at') is not None:
        wx = x(analysis['wipe_at'])
        wipe_text = f'wipe called {fmt_duration(analysis["wipe_at"])}'
        if wx > width - right - 150:  # too close to the end label - fold it in
            wipe_text += f' of {fmt_duration(duration)}'
            end_label = ''
        parts.append(f'<line x1="{wx:.1f}" x2="{wx:.1f}" y1="2" y2="58" stroke="#ffd43b" stroke-width="2" '
                     f'stroke-dasharray="4 3"/><text x="{min(wx, width - right):.1f}" y="68" text-anchor="end" '
                     f'fill="#ffd43b">{wipe_text}</text>')
    parts.append(f'<text x="{left}" y="68">0:00</text>{end_label}</svg>')
    return ''.join(parts)


# ============================================================================
# Tables
# ============================================================================

def scoreboard_table(rows, show_avoidable=True):
    if not rows:
        return '<p class="muted">No players.</p>'
    head = ('<tr><th data-sort>Player</th><th data-sort class="num">Pulls</th>'
            '<th data-sort class="num" title="Deaths before the wipe was called">Deaths</th>'
            '<th data-sort class="num" title="First player to die in a pull">First death</th>'
            '<th data-sort class="num" title="Share of pull time alive (until wipe called)">Alive %</th>')
    if show_avoidable:
        head += ('<th data-sort class="num" title="Hits from abilities tagged avoidable">Avoidable hits</th>'
                 '<th data-sort class="num">Avoidable dmg</th>')
    head += ('<th data-sort class="num">Interrupts</th><th data-sort class="num">Dispels</th>'
             '<th data-sort class="num" title="Pulls with at least one combat or mana potion used during the pull">'
            'Potion pulls</th>'
             '<th data-sort class="num" title="Healthstones + healing potions">Healthstones</th></tr>')
    body = []
    for r in rows:
        alive = 100 * r['alive_ms'] / r['pull_ms'] if r['pull_ms'] else 100
        potion_share = r['potion_pulls'] / r['pulls'] if r['pulls'] else 0
        cells = [f'<td data-v="{esc(r["name"])}">{player_name(r["name"], r["class"], r["role"])}</td>',
                 f'<td class="num">{r["pulls"]}</td>',
                 f'<td class="num{" bad" if r["deaths"] and r["deaths"] >= max(2, r["pulls"] / 2) else ""}">'
                 f'{r["deaths"]}</td>',
                 f'<td class="num{" bad" if r["first_deaths"] >= 2 else ""}">{r["first_deaths"]}</td>',
                 f'<td class="num" data-v="{alive:.1f}">{alive:.0f}%</td>']
        if show_avoidable:
            cells += [f'<td class="num{" bad" if r["avoidable_hits"] else ""}">{r["avoidable_hits"]}</td>',
                      f'<td class="num" data-v="{r["avoidable_damage"]}">{fmt_amount(r["avoidable_damage"])}</td>']
        cells += [f'<td class="num">{r["interrupts"] or ""}</td>',
                  f'<td class="num">{r["dispels"] or ""}</td>',
                  f'<td class="num{" bad" if potion_share < 0.5 else ""}" data-v="{r["potion_pulls"]}">'
                  f'{r["potion_pulls"]}/{r["pulls"]}</td>',
                  f'<td class="num">{r["defensives"] or ""}</td>']
        body.append(f'<tr>{"".join(cells)}</tr>')
    return f'<div class="table-wrapper"><table class="compact">{head}{"".join(body)}</table></div>'


def killers_table(rows, limit=8, guide_for=lambda ability_id, name: None):
    if not rows:
        return '<p class="muted">Nobody died before a wipe was called. 🎉</p>'
    body = ''.join(
        f'<tr><td>{ability(k["name"], k["icon"], k["id"], guide_for(k["id"], k["name"]))}</td><td class="num">{k["count"]}</td>'
        f'<td class="small">{", ".join(f"{esc(n)}" + (f" ×{c}" if c > 1 else "") for n, c in sorted(k["players"].items(), key=lambda kv: -kv[1]))}</td></tr>'
        for k in rows[:limit])
    return (f'<div class="table-wrapper"><table class="compact"><tr><th>Killed by</th><th class="num">Deaths</th>'
            f'<th>Who</th></tr>{body}</table></div>')


def tag_buttons(encounter_id, difficulty, ability_id, ability_name, current, source, back):
    """
    Avoidable / Non-tanks / Ignore toggles; clicking the active one clears the tag.
    Any click is an officer override; ↺ drops the override and returns to the automatic tag.
    """
    buttons = []
    for tag, label, hint in (('avoidable', 'Avoidable', 'Every hit is a mistake'),
                             ('avoidable_nontank', 'Non-tanks', 'A mistake for everyone except tanks'),
                             ('ignore', 'Ignore', 'Hide from the damage tables')):
        on = current == tag
        buttons.append(f'<button name="tag" value="{"none" if on else tag}" '
                       f'class="{"on-" + tag if on else ""}" title="{"Clear tag" if on else hint}">'
                       f'{label}</button>')
    if source == 'manual':
        buttons.append('<button name="tag" value="auto" title="Undo your override and use the automatic tag">'
                       '↺ auto</button>')
    return (f'<form method="post" action="/admin/raids/boss/{encounter_id}/{difficulty}/tag" class="tag-form">'
            f'<input type="hidden" name="ability_id" value="{ability_id}">'
            f'<input type="hidden" name="ability_name" value="{esc(ability_name)}">'
            f'<input type="hidden" name="back" value="{esc(back)}">{"".join(buttons)}</form>')
