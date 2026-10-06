"""
Coaching for one player's raid night - what the "📊 My performance" recap says.

Every insight the data has is a candidate - mechanics and deaths (analyzer feedback), priority adds and
reaction, potion timing (the focus data), cooldowns against the top players, rotation and uptime, wasted
procs, active time, output (parses, most damage to a priority add) - each with an impact (0-100: how much
it cost you, or how good it was). Impacts are weighted by how much the boss mattered tonight: the bosses
you pulled most and ended the night on count; an easy one- or two-pull kill hardly does - nobody needs
three tips about a boss that died first try. The best-weighted few become "work on" and "going well".

Focus insights need a pull's focus data from Warcraft Logs: `night(load=True)` fetches it (and everyone's
damage per target) for the key pull - the kill, else the furthest wipe - of the most important bosses.
Runs in a worker thread (the Discord button: asyncio.to_thread), so the loads use asyncio.run.
"""
import asyncio
import logging

from . import analyzer, benchmarks, db, focus, guides, throughput

logger = logging.getLogger(__name__)

WORK_ON = 3
GOING_WELL = 3
DETAIL_BOSSES = 2          # bosses whose key pull gets the focus data (WCL) - the most important ones
DETAIL_MIN_WEIGHT = 0.5
EASY_KILL_PULLS = 2        # killed in this few pulls: hardly worth coaching on
MIN_SCORE = 8              # weighted impact below this isn't worth a line (an easy kill's tips stay out)
ROTATION_MIN_CPM = 1.0     # a rotation tip: the top players press it at least this often a minute...
ROTATION_MIN_GAP = 0.5     # ...and you're at least this many casts a minute behind


# ============================================================================
# How much each boss matters tonight
# ============================================================================

def boss_weights(bosses):
    """
    bosses: [{'pulls', 'killed', 'start'}] -> a weight per boss, 1 for the most important: more pulls
    count more, the boss the night ended on gets a bonus, an easy kill (EASY_KILL_PULLS or fewer) hardly counts.
    """
    if not bosses:
        return []
    most = max(b['pulls'] for b in bosses) or 1
    last = max(b['start'] for b in bosses)
    raw = []
    for b in bosses:
        w = 0.3 + 0.7 * b['pulls'] / most
        if b['start'] == last:
            w += 0.2
        if b['killed'] and b['pulls'] <= EASY_KILL_PULLS:
            w *= 0.35
        raw.append(w)
    top = max(raw)
    return [w / top for w in raw]


def _insight(tone, impact, kind, text, ability=None, target=None):
    return {'tone': tone, 'impact': max(0.0, min(100.0, impact)), 'kind': kind, 'text': text, 'ability': ability,
            'target': target}


def _pct(v):
    return f'{100 * v:.0f}%'


# ============================================================================
# Insights per boss
# ============================================================================

def _note_kind(note):
    text = note['text'].lower()
    if note.get('ability'):
        return 'mechanic'
    for word, kind in (('die', 'death'), ('death', 'death'), ('potion', 'potion'), ('flask', 'prep'),
                       ('food', 'prep'), ('enchant', 'prep'), ('interrupt', 'utility'), ('dispel', 'utility')):
        if word in text:
            return kind
    return 'note'


def feedback_insights(row):
    """The score's feedback notes (mechanics, deaths, consumables, contributions) on the common scale."""
    return [_insight(n['tone'], 4 * n['weight'], _note_kind(n), n['text'], n.get('ability'))
            for n in row.get('feedback') or [] if n['tone'] in ('bad', 'good')]


def cooldown_insights(data):
    """Major cooldowns lined up (or not) with the top players' moments (benchmarks.notes)."""
    if not data or not data.get('top') or not data.get('rows'):
        return []
    return [_insight(n['tone'], 30 if n['tone'] == 'bad' else 20, 'cooldowns', n['text'])
            for n in benchmarks.notes(data['rows'], data['label'], limit=2) if n['tone'] in ('bad', 'good')]


