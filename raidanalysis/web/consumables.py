"""
Consumables in detail: which potion / healthstone each player used, when, for
how long and how much it healed - plus a WCL-style timeline with the boss's
abilities on top and every player's consumables (and deaths) underneath.

Needs analyses from ANALYSIS_VERSION 4+ ('consumables', 'boss_casts');
older nights only have counts until they're re-analyzed.
"""
from .render import ROLE_ICONS, esc, fmt_amount, fmt_duration, player_name

# What the timeline colors encode is the *kind* of consumable (validated with the
# dataviz palette checker on the card surface, all pairs); the exact potion is in
# the tooltip, the legend text and the tables.
KIND_COLORS = {'potion': '#7484ec', 'mana': '#2f9e8f', 'defensive': '#cc7f3c'}
KIND_LABELS = {'potion': 'Combat potion', 'mana': 'Mana potion', 'defensive': 'Healthstone / healing potion'}
BOSS_TICK = '#9aa1b9'
DEATH = '#ff6b6b'
POTION_BUFF_FALLBACK_MS = 30000
ICON_BASE = 'https://assets.rpglogs.com/img/warcraft/abilities/'


def kind(use):
    if use['kind'] == 'defensive':
        return 'defensive'
    return 'mana' if 'mana' in (use.get('ability') or '').lower() else 'potion'


def has_details(analyses):
    return any('consumables' in a for a in analyses)


def _icon(icon):
    return f'<img class="ability-icon" src="{ICON_BASE}{esc(icon)}" alt="" loading="lazy">' if icon else ''


def legend():
    items = [f'<span style="--c:{KIND_COLORS[k]}">{KIND_LABELS[k]}</span>' for k in ('potion', 'mana', 'defensive')]
    items.append(f'<span style="--c:{DEATH}">Death</span>')
    items.append(f'<span style="--c:{BOSS_TICK}">Enemy ability cast</span>')
    return f'<div class="legend">{"".join(items)}</div>'


# ============================================================================
# Timeline
# ============================================================================

