"""
WoW Raid Event System
Handles raid creation, signups, and character management
"""

import discord
from discord import app_commands
from discord.ui import View, Button, Select
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo
import os
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Default timezone for raid events
# When users create events, they enter times in this timezone
# Discord will then automatically show the correct time for each user's local timezone
# 
# Common European timezones:
#   "Europe/Berlin"  - Germany, most of Central Europe (CET/CEST - UTC+1/+2)
#   "Europe/London"  - UK (GMT/BST - UTC+0/+1)
#   "Europe/Paris"   - France (same as Berlin)
# 
# Other options: "America/New_York", "America/Los_Angeles", "UTC"
# Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones
DEFAULT_TIMEZONE = "Europe/Berlin"  # Change this to your guild's timezone

# ============================================================================
# WoW CLASS AND SPEC DATA
# ============================================================================

# WoW class emojis (Custom Discord emojis)
CLASS_EMOJIS = {
    'Death Knight': '<:deathknight:1422571795097325691>',
    'Demon Hunter': '<:demonhunter:1422571061525872720>',
    'Druid': '<:druid:1422571184859512954>',
    'Evoker': '<:evoker:1422570796701843590>',
    'Hunter': '<:hunter:1422571250047389798>',
    'Mage': '<:mage:1422571804882370652>',
    'Monk': '<:monk:1422571230103601202>',
    'Paladin': '<:paladin:1422570970140508392>',
    'Priest': '<:priest:1422572641989955676>',
    'Rogue': '<:rogue:1422571038226780170>',
    'Shaman': '<:shaman:1422570941170323518>',
    'Warlock': '<:warlock:1422571125455589376>',
    'Warrior': '<:warrior:1422570812971421739>',
}

# Role emojis (Custom Discord emojis)
ROLE_EMOJIS = {
    'tank': '<:tank:1422570700882841610>',
    'healer': '<:healer:1422570731103064176>',
    'melee': '<:melee:1422570750673420352>',
    'ranged': '<:ranged:1422570779874431126>',
}

# Spec emojis (Custom Discord emojis)
SPEC_EMOJIS = {
    # Death Knight
    'Blood': '<:blood:1422570899122688151>',
    'Frost': '<:frostdk:1422570671648800868>',
    'Unholy': '<:unholy:1422570872518213704>',
    # Demon Hunter
    'Havoc': '<:havoc:1422570642699714693>',
    'Vengeance': '<:vengeance:1422570584037920908>',
    # Druid
    'Balance': '<:balance:1422562897975971912>',
    'Feral': '<:feral:1422570561980076174>',
    'Guardian': '<:guardian:1422570550554923072>',
    'Restoration': '<:restodruid:1422562869031206934>',
    # Evoker
    'Devastation': '<:devastation:1422570533781770270>',
    'Preservation': '<:preservation:1422570992131113091>',
    'Augmentation': '<:augmentation:1422570520989405234>',
    # Hunter
    'Beast Mastery': '<:beastmastery:1422570508989497436>',
    'Marksmanship': '<:marksmanship:1422570479557939283>',
    'Survival': '<:survival:1422570463258869920>',
    # Mage
    'Arcane': '<:arcane:1422572651892965488>',
    'Fire': '<:fire:1422571107218624553>',
    'Frost': '<:frostmage:1422571083197976658>',
    # Monk
    'Brewmaster': '<:brewmaster:1422570449212149891>',
    'Mistweaver': '<:mistweaver:1422570438596231229>',
    'Windwalker': '<:windwalker:1422570424109367418>',
    # Paladin
    'Holy': '<:holypala:1422562920633598073>',
    'Protection': '<:protpala:1422570391649648762>',
    'Retribution': '<:retribution:1422570373110825011>',
    # Priest
    'Discipline': '<:discipline:1422570366043295754>',
    'Holy': '<:holypriest:1422570354014163036>',
    'Shadow': '<:shadow:1422570345612709888>',
    # Rogue
    'Assassination': '<:assassination:1422570337714962552>',
    'Outlaw': '<:outlaw:1422570329338941440>',
    'Subtlety': '<:subtlety:1422570318068977744>',
    # Shaman
    'Elemental': '<:elemental:1422570304630161448>',
    'Enhancement': '<:enhancement:1422570295369269308>',
    'Restoration': '<:restoshaman:1422570282907992175>',
    # Warlock
    'Affliction': '<:affliction:1422570226679287869>',
    'Demonology': '<:demonology:1422570215631224873>',
    'Destruction': '<:destruction:1422570204671770779>',
    # Warrior
    'Arms': '<:arms:1422570195007963297>',
    'Fury': '<:fury:1422570186288140381>',
    'Protection': '<:protwarrior:1422570154650239098>',
}

# Status emojis
STATUS_EMOJIS = {
    'signed': '✅',
    'late': '🕐',
    'tentative': '⚖️',
    'absent': '❌',
}

# Class order for display (alphabetical)
CLASS_ORDER = [
    'Death Knight',
    'Demon Hunter',
    'Druid',
    'Evoker',
    'Hunter',
    'Mage',
    'Monk',
    'Paladin',
    'Priest',
    'Rogue',
    'Shaman',
    'Warlock',
    'Warrior',
]

# Melee vs Ranged DPS specs
MELEE_SPECS = {
    'Death Knight': ['Frost', 'Unholy'],
    'Demon Hunter': ['Havoc'],
    'Druid': ['Feral'],
    'Evoker': ['Augmentation'],
    'Hunter': ['Survival'],
    'Monk': ['Windwalker'],
    'Paladin': ['Retribution'],
    'Rogue': ['Assassination', 'Outlaw', 'Subtlety'],
    'Shaman': ['Enhancement'],
    'Warrior': ['Arms', 'Fury'],
}

RANGED_SPECS = {
    'Druid': ['Balance'],
    'Evoker': ['Devastation'],
    'Hunter': ['Beast Mastery', 'Marksmanship'],
    'Mage': ['Arcane', 'Fire', 'Frost'],
    'Priest': ['Shadow'],
    'Shaman': ['Elemental'],
    'Warlock': ['Affliction', 'Demonology', 'Destruction'],
}

# WoW class to available specs mapping
CLASS_SPECS = {
    'Death Knight': {
        'tank': ['Blood'],
        'dps': ['Frost', 'Unholy']
    },
    'Demon Hunter': {
        'tank': ['Vengeance'],
        'dps': ['Havoc']
    },
    'Druid': {
        'tank': ['Guardian'],
        'healer': ['Restoration'],
        'dps': ['Balance', 'Feral']
    },
    'Evoker': {
        'healer': ['Preservation'],
        'dps': ['Devastation', 'Augmentation']
    },
    'Hunter': {
        'dps': ['Beast Mastery', 'Marksmanship', 'Survival']
    },
    'Mage': {
        'dps': ['Arcane', 'Fire', 'Frost']
    },
    'Monk': {
        'tank': ['Brewmaster'],
        'healer': ['Mistweaver'],
        'dps': ['Windwalker']
    },
    'Paladin': {
        'tank': ['Protection'],
        'healer': ['Holy'],
        'dps': ['Retribution']
    },
    'Priest': {
        'healer': ['Discipline', 'Holy'],
        'dps': ['Shadow']
    },
    'Rogue': {
        'dps': ['Assassination', 'Outlaw', 'Subtlety']
    },
    'Shaman': {
        'healer': ['Restoration'],
        'dps': ['Elemental', 'Enhancement']
    },
    'Warlock': {
        'dps': ['Affliction', 'Demonology', 'Destruction']
    },
    'Warrior': {
        'tank': ['Protection'],
        'dps': ['Arms', 'Fury']
    },
}

# ============================================================================
# EMOJI HELPER FUNCTIONS
# ============================================================================

def parse_emoji_for_dropdown(emoji_str: str):
    """
    Convert emoji string to PartialEmoji object for use in SelectOptions.
    
    Custom Discord emojis in format <:name:id> are converted to PartialEmoji objects.
    Unicode emojis are returned as-is.
    
    Args:
        emoji_str: Emoji string (either Unicode or <:name:id> format)
    
    Returns:
        discord.PartialEmoji or str: PartialEmoji object for custom emojis, string for Unicode
    """
    if emoji_str.startswith('<:') and emoji_str.endswith('>'):
        # Extract name and id from <:name:id>
        parts = emoji_str[2:-1].split(':')
        if len(parts) == 2:
            emoji_name, emoji_id = parts
            return discord.PartialEmoji(name=emoji_name, id=int(emoji_id))
    # Unicode emoji - return as string
    return emoji_str

def abbreviate_class_name(class_name: str) -> str:
    """
    Abbreviate long class names for compact display.
    
    Args:
        class_name: Full WoW class name
    
    Returns:
        str: Abbreviated class name
    """
    abbreviations = {
        'Death Knight': 'DK',
        'Demon Hunter': 'DH',
    }
    return abbreviations.get(class_name, class_name)

