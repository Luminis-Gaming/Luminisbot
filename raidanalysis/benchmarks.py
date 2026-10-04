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

Timing: phases start at different times for everyone (they're health-based), so casts are
compared as "time into phase segment n" (the n-th phase change). A *window* is a moment where
at least 3 of the top 5 pressed the same ability within 20 s of each other; a player hits it
when they pressed it within ±20 s of its middle. Windows in phases a pull never reached, or past
the point it ended, don't count.
"""
import logging
import re
from collections import Counter

from . import analyzer, cooldowns

logger = logging.getLogger(__name__)

TOP_N = 5
REFRESH_DAYS = 7
SPECS_PER_RUN = 3
TOP_RARE_LIMIT = 25          # a top player's ability cast more often than this per kill is rotational
MAJOR_COOLDOWN_MS = 30000
WINDOW_MS = 20000
TOLERANCE_MS = 20000
MIN_AGREE = 3
MIN_PULL_MS = 60000          # shorter pulls say nothing about cooldown usage
DIFFICULTIES = (3, 4, 5)

THROUGHPUT, POTION, TRINKET = 'throughput', 'potion', 'trinket'
CATEGORY_LABELS = {THROUGHPUT: 'Damage / healing cooldowns', POTION: 'Combat potions', TRINKET: 'Trinkets & items',
                   **cooldowns.CATEGORY_LABELS}
CATEGORY_ORDER = (THROUGHPUT, POTION, 'personal', TRINKET, 'external', 'raid', 'utility')
POTION_GROUP = 'Combat potion'  # any combat potion counts - which one is a stat choice
# Pressed more often than this (per minute, by the top players) = too frequent for its moments to
# mean much: judged on how often you press it instead.
TIMING_MAX_PER_MIN = 0.75
# Verdicts only for what a player controls alone; externals and raid cooldowns depend on the raid's plan.
JUDGED = (THROUGHPUT, POTION, 'personal', TRINKET)

# Long cooldowns that aren't throughput: movement, interrupts, crowd control, taunts, dispels.
NOT_MAJOR = {
    'Heroic Leap', 'Charge', 'Intervene', 'Disengage', 'Blink', 'Shimmer', 'Demonic Circle', 'Demonic Circle: Teleport',
    'Roll', 'Chi Torpedo', 'Transcendence', 'Transcendence: Transfer', 'Fel Rush', 'Vengeful Retreat',
    'Infernal Strike', "Death's Advance", 'Wraith Walk', 'Death Grip', 'Sprint', 'Dash', 'Tiger Dash', 'Wild Charge',
    'Divine Steed', 'Spirit Walk', 'Ghost Wolf', 'Hover', 'Glide', 'Aspect of the Cheetah',
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


def metric_for(role):
    return 'hps' if role == 'healer' else 'dps'


def cooldown_ms(meta):
    """'Instant · 2 min cooldown' -> 120000 (None without a cooldown)."""
    match = _COOLDOWN_RE.search(meta or '')
    if not match:
        return None
    return float(match.group(1)) * (60000 if match.group(2).lower() == 'min' else 1000)


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
    players = []
    for ranking in rankings:
        if len(players) >= TOP_N:
            break
        r = _ranking_fields(ranking)
        if r['hidden'] or not r['code'] or not r['fight_id'] or not r['name']:
            continue
        try:
            fight = await wcl.get_player_fight(session, r['code'], r['fight_id'], r['name'])
        except wcl.WCLRateLimited:
            raise
        except wcl.WCLError as e:
            logger.info(f"[RAIDS] Skipping top parse {r['code']}#{r['fight_id']}: {e}")
            continue
        events = [e for e in fight['casts'] if e.get('type') == 'cast' and analyzer._event_ability(e)]
        counts = Counter(analyzer._event_ability(e) for e in events)
        casts = [[e['timestamp'] - fight['start'], analyzer._event_ability(e)] for e in events
                 if counts[analyzer._event_ability(e)] <= TOP_RARE_LIMIT]
        if not casts:
            continue
        players.append({'rank': len(players) + 1, 'name': r['name'], 'amount': round(r['amount']),
                        'server': r['server'], 'region': r['region'], 'guild': r['guild'],
                        'code': r['code'], 'fight_id': r['fight_id'], 'duration': fight['end'] - fight['start'],
                        'phases': fight['phases'], 'casts': casts})
    return players


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
    """Moments where >= MIN_AGREE top players cast one of spell_ids: [{'segment', 'at', 'players'}]."""
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
                    out.append({'segment': key, 'at': times[len(times) // 2], 'players': len(players)})
                cluster = []
            if who is not None:
                cluster.append((into, who))
    return sorted(out, key=lambda w: (w['segment'][0], w['at']))


def compare(pulls, top, spell_info):
    """
    How one player's pulls line up with the top players, per major ability.

    pulls: [{'number', 'duration', 'phases': [{'id', 'start'}], 'casts': [[t, id]], 'cast_ids': set or None}]
    top: benchmark players. spell_info: {id: {'name', 'meta', ...}} (Wowhead).
    -> [{'name', 'ids', 'icon_id', 'category', 'top_users', 'top_per_min', 'ours_per_min', 'ours_casts',
         'windows', 'hits', 'considered', 'verdict', 'known'}], most important first.
    """
    pulls = [p for p in pulls if p['duration'] >= MIN_PULL_MS]
    if not top or not pulls:
        return []
    need = min(MIN_AGREE, len(top))
    ref = reference_starts(top)
    # Same ability, several spell IDs (e.g. Alter Time cast / return): group by name.
    groups = {}
    for i, player in enumerate(top):
        for _, sid in player['casts']:
            info = spell_info.get(sid) or {}
            cat = category(sid, info)
            if not cat:
                continue
            key = POTION_GROUP if cat == POTION else info.get('name') or str(sid)
            g = groups.setdefault(key, {'ids': set(), 'users': set(), 'category': cat, 'counts': Counter()})
            g['ids'].add(sid)
            g['users'].add(i)
            g['counts'][i] += 1
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
        known = [p for p in pulls if (ids & p['cast_ids'] if p.get('cast_ids') is not None
                                      else tracked and p.get('tracked'))]
        ours = [[t for t, sid in p['casts'] if sid in ids] for p in pulls]
        ours_casts = sum(len(c) for c in ours)
        wins = windows(top, ids)
        hits = considered = 0
        for pull, casts in zip(pulls, ours):
            if pull not in known:
                continue
            lengths = segment_lengths(pull['phases'], pull['duration'])
            mine = [segment_of(t, pull['phases']) for t in casts]
            for w in wins:
                if w['segment'] not in lengths or w['at'] > lengths[w['segment']]:
                    continue
                considered += 1
                hits += any(key == w['segment'] and abs(into - w['at']) <= TOLERANCE_MS for key, into in mine)
        ours_per_min = ours_casts / minutes if minutes else 0
        verdict = None
        timing = top_per_min <= TIMING_MAX_PER_MIN
        if not timing:  # frequent: overlapping moments say nothing, compare how often instead
            hits = considered = 0
        if not known:
            verdict = None
        elif not ours_casts:
            verdict = None if g['category'] == TRINKET else 'missing'
        elif considered >= 2:
            rate = hits / considered
            verdict = 'good' if rate >= 0.75 else 'off' if rate < 0.4 else 'ok'
        elif top_per_min:
            ratio = ours_per_min / top_per_min
            verdict = 'good' if ratio >= 0.75 else 'off' if ratio < 0.5 else 'ok'
        rows.append({'name': name, 'ids': sorted(ids), 'icon_id': min(ids), 'category': g['category'],
                     'top_users': len(g['users']), 'top_per_min': top_per_min, 'ours_per_min': ours_per_min,
                     'ours_casts': ours_casts, 'windows': [dict(w, ref_at=ref.get(w['segment'], 0) + w['at'])
                                                           for w in wins],
                     'hits': hits, 'considered': considered, 'verdict': verdict, 'known': bool(known)})
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(rows, key=lambda r: (order.get(r['category'], 9), -r['top_users'], r['name']))


def _clock(ms):
    s = int(round(ms / 1000))
    return f'{s // 60}:{s % 60:02d}'


def notes(rows, spec_label, limit=3):
    """Feedback lines from compare(): [{'tone': 'good'|'bad', 'text'}] - misses first, a couple of wins."""
    bad, good = [], []
    for r in rows:
        if r['category'] not in JUDGED or not r['verdict']:
            continue
        moments = ', '.join(_clock(w['ref_at']) for w in r['windows'][:4])
        if r['verdict'] == 'missing':
            bad.append(f"{r['name']}: {r['top_users']} of the top {spec_label} use it - you never pressed it "
                       f"(talent choice, or a missed cooldown?)")
        elif r['verdict'] == 'off' and r['considered'] >= 2:
            bad.append(f"{r['name']}: top {spec_label} press it around {moments} - across your pulls you "
                       f"were within {TOLERANCE_MS // 1000} s of {r['hits']} of {r['considered']} such moments")
        elif r['verdict'] == 'off':
            bad.append(f"{r['name']}: {r['ours_per_min'] * 5:.1f}× per 5 min - the top {spec_label} manage "
                       f"{r['top_per_min'] * 5:.1f}×")
        elif r['verdict'] == 'good':
            good.append(f"{r['name']} lined up with the top {spec_label}"
                        + (f" ({r['hits']}/{r['considered']} moments)" if r['considered'] >= 2 else ''))
    return ([{'tone': 'bad', 'text': t} for t in bad[:limit]]
            + [{'tone': 'good', 'text': t} for t in good[:max(1, limit - len(bad))]])


def our_pulls(pulls, name):
    """Our raid pulls -> compare() input for one character (pulls they weren't in are skipped)."""
    out = []
    for number, pull in pulls:
        analysis = pull.get('analysis') or {}
        if not any(p['name'] == name for p in analysis.get('players') or []):
            continue
        casts = (analysis.get('casts') or {}).get(name)
        if casts is None:  # analyzed before every rare cast was kept: tracked cooldowns + consumables only
            casts = [[c['t'], c['ability_id']] for c in analysis.get('cooldowns') or [] if c['name'] == name]
            casts += [[u['t'], u['ability_id']] for u in analysis.get('consumables') or [] if u['name'] == name]
        cast_ids = analysis.get('cast_ids')
        out.append({'number': number, 'fight_id': pull['fight_id'], 'kill': pull.get('kill'),
                    'duration': pull['end_ms'] - pull['start_ms'], 'phases': pull.get('phases') or [],
                    'casts': sorted(casts), 'cast_ids': set(cast_ids) if cast_ids is not None else None,
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


async def ensure_spells_for(numbered, name):
    """Before comparing one character: make sure their spec's top-player spells have Wowhead text."""
    from . import db
    player = next((p for _, pull in numbered for p in (pull.get('analysis') or {}).get('players') or []
                   if p['name'] == name and p.get('spec')), None)
    if not player or not numbered:
        return 0
    first = numbered[0][1]
    bench = db.get_benchmark(first['encounter_id'], first['difficulty'], player['class'], player['spec'])
    ours = {sid for p in our_pulls(numbered, name) for _, sid in p['casts']}
    return await ensure_spells({sid for p in (bench or {}).get('players') or [] for _, sid in p['casts']} | ours)


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
    out = {}
    for r in rows:
        top = r['players'] or []
        users = {}
        for i, p in enumerate(top):
            for _, sid in p['casts']:
                if category(sid, info.get(sid)) in (THROUGHPUT, TRINKET):
                    users.setdefault(info[sid]['name'], set()).add(i)
        need = min(MIN_AGREE, len(top))
        out[(r['class'], r['spec'])] = {name for name, who in users.items() if len(who) >= need}
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


def for_player(numbered, name):
    """
    Everything the comparison views need for one character on one boss+difficulty:
    {'player', 'benchmark', 'top', 'pulls', 'rows', 'spells', 'label'} - or None when there's
    nothing to compare (no spec known). numbered: [(pull number, pull with analysis)].
    """
    from . import db
    player = next((p for _, pull in numbered for p in (pull.get('analysis') or {}).get('players') or []
                   if p['name'] == name and p.get('spec')), None)
    if not player or not numbered:
        return None
    first = numbered[0][1]
    benchmark = db.get_benchmark(first['encounter_id'], first['difficulty'], player['class'], player['spec'])
    top = (benchmark or {}).get('players') or []
    pulls = our_pulls(numbered, name)
    ids = {sid for p in top for _, sid in p['casts']} | {sid for p in pulls for _, sid in p['casts']}
    spells = db.get_spells(ids) if ids else {}
    return {'player': player, 'benchmark': benchmark, 'top': top, 'pulls': pulls,
            'rows': compare(pulls, top, spells), 'spells': spells, 'label': spec_label(player)}