def timeline(pulls, roster):
    """
    pulls: [{'number', 'analysis' (with _duration), 'phases': [ms]}]. One pull = exact WCL-style
    timeline with the enemy's casts; several = every use from every pull on one axis (habits show
    up as clusters), with deaths left out to keep it readable.
    """
    single = len(pulls) == 1
    longest = max((p['analysis'].get('_duration') or 0) for p in pulls) or 1
    lanes = []  # (label, kind, marks)

    if single:
        # One lane per ability *name* - bosses often cast the same ability under several spell IDs.
        analysis = pulls[0]['analysis']
        names = {a['id']: a['name'] for a in analysis.get('boss_abilities') or []}
        by_name = {}
        for t, guid in analysis.get('boss_casts') or []:
            if guid in names:
                by_name.setdefault(names[guid], []).append(t)
        for name, casts in sorted(by_name.items(), key=lambda kv: min(kv[1])):
            lanes.append((name, 'boss', sorted(casts)))

    for player in roster:
        uses = [(u, p) for p in pulls for u in p['analysis'].get('consumables') or [] if u['name'] == player['name']]
        deaths = ([d for d in pulls[0]['analysis'].get('deaths') or [] if d['name'] == player['name']]
                  if single else [])
        lanes.append((player['name'], 'player', (uses, deaths)))

    row_h, boss_h, left, right, top = 22, 15, 150, 14, 8
    height = top + sum(boss_h if k == 'boss' else row_h for _, k, _ in lanes) + 30
    width = 900
    inner = width - left - right

    def x(t):
        return left + inner * max(0, min(t, longest)) / longest

    parts = [f'<svg class="chart timeline" viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="Consumables timeline">']
    for minute in range(0, int(longest / 60000) + 1):
        parts.append(f'<line class="grid" x1="{x(minute * 60000):.1f}" x2="{x(minute * 60000):.1f}" '
                     f'y1="{top}" y2="{height - 22}"/><text x="{x(minute * 60000):.1f}" y="{height - 6}" '
                     f'text-anchor="middle">{minute}:00</text>')
    if single:
        for start in pulls[0]['phases']:
            parts.append(f'<line x1="{x(start):.1f}" x2="{x(start):.1f}" y1="{top}" y2="{height - 22}" '
                         f'stroke="rgba(255,255,255,0.3)" stroke-dasharray="4 3"/>')

    y = top
    boss_done = False
    for label, lane_kind, marks in lanes:
        h = boss_h if lane_kind == 'boss' else row_h
        mid = y + h / 2
        if lane_kind == 'player' and not boss_done and single and any(k == 'boss' for _, k, _ in lanes):
            parts.append(f'<line x1="0" x2="{width}" y1="{y:.1f}" y2="{y:.1f}" stroke="rgba(255,255,255,0.15)"/>')
            boss_done = True
        short = label if len(label) <= 22 else label[:21] + '…'
        parts.append(f'<text x="{left - 8}" y="{mid + 4:.1f}" text-anchor="end"'
                     f'{" class=axis-label" if lane_kind == "boss" else ""}>{esc(short)}</text>')
        if lane_kind == 'boss':
            for t in marks:
                parts.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{y + 3:.1f}" y2="{y + h - 3:.1f}" '
                             f'stroke="{BOSS_TICK}" stroke-width="2"><title>{esc(label)} — {fmt_duration(t)}</title></line>')
        else:
            uses, deaths = marks
            parts.append(f'<line class="grid" x1="{left}" x2="{width - right}" y1="{mid:.1f}" y2="{mid:.1f}"/>')
            for use, pull in uses:
                k = kind(use)
                color = KIND_COLORS[k]
                opacity = '' if single else ' opacity="0.55"'
                tip = (f'{"Pull " + str(pull["number"]) + ": " if not single else ""}{use["ability"]} at '
                       f'{fmt_duration(use["t"])}{" (pre-pot)" if use.get("prepot") else ""}')
                if k == 'defensive':
                    tip += f' — healed {fmt_amount(use.get("healing") or 0)}'
                    cx = x(use['t'])
                    parts.append(f'<path d="M{cx:.1f},{mid - 6:.1f} L{cx + 6:.1f},{mid:.1f} L{cx:.1f},{mid + 6:.1f} '
                                 f'L{cx - 6:.1f},{mid:.1f} Z" fill="{color}" stroke="#161a2c" stroke-width="1.5"{opacity}>'
                                 f'<title>{esc(tip)}</title></path>')
                else:
                    end = use.get('end') or (use['t'] + POTION_BUFF_FALLBACK_MS)
                    tip += f' — {fmt_duration(end - use["t"])} buff' if single else ''
                    parts.append(f'<rect x="{x(use["t"]):.1f}" y="{mid - 5:.1f}" width="{max(3, x(end) - x(use["t"])):.1f}" '
                                 f'height="10" rx="3" fill="{color}"{opacity}><title>{esc(tip)}</title></rect>')
            for d in deaths:
                cx, color = x(d['t']), (DEATH if d.get('early') else 'rgba(255,255,255,0.35)')
                parts.append(f'<path d="M{cx - 5:.1f},{mid - 5:.1f} L{cx + 5:.1f},{mid + 5:.1f} M{cx + 5:.1f},{mid - 5:.1f} '
                             f'L{cx - 5:.1f},{mid + 5:.1f}" stroke="{color}" stroke-width="2.5">'
                             f'<title>Died to {esc(d["ability"])} at {fmt_duration(d["t"])}</title></path>')
        y += h
    parts.append('</svg>')
    return legend() + ''.join(parts)


# ============================================================================
# Tables
# ============================================================================

def _by_type(uses):
    out = {}
    for u in uses:
        entry = out.setdefault(u['ability'], {'ability': u['ability'], 'icon': u.get('icon'), 'count': 0,
                                              'healing': 0, 'kind': kind(u)})
        entry['count'] += 1
        entry['healing'] += u.get('healing') or 0
    return sorted(out.values(), key=lambda e: -e['count'])


def type_summary(pulls, kinds):
    """'Light's Potential ×14 · Liquid Luster ×5 …' for the given kinds."""
    uses = [u for p in pulls for u in p['analysis'].get('consumables') or [] if kind(u) in kinds]
    if not uses:
        return '<p class="muted small">None used.</p>'
    chips = []
    for e in _by_type(uses):
        healed = f' · {fmt_amount(e["healing"])} healed' if e['healing'] else ''
        chips.append(f'<span class="chip">{_icon(e["icon"])}{esc(e["ability"])} ×{e["count"]}{healed}</span>')
    return f'<div class="chips">{"".join(chips)}</div>'


