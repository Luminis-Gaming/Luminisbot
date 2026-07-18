"""
Roster solver: greedy construction seeded by armor buckets + swap-based
local search, with deterministic randomized restarts.

Guild scale (5-40 players) keeps this cheap; the same (persons, seed)
always produces the same roster, which makes the unattended finalize
pipeline idempotent if it crashes and re-runs.
"""
import random

from ..constants import ARMOR_TYPES, GROUP_ROLES, GROUP_SIZE
from ..models import Group, Roster, Slot
from .scoring import roster_score

RESTARTS = 12
MAX_SEARCH_PASSES = 60


def build_roster(persons, seed=0) -> Roster:
    """Form as many complete 1T/1H/3D groups as possible from the pool."""
    persons_by_id = {p.discord_id: p for p in persons}
    target_groups = len(persons) // GROUP_SIZE

    best_groups = []
    best_score = roster_score([], persons_by_id)

    if target_groups > 0:
        for restart in range(RESTARTS):
            rng = random.Random(seed * 1_000_003 + restart)
            groups = _greedy_build(persons_by_id, target_groups, rng)
            groups = _local_search(groups, persons_by_id, rng)
            score = roster_score(groups, persons_by_id)
            if score > best_score:
                best_score = score
                best_groups = groups

    placed = set()
    for g in best_groups:
        placed |= g.member_ids()
    # Alternate priority: most grace first, then earliest signup
    benched = sorted(
        (p for p in persons if p.discord_id not in placed),
        key=lambda p: (-p.grace_points, p.signup_rank),
    )
    return Roster(groups=best_groups, benched=benched, seed=seed)


def _greedy_build(persons_by_id, target_groups, rng):
    remaining = dict(persons_by_id)
    groups = []
    while len(groups) < target_groups:
        built = None
        used_armors = {g.modal_armor() for g in groups}
        for target_armor in _armor_targets(remaining, used_armors, rng):
            built = _try_build_group(remaining, target_armor, rng)
            if built:
                break
        if not built:
            break
        groups.append(built)
        for member_id in built.member_ids():
            remaining.pop(member_id, None)
    return groups


def _armor_targets(remaining, used_armors, rng):
    """Armor types ordered by how many remaining players can contribute,
    preferring types that don't have a group yet (armor diversity — matches
    the diversity bonus in scoring)."""
    counts = {
        armor: sum(1 for p in remaining.values()
                   if any(o.armor_type == armor for o in p.options))
        for armor in ARMOR_TYPES
    }
    return sorted(ARMOR_TYPES,
                  key=lambda a: (a in used_armors, -counts[a], rng.random()))


def _try_build_group(remaining, target_armor, rng):
    used = set()
    slots = []
    for role in GROUP_ROLES:
        candidates = []
        for person in remaining.values():
            if person.discord_id in used:
                continue
            options = person.options_for_role(role)
            if not options:
                continue
            # This person's best offering for the slot: match the target
            # armor if they can, then their highest-scored character
            option = max(options, key=lambda o: (o.armor_type == target_armor, o.score))
            candidates.append((person, option))
        if not candidates:
            return None

        def pick_key(pair):
            person, option = pair
            # Armor stacking first; for DPS slots protect scarce tanks and
            # healers by preferring pure-DPS players; then grace and
            # signup order (armor > grace per the plan's priority order)
            protects_scarce = (
                role == 'dps'
                and not person.has_role('tank')
                and not person.has_role('healer')
            )
            return (
                option.armor_type == target_armor,
                protects_scarce,
                person.grace_points,
                -person.signup_rank,
                rng.random(),
            )

        person, option = max(candidates, key=pick_key)
        slots.append(Slot(role, option))
        used.add(person.discord_id)
    return Group(slots=slots)


def _local_search(groups, persons_by_id, rng):
    """First-improvement hill climb over swaps until no move helps."""
    if not groups:
        return groups

    for _ in range(MAX_SEARCH_PASSES):
        if not (_pass_replace_benched(groups, persons_by_id)
                or _pass_switch_option(groups, persons_by_id)
                or _pass_swap_slots(groups, persons_by_id)):
            break
    return groups


def _all_slots(groups):
    for gi, group in enumerate(groups):
        for si, slot in enumerate(group.slots):
            yield gi, si, slot


def _pass_replace_benched(groups, persons_by_id):
    """Try putting a benched player into an occupied slot."""
    current = roster_score(groups, persons_by_id)
    placed = set()
    for g in groups:
        placed |= g.member_ids()
    benched = [p for p in persons_by_id.values() if p.discord_id not in placed]

    for gi, si, slot in _all_slots(groups):
        for person in benched:
            for option in person.options_for_role(slot.role):
                original = slot.option
                slot.option = option
                if roster_score(groups, persons_by_id) > current:
                    return True
                slot.option = original
    return False


def _pass_switch_option(groups, persons_by_id):
    """Try a placed player's other characters for their current slot."""
    current = roster_score(groups, persons_by_id)
    for gi, si, slot in _all_slots(groups):
        person = persons_by_id[slot.option.discord_id]
        for option in person.options_for_role(slot.role):
            if option is slot.option:
                continue
            original = slot.option
            slot.option = option
            if roster_score(groups, persons_by_id) > current:
                return True
            slot.option = original
    return False


def _pass_swap_slots(groups, persons_by_id):
    """Try swapping two placed players (across or within groups)."""
    current = roster_score(groups, persons_by_id)
    slots = list(_all_slots(groups))
    for i in range(len(slots)):
        for j in range(i + 1, len(slots)):
            _, _, slot_a = slots[i]
            _, _, slot_b = slots[j]
            person_a = persons_by_id[slot_a.option.discord_id]
            person_b = persons_by_id[slot_b.option.discord_id]
            if person_a.discord_id == person_b.discord_id:
                continue
            for option_a in person_a.options_for_role(slot_b.role):
                for option_b in person_b.options_for_role(slot_a.role):
                    orig_a, orig_b = slot_a.option, slot_b.option
                    slot_a.option = option_b
                    slot_b.option = option_a
                    if roster_score(groups, persons_by_id) > current:
                        return True
                    slot_a.option = orig_a
                    slot_b.option = orig_b
    return False
