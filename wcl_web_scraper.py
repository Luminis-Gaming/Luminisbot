# wcl_web_scraper.py
# Web scraping functionality for WCL data

import asyncio
import os
import re
from http.cookies import SimpleCookie

import aiohttp
from bs4 import BeautifulSoup
from yarl import URL

WCL_ORIGIN = URL('https://www.warcraftlogs.com')
DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'

# Cookie jar shared across scrapes. Seeded from WCL_SCRAPE_COOKIES on first use, then kept
# up to date from WCL's Set-Cookie responses so a rotated wcl_session keeps working without
# anyone touching the env var. The remember_web_* cookie re-authenticates when the session dies.
_browser_jar = None


def _scrape_cookies():
    """Raw Cookie header copied from a browser session that has passed WCL's human check."""
    return (os.getenv('WCL_SCRAPE_COOKIES') or '').strip()


def _scrape_user_agent():
    """Should match the browser the cookies came from - Cloudflare ties clearance to the UA."""
    return (os.getenv('WCL_SCRAPE_USER_AGENT') or '').strip() or DEFAULT_USER_AGENT


def scrape_configured():
    """True when a browser session is configured, so scraping has a chance of working."""
    return bool(_scrape_cookies())


def _get_browser_jar():
    global _browser_jar
    if _browser_jar is None:
        cookie = SimpleCookie()
        for part in _scrape_cookies().split(';'):
            if '=' in part:
                key, value = part.strip().split('=', 1)
                cookie[key] = value
        _browser_jar = aiohttp.CookieJar()
        _browser_jar.update_cookies(cookie, response_url=WCL_ORIGIN)
        print(f"[DEBUG] Seeded WCL browser session with {len(cookie)} cookies")
    return _browser_jar


def _is_bot_challenge(url, html_content):
    """
    Detect WCL's human-verification page and Cloudflare's interstitial, both of
    which are served with HTTP 200 and would otherwise parse as "no data".
    """
    if 'human-challenge' in (url or ''):
        return True
    markers = ('Just a moment...', 'challenges.cloudflare.com', 'cf-challenge', '__cf_chl')
    return any(marker in html_content for marker in markers)


def _table_url(metric_type, report_code, fight_id, start_time, end_time):
    return (f"https://www.warcraftlogs.com/reports/table/{metric_type}/{report_code}/{fight_id}/"
            f"{start_time}/{end_time}/source/0/0/0/0/0/0/-1.0.-1.-1/-1/Any/Any/0/3014")


def _ajax_headers(main_page_url, user_agent):
    return {
        'User-Agent': user_agent,
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


async def _handle_table_response(table_response):
    """Validate the table endpoint response and parse it. Returns {} on any problem."""
    if table_response.status != 200:
        print(f"[ERROR] Table endpoint failed with status {table_response.status}")
        return {}

    html_content = await table_response.text()

    if _is_bot_challenge(str(table_response.url), html_content):
        if scrape_configured():
            print("[WARN] WCL rejected the configured browser session (bot challenge). "
                  "Refresh WCL_SCRAPE_COOKIES from a logged-in browser and restart the bot.")
        else:
            print("[DEBUG] Table endpoint served a bot challenge - set WCL_SCRAPE_COOKIES to enable scraping")
        return {}

    if "Use the API at /v1/docs instead of scraping HTML" in html_content:
        print("[DEBUG] Got anti-scraping message from table endpoint")
        return {}

    if len(html_content) < 500:
        print("[DEBUG] Table endpoint response too short, likely not valid data")
        return {}

    return await parse_table_response(html_content)


async def _scrape_with_browser_session(report_code, fight_id, start_time, end_time, metric_type, main_page_url):
    """Fetch the table using the stored browser session (see _browser_jar)."""
    table_url = _table_url(metric_type, report_code, fight_id, start_time, end_time)
    headers = _ajax_headers(main_page_url, _scrape_user_agent())

    async with aiohttp.ClientSession(cookie_jar=_get_browser_jar()) as session:
        async with session.get(table_url, headers=headers, allow_redirects=True) as table_response:
            return await _handle_table_response(table_response)


async def _scrape_anonymously(session, report_code, fight_id, start_time, end_time, metric_type, main_page_url):
    """
    Original two-step flow: load the report page for a session cookie, then call the
    table endpoint. Kept for when WCL isn't challenging anonymous traffic.
    """
    initial_headers = {
        'User-Agent': DEFAULT_USER_AGENT,
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

    async with session.get(main_page_url, headers=initial_headers, allow_redirects=True) as initial_response:
        if initial_response.status != 200:
            print(f"[ERROR] Failed to get initial page, status: {initial_response.status}")
            return {}

        if _is_bot_challenge(str(initial_response.url), await initial_response.text()):
            print("[DEBUG] Main page served a bot challenge - set WCL_SCRAPE_COOKIES to enable scraping")
            return {}

        print(f"[DEBUG] Successfully loaded main page: {main_page_url}")

    cookies = {c.key: c.value for c in session.cookie_jar if c.key in ('wcl_session', 'XSRF-TOKEN')}
    if not cookies.get('wcl_session') or not cookies.get('XSRF-TOKEN'):
        print("[ERROR] Failed to extract required cookies")
        return {}

    await asyncio.sleep(1)  # Small delay to mimic human behavior

    table_url = _table_url(metric_type, report_code, fight_id, start_time, end_time)
    async with session.get(table_url, headers=_ajax_headers(main_page_url, DEFAULT_USER_AGENT), allow_redirects=True) as table_response:
        return await _handle_table_response(table_response)


async def scrape_wcl_web_data(session, report_code, fight_id, start_time, end_time, encounter_id, metric):
    """
    Scrape parse/ilvl percentages from the WCL website. Used when the GraphQL API has no
    rankings for a fight (wipes). Prefers a configured browser session (WCL_SCRAPE_COOKIES),
    otherwise tries anonymously.
    """
    print(f"[DEBUG] Scraping WCL web data for fight {fight_id}")

    metric_type = "damage-done" if metric == "dps" else "healing"
    main_page_url = f"https://www.warcraftlogs.com/reports/{report_code}?fight={fight_id}&type={metric_type}"
    print(f"[DEBUG] Scraping URL: {main_page_url}")

    try:
        if scrape_configured():
            return await _scrape_with_browser_session(report_code, fight_id, start_time, end_time, metric_type, main_page_url)
        return await _scrape_anonymously(session, report_code, fight_id, start_time, end_time, metric_type, main_page_url)
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
