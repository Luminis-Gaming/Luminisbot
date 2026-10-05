"""
Warcraft Logs' v1 REST API as a stand-in for the v2 GraphQL calls in wcl.py.

v1 answers what it can when v2 itself is down (5xx: Cloudflare 502s) - or first, with WCL_V1_FIRST=1.
It's no way around the budget: v1's 800 requests / minute is only a burst limit, its calls count against
the same hourly points as v2 (a v1 429 comes with v2's reset time). Every
function has the same signature as its wcl.py namesake and returns the same shapes: v2's tables and
events *are* v1's JSON, so mostly it's fetching per fight window instead of per fight id.

v1 can't do: the rate-limit counter and WCL's parses for a report (sync.py asks v2 for a kill's
parses on its own - one small request; wipes are scraped from the website anyway). It's a legacy API: if WCL turns it off, calls
fail and the sync simply waits for v2 again.

Needs WCL_V1_API_KEY (the "V1 Client Key" on warcraftlogs.com/profile).
"""
import logging
import os
import time

from . import wcl

logger = logging.getLogger(__name__)

BASE = 'https://www.warcraftlogs.com/v1'
PAGE_SIZE = 10000  # v1 events come in pages up to this size, like v2

_blocked_until = 0.0
_fights = {}       # report code -> its /report/fights answer (a sync asks for the same report many times)
_FIGHTS_KEEP = 20
_classes = None    # /classes, for the rankings' numeric class / spec ids
remaining = None   # requests left in v1's current window (from its headers)

PLAYER_CLASSES = {'DeathKnight', 'DemonHunter', 'Druid', 'Evoker', 'Hunter', 'Mage', 'Monk', 'Paladin', 'Priest',
                  'Rogue', 'Shaman', 'Warlock', 'Warrior'}
EVENT_VIEWS = {'Casts': 'casts', 'Buffs': 'buffs', 'Debuffs': 'debuffs', 'DamageTaken': 'damage-taken',
               'DamageDone': 'damage-done', 'Healing': 'healing', 'Deaths': 'deaths'}


def api_key():
    return (os.getenv('WCL_V1_API_KEY') or os.getenv('WCL_API_KEY') or os.getenv('WCL_V1_KEY') or '').strip()


def available():
    """Configured, and not rate limited right now."""
    return bool(api_key()) and time.time() >= _blocked_until


def first():
    """
    Use v1 before v2 for what it can answer (WCL_V1_FIRST=1; off by default). Not a way around the
    budget: v1's 800 / minute is only a burst limit - its calls count against the same hourly points as
    v2 (a v1 429 came with v2's reset time) - so v1 mostly helps when v2 itself is down (502s).
    """
    return bool(api_key()) and (os.getenv('WCL_V1_FIRST') or '').strip().lower() in ('1', 'true', 'yes')


def block(seconds):
    global _blocked_until
    _blocked_until = time.time() + max(60, seconds or 0)


async def _get(session, path, **params):
    global remaining
    params = {k: v for k, v in params.items() if v is not None}
    params.update(api_key=api_key(), translate='true')
    async with session.get(f'{BASE}/{path}', params=params) as resp:
        if resp.headers.get('x-ratelimit-remaining', '').isdigit():
            remaining = int(resp.headers['x-ratelimit-remaining'])
        if resp.status == 429:
            retry = resp.headers.get('Retry-After')
            wait = int(retry) if retry and retry.isdigit() else 60
            block(wait)
            raise wcl.WCLRateLimited('WCL v1 rate limit reached', wait)
        if resp.status >= 500:
            raise wcl.WCLServerError(f'WCL v1 returned {resp.status} (WCL or Cloudflare is having a moment)')
        if resp.status != 200:
            body = (await resp.text())[:300]
            raise wcl.WCLError(f'WCL v1 returned {resp.status}: {body}')
        return await resp.json(content_type=None)


def _no_space(name):
    return (name or '').replace(' ', '')


# ============================================================================
# Reports and fights
# ============================================================================

async def _report_fights(session, code):
    if code not in _fights:
        if len(_fights) >= _FIGHTS_KEEP:
            _fights.clear()
        _fights[code] = await _get(session, f'report/fights/{code}')
    return _fights[code]


async def _window(session, code, fight_id):
    """(start, end) of a fight in report time - v1 asks for a time window, not a fight id."""
    for f in (await _report_fights(session, code)).get('fights') or []:
        if f.get('id') == fight_id:
            return f['start_time'], f['end_time']
    raise wcl.WCLError(f'Fight {code}#{fight_id} not found')


