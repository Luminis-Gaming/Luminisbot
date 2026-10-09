"""
Player cooldowns worth seeing on the consumables timeline: personal defensives,
externals, raid cooldowns and raid utility. Matched by ability *name* (from the
pull's Casts table), so spell-ID changes between patches and the several IDs one
ability can have just work - a name that isn't in a log simply never matches.
"""
from .analyzer import cast_entries

CATEGORIES = (
    ('raid', 'Raid cooldowns', '🛡️'),
    ('external', 'Externals', '🤝'),
    ('personal', 'Personal defensives', '💪'),
    ('utility', 'Raid utility', '🏃'),
)
CATEGORY_LABELS = {key: label for key, label, _ in CATEGORIES}

_BY_CATEGORY = {
    'raid': (
        'Anti-Magic Zone', 'Darkness', 'Rallying Cry', 'Commanding Shout', 'Aura Mastery', 'Spirit Link Totem',
        'Healing Tide Totem', 'Earthen Wall Totem', 'Ancestral Guidance', 'Power Word: Barrier', 'Divine Hymn',
        # Not Evangelism / Ultimate Penitence (a Discipline Priest's ramp) or Apotheosis (a Holy Priest's
        # burst): a healer's own cooldowns, judged as their major ones (benchmarks: a 30 s+ cooldown that
        # isn't listed here), not raid assignments
        'Vampiric Embrace', 'Tranquility', 'Revival', 'Restoral',
        'Rewind', 'Dream Flight', 'Zephyr', 'Mass Barrier',
    ),
    'external': (
        'Blessing of Sacrifice', 'Blessing of Protection', 'Blessing of Spellwarding', 'Lay on Hands',
        'Pain Suppression', 'Guardian Spirit', 'Ironbark', 'Life Cocoon', 'Time Dilation', 'Power Infusion',
        'Innervate', 'Intervene', 'Roar of Sacrifice', 'Source of Magic',
    ),
    'personal': (
        # Death Knight / Demon Hunter / Druid / Evoker / Hunter / Mage
        'Anti-Magic Shell', 'Icebound Fortitude', 'Lichborne', 'Vampiric Blood', 'Dancing Rune Weapon',
        'Blur', 'Netherwalk', 'Fiery Brand', 'Barkskin', 'Survival Instincts', 'Frenzied Regeneration', 'Renewal',
        'Obsidian Scales', 'Renewing Blaze', 'Aspect of the Turtle', 'Survival of the Fittest', 'Exhilaration',
        'Ice Block', 'Ice Cold', 'Greater Invisibility', 'Mirror Image', 'Alter Time',
        # Monk / Paladin / Priest / Rogue / Shaman / Warlock / Warrior
        'Fortifying Brew', 'Diffuse Magic', 'Dampen Harm', 'Touch of Karma', 'Zen Meditation',
        'Divine Shield', 'Divine Protection', 'Ardent Defender', 'Guardian of Ancient Kings',
        'Desperate Prayer', 'Dispersion', 'Cloak of Shadows', 'Evasion', 'Feint', 'Crimson Vial',
        'Astral Shift', 'Stone Bulwark Totem', 'Unending Resolve', 'Dark Pact',
        'Die by the Sword', 'Enraged Regeneration', 'Spell Reflection', 'Shield Wall', 'Last Stand',
        'Bitter Immunity',
    ),
    'utility': (
        'Bloodlust', 'Heroism', 'Time Warp', 'Fury of the Aspects', 'Primal Rage', 'Ancient Hysteria',
        'Stampeding Roar', 'Wind Rush Totem', 'Time Spiral', 'Blessing of Freedom',
        'Leap of Faith', "Tiger's Lust", 'Rescue', 'Demonic Gateway', "Gorefiend's Grasp", "Ursol's Vortex", 'Ring of Peace',
        'Rebirth', 'Raise Ally', 'Soulstone', 'Intercession', 'Symbol of Hope',
        # Not Spiritwalker's Grace: it only lets the shaman cast while moving - movement (benchmarks.NOT_MAJOR)
    ),
}
# Utility cast on one player - often yourself (Freedom, Tiger's Lust): only something for the raid when it went on
# someone else. (Externals the same: plenty of priests Power Infusion themselves.)
ON_SOMEONE = {'Blessing of Freedom', "Tiger's Lust", 'Leap of Faith', 'Rescue', 'Rebirth', 'Raise Ally', 'Soulstone',
              'Intercession'}
COOLDOWNS = {name: category for category, names in _BY_CATEGORY.items() for name in names}


def cooldown_meta(casts_table):
    """{spell id: {'name', 'icon', 'category'}} for the cooldowns cast in this pull."""
    return {e['guid']: {'name': e['name'], 'icon': e.get('abilityIcon'), 'category': COOLDOWNS[e['name']]}
            for e in cast_entries(casts_table) if e.get('name') in COOLDOWNS and e.get('guid')}
