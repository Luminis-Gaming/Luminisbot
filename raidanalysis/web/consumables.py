"""
Consumables in detail: which potion / healthstone each player used, when, for
how long and how much it healed - plus a WCL-style timeline with the boss on top
(its phases, a lane per kind of add with a dashed line per spawn through everyone,
its abilities) and every player's consumables, cooldowns (and deaths) underneath.

Needs analyses from ANALYSIS_VERSION 4+ ('consumables', 'boss_casts');
older nights only have counts until they're re-analyzed.
"""
from .. import benchmarks, cooldowns
from ..spells import icon_url
from . import focusview
from .render import ROLE_ICONS, esc, fmt_amount, fmt_duration, player_name, safe_icon, spell_data_json

# What the timeline colors encode is the *kind* of consumable (validated with the
# dataviz palette checker on the card surface, all pairs); the exact potion is in
# the tooltip, the legend text and the tables. Healthstones and healing potions share
# the defensive colour and differ in shape (a fourth hue failed the colourblind checks):
# a diamond for a healthstone, a dot for a healing potion.
KIND_COLORS = {'potion': '#7484ec', 'mana': '#2f9e8f', 'defensive': '#cc7f3c'}
KIND_LABELS = {'potion': 'Combat potion', 'mana': 'Mana potion', 'defensive': 'Healthstone / healing potion'}
# The timeline's finer kinds (timeline_kind): what the Potions dropdown picks between
TIMELINE_KINDS = (('potion', 'Combat potion'), ('mana', 'Mana potion'), ('healthstone', 'Healthstone'),
                  ('healing', 'Healing potion'))
BOSS_TICK = '#9aa1b9'
DEATH = '#ff6b6b'
POTION_BUFF_FALLBACK_MS = 30000
DEFAULT_ON = ()  # cooldown groups shown without clicking: none - the boss and potions are what the timeline opens on
ICON_BASE = 'https://assets.rpglogs.com/img/warcraft/abilities/'


def kind(use):
    if use['kind'] == 'defensive':
        return 'defensive'
    return 'mana' if 'mana' in (use.get('ability') or '').lower() else 'potion'


def timeline_kind(use):
    """kind(), with the defensives split: 'healthstone' (Healthstones, Demonic ones included) or 'healing'."""
    k = kind(use)
    if k != 'defensive':
        return k
    return 'healthstone' if 'healthstone' in (use.get('ability') or '').lower() else 'healing'


def has_details(analyses):
    return any('consumables' in a for a in analyses)


def _icon_src(icon):
    """Logs give icon file names (rpglogs); spells found via Wowhead come as full URLs. None if unsafe."""
    icon = safe_icon(icon)
    if not icon:
        return None
    return icon if icon.startswith('http') else f'{ICON_BASE}{icon}'


def _icon(icon):
    src = _icon_src(icon) if icon else None
    return f'<img class="ability-icon" src="{esc(src)}" alt="" loading="lazy">' if src else ''


# Cooldown groups on the timeline: each spec's own damage / healing cooldowns (found the way the
# top-player comparison finds them), then the tracked defensive / utility groups (cooldowns.py).
THROUGHPUT_GROUP = ('throughput', 'Damage & healing cooldowns', '⚔️')
TIMELINE_CATEGORIES = (THROUGHPUT_GROUP,) + tuple(cooldowns.CATEGORIES)


def cooldowns_by_pull(pulls, spell_lookup=None, majors=None):
    """
    {id(pull): [cooldown use]} - the tracked cooldowns (analysis['cooldowns']) plus each player's
    major damage / healing cooldowns and on-use trinkets from their recorded casts (analysis['casts']):
    the ones their spec's top players use as majors on this boss (majors = benchmarks.spec_majors),
    else anything with a 60 s+ cooldown. Spells not looked up on Wowhead yet just don't show.
    """
    def still_tracked(p):  # stored with the list as it was then: a cooldown taken off it comes from the casts
        return [dict(cd, category=cooldowns.COOLDOWNS[cd['ability']]) for cd in p['analysis'].get('cooldowns') or []
                if cd['ability'] in cooldowns.COOLDOWNS]
    tracked = {cd['ability_id'] for p in pulls for cd in still_tracked(p)}
    consumed = {u['ability_id'] for p in pulls for u in p['analysis'].get('consumables') or []}
    ids = {sid for p in pulls for casts in (p['analysis'].get('casts') or {}).values() for _, sid in casts}
    ids -= tracked | consumed
    info = spell_lookup(list(ids)) if spell_lookup and ids else {}
    majors = majors or {}
    out = {}
    for p in pulls:
        uses = still_tracked(p)
        roster = {pl['name']: pl for pl in p['analysis'].get('players') or []}
        for player, casts in (p['analysis'].get('casts') or {}).items():
            who = roster.get(player, {})
            for t, sid in casts:
                if sid in ids and benchmarks.is_major_for(who, sid, info.get(sid), majors):
                    uses.append({'t': t, 'name': player, 'ability_id': sid, 'ability': info[sid]['name'],
                                 'icon': icon_url(info[sid].get('icon')), 'category': THROUGHPUT_GROUP[0],
                                 'target': None})
        out[id(p)] = uses
    return out


