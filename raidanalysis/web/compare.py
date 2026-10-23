"""
"You vs the top players" (benchmarks.py): a verdict per major ability, and a timeline grouped by
ability - your pull on top, the top 5 parses underneath - so it's easy to see at a glance whether
you press your cooldowns, potions and defensives at the same moments they do.

The timeline has two time modes: "Align phases" (default) shifts everyone's casts onto one shared
timeline phase by phase - phases are health-based, so they start at different times for everyone -
and shades the moments most top players agree on; "Real time" shows each fight as it happened.
"""
from .. import benchmarks, cooldowns, forms
from ..spells import icon_url
from .consumables import LUST as LUST_COLOR
from .render import ICON_BASE, esc, fmt_amount, fmt_duration, json_for_script, safe_icon

VERDICTS = {'good': ('pill-kill', 'In line'), 'mostly': ('pill-mostly', 'Mostly in line'),
            'ok': ('pill', 'Hit & miss'), 'off': ('pill-wipe', 'Off'), 'missing': ('pill-wipe', 'Never used'),
            'not_equipped': ('pill-muted', '💎 Worth getting'), 'not_taken': ('pill-muted', 'Not talented?')}
NOT_TAKEN_TIP = ("You never pressed it on any of these pulls - most likely a talent you didn't take, so it "
                 "isn't judged")


def hero_hint(data):
    """No top players of their hero tree (yet): these are the whole spec's, whichever tree they play - and why."""
    if not (data or {}).get('hero') or not data.get('benchmark') or data['benchmark'].get('hero'):
        return ''
    who = esc(benchmarks.spec_label(data['player'], data['hero']))
    why = {'empty': f"Warcraft Logs has no public top parses of {who} on this boss yet (tried again daily)",
           'error': f"Fetching the top {who} on this boss failed (tried again in a few hours)"}.get(
        data.get('hero_status'), f"The top {who} on this boss haven't been fetched yet (the sync gets them within a "
                                 f"day or so)")
    return (f'<p class="small warn-text">⚠️ {why}, so these are the top of the whole spec, on either hero tree - '
            f'abilities only the other tree has can show up.</p>')


def _spec_icon_class(spell_id):
    return f'sp{spell_id}'


def _verdict_pill(verdict, known=True):
    if not known:
        return '<span class="muted small" title="These pulls were analyzed before every cast was kept">re-analyze</span>'
    if not verdict:
        return '<span class="muted small">—</span>'
    cls, text = VERDICTS[verdict]
    tip = f' title="{NOT_TAKEN_TIP}"' if verdict == 'not_taken' else ''
    return f'<span class="pill {cls}"{tip}>{text}</span>'


def judged(r):
    """
    Judged against the top players: what you control alone, not a talent you didn't take, and something enough of
    them press to compare with (few_top: one of your cooldowns they mostly don't take - shown, not judged).
    """
    return r['category'] in benchmarks.JUDGED and r.get('verdict') != 'not_taken' and not r.get('few_top')


