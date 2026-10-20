"""
Entombed Sentinels' Mark of Blood & Mark of Acid (bossmech.BloodAndAcid), drawn: one row per player (a pull, on the
night and pull pages) or per pull (one player, on their page), every row on one time axis and one stack scale -
Mark of Blood's stacks above the line, Mark of Acid's below - with the moments they were in range of both bosses
behind it: amber when it's on them, grey where most of the raid was (the bosses too close - on nobody).

Having some of both is normal (a mark keeps ticking 40 s after you leave its boss); in range of both is what isn't.
"""
from .. import bossmech
from .render import esc, fmt_duration, section_head

# Validated (dataviz validate_palette.js, dark surface #161a2c): lightness band, chroma, CVD ΔE 10.2, normal 28.9,
# contrast. Identity is also position (Blood above the line, Acid below), and the legend names both.
BLOOD, ACID = '#e5484d', '#2f9e8f'
BOTH = '#fab219'  # the status "warning" step: never a series colour, always with its label
MECH = next(m for m in bossmech.every() if m.key == 'marks')


def data_of(pull):
    return ((pull.get('analysis') or {}).get('boss_mechanics') or {}).get(MECH.key)


def _pct(t, scale):
    return f'{100 * max(0, min(t, scale)) / scale:.3f}%'


def _segments(marks, end):
    """[(from, to, blood, acid)]: the stretches with any stacks, where neither count changes."""
    points = sorted({t for k in ('b', 'a') for t, _ in marks[k]})
    out = []
    for i, t in enumerate(points):
        to = points[i + 1] if i + 1 < len(points) else end
        blood, acid = MECH.stacks_at(marks, t)
        if to <= t or not (blood or acid):
            continue
        if out and out[-1][1] == t and out[-1][2:] == (blood, acid):
            out[-1] = (out[-1][0], to, blood, acid)
        else:
            out.append((t, to, blood, acid))
    return out


def _bands(ticks, cls, tip, scale):
    """A band per run of in-range-of-both ticks, half a tick either side of them."""
    half = MECH.TICK_MS // 2
    out = []
    for run in bossmech._runs(ticks, MECH.TICK_MS):
        a, b = max(0, run[0] - half), run[-1] + half
        out.append(f'<i class="mk-band {cls} has-tip" style="left:{_pct(a, scale)};width:{100 * (b - a) / scale:.3f}%" '
                   f'data-tip="{esc(tip)} · {fmt_duration(run[0])}–{fmt_duration(run[-1])} ({len(run) * 5} s)"></i>')
    return ''.join(out)


def summary(data, analysis, name):
    """One row's numbers: {'stood' (seconds in a 10 s+ stretch: failing it), 'crossed' (one-off ticks), 'peak' (the
    most of both at once: min(blood, acid)), 'at' ((blood, acid) then), 'own' (ticks)}."""
    own = MECH.own_ticks(data, analysis, name).get(name) or []
    runs = bossmech._runs(own, MECH.TICK_MS)
    marks = (data.get('players') or {}).get(name) or {'b': [], 'a': []}
    seg = _segments(marks, data.get('end') or 0)
    worst = max(seg, key=lambda s: min(s[2], s[3]), default=None)
    return {'stood': sum(len(r) for r in runs if len(r) >= MECH.BAD_RUN) * MECH.TICK_MS // 1000,
            'crossed': sum(1 for r in runs if len(r) < MECH.BAD_RUN), 'own': own,
            'peak': min(worst[2], worst[3]) if worst else 0, 'at': worst[2:] if worst else (0, 0)}


def _stats(s):
    if s['stood']:
        main = f'<b class="bad-text">{s["stood"]} s in both</b>'
    elif s['crossed']:
        main = f'<span class="muted">crossed {s["crossed"]}×</span>'
    else:
        main = '<span class="good-text">one side</span>'
    peak = s['peak']
    cls = 'warn-text' if peak >= MECH.BAD_STACKS else 'muted'
    both = (f'<small class="{cls}" data-tip="The most of both marks on them at once: {s["at"][0]} Mark of Blood and '
            f'{s["at"][1]} Mark of Acid">{peak} of both</small>' if peak else '')
    return f'<div class="mk-stat">{main}{both}</div>'


