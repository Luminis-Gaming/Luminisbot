"""
The Focus timeline for one pull (data from focus.py), as horizontal lanes: the boss's phases, its adds
(one lane per kind, a bar per spawn) and abilities, who you were hitting at every moment (switches show as
a change of color), one lane per target - when it was up and when you were on it - and your potion and
major cooldowns. Chips above it show / hide each target (priority adds and the boss on by default).

Under it, one card per kind of add: the priorities (the top DPS pile into them) with an Overall tab and a
tab per spawn - share, reaction, potion timing, cooldowns, drawn rather than written - the rest as one
compact card each.

Built on the shared .tl timeline (PAGE_JS: drag to pan, zoom, rich tooltips from data-tip / data-spell).
"""
from .. import focus, spells
from .render import ICON_BASE, esc, fmt_amount, fmt_duration, json_for_script, npc_portrait, npc_zoom, safe_icon

# Categorical slots for targets, in fixed order. No green, amber, orange or red: those mean good / partly /
# off on these pages (the verdicts), and an add colored like a grade reads as one.
COLORS = ('#3987e5', '#d55181', '#8f6ce0', '#1fa9bb', '#b08550', '#c3c8dc')
OTHER_COLOR = '#5b6178'
VERDICTS = {'good': ('good', '✅ On it'), 'ok': ('ok', '⚠️ Partly'), 'off': ('bad', '❌ Off target')}

REACTION_GOOD_MS, REACTION_OK_MS = 1500, 3000  # first hit on a priority add after it appeared
POTION_WINDOW_MS = 30000                         # a potion this close to a priority spawn (its nearest) is for it


def colors(data):
    order = focus.palette_order(data)
    out = {t: COLORS[i] for i, t in enumerate(order)}
    out[focus.OTHER] = OTHER_COLOR
    return order, out


def _pct(v):
    return f'{100 * v:.0f}%'


def _swatch(color, icon=None, size=''):
    """The target's colour - as a ring around its portrait (npcs.py) when it has one."""
    return npc_portrait(icon, color, size) or f'<i class="fsw" style="background:{color}"></i>'


def _clock(ms):
    """2:20.4 - to the tenth of a second, for timings that matter (a potion against an add appearing)."""
    return f'{int(ms // 60000)}:{ms % 60000 / 1000:04.1f}'


def _at(t, duration):
    return f'{100 * max(0, min(t, duration)) / duration:.3f}%'


def _span(start, end, duration):
    return f'left:{_at(start, duration)};width:{100 * max(0, min(end, duration) - start) / duration:.3f}%'


def potion_lead(potions, w, wins=None):
    """
    (potion, seconds it was pressed before the add appeared - negative: after) for a priority spawn, or None.
    A potion belongs to one spawn: the priority spawn nearest to it (wins: all of the pull's), within
    POTION_WINDOW_MS.
    """
    pot = min(potions, key=lambda p: abs(p['t'] - w['start']), default=None) if w['priority'] else None
    if not pot or abs(pot['t'] - w['start']) > POTION_WINDOW_MS:
        return None
    nearest = min((x for x in wins or [w] if x['priority']), key=lambda x: abs(pot['t'] - x['start']), default=w)
    if nearest is not w and abs(pot['t'] - nearest['start']) < abs(pot['t'] - w['start']):
        return None
    return pot, (w['start'] - pot['t']) / 1000


def _lead_text(lead):
    return (f'{lead:.1f} s before it appeared' if lead >= 0.05 else
            f'{-lead:.1f} s after it appeared' if lead <= -0.05 else 'as it appeared')


def _ends(w):
    """(ms it ended, 'died' / 'gone')."""
    return (w['died_at'], 'died') if w['died_at'] is not None else (w['end'], 'gone')


def _react_band(ms):
    return 'none' if ms is None else 'good' if ms <= REACTION_GOOD_MS else 'ok' if ms <= REACTION_OK_MS else 'bad'


