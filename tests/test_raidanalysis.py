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
                'casts': [[2000, 1], [220000, 1], [100000, 6]], 'cast_ids': None}
        rows = {r['name']: r for r in benchmarks.compare([ours], top, self.SPELLS)}
        meta = rows['Metamorphosis']
        self.assertEqual([w['segment'] for w in meta['windows']], [(0, 1), (1, 2)])
        self.assertEqual((meta['hits'], meta['considered'], meta['verdict']), (2, 2, 'good'))
        self.assertEqual(rows['Essence Break']['verdict'], 'missing')
        # Any combat potion counts, and a trinket we don't have isn't a miss.
        self.assertEqual(rows['Combat potion']['ours_casts'], 1)
        self.assertIsNone(rows['Cursed Trinket']['verdict'])
        notes = benchmarks.notes(list(rows.values()), 'Havoc Demon Hunters')
        self.assertTrue(any('Essence Break' in n['text'] and n['tone'] == 'bad' for n in notes))

    def test_off_timing_and_unreached_phases(self):
        from raidanalysis import benchmarks
        top = [self.top() for _ in range(5)]
        # Meta 60 s late at the pull, and the pull wiped before phase 2: one moment, missed.
        ours = {'number': 1, 'duration': 140000, 'phases': [{'id': 1, 'start': 0}],
                'casts': [[61000, 1], [5000, 2]], 'cast_ids': None}
        meta = next(r for r in benchmarks.compare([ours], top, self.SPELLS) if r['name'] == 'Metamorphosis')
        self.assertEqual((meta['hits'], meta['considered']), (0, 1))


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
