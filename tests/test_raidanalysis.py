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


def died(*name_times):
    return [{'name': n, 'timestamp': 1000 + t, 'killingBlow': {'name': 'Caustic Waves', 'guid': CAUSTIC}}
            for n, t in name_times]


class TestEarlyDeaths(unittest.TestCase):
    def test_only_the_first_four_deaths_count(self):
        names = 'ABCDEFGH'
        a = analyze(actors(*names), deaths=died(*((n, 10000 * (i + 1)) for i, n in enumerate(names))))
        self.assertEqual(a['wipe_at'], 40000)  # 4 of 8 dead
        self.assertEqual([d['early'] for d in a['deaths']], [True] * 4 + [False] * 4)
        self.assertEqual(analyzer.death_note(a['deaths'][4]), 'death #5 — not counted')

        board = {r['name']: r for r in analyzer.scoreboard([dict(a, _duration=600000)], {})}
        self.assertEqual((board['A']['deaths'], board['A']['first_deaths']), (1, 1))
        self.assertEqual(board['E']['deaths'], 0)

    def test_mass_deaths_dont_count(self):
        # A dies alone; B, C and D die within 3s of each other (an AoE) - only A made a mistake.
        a = analyze(actors(*'ABCDEFGH'), deaths=died(('A', 5000), ('B', 20000), ('C', 21000), ('D', 22500)))
        self.assertEqual([(d['name'], d['early'], d['mass']) for d in a['deaths']],
                         [('A', True, False), ('B', False, True), ('C', False, True), ('D', False, True)])
        self.assertEqual(analyzer.death_note(a['deaths'][1]), 'part of a mass death')

        killers = analyzer.killers([a])
        self.assertEqual((killers[0]['count'], killers[0]['mistakes'], killers[0]['mass']), (4, 1, 3))
        self.assertEqual(killers[0]['players'], {'A': 1})

        out = {p['name']: p for p in analyzer.player_report(
            [{'number': 1, 'kill': False, 'analysis': dict(a, _duration=600000)}], {})}
        self.assertEqual(out['A']['deaths'], 1)
        self.assertEqual(out['B']['deaths'], 0)
        self.assertFalse(out['B']['per_pull'][0]['mistake'])
        self.assertIsNotNone(out['B']['per_pull'][0]['died_at'])  # still dead for time-alive purposes

    def test_annotating_stored_analyses(self):
        stored = {'deaths': [{'name': 'B', 't': 9000}, {'name': 'A', 't': 1000}]}  # pre-v5, unsorted
        deaths = analyzer.annotate_deaths(stored)['deaths']
        self.assertEqual([(d['name'], d['order'], d['early']) for d in deaths], [('A', 1, True), ('B', 2, True)])

    def test_kills_have_no_wipe_moment(self):
        players = actors('A', 'B')
        deaths = [{'name': 'A', 'timestamp': 1100}, {'name': 'B', 'timestamp': 1200}]
        self.assertIsNone(analyze(players, deaths=deaths, kill=True)['wipe_at'])


class TestKillingBlow(unittest.TestCase):
    def test_missing_killing_blow_is_inferred(self):
        players = actors('A', 'B')
        deaths = [
            {'name': 'A', 'timestamp': 1100, 'killingBlow': {'name': 'Caustic Waves', 'guid': CAUSTIC}},
            # No killing blow: last damaging hit wins over earlier 0-damage events.
            {'name': 'B', 'timestamp': 1200, 'events': [
                {'type': 'damage', 'amount': 0, 'ability': {'name': 'Rune', 'guid': 5}},
                {'type': 'damage', 'amount': 900, 'ability': {'name': 'Arcane Missiles', 'guid': 6}}],
             'damage': {'abilities': [{'name': "Death's Whisper", 'guid': 7, 'total': 1}]}},
        ]
        a = analyze(players, deaths=deaths)
        self.assertEqual([(d['ability'], d['likely']) for d in a['deaths']],
                         [('Caustic Waves', False), ('Arcane Missiles', True)])

    def test_falls_back_to_biggest_damage_source(self):
        players = actors('A')
        deaths = [{'name': 'A', 'timestamp': 1100, 'events': [],
                   'damage': {'abilities': [{'name': "Death's Whisper", 'guid': 7, 'total': 1}]}}]
        self.assertEqual(analyze(players, deaths=deaths)['deaths'][0]['ability'], "Death's Whisper")


class TestMergePulls(unittest.TestCase):
    def test_overall_sums_pulls(self):
        players = actors('A', 'B')
        p1 = analyze(players, [damage(1, CAUSTIC, 500), damage(2, CAUSTIC, 500)])
        p2 = analyze(players, [damage(1, CAUSTIC, 500)])
        merged = analyzer.merge_pulls([p1, p2])
        caustic = next(a for a in merged['abilities'] if a['id'] == CAUSTIC)
        self.assertEqual(caustic['pulls'], 2)
        self.assertEqual(analyzer.mistake_counts(caustic), {'A': 2, 'B': 1})


class TestPlayerReport(unittest.TestCase):
    def report(self, pulls, tags):
        return {p['name']: p for p in analyzer.player_report(
            [{'number': i, 'kill': False, 'analysis': dict(a, _duration=600000)} for i, a in enumerate(pulls, 1)],
            tags)}

    def test_scores_and_feedback(self):
        players = actors('Clean', 'Sloppy', 'C', 'D')
        pulls = [analyze(players, [damage(2, CAUSTIC, 500, t=1000 + i) for i in range(4)]
                         + [damage(3, CAUSTIC, 500)]) for _ in range(3)]
        out = self.report(pulls, {CAUSTIC: analyzer.TAG_AVOIDABLE})
        self.assertEqual(out['Clean']['scores']['mechanics'], 100.0)
        self.assertLess(out['Sloppy']['scores']['mechanics'], out['C']['scores']['mechanics'])
        self.assertGreater(out['Clean']['score'], out['Sloppy']['score'])
        sloppy_notes = [n['text'] for n in out['Sloppy']['feedback'] if n['tone'] == 'bad']
        self.assertTrue(any('Hit by Ability 1292403 12 times' in t for t in sloppy_notes), sloppy_notes)
        self.assertIn('Never hit by an avoidable mechanic', [n['text'] for n in out['Clean']['feedback']])

    def test_breakdown_components(self):
        players = actors('Clean', 'Sloppy', 'C', 'D')
        pulls = [analyze(players, [damage(2, CAUSTIC, 500, t=1000 + i) for i in range(4)]) for _ in range(3)]
        for a in pulls:  # Clean interrupts something every pull - a bonus, not part of the score
            a['interrupts'] = [{'id': 9, 'name': 'Bolt', 'begun': 1, 'count': 1, 'by': {'Clean': 1}}]
        out = self.report(pulls, {CAUSTIC: analyzer.TAG_AVOIDABLE})
        clean = {c['key'] if c['key'] != 'mechanic' else c['label']: c for c in out['Clean']['components']}
        self.assertEqual(clean['Ability 1292403']['value'], 100.0)
        self.assertTrue(clean['interrupts']['bonus'])
        self.assertEqual(out['Clean']['contribution'], 100)
        scored = [c for c in out['Clean']['components'] if not c['bonus']]
        expected = round(sum(c['value'] * c['weight'] for c in scored) / sum(c['weight'] for c in scored))
        self.assertEqual(out['Clean']['score'], expected)  # interrupts don't move the score
        # Notes quote the same raid average as the breakdown
        sloppy_mech = next(c for c in out['Sloppy']['components'] if c['key'] == 'mechanic')
        note = next(n['text'] for n in out['Sloppy']['feedback'] if 'Ability 1292403' in n['text'])
        self.assertIn(f"{sloppy_mech['ability']['raid_avg']:.1f}", sloppy_mech['detail'])
        self.assertTrue(note)

    def test_tanks_exempt_from_non_tank_mechanics(self):
        players = actors('Tank', 'Dps')
        details = {'playerDetails': {'tanks': [{'name': 'Tank', 'type': 'Warrior', 'icon': 'Warrior-Protection'}]}}
        pulls = [analyze(players, [damage(1, THRASH, 900), damage(1, THRASH, 900)], player_details=details)]
        out = self.report(pulls, {THRASH: analyzer.TAG_AVOIDABLE_NON_TANK})
        self.assertEqual(out['Tank']['avoidable_hits'], 0)

    def test_no_tags_drops_mechanics_score(self):
        out = self.report([analyze(actors('A'))], {})
        self.assertNotIn('mechanics', out['A']['scores'])


class TestWipeReasons(unittest.TestCase):
    def pull(self, deaths, roles=None, wipe_at=1):
        roles = roles or {}
        players = [{'name': n, 'role': roles.get(n, 'dps')} for n in 'ABCDEFGHIJ']
        return {'players': players, 'wipe_at': wipe_at,
                'deaths': [{'t': t, 'name': n, 'ability': a, 'ability_id': 1} for t, n, a in deaths]}

    def test_failed_mechanic_with_healthy_raid(self):
        deaths = [(300000 + i * 500, n, 'Mother\'s Wrath') for i, n in enumerate('ABCDEF')]
        r = analyzer.wipe_reason(self.pull(deaths), False, 310000)
        self.assertEqual(r['code'], 'mass')
        self.assertIn("Mother's Wrath", r['label'])

    def test_tank_death_then_wipe(self):
        deaths = [(280000, 'A', 'Stone Venom')] + [(300000 + i * 500, n, 'Melee') for i, n in enumerate('BCDEF')]
        r = analyzer.wipe_reason(self.pull(deaths, roles={'A': 'tank'}), False, 310000)
        self.assertEqual(r['code'], 'tank')
        self.assertTrue(r['label'].startswith('Tank died (A)'))

    def test_mixed_burst_from_healthy_raid_is_a_called_wipe(self):
        deaths = [(300000 + i * 400, n, f'Ability {i}') for i, n in enumerate('ABCDEF')]
        self.assertEqual(analyzer.wipe_reason(self.pull(deaths), False, 310000)['code'], 'called')

    def test_early_reset_and_kills(self):
        self.assertEqual(analyzer.wipe_reason(self.pull([], wipe_at=None), False, 15000)['code'], 'reset')
        self.assertIsNone(analyzer.wipe_reason(self.pull([]), True, 300000))

    def test_phase_progress(self):
        pulls = [{'phases': [{'id': 1, 'start': 0}, {'id': 2, 'start': 100000}], 'duration': 200000},
                 {'phases': [{'id': 1, 'start': 0}], 'duration': 80000}]
        out = {p['id']: p for p in analyzer.phase_progress(pulls, {'2': {'name': 'Stage Two'}})}
        self.assertEqual((out[1]['reached'], out[2]['reached'], out[2]['name']), (2, 1, 'Stage Two'))
        self.assertEqual(out[2]['avg_time'], 100000)

    def test_revisited_phases_count_once_per_pull(self):
        # Council fights bounce between "phases" (active bosses) within one pull.
        pulls = [{'phases': [{'id': 1, 'start': 0}, {'id': 2, 'start': 10000}, {'id': 1, 'start': 20000},
                             {'id': 2, 'start': 30000}], 'duration': 40000}]
        out = {p['id']: p for p in analyzer.phase_progress(pulls, {})}
        self.assertEqual((out[1]['reached'], out[2]['reached']), (1, 1))
        self.assertEqual((out[2]['avg_entry'], out[2]['avg_time']), (10000, 20000))


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