# ============================================================================
# Timeline
# ============================================================================

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
    outlined for a priority; the whole pull for a boss), underneath what you did (solid: a bar for every
    stretch you were hitting it, brighter the harder you hit; dashed: from it appearing to your first hit).
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
                        f'{" (a priority)" if w["priority"] else ""}, you {_pct(w["you_share"])} of yours')
            raid += (f'<i class="fraid{" prio" if w and w["priority"] else ""}" style="{_span(start, end, duration)}" '
                     f'data-tip="{tip}"></i>')
    you = []
    for w in wins:
        if w['first_hit'] is None:
            you.append(f'<i class="freact never" style="{_span(w["start"], w["end"], duration)}" '
                       f'data-tip="You never hit {esc(target)} while it was up ({_clock(w["start"])}–'
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


def _icon(icon):
    """An <img> for a WCL icon file name or a full (Wowhead) icon URL."""
    src = safe_icon(icon if not icon or icon.startswith('http') else ICON_BASE + icon)
    return f'<img class="ability-icon" src="{esc(src)}" alt="" loading="lazy">' if src else ''


def _bands(row, cls, duration, tip):
    return ''.join(f'<i class="fbuff {cls}" style="{_span(a, b, duration)}" data-spell="{row["id"]}" '
                   f'data-tip="{tip} · {_clock(a)}–{_clock(b)} ({(b - a) / 1000:.0f} s)"></i>' for a, b in row['bands'])


def _cooldown_lanes(cooldowns, auras, duration):
    """
    Your major cooldowns: a lane per ability (first pressed first) with a marker per press and, where the
    ability leaves a buff on you, a bar for how long it lasted. Returns (lanes, picks [(key, name, icon)]):
    each lane has its own key, so it can be picked on its own.
    """
    mine = {a['name']: a for a in auras if a['mine']}
    by_name = {}
    for t, sid, name, icon in sorted(cooldowns):
        by_name.setdefault(name, {'sid': sid, 'icon': icon, 'casts': []})['casts'].append(t)
    for name, aura in mine.items():  # a buff of yours with no press logged (or under another name)
        by_name.setdefault(name, {'sid': aura['id'], 'icon': aura['icon'], 'casts': []})
    lanes, picks = [], []
    for i, (name, cd) in enumerate(by_name.items()):
        aura = mine.get(name)
        bars = _bands(aura, 'mine', duration, esc(name)) if aura else ''
        marks = ''.join(f'<i class="m cd" style="left:{_at(t, duration)}'
                        f'{";background-image:url(" + safe_icon(cd["icon"]) + ")" if cd["icon"] and safe_icon(cd["icon"]) else ""}" '
                        f'data-spell="{cd["sid"]}" data-tip="{esc(name)} pressed · {_clock(t)}"></i>' for t in cd['casts'])
        presses = f'{len(cd["casts"])}× this pull' if cd['casts'] else 'its buff'
        lanes.append((f'<div class="tl-lab f-cd" data-spell="{cd["sid"]}" data-tip="{esc(name)} · {presses}">'
                      f'{_icon(cd["icon"])}<span>{esc(name)}</span></div>', 'f-cd', bars + marks, f'cds{i}'))
        picks.append((f'cds{i}', name, cd['icon'], len(cd['casts']) or len((aura or {}).get('bands') or []),
                      cd['sid'], f'{name} · {presses}'))
    return lanes, picks


def _external_lanes(auras, duration):
    """
    Buffs others put on you (Power Infusion, lust, Pain Suppression...): a lane per buff, a bar per time.
    Returns (lanes, picks), like _cooldown_lanes.
    """
    lanes, picks = [], []
    for i, aura in enumerate(a for a in auras if not a['mine']):
        who = ', '.join(aura['from'])
        lanes.append((f'<div class="tl-lab f-cd" data-spell="{aura["id"]}" data-tip="{esc(aura["name"])} from {esc(who)}">'
                      f'{_icon(aura["icon"])}<span>{esc(aura["name"])}</span></div>', 'f-cd',
                      _bands(aura, 'ext', duration, f'{esc(aura["name"])} from {esc(who)}'), f'ext{i}'))
        picks.append((f'ext{i}', aura['name'], aura['icon'], len(aura['bands']), aura['id'],
                      f'{aura["name"]} from {who}'))
    return lanes, picks


def _group(title, hint='', key=None):
    """A group header in the label column (and an empty row beside it); key: the chip that hides it too."""
    hint_html = f'<small>{hint}</small>' if hint else ''
    return (f'<div class="tl-lab fgrp"><b>{title}</b>{hint_html}</div>', 'fgrp', '', key)


def phase_lane(phases, names, duration):
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


def spawn_lane(kind, color, duration, potions=(), wins=None, you=True):
    """
    One kind of add: a bar per spawn, from appearing (the raid's first hit) to dying (solid end) or going
    away. you: a player's view (their reaction and potion in the tooltips); False: the raid's.
    """
    out = []
    for k, w in enumerate(kind['spawns'], 1):
        end, how = _ends(w)
        react = ('you never hit it' if w['first_hit'] is None else f'you hit it {w["first_hit"] / 1000:.1f} s later')
        pot = potion_lead(potions, w, wins) if you else None
        tip = (f'{esc(kind["target"])} #{k} · appeared {_clock(w["start"])}, {how} {fmt_duration(end)} '
               f'({(end - w["start"]) / 1000:.0f} s)' + (f' · {react}' if you else '')
               + (' · a priority' if not you and kind['priority'] else '')
               + (f' · your potion {_lead_text(pot[1])}' if pot else ''))
        out.append(f'<i class="fspawn {how}" style="{_span(w["start"], end, duration)};--c:{color}" data-tip="{tip}">'
                   f'<span>#{k}</span></i>')
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
                      'boss f-boss', ticks, 'abilities'))
    return lanes, meta


