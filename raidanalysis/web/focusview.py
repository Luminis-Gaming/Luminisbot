"""
The Focus timeline for one pull (data from focus.py): when each add was up, who you and the raid were
damaging moment by moment (100%-stacked strips, one color per target), the boss's abilities, your
potion and major cooldowns - and a card per add window that says whether you were on it.

Built on the shared .tl timeline (PAGE_JS: drag to pan, zoom, rich tooltips from data-tip / data-spell).
"""
from .. import focus
from .render import ICON_BASE, esc, fmt_amount, fmt_duration, json_for_script, safe_icon

# Categorical slots, dark steps, in fixed order (validated on the card surface #161a2c: all checks pass).
COLORS = ('#3987e5', '#d95926', '#199e70', '#c98500', '#d55181')
OTHER_COLOR = '#5b6178'
VERDICTS = {'good': ('pill-kill', 'On it'), 'ok': ('pill', 'Partly'), 'off': ('pill-wipe', 'Off target')}


def colors(data):
    order = focus.palette_order(data)
    out = {t: COLORS[i] for i, t in enumerate(order)}
    out[focus.OTHER] = OTHER_COLOR
    return order, out


def _pct(v):
    return f'{100 * v:.0f}%'


def _swatch(color):
    return f'<i class="fsw" style="background:{color}"></i>'


def _strip(side, order, color_of, step, duration, label):
    """One 100%-stacked column per bucket; hovering a column lists every target's share and DPS."""
    rows = focus.folded(side, order)
    keys = [t for t in order + [focus.OTHER] if t in rows]
    n = max((len(v) for v in rows.values()), default=0)
    cols = []
    for i in range(n):
        total = sum(rows[k][i] for k in keys)
        if not total:
            continue
        segs, tip = [], []
        for k in keys:
            v = rows[k][i]
            if v <= 0:
                continue
            segs.append(f'<b style="height:{100 * v / total:.2f}%;background:{color_of[k]}"></b>')
            tip.append(f'{k} {_pct(v / total)} ({fmt_amount(v / (step / 1000))}/s)')
        start, end = i * step, min(duration, (i + 1) * step)
        cols.append(f'<i class="fcol" style="left:{100 * start / duration:.3f}%;width:{100 * (end - start) / duration:.3f}%" '
                    f'data-tip="{esc(label)} {fmt_duration(start)}–{fmt_duration(end)} · {esc(" · ".join(tip))}">'
                    f'{"".join(segs)}</i>')
    return ''.join(cols)


def _at(t, duration):
    return f'{100 * max(0, min(t, duration)) / duration:.3f}%'