def _row(label, data, analysis, name, scale, top, crowd, summary_):
    """One row: label, track (bands, then the stacks - top: the chart's most stacks, its full height), numbers."""
    end = data.get('end') or scale
    marks = (data.get('players') or {}).get(name) or {'b': [], 'a': []}
    segs = ''.join(
        f'<i class="mk-seg has-tip" style="left:{_pct(a, scale)};width:{100 * (b - a) / scale:.3f}%" '
        f'data-tip="{fmt_duration(a)}–{fmt_duration(b)} · Mark of Blood {blood} · Mark of Acid {acid}'
        f'{f" · {min(blood, acid)} of both at once" if blood and acid else ""}">'
        f'{f"<b class=mk-b style=height:{50 * blood / top:.1f}%></b>" if blood else ""}'
        f'{f"<b class=mk-a style=height:{50 * acid / top:.1f}%></b>" if acid else ""}</i>'
        for a, b, blood, acid in _segments(marks, end))
    crowd_ticks = [t for t in MECH.both_ticks(data).get(name) or [] if any(abs(t - c) <= 1000 for c in crowd)]
    bands = (_bands(crowd_ticks, 'crowd', 'Most of the raid in range of both - the bosses were too close (not '
                                          'counted)', scale)
             + _bands(summary_['own'], 'own', 'In range of both bosses', scale))
    after = (f'<i class="mk-after" style="left:{_pct(end, scale)}" data-tip="The pull ended at {fmt_duration(end)}"></i>'
             if end < scale - 500 else '')
    return (f'<div class="mk-lab">{label}</div><div class="mk-track">{bands}{segs}{after}</div>'
            f'{_stats(summary_)}')


def _top(data):
    return max((s for marks in (data.get('players') or {}).values() for k in ('b', 'a') for _, s in marks[k]),
               default=0)


def _ruler(scale):
    return ''.join(f'<span style="left:{_pct(t, scale)}">{fmt_duration(t)}</span>' for t in range(0, scale + 1, 60000))


def legend():
    return (f'<div class="mk-legend"><span><i style="background:{BLOOD}"></i>Mark of Blood (above the line)</span>'
            f'<span><i style="background:{ACID}"></i>Mark of Acid (below)</span>'
            f'<span><i class="own"></i>In range of both bosses</span>'
            f'<span><i class="crowd"></i>Most of the raid in both (bosses too close - not counted)</span></div>'
            f'<p class="muted small">Some of both is normal: a mark keeps ticking for 40 s after you leave its boss, so '
            f'changing sides carries a few stacks across (typically up to about 5 of the other one). What goes wrong '
            f'is standing in range of both - both marks stacking at once. Crossing the middle (one tick) happens; '
            f'<strong>staying in both for 10 s or more</strong> is counted as failing it, and '
            f'<strong>{MECH.BAD_STACKS}+ of both at once</strong> is the worst tenth of our pulls.</p>')


def _chart(rows, scale, raid_strip=''):
    """rows: [row html]. Shared stack scale per chart, time axis under it."""
    return (f'<div class="mk-chart" style="--blood:{BLOOD};--acid:{ACID};--both:{BOTH}">{raid_strip}'
            f'{"".join(rows)}<div></div><div class="mk-ruler">{_ruler(scale)}</div><div></div></div>')


def _raid_strip(data, scale, crowd):
    """
    How many were in range of both at each tick - a column per tick, full height at RAID_WIDE (or the most there
    were); grey where it's the bosses' spot.
    """
    counts = {}
    for name, hits in MECH.both_ticks(data).items():
        for t in hits:
            key = next((k for k in counts if abs(k - t) <= 1000), t)
            counts.setdefault(key, []).append(name)
    size = max([MECH.RAID_WIDE] + [len(who) for who in counts.values()])  # full height: the bosses-too-close count
    cols = ''.join(
        f'<i class="mk-col has-tip{" crowd" if any(abs(t - c) <= 1000 for c in crowd) else ""}" '
        f'style="left:{_pct(t, scale)};height:{max(8, 100 * len(who) / size):.0f}%" '
        f'data-tip="{fmt_duration(t)} · {len(who)} in range of both: {esc(", ".join(sorted(who)))}"></i>'
        for t, who in sorted(counts.items()))
    return (f'<div class="mk-lab"><b>Raid</b><small>in range of both</small></div>'
            f'<div class="mk-track mk-raid">{cols}</div><div class="mk-stat"></div>')


