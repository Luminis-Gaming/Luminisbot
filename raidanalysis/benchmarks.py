"""
Top-player benchmarks (lorrgs.io-style): when the best parses of a spec press their major
cooldowns, potions and defensives on a boss - and how one of our players lines up with them.

Data: Warcraft Logs' global character rankings for (boss, difficulty, class, spec) - the top 5
parses - and each of those players' casts in that kill. Fetched for the specs we actually
play, a few per sync (they change slowly), cached in raid_benchmarks and refreshed weekly.

"Major" abilities aren't listed by hand, so every spec's own burst (Metamorphosis, Essence Break,
Ebon Might, Combustion, trinkets...) is found automatically: anything the top players cast at most
TOP_RARE_LIMIT times a kill that Wowhead says has a 30 s+ cooldown - minus movement, interrupts,
crowd control, taunts and dispels (NOT_MAJOR) - plus tracked cooldowns (cooldowns.py) and combat
potions.

Not every 30 s+ button is a cooldown you time, though: Immolation Aura or a Blood DK's Death and Decay
are pressed on cooldown (or on procs), so their timing says nothing. Each damage / healing ability is
sorted into a *major* cooldown (judged on timing against the top players) or a *rotational* one
(judged only on how often it's pressed, with the top players as the bar) - see ability_kind(). The
rule decides most of them; ROTATIONAL_NAMES and officers' per-spec overrides (raid_spec_abilities)
fix the rest.

Timing: phases start at different times for everyone (they're health-based), so casts are
compared as "time into phase segment n" (the n-th phase change). A *window* is a moment where
at least 3 of the top 5 pressed the same ability within 20 s of each other; a player hits it
when they pressed it within that moment's margin: about 4 s plus 1.5x how far the top players
themselves are apart, never more than half the ability's effect (pressing a 15 s buff 12 s early
wastes most of it) or a quarter of its cooldown, and always 3-20 s. Windows in phases a pull never
reached, or past the point it ended, don't count.
"""
import logging
import re
from collections import Counter

from . import analyzer, cooldowns

logger = logging.getLogger(__name__)

TOP_N = 5
REFRESH_DAYS = 7
SPECS_PER_RUN = 3
TOP_RARE_LIMIT = 60          # a top player's ability cast more often than this per kill is rotational filler
MAJOR_COOLDOWN_MS = 30000
WINDOW_MS = 20000            # top players' casts this close together are one moment
# Margin for "in line" with a moment (see tolerance()).
TOLERANCE_BASE_MS = 4000
SPREAD_FACTOR = 1.5
TOLERANCE_MIN_MS, TOLERANCE_MAX_MS = 3000, 20000
NEAR_MS = 60000              # a cast this close to a moment counts toward "usually N s early / late"
MIN_AGREE = 3
MIN_PULL_MS = 60000          # shorter pulls say nothing about cooldown usage
DIFFICULTIES = (3, 4, 5)

THROUGHPUT, POTION, TRINKET, ROTATIONAL = 'throughput', 'potion', 'trinket', 'rotational'
CATEGORY_LABELS = {THROUGHPUT: 'Damage / healing cooldowns', POTION: 'Combat potions', TRINKET: 'Trinkets & items',
                   ROTATIONAL: 'Keep on cooldown', **cooldowns.CATEGORY_LABELS}
CATEGORY_ORDER = (THROUGHPUT, POTION, 'personal', TRINKET, 'external', 'raid', 'utility', ROTATIONAL)
POTION_GROUP = 'Combat potion'  # any combat potion counts - which one is a stat choice
VERDICT_RANK = ['off', 'ok', 'mostly', 'good']  # worst first
# Verdicts only for what a player controls alone; externals and raid cooldowns depend on the raid's plan.
JUDGED = (THROUGHPUT, POTION, 'personal', TRINKET, ROTATIONAL)

# Major or rotational (ability_kind): a damage / healing ability is rotational when the top players
# cast it more often than its cooldown allows (procs and resets: Crimson Scourge, charges), or when
# fewer than half their casts fall on a moment most of them agree on (pressed whenever it's ready).
# A 90 s+ cooldown is always major - even pressed on cooldown, it lines up with the fight.
MAJOR, HIDE = 'major', 'hide'
SPEC_KINDS = (MAJOR, ROTATIONAL, HIDE)
ALWAYS_MAJOR_MS = 90000
OVER_COOLDOWN_USAGE = 1.15
MIN_AGREED_SHARE = 0.5
MIN_CASTS_TO_SORT = 6        # fewer top-player casts than this: too little to tell, stays major
# Rotational whatever the numbers say, for every spec (officers can still override per spec).
ROTATIONAL_NAMES = {'Immolation Aura', 'Consuming Fire', 'Death and Decay'}
# Rotational verdicts: your casts per minute as a share of the top players'.
ROTATIONAL_GOOD, ROTATIONAL_OK = 0.85, 0.65

