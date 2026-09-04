# wcl_api.py
# Warcraft Logs API functions

import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()
WCL_CLIENT_ID = os.getenv('WCL_CLIENT_ID')
WCL_CLIENT_SECRET = os.getenv('WCL_CLIENT_SECRET')
WCL_GUILD_ID = 771376  # Example Guild ID

async def get_wcl_token(session):
    """Get an OAuth token for WCL API access."""
    print("[DEBUG] WCL: Requesting new API token.")
    url = "https://www.warcraftlogs.com/oauth/token"
    data = {'grant_type': 'client_credentials'}
    auth = aiohttp.BasicAuth(WCL_CLIENT_ID, WCL_CLIENT_SECRET)
    try:
        async with session.post(url, data=data, auth=auth) as response:
            response.raise_for_status()
            print("[DEBUG] WCL: API token received successfully.")
            return (await response.json())['access_token']
    except aiohttp.ClientError as e:
        print(f"[ERROR] WCL: Failed to get token. Status: {e}")
        return None

async def get_latest_log(session, token):
    """Get the latest log for the configured guild."""
    print("[DEBUG] WCL: Fetching latest log for guild.")
    query = """
    query($guildID: Int!) {
        reportData {
            reports(guildID: $guildID, limit: 1) {
                data {
                    code,
                    title,
                    startTime,
                    owner { name }
                }
            }
        }
    }
    """
    variables = {'guildID': WCL_GUILD_ID}
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"
    async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as resp:
        if resp.status == 200:
            reports_data = (await resp.json()).get('data', {}).get('reportData', {}).get('reports', {}).get('data', [])
            return reports_data[0] if reports_data else None
        return None

async def get_latest_logs(session, token, limit=5):
    """Get the N most recent logs for the configured guild."""
    print(f"[DEBUG] WCL: Fetching latest {limit} logs for guild.")
    query = """
    query($guildID: Int!, $limit: Int!) {
        reportData {
            reports(guildID: $guildID, limit: $limit) {
                data {
                    code,
                    title,
                    startTime,
                    owner { name }
                }
            }
        }
    }
    """
    variables = {'guildID': WCL_GUILD_ID, 'limit': limit}
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"
    async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as resp:
        if resp.status == 200:
            reports_data = (await resp.json()).get('data', {}).get('reportData', {}).get('reports', {}).get('data', [])
            return reports_data
        return []

async def get_fights_from_report(session, token, report_code):
    """Get all boss fights from a report."""
    print(f"[DEBUG] WCL: Fetching fights for report: {report_code}")
    query = """
    query($reportCode: String!) {
        reportData {
            report(code: $reportCode) {
                fights(killType: Encounters) {
                    id, name, kill, startTime, endTime, encounterID, difficulty
                }
            }
        }
    }
    """
    variables = {"reportCode": report_code}
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"
    async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as response:
        if response.status == 200:
            data = await response.json()
            return data.get('data', {}).get('reportData', {}).get('report', {}).get('fights', [])
        return []

async def get_fight_details_with_compare_type(session, token, report_code, fight_id, encounter_id, difficulty, metric, compare_type="Rankings"):
    """Get basic fight details including table data and player information."""
    print(f"[DEBUG] WCL: Fetching basic fight details for report: {report_code}, fight ID: {fight_id}, metric: {metric}")
    table_data_type = "DamageDone" if metric == "dps" else "Healing"
    
    # WCL's ReportRankingMetricType enum uses the same short names we use internally.
    player_metric = "dps" if metric == "dps" else "hps"

    query = """
    query($reportCode: String!, $fightIDs: [Int]!, $tableDataType: TableDataType!, $playerMetric: ReportRankingMetricType!) {
      reportData {
        report(code: $reportCode) {
          table(fightIDs: $fightIDs, dataType: $tableDataType)
          rankings(fightIDs: $fightIDs, playerMetric: $playerMetric)
          fights(fightIDs: $fightIDs) {
            id, startTime, endTime, friendlyPlayers
          }
          playerDetails(fightIDs: $fightIDs, includeCombatantInfo: true)
          masterData {
            actors(type: "Player") {
              id
              name
              type
              subType
            }
          }
        }
      }
    }
    """
    variables = {
        "reportCode": report_code,
        "fightIDs": [fight_id],
        "tableDataType": table_data_type,
        "playerMetric": player_metric
    }
    
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"
    
    async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as response:
        if response.status == 200:
            data = await response.json()
            if 'errors' in data:
                print(f"[ERROR] WCL API returned GraphQL errors: {data['errors']}")
                return None
            
            result = data.get('data', {}).get('reportData', {}).get('report', {})
            print(f"[DEBUG] Basic fight details retrieved successfully for {metric}")

            rankings = result.get('rankings') if isinstance(result, dict) else None
            ranked_fights = rankings.get('data') if isinstance(rankings, dict) else None
            print(f"[DEBUG] Rankings from GraphQL: {len(ranked_fights) if isinstance(ranked_fights, list) else 0} entries")
            
            # Check if we have table data
            if 'table' in result:
                table = result['table']
                if isinstance(table, dict) and 'data' in table:
                    table_data = table['data']
                    if isinstance(table_data, dict) and 'entries' in table_data:
                        entries = table_data['entries']
            
            return result
        else:
            response_text = await response.text()
            print(f"[ERROR] WCL API returned non-200 status {response.status}: {response_text}")
            return None