class TestTrendsAcrossAlts(unittest.TestCase):
    def test_characters_of_one_person_are_one_trend(self):
        from raidanalysis.web.players import player_history
        row = lambda name, score, pulls=5: {'name': name, 'score': score, 'pulls': pulls}
        nights = [
            {'label': '24 Sep', 'code': 'A', 'players': [row('Boopsboops', 60), row('Solo', 70)]},
            {'label': '29 Sep', 'code': 'B', 'players': [row('Boopsproops', 80, 9), row('Boopsboops', 50, 2)]},
        ]
        owners = {'boopsboops': {'key': 'd1', 'display': 'Boops'}, 'boopsproops': {'key': 'd1', 'display': 'Boops'}}
        history = player_history(nights, owners)
        boops = history['d1']
        self.assertEqual([r['name'] for _, _, r in boops['nights']], ['Boopsboops', 'Boopsproops'])
        self.assertEqual(boops['characters'], ['Boopsboops', 'Boopsproops'])
        self.assertEqual(len(history['Solo']['nights']), 1)  # unknown owner: tracked per character


class TestCharacterOwners(unittest.TestCase):
    def test_shared_battlenet_account_split_by_signups(self):
        from raidanalysis.people import own_characters, resolve_owners
        # Gastronomic's Battle.net account links both characters; Naautilus signs up with his own Discord.
        owners = resolve_owners(signups=[('Gastronomic', 'G', 4), ('Naautilus', 'N', 5)],
                                linked=[('Gastronomic', 'G'), ('Naautilus', 'G')])
        self.assertEqual(owners['naautilus']['discord_id'], 'N')
        self.assertEqual(own_characters('G', ['Gastronomic', 'Naautilus'], owners), {'gastronomic'})
        self.assertEqual(own_characters('N', [], owners, signed_with=['Naautilus']), {'naautilus'})

    def test_alt_without_signups_follows_battlenet_link(self):
        from raidanalysis.people import resolve_owners
        owners = resolve_owners(signups=[('Boopsboops', 'B', 3)],
                                linked=[('Boopsboops', 'B'), ('Boopsproops', 'B')], displays={'B': 'Boops'})
        self.assertEqual(owners['boopsproops']['key'], owners['boopsboops']['key'])
        self.assertEqual(owners['boopsproops']['display'], 'Boops')


class TestReadyCheck(unittest.TestCase):
    def test_prepull_parsing_and_enchant_expectations(self):
        players = actors('A', 'B', 'C')
        gear = lambda chest_enchant: [{'id': 1, 'itemLevel': 320, 'setID': 9, 'permanentEnchant': 1},  # head
                                      {'id': 2, 'itemLevel': 320}, {'id': 3, 'itemLevel': 320},
                                      {}, {'id': 5, 'itemLevel': 330, 'setID': 9,
                                           'permanentEnchant': 7 if chest_enchant else 0, 'gems': [{'id': 1}]}]
        auras = [{'name': 'Flask of the Shattered Sun'}, {'name': 'Hearty Well Fed'}, {'name': 'Arcane Intellect'}]
        events = [{'type': 'combatantinfo', 'sourceID': 1, 'auras': auras, 'gear': gear(True)},
                  {'type': 'combatantinfo', 'sourceID': 2, 'auras': auras[:1], 'gear': gear(True)},
                  {'type': 'combatantinfo', 'sourceID': 3, 'auras': [], 'gear': gear(False)}]
        a = analyzer.analyze_fight(fight(players), players, {'damageTaken': damage_table(), 'deaths': {'entries': []},
                                   'interrupts': {'entries': []}, 'dispels': {'entries': []}, 'playerDetails': {}},
                                   [], [], set(), set(), combatant_events=events)
        pre = a['prepull']
        self.assertEqual((pre['A']['flask'], pre['A']['food'], pre['A']['tier'], pre['A']['gems']),
                         ('Flask of the Shattered Sun', 'Hearty Well Fed', 2, 1))
        self.assertIsNone(pre['B']['food'])
        self.assertEqual(pre['A']['buffs'], ['Arcane Intellect'])
        expected = analyzer.expected_enchant_slots(pre.values())
        self.assertEqual(expected, {'0', '4'})  # head + chest: most of the raid enchants them
        report = {r['name']: r for r in analyzer.player_report(
            [{'number': 1, 'kill': False, 'analysis': dict(a, _duration=600000)}], {})}
        self.assertEqual(report['C']['missing_enchants'], ['Chest'])
        self.assertIn('Pulled without flask or food buff', [n['text'] for n in report['C']['feedback']])


class TestProgstats(unittest.TestCase):
    def test_bins_are_folded_and_quantiles_estimated(self):
        from raidanalysis import progstats
        payload = {'data': {
            'encounterStatSummaryV2': {'killCount': 4},
            'encounterStatOverviewV2': {'metricType': ['PULL_COUNT', 'PULL_COUNT', 'START_ILVL', 'PULL_COUNT'],
                                        'binStart': [100, 100, 320, 200], 'binEnd': [150, 150, 321, 250],
                                        'count': [1, 1, 9, 2]}}}
        stats = progstats.parse(payload)
        self.assertEqual(stats['bins'], [(100, 150, 2), (200, 250, 2)])  # two days of the same bin folded
        self.assertEqual(stats['median'], 150)
        self.assertEqual(progstats.share_needing_more(stats['bins'], 125), 0.75)
        self.assertIsNone(progstats.parse({'data': {'encounterStatSummaryV2': {'killCount': 0}}}))


class TestConsumableUses(unittest.TestCase):
    def test_potions_prepots_and_healthstones(self):
        players = actors('A', 'B')
        casts = {'entries': [{'guid': 1236616, 'name': "Light's Potential", 'abilityIcon': 'pot.jpg'},
                             {'guid': 6262, 'name': 'Healthstone', 'abilityIcon': 'hs.jpg'}]}
        tables = {'damageTaken': damage_table(), 'deaths': {'entries': []}, 'interrupts': {'entries': []},
                  'dispels': {'entries': []}, 'playerDetails': {}, 'casts': casts}
        start = 1000
        cast = lambda src, guid, t: {'type': 'cast', 'sourceID': src, 'abilityGameID': guid, 'timestamp': start + t}
        buff = lambda kind, tgt, t: {'type': kind, 'targetID': tgt, 'abilityGameID': 1236616, 'timestamp': start + t}
        heal = lambda src, t, amount: {'type': 'heal', 'sourceID': src, 'abilityGameID': 6262,
                                       'timestamp': start + t, 'amount': amount}
        a = analyzer.analyze_fight(
            fight(players), players, tables, [],
            [cast(1, 1236616, 120000), cast(2, 6262, 200000)], {1236616}, {6262},
            buff_events=[buff('removebuff', 2, 25000),            # B pre-potted
                         buff('applybuff', 1, 120200), buff('removebuff', 1, 150200)],
            heal_events=[heal(2, 200000, 300000), heal(2, 200500, 50000)])  # one healthstone, two heal events
        uses = {(u['name'], u['kind'], u.get('prepot')): u for u in a['consumables']}
        self.assertEqual(uses[('A', 'potion', False)]['end'] - uses[('A', 'potion', False)]['t'], 30200)
        self.assertEqual(uses[('B', 'potion', True)]['t'], 0)
        self.assertEqual(uses[('B', 'defensive', None)]['healing'], 350000)
        self.assertEqual(sum(1 for u in a['consumables'] if u['kind'] == 'defensive'), 1)

    def test_cooldowns_by_name_with_external_targets(self):
        from raidanalysis import cooldowns
        players = actors('Dk', 'Priest', 'Tank')
        casts = {'entries': [{'guid': 51052, 'name': 'Anti-Magic Zone', 'abilityIcon': 'amz.jpg'},
                             {'guid': 33206, 'name': 'Pain Suppression', 'abilityIcon': 'ps.jpg'},
                             {'guid': 585, 'name': 'Smite'}]}
        meta = cooldowns.cooldown_meta(casts)
        self.assertEqual({g: m['category'] for g, m in meta.items()}, {51052: 'raid', 33206: 'external'})
        tables = {'damageTaken': damage_table(), 'deaths': {'entries': []}, 'interrupts': {'entries': []},
                  'dispels': {'entries': []}, 'playerDetails': {}, 'casts': casts}
        events = [{'type': 'cast', 'sourceID': 1, 'targetID': 1, 'abilityGameID': 51052, 'timestamp': 61000},
                  {'type': 'cast', 'sourceID': 2, 'targetID': 3, 'abilityGameID': 33206, 'timestamp': 91000},
                  {'type': 'cast', 'sourceID': 2, 'targetID': 3, 'abilityGameID': 585, 'timestamp': 92000}]
        a = analyzer.analyze_fight(fight(players), players, tables, [], events, set(), set(), cooldown_meta=meta)
        self.assertEqual([(c['t'], c['name'], c['ability'], c['target']) for c in a['cooldowns']],
                         [(60000, 'Dk', 'Anti-Magic Zone', None), (90000, 'Priest', 'Pain Suppression', 'Tank')])