def parse_date(date_str: str) -> date:
    """
    Parse date string in DD/MM/YYYY, DD.MM.YYYY, or YYYY-MM-DD format.
    
    Args:
        date_str: Date string to parse
    
    Returns:
        date: Parsed date object
    
    Raises:
        ValueError: If date format is invalid
    """
    # Try DD/MM/YYYY format first
    if '/' in date_str:
        parts = date_str.split('/')
        if len(parts) != 3:
            raise ValueError("Date must be in DD/MM/YYYY format (e.g., 25/12/2025)")
        day, month, year = map(int, parts)
        return date(year, month, day)
    
    # Try DD.MM.YYYY format
    elif '.' in date_str:
        parts = date_str.split('.')
        if len(parts) != 3:
            raise ValueError("Date must be in DD.MM.YYYY format (e.g., 25.12.2025)")
        day, month, year = map(int, parts)
        return date(year, month, day)
    
    # Try YYYY-MM-DD format
    elif '-' in date_str:
        parts = date_str.split('-')
        if len(parts) != 3:
            raise ValueError("Date must be in YYYY-MM-DD format (e.g., 2025-12-25)")
        year, month, day = map(int, parts)
        return date(year, month, day)
    
    else:
        raise ValueError("Date must be in DD/MM/YYYY, DD.MM.YYYY, or YYYY-MM-DD format")

def parse_time(time_str: str) -> time:
    """
    Parse time string in HH:MM format (24-hour).
    
    Args:
        time_str: Time string to parse
    
    Returns:
        time: Parsed time object
    
    Raises:
        ValueError: If time format is invalid
    """
    parts = time_str.split(':')
    if len(parts) != 2:
        raise ValueError("Time must be in HH:MM format (e.g., 20:00)")
    
    hour, minute = map(int, parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Invalid time - hour must be 0-23, minute must be 0-59")
    
    return time(hour, minute)

def text_to_emoji_letters(text: str, max_chars: int = 20) -> str:
    """
    Convert text to Discord regional indicator emojis (letter emojis).
    Limits to max_chars to prevent titles from being too long.
    
    Args:
        text: Text to convert
        max_chars: Maximum number of characters to convert (default: 20)
    
    Returns:
        str: Text with letters converted to regional indicator emojis
    
    Examples:
        "Raid Night" -> "🇷 🇦 🇮 🇩   🇳 🇮 🇬 🇭 🇹"
        "Very Long Title That Exceeds" -> "🇻 🇪 🇷 🇾   🇱 🇴 🇳 🇬   🇹 🇮 🇹 🇱 🇪 ..."
    """
    # Truncate text if it's too long (keeping whole words when possible)
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(' ', 1)[0] + '...'
    
    result = []
    for char in text.upper():
        if 'A' <= char <= 'Z':
            # Convert A-Z to regional indicator emojis (🇦-🇿)
            # Regional indicators are Unicode: 🇦 = U+1F1E6, 🇧 = U+1F1E7, etc.
            emoji_code = 0x1F1E6 + (ord(char) - ord('A'))
            result.append(chr(emoji_code))
        elif char == ' ':
            result.append('  ')  # Double space for word separation
        elif char.isdigit():
            # Use digit emojis for numbers
            digit_emojis = ['0️⃣', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
            result.append(digit_emojis[int(char)])
        elif char in '!?.':
            # Keep punctuation as-is (added '.' for ellipsis)
            result.append(char)
        else:
            # Skip other characters
            continue
    
    return ' '.join(result)

def format_countdown(event_datetime: datetime) -> tuple[str, bool]:
    """
    Format a countdown string for the event.
    
    Args:
        event_datetime: The datetime of the event (timezone-aware)
    
    Returns:
        tuple: (countdown_string, is_past) - countdown text and whether event has passed
    """
    # Get current time in UTC to compare with event time
    now = datetime.now(timezone.utc)
    
    # If event_datetime is naive (no timezone), assume UTC
    if event_datetime.tzinfo is None:
        event_datetime = event_datetime.replace(tzinfo=timezone.utc)
    
    time_diff = event_datetime - now
    
    if time_diff.total_seconds() <= 0:
        # Event has passed - calculate how long ago
        abs_diff = abs(time_diff)
        days = abs_diff.days
        hours, remainder = divmod(abs_diff.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        
        if days > 0:
            return (f"{days} day{'s' if days != 1 else ''} ago", True)
        elif hours > 0:
            return (f"{hours} hour{'s' if hours != 1 else ''} ago", True)
        elif minutes > 0:
            return (f"{minutes} minute{'s' if minutes != 1 else ''} ago", True)
        else:
            return ("Just now!", True)
    
    # Calculate time components
    days = time_diff.days
    hours, remainder = divmod(time_diff.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    # Format countdown string
    if days > 1:
        return (f"in {days} days", False)
    elif days == 1:
        return (f"in 1 day, {hours} hours", False)
    elif hours > 1:
        return (f"in {hours} hours", False)
    elif hours == 1:
        return (f"in 1 hour, {minutes} minutes", False)
    elif minutes > 1:
        return (f"in {minutes} minutes", False)
    else:
        return (f"Starting soon!", False)

# ============================================================================
# DATABASE HELPER FUNCTIONS
# ============================================================================

def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST', 'postgres'),
        port=os.getenv('DB_PORT', '5432'),
        database=os.getenv('DB_NAME', 'luminisbot'),
        user=os.getenv('DB_USER', 'luminisbot'),
        password=os.getenv('DB_PASSWORD', 'changeme123')
    )

def get_user_characters(discord_id: str):
    """Get all WoW characters for a Discord user"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT character_name, realm_slug, realm_name, character_class, faction, level
        FROM wow_characters
        WHERE discord_id = %s
        ORDER BY level DESC, character_name ASC
    """, (discord_id,))
    
    characters = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return characters

def get_character_preference(discord_id: str, character_name: str, realm_slug: str):
    """Get saved role/spec preference for a character"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT preferred_role, preferred_spec
        FROM character_preferences
        WHERE discord_id = %s AND character_name = %s AND realm_slug = %s
    """, (discord_id, character_name, realm_slug))
    
    preference = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return preference

def save_character_preference(discord_id: str, character_name: str, realm_slug: str, role: str, spec: str = None):
    """Save role/spec preference for a character"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO character_preferences (discord_id, character_name, realm_slug, preferred_role, preferred_spec)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (discord_id, character_name, realm_slug)
        DO UPDATE SET preferred_role = EXCLUDED.preferred_role,
                      preferred_spec = EXCLUDED.preferred_spec,
                      updated_at = NOW()
    """, (discord_id, character_name, realm_slug, role, spec))
    
    conn.commit()
    cursor.close()
    conn.close()

def get_available_roles_for_class(character_class: str):
    """Get available roles for a WoW class"""
    if character_class not in CLASS_SPECS:
        return []
    
    return list(CLASS_SPECS[character_class].keys())

def get_specs_for_class_and_role(character_class: str, role: str):
    """Get available specs for a class/role combination"""
    if character_class not in CLASS_SPECS:
        return []
    
    if role not in CLASS_SPECS[character_class]:
        return []
    
    return CLASS_SPECS[character_class][role]

def is_melee_dps(character_class: str, spec: str):
    """Check if a spec is melee DPS"""
    if character_class in MELEE_SPECS:
        return spec in MELEE_SPECS[character_class]
    return False

def is_ranged_dps(character_class: str, spec: str):
    """Check if a spec is ranged DPS"""
    if character_class in RANGED_SPECS:
        return spec in RANGED_SPECS[character_class]
    return False

def get_dps_type(character_class: str, spec: str):
    """Get DPS type: 'melee' or 'ranged'"""
    if is_melee_dps(character_class, spec):
        return 'melee'
    elif is_ranged_dps(character_class, spec):
        return 'ranged'
    return 'dps'  # Fallback

# ============================================================================
# RAID EVENT DATABASE FUNCTIONS
# ============================================================================

def create_raid_event(guild_id: int, channel_id: int, message_id: int, title: str, 
                     event_date: date, event_time: time, created_by: int):
    """Create a new raid event in the database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO raid_events (guild_id, channel_id, message_id, title, event_date, event_time, created_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (guild_id, channel_id, message_id, title, event_date, event_time, created_by))
    
    event_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    
    return event_id

def get_raid_event(message_id: int):
    """Get raid event by message ID"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT * FROM raid_events WHERE message_id = %s
    """, (message_id,))
    
    event = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return event

def get_raid_event_by_id(event_id: int):
    """Get raid event by event ID"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT * FROM raid_events WHERE id = %s
    """, (event_id,))
    
    event = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return event

def get_raid_signups(event_id: int, status: str = None):
    """Get all signups for a raid event, optionally filtered by status"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    if status:
        cursor.execute("""
            SELECT * FROM raid_signups
            WHERE event_id = %s AND status = %s
            ORDER BY role, character_class, character_name
        """, (event_id, status))
    else:
        cursor.execute("""
            SELECT * FROM raid_signups
            WHERE event_id = %s
            ORDER BY role, character_class, character_name
        """, (event_id,))
    
    signups = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return signups

