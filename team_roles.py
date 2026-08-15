"""
Raid Team Roles

Signing up for a raid event posted in a team's signup channel grants that
team's Discord role. Membership is tracked per team so a player who moves
from one team to the other keeps only the role they are actually active in:
each team's clock is refreshed exclusively by activity in that team's
channel. Roles are removed by a daily sweep once a team's clock goes stale.

Holding both roles at once is allowed and expected — a player raiding with
both teams simply refreshes both clocks.
"""

import discord
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# Signup channel -> raid team role. Events posted in any other channel are
# ignored entirely by this system.
TEAMS = {
    'sun': {
        'name': 'Team Sun',
        'channel_id': 1402570469906841621,   # team-sun-signups
        'role_id': 1538210707542114435,
    },
    'moon': {
        'name': 'Team Moon',
        'channel_id': 1495907119872999485,   # team-moon-signups
        'role_id': 1538210854955130920,
    },
}

# How long a team role survives without a signup in that team's channel.
INACTIVITY_DAYS = 30


def get_team_for_channel(channel_id) -> str | None:
    """Return the team key for a signup channel, or None if it isn't one."""
    if channel_id is None:
        return None
    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        return None

    for team, config in TEAMS.items():
        if config['channel_id'] == channel_id:
            return team
    return None


# ============================================================================
# DATABASE
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


def ensure_schema(cursor):
    """Create the team role tracking table (called from run_migrations)."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_role_members (
            discord_id TEXT NOT NULL,
            team TEXT NOT NULL,
            guild_id BIGINT NOT NULL,
            role_id BIGINT NOT NULL,
            last_signup_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            granted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (discord_id, team)
        );
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_team_role_members_activity
            ON team_role_members(last_signup_at);
    """)

    cursor.execute("""
        GRANT ALL PRIVILEGES ON TABLE team_role_members TO luminisbot;
    """)


def record_activity(discord_id: str, team: str, guild_id: int, role_id: int):
    """Insert or refresh a player's membership row for one team."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO team_role_members (discord_id, team, guild_id, role_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (discord_id, team)
        DO UPDATE SET last_signup_at = NOW(),
                      guild_id = EXCLUDED.guild_id,
                      role_id = EXCLUDED.role_id
    """, (str(discord_id), team, guild_id, role_id))

    conn.commit()
    cursor.close()
    conn.close()


def get_expired_memberships(days: int = INACTIVITY_DAYS):
    """Memberships with no signup in that team's channel for `days` days."""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    cursor.execute("""
        SELECT discord_id, team, guild_id, role_id, last_signup_at
        FROM team_role_members
        WHERE last_signup_at < NOW() - make_interval(days => %s)
    """, (days,))

    expired = cursor.fetchall()
    cursor.close()
    conn.close()

    return expired


def remove_membership(discord_id: str, team: str):
    """Drop a tracking row (role removed, or user no longer reachable)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM team_role_members
        WHERE discord_id = %s AND team = %s
    """, (str(discord_id), team))

    conn.commit()
    cursor.close()
    conn.close()


# ============================================================================
# ROLE GRANTING
# ============================================================================

async def grant_team_role(guild: discord.Guild, user, channel_id):
    """
    Grant the team role for `channel_id` and refresh that team's clock.

    `user` may be a Member (from an interaction) or a plain Discord ID.
    No-op when the channel isn't a team signup channel. Never raises — a
    failure here must not break a signup that already succeeded.
    """
    team = get_team_for_channel(channel_id)
    if not team or guild is None:
        return

    config = TEAMS[team]
    role_id = config['role_id']
    user_id = user.id if isinstance(user, discord.Member) else user

    try:
        member = user if isinstance(user, discord.Member) else guild.get_member(int(user_id))
        if member is None:
            member = await guild.fetch_member(int(user_id))

        role = guild.get_role(role_id)
        if role is None:
            logger.warning(f"[TEAM ROLES] Role {role_id} ({config['name']}) "
                           f"not found in guild {guild.id}")
            return

        if role not in member.roles:
            await member.add_roles(role, reason=f"Signed up in {config['name']} channel")
            logger.info(f"[TEAM ROLES] Granted {config['name']} to {member} ({user_id})")

        # Track membership even when the role was already present, so the
        # inactivity clock covers manually assigned roles from this point on.
        record_activity(user_id, team, guild.id, role_id)

    except discord.Forbidden:
        logger.error(f"[TEAM ROLES] Missing permission to grant {config['name']} — "
                     f"check Manage Roles and that the bot's role is above it")
    except discord.NotFound:
        logger.warning(f"[TEAM ROLES] User {user_id} not found in guild {guild.id}")
    except Exception as e:
        logger.error(f"[TEAM ROLES] Failed to grant {config['name']} to {user_id}: {e}")


# ============================================================================
# INACTIVITY SWEEP
# ============================================================================

async def sweep_expired_team_roles(client: discord.Client):
    """
    Remove team roles from players who haven't signed up for that team in
    INACTIVITY_DAYS. Rows for users we can no longer reach are dropped.
    """
    try:
        expired = get_expired_memberships()
    except Exception as e:
        logger.error(f"[TEAM ROLES] Expiry query failed: {e}")
        return

    if not expired:
        return

    logger.info(f"[TEAM ROLES] {len(expired)} membership(s) past "
                f"{INACTIVITY_DAYS} days — removing roles")

    for membership in expired:
        discord_id = membership['discord_id']
        team = membership['team']
        team_name = TEAMS.get(team, {}).get('name', team)

        guild = client.get_guild(int(membership['guild_id']))
        if guild is None:
            logger.warning(f"[TEAM ROLES] Guild {membership['guild_id']} unavailable — "
                           f"dropping {team_name} row for {discord_id}")
            remove_membership(discord_id, team)
            continue

        try:
            member = guild.get_member(int(discord_id))
            if member is None:
                member = await guild.fetch_member(int(discord_id))

            role = guild.get_role(int(membership['role_id']))
            if role is not None and role in member.roles:
                await member.remove_roles(role, reason=f"Inactive in {team_name} for "
                                                       f"{INACTIVITY_DAYS}+ days")
                logger.info(f"[TEAM ROLES] Removed {team_name} from {member} ({discord_id})")

            remove_membership(discord_id, team)

        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            # Left the server, role gone, or unreachable — stop tracking them.
            logger.warning(f"[TEAM ROLES] Dropping {team_name} row for {discord_id}: {e}")
            remove_membership(discord_id, team)
        except Exception as e:
            # Unexpected: keep the row so the next sweep retries.
            logger.error(f"[TEAM ROLES] Error sweeping {team_name} for {discord_id}: {e}")
