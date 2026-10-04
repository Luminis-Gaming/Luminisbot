"""
Fetches the guild's raid logs from WCL, analyzes every pull and caches the
result in raid_pulls. Pulls are immutable once logged, so each one is only
fetched once; live logs are picked up as new pulls appear.
"""
import asyncio
import logging
import time

import aiohttp

from . import analyzer, cooldowns, db, wcl

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
status = {'running': False, 'current': None, 'last_finished': None, 'last_result': None,
          'last_error': None, 'last_new': 0, 'wcl': None, 'last_points': None, 'paused_until': None}


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


async def _analyze_pull(session, code, fight, actors):
    tables = await wcl.get_fight_tables(session, code, fight['id'])

    tagged = set(db.get_tags(fight['encounterID']))
    damage_ids = analyzer.event_ability_ids(analyzer.hostile_damage_entries(tables.get('damageTaken')), tagged)
    potion_ids, defensive_ids = analyzer.consumable_ids(tables.get('casts'))

    damage_events = []
    if damage_ids:
        damage_events = await wcl.get_events(session, code, fight['id'], 'DamageTaken',
                                             f"ability.id in ({','.join(map(str, damage_ids))})")
    cooldown_meta = cooldowns.cooldown_meta(tables.get('casts'))
    consumable_events, buff_events, heal_events = [], [], []
    # ...plus everything the top players of any spec press on this boss (benchmarks.py), so a spec
    # several of us play still gets every Ebon Might / Combustion even if the raid casts it often.
    # Matched by id and by name: our log can record an ability under another spell id than theirs.
    benchmark_ids = set(db.benchmark_spell_ids(fight['encounterID']))
    benchmark_names = {info['name'] for info in db.get_spells(benchmark_ids).values() if info.get('name')}
    entries = analyzer._entries(tables.get('casts'))
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
                                  combatant_events, cooldown_meta)
    analysis['cast_ids'] = cast_ids  # which spells 'casts' is complete for (benchmarks.compare)
    # Every spell anyone in the raid cast this pull: one that isn't here was really never pressed
    # (a talent you don't take), as opposed to one we didn't fetch.
    analysis['casts_seen'] = sorted(used_ids)
    return analysis


async def sync_report(session, code, source='guild', force=False):
    """Analyze every raid pull in one report that isn't cached yet. Returns pulls analyzed."""
    status['current'] = f"Checking report {code}…"
    report = await wcl.get_report_overview(session, code)
    # Recorded even without raid pulls (Mythic+ / trash logs) so they're only checked once -
    # the pages only list reports that have pulls.
    db.upsert_report(report, _phase_names(report), source=source)
    pulls = _raid_pulls(report)
    if not pulls:
        return 0

    done = set() if force else db.analyzed_fight_ids(code, analyzer.ANALYSIS_VERSION)
    actors = (report.get('masterData') or {}).get('actors') or []

    analyzed = 0
    for number, fight in enumerate(pulls, 1):
        if fight['id'] in done:
            continue
        # A long night is dozens of requests: check the budget as we go, not only between nights.
        # What's left is picked up next sync (already analyzed pulls are skipped).
        if analyzed and analyzed % BUDGET_CHECK_EVERY == 0 and not await _budget_ok(session):
            raise wcl.WCLError(_pause_message() if _paused() else _budget_message())
        status['current'] = f"Analyzing {report.get('title') or code} — pull {number}/{len(pulls)} ({fight['name']})"
        analysis = await _analyze_pull(session, code, fight, actors)
        db.upsert_pull(code, fight, analysis)
        analyzed += 1
        logger.info(f"[RAIDS] Analyzed {code}#{fight['id']} {fight['name']} "
                    f"({'kill' if fight.get('kill') else 'wipe'})")
    return analyzed


BUDGET_CHECK_EVERY = 3  # pulls

# Raid-event logs are picked up automatically only for recent events (older nights can be
# imported by URL), a few per sync so a backlog doesn't burn the hourly WCL API budget.
EVENT_BACKLOG_PER_RUN = 5
EVENT_BACKLOG_DAYS = 21


def _budget_message():
    w = status.get('wcl') or {}
    resets = f", resets in {int((w.get('reset_in') or 0) / 60)} min" if w.get('reset_in') else ''
    return (f"Paused to stay within the WCL API budget ({w.get('spent', '?')}/{w.get('limit', '?')} points "
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
    """Refresh status['wcl'] from WCL's own counter; False once we're past our share of the hour."""
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
                listed = await wcl.list_guild_reports(session, WCL_GUILD_ID, limit=limit)
                codes = [(c, 'manual', True) for c in force_codes]
                codes += [(c, 'guild', False) for c in extra_codes if c not in force_codes]
                codes += [(r['code'], 'guild', False) for r in listed
                          if r['code'] not in force_codes and r['code'] not in extra_codes
                          and not db.report_is_final(r['code'])]
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
            status['current'] = 'Looking up spell tooltips on Wowhead…'
            from .spells import fill_missing
            await fill_missing()
        except Exception:
            logger.exception("[RAIDS] Spell tooltip lookup failed")
        finally:
            _share = WCL_BUDGET_SHARE
            status.update(running=False, current=None, last_finished=time.time(), last_new=total,
                          last_result=f"{total} new pull(s) from {reports} report(s) "
                                      f"in {time.time() - started:.0f}s",
                          last_error='; '.join(errors) or None)
        return total


BENCHMARK_BATCH = 5


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
        done, error = 0, None
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
                    status['last_points'] = max(0, status['wcl']['spent'] - spent_before)
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
            status.update(running=False, current=None, last_finished=time.time(), last_new=0,
                          last_result=f"Top players fetched for {done} spec/boss combo(s) in "
                                      f"{time.time() - started:.0f}s" + (f" - {left} left for later syncs" if left else ''),
                          last_error=error)
        return done