def timeline(data, pull, me_name, color_of, order, cooldowns, potions, phases, phase_names=None, npc_icons=None):
    """
    Horizontal lanes over the pull: the boss's phases, adds and abilities, who you were hitting at every
    moment, one lane per target (when it was up, when you were on it), your potion and major cooldowns.
    cooldowns: [(t, spell id, name, icon url)] your major cooldowns this pull; potions: [{'t', 'end', 'ability'}];
    phases: [{'id', 'start'}]; phase_names: the report's ({encounter id: {phase id: {'name', 'intermission'}}});
    npc_icons: {target: portrait url} (npcs.icons).
    """
    npc_icons = npc_icons or {}
    duration = max(1, pull['end_ms'] - pull['start_ms'])
    step = data.get('bin_ms') or focus.BIN_MS
    boss_lanes, boss_meta = _boss_lanes(pull.get('analysis') or {}, duration)
    wins = focus.windows(data)
    kinds = focus.add_types(wins)
    mine = focus.folded(data.get('you'), order)
    raid_rows = focus.folded(data.get('raid'), order)
    shown = [t for t in order + [focus.OTHER] if t in mine or t in raid_rows]
    # One toggle per target / kind of add (the lane in Targets and its spawns in Boss share it)
    keys, on = {}, set()
    for target in shown + [k['target'] for k in kinds]:
        keys.setdefault(target, f'g{len(keys)}')
    priority = {k['target'] for k in kinds if k['priority']}
    add_kinds = {k['target'] for k in kinds}
    for target, key in keys.items():
        if target == data.get('main') or target in priority or (target not in add_kinds and target != focus.OTHER):
            on.add(key)

    lanes = [_group('👹 Boss', 'phases · adds: a bar per spawn, white end = died')]
    if len(phases) > 1:
        names = (phase_names or {}).get(str(pull.get('encounter_id'))) or {}
        lanes.append(('<div class="tl-lab f-phase">Phases</div>', 'f-phase', phase_lane(phases, names, duration), None))
    for kind in kinds:
        color = color_of.get(kind['target'], OTHER_COLOR)
        prio = '<span class="pill pill-kill">priority</span>' if kind['priority'] else ''
        lanes.append((f'<div class="tl-lab f-spawns" title="{esc(kind["target"])}"><span class="flab">{_swatch(color, npc_icons.get(kind["target"]))}'
                      f'<span>{esc(kind["target"])}</span></span><small>×{len(kind["spawns"])}</small>{prio}</div>',
                      'f-spawns', spawn_lane(kind, color, duration, potions, wins), keys[kind['target']]))
    lanes += boss_lanes
    lanes += [_group('⚔️ Who you were hitting', 'a change of color is a target switch'),
              ('<div class="tl-lab f-ribbon">Your target</div>', 'f-ribbon', _ribbon(data, order, color_of, duration), None)]
    peak = max((sum(b[a:z + 1]) / ((z - a + 1) * step / 1000) for b in mine.values() for a, z in focus.runs(b)),
               default=0)
    lanes.append(_group('⚔️ Targets', 'light: raid on it · solid: you · dashed: reaction'))
    for n, target in enumerate(shown):
        color = color_of.get(target, OTHER_COLOR)
        main = target == data.get('main')
        always_up = main or (target in (data.get('raid') or {})
                             and focus.always_up(data['raid'][target], data.get('n') or 0))
        boss = '<span class="pill pill-muted">boss</span>' if main else ''
        lanes.append((f'<div class="tl-lab f-target{" alt" if n % 2 else ""}" title="{esc(target)}">'
                      f'<span class="flab">{_swatch(color, npc_icons.get(target))}<span>{esc(target)}</span>{boss}</span>'
                      f'<span class="fsides"><small>raid</small><small>you</small></span></div>',
                      f'f-target{" alt" if n % 2 else ""}',
                      _target_lane(target, mine.get(target) or [], None if main else raid_rows.get(target),
                                   [w for w in wins if w['target'] == target], color, step, duration, peak,
                                   always_up), keys[target]))
    def pot_icon(p):  # the potion's own icon, like the raid timeline's (🧪 when the log gave none)
        src = safe_icon(p.get('icon') if not p.get('icon') or p['icon'].startswith('http') else ICON_BASE + p['icon'])
        return f'<b style="background-image:url({src})"></b>' if src else '<span>🧪</span>'
    spells.offer([p['ability_id'] for p in potions if p.get('ability_id')])  # their Wowhead tooltips

    def pot_spell(p):
        return f'data-spell="{int(p["ability_id"])}" ' if p.get('ability_id') else ''
    pots = ''.join(
        f'<i class="fpot" style="left:{_at(p["t"], duration)};width:{100 * max(1000, (p.get("end") or p["t"] + 30000) - p["t"]) / duration:.3f}%" '
        f'{pot_spell(p)}'
        f'data-tip="{esc(p.get("ability") or "Potion")} · {_clock(p["t"])}–{fmt_duration(p.get("end") or p["t"] + 30000)}">'
        f'{pot_icon(p)}</i>' for p in potions)
    for w in wins:
        pot = potion_lead(potions, w, wins)
        if pot:
            a, b = sorted((pot[0]['t'], w['start']))
            pots += (f'<i class="flead" style="{_span(a, b, duration)};--c:{color_of.get(w["target"], OTHER_COLOR)}" '
                     f'data-tip="{esc(pot[0].get("ability") or "Potion")} at {_clock(pot[0]["t"])} - '
                     f'{_lead_text(pot[1])} ({esc(w["target"])}, {_clock(w["start"])})">'
                     f'<span>{abs(pot[1]):.1f} s</span></i>')
    auras = data.get('auras') or []
    (cd_lanes, cd_picks), (ext_lanes, ext_picks) = _cooldown_lanes(cooldowns, auras, duration), \
        _external_lanes(auras, duration)
    if cd_lanes:
        lanes += [_group('⏳ Your cooldowns', 'a marker per press · bar: its buff on you', 'cds')] + cd_lanes
    if ext_lanes:
        lanes += [_group('🤝 Buffs from others', 'externals and lust on you · hover: who', 'ext')] + ext_lanes
    lanes += [_group('🧪 Your potion', 'bracket: potion → priority add appearing'),
              ('<div class="tl-lab f-cds">Potion</div>', 'f-cds', pots, None)]

    # What's drawn, like the raid timeline: a dropdown per group (an All box, a box per thing - PAGE_JS) -
    # Targets (every enemy: its lanes, spawns and spawn lines), your cooldowns, buffs from others. A box's
    # data-name is the thing's name (remembered per browser), its value the lanes' data-k.
    target_items = [(key, 't:' + target, _swatch(color_of.get(target, OTHER_COLOR), npc_icons.get(target)),
                     target, len(next(k['spawns'] for k in kinds if k['target'] == target)) if target in add_kinds else None,
                     None, None, key in on) for target, key in keys.items()]
    groups = [(cat, label, picks) for cat, label, picks in (('cds', '⏳ Your cooldowns', cd_picks),
                                                           ('ext', '🤝 Buffs from others', ext_picks)) if picks]
    on |= {key for _, _, picks in groups for key, *_ in picks}
    spells.offer([sid for _, _, picks in groups for *_, sid, _ in picks])  # their tooltips may be looked up
    chips = _dropdown('targets', '⚔️ Targets', target_items) + ''.join(
        _dropdown(cat, label, [(key, f'{cat}:{name}', _icon(icon), name, count, sid, tip, True)
                               for key, name, icon, count, sid, tip in picks])
        for cat, label, picks in groups)
    phase_lines = ''.join(f'<i class="tl-phase al" style="left:{_at(p["start"], duration)}"></i>'
                          for p in phases[1:] if p.get('start'))
    # Each spawn as a dashed line in its add's colour, top to bottom: do your cooldowns, buffs and potion line
    # up with it? (Shown with the add's box in Targets.)
    phase_lines += ''.join(
        f'<i class="tl-phase fspawnline" data-k="{keys[k["target"]]}"{"" if keys[k["target"]] in on else " hidden"} '
        f'style="left:{_at(w["start"], duration)};--c:{color_of.get(k["target"], OTHER_COLOR)}"></i>'
        for k in kinds for w in k['spawns'])
    every = 30000 if duration <= 240000 else 60000
    grid = ''.join(f'<i style="left:{_at(t, duration)}"></i>' for t in range(0, duration + 1, every))
    ruler = ''.join(f'<span{" class=first" if not t else ""} style="left:{_at(t, duration)}">{fmt_duration(t)}</span>'
                    for t in range(0, duration + 1, every))
    spell_json = {a['id']: {'name': a.get('name') or '', 'icon': f'{ICON_BASE}{a["icon"]}' if a.get('icon') else '',
                            'meta': '', 'desc': ''} for a in boss_meta.values() if safe_icon(a.get('icon'))}

    def attrs(key):
        if key in ('cds', 'ext'):  # a group's header: hidden with its dropdown's last box (PAGE_JS)
            return f' data-kgroup="{key}"'
        return f' data-k="{key}"' + (' hidden' if key not in on else '') if key and key != 'abilities' else ''
    labels = ''.join(label.replace('<div ', f'<div{attrs(key)} ', 1) for label, _, _, key in lanes)
    tracks = ''.join(f'<div class="tl-row {cls}"{attrs(key)}>{body}</div>' for _, cls, body, key in lanes)
    return f"""<div class="tl focus-tl" data-duration="{duration}" data-remember="focus">
        <div class="tl-chips tl-dds">{chips}</div>
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


# ============================================================================
# Cards (one per kind of add)
# ============================================================================

def _overlap(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def _share_bar(you, raid, color):
    """Your share of your damage as a bar, the top DPS's as a tick on it."""
    return (f'<div class="fshare" style="--c:{color}" title="You {_pct(you)} · top DPS {_pct(raid)}">'
            f'<b style="width:{min(100, 100 * you):.1f}%"></b><i style="left:{min(100, 100 * raid):.1f}%"></i></div>')