class TestTopPlayerComparison(unittest.TestCase):
    SPELLS = {1: {'name': 'Metamorphosis', 'meta': 'Instant · 2 min cooldown'},
              2: {'name': 'Essence Break', 'meta': 'Instant · 40 sec cooldown'},
              3: {'name': 'Blur', 'meta': 'Instant · 1 min cooldown'},
              4: {'name': 'Fel Rush', 'meta': '2 charges · 10 sec cooldown'},
              5: {'name': "Light's Potential", 'meta': 'Item effect · Instant · 5 min cooldown',
                  'description': 'Drink to increase your primary stat by 346 for 30 sec.'},
              6: {'name': 'Potion of Recklessness', 'meta': 'Item effect · Instant · 5 min cooldown'},
              7: {'name': 'Cursed Trinket', 'meta': 'Item effect · Instant · 2 min cooldown'}}

    def top(self, offset=0):
        # Phase 2 starts at 150 s (+ offset): Metamorphosis at the pull and 10 s into phase 2.
        phase2 = 150000 + offset
        return {'duration': 300000 + offset, 'phases': [{'id': 1, 'start': 0}, {'id': 2, 'start': phase2}],
                'casts': [[1000, 1], [phase2 + 10000, 1], [5000, 2], [200000, 5], [60000, 7]]}

    def test_cooldown_kinds(self):
        from raidanalysis import benchmarks
        kinds = {sid: benchmarks.category(sid, info) for sid, info in self.SPELLS.items()}
        self.assertEqual(kinds, {1: 'throughput', 2: 'throughput', 3: 'personal', 4: None, 5: 'potion',
                                 6: 'potion', 7: 'trinket'})

    def test_lining_up_phase_by_phase(self):
        from raidanalysis import benchmarks
        top = [self.top(o) for o in (0, 20000, -15000, 30000, 5000)]
        # Our phase 2 starts 60 s later than theirs: Meta 10 s into it is still "in line".
        ours = {'number': 1, 'duration': 360000, 'phases': [{'id': 1, 'start': 0}, {'id': 2, 'start': 210000}],
                'casts': [[2000, 1], [220000, 1], [100000, 6]], 'cast_ids': {1, 2, 3, 5, 6, 7}}
        rows = {r['name']: r for r in benchmarks.compare([ours], top, self.SPELLS)}
        meta = rows['Metamorphosis']
        self.assertEqual([w['segment'] for w in meta['windows']], [(0, 1), (1, 2)])
        self.assertEqual((meta['hits'], meta['considered'], meta['verdict']), (2, 2, 'good'))
        self.assertEqual(rows['Essence Break']['verdict'], 'missing')
        # Any combat potion counts, and a trinket we don't have isn't a miss.
        self.assertEqual(rows['Combat potion']['ours_casts'], 1)
        self.assertEqual(rows['Cursed Trinket']['verdict'], 'not_equipped')
        self.assertEqual(rows['Cursed Trinket']['weak'], [])
        notes = benchmarks.notes(list(rows.values()), 'Havoc Demon Hunters')
        self.assertTrue(any('Essence Break' in n['text'] and n['tone'] == 'bad' for n in notes))
        trinket = [n for n in notes if 'Cursed Trinket' in n['text']]
        self.assertEqual([n['tone'] for n in trinket], ['info'])  # not a missed cast
        self.assertIn('worth getting', trinket[0]['text'])  # loot luck: a tip, not a reproach

    def test_off_timing_and_unreached_phases(self):
        from raidanalysis import benchmarks
        top = [self.top() for _ in range(5)]
        # Meta 60 s late at the pull, and the pull wiped before phase 2: one moment, missed.
        ours = {'number': 1, 'duration': 140000, 'phases': [{'id': 1, 'start': 0}],
                'casts': [[61000, 1], [5000, 2]], 'cast_ids': {1, 2, 3, 5, 6, 7}}
        meta = next(r for r in benchmarks.compare([ours], top, self.SPELLS) if r['name'] == 'Metamorphosis')
        self.assertEqual((meta['hits'], meta['considered']), (0, 1))

    def test_old_analyses_dont_claim_never_used(self):
        from raidanalysis import benchmarks
        top = [self.top() for _ in range(5)]
        # Analyzed before every cast was kept: only tracked cooldowns (Blur) + consumables recorded.
        old = {'number': 1, 'duration': 300000, 'phases': [{'id': 1, 'start': 0}], 'casts': [[90000, 3]],
               'cast_ids': None, 'tracked': True}
        for t in top:
            t['casts'].append([90000, 3])
        rows = {r['name']: r for r in benchmarks.compare([old], top, self.SPELLS)}
        self.assertFalse(rows['Metamorphosis']['known'])
        self.assertIsNone(rows['Metamorphosis']['verdict'])  # not "missing"
        self.assertTrue(rows['Blur']['known'])


class TestSpellTooltips(unittest.TestCase):
    def test_wowhead_tooltip_to_plain_text(self):
        from raidanalysis import spells
        info = spells.parse({'name': "Light's Potential", 'icon': 'potion', 'tooltip': (
            '<table><tr><td><table width="100%"><tr><td><a class="whtt-name" href="/spell=1"><b>Light\'s Potential</b>'
            '</a></td><th><b class="q0"><br>Level <!--lvl-->90</b></th></tr></table><table width="100%"><tr><td>Instant'
            '</td><th><!--cooldownText-->5 min cooldown<!--cooldownText--></th></tr></table></td></tr></table><table>'
            '<tr><td><div class="q">Absorbs up to [Total Health * 30 / 100] damage &amp; lasts <!--pts1-->30 sec.'
            '<br />Stacks.</div></td></tr></table>')})
        self.assertEqual(info['meta'], 'Instant · 5 min cooldown')
        self.assertEqual(info['description'], 'Absorbs up to X damage & lasts 30 sec.\nStacks.')


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


class TestRateLimitPause(unittest.TestCase):
    """After a 429 the sync leaves WCL alone until the budget resets (needs psycopg2 to import sync)."""

    def test_pauses_after_429(self):
        import asyncio
        from unittest import mock
        try:
            from raidanalysis import sync, wcl
        except ImportError as e:
            self.skipTest(f'sync needs {e.name}')
        calls = []

        async def rate_limit(session):
            calls.append('budget')
            return {'pointsSpentThisHour': 100, 'limitPerHour': 3600, 'pointsResetIn': 1200}

        async def reports(session, guild_id, limit=10):
            calls.append('reports')
            raise wcl.WCLRateLimited('WCL rate limit reached - try again later')

        async def nothing(*a, **k):
            return 0

        with mock.patch.object(wcl, 'get_rate_limit', rate_limit), \
                mock.patch.object(wcl, 'list_guild_reports', reports), \
                mock.patch('raidanalysis.guides.scan_missing', nothing), \
                mock.patch('raidanalysis.spells.fill_missing', nothing), \
                mock.patch.dict('sys.modules', {'wcl_api': mock.Mock(WCL_GUILD_ID=1)}):
            sync.status['paused_until'] = None
            asyncio.run(sync.sync_guild(limit=1))
            self.assertTrue(sync._paused())
            self.assertIn('pausing WCL requests until', sync.status['last_error'])
            # ~20 min (WCL's reset timer), not the 15 min fallback
            self.assertGreater(sync.status['paused_until'] - __import__('time').time(), 1100)
            calls.clear()
            self.assertEqual(asyncio.run(sync.sync_guild(limit=1)), 0)
            self.assertEqual(calls, [])  # didn't touch WCL at all
            sync.status['paused_until'] = None


class TestTopPlayersSameSpec(unittest.TestCase):
    """Only ever compare a spec with itself, even if WCL's rankings answer with other specs."""

    def test_other_specs_are_dropped(self):
        import asyncio
        from unittest import mock
        from raidanalysis import benchmarks, wcl
        rankings = [{'name': 'Havocguy', 'spec': 'Havoc', 'amount': 9, 'report': {'code': 'A', 'fightID': 1}},
                    {'name': 'Devo1', 'spec': 'Devourer', 'amount': 8, 'report': {'code': 'B', 'fightID': 2}},
                    {'name': 'Sneaky', 'amount': 7, 'report': {'code': 'C', 'fightID': 3}},  # no spec in ranking
                    {'name': 'Devo2', 'spec': 'Devourer', 'amount': 6, 'report': {'code': 'D', 'fightID': 4}}]

        async def get_rankings(session, *args, **kwargs):
            return rankings

        async def get_fight(session, code, fight_id, name):
            spec = 'Havoc' if name == 'Sneaky' else 'Devourer'  # the fight itself says what they played
            return {'start': 0, 'end': 300000, 'phases': [], 'spec': spec,
                    'casts': [{'type': 'cast', 'abilityGameID': 1, 'timestamp': 1000}]}

        with mock.patch.object(wcl, 'get_character_rankings', get_rankings), \
                mock.patch.object(wcl, 'get_player_fight', get_fight):
            top = asyncio.run(benchmarks.fetch_top_players(None, 1, 4, 'DemonHunter', 'Devourer', 'dps'))
        self.assertEqual([(p['name'], p['spec']) for p in top], [('Devo1', 'Devourer'), ('Devo2', 'Devourer')])
        self.assertEqual([p['rank'] for p in top], [1, 2])

    def test_spec_from_fight_details(self):
        from raidanalysis import wcl
        details = {'data': {'playerDetails': {'dps': [{'name': 'X', 'icon': 'DemonHunter-Devourer'}],
                                              'healers': [{'name': 'Y', 'specs': [{'spec': 'Mistweaver'}]}]}}}
        self.assertEqual(wcl._spec_in_details(details, 'X'), 'Devourer')
        self.assertEqual(wcl._spec_in_details(details, 'Y'), 'Mistweaver')
        self.assertIsNone(wcl._spec_in_details(details, 'Z'))


class TestFullBudget(unittest.TestCase):
    """An admin run can go past the usual 70% share of the hour's WCL points (needs psycopg2)."""

    def test_full_budget_goes_past_seventy_percent(self):
        import asyncio
        from unittest import mock
        try:
            from raidanalysis import sync, wcl
        except ImportError as e:
            self.skipTest(f'sync needs {e.name}')
        reached = []

        async def rate_limit(session):
            return {'pointsSpentThisHour': 2529, 'limitPerHour': 3600, 'pointsResetIn': 1200}

        async def reports(session, guild_id, limit=10):
            reached.append('reports')
            return []

        async def nothing(*a, **k):
            return 0

        with mock.patch.object(wcl, 'get_rate_limit', rate_limit), \
                mock.patch.object(wcl, 'list_guild_reports', reports), \
                mock.patch.object(sync, '_event_codes_to_sync', lambda queued: []), \
                mock.patch('raidanalysis.benchmarks.refresh', nothing), \
                mock.patch('raidanalysis.guides.scan_missing', nothing), \
                mock.patch('raidanalysis.spells.fill_missing', nothing), \
                mock.patch.dict('sys.modules', {'wcl_api': mock.Mock(WCL_GUILD_ID=1)}):
            sync.status['paused_until'] = None
            asyncio.run(sync.sync_guild(limit=1))
            self.assertEqual(reached, [])  # 2529/3600 > 70%: stopped before touching reports
            self.assertIn('Use the full WCL budget', sync.status['last_error'])
            asyncio.run(sync.sync_guild(limit=1, full_budget=True))
            self.assertEqual(reached, ['reports'])
            self.assertEqual(sync._share, sync.WCL_BUDGET_SHARE)  # back to normal after the run


class TestSpecSwap(unittest.TestCase):
    """Someone who swaps spec mid-night counts as the spec they played most - not their first pull's."""

    def test_majority_spec_and_same_spec_pulls(self):
        from raidanalysis import analyzer, benchmarks

        def pull(spec, fight_id):
            players = [{'name': 'Naautilus', 'class': 'DemonHunter', 'spec': spec, 'role': 'dps'}]
            return {'fight_id': fight_id, 'kill': False, 'start_ms': 0, 'end_ms': 300000, 'phases': [],
                    'analysis': {'players': players, 'casts': {'Naautilus': [[1000, fight_id]]}, 'cast_ids': [fight_id]}}
        pulls = [pull('Havoc', 1), pull('Devourer', 2), pull('Devourer', 3)]
        report = analyzer.player_report([{'number': i, 'kill': False, 'analysis': dict(p['analysis'], _duration=300000)}
                                         for i, p in enumerate(pulls, 1)], {})
        me = next(r for r in report if r['name'] == 'Naautilus')
        self.assertEqual(me['spec'], 'Devourer')
        self.assertEqual(me['spec_pulls'], {'Havoc': 1, 'Devourer': 2})
        self.assertEqual(analyzer.main_spec([{'spec': 'Havoc'}, {'spec': 'Devourer'}]), 'Devourer')  # tie: latest
        numbered = list(enumerate(pulls, 1))
        self.assertEqual(benchmarks._main_spec_player(numbered, 'Naautilus')['spec'], 'Devourer')
        self.assertEqual([p['fight_id'] for p in benchmarks.our_pulls(numbered, 'Naautilus', spec='Devourer')], [2, 3])


