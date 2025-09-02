# my_discord_bot.py

# --- Core Discord and Helper Imports ---
import discord
from discord import app_commands
from discord.ext import tasks
import os
from dotenv import load_dotenv
import asyncio
from flask import Flask
from threading import Thread
import aiohttp
import time
import re
from datetime import datetime, timezone

# --- Custom Module Imports ---
from database import get_db_connection, setup_database
from wcl_api import get_wcl_token, get_latest_log, get_fights_from_report
from discord_ui import LogButtonsView, send_message_with_auto_delete

# --- Import for your original command ---
from warcraft_recorder_automator import add_email_to_roster

# --- Load All Secrets from Environment ---
load_dotenv()
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
RECORDER_EMAIL = os.getenv('RECORDER_EMAIL')
RECORDER_PASSWORD = os.getenv('RECORDER_PASSWORD')
WCL_CLIENT_ID = os.getenv('WCL_CLIENT_ID')
WCL_CLIENT_SECRET = os.getenv('WCL_CLIENT_SECRET')
DATABASE_URL = os.getenv('DATABASE_URL')

# --- Configuration Constants ---
WCL_GUILD_ID = 771376 # Example Guild ID

# --- Flask Web Server for Keep-Alive ---
app = Flask('')
@app.route('/')
def home():
    print("[DEBUG] Keep-alive ping received by Flask server.")
    return "Bot is alive!"

def run_web_server():
    # Make sure to run on a port that your hosting service expects, e.g., 8080 or 10000
    app.run(host='0.0.0.0', port=10000)

# --- Bot and Command Tree Setup ---
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

# --- Automatic Log Detection Task ---
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