# Long cooldowns that aren't throughput: movement, interrupts, crowd control, taunts, dispels.
NOT_MAJOR = {
    'Heroic Leap', 'Charge', 'Intervene', 'Disengage', 'Blink', 'Shimmer', 'Demonic Circle', 'Demonic Circle: Teleport',
    'Roll', 'Chi Torpedo', 'Transcendence', 'Transcendence: Transfer', 'Fel Rush', 'Vengeful Retreat',
    'Infernal Strike', "Death's Advance", 'Wraith Walk', 'Death Grip', 'Sprint', 'Dash', 'Tiger Dash', 'Wild Charge',
    'Divine Steed', 'Spirit Walk', 'Ghost Wolf', 'Hover', 'Glide', 'Aspect of the Cheetah', 'Angelic Feather',
    'Shadowstep', 'Grappling Hook', 'Burning Rush', 'Feral Lunge', 'Flying Serpent Kick', 'Rescue', 'Leap of Faith',
    'Kick', 'Pummel', 'Mind Freeze', 'Counterspell', 'Wind Shear', 'Rebuke', 'Skull Bash', 'Solar Beam', 'Disrupt',
    'Spear Hand Strike', 'Quell', 'Counter Shot', 'Muzzle', 'Silence', 'Spell Lock', 'Axe Toss', 'Optical Blast',
    'Hammer of Justice', 'Leg Sweep', 'Psychic Scream', 'Shockwave', 'Chaos Nova', 'Capacitor Totem',
    'Blinding Light', 'Intimidating Shout', 'Mass Entanglement', 'Binding Shot', 'Frost Nova', 'Ring of Frost',
    'Shadowfury', 'Mortal Coil', 'Tail Swipe', 'Wing Buffet', 'Imprison', 'Sigil of Misery', 'Sigil of Silence',
    'Sigil of Chains', 'Storm Bolt', 'Asphyxiate', 'Blind', 'Gouge', 'Cheap Shot', 'Kidney Shot', 'Incapacitating Roar',
    'Typhoon', 'Thunderstorm', 'Earthgrab Totem', 'Earthbind Totem', 'Ring of Peace', 'Paralysis', 'Repentance',
    'Intimidation', 'Freezing Trap', 'Tar Trap', 'Landslide', 'Sleep Walk', 'Oppressing Roar', 'Cyclone',
    'Hibernate', 'Polymorph', 'Fear', 'Howl of Terror', 'Banish', 'Hex', 'Mind Control', 'Dominate Mind',
    'Taunt', 'Growl', 'Provoke', 'Dark Command', 'Hand of Reckoning', 'Torment', 'Distracting Shot', 'Misdirection',
    'Tricks of the Trade', 'Mass Dispel', 'Purify', 'Cleanse', "Nature's Cure", 'Remove Corruption', 'Detox',
    'Purify Spirit', 'Cleanse Spirit', 'Naturalize', 'Expunge', 'Cauterizing Flame', 'Consume Magic', 'Purge',
    'Dispel Magic', 'Soothe', 'Tranquilizing Shot', 'Shadowmeld', 'Vanish', 'Feign Death', 'Fade', 'Invisibility',
    'Soulstone', 'Rebirth', 'Raise Ally', 'Intercession', 'Demonic Gateway', 'Fel Domination', 'Summon Felhunter',
    'Raise Dead', 'Call Pet 1', 'Revive Pet', 'Mend Pet', 'Mark of the Wild', 'Battle Shout', 'Arcane Intellect',
    'Power Word: Fortitude', 'Blessing of the Bronze', 'Skyfury',
    # short rotational absorbs / toggles the top players press often, not burst
    'Prismatic Barrier', 'Blazing Barrier', 'Ice Barrier', 'Sweeping Strikes',
}

_COOLDOWN_RE = re.compile(r'([\d.]+)\s*(min|sec)\s+cooldown', re.I)
_DURATION_RE = re.compile(r'\bfor ([\d.]+) (sec|min)', re.I)


def metric_for(role):
    return 'hps' if role == 'healer' else 'dps'


def cooldown_ms(meta):
    """'Instant · 2 min cooldown' -> 120000 (None without a cooldown)."""
    match = _COOLDOWN_RE.search(meta or '')
    if not match:
        return None
    return float(match.group(1)) * (60000 if match.group(2).lower() == 'min' else 1000)


def duration_ms(description):
    """How long an effect lasts, from Wowhead's text: '... Haste for 15 sec' -> 15000 (None if unknown)."""
    match = _DURATION_RE.search(description or '')
    if not match:
        return None
    try:
        return float(match.group(1)) * (60000 if match.group(2).lower() == 'min' else 1000)
    except ValueError:
        return None


def tolerance(spread, duration=None, cooldown=None):
    """
    How far from a moment a cast may be and still count as in line: tight when the top players agree
    (spread = how far apart they are), never more than half the effect's duration or a quarter of the
    cooldown, always between TOLERANCE_MIN_MS and TOLERANCE_MAX_MS.
    """
    tol = TOLERANCE_BASE_MS + SPREAD_FACTOR * (spread or 0)
    if duration:
        tol = min(tol, duration / 2)
    if cooldown:
        tol = min(tol, cooldown / 4)
    return max(TOLERANCE_MIN_MS, min(TOLERANCE_MAX_MS, tol))


