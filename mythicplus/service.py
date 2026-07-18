"""
Mythic+ orchestration: embed refresh, character enrichment, and the
unattended finalize pipeline (deadline → roster → grace → notifications).
"""
import asyncio
import logging

from psycopg2.extras import RealDictCursor

from . import db
from .constants import ARMOR_EMOJIS, STATUS_OPEN, format_key_range
from .matchmaking import (alternate_reason, build_pool, build_roster,
                          compute_grace_changes)

logger = logging.getLogger(__name__)

# How many characters we refresh against Raider.IO/Blizzard at once
ENRICH_CONCURRENCY = 3
# Skip refreshing characters enriched more recently than this (minutes)
ENRICH_SKIP_FRESHER_THAN_MIN = 60


# ============================================================================
# EMBED REFRESH
# ============================================================================

async def refresh_event_message(client, event_id):
    """Re-render the event embed on its original Discord message."""
    try:
        event = db.get_event(event_id)
        if not event or not event['message_id']:
            return
        channel = client.get_channel(event['channel_id'])
        if channel is None:
            channel = await client.fetch_channel(event['channel_id'])
        message = await channel.fetch_message(event['message_id'])

        from .ui.embeds import generate_event_embed
        embed, view = generate_event_embed(event_id)
        if embed:
            await message.edit(embed=embed, view=view)
    except Exception as e:
        logger.warning(f"[MPLUS] Failed to refresh event {event_id} message: {e}")


# ============================================================================
# CHARACTER ENRICHMENT
# ============================================================================

async def enrich_signup_characters(discord_id, characters):
    """Fire-and-forget refresh after a signup (RIO score, gear, spec)."""
    for char in characters:
        try:
            await _enrich_one(discord_id, char['character_name'],
                              char['realm_slug'])
        except Exception as e:
            logger.warning(f"[MPLUS] Signup enrichment failed for "
                           f"{char.get('character_name')}: {e}")


async def _enrich_one(discord_id, character_name, realm_slug):
    conn = db.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT id, region FROM wow_characters
        WHERE discord_id = %s AND character_name = %s AND realm_slug = %s
    """, (discord_id, character_name, realm_slug))
    char = cursor.fetchone()
    cursor.close()
    conn.close()
    if char:
        from character_enrichment import enrich_and_cache_character
        await enrich_and_cache_character(char['id'], realm_slug,
                                         character_name,
                                         char.get('region') or 'eu')


async def refresh_event_characters(event_id):
    """Batch-refresh all signed characters right before rostering, so
    matchmaking never sorts on stale scores. Low concurrency, skips
    recently-enriched characters."""
    conn = db.get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("""
        SELECT DISTINCT wc.id, wc.character_name, wc.realm_slug,
               wc.discord_id, wc.region
        FROM mplus_signups s
        JOIN wow_characters wc
            ON wc.discord_id = s.discord_id
            AND wc.character_name = s.character_name
            AND wc.realm_slug = s.realm_slug
        WHERE s.event_id = %s
          AND (wc.last_enriched IS NULL
               OR wc.last_enriched < NOW() - make_interval(mins => %s))
    """, (event_id, ENRICH_SKIP_FRESHER_THAN_MIN))
    characters = cursor.fetchall()
    cursor.close()
    conn.close()

    if not characters:
        return
    logger.info(f"[MPLUS] Pre-roster refresh of {len(characters)} characters "
                f"for event {event_id}")
    semaphore = asyncio.Semaphore(ENRICH_CONCURRENCY)

    async def refresh(char):
        async with semaphore:
            try:
                from character_enrichment import enrich_and_cache_character
                await enrich_and_cache_character(
                    char['id'], char['realm_slug'], char['character_name'],
                    char.get('region') or 'eu')
            except Exception as e:
                logger.warning(f"[MPLUS] Pre-roster enrichment failed for "
                               f"{char['character_name']}: {e}")

    await asyncio.gather(*(refresh(c) for c in characters))


# ============================================================================
# WITHDRAWAL & AUTO-PROMOTION (post-finalization)
# ============================================================================

async def handle_roster_withdrawal(client, event_id, discord_id):
    """A rostered player (or reserve) cancels after finalization: free their
    slot, auto-promote the best-fitting reserve, announce, update the embed.
    Returns (vacated, promoted) dicts for the caller's confirmation text."""
    event = db.get_event(event_id)
    vacated = db.withdraw_completely(event_id, discord_id)

    promoted = None
    if vacated:
        candidate = db.find_promotion_candidate(
            event_id, vacated['group_number'], vacated['assigned_role'])
        if candidate:
            error = db.promote_alternate(event_id, candidate['signup_id'],
                                         vacated['group_number'])
            if error:
                logger.warning(f"[MPLUS] Auto-promotion failed for event "
                               f"{event_id}: {error}")
            else:
                promoted = candidate

    await refresh_event_message(client, event_id)

    if vacated and event:
        await _post_withdrawal_note(client, event, vacated, promoted)
        if promoted:
            from .ui.embeds import char_emoji
            emoji = char_emoji(promoted['character_class'], promoted.get('spec'))
            await _try_dm(client, event, promoted['discord_id'],
                          f"🎉 A spot opened up — you've been **promoted from "
                          f"reserve** for **{event['title']}**!\n"
                          f"You're now in **Group {vacated['group_number']}** "
                          f"as **{vacated['assigned_role']}** playing {emoji} "
                          f"**{promoted['character_name']}-"
                          f"{promoted['realm_slug']}**.")
    return vacated, promoted


