"""
Warcraft Logs v2 GraphQL client for raid analysis.

Uses the same client-credentials (WCL_CLIENT_ID / WCL_CLIENT_SECRET) as
wcl_api.py, but caches the token, since a sync makes dozens of calls.

Table and event payloads are the same JSON the v1 API returned; v2 just wraps
tables in {"data": {...}}. Tables cap per-target breakdowns at the top 5, so
anything that needs every player (avoidable hits, potions) goes through events.
"""
import functools
import logging
import time

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://www.warcraftlogs.com/api/v2/client"

# Difficulty IDs WCL uses for raids (LFR, Normal, Heroic, Mythic). M+ is 10.
RAID_DIFFICULTIES = {1, 3, 4, 5}

_token = None
_token_expires = 0.0


class WCLError(Exception):
    pass


class WCLServerError(WCLError):
    """WCL (or Cloudflare in front of it) answered 5xx: down for a moment, not our request's fault."""


class WCLRateLimited(WCLError):
    """WCL said 429. retry_after: seconds from its Retry-After header, when it sends one."""
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


# ============================================================================
# v1 fallback (wcl_v1.py): what v1 can answer goes there while v2 is down (5xx) - or first, with
# WCL_V1_FIRST. Not for rate limits: v1 counts against the same hourly points as v2.
# ============================================================================

V2_BLOCK_FALLBACK_SECONDS = 15 * 60  # after a 429 without a Retry-After
_v2_blocked_until = 0.0
known_guild = None  # {'name', 'server', 'region'} of our guild, from a v2 report (v1 lists reports by name)


def v2_blocked():
    return time.time() < _v2_blocked_until


def block_v2(seconds=None):
    global _v2_blocked_until
    _v2_blocked_until = max(_v2_blocked_until, time.time() + (seconds or V2_BLOCK_FALLBACK_SECONDS))


def on_v1():
    """Whether calls that v1 can answer go there right now."""
    from . import wcl_v1
    return wcl_v1.available() and (wcl_v1.first() or v2_blocked())


def _v1_fallback(fn):
    """Run fn on v1 (wcl_v1's function of the same name) while on_v1(), or when v2 answers 5xx."""
    @functools.wraps(fn)
    async def wrapper(session, *args, **kwargs):
        from . import wcl_v1
        v1 = getattr(wcl_v1, fn.__name__)
        if on_v1():
            try:
                return await v1(session, *args, **kwargs)
            except WCLRateLimited:
                if v2_blocked():
                    raise  # both are out: the sync pauses
                # v1 is out for now (wcl_v1 noted it): v2 it is
            except WCLError as e:
                if v2_blocked():
                    raise
                logger.info(f"[RAIDS] WCL v1 {fn.__name__} failed ({e}) - trying v2")
        try:
            return await fn(session, *args, **kwargs)
        except WCLServerError:
            if not wcl_v1.available():
                raise
            logger.info(f"[RAIDS] WCL v2 is down for a moment - {fn.__name__} on v1 instead")
            return await v1(session, *args, **kwargs)
    return wrapper


async def _get_token(session):
    global _token, _token_expires
    if _token and time.time() < _token_expires - 300:
        return _token

    from wcl_api import WCL_CLIENT_ID, WCL_CLIENT_SECRET
    if not WCL_CLIENT_ID or not WCL_CLIENT_SECRET:
        raise WCLError("WCL_CLIENT_ID / WCL_CLIENT_SECRET are not configured")

    async with session.post("https://www.warcraftlogs.com/oauth/token",
                            data={'grant_type': 'client_credentials'},
                            auth=aiohttp.BasicAuth(WCL_CLIENT_ID, WCL_CLIENT_SECRET)) as resp:
        if resp.status != 200:
            raise WCLError(f"WCL token request failed ({resp.status})")
        data = await resp.json()
    _token = data['access_token']
    _token_expires = time.time() + data.get('expires_in', 3600)
    return _token


async def query(session, gql, variables=None):
    """Run a GraphQL query and return its `data`, raising WCLError on failure."""
    token = await _get_token(session)
    async with session.post(API_URL, json={'query': gql, 'variables': variables or {}},
                            headers={'Authorization': f'Bearer {token}'}) as resp:
        if resp.status == 429:
            retry = resp.headers.get('Retry-After')
            raise WCLRateLimited("WCL rate limit reached - try again later",
                                 int(retry) if retry and retry.isdigit() else None)
        if resp.status >= 500:
            raise WCLServerError(f"WCL API returned {resp.status} (WCL or Cloudflare is having a moment)")
        if resp.status != 200:
            raise WCLError(f"WCL API returned {resp.status}: {(await resp.text())[:300]}")
        body = await resp.json()
    if body.get('errors'):
        raise WCLError(f"WCL GraphQL error: {body['errors'][0].get('message')}")
    return body.get('data') or {}