def _cd_key(cd):
    return f'cd:{cd["category"]}:{cd["ability"]}'


def _dropdown(key, label, items):
    """
    One category as a dropdown chip: an All box, then a box per item (it shows / hides everything on the
    timeline with that data-k). items: [(data-k, mark html, name, count, spell id or None, tip, on)].
    The summary says how many are on (PAGE_JS keeps it current).
    """
    def row(k, mark, name, count, sid, tip, on):
        attrs = (f' data-spell="{int(sid)}"' if sid else '') + (f' data-tip="{esc(tip)}"' if tip else '')
        times = f' <span class="muted">×{count}</span>' if count else ''
        return (f'<label{attrs}><input type="checkbox" value="{esc(k)}" data-name="{esc(k)}"{" checked" if on else ""}>{mark}'
                f'<span>{esc(name)}</span>{times}</label>')
    rows = ''.join(row(*item) for item in items)
    return (f'<details class="tl-dd" data-dd="{key}"><summary><span>{label}</span><b class="tl-dd-n"></b>'
            f'<span class="tl-dd-caret">▾</span></summary><div class="tl-dd-menu">'
            f'<label class="tl-dd-all"><input type="checkbox" data-all>All</label>{rows}</div></details>')


def toolbar(pulls, single, cds, boss_items=()):
    """
    What the timeline shows, a dropdown per category (they double as its legend): Boss (phases, each kind
    of add, the enemy's abilities), Potions & healthstones (each kind), and each cooldown group with its
    abilities - plus a Deaths chip. The boss (its priority adds only) and potions start visible, the cooldown groups (but DEFAULT_ON)
    don't, to keep the default view calm. PAGE_JS does the toggling.
    """
    dds = []
    if boss_items:
        dds.append(_dropdown('boss', '👹 Boss', boss_items))
    counts = {}
    for p in pulls:
        for use in p['analysis'].get('consumables') or []:
            counts[timeline_kind(use)] = counts.get(timeline_kind(use), 0) + 1
    dds.append(_dropdown('cons', '🧪 Potions & healthstones',
                         [(k, f'<i class="tl-key k-{k}"></i>', label, counts.get(k, 0), None, None, True)
                          for k, label in TIMELINE_KINDS]))
    used = {}
    for p in pulls:
        for cd in cds[id(p)]:
            entry = used.setdefault((cd['category'], cd['ability']),
                                    {'icon': cd.get('icon'), 'count': 0, 'sid': cd['ability_id'], 'key': _cd_key(cd)})
            entry['count'] += 1
    for key, label, emoji in TIMELINE_CATEGORIES:
        abilities = sorted(((name, e) for (cat, name), e in used.items() if cat == key), key=lambda x: -x[1]['count'])
        if abilities:
            dds.append(_dropdown(key, f'{emoji} {label}', [
                (e['key'], _icon(e['icon']), name, e['count'], e['sid'], None, key in DEFAULT_ON)
                for name, e in abilities]))
    chips = ''.join(dds)
    if single:
        chips += (f'<button type="button" class="tl-chip" data-k="death" data-name="death" aria-pressed="true">'
                  f'<i style="--c:{DEATH}"></i>Deaths</button>')
    if not used and not any('cooldowns' in p['analysis'] for p in pulls):
        chips += '<span class="muted small">Re-analyze to see cooldowns (defensives, externals, raid CDs).</span>'
    return f'<div class="tl-chips tl-dds">{chips}</div>'


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


def adds_pull(pulls):
    """The pull whose adds and phases the Boss lanes show: reference_pull(), else the longest kill or pull."""
    return reference_pull(pulls) or max(pulls, key=lambda p: (bool(p.get('kill')), p['analysis'].get('_duration') or 0),
                                        default=None)


