"""
Mythic+ Discord views: persistent event buttons + the ephemeral signup chain.

The persistent view carries no state (static custom_ids, rekeyed from the
message → DB), matching RaidButtonsView so buttons survive bot restarts.
"""
import asyncio
import logging

import discord
from discord.ui import Button, Select, View

from raid_system import (CLASS_EMOJIS, WOW_MAX_LEVEL,
                         get_available_roles_for_class, get_user_characters,
                         parse_emoji_for_dropdown)

from .. import db
from ..constants import ARMOR_EMOJIS, STATUS_OPEN, armor_for_class

logger = logging.getLogger(__name__)

_ROLE_CHOICE_EMOJIS = {'tank': '🛡️', 'healer': '💚', 'dps': '⚔️'}
CHARS_PER_PAGE = 18


class MPlusButtonsView(View):
    """Persistent view with M+ event buttons."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Sign Up", style=discord.ButtonStyle.secondary,
                       custom_id="mplus:signup", emoji="✅", row=0)
    async def signup_button(self, interaction: discord.Interaction, button: Button):
        await handle_signup_click(interaction)

    @discord.ui.button(label="My Signups", style=discord.ButtonStyle.secondary,
                       custom_id="mplus:mysignups", emoji="📋", row=0)
    async def mysignups_button(self, interaction: discord.Interaction, button: Button):
        await handle_my_signups_click(interaction)

    @discord.ui.button(label="My Priority", style=discord.ButtonStyle.secondary,
                       custom_id="mplus:grace", emoji="🎟️", row=0)
    async def grace_button(self, interaction: discord.Interaction, button: Button):
        await handle_grace_click(interaction)

    @discord.ui.button(label="Admin", style=discord.ButtonStyle.secondary,
                       custom_id="mplus:admin", emoji="⚙️", row=0)
    async def admin_button(self, interaction: discord.Interaction, button: Button):
        await handle_admin_click(interaction)


# ============================================================================
# BUTTON HANDLERS
# ============================================================================

async def _get_open_event(interaction):
    event = db.get_event_by_message(interaction.message.id)
    if not event:
        await interaction.response.send_message(
            "❌ Could not find this event in the database.", ephemeral=True)
        return None
    return event


async def handle_signup_click(interaction: discord.Interaction):
    event = await _get_open_event(interaction)
    if not event:
        return
    if event['status'] != STATUS_OPEN:
        await interaction.response.send_message(
            "🔒 Signups are closed for this event — groups have already been "
            "formed.", ephemeral=True)
        return

    characters = get_user_characters(str(interaction.user.id))
    if not characters:
        await interaction.response.send_message(
            "❌ You have no characters connected. Use `/connectwow` first!",
            ephemeral=True)
        return

    # Same max-level filter as the raid system
    max_level_chars = [c for c in characters if c.get('level') == WOW_MAX_LEVEL]
    if not max_level_chars:
        levels = [c.get('level') or 0 for c in characters]
        top = max(levels) if levels else 0
        max_level_chars = [c for c in characters if (c.get('level') or 0) == top]

    view = CharacterPickView(event['id'], max_level_chars)
    await interaction.response.send_message(
        "🎮 Pick **all** characters you'd like to offer for this event "
        "(you'll be placed on at most one):",
        view=view, ephemeral=True)


async def handle_my_signups_click(interaction: discord.Interaction):
    event = await _get_open_event(interaction)
    if not event:
        return
    rows = db.get_user_signups(event['id'], str(interaction.user.id))
    if not rows:
        await interaction.response.send_message(
            "You haven't signed up for this event yet.", ephemeral=True)
        return
    view = MySignupsView(event['id'], rows)
    summary = "\n".join(
        f"• **{r['character_name']}-{r['realm_slug']}** — {r['role']}"
        for r in rows)
    await interaction.response.send_message(
        f"📋 Your signups:\n{summary}\n\nSelect one to remove it:",
        view=view, ephemeral=True)


async def handle_grace_click(interaction: discord.Interaction):
    event = await _get_open_event(interaction)
    if not event:
        return
    points = db.get_grace_points(event['guild_id'], str(interaction.user.id))
    if points > 0:
        text = (f"🎟️ You have **{points} priority point"
                f"{'s' if points != 1 else ''}**.\n"
                "You earned this by being benched by the draw despite matching "
                "armor/role — you'll be prioritized over otherwise-equal "
                "players next time. Points reset when you get a spot.")
    else:
        text = ("🎟️ You have **no priority points** right now.\n"
                "You earn one when you lose a spot purely to the luck of the "
                "draw; it prioritizes you at the next event.")
    await interaction.response.send_message(text, ephemeral=True)


async def handle_admin_click(interaction: discord.Interaction):
    event = await _get_open_event(interaction)
    if not event:
        return
    is_creator = interaction.user.id == event['created_by']
    is_manager = interaction.user.guild_permissions.manage_guild
    if not (is_creator or is_manager):
        await interaction.response.send_message(
            "❌ Only the event creator or a server manager can use this.",
            ephemeral=True)
        return
    await interaction.response.send_message(
        f"⚙️ Admin panel for **{event['title']}** (status: {event['status']})",
        view=AdminPanelView(event['id']), ephemeral=True)


# ============================================================================
# SIGNUP CHAIN: characters (multi) → roles per character (multi)
# ============================================================================

class SignupFlow:
    """State for one user's ephemeral signup chain."""

    def __init__(self, event_id, characters):
        self.event_id = event_id
        self.characters = characters      # all max-level chars
        self.queue = []                   # chars still needing a role choice
        self.collected = []               # (char_dict, [roles])

    def next_char(self):
        return self.queue[0] if self.queue else None