async def get_zone_encounters(session, zone_id):
    """A raid tier's boss encounter ids in raid order (as WCL's zone lists them - the encounter journal's)."""
    data = await query(session, """
        query($id: Int!) { worldData { zone(id: $id) { encounters { id name } } } }
    """, {'id': int(zone_id)})
    zone = (data.get('worldData') or {}).get('zone') or {}
    return [e['id'] for e in zone.get('encounters') or [] if e.get('id')]


async def get_rate_limit(session):
    data = await query(session, """
        query { rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn } }
    """)
    return data.get('rateLimitData') or {}


@_v1_fallback
async def list_guild_reports(session, guild_id, limit=10):
    data = await query(session, """
        query($guildID: Int!, $limit: Int!) {
          reportData {
            reports(guildID: $guildID, limit: $limit) {
              data { code title startTime endTime zone { id name } owner { name } }
            }
          }
        }
    """, {'guildID': guild_id, 'limit': limit})
    return ((data.get('reportData') or {}).get('reports') or {}).get('data') or []


@_v1_fallback
async def get_report_overview(session, code):
    """Report metadata, raid encounter pulls, phase names and the player roster."""
    data = await query(session, """
        query($code: String!) {
          reportData {
            report(code: $code) {
              code title startTime endTime
              zone { id name }
              owner { name }
              guild { id name server { slug region { slug } } }
              fights(killType: Encounters) {
                id encounterID name difficulty kill size
                startTime endTime
                fightPercentage bossPercentage
                lastPhase lastPhaseIsIntermission
                phaseTransitions { id startTime }
                friendlyPlayers
              }
              phases {
                encounterID
                phases { id name isIntermission }
              }
              masterData {
                actors(type: "Player") { id name subType server }
              }
            }
          }
        }
    """, {'code': code})
    report = (data.get('reportData') or {}).get('report')
    if not report:
        raise WCLError(f"Report {code} not found (private or deleted?)")
    _remember_guild(report.get('guild'))
    return report


def _remember_guild(guild):
    """Our guild's name / server / region, for listing its reports on v1 (which has no guild ids)."""
    global known_guild
    from wcl_api import WCL_GUILD_ID
    server = (guild or {}).get('server') or {}
    if guild and guild.get('id') == WCL_GUILD_ID and server.get('slug'):
        known_guild = {'name': guild.get('name'), 'server': server['slug'],
                       'region': ((server.get('region') or {}).get('slug') or '').upper()}


@_v1_fallback
async def get_fight_tables(session, code, fight_id):
    """Every aggregate table the analyzer needs for one pull, in a single request."""
    data = await query(session, """
        query($code: String!, $fights: [Int]!) {
          reportData {
            report(code: $code) {
              damageTaken: table(fightIDs: $fights, dataType: DamageTaken,
                                 hostilityType: Friendlies, viewBy: Ability)
              deaths: table(fightIDs: $fights, dataType: Deaths)
              interrupts: table(fightIDs: $fights, dataType: Interrupts)
              dispels: table(fightIDs: $fights, dataType: Dispels)
              casts: table(fightIDs: $fights, dataType: Casts,
                           hostilityType: Friendlies, viewBy: Ability)
              enemyCasts: table(fightIDs: $fights, dataType: Casts,
                                hostilityType: Enemies, viewBy: Ability)
              playerDetails(fightIDs: $fights)
            }
          }
        }
    """, {'code': code, 'fights': [fight_id]})
    report = (data.get('reportData') or {}).get('report') or {}
    # Unwrap v2's {"data": {...}} so the analyzer sees the plain v1-shaped tables.
    return {key: (value or {}).get('data', value) if isinstance(value, dict) else value
            for key, value in report.items()}


async def get_report_rankings(session, code, fight_id):
    """WCL's parses for one pull (kills only) - v2 only, for when the rest came from v1."""
    data = await query(session, """
        query($code: String!, $fights: [Int]!) {
          reportData { report(code: $code) { rankings(fightIDs: $fights) } }
        }
    """, {'code': code, 'fights': [fight_id]})
    return ((data.get('reportData') or {}).get('report') or {}).get('rankings')