def category(spell_id, info):
    """Which kind of major ability a spell is, or None for everything else (rotation, healthstones...)."""
    name = (info or {}).get('name') or ''
    lower = name.lower()
    if 'healthstone' in lower or ('potion' in lower and ('health' in lower or 'healing' in lower)):
        return None  # reactive heals: no "right" moment to compare
    drink = ((info or {}).get('description') or '').lower().startswith('drink')  # potions with fancy names
    if spell_id in analyzer.COMBAT_POTION_IDS or 'potion' in lower or drink:
        return POTION
    if name in cooldowns.COOLDOWNS:
        return cooldowns.COOLDOWNS[name]
    if name in NOT_MAJOR:
        return None
    meta = (info or {}).get('meta') or ''
    cd = cooldown_ms(meta)
    if not cd or cd < MAJOR_COOLDOWN_MS:
        return None
    # On-use items: whether you have that trinket is a gear question, so they're info unless you use one.
    return TRINKET if meta.startswith('Item effect') else THROUGHPUT


# ============================================================================
# Fetching (sync)
# ============================================================================

def _ranking_fields(r):
    """v2 ranking JSON (report/server/guild objects) or v1-style flat fields -> one shape."""
    report, server, guild = r.get('report') or {}, r.get('server') or {}, r.get('guild') or {}
    return {'name': r.get('name'), 'amount': r.get('amount') or r.get('total') or 0,
            'code': report.get('code') or r.get('reportID'), 'fight_id': report.get('fightID') or r.get('fightID'),
            'server': server.get('name') or r.get('serverName') or '',
            'region': server.get('region') or r.get('regionName') or '',
            'guild': guild.get('name') or r.get('guildName') or '', 'hidden': r.get('hidden')}


async def fetch_top_players(session, encounter_id, difficulty, class_name, spec, role):
    """The top TOP_N parses for a spec with their rare casts: [{'rank', 'name', ..., 'phases', 'casts'}]."""
    from . import wcl
    rankings = await wcl.get_character_rankings(session, encounter_id, difficulty, class_name, spec,
                                                metric_for(role))
    players, wrong_spec = [], 0
    for ranking in rankings:
        if len(players) >= TOP_N:
            break
        r = _ranking_fields(ranking)
        if r['hidden'] or not r['code'] or not r['fight_id'] or not r['name']:
            continue
        # Only ever compare a spec with itself: WCL has answered a filter for a brand-new spec
        # (Devourer) with the whole class's rankings. Ranking entries name their spec (v2).
        if isinstance(ranking.get('spec'), str) and _slug(ranking['spec']) != _slug(spec):
            wrong_spec += 1
            continue
        try:
            fight = await wcl.get_player_fight(session, r['code'], r['fight_id'], r['name'])
        except wcl.WCLRateLimited:
            raise
        except wcl.WCLError as e:
            logger.info(f"[RAIDS] Skipping top parse {r['code']}#{r['fight_id']}: {e}")
            continue
        if fight.get('spec') and _slug(fight['spec']) != _slug(spec):  # second check: the fight itself
            wrong_spec += 1
            continue
        events = [e for e in fight['casts'] if e.get('type') == 'cast' and analyzer._event_ability(e)]
        counts = Counter(analyzer._event_ability(e) for e in events)
        casts = [[e['timestamp'] - fight['start'], analyzer._event_ability(e)] for e in events
                 if counts[analyzer._event_ability(e)] <= TOP_RARE_LIMIT]
        if not casts:
            continue
        duration = fight['end'] - fight['start']
        auras, cast_names, resources, procs, on_others, targets = await _top_auras(session, r, fight, duration, role,
                                                                                   spec)
        players.append({'rank': len(players) + 1, 'name': r['name'], 'spec': spec, 'amount': round(r['amount']),
                        'server': r['server'], 'region': r['region'], 'guild': r['guild'],
                        'code': r['code'], 'fight_id': r['fight_id'], 'duration': duration,
                        'phases': fight['phases'], 'casts': casts, 'auras': auras, 'cast_names': cast_names,
                        'resources': resources, 'procs': procs, 'on_others': on_others, 'targets': targets})
    if wrong_spec:
        logger.warning(f"[RAIDS] Top {spec} {class_name} on {encounter_id}/{difficulty}: skipped {wrong_spec} "
                       f"parse(s) of another spec")
    return players


async def _top_auras(session, ranking, fight, duration, role=None, spec=None):
    """
    A top player's self-buffs, debuffs on the bosses, casts per ability, resources and wasted procs
    and for healers / Augmentation the buffs they keep on others (throughput.py): (auras, cast names,
    resources, procs, on_others, damage by target) - empty ones when WCL won't say.
    """
    from . import gamedata, throughput, wcl
    aid = fight.get('actor_id')
    if not aid:
        return [], {}, None, None, None, None
    code, fight_id, name = ranking['code'], ranking['fight_id'], ranking['name'].replace('"', '')
    try:
        others = [aid] if throughput.wants_on_others({'role': role, 'spec': spec}) else []
        tables = (await wcl.get_player_tables(session, code, fight_id, [aid], fight.get('boss_ids') or [],
                                              casts=True, others=others, targets=True)).get(int(aid)) or {}
        auras, cast_names, on_others = throughput.top_auras(tables, fight['start'], duration)
        events = await wcl.get_events(session, code, fight_id, 'Resources',
                                      f'type = "resourcechange" and target.name = "{name}"')
        resources = throughput.resources(events, {int(aid): ranking['name']}, fight['end']).get(ranking['name'])
        tracked = gamedata.tracked_ids()
        procs = throughput.proc_candidates({aid: tables}, tracked)
        proc_events = await wcl.get_events(
            session, code, fight_id, 'Buffs',
            f"source.id = target.id and ability.id in ({','.join(map(str, procs))})") if procs else []
        return (auras, cast_names, resources or {'gains': {}, 'mana_end': None},
                throughput.proc_waste(proc_events, {int(aid): ranking['name']}).get(ranking['name']) or {}, on_others,
                {t[0]: t[1] for t in throughput.targets({'targets': (tables.get('targets') or {}).get('entries')})})
    except wcl.WCLRateLimited:
        raise
    except wcl.WCLError as e:
        logger.info(f"[RAIDS] No auras for top parse {code}#{fight_id}: {e}")
        return [], {}, None, None, None, None


