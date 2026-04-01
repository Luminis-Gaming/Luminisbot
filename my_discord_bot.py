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

# --- Import SimCraft integration ---
from simcraft_integration import (
    submit_sim, poll_sim_status, build_result_url, fetch_text_from_url,
    has_active_sim, get_active_sim_id, set_active_sim, clear_active_sim,
    SIMCRAFT_API_KEY,
)

# --- Import OAuth server ---
from oauth_server import start_oauth_server

# --- Import database migrations ---
from run_migrations import run_migrations

# --- Import raid system ---
from raid_system import (
    RaidButtonsView, generate_raid_embed, create_raid_event,
    get_raid_event, add_raid_reservation, remove_raid_reservation,
    get_user_signup, refresh_event_embed, backfill_reservations_for_existing_events,
    get_pending_reminders, mark_reminder_sent
)

# --- Load All Secrets from Environment ---
load_dotenv()
BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
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
intents.message_content = True  # Required to read message content in guild channels (enable in Developer Portal too)
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

# --- Automatic Log Detection Task ---
@tasks.loop(minutes=10)
async def check_for_new_logs():
    """Check for new logs and post them to configured channels."""
    print("[TASK] Checking for new logs from WCL.")
    
    # Import datetime at the top of the function to avoid scope issues
    from datetime import datetime, timezone
    
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
                    
                    # 🔗 NEW: Auto-link this log to any matching raid event
                    try:
                        from raid_system import auto_link_raid_log
                        
                        log_url = f"https://www.warcraftlogs.com/reports/{log_code}"
                        log_timestamp = datetime.fromtimestamp(log_start_time / 1000, tz=timezone.utc)
                        
                        await auto_link_raid_log(client, guild_id, log_url, log_timestamp)
                        print(f"[TASK] Attempted auto-link for log {log_code} in guild {guild_id}")
                    except Exception as link_error:
                        print(f"[WARNING] TASK: Failed to auto-link log {log_code}: {link_error}")
                    
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


@tasks.loop(hours=24)
async def cleanup_old_raid_events():
    """Clean up raid events that are more than 24 hours old."""
    print("[TASK] Running raid event cleanup...")
    from raid_system import cleanup_old_events
    cleanup_old_events()
    print("[TASK] Raid event cleanup completed.")


@tasks.loop(minutes=1)
async def update_started_events():
    """Update raid events that have recently started."""
    from raid_system import update_started_events
    await update_started_events(client)


@tasks.loop(minutes=2)
async def check_raid_reminders():
    """Check for pending raid reminders and send DMs to users."""
    try:
        from datetime import datetime, timezone
        
        # Get current time in UTC
        current_time = datetime.now(timezone.utc)
        
        # Get all pending reminders that are due
        pending_reminders = get_pending_reminders(current_time)
        
        if not pending_reminders:
            return  # No reminders to send
        
        print(f"[REMINDERS] Found {len(pending_reminders)} pending reminder(s) to send")
        
        for reminder in pending_reminders:
            try:
                # Get user
                user = await client.fetch_user(int(reminder['discord_id']))
                if not user:
                    print(f"[REMINDERS] Could not find user {reminder['discord_id']}")
                    # Mark as sent anyway to avoid retrying
                    mark_reminder_sent(reminder['reminder_id'])
                    continue
                
                # Format event information
                event_title = reminder['event_title']
                event_date = reminder['event_date']
                event_time = reminder['event_time']
                
                # Create Discord timestamp for automatic timezone conversion
                from zoneinfo import ZoneInfo
                from raid_system import DEFAULT_TIMEZONE
                tz = ZoneInfo(DEFAULT_TIMEZONE)
                event_datetime_local = datetime.combine(event_date, event_time)
                event_datetime = event_datetime_local.replace(tzinfo=tz)
                discord_timestamp = f"<t:{int(event_datetime.timestamp())}:F>"
                
                # Create message with link to event
                guild_id = reminder['guild_id']
                channel_id = reminder['channel_id']
                message_id = reminder['message_id']
                message_link = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
                
                # Send DM
                try:
                    await user.send(
                        f"🔔 **Raid Reminder!**\n\n"
                        f"The raid **{event_title}** is starting soon!\n\n"
                        f"**Time:** {discord_timestamp}\n\n"
                        f"[View Event]({message_link})"
                    )
                    print(f"[REMINDERS] Sent reminder to {user.name} for event '{event_title}'")
                except discord.Forbidden:
                    print(f"[REMINDERS] Could not DM user {user.name} - DMs disabled")
                except Exception as e:
                    print(f"[REMINDERS] Failed to send DM to {user.name}: {e}")
                
                # Mark reminder as sent (even if DM failed, to avoid spam retries)
                mark_reminder_sent(reminder['reminder_id'])
                
            except Exception as e:
                print(f"[REMINDERS] Error processing reminder {reminder['reminder_id']}: {e}")
                # Don't mark as sent if there was an error, will retry next loop
        
    except Exception as e:
        print(f"[ERROR] REMINDERS: Exception during reminder check: {e}")


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
    
    # Sync command tree and start background tasks
    await tree.sync()
    if not check_for_new_logs.is_running():
        check_for_new_logs.start()
    if not cleanup_old_raid_events.is_running():
        cleanup_old_raid_events.start()
    if not update_started_events.is_running():
        update_started_events.start()
    if not check_raid_reminders.is_running():
        check_raid_reminders.start()
    
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

    # One-time backfill of reservations from existing ✅ reactions
    if not hasattr(client, 'reservations_backfilled'):
        try:
            await backfill_reservations_for_existing_events(client)
            client.reservations_backfilled = True
            print("[RESERVE] Backfill completed for upcoming events.")
        except Exception as e:
            print(f"[RESERVE] Backfill error: {e}")

