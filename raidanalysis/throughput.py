"""
Throughput, focus and uptime (WowAnalyzer-style) for one pull - stored as analysis['extras'] - and how
a player compares on them with the raid and with the top parses of their spec.

Per pull and player: damage / healing done, active time, their parse (WCL ranks kills; wipes are
scraped from the website, like the Discord log posts do), damage by target, the buffs they gave
themselves and their debuffs on the boss, with when each was up.

Which auras matter isn't listed by hand: an aura counts when the top players of the spec keep it up
a good part of the fight *and* it's one of their own spells (its name is in their Casts table) or one
the game's Cooldown Manager tracks (gamedata.py: Bone Shield, which comes from Marrowrend) - so
Immolation Aura or Flame Shock show up, while Power Infusion or the raid's Bloodlust don't. Wasted
procs (a proc landing while the last one is still unused) are judged on the Cooldown Manager's buffs.

Pure functions only (no I/O).
"""
EXTRAS_VERSION = 1

MAX_BANDS = 60            # stored up/down stretches per aura (for the uptime strip)
MIN_STORED_UPTIME = 0.1   # auras up less than this share of the pull aren't stored
ALWAYS_UP = 0.97          # ...and ones up more than this get no up / down stretches
TOP_TARGETS = 8           # targets stored per player (WCL's table lists at most 5 anyway - everyone's
                          # damage per target comes from focus.load_by_target)
SKIP_AURA_WORDS = ('flask', 'phial', 'well fed', 'potion', 'food', 'augment rune', 'drink')
KEY_AURAS = {'Bone Shield'}

MIN_TOP_UPTIME = 0.4      # one of your spells the top players keep up less than this isn't an uptime goal
MIN_TRACKED_UPTIME = 0.6  # ...a tracked buff that isn't one of your spells: below this it's a proc you spend
                          # (low uptime is good there - see the wasted procs), not a buff to keep up
UPTIME_GOOD_GAP, UPTIME_OK_GAP = 0.05, 0.15  # how far below the top players' uptime (share of the fight)

FOCUS_MIN_SHARE = 0.03    # targets taking less than this share of the damage aren't listed
FOCUS_LOW = 0.7           # less than this × the raid's typical share of damage on a target = low focus
FOCUS_MIN_FLAG = 0.05     # ...and only flagged when the raid puts at least this share into it


def _entries(table):
    return (table or {}).get('entries') or []


def _metric(role):
    return 'hps' if role == 'healer' else 'dps'


# ============================================================================
# One pull -> analysis['extras']
# ============================================================================

def parses_from_rankings(rankings):
    """WCL's report rankings (kills) -> {name: {'rank', 'bracket', 'amount'}}."""
    data = (rankings or {}).get('data', rankings) if isinstance(rankings, dict) else rankings
    out = {}
    for fight in data or []:
        for role in ((fight or {}).get('roles') or {}).values():
            for c in (role or {}).get('characters') or []:
                if isinstance(c, dict) and c.get('name'):
                    out[c['name']] = {'rank': c.get('rankPercent'), 'bracket': c.get('bracketPercent'),
                                      'amount': c.get('amount')}
    return out


def parses_from_scrape(scraped):
    """The website's parse columns (wipes) -> {name: {'rank', 'bracket', 'amount': None}}."""
    return {name: {'rank': v.get('rankPercent'), 'bracket': v.get('bracketPercent'), 'amount': None}
            for name, v in (scraped or {}).items() if isinstance(v, dict)}


