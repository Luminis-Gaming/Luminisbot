"""
Fetches the guild's raid logs from WCL, analyzes every pull and caches the
result in raid_pulls. Pulls are immutable once logged, so each one is only
fetched once; live logs are picked up as new pulls appear.
"""
import asyncio
import logging
import time

import aiohttp

from . import analyzer, bossmech, cooldowns, db, wcl

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
status = {'running': False, 'current': None, 'last_finished': None, 'last_result': None,
          'last_error': None, 'last_new': 0, 'wcl': None, 'last_points': None, 'paused_until': None,
          'data_version': None}  # db.data_version() after the last sync: the page caches' key


after_new_data = []  # async callables run after a sync that changed the data (web/routes.py: warm_pages)


def _note_data_version():
    """
    After a sync: what the pages show, fingerprinted - unchanged keeps every cached page (web/routes.py). Changed
    (and not the first look, at startup): the after_new_data hooks run in the background.
    """
    before = status.get('data_version')
    try:
        status['data_version'] = db.data_version()
    except Exception:
        logger.warning('[RAIDS] Data version unavailable', exc_info=True)
        status['data_version'] = None  # the caches fall back to the sync's time
        return
    if before is not None and status['data_version'] != before:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # not in the bot's loop (a worker thread): nothing to warm from here
        for hook in after_new_data:
            loop.create_task(_run_hook(hook))


async def _run_hook(hook):
    status_before = status.get('data_version')
    await asyncio.sleep(1)  # the sync's status settles (not running) before the pages are built
    if status.get('data_version') == status_before:
        try:
            await hook()
        except Exception:
            logger.exception('[RAIDS] After-sync hook failed')


def _phase_names(report):
    """{encounterID: {phaseID: {name, intermission}}} as JSON-friendly string keys."""
    out = {}
    for encounter in report.get('phases') or []:
        out[str(encounter['encounterID'])] = {
            str(p['id']): {'name': p['name'], 'intermission': bool(p.get('isIntermission'))}
            for p in encounter.get('phases') or []}
    return out


def _raid_pulls(report):
    return [f for f in report.get('fights') or []
            if f.get('encounterID') and f.get('difficulty') in wcl.RAID_DIFFICULTIES]


