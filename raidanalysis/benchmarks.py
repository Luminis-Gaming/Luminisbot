"""
Top-player benchmarks (lorrgs.io-style): when the best parses of a spec press their major
cooldowns, potions and defensives on a boss - and how one of our players lines up with them.

Data: Warcraft Logs' global character rankings for (boss, difficulty, class, spec) - the top 5
parses on the hero tree our player plays (an Annihilator Devourer isn't judged on Void-Scarred buttons) -
and each of those players' casts in that kill. Fetched for the specs and hero trees we actually play,
a few per sync (they change slowly), cached in raid_benchmarks and refreshed weekly.

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
MAX_FAILED_LOADS = 10        # top parses whose log won't load before giving up on a spec (empty, retried tomorrow)
# Pages of WCL's rankings (100 each) to look through for a hero tree: few of the top play the rarer one
# (5 Mountain Thane Fury Warriors in a top 100, the best at #47)
MAX_RANKING_PAGES = 3
DIFFICULTIES = (3, 4, 5)

THROUGHPUT, POTION, TRINKET, ROTATIONAL = 'throughput', 'potion', 'trinket', 'rotational'
CATEGORY_LABELS = {THROUGHPUT: 'Damage / healing cooldowns', POTION: 'Combat potions', TRINKET: 'Trinkets & items',
                   ROTATIONAL: 'Keep on cooldown', **cooldowns.CATEGORY_LABELS}
CATEGORY_ORDER = (THROUGHPUT, POTION, 'personal', TRINKET, 'external', 'raid', 'utility', ROTATIONAL)
POTION_GROUP = 'Combat potion'  # any combat potion counts - which one is a stat choice
VERDICT_RANK = ['off', 'ok', 'mostly', 'good']  # worst first
# Verdicts only for what a player controls alone; raid cooldowns depend on the raid's plan. Externals (Life
# Cocoon, Ironbark, Power Infusion) are judged on how often they're used - when depends on who needs one (RATE_ONLY).
JUDGED = (THROUGHPUT, POTION, 'personal', TRINKET, ROTATIONAL, 'external')
RATE_ONLY = ('external',)

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
# Rotational whatever the numbers say, for every spec (officers can still override per spec) - Mana Tea too, which
# has no cooldown to find it by (it's drunk on stacks) but is kept rolling all the same.
ROTATIONAL_NAMES = {'Immolation Aura', 'Consuming Fire', 'Death and Decay', 'Mana Tea'}
# Burst with no cooldown to find it by - a Devourer's Void Metamorphosis opens on Soul Fragments, not a timer -
# but timed all the same: major cooldowns whatever Wowhead says (the rule still sorts them, officers can override).
NO_COOLDOWN_MAJORS = {'Void Metamorphosis'}
# Rotational verdicts: your casts per minute as a share of the top players'.
ROTATIONAL_GOOD, ROTATIONAL_OK = 0.85, 0.65

# Long cooldowns that aren't throughput: movement, interrupts, crowd control, taunts, dispels.
NOT_MAJOR = {
    'Heroic Leap', 'Charge', 'Intervene', 'Disengage', 'Blink', 'Shimmer', 'Demonic Circle', 'Demonic Circle: Teleport',
    'Roll', 'Chi Torpedo', 'Transcendence', 'Transcendence: Transfer', 'Fel Rush', 'Vengeful Retreat',
    'Infernal Strike', "Death's Advance", 'Wraith Walk', 'Death Grip', 'Sprint', 'Dash', 'Tiger Dash', 'Wild Charge',
    'Divine Steed', 'Spirit Walk', 'Ghost Wolf', 'Hover', 'Glide', 'Aspect of the Cheetah', 'Angelic Feather',
    "Spiritwalker's Grace",
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
    if name in ROTATIONAL_NAMES:
        return THROUGHPUT  # whatever its cooldown (Mana Tea has none): ability_kind() makes it rotational
    if name in NO_COOLDOWN_MAJORS:
        return THROUGHPUT
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
            'guild': guild.get('name') or r.get('guildName') or '', 'hidden': r.get('hidden'),
            'talents': [t.get('talentID') for t in r.get('talents') or [] if isinstance(t, dict)]}


async def _rankings(session, encounter_id, difficulty, class_name, spec, role, hero, listed):
    """
    WCL's ranked parses of a spec, best first - one page, or with a hero tree up to MAX_RANKING_PAGES, each
    fetched only once the one before is used up. listed: a list the page sizes go into.
    """
    from . import wcl
    for page in range(1, (MAX_RANKING_PAGES if hero else 1) + 1):
        rankings = await wcl.get_character_rankings(session, encounter_id, difficulty, class_name, spec,
                                                    metric_for(role), page=page, talents=bool(hero))
        listed.append(len(rankings))
        for ranking in rankings:
            yield ranking
        if not rankings:
            return


async def fetch_top_players(session, encounter_id, difficulty, class_name, spec, role, hero=''):
    """
    The top TOP_N parses for a spec - on one hero tree, when hero is given - with their rare casts:
    ([{'rank', 'name', ..., 'hero', 'phases', 'casts'}], why) - why says what happened to WCL's parses when none
    made it ('WCL listed no parses', '40 failed to load: ...'), so an empty benchmark can tell "nobody's ranked"
    from "we dropped them all".
    """
    from . import gamedata, throughput, wcl
    catalog = gamedata._talent_catalog() if hero else None
    players, wrong_spec, listed = [], 0, []
    dropped, first_error = Counter(), None
    async for ranking in _rankings(session, encounter_id, difficulty, class_name, spec, role, hero, listed):
        if len(players) >= TOP_N:
            break
        r = _ranking_fields(ranking)
        if r['hidden'] or not r['code'] or not r['fight_id'] or not r['name']:
            dropped['hidden or without a log'] += 1
            continue
        # Only ever compare a spec with itself: WCL has answered a filter for a brand-new spec
        # (Devourer) with the whole class's rankings. Ranking entries name their spec (v2).
        if isinstance(ranking.get('spec'), str) and _slug(ranking['spec']) != _slug(spec):
            wrong_spec += 1
            continue
        # ...and a hero tree with itself (their talents say which; none listed: can't tell, so not them)
        if hero and gamedata.hero_tree(r['talents'], catalog) != hero:
            dropped['on another hero tree'] += 1
            continue
        try:
            fight = await wcl.get_player_fight(session, r['code'], r['fight_id'], r['name'])
        except wcl.WCLRateLimited:
            raise
        except wcl.WCLError as e:
            logger.info(f"[RAIDS] Skipping top parse {r['code']}#{r['fight_id']}: {e}")
            dropped['failed to load'] += 1
            first_error = first_error or str(e)
            if not players and dropped['failed to load'] >= MAX_FAILED_LOADS:
                break  # WCL won't hand these logs over: don't spend the hour's budget on the whole page
            continue
        if fight.get('spec') and _slug(fight['spec']) != _slug(spec):  # second check: the fight itself
            wrong_spec += 1
            continue
        events = [e for e in fight['casts'] if e.get('type') == 'cast' and analyzer._event_ability(e)]
        counts = Counter(analyzer._event_ability(e) for e in events)
        casts = [[e['timestamp'] - fight['start'], analyzer._event_ability(e)] for e in events
                 if counts[analyzer._event_ability(e)] <= TOP_RARE_LIMIT]
        if not casts:
            dropped['no casts'] += 1
            continue
        duration = fight['end'] - fight['start']
        auras, cast_names, resources, procs, on_others, targets = await _top_auras(session, r, fight, duration, role,
                                                                                   spec)
        players.append({'rank': len(players) + 1, 'name': r['name'], 'spec': spec, 'hero': hero or None,
                        'amount': round(r['amount']),
                        'server': r['server'], 'region': r['region'], 'guild': r['guild'],
                        'code': r['code'], 'fight_id': r['fight_id'], 'duration': duration,
                        'phases': fight['phases'], 'casts': casts, 'auras': auras, 'cast_names': cast_names,
                        'lust': cooldowns.lust_bands(fight.get('lust'), fight['start'], fight['end'], fight.get('actor_id')),
                        'resources': resources, 'procs': procs, 'on_others': on_others, 'hots_counted': throughput.HOTS_COUNTED,
                        'targets': targets})
    who = f"{hero + ' ' if hero else ''}{spec} {class_name}"
    if wrong_spec:
        logger.warning(f"[RAIDS] Top {who} on {encounter_id}/{difficulty}: skipped {wrong_spec} "
                       f"parse(s) of another spec")
        dropped['another spec'] += wrong_spec
    why = None
    if not players:
        why = (f"WCL listed {sum(listed)} parse(s): "
               + ', '.join(f'{n} {reason}' for reason, n in dropped.most_common())
               + (f' ({first_error})' if first_error else '')) if sum(listed) else 'WCL listed no parses'
        logger.warning(f"[RAIDS] No top {who} on {encounter_id}/{difficulty}: {why}")
    return players, why


async def _top_auras(session, ranking, fight, duration, role=None, spec=None):
    """
    A top player's self-buffs, debuffs on the bosses, casts per ability, resources and wasted procs
    and for healers / Augmentation the buffs they keep on others, counted from their buff events
    (throughput.hots_out): (auras, cast names, resources, procs, on_others, damage by target) - empty ones
    when WCL won't say.
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
        if on_others:  # the candidates: counted from their events, on players only (not pets)
            hot_events = await wcl.get_events(session, code, fight_id, 'Buffs',
                                              throughput.hots_filter([ranking['name']], {a['id'] for a in on_others}))
            player_ids = set((await wcl.get_actor_ids(session, code)).values())
            on_others = throughput.hots_out(hot_events, aid, on_others, player_ids, fight['start'], fight['end'])
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