def rotation_insights(numbered, name, role, data, tracked=frozenset(), spell_names=None):
    """Casts per minute, uptime, wasted procs against the top players; active time against the raid."""
    out = []
    top, label = (data or {}).get('top') or [], (data or {}).get('label') or 'players'
    if top:
        items = {r['name'] for r in data.get('rows') or [] if r['category'] in ('trinket', 'potion')}
        cpm = throughput.cpm(numbered, name, top, items)
        if cpm:
            # A real part of the rotation, and a gap worth a tip - not a button they press now and then
            low = [a for a in cpm['abilities'] if a['verdict'] == 'off' and a['top'] >= ROTATION_MIN_CPM
                   and a['top'] - a['ours'] >= ROTATION_MIN_GAP]
            if low:
                a = min(low, key=lambda a: a['ours'] / a['top'])
                out.append(_insight('bad', 60 * (1 - a['ours'] / a['top']), 'rotation',
                                    f"{a['name']}: {a['ours']:.1f} casts a minute - the top {label} {a['top']:.1f}. "
                                    f"Press it whenever it's ready."))
            # ...or the other way: a filler pressed far more than they do is in the place of something better
            over = [a for a in cpm['abilities'] if a['verdict'] in ('over', 'way_over')
                    and a['top'] >= ROTATION_MIN_CPM]
            if over:
                a = max(over, key=lambda a: a['ours'] / a['top'])
                out.append(_insight('bad', 40 * min(1.0, (a['ours'] / a['top'] - 1) / 2), 'rotation',
                                    f"{a['name']}: {a['ours']:.1f} casts a minute - the top {label} {a['top']:.1f}. "
                                    f"Pressing it this much usually means a higher-priority spell is waiting."))
            if not low and not over and cpm['verdict'] == 'good':
                out.append(_insight('good', 15, 'rotation', f"Casts per minute on par with the top {label}"))
        for u in throughput.uptime(numbered, name, top, tracked):
            if u['verdict'] == 'off':
                what = 'on the boss' if u['kind'] == 'debuff' else 'on you'
                out.append(_insight('bad', 70 * (u['top'] - u['ours']), 'uptime',
                                    f"{u['name']} up {_pct(u['ours'])} of the fight {what} - the top {label} "
                                    f"{_pct(u['top'])}"))
        for p in throughput.proc_rows(numbered, name, top, tracked):
            if p['verdict'] == 'off':
                proc = p['name']
                if str(proc).isdigit():
                    proc = (spell_names or {}).get(p['id']) or 'a proc'
                out.append(_insight('bad', 70 * (p['ours'] - (p['top'] or 0)), 'procs',
                                    f"{_pct(p['ours'])} of your {proc} procs wasted - the top {label} "
                                    f"{_pct(p['top'] or 0)}. Spend it before the next one lands."))
    mine, raid = throughput.active_time(numbered, name, role)
    if mine is not None and raid is not None:
        if raid - mine >= 0.06:
            out.append(_insight('bad', 250 * (raid - mine), 'active',
                                f"Active {_pct(mine)} of the fight - the raid's {_role_word(role)} {_pct(raid)}. "
                                f"Keep casting while you move."))
        elif mine >= 0.97:
            out.append(_insight('good', 10, 'active', f"Active {_pct(mine)} of the fight"))
    return out


def _role_word(role):
    return 'healers' if role == 'healer' else 'tanks' if role == 'tank' else 'DPS'