class TestTimingMargin(unittest.TestCase):
    """12 s early on a 15 s buff the top players press within a second of each other is not 'in line'."""

    def test_early_ascendance_is_off(self):
        from raidanalysis import benchmarks
        spells = {9: {'name': 'Ascendance', 'meta': 'Instant · 3 min cooldown',
                      'description': 'Transform into a Flame Ascendant for 15 sec.'}}
        top = [{'duration': 300000, 'phases': [], 'casts': [[136000 + jitter, 9]]} for jitter in (-800, 0, 300, 600, 900)]
        haldrik = {'number': 1, 'duration': 300000, 'phases': [], 'casts': [[124000, 9]], 'cast_ids': {9}}
        on_time = {'number': 2, 'duration': 300000, 'phases': [], 'casts': [[139000, 9]], 'cast_ids': {9}}
        row = benchmarks.compare([haldrik], top, spells)[0]
        self.assertLess(row['windows'][0]['tolerance'], 7500)      # at most half the 15 s buff
        self.assertEqual((row['hits'], row['considered']), (0, 1))
        self.assertEqual(benchmarks.timing_text(row['offset']), '12 s early')
        row = benchmarks.compare([on_time], top, spells)[0]
        self.assertEqual((row['hits'], row['considered']), (1, 1))
        self.assertEqual(benchmarks.timing_text(row['offset']), '3 s late')


class TestWeakMoments(unittest.TestCase):
    """Mostly right but missing one big moment: not a plain 'In line', and the moment is named."""

    def test_mostly_in_line_names_the_missed_moment(self):
        from raidanalysis import benchmarks
        spells = {7: {'name': 'Essence Break', 'meta': 'Instant · 40 sec cooldown',
                      'description': 'Slash all enemies, increasing damage taken by 80% for 4 sec.'}}
        top = [{'duration': 300000, 'phases': [], 'casts': [[30000, 7], [150000, 7], [270000, 7]]} for _ in range(5)]
        pulls = []
        for n in range(4):
            middle = 150000 if n == 0 else 141000  # 9 s early on the middle moment in 3 of 4 pulls
            pulls.append({'number': n + 1, 'duration': 300000, 'phases': [], 'cast_ids': {7},
                          'casts': [[30000, 7], [middle, 7], [270000, 7]]})
        row = benchmarks.compare(pulls, top, spells)[0]
        self.assertEqual((row['hits'], row['considered']), (9, 12))
        self.assertEqual(row['verdict'], 'mostly')
        self.assertEqual(benchmarks.weak_text(row['weak']), '2:30 usually 9 s early')
        note = benchmarks.notes([row], 'Havoc Demon Hunters')[0]
        self.assertEqual(note['tone'], 'bad')
        self.assertEqual(note['text'], 'Essence Break: mostly in line (75%) - except 2:30, usually 9 s early')


class TestFrequentCooldownTiming(unittest.TestCase):
    """A cooldown pressed often (Essence Break ~1.6/min) is still judged on timing, not just how often."""

    def test_often_pressed_but_off_beat_is_not_in_line(self):
        from raidanalysis import benchmarks
        spells = {7: {'name': 'Essence Break', 'meta': 'Instant · 40 sec cooldown',
                      'description': 'Slash all enemies, increasing damage taken by 80% for 4 sec.'}}
        moments = list(range(10000, 290000, 40000))  # 7 casts in 5 min: 1.4 / min
        top = [{'duration': 300000, 'phases': [], 'casts': [[t, 7] for t in moments]} for _ in range(5)]
        off_beat = {'number': 1, 'duration': 300000, 'phases': [], 'cast_ids': {7},
                    'casts': [[t + 15000, 7] for t in moments]}  # same count, always 15 s late
        row = benchmarks.compare([off_beat], top, spells)[0]
        self.assertGreater(row['top_per_min'], 1.2)
        self.assertEqual(row['hits'], 0)
        self.assertEqual(row['verdict'], 'off')
        self.assertEqual(benchmarks.timing_text(row['offset']), '15 s late')


class TestNeverCastVsNotFetched(unittest.TestCase):
    """Shiv that nobody cast is a real 'never used'; Shiv that was cast but not fetched needs a re-analyze."""

    def test_real_zero_vs_unknown(self):
        from raidanalysis import benchmarks
        spells = {5938: {'name': 'Shiv', 'meta': 'Instant · 30 sec cooldown'},
                  1: {'name': 'Deathmark', 'meta': 'Instant · 2 min cooldown'}}
        top = [{'duration': 300000, 'phases': [], 'casts': [[30000, 5938], [40000, 1]]} for _ in range(5)]
        base = {'number': 1, 'duration': 300000, 'phases': [], 'casts': [[41000, 1]], 'cast_ids': {1}}
        not_talented = dict(base, casts_seen={1, 77})        # no Shiv anywhere in the log
        not_fetched = dict(base, casts_seen={1, 77, 5938})   # Shiv was cast, we just didn't keep it
        shiv = lambda pull: next(r for r in benchmarks.compare([pull], top, spells) if r['name'] == 'Shiv')
        self.assertEqual((shiv(not_talented)['known'], shiv(not_talented)['verdict']), (True, 'missing'))
        self.assertEqual((shiv(not_fetched)['known'], shiv(not_fetched)['verdict']), (False, None))


class TestDisciplineRamp(unittest.TestCase):
    """Evangelism / Ultimate Penitence are a Disc Priest's own cooldowns, not raid assignments."""

    def test_judged_as_major_cooldowns(self):
        from raidanalysis import benchmarks
        evangelism = {'name': 'Evangelism', 'meta': 'Instant · 1.5 min cooldown'}
        penitence = {'name': 'Ultimate Penitence', 'meta': '6 sec cast · 4 min cooldown'}
        self.assertEqual(benchmarks.category(246287, evangelism), benchmarks.THROUGHPUT)
        self.assertEqual(benchmarks.category(421453, penitence), benchmarks.THROUGHPUT)
        self.assertEqual(benchmarks.category(200183, {'name': 'Apotheosis', 'meta': 'Instant · 2 min cooldown'}),
                         benchmarks.THROUGHPUT)
        self.assertIn(benchmarks.THROUGHPUT, benchmarks.JUDGED)
        self.assertEqual(benchmarks.category(1, {'name': 'Power Word: Barrier', 'meta': '3 min cooldown'}), 'raid')

    def test_timeline_reclassifies_stored_uses(self):
        """Pulls analyzed while Evangelism was a raid cooldown: it moves to the Disc's major cooldowns."""
        from raidanalysis.web import consumables
        analysis = {'players': [{'name': 'Disc', 'class': 'Priest', 'spec': 'Discipline', 'role': 'healer'}],
                    'cooldowns': [{'t': 1000, 'name': 'Disc', 'ability_id': 246287, 'ability': 'Evangelism',
                                   'icon': 'e.jpg', 'category': 'raid', 'target': None}],
                    'casts': {'Disc': [[1000, 246287]]}}
        pull = {'analysis': analysis}
        lookup = lambda ids: {246287: {'name': 'Evangelism', 'meta': 'Instant · 1.5 min cooldown', 'icon': 'e'}}
        uses = consumables.cooldowns_by_pull([pull], lookup)[id(pull)]
        self.assertEqual([(u['ability'], u['category']) for u in uses], [('Evangelism', 'throughput')])


class TestMajorVsRotational(unittest.TestCase):
    """Immolation Aura / Death and Decay are pressed on cooldown or on procs: judged on how often, not when."""
    SPELLS = {20: {'name': 'Death and Decay', 'meta': 'Instant · 30 sec cooldown'},
              21: {'name': 'Fel Barrage', 'meta': 'Instant · 30 sec cooldown'},
              22: {'name': 'Eye Beam', 'meta': 'Channeled · 1 min cooldown'},
              23: {'name': 'Celestial Conduit', 'meta': 'Channeled · 1.5 min cooldown'}}

    def test_procs_drift_and_overrides(self):
        from raidanalysis import benchmarks
        top = []
        for p in range(5):
            casts = [[t, 21] for t in range(4000 * p, 300000, 18000)]           # more than a 30 s cd allows
            casts += [[t + 12000 * p, 22] for t in range(0, 240000, 60000)]     # on cooldown, everyone out of step
            casts += [[60000, 23], [200000, 23]]                                # rare and agreed
            top.append({'duration': 300000, 'phases': [], 'casts': casts})
        ours = {'number': 1, 'duration': 300000, 'phases': [], 'cast_ids': {21, 22, 23},
                'casts': [[t, 21] for t in range(0, 300000, 40000)] + [[t, 22] for t in range(5000, 240000, 60000)]
                         + [[61000, 23], [201000, 23]]}
        rows = {r['name']: r for r in benchmarks.compare([ours], top, self.SPELLS)}
        self.assertEqual(rows['Fel Barrage']['category'], 'rotational')    # procs / resets
        self.assertEqual(rows['Eye Beam']['category'], 'rotational')       # no agreed moment
        self.assertEqual(rows['Celestial Conduit']['category'], 'throughput')
        self.assertEqual(rows['Fel Barrage']['windows'], [])
        self.assertEqual(rows['Fel Barrage']['verdict'], 'off')            # 1.6 / min vs ~3.3
        self.assertEqual(rows['Eye Beam']['verdict'], 'good')              # same count, timing doesn't matter
        notes = benchmarks.notes(list(rows.values()), 'Havoc Demon Hunters')
        self.assertTrue(any('Fel Barrage' in n['text'] and 'whenever' in n['text'] for n in notes))
        # An officer's call wins, and the automatic one is kept for the dropdown.
        rows = {r['name']: r for r in benchmarks.compare([ours], top, self.SPELLS,
                                                         {'Eye Beam': 'major', 'Celestial Conduit': 'hide'})}
        self.assertEqual((rows['Eye Beam']['category'], rows['Eye Beam']['auto_kind']), ('throughput', 'rotational'))
        self.assertNotIn('Celestial Conduit', rows)

    def test_named_rotational(self):
        from raidanalysis import benchmarks
        top = [{'duration': 300000, 'phases': [], 'casts': [[30000, 20]]} for _ in range(5)]
        ours = {'number': 1, 'duration': 300000, 'phases': [], 'cast_ids': {20}, 'casts': [[90000, 20]]}
        row = benchmarks.compare([ours], top, self.SPELLS)[0]
        self.assertEqual((row['category'], row['verdict']), ('rotational', 'good'))