def _react_chip(ms):
    if ms is None:
        return '<span class="fchip bad">never hit</span>'
    return f'<span class="fchip {_react_band(ms)}" title="Your first hit after it appeared">{ms / 1000:.1f} s</span>'


def _pot_chip(found):
    if not found:
        return '<span class="fchip none">no potion</span>'
    return (f'<span class="fchip pot" title="{esc(found[0].get("ability") or "Potion")} at {_clock(found[0]["t"])}">'
            f'🧪 {found[1]:+.1f} s</span>')


def _potion_strip(w, found):
    """The spawn's window with the potion's buff over it: when you pressed it against when the add appeared."""
    end, _ = _ends(w)
    if not found:
        return ''
    pot = found[0]
    buff_end = pot.get('end') or pot['t'] + 30000
    lo, hi = min(pot['t'], w['start']) - 2000, max(end, buff_end) + 1000
    span = max(1, hi - lo)

    def x(t):
        return f'{100 * (t - lo) / span:.2f}%'
    covered = _overlap(pot['t'], buff_end, w['start'], end) / max(1, end - w['start'])
    return f"""
        <div class="fpstrip" title="Potion buff {_clock(pot['t'])}–{_clock(buff_end)} · add up {_clock(w['start'])}–{fmt_duration(end)}">
            <i class="fp-add" style="left:{x(w['start'])};width:calc({x(end)} - {x(w['start'])})"></i>
            <i class="fp-buff" style="left:{x(pot['t'])};width:calc({x(buff_end)} - {x(pot['t'])})"></i>
            <i class="fp-press" style="left:{x(pot['t'])}"></i><i class="fp-appear" style="left:{x(w['start'])}"></i>
        </div>
        <div class="fp-legend"><span><i class="fp-buff"></i>potion buff</span><span><i class="fp-add"></i>add up</span>
            <span>pressed <b>{_lead_text(found[1])}</b> · buff covered <b>{_pct(covered)}</b> of it</span></div>"""