_actors = {}  # report code -> {player name: actor id} (the focus view asks once per report)


@_v1_fallback
async def get_actor_ids(session, code):
    """{player name: actor id} in a report."""
    if code not in _actors:
        data = await query(session, """
            query($code: String!) { reportData { report(code: $code) { masterData { actors(type: "Player") { id name } } } } }
        """, {'code': code})
        actors = ((((data.get('reportData') or {}).get('report') or {}).get('masterData') or {}).get('actors')) or []
        _actors[code] = {a['name']: a['id'] for a in actors}
    return _actors[code]


_abilities = {}  # report code -> {game id: (name, icon)} (focus.py: buff events carry only the id)


async def get_report_abilities(session, code):
    """Every ability in a report: {game id: (name, icon file)}."""
    if code not in _abilities:
        if len(_abilities) > 200:
            _abilities.clear()
        data = await query(session, """
            query($code: String!) { reportData { report(code: $code) { masterData { abilities { gameID name icon } } } } }
        """, {'code': code})
        rows = ((((data.get('reportData') or {}).get('report') or {}).get('masterData') or {}).get('abilities')) or []
        _abilities[code] = {a['gameID']: (a.get('name') or '', a.get('icon') or '') for a in rows if a.get('gameID')}
    return _abilities[code]


_all_actors = {}  # report code -> every actor (focus.py: enemies by id, a player's pets)


async def get_report_actors(session, code):
    """Every actor in a report - players, pets, NPCs: [{'id', 'name', 'type', 'subType', 'petOwner', 'gameID',
    'server' (players' realm)}]."""
    if code not in _all_actors:
        if len(_all_actors) > 200:
            _all_actors.clear()
        data = await query(session, """
            query($code: String!) {
              reportData { report(code: $code) { masterData { actors { id name type subType petOwner gameID server } } } }
            }
        """, {'code': code})
        _all_actors[code] = ((((data.get('reportData') or {}).get('report') or {}).get('masterData') or {})
                             .get('actors')) or []
    return _all_actors[code]


@_v1_fallback
async def get_fight_extras(session, code, fight_id):
    """
    Throughput for one pull: the DamageDone / Healing tables (totals, active time and damage by target
    per player), WCL's parses (kills only - wipes are scraped, see sync.py) and the pull's bosses for
    debuff uptime: {'damageDone', 'healing', 'rankings', 'boss_ids'}.
    """
    data = await query(session, """
        query($code: String!, $fights: [Int]!) {
          reportData {
            report(code: $code) {
              damageDone: table(fightIDs: $fights, dataType: DamageDone)
              healing: table(fightIDs: $fights, dataType: Healing)
              enemyDamage: table(fightIDs: $fights, dataType: DamageTaken, hostilityType: Enemies)
              rankings(fightIDs: $fights)
            }
          }
        }
    """, {'code': code, 'fights': [fight_id]})
    report = (data.get('reportData') or {}).get('report') or {}
    return {'damageDone': _unwrap(report.get('damageDone')), 'healing': _unwrap(report.get('healing')),
            'rankings': report.get('rankings'), 'boss_ids': boss_ids(_unwrap(report.get('enemyDamage')))}


async def get_damage_by_target(session, code, fight_id, target_ids):
    """
    Everyone's damage on each of these enemies in one pull - the DamageDone table filtered to the target, so
    every player (the plain table lists only each player's top 5 targets): {target id: [table entries]}.
    """
    if not target_ids:
        return {}
    parts = '\n'.join(f't{int(i)}: table(fightIDs: $fights, dataType: DamageDone, targetID: {int(i)})' for i in target_ids)
    data = await query(session, 'query($code: String!, $fights: [Int]!) { reportData { report(code: $code) { %s } } }'
                       % parts, {'code': code, 'fights': [fight_id]})
    report = (data.get('reportData') or {}).get('report') or {}
    return {int(i): (_unwrap(report.get(f't{int(i)}')) or {}).get('entries') or [] for i in target_ids}


def _unwrap(table):
    return (table or {}).get('data', table) if isinstance(table, dict) else table


MAX_BOSSES = 3
MIN_BOSS_SHARE = 0.2  # of the most-damaged boss's damage taken: less is an add WCL also calls a boss


