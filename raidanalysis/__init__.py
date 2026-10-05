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
# Nobody raids then: each of these hours (guild time) goes to top-player benchmarks with the full
# WCL budget, so a backlog (or the weekly refresh) clears overnight instead of 3 per sync.
BENCHMARK_NIGHT_HOURS = range(2, 8)

_sync_loop = None


def register_views(client):
    """Make the 'My performance' button work on existing messages after a restart. Call from on_ready."""
    from .discord_recap import MyAnalysisView
    client.add_view(MyAnalysisView())
    logger.info("[RAIDS] 'My performance' button registered")


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
        try:
            await _benchmark_night()
        except Exception:
            logger.exception("[RAIDS] Nightly top-player fetch failed")

    _sync_loop = raid_analysis_sync
    _sync_loop.start()
    logger.info("[RAIDS] Raid analysis sync started")


async def _benchmark_night():
    """During BENCHMARK_NIGHT_HOURS: fetch every missing / stale benchmark the hour's WCL budget allows."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from raid_system import DEFAULT_TIMEZONE

    from . import benchmarks, db, sync
    if datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).hour not in BENCHMARK_NIGHT_HOURS or sync._paused():
        return
    w = sync.status.get('wcl') or {}
    if w.get('spent') is not None and w['spent'] >= sync.FULL_BUDGET_SHARE * (w.get('limit') or 3600):
        return  # this hour's budget is spent (as of the sync just now): wait for it to reset
    if db.benchmarks_needed(1, benchmarks.REFRESH_DAYS, benchmarks.DIFFICULTIES):
        await sync.fetch_all_benchmarks(full_budget=True)