def pull_chart(pull, analysis, label_of):
    """Every player in one pull, worst first. label_of(name) -> their label (html)."""
    data = data_of(pull)
    names = sorted((data.get('players') or {}))
    scale = data.get('end') or max((t for marks in data['players'].values() for k in ('b', 'a')
                                    for t, _ in marks[k]), default=1)
    crowd = MECH.crowded(data)
    sums = {n: summary(data, analysis, n) for n in names}
    order = sorted(names, key=lambda n: (-sums[n]['stood'], -sums[n]['crossed'], -sums[n]['peak'], n))
    top = max(_top(data), 1)
    rows = [_row(label_of(n), data, analysis, n, scale, top, crowd, sums[n]) for n in order]
    return _chart(rows, scale, _raid_strip(data, scale, crowd))


def card(numbered, selected_fid, chip_href, label_of, single=False):
    """
    The night's (or a pull's) card: pull chips, the legend, the chart of the chosen pull - None when no pull has the
    marks stored (another boss, or analyzed before the check). numbered: [(number, pull with analysis)].
    """
    have = [(n, p) for n, p in numbered if data_of(p) and data_of(p).get('players')]
    if not have:
        return None
    number, pull = next(((n, p) for n, p in have if p['fight_id'] == selected_fid), None) or \
        max(have, key=lambda np: (bool(np[1].get('kill')), np[1]['end_ms'] - np[1]['start_ms']))
    analysis = pull.get('analysis') or {}
    chips = ''
    if not single and len(have) > 1:
        def chip(n, p):
            fails = len(MECH.failures(data_of(p), p.get('analysis') or {}))
            label = '✔ Kill' if p.get('kill') else f"{p.get('fight_pct') or 0:.0f}%"
            return (f'<a class="pull-chip{" kill" if p.get("kill") else ""}{" active" if p is pull else ""}" '
                    f'href="{esc(chip_href(p["fight_id"]))}" data-swap="marks" title="Pull {n}: '
                    f'{fails} stood in range of both">#{n} {label}{f" <b class=bad-text>{fails}</b>" if fails else ""}</a>')
        chips = (f'<div class="pull-chips" style="margin-bottom:10px"><span class="chips-label">Pull</span>'
                 f'{"".join(chip(n, p) for n, p in have)}</div>')
    sub = ('Mark of Blood and Mark of Acid stacks on everyone, second by second: in range of a boss, its mark gains a '
           'stack every 5 s. Worst first. Hover anything for the numbers.')
    return (f'<div class="card" id="marks">{section_head(MECH.icon, f"Mark of Blood &amp; Acid · pull {number}", sub)}'
            f'{chips}{legend()}{pull_chart(pull, analysis, label_of)}</div>')


def player_card(numbered, name, pull_label):
    """One player's marks in every pull (a row each, one time axis) - None when none are stored for them."""
    have = [(n, p) for n, p in numbered if name in ((data_of(p) or {}).get('players') or {})]
    if not have:
        return None
    scale = max((data_of(p).get('end') or 0) for _, p in have) or 1
    top = max(max(_top(data_of(p)) for _, p in have), 1)
    rows = []
    for n, p in have:
        data, analysis = data_of(p), p.get('analysis') or {}
        rows.append(_row(pull_label(n, p), data, analysis, name, scale, top, MECH.crowded(data),
                         summary(data, analysis, name)))
    sub = ('Your Mark of Blood (above the line) and Mark of Acid (below) stacks in every pull, on one time axis. '
           'Amber: you were in range of both bosses.')
    return (f'<div class="card" id="marks">{section_head(MECH.icon, "Mark of Blood &amp; Acid", sub)}'
            f'{legend()}{_chart(rows, scale)}</div>')