class CharacterPickView(View):
    def __init__(self, event_id, characters, page=0):
        super().__init__(timeout=300)
        self.flow = SignupFlow(event_id, characters)
        self.page = page
        self.add_item(CharacterMultiSelect(self.flow, characters, page))
        total_pages = (len(characters) + CHARS_PER_PAGE - 1) // CHARS_PER_PAGE
        if total_pages > 1:
            if page > 0:
                self.add_item(_PageButton(self.flow, page - 1, "⬅️ Previous"))
            if page < total_pages - 1:
                self.add_item(_PageButton(self.flow, page + 1, "➡️ More"))


class _PageButton(Button):
    def __init__(self, flow, target_page, label):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=1)
        self.flow = flow
        self.target_page = target_page

    async def callback(self, interaction: discord.Interaction):
        view = CharacterPickView(self.flow.event_id, self.flow.characters,
                                 page=self.target_page)
        await interaction.response.edit_message(view=view)


class CharacterMultiSelect(Select):
    def __init__(self, flow, characters, page):
        self.flow = flow
        start = page * CHARS_PER_PAGE
        page_chars = characters[start:start + CHARS_PER_PAGE]
        self.by_value = {}
        options = []
        for c in page_chars:
            value = f"{c['character_name']}|{c['realm_slug']}"
            self.by_value[value] = c
            armor = armor_for_class(c.get('character_class', ''))
            options.append(discord.SelectOption(
                label=f"{c['character_name']} - {c.get('realm_name', c['realm_slug'])}"[:100],
                description=f"{c.get('character_class', '?')} ({armor})"[:100],
                value=value,
                emoji=parse_emoji_for_dropdown(
                    CLASS_EMOJIS.get(c.get('character_class', ''), '❔')),
            ))
        super().__init__(placeholder="Choose your characters…",
                         options=options,
                         min_values=1, max_values=len(options))

    async def callback(self, interaction: discord.Interaction):
        self.flow.queue = [self.by_value[v] for v in self.values]
        await _show_role_step(interaction, self.flow)


async def _show_role_step(interaction, flow):
    char = flow.next_char()
    view = View(timeout=300)
    view.add_item(RoleMultiSelect(flow, char))
    armor = armor_for_class(char.get('character_class', ''))
    await interaction.response.edit_message(
        content=(f"⚔️ Which role(s) would you play on "
                 f"**{char['character_name']}** "
                 f"({char.get('character_class', '?')}, {armor})?"),
        view=view)


class RoleMultiSelect(Select):
    def __init__(self, flow, char):
        self.flow = flow
        self.char = char
        roles = get_available_roles_for_class(char.get('character_class', ''))
        if not roles:
            roles = ['dps']
        options = [
            discord.SelectOption(label=role.capitalize(), value=role,
                                 emoji=_ROLE_CHOICE_EMOJIS.get(role))
            for role in roles
        ]
        super().__init__(placeholder="Choose role(s)…", options=options,
                         min_values=1, max_values=len(options))

    async def callback(self, interaction: discord.Interaction):
        self.flow.collected.append((self.char, list(self.values)))
        self.flow.queue.pop(0)
        if self.flow.next_char():
            await _show_role_step(interaction, self.flow)
        else:
            await _finish_signup(interaction, self.flow)