def add_raid_signup(event_id: int, discord_id: str, character_name: str, realm_slug: str,
                   character_class: str, role: str, spec: str = None):
    """Add a signup to a raid event"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO raid_signups (event_id, discord_id, character_name, realm_slug, 
                                 character_class, role, spec, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'signed')
        ON CONFLICT (event_id, discord_id)
        DO UPDATE SET character_name = EXCLUDED.character_name,
                      realm_slug = EXCLUDED.realm_slug,
                      character_class = EXCLUDED.character_class,
                      role = EXCLUDED.role,
                      spec = EXCLUDED.spec,
                      status = 'signed',
                      signed_at = NOW()
        RETURNING id
    """, (event_id, discord_id, character_name, realm_slug, character_class, role, spec))
    
    signup_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    
    return signup_id

def update_signup_status(event_id: int, discord_id: str, status: str):
    """Update a user's signup status"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE raid_signups
        SET status = %s
        WHERE event_id = %s AND discord_id = %s
    """, (status, event_id, discord_id))
    
    conn.commit()
    cursor.close()
    conn.close()

def get_user_signup(event_id: int, discord_id: str):
    """Get a user's signup for an event"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT * FROM raid_signups
        WHERE event_id = %s AND discord_id = %s
    """, (event_id, discord_id))
    
    signup = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return signup

def is_event_admin(event_id: int, discord_id: str) -> bool:
    """Check if user is event owner or assistant"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Check if user is the creator
    cursor.execute("""
        SELECT created_by FROM raid_events WHERE id = %s
    """, (event_id,))
    event = cursor.fetchone()
    
    if event and str(event['created_by']) == str(discord_id):
        cursor.close()
        conn.close()
        return True
    
    # Check if user is an assistant
    cursor.execute("""
        SELECT 1 FROM event_assistants
        WHERE event_id = %s AND discord_id = %s
    """, (event_id, discord_id))
    
    is_assistant = cursor.fetchone() is not None
    cursor.close()
    conn.close()
    
    return is_assistant

def get_event_assistants(event_id: int):
    """Get all assistants for an event"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT discord_id, granted_by, granted_at
        FROM event_assistants
        WHERE event_id = %s
        ORDER BY granted_at
    """, (event_id,))
    
    assistants = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return assistants

def add_event_assistant(event_id: int, discord_id: str, granted_by: int):
    """Add an assistant to an event"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO event_assistants (event_id, discord_id, granted_by)
        VALUES (%s, %s, %s)
        ON CONFLICT (event_id, discord_id) DO NOTHING
    """, (event_id, discord_id, granted_by))
    
    conn.commit()
    cursor.close()
    conn.close()

def remove_event_assistant(event_id: int, discord_id: str):
    """Remove an assistant from an event"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM event_assistants
        WHERE event_id = %s AND discord_id = %s
    """, (event_id, discord_id))
    
    conn.commit()
    cursor.close()
    conn.close()

def remove_raid_signup(event_id: int, discord_id: str):
    """Remove a signup from a raid event"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        DELETE FROM raid_signups
        WHERE event_id = %s AND discord_id = %s
    """, (event_id, discord_id))
    
    conn.commit()
    cursor.close()
    conn.close()

def update_signup_status(event_id: int, discord_id: str, new_status: str):
    """Update a signup's status (for admin panel)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE raid_signups
        SET status = %s
        WHERE event_id = %s AND discord_id = %s
    """, (new_status, event_id, discord_id))
    
    conn.commit()
    cursor.close()
    conn.close()

def link_raid_log(event_id: int, log_url: str):
    """Link a Warcraft Logs URL to a raid event"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE raid_events
        SET log_url = %s, log_detected_at = NOW()
        WHERE id = %s
    """, (log_url, event_id))
    
    conn.commit()
    cursor.close()
    conn.close()

def find_matching_raid_event(guild_id: int, log_timestamp: datetime, time_window_hours: int = 1):
    """
    Find raid event that matches the log timestamp.
    Looks for events in the same Discord server (guild) within ±time_window_hours of the log.
    
    Args:
        guild_id: Discord server (guild) ID where log was posted
        log_timestamp: Timestamp of when the raid log started (in UTC)
        time_window_hours: How many hours before/after to search (default: 1)
    
    Returns:
        Event dict if match found, None otherwise
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Convert log timestamp from UTC to the guild's configured timezone
    # Event times are stored in the guild's timezone (e.g., Europe/Berlin)
    # So we need to compare apples to apples
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    log_timestamp_local = log_timestamp.astimezone(tz)
    log_date = log_timestamp_local.date()
    log_time = log_timestamp_local.time()
    
    # Search for events in same guild on same date within time window
    cursor.execute("""
        SELECT * FROM raid_events
        WHERE guild_id = %s
        AND event_date = %s
        AND log_url IS NULL
        AND ABS(EXTRACT(EPOCH FROM (event_time - %s::time))) <= %s
        ORDER BY ABS(EXTRACT(EPOCH FROM (event_time - %s::time)))
        LIMIT 1
    """, (guild_id, log_date, log_time, time_window_hours * 3600, log_time))
    
    event = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return event

def count_signups_by_role(event_id: int, status: str = 'signed'):
    """Count signups by role for an event"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT role, COUNT(*) as count
        FROM raid_signups
        WHERE event_id = %s AND status = %s
        GROUP BY role
    """, (event_id, status))
    
    counts = {row['role']: row['count'] for row in cursor.fetchall()}
    cursor.close()
    conn.close()
    
    return counts

# ============================================================================
# EMBED GENERATION
# ============================================================================