class TestTrinketWithSeveralIds(unittest.TestCase):
    def test_item_id_makes_the_whole_ability_a_trinket(self):
        from raidanalysis import benchmarks
        spells = {11: {'name': 'Soulcoiler Ritual Vessel', 'meta': 'Channeled (2 sec cast) · 2 min cooldown'},
                  12: {'name': 'Soulcoiler Ritual Vessel', 'meta': 'Item effect · Channeled (2 sec cast) · 2 min cooldown'}}
        top = [{'duration': 300000, 'phases': [], 'casts': [[30000, 11], [31000, 12]]} for _ in range(5)]
        mine = {'number': 1, 'duration': 300000, 'phases': [], 'casts': [], 'cast_ids': {11, 12}, 'casts_seen': {11, 12}}
        row = benchmarks.compare([mine], top, spells)[0]
        self.assertEqual((row['category'], row['verdict']), ('trinket', 'not_equipped'))


class TestNestedCastVariants(unittest.TestCase):
    """Consuming Fire is listed under Immolation Aura in WCL's Casts table - it must still be fetched."""

    def test_subentries_count(self):
        table = {'entries': [{'name': 'Immolation Aura', 'guid': 258920, 'total': 8, 'composite': True,
                              'subentries': [{'name': 'Immolation Aura', 'guid': 258920, 'total': 8},
                                             {'name': 'Consuming Fire', 'guid': 456640, 'total': 8},
                                             {'name': 'Consuming Fire', 'guid': 452487, 'total': 8},
                                             {'name': 'Immolation Aura', 'guid': 427917, 'total': 2}]},
                             {'name': 'Chaos Strike', 'guid': 162794, 'total': 400}]}
        ids = {e['guid'] for e in analyzer.cast_entries(table)}
        self.assertTrue({456640, 452487, 427917} <= ids)
        self.assertEqual(analyzer.rare_cast_ids(table), [258920, 427917, 452487, 456640])


class TestThroughputAndUptime(unittest.TestCase):
    """analysis['extras']: parses, damage by target, uptime and casts per minute, next to raid and top players."""

    def pull(self, number, kill, heart_share, uptime_share, casts):
        """Two DPS: Boops (whose numbers vary) and Other (always 30% into the Heart)."""
        from raidanalysis import throughput
        fight = {'id': number, 'startTime': 0, 'endTime': 300000, 'kill': kill}
        roster = [{'name': 'Boops', 'role': 'dps'}, {'name': 'Other', 'role': 'dps'}]
        def targets(share):  # the DamageDone table lists each player's damage by target
            return [{'name': "Ula'tek", 'type': 'Boss', 'total': 3_000_000 * (1 - share)},
                    {'name': "Heart of Ula'tek", 'type': 'NPC', 'total': 3_000_000 * share}]
        tables = {
            'damageDone': {'entries': [
                {'name': 'Boops', 'total': 3_000_000, 'activeTime': 285000, 'targets': targets(heart_share)},
                {'name': 'Other', 'total': 3_000_000, 'activeTime': 270000, 'targets': targets(0.3)}]},
            'healing': {'entries': []},
        }

        def player(share, buff_share, cast_count):
            return {'debuffs': [],
                    'buffs': {'auras': [{'guid': 258920, 'name': 'Immolation Aura', 'totalUptime': 300000 * buff_share,
                                         'bands': [{'startTime': 0, 'endTime': 6000}]},
                                        {'guid': 1, 'name': 'Flask of Power', 'totalUptime': 300000}]},
                    'casts': {'entries': [{'name': 'Chaos Strike', 'total': cast_count},
                                          {'name': 'Immolation Aura', 'total': 10}]}}
        per_player = {1: player(heart_share, uptime_share, casts), 2: player(0.3, 0.9, 100)}
        parses = throughput.parses_from_rankings({'data': [{'roles': {'dps': {'characters': [
            {'name': 'Boops', 'rankPercent': 82, 'bracketPercent': 90, 'amount': 10000}]}}}]}) if kill else {}
        extras = throughput.build_extras(fight, roster, {1: 'Boops', 2: 'Other'}, tables, per_player, parses)
        analysis = {'players': roster, 'extras': extras}
        return number, {'fight_id': number, 'kill': kill, 'start_ms': 0, 'end_ms': 300000, 'analysis': analysis}

    def test_focus_uptime_and_cpm(self):
        from raidanalysis import throughput
        numbered = [self.pull(1, False, 0.1, 0.6, 50), self.pull(2, True, 0.1, 0.6, 50)]
        me = numbered[1][1]['analysis']['extras']['players']['Boops']
        self.assertEqual([a['name'] for a in me['auras']], ['Immolation Aura'])   # no flask
        self.assertEqual(me['auras'][0]['bands'], [[0, 6]])                       # seconds
        rows = throughput.per_pull(numbered, 'Boops', 'dps')
        self.assertEqual([r['parse'] for r in rows], [None, 82])
        self.assertAlmostEqual(rows[0]['amount'], 10000)
        heart = next(r for r in throughput.focus(numbered, 'Boops', 'dps') if r['name'] == "Heart of Ula'tek")
        self.assertAlmostEqual(heart['mine_share'], 0.1)
        self.assertAlmostEqual(heart['raid_share'], 0.3)
        self.assertTrue(heart['low'])
        top = [{'duration': 300000, 'auras': [{'id': 258920, 'name': 'Immolation Aura', 'kind': 'buff',
                                               'uptime': 270000}],
                'cast_names': {'Chaos Strike': 100, 'Immolation Aura': 11, 'Felblade': 20}} for _ in range(5)]
        up = throughput.uptime(numbered, 'Boops', top)
        self.assertEqual([(u['name'], round(u['ours'], 2), round(u['top'], 2), u['verdict']) for u in up],
                         [('Immolation Aura', 0.6, 0.9, 'off')])
        cpm = throughput.cpm(numbered, 'Boops', top)
        by_name = {a['name']: a for a in cpm['abilities']}
        self.assertEqual(set(by_name), {'Chaos Strike', 'Immolation Aura', 'Felblade'})  # every cast, either side
        self.assertEqual(by_name['Chaos Strike']['verdict'], 'off')    # 10 / min vs 20
        self.assertEqual(by_name['Felblade']['ours'], 0)
        self.assertAlmostEqual(cpm['ours'], 12.0)
        active, raid = throughput.active_time(numbered, 'Boops', 'dps')
        self.assertAlmostEqual(active, 0.95)
        self.assertAlmostEqual(raid, 0.9)

    def test_detail_only_for_kills_and_furthest_wipes(self):
        from raidanalysis import sync, throughput

        def f(i, kill, pct, secs):
            return {'id': i, 'encounterID': 1, 'difficulty': 5, 'kill': kill, 'fightPercentage': pct,
                    'startTime': 0, 'endTime': secs * 1000}
        pulls = [f(1, False, 90, 40), f(2, False, 60, 120), f(3, False, 30, 200), f(4, False, 45, 180),
                 f(5, False, 20, 50), f(6, False, 25, 240), f(7, True, 0, 300)]
        self.assertEqual(sync.detail_fight_ids(pulls), {7, 6, 3, 4})       # the kill + 3 furthest 1 min+ wipes
        # A late joiner (11) in none of those: their own furthest pull too - one pull for both late joiners
        raid = [1, 2, 3]
        late = [dict(p, friendlyPlayers=raid + ([11, 12] if p['id'] in (1, 2) else [])) for p in pulls]
        self.assertEqual(sync.detail_fight_ids(late), {7, 6, 3, 4, 2})
        # Uptime and casts per minute only count pulls with the detail; a cheap pull doesn't dilute them.
        numbered = [self.pull(1, True, 0.1, 0.6, 50)]
        cheap = self.pull(2, False, 0.1, 0.0, 0)
        cheap[1]['analysis']['extras']['detail'] = False
        top = [{'duration': 300000, 'auras': [{'id': 258920, 'name': 'Immolation Aura', 'kind': 'buff',
                                               'uptime': 270000}],
                'cast_names': {'Chaos Strike': 100, 'Immolation Aura': 11}}] * 5
        self.assertAlmostEqual(throughput.uptime(numbered + [cheap], 'Boops', top)[0]['ours'], 0.6)

    def test_tabs_render(self):
        from raidanalysis.web import performance
        numbered = [self.pull(1, True, 0.1, 0.6, 50)]
        player = {'name': 'Boops', 'role': 'dps'}
        html = performance.damage_tab(numbered, player, lambda n: f'/p/{n}')
        self.assertIn("Heart of Ula", html)
        self.assertIn('parse p75', html)
        html = performance.rotation_tab(numbered, player, None)
        self.assertIn('Active time', html)
        empty = performance.damage_tab([(1, {'fight_id': 1, 'analysis': {}})], player, lambda n: '')
        self.assertIn('Not fetched', empty)


class TestWclV1Fallback(unittest.TestCase):
    """v1 answers what it can while v2 is rate limited or the sync spares v2's hour."""

    def setUp(self):
        from raidanalysis import wcl, wcl_v1
        self.wcl, self.v1 = wcl, wcl_v1
        self.saved = (wcl._v2_blocked_until, wcl_v1._blocked_until)
        wcl._v2_blocked_until, wcl_v1._blocked_until = 0.0, 0.0

    def tearDown(self):
        self.wcl._v2_blocked_until, self.v1._blocked_until = self.saved

    def run_events(self, v2, v1, first='0'):
        import asyncio
        from unittest import mock
        with mock.patch.dict('os.environ', {'WCL_V1_API_KEY': 'key', 'WCL_V1_FIRST': first}), \
                mock.patch.object(self.wcl, 'query', v2), mock.patch.object(self.v1, 'get_events', v1):
            return asyncio.run(self.wcl.get_events(None, 'code', 1, 'Casts', "type = 'cast'"))

    def test_switching(self):
        from unittest import mock

        async def v2_ok(*a, **k):
            return {'reportData': {'report': {'events': {'data': ['v2'], 'nextPageTimestamp': None}}}}

        async def v2_down(*a, **k):
            raise self.wcl.WCLServerError('502')

        async def v2_limited(*a, **k):
            raise self.wcl.WCLRateLimited('429', 120)

        async def v1_down(*a, **k):
            raise self.wcl.WCLServerError('502')
        v1 = mock.AsyncMock(return_value=['v1'])
        self.assertEqual(self.run_events(v2_ok, v1), ['v2'])               # v2 by default
        self.assertEqual(self.run_events(v2_down, v1), ['v1'])             # v2 502 (Cloudflare): v1 answers
        with self.assertRaises(self.wcl.WCLRateLimited):                    # same hourly points: no use trying v1
            self.run_events(v2_limited, v1)
        self.assertEqual(self.run_events(v2_ok, v1, first='1'), ['v1'])    # WCL_V1_FIRST=1
        self.assertEqual(self.run_events(v2_ok, v1_down, first='1'), ['v2'])  # v1 fails: v2 answers

    def test_overview_shape(self):
        report = {'title': 'Raid', 'start': 1, 'end': 2, 'owner': 'me',
                  'phases': [{'boss': 7, 'phases': ['One', 'Break', 'Two'], 'intermissions': [2]}],
                  'friendlies': [{'id': 5, 'name': 'Boops', 'type': 'Monk', 'fights': [{'id': 3}]},
                                 {'id': 6, 'name': 'Ritual Drummer', 'type': 'NPC', 'fights': [{'id': 3}]}],
                  'fights': [{'id': 1, 'boss': 0, 'start_time': 0, 'end_time': 5},
                             {'id': 3, 'boss': 7, 'name': 'Boss', 'difficulty': 5, 'kill': False, 'size': 20,
                              'start_time': 100, 'end_time': 900, 'fightPercentage': 8313, 'bossPercentage': 7633,
                              'lastPhaseForPercentageDisplay': 2, 'phases': [{'id': 2, 'startTime': 400}],
                              'zoneID': 9, 'zoneName': 'Abyss'}]}
        o = self.v1.overview(report, 'code')
        f = o['fights'][0]
        self.assertEqual(len(o['fights']), 1)                                 # trash left out
        self.assertEqual((f['fightPercentage'], f['bossPercentage']), (83.13, 76.33))
        self.assertTrue(f['lastPhaseIsIntermission'])
        self.assertEqual(f['friendlyPlayers'], [5])                           # no NPC allies
        self.assertEqual(o['phases'][0]['phases'][1], {'id': 2, 'name': 'Break', 'isIntermission': True})
        self.assertEqual(o['masterData']['actors'][0]['subType'], 'Monk')


