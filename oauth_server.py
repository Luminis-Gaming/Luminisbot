async def handle_unlink(request):
    """
    /unlink endpoint - allows a user to unlink and delete all their WoW data
    Query params: discord_id (required), confirm (optional, must be 'yes' to actually delete)
    """
    discord_id = request.query.get('discord_id')
    confirm = request.query.get('confirm')
    if not discord_id:
        return web.Response(text="Error: Missing discord_id parameter", status=400)

    if confirm != 'yes':
        # Show confirmation page
        return web.Response(
            text=f"""
            <html>
            <head><title>Unlink & Delete Data</title></head>
            <body style='font-family: Arial; text-align: center; padding: 50px;'>
                <h1>⚠️ Unlink & Delete Data</h1>
                <p>This will <b>permanently delete</b> your Battle.net connection and all stored WoW character data for Discord user <code>{discord_id}</code>.</p>
                <form method='get' action='/unlink'>
                    <input type='hidden' name='discord_id' value='{discord_id}' />
                    <input type='hidden' name='confirm' value='yes' />
                    <button type='submit' style='padding: 10px 30px; font-size: 1.2em; background: #c00; color: #fff; border: none; border-radius: 5px;'>Yes, delete everything</button>
                </form>
                <p style='margin-top: 30px;'><a href='/'>Cancel</a></p>
            </body>
            </html>
            """,
            content_type='text/html'
        )

    # Actually delete data
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM wow_characters WHERE discord_id = %s", (discord_id,))
        cursor.execute("DELETE FROM wow_connections WHERE discord_id = %s", (discord_id,))
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"[Unlink] Deleted all data for Discord user {discord_id}")
        return web.Response(
            text=f"""
            <html>
            <head><title>Data Deleted</title></head>
            <body style='font-family: Arial; text-align: center; padding: 50px;'>
                <h1>✅ Data Deleted</h1>
                <p>Your Battle.net connection and all WoW character data have been deleted.</p>
                <p>You can now close this window or return to Discord.</p>
            </body>
            </html>
            """,
            content_type='text/html'
        )
    except Exception as e:
        logger.error(f"[Unlink] Error deleting data for {discord_id}: {e}")
        return web.Response(text="Error deleting data", status=500)
"""
OAuth Web Server for Battle.net Integration
Handles OAuth2 authorization flow for linking Discord users to WoW characters
"""

import os
import secrets
import asyncio
import aiohttp
from aiohttp import web
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
BLIZZARD_CLIENT_ID = os.getenv('BLIZZARD_CLIENT_ID')
BLIZZARD_CLIENT_SECRET = os.getenv('BLIZZARD_CLIENT_SECRET')
BLIZZARD_REDIRECT_URI = os.getenv('BLIZZARD_REDIRECT_URI', 'https://luminisbot.flipflix.no/callback')
OAUTH_STATE_SECRET = os.getenv('OAUTH_STATE_SECRET', secrets.token_urlsafe(32))

# Database connection
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'luminisbot')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD')

# Blizzard API endpoints (EU region)
BLIZZARD_OAUTH_AUTHORIZE = "https://oauth.battle.net/authorize"
BLIZZARD_OAUTH_TOKEN = "https://oauth.battle.net/token"
BLIZZARD_API_BASE = "https://eu.api.blizzard.com"

# Discord bot reference (for sending notifications)
discord_bot = None


class BattleNetAuthError(Exception):
    """Raised when Battle.net API returns an authorization error (403)"""
    pass


def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


