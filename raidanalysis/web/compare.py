"""
"You vs the top players" (benchmarks.py): a verdict per major ability, and a timeline grouped by
ability - your pull on top, the top 5 parses underneath - so it's easy to see at a glance whether
you press your cooldowns, potions and defensives at the same moments they do.

The timeline has two time modes: "Align phases" (default) shifts everyone's casts onto one shared
timeline phase by phase - phases are health-based, so they start at different times for everyone -
and shades the moments most top players agree on; "Real time" shows each fight as it happened.
"""
from .. import benchmarks
from ..spells import icon_url
from .render import ICON_BASE, esc, fmt_amount, fmt_duration, json_for_script, safe_icon

VERDICTS = {'good': ('pill-kill', 'In line'), 'mostly': ('pill-mostly', 'Mostly in line'),
            'ok': ('pill', 'Hit & miss'), 'off': ('pill-wipe', 'Off'), 'missing': ('pill-wipe', 'Never used'),
            'not_equipped': ('pill-muted', '💎 Worth getting')}


def _spec_icon_class(spell_id):
    return f'sp{spell_id}'


def _verdict_pill(verdict, known=True):
    if not known:
        return '<span class="muted small" title="These pulls were analyzed before every cast was kept">re-analyze</span>'
    if not verdict:
        return '<span class="muted small">—</span>'
    cls, text = VERDICTS[verdict]
    return f'<span class="pill {cls}">{text}</span>'


def _ability(row, spells):
    info = spells.get(row['icon_id']) or {}
    icon = icon_url(info.get('icon'))
    img = f'<img class="ability-icon" src="{esc(icon)}" alt="" loading="lazy">' if icon else ''
    return f'<span class="cmp-ab" data-spell="{row["icon_id"]}">{img}{esc(row["name"])}</span>'


def _weak_line(r):
    """Under the ability: the moments to work on, so a mostly-fine verdict still shows what's left."""
    if not r.get('weak') or r['category'] not in benchmarks.JUDGED:
        return ''
    return (f'<div class="weak-line" title="Moments you line up with less than half the time - '
            f'most important (more top players there) first">⚠ {esc(benchmarks.weak_text(r["weak"]))}</div>')


ROTATION_VERDICTS = {'good': ('pill-kill', 'Often enough'), 'ok': ('pill', 'A bit low'),
                     'off': ('pill-wipe', 'Too few'), 'missing': ('pill-wipe', 'Never used')}
KIND_LABELS = {benchmarks.MAJOR: 'Major cooldown', benchmarks.ROTATIONAL: 'Keep on cooldown', benchmarks.HIDE: 'Hide'}


def major_rows(data):
    """What the cooldown comparison shows: everything that's timed (not the keep-on-cooldown abilities)."""
    return [r for r in data['rows'] if r['category'] != benchmarks.ROTATIONAL]


def _trinket_line(r):
    """A trinket the top players use and you don't have: loot luck, so a tip rather than a verdict."""
    if r.get('verdict') != 'not_equipped':
        return ''
    return (f'<div class="muted small" style="margin:3px 0 0 24px">💎 {r["top_users"]} of the top players use it - '
            f'worth getting if it drops</div>')


def rotational_rows(data):
    return [r for r in data['rows'] if r['category'] == benchmarks.ROTATIONAL]


def kind_form(r, player, back):
    """Officers: is this a major cooldown, one to keep on cooldown, or not worth showing - for the whole spec."""
    auto = KIND_LABELS.get(r.get('auto_kind'), '')
    options = ''.join(f'<option value="{k}"{" selected" if r.get("overridden") and r["kind"] == k else ""}>{label}</option>'
                      for k, label in KIND_LABELS.items())
    return (f'<form method="post" action="/admin/raids/spec-ability" class="tag-form">'
            f'<input type="hidden" name="class" value="{esc(player.get("class") or "")}">'
            f'<input type="hidden" name="spec" value="{esc(player.get("spec") or "")}">'
            f'<input type="hidden" name="ability_name" value="{esc(r["name"])}">'
            f'<input type="hidden" name="back" value="{esc(back)}">'
            f'<select name="kind" class="kind-select" onchange="this.form.submit()" title="For every {esc(benchmarks.spec_label(player))} '
            f'(officers only)"><option value=""{"" if r.get("overridden") else " selected"}>Auto ({esc(auto)})</option>'
            f'{options}</select></form>')


