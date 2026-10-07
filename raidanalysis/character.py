"""
One character across every raid night we keep - the character page (web/character.py) and the front
page's Characters tab. All from stored pulls: no WCL request.

Per boss (and difficulty) and night: our execution score for the night (analyzer.player_report, with the
rest of the raid that night - the same number the night's pages show), their best Warcraft Logs parse that
night, pulls, kills, early deaths, avoidable hits. From those: progression per boss, a timeline of nights
and a few highlights.
"""
from . import analyzer, db, guides, throughput

MIN_IMPROVED_NIGHTS = 3   # "most improved" needs this many nights on a boss
MIN_CLEAN_PULLS = 5       # a "clean night" needs this many pulls


def roster(zone_id=None, difficulty=None, team=None):
    """Everyone in our logs, one entry per name and realm (db.list_characters)."""
    return db.list_characters(zone_id, difficulty, team)


def player_characters(name):
    """
    Every character of the player behind this one (db.character_owners: raid signups first, then linked Battle.net
    characters), this one included, most nights first - [] when nobody owns it or it's their only one.
    """
    owners = db.character_owners()
    me = owners.get(name.lower())
    if not me:
        return []
    names = {n for n, o in owners.items() if o['key'] == me['key']}
    if len(names) < 2:
        return []
    chars = db.list_characters(names=names)
    return sorted(chars, key=lambda c: (-c['nights'], -c['last_seen'], c['name'])) if len(chars) > 1 else []


def resolve(name, realm_slug=None):
    """
    (realm or None, [other realms]) for a URL's name (and realm slug): the realm we know it on that matches the
    slug - else, without a slug, the only one we know (several: None, and the list to pick from).
    """
    from .armory import realm_slug as slug
    known = [r['realm'] for r in db.realms_for(name)]
    if realm_slug:
        return next((r for r in known if slug(r) == realm_slug), None), known
    return (known[0] if len(known) == 1 else None), known


def _parse(analysis, name):
    me = (((analysis.get('extras') or {}).get('players') or {}).get(name)) or {}
    rank = (me.get('parse') or {}).get('rank')
    return float(rank) if rank is not None else None


def _amount(analysis, name, role, duration):
    me = (((analysis.get('extras') or {}).get('players') or {}).get(name)) or {}
    total = me.get('healing') if role == 'healer' else me.get('damage')
    return total / (duration / 1000) if total and duration else None


ALL = 'all'


def tiers_of(pulls):
    """The raid tiers in these pulls, newest first: [{'zone_id', 'zone_name', 'nights', 'last'}]."""
    tiers = {}
    for p in pulls:
        t = tiers.setdefault(p.get('zone_id'), {'zone_id': p.get('zone_id'), 'zone_name': p.get('zone_name') or 'Unknown zone',
                                               'codes': set(), 'last': 0})
        t['codes'].add(p['report_code'])
        t['last'] = max(t['last'], p['report_start'])
    return [{'zone_id': t['zone_id'], 'zone_name': t['zone_name'], 'nights': len(t['codes']), 'last': t['last']}
            for t in sorted(tiers.values(), key=lambda t: -t['last'])]


MAIN_DIFFICULTY_SHARE = 0.2  # the default difficulty: the hardest with at least this share of their pulls in the tier


