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
          'last_error': None, 'last_new': 0, 'wcl': None, 'last_points': None}


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
    cast_ids = potion_ids + defensive_ids + sorted(cooldown_meta)
    if cast_ids:  # potions, healthstones and tracked cooldowns in one request
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

    return analyzer.analyze_fight(fight, actors, tables, damage_events, consumable_events,
                                  set(potion_ids), set(defensive_ids), buff_events, heal_events, enemy_cast_events,
                                  combatant_events, cooldown_meta)


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
        status['current'] = f"Analyzing {report.get('title') or code} — pull {number}/{len(pulls)} ({fight['name']})"
        analysis = await _analyze_pull(session, code, fight, actors)
        db.upsert_pull(code, fight, analysis)
        analyzed += 1
        logger.info(f"[RAIDS] Analyzed {code}#{fight['id']} {fight['name']} "
                    f"({'kill' if fight.get('kill') else 'wipe'})")
    return analyzed


# Raid-event logs are picked up automatically only for recent events (older nights can be
# imported by URL), a few per sync so a backlog doesn't burn the hourly WCL API budget.
EVENT_BACKLOG_PER_RUN = 5
EVENT_BACKLOG_DAYS = 21


def _budget_message():
    w = status.get('wcl') or {}
    resets = f", resets in {int((w.get('reset_in') or 0) / 60)} min" if w.get('reset_in') else ''
    return (f"Paused to stay within the WCL API budget ({w.get('spent', '?')}/{w.get('limit', '?')} points "
            f"used this hour{resets}) — continues on a later sync")


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


async def _budget_ok(session):
    """Refresh status['wcl'] from WCL's own counter; False once we're past our share of the hour."""
    try:
        limits = await wcl.get_rate_limit(session)
    except wcl.WCLError:
        return True  # can't tell - let the request itself report a rate limit
    spent, cap = limits.get('pointsSpentThisHour') or 0, limits.get('limitPerHour') or 3600
    status['wcl'] = {'spent': spent, 'limit': cap, 'reset_in': limits.get('pointsResetIn'),
                     'checked': time.time()}
    return spent < WCL_BUDGET_SHARE * cap


async def sync_guild(limit=10, force_codes=(), extra_codes=()):
    """
    Sync the guild's latest `limit` reports, the logs attached to raid events, extra_codes
    (e.g. a log someone asked about in Discord) and force_codes (re-analyzed from scratch).
    """
    if _lock.locked():
        return None
    async with _lock:
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
                    except wcl.WCLError as e:
                        errors.append(f"{code}: {e}")
                        logger.warning(f"[RAIDS] Sync of {code} failed: {e}")
                        if 'rate limit' in str(e):
                            break
                await _budget_ok(session)
                if spent_before is not None and status.get('wcl'):
                    status['last_points'] = max(0, status['wcl']['spent'] - spent_before)
            # Mechanic clips for any boss we haven't looked up on Mythic Trap recently.
            status['current'] = 'Looking up mechanic clips on Mythic Trap…'
            from .guides import scan_missing
            await scan_missing()
            # Wowhead tooltips (name, cooldown, description) for spells the new pulls mention.
            from .spells import fill_missing
            await fill_missing()
        except Exception as e:
            logger.exception("[RAIDS] Sync failed")
            errors.append(str(e))
        finally:
            status.update(running=False, current=None, last_finished=time.time(), last_new=total,
                          last_result=f"{total} new pull(s) from {reports} report(s) "
                                      f"in {time.time() - started:.0f}s",
                          last_error='; '.join(errors) or None)
        return total