async def handle_authorize(request):
    """
    /authorize endpoint - generates OAuth URL and redirects user to Battle.net
    Query params: discord_id (required)
    """
    discord_id = request.query.get('discord_id')
    
    if not discord_id:
        return web.Response(
            text="Error: Missing discord_id parameter",
            status=400
        )
    
    # Generate secure state token
    state = secrets.token_urlsafe(32)
    
    # Store state in database with discord_id
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Clean up old states (older than 10 minutes)
        cursor.execute("""
            DELETE FROM oauth_states 
            WHERE created_at < NOW() - INTERVAL '10 minutes'
        """)
        
        # Insert new state
        cursor.execute("""
            INSERT INTO oauth_states (state_token, discord_id, created_at)
            VALUES (%s, %s, NOW())
        """, (state, discord_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Generated OAuth state for Discord user {discord_id}")
        
    except Exception as e:
        logger.error(f"Database error storing state: {e}")
        return web.Response(text="Database error", status=500)
    
    # Build Battle.net OAuth URL
    oauth_url = (
        f"{BLIZZARD_OAUTH_AUTHORIZE}"
        f"?client_id={BLIZZARD_CLIENT_ID}"
        f"&redirect_uri={BLIZZARD_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=wow.profile"
        f"&state={state}"
        f"&prompt=consent"  # Force re-authorization even if previously authorized
    )
    
    # Redirect user to Battle.net authorization page
    raise web.HTTPFound(oauth_url)


async def handle_callback(request):
    """
    /callback endpoint - receives authorization code from Battle.net
    Query params: code, state
    """
    code = request.query.get('code')
    state = request.query.get('state')
    error = request.query.get('error')
    
    # Handle authorization errors
    if error:
        logger.error(f"OAuth error: {error}")
        return web.Response(
            text=f"Authorization failed: {error}. You can close this window.",
            content_type='text/html',
            status=400
        )
    
    if not code or not state:
        return web.Response(
            text="Error: Missing code or state parameter",
            status=400
        )
    
    # Verify state and get discord_id
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT discord_id 
            FROM oauth_states 
            WHERE state_token = %s 
            AND created_at > NOW() - INTERVAL '10 minutes'
        """, (state,))
        
        result = cursor.fetchone()
        
        if not result:
            cursor.close()
            conn.close()
            return web.Response(
                text="Error: Invalid or expired state token",
                status=400
            )
        
        discord_id = result['discord_id']
        
        # Delete used state token
        cursor.execute("DELETE FROM oauth_states WHERE state_token = %s", (state,))
        conn.commit()
        cursor.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"Database error verifying state: {e}")
        return web.Response(text="Database error", status=500)
    
    # Exchange authorization code for access token
    try:
        async with aiohttp.ClientSession() as session:
            token_data = {
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': BLIZZARD_REDIRECT_URI
            }
            
            auth = aiohttp.BasicAuth(BLIZZARD_CLIENT_ID, BLIZZARD_CLIENT_SECRET)
            
            async with session.post(BLIZZARD_OAUTH_TOKEN, data=token_data, auth=auth) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Token exchange failed: {error_text}")
                    return web.Response(
                        text="Failed to exchange authorization code",
                        status=500
                    )
                
                token_response = await resp.json()
                access_token = token_response['access_token']
                
        # Log token details for debugging (without exposing the actual token)
        logger.info(f"Successfully obtained access token for Discord user {discord_id}")
        logger.debug(f"Token response keys: {list(token_response.keys())}")
        if 'scope' in token_response:
            logger.info(f"Token scope for user {discord_id}: {token_response['scope']}")
        
    except Exception as e:
        logger.error(f"Error exchanging code for token: {e}")
        return web.Response(text="Token exchange error", status=500)
    
    # Fetch WoW account and character data
    try:
        characters = await fetch_wow_characters(access_token)
        
        if not characters:
            return web.Response(
                text="No WoW characters found on your account. You can close this window.",
                content_type='text/html'
            )
        
        # Store characters in database
        await store_characters(discord_id, characters, access_token)
        
        logger.info(f"Stored {len(characters)} characters for Discord user {discord_id}")
        
        # Send success notification to Discord (if bot is available)
        if discord_bot:
            asyncio.create_task(notify_user_success(discord_id, len(characters)))
        
        # Return success page
        return web.Response(
            text=f"""
            <html>
            <head><title>Success!</title></head>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1>✅ Successfully Connected!</h1>
                <p>Linked {len(characters)} WoW character(s) to your Discord account.</p>
                <p>You can now close this window and return to Discord.</p>
                <p>Use <code>/mycharacters</code> to view your linked characters.</p>
            </body>
            </html>
            """,
            content_type='text/html'
        )
    
    except BattleNetAuthError as e:
        logger.error(f"Battle.net authorization error for Discord user {discord_id}: {e}")
        
        # Clean up any existing connection for this user so they can retry
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Delete any existing connection and characters
            cursor.execute("DELETE FROM wow_characters WHERE discord_id = %s", (discord_id,))
            cursor.execute("DELETE FROM wow_connections WHERE discord_id = %s", (discord_id,))
            
            conn.commit()
            cursor.close()
            conn.close()
            logger.info(f"Cleaned up failed connection for Discord user {discord_id}")
        except Exception as cleanup_error:
            logger.error(f"Error cleaning up failed connection: {cleanup_error}")
        
        # Return user-friendly error message
        return web.Response(
            text="""
            <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1>⚠️ Authorization Failed</h1>
                <p>Battle.net rejected the authorization (Error 403).</p>
                <p>This usually happens when:</p>
                <ul style="text-align: left; max-width: 500px; margin: 20px auto;">
                    <li>Your Battle.net account doesn't have active WoW game time</li>
                    <li>The authorization has expired or been revoked</li>
                    <li>There's a temporary issue with Battle.net services</li>
                </ul>
                <p><strong>Please try the following:</strong></p>
                <ol style="text-align: left; max-width: 500px; margin: 20px auto;">
                    <li>Make sure you have an active WoW subscription</li>
                    <li>Return to Discord and use <code>/connectwow</code> again</li>
                    <li>If the problem persists, contact a server administrator</li>
                </ol>
                <p>You can close this window.</p>
            </body>
            </html>
            """,
            content_type='text/html',
            status=403
        )
        
    except Exception as e:
        logger.error(f"Error fetching/storing characters: {e}")
        return web.Response(
            text=f"Error fetching character data: {str(e)}",
            status=500
        )


async def fetch_wow_characters(access_token):
    """Fetch WoW characters from Battle.net API (supports all regions)"""
    characters = []
    
    try:
        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {access_token}'}
            
            # First, get user info to determine their region
            region = 'eu'  # Default to EU
            try:
                async with session.get(
                    'https://eu.battle.net/oauth/userinfo',
                    headers=headers
                ) as userinfo_resp:
                    if userinfo_resp.status == 200:
                        userinfo = await userinfo_resp.json()
                        # Battle.net userinfo doesn't directly provide region, so we'll try all regions
                        logger.debug(f"User info: {userinfo}")
            except Exception as e:
                logger.warning(f"Could not fetch userinfo: {e}")
            
            # Try all regions to find where the user has WoW characters
            regions = ['eu', 'us', 'kr', 'tw', 'cn']
            api_endpoints = {
                'eu': 'https://eu.api.blizzard.com',
                'us': 'https://us.api.blizzard.com',
                'kr': 'https://kr.api.blizzard.com',
                'tw': 'https://tw.api.blizzard.com',
                'cn': 'https://gateway.battlenet.com.cn'
            }
            
            regions_with_characters = []
            all_403_errors = True  # Track if ALL regions returned 403
            
            # Check ALL regions and collect characters from each
            for region in regions:
                api_base = api_endpoints.get(region, api_endpoints['eu'])
                namespace = f'profile-{region}'
                url = f"{api_base}/profile/user/wow"
                masked_token = access_token[:6] + "..." + access_token[-4:] if len(access_token) > 10 else "***"
                logger.info(f"[BlizzOAuth] Trying region '{region}' URL: {url} with token: {masked_token}")
                try:
                    async with session.get(
                        url,
                        headers=headers,
                        params={'namespace': namespace, 'locale': 'en_US'},
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        resp_text = await resp.text()
                        logger.info(f"[BlizzOAuth] Region {region} status: {resp.status}")
                        logger.debug(f"[BlizzOAuth] Region {region} response body: {resp_text}")
                        
                        if resp.status == 200:
                            all_403_errors = False  # At least one region didn't return 403
                            try:
                                profile_data = await resp.json()
                            except Exception as e:
                                logger.error(f"[BlizzOAuth] Failed to parse JSON for region {region}: {e}")
                                continue
                            
                            wow_accounts = profile_data.get('wow_accounts')
                            if wow_accounts is None:
                                logger.warning(f"[BlizzOAuth] Region {region}: 'wow_accounts' missing in response!")
                            elif not wow_accounts:
                                logger.info(f"[BlizzOAuth] Region {region}: 'wow_accounts' is an empty list.")
                            else:
                                # Check if any account has characters
                                total_chars = sum(len(acc.get('characters', [])) for acc in wow_accounts)
                                if total_chars == 0:
                                    logger.info(f"[BlizzOAuth] Region {region}: All wow_accounts have 0 characters.")
                                else:
                                    logger.info(f"[BlizzOAuth] Found WoW profile in region: {region} with {total_chars} characters.")
                                    regions_with_characters.append({'region': region, 'data': profile_data})
                        elif resp.status == 403:
                            logger.warning(f"[BlizzOAuth] Region {region}: 403 Forbidden - {resp_text}")
                        elif resp.status == 404:
                            all_403_errors = False  # 404 is different from 403
                            logger.info(f"[BlizzOAuth] Region {region}: No WoW profile found (404)")
                        else:
                            all_403_errors = False
                            logger.info(f"[BlizzOAuth] Region {region}: Status {resp.status} - {resp_text}")
                except asyncio.TimeoutError:
                    all_403_errors = False
                    logger.warning(f"[BlizzOAuth] Region {region}: Request timeout")
                except Exception as e:
                    all_403_errors = False
                    logger.error(f"[BlizzOAuth] Region {region}: Error - {e}")
            
            # If we didn't find any characters in any region, raise an error
            if not regions_with_characters:
                if all_403_errors:
                    logger.error("[BlizzOAuth] Failed to fetch WoW profile: 403 in all regions")
                    raise BattleNetAuthError("Could not access WoW profile - please ensure you have an active WoW subscription and game time")
                else:
                    logger.error("[BlizzOAuth] Failed to fetch WoW profile: No characters found in any region")
                    raise BattleNetAuthError("No WoW characters found in any region")

            # Process characters from ALL regions that had them
            char_count = 0
            for region_info in regions_with_characters:
                region = region_info['region']
                profile_data = region_info['data']
                
                for wow_account in profile_data.get('wow_accounts', []):
                    chars = wow_account.get('characters', [])
                    if not chars:
                        logger.info(f"[BlizzOAuth] Account in region {region} has 0 characters: {wow_account}")
                    for character in chars:
                        char_info = {
                            'name': character.get('name'),
                            'realm': character.get('realm', {}).get('name'),
                            'realm_slug': character.get('realm', {}).get('slug'),
                            'level': character.get('level'),
                            'playable_class': character.get('playable_class', {}).get('name'),
                            'playable_race': character.get('playable_race', {}).get('name'),
                            'faction': character.get('faction', {}).get('type'),
                            'character_id': character.get('id'),
                            'region': region
                        }
                        characters.append(char_info)
                        char_count += 1
            
            regions_found = [r['region'] for r in regions_with_characters]
            if char_count == 0:
                logger.warning(f"[BlizzOAuth] Fetched 0 characters from Battle.net API (regions checked: {regions_found}). This means the API returned no characters in the response.")
            else:
                logger.info(f"[BlizzOAuth] Fetched {char_count} characters from Battle.net API across {len(regions_with_characters)} region(s): {regions_found}")
            return characters

    except Exception as e:
        logger.error(f"[BlizzOAuth] Error in fetch_wow_characters: {e}")
        raise


async def store_characters(discord_id, characters, access_token):
    """Store characters in database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update or insert wow_connections
        cursor.execute("""
            INSERT INTO wow_connections (discord_id, access_token, last_updated)
            VALUES (%s, %s, NOW())
            ON CONFLICT (discord_id) 
            DO UPDATE SET 
                access_token = EXCLUDED.access_token,
                last_updated = NOW()
        """, (discord_id, access_token))
        
        # Delete old characters for this user
        cursor.execute("DELETE FROM wow_characters WHERE discord_id = %s", (discord_id,))
        
        # Insert new characters
        for char in characters:
            cursor.execute("""
                INSERT INTO wow_characters (
                    discord_id, character_name, realm_name, realm_slug,
                    character_class, character_race, faction, level, character_id, region
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                discord_id,
                char['name'],
                char['realm'],
                char['realm_slug'],
                char['playable_class'],
                char['playable_race'],
                char['faction'],
                char['level'],
                char['character_id'],
                char.get('region', 'eu')
            ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"Error storing characters: {e}")
        raise


async def notify_user_success(discord_id, character_count):
    """Send success message to user in Discord (if bot is available)"""
    if not discord_bot:
        return
    
    try:
        user = await discord_bot.fetch_user(int(discord_id))
        await user.send(
            f"✅ Successfully linked {character_count} WoW character(s) to your Discord account!\n"
            f"Use `/mycharacters` to view them."
        )
    except Exception as e:
        logger.error(f"Could not send Discord notification: {e}")


async def handle_health(request):
    """Health check endpoint"""
    return web.Response(text="OK")


# ============================================================================
# API KEY AUTHENTICATION & RATE LIMITING
# ============================================================================

# In-memory rate limiting (use Redis in production for multi-instance deployments)
from collections import defaultdict
from time import time

rate_limit_data = defaultdict(list)
RATE_LIMIT_REQUESTS = 60  # requests
RATE_LIMIT_WINDOW = 60  # seconds

def check_rate_limit(identifier):
    """Check if identifier has exceeded rate limit"""
    now = time()
    # Clean old requests
    rate_limit_data[identifier] = [
        req_time for req_time in rate_limit_data[identifier] 
        if now - req_time < RATE_LIMIT_WINDOW
    ]
    
    # Check limit
    if len(rate_limit_data[identifier]) >= RATE_LIMIT_REQUESTS:
        return False
    
    # Add current request
    rate_limit_data[identifier].append(now)
    return True


def generate_api_key():
    """Generate a secure API key"""
    return secrets.token_urlsafe(32)


async def verify_api_key(request):
    """Middleware to verify API key"""
    # Get API key from header
    api_key = request.headers.get('X-API-Key')
    
    if not api_key:
        return web.json_response(
            {'error': 'Missing API key', 'message': 'X-API-Key header required'},
            status=401
        )
    
    # Verify API key in database
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT discord_user_id, guild_id, is_active, created_at, last_used
            FROM api_keys
            WHERE key_hash = %s AND is_active = true
        """, (api_key,))
        
        result = cursor.fetchone()
        
        if not result:
            cursor.close()
            conn.close()
            return web.json_response(
                {'error': 'Invalid API key'},
                status=401
            )
        
        discord_user_id = result['discord_user_id']
        guild_id = result['guild_id']
        
        # Verify user has connected their Battle.net account
        cursor.execute("""
            SELECT discord_id FROM wow_connections WHERE discord_id = %s
        """, (discord_user_id,))
        
        connection = cursor.fetchone()
        
        if not connection:
            cursor.close()
            conn.close()
            return web.json_response(
                {'error': 'Battle.net account not connected', 'message': 'Please connect your Battle.net account using /connectwow in Discord'},
                status=403
            )
        
        # Update last_used timestamp
        cursor.execute("""
            UPDATE api_keys 
            SET last_used = NOW(), request_count = request_count + 1
            WHERE key_hash = %s
        """, (api_key,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # Rate limiting
        if not check_rate_limit(api_key):
            return web.json_response(
                {'error': 'Rate limit exceeded', 'message': f'Max {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW}s'},
                status=429
            )
        
        # Store user and guild info in request for later use
        request['discord_user_id'] = discord_user_id
        request['guild_id'] = guild_id
        request['api_key'] = api_key
        
        return None  # Success, continue to handler
        
    except Exception as e:
        logger.error(f"Error verifying API key: {e}")
        return web.json_response(
            {'error': 'Internal server error'},
            status=500
        )


# ============================================================================
# API ENDPOINTS FOR WOW ADDON
# ============================================================================

async def handle_get_events(request):
    """
    GET /api/v1/events
    Returns all future events for the guild associated with the API key
    """
    # Verify API key
    auth_error = await verify_api_key(request)
    if auth_error:
        return auth_error
    
    guild_id = request['guild_id']
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get all future events for this guild
        cursor.execute("""
            SELECT DISTINCT ON (e.id)
                e.id,
                e.title,
                e.event_date,
                e.event_time,
                e.created_by,
                e.created_at,
                wc.character_name as owner_character
            FROM raid_events e
            LEFT JOIN LATERAL (
                SELECT character_name
                FROM wow_characters
                WHERE discord_id = e.created_by::text
                LIMIT 1
            ) wc ON true
            WHERE e.guild_id = %s
                AND e.event_date >= CURRENT_DATE
            ORDER BY e.id, e.event_date, e.event_time
        """, (guild_id,))
        
        events = cursor.fetchall()
        
        # For each event, get signups
        result = []
        for event in events:
            cursor.execute("""
                SELECT 
                    rs.character_name as character,
                    wc.realm_slug as realm,
                    rs.character_class as class,
                    rs.role,
                    rs.spec,
                    rs.status
                FROM raid_signups rs
                LEFT JOIN wow_characters wc ON 
                    rs.discord_id = wc.discord_id 
                    AND rs.character_name = wc.character_name
                WHERE rs.event_id = %s
                ORDER BY 
                    CASE rs.status
                        WHEN 'signed' THEN 1
                        WHEN 'late' THEN 2
                        WHEN 'tentative' THEN 3
                        WHEN 'benched' THEN 4
                        WHEN 'absent' THEN 5
                    END,
                    rs.role, rs.character_class, rs.character_name
            """, (event['id'],))
            
            signups = cursor.fetchall()
            
            # Deduplicate signups by character name (keep first occurrence)
            seen_characters = set()
            unique_signups = []
            for signup in signups:
                char_key = signup['character'].lower() if signup['character'] else ''
                if char_key and char_key not in seen_characters:
                    seen_characters.add(char_key)
                    unique_signups.append(dict(signup))
            
            result.append({
                'id': event['id'],
                'title': event['title'],
                'date': event['event_date'].isoformat(),
                'time': event['event_time'].strftime('%H:%M:%S'),
                'created_by': event['created_by'],
                'owner_character': event.get('owner_character'),
                'signups': unique_signups
            })
        
        cursor.close()
        conn.close()
        
        logger.info(f"API: Returned {len(result)} events for guild {guild_id}")
        
        return web.json_response({
            'success': True,
            'count': len(result),
            'events': result,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error fetching events: {e}")
        return web.json_response(
            {'success': False, 'error': 'Internal server error'},
            status=500
        )


async def handle_get_single_event(request):
    """
    GET /api/v1/events/{event_id}
    Returns a single event with all signups
    """
    # Verify API key
    auth_error = await verify_api_key(request)
    if auth_error:
        return auth_error
    
    guild_id = request['guild_id']
    event_id = request.match_info.get('event_id')
    
    try:
        event_id = int(event_id)
    except (ValueError, TypeError):
        return web.json_response(
            {'success': False, 'error': 'Invalid event ID'},
            status=400
        )
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get event (verify it belongs to this guild)
        cursor.execute("""
            SELECT 
                e.id,
                e.title,
                e.event_date,
                e.event_time,
                e.created_by,
                wc.character_name as owner_character
            FROM raid_events e
            LEFT JOIN LATERAL (
                SELECT character_name
                FROM wow_characters
                WHERE discord_id = e.created_by::text
                LIMIT 1
            ) wc ON true
            WHERE e.id = %s AND e.guild_id = %s
        """, (event_id, guild_id))
        
        event = cursor.fetchone()
        
        if not event:
            cursor.close()
            conn.close()
            return web.json_response(
                {'success': False, 'error': 'Event not found or unauthorized'},
                status=404
            )
        
        # Get signups
        cursor.execute("""
            SELECT 
                rs.character_name as character,
                wc.realm_slug as realm,
                rs.character_class as class,
                rs.role,
                rs.spec,
                rs.status
            FROM raid_signups rs
            LEFT JOIN wow_characters wc ON 
                rs.discord_id = wc.discord_id 
                AND rs.character_name = wc.character_name
            WHERE rs.event_id = %s
            ORDER BY rs.role, rs.character_class, rs.character_name
        """, (event_id,))
        
        signups = cursor.fetchall()
        
        # Deduplicate signups by character name (keep first occurrence)
        seen_characters = set()
        unique_signups = []
        for signup in signups:
            char_key = signup['character'].lower() if signup['character'] else ''
            if char_key and char_key not in seen_characters:
                seen_characters.add(char_key)
                unique_signups.append(dict(signup))
        
        cursor.close()
        conn.close()
        
        result = {
            'id': event['id'],
            'title': event['title'],
            'date': event['event_date'].isoformat(),
            'time': event['event_time'].strftime('%H:%M:%S'),
            'created_by': event['created_by'],
            'owner_character': event.get('owner_character'),
            'signups': unique_signups
        }
        
        logger.info(f"API: Returned event {event_id} for guild {guild_id}")
        
        return web.json_response({
            'success': True,
            'event': result
        })
        
    except Exception as e:
        logger.error(f"Error fetching event: {e}")
        return web.json_response(
            {'success': False, 'error': 'Internal server error'},
            status=500
        )


async def handle_generate_api_key(request):
    """
    POST /api/v1/keys/generate
    Generate a new API key for a guild (requires admin verification)
    Body: { "guild_id": "123456789", "admin_token": "secret" }
    """
    try:
        data = await request.json()
    except:
        return web.json_response(
            {'error': 'Invalid JSON'},
            status=400
        )
    
    guild_id = data.get('guild_id')
    admin_token = data.get('admin_token')
    
    # Verify admin token (set in environment)
    ADMIN_TOKEN = os.getenv('API_ADMIN_TOKEN')
    if not ADMIN_TOKEN or admin_token != ADMIN_TOKEN:
        return web.json_response(
            {'error': 'Unauthorized'},
            status=401
        )
    
    if not guild_id:
        return web.json_response(
            {'error': 'Missing guild_id'},
            status=400
        )
    
    try:
        # Generate new API key
        api_key = generate_api_key()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Store API key
        cursor.execute("""
            INSERT INTO api_keys (guild_id, key_hash, is_active, created_at, request_count)
            VALUES (%s, %s, true, NOW(), 0)
            RETURNING id
        """, (guild_id, api_key))
        
        key_id = cursor.fetchone()[0]
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Generated new API key (ID: {key_id}) for guild {guild_id}")
        
        return web.json_response({
            'success': True,
            'api_key': api_key,
            'guild_id': guild_id,
            'message': 'Save this key securely - it cannot be retrieved later'
        })
        
    except Exception as e:
        logger.error(f"Error generating API key: {e}")
        return web.json_response(
            {'success': False, 'error': 'Internal server error'},
            status=500
        )


# Security: Block common probe/scan paths
BLOCKED_PATHS = {
    '.env', '.git', '.secrets', 'phpinfo', '.php', 'swagger', 
    'config.json', 'server.js', '.credentials', 'backup', 
    'wp-admin', 'phpmyadmin', 'mysql', '.sql'
}

@web.middleware
async def security_middleware(request, handler):
    """Block suspicious requests and common vulnerability scans"""
    path = request.path.lower()
    
    # Block requests for sensitive files/paths
    if any(blocked in path for blocked in BLOCKED_PATHS):
        logger.warning(f"[SECURITY] Blocked suspicious request from {request.remote}: {request.path}")
        return web.Response(text="Forbidden", status=403)
    
    # Only allow specific routes
    allowed_prefixes = ('/authorize', '/callback', '/health', '/unlink', '/api/v1/', '/admin', '/characters')
    if not any(path.startswith(prefix) for prefix in allowed_prefixes):
        logger.warning(f"[SECURITY] Invalid path from {request.remote}: {request.path}")
        return web.Response(text="Not Found", status=404)
    
    return await handler(request)


# CORS middleware for addon requests
@web.middleware
async def cors_middleware(request, handler):
    """Add CORS headers for WoW addon requests"""
    if request.path.startswith('/api/'):
        # Handle preflight
        if request.method == 'OPTIONS':
            return web.Response(
                headers={
                    'Access-Control-Allow-Origin': '*',
                    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                    'Access-Control-Allow-Headers': 'X-API-Key, Content-Type',
                    'Access-Control-Max-Age': '3600'
                }
            )
        
        # Handle actual request
        response = await handler(request)
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'X-API-Key, Content-Type'
        return response
    
    return await handler(request)


async def handle_update_signup(request):
    """
    POST /api/v1/events/{event_id}/signup
    Update or create a signup for an event
    """
    # Verify API key
    auth_error = await verify_api_key(request)
    if auth_error:
        return auth_error
    
    guild_id = request['guild_id']
    event_id = request.match_info.get('event_id')
    
    try:
        event_id = int(event_id)
    except (ValueError, TypeError):
        return web.json_response(
            {'success': False, 'error': 'Invalid event ID'},
            status=400
        )
    
    # Get request body
    try:
        data = await request.json()
    except Exception as e:
        return web.json_response(
            {'success': False, 'error': 'Invalid JSON'},
            status=400
        )
    
    character = data.get('character')
    realm = data.get('realm')
    status = data.get('status', 'signed')
    
    if not character:
        return web.json_response(
            {'success': False, 'error': 'Character name required'},
            status=400
        )
    
    # Get the discord_user_id from the API key (set by verify_api_key middleware)
    requester_discord_id = request.get('discord_user_id')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Verify event exists and belongs to this guild
        cursor.execute("""
            SELECT e.id, e.created_by
            FROM raid_events e
            WHERE e.id = %s AND e.guild_id = %s
        """, (event_id, guild_id))
        
        event = cursor.fetchone()
        if not event:
            cursor.close()
            conn.close()
            return web.json_response(
                {'success': False, 'error': 'Event not found or unauthorized'},
                status=404
            )
        
        # Get the requester's characters to determine who is making the change
        cursor.execute("""
            SELECT character_name 
            FROM wow_characters 
            WHERE discord_id = %s
        """, (requester_discord_id,))
        
        requester_characters = [row['character_name'] for row in cursor.fetchall()]
        
        # Authorization check: user can either:
        # 1. Change their own character's status (character belongs to their account)
        # 2. Change anyone's status if they're the event owner
        is_own_character = character in requester_characters
        is_event_owner = str(event['created_by']) == requester_discord_id
        
        if not is_own_character and not is_event_owner:
            cursor.close()
            conn.close()
            logger.warning(f"API: Unauthorized status change attempt by Discord user {requester_discord_id} for {character}")
            return web.json_response(
                {'success': False, 'error': 'You can only change your own character status or, if you created the event, manage other players'},
                status=403
            )
        
        # Find the signup by character name (since we don't have discord_id from addon)
        cursor.execute("""
            SELECT discord_id, character_class, role, spec
            FROM raid_signups
            WHERE event_id = %s AND LOWER(character_name) = LOWER(%s)
            LIMIT 1
        """, (event_id, character))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing signup status
            cursor.execute("""
                UPDATE raid_signups
                SET status = %s
                WHERE event_id = %s AND discord_id = %s
            """, (status, event_id, existing['discord_id']))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            logger.info(f"API: Updated signup for {character} to {status} on event {event_id}")
            
            # Trigger Discord bot to update event message
            if discord_bot:
                try:
                    from raid_system import refresh_event_embed
                    asyncio.create_task(refresh_event_embed(discord_bot, event_id))
                except Exception as e:
                    logger.error(f"Failed to refresh event embed: {e}")
            
            return web.json_response({
                'success': True,
                'message': f'Updated {character} status to {status}'
            })
        else:
            cursor.close()
            conn.close()
            return web.json_response(
                {'success': False, 'error': f'Character {character} not found in signups'},
                status=404
            )
            
    except Exception as e:
        logger.error(f"Error updating signup: {e}")
        return web.json_response(
            {'success': False, 'error': 'Internal server error'},
            status=500
        )


# ============================================================================
# Admin Panel - User Authentication & Management
# ============================================================================

import bcrypt

# Session storage for admin logins
admin_sessions = {}


def ensure_default_admin_exists():
    """Create default admin user if no users exist in the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if admin_users table exists and has any users
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'admin_users'
            );
        """)
        table_exists = cursor.fetchone()[0]
        
        if not table_exists:
            logger.info("[ADMIN] admin_users table doesn't exist yet, skipping default user creation")
            cursor.close()
            conn.close()
            return
        
        cursor.execute("SELECT COUNT(*) FROM admin_users")
        user_count = cursor.fetchone()[0]
        
        if user_count == 0:
            # Generate fresh bcrypt hash for 'admin'
            default_password = 'admin'
            password_hash = bcrypt.hashpw(default_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            
            cursor.execute("""
                INSERT INTO admin_users (username, password_hash, role, must_change_password, created_by)
                VALUES (%s, %s, 'admin', true, 'system')
            """, ('admin', password_hash))
            
            conn.commit()
            logger.info("[ADMIN] ✓ Created default admin user (username: admin, password: admin)")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"[ADMIN] Error ensuring default admin exists: {e}")


def generate_session_token():
    """Generate a secure session token"""
    return secrets.token_urlsafe(32)

def hash_password(password):
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password, password_hash):
    """Verify a password against its hash"""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False

def get_session(request):
    """Get session data from cookie, returns None if invalid/expired"""
    session_token = request.cookies.get('admin_session')
    if not session_token:
        return None
    
    session = admin_sessions.get(session_token)
    if not session:
        return None
    
    # Check if session is expired (24 hour expiry)
    if datetime.now() > session['expires']:
        del admin_sessions[session_token]
        return None
    
    return session

def require_auth(func):
    """Decorator to require authentication"""
    async def wrapper(request):
        session = get_session(request)
        if not session:
            raise web.HTTPFound('/admin/login')
        
        # Check if user must change password
        if session.get('must_change_password') and request.path != '/admin/change-password':
            raise web.HTTPFound('/admin/change-password')
        
        request['session'] = session
        return await func(request)
    return wrapper

def require_admin(func):
    """Decorator to require admin role"""
    async def wrapper(request):
        session = get_session(request)
        if not session:
            raise web.HTTPFound('/admin/login')
        
        if session.get('role') != 'admin':
            return web.Response(text="Access denied. Admin role required.", status=403)
        
        request['session'] = session
        return await func(request)
    return wrapper


# ============================================================================
# Shared CSS Styles
# ============================================================================

ADMIN_CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    min-height: 100vh;
    margin: 0;
    padding: 20px;
    color: #fff;
}
.container { max-width: 1400px; margin: 0 auto; }
.card {
    background: rgba(255,255,255,0.1);
    backdrop-filter: blur(10px);
    border-radius: 16px;
    padding: 30px;
    margin-bottom: 20px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
.card-center {
    max-width: 450px;
    margin: 80px auto;
    text-align: center;
}
h1, h2 { margin: 0 0 20px 0; }
.logo { font-size: 48px; margin-bottom: 20px; }
input[type="text"], input[type="password"], select {
    width: 100%;
    padding: 14px;
    border: 2px solid rgba(255,255,255,0.2);
    border-radius: 8px;
    background: rgba(255,255,255,0.1);
    color: #fff;
    font-size: 16px;
    margin-bottom: 15px;
}
input:focus, select:focus { outline: none; border-color: #5865F2; }
input::placeholder { color: rgba(255,255,255,0.5); }
.btn {
    padding: 14px 28px;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
    text-decoration: none;
    display: inline-block;
}
.btn-primary { background: #5865F2; color: #fff; }
.btn-primary:hover { background: #4752C4; }
.btn-secondary { background: rgba(255,255,255,0.1); color: #fff; }
.btn-secondary:hover { background: rgba(255,255,255,0.2); }
.btn-danger { background: #dc3545; color: #fff; }
.btn-danger:hover { background: #c82333; }
.btn-sm { padding: 8px 16px; font-size: 14px; }
.error { color: #ff6b6b; margin-bottom: 20px; }
.success { color: #51cf66; margin-bottom: 20px; }
.nav {
    display: flex;
    gap: 15px;
    margin-bottom: 30px;
    flex-wrap: wrap;
    align-items: center;
}
.nav a { color: #fff; text-decoration: none; padding: 10px 20px; border-radius: 8px; background: rgba(255,255,255,0.1); }
.nav a:hover { background: rgba(255,255,255,0.2); }
.nav a.active { background: #5865F2; }
.nav .spacer { flex: 1; }
.nav .user-info { color: rgba(255,255,255,0.7); font-size: 14px; }
table { width: 100%; border-collapse: collapse; }
th, td { padding: 14px 16px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.1); }
th { background: rgba(88,101,242,0.3); font-weight: 600; text-transform: uppercase; font-size: 12px; }
tr:hover { background: rgba(255,255,255,0.05); }
code { background: rgba(0,0,0,0.3); padding: 4px 8px; border-radius: 4px; font-size: 12px; }
.badge { padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }
.badge-admin { background: #5865F2; }
.badge-user { background: rgba(255,255,255,0.2); }
.stats { display: flex; gap: 20px; flex-wrap: wrap; }
.stat { background: rgba(255,255,255,0.1); padding: 20px; border-radius: 12px; text-align: center; min-width: 120px; }
.stat-value { font-size: 32px; font-weight: 700; color: #5865F2; }
.stat-label { font-size: 14px; color: rgba(255,255,255,0.7); margin-top: 5px; }
.form-group { margin-bottom: 20px; }
.form-group label { display: block; margin-bottom: 8px; font-weight: 500; }
.actions { display: flex; gap: 10px; }
.search-box { margin-bottom: 20px; }
.search-box input { max-width: 400px; }
.table-wrapper { overflow-x: auto; }
.warning-box { background: rgba(255,193,7,0.2); border: 1px solid #ffc107; border-radius: 8px; padding: 15px; margin-bottom: 20px; }
"""


async def handle_admin_login_page(request):
    """GET /admin/login - show login page"""
    error = request.query.get('error', '')
    error_html = f'<p class="error">{error}</p>' if error else ''
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>LuminisBot Admin - Login</title>
        <style>{ADMIN_CSS}</style>
    </head>
    <body>
        <div class="card card-center">
            <div class="logo">🔐</div>
            <h1>Admin Login</h1>
            {error_html}
            <form method="POST" action="/admin/login">
                <input type="text" name="username" placeholder="Username" required autofocus>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit" class="btn btn-primary" style="width:100%">Login</button>
            </form>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')


async def handle_admin_login(request):
    """POST /admin/login - process login"""
    try:
        data = await request.post()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not username or not password:
            raise web.HTTPFound('/admin/login?error=Username and password required')
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT * FROM admin_users WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if not user or not verify_password(password, user['password_hash']):
            cursor.close()
            conn.close()
            logger.warning(f"Failed login attempt for username: {username}")
            raise web.HTTPFound('/admin/login?error=Invalid username or password')
        
        # Update last login
        cursor.execute("UPDATE admin_users SET last_login = NOW() WHERE id = %s", (user['id'],))
        conn.commit()
        cursor.close()
        conn.close()
        
        # Create session
        session_token = generate_session_token()
        admin_sessions[session_token] = {
            'user_id': user['id'],
            'username': user['username'],
            'role': user['role'],
            'must_change_password': user['must_change_password'],
            'created': datetime.now(),
            'expires': datetime.now() + timedelta(hours=24)
        }
        
        logger.info(f"Successful login for user: {username}")
        
        # Redirect based on whether password change is required
        redirect_url = '/admin/change-password' if user['must_change_password'] else '/admin/characters'
        response = web.HTTPFound(redirect_url)
        response.set_cookie('admin_session', session_token, max_age=86400, httponly=True, samesite='Lax')
        raise response
        
    except web.HTTPFound:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise web.HTTPFound('/admin/login?error=Login failed')


async def handle_change_password_page(request):
    """GET /admin/change-password - show password change page"""
    session = get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')
    
    error = request.query.get('error', '')
    success = request.query.get('success', '')
    
    warning_html = ''
    if session.get('must_change_password'):
        warning_html = '<div class="warning-box">⚠️ You must change your password before continuing.</div>'
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>LuminisBot Admin - Change Password</title>
        <style>{ADMIN_CSS}</style>
    </head>
    <body>
        <div class="card card-center">
            <div class="logo">🔑</div>
            <h1>Change Password</h1>
            {warning_html}
            {'<p class="error">' + error + '</p>' if error else ''}
            {'<p class="success">' + success + '</p>' if success else ''}
            <form method="POST" action="/admin/change-password">
                <input type="password" name="current_password" placeholder="Current Password" required>
                <input type="password" name="new_password" placeholder="New Password (min 8 chars)" required minlength="8">
                <input type="password" name="confirm_password" placeholder="Confirm New Password" required>
                <button type="submit" class="btn btn-primary" style="width:100%">Change Password</button>
            </form>
            {'' if session.get('must_change_password') else '<p style="margin-top:20px"><a href="/admin/characters" class="btn btn-secondary">← Back</a></p>'}
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')


async def handle_change_password(request):
    """POST /admin/change-password - process password change"""
    session = get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')
    
    try:
        data = await request.post()
        current_password = data.get('current_password', '')
        new_password = data.get('new_password', '')
        confirm_password = data.get('confirm_password', '')
        
        if new_password != confirm_password:
            raise web.HTTPFound('/admin/change-password?error=Passwords do not match')
        
        if len(new_password) < 8:
            raise web.HTTPFound('/admin/change-password?error=Password must be at least 8 characters')
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT password_hash FROM admin_users WHERE id = %s", (session['user_id'],))
        user = cursor.fetchone()
        
        if not user or not verify_password(current_password, user['password_hash']):
            cursor.close()
            conn.close()
            raise web.HTTPFound('/admin/change-password?error=Current password is incorrect')
        
        # Update password
        new_hash = hash_password(new_password)
        cursor.execute("""
            UPDATE admin_users 
            SET password_hash = %s, must_change_password = false, updated_at = NOW() 
            WHERE id = %s
        """, (new_hash, session['user_id']))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        # Update session
        session['must_change_password'] = False
        
        logger.info(f"Password changed for user: {session['username']}")
        
        raise web.HTTPFound('/admin/characters')
        
    except web.HTTPFound:
        raise
    except Exception as e:
        logger.error(f"Password change error: {e}")
        raise web.HTTPFound('/admin/change-password?error=Failed to change password')


async def handle_admin_logout(request):
    """GET /admin/logout - logout"""
    session_token = request.cookies.get('admin_session')
    if session_token and session_token in admin_sessions:
        del admin_sessions[session_token]
    
    response = web.HTTPFound('/admin/login')
    response.del_cookie('admin_session')
    raise response


def render_nav(session, active='characters'):
    """Render navigation bar"""
    is_admin = session.get('role') == 'admin'
    return f"""
    <nav class="nav">
        <a href="/admin/characters" class="{'active' if active == 'characters' else ''}">🎮 Characters</a>
        {'<a href="/admin/users" class="' + ('active' if active == 'users' else '') + '">👥 Users</a>' if is_admin else ''}
        <a href="/admin/change-password" class="{'active' if active == 'password' else ''}">🔑 Password</a>
        <div class="spacer"></div>
        <span class="user-info">👤 {session['username']} <span class="badge badge-{session['role']}">{session['role']}</span></span>
        <a href="/admin/logout">🚪 Logout</a>
    </nav>
    """


@require_auth
async def handle_characters_page(request):
    """GET /admin/characters - show all characters"""
    session = request['session']
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                wc.character_name, wc.realm_name, wc.character_class,
                wc.character_race, wc.faction, wc.level, wc.item_level,
                wc.discord_id, wc.created_at, wc.last_updated
            FROM wow_characters wc
            ORDER BY wc.last_updated DESC
        """)
        characters = cursor.fetchall()
        
        cursor.execute("SELECT COUNT(DISTINCT discord_id) as user_count FROM wow_characters")
        user_count = cursor.fetchone()['user_count']
        
        cursor.close()
        conn.close()
        
        rows_html = ""
        for char in characters:
            faction_emoji = "🔵" if char['faction'] == 'ALLIANCE' else "🔴" if char['faction'] == 'HORDE' else "⚪"
            created = char['created_at'].strftime('%Y-%m-%d %H:%M') if char['created_at'] else 'N/A'
            updated = char['last_updated'].strftime('%Y-%m-%d %H:%M') if char['last_updated'] else 'N/A'
            
            rows_html += f"""
            <tr>
                <td>{faction_emoji} {char['character_name']}</td>
                <td>{char['realm_name']}</td>
                <td>{char['character_class'] or 'N/A'}</td>
                <td>{char['character_race'] or 'N/A'}</td>
                <td>{char['level'] or 'N/A'}</td>
                <td>{char['item_level'] or 'N/A'}</td>
                <td><code>{char['discord_id']}</code></td>
                <td>{created}</td>
                <td>{updated}</td>
            </tr>
            """
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>LuminisBot Admin - Characters</title>
            <style>{ADMIN_CSS}</style>
        </head>
        <body>
            <div class="container">
                {render_nav(session, 'characters')}
                
                <div class="stats">
                    <div class="stat">
                        <div class="stat-value">{len(characters)}</div>
                        <div class="stat-label">Total Characters</div>
                    </div>
                    <div class="stat">
                        <div class="stat-value">{user_count}</div>
                        <div class="stat-label">Linked Users</div>
                    </div>
                </div>
                
                <div class="card" style="margin-top:20px">
                    <div class="search-box">
                        <input type="text" id="search" placeholder="Search characters, realms, classes..." onkeyup="filterTable()">
                    </div>
                    <div class="table-wrapper">
                        {'<table id="charTable"><thead><tr><th>Character</th><th>Realm</th><th>Class</th><th>Race</th><th>Level</th><th>iLvl</th><th>Discord ID</th><th>Linked</th><th>Updated</th></tr></thead><tbody>' + rows_html + '</tbody></table>' if characters else '<p style="text-align:center;color:rgba(255,255,255,0.5)">No characters found. Users can link their accounts with /connectwow</p>'}
                    </div>
                </div>
            </div>
            <script>
                function filterTable() {{
                    const filter = document.getElementById('search').value.toLowerCase();
                    const rows = document.querySelectorAll('#charTable tbody tr');
                    rows.forEach(row => {{
                        row.style.display = row.textContent.toLowerCase().includes(filter) ? '' : 'none';
                    }});
                }}
            </script>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')
        
    except Exception as e:
        logger.error(f"Error fetching characters: {e}")
        return web.Response(text=f"Error: {e}", status=500)


@require_admin
async def handle_users_page(request):
    """GET /admin/users - manage users (admin only)"""
    session = request['session']
    message = request.query.get('message', '')
    error = request.query.get('error', '')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT id, username, role, must_change_password, created_at, last_login, created_by FROM admin_users ORDER BY created_at")
        users = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        rows_html = ""
        for user in users:
            created = user['created_at'].strftime('%Y-%m-%d %H:%M') if user['created_at'] else 'N/A'
            last_login = user['last_login'].strftime('%Y-%m-%d %H:%M') if user['last_login'] else 'Never'
            must_change = '⚠️' if user['must_change_password'] else ''
            
            # Can't delete yourself or the last admin
            delete_btn = ''
            if user['username'] != session['username']:
                delete_btn = f'''
                <form method="POST" action="/admin/users/delete" style="display:inline" 
                      onsubmit="return confirm('Delete user {user['username']}?')">
                    <input type="hidden" name="user_id" value="{user['id']}">
                    <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                </form>
                '''
            
            rows_html += f"""
            <tr>
                <td>{user['username']} {must_change}</td>
                <td><span class="badge badge-{user['role']}">{user['role']}</span></td>
                <td>{user['created_by'] or 'system'}</td>
                <td>{created}</td>
                <td>{last_login}</td>
                <td class="actions">
                    <a href="/admin/users/edit/{user['id']}" class="btn btn-secondary btn-sm">Edit</a>
                    {delete_btn}
                </td>
            </tr>
            """
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>LuminisBot Admin - Users</title>
            <style>{ADMIN_CSS}</style>
        </head>
        <body>
            <div class="container">
                {render_nav(session, 'users')}
                
                {'<div class="success" style="background:rgba(81,207,102,0.2);padding:15px;border-radius:8px;margin-bottom:20px">' + message + '</div>' if message else ''}
                {'<div class="error" style="background:rgba(255,107,107,0.2);padding:15px;border-radius:8px;margin-bottom:20px">' + error + '</div>' if error else ''}
                
                <div class="card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
                        <h2 style="margin:0">👥 User Management</h2>
                        <a href="/admin/users/new" class="btn btn-primary">+ Add User</a>
                    </div>
                    <div class="table-wrapper">
                        <table>
                            <thead>
                                <tr><th>Username</th><th>Role</th><th>Created By</th><th>Created</th><th>Last Login</th><th>Actions</th></tr>
                            </thead>
                            <tbody>{rows_html}</tbody>
                        </table>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')
        
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        return web.Response(text=f"Error: {e}", status=500)


@require_admin
async def handle_new_user_page(request):
    """GET /admin/users/new - add new user form"""
    session = request['session']
    error = request.query.get('error', '')
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>LuminisBot Admin - Add User</title>
        <style>{ADMIN_CSS}</style>
    </head>
    <body>
        <div class="container">
            {render_nav(session, 'users')}
            
            <div class="card" style="max-width:500px">
                <h2>➕ Add New User</h2>
                {'<p class="error">' + error + '</p>' if error else ''}
                <form method="POST" action="/admin/users/new">
                    <div class="form-group">
                        <label>Username</label>
                        <input type="text" name="username" required pattern="[a-zA-Z0-9_]+" title="Letters, numbers, underscores only">
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input type="password" name="password" required minlength="8">
                    </div>
                    <div class="form-group">
                        <label>Role</label>
                        <select name="role">
                            <option value="user">User (read-only)</option>
                            <option value="admin">Admin (full access)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label><input type="checkbox" name="must_change" checked> Require password change on first login</label>
                    </div>
                    <div class="actions">
                        <button type="submit" class="btn btn-primary">Create User</button>
                        <a href="/admin/users" class="btn btn-secondary">Cancel</a>
                    </div>
                </form>
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')


@require_admin
async def handle_new_user(request):
    """POST /admin/users/new - create new user"""
    session = request['session']
    
    try:
        data = await request.post()
        username = data.get('username', '').strip().lower()
        password = data.get('password', '')
        role = data.get('role', 'user')
        must_change = 'must_change' in data
        
        if not username or not password:
            raise web.HTTPFound('/admin/users/new?error=Username and password required')
        
        if len(password) < 8:
            raise web.HTTPFound('/admin/users/new?error=Password must be at least 8 characters')
        
        if role not in ('user', 'admin'):
            role = 'user'
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if username exists
        cursor.execute("SELECT id FROM admin_users WHERE username = %s", (username,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            raise web.HTTPFound(f'/admin/users/new?error=Username "{username}" already exists')
        
        # Create user
        password_hash = hash_password(password)
        cursor.execute("""
            INSERT INTO admin_users (username, password_hash, role, must_change_password, created_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (username, password_hash, role, must_change, session['username']))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"User '{username}' created by {session['username']}")
        
        raise web.HTTPFound(f'/admin/users?message=User "{username}" created successfully')
        
    except web.HTTPFound:
        raise
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise web.HTTPFound(f'/admin/users/new?error=Failed to create user')


@require_admin
async def handle_edit_user_page(request):
    """GET /admin/users/edit/{id} - edit user form"""
    session = request['session']
    user_id = request.match_info.get('id')
    error = request.query.get('error', '')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT * FROM admin_users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if not user:
            raise web.HTTPFound('/admin/users?error=User not found')
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>LuminisBot Admin - Edit User</title>
            <style>{ADMIN_CSS}</style>
        </head>
        <body>
            <div class="container">
                {render_nav(session, 'users')}
                
                <div class="card" style="max-width:500px">
                    <h2>✏️ Edit User: {user['username']}</h2>
                    {'<p class="error">' + error + '</p>' if error else ''}
                    <form method="POST" action="/admin/users/edit/{user_id}">
                        <div class="form-group">
                            <label>Username</label>
                            <input type="text" value="{user['username']}" disabled style="opacity:0.5">
                        </div>
                        <div class="form-group">
                            <label>New Password (leave empty to keep current)</label>
                            <input type="password" name="password" minlength="8">
                        </div>
                        <div class="form-group">
                            <label>Role</label>
                            <select name="role">
                                <option value="user" {'selected' if user['role'] == 'user' else ''}>User (read-only)</option>
                                <option value="admin" {'selected' if user['role'] == 'admin' else ''}>Admin (full access)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label><input type="checkbox" name="must_change" {'checked' if user['must_change_password'] else ''}> Require password change on next login</label>
                        </div>
                        <div class="actions">
                            <button type="submit" class="btn btn-primary">Save Changes</button>
                            <a href="/admin/users" class="btn btn-secondary">Cancel</a>
                        </div>
                    </form>
                </div>
            </div>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')
        
    except web.HTTPFound:
        raise
    except Exception as e:
        logger.error(f"Error loading user: {e}")
        raise web.HTTPFound('/admin/users?error=Failed to load user')


@require_admin
async def handle_edit_user(request):
    """POST /admin/users/edit/{id} - update user"""
    session = request['session']
    user_id = request.match_info.get('id')
    
    try:
        data = await request.post()
        password = data.get('password', '')
        role = data.get('role', 'user')
        must_change = 'must_change' in data
        
        if role not in ('user', 'admin'):
            role = 'user'
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT username FROM admin_users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            conn.close()
            raise web.HTTPFound('/admin/users?error=User not found')
        
        # Update user
        if password:
            if len(password) < 8:
                cursor.close()
                conn.close()
                raise web.HTTPFound(f'/admin/users/edit/{user_id}?error=Password must be at least 8 characters')
            
            password_hash = hash_password(password)
            cursor.execute("""
                UPDATE admin_users 
                SET password_hash = %s, role = %s, must_change_password = %s, updated_at = NOW()
                WHERE id = %s
            """, (password_hash, role, must_change, user_id))
        else:
            cursor.execute("""
                UPDATE admin_users 
                SET role = %s, must_change_password = %s, updated_at = NOW()
                WHERE id = %s
            """, (role, must_change, user_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"User '{user['username']}' updated by {session['username']}")
        
        raise web.HTTPFound(f'/admin/users?message=User "{user["username"]}" updated')
        
    except web.HTTPFound:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise web.HTTPFound(f'/admin/users/edit/{user_id}?error=Failed to update user')


@require_admin
async def handle_delete_user(request):
    """POST /admin/users/delete - delete user"""
    session = request['session']
    
    try:
        data = await request.post()
        user_id = data.get('user_id')
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("SELECT username FROM admin_users WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            cursor.close()
            conn.close()
            raise web.HTTPFound('/admin/users?error=User not found')
        
        # Can't delete yourself
        if user['username'] == session['username']:
            cursor.close()
            conn.close()
            raise web.HTTPFound('/admin/users?error=Cannot delete your own account')
        
        # Check if this is the last admin
        cursor.execute("SELECT COUNT(*) as count FROM admin_users WHERE role = 'admin'")
        admin_count = cursor.fetchone()['count']
        
        cursor.execute("SELECT role FROM admin_users WHERE id = %s", (user_id,))
        user_role = cursor.fetchone()['role']
        
        if user_role == 'admin' and admin_count <= 1:
            cursor.close()
            conn.close()
            raise web.HTTPFound('/admin/users?error=Cannot delete the last admin user')
        
        cursor.execute("DELETE FROM admin_users WHERE id = %s", (user_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"User '{user['username']}' deleted by {session['username']}")
        
        raise web.HTTPFound(f'/admin/users?message=User "{user["username"]}" deleted')
        
    except web.HTTPFound:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        raise web.HTTPFound('/admin/users?error=Failed to delete user')


# Legacy redirect for old /characters URL
async def handle_characters_redirect(request):
    """Redirect old /characters URL to new /admin/characters"""
    raise web.HTTPFound('/admin/characters')


async def handle_admin_redirect(request):
    """Redirect /admin to /admin/login"""
    raise web.HTTPFound('/admin/login')


def create_app(bot=None):
    """Create and configure the web application"""
    global discord_bot
    discord_bot = bot
    
    # Create app with security and CORS middleware (security first!)
    app = web.Application(middlewares=[security_middleware, cors_middleware])
    
    # OAuth routes
    app.router.add_get('/authorize', handle_authorize)
    app.router.add_get('/callback', handle_callback)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/unlink', handle_unlink)
    
    # Admin panel routes
    app.router.add_get('/admin', handle_admin_redirect)
    app.router.add_get('/admin/login', handle_admin_login_page)
    app.router.add_post('/admin/login', handle_admin_login)
    app.router.add_get('/admin/logout', handle_admin_logout)
    app.router.add_get('/admin/change-password', handle_change_password_page)
    app.router.add_post('/admin/change-password', handle_change_password)
    app.router.add_get('/admin/characters', handle_characters_page)
    app.router.add_get('/admin/users', handle_users_page)
    app.router.add_get('/admin/users/new', handle_new_user_page)
    app.router.add_post('/admin/users/new', handle_new_user)
    app.router.add_get('/admin/users/edit/{id}', handle_edit_user_page)
    app.router.add_post('/admin/users/edit/{id}', handle_edit_user)
    app.router.add_post('/admin/users/delete', handle_delete_user)
    
    # Legacy redirect (old /characters URL)
    app.router.add_get('/characters', handle_characters_redirect)
    
    # API routes (v1)
    app.router.add_get('/api/v1/events', handle_get_events)
    app.router.add_get('/api/v1/events/{event_id}', handle_get_single_event)
    app.router.add_post('/api/v1/events/{event_id}/signup', handle_update_signup)
    app.router.add_post('/api/v1/keys/generate', handle_generate_api_key)
    
    return app


async def start_oauth_server(bot=None, port=8000):
    """Start the OAuth web server"""
    # Ensure default admin user exists
    ensure_default_admin_exists()
    
    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    logger.info(f"OAuth server started on port {port}")
    logger.info(f"Authorize endpoint: http://0.0.0.0:{port}/authorize")
    logger.info(f"Callback endpoint: http://0.0.0.0:{port}/callback")
    
    return runner


if __name__ == '__main__':
    """Run server standalone for testing"""
    ensure_default_admin_exists()
    web.run_app(create_app(), host='0.0.0.0', port=8000)