def timeline(data, pull, me_name, color_of, order, cooldowns, potions, phases):
    """
    cooldowns: [(t, spell id, name, icon url)] your major cooldowns this pull; potions: [{'t', 'end', 'ability'}];
    phases: [{'id', 'start'}].
    """
    duration = max(1, pull['end_ms'] - pull['start_ms'])
    step = data.get('bucket_ms') or focus.BUCKET_MS
    analysis = pull.get('analysis') or {}
    boss_meta = {a['id']: a for a in analysis.get('boss_abilities') or []}
    ticks = ''.join(f'<i class="m tick" style="left:{_at(t, duration)}" data-spell="{sid}" '
                    f'data-tip="{esc(boss_meta[sid].get("name") or "")} · {fmt_duration(t)}"></i>'
                    for t, sid in analysis.get('boss_casts') or [] if sid in boss_meta)
    wins = focus.windows(data)
    bands = ''.join(
        f'<i class="fwin{" prio" if w["priority"] else ""}" style="left:{_at(w["start"], duration)};'
        f'width:{100 * (w["end"] - w["start"]) / duration:.3f}%;--c:{color_of.get(w["target"], OTHER_COLOR)}" '
        f'data-tip="{esc(w["target"])} up {fmt_duration(w["start"])}–{fmt_duration(w["end"])} · the raid put '
        f'{_pct(w["raid_share"])} of its damage into it, you {_pct(w["you_share"])}"><span>{esc(w["target"])}</span></i>'
        for w in wins)
    pots = ''.join(
        f'<i class="fpot" style="left:{_at(p["t"], duration)};width:{100 * max(1000, (p.get("end") or p["t"] + 30000) - p["t"]) / duration:.3f}%" '
        f'data-tip="{esc(p.get("ability") or "Potion")} · {fmt_duration(p["t"])}–{fmt_duration(p.get("end") or p["t"] + 30000)}">'
        f'<span>🧪</span></i>' for p in potions)
    cds = []
    for t, sid, name, icon in cooldowns:
        bg = f';background-image:url({safe_icon(icon)})' if safe_icon(icon) else ''
        cds.append(f'<i class="m cd" style="left:{_at(t, duration)}{bg}" data-spell="{sid}" '
                   f'data-tip="{esc(name)} · {fmt_duration(t)}"></i>')
    phase_lines = ''.join(f'<i class="tl-phase al" style="left:{_at(p["start"], duration)}"></i>'
                          for p in phases[1:] if p.get('start'))
    grid = ''.join(f'<i style="left:{_at(t, duration)}"></i>' for t in range(0, duration + 1, 60000))
    ruler = ''.join(f'<span{" class=first" if not t else ""} style="left:{_at(t, duration)}">{fmt_duration(t)}</span>'
                    for t in range(0, duration + 1, 60000))
    spell_json = {a['id']: {'name': a.get('name') or '', 'icon': f'{ICON_BASE}{a["icon"]}' if a.get('icon') else '',
                            'meta': '', 'desc': ''} for a in boss_meta.values() if safe_icon(a.get('icon'))}
    lanes = [('Boss', 'boss', ticks), ('Adds up', 'wins', bands),
             (f'You', 'strip you', _strip(data.get('you'), order, color_of, step, duration, 'You')),
             ('Raid', 'strip', _strip(data.get('raid'), order, color_of, step, duration, 'Raid')),
             ('Potion & cooldowns', 'cds', pots + ''.join(cds))]
    labels = ''.join(f'<div class="tl-lab f-{cls.split()[0]}">{esc(label)}</div>' for label, cls, _ in lanes)
    tracks = ''.join(f'<div class="tl-row f-{cls.split()[0]}{" you" if "you" in cls else ""}">{body}</div>'
                     for _, cls, body in lanes)
    return f"""<div class="tl focus-tl" data-duration="{duration}">
        <div class="tl-tools">
            <span class="muted small">Drag to pan · Ctrl + scroll or pinch to zoom · hover anything</span>
            <button type="button" data-zoom="out" title="Zoom out">−</button>
            <input type="range" min="0" max="100" value="0" aria-label="Zoom">
            <button type="button" data-zoom="in" title="Zoom in">+</button>
            <button type="button" data-zoom="fit" title="Show the whole fight">Fit</button></div>
        <div class="tl-body">
            <div class="tl-labels">{labels}<div class="tl-ruler-gap"></div></div>
            <div class="tl-scroll"><div class="tl-inner">
                <div class="tl-grid">{grid}</div>{phase_lines}
                {tracks}
                <div class="tl-ruler">{ruler}</div>
                <div class="tl-head" hidden><span></span></div>
            </div></div>
        </div>
        <script type="application/json" class="spell-data">{json_for_script(spell_json)}</script>
    </div>"""


