"""
Coaching for one player's raid night - what the "📊 My performance" recap says.

Every insight the data has is a candidate - mechanics and deaths (analyzer feedback), priority adds and
reaction, potion timing (the focus data), cooldowns against the top players, rotation and uptime, wasted
procs, active time, output (parses, most damage to a priority add) - each with an impact (0-100: how much
it cost you, or how good it was). Impacts are weighted by how much the boss mattered tonight: the hardest
difficulty first - every Mythic boss over every Heroic one over every Normal one - then, within a difficulty,
the later bosses of the raid and the ones you pulled most; an easy one- or two-pull kill hardly counts -
nobody needs three tips about a boss that died first try. The best-weighted few become "work on" and
"going well".

Tips fit the role. DPS get everything. Healers get no add tips (damage share, reaction, potion timing
against spawns - not their job), gentler rotation tips (a healer casts to the damage coming in, not on
cooldown) and their healing parse; a "most healing of the raid's healers" when it's so. Tanks keep the add
praise but not the add complaints (picking up and holding things isn't topping the damage on them).

Focus insights need a pull's focus data from Warcraft Logs: `night(load=True)` fetches it (and everyone's
damage per target) for the key pull - the kill, else the furthest wipe - of the most important bosses.
Runs in a worker thread (the Discord button: asyncio.to_thread), so the loads use asyncio.run.
"""
import asyncio
import logging
import re

from . import analyzer, benchmarks, bossmech, db, defensives, focus, guides, throughput

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

ORDER_SHARE = 0.55   # within a difficulty: how much the boss's place in the raid counts, against pulls
EASY_KILL_FACTOR = 0.5


def boss_weights(bosses, order=None):
    """
    bosses: [{'encounter', 'difficulty', 'pulls', 'killed', 'start'}] -> a weight per boss, 1 for the most important.
    Difficulty first, strictly: each difficulty played tonight is a band, and every boss of a harder one weighs
    more than any boss of an easier one (a Normal last boss never beats a Mythic first boss). Within a band:
    the boss's place in the raid (order: {encounter id: place}, zone_order(); unknown - the night's order) and
    how much it was pulled; an easy kill (EASY_KILL_PULLS or fewer) counts for half.
    """
    if not bosses:
        return []
    order = order or {}
    bands = sorted({b.get('difficulty') or 0 for b in bosses})
    places = sorted(order.values()) if order else []
    last_place = places[-1] if places else 0
    by_night = sorted(bosses, key=lambda b: b['start'])
    raw = []
    for b in bosses:
        band = [x for x in bosses if (x.get('difficulty') or 0) == (b.get('difficulty') or 0)]
        if order and b.get('encounter') in order and last_place:
            place = order[b['encounter']] / last_place
        else:  # boss order unknown: the night's order within the difficulty stands in
            seq = [x for x in by_night if any(x is y for y in band)]
            mine = next(i for i, x in enumerate(seq) if x is b)
            place = mine / (len(seq) - 1) if len(seq) > 1 else 1.0
        effort = b['pulls'] / (max(x['pulls'] for x in band) or 1)
        s = 0.15 + 0.8 * (ORDER_SHARE * place + (1 - ORDER_SHARE) * effort)  # 0.15 .. 0.95: bands never overlap
        if b['killed'] and b['pulls'] <= EASY_KILL_PULLS:
            s *= EASY_KILL_FACTOR
        raw.append(bands.index(b.get('difficulty') or 0) + s)
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
                if role == 'healer':  # healers cast to the damage coming in: a nudge, not "on cooldown"
                    out.append(_insight('bad', 30 * (1 - a['ours'] / a['top']), 'rotation',
                                        f"{a['name']}: {a['ours']:.1f} casts a minute - the top {label} {a['top']:.1f}. "
                                        f"Worth fitting in more often."))
                else:
                    out.append(_insight('bad', 60 * (1 - a['ours'] / a['top']), 'rotation',
                                        f"{a['name']}: {a['ours']:.1f} casts a minute - the top {label} {a['top']:.1f}. "
                                        f"Press it whenever it's ready."))
            # ...or the other way: a filler pressed far more than they do is in the place of something better
            # (not for healers: a heal spammed through heavy damage is the job, not a mistake)
            over = [a for a in cpm['abilities'] if a['verdict'] in ('over', 'way_over')
                    and a['top'] >= ROTATION_MIN_CPM] if role != 'healer' else []
            if over:
                a = max(over, key=lambda a: a['ours'] / a['top'])
                out.append(_insight('bad', 40 * min(1.0, (a['ours'] / a['top'] - 1) / 2), 'rotation',
                                    f"{a['name']}: {a['ours']:.1f} casts a minute - the top {label} {a['top']:.1f}. "
                                    f"Pressing it this much usually means a higher-priority spell is waiting."))
            if not low and not over and cpm['verdict'] == 'good':
                out.append(_insight('good', 15, 'rotation', f"Casts per minute on par with the top {label}"))
        buff = throughput.raid_buff(numbered, name, ((data or {}).get('player') or {}).get('class'))
        if buff and buff['missing']:  # the whole raid's damage / health / mana: worth more than any rotation tip
            which = ', '.join(f'#{n}' for n in buff['missing'])
            out.append(_insight('bad', 85, 'raid_buff',
                                f"The raid went without {buff['buff']} in pull{'s' if len(buff['missing']) > 1 else ''} "
                                f"{which} - cast it before every pull"))
        for u in throughput.uptime(numbered, name, top, tracked, data.get('talents')):
            if u['verdict'] == 'off':
                aura = _spell_name(u['name'], u.get('id'), spell_names)
                if not aura:
                    continue  # a tip about "spell 1234" helps nobody
                what = 'on the boss' if u['kind'] == 'debuff' else 'on you'
                out.append(_insight('bad', 70 * (u['top'] - u['ours']), 'uptime',
                                    f"{aura} up {_pct(u['ours'])} of the fight {what} - the top {label} "
                                    f"{_pct(u['top'])}"))
        for p in throughput.proc_rows(numbered, name, top, tracked):
            if p['verdict'] == 'off':
                proc = _spell_name(p['name'], p['id'], spell_names)
                if not proc:
                    continue
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