def _boss_section(source, adds, phase_names, npc_icons, at, longest):
    """
    The Boss lanes over the source pull: its phases (labelled stretches) and a lane per kind of add (a bar
    per spawn), each with a dashed line per spawn across every player's row. Returns (labels, rows, lines,
    dropdown items) - every piece keyed (data-k) so the Boss dropdown shows / hides it.
    """
    labels, rows, lines, items = [], [], [], []
    phases = (source or {}).get('phase_list') or []
    if len(phases) > 1:
        labels.append('<div class="tl-lab c-phase" data-k="phases">Phases</div>')
        rows.append(f'<div class="tl-row c-lane c-phase" data-k="phases">'
                    f'{focusview.phase_lane(phases, phase_names or {}, longest)}</div>')
        lines += [f'<i class="tl-phase" data-k="phases" style="left:{at(p["start"])}"></i>'
                  for p in phases[1:] if p.get('start')]
        items.append(('phases', '<i class="tl-key k-phase"></i>', 'Phases', len(phases), None, None, True))
    for i, kind_ in enumerate(adds or []):
        target = kind_['target']
        key = f'add:{target}'  # by name: the same add keeps its toggle from pull to pull
        color = focusview.COLORS[i] if i < len(focusview.COLORS) else focusview.OTHER_COLOR
        prio = ('<span class="pill pill-kill" data-tip="A priority: the top DPS pile into it">★</span>'
                if kind_['priority'] else '')
        mark = focusview._swatch(color, npc_icons.get(target))
        labels.append(f'<div class="tl-lab c-add" data-k="{esc(key)}" title="{esc(target)}"><span class="flab">{mark}'
                      f'<span>{esc(target)}</span></span><small>×{len(kind_["spawns"])}</small>{prio}</div>')
        rows.append(f'<div class="tl-row c-lane c-add" data-k="{esc(key)}">'
                    f'{focusview.spawn_lane(kind_, color, longest, you=False)}</div>')
        lines += [f'<i class="tl-phase fspawnline" data-k="{esc(key)}" style="left:{at(w["start"])};--c:{color}"></i>'
                  for w in kind_['spawns']]
        items.append((key, mark, target, len(kind_['spawns']), None,
                      'A priority: the top DPS pile into it' if kind_['priority'] else None, kind_['priority']))
    return labels, rows, lines, items