async def refresh(session, budget_ok, limit=SPECS_PER_RUN, combos=None, progress=None):
    """
    Fetch benchmarks for the specs (and hero trees) we played lately that have none (or a stale one) - or for
    exactly `combos` (db.boss_benchmarks rows: one boss's re-fetch), fresh or not. progress(done) after each.
    Returns how many.
    """
    from . import db
    done = 0
    for combo in db.benchmarks_needed(limit, REFRESH_DAYS, DIFFICULTIES) if combos is None else combos:
        if not await budget_ok(session):
            break
        key = (combo['encounter_id'], combo['difficulty'], combo['class'], combo['spec'], combo.get('hero') or '')
        try:
            players, why = await fetch_top_players(session, *key[:4], combo['role'], key[4])
            db.save_benchmark(*key, metric_for(combo['role']), players, 'ok' if players else 'empty', why)
            # Which of their spells are major cooldowns comes from Wowhead's text: look it up now, not
            # whenever the general backlog gets there (a spell without it silently drops out).
            await ensure_spells({sid for p in players for _, sid in p['casts']})
        except Exception as e:  # retried after a few hours (db.benchmarks_needed)
            from .wcl import WCLRateLimited
            if isinstance(e, WCLRateLimited):
                raise  # not this spec's fault: stop, and let the sync pause
            logger.warning(f"[RAIDS] Top players for {key} failed: {e}")
            db.save_benchmark(*key, metric_for(combo['role']), [], 'error', str(e)[:300])
        done += 1
        if progress:
            progress(done)
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


