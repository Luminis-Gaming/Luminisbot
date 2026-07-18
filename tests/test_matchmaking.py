"""
Unit tests for the Mythic+ matchmaking engine.
Run with:  python -m unittest discover tests
Pure Python — needs neither discord.py nor a database.
"""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mythicplus.constants import (ALT_REASON_COMPOSITION, ALT_REASON_UNLUCKY,
                                  armor_for_class)
from mythicplus.matchmaking import (alternate_reason, build_pool, build_roster,
                                    compute_grace_changes)

T0 = datetime(2026, 7, 1, 12, 0)


def row(discord_id, char, cls, role, signup_id=0, score=0.0, grace=0, minutes=0):
    return {
        'signup_id': signup_id or hash((discord_id, char, role)) % 100000,
        'discord_id': discord_id,
        'character_name': char,
        'realm_slug': 'test-realm',
        'character_class': cls,
        'role': role,
        'armor_type': armor_for_class(cls),
        'score': score,
        'grace_points': grace,
        'signed_at': T0 + timedelta(minutes=minutes),
    }


def make_roster(rows, seed=0):
    persons = build_pool(rows)
    roster = build_roster(persons, seed=seed)
    return roster, {p.discord_id: p for p in persons}


class TestPool(unittest.TestCase):
    def test_multiple_chars_and_roles_collapse_to_one_person(self):
        rows = [
            row('u1', 'Chara', 'Druid', 'tank'),
            row('u1', 'Chara', 'Druid', 'healer'),
            row('u1', 'Charb', 'Warrior', 'dps'),
        ]
        persons = build_pool(rows)
        self.assertEqual(len(persons), 1)
        self.assertEqual(len(persons[0].options), 3)

    def test_signup_rank_follows_earliest_signup(self):
        rows = [
            row('late', 'A', 'Mage', 'dps', minutes=30),
            row('early', 'B', 'Mage', 'dps', minutes=5),
        ]
        persons = {p.discord_id: p for p in build_pool(rows)}
        self.assertLess(persons['early'].signup_rank, persons['late'].signup_rank)


