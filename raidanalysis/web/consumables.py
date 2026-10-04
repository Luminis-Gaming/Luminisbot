"""
Consumables in detail: which potion / healthstone each player used, when, for
how long and how much it healed - plus a WCL-style timeline with the boss's
abilities on top and every player's consumables (and deaths) underneath.

Needs analyses from ANALYSIS_VERSION 4+ ('consumables', 'boss_casts');
older nights only have counts until they're re-analyzed.
"""
from .. import cooldowns
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


def toolbar(pulls, single):
    """
    Toggle chips for what the timeline shows (they double as its legend): each consumable kind,
    deaths, each cooldown group - and an Abilities dropdown to pick single cooldowns. Cooldowns
    start hidden to keep the default view calm. PAGE_JS does the toggling.
    """
    chips = [f'<button type="button" class="tl-chip" data-f="{k}" aria-pressed="true">'
             f'<i style="--c:{KIND_COLORS[k]}"></i>{KIND_LABELS[k]}</button>' for k in ('potion', 'mana', 'defensive')]
    if single:
        chips.append(f'<button type="button" class="tl-chip" data-f="death" aria-pressed="true">'
                     f'<i style="--c:{DEATH}"></i>Deaths</button>')
    used = {}
    for p in pulls:
        for cd in p['analysis'].get('cooldowns') or []:
            entry = used.setdefault((cd['category'], cd['ability']), {'icon': cd.get('icon'), 'count': 0})
            entry['count'] += 1
    groups = []
    for key, label, emoji in cooldowns.CATEGORIES:
        abilities = sorted(((name, e) for (cat, name), e in used.items() if cat == key), key=lambda x: -x[1]['count'])
        if not abilities:
            continue
        total = sum(e['count'] for _, e in abilities)
        chips.append(f'<button type="button" class="tl-chip" data-cat="{key}" aria-pressed="false">{emoji} {label} '
                     f'<span class="muted">{total}</span></button>')
        boxes = ''.join(f'<label><input type="checkbox" data-cat="{key}" value="{esc(name)}">{_icon(e["icon"])}'
                        f'{esc(name)} <span class="muted">×{e["count"]}</span></label>' for name, e in abilities)
        groups.append(f'<div><h5>{emoji} {label}</h5>{boxes}</div>')
    if groups:
        chips.append(f'<details class="tl-pick"><summary>Abilities ▾</summary>'
                     f'<div class="tl-pick-menu">{"".join(groups)}</div></details>')
    elif not any('cooldowns' in p['analysis'] for p in pulls):
        chips.append('<span class="muted small">Re-analyze to see cooldowns (defensives, externals, raid CDs).</span>')
    chips.append(f'<span class="tl-static"><i style="--c:{BOSS_TICK}"></i>Enemy ability cast</span>')
    return f'<div class="tl-chips">{"".join(chips)}</div>'


# ============================================================================
# Timeline
# ============================================================================

def reference_pull(pulls):
    """
    The pull whose enemy casts the timeline shows: the only pull, else the (longest) kill, else the
    longest pull with casts - it saw the most of the fight. Boss timers are mostly scripted, so they
    line up roughly with the other pulls, drifting where a phase was pushed faster or slower.
    """
    with_casts = [p for p in pulls if p['analysis'].get('boss_casts')]
    if len(pulls) == 1 or not with_casts:
        return pulls[0] if len(pulls) == 1 else None
    return max(with_casts, key=lambda p: (bool(p.get('kill')), p['analysis'].get('_duration') or 0))