def _players(report):
    return [a for a in report.get('friendlies') or [] if a.get('type') in PLAYER_CLASSES]


def overview(report, code):
    """v1 /report/fights -> wcl.get_report_overview()'s v2 shape."""
    phase_sets = {p.get('boss'): p for p in report.get('phases') or []}
    players = _players(report)
    fights, zone = [], None
    for f in report.get('fights') or []:
        if not f.get('boss'):
            continue  # trash: v2 asked for encounters only
        zone = zone or {'id': f.get('zoneID'), 'name': f.get('zoneName')}
        intermissions = set((phase_sets.get(f['boss']) or {}).get('intermissions') or [])
        last = f.get('lastPhaseForPercentageDisplay')
        fights.append({
            'id': f['id'], 'encounterID': f['boss'], 'name': f.get('name'), 'difficulty': f.get('difficulty'),
            'kill': bool(f.get('kill')), 'size': f.get('size'), 'startTime': f['start_time'], 'endTime': f['end_time'],
            # v1 has hundredths of a percent; v2 plain percentages
            'fightPercentage': f['fightPercentage'] / 100 if f.get('fightPercentage') is not None else None,
            'bossPercentage': f['bossPercentage'] / 100 if f.get('bossPercentage') is not None else None,
            'lastPhase': last, 'lastPhaseIsIntermission': last in intermissions,
            'phaseTransitions': [{'id': p['id'], 'startTime': p['startTime']} for p in f.get('phases') or []],
            'friendlyPlayers': [a['id'] for a in players if any(x.get('id') == f['id'] for x in a.get('fights') or [])],
        })
    phases = [{'encounterID': boss, 'phases': [{'id': i + 1, 'name': name, 'isIntermission': i + 1 in
                                                set(p.get('intermissions') or [])}
                                               for i, name in enumerate(p.get('phases') or [])]}
              for boss, p in phase_sets.items()]
    return {'code': code, 'title': report.get('title') or code, 'startTime': report.get('start'),
            'endTime': report.get('end'), 'zone': zone, 'owner': {'name': report.get('owner')}, 'guild': None,
            'fights': fights, 'phases': phases,
            'masterData': {'actors': [{'id': a['id'], 'name': a['name'], 'subType': a['type'], 'server': a.get('server')}
                                      for a in players]}}


async def get_report_overview(session, code):
    _fights.pop(code, None)  # a live log grows: always fresh here
    return overview(await _report_fights(session, code), code)


async def list_guild_reports(session, guild_id, limit=10):
    """Needs the guild's name / server / region (v1 has no guild ids): learned from v2, or WCL_GUILD_* settings."""
    guild = wcl.known_guild or {}
    name = os.getenv('WCL_GUILD_NAME') or guild.get('name')
    server = os.getenv('WCL_GUILD_SERVER') or guild.get('server')
    region = os.getenv('WCL_GUILD_REGION') or guild.get('region')
    if not (name and server and region):
        raise wcl.WCLError('WCL v1 needs the guild name / server / region (WCL_GUILD_NAME, _SERVER, _REGION)')
    reports = await _get(session, f'reports/guild/{name}/{server}/{region}')
    reports = sorted(reports or [], key=lambda r: -(r.get('start') or 0))[:limit]
    return [{'code': r['id'], 'title': r.get('title'), 'startTime': r.get('start'), 'endTime': r.get('end'),
             'zone': {'id': r.get('zone')}, 'owner': {'name': r.get('owner')}} for r in reports]


async def get_actor_ids(session, code):
    return {a['name']: a['id'] for a in _players(await _report_fights(session, code))}


# ============================================================================
# Tables and events
# ============================================================================

async def _table(session, code, view, start, end, **params):
    return await _get(session, f'report/tables/{view}/{code}', start=start, end=end, **params)


async def get_fight_tables(session, code, fight_id):
    start, end = await _window(session, code, fight_id)
    summary = await _table(session, code, 'summary', start, end)
    return {'damageTaken': await _table(session, code, 'damage-taken', start, end, by='ability'),
            'deaths': await _table(session, code, 'deaths', start, end),
            'interrupts': await _table(session, code, 'interrupts', start, end),
            'dispels': await _table(session, code, 'dispels', start, end),
            'casts': await _table(session, code, 'casts', start, end, by='ability'),
            'enemyCasts': await _table(session, code, 'casts', start, end, by='ability', hostility=1),
            'playerDetails': {'playerDetails': summary.get('playerDetails') or {}}}