async def _analyze_pull(session, code, fight, actors, detail=True):
    tables = await wcl.get_fight_tables(session, code, fight['id'])

    damage_events, complete_ids, debuff_events = await _mechanic_events(session, code, fight, tables)
    potion_ids, defensive_ids = analyzer.consumable_ids(tables.get('casts'))
    cooldown_meta = cooldowns.cooldown_meta(tables.get('casts'))
    consumable_events, buff_events, heal_events = [], [], []
    # ...plus everything the top players of any spec press on this boss (benchmarks.py), so a spec
    # several of us play still gets every Ebon Might / Combustion even if the raid casts it often.
    # Matched by id and by name: our log can record an ability under another spell id than theirs.
    benchmark_ids = set(db.benchmark_spell_ids(fight['encounterID']))
    benchmark_names = {info['name'] for info in db.get_spells(benchmark_ids).values() if info.get('name')}
    entries = analyzer.cast_entries(tables.get('casts'))  # incl. variants nested under a parent ability
    used_ids = {e.get('guid') for e in entries if e.get('guid')}
    named = {e['guid'] for e in entries if e.get('guid') and e.get('name') in benchmark_names}
    cast_ids = sorted(set(potion_ids) | set(defensive_ids) | set(cooldown_meta)
                      | set(analyzer.rare_cast_ids(tables.get('casts'))) | (benchmark_ids & used_ids) | named)
    if cast_ids:  # potions, healthstones, cooldowns and other rarely cast abilities in one request
        consumable_events = await wcl.get_events(session, code, fight['id'], 'Casts',
                                                 f"ability.id in ({','.join(map(str, cast_ids))})")
    if potion_ids:  # buff windows: how long each potion lasted, and pre-pots
        buff_events = await wcl.get_events(session, code, fight['id'], 'Buffs',
                                           f"ability.id in ({','.join(map(str, potion_ids))})")
    if defensive_ids:  # how much each healthstone / healing potion healed for
        heal_events = await wcl.get_events(session, code, fight['id'], 'Healing',
                                           f"ability.id in ({','.join(map(str, defensive_ids))})")
    # Enemy casts for the timeline (bosses + adds; ~100 per pull)
    enemy_cast_events = await wcl.get_events(session, code, fight['id'], 'Casts', "type = 'cast'",
                                             hostility='Enemies')
    # Gear, flask, food and buffs at the pull (one small event per player)
    combatant_events = await wcl.get_events(session, code, fight['id'], 'CombatantInfo', "type = 'combatantinfo'")

    analysis = analyzer.analyze_fight(fight, actors, tables, damage_events, consumable_events,
                                  set(potion_ids), set(defensive_ids), buff_events, heal_events, enemy_cast_events,
                                  combatant_events, cooldown_meta, event_ids=complete_ids, debuff_events=debuff_events)
    # Curated boss-specific pass/fail mechanics (bossmech.py): each says what it needs fetched and keeps its own
    # summary of it. Its events can be on us or on enemies: both hostilities.
    special = bossmech.for_encounter(fight['encounterID'])
    if special:
        names_by_id = {a['id']: a['name'] for a in actors}
        roster = {p['name'] for p in analysis.get('players') or []}
        analysis['boss_mechanics'] = {}
        for mech in special:
            events = {}
            for name, data_type, expression, positions in mech.fetches():
                for hostility in ('Friendlies', 'Enemies'):
                    events.setdefault(name, []).extend(await wcl.get_events(
                        session, code, fight['id'], data_type, expression, hostility=hostility,
                        include_resources=positions))
            analysis['boss_mechanics'][mech.key] = mech.collect(events, fight['startTime'], names_by_id, roster)
    # Everyone's talents this pull: an ability you never pressed is only "not talented" when it really wasn't
    analysis['talents'] = analyzer.talent_entries({a['id']: a['name'] for a in actors},
                                                  {p['name'] for p in analysis.get('players') or []}, combatant_events)
    analysis['cast_ids'] = cast_ids  # which spells 'casts' is complete for (benchmarks.compare)
    # Every spell anyone in the raid cast this pull: one that isn't here was really never pressed
    # (a talent you don't take), as opposed to one we didn't fetch.
    analysis['casts_seen'] = sorted(used_ids)
    analysis['incoming'] = await _incoming(session, code, fight, actors, analysis)
    extras = await _fight_extras(session, code, fight, actors, analysis, detail)
    if extras:
        analysis['extras'] = extras
    return analysis


async def _incoming(session, code, fight, actors, analysis):
    """
    Every enemy hit on a player, boiled down to what came at whom each second and when their own buffs were up
    (defensives.summarize: the coach's defensive stars) - one events request, ~5 WCL points. None on failure
    or for a very short pull.
    """
    from . import defensives
    if fight['endTime'] - fight['startTime'] < defensives.INCOMING_MIN_PULL_MS:
        return None
    try:
        events = await wcl.get_events(session, code, fight['id'], 'DamageTaken', defensives.EVENTS_FILTER,
                                      max_events=defensives.EVENTS_MAX)
    except wcl.WCLRateLimited:
        raise
    except wcl.WCLError as e:
        logger.info(f"[RAIDS] Incoming damage for {code}#{fight['id']} not fetched: {e}")
        return None
    roles = {p['name']: p.get('role') for p in analysis.get('players') or []}
    mine = {}  # their personal defensives (cooldowns.py), to see what hit them with one up
    for use in analysis.get('cooldowns') or []:
        if use.get('category') == 'personal':
            mine.setdefault(use['name'], set()).add(use['ability_id'])
    return defensives.summarize(events, fight['startTime'], {a['id']: a['name'] for a in actors}, roles,
                                analysis.get('casts') or {}, mine)


TAGGED_EVENTS_MAX = 60000  # the tagged mechanics' damage events in a pull (fetched on their own, first)
DAMAGE_EVENTS_MAX = 20000  # ...and the rest's: the small ones (analyzer.EVENT_FETCH_MAX_EVENTS each)


