"""
Mythic+ domain models — pure dataclasses, no discord/psycopg2 imports.
"""
from dataclasses import dataclass, field
from collections import Counter

from .constants import GROUP_ROLES, GROUP_SIZE, missing_group_roles


@dataclass(frozen=True)
class SignupOption:
    """One (character, role) offering by a player. A player may have many."""
    signup_id: int
    discord_id: str
    character_name: str
    realm_slug: str
    character_class: str
    role: str            # tank | healer | dps
    armor_type: str      # cloth | leather | mail | plate
    score: float = 0.0   # role-specific Raider.IO score (0 when unknown)


@dataclass
class Person:
    """A Discord user in the signup pool with all their offerings."""
    discord_id: str
    options: list = field(default_factory=list)  # list[SignupOption]
    grace_points: int = 0
    signup_rank: int = 0     # 0 = earliest signup, used as final tie-break
    display_name: str = ''

    def options_for_role(self, role: str):
        return [o for o in self.options if o.role == role]

    def has_role(self, role: str) -> bool:
        return any(o.role == role for o in self.options)


@dataclass
class Slot:
    role: str
    option: SignupOption


@dataclass
class Group:
    """A 1T/1H/3D group. Slot order matches GROUP_ROLES.

    A group with fewer than GROUP_SIZE slots is a best-effort "LFG" group:
    complete apart from one role its players are told to fill themselves.
    """
    slots: list  # list[Slot], normally [tank, healer, dps, dps, dps]

    def members(self):
        return [s.option for s in self.slots]

    def member_ids(self):
        return {s.option.discord_id for s in self.slots}

    def modal_armor(self) -> str:
        counts = Counter(o.armor_type for o in self.members())
        return counts.most_common(1)[0][0]

    def is_partial(self) -> bool:
        return len(self.slots) < GROUP_SIZE

    def missing_roles(self) -> list:
        return missing_group_roles(s.role for s in self.slots)

    def armor_score(self) -> int:
        """How many members share the group's most common armor type."""
        counts = Counter(o.armor_type for o in self.members())
        return counts.most_common(1)[0][1]

    def rio_spread(self) -> float:
        scores = [o.score for o in self.members()]
        return max(scores) - min(scores)

    @staticmethod
    def roles():
        return list(GROUP_ROLES)


@dataclass
class Roster:
    """Result of matchmaking: complete groups, best-effort groups formed from
    the leftovers, and everyone who missed a complete group.

    `benched` deliberately still contains the players who landed in a partial
    group — they did not win a real spot, so for grace-point purposes they
    count as benched. `reserves()` is the list that actually goes on the
    reserve list.
    """
    groups: list                 # list[Group], complete 1T/1H/3D
    benched: list                # list[Person], in alternate-priority order
    partial_groups: list = field(default_factory=list)   # list[Group], 4-man
    seed: int = 0

    def placed_ids(self):
        ids = set()
        for g in self.groups:
            ids |= g.member_ids()
        return ids

    def partial_ids(self):
        ids = set()
        for g in self.partial_groups:
            ids |= g.member_ids()
        return ids

    def reserves(self):
        """Benched players who didn't even fit a best-effort group."""
        in_partial = self.partial_ids()
        return [p for p in self.benched if p.discord_id not in in_partial]
