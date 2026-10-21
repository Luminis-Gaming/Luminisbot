"""
Unit tests for the auction house's pure parts: reading a listing's roll (auctionhouse/rolls.py) and which prices
count (auctionhouse/prices.py). Run with:  python -m unittest discover tests
Fixtures are real EU listings and prices seen in October 2026.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auctionhouse import prices, rolls

G = 10000  # copper per gold

# ItemBonus effects (type, value 0, value 1) for the bonus ids below, as wago.tools has them
BONUS = {
    1530: [(1, 58, 0)],                                       # item level +58
    1677: [(2, 32, 4500), (2, 40, 2500), (5, 13152, 0)],      # Critical Strike (more) + Versatility
    1696: [(2, 32, 2000), (2, 36, 5000), (5, 13150, 0)],      # Haste (more) + Critical Strike
    6652: [(0, 0, 0)],
    10844: [(16, 2, 0)],                                      # binds when equipped
    11944: [(3, 3, 0), (7, 4, -1), (49, 378, 0)],             # level curve 378
    12850: [(34, 618, 978), (3, 4, 0), (7, 3, -1), (10, 250, 0), (49, 319, 0)],  # level curve 319
    13335: [(0, 0, 0), (4, 13145, 0)],
    13662: [(37, 13, 0)],
    42: [(2, 61, 3000), (9, 12, 100)],                        # Speed
    9516: [(6, 1, 7), (26, 5, 0)],                            # a socket
}


class RollTest(unittest.TestCase):
    def test_bonus_secondaries(self):
        """Lamplighter's Battleaxe: its stats come from a bonus id; the pair is sorted, the larger one remembered."""
        roll = rolls.decode({'id': 229152, 'bonus_lists': [1530, 1677, 6652, 10844, 11944]}, BONUS)
        self.assertEqual(roll.sec, 'Critical Strike/Versatility')
        self.assertEqual(roll.heavy, 'Critical Strike')
        self.assertEqual(roll.curve, 378)
        self.assertEqual(roll.bind, 2)
        self.assertEqual(roll.level_key, 'c378')

    def test_same_pair_either_way_round_is_one_roll(self):
        a = rolls.decode({'bonus_lists': [1696, 11944]}, BONUS)
        b = rolls.decode({'bonus_lists': [11944], 'modifiers': [{'type': 29, 'value': 32}, {'type': 30, 'value': 36}]}, BONUS)
        self.assertEqual(a.sec, 'Critical Strike/Haste')
        self.assertEqual(a.key, b.key)

    def test_crafted_secondaries(self):
        """Greaves of the Noxious Depths: Midnight gear keeps its random stats in modifiers 29 and 30."""
        item = {'id': 271440, 'bonus_lists': [6652, 13662, 13335, 12850, 10844],
                'modifiers': [{'type': 28, 'value': 7362}, {'type': 29, 'value': 32}, {'type': 30, 'value': 49}]}
        roll = rolls.decode(item, BONUS)
        self.assertEqual(roll.sec, 'Critical Strike/Mastery')
        self.assertEqual(roll.heavy, 'Critical Strike')
        self.assertEqual(roll.crafted, '32:49')
        self.assertEqual(roll.bonus, '6652:10844:12850:13335:13662')
        self.assertEqual(rolls.tooltip_query(roll.bonus, roll.crafted), 'bonus=6652:10844:12850:13335:13662&crafted-stats=32:49')
        self.assertEqual(rolls.item_level(roll, 219, {319: 321}), 321)

    def test_tertiary_and_socket(self):
        roll = rolls.decode({'bonus_lists': [42, 9516]}, BONUS)
        self.assertEqual((roll.sec, roll.ter, roll.sock), ('', 'Speed', 1))

    def test_level_without_curve(self):
        roll = rolls.decode({'bonus_lists': [1530], 'modifiers': [{'type': 9, 'value': 80}]}, BONUS)
        self.assertEqual(roll.level_key, 'd58/80')
        self.assertEqual(rolls.item_level(roll, 545, {}), 603)

    def test_unknown_curve_falls_back_to_base_level(self):
        roll = rolls.decode({'bonus_lists': [12850]}, BONUS)
        self.assertEqual(rolls.item_level(roll, 219, {}), 219)


class PetTest(unittest.TestCase):
    def test_a_caged_pet_is_its_species_with_breed_level_and_quality(self):
        """Living Sandling, as listed: a rare level 1 H/S."""
        cage = {'id': 82800, 'modifiers': [{'type': 6, 'value': 47252}], 'pet_breed_id': 9, 'pet_level': 1,
                'pet_quality_id': 3, 'pet_species_id': 1177}
        self.assertEqual(rolls.pet_item_id(cage['pet_species_id']), -1177)
        roll = rolls.decode_pet(cage)
        self.assertEqual((roll.sec, roll.ter, roll.level_key), ('H/S', 'Rare', 'L1'))
        self.assertEqual(rolls.item_level(roll, 0, {}), 1)
        self.assertEqual(roll.tooltip, 'breed=9&level=1&quality=3')

    def test_breeds_13_to_22_are_the_same_breeds(self):
        a = rolls.decode_pet({'pet_breed_id': 8, 'pet_level': 25, 'pet_quality_id': 3})
        b = rolls.decode_pet({'pet_breed_id': 18, 'pet_level': 25, 'pet_quality_id': 3})
        self.assertEqual(a.sec, 'P/S')
        self.assertEqual(a.key, b.key)


