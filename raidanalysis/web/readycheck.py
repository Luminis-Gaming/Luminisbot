"""
Ready check: flask, food, augment rune, raid buffs, item level, tier, gems and
missing enchants at the pull - from each player's combatantinfo event
(ANALYSIS_VERSION 5+; older nights show a re-analyze hint).
"""
from .. import analyzer
from .render import ROLE_ICONS, esc, player_name


def has_data(analyses):
    return any('prepull' in a for a in analyses)


def _mark(ok, title=''):
    return (f'<span class="good-text" title="{esc(title)}">✓</span>' if ok
            else '<span class="bad-text">✗</span>')


def summary(pulls, roster):
    """(sentence, body_html, tone) for the Mechanics list."""
    single = len(pulls) == 1
    per_player = {}
    for pull in pulls:
        for name, prepull in (pull['analysis'].get('prepull') or {}).items():
            per_player.setdefault(name, []).append(prepull)
    if not per_player:
        return None
    latest = {name: entries[-1] for name, entries in per_player.items()}
    expected = analyzer.expected_enchant_slots(latest.values())

    def missing_enchants(prepull):
        return [analyzer.GEAR_SLOTS[int(slot)] for slot, done in
                sorted((prepull.get('enchants') or {}).items(), key=lambda kv: int(kv[0]))
                if slot in expected and not done]

    rows, totals = [], {'flask': 0, 'food': 0, 'augment': 0, 'checks': 0}
    missing_players = 0
    for player in roster:
        entries = per_player.get(player['name'])
        if not entries:
            continue
        n = len(entries)
        counts = {k: sum(1 for e in entries if e.get(k)) for k in ('flask', 'food', 'augment')}
        for k in counts:
            totals[k] += counts[k]
        totals['checks'] += n
        last = entries[-1]
        missing = missing_enchants(last)
        missing_players += 1 if missing else 0

        def cell(key):
            if single:
                return _mark(bool(last.get(key)), last.get(key) or '')
            cls = 'good-text' if counts[key] == n else 'bad-text' if counts[key] / n < 0.75 else ''
            return f'<span class="{cls}">{counts[key]}/{n}</span>'
        rows.append(f"""
            <tr>
                <td>{ROLE_ICONS.get(player.get('role'), '')} {player_name(player['name'], player.get('class', ''))}</td>
                <td class="num">{cell('flask')}</td><td class="num">{cell('food')}</td>
                <td class="num">{cell('augment')}</td>
                <td class="num">{last.get('ilvl') or ''}</td>
                <td class="num">{last.get('tier', '')}</td>
                <td class="num">{last.get('gems', '')}</td>
                <td class="small{' bad-text' if missing else ''}">{esc(', '.join(missing)) or '<span class="good-text">✓</span>'}</td>
            </tr>""")

    checks = totals['checks'] or 1
    if single:
        n_players = len(rows)
        sentence = (f"Ready check: <strong>{totals['flask']}/{n_players}</strong> flask · "
                    f"<strong>{totals['food']}/{n_players}</strong> food · "
                    f"<strong>{totals['augment']}/{n_players}</strong> augment rune")
    else:
        sentence = (f"Ready check: flask in <strong>{totals['flask'] / checks:.0%}</strong> of pulls · "
                    f"food <strong>{totals['food'] / checks:.0%}</strong> · "
                    f"augment rune <strong>{totals['augment'] / checks:.0%}</strong>")
    if missing_players:
        sentence += f" · <strong>{missing_players}</strong> missing enchants"

    # Raid buffs that weren't on everyone at the pull (dead / out of range / class missing)
    buff_notes = []
    for buff in analyzer.RAID_BUFFS:
        covered = sum(1 for p in pulls for pp in (p['analysis'].get('prepull') or {}).values() if buff in pp['buffs'])
        possible = sum(len(p['analysis'].get('prepull') or {}) for p in pulls)
        if covered and covered < possible:
            buff_notes.append(f'{esc(buff)} {covered / possible:.0%}')
        elif not covered and possible:
            buff_notes.append(f'<span class="muted">{esc(buff)} — nobody had it (class not in raid?)</span>')
    buffs_html = (f'<p class="small">Raid buffs not on everyone at the pull: {" · ".join(buff_notes)}</p>'
                  if buff_notes else '<p class="small good-text">Every raid buff was on everyone at the pull.</p>')
    slots = ', '.join(analyzer.GEAR_SLOTS[int(s)] for s in sorted(expected, key=int))
    body = (f'{buffs_html}<p class="muted small">Enchants are checked on the slots most of the raid enchants: '
            f'{esc(slots)}. Item level, tier pieces and gems are from {"the pull" if single else "the latest pull"}.</p>'
            f'<div class="table-wrapper"><table class="compact"><tr><th>Player</th><th class="num">Flask</th>'
            f'<th class="num">Food</th><th class="num">Rune</th><th class="num">Item level</th>'
            f'<th class="num">Tier</th><th class="num">Gems</th><th>Missing enchants</th></tr>{"".join(rows)}</table></div>')
    tone = 'bad' if missing_players or totals['flask'] < 0.9 * checks else 'good'
    return sentence, body, tone
