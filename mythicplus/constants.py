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

# How roles read in player-facing text ("still needs a tank", "not enough DPS")
ROLE_LABELS = {'tank': 'tank', 'healer': 'healer', 'dps': 'DPS'}
ROLE_PLURALS = {'tank': 'tanks', 'healer': 'healers', 'dps': 'DPS'}

# A full M+ group composition
GROUP_ROLES = ['tank', 'healer', 'dps', 'dps', 'dps']
GROUP_SIZE = 5

# Best-effort ("LFG") groups: tanks are the scarce role, so once no more full
# groups can be formed the leftovers are packed into 4-person groups that are
# short exactly one role and told to find that last player in the in-game
# group finder — far better than benching them all.
PARTIAL_GROUP_SIZE = 4

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


def missing_group_roles(assigned_roles) -> list:
    """Which of the 1T/1H/3D roles a group still needs, as a list."""
    remaining = list(GROUP_ROLES)
    for role in assigned_roles:
        if role in remaining:
            remaining.remove(role)
    return remaining


def format_roles(roles, plural=False) -> str:
    """Human list of roles: "tank", "tank and healer", "healer, DPS and DPS"."""
    labels = ROLE_PLURALS if plural else ROLE_LABELS
    names = [labels.get(role, role) for role in roles]
    if not names:
        return ''
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def armor_for_class(character_class: str) -> str:
    """Armor type for a class; unknown classes fall back to cloth."""
    return ARMOR_BY_CLASS.get(character_class, 'cloth')


def format_key_range(key_min: int, key_max: int) -> str:
    """Display form of a key range: "8–12", or just "10" for a single level."""
    return str(key_min) if key_min == key_max else f"{key_min}–{key_max}"