class CommodityTest(unittest.TestCase):
    def test_market_price_is_the_cheapest_15_percent(self):
        # 1,000 on sale: 100 at 10g, 100 at 12g, 800 at 20g -> the cheapest 150 cost 100x10g + 50x12g
        s = prices.commodity_stats([(10 * G, 100), (12 * G, 100), (20 * G, 800)])
        self.assertEqual(s['lo'], 10 * G)
        self.assertEqual(s['market'], round((100 * 10 + 50 * 12) * G / 150))
        self.assertEqual(s['p05'], 10 * G)
        self.assertEqual(s['p30'], 20 * G)
        self.assertEqual((s['quantity'], s['levels']), (1000, 3))

    def test_lottery_asks_at_the_cap_are_left_out(self):
        s = prices.commodity_stats([(5 * G, 2), (9999999 * G, 1000)])
        self.assertEqual((s['lo'], s['market'], s['quantity']), (5 * G, 5 * G, 2))
        self.assertIsNone(prices.commodity_stats([(9999999 * G, 3)]))


class PriceTest(unittest.TestCase):
    def test_people_pick_round_prices(self):
        for g in (3499999, 296000, 50000, 2900000, 499):
            self.assertTrue(prices.is_round(g * G), g)
        for g in (1688999, 6255261, 4018233):
            self.assertFalse(prices.is_round(g * G), g)
        self.assertTrue(prices.anchored(2899974 * G))   # undercutting 2,900,000g
        self.assertFalse(prices.anchored(4018233 * G))
        self.assertFalse(prices.anchored(3596867 * G))  # a bot 3,133g under 3,600,000g

    def test_bot_wall_of_one_odd_price(self):
        """Darkmoon Pendant: 19 realm groups ask exactly 6,255,261g."""
        lows = [50, 1000, 5000, 38800, 50000, 69900, 660000] + [6255261] * 19 + [10000000] * 7
        walls = prices.find_walls([g * G for g in lows])
        self.assertIn(6255261 * G, walls)
        self.assertNotIn(50000 * G, walls)

    def test_bot_wall_a_few_gold_apart(self):
        lows = [9500, 9995, 10001, 15000] + [4018233, 4019871, 4021863, 4020515]
        walls = prices.find_walls([g * G for g in lows])
        self.assertTrue(all(g * G in walls for g in (4018233, 4019871, 4021863, 4020515)))
        self.assertNotIn(9995 * G, walls)

    def test_people_undercutting_each_other_are_not_a_wall(self):
        """Wooly White Rhino: realms just under 2,900,000g and 3,500,000g are real sellers."""
        lows = [1990000, 2000000, 2081998, 2899881, 2899968, 2899974, 2899982, 2899985] + [2899999] * 5 \
            + [3499954, 3499968] + [3499999] * 8 + [4000000, 7500000]
        walls = prices.find_walls([g * G for g in lows])
        self.assertEqual(walls, {})

    def test_a_popular_round_price_is_not_a_wall(self):
        """Greaves at Myth 2/6: lots of sellers on different realms all ask 499,999g. That's the market."""
        lows = [299999, 449999, 450000] + [499999] * 24 + [699999, 699999]
        self.assertEqual(prices.find_walls([g * G for g in lows]), {})

    def test_the_price_cap_is_a_lottery_ticket(self):
        walls = prices.find_walls([4996 * G, 9999999 * G, 9999999 * G + 9999])
        self.assertEqual(set(walls), {9999999 * G, 9999999 * G + 9999})

    def test_stats_leave_out_walls_and_far_above(self):
        walls = {6255261 * G: 19}
        rows = [(cr, g * G, 1) for cr, g in enumerate([50000, 52000, 55000, 60000, 61000, 65000, 70000, 900000])]
        rows.append((99, 6255261 * G, 1))
        s = prices.stats(rows, walls)
        self.assertEqual(s['lo'], 50000 * G)
        self.assertEqual(s['hi'], 70000 * G)       # 900k is over 10x typical, the wall is a wall
        self.assertEqual(s['flagged'], 2)
        self.assertEqual(s['realms'], 9)
        self.assertGreater(s['gain'], 0)

    def test_stats_fall_back_when_only_walls(self):
        walls = {1688999 * G: 30}
        s = prices.stats([(1, 1688999 * G, 1), (2, 1688999 * G, 1)], walls)
        self.assertTrue(s['fell_back'])
        self.assertEqual(s['flagged'], 0)


if __name__ == '__main__':
    unittest.main()