class TestHotsOnOthers(unittest.TestCase):
    """Renewing Mist is judged on how many are out on the raid, not on its uptime on the healer."""

    def test_average_active_and_not_self_uptime(self):
        from raidanalysis import throughput
        roster = [{'name': 'Boops', 'role': 'healer'}]
        tables = {'damageDone': {'entries': []}, 'healing': {'entries': [{'name': 'Boops', 'total': 1, 'activeTime': 1}]}}
        per_player = {1: {'buffs': {'auras': [{'guid': 119611, 'name': 'Renewing Mist', 'totalUptime': 180000}]},
                          'debuffs': [], 'casts': {'entries': [{'name': 'Renewing Mist', 'total': 50}]},
                          'on_others': {'auras': [{'guid': 119611, 'name': 'Renewing Mist', 'totalUptime': 1_800_000},
                                                  {'guid': 2, 'name': 'Power Infusion', 'totalUptime': 60000}]}}}
        fight = {'id': 1, 'startTime': 0, 'endTime': 300000, 'kill': True}
        extras = throughput.build_extras(fight, roster, {1: 'Boops'}, tables, per_player, {})
        self.assertTrue(throughput.wants_on_others(roster[0]))
        self.assertEqual([a['name'] for a in extras['players']['Boops']['on_others']], ['Renewing Mist'])  # own spells
        numbered = [(1, {'fight_id': 1, 'kill': True, 'start_ms': 0, 'end_ms': 300000,
                         'analysis': {'players': roster, 'extras': extras}})]
        top = [{'duration': 300000, 'on_others': [{'id': 119611, 'name': 'Renewing Mist', 'uptime': 2_400_000}],
                'auras': [{'id': 119611, 'name': 'Renewing Mist', 'kind': 'buff', 'uptime': 150000}],
                'cast_names': {'Renewing Mist': 55}}] * 5
        row = throughput.on_others_rows(numbered, 'Boops', top)[0]
        self.assertEqual((row['name'], row['ours'], row['top'], row['verdict']), ('Renewing Mist', 6.0, 8.0, 'ok'))
        self.assertEqual(throughput.uptime(numbered, 'Boops', top), [])  # no "uptime on you" tile for it


class TestFocusTimeline(unittest.TestCase):
    """The Venomous Heart is up 25 s: the raid piles into it - were you on it, and was your potion ready?"""

    NAMES = {1: "Ula'tek", 2: 'Venomous Heart', 3: 'Blightscale Rawling'}

    @staticmethod
    def events(per_second):
        """[(second, target id, amount)] -> WCL damage events (the pull starts at 1000 ms)."""
        return [{'type': 'damage', 'timestamp': 1000 + s * 1000 + 10, 'targetID': t, 'amount': a}
                for s, t, a in per_second]

    def data(self, my_heart):
        from raidanalysis import focus
        n = 300
        heart = range(140, 165)                                       # up 2:20-2:45
        # The raid (everything but the main boss): 600/s into the heart while it's up, a trickle into an add
        raid = self.events([(s, 2, 600) for s in heart] + [(s, 3, 5) for s in range(0, n, 2)])
        # When you go for the heart, it takes you 4 s to get there
        mine = self.events([(s, 1, 100) for s in range(n) if s not in heart or not my_heart or s < 144]
                           + [(s, 2, 100) for s in heart if my_heart and s >= 144])
        deaths = [{'type': 'death', 'timestamp': 1000 + 165500, 'targetID': 2}]
        raid_part = {'main': "Ula'tek", 'b': focus.bin_damage(raid, 1000, n, self.NAMES),
                     'appear': focus.first_hits(raid, 1000, self.NAMES),
                     'deaths': focus.deaths_by_target(deaths, 1000, self.NAMES)}
        targets = [{'name': "Ula'tek", 'total': 300 * 1000, 'type': 'Boss'},
                   {'name': 'Venomous Heart', 'total': 25 * 600, 'type': 'NPC'}]
        return focus.build(focus.bin_damage(mine, 1000, n, self.NAMES), raid_part, n, targets,
                           you_firsts=focus.first_hits(mine, 1000, self.NAMES))

    def test_windows_and_verdicts(self):
        from raidanalysis import focus
        d = self.data(my_heart=False)
        self.assertEqual(set(d['raid']), {"Ula'tek", 'Venomous Heart', 'Blightscale Rawling'})  # you're part of the raid
        w = focus.windows(d)[0]
        self.assertEqual((w['target'], w['start'], w['end']), ('Venomous Heart', 140010, 165000))  # to the ms
        self.assertTrue(w['priority'])
        self.assertEqual(w['verdict'], 'off')                                       # you stayed on the boss
        self.assertEqual(focus.windows(self.data(my_heart=True))[0]['verdict'], 'good')
        self.assertEqual(len(focus.windows(d)), 1)                                  # the trickle add is up all fight
        self.assertEqual((w['died_at'], w['first_hit']), (165500, None))            # died; you never touched it
        self.assertEqual(focus.windows(self.data(my_heart=True))[0]['first_hit'], 4000)

    def test_up_time_and_switches(self):
        from raidanalysis import focus
        d = self.data(my_heart=True)
        rows = {r['target']: r for r in focus.target_rows(d)}
        self.assertEqual(rows["Ula'tek"]['up_s'], 300)                              # the boss: the whole pull
        self.assertEqual(rows['Venomous Heart']['up_s'], 25)
        runs = focus.your_targets(d, focus.palette_order(d))
        self.assertEqual([r['target'] for r in runs], ["Ula'tek", 'Venomous Heart', "Ula'tek"])
        self.assertEqual((runs[1]['start'], runs[1]['end']), (144000, 165000))

    def test_damage_outside_the_pull_or_on_players_is_left_out(self):
        from raidanalysis import focus
        events = self.events([(0, 1, 10), (5, 99, 10)]) + [{'type': 'damage', 'timestamp': 999_999, 'targetID': 1,
                                                           'amount': 10}, {'type': 'heal', 'timestamp': 1500, 'targetID': 1}]
        self.assertEqual(sum(focus.bin_damage(events, 1000, 10, self.NAMES)["Ula'tek"]), 10)

    def test_buffs_on_you(self):
        """Your Trueshot (one band), Power Infusion from a priest, lust re-applied (merged), Mark of the Wild (left out)."""
        from raidanalysis import focus
        from raidanalysis.web import focusview
        ev = [{'type': t, 'timestamp': 1000 + ms, 'sourceID': src, 'abilityGameID': aid} for t, ms, src, aid in [
            ('applybuff', 0, 9, 1126), ('applybuff', 5000, 5, 288613), ('removebuff', 20000, 5, 288613),
            ('applybuff', 60000, 7, 10060), ('removebuff', 80000, 7, 10060),
            ('applybuff', 100000, 8, 2825), ('removebuff', 110000, 8, 2825), ('applybuff', 110500, 8, 2825),
            ('removebuff', 140000, 8, 2825)]]
        abilities = {1126: ('Mark of the Wild', ''), 288613: ('Trueshot', 'ability_trueshot.jpg'),
                     10060: ('Power Infusion', 'spell_holy_powerinfusion.jpg'), 2825: ('Bloodlust', '')}
        auras = {a['name']: a for a in focus.aura_bands(ev, 1000, 300000, 5, {7: 'Priestly', 8: 'Shammy', 9: 'Druid'},
                                                         abilities)}
        self.assertNotIn('Mark of the Wild', auras)                                 # up all pull
        self.assertEqual((auras['Trueshot']['mine'], auras['Trueshot']['bands']), (True, [[5000, 20000]]))
        self.assertEqual((auras['Power Infusion']['mine'], auras['Power Infusion']['from']), (False, ['Priestly']))
        self.assertEqual(auras['Bloodlust']['bands'], [[100000, 140000]])           # re-applied: one stretch
        d = dict(self.data(my_heart=True), auras=list(auras.values()))
        order, color_of = focusview.colors(d)
        pull = {'fight_id': 1, 'start_ms': 1000, 'end_ms': 301000, 'analysis': {'boss_casts': [], 'boss_abilities': []}}
        html = focusview.timeline(d, pull, 'Boops', color_of, order, [(5000, 288613, 'Trueshot', None)], [], [])
        self.assertIn('Your cooldowns', html)
        self.assertIn('Power Infusion from Priestly', html)
        self.assertIn('Trueshot pressed · 0:05.0', html)
        self.assertIn('data-remember="focus"', html)
        self.assertIn('data-name="cds:Trueshot"', html)                             # pickers remembered by name
        self.assertIn('data-name="t:Venomous Heart"', html)

    def test_view_renders_potion_timing(self):
        from raidanalysis.web import focusview
        d = self.data(my_heart=False)
        order, color_of = focusview.colors(d)
        pull = {'fight_id': 1, 'start_ms': 1000, 'end_ms': 301000, 'analysis': {'boss_casts': [], 'boss_abilities': []}}
        potions = [{'t': 130000, 'end': 160000, 'ability': 'Liquid Luster'}]
        html = focusview.timeline(d, pull, 'Boops', color_of, order, [], potions, [])
        self.assertIn('fraid prio', html)
        self.assertIn('Your target', html)
        self.assertIn('Venomous Heart #1 · appeared 2:20.0, died 2:45', html)        # a bar per spawn
        self.assertIn('class="fspawn died"', html)
        self.assertIn('<span>10.0 s</span>', html)                                  # potion -> add bracket
        self.assertIn('freact never', html)                                         # never hit it
        phased = focusview.timeline(d, dict(pull, encounter_id=7), 'Boops', color_of, order, [], [],
                                    [{'id': 1, 'start': 0}, {'id': 2, 'start': 120000}],
                                    {'7': {'2': {'name': 'Stage Two', 'intermission': False}}})
        self.assertIn('<span>Stage Two</span>', phased)
        self.assertIn('<span>Phase 1</span>', phased)
        cards = focusview.cards(d, color_of, potions, [], {}, {}, 'Havoc Demon Hunters')
        self.assertIn('pressed <b>10.0 s before it appeared</b>', cards)            # the spawn's tab
        self.assertIn('data-tab="1"', cards)
        self.assertIn('🧪 +10.0 s', cards)                                          # overall: potion chip
        self.assertIn('covered <b>78%</b>', cards)                                 # 20 of the 25.5 s until it died
        self.assertIn('Off target', cards)
        self.assertIn('died 2:45', cards)
        self.assertIn('never hit', cards)
        icons = {'Venomous Heart': 'https://wow.zamimg.com/modelviewer/live/webthumbs/npc/196/143812.webp'}
        with_icons = focusview.timeline(d, pull, 'Boops', color_of, order, [], potions, [], None, icons)
        self.assertIn('background-image:url(https://wow.zamimg.com/modelviewer/live/webthumbs/npc/196/143812.webp)',
                      with_icons)
        self.assertIn('143812.webp', focusview.cards(d, color_of, potions, [], {}, {}, 'x', icons))
        self.assertNotIn('evil.example', focusview.timeline(d, pull, 'Boops', color_of, order, [], potions, [], None,
                                                            {'Venomous Heart': 'https://evil.example/x.jpg'}))

    def test_npc_portraits(self):
        """NPC id -> display id (the Creature table, else the Wowhead page) -> Wowhead's model thumbnail."""
        from raidanalysis import npcs
        from raidanalysis.web.render import npc_portrait
        table = ('ID,Name_lang,DisplayID_0,DisplayID_1\n220586,"Queen Ansurek",118230,0\n5,"Nobody",0,0\n')
        self.assertEqual(npcs.parse_creature_table(table), {220586: 118230})
        page = '<a data-mv-type="1" data-mv-type-id="263535" data-mv-display-id="143812">View in 3D</a>'
        self.assertEqual(npcs.display_from_page(page), 143812)
        self.assertIsNone(npcs.display_from_page('<html>no model</html>'))
        self.assertEqual(npcs.thumb_url(143812), 'https://wow.zamimg.com/modelviewer/live/webthumbs/npc/196/143812.webp')
        self.assertIn('background-image:url(https://wow.zamimg.com/', npc_portrait(npcs.thumb_url(1), '#fff', 'lg'))
        self.assertEqual(npc_portrait('https://evil.example/x.webp'), '')
        self.assertEqual(npc_portrait('https://wow.zamimg.com/x.webp);background:url(//evil'), '')

    def test_raid_timeline_boss_lanes_and_dropdowns(self):
        """The heart's spawns get their own lane and a dashed line through everyone; categories are dropdowns."""
        from raidanalysis import focus
        from raidanalysis.web import consumables
        adds = focus.add_types(focus.windows(self.data(my_heart=False)))
        analysis = {'_duration': 300000, 'players': [{'name': 'Boops', 'class': 'Hunter', 'role': 'dps'}],
                    'boss_casts': [[5000, 77]], 'boss_abilities': [{'id': 77, 'name': 'Venom Spit', 'icon': 'a.jpg'}],
                    'consumables': [
                        {'t': 130000, 'end': 160000, 'name': 'Boops', 'ability_id': 431932, 'ability': 'Tempered Potion',
                         'icon': 'potion.jpg', 'kind': 'potion'},
                        {'t': 200000, 'name': 'Boops', 'ability_id': 6262, 'ability': 'Healthstone', 'icon': 'hs.jpg',
                         'kind': 'defensive', 'healing': 100},
                        {'t': 210000, 'name': 'Boops', 'ability_id': 431416, 'ability': 'Algari Healing Potion',
                         'icon': 'hp.jpg', 'kind': 'defensive', 'healing': 200}],
                    'cooldowns': [{'t': 1000, 'name': 'Boops', 'ability_id': 97462, 'ability': 'Rallying Cry',
                                   'icon': 'rc.jpg', 'category': 'raid', 'target': None}]}
        pull = {'number': 1, 'kill': True, 'analysis': analysis, 'phases': [120000],
                'phase_list': [{'id': 1, 'start': 0}, {'id': 2, 'start': 120000}]}
        html = consumables.timeline([pull], analysis['players'], adds=adds,
                                    phase_names={'2': {'name': 'Stage Two', 'intermission': False}})
        self.assertIn('<span>Stage Two</span>', html)                               # the phase lane
        self.assertIn('class="tl-row c-lane c-add" data-k="add:Venomous Heart"', html)  # the heart's own lane
        self.assertIn('class="tl-phase fspawnline" data-k="add:Venomous Heart"', html)  # ...and its line through everyone
        # Remembered across pulls by name (localStorage, PAGE_JS): never by position
        self.assertIn('data-remember="raid"', html)
        self.assertIn('value="add:Venomous Heart" data-name="add:Venomous Heart" checked', html)
        self.assertIn('data-name="cd:raid:Rallying Cry"', html)
        self.assertIn('data-k="death" data-name="death"', html)
        self.assertIn('Venomous Heart #1 · appeared 2:20.0, died 2:45 (25 s) · a priority', html)
        self.assertNotIn('you never hit', html)                                     # the raid's view, not a player's
        self.assertIn('data-dd="boss"', html)
        self.assertIn('data-dd="cons"', html)
        self.assertIn('data-dd="raid"', html)
        self.assertNotIn('Abilities ▾', html)                                       # the old picker is gone
        self.assertIn('class="m dia" data-k="healthstone"', html)                   # told apart: diamond...
        self.assertIn('class="m dot" data-k="healing"', html)                       # ...and dot
        self.assertIn('<b class="sp431932"></b>', html)                             # the potion's icon on its bar
        self.assertIn('data-spell="97462"', html)                                   # the dropdown entry has its tooltip
        self.assertIn('value="cd:raid:Rallying Cry" data-name="cd:raid:Rallying Cry">', html)  # off by default
        self.assertIn('class="m cd sp97462" data-k="cd:raid:Rallying Cry"', html)
        loading = consumables.timeline([pull], analysis['players'], loading='<div class="castbar-wrap"></div>')
        self.assertIn('castbar-wrap', loading)                                      # adds not loaded yet
        self.assertNotIn('value="add:', loading)
        self.assertIn('value="phases"', loading)                                    # phases don't need them