def focus_insights(data, number, potions, ranking=None, name=None):
    """
    The key pull's priority adds: your share of damage against the top DPS's, how fast you got on them,
    the potion against the spawn it was for (one potion can't cover every add - one note if it was pressed
    near none of them); most damage to one in the raid. data: focus.load()'s; potions: your combat potions
    that pull; ranking: throughput.target_ranking() of that pull.
    """
    from .web.focusview import potion_lead
    out, lined_up = [], False
    wins = focus.windows(data)
    for kind in (k for k in focus.add_types(wins) if k['priority']):
        target, gap = kind['target'], kind['raid_share'] - kind['you_share']
        if gap > 0.15:
            out.append(_insight('bad', 120 * gap, 'focus',
                                f"{target}: you put {_pct(kind['you_share'])} of your damage into it while it was "
                                f"up - the top DPS {_pct(kind['raid_share'])}. Swap to it as soon as it spawns."))
        elif kind['verdict'] == 'good':
            out.append(_insight('good', 30, 'focus', f"On {target}: {_pct(kind['you_share'])} of your damage while it "
                                                    f"was up (the top DPS {_pct(kind['raid_share'])})"))
        if kind['missed']:
            out.append(_insight('bad', 45, 'focus', f"Never hit {target} in {kind['missed']} of its "
                                                    f"{len(kind['spawns'])} spawns"))
        elif kind['reaction'] is not None and kind['reaction'] > 3000:
            out.append(_insight('bad', 8 * kind['reaction'] / 1000, 'reaction',
                                f"{kind['reaction'] / 1000:.1f} s from {target} appearing to your first hit on it"))
        elif kind['reaction'] is not None and kind['reaction'] <= 1500:
            out.append(_insight('good', 20, 'reaction', f"Fast onto {target}: first hit {kind['reaction'] / 1000:.1f} s "
                                                       f"after it appeared"))
        timed = [(w, found) for w, found in ((w, potion_lead(potions, w, wins)) for w in kind['spawns']) if found]
        if timed:
            lined_up = True
            w, (pot, lead) = timed[0]
            end = w['died_at'] if w['died_at'] is not None else w['end']
            buff_end = pot.get('end') or pot['t'] + 30000
            covered = max(0, min(buff_end, end) - max(pot['t'], w['start'])) / max(1, end - w['start'])
            if lead < 0:
                out.append(_insight('bad', 30, 'potion', f"Potion {-lead:.1f} s after {target} appeared - press it "
                                                         f"a few seconds before it spawns"))
            elif covered < 0.5:
                out.append(_insight('bad', 25, 'potion', f"Potion {lead:.1f} s before {target}: its buff covered only "
                                                         f"{_pct(covered)} of it - press it closer to the spawn"))
            elif covered >= 0.7:
                out.append(_insight('good', 30, 'potion', f"Potion {lead:.1f} s before {target}: the buff covered "
                                                          f"{_pct(covered)} of it"))
        place = next((i for i, p in enumerate((ranking or {}).get(target, {}).get('players') or [], 1)
                      if p['name'] == name), None)
        if place == 1:
            out.append(_insight('good', 45, 'star', f"★ Most damage to {target} in the raid (pull #{number})",
                                target=target))
        elif place and place <= 3:
            out.append(_insight('good', 25, 'star', f"#{place} in the raid on {target} (pull #{number})", target=target))
    priority = [w for w in wins if w['priority']]
    if potions and priority and not lined_up:
        first = priority[0]
        out.append(_insight('bad', 25, 'potion', f"Potion at {_clock(potions[0]['t'])} - not lined up with a priority "
                                                 f"add ({first['target']} appeared at {_clock(first['start'])})"))
    return out


def _clock(ms):
    return f'{int(ms // 60000)}:{int(ms % 60000 // 1000):02d}'


def output_insights(numbered, name, role):
    """Your best parse, when it's worth a mention."""
    parses = [r['parse'] for r in throughput.per_pull(numbered, name, role) if r['parse'] is not None]
    if not parses or max(parses) < 75:
        return [], (max(parses) if parses else None)
    best = max(parses)
    return [_insight('good', 20 + (best - 75), 'parse', f"Best parse {best:.0f}")], best


# ============================================================================
# The night
# ============================================================================

def _pick(insights, tone, count):
    """The best-weighted `count` of one tone - one per (boss, kind), so three rotation tips don't crowd out the rest."""
    best = {}
    for i in insights:
        if i['tone'] != tone or i['score'] < MIN_SCORE:
            continue
        key = (i['boss'], i['kind'])
        if key not in best or i['score'] > best[key]['score']:
            best[key] = i
    return sorted(best.values(), key=lambda i: -i['score'])[:count]


def _load(code, pull, name, cooldown_names):
    """The key pull's focus data and everyone's damage per target, from WCL if not stored yet."""
    try:
        data, why = asyncio.run(focus.load(code, pull, name, ((pull.get('analysis') or {}).get('extras') or {}),
                                           cooldown_names))
        if data:
            asyncio.run(focus.load_by_target(code, [pull]))
        return data, why
    except Exception:
        logger.exception('[RAIDS] Coaching data for %s#%s %s failed', code, pull['fight_id'], name)
        return None, 'loading it failed'