def timeline(pulls, roster, spell_lookup=None):
    """
    pulls: [{'number', 'kill', 'analysis' (with _duration), 'phases': [ms]}]. One pull = exact
    WCL-style timeline with the enemy's casts and deaths; several = every use from every pull on one
    axis (habits show up as clusters) under the enemy casts of reference_pull(), deaths left out.

    Drawn as an editor-style timeline (see render.deaths_strip and PAGE_JS): names pinned on the
    left, marks placed in % of the track so zooming keeps icons their size, drag to pan. Every
    mark has a rich tooltip - what/when from data-tip, plus the spell's Wowhead text from the
    page's spell-data JSON. spell_lookup(ids) -> {id: {'name', 'icon', 'meta', 'description'}}.
    """
    single = len(pulls) == 1
    longest = max((p['analysis'].get('_duration') or 0) for p in pulls) or 1
    reference = reference_pull(pulls)
    spells = {}  # spell id -> (name, rpglogs icon) as the logs know it

    def at(t):
        return f'{100 * max(0, min(t, longest)) / longest:.3f}%'

    def prefix(pull):
        return '' if single else f'Pull {pull["number"]} · '

    labels, rows = [], []
    if reference:
        # One lane per ability *name* - bosses often cast the same ability under several spell IDs.
        analysis = reference['analysis']
        meta = {a['id']: a for a in analysis.get('boss_abilities') or []}
        by_name = {}
        for t, guid in analysis.get('boss_casts') or []:
            if guid in meta:
                by_name.setdefault(meta[guid]['name'], []).append((t, guid))
        source = '' if single else f' · pull {reference["number"]}'
        for name, casts in sorted(by_name.items(), key=lambda kv: min(kv[1])[0]):
            for _, guid in casts:
                spells.setdefault(guid, (name, meta[guid].get('icon')))
            first = casts[0][1]
            labels.append(f'<div class="tl-lab boss" data-spell="{first}" data-tip="Cast {len(casts)}× this pull">'
                          f'{_icon(meta[first].get("icon"))}<span>{esc(name)}</span></div>')
            ticks = ''.join(f'<i class="m tick" style="left:{at(t)}" data-spell="{guid}" '
                            f'data-tip="{fmt_duration(t)}{source}"></i>' for t, guid in sorted(casts))
            rows.append(f'<div class="tl-row boss">{ticks}</div>')

    for i, player in enumerate(roster):
        sep = ' sep' if i == 0 and rows else ''
        marks = []
        for pull in pulls:
            for use in pull['analysis'].get('consumables') or []:
                if use['name'] != player['name']:
                    continue
                k = kind(use)
                spells.setdefault(use['ability_id'], (use['ability'], use.get('icon')))
                tip = f'{prefix(pull)}{fmt_duration(use["t"])}{" (pre-pot)" if use.get("prepot") else ""}'
                if k == 'defensive':
                    tip += f' · healed {fmt_amount(use.get("healing") or 0)}'
                    marks.append(f'<i class="m dia" data-f="{k}" style="left:{at(use["t"])}" '
                                 f'data-spell="{use["ability_id"]}" data-tip="{esc(tip)}"></i>')
                else:
                    end = use.get('end') or (use['t'] + POTION_BUFF_FALLBACK_MS)
                    tip += f' · {fmt_duration(end - use["t"])} buff'
                    width = 100 * (min(end, longest) - max(0, use['t'])) / longest
                    marks.append(f'<i class="m bar k-{k}" data-f="{k}" style="left:{at(use["t"])};width:{width:.3f}%" '
                                 f'data-spell="{use["ability_id"]}" data-tip="{esc(tip)}"></i>')
            for cd in pull['analysis'].get('cooldowns') or []:
                if cd['name'] != player['name']:
                    continue
                spells.setdefault(cd['ability_id'], (cd['ability'], cd.get('icon')))
                tip = (f'{prefix(pull)}{"→ " + cd["target"] + " · " if cd.get("target") else ""}'
                       f'{fmt_duration(cd["t"])}')
                marks.append(f'<i class="m cd sp{cd["ability_id"]}" data-f="cd" data-ab="{esc(cd["ability"])}" '
                             f'style="left:{at(cd["t"])}" data-spell="{cd["ability_id"]}" data-tip="{esc(tip)}" hidden></i>')
        if single:
            for d in pulls[0]['analysis'].get('deaths') or []:
                if d['name'] != player['name']:
                    continue
                if d.get('ability_id'):
                    spells.setdefault(d['ability_id'], (d['ability'], d.get('icon')))
                marks.append(f'<i class="m death{" early" if d.get("early") else ""}" data-f="death" '
                             f'style="left:{at(d["t"])}" data-spell="{d.get("ability_id") or ""}" '
                             f'data-tip="Died at {fmt_duration(d["t"])} · {esc(_death_text(d))}">✕</i>')
        labels.append(f'<div class="tl-lab{sep}">{esc(player["name"])}</div>')
        rows.append(f'<div class="tl-row{sep}">{"".join(marks)}</div>')

    phases = ''.join(f'<i class="tl-phase" style="left:{at(start)}"></i>' for start in (reference or {}).get('phases') or [])
    grid = ''.join(f'<i style="left:{at(t)}"></i>' for t in range(0, longest + 1, 60000))
    ruler = ''.join(f'<span{" class=first" if not t else ""} style="left:{at(t)}">{fmt_duration(t)}</span>'
                    for t in range(0, longest + 1, 60000))
    icon_css = ''.join(f'.sp{sid}{{background-image:url({ICON_BASE}{esc(icon)})}}'
                       for sid, (_, icon) in spells.items() if icon)
    return f"""<div class="tl cons-tl{"" if single else " multi"}" data-duration="{longest}"
        style="--potion:{KIND_COLORS['potion']};--mana:{KIND_COLORS['mana']};--defensive:{KIND_COLORS['defensive']}">
        <style>{icon_css}</style>
        {toolbar(pulls, single)}
        <div class="tl-tools"><span class="muted small">Drag to pan · Ctrl + scroll or pinch to zoom</span>
            <button type="button" data-zoom="out" title="Zoom out">−</button>
            <input type="range" min="0" max="100" value="0" aria-label="Zoom">
            <button type="button" data-zoom="in" title="Zoom in">+</button>
            <button type="button" data-zoom="fit" title="Show the whole pull">Fit</button></div>
        <div class="tl-body">
            <div class="tl-labels">{"".join(labels)}<div class="tl-ruler-gap"></div></div>
            <div class="tl-scroll"><div class="tl-inner">
                <div class="tl-grid">{grid}</div>{phases}
                {"".join(rows)}
                <div class="tl-ruler">{ruler}</div>
                <div class="tl-head" hidden><span></span></div>
            </div></div>
        </div>
        <script type="application/json" class="spell-data">{_spell_json(spells, spell_lookup)}</script>
    </div>"""


def _death_text(death):
    from .. import analyzer
    return analyzer.death_note(death)


def _spell_json(spells, spell_lookup):
    """{id: {name, icon, meta, desc}} for the tooltips: Wowhead's text where we have it, the log's name otherwise."""
    import json
    known = spell_lookup(list(spells)) if spell_lookup and spells else {}
    out = {}
    for sid, (name, icon) in spells.items():
        info = known.get(sid) or {}
        out[sid] = {'name': info.get('name') or name,
                    'icon': f'{ICON_BASE}{icon}' if icon else spell_icon_url(info.get('icon')),
                    'meta': info.get('meta') or '', 'desc': info.get('description') or ''}
    # Inside <script>: keep "</script>" from ever closing it early.
    return json.dumps(out, ensure_ascii=False).replace('</', '<\\/')


def spell_icon_url(icon):
    from ..spells import icon_url
    return icon_url(icon)


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
