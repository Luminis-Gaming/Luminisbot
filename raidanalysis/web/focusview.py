"""
The Focus timeline for one pull (data from focus.py), as horizontal lanes: the boss's abilities, who you
were hitting at every moment (switches show as a change of color), one lane per target - when it was up
and when you were on it - and your potion and major cooldowns; then a card per add window that says
whether you were on it.

Built on the shared .tl timeline (PAGE_JS: drag to pan, zoom, rich tooltips from data-tip / data-spell).
"""
from .. import focus
from .render import ICON_BASE, esc, fmt_amount, fmt_duration, json_for_script, safe_icon

# Categorical slots, dark steps, in fixed order (validated on the card surface #161a2c: all checks pass).
COLORS = ('#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#8f6ce0')
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


def _clock(ms):
    """2:20.4 - to the tenth of a second, for timings that matter (a potion against an add appearing)."""
    return f'{int(ms // 60000)}:{ms % 60000 / 1000:04.1f}'


def _at(t, duration):
    return f'{100 * max(0, min(t, duration)) / duration:.3f}%'


def _span(start, end, duration):
    return f'left:{_at(start, duration)};width:{100 * max(0, min(end, duration) - start) / duration:.3f}%'


def _ribbon(data, order, color_of, duration):
    """Who you were hitting at every moment (focus.your_targets): one colored stretch per target, switches in between."""
    out = []
    for r in focus.your_targets(data, order):
        secs = (r['end'] - r['start']) / 1000
        out.append(f'<i class="frun" style="{_span(r["start"], r["end"], duration)};--c:{color_of.get(r["target"], OTHER_COLOR)}" '
                   f'data-tip="{esc(r["target"])} · {fmt_duration(r["start"])}–{fmt_duration(r["end"])} ({secs:.0f} s) · '
                   f'{fmt_amount(r["damage"])} damage"></i>')
    return ''.join(out)


def _target_lane(target, mine, raid_row, wins, color, step, duration, peak, always_up):
    """
    One target, two tracks: on top what the raid did (light: the add was up and the raid was hitting it -
    outlined while it was the raid's priority; the whole pull for a boss), underneath what you did (solid: a
    bar for every stretch you were hitting it, brighter the harder you hit).
    """
    if always_up:
        raid = (f'<i class="fraid" style="{_span(0, duration, duration)}" '
                f'data-tip="{esc(target)} · up the whole pull"></i>')
    else:
        raid = ''
        for first, last in focus.runs(raid_row or []):
            start, end = first * step, (last + 1) * step
            w = next((w for w in wins if w['start'] < end and w['end'] > start), None)
            tip = f'{esc(target)} up {fmt_duration(start)}–{fmt_duration(end)}'
            if w:
                tip += (f' · the top DPS put {_pct(w["raid_share"])} of their damage into it'
                        f'{" - a priority" if w["priority"] else ""}, you {_pct(w["you_share"])} of yours')
            raid += (f'<i class="fraid{" prio" if w and w["priority"] else ""}" style="{_span(start, end, duration)}" '
                     f'data-tip="{tip}"></i>')
    you = []
    for w in wins:  # from the add appearing to your first hit on it
        if w['first_hit'] is None:
            you.append(f'<i class="freact never" style="{_span(w["start"], w["end"], duration)}" '
                       f'data-tip="You never hit {esc(target)} while it was up ({fmt_duration(w["start"])}–'
                       f'{fmt_duration(w["end"])})"></i>')
        elif w['first_hit'] >= step:
            you.append(f'<i class="freact" style="{_span(w["start"], w["start"] + w["first_hit"], duration)}" '
                       f'data-tip="Reaction: you first hit {esc(target)} {w["first_hit"] / 1000:.1f} s after it '
                       f'appeared ({_clock(w["start"])})"></i>')
    for first, last in focus.runs(mine):
        start, end = first * step, (last + 1) * step
        dmg = sum(mine[first:last + 1])
        dps = dmg / ((end - start) / 1000)
        strength = 0.5 + 0.5 * min(1, dps / peak) if peak else 1
        you.append(f'<i class="fyou" style="{_span(start, end, duration)};opacity:{strength:.2f}" '
                   f'data-tip="You on {esc(target)} · {fmt_duration(start)}–{fmt_duration(end)} · {fmt_amount(dmg)} '
                   f'({fmt_amount(dps)}/s)"></i>')
    return f'<div class="flane" style="--c:{color}">{raid}{"".join(you)}</div>'


def _group(title, hint=''):
    """A group header in the label column (and an empty row beside it)."""
    hint_html = f'<small>{hint}</small>' if hint else ''
    return (f'<div class="tl-lab fgrp"><b>{title}</b>{hint_html}</div>', 'fgrp', '')