async def _mechanic_events(session, code, fight, tables):
    """
    Damage events for the per-player hits on enemy abilities: (events, ids whose events are complete,
    debuff events). Every tagged mechanic is fetched whatever its size - by name, so all the spell ids it's
    logged under - in a request of its own, before the small untagged ones; a request that hits its cap
    leaves its ids incomplete (counted from WCL's top-5 table instead). A tagged mechanic that dealt no
    damage at all (Shell Spin's shells only stun) is counted from its debuff landing on players.
    """
    from . import guides
    hostile = analyzer.hostile_damage_entries(tables.get('damageTaken'))
    tags, _ = guides.effective_tags(fight['encounterID'], fresh=True)  # this sync's own guide scans count
    tagged_names = {e.get('name') for e in hostile if tags.get(e['guid']) in analyzer.AVOIDABLE_TAGS}
    tagged = sorted({e['guid'] for e in hostile if e.get('name') in tagged_names})
    rest = [i for i in analyzer.event_ability_ids(hostile) if i not in set(tagged)]
    events, complete = [], set()
    for ids, cap in ((tagged, TAGGED_EVENTS_MAX), (rest, DAMAGE_EVENTS_MAX)):
        if not ids:
            continue
        got = await wcl.get_events(session, code, fight['id'], 'DamageTaken',
                                   f"ability.id in ({','.join(map(str, ids))})", max_events=cap)
        events += got
        if len(got) < cap:
            complete |= set(ids)
    totals = {}
    for e in hostile:
        totals[e.get('name')] = totals.get(e.get('name'), 0) + (e.get('total') or 0)
    status = sorted(n for n in tagged_names if n and not totals.get(n))
    debuffs = []
    if status:
        names = ', '.join('"' + n.replace('"', '') + '"' for n in status)
        debuffs = await wcl.get_events(session, code, fight['id'], 'Debuffs',
                                       f'type = "applydebuff" and ability.name in ({names})')
        abilities = await wcl.get_report_abilities(session, code) if debuffs else {}
        for e in debuffs:  # events carry only the spell id: the name ties it to its mechanic
            e['abilityName'] = (abilities.get(e.get('abilityGameID')) or ('',))[0]
    return events, complete, debuffs


# The per-player detail (buffs, debuffs, casts, resources, procs: most of a pull's WCL points) is fetched
# for the pulls the comparisons are about - every kill and the furthest wipes per boss and night. Every
# pull still gets the cheap part: parses, damage / healing, active time, damage by target.
DETAIL_WIPES = 3
DETAIL_MIN_MS = 60000


def detail_fight_ids(pulls):
    """
    Which of a report's pulls get the per-player detail: kills, and the DETAIL_WIPES furthest wipes per boss -
    plus, for anyone in none of those (joined late, sat out the kill), their own furthest pull, so everyone has
    one to show their rotation from. One such pull usually covers several of them (friendlyPlayers: who was in it).
    """
    groups, out = {}, set()
    for f in pulls:
        groups.setdefault((f.get('encounterID'), f.get('difficulty')), []).append(f)

    def furthest(f):
        return (not f.get('kill'), f.get('fightPercentage') if f.get('fightPercentage') is not None else 100,
                -(f['endTime'] - f['startTime']))
    for fights in groups.values():
        chosen = {f['id'] for f in fights if f.get('kill')}
        wipes = sorted((f for f in fights if not f.get('kill') and f['endTime'] - f['startTime'] >= DETAIL_MIN_MS),
                       key=furthest)
        chosen |= {f['id'] for f in wipes[:DETAIL_WIPES]}
        covered = {p for f in fights if f['id'] in chosen for p in f.get('friendlyPlayers') or []}
        for f in wipes:  # furthest first: the best pull left for whoever isn't covered yet
            if f['id'] not in chosen and set(f.get('friendlyPlayers') or []) - covered:
                chosen.add(f['id'])
                covered |= set(f['friendlyPlayers'])
        out |= chosen
    return out


PROC_EVENTS_MAX = 60000  # a raid's tracked self-buff events: ~20-30k a pull
SCRAPE_PAUSE_SECONDS = 1  # between website scrapes (wipe parses), to look less like a bot


async def _wipe_parses(session, code, fight, roster):
    """
    WCL's API only ranks kills; the website shows parses for wipes too - scraped the same way as for
    the Discord log posts, when a browser session is configured (WCL_SCRAPE_COOKIES).
    """
    from wcl_web_scraper import scrape_configured, scrape_wcl_web_data
    if not scrape_configured():
        return {}
    from . import throughput
    parses = {}
    metrics = ['dps'] + (['hps'] if any(p.get('role') == 'healer' for p in roster) else [])
    for metric in metrics:
        scraped = await scrape_wcl_web_data(session, code, fight['id'], fight['startTime'], fight['endTime'],
                                            fight['encounterID'], metric)
        wanted = {p['name'] for p in roster if (p.get('role') == 'healer') == (metric == 'hps')}
        parses.update({n: v for n, v in throughput.parses_from_scrape(scraped).items() if n in wanted})
        await asyncio.sleep(SCRAPE_PAUSE_SECONDS)
    return parses


