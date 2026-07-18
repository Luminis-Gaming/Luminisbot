"""
Grace point rules (see MYTHICPLUS_PLAN.md §5).

Award: a benched player earns +1 iff swapping them into some occupied slot
would leave the group count and armor homogeneity unchanged — they were
genuinely interchangeable with someone who got in and lost the draw.
Benched because no group could use their armor/role → no point.

Consume: any placed player's points reset to 0 — getting a spot spends
your priority, contested or not.

Both are computed here as pure decisions; persisting them is db.py's job.
"""
from dataclasses import dataclass, field

from .scoring import roster_score


@dataclass
class GraceChanges:
    awards: list = field(default_factory=list)   # discord_ids to give +1
    resets: list = field(default_factory=list)   # discord_ids to reset to 0


def compute_grace_changes(roster, persons_by_id) -> GraceChanges:
    changes = GraceChanges()
    placed_ids = roster.placed_ids()

    for person in roster.benched:
        if _is_interchangeable(person, roster, persons_by_id):
            changes.awards.append(person.discord_id)

    for pid in placed_ids:
        if persons_by_id[pid].grace_points > 0:
            changes.resets.append(pid)

    return changes


def alternate_reason(person, roster, persons_by_id) -> str:
    from ..constants import ALT_REASON_COMPOSITION, ALT_REASON_UNLUCKY
    if _is_interchangeable(person, roster, persons_by_id):
        return ALT_REASON_UNLUCKY
    return ALT_REASON_COMPOSITION


def _is_interchangeable(person, roster, persons_by_id) -> bool:
    """Would swapping this benched player in keep objectives 1 & 2 intact?"""
    if not roster.groups:
        return False
    base = roster_score(roster.groups, persons_by_id)
    base_key = base[:2]  # (complete groups, armor homogeneity)

    for group in roster.groups:
        for slot in group.slots:
            for option in person.options_for_role(slot.role):
                original = slot.option
                slot.option = option
                key = roster_score(roster.groups, persons_by_id)[:2]
                slot.option = original
                if key >= base_key:
                    return True
    return False