class TestDamageByTarget(unittest.TestCase):
    """Everyone's damage per target over the boss's pulls: ranked, a star for the top, you highlighted."""

    @staticmethod
    def pull(players):
        roster = [{'name': n, 'class': c, 'role': r} for n, c, r, _ in players]
        return {'analysis': {'players': roster, 'extras': {
            'targets': [{'name': "Ula'tek", 'total': 1, 'type': 'Boss'}],
            'players': {n: {'targets': t} for n, _, _, t in players}}}}

    def test_ranking_and_view(self):
        from raidanalysis import throughput
        from raidanalysis.web import targets
        a = self.pull([('Boops', 'Monk', 'dps', [["Ula'tek", 100, 'Boss'], ['Venomous Heart', 50, 'NPC']]),
                       ('Futhark', 'Hunter', 'dps', [["Ula'tek", 80, 'Boss'], ['Venomous Heart', 90, 'NPC']]),
                       ('Holy', 'Priest', 'healer', [['Venomous Heart', 5, 'NPC']])])
        b = self.pull([('Futhark', 'Hunter', 'dps', [['Venomous Heart', 30, 'NPC']])])
        ranked = {t['name']: t for t in throughput.target_ranking([(1, a), (2, b)])}
        heart = ranked['Venomous Heart']
        self.assertEqual([(p['name'], p['damage'], p['pulls']) for p in heart['players']],
                         [('Futhark', 120, 2), ('Boops', 50, 1), ('Holy', 5, 1)])
        self.assertAlmostEqual(heart['players'][0]['share'], 120 / 175)
        self.assertTrue(ranked["Ula'tek"]['main'])
        self.assertEqual(targets.your_rank(heart, 'Boops'), '#2 of 3')
        html = targets.ranking(heart, 'Boops')
        self.assertIn('dt-star', html)                                              # Futhark: the most
        self.assertIn('dt-row you', html)
        card = targets.section(list(ranked.values()), {'Venomous Heart'}, 'all 2 pulls tonight')
        self.assertLess(card.index('Venomous Heart'), card.index("Ula&#x27;tek"))   # priority first
        self.assertIn('Holy', card)                                                 # healers rank like everyone
        crowd = {'name': 'Blightscale Clutch', 'players': [
            {'name': f'P{i}', 'class': 'Mage', 'role': 'dps', 'damage': 100 - i, 'dps': 1 - i / 100, 'share': 0.1,
             'pulls': 1} for i in range(10)]
            + [{'name': 'Zero', 'class': 'Mage', 'role': 'dps', 'damage': 0, 'dps': 0, 'share': 0, 'pulls': 1}]}
        html = targets.ranking(crowd)
        self.assertNotIn('Zero', html)                                              # 0 damage: left out
        self.assertIn('Show all 10', html)                                          # the count matches the list
        self.assertEqual(html.count('dt-row extra'), 2)                             # 9th and 10th behind the button
        self.assertLess(html.index('dt-row extra'), html.index('dt-toggle'))        # the button at the bottom

    def test_stored_full_lists_win(self):
        """WCL's plain table has only each player's top 5 targets: the stored per-target tables have everyone."""
        from raidanalysis import throughput
        a = dict(self.pull([('Boops', 'Monk', 'dps', [["Ula'tek", 100, 'Boss']])]), fight_id=1)
        b = dict(self.pull([('Boops', 'Monk', 'dps', [["Ula'tek", 70, 'Boss']])]), fight_id=2)
        stored = {1: {"Ula'tek": {'Boops': 100}, 'Blightscale Clutch': {'Boops': 9, 'Futhark': 12}}}
        ranked = {t['name']: t for t in throughput.target_ranking([(1, a), (2, b)], stored)}
        self.assertEqual([p['name'] for p in ranked['Blightscale Clutch']['players']], ['Futhark', 'Boops'])
        self.assertEqual(ranked["Ula'tek"]['players'][0]['damage'], 170)            # pull 2 from its table
        self.assertFalse(ranked["Ula'tek"]['complete'])                             # ...so: partial
        self.assertTrue(throughput.target_ranking([(1, a)], stored)[0]['complete'])


