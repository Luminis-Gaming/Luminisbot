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
    setup_database()
    
    # Add persistent view for button interactions
    if not hasattr(client, 'added_view'):
        client.add_view(LogButtonsView())
        client.added_view = True
    
    # Sync command tree and start background task
    await tree.sync()
    if not check_for_new_logs.is_running():
        check_for_new_logs.start()
        
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