def _avg_times(per_pull_times):
    """Average time of the 1st, 2nd, … potion across pulls: '0:01 · 4:12' (slots seen in ≥ 30% of pulls)."""
    slots = {}
    for times in per_pull_times:
        for i, t in enumerate(sorted(times)):
            slots.setdefault(i, []).append(t)
    pulls = len(per_pull_times) or 1
    averages = sorted(sum(v) / len(v) for v in slots.values() if len(v) / pulls >= 0.3)
    return ' · '.join(fmt_duration(t) for t in averages)


def _median_time(times):
    times = sorted(times)
    return fmt_duration(times[len(times) // 2]) if times else ''


def player_rows(pulls, roster, kinds, code=None):
    """Expandable row per player: what they used, average timing, healing, and per-pull details."""
    single = len(pulls) == 1
    defensive = kinds == {'defensive'}
    rows = []
    for player in roster:
        # Only the pulls this player was actually in.
        present = [p for p in pulls if any(x['name'] == player['name'] for x in p['analysis'].get('players') or [])]
        per_pull = [(p, [u for u in p['analysis'].get('consumables') or []
                         if u['name'] == player['name'] and kind(u) in kinds]) for p in present]
        uses = [u for _, us in per_pull for u in us]
        types = ', '.join(f'{e["ability"]} ×{e["count"]}' for e in _by_type(uses)) or 'nothing'
        healing = sum(u.get('healing') or 0 for u in uses)
        if single:
            timing = ' · '.join(fmt_duration(u['t']) for u in uses)
        elif defensive:
            timing = _median_time([u['t'] for u in uses])
        else:
            timing = _avg_times([[u['t'] for u in us] for _, us in per_pull if us])
        prepots = sum(1 for u in uses if u.get('prepot'))
        used_pulls = sum(1 for _, us in per_pull if us)
        summary = [f'<strong>{len(uses)}</strong> — {esc(types)}']
        if not single:
            summary.append(f'in {used_pulls}/{len(present)} pulls')
        if timing:
            summary.append(f'{"at" if single else "typically at" if defensive else "avg"} {timing}')
        if prepots:
            summary.append(f'{prepots} pre-pot{"s" if prepots != 1 else ""}')
        if healing:
            summary.append(f'healed {fmt_amount(healing)}')
        lines = []
        unused = [str(pull['number']) for pull, us in per_pull if not us]
        for pull, us in per_pull:
            if not us:
                continue
            label = '' if single else (f'<a href="/admin/raids/report/{esc(code)}/{pull["fight_id"]}">#{pull["number"]}</a> '
                                       if code and pull.get('fight_id') else f'#{pull["number"]} ')
            items = ', '.join(
                f'{_icon(u.get("icon"))}{esc(u["ability"])} {fmt_duration(u["t"])}'
                + (' <span class="muted">(pre-pot)</span>' if u.get('prepot') else '')
                + (f' <span class="muted">+{fmt_amount(u["healing"])}</span>' if u.get('healing') else '')
                + (f' <span class="muted">({fmt_duration(u["end"] - u["t"])})</span>'
                   if u.get('end') and kind(u) != 'defensive' and single else '')
                for u in us)
            lines.append(f'<p class="small">{label}{items}</p>')
        if unused and not single:
            lines.append(f'<p class="small muted">None in pull{"s" if len(unused) != 1 else ""} '
                         f'#{", #".join(unused)}</p>')
        tone = 'bad' if not uses and not defensive else ''
        rows.append(f'<details class="insight {tone}"><summary><span>{ROLE_ICONS.get(player.get("role"), "")}</span>'
                    f'<span>{player_name(player["name"], player.get("class", ""))} — {" · ".join(summary)}</span>'
                    f'</summary><div class="insight-body">{"".join(lines) or "<p class=muted>Nothing used.</p>"}'
                    f'</div></details>')
    return ''.join(rows)