def _spell_name(name, spell_id=None, known=None):
    """
    A spell's name for a tip. Proc and aura events often carry only the spell id - then the comparison's spell
    list (known: {id: name}), else our Wowhead cache, looked up right now if it never was (the coach runs in a
    worker thread). None when it can't be named.
    """
    if name and not str(name).isdigit():
        return name
    spell_id = spell_id or (int(name) if name and str(name).isdigit() else None)
    if not spell_id:
        return None
    if (known or {}).get(spell_id):
        return known[spell_id]
    from . import spells
    info = db.get_spells([spell_id]).get(spell_id)
    if not info and spell_id not in db.attempted_spell_ids([spell_id]):
        try:
            asyncio.run(spells.fetch_ids([spell_id]))
            info = db.get_spells([spell_id]).get(spell_id)
        except Exception as e:  # no lookup now (e.g. called inside an event loop): the tip just waits
            logger.info(f'[RAIDS] Spell {spell_id} not named for the coach: {e}')
    return (info or {}).get('name') or None


def _role_word(role):
    return 'healers' if role == 'healer' else 'tanks' if role == 'tank' else 'DPS'


def focus_insights(data, number, potions, ranking=None, name=None, role='dps'):
    """
    The key pull's priority adds: your share of damage against the top DPS's, how fast you got on them,
    the potion against the spawn it was for (one potion can't cover every add - one note if it was pressed
    near none of them); most damage to one in the raid. data: focus.load()'s; potions: your combat potions
    that pull; ranking: throughput.target_ranking() of that pull. Healers: none of it; tanks: the praise only.
    """
    if role == 'healer':
        return []
    found = _focus_insights(data, number, potions, ranking, name)
    return [i for i in found if i['tone'] == 'good'] if role == 'tank' else found


def _focus_insights(data, number, potions, ranking, name):
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


def boss_mechanic_insights(encounter_id, numbered, name):
    """
    The boss's curated pass/fail mechanics (bossmech.py) for one player: failing one tends to cost the pull for
    everyone, so it outweighs any rotation tip. A small "going well" when they took part and never failed it.
    """
    out = []
    for mech in bossmech.for_encounter(encounter_id):
        mine, used = [], 0
        for number, pull in numbered:
            analysis = pull.get('analysis') or {}
            fails = bossmech.failures(analysis, mech)
            if fails is None:
                continue  # analyzed before the check
            mine += [(number, f) for f in fails if name in f['players']]
            used += bossmech.uses(analysis, mech, name)
        guide = {'id': mech.guide[0], 'name': mech.guide[1]} if mech.guide else None  # its Mythic Trap clip
        if mine:
            out.append(dict(_insight('bad', 90, 'boss_mechanic', mech.you_failed(name, mine), guide), mechanic=mech.key))
        elif used:
            out.append(dict(_insight('good', 20, 'boss_mechanic', mech.you_ok(used), guide), mechanic=mech.key))
    return out