def _phase_lane(phases, names, duration):
    """The boss's phases as labelled stretches (names from the report, else Phase n)."""
    out = []
    for i, phase in enumerate(phases):
        end = phases[i + 1]['start'] if i + 1 < len(phases) else duration
        info = names.get(str(phase['id'])) or {}
        label = info.get('name') or f"Phase {phase['id']}"
        out.append(f'<i class="fphase{" alt" if i % 2 else ""}{" inter" if info.get("intermission") else ""}" '
                   f'style="{_span(phase["start"], end, duration)}" data-tip="{esc(label)} · '
                   f'{fmt_duration(phase["start"])}–{fmt_duration(end)}"><span>{esc(label)}</span></i>')
    return ''.join(out)


def potion_lead(potions, w):
    """(potion, seconds it was pressed before the add appeared - negative: after) for a priority window, or None."""
    pot = min(potions, key=lambda p: abs(p['t'] - w['start']), default=None) if w['priority'] else None
    if not pot or abs(pot['t'] - w['start']) > 60000:
        return None
    return pot, (w['start'] - pot['t']) / 1000


def _lead_text(lead):
    return (f'{lead:.1f} s before it appeared' if lead >= 0.05 else
            f'{-lead:.1f} s after it appeared' if lead <= -0.05 else 'as it appeared')


def _adds_lane(wins, color_of, duration, potions=()):
    """Each add window: a marker where it appeared (the raid's first hit) and where it died or went away."""
    out = []
    for w in wins:
        color = color_of.get(w['target'], OTHER_COLOR)
        name = esc(w['target'])
        react = ('you never hit it' if w['first_hit'] is None else
                 f'you hit it {w["first_hit"] / 1000:.1f} s later')
        label = f'<span>{name}</span>' if w['priority'] else ''
        pot = potion_lead(potions, w)
        pot_tip = f' · your potion {_lead_text(pot[1])}' if pot else ''
        out.append(f'<i class="fev in{" prio" if w["priority"] else ""}" style="left:{_at(w["start"], duration)};'
                   f'--c:{color}" data-tip="{name} appeared · {_clock(w["start"])} · {react}{pot_tip}">▲{label}</i>')
        died = w['died_at'] is not None
        end = w['died_at'] if died else w['end']
        what = 'died' if died else 'gone (the raid stopped hitting it)'
        out.append(f'<i class="fev {"died" if died else "out"}" style="left:{_at(end, duration)};--c:{color}" '
                   f'data-tip="{name} {what} · {fmt_duration(end)} · up {(end - w["start"]) / 1000:.0f} s">'
                   f'{"✖" if died else "▼"}</i>')
    return ''.join(out)


def _boss_lanes(analysis, duration):
    """One lane per boss ability (icon + name, first cast first), a tick per cast - like the cooldown timeline."""
    meta = {a['id']: a for a in analysis.get('boss_abilities') or []}
    by_name = {}
    for t, sid in analysis.get('boss_casts') or []:
        if sid in meta:
            by_name.setdefault(meta[sid].get('name') or '?', []).append((t, sid))
    lanes = []
    for name, casts in sorted(by_name.items(), key=lambda kv: min(t for t, _ in kv[1])):
        first = casts[0][1]
        icon = safe_icon(meta[first].get('icon'))
        img = f'<img class="ability-icon" src="{ICON_BASE}{esc(icon)}" alt="" loading="lazy">' if icon else ''
        ticks = ''.join(f'<i class="m tick" style="left:{_at(t, duration)}" data-spell="{sid}" '
                        f'data-tip="{esc(name)} · {fmt_duration(t)}"></i>' for t, sid in sorted(casts))
        lanes.append((f'<div class="tl-lab boss f-boss" data-spell="{first}" '
                      f'data-tip="Cast {len(casts)}× this pull">{img}<span>{esc(name)}</span></div>',
                      'boss f-boss', ticks))
    return lanes, meta