def night(code, character_names, load=True):
    """
    One player's night: {'report', 'character', 'other_characters', 'bosses': [{'name', 'difficulty', 'key',
    'pulls', 'killed', 'best', 'score', 'parse', 'deaths', 'weight', 'star', 'guide_for'}] (night order),
    'work_on', 'going_well' (insights with 'boss', 'score', 'guide_for'), 'missing' (why some focus insights
    are missing, or None)} - or {'error'} like the old recap.
    """
    report = db.get_report(code)
    pulls = db.get_pulls(code) if report else []
    if not pulls:
        return {'error': 'not_analyzed' if not report else 'no_raid'}
    played = {}
    for pull in pulls:
        for p in (pull.get('analysis') or {}).get('players') or []:
            if p['name'].lower() in character_names:
                played[p['name']] = played.get(p['name'], 0) + 1
    if not played:
        return {'error': 'not_in_log', 'report': report}
    character = max(played, key=played.get)

    groups = {}
    for pull in pulls:  # night order: by each boss's first pull
        groups.setdefault((pull['encounter_id'], pull['difficulty']), []).append(pull)
    bosses = []
    for key, boss_pulls in groups.items():
        numbered = list(enumerate(boss_pulls, 1))
        insight_pulls = [{'number': i, 'kill': p['kill'],
                          'analysis': dict(p['analysis'] or {}, _duration=p['end_ms'] - p['start_ms'])}
                         for i, p in numbered]
        tags, _ = guides.effective_tags(key[0])
        row = next((r for r in analyzer.player_report(insight_pulls, tags) if r['name'] == character), None)
        if not row:
            continue
        bosses.append({'name': boss_pulls[0]['encounter_name'], 'difficulty': key[1], 'key': key, 'numbered': numbered,
                       'pulls': len(boss_pulls), 'killed': any(p['kill'] for p in boss_pulls),
                       'best': min((p['fight_pct'] or 0 for p in boss_pulls if not p['kill']), default=None),
                       'start': boss_pulls[0]['start_ms'], 'row': row, 'score': row['score'],
                       'deaths': row['deaths'], 'guide_for': guides.guide_lookup(key[0]), 'star': None})
    for boss, weight in zip(bosses, boss_weights(bosses)):
        boss['weight'] = weight

    from .gamedata import tracked_ids
    tracked = tracked_ids()
    insights, missing = [], None
    detail = [b for b in sorted(bosses, key=lambda b: -b['weight']) if b['weight'] >= DETAIL_MIN_WEIGHT][:DETAIL_BOSSES]
    for boss in bosses:
        numbered, role = boss['numbered'], boss['row'].get('role')
        found = feedback_insights(boss['row'])
        try:
            asyncio.run(benchmarks.ensure_spells_for(numbered, character))
            data = benchmarks.for_player(numbered, character)
        except Exception:
            logger.exception('[RAIDS] Top-player comparison for the recap failed')
            data = None
        found += cooldown_insights(data)
        if boss['weight'] >= DETAIL_MIN_WEIGHT:  # rotation tips only where it matters
            spell_names = {sid: info.get('name') for sid, info in ((data or {}).get('spells') or {}).items()}
            found += rotation_insights(numbered, character, role, data, tracked, spell_names)
        more, boss['parse'] = output_insights(numbered, character, role)
        found += more
        if boss['killed'] and boss['pulls'] <= EASY_KILL_PULLS and not boss['deaths']:
            found.append(_insight('good', 15, 'kill', f"Clean kill in {boss['pulls']} pull{'s' if boss['pulls'] != 1 else ''}"))
        if boss in detail:
            key = focus.key_pull(numbered, character)
            if key:
                number, pull = key
                analysis = pull.get('analysis') or {}
                cooldowns = benchmarks.major_casts(analysis, character)
                data_f = focus.cached(code, pull['fight_id'], character)
                if data_f is None and load:
                    data_f, why = _load(code, pull, character, {c[2] for c in cooldowns if c[2]})
                    missing = missing or (None if data_f else why)
                if data_f:
                    potions = [u for u in analysis.get('consumables') or []
                               if u['name'] == character and u.get('kind') == 'potion']
                    stored = focus.by_target_cached(code, pull['fight_id'])
                    ranking = {t['name']: t for t in throughput.target_ranking(
                        [(number, pull)], {pull['fight_id']: stored} if stored is not None else None,
                        {pull['fight_id']: focus.up_cached(code, pull['fight_id'], pull)})}
                    more = focus_insights(data_f, number, potions, ranking, character)
                    found += more
                    boss['star'] = next((i['target'] for i in more if i['kind'] == 'star' and i['impact'] >= 45), None)
        for i in found:
            i.update(boss=boss['name'], score=i['impact'] * boss['weight'], guide_for=boss['guide_for'])
        insights += found
    for boss in bosses:
        del boss['numbered']
    return {'report': report, 'character': character, 'other_characters': sorted(set(played) - {character}),
            'bosses': bosses, 'work_on': _pick(insights, 'bad', WORK_ON),
            'going_well': _pick(insights, 'good', GOING_WELL), 'missing': missing}