# --- Emoji Reaction Handlers for Reserve ---
@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Handle ✅ reactions on raid signup messages to add to Reserve"""
    try:
        # Only process white check mark unicode emoji
        if payload.emoji is None:
            return
        if payload.emoji.name != '✅':
            return

        # Find raid event associated with this message
        event = get_raid_event(int(payload.message_id))
        if not event:
            return

        discord_id = str(payload.user_id)

        # Ignore bot's own reactions
        if client.user and payload.user_id == client.user.id:
            return

        # If user already has an official signup, skip reserving to avoid duplicates
        existing = get_user_signup(event['id'], discord_id)
        if existing:
            # Optionally, could DM user that they're already signed
            return

        # Add reservation and refresh message
        add_raid_reservation(event['id'], discord_id)
        await refresh_event_embed(client, event['id'])
    except Exception as e:
        print(f"[RESERVE] Error handling reaction add: {e}")

@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Handle ✅ reaction removals to remove from Reserve"""
    try:
        if payload.emoji is None:
            return
        if payload.emoji.name != '✅':
            return

        event = get_raid_event(int(payload.message_id))
        if not event:
            return

        discord_id = str(payload.user_id)

        remove_raid_reservation(event['id'], discord_id)
        await refresh_event_embed(client, event['id'])
    except Exception as e:
        print(f"[RESERVE] Error handling reaction remove: {e}")

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

@tree.command(name="warcraftrecorder", description="Get the join code to join our Warcraft Recorder guild")
async def warcraft_recorder_command(interaction: discord.Interaction):
    """Display the Warcraft Recorder join code."""
    join_code = "c64244fb9fd752702d13cc9078ea3fdd"
    
    embed = discord.Embed(
        title="🎥 Warcraft Recorder - Join Our Guild",
        description="Use the join code below to join our guild on Warcraft Recorder and automatically record your raids!",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📋 Join Code",
        value=f"```{join_code}```",
        inline=False
    )
    
    embed.add_field(
        name="📖 How to Use",
        value=(
            "1️⃣ Go to [warcraftrecorder.com](https://warcraftrecorder.com)\n"
            "2️⃣ Log in or create an account\n"
            "3️⃣ Click on **'Join Guild'** or **'Enter Join Code'**\n"
            "4️⃣ Paste the join code above\n"
            "5️⃣ You're all set! Your raids will now be automatically recorded 🎉"
        ),
        inline=False
    )
    
    embed.set_footer(text="Warcraft Recorder automatically records your WoW gameplay")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

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