def _overlap(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def cards(data, color_of, potions, cooldowns, top_share, my_share, label):
    """
    One card per add window, priorities first: your share of damage vs the raid's, DPS on it, the potion's
    timing and coverage, cooldowns pressed during it - and the top players' share into it over their kill.
    top_share / my_share: {target: share of all damage over the pull / their kill}.
    """
    out = []
    for w in sorted(focus.windows(data), key=lambda w: (not w['priority'], w['start'])):
        length = w['end'] - w['start']
        cls, text = VERDICTS.get(w['verdict'], ('pill-muted', 'Not a priority'))
        lines = [f'You put <b>{_pct(w["you_share"])}</b> of your damage into it - the raid <b>{_pct(w["raid_share"])}</b>',
                 f'Your DPS on it <b>{fmt_amount(w["you_dps"])}</b> · raid average per player {fmt_amount(w["raid_dps"])}']
        pot = min(potions, key=lambda p: abs(p['t'] - w['start']), default=None) if w['priority'] else None
        if pot and abs(pot['t'] - w['start']) <= 60000:
            end = pot.get('end') or pot['t'] + 30000
            lead = (w['start'] - pot['t']) / 1000
            when = (f'{lead:.0f} s before it appeared' if lead >= 1 else
                    f'{-lead:.0f} s after it appeared' if lead <= -1 else 'as it appeared')
            lines.append(f'🧪 {esc(pot.get("ability") or "Potion")} {when} - its buff covered '
                         f'<b>{_pct(_overlap(pot["t"], end, w["start"], w["end"]) / length)}</b> of the window')
        elif w['priority']:
            lines.append('🧪 No potion near this window')
        during = [name for t, _, name, _ in cooldowns if w['start'] - 5000 <= t <= w['end']]
        if during:
            lines.append('⚔️ Cooldowns during it: ' + esc(', '.join(dict.fromkeys(during))))
        if top_share.get(w['target']) is not None:
            lines.append(f'Top {esc(label)} put {_pct(top_share[w["target"]])} of their whole kill into '
                         f'{esc(w["target"])} - you {_pct(my_share.get(w["target"], 0))} of this pull')
        out.append(f"""
            <div class="fcard{" prio" if w['priority'] else ""}" style="--c:{color_of.get(w['target'], OTHER_COLOR)}">
                <div class="fcard-head">{_swatch(color_of.get(w['target'], OTHER_COLOR))}<b>{esc(w['target'])}</b>
                    <span class="muted small">{fmt_duration(w['start'])}–{fmt_duration(w['end'])} · {length / 1000:.0f} s</span>
                    <span class="pill {cls}">{text}</span></div>
                <ul>{''.join(f'<li>{line}</li>' for line in lines)}</ul>
            </div>""")
    return f'<div class="fcards">{"".join(out)}</div>' if out else ''


def target_table(data, color_of):
    rows = ''.join(f"""
        <tr><td>{_swatch(color_of.get(r['target'], OTHER_COLOR))}{esc(r['target'])}
                {' <span class="pill pill-muted">boss</span>' if r['type'] == 'Boss' else ''}</td>
            <td class="num" data-v="{r['damage']}">{fmt_amount(r['damage'])}</td>
            <td class="num" data-v="{r['share']:.4f}">{_pct(r['share'])}</td>
            <td class="num" data-v="{r['up_s']:.0f}">{fmt_duration(r['up_s'] * 1000)}</td>
            <td class="num" data-v="{r['dps']:.0f}">{fmt_amount(r['dps'])}</td></tr>"""
                   for r in focus.target_rows(data) if r['damage'])
    return f"""<div class="table-wrapper"><table class="compact">
        <tr><th data-sort>Target</th><th data-sort class="num">Your damage</th><th data-sort class="num">Share</th>
            <th data-sort class="num" title="How long the raid was hitting it">Up</th>
            <th data-sort class="num" title="Your damage on it divided by the time it was up">Your DPS while up</th></tr>
        {rows}</table></div>"""


def legend(data, order, color_of):
    """Every colored target, plus Other when some were folded into it."""
    folded_away = any(t not in order for side in ('raid', 'you') for t in data.get(side) or {})
    shown = order + ([focus.OTHER] if folded_away else [])
    return '<div class="flegend">' + ''.join(f'<span>{_swatch(color_of[t])}{esc(t)}</span>' for t in shown) + '</div>'
