"""
Fetches the guild's raid logs from WCL, analyzes every pull and caches the
result in raid_pulls. Pulls are immutable once logged, so each one is only
fetched once; live logs are picked up as new pulls appear.
"""
import asyncio
import logging
import time

import aiohttp

from . import analyzer, db, wcl

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
status = {'running': False, 'last_finished': None, 'last_result': None, 'last_error': None}


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
    consumable_events = []
    if potion_ids or defensive_ids:
        consumable_events = await wcl.get_events(session, code, fight['id'], 'Casts',
                                                 f"ability.id in ({','.join(map(str, potion_ids + defensive_ids))})")

    return analyzer.analyze_fight(fight, actors, tables, damage_events, consumable_events,
                                  set(potion_ids), set(defensive_ids))


async def sync_report(session, code, source='guild', force=False):
    """Analyze every raid pull in one report that isn't cached yet. Returns pulls analyzed."""
    report = await wcl.get_report_overview(session, code)
    pulls = _raid_pulls(report)
    if not pulls:
        return 0  # Mythic+ / trash-only log - not ours to track

    db.upsert_report(report, _phase_names(report), source=source)
    done = set() if force else db.analyzed_fight_ids(code, analyzer.ANALYSIS_VERSION)
    actors = (report.get('masterData') or {}).get('actors') or []

    analyzed = 0
    for fight in pulls:
        if fight['id'] in done:
            continue
        analysis = await _analyze_pull(session, code, fight, actors)
        db.upsert_pull(code, fight, analysis)
        analyzed += 1
        logger.info(f"[RAIDS] Analyzed {code}#{fight['id']} {fight['name']} "
                    f"({'kill' if fight.get('kill') else 'wipe'})")
    return analyzed


async def sync_guild(limit=10, force_codes=()):
    """Sync the guild's latest `limit` reports plus any explicitly requested codes."""
    if _lock.locked():
        return None
    async with _lock:
        status.update(running=True, last_error=None)
        started = time.time()
        total, reports, errors = 0, 0, []
        try:
            from wcl_api import WCL_GUILD_ID
            async with aiohttp.ClientSession() as session:
                listed = await wcl.list_guild_reports(session, WCL_GUILD_ID, limit=limit)
                codes = [(r['code'], 'guild', False) for r in listed]
                codes += [(c, 'manual', True) for c in force_codes]
                for code, source, force in codes:
                    try:
                        count = await sync_report(session, code, source=source, force=force)
                        total += count
                        reports += 1 if count else 0
                    except wcl.WCLError as e:
                        errors.append(f"{code}: {e}")
                        logger.warning(f"[RAIDS] Sync of {code} failed: {e}")
                        if 'rate limit' in str(e):
                            break
            # Mechanic clips for any boss we haven't looked up on Mythic Trap recently.
            from .guides import scan_missing
            await scan_missing()
        except Exception as e:
            logger.exception("[RAIDS] Sync failed")
            errors.append(str(e))
        finally:
            status.update(running=False, last_finished=time.time(),
                          last_result=f"{total} new pull(s) from {reports} report(s) "
                                      f"in {time.time() - started:.0f}s",
                          last_error='; '.join(errors) or None)
        return total
