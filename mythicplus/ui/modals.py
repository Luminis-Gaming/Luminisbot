"""
Mythic+ modals: event creation.
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import discord

from raid_system import DEFAULT_TIMEZONE, parse_date, parse_time

from .. import db
from ..constants import DEFAULT_DEADLINE_HOURS_BEFORE

logger = logging.getLogger(__name__)


def parse_key_range(value: str):
    """Parse "8-12", "+8-+12", "8 – 12", or a single "10" into (min, max)."""
    cleaned = value.replace('+', '').replace('–', '-').replace(' ', '')
    if '-' in cleaned:
        low, high = cleaned.split('-', 1)
    else:
        low = high = cleaned
    try:
        key_min, key_max = int(low), int(high)
    except ValueError:
        raise ValueError("Key range must look like 8-12 (or a single level like 10)")
    if key_min > key_max:
        key_min, key_max = key_max, key_min
    if not (2 <= key_min <= 40 and 2 <= key_max <= 40):
        raise ValueError("Key levels must be between +2 and +40")
    return key_min, key_max


class CreateMPlusModal(discord.ui.Modal, title="Create Mythic+ Event"):
    """Modal for creating an armor-stacking M+ event (5 inputs = Discord max)."""

    def __init__(self):
        super().__init__()
        self.title_input = discord.ui.TextInput(
            label="Event Title",
            placeholder="e.g., Armor Stack Monday, Season Start Push",
            max_length=100, required=True)
        self.add_item(self.title_input)

        self.date_input = discord.ui.TextInput(
            label="Date (DD/MM/YYYY, DD.MM.YYYY, or YYYY-MM-DD)",
            placeholder="e.g., 21/07/2026",
            max_length=20, required=True)
        self.add_item(self.date_input)

        self.time_input = discord.ui.TextInput(
            label="Time (HH:MM in 24-hour format)",
            placeholder="e.g., 20:00",
            max_length=5, required=True)
        self.add_item(self.time_input)

        self.key_range_input = discord.ui.TextInput(
            label="Key level range",
            placeholder="e.g., 8-12",
            max_length=10, required=True)
        self.add_item(self.key_range_input)

        self.deadline_input = discord.ui.TextInput(
            label="Signup deadline (optional, default -2h)",
            placeholder="e.g., 18:00 (event day) or 20/07/2026 18:00",
            max_length=20, required=False)
        self.add_item(self.deadline_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            event_date = parse_date(self.date_input.value)
            event_time = parse_time(self.time_input.value)
            key_min, key_max = parse_key_range(self.key_range_input.value)
            title = self.title_input.value

            tz = ZoneInfo(DEFAULT_TIMEZONE)
            event_start = datetime.combine(event_date, event_time, tzinfo=tz)

            deadline_value = self.deadline_input.value.strip()
            if deadline_value:
                if ' ' in deadline_value:
                    date_part, time_part = deadline_value.split(' ', 1)
                    signup_deadline = datetime.combine(
                        parse_date(date_part), parse_time(time_part), tzinfo=tz)
                else:
                    signup_deadline = datetime.combine(
                        event_date, parse_time(deadline_value), tzinfo=tz)
            else:
                signup_deadline = event_start - timedelta(
                    hours=DEFAULT_DEADLINE_HOURS_BEFORE)

            if signup_deadline > event_start:
                raise ValueError("Signup deadline must be before the event starts")
        except ValueError as e:
            await interaction.response.send_message(
                f"❌ Invalid input!\nError: {e}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from .embeds import generate_event_embed
        from .views import MPlusButtonsView

        placeholder = discord.Embed(title="Creating Mythic+ event...",
                                    color=discord.Color.purple())
        message = await interaction.channel.send(embed=placeholder,
                                                 view=MPlusButtonsView())

        event_id = db.create_event(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel.id,
            message_id=message.id,
            title=title,
            event_date=event_date,
            event_time=event_time,
            key_level_min=key_min,
            key_level_max=key_max,
            created_by=interaction.user.id,
            signup_deadline=signup_deadline,
        )

        embed, view = generate_event_embed(event_id)
        await message.edit(embed=embed, view=view)

        await interaction.followup.send(
            f"✅ Mythic+ event **{title}** created (keys +{key_min}–+{key_max})!\n"
            f"📋 Event ID: {event_id} — groups form automatically at the deadline.",
            ephemeral=True)
        logger.info(f"[MPLUS] Created event '{title}' by {interaction.user.name} "
                    f"(ID: {event_id})")