class TestPlayersCompactOutput(unittest.TestCase):
    """The Mechanics tab's players table: a Parse column (WCL, average) next to our Score, told apart."""

    def test_output_columns(self):
        from raidanalysis.web import players
        roster = [{'name': 'Futhark', 'class': 'Hunter', 'role': 'dps'}, {'name': 'Boops', 'class': 'Monk', 'role': 'dps'}]
        def pull(n, futhark_parse):
            return (n, {'fight_id': n, 'start_ms': 0, 'end_ms': 100000, 'analysis': {'players': roster, 'extras': {
                'duration': 100000, 'players': {
                    'Futhark': {'damage': 30e6, 'active_ms': 95000, 'parse': {'rank': futhark_parse}},
                    'Boops': {'damage': 20e6, 'active_ms': 60000, 'parse': None}}}}})
        report = [{'name': n['name'], 'class': n['class'], 'role': 'dps', 'spec': '', 'score': 80,
                   'scores': {k: 70 for k, _, _ in players.SUBSCORES}, 'deaths': 0, 'avoidable_hits': 0,
                   'interrupts': 0, 'dispels': 0, 'feedback': []} for n in roster]
        html = players.compact_table(report, lambda n: '#', [pull(1, 60), pull(2, 90)])
        self.assertIn('<b>Score</b> = our 0-100 grade for the mechanics', html)     # told apart from a parse
        self.assertLess(html.index('>Score</th>'), html.index('>Parse</th>'))
        self.assertLess(html.index('>Parse</th>'), html.index('>Player</th>'))       # between score and player
        self.assertIn('title="Average 75 over 2 parses · best 90"><span class="parse p75">75</span>', html)
        self.assertIn('title="No Warcraft Logs parse in these pulls">—', html)      # Boops: none


class TestCoach(unittest.TestCase):
    """The 'My performance' coaching: the bosses that mattered, the few things that cost the most, what went well."""

    def test_boss_weights(self):
        from raidanalysis import coach
        easy = {'pulls': 1, 'killed': True, 'start': 0}          # first boss, one-shot
        mid = {'pulls': 6, 'killed': True, 'start': 1}
        prog = {'pulls': 18, 'killed': False, 'start': 2}        # the night ended on 18 wipes here
        w_easy, w_mid, w_prog = coach.boss_weights([easy, mid, prog])
        self.assertEqual(w_prog, 1)
        self.assertLess(w_easy, 0.15)                             # hardly worth a word
        self.assertTrue(w_easy < w_mid < w_prog)

    def test_pick_weighs_and_dedupes(self):
        from raidanalysis import coach
        found = [dict(coach._insight('bad', 60, 'death', 'Died first'), boss='Easy', score=60 * 0.1),
                 dict(coach._insight('bad', 40, 'rotation', 'Rapid Fire low'), boss='Prog', score=40),
                 dict(coach._insight('bad', 30, 'rotation', 'Aimed Shot low'), boss='Prog', score=30),
                 dict(coach._insight('bad', 35, 'focus', 'Off the Heart'), boss='Prog', score=35),
                 dict(coach._insight('good', 45, 'star', 'Most damage to the Heart'), boss='Prog', score=45)]
        work = coach._pick(found, 'bad', 3)
        self.assertEqual([i['text'] for i in work], ['Rapid Fire low', 'Off the Heart'])  # one rotation tip, easy boss out
        self.assertEqual([i['text'] for i in coach._pick(found, 'good', 3)], ['Most damage to the Heart'])

    def test_focus_insights(self):
        from raidanalysis import coach
        t = TestFocusTimeline()
        off = coach.focus_insights(t.data(my_heart=False), 3, [{'t': 130000, 'end': 160000}])
        texts = ' | '.join(i['text'] for i in off)
        self.assertIn('Venomous Heart: you put 0% of your damage into it', texts)
        self.assertIn('Never hit Venomous Heart', texts)
        self.assertIn('Potion 10.0 s before Venomous Heart', texts)
        late = coach.focus_insights(t.data(my_heart=True), 3, [{'t': 150000, 'end': 180000}],
                                    {'Venomous Heart': {'players': [{'name': 'Boops'}, {'name': 'Futhark'}]}}, 'Boops')
        texts = ' | '.join(i['text'] for i in late)
        self.assertIn('Potion 10.0 s after Venomous Heart appeared', texts)
        self.assertIn('4.0 s from Venomous Heart appearing to your first hit', texts)
        self.assertIn('★ Most damage to Venomous Heart in the raid (pull #3)', texts)

    def test_recap_message(self):
        from unittest import mock
        from raidanalysis import coach, discord_recap
        work = [dict(coach._insight('bad', 50, 'focus', 'Venomous Heart: you put 34% of your damage into it'),
                     boss="Ula'tek", score=50, guide_for=None)]
        good = [dict(coach._insight('good', 45, 'star', '★ Most damage to Venomous Heart in the raid (pull #9)'),
                     boss="Ula'tek", score=45, guide_for=None)]
        bosses = [{'name': 'Gore Rattle', 'difficulty': 5, 'key': (1, 5), 'pulls': 1, 'killed': True, 'best': None,
                   'score': 88, 'parse': 71.0, 'weight': 0.1, 'star': None},
                  {'name': "Ula'tek", 'difficulty': 5, 'key': (2, 5), 'pulls': 18, 'killed': False, 'best': 8.9,
                   'score': 62, 'parse': 53.0, 'weight': 1, 'star': 'Venomous Heart'}]
        recap = {'report': {'title': 'Tuesday', 'code': 'abc'}, 'character': 'Futhark', 'other_characters': [],
                 'bosses': bosses, 'work_on': work, 'going_well': good, 'missing': None}
        with mock.patch('raidanalysis.web.routes.public_base_url', return_value='https://lumi.example'):
            embed, view = discord_recap.recap_message(recap)
        fields = {f.name: f.value for f in embed.fields}
        self.assertIn("**Ula'tek** · Venomous Heart: you put 34%", fields['🔧 Work on'])
        self.assertIn("✖ **Ula'tek** (Mythic) · 18 pulls · best 8.9% · score **62** · parse **53** · ⭐ Venomous Heart",
                      fields['📋 Boss by boss'])
        self.assertIn('Best parse **71**', embed.description)
        urls = [b.url for b in view.children]
        self.assertIn("https://lumi.example/raids/report/abc/player/Futhark?boss=2-5&tab=damage", urls)

    def test_no_rotation_tip_for_a_filler_button(self):
        """Top players pressing Blackout Kick once in downtime isn't a rotation to work on."""
        from raidanalysis import coach, throughput
        pull = (1, {'fight_id': 1, 'start_ms': 0, 'end_ms': 600000, 'analysis': {'players': [], 'extras': {
            'duration': 600000, 'players': {'Boops': {'casts': {'Vivify': 160, 'Rising Sun Kick': 30, 'Blackout Kick': 1}}}}}})
        top = [{'duration': 600000, 'cast_names': {'Vivify': 165, 'Rising Sun Kick': 72, 'Blackout Kick': 1}}] * 5
        rows = {a['name']: a for a in throughput.cpm([pull], 'Boops', top)['abilities']}
        self.assertIsNone(rows['Blackout Kick']['verdict'])                           # 0.1 a minute: not judged
        self.assertEqual(rows['Rising Sun Kick']['verdict'], 'off')
        tips = [i['text'] for i in coach.rotation_insights([pull], 'Boops', 'healer', {'top': top, 'rows': [],
                                                                                      'label': 'Mistweaver Monks'})]
        self.assertTrue(any(t.startswith('Rising Sun Kick: 3.0 casts a minute') for t in tips))
        self.assertFalse(any('Blackout Kick' in t for t in tips))

    def test_no_rotation_tip_for_utility(self):
        """An interrupt is pressed when the fight asks for it - never a casts-per-minute tip, however often."""
        from raidanalysis import coach, throughput
        pull = (1, {'fight_id': 1, 'start_ms': 0, 'end_ms': 600000, 'analysis': {'players': [], 'extras': {
            'duration': 600000, 'players': {'Mage': {'casts': {'Frostbolt': 150, 'Counterspell': 1}}}}}})
        top = [{'duration': 600000, 'cast_names': {'Frostbolt': 155, 'Counterspell': 12}}] * 5   # 2 a minute
        rows = {a['name']: a for a in throughput.cpm([pull], 'Mage', top)['abilities']}
        self.assertIsNone(rows['Counterspell']['verdict'])
        tips = coach.rotation_insights([pull], 'Mage', 'dps', {'top': top, 'rows': [], 'label': 'Frost Mages'})
        self.assertFalse(any('Counterspell' in i['text'] for i in tips))

    def test_ranked_by_dps_over_the_pulls_you_were_in(self):
        """In 1 of 2 pulls with the add, but the hardest hitter in it: first - total damage would say otherwise."""
        from raidanalysis import throughput
        def pull(fid, players):
            return (fid, {'fight_id': fid, 'start_ms': 0, 'end_ms': 100000, 'analysis': {
                'players': [{'name': n, 'class': 'Mage', 'role': 'dps'} for n in players],
                'extras': {'targets': [{'name': "Ula'tek", 'total': 1, 'type': 'Boss'}], 'players': {}}}})
        stored = {1: {'Heart': {'Steady': 1000, 'Late': 1500}}, 2: {'Heart': {'Steady': 1000}}}
        ranked = {t['name']: t for t in throughput.target_ranking([pull(1, ['Steady', 'Late']), pull(2, ['Steady'])],
                                                                   stored)}
        heart = ranked['Heart']
        self.assertEqual([(p['name'], p['dps'], p['pulls']) for p in heart['players']],
                         [('Late', 15.0, 1), ('Steady', 10.0, 2)])                  # 1500 over 100 s vs 2000 over 200 s
        self.assertEqual(heart['pulls'], 2)
        # With the add's up times: over the 10 s / 20 s it was there, not the 100 s pulls
        up = {1: {'Heart': 10}, 2: {'Heart': 20}}
        ranked = {t['name']: t for t in throughput.target_ranking([pull(1, ['Steady', 'Late']), pull(2, ['Steady'])],
                                                                   stored, up)}
        self.assertEqual([(p['name'], p['dps']) for p in ranked['Heart']['players']],
                         [('Late', 150.0), ('Steady', 2000 / 30)])

    def test_up_seconds(self):
        """An add's up time: the stretches it was hit (short gaps bridged); hit nearly all pull: the whole pull."""
        from raidanalysis import focus
        bins = {'Heart': [0, 5, 5, 0, 0, 5, 0, 0, 0, 0, 0, 0, 5, 5, 0, 0, 0, 0, 0, 0],
                'Second Boss': [5] * 19 + [0]}
        self.assertEqual(focus.up_seconds(bins, 20), {'Heart': 7.0, 'Second Boss': 20.0})
        self.assertIn('target.name = "Heart" and (source.name = "A" or source.owner.name = "A"',
                      focus._up_filter({'Heart': ['A', 'B']}))