# A Mythic Trap entry telling people to take it ("Soak together", "Run over droplets", "Split and soak"): a defensive
# up for one of those is taking a mechanic for the team
SOAK_RE = re.compile(r'\b(soak|run over|split|intercept|catch|take (it|the|a))', re.I)


def soak_guide(guide):
    """Whether a Mythic Trap entry is a mechanic someone takes for the raid."""
    return bool(guide) and bool(SOAK_RE.search(f"{guide.get('category') or ''} {guide.get('subtitle') or ''}"))


def defensive_insights(numbered, name, role, guide_for=None):
    """
    Personal defensives against the damage that came (defensives.moments) - healers and DPS; tanks press theirs
    all the time. A star for defensives up through damage aimed at you or a raid-wide burst; a gentle tip only for
    a clear pattern: several pressed when next to nothing came at you while big hits landed with none up (or one
    right before you died). A defensive up through some damage (a soak, a droplet) is never held against anyone:
    what it prevented doesn't show in the damage. Pulls synced before the incoming damage was kept have nothing
    to say. guide_for(ability id, name) -> Mythic Trap entry: a defensive up while soaking a mechanic it says to
    take (soak_guide) earns its own "going well" - taking it for the team.
    """
    if role == 'tank':
        return []
    good, quiet, spikes, soaks, judged = [], [], [], [], 0
    names = {}
    for number, pull in numbered:
        analysis = pull.get('analysis') or {}
        for a in (analysis.get('abilities') or []) + (analysis.get('boss_abilities') or []):
            if a.get('id') and a.get('name'):
                names[a['id']] = a['name']
        found = defensives.moments(analysis, name, defensives.presses(analysis, name), pull['end_ms'] - pull['start_ms'])
        if not found:
            continue
        judged += len(found['presses'])
        died = [d['t'] for d in analysis.get('deaths') or [] if d.get('name') == name and d.get('t') is not None]
        for p in found['presses']:
            soaked = p.get('guarded')
            if soaked and guide_for and soak_guide(guide_for(soaked, names.get(soaked))):
                soaks.append((number, p))
                continue  # praised as a soak - not again as "up for the raid-wide ..." (a soak isn't raid-wide)
            if p['kind'] in ('aimed', 'raid', 'heavy'):
                good.append((number, p))
            elif p['kind'] == 'quiet' and p['name'] not in defensives.NOT_ONLY_DEFENSIVE:
                quiet.append((number, p))  # 'used' (damage came, not heavy - a soak): never held against them
        for s in found['spikes']:
            fatal = any(0 <= t - s['t'] <= (defensives.SPIKE_WINDOW_S + 3) * 1000 for t in died)
            spikes.append((number, dict(s, fatal=fatal)))
    out = []
    if good:
        rank = {'aimed': 0, 'raid': 1, 'heavy': 2}
        number, best = min(good, key=lambda g: (rank[g[1]['kind']], -g[1]['taken']))
        what = names.get(best['ability']) or 'the damage'
        how = {'aimed': f'{what} aimed at you', 'raid': f"the raid-wide {what}", 'heavy': what}[best['kind']]
        text = f"{best['name']} up for {how} (pull #{number}, {_clock(best['t'])})"
        if len(good) > 1:
            text += f" - {len(good)} of your {judged} defensives lined up with heavy damage"
        out.append(_insight('good', 20 + 6 * min(len(good), 4) + (10 if best['kind'] == 'aimed' else 0),
                            'defensive', text))
    if soaks:
        what = sorted({names.get(p['guarded']) for _, p in soaks if names.get(p['guarded'])})
        spells = sorted({p['name'] for _, p in soaks})
        where = ', '.join(f"#{n} {_clock(p['t'])}" for n, p in soaks[:3]) + (' …' if len(soaks) > 3 else '')
        first = soaks[0][1]['guarded']
        out.append(_insight('good', 30 + 5 * min(len(soaks), 4), 'soak',
                            f"Took mechanics for the team with {' / '.join(spells)} up - {', '.join(what) or 'soaks'} "
                            f"({len(soaks)}×: {where})", {'id': first, 'name': names.get(first) or ''}))
    fatal = [s for s in spikes if s[1]['fatal']]
    if (len(quiet) >= 2 and len({n for n, _ in spikes}) >= 2) or (fatal and quiet):
        shown = (fatal or sorted(spikes, key=lambda s: -s[1]['share']))[:2]
        where = ', '.join(f"#{n} {_clock(s['t'])}" for n, s in shown)
        hit = names.get(shown[0][1]['ability']) or 'big hits'
        text = (f"{len(quiet)} of your defensives went out in quiet moments, while {hit} hit you hard with none up "
                f"({where}). Save one for it.")
        if fatal:
            text = (f"You died right after {hit} hit you hard with no defensive up ({where}) - and {len(quiet)} "
                    f"defensive{'s' if len(quiet) != 1 else ''} went out in quiet moments. Save one for it.")
        out.append(_insight('bad', 40 if fatal else 25, 'defensive', text))
    return out