async def _fight_extras(session, code, fight, actors, analysis, detail=True):
    """
    Throughput, parses and damage by target per player (one request) - and with detail, uptime, casts,
    resources and wasted procs (a handful more; see detail_fight_ids) - for throughput.build_extras.
    A failure here never fails the pull: it's retried on a later sync.
    """
    from . import gamedata, throughput
    roster = analysis.get('players') or []
    names_by_id = {a['id']: a['name'] for a in actors}
    try:
        extras = await wcl.get_fight_extras(session, code, fight['id'])
        in_pull = {p['name'] for p in roster}
        ids = [aid for aid, name in names_by_id.items() if name in in_pull]
        tracked = gamedata.tracked_ids()
        per_player, resource_events, procs, proc_events = {}, [], [], []
        if detail:
            # Healers' HoTs (and Augmentation's buffs) are kept on others: one more table each
            keep_up = {p['name'] for p in roster if throughput.wants_on_others(p)}
            others = [aid for aid in ids if names_by_id.get(aid) in keep_up]
            per_player = await wcl.get_player_tables(session, code, fight['id'], ids, extras['boss_ids'], casts=True,
                                                     others=others)
            resource_events = await wcl.get_events(session, code, fight['id'], 'Resources', "type = 'resourcechange'")
            procs = throughput.proc_candidates(per_player, tracked)
        if procs:  # only the self-buffs worth checking: the whole raid's are ~30k events a pull
            proc_events = await wcl.get_events(session, code, fight['id'], 'Buffs',
                                               f"source.id = target.id and ability.id in ({','.join(map(str, procs))})",
                                               max_events=PROC_EVENTS_MAX)
        parses = throughput.parses_for_roles(roster, extras.get('rankings'), extras.get('healer_rankings'))
        if not parses and fight.get('kill') and extras.get('rankings') is None and not wcl.v2_blocked():
            try:  # the rest came from v1, which has no parses: one small v2 request
                ranked = await wcl.get_report_rankings(session, code, fight['id'])
                parses = throughput.parses_for_roles(roster, ranked.get('dps'), ranked.get('hps'))
            except wcl.WCLError as e:  # rate limited too: the kill just goes without a parse
                logger.info(f"[RAIDS] Parses for {code}#{fight['id']} not fetched: {e}")
        if not parses and not fight.get('kill'):
            try:
                parses = await _wipe_parses(session, code, fight, roster)
            except Exception as e:  # the website is best effort
                logger.info(f"[RAIDS] Wipe parses for {code}#{fight['id']} not scraped: {e}")
        return throughput.build_extras(fight, roster, names_by_id, extras, per_player, parses,
                                       resource_events, proc_events, tracked, detail=detail)
    except wcl.WCLRateLimited:
        raise
    except wcl.WCLError as e:
        logger.warning(f"[RAIDS] Throughput / uptime for {code}#{fight['id']} failed: {e}")
        return None