async def _finish_signup(interaction, flow):
    discord_id = str(interaction.user.id)
    written, closed = [], False
    for char, roles in flow.collected:
        char_class = char.get('character_class', '')
        armor = armor_for_class(char_class)
        for role in roles:
            ok = db.add_signup(flow.event_id, discord_id,
                               char['character_name'], char['realm_slug'],
                               char_class, role, armor)
            if not ok:
                closed = True
            else:
                written.append((char, role))

    if closed and not written:
        await interaction.response.edit_message(
            content="🔒 Signups closed while you were choosing — sorry!",
            view=None)
        return

    # Refresh RIO/gear/spec for each signed character in the background,
    # same pattern as raid finalize_signup
    from ..service import enrich_signup_characters, refresh_event_message
    asyncio.create_task(enrich_signup_characters(
        discord_id, [c for c, _ in flow.collected]))
    asyncio.create_task(refresh_event_message(interaction.client, flow.event_id))

    lines = [f"• **{c['character_name']}-{c['realm_slug']}** as {r}"
             for c, r in written]
    await interaction.response.edit_message(
        content=("✅ Signed up with:\n" + "\n".join(lines) +
                 "\n\nYou'll be placed on **one** of these when groups form. "
                 "Use **My Signups** on the event to make changes."),
        view=None)


# ============================================================================
# MY SIGNUPS (remove offerings)
# ============================================================================

class MySignupsView(View):
    def __init__(self, event_id, rows):
        super().__init__(timeout=180)
        self.add_item(MySignupsSelect(event_id, rows))


class MySignupsSelect(Select):
    def __init__(self, event_id, rows):
        self.event_id = event_id
        options = [
            discord.SelectOption(
                label=f"{r['character_name']}-{r['realm_slug']} — {r['role']}"[:100],
                value=str(r['id']),
                emoji=_ROLE_CHOICE_EMOJIS.get(r['role']))
            for r in rows[:24]
        ]
        options.append(discord.SelectOption(
            label="🗑️ Withdraw completely (remove ALL signups)",
            value="__ALL__"))
        super().__init__(placeholder="Remove a signup…", options=options)

    async def callback(self, interaction: discord.Interaction):
        discord_id = str(interaction.user.id)
        if self.values[0] == "__ALL__":
            db.remove_all_signups(self.event_id, discord_id)
            content = "🗑️ You have withdrawn from this event."
        else:
            db.remove_signup(int(self.values[0]), discord_id)
            content = "✅ Signup removed."
        from ..service import refresh_event_message
        asyncio.create_task(refresh_event_message(interaction.client, self.event_id))
        await interaction.response.edit_message(content=content, view=None)


# ============================================================================
# ADMIN PANEL
# ============================================================================

class AdminPanelView(View):
    def __init__(self, event_id):
        super().__init__(timeout=180)
        self.event_id = event_id

    @discord.ui.button(label="Close signups & form groups now",
                       style=discord.ButtonStyle.primary, emoji="⚡", row=0)
    async def close_now(self, interaction: discord.Interaction, button: Button):
        event = db.get_event(self.event_id)
        if not event or event['status'] != STATUS_OPEN:
            await interaction.response.edit_message(
                content="❌ Event is not open — nothing to do.", view=None)
            return
        await interaction.response.edit_message(
            content="⚡ Forming groups now — results will be posted and "
                    "everyone will be DM'd…", view=None)
        from ..service import finalize_event
        await finalize_event(interaction.client, self.event_id)

    @discord.ui.button(label="Cancel event",
                       style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def cancel_event(self, interaction: discord.Interaction, button: Button):
        view = _ConfirmCancelView(self.event_id)
        await interaction.response.edit_message(
            content="⚠️ Really cancel this event? This can't be undone.",
            view=view)


class _ConfirmCancelView(View):
    def __init__(self, event_id):
        super().__init__(timeout=60)
        self.event_id = event_id

    @discord.ui.button(label="Yes, cancel it", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        db.set_event_status(self.event_id, 'cancelled')
        from ..service import refresh_event_message
        await refresh_event_message(interaction.client, self.event_id)
        await interaction.response.edit_message(
            content="🗑️ Event cancelled.", view=None)

    @discord.ui.button(label="Keep it", style=discord.ButtonStyle.secondary)
    async def abort(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content="👍 Event kept as-is.", view=None)