def _few_top(r, data):
    """A cooldown of yours too few of the top players press to judge: says so in place of a verdict."""
    tip = (f"Fewer than {benchmarks.MIN_AGREE} of the top {len(data['top'])} use it, so there's nothing to line it "
           f"up with - shown so you can see your own use, not judged")
    return f'<span class="muted small" title="{esc(tip)}">only {r["top_users"]} of top {len(data["top"])}</span>'


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
                     'off': ('pill-wipe', 'Too few'), 'missing': ('pill-wipe', 'Never used'),
                     'not_taken': ('pill-muted', 'Not talented?')}
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
            <tr class="{'' if judged(r) else 'muted-row'}">
                <td>{_ability(r, data['spells'])}{_weak_line(r)}{_trinket_line(r)}</td>
                <td class="small muted">{esc(benchmarks.CATEGORY_LABELS.get(r['category'], ''))}
                    {kind_form(r, data['player'], back) if back and r['category'] in (benchmarks.THROUGHPUT, benchmarks.TRINKET) else ''}</td>
                <td class="num" data-v="{r['top_per_min']:.3f}">{r['top_per_min'] * 5:.1f}
                    <span class="muted small">({r['top_users']}/{len(data['top'])})</span></td>
                <td class="num" data-v="{r['ours_per_min']:.3f}">{r['ours_per_min'] * 5:.1f}</td>
                <td class="small">{top_when}</td>
                <td class="num">{moments}</td>
                <td class="small{' bad-text' if benchmarks.timing_text(r['offset']) not in ('', 'on time') and r['verdict'] in ('off', 'ok') else ''}">{benchmarks.timing_text(r['offset']) or '<span class="muted">—</span>'}</td>
                <td>{_few_top(r, data) if r.get('few_top') else _verdict_pill(r['verdict'], r['known']) if r['category'] in benchmarks.JUDGED else '<span class="muted small">info</span>'}</td>
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
    # A talent you didn't take goes last, dimmed: shown (so it's clear it was noticed), not judged
    for r in sorted(rotational_rows(data), key=lambda r: r['verdict'] == 'not_taken'):
        not_taken = r['verdict'] == 'not_taken'
        share = r['ours_per_min'] / r['top_per_min'] if r['top_per_min'] else 0
        band = 'neutral' if not_taken else {'good': 'good', 'ok': 'ok'}.get(r['verdict'], 'bad')
        cls, text = ROTATION_VERDICTS.get(r['verdict'], ('pill-muted', '—'))
        tip = f' title="{NOT_TAKEN_TIP}"' if not_taken else ''
        pill = f'<span class="pill {cls}"{tip}>{text}</span>' if r['known'] else _verdict_pill(None, False)
        cooldown = f' · {r["cooldown_ms"] / 1000:.0f} s cooldown' if r.get('cooldown_ms') else ''
        tiles.append(f"""
            <div class="rot-tile{' not-taken' if not_taken else ''}">
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
    Every lane shows where its fight ended (a skull for a kill, hatched after it: a faster kill is why
    someone has no casts left there) and, with the Bloodlust chip, when their raid lusted.
    """
    top, rows, spells = data['top'], major_rows(data), data['spells']
    ref = benchmarks.reference_starts(top)
    boss = boss or {}
    boss_meta = {a['id']: a for a in boss.get('abilities') or []}
    boss_casts = [(t, sid) for t, sid in boss.get('casts') or [] if sid in boss_meta]
    form = (data.get('form') or {}).get('form')
    lanes = [{'label': f'You · pull #{pull["number"]}', 'you': True, 'duration': pull['duration'],
              'phases': pull['phases'], 'casts': pull['casts'], 'kill': pull.get('kill'), 'form': pull.get('form'),
              'lust': [(s, e, sid, f'{ability} by {who}') for s, e, sid, ability, who in pull.get('lust') or []],
              'who': f'You (pull #{pull["number"]}, {fmt_duration(pull["duration"])}'
                     f'{" kill" if pull.get("kill") else ""})'}]
    for p in top:
        lanes.append({'label': f'#{p["rank"]} {p["name"]}', 'you': False, 'duration': p['duration'],
                      'phases': p['phases'], 'casts': p['casts'], 'kill': True,
                      'form': (p.get('forms') or {}).get(form['name']) if form else None,
                      'lust': [(s, e, sid, cooldowns.LUST_IDS.get(sid, 'Bloodlust')) for s, e, sid in p.get('lust') or []],
                      'who': f'#{p["rank"]} {p["name"]} ({fmt_amount(p["amount"])} · {fmt_duration(p["duration"])} kill)'})
    for lane in lanes:
        lane['aligned'] = [(benchmarks.align(t, lane['phases'], ref), t, sid) for t, sid in lane['casts']]
        lane['end'] = benchmarks.align(lane['duration'], lane['phases'], ref)
    boss_aligned = [(benchmarks.align(t, pull['phases'], ref), t, sid) for t, sid in boss_casts]
    longest = max([lane['duration'] for lane in lanes] + [lane['end'] for lane in lanes]
                  + [a for lane in lanes for a, _, _ in lane['aligned']] + [a for a, _, _ in boss_aligned] + [1])

    def at(t):
        return f'{100 * max(0, min(t, longest)) / longest:.3f}%'

    def placed(cls, aligned, real, extra=''):  # a mark at its aligned spot, moved to `real` by Real time (PAGE_JS)
        return f'<i class="m {cls}" style="left:{at(aligned)}{extra}" data-a="{at(aligned)}" data-r="{at(real)}"'

    def lane_overlay(lane):
        """(under its casts, over them): a lane's lusts (the Bloodlust chip shows them), hatching after its end, its end."""
        lust = ''.join(placed('lust', benchmarks.align(s, lane['phases'], ref), s, f';width:{100 * (e - s) / longest:.3f}%')
                       + f' data-spell="{sid}" data-tip="{esc(lane["who"])} · {esc(what)} · {fmt_duration(s)}–'
                         f'{fmt_duration(e)} ({(e - s) / 1000:.0f} s)"></i>'
                       for s, e, sid, what in lane['lust'])
        ended = (f'Boss killed at {fmt_duration(lane["duration"])} - nothing left to press after this'
                 if lane['kill'] else f'Pull ended (wipe) at {fmt_duration(lane["duration"])}')
        after = placed('after', lane['end'], lane['duration']) + '></i>'
        fin = (placed('fin kill' if lane['kill'] else 'fin', lane['end'], lane['duration'])
               + f' data-tip="{esc(lane["who"])} · {esc(ended)}">{"💀" if lane["kill"] else "✕"}</i>')
        return lust + after, fin

    for lane in lanes:
        lane['under'], lane['fin'] = lane_overlay(lane)

    labels, tracks, chips, icons = [], [], [], {}
    if any(lane['lust'] for lane in lanes):
        missing = '' if all('lust' in p for p in top) else (" The top players' shows once their parses are "
                                                            "fetched again (within a few days).")
        chips.append(f'<button type="button" class="tl-chip" data-lust data-name="lust" aria-pressed="false" '
                     f'data-tip="When each raid lusted (Bloodlust, Heroism, Time Warp, Primal Rage, Fury of the '
                     f'Aspects) and for how long, on every lane.{missing}"><i style="--c:{LUST_COLOR}"></i>Bloodlust</button>')
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
    if form and any(lane['form'] for lane in lanes):
        chips.append(f'<button type="button" class="tl-chip" data-g="form" data-name="form:{esc(form["name"])}" '
                     f'aria-pressed="true"><img class="chip-icon" src="{ICON_BASE}{esc(form["icon"])}" alt="">'
                     f'{esc(form["name"])}</button>')
        labels.append(_form_label(form, pull))
        tracks.append('<div class="tl-row grp" data-g="form"></div>')
        for lane in lanes:
            labels.append(_lane_label(lane, 'form', ''))
            tracks.append(f'<div class="tl-row lane{" you" if lane["you"] else ""}" data-g="form">'
                          f'{lane["under"]}{_form_marks(form, lane, placed, ref, longest)}{lane["fin"]}</div>')
    for g, r in enumerate(rows):
        ids = set(r['ids'])
        on = judged(r)  # anything else starts hidden - its chip shows it
        hidden = '' if on else ' hidden'
        info = spells.get(r['icon_id']) or {}
        if info.get('icon'):
            icons[r['icon_id']] = icon_url(info['icon'])
        chip_icon = icons.get(r['icon_id'])
        chips.append(f'<button type="button" class="tl-chip" data-g="{g}" data-name="{esc(r["name"])}" '
                     f'aria-pressed="{"true" if on else "false"}">'
                     + (f'<img class="chip-icon" src="{esc(chip_icon)}" alt="">' if chip_icon else '')
                     + f'{esc(r["name"])}</button>')
        weak_at = {m['ref_at'] for m in r.get('weak') or []}
        bands = ''.join(f'<i class="win{" weak" if w["ref_at"] in weak_at else ""}" style="left:{at(w["ref_at"] - w["tolerance"])};'
                        f'width:{100 * 2 * w["tolerance"] / longest:.3f}%" '
                        f'data-tip="{w["players"]} of the top {len(top)} press it around {fmt_duration(w["ref_at"])} '
                        f'(in line = within ±{w["tolerance"] / 1000:.0f} s)'
                        f'{" - one you usually miss" if w["ref_at"] in weak_at else ""}"></i>'
                        for w in r['windows'])
        shown = _pull_lined_up(r, pull) if on and r['verdict'] != 'not_equipped' else None
        this_pull = (f'<span class="pull-score" title="Moments in line in the pull shown (the verdict covers '
                     f'the whole night)">this pull {shown[0]}/{shown[1]}</span>' if shown and shown[1] else '')
        labels.append(f'<div class="tl-lab grp" data-g="{g}"{hidden}>{_ability(r, spells)}'
                      f'<span class="grp-right">{this_pull}{_verdict_pill(r["verdict"], r["known"]) if on else ""}</span></div>')
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
            labels.append(_lane_label(lane, g, hidden))
            tracks.append(f'<div class="tl-row lane{" you" if lane["you"] else ""}" data-g="{g}"{hidden}>'
                          f'{phase_ticks}{lane["under"]}{"".join(marks)}{lane["fin"]}</div>')
    phases = ''.join(f'<i class="tl-phase al" style="left:{at(start)}"></i>'
                     for key, start in sorted(ref.items()) if start > 0)
    grid = ''.join(f'<i style="left:{at(t)}"></i>' for t in range(0, longest + 1, 60000))
    ruler = ''.join(f'<span{" class=first" if not t else ""} style="left:{at(t)}">{fmt_duration(t)}</span>'
                    for t in range(0, longest + 1, 60000))
    icon_css = ''.join(f'.{_spec_icon_class(int(sid))}{{background-image:url({safe_icon(url)})}}'
                       for sid, url in icons.items() if safe_icon(url))
    spell_json = {sid: {'name': info.get('name') or '', 'icon': icon_url(info.get('icon')), 'meta': info.get('meta') or '',
                        'desc': info.get('description') or ''} for sid, info in spells.items()}
    if form:
        spell_json[form['buff_ids'][0]] = {'name': form['name'], 'icon': ICON_BASE + form['icon'], 'meta': '',
                                           'desc': f"A burst form: no cooldown, no cast in the log - each bar is one "
                                                   f"stretch in it, ★ the {form['spender']} casts inside"}
    known = spell_lookup(list(boss_spells)) if spell_lookup and boss_spells else {}
    for sid, (name, icon) in boss_spells.items():
        info = known.get(sid) or {}
        spell_json[sid] = {'name': info.get('name') or name, 'icon': f'{ICON_BASE}{icon}' if icon else icon_url(info.get('icon')),
                           'meta': info.get('meta') or '', 'desc': info.get('description') or ''}
    has_phases = len(ref) > 1
    return f"""<div class="tl cmp-tl" data-duration="{longest}" data-remember="cooldowns" style="--lust:{LUST_COLOR}">
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


def _lane_label(lane, g, hidden):
    return (f'<div class="tl-lab{" you" if lane["you"] else ""}" data-g="{g}"{hidden}>'
            f'<span>{esc(lane["label"])}</span><small class="fin-t" data-tip="'
            f'{"Boss killed" if lane["kill"] else "Wiped"} at {fmt_duration(lane["duration"])}">'
            f'{fmt_duration(lane["duration"])}</small></div>')


def _form_label(form, pull):
    """The burst form's header on the timeline: its name, and this pull's windows and spends per window."""
    wins = forms.windows(pull.get('form'))
    spends = sum(len(w['spends']) for w in wins)
    if wins:
        this_pull = (f'<span class="pull-score" title="In the pull shown">this pull {len(wins)}× · '
                     f'{spends / len(wins):.1f} ★ each</span>')
    elif pull.get('form') is None:
        this_pull = '<span class="pull-score">not fetched for this pull yet</span>'
    else:
        this_pull = '<span class="pull-score">never this pull</span>'
    return (f'<div class="tl-lab grp" data-g="form"><span class="cmp-ab" data-spell="{form["buff_ids"][0]}">'
            f'<img class="ability-icon" src="{ICON_BASE}{esc(form["icon"])}" alt="" loading="lazy">'
            f'{esc(form["name"])}</span><span class="grp-right">{this_pull}</span></div>')


def _form_marks(form, lane, placed, ref, longest):
    """One lane's stretches in the form: a bar each with its spender count, and a tick per spender cast."""
    out = []
    spender = form['spender']
    for w in forms.windows(lane['form']):
        n = len(w['spends'])
        start = benchmarks.align(w['start'], lane['phases'], ref)
        width = 100 * (w['end'] - w['start']) / longest
        out.append(placed('fwin', start, w['start'], f';width:{width:.3f}%')
                   + f' data-tip="{esc(lane["who"])} · {esc(form["name"])} {fmt_duration(w["start"])}–'
                     f'{fmt_duration(w["end"])} ({(w["end"] - w["start"]) / 1000:.0f} s) · {n} {esc(spender)}'
                     f'{"s" if n != 1 else ""}"><span>{n}★</span></i>')
        out += [placed('tick fspend', benchmarks.align(t, lane['phases'], ref), t)
                + f' data-tip="{esc(spender)} · {fmt_duration(t)}"></i>' for t in w['spends']]
    return ''.join(out)


def form_summary(data):
    """
    The spec's burst form (forms.py - a Devourer's Void Metamorphosis) over tonight's pulls, next to the top players:
    how often they go in, how long it lasts, how much of the fight it's up and the spends in each window.
    """
    found = data.get('form')
    if not found:
        return ''
    form, ours, top = found['form'], found['ours'], found['top']
    intro = (f'<p class="muted small"><img class="ability-icon" src="{ICON_BASE}{esc(form["icon"])}" alt=""> '
             f'<strong>{esc(form["name"])}</strong> has no cooldown - you go in when you can, so there\'s no moment to '
             f'line up with. It\'s compared on how it\'s used instead: how often you go in, how long you stay, and the '
             f'{esc(form["spender"])} casts you fit in each window, next to the top {esc(data["label"])} '
             f'(their median).</p>')
    if not ours and not top:
        return intro + '<p class="muted small">⏳ Fetched with the next syncs - for your pulls and the top players.</p>'

    def cell(stats, key, fmt):
        return f'<td class="num">{fmt(stats[key])}</td>' if stats else '<td class="num muted">…</td>'
    rows = [('Windows / 5 min', 'per_5min', lambda v: f'{v:.1f}'),
            ('Average length', 'avg_ms', lambda v: f'{v / 1000:.0f} s'),
            ('Time in it', 'uptime', lambda v: f'{100 * v:.0f}%'),
            (f'{form["spender"]} per window', 'per_window', lambda v: f'{v:.1f}')]
    body = ''.join(f'<tr><td>{label}</td>{cell(ours, key, fmt)}{cell(top, key, fmt)}</tr>' for label, key, fmt in rows)
    whose = 'Yours are' if not ours else "The top players' are"
    pending = '' if ours and top else f'<p class="muted small">⏳ {whose} fetched with the next syncs.</p>'
    return f"""{intro}
        <div class="table-wrapper"><table class="compact"><tr><th></th><th class="num">You</th>
            <th class="num">Top</th></tr>{body}</table></div>{pending}"""


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