def _slug(name):
    return (name or '').replace(' ', '').lower()


async def refresh(session, budget_ok, limit=SPECS_PER_RUN):
    """Fetch benchmarks for the specs we played lately that have none (or a stale one). Returns how many."""
    from . import db
    done = 0
    for combo in db.benchmarks_needed(limit, REFRESH_DAYS, DIFFICULTIES):
        if not await budget_ok(session):
            break
        key = (combo['encounter_id'], combo['difficulty'], combo['class'], combo['spec'])
        try:
            players = await fetch_top_players(session, *key, combo['role'])
            db.save_benchmark(*key, metric_for(combo['role']), players, 'ok' if players else 'empty')
            # Which of their spells are major cooldowns comes from Wowhead's text: look it up now, not
            # whenever the general backlog gets there (a spell without it silently drops out).
            await ensure_spells({sid for p in players for _, sid in p['casts']})
        except Exception as e:  # retried after a day
            from .wcl import WCLRateLimited
            if isinstance(e, WCLRateLimited):
                raise  # not this spec's fault: stop, and let the sync pause
            logger.warning(f"[RAIDS] Top players for {key} failed: {e}")
            db.save_benchmark(*key, metric_for(combo['role']), [], 'error', str(e)[:300])
        done += 1
    return done


# ============================================================================
# Comparing (pure)
# ============================================================================

def segment_of(t, phases):
    """((segment index, phase id), ms into that segment) for a cast at t ms into the fight."""
    phases = phases or []
    k = 0
    for i, phase in enumerate(phases):
        if phase['start'] <= t:
            k = i
        else:
            break
    if not phases:
        return (0, 0), t
    return (k, phases[k]['id']), t - phases[k]['start']


def segment_lengths(phases, duration):
    """{(segment index, phase id): how long the pull spent in it}."""
    if not phases:
        return {(0, 0): duration}
    return {(i, p['id']): (phases[i + 1]['start'] if i + 1 < len(phases) else duration) - p['start']
            for i, p in enumerate(phases)}