def filter_pulls(pulls, tier=None, difficulty=None):
    """
    (pulls, tier, difficulty, difficulties) - the pulls of one raid tier (None: their latest; ALL: every tier) and
    difficulty (None: the hardest they've really raided there - MAIN_DIFFICULTY_SHARE of their pulls, so early
    Heroic farm doesn't outweigh Mythic progression and a stray Mythic pull doesn't take over; ALL: every one -
    not the default, as farm and progression nights mixed make the trends jump). difficulties: [(difficulty,
    pulls)] in that tier, hardest first.
    """
    tiers = tiers_of(pulls)
    known = {t['zone_id'] for t in tiers}
    if tier != ALL and tier not in known:
        tier = tiers[0]['zone_id'] if tiers else ALL
    in_tier = pulls if tier == ALL else [p for p in pulls if p.get('zone_id') == tier]
    counts = {}
    for p in in_tier:
        counts[p['difficulty']] = counts.get(p['difficulty'], 0) + 1
    difficulties = sorted(counts.items(), key=lambda d: -d[0])
    if difficulty != ALL and difficulty not in counts:
        total = sum(counts.values())
        difficulty = next((d for d, n in difficulties if n >= MAIN_DIFFICULTY_SHARE * total), ALL) if counts else ALL
    chosen = in_tier if difficulty == ALL else [p for p in in_tier if p['difficulty'] == difficulty]
    return chosen, tier, difficulty, difficulties


def profile(name, realm=None, tier=None, difficulty=None):
    """
    {'name', 'realm', 'class', 'spec', 'role', 'bosses': [boss], 'nights': [night], 'totals', 'highlights',
    'latest_code', 'tiers', 'tier', 'difficulties', 'difficulty'} or None when they're in none of our logs.
    realm (WCL's spelling, e.g. 'TarrenMill'): only that realm's character of the name. tier (a zone id) and
    difficulty narrow it (filter_pulls: their latest tier and hardest real difficulty by default; ALL for every one).
    boss: {'key', 'name', 'difficulty', 'pulls', 'kills', 'best_parse', 'best_parse_wipe', 'best_pct', 'nights': [entry],
    'first_kill'}. Parses: kill parses only, whenever there are any (throughput.counted_parses) - else a wipe's, with
    its *_wipe flag set (shown as not counting); totals 'best_parse' / 'avg_parse' / 'parse_wipe' the same way.
    night: {'code', 'title', 'date', 'zone', 'entries': [entry]}; entry: {'code', 'date', 'boss', 'difficulty',
    'key', 'score', 'parse', 'parse_wipe', 'amount', 'pulls', 'kills', 'best_pct' (boss % left, 0 = killed), 'deaths',
    'avoidable', 'interrupts', 'fight_id' (the night's last pull of it)}
    """
    every = db.character_pull_index(name, realm)
    if not every:
        return None
    latest_code = every[-1]['report_code']
    tiers = tiers_of(every)
    pulls, tier, difficulty, difficulties = filter_pulls(every, tier, difficulty)
    groups = {}  # (code, encounter, difficulty) -> their pulls, in night order
    for p in pulls:
        groups.setdefault((p['report_code'], p['encounter_id'], p['difficulty']), []).append(p)
    summaries = group_summaries(list(groups))
    me_last = {}
    entries = []
    for (code, encounter, difficulty), boss_pulls in groups.items():
        mine = (summaries.get((code, encounter, difficulty)) or {}).get(name)
        if not mine:
            continue
        me_last = mine
        entries.append({'code': code, 'date': boss_pulls[0]['report_start'], 'title': boss_pulls[0]['report_title'],
                        'zone': boss_pulls[0]['zone_name'], 'boss': boss_pulls[0]['encounter_name'],
                        'difficulty': difficulty, 'key': (encounter, difficulty),
                        **{k: v for k, v in mine.items() if k not in ('class', 'spec', 'role')}})
    if not entries:
        return None

    bosses = {}
    for e in entries:
        b = bosses.setdefault(e['key'], {'key': e['key'], 'name': e['boss'], 'difficulty': e['difficulty'], 'pulls': 0,
                                         'kills': 0, 'best_parse': None, 'best_parse_wipe': False, 'nights': [],
                                         'first_kill': None, 'best_pct': 100.0})
        b['pulls'] += e['pulls']
        b['best_pct'] = min(b['best_pct'], e['best_pct'])
        b['kills'] += e['kills']
        b['nights'].append(e)
        if e['kills'] and b['first_kill'] is None:
            b['first_kill'] = e['date']
    for b in bosses.values():  # a kill parse on any night beats every wipe's
        best, b['best_parse_wipe'] = _best_parse(b['nights'])
        b['best_parse'] = max(best) if best else None
    # hardest difficulty first, then the most recently pulled
    boss_list = sorted(bosses.values(), key=lambda b: (-b['difficulty'], -b['nights'][-1]['date']))

    nights = {}
    for e in entries:
        n = nights.setdefault(e['code'], {'code': e['code'], 'title': e['title'], 'date': e['date'], 'zone': e['zone'],
                                          'entries': []})
        n['entries'].append(e)
    night_list = sorted(nights.values(), key=lambda n: n['date'])

    parses, parse_wipe = _best_parse(entries)
    totals = {'nights': len(night_list), 'pulls': sum(e['pulls'] for e in entries),
              'kills': sum(e['kills'] for e in entries), 'bosses_killed': sum(1 for b in boss_list if b['kills']),
              'best_parse': max(parses) if parses else None,
              'avg_parse': sum(parses) / len(parses) if parses else None, 'parse_wipe': parse_wipe,
              'score': round(sum(e['score'] * e['pulls'] for e in entries) / sum(e['pulls'] for e in entries)),
              'interrupts': sum(e['interrupts'] for e in entries)}
    return {'name': name, 'realm': realm, 'class': me_last.get('class') or '', 'spec': me_last.get('spec') or '',
            'role': me_last.get('role') or 'dps', 'bosses': boss_list, 'nights': night_list, 'totals': totals,
            'highlights': highlights(entries, boss_list), 'latest_code': latest_code, 'tiers': tiers, 'tier': tier,
            'difficulties': difficulties, 'difficulty': difficulty}