async def sync_report(session, code, source='guild', force=False):
    """Analyze every raid pull in one report that isn't cached yet. Returns pulls analyzed."""
    status['current'] = f"Checking report {code}…"
    report = await wcl.get_report_overview(session, code)
    # Recorded even without raid pulls (Mythic+ / trash logs) so they're only checked once -
    # the pages only list reports that have pulls.
    db.upsert_report(report, _phase_names(report), source=source)
    # each player's realm (character pages go by realm and name: two of one name are two people)
    db.save_realms(code, {a['name']: a.get('server') for a in ((report.get('masterData') or {}).get('actors') or [])})
    pulls = _raid_pulls(report)
    if not pulls:
        return 0

    done = set() if force else db.analyzed_fight_ids(code, analyzer.ANALYSIS_VERSION)
    actors = (report.get('masterData') or {}).get('actors') or []
    detailed = detail_fight_ids(pulls)

    analyzed = 0
    for number, fight in enumerate(pulls, 1):
        if fight['id'] in done:
            continue
        # A long night is dozens of requests: check the budget as we go, not only between nights.
        # What's left is picked up next sync (already analyzed pulls are skipped).
        if analyzed and analyzed % BUDGET_CHECK_EVERY == 0 and not await _budget_ok(session):
            raise wcl.WCLError(_pause_message() if _paused() else _budget_message())
        status['current'] = f"Analyzing {report.get('title') or code} — pull {number}/{len(pulls)} ({fight['name']})"
        analysis = await _analyze_pull(session, code, fight, actors, fight['id'] in detailed)
        db.upsert_pull(code, fight, analysis)
        analyzed += 1
        logger.info(f"[RAIDS] Analyzed {code}#{fight['id']} {fight['name']} "
                    f"({'kill' if fight.get('kill') else 'wipe'})")
    # Pulls analyzed before throughput / uptime were fetched - or that became one of the night's furthest
    # wipes since (a live log): just that part.
    from .throughput import EXTRAS_VERSION
    state = db.extras_state(code, EXTRAS_VERSION)
    missing = {fid for fid in done if state.get(fid) is None or (fid in detailed and not state[fid])}
    for i, fight in enumerate(f for f in pulls if f['id'] in missing):
        if i and i % BUDGET_CHECK_EVERY == 0 and not await _budget_ok(session):
            raise wcl.WCLError(_pause_message() if _paused() else _budget_message())
        status['current'] = f"Fetching throughput & uptime — {report.get('title') or code} ({fight['name']})"
        pull = db.get_pull(code, fight['id'])
        extras = await _fight_extras(session, code, fight, actors, (pull or {}).get('analysis') or {},
                                     fight['id'] in detailed)
        if extras:
            db.set_pull_extras(code, fight['id'], extras)
            analyzed += 1
    return analyzed


BUDGET_CHECK_EVERY = 3  # pulls

# Raid-event logs are picked up automatically only for recent events (older nights can be
# imported by URL), a few per sync so a backlog doesn't burn the hourly WCL API budget.
EVENT_BACKLOG_PER_RUN = 5
EVENT_BACKLOG_DAYS = 21


def _budget_message():
    w = status.get('wcl') or {}
    resets = f", resets in {int((w.get('reset_in') or 0) / 60)} min" if w.get('reset_in') else ''
    spent = f"{w['spent']:.0f}" if isinstance(w.get('spent'), (int, float)) else '?'
    return (f"Paused to stay within the WCL API budget ({spent}/{w.get('limit', '?')} points "
            f"used this hour{resets}) — continues on a later sync"
            + ("" if _share > WCL_BUDGET_SHARE else " (tick 'Use the full WCL budget' to go further now)"))


def _event_codes_to_sync(already_queued):
    """Raid-event logs (newest first) that still need fetching, capped per run."""
    out = []
    for code in db.event_report_codes(since_days=EVENT_BACKLOG_DAYS):
        if code in already_queued or db.report_is_final(code):
            continue
        out.append(code)
        if len(out) >= EVENT_BACKLOG_PER_RUN:
            break
    return out


# WCL's limit is points per hour (heavier queries cost more), shared with the bot's other WCL
# features (DPS / Heal / Deaths buttons). The sync stops once this share of the hour's budget
# is used and carries on next run.
WCL_BUDGET_SHARE = 0.7
# An admin can let one run (Sync now / Re-analyze / Fetch all) use nearly the whole hour instead -
# the small rest keeps us off WCL's hard limit. The bot's other WCL buttons may then be short until
# the hour resets.
FULL_BUDGET_SHARE = 0.98
_share = WCL_BUDGET_SHARE  # the current run's share (one run at a time: _lock)


# After WCL answers 429 we leave it alone until its hourly budget resets (or for this long when
# we can't tell when that is), instead of knocking again every sync.
RATE_LIMIT_PAUSE_FALLBACK = 15 * 60


def _paused():
    return bool(status.get('paused_until') and status['paused_until'] > time.time())


def _pause_message():
    from datetime import datetime
    until = datetime.fromtimestamp(status['paused_until']).strftime('%H:%M')
    return f"WCL rate limit hit - pausing WCL requests until {until} (the hourly budget resets)"