def reference_starts(top):
    """When each phase segment starts on a shared timeline: the median over the top players."""
    starts = {}
    for player in top:
        for i, phase in enumerate(player.get('phases') or []):
            starts.setdefault((i, phase['id']), []).append(phase['start'])
    return {key: sorted(v)[len(v) // 2] for key, v in starts.items()} or {(0, 0): 0}


def align(t, phases, ref):
    """A cast's time on the shared (reference) timeline - real time when its phase isn't known there."""
    key, into = segment_of(t, phases)
    return ref[key] + into if key in ref else t


def windows(top, spell_ids):
    """
    Moments where >= MIN_AGREE top players cast one of spell_ids:
    [{'segment', 'at' (median), 'players', 'spread' (median distance from 'at')}].
    """
    need = min(MIN_AGREE, len(top))
    points = {}
    for i, player in enumerate(top):
        for t, sid in player['casts']:
            if sid in spell_ids:
                key, into = segment_of(t, player.get('phases'))
                points.setdefault(key, []).append((into, i))
    out = []
    for key, pts in points.items():
        pts.sort()
        cluster = []
        for into, who in pts + [(float('inf'), None)]:
            if cluster and into - cluster[0][0] > WINDOW_MS:
                players = {w for _, w in cluster}
                if len(players) >= need:
                    times = [c for c, _ in cluster]
                    at = times[len(times) // 2]
                    gaps = sorted(abs(c - at) for c in times)
                    out.append({'segment': key, 'at': at, 'players': len(players), 'spread': gaps[len(gaps) // 2]})
                cluster = []
            if who is not None:
                cluster.append((into, who))
    return sorted(out, key=lambda w: (w['segment'][0], w['at']))


def top_groups(top, spell_info):
    """
    The top players' major-ability casts, grouped by name - the same ability can have several spell
    IDs (e.g. Alter Time cast / return): {name: {'ids', 'users', 'category', 'counts': {player: casts}}}.
    """
    groups = {}
    for i, player in enumerate(top):
        for _, sid in player['casts']:
            info = spell_info.get(sid) or {}
            cat = category(sid, info)
            if not cat:
                continue
            key = POTION_GROUP if cat == POTION else info.get('name') or str(sid)
            g = groups.setdefault(key, {'ids': set(), 'users': set(), 'category': cat, 'counts': Counter()})
            if cat == TRINKET:  # any of its spell ids is an item: the whole ability is (not a class cooldown)
                g['category'] = TRINKET
            g['ids'].add(sid)
            g['users'].add(i)
            g['counts'][i] += 1
    return groups


def agreed_share(top, ids, wins):
    """Share of the top players' casts of `ids` that fall on one of the moments (windows) most of them agree on."""
    moments = {}
    for w in wins:
        moments.setdefault(w['segment'], []).append(w['at'])
    total = agreed = 0
    for player in top:
        for t, sid in player['casts']:
            if sid not in ids:
                continue
            key, into = segment_of(t, player.get('phases'))
            total += 1
            agreed += any(abs(into - at) <= WINDOW_MS / 2 for at in moments.get(key, ()))
    return agreed / total if total else 0.0


def ability_kind(name, group, top, wins, cooldown, override=None):
    """
    MAJOR (judged on timing) or ROTATIONAL (judged on how often) - or HIDE when an officer said so.
    Only damage / healing cooldowns are sorted by the rule; potions, trinkets and defensives stay major.
    """
    if override in SPEC_KINDS:
        return override
    if group['category'] != THROUGHPUT:
        return MAJOR
    if name in ROTATIONAL_NAMES:
        return ROTATIONAL
    if not cooldown or cooldown >= ALWAYS_MAJOR_MS:
        return MAJOR
    users = [i for i in group['users'] if top[i].get('duration')]
    if sum(group['counts'][i] for i in users) < MIN_CASTS_TO_SORT:
        return MAJOR
    # How many casts the cooldown allows in each top player's fight (+1: it starts ready).
    usage = sorted(group['counts'][i] / (top[i]['duration'] / cooldown + 1) for i in users)
    if usage[len(usage) // 2] > OVER_COOLDOWN_USAGE:
        return ROTATIONAL  # more casts than the cooldown allows: procs / resets
    if agreed_share(top, group['ids'], wins) < MIN_AGREED_SHARE:
        return ROTATIONAL  # no moment they agree on: pressed whenever it's ready
    return MAJOR


def _texts(ids, spell_info):
    """(effect duration, cooldown) of an ability from Wowhead's text, None when unknown."""
    texts = [spell_info.get(sid) or {} for sid in sorted(ids)]
    effect = next((d for d in (duration_ms(t.get('description')) for t in texts) if d), None)
    cooldown = next((c for c in (cooldown_ms(t.get('meta')) for t in texts) if c), None)
    return effect, cooldown


def compare(pulls, top, spell_info, overrides=None):
    """
    How one player's pulls line up with the top players, per major ability.

    pulls: [{'number', 'duration', 'phases': [{'id', 'start'}], 'casts': [[t, id]], 'cast_ids': set or None}]
    top: benchmark players. spell_info: {id: {'name', 'meta', ...}} (Wowhead).
    overrides: {ability name: MAJOR / ROTATIONAL / HIDE} - officers' calls for this spec.
    -> [{'name', 'ids', 'icon_id', 'category', 'top_users', 'top_per_min', 'ours_per_min', 'ours_casts',
         'windows', 'hits', 'considered', 'verdict', 'known', 'kind', 'auto_kind'}], most important first.
       Rotational abilities have category ROTATIONAL, no windows, and a verdict on how often alone.
    """
    pulls = [p for p in pulls if p['duration'] >= MIN_PULL_MS]
    if not top or not pulls:
        return []
    overrides = overrides or {}
    need = min(MIN_AGREE, len(top))
    ref = reference_starts(top)
    groups = top_groups(top, spell_info)
    rows = []
    minutes = sum(p['duration'] for p in pulls) / 60000
    # Every potion we drank counts for the potion group, not just the ones the top players picked -
    # and an ability our log records under another spell ID than theirs still counts (same name).
    for sid in {sid for p in pulls for _, sid in p['casts']}:
        info = spell_info.get(sid) or {}
        if category(sid, info) == POTION and POTION_GROUP in groups:
            groups[POTION_GROUP]['ids'].add(sid)
        elif info.get('name') in groups:
            groups[info['name']]['ids'].add(sid)
    for name, g in groups.items():
        if len(g['users']) < need:
            continue
        ids = g['ids']
        top_per_min = sum(g['counts'][i] / (top[i]['duration'] / 60000) for i in g['users']) / len(g['users'])
        # Pulls where we fetched these spells at all. Analyses from before the comparison only kept
        # the tracked cooldowns (cooldowns.py) and consumables - for anything else they can't tell
        # "never pressed" from "not recorded", so those pulls don't count until re-analyzed.
        tracked = g['category'] in cooldowns.CATEGORY_LABELS or g['category'] == POTION

        def is_known(p):
            if p.get('cast_ids') is None:
                return tracked and p.get('tracked')
            if ids & p['cast_ids']:
                return True
            # Nobody in the raid cast it at all that pull: a real zero (e.g. not talented).
            return p.get('casts_seen') is not None and not ids & p['casts_seen']
        known = [p for p in pulls if is_known(p)]
        ours = [[t for t, sid in p['casts'] if sid in ids] for p in pulls]
        ours_casts = sum(len(c) for c in ours)
        # The effect's duration and the cooldown, from Wowhead, cap each moment's margin.
        effect, cooldown = _texts(ids, spell_info)
        wins = windows(top, ids)
        auto_kind = ability_kind(name, g, top, wins, cooldown)
        kind = ability_kind(name, g, top, wins, cooldown, overrides.get(name))
        if kind == HIDE:
            continue
        cat = ROTATIONAL if kind == ROTATIONAL else g['category']
        if kind == ROTATIONAL:
            wins = []  # pressed whenever it's ready: there are no moments to line up with
        for w in wins:
            w['tolerance'] = tolerance(w['spread'], effect, cooldown)
            w.update(considered=0, hits=0, deltas=[], skipped=0)
        hits = considered = 0
        offsets = []  # ms early (-) / late (+) of our nearest cast to each moment, when it's near at all
        for pull, casts in zip(pulls, ours):
            if pull not in known:
                continue
            lengths = segment_lengths(pull['phases'], pull['duration'])
            mine = [segment_of(t, pull['phases']) for t in casts]
            for w in wins:
                if w['segment'] not in lengths or w['at'] > lengths[w['segment']]:
                    continue
                considered += 1
                w['considered'] += 1
                deltas = [into - w['at'] for key, into in mine if key == w['segment']]
                nearest = min(deltas, key=abs) if deltas else None
                if nearest is not None and abs(nearest) <= w['tolerance']:
                    hits += 1
                    w['hits'] += 1
                if nearest is not None and abs(nearest) <= NEAR_MS:
                    offsets.append(nearest)
                    w['deltas'].append(nearest)
                else:
                    w['skipped'] += 1
        ours_per_min = ours_casts / minutes if minutes else 0
        # Judged on timing (the moments the top players agree on) whenever there are moments to judge,
        # and on how often it's pressed - the verdict is the worse of the two: pressing it at the right
        # moments but half as often isn't "in line", and neither is pressing it often but off-beat.
        verdict = None
        timing = considered >= 2
        if not known:
            verdict = None
        elif not ours_casts:
            # A trinket you never used all night is one you don't have on - not a missed cast.
            verdict = 'not_equipped' if cat == TRINKET else 'missing'
        elif cat == ROTATIONAL:
            ratio = ours_per_min / top_per_min if top_per_min else 1
            verdict = 'good' if ratio >= ROTATIONAL_GOOD else 'ok' if ratio >= ROTATIONAL_OK else 'off'
        else:
            verdicts = []
            if timing:
                rate = hits / considered
                verdicts.append('good' if rate >= GOOD_RATE else 'mostly' if rate >= MOSTLY_RATE
                                else 'ok' if rate >= OFF_RATE else 'off')
            if top_per_min:
                ratio = ours_per_min / top_per_min
                verdicts.append('good' if ratio >= 0.75 else 'off' if ratio < 0.5 else 'ok')
            verdict = min(verdicts, key=VERDICT_RANK.index) if verdicts else None
        offset = sorted(offsets)[len(offsets) // 2] if offsets else None  # shown from one moment on
        weak = weak_moments(wins, ref) if considered and ours_casts else []  # nothing to work on if never used
        rows.append({'name': name, 'ids': sorted(ids), 'icon_id': min(ids), 'category': cat,
                     'top_users': len(g['users']), 'top_per_min': top_per_min, 'ours_per_min': ours_per_min,
                     'ours_casts': ours_casts, 'windows': [dict(w, ref_at=ref.get(w['segment'], 0) + w['at'])
                                                           for w in wins],
                     'hits': hits, 'considered': considered, 'verdict': verdict, 'known': bool(known),
                     'offset': offset, 'effect_ms': effect, 'weak': weak, 'cooldown_ms': cooldown,
                     'kind': kind, 'auto_kind': auto_kind, 'overridden': name in overrides})
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(rows, key=lambda r: (order.get(r['category'], 9), -r['top_users'], r['name']))


# Share of moments lined up for each verdict. "In line" is kept for nearly all of them: a green
# label reads as "nothing to improve", so a few missed big moments make it "Mostly in line".
GOOD_RATE, MOSTLY_RATE, OFF_RATE = 0.9, 0.75, 0.4
WEAK_RATE = 0.5          # a moment you line up with less often than this is one to work on


def weak_moments(wins, ref):
    """
    The moments a player usually misses, most important first (more top players there, then earlier):
    [{'ref_at', 'players', 'hits', 'considered', 'how'}] - how: 'usually 9 s early' / 'often not pressed'.
    """
    out = []
    for w in wins:
        if not w.get('considered') or w['hits'] / w['considered'] >= WEAK_RATE:
            continue
        deltas = sorted(w['deltas'])
        if w['skipped'] > len(deltas):
            how = 'often not pressed'
        else:
            how = f'usually {timing_text(deltas[len(deltas) // 2])}'
        out.append({'ref_at': ref.get(w['segment'], 0) + w['at'], 'players': w['players'],
                    'hits': w['hits'], 'considered': w['considered'], 'how': how})
    return sorted(out, key=lambda m: (-m['players'], m['ref_at']))


def weak_text(weak, limit=3):
    """'2:16 usually 9 s early, 6:46 often not pressed'."""
    return ', '.join(f"{_clock(m['ref_at'])} {m['how']}" for m in weak[:limit])


def timing_text(offset):
    """-12000 -> '12 s early', 800 -> 'on time', None -> ''."""
    if offset is None:
        return ''
    if abs(offset) < 2000:
        return 'on time'
    return f"{abs(offset) / 1000:.0f} s {'early' if offset < 0 else 'late'}"


def _clock(ms):
    s = int(round(ms / 1000))
    return f'{s // 60}:{s % 60:02d}'


def _moments(windows, count=2):
    """'0:28 and 1:30' - when the top players press it (the first few moments)."""
    times = [_clock(w['ref_at']) for w in windows[:count]]
    return ' and '.join(times) if len(times) <= 2 else ', '.join(times[:-1]) + ' and ' + times[-1]


def notes(rows, spec_label, limit=3):
    """
    Feedback lines from compare() - the recap's, so short: the takeaway first (how often you were in line,
    as a share), then at most the one moment that matters most. [{'tone': 'good'|'bad'|'info', 'text'}] -
    misses first, a couple of wins. A trinket you don't have is loot luck, not a mistake: it's a tip about
    what's worth getting.
    """
    bad, good, info = [], [], []
    for r in rows:
        if r['category'] not in JUDGED or not r['verdict']:
            continue
        share = f"{100 * r['hits'] / r['considered']:.0f}%" if r.get('considered') else None
        if r['verdict'] == 'not_equipped':
            info.append(trinket_tip(r, spec_label))
        elif r['category'] == ROTATIONAL:
            if r['verdict'] == 'missing':
                bad.append(f"{r['name']}: never pressed - {r['top_users']} of the top {spec_label} keep it rolling "
                           f"(talented?)")
            elif r['verdict'] in ('off', 'ok'):
                bad.append(f"{r['name']}: {r['ours_per_min']:.1f} a minute - the top {spec_label} "
                           f"{r['top_per_min']:.1f}. Press it whenever it's ready")
            continue
        elif r['verdict'] == 'missing':
            bad.append(f"{r['name']}: never pressed - {r['top_users']} of the top {spec_label} use it (talented?)")
        elif r['verdict'] in ('mostly', 'ok', 'off') and r.get('weak'):
            worst = r['weak'][0]
            if r['verdict'] == 'mostly':
                bad.append(f"{r['name']}: mostly in line ({share}) - except {_clock(worst['ref_at'])}, {worst['how']}")
            else:
                bad.append(f"{r['name']}: in line only {share} of the time - worst at {_clock(worst['ref_at'])}, "
                           f"{worst['how']}")
        elif r['verdict'] in ('off', 'ok') and r['considered'] >= 2 and timing_text(r['offset']) not in ('', 'on time'):
            bad.append(f"{r['name']}: you press it about {timing_text(r['offset'])} - the top {spec_label} around "
                       f"{_moments(r['windows'])}")
        elif r['verdict'] == 'off' and r['considered'] >= 2:
            bad.append(f"{r['name']}: in line only {share} of the time - the top {spec_label} press it around "
                       f"{_moments(r['windows'])}")
        elif r['verdict'] == 'off':
            bad.append(f"{r['name']}: {r['ours_per_min'] * 5:.1f}× per 5 min - the top {spec_label} "
                       f"{r['top_per_min'] * 5:.1f}×")
        elif r['verdict'] == 'good':
            good.append(f"{r['name']}: lined up with the top {spec_label}"
                        + (f" ({share} of the time)" if r['considered'] >= 2 else ''))
    return ([{'tone': 'bad', 'text': t} for t in bad[:limit]]
            + [{'tone': 'good', 'text': t} for t in good[:max(1, limit - len(bad))]]
            + [{'tone': 'info', 'text': t} for t in info[:1]])


def trinket_tip(row, spec_label):
    """'Soulcoiler Ritual Vessel: 4 of the top 5 Havoc Demon Hunters use this trinket - worth getting if it drops'."""
    return (f"{row['name']}: {row['top_users']} of the top {spec_label} use this trinket - "
            f"worth getting if it drops")


def our_pulls(pulls, name, spec=None):
    """
    Our raid pulls -> compare() input for one character: pulls they weren't in are skipped, and so
    are pulls on another spec than `spec` (a Havoc pull doesn't count against the Devourer top).
    """
    out = []
    for number, pull in pulls:
        analysis = pull.get('analysis') or {}
        me = next((p for p in analysis.get('players') or [] if p['name'] == name), None)
        if not me or (spec and me.get('spec') and me['spec'] != spec):
            continue
        casts = (analysis.get('casts') or {}).get(name)
        if casts is None:  # analyzed before every rare cast was kept: tracked cooldowns + consumables only
            casts = [[c['t'], c['ability_id']] for c in analysis.get('cooldowns') or [] if c['name'] == name]
            casts += [[u['t'], u['ability_id']] for u in analysis.get('consumables') or [] if u['name'] == name]
        cast_ids, seen = analysis.get('cast_ids'), analysis.get('casts_seen')
        out.append({'number': number, 'fight_id': pull['fight_id'], 'kill': pull.get('kill'),
                    'duration': pull['end_ms'] - pull['start_ms'], 'phases': pull.get('phases') or [],
                    'casts': sorted(casts), 'cast_ids': set(cast_ids) if cast_ids is not None else None,
                    'casts_seen': set(seen) if seen is not None else None,
                    'tracked': 'cooldowns' in analysis})
    return out


# ============================================================================
# Glue for the pages and the Discord recap (DB)
# ============================================================================

async def ensure_spells(spell_ids):
    """Look up (on Wowhead) whichever of these spells we've never looked up. Returns how many."""
    from . import db, spells
    ids = {int(i) for i in spell_ids if i}
    missing = sorted(ids - db.attempted_spell_ids(ids)) if ids else []
    return await spells.fetch_ids(missing) if missing else 0


def _main_spec_player(numbered, name):
    """The character's player entry for the spec they played on most of these pulls (None if unknown)."""
    from .analyzer import main_spec
    entries = [p for _, pull in numbered for p in (pull.get('analysis') or {}).get('players') or []
               if p['name'] == name and p.get('spec')]
    spec = main_spec(entries)
    return next((p for p in reversed(entries) if p['spec'] == spec), None)


async def ensure_spells_for(numbered, name):
    """Before comparing one character: make sure their spec's top-player spells have Wowhead text."""
    from . import db
    player = _main_spec_player(numbered, name)
    if not player or not numbered:
        return 0
    first = numbered[0][1]
    bench = db.get_benchmark(first['encounter_id'], first['difficulty'], player['class'], player['spec'])
    ours = {sid for p in our_pulls(numbered, name, spec=player['spec']) for _, sid in p['casts']}
    # Wasted procs: the buffs' events only carry ids, so their names and icons come from Wowhead too
    from .throughput import detail_pulls
    procs = {v[2] for _, _, me, _ in detail_pulls(numbered, name) for v in (me.get('procs') or {}).values()}
    procs |= {v[2] for p in (bench or {}).get('players') or [] for v in (p.get('procs') or {}).values()}
    return await ensure_spells({sid for p in (bench or {}).get('players') or [] for _, sid in p['casts']}
                               | ours | procs)


# Without top-player data for a spec, the raid timeline only treats long cooldowns as major.
FALLBACK_MAJOR_MS = 60000


def spec_majors(encounter_id, difficulty, spell_lookup):
    """
    {(class, spec): {ability names}} - the damage / healing cooldowns and trinkets each spec's top
    players use as majors on this boss (same rule as compare(): at least MIN_AGREE of them), so the
    raid timeline shows what matters for that spec instead of every 30 s button.
    """
    from . import db
    rows = db.get_benchmarks(encounter_id, difficulty)
    ids = {sid for r in rows for p in r['players'] or [] for _, sid in p['casts']}
    info = spell_lookup(list(ids)) if spell_lookup and ids else {}
    all_overrides = db.get_spec_overrides()
    out = {}
    for r in rows:
        top = r['players'] or []
        need = min(MIN_AGREE, len(top))
        overrides = all_overrides.get((r['class'], r['spec']), {})
        majors = set()
        for name, g in top_groups(top, info).items():
            if g['category'] not in (THROUGHPUT, TRINKET) or len(g['users']) < need:
                continue
            kind = ability_kind(name, g, top, windows(top, g['ids']), _texts(g['ids'], info)[1], overrides.get(name))
            if kind == MAJOR:
                majors.add(name)
        out[(r['class'], r['spec'])] = majors
    return out


def is_major_for(player, spell_id, info, majors):
    """Raid timeline: is this cast one of the player's spec's major damage / healing cooldowns?"""
    if category(spell_id, info) not in (THROUGHPUT, TRINKET):
        return False
    key = (player.get('class'), player.get('spec'))
    if key in majors:
        return (info or {}).get('name') in majors[key]
    return (cooldown_ms((info or {}).get('meta')) or 0) >= FALLBACK_MAJOR_MS


def readable(slug):
    """'DeathKnight' -> 'Death Knight', 'BeastMastery' -> 'Beast Mastery'."""
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', slug or '')


def spec_label(player):
    """'Fire Mages', 'Havoc Demon Hunters'."""
    return f"{readable(player.get('spec'))} {readable(player.get('class'))}s".strip()


def major_casts(analysis, name):
    """
    A player's major cooldowns in one pull - damage / healing, on-use items, personal defensives:
    [(ms into the pull, spell id, name, icon url)] (the focus timeline's lanes, the recap's coaching).
    """
    from . import db, spells
    casts = (analysis.get('casts') or {}).get(name) or []
    info = db.get_spells({sid for _, sid in casts}) if casts else {}
    return [(t, sid, info[sid].get('name') or '', spells.icon_url(info[sid].get('icon'))) for t, sid in casts
            if category(sid, info.get(sid)) in (THROUGHPUT, TRINKET, 'personal')]


def for_player(numbered, name):
    """
    Everything the comparison views need for one character on one boss+difficulty:
    {'player', 'benchmark', 'top', 'pulls', 'rows', 'spells', 'label'} - or None when there's
    nothing to compare (no spec known). numbered: [(pull number, pull with analysis)].
    """
    from . import db
    player = _main_spec_player(numbered, name)
    if not player or not numbered:
        return None
    first = numbered[0][1]
    benchmark = db.get_benchmark(first['encounter_id'], first['difficulty'], player['class'], player['spec'])
    top = (benchmark or {}).get('players') or []
    pulls = our_pulls(numbered, name, spec=player['spec'])
    ids = {sid for p in top for _, sid in p['casts']} | {sid for p in pulls for _, sid in p['casts']}
    spells = db.get_spells(ids) if ids else {}
    overrides = db.get_spec_overrides().get((player['class'], player['spec']), {})
    return {'player': player, 'benchmark': benchmark, 'top': top, 'pulls': pulls,
            'rows': compare(pulls, top, spells, overrides), 'spells': spells, 'label': spec_label(player)}