# A night's boss, summed up for everyone in it (group_summaries) - kept until the data changes (or an officer's
# tags do: forget()), so every character page of that raid reuses it, and the warmer builds the tier's ahead.
SUMMARIES_MAX = 4000
_summaries = {}


def forget():
    _summaries.clear()


def group_summaries(groups):
    """
    {(code, encounter, difficulty): {name: summary}} for these nights' bosses: each scored once for the whole raid
    (analyzer.player_report over every pull of it - the same numbers the night's pages show) - the kept ones as
    they are, the rest loaded together (db.group_pulls). summary: {'class', 'spec', 'role', 'score', 'parse',
    'parse_wipe', 'amount', 'pulls', 'kills', 'best_pct', 'fight_id', 'deaths', 'avoidable', 'interrupts', 'alive'}.
    """
    version = guides._data_version()
    missing = [g for g in groups if (g, version) not in _summaries]
    if missing:
        by_group = {}
        for p in db.group_pulls(missing):
            by_group.setdefault((p['report_code'], p['encounter_id'], p['difficulty']), []).append(p)
        if len(_summaries) + len(missing) > SUMMARIES_MAX:
            _summaries.clear()
        for g in missing:
            _summaries[(g, version)] = _summarise(g[1], by_group.get(g) or [])
    return {g: _summaries[(g, version)] for g in groups}


def _summarise(encounter, boss_pulls):
    """One night's boss for everyone in it: {name: summary} (group_summaries)."""
    if not boss_pulls:
        return {}
    tags = guides.effective_tags(encounter)[0]
    insight = [{'number': i, 'kill': p['kill'], 'analysis': dict(p['analysis'] or {}, _duration=p['end_ms'] - p['start_ms'])}
               for i, p in enumerate(boss_pulls, 1)]
    guides.apply_death_only(encounter, tags, [x['analysis'] for x in insight])
    out = {}
    for row in analyzer.player_report(insight, tags):
        name = row['name']
        mine = [(p, x['analysis']) for p, x in zip(boss_pulls, insight)
                if any(q.get('name') == name for q in x['analysis'].get('players') or [])]
        if not mine:
            continue
        parses, parse_wipe = throughput.counted_parses([(_parse(a, name), p['kill']) for p, a in mine])
        amounts = [v for v in (_amount(a, name, row.get('role'), p['end_ms'] - p['start_ms']) for p, a in mine) if v]
        out[name] = {'class': row.get('class'), 'spec': row.get('spec'), 'role': row.get('role'), 'score': row['score'],
                     'parse': max(parses) if parses else None, 'parse_wipe': parse_wipe and bool(parses),
                     'amount': sum(amounts) / len(amounts) if amounts else None,
                     'pulls': len(mine), 'kills': sum(1 for p, _ in mine if p['kill']),
                     'best_pct': min(0.0 if p['kill'] else float(p['fight_pct'] or 100) for p, _ in mine),
                     'fight_id': mine[-1][0]['fight_id'], 'deaths': row['deaths'], 'avoidable': row['avoidable_hits'],
                     'interrupts': row['interrupts'],
                     'alive': [not any(d['name'] == name and d.get('early') for d in a.get('deaths') or [])
                               for _, a in mine]}
    return out


