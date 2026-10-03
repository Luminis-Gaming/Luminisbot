"""
Raid analysis — a Wipefest-style breakdown of the guild's raid logs.

Every pull from the guild's Warcraft Logs reports (raid difficulties only) is
fetched once, analyzed (deaths, wipe moment, damage taken per mechanic per
player, interrupts, dispels, potions/healthstones) and cached in Postgres.
The admin site renders nights, pulls and boss progression from that cache;
officers tag boss abilities as "avoidable" to drive the mistake counts.

Integration (matching the house patterns):

    import raidanalysis
    # inside on_ready:
    raidanalysis.start_tasks()          # periodic sync loop

plus raidanalysis.db.ensure_schema(cursor) inside run_migrations(), and
raidanalysis.web.register_routes(app) inside oauth_server.create_app().
"""
import logging

logger = logging.getLogger(__name__)

SYNC_INTERVAL_MINUTES = 10
SYNC_REPORT_LIMIT = 10

_sync_loop = None


def register_views(client):
    """Make the 'My analysis' button work on existing messages after a restart. Call from on_ready."""
    from .discord_recap import MyAnalysisView
    client.add_view(MyAnalysisView())
    logger.info("[RAIDS] 'My analysis' button registered")


def start_tasks():
    """Start the periodic WCL sync. Call from on_ready (needs an event loop)."""
    global _sync_loop
    if _sync_loop is not None and _sync_loop.is_running():
        return

    from discord.ext import tasks as ext_tasks

    from .sync import sync_guild

    @ext_tasks.loop(minutes=SYNC_INTERVAL_MINUTES)
    async def raid_analysis_sync():
        await sync_guild(limit=SYNC_REPORT_LIMIT)

    _sync_loop = raid_analysis_sync
    _sync_loop.start()
    logger.info("[RAIDS] Raid analysis sync started")