def _rate_limited(error):
    """WCL said 429: pause until its budget resets. Returns the message to show."""
    w = status.get('wcl') or {}
    wait = getattr(error, 'retry_after', None)
    if not wait and w.get('reset_in') and w.get('checked'):
        wait = w['reset_in'] - (time.time() - w['checked'])
    status['paused_until'] = time.time() + max(60, wait or RATE_LIMIT_PAUSE_FALLBACK)
    logger.warning(f"[RAIDS] {_pause_message()}")
    return _pause_message()


async def _budget_ok(session):
    """
    Refresh status['wcl'] from WCL's own counter; False once we're past our share of the hour. (WCL v1
    doesn't help here: its calls count against the same hourly points.)
    """
    if _paused():
        return False
    try:
        limits = await wcl.get_rate_limit(session)
    except wcl.WCLError:
        return True  # can't tell - let the request itself report a rate limit
    spent, cap = limits.get('pointsSpentThisHour') or 0, limits.get('limitPerHour') or 3600
    status['wcl'] = {'spent': spent, 'limit': cap, 'reset_in': limits.get('pointsResetIn'),
                     'checked': time.time()}
    return spent < _share * cap


async def sync_guild(limit=10, force_codes=(), extra_codes=(), full_budget=False):
    """
    Sync the guild's latest `limit` reports, the logs attached to raid events, extra_codes
    (e.g. a log someone asked about in Discord) and force_codes (re-analyzed from scratch).
    """
    if _lock.locked():
        return None
    if _paused():  # WCL said 429 earlier: wait for its budget to reset instead of knocking again
        status.update(running=False, current=None, last_result=_pause_message(), last_error=_pause_message())
        return 0
    async with _lock:
        global _share
        _share = FULL_BUDGET_SHARE if full_budget else WCL_BUDGET_SHARE
        status.update(running=True, last_error=None)
        started = time.time()
        total, reports, errors = 0, 0, []
        try:
            from wcl_api import WCL_GUILD_ID
            async with aiohttp.ClientSession() as session:
                if not await _budget_ok(session):
                    raise wcl.WCLError(_budget_message())
                spent_before = status['wcl']['spent'] if status.get('wcl') else None
                try:
                    listed = await wcl.list_guild_reports(session, WCL_GUILD_ID, limit=limit)
                except wcl.WCLRateLimited:
                    raise
                except wcl.WCLError as e:  # e.g. v1 without the guild's name: the other logs still sync
                    logger.warning(f"[RAIDS] Guild report list unavailable: {e}")
                    errors.append(str(e))
                    listed = []
                codes = [(c, 'manual', True) for c in force_codes]
                # A log someone asked about (Discord recap): kept for a week like an import, unless it's a
                # recent guild log anyway (then the guild list below upgrades it).
                codes += [(c, 'manual', False) for c in extra_codes if c not in force_codes]
                # Finished nights too, while their pulls lack throughput / uptime (fetched since) - or someone
                # has no pull with the per-player detail (picked for late joiners since: detail_fight_ids).
                from .throughput import EXTRAS_VERSION
                codes += [(r['code'], 'guild', False) for r in listed
                          if r['code'] not in force_codes and r['code'] not in extra_codes
                          and (not db.report_is_final(r['code'])
                               or db.fight_ids_missing_extras(r['code'], EXTRAS_VERSION)
                               or db.players_missing_detail(r['code'], DETAIL_MIN_MS))]
                queued = {code for code, _, _ in codes}
                codes += [(c, 'event', False) for c in _event_codes_to_sync(queued)]
                for i, (code, source, force) in enumerate(codes):
                    if i and not await _budget_ok(session):
                        errors.append(_budget_message())
                        logger.warning(f"[RAIDS] {_budget_message()}")
                        break
                    try:
                        count = await sync_report(session, code, source=source, force=force)
                        total += count
                        reports += 1 if count else 0
                    except wcl.WCLRateLimited as e:
                        errors.append(_rate_limited(e))
                        break
                    except wcl.WCLError as e:
                        errors.append(f"{code}: {e}")
                        logger.warning(f"[RAIDS] Sync of {code} failed: {e}")
                        if _paused() or not await _budget_ok(session):
                            break
                # Top parses for the specs we played lately (a few per run; see benchmarks.py)
                try:
                    from . import benchmarks
                    status['current'] = 'Fetching top-player benchmarks…'
                    await benchmarks.refresh(session, _budget_ok)
                except wcl.WCLRateLimited as e:
                    errors.append(_rate_limited(e))
                except Exception as e:
                    logger.warning(f"[RAIDS] Benchmarks skipped: {e}")
                try:  # players' realms for logs synced before they were recorded
                    await _backfill_realms(session)
                    await _backfill_zones(session)
                    await _backfill_healer_parses(session)
                    await _backfill_applied_hots(session)
                except wcl.WCLRateLimited as e:
                    errors.append(_rate_limited(e))
                except Exception as e:
                    logger.warning(f"[RAIDS] Realm backfill skipped: {e}")
                await _budget_ok(session)
                if spent_before is not None and status.get('wcl'):
                    status['last_points'] = max(0, status['wcl']['spent'] - spent_before)
        except wcl.WCLRateLimited as e:
            errors.append(_rate_limited(e))
        except wcl.WCLError as e:  # budget pause, WCL down: a warning, not a stack trace
            logger.warning(f"[RAIDS] Sync stopped: {e}")
            errors.append(str(e))
        except Exception as e:
            logger.exception("[RAIDS] Sync failed")
            errors.append(str(e))
        # Not WCL, so these run even when the sync stopped early (budget pause, WCL down):
        # mechanic clips for bosses we haven't looked up on Mythic Trap recently, and Wowhead
        # tooltip text (name, cooldown, description) for spells our pages show.
        try:
            status['current'] = 'Looking up mechanic clips on Mythic Trap…'
            from .guides import scan_missing
            await scan_missing()
        except Exception:
            logger.exception("[RAIDS] Mythic Trap scan failed")
        try:
            removed, archived = db.prune_reports()
            if removed:
                logger.info(f"[RAIDS] Removed {len(removed)} old log(s): {', '.join(removed)}")
            if archived:
                logger.info(f"[RAIDS] Archived {len(archived)} old raid night(s): {', '.join(archived)}")
        except Exception:
            logger.exception("[RAIDS] Pruning old raid logs failed")
        try:
            status['current'] = 'Refreshing the Cooldown Manager spell list…'
            from .gamedata import refresh_if_stale
            await refresh_if_stale()
        except Exception as e:
            logger.warning(f"[RAIDS] Cooldown Manager spells not refreshed: {e}")
        try:
            status['current'] = 'Looking up spell tooltips on Wowhead…'
            from .spells import fill_missing
            await fill_missing()
        except Exception:
            logger.exception("[RAIDS] Spell tooltip lookup failed")
        finally:
            _share = WCL_BUDGET_SHARE
            _note_data_version()
            status.update(running=False, current=None, last_finished=time.time(), last_new=total,
                          last_result=f"{total} new pull(s) from {reports} report(s) "
                                      f"in {time.time() - started:.0f}s",
                          last_error='; '.join(errors) or None)
        return total


