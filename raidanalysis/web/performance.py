"""
The player page's "Damage & focus" and "Rotation" sections (numbers from throughput.py):

- Damage & focus: parse, DPS / HPS, active time and raid rank per pull, and where their damage went
  next to the rest of the raid - priority adds (the add the raid pours 25% of its damage into) stand
  out by themselves.
- Rotation (WowAnalyzer-style tiles): active time, casts per minute, the keep-on-cooldown abilities,
  uptime of the auras that matter for the spec, and casts per minute of every ability - all next to
  the top parses of the spec.
"""
from .. import spells, throughput
from . import compare
from .players import throughput_label
from .render import (ICON_BASE, boss_portrait, esc, fmt_amount, fmt_duration, per_pull_columns, safe_icon, section_head,
                     stat_tiles, subsection)

VERDICT_PILLS = {'good': ('pill-kill', 'On par'), 'ok': ('pill', 'A bit low'), 'off': ('pill-wipe', 'Low')}
NO_EXTRAS = ('<p class="muted">Not fetched for these pulls yet - the sync picks up throughput, parses and uptime '
             'for recent nights by itself (older ones: <strong>🔄 Re-analyze</strong> on the night page).</p>')


def parse_html(value):
    """A parse percentile in WCL's colors (grey < 25 < green < 50 < blue < 75 < purple < 95 < orange < 99 < pink < 100 gold)."""
    if value is None:
        return '<span class="muted">—</span>'
    cls = next(f'p{t}' for t in (100, 99, 95, 75, 50, 25, 0) if value >= t)
    return f'<span class="parse {cls}">{int(value)}</span>'


def _pill(verdict):
    if not verdict:
        return '<span class="muted small">—</span>'
    cls, text = VERDICT_PILLS[verdict]
    return f'<span class="pill {cls}">{text}</span>'


def _pct(share):
    return '<span class="muted">—</span>' if share is None else f'{100 * share:.0f}%'


# ============================================================================
# Damage & focus
# ============================================================================