def output_insights(numbered, name, role):
    """
    Your best kill parse in your role's metric (a healer's healing parse), when it's worth a mention - a wipe's
    doesn't count (throughput.counted_parses); for healers, most healing of the raid's healers when it's so.
    """
    rows = throughput.per_pull(numbered, name, role)
    out = []
    if role == 'healer':
        ranked = [r for r in rows if r['raid_rank'] and r['raid_size'] >= 2]
        top = [r for r in ranked if r['raid_rank'] == 1]
        if ranked and len(top) * 2 >= len(ranked):
            out.append(_insight('good', 30, 'healing',
                                f"Most healing of the raid's {ranked[0]['raid_size']} healers"
                                + (f" in {len(top)} of {len(ranked)} pulls" if len(ranked) > 1 else '')))
    parses = [r['parse'] for r in rows if r['parse'] is not None and r['kill']]
    best = max(parses) if parses else None
    if best is not None and best >= 75:
        what = 'healing parse' if role == 'healer' else 'parse'
        out.append(_insight('good', 20 + (best - 75), 'parse', f"Best {what} {best:.0f}"))
    return out, best


# ============================================================================
# The night
# ============================================================================

def _pick(insights, tone, count):
    """
    The best-weighted `count` of one tone - one per (boss, kind), so three rotation tips don't crowd out the rest;
    each boss mechanic (bossmech.py) counts as its own kind - failing two on one boss is two things to work on.
    """
    best = {}
    for i in insights:
        if i['tone'] != tone or i['score'] < MIN_SCORE:
            continue
        key = (i['boss'], i['kind'], i.get('mechanic'))
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
        tags, _ = guides.effective_tags(key[0])
        guides.apply_death_only(key[0], tags, [p.get('analysis') for p in boss_pulls])  # deaths to "deaths only" ones count
        insight_pulls = [{'number': i, 'kill': p['kill'],
                          'analysis': dict(p['analysis'] or {}, _duration=p['end_ms'] - p['start_ms'])}
                         for i, p in numbered]
        row = next((r for r in analyzer.player_report(insight_pulls, tags) if r['name'] == character), None)
        if not row:
            continue
        bosses.append({'name': boss_pulls[0]['encounter_name'], 'encounter': key[0], 'difficulty': key[1], 'key': key,
                       'numbered': numbered,
                       'pulls': len(boss_pulls), 'killed': any(p['kill'] for p in boss_pulls),
                       'best': min((p['fight_pct'] or 0 for p in boss_pulls if not p['kill']), default=None),
                       'start': boss_pulls[0]['start_ms'], 'row': row, 'score': row['score'],
                       'deaths': row['deaths'], 'guide_for': guides.guide_lookup(key[0]), 'star': None})
    for boss, weight in zip(bosses, boss_weights(bosses, db.zone_order(report.get('zone_id')))):
        boss['weight'] = weight

    from .gamedata import tracked_ids
    tracked = tracked_ids()
    insights, missing = [], None
    detail = [b for b in sorted(bosses, key=lambda b: -b['weight']) if b['weight'] >= DETAIL_MIN_WEIGHT][:DETAIL_BOSSES]
    for boss in bosses:
        numbered, role = boss['numbered'], boss['row'].get('role')
        boss['role'] = role
        found = feedback_insights(boss['row'])
        found += boss_mechanic_insights(boss['key'][0], numbered, character)
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
        found += defensive_insights(numbered, character, role, boss['guide_for'])
        more, boss['parse'] = output_insights(numbered, character, role)
        found += more
        if boss['killed'] and boss['pulls'] <= EASY_KILL_PULLS and not boss['deaths']:
            found.append(_insight('good', 15, 'kill', f"Clean kill in {boss['pulls']} pull{'s' if boss['pulls'] != 1 else ''}"))
        if boss in detail and role != 'healer':  # healers get no add tips: no need to load (and pay for) them
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
                    more = focus_insights(data_f, number, potions, ranking, character, role)
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
