"""
WoW Raid Event System
Handles raid creation, signups, and character management
"""

import discord
from discord import app_commands
from discord.ui import View, Button, Select
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, time
import os
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# WoW CLASS AND SPEC DATA
# ============================================================================

# WoW class emojis (using Unicode - can be replaced with custom Discord emojis later)
CLASS_EMOJIS = {
    'Death Knight': '🛡️',
    'Demon Hunter': '🐉',
    'Druid': '🌿',
    'Evoker': '🐲',
    'Hunter': '🏹',
    'Mage': '🔮',
    'Monk': '🥋',
    'Paladin': '⚔️',
    'Priest': '✨',
    'Rogue': '🗡️',
    'Shaman': '⚡',
    'Warlock': '💀',
    'Warrior': '⚔️',
}

# Role emojis
ROLE_EMOJIS = {
    'tank': '🛡️',
    'healer': '💚',
    'dps': '⚔️',
}

# Status emojis
STATUS_EMOJIS = {
    'signed': '✅',
    'late': '🕐',
    'tentative': '⚖️',
    'absent': '❌',
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

# Default role limits for raids
ROLE_LIMITS = {
    'tank': 3,
    'healer': 5,
    'dps': 20,  # Flexible limit
}

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
        SELECT character_name, realm_slug, realm_name, character_class, faction
        FROM wow_characters
        WHERE discord_id = %s
        ORDER BY character_name
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
    
    # Create embed
    embed = discord.Embed(
        title=f"📅 {event['title']}",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    # Format date and time
    event_datetime = datetime.combine(event['event_date'], event['event_time'])
    embed.add_field(
        name="🗓️ Date & Time",
        value=event_datetime.strftime("%A, %d %B %Y %H:%M"),
        inline=False
    )
    
    # Get signups by status
    signed_signups = get_raid_signups(event_id, 'signed')
    late_signups = get_raid_signups(event_id, 'late')
    tentative_signups = get_raid_signups(event_id, 'tentative')
    absent_signups = get_raid_signups(event_id, 'absent')
    
    # Group signed signups by role
    tanks = [s for s in signed_signups if s['role'] == 'tank']
    healers = [s for s in signed_signups if s['role'] == 'healer']
    dps = [s for s in signed_signups if s['role'] == 'dps']
    
    # Build role sections
    def format_signup_list(signups, show_role=True):
        """Format a list of signups with emojis"""
        if not signups:
            return "_No signups yet_"
        
        lines = []
        for signup in signups:
            class_emoji = CLASS_EMOJIS.get(signup['character_class'], '❓')
            name = signup['character_name']
            spec = f" ({signup['spec']})" if signup.get('spec') else ""
            lines.append(f"{class_emoji} **{name}**{spec}")
        
        return "\n".join(lines)
    
    # Tanks section
    tank_count = len(tanks)
    tank_limit = ROLE_LIMITS['tank']
    embed.add_field(
        name=f"🛡️ Tanks ({tank_count}/{tank_limit})",
        value=format_signup_list(tanks),
        inline=False
    )
    
    # Healers section
    healer_count = len(healers)
    healer_limit = ROLE_LIMITS['healer']
    embed.add_field(
        name=f"💚 Healers ({healer_count}/{healer_limit})",
        value=format_signup_list(healers),
        inline=False
    )
    
    # DPS section
    dps_count = len(dps)
    dps_limit = ROLE_LIMITS['dps']
    embed.add_field(
        name=f"⚔️ DPS ({dps_count}/{dps_limit})",
        value=format_signup_list(dps),
        inline=False
    )
    
    # Late section
    if late_signups:
        embed.add_field(
            name=f"🕐 Late ({len(late_signups)})",
            value=format_signup_list(late_signups),
            inline=False
        )
    
    # Tentative section
    if tentative_signups:
        embed.add_field(
            name=f"⚖️ Tentative ({len(tentative_signups)})",
            value=format_signup_list(tentative_signups),
            inline=False
        )
    
    # Absence section
    if absent_signups:
        absence_names = [s['character_name'] for s in absent_signups]
        embed.add_field(
            name=f"❌ Absence ({len(absent_signups)})",
            value=", ".join(absence_names) if absence_names else "_None_",
            inline=False
        )
    
    embed.set_footer(text="Click a button below to sign up or change your status")
    
    return embed

# ============================================================================
# DISCORD UI COMPONENTS
# ============================================================================

class RaidButtonsView(View):
    """Persistent view with raid signup buttons"""
    
    def __init__(self):
        super().__init__(timeout=None)  # Persistent view
    
    @discord.ui.button(label="Sign Up", style=discord.ButtonStyle.success, custom_id="raid:signup", emoji="✅")
    async def signup_button(self, interaction: discord.Interaction, button: Button):
        """Handle sign up button click"""
        await handle_signup_click(interaction)
    
    @discord.ui.button(label="Late", style=discord.ButtonStyle.secondary, custom_id="raid:late", emoji="🕐")
    async def late_button(self, interaction: discord.Interaction, button: Button):
        """Handle late button click"""
        await handle_status_change(interaction, 'late')
    
    @discord.ui.button(label="Tentative", style=discord.ButtonStyle.secondary, custom_id="raid:tentative", emoji="⚖️")
    async def tentative_button(self, interaction: discord.Interaction, button: Button):
        """Handle tentative button click"""
        await handle_status_change(interaction, 'tentative')
    
    @discord.ui.button(label="Absence", style=discord.ButtonStyle.danger, custom_id="raid:absent", emoji="❌")
    async def absent_button(self, interaction: discord.Interaction, button: Button):
        """Handle absence button click"""
        await handle_status_change(interaction, 'absent')
    
    @discord.ui.button(label="Change Role", style=discord.ButtonStyle.primary, custom_id="raid:changerole", emoji="🔄")
    async def changerole_button(self, interaction: discord.Interaction, button: Button):
        """Handle change role button click"""
        await handle_change_role_click(interaction)


class CharacterSelectDropdown(Select):
    """Dropdown for selecting a WoW character"""
    
    def __init__(self, characters, event_id):
        self.event_id = event_id
        
        # Create options from characters
        options = []
        for char in characters[:25]:  # Discord limit is 25 options
            label = f"{char['character_name']} - {char['realm_name']}"
            description = f"{char['character_class']} ({char['faction']})"
            options.append(discord.SelectOption(
                label=label,
                description=description,
                value=f"{char['character_name']}|{char['realm_slug']}|{char['character_class']}"
            ))
        
        super().__init__(
            placeholder="Choose your character...",
            options=options,
            custom_id="raid:select_character"
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle character selection"""
        # Parse selection
        char_name, realm_slug, char_class = self.values[0].split('|')
        
        # Check for saved preference
        discord_id = str(interaction.user.id)
        preference = get_character_preference(discord_id, char_name, realm_slug)
        
        if preference:
            # Use saved preference
            role = preference['preferred_role']
            spec = preference['preferred_spec']
            
            # Add signup to database
            add_raid_signup(
                self.event_id,
                discord_id,
                char_name,
                realm_slug,
                char_class,
                role,
                spec
            )
            
            # Update the embed
            await update_raid_message(interaction.message)
            
            await interaction.response.send_message(
                f"✅ Signed up as **{char_name}** ({spec} {role.capitalize()})!",
                ephemeral=True
            )
        else:
            # No preference - show role selection
            await show_role_selection(interaction, char_name, realm_slug, char_class, self.event_id)


class CharacterSelectView(View):
    """View containing character selection dropdown"""
    
    def __init__(self, characters, event_id):
        super().__init__(timeout=180)  # 3 minute timeout
        self.add_item(CharacterSelectDropdown(characters, event_id))


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
            emoji = ROLE_EMOJIS.get(role, '❓')
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
        options = [discord.SelectOption(label=spec, value=spec) for spec in specs]
        
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
    
    embed = generate_raid_embed(event['id'])
    if embed:
        await message.edit(embed=embed)
