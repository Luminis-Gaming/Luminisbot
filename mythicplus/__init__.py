"""
Mythic+ event system — armor-stacking dungeon groups with fair rostering.

Design: MYTHICPLUS_PLAN.md. Integration (matching the house patterns):

    import mythicplus
    mythicplus.setup(client, tree)      # at import, after client/tree creation
    ...
    # inside on_ready:
    mythicplus.start_tasks(client)      # starts the deadline watcher loop

plus mythicplus.db.ensure_schema(cursor) inside run_migrations().
"""
import logging

logger = logging.getLogger(__name__)

_deadline_watcher = None


def setup(client, tree):
    """Register the slash command and persistent view. Call at import time,
    before tree.sync()."""
    import discord

    from .ui.modals import CreateMPlusModal
    from .ui.views import MPlusButtonsView

    @tree.command(name="createmplus",
                  description="Create a Mythic+ armor-stacking event with "
                              "automatic group formation")
    async def createmplus_command(interaction: discord.Interaction):
        await interaction.response.send_modal(CreateMPlusModal())

    client.add_view(MPlusButtonsView())
    logger.info("[MPLUS] Mythic+ commands and views registered")


def start_tasks(client):
    """Start the deadline watcher. Call from on_ready (needs an event loop)."""
    global _deadline_watcher
    if _deadline_watcher is not None and _deadline_watcher.is_running():
        return

    from discord.ext import tasks as ext_tasks

    from .tasks import check_deadlines

    @ext_tasks.loop(minutes=1)
    async def mplus_deadline_watcher():
        await check_deadlines(client)

    _deadline_watcher = mplus_deadline_watcher
    _deadline_watcher.start()
    logger.info("[MPLUS] Deadline watcher started")