BENCHMARK_BATCH = 5
REALM_BACKFILL_PER_RUN = 5


async def _backfill_realms(session):
    """Players' realms for older logs (recorded at sync since): a few per run, while the WCL budget allows."""
    for code in db.reports_missing_realms(REALM_BACKFILL_PER_RUN):
        if not await _budget_ok(session):
            return
        actors = await wcl.get_report_actors(session, code)
        db.save_realms(code, {a['name']: a.get('server') for a in actors if a.get('type') == 'Player'})


APPLIED_HOTS_PER_RUN = 6


async def _backfill_applied_hots(session):
    """
    Pulls synced before buffs put out under another name than the cast were kept (throughput.APPLIES: a Merithra's
    Blessing Evoker's Reversions): just those players' buffs-on-others table again, a few pulls per run.
    """
    from . import throughput
    for pull in db.pulls_missing_applied_hots(sorted(throughput.APPLIES), APPLIED_HOTS_PER_RUN):
        if not await _budget_ok(session):
            return
        code, fight_id, extras = pull['report_code'], pull['fight_id'], pull['extras'] or {}
        players = extras.get('players') or {}
        who = [n for n, row in players.items() if set(row.get('casts') or {}) & set(throughput.APPLIES)]
        if who:
            try:
                ids = await wcl.get_actor_ids(session, code)
                aids = [ids[n] for n in who if n in ids]
                tables = await wcl.get_player_tables(session, code, fight_id, aids, others=aids)
            except wcl.WCLRateLimited:
                raise
            except wcl.WCLError as e:
                logger.info(f"[RAIDS] Buffs on others for {code}#{fight_id} not fetched again: {e}")
                continue
            duration = extras.get('duration') or (pull['end_ms'] - pull['start_ms'])
            for n in who:
                table = (tables.get(ids.get(n)) or {}).get('on_others')
                if table is not None:
                    players[n]['on_others'] = throughput.on_others(table, duration, players[n].get('casts') or {})
        extras['applied_hots'] = True
        db.set_pull_extras(code, fight_id, extras)