def boss_ids(enemy_damage_taken):
    """
    The pull's bosses, most damaged first, from the enemies' DamageTaken table - every one that took a
    real share, so councils (several bosses that all have to die) count each of them; a short-lived add
    that WCL also marks as a boss (Echo of Jawae) doesn't.
    """
    bosses = sorted((e for e in (enemy_damage_taken or {}).get('entries') or []
                     if e.get('type') == 'Boss' and e.get('id') is not None), key=lambda e: -(e.get('total') or 0))
    if not bosses:
        return []
    most = bosses[0].get('total') or 0
    return [e['id'] for e in bosses if (e.get('total') or 0) >= MIN_BOSS_SHARE * most][:MAX_BOSSES]


PLAYER_TABLES_PER_REQUEST = 5


@_v1_fallback
async def get_player_tables(session, code, fight_id, actor_ids, bosses=(), casts=False, others=(), targets=False):
    """
    Per player: the buffs they gave themselves, their debuffs on each boss, with casts=True their Casts
    table (names + counts), and for the ids in others (healers) the buffs they put on anyone - HoTs like
    Renewing Mist - and with targets=True their damage by target (the top players' focus) - a few players
    per request: {actor id: {'buffs', 'debuffs': [one table per boss], 'casts', 'on_others', 'targets'}}
    (v1-shaped tables, None when not asked).
    """
    if not actor_ids:
        return {}
    if len(actor_ids) > PLAYER_TABLES_PER_REQUEST:  # keep each query small: a raid is a handful of requests
        out = {}
        for i in range(0, len(actor_ids), PLAYER_TABLES_PER_REQUEST):
            out.update(await get_player_tables(session, code, fight_id, actor_ids[i:i + PLAYER_TABLES_PER_REQUEST],
                                               bosses, casts, others, targets))
        return out
    parts = []
    for aid in actor_ids:
        aid = int(aid)
        parts.append(f'b{aid}: table(fightIDs: $fights, dataType: Buffs, sourceID: {aid}, targetID: {aid})')
        for k, boss in enumerate(bosses):
            parts.append(f'd{aid}_{k}: table(fightIDs: $fights, dataType: Debuffs, hostilityType: Enemies, '
                         f'sourceID: {aid}, targetID: {int(boss)})')
        if casts:
            parts.append(f'c{aid}: table(fightIDs: $fights, dataType: Casts, sourceID: {aid})')
        if aid in {int(o) for o in others}:
            parts.append(f'o{aid}: table(fightIDs: $fights, dataType: Buffs, sourceID: {aid})')
        if targets:
            parts.append(f't{aid}: table(fightIDs: $fights, dataType: DamageDone, viewBy: Target, sourceID: {aid})')
    data = await query(session, """
        query($code: String!, $fights: [Int]!) {
          reportData { report(code: $code) { %s } }
        }
    """ % '\n'.join(parts), {'code': code, 'fights': [fight_id]})
    report = (data.get('reportData') or {}).get('report') or {}
    return {int(aid): {'buffs': _unwrap(report.get(f'b{int(aid)}')),
                       'debuffs': [_unwrap(report.get(f'd{int(aid)}_{k}')) for k in range(len(bosses))],
                       'casts': _unwrap(report.get(f'c{int(aid)}')),
                       'on_others': _unwrap(report.get(f'o{int(aid)}')),
                       'targets': _unwrap(report.get(f't{int(aid)}'))}
            for aid in actor_ids}


PAGE_END = 1e13  # "until the end": a later page's endTime (the fight ids bound it)


@_v1_fallback
async def get_events(session, code, fight_id, data_type, filter_expression, max_events=20000,
                     hostility='Friendlies'):
    """All events matching filter_expression in one pull, following pagination."""
    events = []
    start = None
    while True:
        variables = {'code': code, 'fights': [fight_id], 'dataType': data_type,
                     'filter': filter_expression, 'hostility': hostility}
        start_arg = ''
        if start is not None:
            # Both ends: with only a startTime WCL answers the next page with nothing at all (the fight ids
            # still bound it), so every request used to stop at its first 10,000 events.
            variables.update(start=start, end=PAGE_END)
            start_arg = ', startTime: $start, endTime: $end'
        data = await query(session, f"""
            query($code: String!, $fights: [Int]!, $dataType: EventDataType!, $hostility: HostilityType!,
                  $filter: String{', $start: Float, $end: Float' if start is not None else ''}) {{
              reportData {{
                report(code: $code) {{
                  events(fightIDs: $fights, dataType: $dataType, hostilityType: $hostility,
                         filterExpression: $filter, limit: 10000{start_arg}) {{
                    data
                    nextPageTimestamp
                  }}
                }}
              }}
            }}
        """, variables)
        page = (((data.get('reportData') or {}).get('report') or {}).get('events')) or {}
        events.extend(page.get('data') or [])
        start = page.get('nextPageTimestamp')
        if not start or len(events) >= max_events:
            if start:
                logger.warning(f"[RAIDS] Event cap hit for {code}#{fight_id} ({filter_expression[:60]})")
            return events