def damage_tab(numbered, player, pull_href, focus_section='', pull_focus=None):
    """
    numbered: [(pull number, pull)] the page covers; player: analyzer.player_report row; focus_section:
    the one-pull focus timeline (routes.py builds it - it may fetch from WCL); pull_focus: that pull's
    numbers by target ({'number', 'colors', 'rows'}) for the table.
    """
    name, role = player['name'], player.get('role')
    metric = 'HPS' if role == 'healer' else 'DPS'
    rows = throughput.per_pull(numbered, name, role)
    if not rows:
        return f'<div class="card">{section_head("📈", throughput_label(role))}{NO_EXTRAS}</div>'
    parses = [r['parse'] for r in rows if r['parse'] is not None]
    kills = [r for r in rows if r['kill']]
    active, raid_active = throughput.active_time(numbered, name, role)
    tiles = [(parse_html(max(parses)) if parses else '—', 'Best parse'),
             (parse_html(sorted(parses)[len(parses) // 2]) if parses else '—', 'Typical parse'),
             (fmt_amount(sum(r['amount'] for r in rows) / len(rows)), f'Average {metric}'),
             (fmt_amount(max(r['amount'] for r in kills)) if kills else '—', f'{metric} on the kill'),
             (_pct(active), f'Active time · raid {_pct(raid_active)}' if raid_active else 'Active time')]
    table = ''.join(f"""
        <tr class="click-row" onclick="location='{esc(pull_href(r['number']))}'">
            <td class="num">#{r['number']}</td>
            <td>{'<span class="pill pill-kill">✔ Kill</span>' if r['kill'] else ''}</td>
            <td class="num">{fmt_duration(r['duration'])}</td>
            <td class="num" data-v="{r['parse'] if r['parse'] is not None else -1}">{parse_html(r['parse'])}</td>
            <td class="num" data-v="{r['bracket'] if r['bracket'] is not None else -1}">{parse_html(r['bracket'])}</td>
            <td class="num" data-v="{r['amount']:.0f}">{fmt_amount(r['amount'])}</td>
            <td class="num">{_pct(r['active'])}</td>
            <td class="num">{f"{r['raid_rank']} / {r['raid_size']}" if r['raid_rank'] else '—'}</td>
        </tr>""" for r in rows)
    chart = per_pull_columns([(r['number'], round(r['parse'])) for r in rows if r['parse'] is not None],
                             'Parse per pull')
    no_wipe_parses = any(not r['kill'] and r['parse'] is None for r in rows)
    performance = f"""
        {stat_tiles(tiles)}
        <div class="table-wrapper"><table class="compact">
            <tr><th class="num">Pull</th><th></th><th class="num">Length</th>
                <th data-sort class="num" title="Warcraft Logs parse: percentile among everyone of your spec">Parse</th>
                <th data-sort class="num" title="Parse among players at your item level">ilvl parse</th>
                <th data-sort class="num">{metric}</th>
                <th class="num" title="Share of the pull you were casting or attacking">Active</th>
                <th class="num" title="Among the raid's {'healers' if role == 'healer' else 'tanks' if role == 'tank' else 'DPS'}">Raid rank</th></tr>
            {table}</table></div>
        {f'<h4>Parse per pull</h4>{chart}' if chart else ''}
        {'<p class="muted small">No parse for some wipes: Warcraft Logs only shows those on its website, which needs '
         'a browser session set up (WCL_SCRAPE_COOKIES).</p>' if no_wipe_parses else ''}"""
    return f"""
    <div class="card">
        {section_head('📈', throughput_label(role),
                      f'Parses, {metric} and where your damage went, pull by pull.' if role != 'healer' else
                      'Parses, HPS and active time pull by pull - and where your damage went, which still '
                      'matters on adds the raid has to burn.')}
        {subsection('Performance', performance)}
        {subsection('Focus', focus_section + '<h4>Where your damage went</h4>' + _focus(numbered, name, role, pull_focus))}
    </div>"""


def _focus(numbered, name, role, pull_focus=None):
    """
    Where your damage went, as a damage meter (WCL-style): a bar per target in its timeline color with the
    timeline's pull (your damage and share inside it, how long it was up, your DPS while up - small bars to
    compare at a glance), and all these pulls: your share with the raid's typical one as a tick, and how many
    points you're above or below it.
    """
    rows = throughput.focus(numbered, name, role)
    pull_rows = (pull_focus or {}).get('rows') or {}
    colors = (pull_focus or {}).get('colors') or {}
    if not rows and not pull_rows:
        return '<p class="muted">No damage by target recorded.</p>'
    peers = 'tanks' if role == 'tank' else 'DPS'
    overall = {r['name']: r for r in rows}
    if pull_rows:
        names = sorted(pull_rows, key=lambda t: -pull_rows[t]['damage'])
        names += [t for t in overall if t not in pull_rows]
    else:
        names = list(overall)
    number = (pull_focus or {}).get('number')
    main = (pull_focus or {}).get('main')
    encounter = numbered[0][1].get('encounter_id') if numbered else None
    most = max((p['damage'] for p in pull_rows.values()), default=0) or 1
    longest = max((p['up_s'] for p in pull_rows.values()), default=0) or 1
    fastest = max((p['dps'] for p in pull_rows.values()), default=0) or 1
    out = []
    for i, target in enumerate(names):
        r, p = overall.get(target), pull_rows.get(target)
        color = colors.get(target, '#7484ec')
        boss = (r or {}).get('type') == 'Boss' or (p or {}).get('type') == 'Boss'
        portrait = boss_portrait(encounter, 'sm') if target == main and encounter else ''
        kind = ' <span class="pill pill-muted">boss</span>' if boss else ''
        name_cell = f'<td><div class="dname" style="--c:{color}">{portrait}<span>{esc(target)}</span>{kind}</div></td>'
        if pull_focus and p:
            pull_cells = f"""
                <td data-v="{p['damage']}"><div class="dbar" style="--c:{color};--w:{100 * p['damage'] / most:.1f}%">
                    <span>{fmt_amount(p['damage'])}</span><b>{_pct(p['share'])}</b></div></td>
                <td class="num" data-v="{p['up_s']:.0f}" style="--c:{color}">{fmt_duration(p['up_s'] * 1000)}
                    <div class="dmini"><i style="width:{100 * p['up_s'] / longest:.0f}%"></i></div></td>
                <td class="num{' dtop' if p['dps'] >= fastest else ''}" data-v="{p['dps']:.0f}" style="--c:{color}">
                    <span class="dnum">{fmt_amount(p['dps'])}</span>
                    <div class="dmini"><i style="width:{100 * p['dps'] / fastest:.0f}%"></i></div></td>"""
        elif pull_focus:
            pull_cells = '<td class="muted small">not hit this pull</td><td></td><td></td>'
        else:
            pull_cells = ''
        if r:
            raid = r['raid_share']
            delta = 100 * (r['mine_share'] - raid) if raid is not None else None
            band = 'bad' if r['low'] else 'good' if delta is not None and delta >= 3 else ''
            chip = (f'<span class="ddelta {band}" title="Your share minus the raid\'s {peers}\' typical share">'
                    f'{delta:+.0f} pts</span>' if delta is not None else '')
            tick = (f'<i style="left:{min(100, 100 * raid):.1f}%"></i>' if raid is not None else '')
            all_cells = f"""
                <td data-v="{r['mine_share']:.4f}" style="min-width:150px">
                    <div class="fshare" style="--c:{'var(--bad)' if r['low'] else color}"
                         title="You {_pct(r['mine_share'])} · raid typical {_pct(raid)}">
                        <b style="width:{min(100, 100 * r['mine_share']):.1f}%"></b>{tick}</div>
                    <span class="small muted">{_pct(r['mine_share'])} · raid {_pct(raid)}</span></td>
                <td data-v="{delta if delta is not None else 0:.1f}">{chip}</td>"""
        else:
            all_cells = '<td class="muted small">—</td><td></td>'
        out.append(f'<tr>{name_cell}{pull_cells}{all_cells}</tr>')
    pull_head = (f'<th colspan="3" class="col-pull">Pull #{number} (the timeline above)</th>' if pull_focus else '')
    pull_cols = ('<th data-sort class="col-pull">Your damage</th>'
                 '<th data-sort class="num" title="Bosses: the whole pull. Adds: while the raid was hitting them">Up</th>'
                 '<th data-sort class="num" title="Your damage on it over the time it was up">DPS while up</th>'
                 if pull_focus else '')
    return f"""
        <p class="muted small">{f'Pull #{number} on the left; ' if pull_focus else ''}all {len(numbered)} pull(s) of
           this boss on the right: your share of your damage against the raid's {peers} (their typical share is the
           tick), and how many points you're above (green) or clearly below (red) them.</p>
        <div class="table-wrapper"><table class="compact focus-table dtable">
            <tr class="group-head"><th></th>{pull_head}<th colspan="2" class="col-all">All these pulls</th></tr>
            <tr><th data-sort>Target</th>{pull_cols}
                <th data-sort class="col-all">Your share</th><th data-sort>vs raid</th></tr>
            {''.join(out)}</table></div>"""


# ============================================================================
# Rotation
# ============================================================================

def _spell(name, spell_id=None, icon=None, info=None):
    """
    Icon + name with the Wowhead tooltip on hover (PAGE_JS: data-spell). Proc events only carry the buff's
    id, so then the name and icon come from Wowhead (info: a spells.lookup row).
    """
    info = info or {}
    if not name or str(name).isdigit():
        name = info.get('name') or (f'Spell {spell_id}' if spell_id else '?')
    src = safe_icon(ICON_BASE + icon) if icon else safe_icon(spells.icon_url(info.get('icon')))
    img = f'<img class="ability-icon" src="{esc(src)}" alt="" loading="lazy">' if src else ''
    if not spell_id:
        return f'<span class="cmp-ab">{img}{esc(name)}</span>'
    spells.offer([spell_id])  # its tooltip may be looked up on demand
    return f'<span class="cmp-ab" data-spell="{int(spell_id)}">{img}{esc(name)}</span>'


def _bar(share, band, top=None):
    """A tile's bar, with a tick where the top players are (same scale)."""
    mark = (f'<i class="subscore-mark" style="left:{min(100, 100 * top):.0f}%" title="Top players: {100 * top:.0f}%">'
            f'</i>' if top is not None else '')
    return (f'<div class="subscore-track{" marked" if mark else ""}"><div class="subscore-fill {band}" '
            f'style="width:{min(100, 100 * share):.0f}%"></div>{mark}</div>')


def _strip(row):
    """When the aura was up in one pull (WowAnalyzer's uptime bar)."""
    total = (row.get('band_duration') or 0) / 1000  # bands are in seconds
    if not total or not row['bands']:
        return ''
    bands = ''.join(f'<i style="left:{100 * a / total:.2f}%;width:{max(0.2, 100 * (b - a) / total):.2f}%"></i>'
                    for a, b in row['bands'])
    return (f'<div class="uptime-strip" title="When it was up in pull #{row["band_pull"]}">{bands}</div>')


def _uptime_tiles(rows, lookup):
    tiles = []
    for r in rows:
        band = {'good': 'good', 'ok': 'ok'}.get(r['verdict'], 'bad')
        what = 'on the boss' if r['kind'] == 'debuff' else 'on you'
        tiles.append(f"""
            <div class="rot-tile">
                <div class="rot-head">{_spell(r['name'], r['id'], r.get('icon'), lookup.get(r['id']))}{_pill(r['verdict'])}</div>
                <div class="rot-value"><b>{100 * r['ours']:.0f}%</b><span>uptime {what}</span></div>
                {_bar(r['ours'], band, r['top'])}
                {_strip(r)}
                <div class="muted small">Top {r['top_users']}: {100 * r['top']:.0f}%</div>
            </div>""")
    return f'<div class="rot-tiles">{"".join(tiles)}</div>'


def _cpm_table(cpm, top_count, by_name):
    rows = []
    for a in cpm['abilities']:
        share = a['ours'] / a['top'] if a['top'] else None
        info = by_name.get(a['name']) or {}
        rows.append(f"""
            <tr class="{'' if a['verdict'] else 'muted-row'}">
                <td>{_spell(a['name'], info.get('spell_id'), info=info)}</td>
                <td class="num" data-v="{a['ours']:.3f}">{a['ours']:.1f}</td>
                <td class="num" data-v="{a['top']:.3f}">{a['top']:.1f}
                    <span class="muted small">({a['top_users']}/{top_count})</span></td>
                <td class="num" data-v="{share or 0:.3f}">{_pct(share)}</td>
                <td class="num">{a['casts']}</td>
                <td>{_pill(a['verdict'])}</td>
            </tr>""")
    return f"""<div class="table-wrapper"><table class="compact">
        <tr><th data-sort>Ability</th><th data-sort class="num">You / min</th>
            <th data-sort class="num" title="Median over the top players (how many of them cast it)">Top / min</th>
            <th data-sort class="num">Of top</th><th data-sort class="num">Your casts</th><th>Verdict</th></tr>
        {''.join(rows)}</table></div>"""


def _resource_tiles(rows):
    tiles = []
    for r in rows:
        mana = r['type'] == throughput.MANA
        band = {'good': 'good', 'ok': 'ok', None: 'neutral'}.get(r['verdict'], 'bad')
        what = 'left at the end of the kill' if mana else 'wasted (gained at the cap)'
        detail = '' if mana else f' · {r["wasted"]:,} of {r["gained"]:,}'
        top = (f'Top {r["top_users"]}: {100 * r["top"]:.0f}%' if r['top'] is not None else
               'Top players: not enough data')
        tiles.append(f"""
            <div class="rot-tile">
                <div class="rot-head"><span>{esc(r['name'])}</span>{_pill(r['verdict'])}</div>
                <div class="rot-value"><b>{100 * r['ours']:.0f}%</b><span>{what}</span></div>
                {_bar(r['ours'], band, r['top'])}
                <div class="muted small">{top}{detail}</div>
            </div>""")
    return f'<div class="rot-tiles">{"".join(tiles)}</div>'


def _on_others_tiles(rows, lookup):
    tiles = []
    for r in rows:
        share = r['ours'] / r['top'] if r['top'] else None
        band = {'good': 'good', 'ok': 'ok', None: 'neutral'}.get(r['verdict'], 'bad')
        top = f'Top {r["top_users"]}: {r["top"]:.1f} active' if r['top'] else 'Top players: no data'
        tiles.append(f"""
            <div class="rot-tile">
                <div class="rot-head">{_spell(r['name'], r['id'], info=lookup.get(r['id']))}{_pill(r['verdict'])}</div>
                <div class="rot-value"><b>{r['ours']:.1f}</b><span>active on average</span></div>
                <div class="subscore-track"><div class="subscore-fill {band}" style="width:{min(100, 100 * (share or 0)):.0f}%"></div></div>
                <div class="muted small">{top}</div>
            </div>""")
    return f'<div class="rot-tiles">{"".join(tiles)}</div>'


def _proc_tiles(rows, lookup):
    tiles = []
    for r in rows:
        band = {'good': 'good', 'ok': 'ok', None: 'neutral'}.get(r['verdict'], 'bad')
        top = f'Top {r["top_users"]} waste {100 * r["top"]:.0f}%' if r['top'] is not None else 'Top players: no data'
        tiles.append(f"""
            <div class="rot-tile">
                <div class="rot-head">{_spell(r['name'], r['id'], info=lookup.get(r['id']))}{_pill(r['verdict'])}</div>
                <div class="rot-value"><b>{100 * r['ours']:.0f}%</b><span>wasted · {r['wasted']} of {r['procs']} procs</span></div>
                {_bar(r['ours'], band, r['top'])}
                <div class="muted small">{top}</div>
            </div>""")
    return f'<div class="rot-tiles">{"".join(tiles)}</div>'


def rotation_tab(numbered, player, data, back=None, tracked=frozenset()):
    """data: benchmarks.for_player() (the top parses + the keep-on-cooldown rows), or None."""
    name, role = player['name'], player.get('role')
    top = (data or {}).get('top') or []
    label = esc((data or {}).get('label') or 'players')
    have_extras = bool(throughput.player_pulls(numbered, name))
    active, raid_active = throughput.active_time(numbered, name, role)
    # Trinkets and potions the cooldown comparison knows from Wowhead: not part of the rotation.
    items = {r['name'] for r in (data or {}).get('rows') or [] if r['category'] in ('trinket', 'potion')}
    cpm = throughput.cpm(numbered, name, top, items)
    tiles = []
    if active is not None:
        tiles.append((_pct(active), f'Active time · raid {_pct(raid_active)}' if raid_active else 'Active time'))
    if cpm:
        tiles.append((f'{cpm["ours"]:.1f}', f'Casts / min · top {cpm["top"]:.1f}'))
    sections = []
    if tiles:
        sections.append(stat_tiles(tiles))
    rotational = compare.rotation_tiles(data, back) if data and data.get('rows') else ''
    if rotational:
        sections.append(subsection('Keep on cooldown', f"""
            <p class="muted small">Abilities you press whenever they're ready (or on procs) - there's no right
               moment, so they're judged on how often you press them, next to the top {label}.</p>{rotational}"""))
    kept_out = throughput.on_others_rows(numbered, name, top)
    uptime = throughput.uptime(numbered, name, top, tracked)
    procs = throughput.proc_rows(numbered, name, top, tracked)
    # Names and icons from Wowhead - procs only come with the buff's id (benchmarks.ensure_spells_for looked
    # them up before the page; anything new is fetched in the background for the next load).
    lookup = spells.lookup({r['id'] for r in kept_out + uptime + procs if r.get('id')})
    by_name = {info['name']: info for info in ((data or {}).get('spells') or {}).values() if info.get('name')}
    if kept_out:
        sections.append(subsection('HoTs & buffs on others', f"""
            <p class="muted small">How many of each you kept out on the raid on average, over the whole fight
               (WowAnalyzer's "average Renewing Mists"), next to the top {label}. Letting charges sit at their
               cap shows up here and in casts per minute.</p>{_on_others_tiles(kept_out, lookup)}"""))
    if uptime:
        sections.append(subsection('Uptime', f"""
            <p class="muted small">Your own buffs and debuffs on the boss that the top {label} keep up most of
               the fight. The strip shows when it was up in your longest pull.</p>{_uptime_tiles(uptime, lookup)}"""))
    elif have_extras and top and not any(p.get('auras') for p in top):
        sections.append(f"""<p class="warn-text small">⏳ <strong>Uptime, wasted procs, resources and casts per minute</strong>
            are compared with the top {label}, whose buffs, procs and casts haven't been fetched since this was added.
            The sync re-fetches a few specs at a time, so they fill in over the next syncs<span class="admin-only"> - or
            press <strong>Fetch all top players</strong> on the Raid Analysis page to get them all now</span>.</p>""")
    if procs:
        sections.append(subsection('Wasted procs', f"""
            <p class="muted small">A proc is wasted when a new one lands while the last is still unused (the buff
               is up at its most stacks and nothing was spent). Only the buffs the game's Cooldown Manager tracks for
               your spec, next to the top {label} - some procs are meant to roll over. The tick on each bar
               is where the top players are.</p>{_proc_tiles(procs, lookup)}"""))
    resources = throughput.resource_rows(numbered, name, top, role)
    if resources:
        sections.append(subsection('Resources', f"""
            <p class="muted small">How much of each resource you gained while already capped, next to the top {label}
               (some waste is built into a spec, and passive regeneration isn't logged - so the bar is what they
               manage){' - and the mana left unspent when the boss died' if role == 'healer' else ''}.</p>
            {_resource_tiles(resources)}"""))
    if cpm:
        sections.append(subsection('Casts per minute', f"""
            <p class="muted small">Every ability you or the top {label} cast, most-pressed first. Greyed-out rows
               aren't judged: most of them don't use it, or you never cast it (a talent or trinket choice).</p>{_cpm_table(cpm, len(top), by_name)}"""))
    if not sections:
        body = NO_EXTRAS if not have_extras else '<p class="muted">Nothing to compare yet - the top players for ' \
                                                 'this spec are fetched over the next syncs.</p>'
        sections.append(body)
    return f"""
    <div class="card">
        {section_head('🔁', 'Rotation', f'How you keep your rotation going, next to the top {label} on this boss: '
                                         'active time, keep-on-cooldown abilities, HoTs on others, uptime, wasted '
                                         'procs, resources and casts per minute - from your kills and furthest '
                                         'wipes.')}
        {''.join(sections)}
    </div>"""