def _best_parse(entries):
    """(the entries' parses that count, from_wipes): kill parses when any entry has one, else the wipes' (flagged)."""
    vals, wipe = throughput.counted_parses([(e['parse'], not e['parse_wipe']) for e in entries])
    return vals, wipe and bool(vals)


def highlights(entries, bosses):
    """The fun facts: [{'icon', 'title', 'text', 'tone'}] - best parse, most improved, streaks, first kills."""
    out = []
    # kill parses only: a 100 on a 20 s wipe isn't one to brag about
    best = max((e for e in entries if e['parse'] is not None and not e['parse_wipe']), key=lambda e: e['parse'],
               default=None)
    if best:
        out.append({'icon': '🏆', 'title': f"{best['parse']:.0f} parse", 'tone': 'parse',
                    'text': f"Best parse - {best['boss']}, {_date(best['date'])}"})
    improved = []
    for b in bosses:
        scores = [e['score'] for e in b['nights']]
        if len(scores) >= MIN_IMPROVED_NIGHTS:
            improved.append((scores[-1] - scores[0], b, scores))
    if improved:
        gain, b, scores = max(improved, key=lambda x: x[0])
        if gain > 0:
            out.append({'icon': '📈', 'title': f'+{gain:.0f} score', 'tone': 'good',
                        'text': f"Most improved - {b['name']}, {scores[0]:.0f} → {scores[-1]:.0f} over {len(scores)} nights"})
    streak = run = 0
    for e in entries:  # night order
        for alive in e['alive']:
            run = run + 1 if alive else 0
            streak = max(streak, run)
    if streak >= 5:
        out.append({'icon': '🛡️', 'title': f'{streak} pulls', 'tone': 'good',
                    'text': 'Longest streak without an early death'})
    clean = [e for e in entries if e['pulls'] >= MIN_CLEAN_PULLS and not e['deaths'] and not e['avoidable']]
    if clean:
        e = max(clean, key=lambda e: e['pulls'])
        out.append({'icon': '✨', 'title': 'Clean night', 'tone': 'good',
                    'text': f"{e['pulls']} pulls of {e['boss']} without an early death or avoidable hit, {_date(e['date'])}"})
    kills = sorted((b for b in bosses if b['first_kill']), key=lambda b: b['first_kill'])
    if kills:
        b = kills[-1]
        out.append({'icon': '⚔️', 'title': 'Latest first kill', 'tone': 'kill',
                    'text': f"{b['name']} ({_diff(b['difficulty'])}), {_date(b['first_kill'])}"})
    interrupts = sum(e['interrupts'] for e in entries)
    if interrupts >= 20:
        out.append({'icon': '🛑', 'title': f'{interrupts} interrupts', 'tone': 'good', 'text': 'Kicks across every night'})
    return out


def _date(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime('%d %b %Y').lstrip('0')


def _diff(difficulty):
    return {1: 'LFR', 3: 'Normal', 4: 'Heroic', 5: 'Mythic'}.get(difficulty, str(difficulty))
