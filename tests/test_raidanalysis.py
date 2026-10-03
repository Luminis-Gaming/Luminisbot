"""
Unit tests for the raid analysis engine (raidanalysis/analyzer.py).
Run with:  python -m unittest discover tests
Pure Python — needs neither WCL nor a database. Fixtures use the same JSON
shapes WCL returns (v2 tables are v1 tables; events carry abilityGameID).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from raidanalysis import analyzer

BOSS, CAUSTIC, AURA, THRASH = 1, 1292403, 1306858, 1305709


def actors(*names):
    return [{'id': i + 1, 'name': n, 'subType': 'Warrior'} for i, n in enumerate(names)]


def fight(players, kill=False, size=None):
    return {'id': 11, 'startTime': 1000, 'endTime': 601000, 'kill': kill, 'size': size or len(players),
            'friendlyPlayers': [p['id'] for p in players]}


def damage(target_id, ability, amount, tick=False, t=5000):
    event = {'timestamp': t, 'type': 'damage', 'targetID': target_id, 'abilityGameID': ability,
             'amount': amount}
    if tick:
        event['tick'] = True
    return event


def damage_table(*guids):
    return {'entries': [{'guid': g, 'name': f'Ability {g}', 'total': 1, 'hitCount': 1, 'tickCount': 0,
                         'sources': [{'name': 'Boss', 'type': 'Boss'}], 'targets': []} for g in guids]}


def analyze(players, events=(), deaths=(), kill=False, player_details=None, casts=None, consumables=()):
    tables = {'damageTaken': damage_table(CAUSTIC, AURA, THRASH), 'deaths': {'entries': list(deaths)},
              'interrupts': {'entries': []}, 'dispels': {'entries': []},
              'playerDetails': player_details or {}}
    potions, defensives = analyzer.consumable_ids(casts or {'entries': []})
    return analyzer.analyze_fight(fight(players, kill), players, tables, list(events), list(consumables),
                                  set(potions), set(defensives))


class TestDeathsAndWipeCall(unittest.TestCase):
    def test_deaths_after_half_the_raid_is_dead_dont_count(self):
        players = actors('A', 'B', 'C', 'D')
        deaths = [{'name': n, 'timestamp': 1000 + t, 'killingBlow': {'name': 'Caustic Waves', 'guid': CAUSTIC}}
                  for n, t in (('A', 100), ('B', 200), ('C', 300), ('D', 400))]
        a = analyze(players, deaths=deaths)
        self.assertEqual(a['wipe_at'], 200)  # 2 of 4 dead
        self.assertEqual([d['after_wipe'] for d in a['deaths']], [False, False, True, True])

        board = {r['name']: r for r in analyzer.scoreboard([dict(a, _duration=600000)], {})}
        self.assertEqual(board['A']['first_deaths'], 1)
        self.assertEqual(board['C']['deaths'], 0)

    def test_kills_have_no_wipe_moment(self):
        players = actors('A', 'B')
        deaths = [{'name': 'A', 'timestamp': 1100}, {'name': 'B', 'timestamp': 1200}]
        self.assertIsNone(analyze(players, deaths=deaths, kill=True)['wipe_at'])


class TestMistakeCounting(unittest.TestCase):
    def test_dot_ticks_after_a_direct_hit_are_one_mistake(self):
        players = actors('A')
        a = analyze(players, [damage(1, CAUSTIC, 500), damage(1, CAUSTIC, 50, tick=True),
                              damage(1, CAUSTIC, 50, tick=True)])
        caustic = next(x for x in a['abilities'] if x['id'] == CAUSTIC)
        self.assertEqual(analyzer.mistake_counts(caustic), {'A': 1})

    def test_tick_only_auras_count_every_tick(self):
        players = actors('A')
        a = analyze(players, [damage(1, AURA, 100, tick=True) for _ in range(3)])
        aura = next(x for x in a['abilities'] if x['id'] == AURA)
        self.assertEqual(analyzer.mistake_counts(aura), {'A': 3})

    def test_zero_damage_events_are_not_hits(self):
        # An immune player's 0-damage "hit" must not flip a tick-only aura into hit counting.
        players = actors('A', 'B')
        a = analyze(players, [damage(1, AURA, 100, tick=True), damage(2, AURA, 0)])
        aura = next(x for x in a['abilities'] if x['id'] == AURA)
        self.assertEqual(analyzer.mistake_counts(aura), {'A': 1})

    def test_non_tank_tag_ignores_tanks(self):
        players = actors('Tank', 'Dps')
        details = {'playerDetails': {'tanks': [{'name': 'Tank', 'type': 'Warrior', 'icon': 'Warrior-Protection'}],
                                     'dps': [{'name': 'Dps', 'type': 'Warrior', 'icon': 'Warrior-Arms'}]}}
        a = analyze(players, [damage(1, THRASH, 900), damage(2, THRASH, 900)], player_details=details)
        out = analyzer.avoidable_by_player(a, {THRASH: analyzer.TAG_AVOIDABLE_NON_TANK})
        self.assertEqual(set(out), {'Dps'})
        out = analyzer.avoidable_by_player(a, {THRASH: analyzer.TAG_AVOIDABLE})
        self.assertEqual(set(out), {'Tank', 'Dps'})


class TestConsumables(unittest.TestCase):
    def test_potions_found_by_id_and_name(self):
        casts = {'entries': [
            {'guid': 1236616, 'name': "Light's Potential"},                     # no "potion" in name
            {'guid': 999001, 'name': 'Potion of Future Power'},                 # name match
            {'guid': 1295247, 'name': 'Concentrated Silvermoon Health Potion'},  # healing, not combat
            {'guid': 6262, 'name': 'Healthstone'},
            {'guid': 2, 'name': 'Fireball'},
        ]}
        potions, defensives = analyzer.consumable_ids(casts)
        self.assertEqual(potions, [999001, 1236616])
        self.assertEqual(defensives, [6262, 1295247])


class TestSuggestions(unittest.TestCase):
    def test_tank_only_abilities_are_not_suggested(self):
        players = actors('Tank', 'B', 'C', 'D', 'E')
        details = {'playerDetails': {'tanks': [{'name': 'Tank', 'type': 'Warrior', 'icon': 'Warrior-Protection'}]}}
        a = analyze(players, [damage(1, CAUSTIC, 900), damage(2, AURA, 900, tick=True)], player_details=details)
        suggested = {s['id'] for s in analyzer.suggest_avoidable([a], set())}
        self.assertEqual(suggested, {AURA})


class TestMythicTrapGuides(unittest.TestCase):
    PAGE = ('<html><script id="__NEXT_DATA__" type="application/json">'
            '{"props": {"pageProps": {"boss": {"id": "ulatek", "raidID": "venomous-abyss", "bossPhases": ['
            '{"bossAbilitiesWithVideos": [{"id": "ulatekSerBit", "spellID": 1295905, "name": "Serpent\'s Bite",'
            ' "category": "Help soak", "subtitle": "Soak", "descriptionHTML": "<p>Soak it.</p>",'
            ' "associatedVideo": {"videoURL": "videos/venomous-abyss/ulatek/serpentsBite.mp4",'
            ' "items": [{"titleHTML": "<p>Everyone</p>", "textHTML": "<p>Soak the bitten players</p>"}]}},'
            '{"id": "ulatekDesTra", "spellID": 1305709, "name": "Desperate Trash", "associatedVideo":'
            ' {"videoURL": "videos/x.mp4", "items": []}}],'
            ' "bossAbilities": [{"id": "ulatekMotWra", "spellID": 1298367, "name": "Mother\'s Wrath",'
            ' "descriptionHTML": "<p>Tankbuster.</p>"}]}]}}}}</script></html>')

    def setUp(self):
        import asyncio
        from raidanalysis import guides

        async def fake_get(session, url):
            return self.PAGE
        original, guides._get = guides._get, fake_get
        self.addCleanup(setattr, guides, '_get', original)
        self.guides = asyncio.run(guides.fetch_boss_guide(None, 'https://www.mythictrap.com/en/venomous-abyss/ulatek'))

    def test_page_parsing(self):
        bite = next(g for g in self.guides if g['guide_id'] == 'ulatekSerBit')
        self.assertEqual(bite['spell_id'], 1295905)
        self.assertEqual(bite['tip'], 'Everyone: Soak the bitten players')
        self.assertEqual(bite['embed_url'],
                         'https://www.mythictrap.com/en/embed-ability/venomous-abyss/ulatek/ulatekSerBit')
        wrath = next(g for g in self.guides if g['guide_id'] == 'ulatekMotWra')
        self.assertIsNone(wrath['video_url'])
        self.assertEqual(wrath['description'], 'Tankbuster.')

    def test_matching_by_spell_then_name(self):
        from raidanalysis.guides import match_guide
        # Their typo'd name still matches through the spell ID.
        self.assertEqual(match_guide(self.guides, 1305709, 'Desperate Thrash')['guide_id'], 'ulatekDesTra')
        # Damage spell differs from the cast spell they list: fall back to the name.
        self.assertEqual(match_guide(self.guides, 1293146, "Serpent's Bite")['guide_id'], 'ulatekSerBit')
        self.assertIsNone(match_guide(self.guides, 42, 'Melee'))

    def test_auto_tags_from_categories(self):
        from raidanalysis.guides import EXPECTED, classify
        cases = {
            ('Dodge waves', 'Waves'): analyzer.TAG_AVOIDABLE,
            ('Dodge', 'Frontal'): analyzer.TAG_AVOIDABLE_NON_TANK,
            ('Move out', 'Tail AOE'): analyzer.TAG_AVOIDABLE_NON_TANK,
            ('Face away from raid', 'Tankbuster'): analyzer.TAG_AVOIDABLE_NON_TANK,
            ('Soak and dodge', 'Tank soak'): analyzer.TAG_AVOIDABLE_NON_TANK,
            ('Help soak', 'Soak'): EXPECTED,
            ('Use defensives', 'Tankbuster'): EXPECTED,
            ('Heal Through', 'Rot damage'): EXPECTED,
            ('Move away', 'Fall off damage'): EXPECTED,  # everyone takes some - not a mistake
            ('Swap tanks', 'Tank debuff'): EXPECTED,
            ('Spread', 'Spread'): None,                  # wording doesn't say - left to officers
        }
        for (category, subtitle), expected in cases.items():
            self.assertEqual(classify({'category': category, 'subtitle': subtitle}), expected, category)

    def test_raid_wide_abilities_are_never_auto_blamed(self):
        from raidanalysis.guides import auto_tags
        guides = [{'guide_id': 'x', 'spell_id': 7, 'name': 'Wave', 'category': 'Dodge', 'subtitle': 'Waves'}]
        self.assertEqual(auto_tags(guides, {7: {'name': 'Wave', 'share': 0.25}}), {7: analyzer.TAG_AVOIDABLE})
        self.assertEqual(auto_tags(guides, {7: {'name': 'Wave', 'share': 0.97}}), {})

    def test_slugs(self):
        from raidanalysis.guides import slugify
        self.assertEqual(slugify("Nek'zali the Soulcoiler"), 'nekzali-the-soulcoiler')
        self.assertEqual(slugify("Ula'tek"), 'ulatek')


if __name__ == '__main__':
    unittest.main()