def generate_raid_embed(event_id: int):
    """Generate the raid event embed with all signups"""
    # Get event details
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("SELECT * FROM raid_events WHERE id = %s", (event_id,))
    event = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not event:
        return None
    
    # Format date and time with countdown
    # Combine date and time, treating it as being in the configured timezone
    # Then convert to UTC for Discord timestamp display
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    event_datetime_local = datetime.combine(event['event_date'], event['event_time'], tzinfo=tz)
    event_datetime = event_datetime_local.astimezone(timezone.utc)
    
    countdown_text, is_past = format_countdown(event_datetime)
    
    # Set embed color based on whether event has passed
    embed_color = discord.Color.red() if is_past else discord.Color.blue()
    
    # Convert title to emoji letters
    emoji_title = text_to_emoji_letters(event['title'])
    
    # Create embed with emoji title (no date emoji)
    embed = discord.Embed(
        title=emoji_title,
        color=embed_color,
        timestamp=datetime.now()
    )
    
    # Format date field with Discord timestamp (shows in user's local timezone with hover tooltip!)
    # Discord timestamp format: <t:UNIX_TIMESTAMP:FORMAT>
    # F = Full date/time, R = Relative time ("in 6 days")
    unix_timestamp = int(event_datetime.timestamp())
    
    if is_past:
        # For past events, show red text in ANSI code block
        date_display = f"```ansi\n\u001b[1;31m⚠️ EVENT STARTED - {countdown_text.upper()}\u001b[0m\n{event_datetime.strftime('%A, %d %B %Y at %H:%M')} ({DEFAULT_TIMEZONE})\n```"
    else:
        # Use Discord's native timestamp - shows full date with hover tooltip showing relative time
        # Format: "Saturday, October 5, 2024 at 8:00 PM" (hover shows "in 6 days")
        date_display = f"<t:{unix_timestamp}:F> - ⏰ <t:{unix_timestamp}:R>"
    
    embed.add_field(
        name="\u200b",  # Zero-width space for no visible title
        value=date_display,
        inline=False
    )
    
    # Get signed up players only (for main roster)
    signed_signups = get_raid_signups(event_id, 'signed')
    
    # Count role types
    tank_count = sum(1 for s in signed_signups if s['role'] == 'tank')
    healer_count = sum(1 for s in signed_signups if s['role'] == 'healer')
    melee_count = sum(1 for s in signed_signups if s['role'] == 'dps' and is_melee_dps(s['character_class'], s.get('spec', '')))
    ranged_count = sum(1 for s in signed_signups if s['role'] == 'dps' and is_ranged_dps(s['character_class'], s.get('spec', '')))
    
    # Role summary at the top (no title needed, just the counts)
    role_summary = f"{ROLE_EMOJIS['tank']} **{tank_count}** Tanks  |  {ROLE_EMOJIS['melee']} **{melee_count}** Melee  |  {ROLE_EMOJIS['ranged']} **{ranged_count}** Ranged  |  {ROLE_EMOJIS['healer']} **{healer_count}** Healers"
    embed.add_field(
        name="\u200b",  # Zero-width space for no visible title
        value=role_summary,
        inline=False
    )
    
    # Add spacing between composition and roster
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    
    # Group signups by class
    class_groups = {}
    for signup in signed_signups:
        char_class = signup['character_class']
        if char_class not in class_groups:
            class_groups[char_class] = []
        class_groups[char_class].append(signup)
    
    # Build class sections in 3-column layout
    # We'll create fields for each class
    class_fields = []
    
    for class_name in CLASS_ORDER:
        if class_name not in class_groups:
            continue
        
        players = class_groups[class_name]
        class_emoji = CLASS_EMOJIS.get(class_name, '❓')
        class_display = abbreviate_class_name(class_name)
        
        # Build player list with spec emojis
        player_lines = []
        for player in players:
            spec = player.get('spec', '')
            spec_emoji = SPEC_EMOJIS.get(spec, '')
            char_name = player['character_name']
            player_lines.append(f"{spec_emoji} {char_name}")
        
        # Create field with extra newline at end for spacing between classes
        field_value = "\n".join(player_lines) + "\n\u200b" if player_lines else "_None_"
        class_fields.append({
            'name': f"{class_emoji} **{class_display}** ({len(players)})",
            'value': field_value,
            'inline': True
        })
    
    # Add class fields (Discord supports up to 25 fields, we have max 13 classes)
    if class_fields:
        for field in class_fields:
            embed.add_field(name=field['name'], value=field['value'], inline=field['inline'])
    else:
        embed.add_field(name="📋 Roster", value="_No signups yet_", inline=False)
    
    # Add spacing after roster section (before late/tentative/absent)
    embed.add_field(name="\u200b", value="\u200b", inline=False)
    
    # Late section
    late_signups = get_raid_signups(event_id, 'late')
    if late_signups:
        late_names = []
        for signup in late_signups:
            spec_emoji = SPEC_EMOJIS.get(signup.get('spec', ''), '')
            late_names.append(f"{spec_emoji} {signup['character_name']}")
        
        late_text = "\n".join(late_names)
        
        # Safety check: Discord field value limit is 1024 characters
        if len(late_text) > 1024:
            # Show first N players that fit, then add count
            truncated_names = []
            char_count = 0
            for name in late_names:
                if char_count + len(name) + 1 > 1000:  # +1 for newline
                    break
                truncated_names.append(name)
                char_count += len(name) + 1
            late_text = "\n".join(truncated_names) + f"\n_...and {len(late_signups) - len(truncated_names)} more_"
        
        embed.add_field(
            name=f"🕐 Late ({len(late_signups)})",
            value=late_text,
            inline=False
        )
    
    # Tentative section
    tentative_signups = get_raid_signups(event_id, 'tentative')
    if tentative_signups:
        tentative_names = []
        for signup in tentative_signups:
            spec_emoji = SPEC_EMOJIS.get(signup.get('spec', ''), '')
            tentative_names.append(f"{spec_emoji} {signup['character_name']}")
        
        tentative_text = "\n".join(tentative_names)
        
        # Safety check: Discord field value limit is 1024 characters
        if len(tentative_text) > 1024:
            # Show first N players that fit, then add count
            truncated_names = []
            char_count = 0
            for name in tentative_names:
                if char_count + len(name) + 1 > 1000:  # +1 for newline
                    break
                truncated_names.append(name)
                char_count += len(name) + 1
            tentative_text = "\n".join(truncated_names) + f"\n_...and {len(tentative_signups) - len(truncated_names)} more_"
        
        embed.add_field(
            name=f"⚖️ Tentative ({len(tentative_signups)})",
            value=tentative_text,
            inline=False
        )
    
    # Benched section
    benched_signups = get_raid_signups(event_id, 'benched')
    if benched_signups:
        benched_names = []
        for signup in benched_signups:
            spec_emoji = SPEC_EMOJIS.get(signup.get('spec', ''), '')
            benched_names.append(f"{spec_emoji} {signup['character_name']}")
        
        benched_text = "\n".join(benched_names)
        
        # Safety check: Discord field value limit is 1024 characters
        if len(benched_text) > 1024:
            # Show first N players that fit, then add count
            truncated_names = []
            char_count = 0
            for name in benched_names:
                if char_count + len(name) + 1 > 1000:  # +1 for newline
                    break
                truncated_names.append(name)
                char_count += len(name) + 1
            benched_text = "\n".join(truncated_names) + f"\n_...and {len(benched_signups) - len(truncated_names)} more_"
        
        embed.add_field(
            name=f"🪑 Benched ({len(benched_signups)})",
            value=benched_text,
            inline=False
        )
    
    # Absence section (comma-separated to save space)
    absent_signups = get_raid_signups(event_id, 'absent')
    if absent_signups:
        absence_names = [s['character_name'] for s in absent_signups]
        absence_text = ", ".join(absence_names) if absence_names else "_None_"
        
        # Safety check: Discord field value limit is 1024 characters
        if len(absence_text) > 1024:
            # Truncate and add count
            absence_text = absence_text[:1000] + f"... +{len(absent_signups) - absence_text[:1000].count(',') - 1} more"
        
        embed.add_field(
            name=f"❌ Absence ({len(absent_signups)})",
            value=absence_text,
            inline=False
        )
    
    embed.set_footer(text="Click a button below to sign up or change your status")
    
    # Create view with optional Show Logs button
    view = create_raid_buttons_view(event.get('log_url'))
    
    return embed, view

# ============================================================================
# DISCORD UI COMPONENTS
# ============================================================================

class RaidButtonsView(View):
    """Persistent view with raid signup buttons"""
    
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view
    
    @discord.ui.button(label="Sign Up", style=discord.ButtonStyle.secondary, custom_id="raid:signup", emoji="✅", row=0)
    async def signup_button(self, interaction: discord.Interaction, button: Button):
        """Handle sign up button click"""
        await handle_signup_click(interaction)
    
    @discord.ui.button(label="Late", style=discord.ButtonStyle.secondary, custom_id="raid:late", emoji="🕐", row=0)
    async def late_button(self, interaction: discord.Interaction, button: Button):
        """Handle late button click"""
        await handle_status_change(interaction, 'late')
    
    @discord.ui.button(label="Tentative", style=discord.ButtonStyle.secondary, custom_id="raid:tentative", emoji="⚖️", row=0)
    async def tentative_button(self, interaction: discord.Interaction, button: Button):
        """Handle tentative button click"""
        await handle_status_change(interaction, 'tentative')
    
    @discord.ui.button(label="Absence", style=discord.ButtonStyle.secondary, custom_id="raid:absent", emoji="❌", row=0)
    async def absent_button(self, interaction: discord.Interaction, button: Button):
        """Handle absence button click"""
        await handle_status_change(interaction, 'absent')
    
    @discord.ui.button(label="Change Role", style=discord.ButtonStyle.secondary, custom_id="raid:changerole", emoji="🔄", row=0)
    async def changerole_button(self, interaction: discord.Interaction, button: Button):
        """Handle change role button click"""
        await handle_change_role_click(interaction)
    
    @discord.ui.button(label="Admin Panel", style=discord.ButtonStyle.secondary, custom_id="raid:admin", emoji="⚙️", row=1)
    async def admin_button(self, interaction: discord.Interaction, button: Button):
        """Open admin panel (owner and assistants only)"""
        await handle_admin_panel_click(interaction)


def create_raid_buttons_view(log_url: str = None):
    """Create raid buttons view with optional Show Logs button"""
    view = RaidButtonsView()
    
    # Add Show Logs button if log URL exists
    if log_url:
        # Discord link buttons open URLs directly
        show_logs_button = Button(
            label="Show Logs",
            style=discord.ButtonStyle.link,
            emoji="📊",
            url=log_url,
            row=2
        )
        view.add_item(show_logs_button)
    
    return view


