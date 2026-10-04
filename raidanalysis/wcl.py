"""
Warcraft Logs v2 GraphQL client for raid analysis.

Uses the same client-credentials (WCL_CLIENT_ID / WCL_CLIENT_SECRET) as
wcl_api.py, but caches the token, since a sync makes dozens of calls.

Table and event payloads are the same JSON the v1 API returned; v2 just wraps
tables in {"data": {...}}. Tables cap per-target breakdowns at the top 5, so
anything that needs every player (avoidable hits, potions) goes through events.
"""
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


class WCLRateLimited(WCLError):
    """WCL said 429. retry_after: seconds from its Retry-After header, when it sends one."""
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


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
        if resp.status != 200:
            raise WCLError(f"WCL API returned {resp.status}: {(await resp.text())[:300]}")
        body = await resp.json()
    if body.get('errors'):
        raise WCLError(f"WCL GraphQL error: {body['errors'][0].get('message')}")
    return body.get('data') or {}


async def get_rate_limit(session):
    data = await query(session, """
        query { rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn } }
    """)
    return data.get('rateLimitData') or {}


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
    return report


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
            variables['start'] = start
            start_arg = ', startTime: $start'
        data = await query(session, f"""
            query($code: String!, $fights: [Int]!, $dataType: EventDataType!, $hostility: HostilityType!,
                  $filter: String{', $start: Float' if start is not None else ''}) {{
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
            }
          }
        }
    """, {'code': code, 'fights': [fight_id], 'filter': f'source.name = "{name}"'})
    report = (data.get('reportData') or {}).get('report') or {}
    fight = next(iter(report.get('fights') or []), None)
    if not fight:
        raise WCLError(f"Fight {code}#{fight_id} not found")
    start = fight['startTime']
    return {'start': start, 'end': fight['endTime'],
            'phases': [{'id': p['id'], 'start': p['startTime'] - start} for p in fight.get('phaseTransitions') or []],
            'casts': ((report.get('events') or {}).get('data')) or [],
            'spec': _spec_in_details(report.get('playerDetails'), name)}


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
