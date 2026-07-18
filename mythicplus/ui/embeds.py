"""
Mythic+ event embeds.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

from raid_system import (CLASS_EMOJIS, DEFAULT_TIMEZONE, ROLE_EMOJIS,
                         text_to_emoji_letters)

from .. import db
from ..constants import (ARMOR_EMOJIS, ARMOR_TYPES, STATUS_CANCELLED,
                         STATUS_FINALIZED, STATUS_OPEN)

# raid ROLE_EMOJIS uses melee/ranged for dps; M+ shows a single dps icon
_ROLE_ICONS = {
    'tank': ROLE_EMOJIS.get('tank', '🛡️'),
    'healer': ROLE_EMOJIS.get('healer', '💚'),
    'dps': '⚔️',
}


def _event_unix(event) -> int:
    tz = ZoneInfo(DEFAULT_TIMEZONE)
    dt = datetime.combine(event['event_date'], event['event_time'], tzinfo=tz)
    return int(dt.timestamp())


def generate_event_embed(event_id):
    """Build (embed, view) for an event in any state. View import is lazy to
    avoid a circular import with views.py."""
    from .views import MPlusButtonsView

    event = db.get_event(event_id)
    if not event:
        return None, None

    unix = _event_unix(event)
    key_range = f"+{event['key_level_min']}–+{event['key_level_max']}"

    color = discord.Color.purple()
    if event['status'] == STATUS_CANCELLED:
        color = discord.Color.dark_grey()
    elif event['status'] == STATUS_FINALIZED:
        color = discord.Color.green()

    embed = discord.Embed(
        title=text_to_emoji_letters(event['title']),
        color=color,
    )
    lines = [
        f"🗓️ <t:{unix}:F> (<t:{unix}:R>)",
        f"🔑 Keys **{key_range}** — armor stacking event",
    ]
    if event['signup_deadline'] and event['status'] == STATUS_OPEN:
        deadline_unix = int(event['signup_deadline'].timestamp())
        lines.append(f"⏳ Signups close <t:{deadline_unix}:R> — groups are "
                     f"formed automatically")
    if event['status'] == STATUS_CANCELLED:
        lines.append("❌ **Event cancelled**")
    embed.description = "\n".join(lines)

    if event['status'] == STATUS_FINALIZED:
        _add_roster_fields(embed, event_id)
    else:
        _add_signup_fields(embed, event_id)

    embed.set_footer(text=f"Event ID: {event_id} • Sign up with multiple "
                          f"characters and roles — you'll be placed once")
    return embed, MPlusButtonsView()


def _add_signup_fields(embed, event_id):
    rows = db.get_signup_summary(event_id)
    players = {r['discord_id'] for r in rows}
    embed.add_field(name="👥 Players signed",
                    value=str(len(players)) if players else "Nobody yet — be first!",
                    inline=False)

    for armor in ARMOR_TYPES:
        chars = [r for r in rows if r['armor_type'] == armor]
        if not chars:
            continue
        lines = []
        for c in chars[:15]:
            class_emoji = CLASS_EMOJIS.get(c['character_class'], '')
            roles = ' '.join(_ROLE_ICONS.get(role, role) for role in c['roles'])
            lines.append(f"{class_emoji} {c['character_name']} {roles}")
        if len(chars) > 15:
            lines.append(f"…and {len(chars) - 15} more")
        embed.add_field(
            name=f"{ARMOR_EMOJIS[armor]} {armor.capitalize()} ({len(chars)})",
            value="\n".join(lines)[:1024],
            inline=True,
        )


def _add_roster_fields(embed, event_id):
    groups = db.get_roster(event_id)
    for group in groups:
        armor = group['armor_type'] or 'mixed'
        lines = []
        off_armor = 0
        for m in group['members']:
            class_emoji = CLASS_EMOJIS.get(m['character_class'], '')
            role_icon = _ROLE_ICONS.get(m['assigned_role'], '')
            marker = ''
            if m['armor_type'] != group['armor_type']:
                off_armor += 1
                marker = f", {m['armor_type']}"
            # Character + realm + role is the authoritative roster line;
            # the @mention is only there for pinging
            lines.append(
                f"{role_icon} {class_emoji} "
                f"**{m['character_name']}-{m['realm_name']}** "
                f"({m['assigned_role'].capitalize()}{marker}) — <@{m['discord_id']}>")
        name = (f"{ARMOR_EMOJIS.get(armor, '')} Group {group['group_number']}"
                f" — {armor.capitalize()}")
        if off_armor:
            name += f" ({5 - off_armor}/5 stacked)"
        embed.add_field(name=name, value="\n".join(lines)[:1024], inline=False)

    alternates = db.get_alternates(event_id)
    if alternates:
        # Alphabetical by mention id — deliberately NOT in priority order so
        # private grace points can't be inferred (plan §5)
        mentions = sorted(f"<@{a['discord_id']}>" for a in alternates)
        embed.add_field(name="🪑 Reserves",
                        value=" ".join(mentions)[:1024], inline=False)
