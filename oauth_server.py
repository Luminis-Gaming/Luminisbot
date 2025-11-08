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
                
        logger.info(f"Successfully obtained access token for Discord user {discord_id}")
        
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
        
    except Exception as e:
        logger.error(f"Error fetching/storing characters: {e}")
        return web.Response(
            text=f"Error fetching character data: {str(e)}",
            status=500
        )


async def fetch_wow_characters(access_token):
    """Fetch WoW characters from Battle.net API"""
    characters = []
    
    try:
        async with aiohttp.ClientSession() as session:
            # Get account profile (lists all characters)
            headers = {'Authorization': f'Bearer {access_token}'}
            
            async with session.get(
                f"{BLIZZARD_API_BASE}/profile/user/wow",
                headers=headers,
                params={'namespace': 'profile-eu', 'locale': 'en_US'}
            ) as resp:
                
                if resp.status != 200:
                    logger.error(f"Failed to fetch WoW profile: {resp.status}")
                    return []
                
                profile_data = await resp.json()
                
                # Extract character info from wow_accounts
                for wow_account in profile_data.get('wow_accounts', []):
                    for character in wow_account.get('characters', []):
                        char_info = {
                            'name': character.get('name'),
                            'realm': character.get('realm', {}).get('name'),
                            'realm_slug': character.get('realm', {}).get('slug'),
                            'level': character.get('level'),
                            'playable_class': character.get('playable_class', {}).get('name'),
                            'playable_race': character.get('playable_race', {}).get('name'),
                            'faction': character.get('faction', {}).get('type'),
                            'character_id': character.get('id')
                        }
                        characters.append(char_info)
        
        logger.info(f"Fetched {len(characters)} characters from Battle.net API")
        return characters
        
    except Exception as e:
        logger.error(f"Error in fetch_wow_characters: {e}")
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
                    character_class, character_race, faction, level, character_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                discord_id,
                char['name'],
                char['realm'],
                char['realm_slug'],
                char['playable_class'],
                char['playable_race'],
                char['faction'],
                char['level'],
                char['character_id']
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


def create_app(bot=None):
    """Create and configure the web application"""
    global discord_bot
    discord_bot = bot
    
    # Create app with middleware
    app = web.Application(middlewares=[cors_middleware])
    
    # OAuth routes
    app.router.add_get('/authorize', handle_authorize)
    app.router.add_get('/callback', handle_callback)
    app.router.add_get('/health', handle_health)
    
    # API routes (v1)
    app.router.add_get('/api/v1/events', handle_get_events)
    app.router.add_get('/api/v1/events/{event_id}', handle_get_single_event)
    app.router.add_post('/api/v1/events/{event_id}/signup', handle_update_signup)
    app.router.add_post('/api/v1/keys/generate', handle_generate_api_key)
    
    return app


async def start_oauth_server(bot=None, port=8000):
    """Start the OAuth web server"""
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
    web.run_app(create_app(), host='0.0.0.0', port=8000)