HEALER_PARSES_PER_RUN = 8


async def _backfill_healer_parses(session):
    """
    Kills synced before healers' parses were fetched as healing parses (WCL's default ranks their damage):
    the healing ones, a few kills per run - archived nights too, so the character pages' history is right.
    """
    from . import throughput
    for pull in db.pulls_missing_healer_parses(HEALER_PARSES_PER_RUN):
        if not await _budget_ok(session):
            return
        try:
            ranked = await wcl.get_report_rankings(session, pull['report_code'], pull['fight_id'], ('hps',))
        except wcl.WCLError as e:
            logger.info(f"[RAIDS] Healer parses for {pull['report_code']}#{pull['fight_id']} not fetched: {e}")
            continue
        parses = throughput.parses_for_roles(pull['players'], None, ranked.get('hps'))
        db.save_healer_parses(pull['report_code'], pull['fight_id'],
                              {n: dict(v, metric='hps') for n, v in parses.items()})


async def _backfill_zones(session):
    """Raid tiers' boss order (coach.boss_weights): fetched once per tier (and weekly), a point or two each."""
    for zone_id in db.zones_missing(3):
        if not await _budget_ok(session):
            return
        try:
            ids = await wcl.get_zone_encounters(session, zone_id)
        except wcl.WCLError as e:
            logger.warning(f'[RAIDS] Boss order of zone {zone_id} failed: {e}')
            continue
        if ids:
            db.save_zone(zone_id, ids)


async def fetch_all_benchmarks(full_budget=False):
    """
    Admin "Fetch all top players" button: benchmarks for every spec / boss we played lately that has
    none (or a stale one), instead of a few per sync - then the Wowhead text for their spells. Stops
    at the WCL budget share like a sync; what's left is picked up by the next syncs (or another click).
    Returns how many spec / boss combos it fetched, or None if a sync was already running.
    """
    from . import benchmarks
    from .spells import fill_missing
    if _lock.locked():
        return None
    async with _lock:
        global _share
        _share = FULL_BUDGET_SHARE if full_budget else WCL_BUDGET_SHARE
        status.update(running=True, last_error=None, current='Fetching top players…')
        started = time.time()
        done, error, points = 0, None, None
        total = len(db.benchmarks_needed(10000, benchmarks.REFRESH_DAYS, benchmarks.DIFFICULTIES))
        try:
            async with aiohttp.ClientSession() as session:
                spent_before = status['wcl']['spent'] if await _budget_ok(session) and status.get('wcl') else None
                while True:
                    status['current'] = f'Fetching top players… {done}/{total} specs'
                    fetched = await benchmarks.refresh(session, _budget_ok, limit=BENCHMARK_BATCH)
                    done += fetched
                    if fetched < BENCHMARK_BATCH:  # nothing left, or the WCL budget said stop
                        break
                if done < total and not await _budget_ok(session):
                    error = _budget_message()
                if spent_before is not None and status.get('wcl'):
                    status['last_points'] = points = max(0, status['wcl']['spent'] - spent_before)
            status['current'] = 'Looking up spell tooltips on Wowhead…'
            while await fill_missing() >= 400:  # spells.PER_RUN at a time until none are left
                pass
        except wcl.WCLRateLimited as e:
            error = _rate_limited(e)
        except Exception as e:
            logger.exception("[RAIDS] Fetching all benchmarks failed")
            error = str(e)
        finally:
            _share = WCL_BUDGET_SHARE
            left = max(0, total - done)
            cost = (f", {points:.0f} WCL points" + (f" (~{points / done:.0f} per combo)" if done else '')
                    if points is not None else '')
            _note_data_version()
            status.update(running=False, current=None, last_finished=time.time(), last_new=0,
                          last_result=f"Top players fetched for {done} spec/boss combo(s) in "
                                      f"{time.time() - started:.0f}s{cost}"
                                      + (f" - {left} left for later syncs" if left else ''),
                          last_error=error)
        return done