def _pull_lined_up(r, pull):
    """(moments in line, moments reached) for one pull - the same rule compare() uses for the night."""
    ids = set(r['ids'])
    lengths = benchmarks.segment_lengths(pull['phases'], pull['duration'])
    mine = [benchmarks.segment_of(t, pull['phases']) for t, sid in pull['casts'] if sid in ids]
    hits = considered = 0
    for w in r['windows']:
        if w['segment'] not in lengths or w['at'] > lengths[w['segment']]:
            continue
        considered += 1
        hits += any(key == w['segment'] and abs(into - w['at']) <= w['tolerance'] for key, into in mine)
    return hits, considered


def summary(data, back=None):
    """
    One row per major ability: top usage, yours, how many top-player moments you hit, verdict.
    back: the page to return to after an officer re-sorts an ability (adds the Kind control).
    """
    rows = []
    for r in major_rows(data):
        moments = (f'{r["hits"]} / {r["considered"]}' if r['considered'] else
                   '<span class="muted">—</span>')
        top_when = ', '.join(fmt_duration(w['ref_at']) for w in r['windows'][:5]) or '<span class="muted">no shared moment</span>'
        rows.append(f"""
            <tr class="{'' if r['category'] in benchmarks.JUDGED else 'muted-row'}">
                <td>{_ability(r, data['spells'])}{_weak_line(r)}{_trinket_line(r)}</td>
                <td class="small muted">{esc(benchmarks.CATEGORY_LABELS.get(r['category'], ''))}
                    {kind_form(r, data['player'], back) if back and r['category'] in (benchmarks.THROUGHPUT, benchmarks.TRINKET) else ''}</td>
                <td class="num" data-v="{r['top_per_min']:.3f}">{r['top_per_min'] * 5:.1f}
                    <span class="muted small">({r['top_users']}/{len(data['top'])})</span></td>
                <td class="num" data-v="{r['ours_per_min']:.3f}">{r['ours_per_min'] * 5:.1f}</td>
                <td class="small">{top_when}</td>
                <td class="num">{moments}</td>
                <td class="small{' bad-text' if benchmarks.timing_text(r['offset']) not in ('', 'on time') and r['verdict'] in ('off', 'ok') else ''}">{benchmarks.timing_text(r['offset']) or '<span class="muted">—</span>'}</td>
                <td>{_verdict_pill(r['verdict'], r['known']) if r['category'] in benchmarks.JUDGED else '<span class="muted small">info</span>'}</td>
            </tr>""")
    return f"""<div class="table-wrapper"><table class="compact">
        <tr><th data-sort>Ability</th><th>Kind</th>
            <th data-sort class="num" title="Casts per 5 minutes of fight (how many of the top 5 use it)">Top / 5 min</th>
            <th data-sort class="num" title="Your casts per 5 minutes, over this night's pulls on the boss">You / 5 min</th>
            <th title="Moments (on the aligned timeline) where at least 3 of the top 5 press it">Top players press it at</th>
            <th class="num" title="Of those moments your pulls reached, how many you pressed it within their margin">Lined up</th>
            <th title="Your nearest cast to each moment, typically (median)">Usually</th>
            <th>Verdict</th></tr>
        {''.join(rows)}</table></div>"""


