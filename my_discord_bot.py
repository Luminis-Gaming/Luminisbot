# my_discord_bot.py

# --- Core Discord and Helper Imports ---
import discord
from discord import app_commands
from discord.ext import tasks
import os
from dotenv import load_dotenv
import asyncio
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

# --- Import OAuth server ---
from oauth_server import start_oauth_server

# --- Import database migrations ---
from run_migrations import run_migrations

# --- Import raid system ---
from raid_system import (
    RaidButtonsView, generate_raid_embed, create_raid_event
)

# --- Load All Secrets from Environment ---
load_dotenv()
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
RECORDER_EMAIL = os.getenv('RECORDER_EMAIL')
RECORDER_PASSWORD = os.getenv('RECORDER_PASSWORD')
WCL_CLIENT_ID = os.getenv('WCL_CLIENT_ID')
WCL_CLIENT_SECRET = os.getenv('WCL_CLIENT_SECRET')
DATABASE_URL = os.getenv('DATABASE_URL')
BLIZZARD_CLIENT_ID = os.getenv('BLIZZARD_CLIENT_ID')
BLIZZARD_CLIENT_SECRET = os.getenv('BLIZZARD_CLIENT_SECRET')
BLIZZARD_REDIRECT_URI = os.getenv('BLIZZARD_REDIRECT_URI')

# --- Configuration Constants ---
WCL_GUILD_ID = 771376 # Example Guild ID



# --- Bot and Command Tree Setup ---
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

# --- Automatic Log Detection Task ---
@tasks.loop(minutes=10)
async def check_for_new_logs():
    """Check for new logs and post them to configured channels."""
    print("[TASK] Checking for new logs from WCL.")
    
    conn = get_db_connection()
    if not conn:
        print("[ERROR] TASK: Cannot connect to database for log checking.")
        return
    
    import psycopg2.extras
    
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM guild_channels")
        guild_configs = cur.fetchall()
        
        if not guild_configs:
            print("[TASK] No guilds configured for automatic logs.")
            return
        
        async with aiohttp.ClientSession() as session:
            token = await get_wcl_token(session)
            if not token:
                print("[ERROR] TASK: Failed to get WCL token for log checking.")
                return
                
            latest_log = await get_latest_log(session, token)
            if not latest_log:
                print("[TASK] No logs found for guild.")
                return
                
            log_code = latest_log['code']
            log_title = latest_log['title']
            log_start_time = latest_log['startTime']
            log_owner = latest_log['owner']['name'] if latest_log.get('owner') else 'Unknown'
            
            for guild_config in guild_configs:
                guild_id = guild_config['guild_id']
                channel_id = guild_config['channel_id']
                last_log_id = guild_config.get('last_log_id')
                
                if last_log_id == log_code:
                    print(f"[TASK] Log {log_code} already posted to guild {guild_id}.")
                    continue
                    
                channel = client.get_channel(channel_id)
                if not channel:
                    print(f"[ERROR] TASK: Channel {channel_id} not found for guild {guild_id}.")
                    continue
                
                # Format start time
                start_datetime = datetime.fromtimestamp(log_start_time / 1000, tz=timezone.utc)
                formatted_time = start_datetime.strftime('%Y-%m-%d %H:%M UTC')
                
                # Create embed
                embed = discord.Embed(
                    title=log_title,
                    url=f"https://www.warcraftlogs.com/reports/{log_code}",
                    description=f"**Owner:** {log_owner}\n**Date:** {formatted_time}",
                    color=0x00ff00
                )
                embed.set_footer(text="Click the buttons below to view performance data")
                
                # Add buttons
                view = LogButtonsView()
                
                try:
                    await send_message_with_auto_delete(channel, embed=embed, view=view)
                    print(f"[TASK] Posted log {log_code} to guild {guild_id} channel {channel_id}.")
                    
                    # Update database with new log ID
                    cur.execute(
                        "UPDATE guild_channels SET last_log_id = %s WHERE guild_id = %s",
                        (log_code, guild_id)
                    )
                    conn.commit()
                    
                except Exception as e:
                    print(f"[ERROR] TASK: Failed to post log to guild {guild_id}: {e}")
    
    except Exception as e:
        print(f"[ERROR] TASK: Exception during log checking: {e}")
    finally:
        if conn:
            conn.close()