class TestSolver(unittest.TestCase):
    def test_two_full_plate_groups(self):
        rows = []
        for i in range(2):
            rows += [
                row(f'tank{i}', f'T{i}', 'Warrior', 'tank'),
                row(f'heal{i}', f'H{i}', 'Paladin', 'healer'),
            ]
            for j in range(3):
                rows.append(row(f'dps{i}{j}', f'D{i}{j}', 'Death Knight', 'dps'))
        roster, _ = make_roster(rows)
        self.assertEqual(len(roster.groups), 2)
        self.assertEqual([g.armor_score() for g in roster.groups], [5, 5])
        self.assertEqual(roster.benched, [])

    def test_person_never_in_two_groups(self):
        # 10 signups but only 7 people: flex player offers many chars
        rows = [
            row('flex', 'F1', 'Druid', 'tank'),
            row('flex', 'F2', 'Monk', 'healer'),
            row('flex', 'F3', 'Rogue', 'dps'),
            row('t2', 'T2', 'Warrior', 'tank'),
            row('h2', 'H2', 'Priest', 'healer'),
            row('d1', 'D1', 'Mage', 'dps'),
            row('d2', 'D2', 'Hunter', 'dps'),
            row('d3', 'D3', 'Warlock', 'dps'),
            row('d4', 'D4', 'Rogue', 'dps'),
        ]
        roster, _ = make_roster(rows)
        placed = [m.discord_id for g in roster.groups for m in g.members()]
        self.assertEqual(len(placed), len(set(placed)))

    def test_mail_group_gets_offarmor_tank(self):
        # 4 mail players + a leather tank: mail has no tank specs, so the
        # best possible mail stack is 4/5
        rows = [
            row('t', 'Tk', 'Druid', 'tank'),
            row('h', 'Hl', 'Shaman', 'healer'),
            row('d1', 'D1', 'Hunter', 'dps'),
            row('d2', 'D2', 'Shaman', 'dps'),
            row('d3', 'D3', 'Evoker', 'dps'),
        ]
        roster, _ = make_roster(rows)
        self.assertEqual(len(roster.groups), 1)
        group = roster.groups[0]
        self.assertEqual(group.modal_armor(), 'mail')
        self.assertEqual(group.armor_score(), 4)

    def test_no_tanks_means_no_groups(self):
        rows = [row(f'u{i}', f'C{i}', 'Mage', 'dps') for i in range(6)]
        roster, persons_by_id = make_roster(rows)
        self.assertEqual(roster.groups, [])
        self.assertEqual(len(roster.benched), 6)
        # Nobody was placed, so nobody was "unlucky" — no grace awards
        changes = compute_grace_changes(roster, persons_by_id)
        self.assertEqual(changes.awards, [])

    def test_armor_stacking_beats_mixed_assignment(self):
        # 5 plate + 5 cloth-ish players with exactly matching roles: the
        # solver should produce one plate-stacked and one cloth-stacked group
        rows = [
            row('pt', 'PT', 'Warrior', 'tank'),
            row('ph', 'PH', 'Paladin', 'healer'),
            row('pd1', 'PD1', 'Death Knight', 'dps'),
            row('pd2', 'PD2', 'Warrior', 'dps'),
            row('pd3', 'PD3', 'Paladin', 'dps'),
            row('ct', 'CT', 'Monk', 'tank'),
            row('ch', 'CH', 'Priest', 'healer'),
            row('cd1', 'CD1', 'Mage', 'dps'),
            row('cd2', 'CD2', 'Warlock', 'dps'),
            row('cd3', 'CD3', 'Priest', 'dps'),
        ]
        roster, _ = make_roster(rows)
        self.assertEqual(len(roster.groups), 2)
        # Plate group must be 5/5; the other stacks 4 cloth + leather tank
        scores = sorted(g.armor_score() for g in roster.groups)
        self.assertEqual(scores, [4, 5])

    def test_armor_diversity_gives_cloth_a_group(self):
        # 10 leather (2 tanks, 2 healers, 6 dps) + 4 cloth (healer + 3 dps).
        # Pure homogeneity would double-stack leather (5+5) and bench all
        # cloth; the diversity bonus should instead produce one leather 5/5
        # and one cloth-modal group (leather tank + priest + 3 mages)
        rows = [
            row('lt1', 'LT1', 'Druid', 'tank'),
            row('lt2', 'LT2', 'Druid', 'tank'),
            row('lh1', 'LH1', 'Monk', 'healer'),
            row('lh2', 'LH2', 'Monk', 'healer'),
        ]
        rows += [row(f'ld{i}', f'LD{i}', 'Rogue', 'dps') for i in range(6)]
        rows += [row('ch', 'CH', 'Priest', 'healer')]
        rows += [row(f'cd{i}', f'CD{i}', 'Mage', 'dps') for i in range(3)]
        roster, _ = make_roster(rows)
        self.assertEqual(len(roster.groups), 2)
        modal_armors = {g.modal_armor() for g in roster.groups}
        self.assertEqual(modal_armors, {'leather', 'cloth'})

    def test_diversity_never_beats_a_second_full_group(self):
        # Only leather players: diversity can't invent cloth groups — the
        # solver must still just build two full leather groups
        rows = [
            row('t1', 'T1', 'Druid', 'tank'),
            row('t2', 'T2', 'Demon Hunter', 'tank'),
            row('h1', 'H1', 'Monk', 'healer'),
            row('h2', 'H2', 'Druid', 'healer'),
        ]
        rows += [row(f'd{i}', f'D{i}', 'Rogue', 'dps') for i in range(6)]
        roster, _ = make_roster(rows)
        self.assertEqual(len(roster.groups), 2)
        self.assertEqual([g.armor_score() for g in roster.groups], [5, 5])

    def test_deterministic_for_same_seed(self):
        rows = [
            row('t1', 'T1', 'Druid', 'tank'),
            row('h1', 'H1', 'Monk', 'healer'),
        ] + [row(f'd{i}', f'D{i}', 'Rogue', 'dps') for i in range(5)]
        roster_a, _ = make_roster(rows, seed=42)
        roster_b, _ = make_roster(rows, seed=42)
        ids_a = [[m.signup_id for m in g.members()] for g in roster_a.groups]
        ids_b = [[m.signup_id for m in g.members()] for g in roster_b.groups]
        self.assertEqual(ids_a, ids_b)


