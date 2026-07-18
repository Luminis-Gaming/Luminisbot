"""
Lexicographic roster objective.

Priority order (decided in MYTHICPLUS_PLAN.md):
    1. number of complete groups
    2. armor homogeneity + diversity (see below)
    3. grace-weighted placement (sum of placed players' grace points)
    4. RIO cohesion (negated sum of per-group score spreads)
    5. tie-break: earlier signups placed first (negated sum of signup ranks)

Tuples compare left-to-right, so a higher earlier component always beats
any improvement in a later one. Maximize.

The armor component is Σ per-group modal-armor counts plus a bonus per
DISTINCT armor type among the groups. Without the bonus, tank supply
(leather/plate only) drags every group toward leather/plate stacks and
cloth/mail players end up benched or scattered. The bonus makes the solver
trade up to ~1 stacking point to give another armor type its own group
(leather 5/5 + cloth 4/5 = 9+2·2 beats leather 5/5 + leather 5/5 = 10+2·1),
while still refusing bad trades when cloth/mail presence is too thin to
stack at all.
"""

ARMOR_DIVERSITY_BONUS = 2


def roster_score(groups, persons_by_id):
    placed_ids = set()
    for g in groups:
        placed_ids |= g.member_ids()

    armor_sum = sum(g.armor_score() for g in groups)
    distinct_armors = len({g.modal_armor() for g in groups})
    armor_component = armor_sum + ARMOR_DIVERSITY_BONUS * distinct_armors
    grace_sum = sum(persons_by_id[pid].grace_points for pid in placed_ids)
    spread_sum = sum(g.rio_spread() for g in groups)
    rank_sum = sum(persons_by_id[pid].signup_rank for pid in placed_ids)

    return (len(groups), armor_component, grace_sum, -spread_sum, -rank_sum)