async def get_fight_details(session, token, report_code, fight_id, encounter_id, difficulty, metric, is_kill=False):
    """Get complete fight details including web scraped parse data."""
    print(f"[DEBUG] WCL: Fetching fight details for report: {report_code}, fight ID: {fight_id}, metric: {metric}")
    
    # Import here to avoid circular import
    from wcl_web_scraper import scrape_wcl_web_data
    
    # Get basic fight data from GraphQL (table, playerDetails, etc.)
    fight_details = await get_fight_details_with_compare_type(session, token, report_code, fight_id, encounter_id, difficulty, metric)
    
    if not fight_details:
        print(f"[DEBUG] Failed to get basic fight details from GraphQL API")
        return None

    # The GraphQL `rankings` field is the primary source for parse/ilvl percentiles.
    # Only fall back to HTML scraping when it gave us nothing for a kill; wipes are
    # never ranked, so scraping them just burns requests.
    rankings = fight_details.get('rankings')
    ranked_fights = rankings.get('data') if isinstance(rankings, dict) else rankings
    if ranked_fights:
        return fight_details

    if not is_kill:
        print("[DEBUG] No rankings for this fight (wipe) - skipping HTML scrape fallback")
        return fight_details

    fights_data = fight_details.get('fights', [])
    fight_info = None
    for fight in fights_data:
        if fight.get('id') == fight_id:
            fight_info = fight
            break

    if fight_info and encounter_id:
        start_time = fight_info.get('startTime')
        end_time = fight_info.get('endTime')

        if start_time and end_time:
            # Attempt web scraping
            scraped_data = await scrape_wcl_web_data(session, report_code, fight_id, start_time, end_time, encounter_id, metric)

            if scraped_data:
                # Inject the scraped data into the fight_details structure
                fight_details['scraped_parses'] = scraped_data

    return fight_details


async def get_all_boss_health_for_report(session, token, report_code):
    """
    Get boss health percentages for every wipe in a report via the GraphQL API.
    Returns a dictionary mapping fight_id -> boss_health_percentage.
    """
    print(f"[DEBUG] WCL: Fetching boss health for all fights in report: {report_code}")
    query = """
    query($reportCode: String!) {
        reportData {
            report(code: $reportCode) {
                fights(killType: Encounters) {
                    id, kill, bossPercentage, fightPercentage
                }
            }
        }
    }
    """
    variables = {"reportCode": report_code}
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"

    try:
        async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as response:
            if response.status != 200:
                print(f"[ERROR] Boss health query failed with status {response.status}")
                return {}

            data = await response.json()
            if 'errors' in data:
                print(f"[ERROR] Boss health query returned GraphQL errors: {data['errors']}")
                return {}

            fights = data.get('data', {}).get('reportData', {}).get('report', {}).get('fights', []) or []

            boss_health_data = {}
            for fight in fights:
                fight_id = fight.get('id')
                raw = fight.get('bossPercentage')
                if fight.get('kill') or fight_id is None or raw is None:
                    continue
                # WCL has returned this both as a plain percentage and as hundredths
                # (e.g. 8544 for 85.44%) depending on the endpoint - normalise both.
                boss_health_data[fight_id] = raw / 100 if raw > 100 else raw

            print(f"[DEBUG] Successfully extracted boss health data for {len(boss_health_data)} wipes")
            return boss_health_data

    except Exception as e:
        print(f"[ERROR] Exception fetching boss health: {e}")
        return {}


async def get_boss_health_for_wipe(session, token, report_code, fight_id, boss_health_cache=None):
    """
    Get the boss health percentage for a single wipe, using boss_health_cache when available.
    """
    if boss_health_cache:
        boss_health_percentage = boss_health_cache.get(fight_id)
        if boss_health_percentage is not None:
            print(f"[DEBUG] Got boss health from cache: {boss_health_percentage:.2f}%")
            return boss_health_percentage

    all_boss_health = await get_all_boss_health_for_report(session, token, report_code)
    boss_health_percentage = all_boss_health.get(fight_id)

    if boss_health_percentage is not None:
        print(f"[DEBUG] Successfully got boss health from GraphQL: {boss_health_percentage:.2f}%")
    else:
        print("[DEBUG] No boss health found for this fight")
    return boss_health_percentage

