"""
Reaction-based signup for a specific guild member who will only interact via
a ✅ reaction, never the signup buttons.

Stonasloth (paranoid about clicking bot buttons) signs his Protection/
Retribution paladin up by reacting ✅ to an M+ event message, and cancels by
removing the reaction. Everyone else's reactions are ignored here — the normal
button flow is unaffected.
"""
import logging

from . import db
from .constants import STATUS_OPEN, armor_for_class

logger = logging.getLogger(__name__)

_CHECK_EMOJI = '✅'

# Hardcoded by explicit request — this one user opts out of the button flow.
_REACT_USER_ID = 1141804034416713848
_REACT_CHARACTER = {
    'discord_id': str(_REACT_USER_ID),
    'character_name': 'Stonasloth',
    'realm_slug': 'doomhammer',
    'character_class': 'Paladin',
    # (role, spec) offerings — placed on at most one when groups form
    'offerings': [('tank', 'Protection'), ('dps', 'Retribution')],
}


def _is_react_signup(payload):
    """True only for our special user reacting with the ✅ emoji."""
    if payload.user_id != _REACT_USER_ID:
        return False
    return payload.emoji is not None and payload.emoji.name == _CHECK_EMOJI


async def handle_reaction_add(client, payload):
    """✅ from the special user → sign their paladin up (tank + dps offerings)."""
    if not _is_react_signup(payload):
        return
    event = db.get_event_by_message(int(payload.message_id))
    if not event or event['status'] != STATUS_OPEN:
        return

    char = _REACT_CHARACTER
    armor = armor_for_class(char['character_class'])
    wrote = False
    for role, spec in char['offerings']:
        if db.add_signup(event['id'], char['discord_id'],
                         char['character_name'], char['realm_slug'],
                         char['character_class'], role, armor, spec=spec):
            wrote = True

    if wrote:
        from .service import refresh_event_message
        await refresh_event_message(client, event['id'])
        logger.info("[MPLUS] Reaction signup added for %s-%s on event %s",
                    char['character_name'], char['realm_slug'], event['id'])


async def handle_reaction_remove(client, payload):
    """Removing the ✅ cancels the signup (only while signups are still open —
    after groups form, the roster/reserve flow owns withdrawals)."""
    if not _is_react_signup(payload):
        return
    event = db.get_event_by_message(int(payload.message_id))
    if not event or event['status'] != STATUS_OPEN:
        return

    db.remove_all_signups(event['id'], _REACT_CHARACTER['discord_id'])
    from .service import refresh_event_message
    await refresh_event_message(client, event['id'])
    logger.info("[MPLUS] Reaction signup cancelled for %s on event %s",
                _REACT_CHARACTER['character_name'], event['id'])