def _spawn_pane(w, k, color, potions, cooldowns, wins):
    """One spawn of a priority add, drawn: share, DPS, reaction, the potion against it, cooldowns pressed."""
    end, how = _ends(w)
    found = potion_lead(potions, w, wins)
    peak = max(w['you_dps'], w['raid_dps']) or 1
    during = [(t, sid, name, icon) for t, sid, name, icon in cooldowns if w['start'] - 5000 <= t <= end]
    icons = ''.join(f'<img class="ability-icon" src="{esc(safe_icon(icon))}" alt="" data-spell="{sid}" '
                    f'data-tip="{esc(name)} · {_clock(t)} ({(t - w["start"]) / 1000:+.1f} s)">'
                    for t, sid, name, icon in during if safe_icon(icon))
    return f"""
        <p class="muted small">#{k}: appeared <b>{_clock(w['start'])}</b>, {how} {fmt_duration(end)}
           ({(end - w['start']) / 1000:.0f} s up)</p>
        <div class="fstats">
            <div><span>Reaction</span>{_react_chip(w['first_hit'])}</div>
            <div><span>Potion</span>{_pot_chip(found)}</div>
        </div>
        <div class="fmetric"><span>Share of your damage</span>{_share_bar(w['you_share'], w['raid_share'], color)}
            <em>you {_pct(w['you_share'])} · top DPS {_pct(w['raid_share'])}</em></div>
        <div class="fmetric"><span>DPS on it</span>
            <div class="fdps"><b style="width:{100 * w['you_dps'] / peak:.1f}%;--c:{color}"></b>
                <i style="width:{100 * w['raid_dps'] / peak:.1f}%"></i></div>
            <em>you {fmt_amount(w['you_dps'])} · top DPS {fmt_amount(w['raid_dps'])} each</em></div>
        {_potion_strip(w, found)}
        {f'<div class="fmetric"><span>Cooldowns during it</span><div class="fcds">{icons}</div></div>' if icons else ''}"""