async def _post_withdrawal_note(client, event, vacated, promoted):
    try:
        channel = client.get_channel(event['channel_id'])
        if channel is None:
            channel = await client.fetch_channel(event['channel_id'])
        char = f"**{vacated['character_name']}-{vacated['realm_slug']}**"
        if promoted:
            await channel.send(
                f"🔄 {char} cancelled their spot in Group "
                f"{vacated['group_number']} of **{event['title']}** — "
                f"<@{promoted['discord_id']}> has been promoted from reserve "
                f"as **{vacated['assigned_role']}** on "
                f"**{promoted['character_name']}-{promoted['realm_slug']}**!")
        else:
            await channel.send(
                f"⚠️ {char} cancelled their spot in **{event['title']}** — "
                f"Group {vacated['group_number']} now needs a "
                f"**{vacated['assigned_role']}** and no reserve can fill it.")
    except Exception as e:
        logger.warning(f"[MPLUS] Withdrawal note failed for event "
                       f"{event['id']}: {e}")


# ============================================================================
# FINALIZE PIPELINE (unattended)
# ============================================================================

async def finalize_event(client, event_id):
    """Deadline pipeline: close → refresh RIO → matchmake → persist roster +
    grace → update embed → channel summary → DMs. Idempotent: only an 'open'
    event can be finalized."""
    event = db.get_event(event_id)
    if not event or event['status'] != STATUS_OPEN:
        return

    await refresh_event_characters(event_id)

    rows = db.get_signup_rows(event_id)
    persons = build_pool(rows)
    persons_by_id = {p.discord_id: p for p in persons}

    # Seeded by event id: a crashed re-run reproduces the identical roster
    roster = build_roster(persons, seed=event_id)
    reasons = {p.discord_id: alternate_reason(p, roster, persons_by_id)
               for p in roster.benched}
    grace_changes = compute_grace_changes(roster, persons_by_id)

    db.save_roster(event_id, roster, reasons)
    db.apply_grace_changes(event['guild_id'], event_id, grace_changes)

    logger.info(f"[MPLUS] Finalized event {event_id}: {len(roster.groups)} "
                f"groups, {len(roster.benched)} reserves, "
                f"{len(grace_changes.awards)} grace awards")

    await refresh_event_message(client, event_id)
    await _post_channel_summary(client, event, roster)
    await _send_result_dms(client, event, roster, reasons, grace_changes)


async def _post_channel_summary(client, event, roster):
    try:
        channel = client.get_channel(event['channel_id'])
        if channel is None:
            channel = await client.fetch_channel(event['channel_id'])

        if not roster.groups:
            await channel.send(
                f"📋 Signups for **{event['title']}** are closed — not enough "
                f"players for a full group this time. "
                f"({len(roster.benched)} signed up; a group needs a tank, a "
                f"healer and three DPS.)")
            return

        from .ui.embeds import char_emoji

        lines = [f"📋 **{event['title']}** — groups are set! "
                 f"(🔑 {format_key_range(event['key_level_min'], event['key_level_max'])})"]
        groups = db.get_roster(event['id'])
        for group in groups:
            armor = group['armor_type'] or 'mixed'
            lines.append(f"\n{ARMOR_EMOJIS.get(armor, '')} **Group "
                         f"{group['group_number']} — {armor.capitalize()}**")
            for m in group['members']:
                lines.append(
                    f"  {char_emoji(m['character_class'], m.get('spec'))} "
                    f"**{m['character_name']}-{m['realm_name']}** "
                    f"(<@{m['discord_id']}>)")
        if roster.benched:
            mentions = sorted(f"<@{p.discord_id}>" for p in roster.benched)
            lines.append(f"\n🪑 Reserves: {' '.join(mentions)} — check your "
                         f"DMs for details.")
        await channel.send("\n".join(lines)[:2000])
    except Exception as e:
        logger.warning(f"[MPLUS] Channel summary failed for event "
                       f"{event['id']}: {e}")