async def get_fights_from_report(session, token, report_code):
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
    """Helper function to get fight details - simplified to just get table and basic data."""
    print(f"[DEBUG] WCL: Fetching basic fight details for report: {report_code}, fight ID: {fight_id}, metric: {metric}")
    table_data_type = "DamageDone" if metric == "dps" else "Healing"
    
    # Simplified query - just get the essential data, no rankings
    query = """
    query($reportCode: String!, $fightIDs: [Int]!, $tableDataType: TableDataType!) {
      reportData {
        report(code: $reportCode) {
          table(fightIDs: $fightIDs, dataType: $tableDataType)
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
        "tableDataType": table_data_type
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

async def scrape_wcl_web_data(session, report_code, fight_id, start_time, end_time, encounter_id, metric):
    """
    Fallback function to scrape parse/ilvl percentages from WCL website when GraphQL API doesn't provide ranking data.
    Uses a two-step process: first get session tokens, then make the AJAX request.
    """
    print(f"[DEBUG] Scraping WCL web data for fight {fight_id}")
    
    # Step 1: Visit the main page to get session cookies and XSRF token
    metric_type = "damage-done" if metric == "dps" else "healing"
    main_page_url = f"https://www.warcraftlogs.com/reports/{report_code}?fight={fight_id}&type={metric_type}"
    
    print(f"[DEBUG] Scraping URL: {main_page_url}")
    
    # First request to get session and XSRF token
    initial_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Priority': 'u=0, i',
        'Sec-Ch-Ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"'
    }
    
    try:
        # Step 1: Get session cookies and XSRF token
        async with session.get(main_page_url, headers=initial_headers, allow_redirects=True) as initial_response:
            if initial_response.status != 200:
                print(f"[ERROR] Failed to get initial page, status: {initial_response.status}")
                return {}
            
            print(f"[DEBUG] Successfully loaded main page: {main_page_url}")
            
            # Extract cookies from the session
            cookies = {}
            for cookie in session.cookie_jar:
                if cookie.key in ['wcl_session', 'XSRF-TOKEN']:
                    cookies[cookie.key] = cookie.value
            
            if not cookies.get('wcl_session') or not cookies.get('XSRF-TOKEN'):
                print(f"[ERROR] Failed to extract required cookies")
                return {}
            
            # Step 2: Make the AJAX request to the table endpoint with the tokens
            table_url = f"https://www.warcraftlogs.com/reports/table/{metric_type}/{report_code}/{fight_id}/{start_time}/{end_time}/source/0/0/0/0/0/0/-1.0.-1.-1/-1/Any/Any/0/3014"
            
            # Headers for the AJAX request (mimicking the browser request you showed)
            ajax_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Priority': 'u=1, i',
                'Referer': main_page_url,
                'Sec-Ch-Ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                'X-Requested-With': 'XMLHttpRequest'
            }
            
            await asyncio.sleep(1)  # Small delay to mimic human behavior
            
            async with session.get(table_url, headers=ajax_headers, allow_redirects=True) as table_response:
                if table_response.status != 200:
                    print(f"[ERROR] Table endpoint failed with status {table_response.status}")
                    return {}
                
                html_content = await table_response.text()
                
                # Check if we got an error or anti-scraping message
                if "Use the API at /v1/docs instead of scraping HTML" in html_content:
                    print(f"[DEBUG] Got anti-scraping message from table endpoint")
                    return {}
                
                if len(html_content) < 500:
                    print(f"[DEBUG] Table endpoint response too short, likely not valid data")
                    return {}
                
                # Parse the response for table data only (no boss health)
                table_data = await parse_table_response(html_content)
                return table_data
    
    except Exception as e:
        print(f"[ERROR] Web scraping failed: {e}")
        return {}

def _extract_player_name(row):
    """Extract player name from a table row."""
    name_cell = row.find('td', class_='main-table-name')
    if not name_cell:
        return None
    
    name_link = name_cell.find('a', href='#')
    if not name_link:
        return None
    
    player_name = name_link.get_text(strip=True)
    return player_name if player_name else None

def _extract_percentage(row, cell_class):
    """Extract percentage value from a table cell."""
    cell = row.find('td', class_=cell_class)
    if not cell:
        return None
    
    link = cell.find('a')
    if not link:
        return None
    
    text = link.get_text(strip=True)
    text_clean = ''.join(c for c in text if c.isdigit())
    return int(text_clean) if text_clean.isdigit() else None

async def parse_table_response(html_content):
    """
    Parse the HTML response from the table endpoint to extract player data.
    """
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for the main table with data
        main_table = soup.find('table', {'id': 'main-table-0'})
        if not main_table:
            # Try to find any table with data
            all_tables = soup.find_all('table')
            for table in all_tables:
                rows = table.find_all('tr')
                if len(rows) > 5:  # Table with meaningful data
                    main_table = table
                    break
        
        if not main_table:
            return {}
        
        # Look for table rows with data
        table_rows = main_table.find_all('tr', {'id': re.compile(r'main-table-row-\d+-\d+-\d+')})
        
        if len(table_rows) == 0:
            # Try alternative row selection - look for rows with specific classes
            table_rows = main_table.find_all('tr', class_=re.compile(r'(odd|even)'))
            table_rows = [row for row in table_rows if row.get('id') and 'totals' not in row.get('id', '')]
        
        if len(table_rows) == 0:
            return {}
        
        # Parse the table data
        scraped_data = {}
        
        for row in table_rows:
            try:
                player_name = _extract_player_name(row)
                if not player_name:
                    continue
                
                parse_percent = _extract_percentage(row, 'main-table-performance')
                ilvl_percent = _extract_percentage(row, 'main-table-ilvl-performance')
                
                # Store the data if we found percentages
                if parse_percent is not None or ilvl_percent is not None:
                    scraped_data[player_name] = {
                        'rankPercent': parse_percent,
                        'bracketPercent': ilvl_percent
                    }
            
            except Exception:
                continue
        
        if scraped_data:
            print(f"[DEBUG] Web scraping successful! Got data for {len(scraped_data)} players")
        
        return scraped_data
    
    except Exception as e:
        print(f"[ERROR] Failed to parse table response: {e}")
        return {}

async def get_fight_details(session, token, report_code, fight_id, encounter_id, difficulty, metric, is_kill=False):
    print(f"[DEBUG] WCL: Fetching fight details for report: {report_code}, fight ID: {fight_id}, metric: {metric}")
    
    # Get basic fight data from GraphQL (table, playerDetails, etc.)
    fight_details = await get_fight_details_with_compare_type(session, token, report_code, fight_id, encounter_id, difficulty, metric)
    
    if not fight_details:
        print(f"[DEBUG] Failed to get basic fight details from GraphQL API")
        return None
    
    # Always attempt web scraping for parse percentiles
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

async def get_deaths_for_fight(session, token, report_code, fight_id):
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

async def get_all_boss_health_for_report(session, report_code):
    """
    Get boss health percentages for ALL fights in a report using the fights-and-participants endpoint.
    This is much more efficient than making individual requests per fight.
    Returns a dictionary mapping fight_id -> boss_health_percentage
    """
    print(f"[DEBUG] WCL: Fetching boss health for all fights in report: {report_code}")
    
    # Step 1: Visit the main page to get session cookies and XSRF token
    main_page_url = f"https://www.warcraftlogs.com/reports/{report_code}"
    
    print(f"[DEBUG] Getting session cookies from: {main_page_url}")
    
    # First request to get session and XSRF token
    initial_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache',
        'Priority': 'u=0, i',
        'Sec-Ch-Ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"'
    }
    
    try:
        # Step 1: Get session cookies and XSRF token
        async with session.get(main_page_url, headers=initial_headers, allow_redirects=True) as initial_response:
            if initial_response.status != 200:
                print(f"[ERROR] Failed to get initial page for participants endpoint, status: {initial_response.status}")
                return {}
            
            print(f"[DEBUG] Successfully loaded main page for participants endpoint")
            
            # Extract cookies from the session
            cookies = {}
            for cookie in session.cookie_jar:
                if cookie.key in ['wcl_session', 'XSRF-TOKEN']:
                    cookies[cookie.key] = cookie.value
            
            if not cookies.get('wcl_session') or not cookies.get('XSRF-TOKEN'):
                print(f"[ERROR] Failed to extract required cookies for participants endpoint")
                return {}
            
            # Step 2: Make the AJAX request to the fights-and-participants endpoint
            participants_url = f"https://www.warcraftlogs.com/reports/fights-and-participants/{report_code}/0"
            
            # Headers for the AJAX request
            ajax_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br, zstd',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Priority': 'u=1, i',
                'Referer': main_page_url,
                'Sec-Ch-Ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-origin',
                'X-Requested-With': 'XMLHttpRequest'
            }
            
            await asyncio.sleep(1)  # Small delay to mimic human behavior
            
            async with session.get(participants_url, headers=ajax_headers, allow_redirects=True) as response:
                if response.status != 200:
                    print(f"[ERROR] Participants endpoint failed with status {response.status}")
                    return {}
                
                data = await response.json()
                
                if not isinstance(data, dict) or 'fights' not in data:
                    print(f"[ERROR] Invalid response format from participants endpoint")
                    return {}
                
                fights = data['fights']
                if not isinstance(fights, list):
                    print(f"[ERROR] Fights data is not a list")
                    return {}
                
                # Extract boss health data for all fights that are wipes
                boss_health_data = {}
                for fight in fights:
                    if isinstance(fight, dict):
                        fight_id = fight.get('id')
                        is_kill = fight.get('kill', False)
                        boss_percentage_raw = fight.get('bossPercentage')
                        
                        # Only include wipes that have boss percentage data
                        if not is_kill and fight_id is not None and boss_percentage_raw is not None:
                            # Convert from hundredths to actual percentage (e.g., 8544 -> 85.44)
                            boss_health_percentage = boss_percentage_raw / 100
                            boss_health_data[fight_id] = boss_health_percentage
                            print(f"[DEBUG] Fight {fight_id}: {boss_health_percentage:.2f}% boss health")
                
                print(f"[DEBUG] Successfully extracted boss health data for {len(boss_health_data)} wipes")
                return boss_health_data
                
    except Exception as e:
        print(f"[ERROR] Exception calling participants endpoint: {e}")
        return {}

async def get_boss_health_for_wipe(session, token, report_code, fight_id, start_time=None, end_time=None, encounter_id=None, boss_health_cache=None):
    """
    Get boss health percentage for a wipe. 
    If boss_health_cache is provided, use it instead of making a new request.
    This is more efficient when getting health for multiple fights from the same report.
    """
    print(f"[DEBUG] WCL: Fetching boss health for wipe - report: {report_code}, fight ID: {fight_id}")
    
    # If we have a cache, use it
    if boss_health_cache is not None:
        boss_health_percentage = boss_health_cache.get(fight_id)
        if boss_health_percentage is not None:
            print(f"[DEBUG] Got boss health from cache: {boss_health_percentage:.2f}%")
            return boss_health_percentage
        else:
            print("[DEBUG] No boss health found in cache for this fight")
            return None
    
    # Fallback: get health data for all fights in the report (less efficient but still works)
    all_boss_health = await get_all_boss_health_for_report(session, report_code)
    boss_health_percentage = all_boss_health.get(fight_id)
    
    if boss_health_percentage is not None:
        print(f"[DEBUG] Successfully got boss health from participants endpoint: {boss_health_percentage:.2f}%")
        return boss_health_percentage
    else:
        print("[DEBUG] No boss health found in participants endpoint data")
        return None

async def get_fight_basic_info(session, token, report_code, fight_id):
    """
    Get basic fight information (startTime, endTime, encounterID, kill status).
    """
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

async def get_boss_health_from_events(session, token, report_code, fight_id):
    """
    Alternative approach: get boss health from combat events near the end of the fight.
    """
    print(f"[DEBUG] WCL: Trying to get boss health from events for fight {fight_id}")
    
    # First get fight info to determine the end time
    query = """
    query($reportCode: String!, $fightIDs: [Int]!) {
        reportData {
            report(code: $reportCode) {
                fights(fightIDs: $fightIDs) {
                    id, startTime, endTime, kill
                    enemyNPCs {
                        id
                        instanceCount
                    }
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
            if not fights or fights[0].get('kill'):
                return None  # Skip if it's a kill
            
            fight = fights[0]
            end_time = fight.get('endTime')
            start_time = fight.get('startTime')
            
            if not end_time or not start_time:
                return None
            
            # Try the new includeResources approach
            return await get_boss_health_with_resources(session, token, report_code, fight_id)
            
    except Exception as e:
        print(f"[ERROR] Exception getting boss health from events: {e}")
        return None

async def get_boss_health_with_resources(session, token, report_code, fight_id):
    """
    New approach: Use includeResources to get detailed unit resource information
    which might include boss health data.
    """
    print(f"[DEBUG] WCL: Trying includeResources approach for boss health - fight {fight_id}")
    
    query = """
    query($reportCode: String!, $fightIDs: [Int]!) {
        reportData {
            report(code: $reportCode) {
                fights(fightIDs: $fightIDs, includeResources: true) {
                    id
                    startTime
                    endTime
                    kill
                    enemyNPCs {
                        id
                        instanceCount
                        gameID
                    }
                }
                masterData {
                    actors(type: "NPC") {
                        id
                        name
                        type
                        subType
                        gameID
                    }
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
                print(f"[ERROR] includeResources query failed with status {response.status}")
                return None
            
            data = await response.json()
            if 'errors' in data:
                print(f"[ERROR] includeResources query returned GraphQL errors: {data['errors']}")
                return None
            
            report_data = data.get('data', {}).get('reportData', {}).get('report', {})
            fights = report_data.get('fights', [])
            master_data = report_data.get('masterData', {})
            
            if not fights or fights[0].get('kill'):
                return None  # Skip if it's a kill
            
            fight = fights[0]
            enemy_npcs = fight.get('enemyNPCs', [])
            actors = master_data.get('actors', [])
            
            print(f"[DEBUG] Found {len(enemy_npcs)} enemy NPCs and {len(actors)} actors")
            
            # If the resources approach doesn't give us health directly,
            # try looking for resource events around the end of the fight
            start_time = fight.get('startTime')
            end_time = fight.get('endTime')
            
            if start_time and end_time:
                return await get_boss_health_from_resource_events(session, token, report_code, fight_id, start_time, end_time, enemy_npcs)
            
            return None
            
    except Exception as e:
        print(f"[ERROR] Exception in includeResources query: {e}")
        return None

async def get_boss_health_from_resource_events(session, token, report_code, fight_id, start_time, end_time, enemy_npcs):
    """
    Query for resource-related events near the end of the fight to find boss health.
    """
    print(f"[DEBUG] WCL: Querying resource events for boss health")
    
    # Query for events in the last 10 seconds of the fight
    query_start_time = max(start_time, end_time - 10000)  # Last 10 seconds
    
    query = """
    query($reportCode: String!, $fightIDs: [Int]!, $startTime: Float!, $endTime: Float!) {
        reportData {
            report(code: $reportCode) {
                events(
                    fightIDs: $fightIDs, 
                    startTime: $startTime, 
                    endTime: $endTime,
                    hostilityType: Enemies,
                    includeResources: true
                ) {
                    data
                }
            }
        }
    }
    """
    
    variables = {
        "reportCode": report_code, 
        "fightIDs": [fight_id],
        "startTime": query_start_time,
        "endTime": end_time
    }
    headers = {'Authorization': f'Bearer {token}'}
    url = "https://www.warcraftlogs.com/api/v2/client"
    
    try:
        async with session.post(url, json={'query': query, 'variables': variables}, headers=headers) as response:
            if response.status != 200:
                print(f"[ERROR] Resource events query failed with status {response.status}")
                return None
            
            data = await response.json()
            if 'errors' in data:
                print(f"[ERROR] Resource events query returned GraphQL errors: {data['errors']}")
                return None
            
            events_data = data.get('data', {}).get('reportData', {}).get('report', {}).get('events', {})
            events = events_data.get('data', []) if events_data else []
            
            print(f"[DEBUG] Found {len(events)} events with includeResources")
            
            # Look for events that might contain boss health information
            for event in events:
                if isinstance(event, dict):
                    # Look for resource-related fields
                    if any(key in event for key in ['hitPoints', 'maxHitPoints', 'health', 'resources']):
                        print(f"[DEBUG] Found event with potential health data: {event}")
                        
                        # Try to extract health percentage
                        current_hp = event.get('hitPoints')
                        max_hp = event.get('maxHitPoints')
                        
                        if current_hp is not None and max_hp is not None and max_hp > 0:
                            health_percentage = (current_hp / max_hp) * 100
                            print(f"[DEBUG] Calculated boss health: {health_percentage:.1f}%")
                            return health_percentage
                        
                        # Check for resources array
                        resources = event.get('resources')
                        if isinstance(resources, list):
                            for resource in resources:
                                if isinstance(resource, dict) and resource.get('type') == 0:  # Health resource type
                                    current = resource.get('amount', resource.get('current'))
                                    maximum = resource.get('max', resource.get('maximum'))
                                    if current is not None and maximum is not None and maximum > 0:
                                        health_percentage = (current / maximum) * 100
                                        print(f"[DEBUG] Calculated boss health from resources: {health_percentage:.1f}%")
                                        return health_percentage
            
            print("[DEBUG] No health data found in resource events")
            return None
            
    except Exception as e:
        print(f"[ERROR] Exception querying resource events: {e}")
        return None

# --- Helper functions for cleaner code ---
async def send_ephemeral_with_auto_delete(interaction, content=None, embed=None, view=None, delete_after=600):
    """
    Send an ephemeral message. Note: Ephemeral messages cannot be programmatically deleted
    by bots as they only exist on the user's client side. They automatically disappear
    when the user refreshes Discord or navigates away.
    
    Args:
        interaction: Discord interaction object
        content: Message content (optional)
        embed: Discord embed (optional)
        view: Discord view with components (optional)
        delete_after: Ignored for ephemeral messages (kept for API compatibility)
    """
    try:
        # Prepare kwargs, only including non-None values
        kwargs = {'ephemeral': True}
        if content is not None:
            kwargs['content'] = content
        if embed is not None:
            kwargs['embed'] = embed
        if view is not None:
            kwargs['view'] = view
        
        # Send the ephemeral message
        if hasattr(interaction, 'followup') and interaction.response.is_done():
            # Use followup if interaction already responded
            return await interaction.followup.send(**kwargs)
        else:
            # Use response if we haven't responded yet
            await interaction.response.send_message(**kwargs)
            return await interaction.original_response()
        
    except Exception as e:
        print(f"[ERROR] Failed to send ephemeral message: {e}")
        # Fallback to regular ephemeral message
        try:
            fallback_kwargs = {'ephemeral': True}
            if content is not None:
                fallback_kwargs['content'] = content
            if embed is not None:
                fallback_kwargs['embed'] = embed
            if view is not None:
                fallback_kwargs['view'] = view
            
            if hasattr(interaction, 'followup') and interaction.response.is_done():
                return await interaction.followup.send(**fallback_kwargs)
            else:
                await interaction.response.send_message(**fallback_kwargs)
                return await interaction.original_response()
        except Exception as fallback_error:
            print(f"[ERROR] Fallback ephemeral message also failed: {fallback_error}")
            return None

async def send_message_with_auto_delete(channel, content=None, embed=None, view=None, delete_after=600):
    """
    Send a regular (non-ephemeral) message that automatically deletes itself after a specified time.
    
    Args:
        channel: Discord channel to send to
        content: Message content (optional)
        embed: Discord embed (optional)
        view: Discord view with components (optional)
        delete_after: Time in seconds before auto-deletion (default: 600 = 10 minutes)
    """
    try:
        # Prepare kwargs, only including non-None values
        kwargs = {}
        if content is not None:
            kwargs['content'] = content
        if embed is not None:
            kwargs['embed'] = embed
        if view is not None:
            kwargs['view'] = view
        
        # Send the message
        message = await channel.send(**kwargs)
        
        # Schedule automatic deletion
        async def delete_message():
            await asyncio.sleep(delete_after)
            try:
                await message.delete()
                print(f"[DEBUG] Auto-deleted message after {delete_after} seconds")
            except discord.NotFound:
                print(f"[DEBUG] Message already deleted")
            except discord.Forbidden:
                print(f"[DEBUG] Cannot delete message - insufficient permissions")
            except Exception as e:
                print(f"[DEBUG] Error deleting message: {e}")
        
        # Run deletion in background
        asyncio.create_task(delete_message())
        return message
        
    except Exception as e:
        print(f"[ERROR] Failed to send message with auto-delete: {e}")
        return None

def _find_ranking_list(ranking_data):
    """Extract ranking list from various nested structures."""
    if not ranking_data:
        return None
    
    # Pattern 1: Direct list
    if isinstance(ranking_data, list):
        return ranking_data
    
    if not isinstance(ranking_data, dict):
        return None
    
    # Pattern 2: Direct data key
    if 'data' in ranking_data:
        potential_list = ranking_data['data']
        if isinstance(potential_list, list):
            return potential_list
        
        # Pattern 3: Double nested like playerDetails
        if isinstance(potential_list, dict) and 'rankings' in potential_list:
            nested_rankings = potential_list['rankings']
            if isinstance(nested_rankings, list):
                return nested_rankings
            elif isinstance(nested_rankings, dict) and 'data' in nested_rankings:
                triple_nested = nested_rankings['data']
                if isinstance(triple_nested, list):
                    return triple_nested
    
    # Pattern 4: Look for 'rankings' key at top level
    if 'rankings' in ranking_data:
        potential_rankings = ranking_data['rankings']
        if isinstance(potential_rankings, list):
            return potential_rankings
        elif isinstance(potential_rankings, dict) and 'data' in potential_rankings:
            data_level = potential_rankings['data']
            if isinstance(data_level, list):
                return data_level
    
    return None

def _parse_ranking_data(ranking_data, fight_details=None):
    """
    Parse WCL ranking data and extract player parse data and roles.
    Now prioritizes scraped web data over GraphQL rankings.
    Returns: (parses_dict, player_roles_dict)
    """
    parses = {}
    player_roles = {}
    
    # First priority: Check for scraped web data
    if fight_details and 'scraped_parses' in fight_details:
        scraped_data = fight_details['scraped_parses']
        for player_name, player_data in scraped_data.items():
            parses[player_name] = player_data
        return parses, player_roles
    
    # Fallback: Try to parse GraphQL ranking data
    ranking_list = _find_ranking_list(ranking_data)
    
    if ranking_list and len(ranking_list) > 0:
        ranking_record = ranking_list[0]
        if isinstance(ranking_record, dict) and 'roles' in ranking_record:
            roles = ranking_record['roles']
            for role_name, role_data in roles.items():
                _process_role_data(role_name, role_data, parses, player_roles)
    
    return parses, player_roles

def _process_role_data(role_name, role_data, parses, player_roles):
    """Process a single role's data and update parses and player_roles dictionaries."""
    if not isinstance(role_data, dict) or 'characters' not in role_data:
        return
    
    characters = role_data['characters']
    
    # Map role names to simplified role types
    role_mapping = {
        'dps': 'dps',
        'healers': 'healer', 
        'tanks': 'tank'
    }
    simplified_role = role_mapping.get(role_name, role_name)
    
    for char in characters:
        if isinstance(char, dict):
            name = char.get('name', 'Unknown')
            parses[name] = char
            player_roles[name] = simplified_role

def _filter_player_entries(sorted_entries, parses, player_roles):
    """
    Filter table entries to only include actual players, not NPCs/pets.
    Returns: list of player entries
    """
    has_any_ranking_data = len(parses) > 0 or len(player_roles) > 0
    
    if has_any_ranking_data:
        # We have ranking data, so filter based on it
        player_entries = []
        for entry in sorted_entries:
            name = entry['name']
            # Include entry if it has ranking data (which means it's a player)
            if name in parses or name in player_roles:
                player_entries.append(entry)
        return player_entries
    else:
        # No ranking data available, use basic filtering
        return _apply_basic_filtering(sorted_entries)

def _apply_basic_filtering(sorted_entries):
    """Apply basic filtering for encounters without ranking data."""
    filtered_entries = []
    npc_keywords = ['totem', 'pet', 'spirit', 'minion', 'guardian', 'elemental', 'wolf', 'mirror image']
    
    for entry in sorted_entries:
        name = entry['name']
        
        # Skip entries with names that are clearly not players
        if any(keyword in name.lower() for keyword in npc_keywords):
            continue
            
        # Skip entries with very low damage (likely environmental or incidental)
        if entry['total'] < 1000:  # Less than 1k total damage is probably not a real player
            continue
            
        filtered_entries.append(entry)
    
    return filtered_entries

def _extract_role_data_from_playerdetails(player_details_data):
    """Extract the role data structure from nested playerDetails response."""
    if not isinstance(player_details_data, dict):
        return {}
    
    # Check if playerDetails has the nested 'data' structure
    if 'data' in player_details_data:
        data_level = player_details_data['data']
        if isinstance(data_level, dict):
            # Check if there's another nested 'playerDetails' level
            if 'playerDetails' in data_level:
                return data_level['playerDetails'] if isinstance(data_level['playerDetails'], dict) else {}
            else:
                # Direct data structure
                return data_level
    
    # Fallback: assume direct structure
    return player_details_data

def _extract_player_roles_from_playerdetails(player_details_data, friendly_players=None):
    """
    Extract player roles from playerDetails data based on their role groupings.
    Returns: dict mapping player names to roles ('tank', 'healer', 'dps')
    """
    player_roles = {}
    role_data = _extract_role_data_from_playerdetails(player_details_data)
    
    # Map role group names to our simplified role types
    role_mapping = {
        'tanks': 'tank',
        'dps': 'dps', 
        'healers': 'healer'
    }
    
    for api_role_name, players_list in role_data.items():
        if api_role_name in role_mapping and isinstance(players_list, list):
            simplified_role = role_mapping[api_role_name]
            
            for player_entry in players_list:
                if isinstance(player_entry, dict) and 'name' in player_entry:
                    name = player_entry.get('name')
                    if name:
                        player_roles[name] = simplified_role
    
    return player_roles

def _get_colored_name(name, player_roles):
    """Apply role-based color to player name."""
    player_role = player_roles.get(name, 'unknown')
    
    color_mapping = {
        'dps': '\033[31m',     # Red
        'healer': '\033[32m',  # Green  
        'tank': '\033[34m'     # Blue
    }
    
    if player_role in color_mapping:
        return f"{color_mapping[player_role]}{name}\033[0m"
    else:
        return name  # White for unknown roles

def _format_name_with_padding(colored_name, target_width=20):
    """
    Format a name (potentially with ANSI color codes) with proper padding.
    ANSI codes are invisible but take up characters, so we need to account for them.
    """
    # Check if the name has ANSI color codes
    if '\033[' in colored_name:
        # Has color codes - use larger padding to account for invisible characters
        return colored_name.ljust(target_width + 10)  # +10 for ANSI codes (\033[31m and \033[0m)
    else:
        # No color codes - use normal padding
        return colored_name.ljust(target_width)

def _get_colored_percentage(percentage_str, percentage_value):
    """Apply color coding to percentage values based on WoW item quality colors."""
    if percentage_value is None:
        return percentage_str.rjust(3)
    
    # Color thresholds based on WoW item quality
    if percentage_value >= 95:
        return f"\033[33m{percentage_str.rjust(3)}\033[0m"  # Yellow for legendary (95+)
    elif percentage_value >= 75:
        return f"\033[35m{percentage_str.rjust(3)}\033[0m"  # Purple for epic (75+)
    elif percentage_value >= 50:
        return f"\033[34m{percentage_str.rjust(3)}\033[0m"  # Blue for rare (50+)
    elif percentage_value >= 25:
        return f"\033[32m{percentage_str.rjust(3)}\033[0m"  # Green for uncommon (25+)
    else:
        return percentage_str.rjust(3)  # Below 25 stays white (no color)

def _get_player_percentages(player_parses):
    """Extract parse and ilvl percentages from player parse data."""
    parse_pct = "N/A"
    ilvl_pct = "N/A"
    
    if player_parses and isinstance(player_parses, dict):
        # Use the correct field names from WCL API
        if 'rankPercent' in player_parses and player_parses['rankPercent'] is not None:
            parse_pct = f"{player_parses['rankPercent']:.0f}"
        
        if 'bracketPercent' in player_parses and player_parses['bracketPercent'] is not None:
            ilvl_pct = f"{player_parses['bracketPercent']:.0f}"
    
    return parse_pct, ilvl_pct

def _format_amounts_and_activity(entry, fight_duration_seconds):
    """Format DPS/HPS amounts and activity percentage."""
    # Calculate amount per second
    amount_per_second = entry['total'] / fight_duration_seconds
    amount_str = f"{amount_per_second / 1_000_000:.2f}m" if amount_per_second >= 1_000_000 else f"{amount_per_second / 1_000:.1f}k"
    amount_str = amount_str.ljust(6)

    # Format total amount
    total_amount = entry['total']
    if total_amount >= 1_000_000_000:  # Billions
        amount_total_str = f"{total_amount / 1_000_000_000:.1f}B"
    elif total_amount >= 1_000_000:    # Millions
        amount_total_str = f"{total_amount / 1_000_000:.1f}M"
    elif total_amount >= 1_000:        # Thousands
        amount_total_str = f"{total_amount / 1_000:.1f}K"
    else:
        amount_total_str = str(total_amount)
    amount_total_str = amount_total_str.ljust(8)

    # Calculate active percentage
    active_time = entry.get('activeTime', entry.get('uptime', 0))
    if fight_duration_seconds > 0:
        active_percent = (active_time / 1000) / fight_duration_seconds * 100  # activeTime is in milliseconds
        active_percent_str = f"{active_percent:.0f}%".rjust(6)
    else:
        active_percent_str = "N/A".rjust(6)
    
    return amount_str, amount_total_str, active_percent_str

def _format_overheal(entry):
    """Calculate and format overheal percentage for healing entries."""
    overheal = entry.get('overheal', 0)
    total_amount = entry['total']
    
    if total_amount > 0:
        overheal_percent = (overheal / (total_amount + overheal)) * 100
        return f"{overheal_percent:.0f}%".rjust(8)
    else:
        return "N/A".rjust(8)

# --- Formatting and UI View Classes ---
def format_merged_table(fight_details, metric, fight_duration_seconds, encounter_name=None, boss_health_percentage=None):
    table_data = fight_details.get('table', {}).get('data', {})
    ranking_data = fight_details.get('rankings') 
    
    # Create header with encounter name and boss health percentage for wipes
    if encounter_name:
        if boss_health_percentage is not None:
            table_title = f"{metric.upper()} on {encounter_name} Wipe ({boss_health_percentage:.2f}%)"
        else:
            table_title = f"{metric.upper()} on {encounter_name}"
    else:
        table_title = metric.upper()
    
    if metric.upper() == "DPS":
        header = "Parse% | Name                 | DPS      | Amount   | Active% | iLvl %"
    else:  # HPS
        header = "Parse% | Name                 | HPS      | Amount   | Overheal | Active% | iLvl %"
    
    lines = [f"```ansi\n{table_title}", "=" * len(table_title), header, "-" * len(header)]

    if not table_data or not table_data.get('entries'):
        return "```No performance data found for this fight.```"

    parses, player_roles = _parse_ranking_data(ranking_data, fight_details)
    
    # If no ranking data was found, try to extract roles from playerDetails
    if not player_roles:
        player_details_data = fight_details.get('playerDetails')
        player_roles = _extract_player_roles_from_playerdetails(player_details_data)

    if fight_duration_seconds <= 0: fight_duration_seconds = 1

    # Sort table entries by total damage/healing (highest first)
    sorted_entries = sorted(table_data.get('entries', []), key=lambda x: x['total'], reverse=True)
    
    # Filter entries to only include actual players
    player_entries = _filter_player_entries(sorted_entries, parses, player_roles)

    # Limit the number of players to prevent message length issues
    max_players = 25  # Limit to top 25 players to keep message manageable
    if len(player_entries) > max_players:
        player_entries = player_entries[:max_players]

    for entry in player_entries:
        name = entry['name']
        player_parses = parses.get(name)

        # Apply role-based color to player name
        colored_name = _get_colored_name(name, player_roles)
        formatted_name = _format_name_with_padding(colored_name)

        # Get parse and ilvl percentages
        parse_pct, ilvl_pct = _get_player_percentages(player_parses)

        # Apply color coding to percentages
        parse_value = int(parse_pct) if parse_pct != "N/A" and parse_pct.isdigit() else None
        ilvl_value = int(ilvl_pct) if ilvl_pct != "N/A" and ilvl_pct.isdigit() else None
        
        parse_pct_display = _get_colored_percentage(parse_pct, parse_value)
        ilvl_pct_display = _get_colored_percentage(ilvl_pct, ilvl_value)

        # Format amounts and percentages
        amount_str, amount_total_str, active_percent_str = _format_amounts_and_activity(
            entry, fight_duration_seconds
        )

        # Build the table row
        if metric.upper() == "DPS":
            lines.append(f"{parse_pct_display}%   | {formatted_name} | {amount_str} | {amount_total_str} | {active_percent_str} | {ilvl_pct_display}%")
        else:  # HPS - include overheal
            overheal_str = _format_overheal(entry)
            lines.append(f"{parse_pct_display}%   | {formatted_name} | {amount_str} | {amount_total_str} | {overheal_str} | {active_percent_str} | {ilvl_pct_display}%")

    # Add note if we limited the number of players shown
    has_any_ranking_data = len(parses) > 0 or len(player_roles) > 0
    if has_any_ranking_data:
        # Calculate based on filtering with ranking data
        total_player_entries = len([entry for entry in sorted_entries if entry['name'] in parses or entry['name'] in player_roles])
    else:
        # No ranking data, so all entries are considered players
        total_player_entries = len(sorted_entries)
        
    if total_player_entries > max_players:
        lines.append("")
        lines.append(f"(Showing top {max_players} players - {total_player_entries - max_players} more players not shown)")

    lines.append("```")
    return "\n".join(lines)

def _process_death_event(event, players, abilities, fight_start_time, player_roles):
    """Process a single death event and return formatted line or None."""
    if event.get('type') != 'death':
        return None
    
    # Get the target ID and convert to player name
    target_id = event.get('targetID')
    target_name = players.get(target_id, f'Player{target_id}')
    
    relative_timestamp_ms = event['timestamp'] - fight_start_time
    timestamp_str = time.strftime('%M:%S', time.gmtime(relative_timestamp_ms / 1000))
    
    # Apply role-based color to player name in deaths table
    colored_name = _get_colored_name(target_name, player_roles) if player_roles and target_name in player_roles else target_name
    formatted_name = _format_name_with_padding(colored_name)
    
    # Get the killing ability name
    killing_ability_id = event.get('killingAbilityGameID')
    ability_name = abilities.get(killing_ability_id, f'Ability{killing_ability_id}' if killing_ability_id else 'Unknown')
    
    return f"{timestamp_str.ljust(9)} | {formatted_name} | {ability_name}"

def format_deaths_table(death_data, fight_start_time, player_roles=None, encounter_name=None):
    events = death_data.get('events', [])
    players = death_data.get('players', {})
    abilities = death_data.get('abilities', {})
    
    # Create header with encounter name
    table_title = f"Deaths on {encounter_name}" if encounter_name else "Deaths"
    header = "Timestamp | Name                 | Killing Blow"
    lines = [f"```ansi\n{table_title}", "=" * len(table_title), header, "-" * len(header)]
    
    if not events:
        if encounter_name and "Kill" in encounter_name:
            return f"```ansi\nDeaths on {encounter_name}\n{'=' * len(f'Deaths on {encounter_name}')}\n\n🎉 Flawless victory! No player deaths occurred during this fight.\n```"
        else:
            return f"```ansi\nDeaths on {encounter_name if encounter_name else 'Unknown Fight'}\n{'=' * len(f'Deaths on {encounter_name}' if encounter_name else 'Deaths on Unknown Fight')}\n\nNo player deaths found for this fight.\n```"

    max_deaths = 50  # Limit to 50 deaths to prevent message length issues
    death_lines = []
    
    for event in events[:max_deaths]:
        death_line = _process_death_event(event, players, abilities, fight_start_time, player_roles)
        if death_line:
            death_lines.append(death_line)
    
    if not death_lines:
        return "```No player deaths found for this fight.```"
    
    lines.extend(death_lines)
    
    # Add note if we hit the limit
    total_deaths = len([e for e in events if e.get('type') == 'death'])
    if total_deaths > max_deaths:
        lines.append("")
        lines.append(f"(Showing first {max_deaths} deaths - {total_deaths - max_deaths} more deaths occurred)")
    
    lines.append("```")
    return "\n".join(lines)

class FightSelect(discord.ui.Select):
    def __init__(self, fights, report_code, metric, boss_health_data=None):
        self.report_code = report_code
        self.metric = metric
        self.fights = {str(f['id']): f for f in fights}
        self.boss_health_data = boss_health_data or {}

        options = []
        wipe_counters = {}
        for fight in fights:
            boss_name = fight['name']
            if fight['kill']:
                label = f"{boss_name} (Kill)"
            else:
                wipe_counters[boss_name] = wipe_counters.get(boss_name, 0) + 1
                
                # Check if we have boss health data for this fight
                fight_id = fight['id']
                if fight_id in self.boss_health_data:
                    boss_health = self.boss_health_data[fight_id]
                    label = f"{boss_name} (Wipe {wipe_counters[boss_name]} - {boss_health:.2f}%)"
                else:
                    label = f"{boss_name} (Wipe {wipe_counters[boss_name]})"
            
            if len(label) > 100: label = label[:97] + "..."
            options.append(discord.SelectOption(label=label, value=str(fight['id'])))
        
        super().__init__(placeholder="Choose a fight...", min_values=1, max_values=1, options=options[:25])
    
    @staticmethod
    async def create_with_boss_health(fights, report_code, metric, session, token):
        """Create a FightSelect with boss health data for wipes."""
        # Get boss health for ALL fights in the report with one efficient request
        boss_health_data = await get_all_boss_health_for_report(session, report_code)
        
        return FightSelect(fights, report_code, metric, boss_health_data)

    async def callback(self, interaction: discord.Interaction):
        fight_id = int(self.values[0])
        selected_fight = self.fights[str(fight_id)]
        
        await interaction.response.defer(thinking=True, ephemeral=True)

        async with aiohttp.ClientSession() as session:
            token = await get_wcl_token(session)
            if not token:
                print("[ERROR] Failed to get WCL token in select callback.")
                await interaction.edit_original_response(content="Error: Could not get WCL token.", view=None)
                return

            formatted_table = "An unknown error occurred."
            if self.metric in ["dps", "hps"]:
                encounter_id = selected_fight.get('encounterID')
                difficulty = selected_fight.get('difficulty')

                if not encounter_id or encounter_id == 0:
                    await interaction.edit_original_response(
                        content=f"The selected fight, **{selected_fight['name']}**, does not have rankings available (it may be a trash fight). Please select a boss kill or wipe.",
                        view=None
                    )
                    return

                is_kill = selected_fight.get('kill', False)
                fight_details = await get_fight_details(session, token, self.report_code, fight_id, encounter_id, difficulty, self.metric, is_kill)
                
                if not fight_details:
                    print("[ERROR] get_fight_details returned no data.")
                    await interaction.edit_original_response(content="Could not retrieve data for the selected fight. The API may have returned an error. Please check the bot's console for details.", view=None)
                    return

                fight_duration_seconds = (selected_fight['endTime'] - selected_fight['startTime']) / 1000
                
                # Create encounter name with kill/wipe status
                encounter_name = selected_fight['name']
                boss_health_percentage = None
                
                if selected_fight['kill']:
                    encounter_name += " (Kill)"
                else:
                    # Count wipes for this encounter name in the fights list
                    wipe_count = 1
                    for fight in self.fights.values():
                        if (fight['name'] == selected_fight['name'] and 
                            fight['id'] < selected_fight['id'] and 
                            not fight['kill']):
                            wipe_count += 1
                    
                    # Get boss health percentage for wipes
                    boss_health = None
                    
                    # First try to get it from scraped data if we have fight_details
                    if fight_details and 'scraped_parses' in fight_details:
                        scraped_data = fight_details['scraped_parses']
                        if 'boss_health_percentage' in scraped_data:
                            boss_health = scraped_data['boss_health_percentage']
                            print(f"[DEBUG] Got boss health from scraped data: {boss_health}%")
                    
                    # If no scraped health data, try the dedicated boss health function
                    if boss_health is None:
                        boss_health = await get_boss_health_for_wipe(session, token, self.report_code, fight_id, boss_health_cache=self.boss_health_data)
                    
                    if boss_health is not None:
                        encounter_name += f" Wipe {wipe_count}"
                        boss_health_percentage = boss_health
                    else:
                        encounter_name += f" Wipe {wipe_count}"
                
                formatted_table = format_merged_table(fight_details, self.metric, fight_duration_seconds, encounter_name, boss_health_percentage)
            
            elif self.metric == "deaths":
                print(f"[UI] Getting death details.")
                fight_start_time = selected_fight['startTime']
                death_events = await get_deaths_for_fight(session, token, self.report_code, fight_id)
                
                # Create encounter name with kill/wipe status
                encounter_name = selected_fight['name']
                if selected_fight['kill']:
                    encounter_name += " (Kill)"
                else:
                    # Count wipes for this encounter name in the fights list
                    wipe_count = 1
                    for fight in self.fights.values():
                        if (fight['name'] == selected_fight['name'] and 
                            fight['id'] < selected_fight['id'] and 
                            not fight['kill']):
                            wipe_count += 1
                    
                    # Get boss health percentage for wipes
                    boss_health = await get_boss_health_for_wipe(session, token, self.report_code, fight_id, boss_health_cache=self.boss_health_data)
                    
                    if boss_health is not None:
                        encounter_name += f" Wipe {wipe_count} ({boss_health:.2f}%)"
                    else:
                        encounter_name += f" Wipe {wipe_count}"
                
                # Also get player roles for color coding in deaths table
                encounter_id = selected_fight.get('encounterID')
                difficulty = selected_fight.get('difficulty')
                player_roles = {}
                
                if encounter_id and encounter_id != 0:
                    # Get rankings data to extract player roles
                    is_kill = selected_fight.get('kill', False)
                    fight_details = await get_fight_details(session, token, self.report_code, fight_id, encounter_id, difficulty, "dps", is_kill)
                    if fight_details and fight_details.get('rankings'):
                        # Try to get roles from ranking data first
                        ranking_data = fight_details.get('rankings')
                        parses, player_roles = _parse_ranking_data(ranking_data)
                    
                    # If no ranking data, try to extract roles from playerDetails
                    if not player_roles and fight_details:
                        print("[DEBUG] No ranking data for deaths table, trying playerDetails role groups")
                        player_details_data = fight_details.get('playerDetails')
                        fights_data = fight_details.get('fights', [])
                        friendly_players = fights_data[0].get('friendlyPlayers', []) if fights_data else None
                        player_roles = _extract_player_roles_from_playerdetails(player_details_data, friendly_players)
                        
                        if not player_roles:
                            print("[DEBUG] No spec data available for deaths table - will show names without role colors")
                
                formatted_table = format_deaths_table(death_events, fight_start_time, player_roles, encounter_name)
            
            print("[UI] Data formatted. Checking message length before sending.")
            
            # Check if the message is too long for Discord (2000 character limit)
            if len(formatted_table) > 2000:
                print(f"[UI] Message too long ({len(formatted_table)} chars), truncating.")
                
                # Calculate how much space we need for the warning message and closing
                warning_msg = "\n\n(Table truncated - too many players to display)\n```"
                max_content_length = 1950 - len(warning_msg)  # More conservative buffer
                
                # Find a good place to truncate - look for the last complete line before the limit
                truncated = formatted_table[:max_content_length]
                last_newline = truncated.rfind('\n')
                if last_newline > 0:
                    truncated = truncated[:last_newline]
                
                # Make sure we properly close any ANSI codes and the code block
                if not truncated.endswith('\033[0m'):
                    truncated += '\033[0m'  # Reset ANSI codes
                
                # Add warning message and close the code block
                formatted_table = truncated + warning_msg
                print(f"[UI] Truncated to {len(formatted_table)} characters.")
                
                # Final safety check
                if len(formatted_table) > 2000:
                    print(f"[UI] Still too long after truncation, doing emergency truncation.")
                    formatted_table = formatted_table[:1990] + "\n```"
            
            await send_ephemeral_with_auto_delete(interaction, content=formatted_table)

class LogButtonsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        print("[UI] Persistent LogButtonsView created.")

    def _get_report_code_from_interaction(self, interaction: discord.Interaction) -> str | None:
        try:
            if not interaction.message or not interaction.message.embeds:
                print("[ERROR] Interaction message has no embeds.")
                return None
            
            embed_url = interaction.message.embeds[0].url
            if not embed_url or "warcraftlogs.com/reports/" not in embed_url:
                print(f"[ERROR] Embed URL is invalid or missing: {embed_url}")
                return None

            report_code = embed_url.strip().split('/')[-1]
            if not report_code:
                print("[ERROR] Extracted report code is empty.")
                return None
            
            print(f"[UI] Extracted report code: {report_code}")
            return report_code
        except (IndexError, AttributeError) as e:
            print(f"[ERROR] Failed to extract report code from interaction: {e}")
            return None

    async def show_fight_selection(self, interaction: discord.Interaction, metric: str):
        print(f"[UI] show_fight_selection called for metric: {metric}")
        
        report_code = self._get_report_code_from_interaction(interaction)
        if not report_code:
            await send_ephemeral_with_auto_delete(
                interaction,
                content="Could not find the report code from the original message. The message might be malformed."
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        async with aiohttp.ClientSession() as session:
            token = await get_wcl_token(session)
            if not token:
                await send_ephemeral_with_auto_delete(interaction, content="Error: Could not get WCL token.")
                return
            
            fights = await get_fights_from_report(session, token, report_code)
            if not fights:
                await send_ephemeral_with_auto_delete(interaction, content="Sorry, no boss encounters found in this log.")
                return
            
            select_view = discord.ui.View(timeout=180)
            
            # Create FightSelect with boss health data for wipes
            fight_select = await FightSelect.create_with_boss_health(fights, report_code, metric, session, token)
            select_view.add_item(fight_select)
            
            await send_ephemeral_with_auto_delete(interaction, content="Please select a fight:", view=select_view)

    @discord.ui.button(label="DPS", style=discord.ButtonStyle.primary, custom_id="dps_button_persistent_final")
    async def dps_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("[UI] DPS button pressed.")
        await self.show_fight_selection(interaction, "dps")

    @discord.ui.button(label="Heal", style=discord.ButtonStyle.success, custom_id="heal_button_persistent_final")
    async def heal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("[UI] Heal button pressed.")
        await self.show_fight_selection(interaction, "hps")
    
    @discord.ui.button(label="Deaths", style=discord.ButtonStyle.secondary, custom_id="deaths_button_persistent_final")
    async def deaths_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("[UI] Deaths button pressed.")
        await self.show_fight_selection(interaction, "deaths")

# --- Background Task ---
@tasks.loop(minutes=10)
async def check_for_new_logs():
    print("[TASK] Log check running (every 10 minutes).")
    conn = get_db_connection()
    if not conn: return
    
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM guild_channels;")
    registered_guilds = cur.fetchall()
    cur.close()
    conn.close()

    if not registered_guilds:
        print("[TASK] No registered channels found.")
        return

    async with aiohttp.ClientSession() as session:
        token = await get_wcl_token(session)
        if not token:
            print("[ERROR] Task failed to get WCL token.")
            return
        
        latest_log = await get_latest_log(session, token)
        if not latest_log:
            print("[TASK] No new logs found on WCL.")
            return

        for guild_config in registered_guilds:
            if latest_log['code'] != guild_config['last_log_id']:
                print(f"[TASK] New log {latest_log['code']} for guild {guild_config['guild_id']}.")
                channel = client.get_channel(guild_config['channel_id'])
                if channel:
                    embed = discord.Embed(
                        title=f"New Raid Log: {latest_log['title']}",
                        url=f"https://www.warcraftlogs.com/reports/{latest_log['code']}",
                        description=f"Uploaded by **{latest_log['owner']['name']}**.",
                        timestamp=datetime.fromtimestamp(latest_log['startTime'] / 1000, tz=timezone.utc)
                    )
                    view = LogButtonsView()
                    await channel.send(embed=embed, view=view)
                    
                    conn_update = get_db_connection()
                    if not conn_update: continue
                    with conn_update.cursor() as cur_update:
                        cur_update.execute(
                            "UPDATE guild_channels SET last_log_id = %s WHERE guild_id = %s;",
                            (latest_log['code'], guild_config['guild_id'])
                        )
                    conn_update.commit()
                    conn_update.close()

# --- Bot Startup Event ---
@client.event
async def on_ready():
    print("--- BOT STARTING UP ---")
    setup_database()
    
    if not hasattr(client, 'added_view'):
        client.add_view(LogButtonsView())
        client.added_view = True
        print("[SETUP] Persistent view registered.")

    await tree.sync()
    print("[SETUP] Commands synced globally.")
    
    if not check_for_new_logs.is_running():
        check_for_new_logs.start()
        print("[SETUP] Background task started.")
        
    print(f'--- BOT READY --- Logged in as {client.user}')

# --- Slash Commands ---
@tree.command(name="set_log_channel", description="Sets this channel for automatic Warcraft Log posts.")
@app_commands.default_permissions(manage_guild=True)
async def set_log_channel(interaction: discord.Interaction):
    print(f"[CMD] /set_log_channel used by {interaction.user} in guild {interaction.guild.id}")
    await interaction.response.defer(ephemeral=True)
    
    guild_id = interaction.guild.id
    channel_id = interaction.channel.id
    
    conn = get_db_connection()
    if not conn:
        await send_ephemeral_with_auto_delete(interaction, content="❌ Error: Could not connect to the database.")
        return

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO guild_channels (guild_id, channel_id, last_log_id)
            VALUES (%s, %s, %s) ON CONFLICT (guild_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id, last_log_id = EXCLUDED.last_log_id;
        """, (guild_id, channel_id, ''))
    
    conn.commit()
    conn.close()
    
    await send_ephemeral_with_auto_delete(interaction, content="✅ Done! This channel will now receive Warcraft Logs updates.")
    print(f"[SETUP] Channel {channel_id} registered for guild {guild_id}.")

@tree.command(name="warcraftrecorder", description="Adds a user's email to the Warcraft Recorder roster.")
async def warcraftrecorder(interaction: discord.Interaction, email: str):
    try:
        # 1. Send the initial message immediately. This acts as your acknowledgement.
        await interaction.response.send_message(
            f"⏳ Attempting to add `{email}` to the roster. This may take a moment...",
            ephemeral=True
        )

        # 2. Run the slow Selenium script in a background thread
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            add_email_to_roster,
            RECORDER_EMAIL, RECORDER_PASSWORD, email
        )

        # 3. Edit the original message with the final result
        if result is True:
            await interaction.edit_original_response(content=f"✅ Successfully added `{email}` to the roster.")
        else:
            await interaction.edit_original_response(content=f"❌ **Error:** {result}")

    except Exception as e:
        print(f"An exception occurred in the command handler: {e}")
        # Use edit_original_response if the initial message was already sent
        if interaction.response.is_done():
            await interaction.edit_original_response(content="A critical error occurred after the initial response.")
# --- Main Execution Block ---
if __name__ == "__main__":
    if not all([BOT_TOKEN, WCL_CLIENT_ID, WCL_CLIENT_SECRET, DATABASE_URL]):
        print("[FATAL] One or more essential environment variables are missing.")
        print("[FATAL] Please check your .env file or environment configuration.")
    else:
        print("--- SCRIPT LAUNCH ---")
        server_thread = Thread(target=run_web_server)
        server_thread.start()
        
        # Add retry logic for Discord connection issues
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"[DEBUG] Starting Discord bot (attempt {attempt + 1}/{max_retries})...")
                client.run(BOT_TOKEN)
                break  # If we get here, the bot started successfully
            except aiohttp.client_exceptions.WSServerHandshakeError as e:
                print(f"[ERROR] Discord WebSocket handshake failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    print(f"[DEBUG] Retrying in 5 seconds...")
                    time.sleep(5)
                else:
                    print(f"[FATAL] Failed to connect to Discord after {max_retries} attempts.")
                    print(f"[FATAL] This is usually a temporary Discord service issue. Try again later.")
            except Exception as e:
                print(f"[ERROR] Unexpected error starting bot (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    print(f"[DEBUG] Retrying in 5 seconds...")
                    time.sleep(5)
                else:
                    print(f"[FATAL] Failed to start bot after {max_retries} attempts: {e}")
                    raise