def auras(table, fight_start, duration, kind):
    """
    A Buffs / Debuffs table -> [{'id', 'name', 'kind', 'uptime' (ms), 'bands': [[from, to]] in seconds
    into the pull}], one per name (an aura logged under several spell ids keeps its longest) -
    consumables and barely-up auras left out, and no bands for one that's up all fight (kept small:
    every pull's analysis is loaded for a night's pages).
    """
    best = {}
    for a in (table or {}).get('auras') or []:
        name = a.get('name') or ''
        uptime = min(a.get('totalUptime') or 0, duration)
        if not a.get('guid') or any(w in name.lower() for w in SKIP_AURA_WORDS):
            continue
        if not duration or uptime / duration < MIN_STORED_UPTIME:
            continue
        if name in best and best[name]['uptime'] >= uptime:
            continue
        bands = [] if uptime / duration >= ALWAYS_UP else [
            [max(0, (b.get('startTime', fight_start) - fight_start) // 1000),
             max(0, -(-(b.get('endTime', fight_start) - fight_start) // 1000))]
            for b in a.get('bands') or []][:MAX_BANDS]
        best[name] = {'id': a['guid'], 'name': name, 'kind': kind, 'uptime': uptime, 'bands': bands}
    return sorted(best.values(), key=lambda x: -x['uptime'])


ON_OTHERS_SPECS = {'Augmentation'}  # besides healers: specs whose key buffs go on others (Ebon Might, Prescience)
MIN_ON_OTHERS = 0.1                 # a buff on others averaging fewer active than this isn't kept


def wants_on_others(player):
    """Healers (HoTs: Renewing Mist, Rejuvenation, Atonement...) and Augmentation keep buffs up on others."""
    return player.get('role') == 'healer' or player.get('spec') in ON_OTHERS_SPECS


def on_others(table, duration, cast):
    """
    The buffs a player kept on anyone (their own spells only: cast = their Casts table's names) ->
    [{'id', 'name', 'uptime'}]: uptime summed over every target, so uptime / duration = how many were
    active on average (WowAnalyzer's "average Renewing Mists").
    """
    best = {}
    for a in (table or {}).get('auras') or []:
        name = a.get('name') or ''
        if not a.get('guid') or name not in cast or not duration:
            continue
        uptime = a.get('totalUptime') or 0
        if uptime / duration >= MIN_ON_OTHERS and uptime > best.get(name, {}).get('uptime', 0):
            best[name] = {'id': a['guid'], 'name': name, 'uptime': uptime}
    return sorted(best.values(), key=lambda a: -a['uptime'])


def boss_debuffs(tables, fight_start, duration):
    """
    Debuffs a player kept on the bosses (one Debuffs table per boss): each aura once, on the boss it
    was up longest on - on a council that has to die together, a DoT kept on any of them counts.
    """
    best = {}
    for table in tables or []:
        for a in auras(table, fight_start, duration, 'debuff'):
            if a['name'] not in best or a['uptime'] > best[a['name']]['uptime']:
                best[a['name']] = a
    return sorted(best.values(), key=lambda x: -x['uptime'])


def targets(entry):
    """A DamageDone entry's damage by target -> [[name, damage, type]] biggest first (top TOP_TARGETS)."""
    rows = [[t.get('name') or '?', t.get('total') or 0, t.get('type') or ''] for t in (entry or {}).get('targets') or []
            if (t.get('total') or 0) > 0]
    return sorted(rows, key=lambda r: -r[1])[:TOP_TARGETS]


RESOURCE_NAMES = {0: 'Mana', 1: 'Rage', 2: 'Focus', 3: 'Energy', 4: 'Combo Points', 5: 'Runes', 6: 'Runic Power',
                  7: 'Soul Shards', 8: 'Astral Power', 9: 'Holy Power', 11: 'Maelstrom', 12: 'Chi', 13: 'Insanity',
                  16: 'Arcane Charges', 17: 'Fury', 18: 'Pain', 19: 'Essence'}
MANA = 0
MANA_END_RECENT_MS = 30000  # the last mana reading must be this close to the end to say what was left


def resources(events, names_by_id, fight_end):
    """
    resourcechange events -> {name: {'gains': {type: [gained, wasted]}, 'mana_end': share of max or None}}.
    Gains go to the event's target; classResources describe the source (resourceActor 1) or target (2).
    """
    out = {}
    last_mana = {}
    for e in sorted(events or [], key=lambda e: e.get('timestamp') or 0):
        if e.get('type') != 'resourcechange':
            continue
        target = names_by_id.get(e.get('targetID'))
        if target:
            gains = out.setdefault(target, {'gains': {}, 'mana_end': None})['gains']
            g = gains.setdefault(str(e.get('resourceChangeType')), [0, 0])
            g[0] += e.get('resourceChange') or 0
            g[1] += e.get('waste') or 0
        owner = names_by_id.get(e.get('sourceID') if e.get('resourceActor') == 1 else e.get('targetID'))
        for r in e.get('classResources') or []:
            if owner and r.get('type') == MANA and r.get('max'):
                last_mana[owner] = (e['timestamp'], r.get('amount', 0) / r['max'])
    for name, (t, share) in last_mana.items():
        if fight_end - t <= MANA_END_RECENT_MS:
            out.setdefault(name, {'gains': {}, 'mana_end': None})['mana_end'] = share
    return out


MIN_PROCS = 3        # a self-buff applied fewer times than this isn't a proc worth tracking
MAX_PROCS = 100      # ...nor one applied more than this a pull (Flurry, Maelstrom Weapon stacks: ~850 each) -
                     # a stack builder, not a proc to save, and half of the raid's buff events
SAME_MOMENT_MS = 20  # events of one aura this close together are one thing happening


def proc_candidates(per_player, tracked=frozenset()):
    """
    Self-buff ids worth checking for wasted procs (to keep the events request small): procs - buffs that
    aren't a spell the player casts - applied MIN_PROCS to MAX_PROCS times, of the ones the game's
    Cooldown Manager tracks (gamedata.py; without that list, any).
    """
    ids = set()
    for tables in per_player.values():
        cast = set(cast_counts(tables.get('casts')))
        for a in (tables.get('buffs') or {}).get('auras') or []:
            if not a.get('guid') or not MIN_PROCS <= (a.get('totalUses') or 0) <= MAX_PROCS:
                continue
            if a.get('name') in cast or any(w in (a.get('name') or '').lower() for w in SKIP_AURA_WORDS):
                continue  # your own spell's buff (Renewing Mist): not a proc that can go to waste
            if not tracked or a['guid'] in tracked:
                ids.add(a['guid'])
    return sorted(ids)


def proc_waste(events, names_by_id):
    """
    Self-buff events -> {player: {aura: [procs, wasted, spell id]}}. A proc is wasted when it lands while the
    buff is already up at its most stacks (seen in this pull) and nothing is consumed at that moment:
    a lone refreshbuff. A refresh next to a stack being used or the buff ending is the game moving
    the buff along (Spiritfont holds 2 charges: using one refreshes the other), not a lost proc.
    """
    by_aura = {}
    for e in events or []:
        if e.get('sourceID') != e.get('targetID') or e.get('targetID') not in names_by_id:
            continue
        ability = e.get('ability') or {}
        aura = ability.get('name') or e.get('abilityGameID')
        by_aura.setdefault((e['targetID'], aura), []).append(e)
    ids = {}
    for (target, aura), seq in by_aura.items():
        ids[(target, aura)] = next(((e.get('ability') or {}).get('guid') or e.get('abilityGameID') for e in seq), None)
    out = {}
    for (target, aura), seq in by_aura.items():
        seq.sort(key=lambda e: e['timestamp'])
        most = max([e.get('stack') or 1 for e in seq if e['type'] in ('applybuffstack', 'removebuffstack')] + [1])
        stack, procs, wasted = 0, 0, 0
        for i, e in enumerate(seq):
            kind = e['type']
            if kind == 'applybuff':
                stack, procs = 1, procs + 1
            elif kind == 'applybuffstack':
                stack, procs = e.get('stack') or stack + 1, procs + 1
            elif kind == 'removebuffstack':
                stack = e.get('stack') or max(0, stack - 1)
            elif kind == 'removebuff':
                stack = 0
            elif kind == 'refreshbuff':
                near = [o for o in seq[max(0, i - 4):i + 5]
                        if o is not e and abs(o['timestamp'] - e['timestamp']) <= SAME_MOMENT_MS]
                if not near and stack >= most:
                    procs += 1
                    wasted += 1
        if procs >= MIN_PROCS:
            out.setdefault(names_by_id[target], {})[str(aura)] = [procs, wasted, ids[(target, aura)]]
    return out


def _worth_keeping(aura, cast, tracked):
    """Stored auras: the player's own spells and the buffs the Cooldown Manager tracks (all of them without that list)."""
    return not tracked or aura['name'] in cast or aura['id'] in tracked


def build_extras(fight, roster, names_by_id, extras, per_player, parses, resource_events=(), proc_events=(),
                 tracked=frozenset(), detail=True):
    """
    analysis['extras'] for one pull. roster: analysis['players']; extras: wcl.get_fight_extras();
    per_player: wcl.get_player_tables() by actor id; parses: {name: {'rank', 'bracket', 'amount'}};
    resource_events: the pull's resourcechange events; proc_events: self-buff events of proc_candidates();
    tracked: the Cooldown Manager's buff ids (gamedata.py) - procs, enchants and others' buffs aren't kept.
    """
    start = fight['startTime']
    duration = fight['endTime'] - start
    ids_by_name = {name: aid for aid, name in names_by_id.items()}
    done = {e.get('name'): e for e in _entries(extras.get('damageDone'))}
    healed = {e.get('name'): e for e in _entries(extras.get('healing'))}
    gained = resources(resource_events, names_by_id, fight['endTime'])
    procs = proc_waste(proc_events, names_by_id)
    players = {}
    for p in roster:
        name = p['name']
        d, h = done.get(name) or {}, healed.get(name) or {}
        main = h if p.get('role') == 'healer' else d
        tables = per_player.get(ids_by_name.get(name)) or {}
        cast = cast_counts(tables.get('casts')) if tables.get('casts') else None
        kept = [a for a in (auras(tables.get('buffs'), start, duration, 'buff')
                            + boss_debuffs(tables.get('debuffs'), start, duration))
                if _worth_keeping(a, cast or {}, tracked)]
        players[name] = {
            'damage': d.get('total') or 0, 'healing': h.get('total') or 0,
            'active_ms': main.get('activeTime') or d.get('activeTime') or h.get('activeTime'),
            'parse': (dict(parses[name], metric=_metric(p.get('role'))) if name in parses else None),
            'targets': targets(d),
            'auras': kept,
            'casts': cast,
            'resources': gained.get(name),
            'procs': procs.get(name) or {},
            'on_others': (on_others(tables['on_others'], duration, cast or {})
                          if tables.get('on_others') is not None else None),
        }
    raid = {}
    for p in players.values():
        for name, damage, kind in p['targets']:
            t = raid.setdefault(name, {'name': name, 'type': kind, 'total': 0})
            t['total'] += damage
    return {'v': EXTRAS_VERSION, 'detail': detail, 'duration': duration, 'players': players,
            'targets': sorted(raid.values(), key=lambda t: -t['total'])}


def is_item(entry):
    """A trinket / potion / other item use in a Casts table: item icons are inv_* (class spells: inv_ability_*)."""
    icon = (entry.get('abilityIcon') or '').lower()
    return icon.startswith('inv_') and not icon.startswith('inv_ability')


def cast_counts(casts_table):
    """A player's Casts table -> {ability name: casts}, items left out (variants under one name add up)."""
    names = {}
    for e in _entries(casts_table):
        if e.get('name') and (e.get('total') or 0) > 0 and not is_item(e):
            names[e['name']] = names.get(e['name'], 0) + e['total']
    return names


def top_auras(tables, start, duration):
    """A top player's stored auras (no bands) and spell list, from wcl.get_player_tables()."""
    found = (auras(tables.get('buffs'), start, duration, 'buff')
             + boss_debuffs(tables.get('debuffs'), start, duration))
    cast = cast_counts(tables.get('casts'))
    return ([{k: a[k] for k in ('id', 'name', 'kind', 'uptime')} for a in found], cast,
            on_others(tables['on_others'], duration, cast) if tables.get('on_others') is not None else None)


# ============================================================================
# Comparing (render time)
# ============================================================================

def target_ranking(numbered, stored=None):
    """
    Everyone's damage by target over these pulls: [{'name', 'type', 'total', 'main' (the pulls' biggest
    target), 'complete', 'players': [{'name', 'class', 'role', 'damage', 'share' (of the target's total),
    'pulls' (how many of these pulls they hit it in)}]}] - targets by total, players by damage.
    stored: {fight id: {target: {player: damage}}} (focus.by_target_cached - every player); a pull without
    it falls back to its DamageDone table, which lists only each player's top 5 targets ('complete' False).
    """
    targets, mains, complete = {}, {}, True
    for _, pull in numbered:
        analysis = pull.get('analysis') or {}
        extras = analysis.get('extras') or {}
        roster = {p['name']: p for p in analysis.get('players') or []}
        biggest = next(iter(extras.get('targets') or []), None)
        if biggest:
            mains[biggest['name']] = mains.get(biggest['name'], 0) + 1
        full = (stored or {}).get(pull.get('fight_id'))
        if full is not None:
            kinds = {t['name']: t.get('type') or '' for t in extras.get('targets') or []}
            hits = [(name, target, damage, kinds.get(target, ''))
                    for target, players in full.items() for name, damage in players.items()]
        else:
            complete = False
            hits = [(name, target, damage, kind) for name, row in (extras.get('players') or {}).items()
                    for target, damage, kind in row.get('targets') or []]
        for name, target, damage, kind in hits:
            t = targets.setdefault(target, {'name': target, 'type': kind, 'total': 0, 'players': {}})
            t['total'] += damage
            who = roster.get(name) or {}
            p = t['players'].setdefault(name, {'name': name, 'class': who.get('class') or '',
                                               'role': who.get('role') or 'dps', 'damage': 0, 'pulls': 0})
            p['damage'] += damage
            p['pulls'] += 1
    main = max(mains, key=mains.get) if mains else None
    out = []
    for t in targets.values():
        players = sorted(t['players'].values(), key=lambda p: -p['damage'])
        for p in players:
            p['share'] = p['damage'] / t['total'] if t['total'] else 0
        out.append(dict(t, players=players, main=t['name'] == main, complete=complete))
    return sorted(out, key=lambda t: -t['total'])


def player_pulls(numbered, name):
    """[(number, pull, extras player row, extras)] for the pulls with extras that this character was in."""
    out = []
    for number, pull in numbered:
        extras = (pull.get('analysis') or {}).get('extras') or {}
        me = (extras.get('players') or {}).get(name)
        if me is not None:
            out.append((number, pull, me, extras))
    return out


def detail_pulls(numbered, name):
    """player_pulls() of the pulls that have the per-player detail (kills and the furthest wipes - sync.py)."""
    return [m for m in player_pulls(numbered, name) if m[3].get('detail', True)]


def amount(row, role, duration):
    """Damage (or healing, for healers) per second."""
    total = row['healing'] if role == 'healer' else row['damage']
    return total / (duration / 1000) if duration else 0


def per_pull(numbered, name, role):
    """
    One row per pull: [{'number', 'kill', 'fight_id', 'parse', 'bracket', 'amount', 'active', 'raid_rank',
    'raid_size'}] - raid rank among players of the same role.
    """
    rows = []
    for number, pull, me, extras in player_pulls(numbered, name):
        duration = extras.get('duration') or (pull['end_ms'] - pull['start_ms'])
        roles = {p['name']: p.get('role') for p in (pull.get('analysis') or {}).get('players') or []}
        same = sorted((amount(r, role, duration) for n, r in extras['players'].items() if roles.get(n) == role),
                      reverse=True)
        mine = amount(me, role, duration)
        parse = me.get('parse') or {}
        rows.append({'number': number, 'kill': pull.get('kill'), 'fight_id': pull['fight_id'],
                     'parse': parse.get('rank'), 'bracket': parse.get('bracket'), 'amount': mine,
                     'active': (me['active_ms'] / duration) if me.get('active_ms') and duration else None,
                     'raid_rank': same.index(mine) + 1 if mine in same else None, 'raid_size': len(same),
                     'duration': duration})
    return rows


def focus(numbered, name, role):
    """
    Where a player's damage went over these pulls, next to the rest of the raid (same role, else DPS):
    [{'name', 'type', 'mine', 'mine_share', 'raid_share' (median of the others' shares), 'low'}].
    Priority adds show up by themselves: a short-lived add the raid puts 25% of its damage into.
    """
    damage = {}  # player -> {'total', 'targets': {target: damage}} over these pulls
    kinds = {}
    peers = role if role != 'healer' else 'dps'
    for _, pull, _, extras in player_pulls(numbered, name):
        roles = {p['name']: p.get('role') for p in (pull.get('analysis') or {}).get('players') or []}
        for t in extras.get('targets') or []:
            kinds.setdefault(t['name'], t.get('type'))
        for n, r in extras['players'].items():
            if n != name and roles.get(n) != peers:
                continue
            d = damage.setdefault(n, {'total': 0, 'targets': {}})
            d['total'] += r.get('damage') or 0
            for target, amount_done, _ in r.get('targets') or []:
                d['targets'][target] = d['targets'].get(target, 0) + amount_done
    me = damage.pop(name, {'total': 0, 'targets': {}})
    others = [o for o in damage.values() if o['total']]
    rows = []
    for target in set(me['targets']) | {t for o in others for t in o['targets']}:
        shares = sorted(o['targets'].get(target, 0) / o['total'] for o in others)
        raid_share = shares[len(shares) // 2] if shares else None
        mine_share = me['targets'].get(target, 0) / me['total'] if me['total'] else 0
        if mine_share < FOCUS_MIN_SHARE and (raid_share or 0) < FOCUS_MIN_SHARE:
            continue
        low = (raid_share is not None and raid_share >= FOCUS_MIN_FLAG and mine_share < FOCUS_LOW * raid_share)
        rows.append({'name': target, 'type': kinds.get(target) or '', 'mine': me['targets'].get(target, 0),
                     'mine_share': mine_share, 'raid_share': raid_share, 'low': low})
    return sorted(rows, key=lambda r: -max(r['mine_share'], r['raid_share'] or 0))


def uptime(numbered, name, top, tracked=frozenset()):
    """
    The auras that matter for the spec (see the module doc), yours next to the top players':
    [{'id', 'name', 'kind', 'ours', 'top', 'top_users', 'verdict', 'bands', 'band_duration'}].
    ours / top: share of the fight it was up (top = median of the top players that have it).
    bands: the longest pull's stretches (seconds), for the strip.
    """
    mine = detail_pulls(numbered, name)
    if not mine or not top:
        return []
    need = min(3, len(top))
    spells = set(KEY_AURAS)
    for p in top:
        spells.update((p.get('cast_names') or {}).keys())
    # A HoT like Renewing Mist is about how many are out on the raid (on_others_rows), not the one on you.
    on_raid = {a['name'] for p in top for a in p.get('on_others') or []}
    on_raid |= {a['name'] for _, _, me, _ in mine for a in me.get('on_others') or []}
    seen = {}
    for i, p in enumerate(top):
        if not p.get('duration'):
            continue
        for a in p.get('auras') or []:
            if (a['name'] not in spells and a['id'] not in tracked) or a['name'] in on_raid:
                continue
            s = seen.setdefault((a['name'], a['kind']), {'id': a['id'], 'icon': a.get('icon'), 'shares': {},
                                                         'cast': a['name'] in spells})
            s['shares'][i] = max(s['shares'].get(i, 0), a['uptime'] / p['duration'])
    total = sum(ex.get('duration') or 0 for _, _, _, ex in mine)
    longest = max(mine, key=lambda m: m[3].get('duration') or 0)
    rows = []
    for (aura, kind), s in seen.items():
        shares = sorted(s['shares'].values())
        if len(shares) < need:
            continue
        top_share = shares[len(shares) // 2]
        if top_share < (MIN_TOP_UPTIME if s['cast'] else MIN_TRACKED_UPTIME):
            continue
        up = sum(next((a['uptime'] for a in me['auras'] if a['name'] == aura and a['kind'] == kind), 0)
                 for _, _, me, _ in mine)
        ours = up / total if total else 0
        if min(shares) >= ALWAYS_UP and ours >= ALWAYS_UP:
            continue  # a passive: always up for everyone, nothing to see
        gap = top_share - ours
        verdict = 'good' if gap <= UPTIME_GOOD_GAP else 'ok' if gap <= UPTIME_OK_GAP else 'off'
        strip = next((a for a in longest[2]['auras'] if a['name'] == aura and a['kind'] == kind), None)
        rows.append({'id': s['id'], 'name': aura, 'icon': (strip or {}).get('icon') or s['icon'], 'kind': kind,
                     'ours': ours, 'top': top_share, 'top_users': len(shares), 'verdict': verdict,
                     'bands': (strip or {}).get('bands') or [], 'band_duration': longest[3].get('duration'),
                     'band_pull': longest[0]})
    return sorted(rows, key=lambda r: (r['verdict'] == 'good', -r['top']))


ON_OTHERS_GOOD, ON_OTHERS_OK = 0.9, 0.75   # how many you keep out on average, as a share of the top players'


def on_others_rows(numbered, name, top):
    """
    HoTs and buffs kept on others, as the average number active over the fight, next to the top players
    (median of those who use it): [{'id', 'name', 'ours', 'top', 'top_users', 'verdict'}].
    """
    mine = [m for m in detail_pulls(numbered, name) if m[2].get('on_others') is not None]
    top = [p for p in top or [] if p.get('on_others') is not None and p.get('duration')]
    if not mine:
        return []
    need = min(3, len(top))
    total = sum(ex.get('duration') or 0 for _, _, _, ex in mine)
    ours, ids = {}, {}
    for _, _, me, _ in mine:
        for a in me['on_others']:
            ours[a['name']] = ours.get(a['name'], 0) + a['uptime']
            ids.setdefault(a['name'], a['id'])
    tops = {}
    for p in top:
        for a in p['on_others']:
            tops.setdefault(a['name'], []).append(a['uptime'] / p['duration'])
            ids.setdefault(a['name'], a['id'])
    rows = []
    for aura in set(ours) | {a for a, v in tops.items() if len(v) >= need}:
        mean = ours.get(aura, 0) / total if total else 0
        shares = tops.get(aura, [])
        top_mean = _median(shares) if len(shares) >= need and shares else None
        verdict = None
        if top_mean:
            ratio = mean / top_mean
            verdict = 'good' if ratio >= ON_OTHERS_GOOD else 'ok' if ratio >= ON_OTHERS_OK else 'off'
        rows.append({'id': ids.get(aura), 'name': aura, 'ours': mean, 'top': top_mean, 'top_users': len(shares),
                     'verdict': verdict})
    return sorted(rows, key=lambda r: -max(r['ours'], r['top'] or 0))


MIN_GAINED = 50                 # less of a resource than this over the night says nothing about waste
STRUCTURAL_WASTE = 0.4          # the top players "waste" this much too (Arcane Charges at cap): not judged
WASTE_GOOD_GAP, WASTE_OK_GAP = 0.03, 0.08   # how much more of it you wasted than the top players
MANA_GOOD_GAP, MANA_OK_GAP = 0.10, 0.25     # how much more mana you had left at the end of a kill


def _median(values):
    values = sorted(values)
    return values[len(values) // 2] if values else None


def resource_rows(numbered, name, top, role):
    """
    Resources wasted (gained at the cap), next to the top players - and for healers, the mana left
    unused at the end of the kills: [{'type', 'name', 'gained', 'wasted', 'ours', 'top', 'top_users',
    'verdict'}] (ours / top: share wasted; for mana: share of max left at the end).
    Only judged against the top players: some waste is built into a spec (or only partly logged -
    passive energy regen isn't), so the bar is what the best players of that spec manage.
    """
    mine = detail_pulls(numbered, name)
    top = [p for p in top or [] if p.get('resources')]
    if not mine:
        return []
    need = min(3, len(top))
    totals = {}
    for _, _, me, _ in mine:
        for kind, (got, lost) in ((me.get('resources') or {}).get('gains') or {}).items():
            t = totals.setdefault(kind, [0, 0])
            t[0] += got
            t[1] += lost
    rows = []
    for kind, (got, lost) in sorted(totals.items(), key=lambda kv: -kv[1][0]):
        if int(kind) == MANA or got < MIN_GAINED:
            continue
        shares = [g[1] / g[0] for g in ((p['resources'].get('gains') or {}).get(kind) for p in top) if g and g[0]]
        top_share = _median(shares) if len(shares) >= need and shares else None
        ours = lost / got
        verdict = None
        if top_share is not None and top_share < STRUCTURAL_WASTE:
            gap = ours - top_share
            verdict = 'good' if gap <= WASTE_GOOD_GAP else 'ok' if gap <= WASTE_OK_GAP else 'off'
        rows.append({'type': int(kind), 'name': RESOURCE_NAMES.get(int(kind), f'Resource {kind}'), 'gained': got,
                     'wasted': lost, 'ours': ours, 'top': top_share, 'top_users': len(shares), 'verdict': verdict})
    if role == 'healer':
        left = _median([(me.get('resources') or {}).get('mana_end') for _, pull, me, _ in mine
                        if pull.get('kill') and (me.get('resources') or {}).get('mana_end') is not None])
        top_left = [p['resources'].get('mana_end') for p in top if p['resources'].get('mana_end') is not None]
        if left is not None:
            top_share = _median(top_left) if len(top_left) >= need and top_left else None
            verdict = None
            if top_share is not None:
                gap = left - top_share
                verdict = 'good' if gap <= MANA_GOOD_GAP else 'ok' if gap <= MANA_OK_GAP else 'off'
            rows.insert(0, {'type': MANA, 'name': 'Mana left at the end', 'gained': None, 'wasted': None,
                            'ours': left, 'top': top_share, 'top_users': len(top_left), 'verdict': verdict})
    return rows


CARED_FOR_WASTE = 0.10   # a proc the top players waste less of than this is one they make a point of using
PROC_GOOD_GAP, PROC_OK_GAP = 0.05, 0.12   # how much more of a proc you wasted than the top players


def proc_rows(numbered, name, top, tracked=frozenset()):
    """
    Wasted procs (one landed while the last was still unused), next to the top players: [{'name', 'id',
    'procs', 'wasted', 'ours', 'top', 'top_users', 'verdict'}]. Which procs count: the buffs the game's
    Cooldown Manager tracks for the spec (tracked - gamedata.py); without that list, the ones the top
    players clearly take care to use (CARED_FOR_WASTE) - an enchant proc everyone refreshes isn't one.
    """
    mine = detail_pulls(numbered, name)
    top = [p for p in top or [] if p.get('procs') is not None]
    if not mine:
        return []
    need = min(3, len(top))
    totals = {}
    for _, _, me, _ in mine:
        for aura, (got, lost, sid) in (me.get('procs') or {}).items():
            t = totals.setdefault(aura, [0, 0, sid])
            t[0] += got
            t[1] += lost
    rows = []
    for aura, (got, lost, sid) in totals.items():
        shares = [p['procs'][aura][1] / p['procs'][aura][0] for p in top if (p['procs'].get(aura) or [0])[0]]
        top_share = _median(shares) if len(shares) >= need and shares else None
        if tracked:
            # A tracked buff the top players "waste" a lot of too is one that's meant to be refreshed
            # (Voracious, Icy Talons): not a proc to save.
            if sid not in tracked and not any(p['procs'][aura][2] in tracked for p in top if aura in p['procs']):
                continue
            if top_share is None or top_share >= STRUCTURAL_WASTE:
                continue
        elif top_share is None or top_share > CARED_FOR_WASTE:
            continue
        ours = lost / got if got else 0
        if not lost and not top_share:
            continue  # nobody wastes this one: nothing to see
        verdict = None
        if top_share is not None:
            gap = ours - top_share
            verdict = 'good' if gap <= PROC_GOOD_GAP else 'ok' if gap <= PROC_OK_GAP else 'off'
        rows.append({'name': aura, 'id': sid, 'procs': got, 'wasted': lost, 'ours': ours, 'top': top_share,
                     'top_users': len(shares), 'verdict': verdict})
    return sorted(rows, key=lambda r: (-(r['ours'] - (r['top'] or 0)), r['name']))


CPM_GOOD, CPM_OK = 0.9, 0.75  # your casts per minute as a share of the top players'
MIN_CPM = 0.1                 # pressed less than this by you and the top players: left out of the table
JUDGE_MIN_CPM = 0.5           # the top players press it less than this: downtime filler or situational, not judged


def _cpm_verdict(ours, top):
    if not top:
        return None
    ratio = ours / top
    return 'good' if ratio >= CPM_GOOD else 'ok' if ratio >= CPM_OK else 'off'


def cpm(numbered, name, top, items=frozenset()):
    """
    Casts per minute, overall and for every ability either side cast, next to the top players'
    (median): {'ours', 'top', 'verdict', 'abilities': [{'name', 'ours', 'top', 'top_users', 'casts',
    'verdict'}]} most-pressed first - or None without cast data on either side. Items (trinkets,
    potions: is_item(), plus the names in items) are left out - they're gear, not rotation.
    """
    mine = [(me.get('casts'), ex.get('duration') or 0) for _, _, me, ex in detail_pulls(numbered, name)
            if me.get('casts') is not None]
    minutes = sum(d for _, d in mine) / 60000
    top = [p for p in top or [] if p.get('cast_names') and p.get('duration')]
    if not mine or not minutes or not top:
        return None
    ours = {}
    for casts, _ in mine:
        for ability, n in casts.items():
            ours[ability] = ours.get(ability, 0) + n

    def median(values):
        values = sorted(values)
        return values[len(values) // 2] if values else 0
    top_rates = {}
    for p in top:
        for ability, n in p['cast_names'].items():
            top_rates.setdefault(ability, []).append(n / (p['duration'] / 60000))
    need = min(3, len(top))
    abilities = []
    for ability in (set(top_rates) | set(ours)) - set(items):
        rates = top_rates.get(ability, [])
        # Median over all top players (0 for those who never cast it): a talent only one of them takes
        # doesn't set the bar - and it's only judged when most of them use it.
        top_rate = median(rates + [0] * (len(top) - len(rates)))
        our_rate = ours.get(ability, 0) / minutes
        if our_rate < MIN_CPM and top_rate < MIN_CPM:
            continue
        # Never cast at all is a talent or a trinket you don't have, not a rate to work on; one the top
        # players barely press (a Blackout Kick in downtime) isn't part of the rotation.
        judged = len(rates) >= need and ours.get(ability) and top_rate >= JUDGE_MIN_CPM
        abilities.append({'name': ability, 'ours': our_rate, 'top': top_rate, 'top_users': len(rates),
                          'casts': ours.get(ability, 0),
                          'verdict': _cpm_verdict(our_rate, top_rate) if judged else None})
    abilities.sort(key=lambda a: (-a['top'], -a['ours'], a['name']))
    overall_top = median(sum(p['cast_names'].values()) / (p['duration'] / 60000) for p in top)
    overall = sum(ours.values()) / minutes
    return {'ours': overall, 'top': overall_top, 'verdict': _cpm_verdict(overall, overall_top),
            'abilities': abilities}


def active_time(numbered, name, role):
    """(your active time, the raid's median for your role) as shares of the fight, None when unknown."""
    mine, others = [], {}
    for _, pull, me, extras in player_pulls(numbered, name):
        duration = extras.get('duration') or 0
        roles = {p['name']: p.get('role') for p in (pull.get('analysis') or {}).get('players') or []}
        for n, r in extras['players'].items():
            if roles.get(n) == role and r.get('active_ms') and duration:
                (mine if n == name else others.setdefault(n, [])).append((r['active_ms'], duration))
    if not mine:
        return None, None
    share = sum(a for a, _ in mine) / sum(d for _, d in mine)
    medians = sorted(sum(a for a, _ in v) / sum(d for _, d in v) for v in others.values())
    return share, (medians[len(medians) // 2] if medians else None)
