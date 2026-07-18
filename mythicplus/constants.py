"""
Mythic+ constants: armor types, event defaults.

This module must stay free of discord/psycopg2 imports — the matchmaking
engine depends on it and is unit-tested without those packages installed.
Class emojis, spec tables, and parse helpers live in raid_system and are
imported by the UI layer only.
"""

# Armor type per class — the core of armor-stacking groups
ARMOR_BY_CLASS = {
    'Mage': 'cloth',
    'Priest': 'cloth',
    'Warlock': 'cloth',
    'Demon Hunter': 'leather',
    'Druid': 'leather',
    'Monk': 'leather',
    'Rogue': 'leather',
    'Evoker': 'mail',
    'Hunter': 'mail',
    'Shaman': 'mail',
    'Death Knight': 'plate',
    'Paladin': 'plate',
    'Warrior': 'plate',
}

ARMOR_TYPES = ['cloth', 'leather', 'mail', 'plate']

ARMOR_EMOJIS = {
    'cloth': '🧵',
    'leather': '🥋',
    'mail': '⛓️',
    'plate': '🛡️',
}

ROLES = ['tank', 'healer', 'dps']

# A full M+ group composition
GROUP_ROLES = ['tank', 'healer', 'dps', 'dps', 'dps']
GROUP_SIZE = 5

EVENT_TYPE_ARMOR_STACKING = 'armor_stacking'

# Event statuses
STATUS_OPEN = 'open'
STATUS_FINALIZED = 'finalized'
STATUS_COMPLETED = 'completed'
STATUS_CANCELLED = 'cancelled'

# Alternates
ALT_REASON_UNLUCKY = 'unlucky'          # interchangeable, lost the draw → grace point
ALT_REASON_COMPOSITION = 'composition'  # no group needed their armor/role

# If the creator leaves the deadline blank, signups close this long before start
DEFAULT_DEADLINE_HOURS_BEFORE = 2


def armor_for_class(character_class: str) -> str:
    """Armor type for a class; unknown classes fall back to cloth."""
    return ARMOR_BY_CLASS.get(character_class, 'cloth')