async def _events(session, code, start, end, view, filter_expression, max_events, hostility=None):
    events = []
    while start is not None:
        page = await _get(session, f'report/events/{view}/{code}', start=start, end=end, filter=filter_expression,
                          hostility=hostility)
        events.extend(page.get('events') or [])
        start = page.get('nextPageTimestamp')
        if len(events) >= max_events:
            if start:
                logger.warning(f'[RAIDS] Event cap hit for {code} (v1, {(filter_expression or "")[:60]})')
            break
    return events


async def get_events(session, code, fight_id, data_type, filter_expression, max_events=20000,
                     hostility='Friendlies'):
    start, end = await _window(session, code, fight_id)
    # Resources, CombatantInfo, All: the summary view, narrowed by the filter (which names the type)
    view = EVENT_VIEWS.get(data_type, 'summary')
    return await _events(session, code, start, end, view, filter_expression, max_events,
                         1 if hostility == 'Enemies' else None)


async def get_fight_extras(session, code, fight_id):
    start, end = await _window(session, code, fight_id)
    return {'damageDone': await _table(session, code, 'damage-done', start, end),
            'healing': await _table(session, code, 'healing', start, end),
            'rankings': None,  # v1 can't say: kills go without a parse this time
            'boss_ids': wcl.boss_ids(await _table(session, code, 'damage-taken', start, end, hostility=1))}


async def get_player_tables(session, code, fight_id, actor_ids, bosses=(), casts=False, others=(), targets=False):
    start, end = await _window(session, code, fight_id)
    others = {int(o) for o in others}
    out = {}
    for aid in actor_ids:
        aid = int(aid)
        out[aid] = {'buffs': await _table(session, code, 'buffs', start, end, sourceid=aid, targetid=aid),
                    'debuffs': [await _table(session, code, 'debuffs', start, end, sourceid=aid, targetid=int(b),
                                             hostility=1) for b in bosses],
                    'casts': await _table(session, code, 'casts', start, end, sourceid=aid) if casts else None,
                    'on_others': (await _table(session, code, 'buffs', start, end, sourceid=aid)
                                  if aid in others else None),
                    'targets': (await _table(session, code, 'damage-done', start, end, sourceid=aid, by='target')
                                if targets else None)}
    return out


# ============================================================================
# Top players (benchmarks.py)
# ============================================================================

async def _class_ids(session, class_name, spec_name):
    global _classes
    if _classes is None:
        _classes = await _get(session, 'classes')
    for c in _classes or []:
        if _no_space(c.get('name')) == _no_space(class_name):
            for s in c.get('specs') or []:
                if _no_space(s.get('name')) == _no_space(spec_name):
                    return c['id'], s['id']
    raise wcl.WCLError(f'WCL v1 has no class / spec {class_name} {spec_name}')


async def get_character_rankings(session, encounter_id, difficulty, class_name, spec_name, metric='dps'):
    """v1-style flat rankings (name, reportID, fightID, total...) - benchmarks._ranking_fields reads both shapes."""
    class_id, spec_id = await _class_ids(session, class_name, spec_name)
    data = await _get(session, f'rankings/encounter/{int(encounter_id)}', metric=metric, difficulty=difficulty,
                      **{'class': class_id, 'spec': spec_id, 'page': 1})
    return (data or {}).get('rankings') or []


async def get_player_fight(session, code, fight_id, name):
    report = await _report_fights(session, code)
    fight = next((f for f in report.get('fights') or [] if f.get('id') == fight_id), None)
    if not fight:
        raise wcl.WCLError(f'Fight {code}#{fight_id} not found')
    start, end = fight['start_time'], fight['end_time']
    safe = name.replace('"', '')
    casts = await _events(session, code, start, end, 'casts', f'source.name = "{safe}"', PAGE_SIZE)
    details = (await _table(session, code, 'summary', start, end)).get('playerDetails') or {}
    entry = wcl._details_entry({'playerDetails': details}, name) or {}
    return {'start': start, 'end': end,
            'phases': [{'id': p['id'], 'start': p['startTime'] - start} for p in fight.get('phases') or []],
            'casts': casts, 'spec': wcl._spec_in_details({'playerDetails': details}, name),
            'actor_id': entry.get('id'),
            'boss_ids': wcl.boss_ids(await _table(session, code, 'damage-taken', start, end, hostility=1))}
