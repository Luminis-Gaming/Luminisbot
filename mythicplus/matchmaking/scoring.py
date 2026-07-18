"""
Lexicographic roster objective.

Priority order (decided in MYTHICPLUS_PLAN.md):
    1. number of complete groups
    2. armor homogeneity (sum of per-group modal-armor counts)
    3. grace-weighted placement (sum of placed players' grace points)
    4. RIO cohesion (negated sum of per-group score spreads)
    5. tie-break: earlier signups placed first (negated sum of signup ranks)

Tuples compare left-to-right, so a higher earlier component always beats
any improvement in a later one. Maximize.
"""


def roster_score(groups, persons_by_id):
    placed_ids = set()
    for g in groups:
        placed_ids |= g.member_ids()

    armor_sum = sum(g.armor_score() for g in groups)
    grace_sum = sum(persons_by_id[pid].grace_points for pid in placed_ids)
    spread_sum = sum(g.rio_spread() for g in groups)
    rank_sum = sum(persons_by_id[pid].signup_rank for pid in placed_ids)

    return (len(groups), armor_sum, grace_sum, -spread_sum, -rank_sum)