async def _send_result_dms(client, event, roster, reasons, grace_changes):
    groups = db.get_roster(event['id'])
    member_group = {}
    for group in groups:
        for m in group['members']:
            member_group[m['discord_id']] = group

    for discord_id, group in member_group.items():
        text = _rostered_dm_text(event, group, discord_id)
        await _try_dm(client, event, discord_id, text)

    benched_names = await _display_names(
        client, event, [p.discord_id for p in roster.benched])
    for person in roster.benched:
        text = _reserve_dm_text(event, person, roster, reasons,
                                grace_changes, benched_names)
        await _try_dm(client, event, person.discord_id, text)


def _rostered_dm_text(event, group, discord_id):
    from .ui.embeds import char_emoji

    armor = group['armor_type'] or 'mixed'
    lines = [f"🎉 You're rostered for **{event['title']}** "
             f"(🔑 {format_key_range(event['key_level_min'], event['key_level_max'])})!",
             f"\n{ARMOR_EMOJIS.get(armor, '')} **Group "
             f"{group['group_number']} — {armor.capitalize()}**"]
    off_armor = []
    your_char = None
    for m in group['members']:
        marker = ''
        if m['armor_type'] != group['armor_type']:
            off_armor.append(m)
            marker = f" ({m['armor_type']})"
        you = ' ← you' if m['discord_id'] == discord_id else ''
        if m['discord_id'] == discord_id:
            your_char = m
        lines.append(f"  {char_emoji(m['character_class'], m.get('spec'))} "
                     f"**{m['character_name']}-{m['realm_name']}**{marker}{you}")
    if your_char:
        spec = f" ({your_char['spec']})" if your_char.get('spec') else ''
        lines.insert(1, f"You're playing **{your_char['character_name']}-"
                        f"{your_char['realm_name']}** as "
                        f"**{your_char['assigned_role']}**{spec}.")
    if off_armor and armor in ('mail', 'cloth'):
        lines.append(f"\nℹ️ {armor.capitalize()} has no tank specs, so this "
                     f"is the best possible {armor} stack — the off-armor "
                     f"member fills the gap.")
    elif off_armor:
        lines.append("\nℹ️ Not enough same-armor players for a full stack, "
                     "so this group mixes armor types — best effort!")
    return "\n".join(lines)


def _reserve_dm_text(event, person, roster, reasons, grace_changes, names):
    from .constants import ALT_REASON_UNLUCKY
    lines = [f"🪑 You're on the **reserve list** for **{event['title']}**."]

    if reasons.get(person.discord_id) == ALT_REASON_UNLUCKY:
        lines.append(
            "\nYou had the right armor type and role — this was purely the "
            "luck of the draw with more signups than spots.")
        if person.discord_id in grace_changes.awards:
            lines.append(
                "🎟️ You've been given a **priority point**: next event, "
                "you'll be picked ahead of otherwise-equal players.")
    else:
        lines.append(
            "\nNo group could fit your armor type/role combination this "
            "time — the groups are stacked by armor type for trade loot, and "
            "the slots your characters cover were already filled by "
            "same-armor players.")

    others = [names[pid] for pid in names
              if pid != person.discord_id]
    if others:
        pugs_needed = max(0, 5 - (len(others) + 1))
        lines.append(
            f"\n👥 Fellow reserves: {', '.join(sorted(others))}. "
            + (f"Together you can start your own run with {pugs_needed} PUG "
               f"player{'s' if pugs_needed != 1 else ''}!"
               if pugs_needed else
               "That's enough of you for a full group of your own — go for it!"))
    return "\n".join(lines)


async def _display_names(client, event, discord_ids):
    names = {}
    guild = client.get_guild(event['guild_id'])
    for discord_id in discord_ids:
        name = None
        try:
            if guild:
                member = guild.get_member(int(discord_id))
                if member:
                    name = member.display_name
            if not name:
                user = client.get_user(int(discord_id))
                if user:
                    name = user.display_name
        except Exception as e:
            # Non-numeric test ids / departed users — fall back to the raw id
            logger.debug(f"[MPLUS] Name lookup failed for {discord_id}: {e}")
        names[discord_id] = name or str(discord_id)
    return names


async def _try_dm(client, event, discord_id, text):
    try:
        user = client.get_user(int(discord_id))
        if user is None:
            user = await client.fetch_user(int(discord_id))
        link = (f"https://discord.com/channels/{event['guild_id']}/"
                f"{event['channel_id']}/{event['message_id']}")
        await user.send(f"{text}\n\n🔗 Event: {link}")
    except Exception as e:
        # Blocked DMs are fine — the channel summary already pinged them
        logger.info(f"[MPLUS] Could not DM {discord_id}: {e}")