async def get_deaths_for_fight(session, token, report_code, fight_id):
    """Get death events for a specific fight."""
    print(f"[DEBUG] WCL: Fetching deaths for report: {report_code}, fight ID: {fight_id}")
    
    # First, try the standard Deaths query
    query = """
    query($reportCode: String!, $fightIDs: [Int]!) {
        reportData {
            report(code: $reportCode) {
                events(fightIDs: $fightIDs, dataType: Deaths, startTime: 0, endTime: 99999999999) {
                    data
                }
                fights(fightIDs: $fightIDs) {
                    friendlyPlayers
                    startTime
                    endTime
                }
                masterData {
                    actors(type: "Player") {
                        id
                        name
                        type
                    }
                    abilities {
                        gameID
                        name
                    }
                }
            }
        }
    }
    """
    variables = {"reportCode": report_code, "fightIDs": [fight_id]}
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"
    
    async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as response:
        if response.status == 200:
            data = await response.json()
            if 'errors' in data:
                print(f"[ERROR] Deaths query returned GraphQL errors: {data['errors']}")
                # Try alternative query without dataType restriction
                return await get_deaths_alternative_query(session, token, report_code, fight_id)
            
            report_data = data.get('data', {}).get('reportData', {}).get('report', {})
            events_data = report_data.get('events', {})
            events = events_data.get('data', []) if events_data else []
            
            # If no events found, try alternative query
            if not events:
                return await get_deaths_alternative_query(session, token, report_code, fight_id)
            
            # Build player ID to name mapping from masterData.actors
            players = {}
            master_data = report_data.get('masterData', {})
            if master_data and 'actors' in master_data:
                actors_list = master_data['actors']
                for actor in actors_list:
                    if actor.get('type') == 'Player':
                        players[actor.get('id')] = actor.get('name', 'Unknown')
            
            # Build ability ID to name mapping from masterData.abilities
            abilities = {}
            if master_data and 'abilities' in master_data:
                ability_list = master_data['abilities']
                for ability in ability_list:
                    abilities[ability.get('gameID')] = ability.get('name', 'Unknown')
            
            return {'events': events, 'players': players, 'abilities': abilities}
        else:
            response_text = await response.text()
            print(f"[ERROR] Deaths query failed with status {response.status}: {response_text}")
            return {'events': [], 'players': {}, 'abilities': {}}

async def get_deaths_alternative_query(session, token, report_code, fight_id):
    """Alternative deaths query using filter expression."""
    print(f"[DEBUG] WCL: Trying alternative deaths query for report: {report_code}, fight ID: {fight_id}")
    
    # Try querying all events and filter for deaths
    query = """
    query($reportCode: String!, $fightIDs: [Int]!) {
        reportData {
            report(code: $reportCode) {
                events(fightIDs: $fightIDs, startTime: 0, endTime: 99999999999, filterExpression: "type = 'death'") {
                    data
                }
                fights(fightIDs: $fightIDs) {
                    friendlyPlayers
                    startTime
                    endTime
                }
                masterData {
                    actors(type: "Player") {
                        id
                        name
                        type
                    }
                    abilities {
                        gameID
                        name
                    }
                }
            }
        }
    }
    """
    variables = {"reportCode": report_code, "fightIDs": [fight_id]}
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"
    
    async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as response:
        if response.status == 200:
            data = await response.json()
            if 'errors' in data:
                print(f"[ERROR] Alternative deaths query returned GraphQL errors: {data['errors']}")
                return {'events': [], 'players': {}, 'abilities': {}}
            
            report_data = data.get('data', {}).get('reportData', {}).get('report', {})
            events_data = report_data.get('events', {})
            events = events_data.get('data', []) if events_data else []
            
            # Build player and ability mappings
            players = {}
            master_data = report_data.get('masterData', {})
            if master_data and 'actors' in master_data:
                actors_list = master_data['actors']
                for actor in actors_list:
                    if actor.get('type') == 'Player':
                        players[actor.get('id')] = actor.get('name', 'Unknown')
            
            abilities = {}
            if master_data and 'abilities' in master_data:
                ability_list = master_data['abilities']
                for ability in ability_list:
                    abilities[ability.get('gameID')] = ability.get('name', 'Unknown')
            
            return {'events': events, 'players': players, 'abilities': abilities}
        else:
            response_text = await response.text()
            print(f"[ERROR] Alternative deaths query failed with status {response.status}: {response_text}")
            return {'events': [], 'players': {}, 'abilities': {}}

async def get_fight_basic_info(session, token, report_code, fight_id):
    """Get basic fight information (startTime, endTime, encounterID, kill status)."""
    query = """
    query($reportCode: String!, $fightIDs: [Int]!) {
        reportData {
            report(code: $reportCode) {
                fights(fightIDs: $fightIDs) {
                    id
                    startTime
                    endTime
                    encounterID
                    kill
                }
            }
        }
    }
    """
    
    variables = {"reportCode": report_code, "fightIDs": [fight_id]}
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"
    
    try:
        async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as response:
            if response.status != 200:
                return None
            
            data = await response.json()
            if 'errors' in data:
                return None
            
            fights = data.get('data', {}).get('reportData', {}).get('report', {}).get('fights', [])
            return fights[0] if fights else None
            
    except Exception as e:
        print(f"[ERROR] Exception getting basic fight info: {e}")
        return None