# --- Discord Event Handlers ---
@client.event
async def on_ready():
    """Bot ready event handler."""
    # Run database migrations first
    print("[MIGRATIONS] Running database migrations...")
    run_migrations()
    
    setup_database()
    
    # Add persistent view for button interactions
    if not hasattr(client, 'added_view'):
        client.add_view(LogButtonsView())
        client.add_view(RaidButtonsView())  # Add raid system buttons
        client.added_view = True
    
    # Sync command tree and start background task
    await tree.sync()
    if not check_for_new_logs.is_running():
        check_for_new_logs.start()
    
    # Start OAuth web server for Battle.net integration
    if not hasattr(client, 'oauth_server_started'):
        try:
            client.oauth_runner = await start_oauth_server(client, port=8000)
            client.oauth_server_started = True
            print("[OAUTH] OAuth web server started on port 8000")
        except Exception as e:
            print(f"[ERROR] Failed to start OAuth server: {e}")
        
    # Debug info
    print(f'--- BOT READY --- Logged in as {client.user}')

# --- Discord Slash Commands ---
@tree.command(name="set_log_channel", description="Sets this channel for automatic Warcraft Log posts.")
async def set_log_channel_command(interaction: discord.Interaction):
    """Set the channel for automatic log posts."""
    await interaction.response.defer(ephemeral=True)
    
    guild_id = interaction.guild_id
    channel_id = interaction.channel_id
    
    conn = get_db_connection()
    if not conn:
        await interaction.edit_original_response(content="❌ **Database Error:** Could not connect to database.")
        return
    
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO guild_channels (guild_id, channel_id) 
            VALUES (%s, %s) 
            ON CONFLICT (guild_id) 
            DO UPDATE SET channel_id = EXCLUDED.channel_id
        """, (guild_id, channel_id))
        conn.commit()
        
        await interaction.edit_original_response(
            content=f"✅ **Success!** This channel will now receive automatic Warcraft Log posts."
        )
        print(f"[CMD] Set log channel for guild {guild_id} to channel {channel_id}")
        
    except Exception as e:
        print(f"[ERROR] Failed to set log channel: {e}")
        await interaction.edit_original_response(content=f"❌ **Error:** {e}")
    finally:
        conn.close()

@tree.command(name="warcraftrecorder", description="Adds a user's email to the Warcraft Recorder roster.")
async def warcraft_recorder_command(interaction: discord.Interaction, email: str):
    """Add email to Warcraft Recorder roster."""
    await interaction.response.defer(ephemeral=True)
    
    try:
        print(f"[CMD] Processing warcraft recorder request for email: {email}")
        result = await add_email_to_roster(
            email=email,
            recorder_email=RECORDER_EMAIL,
            recorder_password=RECORDER_PASSWORD
        )
        
        if "successfully" in result.lower():
            await interaction.edit_original_response(content=f"✅ **Success!** {result}")
        else:
            await interaction.edit_original_response(content=f"❌ **Error:** {result}")

    except Exception as e:
        print(f"An exception occurred in the command handler: {e}")
        # Use edit_original_response if the initial message was already sent
        if interaction.response.is_done():
            await interaction.edit_original_response(content="A critical error occurred after the initial response.")

@tree.command(name="connectwow", description="Link your World of Warcraft characters to your Discord account")
async def connectwow_command(interaction: discord.Interaction):
    """Generate OAuth URL for user to connect their Battle.net account."""
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    
    # Generate authorization URL
    auth_url = f"{BLIZZARD_REDIRECT_URI.replace('/callback', '')}/authorize?discord_id={discord_id}"
    
    embed = discord.Embed(
        title="🎮 Connect Your WoW Characters",
        description=(
            "Click the button below to authorize LuminisBot to access your World of Warcraft character information.\n\n"
            "**What we'll access:**\n"
            "• Character names and realms\n"
            "• Character classes and levels\n"
            "• Basic character stats\n\n"
            "**Privacy:** Your data is only used for guild features and is never shared."
        ),
        color=0x00ff00
    )
    
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="Authorize Battle.net",
        url=auth_url,
        style=discord.ButtonStyle.link,
        emoji="🔗"
    ))
    
    await interaction.edit_original_response(embed=embed, view=view)
    print(f"[CMD] Generated WoW connection URL for Discord user {discord_id}")

@tree.command(name="mycharacters", description="View your linked World of Warcraft characters")
async def mycharacters_command(interaction: discord.Interaction):
    """Display user's linked WoW characters."""
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    
    conn = get_db_connection()
    if not conn:
        await interaction.edit_original_response(content="❌ **Database Error:** Could not connect to database.")
        return
    
    try:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Check if user has connected their account
        cur.execute("SELECT * FROM wow_connections WHERE discord_id = %s", (discord_id,))
        connection = cur.fetchone()
        
        if not connection:
            await interaction.edit_original_response(
                content="❌ You haven't connected your Battle.net account yet. Use `/connectwow` to get started!"
            )
            return
        
        # Fetch characters
        cur.execute("""
            SELECT character_name, realm_name, character_class, level, faction
            FROM wow_characters 
            WHERE discord_id = %s
            ORDER BY level DESC, character_name ASC
        """, (discord_id,))
        
        characters = cur.fetchall()
        
        if not characters:
            await interaction.edit_original_response(
                content="⚠️ No characters found. Try reconnecting with `/connectwow`."
            )
            return
        
        # Build character list
        embed = discord.Embed(
            title=f"🎮 {interaction.user.display_name}'s WoW Characters",
            description=f"Found {len(characters)} character(s)",
            color=0x0099ff
        )
        
        for char in characters[:25]:  # Discord embed field limit
            faction_emoji = "🔵" if char['faction'] == 'ALLIANCE' else "🔴"
            class_name = char['character_class'] or 'Unknown'
            
            embed.add_field(
                name=f"{faction_emoji} {char['character_name']} - {char['realm_name']}",
                value=f"Level {char['level']} {class_name}",
                inline=True
            )
        
        last_updated = connection['last_updated'].strftime('%Y-%m-%d %H:%M UTC')
        embed.set_footer(text=f"Last updated: {last_updated} • Use /connectwow to refresh")
        
        await interaction.edit_original_response(embed=embed)
        print(f"[CMD] Displayed {len(characters)} characters for Discord user {discord_id}")
        
    except Exception as e:
        print(f"[ERROR] Failed to fetch characters: {e}")
        await interaction.edit_original_response(content=f"❌ **Error:** {e}")
    finally:
        conn.close()