def rotation_tiles(data, back=None):
    """
    The keep-on-cooldown abilities as WowAnalyzer-style tiles: casts per minute next to the top players'
    (their timing doesn't matter, only that it's rolling). back adds the officers' Kind control.
    """
    tiles = []
    for r in rotational_rows(data):
        share = r['ours_per_min'] / r['top_per_min'] if r['top_per_min'] else 0
        band = {'good': 'good', 'ok': 'ok'}.get(r['verdict'], 'bad')
        cls, text = ROTATION_VERDICTS.get(r['verdict'], ('pill-muted', '—'))
        pill = f'<span class="pill {cls}">{text}</span>' if r['known'] else _verdict_pill(None, False)
        cooldown = f' · {r["cooldown_ms"] / 1000:.0f} s cooldown' if r.get('cooldown_ms') else ''
        tiles.append(f"""
            <div class="rot-tile">
                <div class="rot-head">{_ability(r, data['spells'])}{pill}</div>
                <div class="rot-value"><b>{r['ours_per_min']:.1f}</b><span>casts / min</span></div>
                <div class="subscore-track" title="{100 * share:.0f}% of the top players' rate">
                    <div class="subscore-fill {band}" style="width:{min(100, 100 * share):.0f}%"></div></div>
                <div class="muted small">Top {r['top_users']}/{len(data['top'])}: {r['top_per_min']:.1f} / min{cooldown}</div>
                {kind_form(r, data['player'], back) if back else ''}
            </div>""")
    if not tiles:
        return ''
    return f'<div class="rot-tiles">{"".join(tiles)}</div>'