def _dropdown(key, label, items):
    """
    A group as a dropdown chip - the raid timeline's (consumables.py), same look and PAGE_JS: an All box,
    then a box per item. items: [(lane key, name to remember it by, mark html, label, count, spell id, tip, on)].
    """
    def row(k, name, mark, text, count, sid, tip, on):
        attrs = (f' data-spell="{int(sid)}"' if sid else '') + (f' data-tip="{esc(tip)}"' if tip else '')
        times = f' <span class="muted">×{count}</span>' if count else ''
        return (f'<label{attrs}><input type="checkbox" value="{esc(k)}" data-name="{esc(name)}"{" checked" if on else ""}>'
                f'{mark}<span>{esc(text)}</span>{times}</label>')
    return (f'<details class="tl-dd" data-dd="{key}"><summary><span>{label}</span><b class="tl-dd-n"></b>'
            f'<span class="tl-dd-caret">▾</span></summary><div class="tl-dd-menu">'
            f'<label class="tl-dd-all"><input type="checkbox" data-all>All</label>{"".join(row(*i) for i in items)}'
            f'</div></details>')


def _card_mark(name, color, icon, href, size=''):
    """An add card's portrait - a button showing it bigger (npc_zoom) - or its colour swatch."""
    return npc_zoom(name, icon, href, color, size) or _swatch(color)