class CharacterSelectDropdown(Select):
    """Dropdown for selecting a WoW character"""
    
    def __init__(self, characters, event_id, show_all=False):
        self.event_id = event_id
        self.all_characters = characters
        self.show_all = show_all
        
        # Filter to max-level characters first (unless show_all is True)
        if not show_all:
            # Filter to level 80 characters
            max_level_chars = [char for char in characters if char.get('level') == 80]
            
            # If no level 80s, find actual max level
            if not max_level_chars:
                levels = [char.get('level', 0) for char in characters if char.get('level') is not None]
                if levels:
                    max_level = max(levels)
                    max_level_chars = [char for char in characters if char.get('level') == max_level]
                else:
                    max_level_chars = characters  # Fallback to all if no levels
            
            # If still too many, take first 24 (leave room for "Show All" option)
            if len(max_level_chars) > 24:
                display_chars = max_level_chars[:24]
            else:
                display_chars = max_level_chars
        else:
            # Show all - take first 25
            display_chars = characters[:25]
        
        # Create options from characters
        options = []
        for char in display_chars:
            label = f"{char['character_name']} - {char.get('realm_name', 'Unknown')}"
            level = char.get('level')
            if level is None:
                level_str = '?'
            else:
                level_str = str(level)
            char_class = char.get('character_class', 'Unknown')
            faction = char.get('faction', 'Unknown')
            description = f"Level {level_str} {char_class} ({faction})"
            
            options.append(discord.SelectOption(
                label=label[:100],  # Discord label limit
                description=description[:100],  # Discord description limit
                value=f"{char['character_name']}|{char['realm_slug']}|{char_class}"
            ))
        
        # Add "Show All Characters" option if we filtered and have more
        if not show_all and len(characters) > len(display_chars):
            options.append(discord.SelectOption(
                label="🔍 Show All Characters...",
                description=f"View all {len(characters)} characters",
                value="__SHOW_ALL__"
            ))
        
        super().__init__(
            placeholder="Choose your character...",
            options=options,
            custom_id="raid:select_character"
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle character selection"""
        # Check if user wants to show all characters
        if self.values[0] == "__SHOW_ALL__":
            # Show all characters view
            view = CharacterSelectView(self.all_characters, self.event_id, show_all=True)
            await interaction.response.edit_message(
                content="🎮 Showing all characters:",
                view=view
            )
            return
        
        # Parse selection
        char_name, realm_slug, char_class = self.values[0].split('|')
        
        # Check for saved preference
        discord_id = str(interaction.user.id)
        preference = get_character_preference(discord_id, char_name, realm_slug)
        
        if preference:
            # Use saved preference
            role = preference['preferred_role']
            spec = preference['preferred_spec']
            
            # Add signup to database (this also updates status to 'signed')
            add_raid_signup(
                self.event_id,
                discord_id,
                char_name,
                realm_slug,
                char_class,
                role,
                spec
            )
            
            # Fetch and update the raid event message
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT message_id, channel_id FROM raid_events WHERE id = %s", (self.event_id,))
            event_data = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if event_data:
                channel = interaction.guild.get_channel(event_data['channel_id'])
                if channel:
                    try:
                        message = await channel.fetch_message(event_data['message_id'])
                        await update_raid_message(message)
                    except Exception as e:
                        logger.error(f"Failed to update raid message: {e}")
            
            await interaction.response.send_message(
                f"✅ Signed up as **{char_name}** ({spec} {role.capitalize()})!",
                ephemeral=True
            )
        else:
            # No preference - show role selection
            await show_role_selection(interaction, char_name, realm_slug, char_class, self.event_id)


class CharacterSelectView(View):
    """View containing character selection dropdown"""
    
    def __init__(self, characters, event_id, show_all=False):
        super().__init__(timeout=180)  # 3 minute timeout
        self.add_item(CharacterSelectDropdown(characters, event_id, show_all))


class RoleSelectDropdown(Select):
    """Dropdown for selecting role"""
    
    def __init__(self, character_name, realm_slug, character_class, event_id, available_roles):
        self.character_name = character_name
        self.realm_slug = realm_slug
        self.character_class = character_class
        self.event_id = event_id
        
        # Create options from available roles
        options = []
        for role in available_roles:
            emoji_str = ROLE_EMOJIS.get(role, '❓')
            emoji = parse_emoji_for_dropdown(emoji_str)
            
            options.append(discord.SelectOption(
                label=role.capitalize(),
                description=f"Sign up as {role}",
                value=role,
                emoji=emoji
            ))
        
        super().__init__(
            placeholder="Choose your role...",
            options=options,
            custom_id="raid:select_role"
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle role selection"""
        role = self.values[0]
        
        # Get available specs for this class/role
        specs = get_specs_for_class_and_role(self.character_class, role)
        
        if len(specs) == 1:
            # Only one spec - use it automatically
            spec = specs[0]
            await finalize_signup(
                interaction,
                self.event_id,
                self.character_name,
                self.realm_slug,
                self.character_class,
                role,
                spec
            )
        else:
            # Multiple specs - show spec selection
            await show_spec_selection(
                interaction,
                self.character_name,
                self.realm_slug,
                self.character_class,
                self.event_id,
                role,
                specs
            )


class RoleSelectView(View):
    """View containing role selection dropdown"""
    
    def __init__(self, character_name, realm_slug, character_class, event_id, available_roles):
        super().__init__(timeout=180)
        self.add_item(RoleSelectDropdown(character_name, realm_slug, character_class, event_id, available_roles))


class SpecSelectDropdown(Select):
    """Dropdown for selecting spec"""
    
    def __init__(self, character_name, realm_slug, character_class, event_id, role, specs):
        self.character_name = character_name
        self.realm_slug = realm_slug
        self.character_class = character_class
        self.event_id = event_id
        self.role = role
        
        # Create options from specs
        options = []
        for spec in specs:
            emoji_str = SPEC_EMOJIS.get(spec, '❓')
            emoji = parse_emoji_for_dropdown(emoji_str)
            
            options.append(discord.SelectOption(
                label=spec,
                value=spec,
                emoji=emoji
            ))
        
        super().__init__(
            placeholder="Choose your specialization...",
            options=options,
            custom_id="raid:select_spec"
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle spec selection"""
        spec = self.values[0]
        await finalize_signup(
            interaction,
            self.event_id,
            self.character_name,
            self.realm_slug,
            self.character_class,
            self.role,
            spec
        )


class SpecSelectView(View):
    """View containing spec selection dropdown"""
    
    def __init__(self, character_name, realm_slug, character_class, event_id, role, specs):
        super().__init__(timeout=180)
        self.add_item(SpecSelectDropdown(character_name, realm_slug, character_class, event_id, role, specs))


class EditEventModal(discord.ui.Modal, title="Edit Raid Event"):
    """Modal for editing raid event details"""
    
    def __init__(self, event):
        super().__init__()
        self.event = event
        
        # Add input fields with current values
        event_datetime = datetime.combine(event['event_date'], event['event_time'])
        
        self.title_input = discord.ui.TextInput(
            label="Event Title",
            default=event['title'],
            max_length=100,
            required=True
        )
        self.add_item(self.title_input)
        
        self.date_input = discord.ui.TextInput(
            label="Date (YYYY-MM-DD or DD/MM/YYYY)",
            default=event['event_date'].strftime("%Y-%m-%d"),
            placeholder="2025-12-25 or 25/12/2025",
            max_length=20,
            required=True
        )
        self.add_item(self.date_input)
        
        self.time_input = discord.ui.TextInput(
            label="Time (HH:MM in 24h format)",
            default=event['event_time'].strftime("%H:%M"),
            placeholder="20:00",
            max_length=5,
            required=True
        )
        self.add_item(self.time_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        """Handle modal submission"""
        try:
            # Parse new date and time using functions from this module
            new_date = parse_date(self.date_input.value)
            new_time = parse_time(self.time_input.value)
            new_title = self.title_input.value
            
            # Update event in database
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE raid_events
                SET title = %s, event_date = %s, event_time = %s
                WHERE id = %s
            """, (new_title, new_date, new_time, self.event['id']))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            # Update the embed
            message = interaction.message if interaction.message else await interaction.channel.fetch_message(self.event['message_id'])
            embed, view = generate_raid_embed(self.event['id'])
            if embed:
                await message.edit(embed=embed, view=view)
            
            await interaction.response.send_message(
                f"✅ Event updated successfully!\n**{new_title}** - {new_date.strftime('%d/%m/%Y')} at {new_time.strftime('%H:%M')}",
                ephemeral=True
            )
        except ValueError as e:
            await interaction.response.send_message(
                f"❌ Invalid date or time format: {e}",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error updating event: {e}",
                ephemeral=True
            )


class ConfirmDeleteView(View):
    """View with confirm/cancel buttons for event deletion"""
    
    def __init__(self, event_id, message_id):
        super().__init__(timeout=60)
        self.event_id = event_id
        self.message_id = message_id
    
    @discord.ui.button(label="Confirm Delete", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        """Confirm deletion"""
        try:
            # Delete from database
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Delete signups first (foreign key constraint)
            cursor.execute("DELETE FROM raid_signups WHERE event_id = %s", (self.event_id,))
            # Delete event
            cursor.execute("DELETE FROM raid_events WHERE id = %s", (self.event_id,))
            
            conn.commit()
            cursor.close()
            conn.close()
            
            # Delete the message
            try:
                message = await interaction.channel.fetch_message(self.message_id)
                await message.delete()
            except:
                pass  # Message might already be deleted
            
            await interaction.response.send_message(
                "✅ Event deleted successfully!",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Error deleting event: {e}",
                ephemeral=True
            )
        
        # Disable buttons
        self.stop()
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        """Cancel deletion"""
        await interaction.response.send_message(
            "Deletion cancelled.",
            ephemeral=True
        )
        self.stop()


class MovePlayerSelectView(View):
    """View for selecting a player to move"""
    
    def __init__(self, event_id, signups):
        super().__init__(timeout=60)
        self.event_id = event_id
        
        # Create dropdown with players (max 25 options)
        options = []
        for signup in signups[:25]:
            status_emoji = {'signed': '✅', 'late': '🕐', 'tentative': '⚖️', 'benched': '🪑', 'absent': '❌'}.get(signup['status'], '❓')
            options.append(discord.SelectOption(
                label=f"{signup['character_name']} ({signup['status'].title()})",
                description=f"{signup['character_class']} - {signup['role']}",
                value=f"{signup['discord_id']}|{signup['character_name']}|{signup['status']}",
                emoji=status_emoji
            ))
        
        self.player_select = Select(
            placeholder="Choose a player to move...",
            options=options,
            row=0
        )
        self.player_select.callback = self.player_selected
        self.add_item(self.player_select)
    
    async def player_selected(self, interaction: discord.Interaction):
        """Handle player selection"""
        discord_id, char_name, current_status = self.player_select.values[0].split('|')
        
        # Show status options
        view = MovePlayerStatusView(self.event_id, discord_id, char_name, current_status)
        await interaction.response.send_message(
            f"Move **{char_name}** to which status?",
            view=view,
            ephemeral=True
        )


class MovePlayerStatusView(View):
    """View for selecting new status for a player"""
    
    def __init__(self, event_id, discord_id, char_name, current_status):
        super().__init__(timeout=60)
        self.event_id = event_id
        self.discord_id = discord_id
        self.char_name = char_name
        self.current_status = current_status
        
        # Create dropdown with status options (excluding current status)
        statuses = [
            ('signed', '✅ Signed', 'Move to main roster'),
            ('late', '🕐 Late', 'Mark as arriving late'),
            ('tentative', '⚖️ Tentative', 'Mark as tentative'),
            ('benched', '🪑 Benched', 'Move to bench'),
            ('absent', '❌ Absent', 'Mark as absent')
        ]
        
        options = []
        for status_value, status_label, status_desc in statuses:
            if status_value != current_status:
                options.append(discord.SelectOption(
                    label=status_label,
                    description=status_desc,
                    value=status_value
                ))
        
        self.status_select = Select(
            placeholder="Choose new status...",
            options=options,
            row=0
        )
        self.status_select.callback = self.status_selected
        self.add_item(self.status_select)
    
    async def status_selected(self, interaction: discord.Interaction):
        """Handle status selection"""
        new_status = self.status_select.values[0]
        
        # Update the status
        update_signup_status(self.event_id, self.discord_id, new_status)
        
        # Update the raid message
        event = get_raid_event_by_id(self.event_id)
        if event:
            try:
                channel = interaction.guild.get_channel(event['channel_id'])
                message = await channel.fetch_message(event['message_id'])
                embed, view = generate_raid_embed(self.event_id)
                await message.edit(embed=embed, view=view)
            except:
                pass
        
        status_names = {'signed': 'Signed', 'late': 'Late', 'tentative': 'Tentative', 'benched': 'Benched', 'absent': 'Absent'}
        await interaction.response.send_message(
            f"✅ Moved **{self.char_name}** to **{status_names[new_status]}**!",
            ephemeral=True
        )


class RemovePlayerSelectView(View):
    """View for selecting a player to remove"""
    
    def __init__(self, event_id, signups):
        super().__init__(timeout=60)
        self.event_id = event_id
        
        # Create dropdown with players (max 25 options)
        options = []
        for signup in signups[:25]:
            status_emoji = {'signed': '✅', 'late': '🕐', 'tentative': '⚖️', 'benched': '🪑', 'absent': '❌'}.get(signup['status'], '❓')
            options.append(discord.SelectOption(
                label=f"{signup['character_name']} ({signup['status'].title()})",
                description=f"{signup['character_class']} - {signup['role']}",
                value=f"{signup['discord_id']}|{signup['character_name']}",
                emoji=status_emoji
            ))
        
        self.player_select = Select(
            placeholder="Choose a player to remove...",
            options=options,
            row=0
        )
        self.player_select.callback = self.player_selected
        self.add_item(self.player_select)
    
    async def player_selected(self, interaction: discord.Interaction):
        """Handle player selection - confirm removal"""
        discord_id, char_name = self.player_select.values[0].split('|')
        
        # Confirm removal
        view = ConfirmRemovePlayerView(self.event_id, discord_id, char_name)
        await interaction.response.send_message(
            f"⚠️ Are you sure you want to remove **{char_name}** from this event?",
            view=view,
            ephemeral=True
        )


class ConfirmRemovePlayerView(View):
    """View for confirming player removal"""
    
    def __init__(self, event_id, discord_id, char_name):
        super().__init__(timeout=60)
        self.event_id = event_id
        self.discord_id = discord_id
        self.char_name = char_name
    
    @discord.ui.button(label="Confirm Remove", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: Button):
        """Confirm removal"""
        # Remove the signup
        remove_raid_signup(self.event_id, self.discord_id)
        
        # Update the raid message
        event = get_raid_event_by_id(self.event_id)
        if event:
            try:
                channel = interaction.guild.get_channel(event['channel_id'])
                message = await channel.fetch_message(event['message_id'])
                embed, view = generate_raid_embed(self.event_id)
                await message.edit(embed=embed, view=view)
            except:
                pass
        
        await interaction.response.send_message(
            f"✅ Removed **{self.char_name}** from the event!",
            ephemeral=True
        )
        self.stop()
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        """Cancel removal"""
        await interaction.response.send_message(
            "Removal cancelled.",
            ephemeral=True
        )
        self.stop()


class ManageAssistantsView(View):
    """View for managing event assistants"""
    
    def __init__(self, event_id):
        super().__init__(timeout=120)
        self.event_id = event_id
    
    @discord.ui.button(label="Add Assistant", style=discord.ButtonStyle.success, emoji="➕", row=0)
    async def add_assistant_button(self, interaction: discord.Interaction, button: Button):
        """Add an assistant"""
        view = AddAssistantSelectView(self.event_id)
        await interaction.response.send_message(
            "Select a user to add as an event assistant:",
            view=view,
            ephemeral=True
        )
    
    @discord.ui.button(label="Remove Assistant", style=discord.ButtonStyle.danger, emoji="➖", row=0)
    async def remove_assistant_button(self, interaction: discord.Interaction, button: Button):
        """Remove an assistant"""
        assistants = get_event_assistants(self.event_id)
        
        if not assistants:
            await interaction.response.send_message(
                "❌ No assistants to remove!",
                ephemeral=True
            )
            return
        
        view = RemoveAssistantSelectView(self.event_id, assistants)
        await interaction.response.send_message(
            "Select an assistant to remove:",
            view=view,
            ephemeral=True
        )


class AddAssistantSelectView(View):
    """View for selecting a user to add as assistant"""
    
    def __init__(self, event_id):
        super().__init__(timeout=60)
        self.event_id = event_id
        
        # Add user select dropdown
        self.user_select = discord.ui.UserSelect(
            placeholder="Select a user to add as assistant",
            min_values=1,
            max_values=1
        )
        self.user_select.callback = self.user_selected
        self.add_item(self.user_select)
    
    async def user_selected(self, interaction: discord.Interaction):
        """Handle user selection"""
        selected_user = self.user_select.values[0]
        user_id = str(selected_user.id)
        
        # Check if user is already creator
        event = get_raid_event_by_id(self.event_id)
        if event and str(event['created_by']) == user_id:
            await interaction.response.send_message(
                "❌ The event creator is already an admin!",
                ephemeral=True
            )
            return
        
        # Check if user is already an assistant
        assistants = get_event_assistants(self.event_id)
        if any(str(a['discord_id']) == user_id for a in assistants):
            await interaction.response.send_message(
                f"❌ {selected_user.mention} is already an event assistant!",
                ephemeral=True
            )
            return
        
        # Add assistant
        add_event_assistant(self.event_id, user_id, interaction.user.id)
        
        await interaction.response.send_message(
            f"✅ Added {selected_user.mention} as an event assistant!",
            ephemeral=True
        )
        self.stop()


class RemoveAssistantSelectView(View):
    """View for selecting an assistant to remove using Discord's UserSelect"""
    
    def __init__(self, event_id, assistants):
        super().__init__(timeout=60)
        self.event_id = event_id
        self.assistant_ids = [str(assistant['discord_id']) for assistant in assistants]
        
        # Use Discord's native UserSelect - shows usernames automatically!
        self.user_select = discord.ui.UserSelect(
            placeholder="Select an assistant to remove",
            min_values=1,
            max_values=1
        )
        self.user_select.callback = self.user_selected
        self.add_item(self.user_select)
    
    async def user_selected(self, interaction: discord.Interaction):
        """Handle user selection"""
        selected_user = self.user_select.values[0]
        user_id = str(selected_user.id)
        
        # Check if the selected user is actually an assistant
        if user_id not in self.assistant_ids:
            await interaction.response.send_message(
                f"❌ {selected_user.mention} is not an assistant for this event!",
                ephemeral=True
            )
            return
        
        # Remove assistant
        remove_event_assistant(self.event_id, user_id)
        
        await interaction.response.send_message(
            f"✅ Removed {selected_user.mention} as an event assistant!",
            ephemeral=True
        )
        self.stop()


class AdminPanelView(View):
    """Admin panel for managing raid events"""
    
    def __init__(self, event_id, event, admin_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.event_id = event_id
        self.event = event
        self.admin_id = admin_id
        self.is_owner = str(event['created_by']) == str(admin_id)
    
    @discord.ui.button(label="Move Player", style=discord.ButtonStyle.primary, emoji="➡️", row=0)
    async def move_player_button(self, interaction: discord.Interaction, button: Button):
        """Move a player to a different status"""
        # Get all signups for the event
        all_signups = []
        for status in ['signed', 'late', 'tentative', 'benched', 'absent']:
            signups = get_raid_signups(self.event_id, status)
            all_signups.extend(signups)
        
        if not all_signups:
            await interaction.response.send_message(
                "❌ No players have signed up yet!",
                ephemeral=True
            )
            return
        
        # Create dropdown with all players
        view = MovePlayerSelectView(self.event_id, all_signups)
        await interaction.response.send_message(
            "Select a player to move:",
            view=view,
            ephemeral=True
        )
    
    @discord.ui.button(label="Remove Player", style=discord.ButtonStyle.danger, emoji="🗑️", row=0)
    async def remove_player_button(self, interaction: discord.Interaction, button: Button):
        """Remove a player from the event"""
        # Get all signups for the event
        all_signups = []
        for status in ['signed', 'late', 'tentative', 'benched', 'absent']:
            signups = get_raid_signups(self.event_id, status)
            all_signups.extend(signups)
        
        if not all_signups:
            await interaction.response.send_message(
                "❌ No players have signed up yet!",
                ephemeral=True
            )
            return
        
        # Create dropdown with all players
        view = RemovePlayerSelectView(self.event_id, all_signups)
        await interaction.response.send_message(
            "Select a player to remove:",
            view=view,
            ephemeral=True
        )
    
    @discord.ui.button(label="Manage Assistants", style=discord.ButtonStyle.secondary, emoji="👥", row=1)
    async def manage_assistants_button(self, interaction: discord.Interaction, button: Button):
        """Manage event assistants (owner only)"""
        if not self.is_owner:
            await interaction.response.send_message(
                "❌ Only the event creator can manage assistants!",
                ephemeral=True
            )
            return
        
        view = ManageAssistantsView(self.event_id)
        await interaction.response.send_message(
            "Enter the Discord User ID or mention of the user to add as assistant:",
            view=view,
            ephemeral=True
        )
    
    @discord.ui.button(label="Edit Event", style=discord.ButtonStyle.secondary, emoji="✏️", row=2)
    async def edit_event_button(self, interaction: discord.Interaction, button: Button):
        """Edit event details (owner and assistants only)"""
        await handle_edit_event_click(interaction)
    
    @discord.ui.button(label="Delete Event", style=discord.ButtonStyle.danger, emoji="🗑️", row=2)
    async def delete_event_button(self, interaction: discord.Interaction, button: Button):
        """Delete event (owner and assistants only)"""
        await handle_delete_event_click(interaction)
    
    @discord.ui.button(label="Invite Macro", style=discord.ButtonStyle.secondary, emoji="📋", row=2)
    async def invite_macro_button(self, interaction: discord.Interaction, button: Button):
        """Generate WoW invite macro (owner and assistants only)"""
        await handle_invite_macro_click(interaction)


# ============================================================================
# BUTTON HANDLER FUNCTIONS
# ============================================================================

async def handle_signup_click(interaction: discord.Interaction):
    """Handle sign up button click"""
    discord_id = str(interaction.user.id)
    
    # Get user's characters
    characters = get_user_characters(discord_id)
    
    if not characters:
        # No characters - prompt to connect account
        await interaction.response.send_message(
            "❌ You haven't connected your Battle.net account yet!\n\n"
            "Please use the `/connectwow` command to link your WoW characters first.",
            ephemeral=True
        )
        return
    
    # Get event ID from message
    event = get_raid_event(interaction.message.id)
    if not event:
        await interaction.response.send_message("❌ Raid event not found!", ephemeral=True)
        return
    
    event_id = event['id']
    
    # Show character selection
    view = CharacterSelectView(characters, event_id)
    await interaction.response.send_message(
        "🎮 Select your character:",
        view=view,
        ephemeral=True
    )


async def handle_status_change(interaction: discord.Interaction, new_status: str):
    """Handle status change button clicks (late/tentative/absent)"""
    discord_id = str(interaction.user.id)
    
    # Get event
    event = get_raid_event(interaction.message.id)
    if not event:
        await interaction.response.send_message("❌ Raid event not found!", ephemeral=True)
        return
    
    event_id = event['id']
    
    # Check if user is signed up
    signup = get_user_signup(event_id, discord_id)
    
    if not signup:
        await interaction.response.send_message(
            "❌ You need to sign up first before changing your status!",
            ephemeral=True
        )
        return
    
    # Update status
    update_signup_status(event_id, discord_id, new_status)
    
    # Update embed
    await update_raid_message(interaction.message)
    
    status_names = {
        'late': 'Late',
        'tentative': 'Tentative',
        'absent': 'Absent',
        'signed': 'Signed Up'
    }
    
    await interaction.response.send_message(
        f"✅ Status updated to **{status_names[new_status]}**!",
        ephemeral=True
    )


async def handle_change_role_click(interaction: discord.Interaction):
    """Handle change role button click"""
    discord_id = str(interaction.user.id)
    
    # Get event
    event = get_raid_event(interaction.message.id)
    if not event:
        await interaction.response.send_message("❌ Raid event not found!", ephemeral=True)
        return
    
    event_id = event['id']
    
    # Check if user is signed up
    signup = get_user_signup(event_id, discord_id)
    
    if not signup:
        await interaction.response.send_message(
            "❌ You need to sign up first before changing your role!",
            ephemeral=True
        )
        return
    
    # Show role selection
    char_class = signup['character_class']
    available_roles = get_available_roles_for_class(char_class)
    
    await show_role_selection(
        interaction,
        signup['character_name'],
        signup['realm_slug'],
        char_class,
        event_id,
        is_change=True
    )


async def handle_edit_event_click(interaction: discord.Interaction):
    """Handle edit event button click (owner and assistants only)"""
    # Get event
    event = get_raid_event(interaction.message.id)
    if not event:
        await interaction.response.send_message("❌ Raid event not found!", ephemeral=True)
        return
    
    # Check if user is admin (owner or assistant)
    event_id = event['id']
    if not is_event_admin(event_id, str(interaction.user.id)):
        await interaction.response.send_message(
            "❌ Only the event creator and assistants can edit this event!",
            ephemeral=True
        )
        return
    
    # Show edit modal
    modal = EditEventModal(event)
    await interaction.response.send_modal(modal)


async def handle_delete_event_click(interaction: discord.Interaction):
    """Handle delete event button click (owner and assistants only)"""
    # Get event
    event = get_raid_event(interaction.message.id)
    if not event:
        await interaction.response.send_message("❌ Raid event not found!", ephemeral=True)
        return
    
    # Check if user is admin (owner or assistant)
    event_id = event['id']
    if not is_event_admin(event_id, str(interaction.user.id)):
        await interaction.response.send_message(
            "❌ Only the event creator and assistants can delete this event!",
            ephemeral=True
        )
        return
    
    # Confirm deletion
    view = ConfirmDeleteView(event['id'], interaction.message.id)
    await interaction.response.send_message(
        f"⚠️ Are you sure you want to delete the event **{event['title']}**?\nThis will remove all signups and cannot be undone!",
        view=view,
        ephemeral=True
    )


async def handle_invite_macro_click(interaction: discord.Interaction):
    """Generate WoW invite macro for all signed up players (owner and assistants only)"""
    # Get event
    event = get_raid_event(interaction.message.id)
    if not event:
        await interaction.response.send_message("❌ Raid event not found!", ephemeral=True)
        return
    
    # Check if user is admin (owner or assistant)
    event_id = event['id']
    if not is_event_admin(event_id, str(interaction.user.id)):
        await interaction.response.send_message(
            "❌ Only the event creator and assistants can generate the invite macro!",
            ephemeral=True
        )
        return
    
    # Get all signed up players (status = 'signed')
    signed_signups = get_raid_signups(event_id, 'signed')
    
    if not signed_signups:
        await interaction.response.send_message(
            "❌ No one has signed up yet!",
            ephemeral=True
        )
        return
    
    # Extract character names with realm (max 40 characters for WoW raid)
    # Format: "CharacterName-RealmSlug" for cross-realm invites
    character_invites = []
    for signup in signed_signups[:40]:
        char_name = signup['character_name']
        realm_slug = signup['realm_slug']
        # WoW uses format: /invite CharacterName-RealmSlug
        character_invites.append(f"{char_name}-{realm_slug}")
    
    # Create WoW invite macro
    # WoW macros have a 255 character limit per line, so we need to split into multiple lines
    invite_commands = []
    for invite_target in character_invites:
        invite_commands.append(f"/invite {invite_target}")
    
    # Split into chunks of ~10 invites per macro (to stay under 255 char limit)
    macro_chunks = []
    chunk_size = 10
    for i in range(0, len(invite_commands), chunk_size):
        chunk = invite_commands[i:i + chunk_size]
        macro_text = "\n".join(chunk)
        macro_chunks.append(macro_text)
    
    # Format the response
    response = f"📋 **WoW Invite Macro for {event['title']}**\n"
    response += f"Found **{len(character_invites)}** signed up players.\n\n"
    
    if len(macro_chunks) == 1:
        response += "Copy and paste this into WoW chat:\n```\n"
        response += macro_chunks[0]
        response += "\n```"
    else:
        response += f"Due to character limits, split into {len(macro_chunks)} parts:\n\n"
        for idx, chunk in enumerate(macro_chunks, 1):
            response += f"**Part {idx}:**\n```\n{chunk}\n```\n"
    
    await interaction.response.send_message(response, ephemeral=True)


async def handle_admin_panel_click(interaction: discord.Interaction):
    """Open admin panel for managing the raid event (owner and assistants only)"""
    # Get event
    event = get_raid_event(interaction.message.id)
    if not event:
        await interaction.response.send_message("❌ Raid event not found!", ephemeral=True)
        return
    
    event_id = event['id']
    
    # Check if user is admin (owner or assistant)
    if not is_event_admin(event_id, str(interaction.user.id)):
        await interaction.response.send_message(
            "❌ Only the event creator and assistants can access the admin panel!",
            ephemeral=True
        )
        return
    
    # Show admin panel
    view = AdminPanelView(event_id, event, interaction.user.id)
    
    # Get current assistants
    assistants = get_event_assistants(event_id)
    assistant_list = "\n".join([f"<@{a['discord_id']}>" for a in assistants]) if assistants else "_None_"
    
    # Build player roster for quick reference
    roster_text = ""
    for status in ['signed', 'late', 'tentative', 'benched', 'absent']:
        signups = get_raid_signups(event_id, status)
        if signups:
            status_display = {
                'signed': '✅ Signed',
                'late': '🕐 Late', 
                'tentative': '⚖️ Tentative',
                'benched': '🪑 Benched',
                'absent': '❌ Absent'
            }[status]
            
            roster_text += f"\n**{status_display}** ({len(signups)}):\n"
            for signup in signups[:10]:  # Limit to 10 per status to avoid embed size limit
                role_emoji = ROLE_EMOJIS.get(signup['role'], '')
                roster_text += f"{role_emoji} {signup['character_name']} ({signup['character_class']})\n"
            
            if len(signups) > 10:
                roster_text += f"_...and {len(signups) - 10} more_\n"
    
    if not roster_text:
        roster_text = "_No players signed up yet_"
    
    embed = discord.Embed(
        title="⚙️ Admin Panel",
        description=f"**Event:** {event['title']}\n\n**Current Assistants:**\n{assistant_list}",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="📋 Current Roster",
        value=roster_text,
        inline=False
    )
    
    embed.add_field(
        name="📝 Available Actions",
        value="• **Move Player** - Change a player's status\n• **Remove Player** - Remove a player from the event\n• **Manage Assistants** - Grant/revoke admin rights\n• **Edit Event** - Change event details\n• **Delete Event** - Remove the entire event\n• **Invite Macro** - Generate WoW invite commands",
        inline=False
    )
    
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def show_role_selection(interaction: discord.Interaction, character_name: str, 
                              realm_slug: str, character_class: str, event_id: int, is_change=False):
    """Show role selection dropdown"""
    available_roles = get_available_roles_for_class(character_class)
    
    if not available_roles:
        await interaction.response.send_message(
            f"❌ No roles available for {character_class}!",
            ephemeral=True
        )
        return
    
    view = RoleSelectView(character_name, realm_slug, character_class, event_id, available_roles)
    
    message = "🎭 Choose your role:" if not is_change else "🔄 Change your role:"
    
    if interaction.response.is_done():
        await interaction.followup.send(message, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(message, view=view, ephemeral=True)


async def show_spec_selection(interaction: discord.Interaction, character_name: str,
                              realm_slug: str, character_class: str, event_id: int, role: str, specs: list):
    """Show spec selection dropdown"""
    view = SpecSelectView(character_name, realm_slug, character_class, event_id, role, specs)
    
    await interaction.response.send_message(
        "⚔️ Choose your specialization:",
        view=view,
        ephemeral=True
    )


async def finalize_signup(interaction: discord.Interaction, event_id: int, character_name: str,
                         realm_slug: str, character_class: str, role: str, spec: str):
    """Finalize the signup and update the embed"""
    discord_id = str(interaction.user.id)
    
    # Save preference
    save_character_preference(discord_id, character_name, realm_slug, role, spec)
    
    # Add signup
    add_raid_signup(event_id, discord_id, character_name, realm_slug, character_class, role, spec)
    
    # Get the original message
    event = get_raid_event(None)  # We need to find by event_id
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT message_id, channel_id FROM raid_events WHERE id = %s", (event_id,))
    event_data = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if event_data:
        # Fetch the message and update it
        channel = interaction.guild.get_channel(event_data['channel_id'])
        if channel:
            try:
                message = await channel.fetch_message(event_data['message_id'])
                await update_raid_message(message)
            except:
                pass
    
    await interaction.response.send_message(
        f"✅ Signed up as **{character_name}** ({spec} {role.capitalize()})!",
        ephemeral=True
    )


async def update_raid_message(message: discord.Message):
    """Update the raid embed message"""
    event = get_raid_event(message.id)
    if not event:
        return
    
    embed, view = generate_raid_embed(event['id'])
    if embed:
        await message.edit(embed=embed, view=view)


# ============================================================================
# BACKGROUND TASKS
# ============================================================================

def cleanup_old_events():
    """Delete raid events that are more than 24 hours old"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Calculate cutoff time (24 hours after event datetime)
        cursor.execute("""
            DELETE FROM raid_signups
            WHERE event_id IN (
                SELECT id FROM raid_events
                WHERE (event_date + event_time) < (NOW() - INTERVAL '24 hours')
            )
        """)
        
        cursor.execute("""
            DELETE FROM raid_events
            WHERE (event_date + event_time) < (NOW() - INTERVAL '24 hours')
            RETURNING id, title
        """)
        
        deleted = cursor.fetchall()
        conn.commit()
        
        if deleted:
            logger.info(f"Cleaned up {len(deleted)} old raid events")
            for event_id, title in deleted:
                logger.info(f"  - Deleted: {title} (ID: {event_id})")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"Error cleaning up old events: {e}")


async def auto_link_raid_log(bot, guild_id: int, log_url: str, log_timestamp: datetime):
    """
    Automatically link a raid log to a matching event.
    Called when a new raid log is detected.
    
    Args:
        bot: Discord bot instance
        guild_id: Discord server (guild) ID where log was posted
        log_url: Warcraft Logs URL
        log_timestamp: When the raid started
    
    Returns:
        bool: True if linked successfully, False otherwise
    """
    try:
        # Find matching event in the guild
        event = find_matching_raid_event(guild_id, log_timestamp, time_window_hours=1)
        
        if not event:
            logger.info(f"[RAID LOGS] No matching event found for log in guild {guild_id} at {log_timestamp}")
            return False
        
        # Link the log to the event
        link_raid_log(event['id'], log_url)
        logger.info(f"[RAID LOGS] Linked log to event '{event['title']}' (ID: {event['id']})")
        
        # Update the Discord message with the new Show Logs button
        try:
            channel = bot.get_channel(event['channel_id'])
            if channel:
                message = await channel.fetch_message(event['message_id'])
                embed, view = generate_raid_embed(event['id'])
                await message.edit(embed=embed, view=view)
                logger.info(f"[RAID LOGS] Updated event message with Show Logs button")
        except Exception as e:
            logger.error(f"[RAID LOGS] Failed to update message: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"[RAID LOGS] Error auto-linking raid log: {e}")
        return False