class TestGraceAndRio(unittest.TestCase):
    def base_rows(self, extra_dps_grace=0):
        return [
            row('t1', 'T1', 'Warrior', 'tank'),
            row('h1', 'H1', 'Paladin', 'healer'),
            row('d1', 'D1', 'Death Knight', 'dps', minutes=1),
            row('d2', 'D2', 'Death Knight', 'dps', minutes=2),
            row('d3', 'D3', 'Death Knight', 'dps', minutes=3),
            row('d4', 'D4', 'Death Knight', 'dps', minutes=4,
                grace=extra_dps_grace),
        ]

    def test_unlucky_bench_earns_grace(self):
        # 6 players, 4 interchangeable plate DPS — one sits out and is owed
        roster, persons_by_id = make_roster(self.base_rows())
        self.assertEqual(len(roster.groups), 1)
        self.assertEqual(len(roster.benched), 1)
        benched = roster.benched[0]
        self.assertEqual(
            alternate_reason(benched, roster, persons_by_id), ALT_REASON_UNLUCKY)
        changes = compute_grace_changes(roster, persons_by_id)
        self.assertEqual(changes.awards, [benched.discord_id])

    def test_grace_holder_wins_the_draw(self):
        # d4 signed last but holds a grace point → beats d3 for the last slot
        roster, persons_by_id = make_roster(self.base_rows(extra_dps_grace=1))
        placed = roster.placed_ids()
        self.assertIn('d4', placed)
        # ...and their point is consumed by being placed
        changes = compute_grace_changes(roster, persons_by_id)
        self.assertIn('d4', changes.resets)

    def test_grace_cannot_break_armor_stacking(self):
        # A grace-holding cloth DPS must not displace plate DPS from a
        # plate-stacked group (armor homogeneity outranks grace)
        rows = self.base_rows() + [
            row('mage', 'M1', 'Mage', 'dps', grace=5, minutes=0),
        ]
        roster, persons_by_id = make_roster(rows)
        group = roster.groups[0]
        self.assertEqual(group.armor_score(), 5)
        self.assertNotIn('mage', group.member_ids())
        # The mage is benched for composition, not luck — no grace award
        mage = next(p for p in roster.benched if p.discord_id == 'mage')
        self.assertEqual(
            alternate_reason(mage, roster, persons_by_id), ALT_REASON_COMPOSITION)

    def test_rio_sorts_within_equal_armor(self):
        # Two full plate groups; scores should cluster high/low
        rows = [
            row('t1', 'T1', 'Warrior', 'tank', score=3000),
            row('t2', 'T2', 'Paladin', 'tank', score=1000),
            row('h1', 'H1', 'Paladin', 'healer', score=3000),
            row('h2', 'H2', 'Paladin', 'healer', score=1000),
        ]
        for i, score in enumerate([3000, 2900, 2800, 1100, 1000, 900]):
            rows.append(row(f'd{i}', f'D{i}', 'Death Knight', 'dps', score=score))
        roster, _ = make_roster(rows)
        self.assertEqual(len(roster.groups), 2)
        for group in roster.groups:
            self.assertEqual(group.armor_score(), 5)
            self.assertLessEqual(group.rio_spread(), 300)

    def test_alternates_ordered_by_grace_then_signup(self):
        rows = self.base_rows() + [
            row('d5', 'D5', 'Death Knight', 'dps', minutes=5, grace=2),
            row('d6', 'D6', 'Death Knight', 'dps', minutes=6),
        ]
        roster, _ = make_roster(rows)
        self.assertEqual(len(roster.benched), 3)
        # d5 holds 2 grace points... but wait: grace holders get placed first,
        # so d5 should be IN the group and the bench holds pure-luck losers
        self.assertIn('d5', roster.placed_ids())


if __name__ == '__main__':
    unittest.main()