@tree.command(name="subscribe", description="Get subscription string for Luminisbot Companion App (optional)")
async def subscribe_command(interaction: discord.Interaction):
    """Generate personalized subscription string for Companion App."""
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ This command can only be used in a server, not in DMs!",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    guild_id = interaction.guild.id
    
    conn = get_db_connection()
    if not conn:
        await interaction.edit_original_response(content="❌ **Database Error:** Could not connect to database.")
        return
    
    try:
        import psycopg2.extras
        import secrets
        import base64
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Check if user has connected their Battle.net account
        cur.execute("SELECT * FROM wow_connections WHERE discord_id = %s", (discord_id,))
        connection = cur.fetchone()
        
        if not connection:
            embed = discord.Embed(
                title="❌ Battle.net Not Connected",
                description=(
                    "You must link your Battle.net account before subscribing to raid events.\n\n"
                    "**How to connect:**\n"
                    "1. Use the `/connectwow` command\n"
                    "2. Authorize LuminisBot with your Battle.net account\n"
                    "3. Come back here and use `/subscribe` again"
                ),
                color=0xff0000
            )
            await interaction.edit_original_response(embed=embed)
            return
        
        # Check if user already has an API key for this guild
        cur.execute("""
            SELECT key_hash FROM api_keys 
            WHERE discord_user_id = %s AND guild_id = %s AND is_active = true
        """, (discord_id, guild_id))
        
        existing_key = cur.fetchone()
        
        if existing_key:
            api_key = existing_key['key_hash']
            print(f"[CMD] Reusing existing API key for user {discord_id} in guild {guild_id}")
        else:
            # Generate new API key
            api_key = secrets.token_urlsafe(32)
            
            # Store in database
            cur.execute("""
                INSERT INTO api_keys (discord_user_id, guild_id, key_hash, is_active, created_at, request_count, notes)
                VALUES (%s, %s, %s, true, NOW(), 0, %s)
            """, (discord_id, guild_id, api_key, f"Generated for {interaction.user.name} in {interaction.guild.name}"))
            
            conn.commit()
            print(f"[CMD] Generated new API key for user {discord_id} in guild {guild_id}")
        
        # Create subscription string: guild_id:api_key
        subscription_data = f"{guild_id}:{api_key}"
        
        # Base64 encode for easier copying (optional, makes it look cleaner)
        subscription_string = base64.b64encode(subscription_data.encode()).decode()
        
        # Create embed with instructions
        embed = discord.Embed(
            title="✅ Subscription String Generated",
            description=(
                f"Your personalized subscription for **{interaction.guild.name}**\n\n"
                "**Your Subscription String:**\n"
                f"```{subscription_string}```\n"
                "⚠️ **Keep this private!** This string is unique to you.\n\n"
                "📋 **What is this for?**\n"
                "This is for the **Luminisbot Companion App** (optional desktop app)\n"
                "that enables automatic syncing every 60 seconds.\n\n"
                "**Don't have the Companion App?**\n"
                "No problem! Use `/syncevents` to manually sync anytime.\n"
                "The Companion App is completely optional.\n\n"
                "**Want the Companion App?**\n"
                "1. Download from CurseForge or GitHub\n"
                "2. Paste this string into the app\n"
                "3. Click 'Start Syncing' - Done!"
            ),
            color=0x00ff00
        )
        embed.set_footer(text=f"Luminisbot • {interaction.guild.name}")
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        
        await interaction.edit_original_response(embed=embed)
        print(f"[CMD] Provided subscription string to user {interaction.user.name} for guild {guild_id}")
        
    except Exception as e:
        print(f"[ERROR] Failed to generate subscription: {e}")
        await interaction.edit_original_response(content=f"❌ **Error:** {e}")
    finally:
        conn.close()