def timeline(data, pull, me_name, color_of, order, cooldowns, potions, phases, phase_names=None):
    """
    Horizontal lanes over the pull: the boss's abilities, who you were hitting at every moment, one lane per
    target (when it was up, when you were on it), your potion and major cooldowns.
    cooldowns: [(t, spell id, name, icon url)] your major cooldowns this pull; potions: [{'t', 'end', 'ability'}];
    phases: [{'id', 'start'}]; phase_names: the report's ({encounter id: {phase id: {'name', 'intermission'}}}).
    """
    duration = max(1, pull['end_ms'] - pull['start_ms'])
    step = data.get('bin_ms') or focus.BIN_MS
    boss_lanes, boss_meta = _boss_lanes(pull.get('analysis') or {}, duration)
    wins = focus.windows(data)
    lanes = [_group('👹 Boss', 'phases, adds appearing (▲) and dying (✖) or going away (▼), every cast')]
    if len(phases) > 1:
        names = (phase_names or {}).get(str(pull.get('encounter_id'))) or {}
        lanes.append(('<div class="tl-lab f-phase">Phases</div>', 'f-phase', _phase_lane(phases, names, duration)))
    if wins:
        lanes.append(('<div class="tl-lab f-adds">Adds</div>', 'f-adds', _adds_lane(wins, color_of, duration, potions)))
    lanes += boss_lanes
    lanes += [_group('🎯 Who you were hitting', 'a change of color is a target switch'),
              ('<div class="tl-lab f-ribbon">Your target</div>', 'f-ribbon', _ribbon(data, order, color_of, duration))]
    mine = focus.folded(data.get('you'), order)
    raid_rows = focus.folded(data.get('raid'), order)
    peak = max((sum(b[a:z + 1]) / ((z - a + 1) * step / 1000) for b in mine.values() for a, z in focus.runs(b)),
               default=0)
    lanes.append(_group('⚔️ Targets', 'light = raid on it (add up) · solid = you on it · dashed = your reaction'))
    n = 0
    for target in order + [focus.OTHER]:
        if target not in mine and target not in raid_rows:
            continue
        color = color_of.get(target, OTHER_COLOR)
        main = target == data.get('main')
        always_up = main or (target in (data.get('raid') or {})
                             and focus.always_up(data['raid'][target], data.get('n') or 0))
        boss = '<span class="pill pill-muted">boss</span>' if main else ''
        lanes.append((f'<div class="tl-lab f-target{" alt" if n % 2 else ""}" title="{esc(target)}">'
                      f'<span class="flab">{_swatch(color)}<span>{esc(target)}</span>{boss}</span>'
                      f'<span class="fsides"><small>raid</small><small>you</small></span></div>',
                      f'f-target{" alt" if n % 2 else ""}',
                      _target_lane(target, mine.get(target) or [], None if main else raid_rows.get(target),
                                   [w for w in wins if w['target'] == target], color, step, duration, peak,
                                   always_up)))
        n += 1
    pots = ''.join(
        f'<i class="fpot" style="left:{_at(p["t"], duration)};width:{100 * max(1000, (p.get("end") or p["t"] + 30000) - p["t"]) / duration:.3f}%" '
        f'data-tip="{esc(p.get("ability") or "Potion")} · {fmt_duration(p["t"])}–{fmt_duration(p.get("end") or p["t"] + 30000)}">'
        f'<span>🧪</span></i>' for p in potions)
    for w in wins:
        pot = potion_lead(potions, w)
        if pot:
            a, b = sorted((pot[0]['t'], w['start']))
            pots += (f'<i class="flead" style="{_span(a, b, duration)};--c:{color_of.get(w["target"], OTHER_COLOR)}" '
                     f'data-tip="{esc(pot[0].get("ability") or "Potion")} at {_clock(pot[0]["t"])} - '
                     f'{_lead_text(pot[1])} ({esc(w["target"])}, {_clock(w["start"])})">'
                     f'<span>{abs(pot[1]):.1f} s</span></i>')
    cds = []
    for t, sid, name, icon in cooldowns:
        bg = f';background-image:url({safe_icon(icon)})' if safe_icon(icon) else ''
        cds.append(f'<i class="m cd" style="left:{_at(t, duration)}{bg}" data-spell="{sid}" '
                   f'data-tip="{esc(name)} · {fmt_duration(t)}"></i>')
    lanes += [_group('🧪 Your potion & cooldowns'),
              ('<div class="tl-lab f-cds">You</div>', 'f-cds', pots + ''.join(cds))]
    phase_lines = ''.join(f'<i class="tl-phase al" style="left:{_at(p["start"], duration)}"></i>'
                          for p in phases[1:] if p.get('start'))
    every = 30000 if duration <= 240000 else 60000
    grid = ''.join(f'<i style="left:{_at(t, duration)}"></i>' for t in range(0, duration + 1, every))
    ruler = ''.join(f'<span{" class=first" if not t else ""} style="left:{_at(t, duration)}">{fmt_duration(t)}</span>'
                    for t in range(0, duration + 1, every))
    spell_json = {a['id']: {'name': a.get('name') or '', 'icon': f'{ICON_BASE}{a["icon"]}' if a.get('icon') else '',
                            'meta': '', 'desc': ''} for a in boss_meta.values() if safe_icon(a.get('icon'))}
    labels = ''.join(label for label, _, _ in lanes)
    tracks = ''.join(f'<div class="tl-row {cls}">{body}</div>' for _, cls, body in lanes)
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
        react = ('<b class="bad-text">You never hit it</b>' if w['first_hit'] is None else
                 f'You first hit it <b>{w["first_hit"] / 1000:.1f} s</b> after it appeared')
        ended = (f'died at {fmt_duration(w["died_at"])}' if w['died_at'] is not None else
                 f'gone at {fmt_duration(w["end"])}')
        lines = [f'⏱ Appeared at {_clock(w["start"])}, {ended} - {react}',
                 f'You put <b>{_pct(w["you_share"])}</b> of your damage into it - the raid\'s top DPS <b>{_pct(w["raid_share"])}</b>',
                 f'Your DPS on it <b>{fmt_amount(w["you_dps"])}</b> · the top DPS averaged {fmt_amount(w["raid_dps"])} each']
        found = potion_lead(potions, w)
        if found:
            pot, lead = found
            end = pot.get('end') or pot['t'] + 30000
            lines.append(f'🧪 {esc(pot.get("ability") or "Potion")} pressed at {_clock(pot["t"])}, '
                         f'<b>{_lead_text(lead)}</b> - its buff covered '
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