@_v1_fallback
async def get_character_rankings(session, encounter_id, difficulty, class_name, spec_name, metric='dps'):
    """
    The best parses of one spec on one boss (WCL's global character rankings, page 1), best first:
    [{'name', 'amount', 'duration', 'report': {'code', 'fightID'}, 'server', 'guild', ...}].
    class_name / spec_name are WCL slugs, e.g. 'DeathKnight' / 'Frost', 'Hunter' / 'BeastMastery'.
    """
    data = await query(session, """
        query($id: Int!, $cls: String!, $spec: String!, $diff: Int!, $metric: CharacterRankingMetricType!) {
          worldData {
            encounter(id: $id) {
              characterRankings(className: $cls, specName: $spec, difficulty: $diff, metric: $metric, page: 1)
            }
          }
        }
    """, {'id': encounter_id, 'cls': class_name, 'spec': spec_name, 'diff': difficulty, 'metric': metric})
    rankings = (((data.get('worldData') or {}).get('encounter') or {}).get('characterRankings')) or {}
    return rankings.get('rankings') or []


@_v1_fallback
async def get_player_fight(session, code, fight_id, name):
    """
    One player's casts in someone else's logged kill, plus that fight's timing and the spec they
    played in it: {'start', 'end', 'phases': [{'id', 'start'}] (ms into the fight), 'casts': [events],
    'spec': 'Devourer' or None}.
    """
    data = await query(session, """
        query($code: String!, $fights: [Int]!, $filter: String!) {
          reportData {
            report(code: $code) {
              fights(fightIDs: $fights) { id startTime endTime phaseTransitions { id startTime } }
              events(fightIDs: $fights, dataType: Casts, filterExpression: $filter, limit: 10000) { data }
              playerDetails(fightIDs: $fights)
              enemyDamage: table(fightIDs: $fights, dataType: DamageTaken, hostilityType: Enemies)
            }
          }
        }
    """, {'code': code, 'fights': [fight_id], 'filter': f'source.name = "{name}"'})
    report = (data.get('reportData') or {}).get('report') or {}
    fight = next(iter(report.get('fights') or []), None)
    if not fight:
        raise WCLError(f"Fight {code}#{fight_id} not found")
    start = fight['startTime']
    entry = _details_entry(report.get('playerDetails'), name) or {}
    return {'start': start, 'end': fight['endTime'],
            'phases': [{'id': p['id'], 'start': p['startTime'] - start} for p in fight.get('phaseTransitions') or []],
            'casts': ((report.get('events') or {}).get('data')) or [],
            'spec': _spec_in_details(report.get('playerDetails'), name),
            'actor_id': entry.get('id'), 'boss_ids': boss_ids(_unwrap(report.get('enemyDamage')))}


def _details_entry(player_details, name):
    details = (player_details or {}).get('data', player_details) or {}
    details = details.get('playerDetails', details) or {}
    for role in ('tanks', 'healers', 'dps'):
        for entry in details.get(role) or []:
            if entry.get('name') == name:
                return entry
    return None


def _spec_in_details(player_details, name):
    """The spec a player had in a fight, from its playerDetails ('DemonHunter-Devourer' icon or specs list)."""
    details = (player_details or {}).get('data', player_details) or {}
    details = details.get('playerDetails', details) or {}
    for role in ('tanks', 'healers', 'dps'):
        for entry in details.get(role) or []:
            if entry.get('name') != name:
                continue
            icon = entry.get('icon') or ''
            if '-' in icon:
                return icon.split('-', 1)[1]
            specs = entry.get('specs') or []
            if specs:
                first = specs[0]
                return first.get('spec') if isinstance(first, dict) else first
    return None
