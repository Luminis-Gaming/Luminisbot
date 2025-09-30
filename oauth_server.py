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


def create_app(bot=None):
    """Create and configure the web application"""
    global discord_bot
    discord_bot = bot
    
    app = web.Application()
    app.router.add_get('/authorize', handle_authorize)
    app.router.add_get('/callback', handle_callback)
    app.router.add_get('/health', handle_health)
    
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