def timeline(data, pull, boss=None, spell_lookup=None):
    """
    Grouped by ability: a header lane with the shared moments, then You and the top 5 underneath -
    under the boss's abilities from your pull (boss = {'abilities', 'casts'} from its analysis), so
    you can see what a cooldown was lined up against. spell_lookup(ids) -> Wowhead text (spells.lookup).
    """
    top, rows, spells = data['top'], major_rows(data), data['spells']
    ref = benchmarks.reference_starts(top)
    boss = boss or {}
    boss_meta = {a['id']: a for a in boss.get('abilities') or []}
    boss_casts = [(t, sid) for t, sid in boss.get('casts') or [] if sid in boss_meta]
    lanes = [{'label': f'You · pull #{pull["number"]}', 'you': True, 'duration': pull['duration'],
              'phases': pull['phases'], 'casts': pull['casts'],
              'who': f'You (pull #{pull["number"]}, {fmt_duration(pull["duration"])}'
                     f'{" kill" if pull.get("kill") else ""})'}]
    for p in top:
        lanes.append({'label': f'#{p["rank"]} {p["name"]}', 'you': False, 'duration': p['duration'],
                      'phases': p['phases'], 'casts': p['casts'],
                      'who': f'#{p["rank"]} {p["name"]} ({fmt_amount(p["amount"])} · {fmt_duration(p["duration"])} kill)'})
    for lane in lanes:
        lane['aligned'] = [(benchmarks.align(t, lane['phases'], ref), t, sid) for t, sid in lane['casts']]
    boss_aligned = [(benchmarks.align(t, pull['phases'], ref), t, sid) for t, sid in boss_casts]
    longest = max([lane['duration'] for lane in lanes]
                  + [a for lane in lanes for a, _, _ in lane['aligned']] + [a for a, _, _ in boss_aligned] + [1])

    def at(t):
        return f'{100 * max(0, min(t, longest)) / longest:.3f}%'

    labels, tracks, chips, icons = [], [], [], {}
    # Boss abilities from your pull on top (one lane per ability name, like the consumables timeline).
    boss_spells = {}
    if boss_aligned:
        chips.append('<button type="button" class="tl-chip" data-g="boss" data-name="boss" aria-pressed="true">'
                     '👹 Boss abilities</button>')
        labels.append(f'<div class="tl-lab grp" data-g="boss"><span>👹 Boss · your pull #{pull["number"]}</span></div>')
        tracks.append('<div class="tl-row grp" data-g="boss"></div>')
        by_name = {}
        for a, t, sid in boss_aligned:
            by_name.setdefault(boss_meta[sid]['name'], []).append((a, t, sid))
        for name, casts in sorted(by_name.items(), key=lambda kv: min(t for _, t, _ in kv[1])):
            first = casts[0][2]
            for _, _, sid in casts:
                boss_spells.setdefault(sid, (name, boss_meta[sid].get('icon')))
            icon = boss_meta[first].get('icon')
            img = f'<img class="ability-icon" src="{ICON_BASE}{esc(icon)}" alt="" loading="lazy">' if icon else ''
            labels.append(f'<div class="tl-lab boss" data-g="boss" data-spell="{first}" '
                          f'data-tip="Cast {len(casts)}× in your pull #{pull["number"]}">{img}<span>{esc(name)}</span></div>')
            ticks = ''.join(f'<i class="m tick" style="left:{at(a)}" data-a="{at(a)}" data-r="{at(t)}" '
                            f'data-spell="{sid}" data-tip="Your pull #{pull["number"]} · {fmt_duration(t)}"></i>'
                            for a, t, sid in sorted(casts))
            tracks.append(f'<div class="tl-row boss" data-g="boss">{ticks}</div>')
    for g, r in enumerate(rows):
        ids = set(r['ids'])
        judged = r['category'] in benchmarks.JUDGED
        hidden = '' if judged else ' hidden'
        info = spells.get(r['icon_id']) or {}
        if info.get('icon'):
            icons[r['icon_id']] = icon_url(info['icon'])
        chip_icon = icons.get(r['icon_id'])
        chips.append(f'<button type="button" class="tl-chip" data-g="{g}" data-name="{esc(r["name"])}" '
                     f'aria-pressed="{"true" if judged else "false"}">'
                     + (f'<img class="chip-icon" src="{esc(chip_icon)}" alt="">' if chip_icon else '')
                     + f'{esc(r["name"])}</button>')
        weak_at = {m['ref_at'] for m in r.get('weak') or []}
        bands = ''.join(f'<i class="win{" weak" if w["ref_at"] in weak_at else ""}" style="left:{at(w["ref_at"] - w["tolerance"])};'
                        f'width:{100 * 2 * w["tolerance"] / longest:.3f}%" '
                        f'data-tip="{w["players"]} of the top {len(top)} press it around {fmt_duration(w["ref_at"])} '
                        f'(in line = within ±{w["tolerance"] / 1000:.0f} s)'
                        f'{" - one you usually miss" if w["ref_at"] in weak_at else ""}"></i>'
                        for w in r['windows'])
        shown = _pull_lined_up(r, pull) if judged and r['verdict'] != 'not_equipped' else None
        this_pull = (f'<span class="pull-score" title="Moments in line in the pull shown (the verdict covers '
                     f'the whole night)">this pull {shown[0]}/{shown[1]}</span>' if shown and shown[1] else '')
        labels.append(f'<div class="tl-lab grp" data-g="{g}"{hidden}>{_ability(r, spells)}'
                      f'<span class="grp-right">{this_pull}{_verdict_pill(r["verdict"], r["known"]) if judged else ""}</span></div>')
        tracks.append(f'<div class="tl-row grp" data-g="{g}"{hidden}>{bands}</div>')
        for lane in lanes:
            marks = []
            for a, t, sid in lane['aligned']:
                if sid not in ids:
                    continue
                if (spells.get(sid) or {}).get('icon'):
                    icons.setdefault(sid, icon_url(spells[sid]['icon']))
                seg, into = benchmarks.segment_of(t, lane['phases'])
                where = f' (phase segment {seg[0] + 1} +{fmt_duration(into)})' if len(lane['phases']) > 1 else ''
                marks.append(f'<i class="m cd {_spec_icon_class(sid if sid in icons else r["icon_id"])}" '
                             f'style="left:{at(a)}" data-a="{at(a)}" data-r="{at(t)}" data-spell="{sid}" '
                             f'data-tip="{esc(lane["who"])} · {fmt_duration(t)}{where}"></i>')
            phase_ticks = ''.join(f'<i class="ph rl" style="left:{at(p["start"])}"></i>' for p in lane['phases'][1:])
            labels.append(f'<div class="tl-lab{" you" if lane["you"] else ""}" data-g="{g}"{hidden}>{esc(lane["label"])}</div>')
            tracks.append(f'<div class="tl-row lane{" you" if lane["you"] else ""}" data-g="{g}"{hidden}>'
                          f'{phase_ticks}{"".join(marks)}</div>')
    phases = ''.join(f'<i class="tl-phase al" style="left:{at(start)}"></i>'
                     for key, start in sorted(ref.items()) if start > 0)
    grid = ''.join(f'<i style="left:{at(t)}"></i>' for t in range(0, longest + 1, 60000))
    ruler = ''.join(f'<span{" class=first" if not t else ""} style="left:{at(t)}">{fmt_duration(t)}</span>'
                    for t in range(0, longest + 1, 60000))
    icon_css = ''.join(f'.{_spec_icon_class(int(sid))}{{background-image:url({safe_icon(url)})}}'
                       for sid, url in icons.items() if safe_icon(url))
    spell_json = {sid: {'name': info.get('name') or '', 'icon': icon_url(info.get('icon')), 'meta': info.get('meta') or '',
                        'desc': info.get('description') or ''} for sid, info in spells.items()}
    known = spell_lookup(list(boss_spells)) if spell_lookup and boss_spells else {}
    for sid, (name, icon) in boss_spells.items():
        info = known.get(sid) or {}
        spell_json[sid] = {'name': info.get('name') or name, 'icon': f'{ICON_BASE}{icon}' if icon else icon_url(info.get('icon')),
                           'meta': info.get('meta') or '', 'desc': info.get('description') or ''}
    has_phases = len(ref) > 1
    return f"""<div class="tl cmp-tl" data-duration="{longest}" data-remember="cooldowns">
        <style>{icon_css}</style>
        <div class="tl-chips">{''.join(chips)}</div>
        <div class="tl-tools">
            {'<span class="seg"><button type="button" data-mode="aligned" data-name="mode:aligned" aria-pressed="true">'
             'Align phases</button><button type="button" data-mode="real" data-name="mode:real" aria-pressed="false">'
             'Real time</button></span>' if has_phases else ''}
            <span class="muted small">Drag to pan · Ctrl + scroll or pinch to zoom</span>
            <button type="button" data-zoom="out" title="Zoom out">−</button>
            <input type="range" min="0" max="100" value="0" aria-label="Zoom">
            <button type="button" data-zoom="in" title="Zoom in">+</button>
            <button type="button" data-zoom="fit" title="Show the whole fight">Fit</button></div>
        <div class="tl-body">
            <div class="tl-labels">{''.join(labels)}<div class="tl-ruler-gap"></div></div>
            <div class="tl-scroll"><div class="tl-inner">
                <div class="tl-grid">{grid}</div>{phases}
                {''.join(tracks)}
                <div class="tl-ruler">{ruler}</div>
                <div class="tl-head" hidden><span></span></div>
            </div></div>
        </div>
        <script type="application/json" class="spell-data">{json_for_script(spell_json)}</script>
    </div>"""


def top_players(data):
    items = []
    for p in data['top']:
        where = ' · '.join(x for x in (p.get('guild'), f"{p.get('server')}-{p.get('region')}".strip('-')) if x)
        spec = f' · {esc(benchmarks.readable(p["spec"]))}' if p.get('spec') else ''
        items.append(f'<li><strong>#{p["rank"]} {esc(p["name"])}</strong>{spec} <span class="muted small">{esc(where)}</span> — '
                     f'{fmt_amount(p["amount"])} {esc((data["benchmark"] or {}).get("metric") or "dps").upper()} · '
                     f'{fmt_duration(p["duration"])} kill · <a href="https://www.warcraftlogs.com/reports/{esc(p["code"])}'
                     f'#fight={p["fight_id"]}" target="_blank" rel="noopener">log ↗</a></li>')
    return f'<ul class="top-list">{"".join(items)}</ul>'