def _priority_card(kind, color, potions, cooldowns, top_share, my_share, label, idx, wins, icon=None, href=None):
    cls, text = VERDICTS.get(kind['verdict'], ('none', '—'))
    spawns = kind['spawns']
    rows = ''.join(
        f'<div class="fsrow"><span class="fs-when">#{k} {_clock(w["start"])}</span>'
        f'{_share_bar(w["you_share"], w["raid_share"], color)}{_react_chip(w["first_hit"])}'
        f'{_pot_chip(potion_lead(potions, w, wins))}</div>' for k, w in enumerate(spawns, 1))
    leads = [f for f in (potion_lead(potions, w, wins) for w in spawns) if f]
    whole = (f'<p class="muted small">Over their whole kill the top {esc(label)} put '
             f'{_pct(top_share[kind["target"]])} of their damage into {esc(kind["target"])} - you '
             f'{_pct(my_share.get(kind["target"], 0))} of this pull.</p>' if top_share.get(kind['target']) is not None else '')
    overall = f"""
        <div class="fstats">
            <div><span>Your share</span><b>{_pct(kind['you_share'])}</b><small>top DPS {_pct(kind['raid_share'])}</small></div>
            <div><span>Reaction</span><b>{f"{kind['reaction'] / 1000:.1f} s" if kind['reaction'] is not None else '—'}</b>
                <small>median{f" · missed {kind['missed']}" if kind['missed'] else ''}</small></div>
            <div><span>Potion</span><b>{f"{leads[0][1]:+.1f} s" if leads else '—'}</b>
                <small>{'before the spawn it was for' if leads else 'none near a spawn'}</small></div>
        </div>
        <div class="fsrows"><div class="fsrow head"><span>Spawn</span><span>Your share (tick: top DPS)</span>
            <span>Reaction</span><span>Potion</span></div>{rows}</div>
        {whole}"""
    tabs = [('o', 'Overall', overall)] + [
        (str(k), f'#{k} {fmt_duration(w["start"])}', _spawn_pane(w, k, color, potions, cooldowns, wins))
        for k, w in enumerate(spawns, 1)]
    buttons = ''.join(f'<button type="button" role="tab" data-tab="{t}" aria-selected="{"true" if not i else "false"}">'
                      f'{esc(name)}</button>' for i, (t, name, _) in enumerate(tabs))
    panes = ''.join(f'<div class="fpane" data-pane="{t}"{"" if not i else " hidden"}>{body}</div>'
                    for i, (t, _, body) in enumerate(tabs))
    return f"""
        <div class="fcard prio" style="--c:{color}" id="fcard-{idx}">
            <div class="fcard-head">{_card_mark(kind['target'], color, icon, href, 'md')}<b>{esc(kind['target'])}</b>
                <span class="muted small">{len(spawns)} spawn{'s' if len(spawns) != 1 else ''}</span>
                <span class="fverdict {cls}" title="Your share of damage on it against the top DPS's, over its spawns">{text}</span></div>
            <div class="ftabs" role="tablist">{buttons}</div>
            {panes}
        </div>"""


def _compact_card(kind, color, icon=None, href=None):
    """A kind of add that isn't a priority: your share against the top DPS's, a square per spawn."""
    def square(k, w):
        band = ('bad' if w['first_hit'] is None else
                'good' if w['you_share'] >= focus.GOOD_FOCUS * w['raid_share'] else 'ok')
        hit = 'never hit it' if w['first_hit'] is None else f'first hit {w["first_hit"] / 1000:.1f} s'
        return (f'<i class="fsq {band}" data-tip="#{k} {_clock(w["start"])} · you {_pct(w["you_share"])}, '
                f'top DPS {_pct(w["raid_share"])} · {hit}"></i>')
    squares = ''.join(square(k, w) for k, w in enumerate(kind['spawns'], 1))
    return f"""
        <div class="fcard compact" style="--c:{color}">
            <div class="fcard-head">{_card_mark(kind['target'], color, icon, href, 'md')}<b>{esc(kind['target'])}</b>
                <span class="muted small">×{len(kind['spawns'])}</span></div>
            {_share_bar(kind['you_share'], kind['raid_share'], color)}
            <div class="fcompact-meta"><span>you {_pct(kind['you_share'])} · top DPS {_pct(kind['raid_share'])}</span>
                <span>{f"reaction {kind['reaction'] / 1000:.1f} s" if kind['reaction'] is not None else ''}
                {f" · missed {kind['missed']}" if kind['missed'] else ''}</span></div>
            <div class="fsqs">{squares}</div>
        </div>"""


