# wcl_web_scraper.py
# Web scraping functionality for WCL data

import asyncio
import re
from bs4 import BeautifulSoup


def _is_bot_challenge(url, html_content):
    """
    Detect WCL's human-verification page and Cloudflare's interstitial, both of
    which are served with HTTP 200 and would otherwise parse as "no data".
    """
    if 'human-challenge' in (url or ''):
        return True
    markers = ('Just a moment...', 'challenges.cloudflare.com', 'cf-challenge', '__cf_chl')
    return any(marker in html_content for marker in markers)


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
            
            if _is_bot_challenge(str(initial_response.url), await initial_response.text()):
                print("[DEBUG] Main page served a bot challenge - HTML scraping is blocked")
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

                if _is_bot_challenge(str(table_response.url), html_content):
                    print("[DEBUG] Table endpoint served a bot challenge - HTML scraping is blocked")
                    return {}

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