@tree.command(name="createraid", description="Create a new raid event with signup system")
@app_commands.describe(
    title="Raid title (e.g., 'Monday Raid', 'Mythic Night')",
    date="Date in DD/MM/YYYY format (e.g., 06/10/2025)",
    time="Time in HH:MM format (24-hour, e.g., 18:30)"
)
async def createraid_command(interaction: discord.Interaction, title: str, date: str, time: str):
    """Create a raid event with interactive signup system."""
    await interaction.response.defer()
    
    try:
        # Parse date (DD/MM/YYYY)
        from datetime import datetime, date as date_type, time as time_type
        
        date_parts = date.split('/')
        if len(date_parts) != 3:
            await interaction.edit_original_response(
                content="❌ Invalid date format! Use DD/MM/YYYY (e.g., 06/10/2025)"
            )
            return
        
        day, month, year = map(int, date_parts)
        event_date = date_type(year, month, day)
        
        # Parse time (HH:MM)
        time_parts = time.split(':')
        if len(time_parts) != 2:
            await interaction.edit_original_response(
                content="❌ Invalid time format! Use HH:MM (e.g., 18:30)"
            )
            return
        
        hour, minute = map(int, time_parts)
        event_time = time_type(hour, minute)
        
    except ValueError as e:
        await interaction.edit_original_response(
            content=f"❌ Invalid date/time format! Please use DD/MM/YYYY for date and HH:MM for time.\nError: {e}"
        )
        return
    
    # Generate initial embed (empty signups)
    embed = discord.Embed(
        title=f"📅 {title}",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    event_datetime = datetime.combine(event_date, event_time)
    embed.add_field(
        name="🗓️ Date & Time",
        value=event_datetime.strftime("%A, %d %B %Y %H:%M"),
        inline=False
    )
    
    embed.add_field(
        name="� Composition",
        value=":tank: **0** Tanks  |  :melee: **0** Melee  |  :ranged: **0** Ranged  |  :healer: **0** Healers",
        inline=False
    )
    
    embed.add_field(name="📋 Roster", value="_No signups yet - click Sign Up below!_", inline=False)
    
    embed.set_footer(text="Click a button below to sign up or change your status")
    
    # Create view with buttons
    view = RaidButtonsView()
    
    # Send message
    message = await interaction.channel.send(embed=embed, view=view)
    
    # Store event in database
    event_id = create_raid_event(
        guild_id=interaction.guild.id,
        channel_id=interaction.channel.id,
        message_id=message.id,
        title=title,
        event_date=event_date,
        event_time=event_time,
        created_by=interaction.user.id
    )
    
    await interaction.edit_original_response(
        content=f"✅ Raid event **{title}** created successfully!\n📋 Event ID: {event_id}"
    )
    
    print(f"[RAID] Created raid event '{title}' by {interaction.user.name} (ID: {event_id})")

# --- Main Execution Block ---
if __name__ == "__main__":
    if not all([BOT_TOKEN, WCL_CLIENT_ID, WCL_CLIENT_SECRET, DATABASE_URL]):
        print("[FATAL] One or more essential environment variables are missing.")
        print("[FATAL] Please check your .env file or environment configuration.")
    else:
        print("--- SCRIPT LAUNCH ---")
        
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