def cards(data, color_of, potions, cooldowns, top_share, my_share, label, npc_icons=None, npc_links=None):
    """
    One card per kind of add: priorities (Overall + a tab per spawn) first, then the rest compactly.
    top_share / my_share: {target: share of all damage over the top players' kill / this pull}; npc_icons /
    npc_links: {target: portrait / Wowhead URL} - a portrait opens bigger on a click.
    """
    npc_icons, npc_links = npc_icons or {}, npc_links or {}
    wins = focus.windows(data)
    kinds = focus.add_types(wins)
    prio = [k for k in kinds if k['priority']]
    rest = [k for k in kinds if not k['priority']]
    out = ''
    if prio:
        out += ('<h4>Priority adds</h4><p class="muted small">The ones the top DPS pile into. Overall first; a tab per '
                'spawn for its reaction, potion timing and cooldowns.</p><div class="fcards prio">'
                + ''.join(_priority_card(k, color_of.get(k['target'], OTHER_COLOR), potions, cooldowns, top_share,
                                         my_share, label, i, wins, npc_icons.get(k['target']), npc_links.get(k['target']))
                         for i, k in enumerate(prio)) + '</div>')
    if rest:
        out += ('<h4>Other adds</h4><p class="muted small">Your share of your damage while they were up (the tick: the '
                'top DPS\'s), and a square per spawn - green on it, amber partly, red never hit.</p>'
                '<div class="fcards compact">' + ''.join(_compact_card(k, color_of.get(k['target'], OTHER_COLOR),
                                                                       npc_icons.get(k['target']), npc_links.get(k['target']))
                                                         for k in rest) + '</div>')
    return out


# ============================================================================
# Loading: a WoW cast bar while the pull's events come from Warcraft Logs
# ============================================================================

LOADER_ICON = 'https://wow.zamimg.com/images/wow/icons/large/inv_misc_rune_01.jpg'  # the Hearthstone
LOADER_LINES = (
    'Waiting for the tank to pull…', 'Asking Warcraft Logs nicely…', 'Counting every Venomous Heart…',
    'Lining up your potion with the spawns…', 'Checking who stood in the bad…', 'Rolling Need on your damage events…',
    'Reading the whole combat log. Every line.', 'Releasing spirit… no wait, still loading',
    'Drinking to full before the next pull…', 'Buffing the raid, one last time…',
)


def loader(number=None, text=None, what='1', compact=False):
    """
    The cast bar shown while data comes from Warcraft Logs - pull #number's focus data, or what `text` says
    (PAGE_JS: it asks the page for ?focus_load=<what>, then reloads with everything in place - or shows the
    cast as interrupted, with why). compact: a slimmer one, inside a card that shows other things meanwhile.
    """
    import json
    return f"""
        <div class="castbar-wrap{' compact' if compact else ''}" data-focus-load="{esc(what)}"
             data-lines="{esc(json.dumps(LOADER_LINES))}">
            <div class="castbar">
                <img class="cb-icon" src="{LOADER_ICON}" alt="">
                <div class="cb-bar"><i class="cb-fill"></i>
                    <span class="cb-name">{esc(text or f'Summoning pull #{number} from Warcraft Logs')}</span>
                    <span class="cb-time">0.0</span></div>
            </div>
            <p class="cb-flavor">{LOADER_LINES[0]}</p>
            <button type="button" class="btn btn-secondary btn-sm cb-retry" hidden>Recast</button>
        </div>"""