def merge_choices(groups, choices):
    """
    top_groups() with the options of one talent choice (Revival / Restoral, Invoke Yu'lon / Invoke Chi-Ji -
    gamedata.choices()) as one group named after them all, most top players' pick first: whichever one a player
    took counts, theirs and ours. Every group gets 'members': the ability names in it.
    """
    out, done = {}, set()
    for name in sorted(groups, key=lambda n: (-len(groups[n]['users']), n)):
        if name in done:
            continue
        others = sorted(n for n in (choices or {}).get(name, ()) if n in groups and n != name and n not in done)
        members = [name] + others
        done.update(members)
        parts = [groups[n] for n in members]
        out[' / '.join(members)] = {'ids': set().union(*(g['ids'] for g in parts)),
                                    'users': set().union(*(g['users'] for g in parts)),
                                    'category': parts[0]['category'], 'members': members,
                                    'counts': sum((g['counts'] for g in parts), Counter())}
    return out


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


def compare(pulls, top, spell_info, overrides=None, talents=None, choices=None):
    """
    How one player's pulls line up with the top players, per major ability.

    pulls: [{'number', 'duration', 'phases': [{'id', 'start'}], 'casts': [[t, id]], 'cast_ids': set or None}]
    top: benchmark players. spell_info: {id: {'name', 'meta', ...}} (Wowhead).
    overrides: {ability name: MAJOR / ROTATIONAL / HIDE} - officers' calls for this spec.
    talents: gamedata.not_taken() - which abilities their talents didn't give them; None when unknown.
    choices: gamedata.choices() - the options of a talent choice are one row (Revival / Restoral).
    -> [{'name', 'ids', 'icon_id', 'category', 'top_users', 'top_per_min', 'ours_per_min', 'ours_casts',
         'windows', 'hits', 'considered', 'verdict', 'known', 'kind', 'auto_kind', 'few_top'}], most important first.
       Rotational abilities have category ROTATIONAL, no windows, and a verdict on how often alone.
       Never pressed: 'not_taken' (a talent you didn't take - not judged), 'not_equipped' (a trinket),
       'missing' (a combat potion, or an ability you had).
       few_top: one of your cooldowns too few of the top players press to compare with (fewer than MIN_AGREE) -
       shown so it isn't missing, not judged.
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
    # and an ability our log records under another spell ID than theirs still counts (same name). One
    # the top players never pressed is still one of ours: a row of its own.
    our_ids = {sid for p in pulls for _, sid in p['casts']}
    for sid in our_ids:
        info = spell_info.get(sid) or {}
        cat = category(sid, info)
        if cat == POTION and POTION_GROUP in groups:
            groups[POTION_GROUP]['ids'].add(sid)
        elif info.get('name') in groups:
            groups[info['name']]['ids'].add(sid)
        elif cat and cat != POTION and info.get('name'):
            groups[info['name']] = {'ids': {sid}, 'users': set(), 'category': cat, 'counts': Counter()}
    for name, g in merge_choices(groups, choices).items():
        ids = g['ids']
        few = len(g['users']) < need
        if few and not ids & our_ids:
            continue
        override = next((overrides[n] for n in [name] + g['members'] if n in overrides), None)
        top_per_min = (sum(g['counts'][i] / (top[i]['duration'] / 60000) for i in g['users']) / len(g['users'])
                       if g['users'] else 0)
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
        wins = [] if few else windows(top, ids)
        auto_kind = MAJOR if few else ability_kind(name, g, top, wins, cooldown)
        kind = (HIDE if override == HIDE else MAJOR) if few else ability_kind(name, g, top, wins, cooldown, override)
        if kind == HIDE:
            continue
        cat = ROTATIONAL if kind == ROTATIONAL else g['category']
        if kind == ROTATIONAL or cat in RATE_ONLY:
            wins = []  # pressed whenever it's ready (or needed): there are no moments to line up with
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
        if not known or few:
            verdict = None
        elif not ours_casts:
            # Never pressed all night: a trinket you don't have on, or a talent you didn't take (Rushing Wind
            # Kick in place of Rising Sun Kick) - neither is a missed cast. Your talents say which;
            # pulls from before talents were kept can't tell, so a class ability gets the benefit of the doubt.
            if cat == TRINKET:
                verdict = 'not_equipped'
            elif cat != POTION and (talents is None or all(n in talents.missing for n in g['members'])):
                verdict = 'not_taken'
            else:
                verdict = 'missing'
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
        pressed = Counter(sid for p in pulls for _, sid in p['casts'] if sid in ids)  # your pick's icon
        rows.append({'name': name, 'ids': sorted(ids), 'category': cat, 'few_top': few,
                     'icon_id': pressed.most_common(1)[0][0] if pressed else min(ids),
                     'top_users': len(g['users']), 'top_per_min': top_per_min, 'ours_per_min': ours_per_min,
                     'ours_casts': ours_casts, 'windows': [dict(w, ref_at=ref.get(w['segment'], 0) + w['at'])
                                                           for w in wins],
                     'hits': hits, 'considered': considered, 'verdict': verdict, 'known': bool(known),
                     'offset': offset, 'effect_ms': effect, 'weak': weak, 'cooldown_ms': cooldown,
                     'kind': kind, 'auto_kind': auto_kind, 'overridden': override is not None})
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
        if r['category'] not in JUDGED or not r['verdict'] or r['verdict'] == 'not_taken':
            continue  # never pressed a class ability: a talent you didn't take, nothing to say about it
        share = f"{100 * r['hits'] / r['considered']:.0f}%" if r.get('considered') else None
        if r['verdict'] == 'not_equipped':
            info.append(trinket_tip(r, spec_label))
        elif r['category'] == ROTATIONAL:
            if r['verdict'] == 'missing':
                bad.append(f"{r['name']}: never pressed - you had it, and {r['top_users']} of the top {spec_label} "
                           f"keep it rolling")
            elif r['verdict'] in ('off', 'ok'):
                bad.append(f"{r['name']}: {r['ours_per_min']:.1f} a minute - the top {spec_label} "
                           f"{r['top_per_min']:.1f}. Press it whenever it's ready")
            continue
        elif r['verdict'] == 'missing' and r['name'] == POTION_GROUP:
            bad.append(f"{r['name']}: never used - {r['top_users']} of the top {spec_label} use one")
        elif r['verdict'] == 'missing':  # talented (or baseline), and never pressed
            bad.append(f"{r['name']}: never pressed - you had it, and {r['top_users']} of the top {spec_label} "
                       f"use it")
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
        elif r['verdict'] == 'good' and r['category'] in RATE_ONLY:
            good.append(f"{r['name']}: used as often as the top {spec_label}")
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


def our_pulls(pulls, name, spec=None, hero=None, catalog=None):
    """
    Our raid pulls -> compare() input for one character: pulls they weren't in are skipped, and so
    are pulls on another spec than `spec` (a Havoc pull doesn't count against the Devourer top) or
    another hero tree than `hero` (pulls whose talents don't say still count).
    """
    from .gamedata import pull_hero
    out = []
    for number, pull in pulls:
        analysis = pull.get('analysis') or {}
        me = next((p for p in analysis.get('players') or [] if p['name'] == name), None)
        if not me or (spec and me.get('spec') and me['spec'] != spec):
            continue
        if hero and pull_hero(analysis, name, catalog) not in (None, hero):
            continue
        casts = (analysis.get('casts') or {}).get(name)
        if casts is None:  # analyzed before every rare cast was kept: tracked cooldowns + consumables only
            casts = [[c['t'], c['ability_id']] for c in analysis.get('cooldowns') or [] if c['name'] == name]
            casts += [[u['t'], u['ability_id']] for u in analysis.get('consumables') or [] if u['name'] == name]
        cast_ids, seen = analysis.get('cast_ids'), analysis.get('casts_seen')
        lust = [[u['t'], u['end'], u['ability_id'], u['ability'], u['name']]
                for u in cooldowns.lust_uses(analysis.get('cooldowns'), pull['end_ms'] - pull['start_ms'])]
        out.append({'number': number, 'fight_id': pull['fight_id'], 'kill': pull.get('kill'), 'lust': lust,
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


def _benchmark_for(numbered, name):
    """
    (player entry, hero tree, benchmark row, our pulls, hero status) for one character, or None when their spec
    isn't known. The benchmark is their hero tree's top players; when there are none (not fetched yet, WCL had no
    parses of it, or fetching failed - hero status: None / 'empty' / 'error'), the whole spec's (from before hero
    trees) if it has any - its 'hero' says which it is.
    """
    from . import db
    from .gamedata import main_hero
    player = _main_spec_player(numbered, name)
    if not player or not numbered:
        return None
    first = numbered[0][1]
    key = (first['encounter_id'], first['difficulty'], player['class'], player['spec'])
    hero = main_hero(numbered, name, player['spec'])
    benchmark = db.get_benchmark(*key, hero or '')
    hero_status = (benchmark or {}).get('status')
    if hero and not (benchmark or {}).get('players'):
        whole = db.get_benchmark(*key, '')
        if (whole or {}).get('players') or benchmark is None:
            benchmark = whole
    return player, hero, benchmark, our_pulls(numbered, name, spec=player['spec'], hero=hero), hero_status


async def ensure_spells_for(numbered, name):
    """Before comparing one character: make sure their spec's top-player spells have Wowhead text."""
    found = _benchmark_for(numbered, name)
    if not found:
        return 0
    _, _, bench, pulls, _ = found
    ours = {sid for p in pulls for _, sid in p['casts']}
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
    players use as majors on this boss (same rule as compare(): at least MIN_AGREE of them - on any of
    its hero trees), so the raid timeline shows what matters for that spec instead of every 30 s button.
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
        majors = out.setdefault((r['class'], r['spec']), set())
        for name, g in top_groups(top, info).items():
            if g['category'] not in (THROUGHPUT, TRINKET) or len(g['users']) < need:
                continue
            kind = ability_kind(name, g, top, windows(top, g['ids']), _texts(g['ids'], info)[1], overrides.get(name))
            if kind == MAJOR:
                majors.add(name)
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


def spec_label(player, hero=None):
    """'Fire Mages', 'Havoc Demon Hunters' - with a hero tree 'Annihilator Devourer Demon Hunters'."""
    return f"{hero or ''} {readable(player.get('spec'))} {readable(player.get('class'))}s".strip()


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
    {'player', 'hero' (their hero tree, None when unknown), 'benchmark', 'top', 'pulls', 'rows', 'spells', 'label',
    'talents' (gamedata.not_taken)} - or None when there's nothing to compare (no spec known).
    numbered: [(pull number, pull with analysis)].
    """
    from . import db
    found = _benchmark_for(numbered, name)
    if not found:
        return None
    player, hero, benchmark, pulls, hero_status = found
    top = (benchmark or {}).get('players') or []
    ids = {sid for p in top for _, sid in p['casts']} | {sid for p in pulls for _, sid in p['casts']}
    spells = db.get_spells(ids) if ids else {}
    overrides = db.get_spec_overrides().get((player['class'], player['spec']), {})
    from .gamedata import choices, not_taken
    talents = not_taken(numbered, name)
    # Named after the top players it really is: their hero tree's, or the whole spec's until those are fetched
    label = spec_label(player, benchmark.get('hero') if benchmark else hero)
    return {'player': player, 'hero': hero, 'hero_status': hero_status, 'benchmark': benchmark, 'top': top,
            'pulls': pulls, 'talents': talents,
            'rows': compare(pulls, top, spells, overrides, talents, choices()), 'spells': spells, 'label': label}