def timeline(pulls, roster, spell_lookup=None, majors=None, adds=None, phase_names=None, npc_icons=None, loading=''):
    """
    pulls: [{'number', 'kill', 'analysis' (with _duration), 'phases': [ms], 'phase_list': [{'id', 'start'}]}].
    One pull = exact WCL-style timeline with the enemy's casts and deaths; several = every use from every
    pull on one axis (habits show up as clusters) under the enemy casts, phases and adds of reference_pull()
    / adds_pull(), deaths left out.
    adds: focus.add_types() of adds_pull() (focus.raid_adds), None when not loaded - loading: the cast bar
    fetching them; phase_names: {phase id: {'name', 'intermission'}} for this encounter; npc_icons: {enemy:
    portrait url} (npcs.icons).

    Drawn as an editor-style timeline (see render.deaths_strip and PAGE_JS): names pinned on the
    left, marks placed in % of the track so zooming keeps icons their size, drag to pan. Every
    mark has a rich tooltip - what/when from data-tip, plus the spell's Wowhead text from the
    page's spell-data JSON. spell_lookup(ids) -> {id: {'name', 'icon', 'meta', 'description'}}.
    """
    single = len(pulls) == 1
    longest = max((p['analysis'].get('_duration') or 0) for p in pulls) or 1
    reference = reference_pull(pulls)
    spells = {}  # spell id -> (name, rpglogs icon file or icon URL)
    cds = cooldowns_by_pull(pulls, spell_lookup, majors)
    for uses in cds.values():  # every ability in the dropdowns has its Wowhead tooltip
        for cd in uses:
            spells.setdefault(cd['ability_id'], (cd['ability'], cd.get('icon')))

    def at(t):
        return f'{100 * max(0, min(t, longest)) / longest:.3f}%'

    def prefix(pull):
        return '' if single else f'Pull {pull["number"]} · '

    labels, rows, lines, boss_items = _boss_section(adds_pull(pulls), adds, phase_names, npc_icons or {}, at, longest)
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
            labels.append(f'<div class="tl-lab boss" data-k="abilities" data-spell="{first}" '
                          f'data-tip="Cast {len(casts)}× this pull">{_icon(meta[first].get("icon"))}<span>{esc(name)}</span></div>')
            ticks = ''.join(f'<i class="m tick" style="left:{at(t)}" data-spell="{guid}" '
                            f'data-tip="{fmt_duration(t)}{source}"></i>' for t, guid in sorted(casts))
            rows.append(f'<div class="tl-row boss" data-k="abilities">{ticks}</div>')
        if by_name:
            boss_items.append(('abilities', f'<i class="tl-key k-tick" style="--c:{BOSS_TICK}"></i>', 'Enemy abilities',
                               len(by_name), None, 'A lane per ability, a tick per cast', True))

    for i, player in enumerate(roster):
        sep = ' sep' if i == 0 and rows else ''
        marks = []
        for pull in pulls:
            for use in pull['analysis'].get('consumables') or []:
                if use['name'] != player['name']:
                    continue
                k = timeline_kind(use)
                spells.setdefault(use['ability_id'], (use['ability'], use.get('icon')))
                tip = f'{prefix(pull)}{fmt_duration(use["t"])}{" (pre-pot)" if use.get("prepot") else ""}'
                if k in ('healthstone', 'healing'):
                    tip += f' · healed {fmt_amount(use.get("healing") or 0)}'
                    marks.append(f'<i class="m {"dia" if k == "healthstone" else "dot"}" data-k="{k}" '
                                 f'style="left:{at(use["t"])}" data-spell="{use["ability_id"]}" data-tip="{esc(tip)}"></i>')
                else:
                    end = use.get('end') or (use['t'] + POTION_BUFF_FALLBACK_MS)
                    tip += f' · {fmt_duration(end - use["t"])} buff'
                    width = 100 * (min(end, longest) - max(0, use['t'])) / longest
                    marks.append(f'<i class="m bar k-{k}" data-k="{k}" style="left:{at(use["t"])};width:{width:.3f}%" '
                                 f'data-spell="{use["ability_id"]}" data-tip="{esc(tip)}">'
                                 f'<b class="sp{int(use["ability_id"])}"></b></i>')
            for cd in cds[id(pull)]:
                if cd['name'] != player['name']:
                    continue
                spells.setdefault(cd['ability_id'], (cd['ability'], cd.get('icon')))
                tip = (f'{prefix(pull)}{"→ " + cd["target"] + " · " if cd.get("target") else ""}'
                       f'{fmt_duration(cd["t"])}')
                marks.append(f'<i class="m cd sp{cd["ability_id"]}" data-k="{esc(_cd_key(cd))}" '
                             f'style="left:{at(cd["t"])}" data-spell="{cd["ability_id"]}" data-tip="{esc(tip)}" hidden></i>')
        if single:
            for d in pulls[0]['analysis'].get('deaths') or []:
                if d['name'] != player['name']:
                    continue
                if d.get('ability_id'):
                    spells.setdefault(d['ability_id'], (d['ability'], d.get('icon')))
                marks.append(f'<i class="m death{" early" if d.get("early") else ""}" data-k="death" '
                             f'style="left:{at(d["t"])}" data-spell="{d.get("ability_id") or ""}" '
                             f'data-tip="Died at {fmt_duration(d["t"])} · {esc(_death_text(d))}">✕</i>')
        labels.append(f'<div class="tl-lab{sep}">{esc(player["name"])}</div>')
        rows.append(f'<div class="tl-row{sep}">{"".join(marks)}</div>')

    if not any(k == 'phases' for k, *_ in boss_items):  # no phase lane: the other pulls' phase changes as lines
        lines.append(''.join(f'<i class="tl-phase" style="left:{at(start)}"></i>'
                             for start in (reference or {}).get('phases') or []))
    grid = ''.join(f'<i style="left:{at(t)}"></i>' for t in range(0, longest + 1, 60000))
    ruler = ''.join(f'<span{" class=first" if not t else ""} style="left:{at(t)}">{fmt_duration(t)}</span>'
                    for t in range(0, longest + 1, 60000))
    icon_css = ''.join(f'.sp{int(sid)}{{background-image:url({_icon_src(icon)})}}'
                       for sid, (_, icon) in spells.items() if icon and _icon_src(icon))
    return f"""<div class="tl cons-tl{"" if single else " multi"}" data-duration="{longest}" data-remember="raid"
        style="--potion:{KIND_COLORS['potion']};--mana:{KIND_COLORS['mana']};--defensive:{KIND_COLORS['defensive']}">
        <style>{icon_css}</style>
        {toolbar(pulls, single, cds, boss_items)}
        {loading}
        <div class="tl-tools"><span class="muted small">Drag to pan · Ctrl + scroll or pinch to zoom</span>
            <button type="button" data-zoom="out" title="Zoom out">−</button>
            <input type="range" min="0" max="100" value="0" aria-label="Zoom">
            <button type="button" data-zoom="in" title="Zoom in">+</button>
            <button type="button" data-zoom="fit" title="Show the whole pull">Fit</button></div>
        <div class="tl-body">
            <div class="tl-labels">{"".join(labels)}<div class="tl-ruler-gap"></div></div>
            <div class="tl-scroll"><div class="tl-inner">
                <div class="tl-grid">{grid}</div>{"".join(lines)}
                {"".join(rows)}
                <div class="tl-ruler">{ruler}</div>
                <div class="tl-head" hidden><span></span></div>
            </div></div>
        </div>
        <script type="application/json" class="spell-data">{spell_data_json(spells, spell_lookup)}</script>
    </div>"""


def _death_text(death):
    from .. import analyzer
    return analyzer.death_note(death)


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