@tree.command(name="syncevents", description="Get latest raid events as an import string for WoW addon")
async def syncevents_command(interaction: discord.Interaction):
    """Generate import string with latest events for the addon."""
    if not interaction.guild:
        await interaction.response.send_message(
            "❌ This command can only be used in a server, not in DMs!",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    discord_id = str(interaction.user.id)
    guild_id = interaction.guild.id
    
    conn = get_db_connection()
    if not conn:
        await interaction.edit_original_response(content="❌ **Database Error:** Could not connect to database.")
        return
    
    try:
        import psycopg2.extras
        import json
        import base64
        from datetime import datetime, date
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Check if user has subscribed
        cur.execute("""
            SELECT key_hash FROM api_keys 
            WHERE discord_user_id = %s AND guild_id = %s AND is_active = true
        """, (discord_id, guild_id))
        
        api_key_result = cur.fetchone()
        
        if not api_key_result:
            embed = discord.Embed(
                title="❌ Not Subscribed",
                description=(
                    "You haven't subscribed to events in this server yet!\n\n"
                    "**How to subscribe:**\n"
                    "1. Use `/connectwow` to link your Battle.net account (if not done)\n"
                    "2. Use `/subscribe` to get your subscription string\n"
                    "3. Paste it in the addon Settings tab\n"
                    "4. Come back here and use `/syncevents` again"
                ),
                color=0xff0000
            )
            await interaction.edit_original_response(embed=embed)
            return
        
        # Fetch all future events for this guild
        cur.execute("""
            SELECT 
                re.id,
                re.title,
                re.event_date,
                re.event_time,
                re.created_by,
                re.log_url
            FROM raid_events re
            WHERE re.guild_id = %s 
                AND re.event_date >= CURRENT_DATE
            ORDER BY re.event_date, re.event_time
        """, (guild_id,))
        
        events = cur.fetchall()
        
        if not events:
            await interaction.edit_original_response(
                content="ℹ️ No upcoming events found in this server.\n\nCreate an event with `/createraid` first!"
            )
            return
        
        # Fetch signups for each event
        event_list = []
        for event in events:
            cur.execute("""
                SELECT 
                    rs.character_name,
                    rs.realm_slug,
                    rs.character_class,
                    rs.role,
                    rs.spec,
                    rs.status
                FROM raid_signups rs
                WHERE rs.event_id = %s
                ORDER BY 
                    CASE rs.status 
                        WHEN 'signed' THEN 1 
                        WHEN 'tentative' THEN 2 
                        WHEN 'declined' THEN 3 
                    END,
                    CASE rs.role 
                        WHEN 'tank' THEN 1 
                        WHEN 'healer' THEN 2 
                        WHEN 'dps' THEN 3 
                    END,
                    rs.character_name
            """, (event['id'],))
            
            signups = cur.fetchall()
            
            event_data = {
                'id': event['id'],
                'title': event['title'],
                'date': event['event_date'].strftime('%Y-%m-%d'),
                'time': event['event_time'].strftime('%H:%M'),
                'createdBy': str(event['created_by']),
                'logUrl': event['log_url'],
                'signups': []
            }
            
            for signup in signups:
                event_data['signups'].append({
                    'character': signup['character_name'],
                    'realm': signup['realm_slug'],
                    'class': signup['character_class'],
                    'role': signup['role'],
                    'spec': signup['spec'],
                    'status': signup['status']
                })
            
            event_list.append(event_data)
        
        # Create import string (same format as existing import system)
        import_data = {
            'events': event_list,
            'timestamp': datetime.now().isoformat()
        }
        
        json_string = json.dumps(import_data, ensure_ascii=False)
        encoded_string = base64.b64encode(json_string.encode('utf-8')).decode('utf-8')
        
        # Create embed with import string
        embed = discord.Embed(
            title="✅ Events Ready to Import",
            description=(
                f"Found **{len(event_list)}** upcoming event(s) in **{interaction.guild.name}**\n\n"
                "**Import String:**\n"
                f"```{encoded_string[:100]}{'...' if len(encoded_string) > 100 else ''}```\n"
                f"*({len(encoded_string)} characters)*\n\n"
                "**How to import:**\n"
                "1. Copy the FULL string below (click to select all)\n"
                "2. Open WoW and type `/lb`\n"
                "3. Go to the **Import String** tab\n"
                "4. Paste the string and click **Import Event**"
            ),
            color=0x00ff00
        )
        
        # List events
        event_summary = "\n".join([
            f"• **{evt['title']}** - {evt['date']} at {evt['time']} ({len(evt['signups'])} signups)"
            for evt in event_list[:10]
        ])
        if len(event_list) > 10:
            event_summary += f"\n... and {len(event_list) - 10} more"
        
        embed.add_field(name="Events Included", value=event_summary, inline=False)
        embed.set_footer(text=f"Synced at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Send embed first
        await interaction.edit_original_response(embed=embed)
        
        # Send full string in a follow-up message (easier to copy)
        await interaction.followup.send(
            f"**Full Import String (copy everything below):**\n```{encoded_string}```",
            ephemeral=True
        )
        
        print(f"[CMD] Generated event sync for user {interaction.user.name} in guild {guild_id} ({len(event_list)} events)")
        
    except Exception as e:
        print(f"[ERROR] Failed to sync events: {e}")
        import traceback
        traceback.print_exc()
        await interaction.edit_original_response(content=f"❌ **Error:** {e}")
    finally:
        conn.close()

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
            faction_emoji = "<:alliance:1422562308600893542>" if char['faction'] == 'ALLIANCE' else "<:horde:1422562343015022723>"
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


@tree.command(name="unlinkwow", description="Unlink your Battle.net account and delete all WoW data")
async def unlinkwow_command(interaction: discord.Interaction):
    """Unlink and delete all WoW data for the user."""
    await interaction.response.defer(ephemeral=True)
    discord_id = str(interaction.user.id)
    conn = get_db_connection()
    if not conn:
        await interaction.edit_original_response(content="❌ **Database Error:** Could not connect to database.")
        return
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM wow_characters WHERE discord_id = %s", (discord_id,))
        cur.execute("DELETE FROM wow_connections WHERE discord_id = %s", (discord_id,))
        conn.commit()
        await interaction.edit_original_response(content="✅ Your Battle.net account and all WoW character data have been deleted. You can use /connectwow to link again at any time.")
        print(f"[CMD] Unlinked and deleted all WoW data for Discord user {discord_id}")
    except Exception as e:
        print(f"[ERROR] Failed to unlink data: {e}")
        await interaction.edit_original_response(content=f"❌ **Error deleting data:** {e}")
    finally:
        conn.close()


class CreateRaidModal(discord.ui.Modal, title="Create Raid Event"):
    """Modal for creating a new raid event"""
    
    def __init__(self):
        super().__init__()
        
        self.title_input = discord.ui.TextInput(
            label="Event Title",
            placeholder="e.g., Monday Raid, Mythic Night, Weekly Clear",
            max_length=100,
            required=True
        )
        self.add_item(self.title_input)
        
        self.date_input = discord.ui.TextInput(
            label="Date (DD/MM/YYYY, DD.MM.YYYY, or YYYY-MM-DD)",
            placeholder="e.g., 06/10/2025, 06.10.2025, or 2025-10-06",
            max_length=20,
            required=True
        )
        self.add_item(self.date_input)
        
        self.time_input = discord.ui.TextInput(
            label="Time (HH:MM in 24-hour format)",
            placeholder="e.g., 20:00 for 8 PM",
            max_length=5,
            required=True
        )
        self.add_item(self.time_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        try:
            # Import parse functions from raid_system
            from raid_system import parse_date, parse_time, create_raid_event, RaidButtonsView
            from datetime import datetime
            
            # Parse date and time
            event_date = parse_date(self.date_input.value)
            event_time = parse_time(self.time_input.value)
            title = self.title_input.value
            
        except ValueError as e:
            await interaction.response.send_message(
                f"❌ Invalid date/time format!\nError: {e}",
                ephemeral=True
            )
            return
        
        # Defer the response since we're going to create a message
        await interaction.response.defer(ephemeral=True)
        
        # Create view with buttons
        view = RaidButtonsView()
        
        # Send a placeholder message first (we need the message ID for the database)
        placeholder_embed = discord.Embed(
            title="Creating raid event...",
            color=discord.Color.blue()
        )
        message = await interaction.channel.send(embed=placeholder_embed, view=view)
        
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
        
        # Now generate the proper embed using generate_raid_embed
        from raid_system import generate_raid_embed
        embed, view = generate_raid_embed(event_id)
        
        # Update the message with the proper embed
        await message.edit(embed=embed, view=view)
        
        await interaction.followup.send(
            f"✅ Raid event **{title}** created successfully!\n📋 Event ID: {event_id}",
            ephemeral=True
        )
        
        print(f"[RAID] Created raid event '{title}' by {interaction.user.name} (ID: {event_id})")


@tree.command(name="createraid", description="Create a new raid event with signup system")
async def createraid_command(interaction: discord.Interaction):
    """Create a raid event with interactive signup system."""
    modal = CreateRaidModal()
    await interaction.response.send_modal(modal)


# --- SimCraft Sim Command ---

SIM_TYPE_LABELS = {
    "quick": "⚔️ Quick Sim",
    "vault": "🏦 Sim Vault",
    "top_gear": "🎯 Top Gear",
    "crest_upgrades": "💎 Crest Upgrades",
}

GEAR_SLOT_OPTIONS = [
    discord.SelectOption(label="Head", value="head"),
    discord.SelectOption(label="Neck", value="neck"),
    discord.SelectOption(label="Shoulders", value="shoulder"),
    discord.SelectOption(label="Back", value="back"),
    discord.SelectOption(label="Chest", value="chest"),
    discord.SelectOption(label="Wrists", value="wrist"),
    discord.SelectOption(label="Hands", value="hands"),
    discord.SelectOption(label="Waist", value="waist"),
    discord.SelectOption(label="Legs", value="legs"),
    discord.SelectOption(label="Feet", value="feet"),
    discord.SelectOption(label="Ring 1", value="finger1"),
    discord.SelectOption(label="Ring 2", value="finger2"),
    discord.SelectOption(label="Trinket 1", value="trinket1"),
    discord.SelectOption(label="Trinket 2", value="trinket2"),
    discord.SelectOption(label="Main Hand", value="main_hand"),
    discord.SelectOption(label="Off Hand", value="off_hand"),
]


class SimTypeSelect(discord.ui.Select):
    """Dropdown for choosing sim type."""
    def __init__(self):
        options = [
            discord.SelectOption(label="Quick Sim", value="quick", emoji="⚔️",
                description="Sim your current gear for DPS + stat weights"),
            discord.SelectOption(label="Sim Vault", value="vault", emoji="🏦",
                description="Find the best Great Vault pick"),
            discord.SelectOption(label="Top Gear", value="top_gear", emoji="🎯",
                description="Find the best gear combo from your bags"),
            discord.SelectOption(label="Crest Upgrades", value="crest_upgrades", emoji="💎",
                description="Find the best item to spend crests on"),
        ]
        super().__init__(placeholder="Choose a sim type...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        sim_type = self.values[0]
        label = SIM_TYPE_LABELS.get(sim_type, sim_type)
        self.view.stop()

        await interaction.response.edit_message(
            content=f"Selected: **{label}**\n\n📋 **Paste your SimC string below.** "
                    f"I'll grab it automatically.\n"
                    f"*(You have 2 minutes. The message will be deleted to keep the channel clean.)*",
            view=None,
        )

        # Wait for the user to paste their SimC string in the channel
        channel = interaction.channel
        user_id = interaction.user.id
        print(f"[SIMCRAFT] Waiting for SimC paste from user {user_id} in channel {channel.id if channel else 'None'}")

        def check(m: discord.Message):
            if m.author.id != user_id:
                return False
            if channel and m.channel.id != channel.id:
                return False
            print(f"[SIMCRAFT] Got message from user: content_len={len(m.content)}, attachments={[a.filename for a in m.attachments]}")
            # Accept any message with attachments or non-trivial content
            if m.attachments:
                return True
            if len(m.content) > 30:
                return True
            if m.content.strip().startswith('http'):
                return True
            return False

        try:
            msg = await client.wait_for('message', check=check, timeout=120.0)
        except asyncio.TimeoutError:
            await interaction.edit_original_response(
                content="⏰ Timed out waiting for SimC string. Use `/sim` to try again."
            )
            return

        # Extract SimC string from message
        simc_input = None
        try:
            if msg.attachments:
                # Read first text-like attachment (Discord auto-converts long pastes to .txt)
                for att in msg.attachments:
                    if att.filename.endswith('.txt') or att.content_type and 'text' in att.content_type:
                        raw = await att.read()
                        simc_input = raw.decode('utf-8', errors='replace')
                        break
                # Fallback: try reading any attachment as text
                if not simc_input and msg.attachments:
                    try:
                        raw = await msg.attachments[0].read()
                        simc_input = raw.decode('utf-8', errors='replace')
                    except Exception:
                        pass
            elif msg.content.strip().startswith('http'):
                simc_input = await fetch_text_from_url(msg.content.strip())
            else:
                simc_input = msg.content
        except Exception as e:
            await interaction.edit_original_response(
                content=f"❌ Failed to read SimC input: {e}"
            )
            try:
                await msg.delete()
            except discord.errors.Forbidden:
                pass
            return

        # Delete the user's paste message to keep channel clean
        try:
            await msg.delete()
        except discord.errors.Forbidden:
            pass

        if not simc_input or len(simc_input.strip()) < 50:
            await interaction.edit_original_response(
                content="❌ SimC string is too short. Make sure you copied the full output from the SimC addon."
            )
            return

        # For top_gear, show slot picker before submitting
        selected_slots = None
        if sim_type == "top_gear":
            slot_view = GearSlotPickerView()
            await interaction.edit_original_response(
                content="🎯 **Select which gear slots to compare:**\n"
                        "⚠️ *Only pick slots where you have alternative items you want to test. "
                        "More slots = exponentially slower simulation.*",
                view=slot_view,
            )

            timed_out = await slot_view.wait()
            if timed_out or not slot_view.selected_slots:
                await interaction.edit_original_response(
                    content="⏰ No slots selected. Use `/sim` to try again.",
                    view=None,
                )
                return

            selected_slots = slot_view.selected_slots
            slot_names = ", ".join(selected_slots)
            await interaction.edit_original_response(
                content=f"🔄 Starting **{label}** for: {slot_names}...",
                view=None,
            )
        else:
            # Submit to SimCraft API
            await interaction.edit_original_response(
                content=f"🔄 Starting **{label}** simulation..."
            )

        try:
            result = await submit_sim(simc_input, sim_type, selected_slots=selected_slots)
            job_id = result['id']
            set_active_sim(interaction.user.id, job_id)
        except ValueError as e:
            await interaction.edit_original_response(
                content=f"❌ Failed to start simulation: {e}"
            )
            return

        result_url = build_result_url(job_id)
        await interaction.edit_original_response(
            content=f"⏳ **{label}** simulation running...\n🔗 Live progress: {result_url}"
        )

        # Poll in background and send result when done
        async def _poll_and_notify():
            try:
                status = await poll_sim_status(job_id, timeout_seconds=600, interval=5.0)
                clear_active_sim(interaction.user.id)

                if status.get('status') == 'done':
                    dps = None
                    result_data = status.get('result')
                    if result_data and isinstance(result_data, dict):
                        dps = result_data.get('dps')

                    embed = discord.Embed(
                        title=f"✅ {label} Complete",
                        url=result_url,
                        color=0xC8992A,  # SimHammer gold
                    )
                    if dps:
                        embed.add_field(name="DPS", value=f"**{dps:,.0f}**" if isinstance(dps, (int, float)) else str(dps), inline=True)
                    embed.add_field(name="Results", value=f"[View Full Results]({result_url})", inline=False)
                    embed.set_footer(text="Luminis sim service, powered by Luminis Plus")

                    await interaction.followup.send(
                        content=f"{interaction.user.mention}",
                        embed=embed,
                        ephemeral=True,
                    )
                elif status.get('status') == 'failed':
                    error_msg = status.get('error', 'Unknown error')
                    await interaction.followup.send(
                        content=f"{interaction.user.mention} ❌ Simulation failed: {error_msg}",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        content=f"{interaction.user.mention} ⚠️ Simulation ended with status: {status.get('status')}",
                        ephemeral=True,
                    )
            except TimeoutError:
                clear_active_sim(interaction.user.id)
                await interaction.followup.send(
                    content=f"{interaction.user.mention} ⏰ Simulation timed out (10 min). Check status: {result_url}",
                    ephemeral=True,
                )
            except Exception as e:
                clear_active_sim(interaction.user.id)
                print(f"[SIMCRAFT] Polling error for job {job_id}: {e}")
                await interaction.followup.send(
                    content=f"{interaction.user.mention} ⚠️ Lost track of simulation. Check results: {result_url}",
                    ephemeral=True,
                )

        asyncio.create_task(_poll_and_notify())


class GearSlotSelect(discord.ui.Select):
    """Multi-select dropdown for gear slots."""
    def __init__(self):
        super().__init__(
            placeholder="Select gear slots...",
            options=GEAR_SLOT_OPTIONS,
            min_values=1,
            max_values=len(GEAR_SLOT_OPTIONS),
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.selected_slots = self.values
        self.view.stop()
        await interaction.response.defer()


class GearSlotPickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.selected_slots = []
        self.add_item(GearSlotSelect())


class SimTypeView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(SimTypeSelect())


@tree.command(name="sim", description="Run a SimulationCraft simulation")
async def sim_command(interaction: discord.Interaction):
    if not SIMCRAFT_API_KEY:
        await interaction.response.send_message(
            "❌ SimCraft integration is not configured. Ask an admin to set `SIMCRAFT_API_KEY`.",
            ephemeral=True,
        )
        return

    if has_active_sim(interaction.user.id):
        active_id = get_active_sim_id(interaction.user.id)
        url = build_result_url(active_id)
        await interaction.response.send_message(
            f"⏳ You already have a simulation running.\n🔗 {url}\n\nWait for it to finish before starting another.",
            ephemeral=True,
        )
        return

    view = SimTypeView()
    await interaction.response.send_message(
        "**SimHammer** — Choose a simulation type:",
        view=view,
        ephemeral=True,
    )


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
