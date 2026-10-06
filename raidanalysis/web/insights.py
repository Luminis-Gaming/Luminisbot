"""
The "Mechanics" list: one plain-language line per thing worth knowing about a
pull (or all pulls of a boss), each expandable into per-player bars and charts.
Wipefest's insight list is the model.
"""
from .. import analyzer
from . import consumables, readycheck
from .render import (ability as ability_html, bar_table, esc, fmt_amount, guide_button, hit_timeline,
                     per_pull_columns, player_name)


REANALYZE_HINT = ('<p class="muted small">Which potions and when they were used shows up after this night is '
                  're-analyzed (🔄 Re-analyze at the top).</p>')

CAUSE_TITLES = {
    'tank': 'A tank died', 'healers': 'Healers went down', 'attrition': 'Early deaths piled up',
    'mass': 'Failed raid-wide mechanic', 'enrage': 'Enrage', 'called': 'Wipe called (raid died together)',
    'chain': 'One mechanic killed several in a row', 'reset': 'Early reset', 'reset_called': 'Reset called',
}


def _row(icon, sentence, body, tone=''):
    return (f'<details class="insight {tone}"><summary><span>{icon}</span><span>{sentence}</span></summary>'
            f'<div class="insight-body">{body}</div></details>')


def _plural(n, word, plural=None):
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def build(pulls, tags, guide_for, code):
    """
    pulls: [{'number', 'fight_id', 'kill', 'reason', 'analysis' (with _duration), 'phases': [ms]}] -
    one entry for an individual pull, several for the Overall view. code: the WCL report code.
    """
    single = len(pulls) == 1
    analyses = [p['analysis'] for p in pulls]
    merged = analyzer.merge_pulls(analyses)
    roster = {p['name']: p for p in merged['players']}
    raid = max(1, len(roster))

    def pname(name):
        p = roster.get(name, {})
        return player_name(name, p.get('class', ''), p.get('role'))

    def players_bars(counts, value_head, fmt=str, notes=None):
        rows = sorted(((n, c) for n, c in counts.items() if c), key=lambda kv: -kv[1])
        return bar_table([(pname(n), c, fmt(c), (notes or {}).get(n, '')) for n, c in rows],
                         value_head, 'Damage' if notes else '')

    groups = {'Why we wiped': [], 'Deaths': [], 'Avoidable mechanics': [], 'Interrupts & dispels': [],
              'Consumables': []}

    # --- Why pulls ended ------------------------------------------------------
    by_cause = {}
    for p in pulls:
        if p.get('reason'):
            by_cause.setdefault(p['reason']['code'], []).append(p)
    for cause, cause_pulls in sorted(by_cause.items(), key=lambda kv: -len(kv[1])):
        numbers = ', '.join(f'#{p["number"]}' for p in cause_pulls)
        title = CAUSE_TITLES.get(cause, cause_pulls[0]['reason']['label'])
        if single:
            sentence = (f'<strong>{esc(cause_pulls[0]["reason"]["label"])}</strong> — '
                        f'{esc(cause_pulls[0]["reason"]["detail"])}')
            groups['Why we wiped'].append(_row('🧯', sentence, '', 'bad'))
            continue
        body = ''.join(
            f'<p class="small"><a href="/admin/raids/report/{esc(code)}/{p["fight_id"]}">#{p["number"]}</a> '
            f'<strong>{esc(p["reason"]["label"])}</strong> — <span class="muted">{esc(p["reason"]["detail"])}</span></p>'
            for p in cause_pulls)
        groups['Why we wiped'].append(_row('🧯', f'{title} — <strong>{_plural(len(cause_pulls), "pull")}</strong> '
                                                 f'<span class="muted small">({numbers})</span>', body, 'bad'))

    # --- Deaths ---------------------------------------------------------------
    for a in analyses:
        analyzer.annotate_deaths(a)
    counted = [d for a in analyses for d in a.get('deaths') or [] if d.get('early')]
    total_deaths = sum(len(a.get('deaths') or []) for a in analyses)
    all_kills = all(p.get('kill') for p in pulls)
    by_ability, by_player, first = {}, {}, {}
    for d in counted:
        by_ability.setdefault((d.get('ability_id'), d['ability'], d.get('icon')), 0)
        by_ability[(d.get('ability_id'), d['ability'], d.get('icon'))] += 1
        by_player[d['name']] = by_player.get(d['name'], 0) + 1
    for a in analyses:
        firsts = a.get('deaths') or []
        if firsts and firsts[0].get('early'):
            first[firsts[0]['name']] = first.get(firsts[0]['name'], 0) + 1
    ability_bars = bar_table([(ability_html(name, icon, aid, guide_for(aid, name)), n, str(n), '')
                              for (aid, name, icon), n in sorted(by_ability.items(), key=lambda kv: -kv[1])], 'Deaths')
    body = (f'<div class="grid-2"><div><h4>Killed by</h4>{ability_bars}</div>'
            f'<div><h4>Who died</h4>{players_bars(by_player, "Deaths")}</div></div>')
    if not single:
        body += f'<h4>First to die</h4>{players_bars(first, "Pulls")}'
    across = '' if single else f' across {_plural(len(pulls), "pull")}'
    if all_kills and not total_deaths:
        groups['Deaths'].append(_row('💀', 'Killed the boss without a single death!', body, 'good'))
    elif all_kills:
        groups['Deaths'].append(_row('💀', f'<strong>{_plural(total_deaths, "death")}</strong> during the kill'
                                     f'{"s" if not single else ""}', body, 'bad'))
    elif counted:
        sentence = (f'<strong>{_plural(len(counted), "early death")}</strong> by mistake'
                    f'{f" ({total_deaths} in total)" if total_deaths != len(counted) else ""}{across}')
        groups['Deaths'].append(_row('💀', sentence, body, 'bad'))
    else:
        groups['Deaths'].append(_row('💀', 'No early deaths by mistake', body, 'good'))

    # --- Avoidable mechanics ----------------------------------------------------
    for ability in merged['abilities']:
        tag = tags.get(ability['id'])
        if tag not in analyzer.AVOIDABLE_TAGS:
            continue
        counts, damage = {}, {}
        for name, stats in ability['players'].items():
            if tag == analyzer.TAG_AVOIDABLE_NON_TANK and roster.get(name, {}).get('role') == 'tank':
                continue
            n = analyzer.mistake_counts({'players': {name: stats}})[name] if ability.get('complete') else 0
            if n:
                counts[name] = n
                damage[name] = stats.get('damage') or 0
        clip = guide_button(guide_for(ability['id'], ability['name']), ability['name'])
        label = f'<strong>{esc(ability["name"])}</strong>{clip}'
        who = ' (non-tanks)' if tag == analyzer.TAG_AVOIDABLE_NON_TANK else ''
        if not counts:
            groups['Avoidable mechanics'].append(_row('🎯', f'Nobody{who} got hit by {label}', '', 'good'))
            continue
        hits = sum(counts.values())
        sentence = (f'Hit by {label} <strong>{_plural(hits, "time")}</strong> — {_plural(len(counts), "player")}{who}, '
                    f'{fmt_amount(sum(damage.values()))} damage')
        body = players_bars(counts, 'Hits', notes={n: fmt_amount(d) for n, d in damage.items()})
        if single:
            # Hit timestamps live on the pull's own analysis (merging drops them).
            own = next((a for a in analyses[0].get('abilities') or [] if a['name'] == ability['name']), {})
            times = [(n, (own.get('players') or {}).get(n, {}).get('times') or [])
                     for n in sorted(counts, key=lambda n: -counts[n])]
            if any(t for _, t in times):
                body = (f'<h4>When</h4>{hit_timeline(times, pulls[0]["analysis"]["_duration"], pulls[0]["phases"])}'
                        f'<h4>Who</h4>{body}')
        else:
            per_pull = []
            for p in pulls:
                hit = next((a for a in p['analysis'].get('abilities') or [] if a['name'] == ability['name']), None)
                n = 0
                if hit:
                    for name, c in analyzer.mistake_counts(hit).items():
                        if not (tag == analyzer.TAG_AVOIDABLE_NON_TANK and roster.get(name, {}).get('role') == 'tank'):
                            n += c
                per_pull.append((p['number'], n))
            body = f'<h4>Hits per pull</h4>{per_pull_columns(per_pull)}<h4>Who</h4>{body}'
        groups['Avoidable mechanics'].append(_row('🎯', sentence, body, 'bad'))

    # --- Interrupts & dispels ---------------------------------------------------
    for entry in merged['interrupts']:
        missed = entry['begun'] - entry['count']
        sentence = (f'Interrupted {esc(entry["name"])}{guide_button(guide_for(entry["id"], entry["name"]), entry["name"])} '
                    f'<strong>{entry["count"]}/{entry["begun"]}</strong> times')
        groups['Interrupts & dispels'].append(_row('✋', sentence, players_bars(entry['by'], 'Interrupts'),
                                                   'bad' if missed > 0 else 'good'))
    for entry in merged['dispels']:
        sentence = (f'Dispelled {esc(entry["name"])}{guide_button(guide_for(entry["id"], entry["name"]), entry["name"])} '
                    f'<strong>{_plural(entry["count"], "time")}</strong>')
        groups['Interrupts & dispels'].append(_row('✨', sentence, players_bars(entry['by'], 'Dispels')))

    # --- Consumables -------------------------------------------------------------
    potions, potion_pulls, defensives = {}, {}, {}
    for a in analyses:
        for name, n in (a.get('potions') or {}).items():
            potions[name] = potions.get(name, 0) + n
            potion_pulls[name] = potion_pulls.get(name, 0) + 1
        for name, n in (a.get('defensives') or {}).items():
            defensives[name] = defensives.get(name, 0) + n
    without = [n for n in roster if n not in potions]
    missing = (f'<p class="small muted">No potion: {", ".join(pname(n) for n in sorted(without))}</p>'
               if without else '')
    ready = readycheck.summary(pulls, merged['players'])
    if ready:
        groups['Consumables'].append(_row('📋', ready[0], ready[1], ready[2]))
    elif analyses:
        groups['Consumables'].append(_row('📋', 'Ready check (flask, food, enchants)', REANALYZE_HINT))
    detailed = consumables.has_details(analyses)
    ordered_roster = merged['players']
    if single:
        sentence = (f'Used <strong>{_plural(sum(potions.values()), "combat potion")}</strong> — '
                    f'{len(potions)}/{raid} players drank one')
        body = players_bars(potions, 'Potions') + missing
    else:
        share = sum(potion_pulls.values()) / (raid * len(pulls))
        sentence = (f'Used <strong>{_plural(sum(potions.values()), "combat potion")}</strong> — players potted in '
                    f'{share:.0%} of their pulls')
        body = players_bars(potion_pulls, 'Pulls with a potion') + missing
    if detailed:  # which potions, when, per player (click a player for every use)
        body = (f'<h4>Which potions</h4>{consumables.type_summary(pulls, {"potion", "mana"})}'
                f'<h4>Per player — click for every use</h4>'
                f'{consumables.player_rows(pulls, ordered_roster, {"potion", "mana"}, code)}')
    else:
        body += REANALYZE_HINT
    groups['Consumables'].append(_row('🧪', sentence, body, 'bad' if len(without) > raid / 3 else ''))

    used = _plural(sum(defensives.values()), 'healthstone / healing potion', 'healthstones / healing potions')
    healed = sum(u.get('healing') or 0 for a in analyses for u in a.get('consumables') or [] if u['kind'] == 'defensive')
    sentence = f'Used <strong>{used}</strong>' + (f', healing for <strong>{fmt_amount(healed)}</strong>' if healed else '')
    if detailed:
        body = (f'<h4>Which ones</h4>{consumables.type_summary(pulls, {"defensive"})}'
                f'<h4>Per player — click for every use</h4>'
                f'{consumables.player_rows(pulls, ordered_roster, {"defensive"}, code)}')
    else:
        body = players_bars(defensives, 'Used') + REANALYZE_HINT
    groups['Consumables'].append(_row('❤️', sentence, body))

    out = ['<div style="text-align:right"><button type="button" class="btn btn-secondary btn-sm expand-all">'
           'Expand all</button></div>']
    for title, rows in groups.items():
        if rows:
            out.append(f'<div class="insight-group">{title}</div>{"".join(rows)}')
    return ''.join(out)


def death_strip_rows(code, pulls):
    """Rows for render.deaths_strip from [(pull_number, pull record with analysis)]."""
    rows = []
    for number, pull in pulls:
        analysis = analyzer.annotate_deaths(pull.get('analysis') or {})
        result = 'Kill' if pull['kill'] else f"{pull['fight_pct'] or 0:.1f}%"
        rows.append({'label': f'#{number}  {result}', 'href': f'/admin/raids/report/{code}/{pull["fight_id"]}',
                     'duration': pull['end_ms'] - pull['start_ms'], 'kill': pull['kill'],
                     'phases': [p['start'] for p in (pull.get('phases') or [])[1:]],
                     'deaths': analysis.get('deaths') or [], 'wipe_at': analysis.get('wipe_at')})
    return rows
