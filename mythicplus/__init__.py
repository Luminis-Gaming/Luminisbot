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
    """Register the slash command. Call at import time, before tree.sync().

    The persistent view is NOT registered here — see register_views(), which
    must run after the bot has logged in (from on_ready), or button clicks on
    events created in a previous session silently time out after a restart.
    """
    import discord

    from .ui.modals import CreateMPlusModal

    @tree.command(name="createmplus",
                  description="Create a Mythic+ armor-stacking event with "
                              "automatic group formation")
    async def createmplus_command(interaction: discord.Interaction):
        await interaction.response.send_modal(CreateMPlusModal())

    logger.info("[MPLUS] Mythic+ command registered")


def register_views(client):
    """Register the persistent event-button view so buttons on events from
    previous sessions keep working after a restart. Call from on_ready.

    The view carries no per-message state (static custom_ids), so this single
    call reclaims every existing M+ event message at once."""
    from .ui.views import MPlusButtonsView

    client.add_view(MPlusButtonsView())
    logger.info("[MPLUS] Persistent event view registered")


async def on_reaction_add(client, payload):
    """Forward a raw reaction-add to the M+ reaction-signup handler.
    Call from the bot's on_raw_reaction_add alongside the raid handler."""
    from . import reactions
    await reactions.handle_reaction_add(client, payload)


async def on_reaction_remove(client, payload):
    """Forward a raw reaction-remove to the M+ reaction-signup handler."""
    from . import reactions
    await reactions.handle_reaction_remove(client, payload)


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
