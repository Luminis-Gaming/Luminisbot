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

    def test_shared_battlenet_alt_nobody_signed_up_with_stands_alone(self):
        from raidanalysis.people import own_characters, resolve_owners
        # Gastronomic's Discord links the shared account: her characters and Naautilus' (Naautilus, his alt
        # Metropolis). Nobody has signed up with Metropolis: it could be either's - so it's nobody's for now.
        owners = resolve_owners(signups=[('Gastronomic', 'G', 4), ('Irio', 'G', 1), ('Naautilus', 'N', 5)],
                                linked=[('Gastronomic', 'G'), ('Irio', 'G'), ('Naautilus', 'G'), ('Metropolis', 'G'),
                                        ('Boopsproops', 'B')])
        self.assertEqual(owners['irio']['key'], 'dG')            # signed up with it herself: hers
        self.assertEqual(owners['metropolis']['key'], 'cmetropolis')  # on its own
        self.assertIsNone(owners['metropolis']['discord_id'])
        self.assertEqual(owners['boopsproops']['key'], 'dB')    # an account nobody shares: its links stand
        self.assertNotIn('metropolis', own_characters('G', ['Gastronomic', 'Irio', 'Naautilus', 'Metropolis'], owners))
        # Naautilus signs up with Metropolis once: his
        owners = resolve_owners(signups=[('Gastronomic', 'G', 4), ('Naautilus', 'N', 5), ('Metropolis', 'N', 1)],
                                linked=[('Gastronomic', 'G'), ('Naautilus', 'G'), ('Metropolis', 'G')])
        self.assertEqual(owners['metropolis']['key'], 'dN')

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
        # Never pressed, talents unknown: most likely not talented - not judged
        self.assertEqual(rows['Essence Break']['verdict'], 'not_taken')
        # Any combat potion counts, and a trinket we don't have isn't a miss.
        self.assertEqual(rows['Combat potion']['ours_casts'], 1)
        self.assertEqual(rows['Cursed Trinket']['verdict'], 'not_equipped')
        self.assertEqual(rows['Cursed Trinket']['weak'], [])
        notes = benchmarks.notes(list(rows.values()), 'Havoc Demon Hunters')
        self.assertFalse(any('Essence Break' in n['text'] for n in notes))
        # ...but with their talents known: it was taken (or baseline) and never pressed - a real miss
        from raidanalysis.gamedata import Talents
        had_it = Talents(frozenset({'Some Other Talent'}), frozenset({'Essence Break', 'Some Other Talent'}))
        rows_t = {r['name']: r for r in benchmarks.compare([ours], top, self.SPELLS, talents=had_it)}
        self.assertEqual(rows_t['Essence Break']['verdict'], 'missing')
        self.assertTrue(any('Essence Break' in n['text'] and n['tone'] == 'bad'
                            for n in benchmarks.notes(list(rows_t.values()), 'Havoc Demon Hunters')))
        skipped = Talents(frozenset({'Essence Break'}), frozenset({'Essence Break'}))
        rows_t = {r['name']: r for r in benchmarks.compare([ours], top, self.SPELLS, talents=skipped)}
        self.assertEqual(rows_t['Essence Break']['verdict'], 'not_taken')
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


class TestDeathsOnlyMechanics(unittest.TestCase):
    """Gravebound: picking up soul fragments hurts (fine) - dying to it is the mistake, whenever it happens."""

    def analysis(self):
        deaths = [{'t': t, 'name': n, 'ability': a, 'ability_id': i} for t, n, a, i in [
            (10000, 'Tanky', 'Melee', 1), (11000, 'P2', 'Melee', 1), (12000, 'P3', 'Melee', 1), (13000, 'P4', 'Melee', 1),
            (200000, 'Aedrios', 'Gravebound', 777),                        # 5th death: wouldn't count on its own
            (260000, 'P6', 'Gravebound', 777)]]                            # after the wipe was called
        deaths[-1]['after_wipe'] = True
        players = [{'name': n, 'class': 'Warrior', 'role': 'dps'} for n in ('Tanky', 'P2', 'P3', 'P4', 'Aedrios', 'P6')]
        return {'_duration': 300000, 'players': players, 'deaths': deaths, 'abilities': [
            {'id': 776, 'name': 'Gravebound', 'total': 9000, 'events': 9, 'complete': True,
             'players': {'Aedrios': {'damage': 9000, 'hits': 3}}}]}

    def test_deaths_count_hits_dont(self):
        from raidanalysis import analyzer
        a = analyzer.mark_death_only(self.analysis(), {776}, {'Gravebound'})            # death logged under another id
        early = {d['name']: d['early'] for d in a['deaths']}
        self.assertTrue(early['Aedrios'])                                          # 5th death, but deaths only: a mistake
        self.assertFalse(early['P6'])                                              # after the wipe: not
        self.assertEqual(analyzer.death_note(a['deaths'][4]), 'died to it - for this mechanic only dying is the mistake')
        self.assertEqual(analyzer.avoidable_by_player(a, {776: analyzer.TAG_DEATH_ONLY}), {})  # its hits aren't mistakes
        self.assertTrue(analyzer.annotate_deaths(a)['deaths'][4]['early'])         # survives re-annotating

    def test_night_summary(self):
        from raidanalysis import analyzer
        from raidanalysis.web import insights
        a = analyzer.mark_death_only(self.analysis(), {776}, {'Gravebound'})
        html = insights.build([{'number': 1, 'fight_id': 1, 'kill': False, 'reason': None, 'phases': [], 'analysis': a}],
                              {776: analyzer.TAG_DEATH_ONLY}, lambda i, n: None, 'x')
        self.assertIn('Died to <strong>Gravebound</strong> <strong>1 time</strong> — 1 player', html)
        self.assertNotIn('Hit by <strong>Gravebound', html)


class TestHelicalToxins(unittest.TestCase):
    """Entombed Sentinels, from real pulls: pairs that make 4, a 2 and a 3 making 5, a locked one bumping on, one alone."""

    def setUp(self):
        from raidanalysis import bossmech
        self.mech = next(m for m in bossmech.for_encounter(3445) if m.key == 'helical')
        people = ['Moerade', 'Stonasloth', 'Zorromix', 'Asiriel', 'Barathrûm', 'Haldrik', 'P7', 'P8']
        self.names = {i: n for i, n in enumerate(people, 1)}
        self.ids = {n: i for i, n in self.names.items()}
        self.roster = set(people)

    def ev(self, t, kind, who, stack=None):
        e = {'timestamp': t, 'type': kind, 'sourceID': -1, 'targetID': self.ids[who]}
        if stack:
            e['stack'] = stack
        return e

    def data(self):
        ev = [self.ev(161210 + i, 'applydebuff', n) for i, n in enumerate(['Moerade', 'Stonasloth', 'Zorromix',
                                                                            'Asiriel', 'Barathrûm', 'Haldrik'])]
        ev += [self.ev(163510, 'removedebuff', 'Moerade'), self.ev(163510, 'removedebuff', 'Stonasloth'),  # made 4
               self.ev(163690, 'applydebuffstack', 'Zorromix', 5), self.ev(163690, 'applydebuffstack', 'Asiriel', 5),
               self.ev(165000, 'applydebuffstack', 'Zorromix', 7),                                          # locked 5
               self.ev(165000, 'applydebuffstack', 'Barathrûm', 7),                                         # + a 2
               self.ev(189270, 'removedebuff', 'Zorromix'), self.ev(189340, 'removedebuff', 'Asiriel'),
               self.ev(189300, 'removedebuff', 'Barathrûm'),
               self.ev(189290, 'removedebuff', 'Haldrik')]                                                  # ran out
        return self.mech.collect({'toxins': ev}, 0, self.names, self.roster)

    def analysis(self):
        return {'players': [{'name': n} for n in self.roster], 'deaths': [], 'boss_mechanics': {'helical': self.data()}}

    def test_outcomes(self):
        from raidanalysis import bossmech
        fails = bossmech.failures(self.analysis(), self.mech)
        self.assertEqual([(f['players'], f['kind']) for f in fails],
                         [(['Zorromix', 'Asiriel'], 'wrong'), (['Zorromix', 'Barathrûm'], 'wrong')])
        self.assertIn('made 5, not 4', fails[0]['detail'])
        self.assertIn('made 7 (5 + 2), not 4', fails[1]['detail'])                  # a known 5: the other was a 2
        # Running out alone isn't on them (their match may have gone into a wrong pair): a note, never a fail
        notes = bossmech.notes(self.analysis(), self.mech)
        self.assertEqual([n['players'] for n in notes], [['Haldrik']])
        self.assertIn('had no match left - it ran out after 28 s (not counted', notes[0]['detail'])
        self.assertEqual(bossmech.uses(self.analysis(), self.mech, 'Moerade'), 1)    # matched right
        self.assertEqual(bossmech.uses(self.analysis(), self.mech, 'Zorromix'), 0)

    def test_both_sentinels_mechanics_make_it_to_work_on(self):
        """Failing Protovenom and Helical Toxins on the same boss: two separate things to work on, not one."""
        from raidanalysis import coach
        tips = [dict(coach._insight('bad', 90, 'boss_mechanic', t), mechanic=m, boss='Entombed Sentinels', score=90)
                for t, m in (('rings', 'protovenom'), ('toxins', 'helical'))]
        tips.append(dict(coach._insight('bad', 50, 'rotation', 'x'), boss='Entombed Sentinels', score=50))
        picked = coach._pick(tips, 'bad', 3)
        self.assertEqual({i['text'] for i in picked}, {'rings', 'toxins', 'x'})

    def test_night_summary_shows_the_unmatched_without_blaming(self):
        from raidanalysis.web import insights
        a = dict(self.analysis(), _duration=200000, abilities=[])
        for p in a['players']:
            p.update({'class': 'Mage', 'role': 'dps'})
        html = insights.build([{'number': 9, 'fight_id': 9, 'kill': False, 'reason': None, 'phases': [], 'analysis': a}],
                              {}, lambda i, n: None, 'x')
        self.assertIn('Helical Toxins: matched wrong', html)
        self.assertIn('<h4>Also</h4>', html)
        self.assertIn('had no match left', html)
        who = html[html.index('Who failed it'):html.index('<h4>When</h4>')]
        self.assertNotIn('Haldrik', who)                                            # not in the blame chart

    def test_coaching(self):
        from raidanalysis import coach
        numbered = [(9, {'analysis': self.analysis()})]
        tip = {i['text'] for i in coach.boss_mechanic_insights(3445, numbered, 'Zorromix')}
        self.assertTrue(any('You matched wrong on Helical Toxins 2 times' in t and 'with Asiriel (5), Barathrûm (7)' in t
                            and 'a 2 goes with a 2, a 1 with a 3' in t for t in tip))
        self.assertFalse([i for i in coach.boss_mechanic_insights(3445, numbered, 'Haldrik') if i['tone'] == 'bad'])
        wrong = next(i for i in coach.boss_mechanic_insights(3445, numbered, 'Asiriel') if i['tone'] == 'bad')
        self.assertEqual(wrong['ability'], {'id': 1284590, 'name': 'Helical Toxins'})
        good = coach.boss_mechanic_insights(3445, numbered, 'Moerade')
        self.assertIn('Helical Toxins: matched right every time (1×)', {i['text'] for i in good})


class TestProtovenomCollision(unittest.TestCase):
    """Entombed Sentinels, a real pull: two pairs clear their rings together; Azzazel runs into Qeek, then Mangor."""

    def setUp(self):
        from raidanalysis import bossmech
        self.mech = next(m for m in bossmech.for_encounter(3445) if m.key == 'protovenom')
        people = ['Mangor', 'Scrumsh', 'Azzazel', 'Boopsboops', 'Qeek', 'Mageblazee', 'Alliuda', 'Stonasloth']
        self.names = {i: n for i, n in enumerate(people, 1)}
        self.names[99] = 'Vashnik'
        self.ids = {n: i for i, n in self.names.items()}
        self.roster = set(people)

    def ring(self, t, who, kind='applydebuff'):
        return {'timestamp': t, 'type': kind, 'sourceID': 99, 'targetID': self.ids[who]}

    def hit(self, t, who, x, y):
        return {'timestamp': t, 'type': 'damage', 'sourceID': 99, 'targetID': self.ids[who], 'x': x, 'y': y}

    def data(self):
        rings = [self.ring(36560, n) for n in ('Mangor', 'Scrumsh')] + \
                [self.ring(38710, n, 'removedebuff') for n in ('Mangor', 'Scrumsh')] + \
                [self.ring(101570, n) for n in ('Azzazel', 'Boopsboops')]               # these two never pair up
        eruptions = [self.hit(103390, 'Qeek', 34545, 70579), self.hit(103390, 'Boopsboops', 35180, 70128),
                     self.hit(103390, 'Azzazel', 34481, 70936),                         # Qeek 3.6 yd from Azzazel
                     self.hit(104370, 'Scrumsh', 33269, 70402), self.hit(104370, 'Mageblazee', 32147, 71473),
                     self.hit(104370, 'Mangor', 32701, 70646), self.hit(104370, 'Alliuda', 32929, 69805),
                     self.hit(104370, 'Azzazel', 32758, 70709),                         # Mangor 0.8 yd away
                     self.hit(104440, 'Azzazel', 32758, 70709),                         # same burst, logged again
                     self.hit(160000, 'Stonasloth', 30000, 70000)]                      # no ring in it: not a collision
        return self.mech.collect({'rings': rings, 'eruptions': eruptions}, 0, self.names, self.roster)

    def test_who_ran_into_whom(self):
        data = self.data()
        self.assertEqual([c[1:3] for c in data['collisions']], [['Azzazel', 'Qeek'], ['Azzazel', 'Mangor']])
        self.assertEqual([c[3] for c in data['collisions']], [3.6, 0.8])
        analysis = {'players': [{'name': n} for n in self.roster], 'deaths': [], 'boss_mechanics': {'protovenom': data}}
        from raidanalysis import bossmech
        fails = bossmech.failures(analysis, self.mech)
        self.assertEqual(fails[0]['players'], ['Azzazel', 'Qeek'])
        self.assertIn('Azzazel had the red ring, Qeek didn\'t (3 players caught in the eruption)', fails[0]['detail'])
        self.assertEqual(bossmech.uses(analysis, self.mech, 'Mangor'), 1)              # paired cleanly
        self.assertEqual(bossmech.uses(analysis, self.mech, 'Azzazel'), 0)

    def test_coaching_per_side(self):
        from raidanalysis import coach
        numbered = [(4, {'analysis': {'players': [{'name': n} for n in self.roster], 'deaths': [],
                                      'boss_mechanics': {'protovenom': self.data()}}})]
        ring = coach.boss_mechanic_insights(3445, numbered, 'Azzazel')[0]['text']
        self.assertIn('With the red ring you ran into players without one 2 times', ring)
        self.assertIn("calm down, don't run people over", ring)
        bumped = coach.boss_mechanic_insights(3445, numbered, 'Qeek')[0]['text']
        self.assertIn('You got run into by a red ring 1 time (#4 at 1:43: Azzazel)', bumped)
        self.assertIn('part the sea', bumped)
        both = coach.boss_mechanic_insights(3445, numbered, 'Mangor')[0]          # paired once, run into once
        self.assertEqual(both['tone'], 'bad')
        self.assertIn('got run into by a red ring', both['text'])
        self.assertEqual(coach.boss_mechanic_insights(3445, numbered, 'Scrumsh')[0]['tone'], 'good')

    def test_clip_goes_with_it(self):
        """Mythic Trap's Shifting Protovenom clip on the night's line and on the player's tip."""
        from raidanalysis import coach
        from raidanalysis.web import insights
        guide = {'name': 'Shifting Protovenom', 'video_url': 'https://assets2.mythictrap.com/v.mp4', 'tip': 'Touch',
                 'embed_url': 'https://www.mythictrap.com/en/embed-ability/venomous-abyss/entombed-sentinels/entsentShiPro'}
        analysis = {'players': [{'name': n, 'class': 'Mage', 'role': 'dps'} for n in self.roster], 'deaths': [],
                    'boss_mechanics': {'protovenom': self.data()}, '_duration': 200000, 'abilities': []}
        seen = []

        def guide_for(i, n):
            seen.append((i, n))
            return guide if (i, n) == (1296878, 'Shifting Protovenom') else None
        html = insights.build([{'number': 4, 'fight_id': 4, 'kill': False, 'reason': None, 'phases': [],
                                'analysis': analysis}], {}, guide_for, 'x')
        self.assertIn('entsentShiPro', html)
        tip = coach.boss_mechanic_insights(3445, [(4, {'analysis': analysis})], 'Qeek')[0]
        self.assertEqual(tip['ability'], {'id': 1296878, 'name': 'Shifting Protovenom'})


class TestMushroomBounce(unittest.TestCase):
    """The Lost Explorers: two pulls from the log - Naautilus alone 0.5 s after it appeared; the raid 23 s later."""
    MUSHROOM = 99

    def events(self, start, appear_ms, bounces):
        """The log's "Bounce" events: the mushroom gaining and casting it as it appears, then players afflicted."""
        ev = [{'timestamp': start + appear_ms, 'type': t, 'sourceID': self.MUSHROOM, 'targetID': tgt}
              for t, tgt in (('applybuff', self.MUSHROOM), ('cast', -1), ('applybuff', self.MUSHROOM))]
        for ms, who in bounces:
            ev.append({'timestamp': start + ms, 'type': 'applydebuff', 'sourceID': self.MUSHROOM, 'targetID': who})
            ev.append({'timestamp': start + ms + 1500, 'type': 'removedebuff', 'sourceID': self.MUSHROOM,
                       'targetID': who})
        return ev

    def setUp(self):
        self.names = {i: f'P{i}' for i in range(1, 21)}
        self.names.update({1: 'Naautilus', 2: 'Futhark', self.MUSHROOM: 'Bouncy Mushroom'})
        self.roster = {n for i, n in self.names.items() if i != self.MUSHROOM}

    def analysis(self, data, deaths=()):
        return {'players': [{'name': n} for n in sorted(self.roster)], 'deaths': [{'t': t} for t in deaths],
                'boss_mechanics': {'mushroom': data}}

    def test_alone_right_after_it_appeared_fails(self):
        from raidanalysis import bossmech
        mech = bossmech.for_encounter(3497)[0]
        early = mech.collect({'bounce': self.events(0, 81109, [(81595, 1)])}, 0, self.names, self.roster)
        self.assertEqual(early, [[81109, ['Naautilus'], 81595]])                    # the mushroom's own events aren't bounces
        self.assertEqual(bossmech.failures(self.analysis(early), mech), [{
            't': 81595, 'players': ['Naautilus'],
            'detail': 'bounced 0.5 s after the mushroom appeared, alone - it was gone before the rest could'}])
        together = mech.collect({'bounce': self.events(0, 81046, [(104494 + 100 * i, i) for i in range(2, 12)])}, 0,
                                self.names, self.roster)
        self.assertEqual(len(together[0][1]), 10)
        self.assertEqual(bossmech.failures(self.analysis(together), mech), [])     # the raid together: fine
        # Three left standing after a wipe bouncing isn't failing it
        self.assertEqual(bossmech.failures(self.analysis(early, deaths=[1000] * 15), mech), [])
        self.assertIsNone(bossmech.failures({'players': []}, mech))                 # analyzed before the check

    def test_my_performance(self):
        """Failing it is a top "work on" for the one who went early; the others get a small "going well"."""
        from raidanalysis import coach
        numbered = [(3, {'analysis': self.analysis([[81109, ['Naautilus'], 81595]])}),
                    (4, {'analysis': self.analysis([[81046, ['Naautilus', 'P3', 'P4', 'P5'], 104494]])})]
        bad = coach.boss_mechanic_insights(3497, numbered, 'Naautilus')
        self.assertEqual((bad[0]['tone'], bad[0]['impact'], bad[0]['kind']), ('bad', 90, 'boss_mechanic'))
        self.assertIn('You bounced on the mushroom too early in 1 pull (#3 at 1:21', bad[0]['text'])
        good = coach.boss_mechanic_insights(3497, numbered, 'P3')
        self.assertEqual((good[0]['tone'], good[0]['text']), ('good', 'Mushroom bounce: with the raid every time (1×), never too early'))
        self.assertEqual(coach.boss_mechanic_insights(1234, numbered, 'P3'), [])     # another boss: nothing

    def test_night_summary(self):
        from raidanalysis.web import insights

        def pull(n, data):
            return {'number': n, 'fight_id': n, 'kill': False, 'reason': None, 'phases': [],
                    'analysis': dict(self.analysis(data), _duration=150000, abilities=[])}
        html = insights.build([pull(1, [[81109, ['Naautilus'], 81595]]), pull(2, [[81046, ['P3', 'P4', 'P5', 'P6'], 104494]])],
                              {}, lambda i, n: None, 'x')
        self.assertIn('Failed the mushroom (went too early) — <strong>1 pull</strong>', html)
        self.assertIn('bounced 0.5 s after the mushroom appeared, alone', html)
        self.assertIn('Naautilus', html)


class TestSameNameMechanics(unittest.TestCase):
    """The Lost Explorers: Shell Spin only stuns (0-damage hits), Evil Eyes is logged under two spell ids."""

    def fight(self):
        from raidanalysis import analyzer
        roster_actors = [{'id': i, 'name': n, 'type': 'Player'} for i, n in ((1, 'Aedrios'), (2, 'Mangor'))]
        tables = {'playerDetails': {'dps': [{'name': 'Aedrios', 'type': 'Warrior', 'specs': [{'spec': 'Arms'}]}],
                                    'tanks': [{'name': 'Mangor', 'type': 'Monk', 'specs': [{'spec': 'Brewmaster'}]}]},
                  'damageTaken': {'entries': [
                      {'guid': 1291918, 'name': 'Shell Spin', 'total': 0, 'hitCount': 3, 'actorType': 'NPC'},
                      {'guid': 1292764, 'name': 'Evil Eyes', 'total': 800, 'hitCount': 2, 'actorType': 'NPC'},
                      {'guid': 1292758, 'name': 'Evil Eyes', 'total': 0, 'hitCount': 0, 'actorType': 'NPC'}]}}
        ev = [{'type': 'damage', 'timestamp': 1000 + t, 'targetID': who, 'abilityGameID': aid, 'amount': amt,
               'hitType': ht} for t, who, aid, amt, ht in [
            (5000, 1, 1291918, 0, 1), (9000, 1, 1291918, 0, 1),            # stunned twice: 0 damage, landed
            (9500, 2, 1291918, 0, 10),                                     # immune: not a hit
            (7000, 1, 1292764, 400, 1), (8000, 2, 1292764, 400, 1)]]
        fight = {'id': 1, 'startTime': 1000, 'endTime': 301000, 'kill': False, 'size': 2}
        return analyzer.analyze_fight(fight, roster_actors, tables, ev, [], set(), set())

    def test_stun_only_hits_count(self):
        from raidanalysis import analyzer
        shell = next(a for a in self.fight()['abilities'] if a['name'] == 'Shell Spin')
        self.assertEqual(analyzer.mistake_counts(shell), {'Aedrios': 2})
        tags = {1291918: analyzer.TAG_AVOIDABLE}
        self.assertEqual(analyzer.avoidable_by_player(self.fight(), tags)['Aedrios']['hits'], 2)

    def test_same_name_is_one_mechanic(self):
        from raidanalysis import analyzer
        analysis = self.fight()
        eyes = [a for a in analysis['abilities'] if a['name'] == 'Evil Eyes']
        self.assertEqual(len(eyes), 1)
        self.assertEqual((eyes[0]['id'], eyes[0]['ids'], eyes[0]['total']), (1292764, [1292758, 1292764], 800))
        self.assertEqual(analyzer.annotate_deaths(analysis)['abilities'], analysis['abilities'])  # idempotent
        # Two pulls where a different id did the damage: still one row overall
        other = dict(analysis, abilities=[dict(eyes[0], id=1292758, ids=[1292758])])
        merged = analyzer.merge_pulls([analysis, other])
        self.assertEqual(len([a for a in merged['abilities'] if a['name'] == 'Evil Eyes']), 1)
        # ...and one row (hits added up) on a player's page - the player report keys mechanics by name too
        tags = {1292758: analyzer.TAG_AVOIDABLE, 1292764: analyzer.TAG_AVOIDABLE}
        report = {r['name']: r for r in analyzer.player_report(
            [{'number': i, 'kill': False, 'analysis': dict(a, _duration=300000)}
             for i, a in enumerate((self.fight(), other), 1)], tags)}
        eyes_rows = [a for a in report['Aedrios']['avoidable'].values() if a['name'] == 'Evil Eyes']
        self.assertEqual([a['hits'] for a in eyes_rows], [2])

    def test_fetched_with_nobody_hit_is_complete(self):
        """Evil Eyes' cast id was fetched and nobody took it: a real zero, not "unknown" - the merge stays complete."""
        from raidanalysis import analyzer
        a = self.fight_with(event_ids={1291918, 1292764, 1292758})
        eyes = next(x for x in a['abilities'] if x['name'] == 'Evil Eyes')
        self.assertTrue(eyes['complete'])
        self.assertEqual(analyzer.mistake_counts(eyes), {'Aedrios': 1, 'Mangor': 1})

    def test_stuns_count_from_the_debuff(self):
        """Shell Spin's shells stun for 0 damage: each debuff landing on a player is a hit."""
        from raidanalysis import analyzer
        debuffs = [{'type': 'applydebuff', 'timestamp': 1000 + t, 'targetID': who, 'abilityGameID': 1291920,
                    'abilityName': 'Shell Spin'} for t, who in ((20000, 1), (60000, 1), (61000, 2))]
        a = self.fight_with(event_ids={1291918}, damage=False, debuffs=debuffs)
        shell = next(x for x in a['abilities'] if x['name'] == 'Shell Spin')
        self.assertTrue(shell['complete'])
        self.assertEqual(analyzer.mistake_counts(shell), {'Aedrios': 2, 'Mangor': 1})
        self.assertEqual(shell['players']['Aedrios']['times'], [20000, 60000])

    def fight_with(self, event_ids=None, damage=True, debuffs=()):
        from raidanalysis import analyzer
        actors = [{'id': 1, 'name': 'Aedrios', 'type': 'Player'}, {'id': 2, 'name': 'Mangor', 'type': 'Player'}]
        tables = {'playerDetails': {'dps': [{'name': 'Aedrios', 'type': 'Warrior', 'specs': [{'spec': 'Arms'}]}],
                                    'tanks': [{'name': 'Mangor', 'type': 'Monk', 'specs': [{'spec': 'Brewmaster'}]}]},
                  'damageTaken': {'entries': [
                      {'guid': 1291918, 'name': 'Shell Spin', 'total': 0, 'hitCount': 3, 'actorType': 'NPC',
                       'targets': [{'name': 'Aedrios', 'total': 0}]},
                      {'guid': 1292764, 'name': 'Evil Eyes', 'total': 800, 'hitCount': 2, 'actorType': 'NPC'},
                      {'guid': 1292758, 'name': 'Evil Eyes', 'total': 0, 'hitCount': 0, 'actorType': 'NPC',
                       'targets': [{'name': 'Aedrios', 'total': 0}]}]}}
        ev = [{'type': 'damage', 'timestamp': 1000 + t, 'targetID': who, 'abilityGameID': aid, 'amount': 400,
               'hitType': 1} for t, who, aid in ((7000, 1, 1292764), (8000, 2, 1292764))] if damage else []
        fight = {'id': 1, 'startTime': 1000, 'endTime': 301000, 'kill': False, 'size': 2}
        return analyzer.annotate_deaths(analyzer.analyze_fight(fight, actors, tables, ev, [], set(), set(),
                                                               event_ids=event_ids, debuff_events=debuffs))

    def test_tagged_mechanics_fetched_first_and_in_full(self):
        """Tagged mechanics (every id of their name) get a request of their own; a capped request isn't complete."""
        import asyncio
        from unittest import mock
        from raidanalysis import sync
        tables = {'damageTaken': {'entries': [
            {'guid': 1, 'name': 'Shell Spin', 'total': 0, 'hitCount': 3, 'actorType': 'NPC'},
            {'guid': 2, 'name': 'Evil Eyes', 'total': 10, 'hitCount': 900, 'actorType': 'NPC'},   # big, but tagged
            {'guid': 3, 'name': 'Evil Eyes', 'total': 0, 'hitCount': 0, 'actorType': 'NPC'},     # its other id
            {'guid': 4, 'name': 'Raid Pulse', 'total': 99, 'hitCount': 9000, 'actorType': 'NPC'},  # big, untagged
            {'guid': 5, 'name': 'Small Thing', 'total': 5, 'hitCount': 3, 'actorType': 'NPC'}]}}
        calls = []

        async def events(session, code, fid, kind, flt, max_events=20000, hostility='Friendlies'):
            calls.append((kind, flt))
            return [{}] * (max_events if '5' in flt else 1)                            # the small request: capped

        async def abilities(session, code):
            return {}
        with mock.patch('raidanalysis.guides.effective_tags', return_value=({1: 'avoidable', 2: 'avoidable'}, {})), \
                mock.patch('raidanalysis.wcl.get_events', events), \
                mock.patch('raidanalysis.wcl.get_report_abilities', abilities):
            _, complete, _ = asyncio.run(sync._mechanic_events(None, 'x', {'id': 1, 'encounterID': 9}, tables))
        self.assertEqual(calls[0], ('DamageTaken', 'ability.id in (1,2,3)'))          # tagged, by name, whatever size
        self.assertEqual(calls[1], ('DamageTaken', 'ability.id in (5)'))              # small untagged; not the pulse
        self.assertEqual(calls[2], ('Debuffs', 'type = "applydebuff" and ability.name in ("Shell Spin")'))
        self.assertEqual(complete, {1, 2, 3})                                          # the capped one isn't

    def test_partial_detail_is_a_floor_not_nobody(self):
        """One pull with the per-hit detail, one without: the known hits plus at least one - never "nobody"."""
        import re
        from raidanalysis import analyzer
        from raidanalysis.web import insights

        def pull(n, hits):
            return {'number': n, 'fight_id': n, 'kill': False, 'reason': None, 'phases': [],
                    'analysis': {'_duration': 300000, 'deaths': [],
                                 'players': [{'name': 'Aedrios', 'class': 'Warrior', 'role': 'dps'}],
                                 'abilities': [{'id': 7, 'name': 'Blast Wave', 'total': 500, 'events': 9,
                                                'players': {'Aedrios': {'damage': 500, 'hits': hits}},
                                                'complete': hits is not None}]}}
        tags = {7: analyzer.TAG_AVOIDABLE}
        html = insights.build([pull(1, 3), pull(2, None)], tags, lambda i, n: None, 'x')
        self.assertIn('Hit by <strong>Blast Wave</strong> <strong>at least 3 times</strong>', html)
        self.assertNotIn('Nobody got hit', html)
        self.assertEqual(analyzer.avoidable_by_player(pull(2, None)['analysis'], tags)['Aedrios']['hits'], 1)
        self.assertIn('<strong>6 times</strong>', insights.build([pull(1, 3), pull(2, 3)], tags, lambda i, n: None, 'x'))

    def test_tags_cover_every_id_of_a_name(self):
        from raidanalysis import analyzer, guides
        guide = [{'spell_id': 1292388, 'name': 'Evil Eyes', 'category': 'Dodge', 'subtitle': 'Swirlies'}]
        shares = {1292764: {'name': 'Evil Eyes', 'share': 0.2}, 1292758: {'name': 'Evil Eyes', 'share': 0}}
        auto = guides.auto_tags(guide, shares)
        self.assertEqual(auto, {1292764: analyzer.TAG_AVOIDABLE, 1292758: analyzer.TAG_AVOIDABLE})
        names = {i: v['name'] for i, v in shares.items()}
        # An officer's call on one id covers its sibling; the newest call wins
        rows = [{'ability_id': 1292758, 'ability_name': 'Evil Eyes', 'tag': 'ignore'},
                {'ability_id': 1292764, 'ability_name': 'Evil Eyes', 'tag': 'avoidable'}]
        tags, sources = guides.name_tags(auto, names, rows)
        self.assertEqual((tags[1292764], sources[1292764]), ('ignore', 'manual'))
        cleared, _ = guides.name_tags(auto, names, [{'ability_id': 1292764, 'ability_name': 'Evil Eyes', 'tag': 'none'}])
        self.assertNotIn(1292758, cleared)                                         # cleared for both ids


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
    """Shiv that nobody cast is a real zero (not talented); Shiv that was cast but not fetched needs a re-analyze."""

    def test_real_zero_vs_unknown(self):
        from raidanalysis import benchmarks
        spells = {5938: {'name': 'Shiv', 'meta': 'Instant · 30 sec cooldown'},
                  1: {'name': 'Deathmark', 'meta': 'Instant · 2 min cooldown'}}
        top = [{'duration': 300000, 'phases': [], 'casts': [[30000, 5938], [40000, 1]]} for _ in range(5)]
        base = {'number': 1, 'duration': 300000, 'phases': [], 'casts': [[41000, 1]], 'cast_ids': {1}}
        not_talented = dict(base, casts_seen={1, 77})        # no Shiv anywhere in the log
        not_fetched = dict(base, casts_seen={1, 77, 5938})   # Shiv was cast, we just didn't keep it
        shiv = lambda pull: next(r for r in benchmarks.compare([pull], top, spells) if r['name'] == 'Shiv')
        self.assertEqual((shiv(not_talented)['known'], shiv(not_talented)['verdict']), (True, 'not_taken'))
        self.assertEqual((shiv(not_fetched)['known'], shiv(not_fetched)['verdict']), (False, None))


class TestCastsPerMinuteOveruse(unittest.TestCase):
    """4.6 Slams a minute where the top Arms Warriors press 1.7: not "on par" - it's crowding out better spells."""

    def test_pressed_far_more_than_the_top(self):
        from raidanalysis import throughput
        minute = 60000
        pull = (1, {'analysis': {'extras': {'detail': True, 'duration': 10 * minute, 'players': {
            'Aedrios': {'casts': {'Slam': 46, 'Mortal Strike': 50, 'Overpower': 30, 'Execute': 26}}}}}})
        top = [{'duration': 10 * minute, 'cast_names': {'Slam': 17, 'Mortal Strike': 50, 'Overpower': 18,
                                                        'Execute': 17}}] * 5
        rows = {a['name']: a for a in throughput.cpm([pull], 'Aedrios', top)['abilities']}
        self.assertEqual(rows['Slam']['verdict'], 'way_over')                       # 2.7x, +2.9 a minute
        self.assertEqual(rows['Overpower']['verdict'], 'over')                      # 1.7x, +1.2 a minute
        self.assertEqual(rows['Execute']['verdict'], 'good')                        # 1.5x but only +0.9 a minute
        self.assertEqual(rows['Mortal Strike']['verdict'], 'good')

    def test_small_rates_are_noise(self):
        from raidanalysis import throughput
        self.assertEqual(throughput._cpm_verdict(0.6, 0.3, overuse=True), 'good')   # 2x, but only +0.3 a minute
        self.assertEqual(throughput._cpm_verdict(4.6, 1.7), 'good')                 # overall: more is never bad


class TestTalents(unittest.TestCase):
    """A Mistweaver on Rushing Wind Kick, without Healing Elixir: neither is held against them - and per pull."""

    def catalog(self):
        from raidanalysis import gamedata
        entries = ('ID,TraitDefinitionID,MaxRanks,NodeEntryType,TraitSubTreeID\n'
                   '1,11,1,1,0\n2,12,1,1,0\n3,13,1,1,0\n5,15,1,1,0\n9,19,1,1,0\n')
        definitions = ('OverrideName_lang,OverrideSubtext_lang,OverrideDescription_lang,ID,SpellID,OverrideIcon,'
                       'OverridesSpellID,VisibleSpellID\n'
                       ',,,11,107428,0,0,0\n,,,12,467307,0,107428,0\n,,,13,122281,0,0,0\n,,,15,1260511,0,0,0\n'
                       ',,,19,191427,0,0,0\n')
        node_entries = 'ID,TraitNodeID,TraitNodeEntryID,_Index\n1,101,1,0\n2,102,2,0\n3,103,3,0\n4,105,5,0\n5,109,9,0\n'
        nodes = 'ID,TraitTreeID,PosX,PosY,Type,Flags,TraitSubTreeID\n101,1000,0,0,0,0,0\n102,1000,0,0,0,0,0\n' \
                '103,1000,0,0,0,0,0\n105,1000,0,0,0,0,0\n109,2000,0,0,0,0,0\n'
        names = ('ID,Name_lang\n107428,Rising Sun Kick\n467307,Rushing Wind Kick\n122281,Healing Elixir\n'
                 '1260511,Spiritfont\n191427,Metamorphosis\n116670,Vivify\n')
        rows = gamedata.talent_rows(entries, definitions, node_entries, nodes, names)
        self.assertIn((2, 1000, 'Rushing Wind Kick', 'Rising Sun Kick'), rows)
        return gamedata.catalog_from([dict(zip(('entry_id', 'tree_id', 'name', 'overrides'), r)) for r in rows])

    def test_talents_from_combatantinfo(self):
        events = [{'type': 'combatantinfo', 'sourceID': 1,
                   'talentTree': [{'id': 1, 'rank': 1, 'nodeID': 101}, {'id': 3, 'rank': 0, 'nodeID': 103}]},
                  {'type': 'combatantinfo', 'sourceID': 2}]  # no talents logged
        self.assertEqual(analyzer.talent_entries({1: 'Boops', 2: 'Other'}, {'Boops', 'Other'}, events), {'Boops': [1]})

    def test_missing_abilities_per_pull(self):
        from raidanalysis import gamedata
        catalog = self.catalog()
        # Rushing Wind Kick takes Rising Sun Kick's place; Metamorphosis is another class's tree - not theirs
        rwk = gamedata.missing_abilities([1, 2], catalog)
        self.assertEqual(rwk.missing, {'Rising Sun Kick', 'Healing Elixir', 'Spiritfont'})
        self.assertNotIn('Vivify', rwk.known)  # baseline: never "not talented"
        # Talents change between pulls: only what they had in none of them is missing
        pull = lambda n, entries: (n, {'analysis': {'talents': {'Boops': entries}}})  # noqa: E731
        talents = gamedata.not_taken([pull(1, [1, 2]), pull(2, [1, 3]), pull(3, None)], 'Boops', catalog)
        self.assertEqual(talents.missing, {'Spiritfont'})
        self.assertIsNone(gamedata.not_taken([pull(1, None)], 'Boops', catalog))  # nothing to go on
        self.assertIsNone(gamedata.not_taken([pull(1, [777])], 'Boops', catalog))  # ids the catalog doesn't know

    def test_uptime_and_hots_of_talents_not_taken(self):
        from raidanalysis import throughput
        from raidanalysis.gamedata import Talents
        me = {'auras': [], 'casts': {'Vivify': 50}, 'on_others': []}
        numbered = [(1, {'fight_id': 1, 'start_ms': 0, 'end_ms': 300000,
                         'analysis': {'extras': {'duration': 300000, 'players': {'Boops': me}}}})]
        top = [{'duration': 300000, 'auras': [{'id': 1, 'name': 'Healing Elixir', 'kind': 'buff', 'uptime': 200000}],
                'cast_names': {'Healing Elixir': 5}, 'on_others': [{'id': 2, 'name': 'Spiritfont', 'uptime': 600000}]}
               for _ in range(5)]
        # Talents unknown: never up and never cast - most likely not talented, no verdict
        up = throughput.uptime(numbered, 'Boops', top)
        self.assertEqual([(u['name'], u['not_taken'], u['verdict']) for u in up], [('Healing Elixir', True, None)])
        hots = throughput.on_others_rows(numbered, 'Boops', top)
        self.assertEqual([(h['name'], h['not_taken'], h['verdict']) for h in hots], [('Spiritfont', True, None)])
        # Their talents say they had both: zero is a real miss
        had = Talents(frozenset(), frozenset({'Healing Elixir', 'Spiritfont'}))
        self.assertEqual(throughput.uptime(numbered, 'Boops', top, talents=had)[0]['verdict'], 'off')
        self.assertEqual(throughput.on_others_rows(numbered, 'Boops', top, talents=had)[0]['verdict'], 'off')
        skipped = Talents(frozenset({'Healing Elixir'}), frozenset({'Healing Elixir'}))
        self.assertTrue(throughput.uptime(numbered, 'Boops', top, talents=skipped)[0]['not_taken'])
        # A sliver of it (0.3% - "up 0% of the fight") without talents to go on: still not taken, nothing to coach
        me['auras'] = [{'id': 1, 'name': 'Healing Elixir', 'kind': 'buff', 'uptime': 900, 'bands': []}]
        row = throughput.uptime(numbered, 'Boops', top)[0]
        self.assertEqual((row['not_taken'], row['verdict']), (True, None))
        me['auras'] = [{'id': 1, 'name': 'Healing Elixir', 'kind': 'buff', 'uptime': 30000, 'bands': []}]  # 10%: had it
        self.assertEqual(throughput.uptime(numbered, 'Boops', top)[0]['verdict'], 'off')

    def test_my_performance_agrees_with_the_rotation_tab(self):
        """The Discord coach looks at the whole night: a sliver of a buff in one pull isn't "had the talent"."""
        from raidanalysis import coach, throughput
        def pull(n, uptime):
            me = {'auras': [{'id': 1, 'name': 'Predictive Training', 'kind': 'buff', 'uptime': uptime, 'bands': []}]
                  if uptime else [], 'casts': {'Keg Smash': 40}, 'on_others': []}
            return (n, {'fight_id': n, 'start_ms': 0, 'end_ms': 300000,
                        'analysis': {'extras': {'duration': 300000, 'players': {'Mangor': me}}}})
        night = [pull(1, 900), pull(2, 0), pull(3, 0)]  # up 0.3% of one pull - "0% of the fight"
        top = [{'duration': 300000, 'auras': [{'id': 1, 'name': 'Predictive Training', 'kind': 'buff', 'uptime': 261000}],
                'cast_names': {'Keg Smash': 40}, 'on_others': []} for _ in range(5)]
        data = {'top': top, 'label': 'Brewmaster Monks', 'rows': [], 'player': {'class': 'Monk'}, 'talents': None}
        tips = coach.rotation_insights(night, 'Mangor', 'tank', data, frozenset({1}))
        self.assertFalse([t for t in tips if t['kind'] == 'uptime'])
        self.assertTrue(all(r['not_taken'] for r in throughput.uptime(night, 'Mangor', top, frozenset({1}))))


class TestForTheRaid(unittest.TestCase):
    """The player page's "For the raid" strip only counts what helped someone else."""

    def test_self_only_spells_dont_count(self):
        from raidanalysis import benchmarks, cooldowns
        from raidanalysis.web import players
        use = lambda ab, tgt=None: {'t': 1, 'name': 'Azzazel', 'ability': ab, 'ability_id': 1, 'icon': '', 'target': tgt}
        numbered = [(1, {'analysis': {'cooldowns': [
            use("Spiritwalker's Grace"), use("Spiritwalker's Grace"),        # only lets them cast while moving
            use('Power Infusion'),                                            # on themselves
            use('Power Infusion', 'Futhark'),                                 # on someone else: counts
            use('Blessing of Freedom'),                                       # on themselves
            use('Blessing of Freedom', 'Mangor'),                             # on the tank: counts
            use('Bloodlust')]}})]                                             # raid-wide: counts
        tiles = {t['label']: t for t in players.raid_tiles(numbered, 'Azzazel')}
        self.assertEqual(set(tiles), {'Power Infusion', 'Blessing of Freedom', 'Bloodlust'})
        self.assertEqual((tiles['Power Infusion']['value'], tiles['Power Infusion']['sub']), ('1×', '→ Futhark'))
        self.assertEqual(tiles['Blessing of Freedom']['value'], '1×')
        self.assertNotIn("Spiritwalker's Grace", cooldowns.COOLDOWNS)
        self.assertIsNone(benchmarks.category(1, {'name': "Spiritwalker's Grace", 'meta': '2 min cooldown'}))

    def test_landings_decide_for_self_casts(self):
        """
        From a real log: Alliuda's Power Infusion on Futhark (the talent echoes a cast on herself 12 ms later) - one;
        a self-cast PI the talent sent to Arvidkk - counts; Stonasloth's Freedom, logged on himself, landing on
        Futhark - counts; a self-cast that landed on nobody else - doesn't.
        """
        from raidanalysis.web import players
        pi = lambda t, tgt=None: {'t': t, 'name': 'Alliuda', 'ability': 'Power Infusion', 'ability_id': 10060,
                                  'icon': '', 'target': tgt}
        numbered = [(1, {'analysis': {
            'cooldowns': [pi(1000, 'Futhark'), pi(1012), pi(60000), pi(120000)],
            'buffs_given': [[1001, 'Alliuda', 'Futhark', 'Power Infusion'], [60000, 'Alliuda', 'Arvidkk', 'Power Infusion']]}})]
        tile = next(t for t in players.raid_tiles(numbered, 'Alliuda') if t['label'] == 'Power Infusion')
        self.assertEqual((tile['value'], tile['sub']), ('2×', '→ Futhark, Arvidkk'))
        freedom = [(1, {'analysis': {
            'cooldowns': [{'t': 5000, 'name': 'Stonasloth', 'ability': 'Blessing of Freedom', 'ability_id': 1044,
                           'icon': '', 'target': None}],
            'buffs_given': [[5001, 'Stonasloth', 'Futhark', 'Blessing of Freedom']]}})]
        tile = next(t for t in players.raid_tiles(freedom, 'Stonasloth'))
        self.assertEqual((tile['label'], tile['sub']), ('Blessing of Freedom', '→ Futhark'))


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

    def test_raid_buff_missing(self):
        """Nobody of the class kept the raid buff up: every one of them hears it. Two priests sharing it is fine."""
        from raidanalysis import throughput
        # Cast before the pull (not in its casts): still kept, and the pull says raid buffs are stored
        fort = {'guid': 21562, 'name': 'Power Word: Fortitude', 'totalUptime': 300000}
        per_player = {1: {'buffs': {'auras': [fort]}, 'debuffs': [], 'casts': {'entries': [{'name': 'Smite', 'total': 9}]}}}
        fight = {'id': 1, 'startTime': 0, 'endTime': 300000, 'kill': True}
        tables = {'damageDone': {'entries': []}, 'healing': {'entries': []}}
        extras = throughput.build_extras(fight, [{'name': 'Asiriel', 'class': 'Priest'}], {1: 'Asiriel'}, tables,
                                         per_player, {}, tracked={999})
        self.assertTrue(extras['raid_buffs'])
        self.assertEqual([a['name'] for a in extras['players']['Asiriel']['auras']], ['Power Word: Fortitude'])

        def pull(number, ups, stored=True):
            players = {n: {'auras': [{'id': 21562, 'name': 'Power Word: Fortitude', 'kind': 'buff', 'uptime': u}]
                           if u else []} for n, u in ups.items()}
            ex = {'detail': True, 'duration': 300000, 'players': players}
            if stored:
                ex['raid_buffs'] = True
            return (number, {'analysis': {'extras': ex, 'players': [
                {'name': n, 'class': 'Priest'} for n in ups] + [{'name': 'Aedrios', 'class': 'Warrior'}]}})
        numbered = [pull(1, {'Asiriel': 300000, 'Alliuda': 0}),               # Asiriel's copy: the raid had it
                    pull(2, {'Asiriel': 120000, 'Alliuda': 180000}),          # recast by the other: still all fight
                    pull(3, {'Asiriel': 0, 'Alliuda': 0})]                    # nobody: missing
        buff = throughput.raid_buff(numbered, 'Alliuda', 'Priest')
        self.assertEqual((buff['buff'], buff['missing'], buff['verdict']), ('Power Word: Fortitude', [3], 'off'))
        self.assertEqual([p['share'] for p in buff['pulls']], [1.0, 1.0, 0.0])
        self.assertIsNone(throughput.raid_buff(numbered, 'Alliuda', 'Rogue'))       # no raid buff to bring
        old = [pull(1, {'Asiriel': 0, 'Alliuda': 0}, stored=False)]
        self.assertIsNone(throughput.raid_buff(old, 'Alliuda', 'Priest'))           # before they were kept: no alarm

    def test_raid_buff_lost_to_deaths_isnt_missing(self):
        """Boopsproops cast Blessing of the Bronze before the pull and died later: the raid still had it."""
        from raidanalysis import throughput

        def pull(number, bands=None, uptime=0, died=None, stored=True):
            auras = [{'id': 364342, 'name': 'Blessing of the Bronze', 'kind': 'buff', 'uptime': uptime,
                      'bands': bands or []}] if stored else []
            return (number, {'analysis': {
                'players': [{'name': 'Boopsproops', 'class': 'Evoker'}, {'name': 'Mangor', 'class': 'Monk'}],
                'deaths': [{'name': 'Boopsproops', 't': died}] if died is not None else [],
                'extras': {'detail': True, 'raid_buffs': True, 'duration': 300000,
                           'players': {'Boopsproops': {'auras': auras}, 'Mangor': {'auras': []}}}}})
        numbered = [pull(1, bands=[[0, 95]], uptime=95000, died=95000),          # up from the start, died at 1:35
                    pull(2, uptime=300000),                                      # up all pull (no stretches kept)
                    pull(3, bands=[[90, 300]], uptime=210000),                   # cast a minute and a half in
                    pull(4, stored=False),                                       # never cast
                    pull(5, stored=False, died=4000)]                            # died 4 s in: can't tell
        buff = throughput.raid_buff(numbered, 'Boopsproops', 'Evoker')
        self.assertEqual(buff['missing'], [3, 4])
        self.assertEqual([p['number'] for p in buff['pulls']], [1, 2, 3, 4])      # pull 5 skipped
        self.assertEqual(buff['pulls'][2]['share'], 0.7)                          # had it from 1:30 on

    def test_raid_buff_of_a_caster_who_died_at_0_29(self):
        """
        Entombed Sentinels pull #9: Boopsproops (the only Evoker) had Blessing of the Bronze up from 0:00 and died at
        0:29 - his copy was up 9 % of the 5:28 pull. Synced now it's kept (raid buffs always are) and counts as cast;
        stored before that (dropped as barely up), the early death means "can't tell", never "went without".
        """
        from raidanalysis import throughput
        tables = {'damageDone': {'entries': []}, 'healing': {'entries': []}}
        per_player = {2: {'buffs': {'auras': [{'guid': 381748, 'name': 'Blessing of the Bronze', 'totalUptime': 29416,
                                                'bands': [{'startTime': 0, 'endTime': 29416}]}]},
                          'debuffs': [], 'casts': {'entries': [{'name': 'Living Flame', 'total': 9}]}}}
        fight = {'id': 43, 'startTime': 0, 'endTime': 327673, 'kill': False}
        roster = [{'name': 'Boopsproops', 'class': 'Evoker'}, {'name': 'Mangor', 'class': 'Monk'}]
        extras = throughput.build_extras(fight, roster, {2: 'Boopsproops', 3: 'Mangor'}, tables, per_player, {},
                                         tracked={999})
        self.assertEqual([a['name'] for a in extras['players']['Boopsproops']['auras']], ['Blessing of the Bronze'])
        deaths = [{'name': 'Boopsproops', 't': 29418}]
        new = (9, {'analysis': {'players': roster, 'deaths': deaths, 'extras': extras}})
        self.assertEqual(throughput.raid_buff([new], 'Boopsproops', 'Evoker')['missing'], [])
        old_extras = dict(extras, players={'Boopsproops': {'auras': []}, 'Mangor': {'auras': []}})
        old = (9, {'analysis': {'players': roster, 'deaths': deaths, 'extras': old_extras}})
        self.assertIsNone(throughput.raid_buff([old], 'Boopsproops', 'Evoker'))   # skipped: can't tell

    def test_raid_buffs_are_not_an_uptime_goal(self):
        """Two priests: the other one's Fortitude was up all fight - yours shows 0%. Not a rotation problem."""
        from raidanalysis import throughput
        extras = {'detail': True, 'duration': 300000, 'players': {'Boops': {'auras': [
            {'id': 21562, 'name': 'Power Word: Fortitude', 'kind': 'buff', 'uptime': 0},
            {'id': 194249, 'name': 'Voidform', 'kind': 'buff', 'uptime': 30000}]}}}
        numbered = [(1, {'fight_id': 1, 'analysis': {'extras': extras}})]
        top = [{'duration': 300000, 'cast_names': {'Power Word: Fortitude': 1, 'Voidform': 3},
                'auras': [{'id': 21562, 'name': 'Power Word: Fortitude', 'kind': 'buff', 'uptime': 300000},
                          {'id': 194249, 'name': 'Voidform', 'kind': 'buff', 'uptime': 150000}]}] * 5
        rows = throughput.uptime(numbered, 'Boops', top)
        self.assertEqual([r['name'] for r in rows], ['Voidform'])                   # your own buffs still count
        # ...and the same in "HoTs & buffs on others": the priest who didn't cast it isn't "Low"
        extras['players']['Boops']['on_others'] = [{'id': 21562, 'name': 'Power Word: Fortitude', 'uptime': 0},
                                                   {'id': 17, 'name': 'Power Word: Shield', 'uptime': 300000}]
        for p in top:
            p['on_others'] = [{'id': 21562, 'name': 'Power Word: Fortitude', 'uptime': 300000}]
        self.assertEqual([r['name'] for r in throughput.on_others_rows(numbered, 'Boops', top)], ['Power Word: Shield'])
        self.assertNotIn("Hunter's Mark", throughput.RAID_WIDE_AURAS)               # one per hunter: still theirs


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
        self.assertIn('<span>🧪</span>', html)                                      # no icon in the log: the emoji
        iconned = focusview.timeline(d, pull, 'Boops', color_of, order, [], [dict(potions[0], ability_id=431932,
                                     icon='trade_alchemy_potionc4.jpg')], [])
        self.assertIn('data-spell="431932"', iconned)                               # its Wowhead tooltip
        self.assertIn('<b style="background-image:url(https://assets.rpglogs.com/img/warcraft/abilities/'
                      'trade_alchemy_potionc4.jpg)"></b>', iconned)                 # the potion's own icon
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
        add_cards = focusview.cards(d, color_of, potions, [], {}, {}, 'x', icons,
                                    {'Venomous Heart': 'https://www.wowhead.com/npc=1'})
        self.assertIn('class="npc-zoom" data-src="https://wow.zamimg.com/modelviewer/live/webthumbs/npc/196/143812.webp" '
                      'data-name="Venomous Heart" data-href="https://www.wowhead.com/npc=1"', add_cards)
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

    def test_damage_by_target_portraits_and_links(self):
        """A portrait opens it bigger (#npc-modal); the name opens its Wowhead page in a new tab."""
        from raidanalysis.web import targets
        ranked = [{'name': 'Blightscale Clutch', 'type': 'NPC', 'total': 10, 'main': False, 'pulls': 1, 'complete': True,
                   'players': [{'name': 'Boops', 'class': 'Hunter', 'role': 'dps', 'damage': 10, 'dps': 1, 'share': 1,
                                'pulls': 1}]}]
        thumb = 'https://wow.zamimg.com/modelviewer/live/webthumbs/npc/196/143812.webp'
        html = targets.section(ranked, npc_icons={'Blightscale Clutch': thumb},
                               npc_links={'Blightscale Clutch': 'https://www.wowhead.com/npc=263535'})
        self.assertIn(f'class="npc-zoom" data-src="{thumb}" data-name="Blightscale Clutch"', html)
        self.assertIn('<a class="dt-npc" href="https://www.wowhead.com/npc=263535" target="_blank" rel="noopener"', html)
        plain = targets.section(ranked, npc_links={'Blightscale Clutch': 'https://evil.example/'})
        self.assertNotIn('evil.example', plain)                                    # only Wowhead links
        self.assertNotIn('npc-zoom', plain)                                         # no portrait: nothing to open

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
        side = [dict(adds[0], target='Blightscale Rawling', priority=False)]
        quiet = consumables.timeline([pull], analysis['players'], adds=adds + side)
        self.assertIn('value="add:Blightscale Rawling" data-name="add:Blightscale Rawling">', quiet)  # in the dropdown, off
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
        def pull(n, futhark_parse, kill=False):
            return (n, {'fight_id': n, 'kill': kill, 'start_ms': 0, 'end_ms': 100000, 'analysis': {'players': roster, 'extras': {
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
        # Only wipes so far: their parses, marked as not counting
        self.assertIn('title="Average 75 over 2 wipe parses · best 90 - no kill yet', html)
        self.assertIn('<span class="parse p75 from-wipe"', html)
        self.assertIn('title="No Warcraft Logs parse in these pulls">—', html)      # Boops: none
        # A kill's parse is there: only it counts - the 99 on a quick wipe doesn't
        html = players.compact_table(report, lambda n: '#', [pull(1, 99), pull(2, 40, kill=True)])
        self.assertIn('title="Average 40 over 1 kill parse · best 40"><span class="parse p25">40</span>', html)


class TestKillParsesCount(unittest.TestCase):
    """A 100 on a 20 s wipe isn't a best parse: kill parses count whenever there are any; without, a wipe's - marked."""

    def test_counted_parses(self):
        from raidanalysis import throughput
        from raidanalysis.web.performance import parse_html
        self.assertEqual(throughput.counted_parses([(100, False), (17, True), (22, True), (None, True)]), ([17, 22], False))
        self.assertEqual(throughput.counted_parses([(100, False), (60, False)]), ([100, 60], True))
        self.assertEqual(throughput.counted_parses([(None, False)]), ([], True))
        self.assertIn('from-wipe', parse_html(100, wipe=True))
        self.assertIn('100*', parse_html(100, wipe=True))
        self.assertNotIn('from-wipe', parse_html(100))

    def test_character_best_parse(self):
        from raidanalysis import character
        e = lambda parse, wipe: {'parse': parse, 'parse_wipe': wipe}  # noqa: E731
        # Killed on some night: that night's kill parse is the best, whatever the wipe nights said
        self.assertEqual(character._best_parse([e(100, True), e(17, False), e(30, False)]), ([17, 30], False))
        # Never killed: the wipes', flagged
        self.assertEqual(character._best_parse([e(100, True), e(80, True), e(None, True)]), ([100, 80], True))
        self.assertEqual(character._best_parse([e(None, False)]), ([], False))  # nothing at all: nothing to flag


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


class TestArmory(unittest.TestCase):
    """The Character tab's data: realm slugs, Blizzard's gear or Raider.IO's, the full-body render."""

    def test_realm_slug(self):
        from raidanalysis import armory
        self.assertEqual(armory.realm_slug('TarrenMill'), 'tarren-mill')       # WCL spells realms run together
        self.assertEqual(armory.realm_slug('Tarren Mill'), 'tarren-mill')
        self.assertEqual(armory.realm_slug("Kel'Thuzad"), 'kelthuzad')
        self.assertEqual(armory.realm_slug(None), '')

    def test_gear_from_raiderio_and_render_from_thumbnail(self):
        from raidanalysis import armory
        data = {'raiderio': {'thumbnail_url': 'https://render.worldofwarcraft.com/eu/character/x/0/1-avatar.jpg?alt=y',
                             'gear': {'items': {'head': {'item_id': 1, 'item_level': 321, 'icon': 'inv_helm', 'name': 'Fangs',
                                                         'item_quality': 4, 'enchant': 8017, 'gems': [], 'tier': 'tier'},
                                                'wrist': {'item_id': 2, 'item_level': 331, 'icon': 'inv_bracer', 'name': 'Bracers',
                                                          'item_quality': 4, 'gems': [213]}}}}}
        gear = armory.items(data)
        self.assertEqual((gear['HEAD']['ilvl'], gear['HEAD']['enchant'], gear['HEAD']['tier']), (321, True, True))
        self.assertEqual((gear['WRIST']['enchant'], gear['WRIST']['sockets']), (None, 1))
        self.assertEqual(armory.render_url(data), 'https://render.worldofwarcraft.com/eu/character/x/0/1-main-raw.png')

    def test_blizzard_gear_wins(self):
        from raidanalysis import armory
        data = {'equipped_items': [{'slot': {'type': 'CHEST'}, 'name': 'Vest', 'level': {'value': 321},
                                    'quality': {'type': 'EPIC'}, 'item': {'id': 9},
                                    'enchantments': [{'display_string': 'Enchanted: Crystalline Radiance'}],
                                    'sockets': [{'item': {'name': 'Gem'}}, {}], 'set': {}}],
                'raiderio': {'gear': {'items': {'head': {'name': 'ignored'}}}}}
        gear = armory.items(data)
        self.assertEqual(list(gear), ['CHEST'])
        self.assertEqual((gear['CHEST']['enchant'], gear['CHEST']['gems'], gear['CHEST']['sockets']),
                         ('Crystalline Radiance', ['Gem'], 2))

    def test_tab_flags_missing_enchants(self):
        from raidanalysis.web import armory as view
        data = {'raiderio': {'gear': {'items': {'back': {'item_id': 3, 'item_level': 321, 'icon': 'x', 'name': 'Drape',
                                                         'item_quality': 4}}}}}
        html = view.tab(data, {'name': 'Futhark', 'class': 'Hunter', 'missing_enchants': ['Back']})
        self.assertIn('No enchant', html)
        self.assertIn('https://www.wowhead.com/item=3', html)
        self.assertIn('data-slot="BACK"', html)  # what PAGE_JS compares to light up changed gear
        # Blizzard's per-item icon request failed: Raider.IO's icon for the same item fills in
        from raidanalysis import armory
        blizzard = {'equipped_items': [{'slot': {'type': 'FINGER_1'}, 'name': 'Band of the Amani Warlord',
                                        'item': {'id': 77}, 'level': {'value': 321}, 'quality': {'type': 'EPIC'}},
                                       {'slot': {'type': 'FINGER_2'}, 'name': 'Masterwork Band', 'item': {'id': 78},
                                        'icon_url': 'https://render.worldofwarcraft.com/icons/56/ring.jpg'}],
                    'raiderio': {'gear': {'items': {'finger1': {'item_id': 77, 'icon': 'inv_ring_amani'}}}}}
        gear = armory.items(blizzard)
        self.assertEqual(gear['FINGER_1']['icon'], 'https://wow.zamimg.com/images/wow/icons/large/inv_ring_amani.jpg')
        self.assertEqual(gear['FINGER_2']['icon'], 'https://render.worldofwarcraft.com/icons/56/ring.jpg')
        self.assertNotIn('data-armory-refresh', html)
        # A fresh copy on its way: the page waits for it and swaps the card in (PAGE_JS) - no "reload" advice
        live = view.tab(data, {'name': 'Futhark', 'class': 'Hunter'}, stale=True, refreshing=True)
        self.assertIn('data-armory-refresh', live)
        self.assertIn('id="armory-card"', live)
        self.assertNotIn('reload', live.lower())


class TestCharacterPage(unittest.TestCase):
    """character.py (one character across nights), its realm handling and web/character.py."""

    def setUp(self):
        from unittest import mock
        from raidanalysis import character, db, guides
        players = actors('Futhark', 'B', 'C', 'D')
        self.pulls = []
        for night in range(4):
            for i in range(3):
                kill = night >= 2 and i == 2
                a = analyze(players, [damage(1, CAUSTIC, 500, t=1000 + k) for k in range(3 - night if night < 3 else 0)],
                            deaths=died(('Futhark', 20000)) if night == 0 and i == 0 else [], kill=kill)
                a['extras'] = {'players': {'Futhark': {'parse': {'rank': 40 + night * 15}, 'damage': 1e8}}}
                self.pulls.append({'report_code': f'C{night}', 'fight_id': i + 1, 'encounter_id': 3010,
                                   'encounter_name': "Ula'tek", 'difficulty': 5, 'kill': kill, 'start_ms': i * 1000,
                                   'end_ms': i * 1000 + 300000, 'fight_pct': 0 if kill else 50 - night * 10 - i,
                                   'analysis': a, 'report_title': f'Night {night}', 'zone_name': 'Undermine',
                                   'report_start': 1757000000000 + night * 604800000})
        character.forget()  # nothing kept from another test
        index = [{k: v for k, v in p.items() if k != 'analysis'} for p in self.pulls]
        patches = [mock.patch.object(db, 'character_pull_index', lambda name, realm=None: index),
                   mock.patch.object(db, 'group_pulls', lambda groups: [
                       p for p in self.pulls if (p['report_code'], p['encounter_id'], p['difficulty']) in set(groups)]),
                   mock.patch.object(guides, 'effective_tags', lambda enc: ({CAUSTIC: analyzer.TAG_AVOIDABLE}, {})),
                   mock.patch.object(guides, 'apply_death_only', lambda *a, **k: None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.prof = character.profile('Futhark', 'Frostwhisper')

    def test_profile_per_boss_and_night(self):
        prof = self.prof
        self.assertEqual((prof['totals']['nights'], prof['totals']['pulls'], prof['totals']['kills']), (4, 12, 2))
        boss = prof['bosses'][0]
        self.assertEqual((boss['kills'], boss['best_parse'], boss['best_pct']), (2, 85.0, 0.0))
        self.assertEqual(boss['first_kill'], self.pulls[6]['report_start'])
        self.assertEqual(boss['nights'][0]['best_pct'], 48.0)
        scores = [e['score'] for e in boss['nights']]
        self.assertLess(scores[0], scores[-1])  # fewer avoidable hits, no death
        self.assertEqual(prof['latest_code'], 'C3')
        titles = [h['title'] for h in prof['highlights']]
        self.assertIn('85 parse', titles)
        self.assertTrue(any(t.startswith('+') for t in titles))  # most improved

    def test_page_links_every_night(self):
        from raidanalysis.web import character as view
        html = view.page(self.prof, None, '<div class="card">gear</div>')
        for night in range(4):
            self.assertIn(f'/admin/raids/report/C{night}/player/Futhark?boss=3010-5', html)
        self.assertIn('/admin/raids/boss/3010/5/player/Futhark', html)  # the boss trend
        self.assertIn('Raid logs <span class="muted small">(4)</span>', html)
        self.assertIn('data-pin=', html)
        self.assertIn('Frostwhisper', html)
        self.assertIn('warcraftlogs.com/character/eu/frostwhisper/futhark', html)

    def test_lately_compares_recent_nights(self):
        from raidanalysis.web import character as view
        points = [{'score': s, 'parse': None, 'deaths': 0} for s in (40, 50, 60, 70, 80, 90)]
        html = view._lately(points, 'score', 'Score lately')
        self.assertIn('<b>80</b>', html)      # the last 3
        self.assertIn('▲ 30', html)           # against the 3 before (50)
        self.assertEqual(view._lately(points, 'parse', 'Parse'), '')

    def test_urls_carry_the_realm(self):
        from raidanalysis.web import character as view
        self.assertEqual(view.url('Futhark', 'TarrenMill'), '/admin/raids/character/tarren-mill/Futhark')
        self.assertEqual(view.url('Futhark'), '/admin/raids/character/Futhark')

    def test_resolve_by_realm(self):
        from unittest import mock
        from raidanalysis import character, db
        with mock.patch.object(db, 'realms_for', lambda name: [{'realm': 'TarrenMill', 'nights': 5},
                                                               {'realm': 'Frostwhisper', 'nights': 2}]):
            self.assertEqual(character.resolve('Futhark', 'frostwhisper')[0], 'Frostwhisper')
            self.assertEqual(character.resolve('Futhark', 'draenor')[0], None)
            self.assertEqual(character.resolve('Futhark'), (None, ['TarrenMill', 'Frostwhisper']))
        with mock.patch.object(db, 'realms_for', lambda name: [{'realm': 'TarrenMill', 'nights': 5}]):
            self.assertEqual(character.resolve('Futhark')[0], 'TarrenMill')

    def test_unknown_realms_fold_into_the_known_one(self):
        from raidanalysis import db
        rows = [{'name': 'A', 'realm': 'X', 'pulls': 10, 'kills': 1, 'nights': 3, 'last_seen': 5, 'spec': 's', 'role': 'dps'},
                {'name': 'A', 'realm': 'Y', 'pulls': 4, 'kills': 0, 'nights': 1, 'last_seen': 9, 'spec': 's', 'role': 'dps'},
                {'name': 'A', 'realm': None, 'pulls': 6, 'kills': 2, 'nights': 2, 'last_seen': 7, 'spec': 'new', 'role': 'tank'},
                {'name': 'B', 'realm': None, 'pulls': 1, 'kills': 0, 'nights': 1, 'last_seen': 1, 'spec': 's', 'role': 'dps'}]
        out = {(r['name'], r['realm']): r for r in db._merge_unknown_realms(rows)}
        self.assertEqual(set(out), {('A', 'X'), ('A', 'Y'), ('B', None)})
        self.assertEqual((out['A', 'X']['pulls'], out['A', 'X']['nights'], out['A', 'X']['spec']), (16, 5, 'new'))

    @staticmethod
    def char(name, cls, spec, role, nights, realm='Frostwhisper', last_seen=1757000000000):
        return {'name': name, 'realm': realm, 'class': cls, 'spec': spec, 'role': role, 'pulls': nights * 18,
                'kills': nights, 'nights': nights, 'last_seen': last_seen}

    def test_players_group_characters_by_their_owner(self):
        from raidanalysis.web import routes
        c = self.char
        roster = [c('Boopsboops', 'Monk', 'Mistweaver', 'healer', 8), c('Boopsproops', 'Evoker', 'Preservation', 'healer', 3),
                  c('Naautilus', 'DemonHunter', 'Devourer', 'dps', 9), c('Gastronomic', 'Druid', 'Restoration', 'healer', 10),
                  c('Pugsy', 'Warrior', 'Arms', 'dps', 1)]
        # Naautilus and Gastronomic share a Battle.net account, but signed up as themselves: two players
        owners = {'boopsboops': {'key': 'd1', 'discord_id': '1', 'display': 'Boops'},
                  'boopsproops': {'key': 'd1', 'discord_id': '1', 'display': 'Boops'},
                  'naautilus': {'key': 'd2', 'discord_id': '2', 'display': 'Naau'},
                  'gastronomic': {'key': 'd3', 'discord_id': '3', 'display': 'Gastro'}}
        players = routes._players(roster, owners)
        self.assertEqual([(p['main']['name'], [a['name'] for a in p['alts']], p['nights']) for p in players],
                         [('Boopsboops', ['Boopsproops'], 11), ('Gastronomic', [], 10), ('Naautilus', [], 9)])  # no pug
        # Nobody known at all (a fresh install): everyone, one each
        self.assertEqual(len(routes._players(roster, {})), 5)
        html = routes._home_characters(players, {('boopsproops', 'frostwhisper'): {'avatar': 'https://render.worldofwarcraft.com/eu/x-avatar.jpg'}})
        self.assertIn('href="/admin/raids/character/frostwhisper/Boopsboops"', html)
        self.assertIn('data-alt data-search="boopsproops frostwhisper preservation evoker"', html)  # the alt's face
        self.assertIn('x-avatar.jpg', html)
        self.assertIn('boops', html.split('class="pl-tile"')[1].split('data-search="')[1].split('"')[0])  # Discord name
        public = routes._home_characters(players, public=True)
        self.assertNotIn('Played by', public)
        self.assertNotIn(' gastro"', public)

    def test_regulars_are_who_raided_lately(self):
        from raidanalysis.web import routes
        nights = list(range(1, 13))  # 12 nights; the latest 6 are 7-12

        def c(name, starts, cls='Priest'):
            row = self.char(name, cls, 'Holy', 'healer', len(starts))
            return dict(row, night_starts=list(starts))
        roster = [c('Veteran', nights[:6]),            # 6 nights, but none lately: "also raided"
                  c('Everyother', [8, 10, 12]),        # every other week: a regular
                  c('Newhealer', [11, 12]),            # joined the last two: a regular straight away
                  c('Once', [12]),                     # one of the latest: not yet
                  c('Mainy', nights[6:11]), c('Alty', [11, 12], 'Evoker'),
                  c('Stonasloth', nights[6:], 'Paladin')]  # in every raid, but nobody signed up with or linked him
        owners = {n: {'key': n, 'discord_id': n, 'display': None}
                  for n in ('veteran', 'everyother', 'newhealer', 'once', 'mainy')}
        owners['alty'] = owners['mainy']
        players = routes._players(roster, owners)
        mainy = next(p for p in players if p['main']['name'] == 'Mainy')
        self.assertEqual(mainy['nights'], 6)  # night 11 on both characters counts once
        regulars, rest = routes._regulars(players)
        self.assertEqual(sorted(p['main']['name'] for p in regulars), ['Everyother', 'Mainy', 'Newhealer'])
        self.assertEqual(sorted(p['main']['name'] for p in rest), ['Once', 'Veteran'])
        # The one left out for not being linked: named for officers, never on the public site
        unlinked = routes._unlinked(roster, owners)
        self.assertEqual([(ch['name'], n) for ch, n in unlinked], [('Stonasloth', 6)])
        # On a shared Battle.net account and nobody has signed up with it yet: left out like a pug, named for officers
        owners['stonasloth'] = {'key': 'cstonasloth', 'discord_id': None, 'display': None}
        self.assertNotIn('Stonasloth', [p['main']['name'] for p in routes._players(roster, owners)])
        self.assertEqual([ch['name'] for ch, _ in routes._unlinked(roster, owners)], ['Stonasloth'])
        self.assertIn('Stonasloth</a> (6 of the last 6)', routes._home_characters(players, unlinked=unlinked))
        self.assertNotIn('Stonasloth', routes._home_characters(players, public=True, unlinked=unlinked))

    def test_character_page_knows_the_players_other_characters(self):
        import json
        from raidanalysis.web import character as cview
        prof = {'name': 'Boopsproops', 'realm': 'Frostwhisper'}
        chars = [self.char('Boopsboops', 'Monk', 'Mistweaver', 'healer', 8),
                 self.char('Boopsproops', 'Evoker', 'Preservation', 'healer', 3)]
        images = {('boopsboops', 'frostwhisper'): {'avatar': 'https://render.worldofwarcraft.com/eu/b-avatar.jpg'}}
        tabs = cview.switcher(prof, chars, images)
        self.assertIn('href="/admin/raids/character/frostwhisper/Boopsboops"', tabs)
        self.assertEqual(tabs.count('ch-switch-tab active'), 1)
        self.assertIn('aria-current=page', tabs.split('Boopsproops')[0][-400:] + tabs)  # this one is lit
        alts = cview.pin_alts(prof, chars, images)
        self.assertEqual([(a['name'], a['img']) for a in alts], [('Boopsboops', 'https://render.worldofwarcraft.com/eu/b-avatar.jpg')])
        json.dumps(alts)  # goes into the 📌's data
        self.assertEqual(cview.switcher(prof, [], images), '')  # one character: no switcher

    def test_front_page_characters_tab(self):
        from raidanalysis.web import routes
        html = routes._home_characters(routes._players([self.char('Futhark', 'Hunter', 'Survival', 'dps', 2)], {}))
        self.assertIn('href="/admin/raids/character/frostwhisper/Futhark"', html)
        self.assertIn('data-search="futhark frostwhisper survival hunter"', html)
        self.assertIn('1 players · 1 characters', html)
        # Every tab link names its tab: the bare address is "the tab used last" (the nav's Raid Analysis)
        self.assertEqual(routes._home_href({'tier': '3'}, 'nights'), '/admin/raids?tier=3&tab=nights')
        self.assertEqual(routes._home_href({'tier': '3'}, 'bosses'), '/admin/raids?tier=3&tab=bosses')
        self.assertEqual(routes._home_href({}, 'characters'), '/admin/raids?tab=characters')


class TestItemTooltips(unittest.TestCase):
    """items.py: the tooltip query, the item set as the game shows it, sanitizing; armory's stat sheet."""

    RAW_SET = ('<b class="q4">Fangs</b><br>+167 [Agility or Intellect]<br><br />'
               '<span class="q"><a href="/item-set=2059/x" class="q">Viper Set</a> (0/5)</span>'
               '<div class="q0 indent"><span><!--si1--><a href="/item=1">Head</a></span><br />'
               '<span><!--si2--><a href="/item=2">Hands</a></span><br />'
               '<span><!--si3--><a href="/item=3">Legs</a></span></div><br />'
               '<span class="q0"><!--itemeffectspec253:0--><span>(2) Set Beast Mastery: <a href="/spell=1">BM two</a></span>'
               '<!--itemeffectspec--><br /><!--itemeffectspec254:0--><span>(2) Set Marksmanship: <a href="/spell=2">MM two</a>'
               '</span><!--itemeffectspec--><br /><!--itemeffectspec254:0--><span>(4) Set Marksmanship: <a href="/spell=3">'
               'MM four</a></span><!--itemeffectspec--></span>')

    def test_query_is_canonical(self):
        from raidanalysis import items
        q = items.query(bonus=[2, 1], ilvl=321, ench=8017, gems=[5], pcs=[9, 3, 9], spec=254)
        self.assertEqual(q, 'bonus=2:1&ilvl=321&ench=8017&gems=5&pcs=3:9&spec=254')
        self.assertEqual(items.parse_query({'spec': '254', 'bonus': '2:1', 'ilvl': '321', 'ench': '8017',
                                            'gems': '5', 'pcs': '3:9'}), q)
        self.assertIsNone(items.parse_query({'bonus': '1;DROP'}))
        self.assertEqual(items.spec_id('Death Knight', 'Frost'), 251)
        self.assertEqual(items.spec_id('Hunter', 'BeastMastery'), 253)

    def test_set_lit_like_in_game(self):
        from raidanalysis import items
        html = items.sanitize(items.with_primary(items.with_set(self.RAW_SET, {'1', '2', '9'}, 254), 254))
        self.assertIn('(2/5)', html)
        self.assertEqual(html.count('class="q8"'), 2)      # the two pieces worn
        self.assertIn('<span class="q2">(2) Set Marksmanship', html)
        self.assertIn('<span class="q0">(4) Set Marksmanship', html)
        self.assertNotIn('Beast Mastery', html)           # another spec's bonus
        self.assertIn('+167 Agility', html)
        self.assertNotIn('<a', html)
        self.assertNotIn('<!--', html)

    def test_sanitize_keeps_only_the_allow_list(self):
        from raidanalysis import items
        dirty = ('<div class="q2 evil" onclick="x()">Hi<script>alert(1)</script></div>'
                 '<img src="https://evil.example/x.png" onerror="x()"><img src="https://wow.zamimg.com/a/b.png">'
                 '<span style="background-image:url(https://wow.zamimg.com/i/g.gif);position:fixed">gem</span>'
                 '<a href="javascript:alert(1)">link</a><div class="whtt-sellprice">Sell Price: 5</div>'
                 '<span style="color: #00FF00; background:url(javascript:x)">ok</span>')
        html = items.sanitize(dirty)
        for bad in ('onclick', 'onerror', 'evil', '<script', 'javascript', 'position', 'Sell Price'):
            self.assertNotIn(bad, html)
        self.assertIn('<div class="q2">Hi', html)  # the script tag is gone, its text is inert
        self.assertIn('src="https://wow.zamimg.com/a/b.png"', html)
        self.assertIn('background-image:url(https://wow.zamimg.com/i/g.gif)', html)
        self.assertIn('<span>link</span>', html)
        self.assertIn('style="color:#00FF00"', html)

    def test_gear_gets_its_tooltip_query(self):
        from raidanalysis import armory
        data = {'raiderio': {'class': 'Hunter', 'active_spec_name': 'Marksmanship', 'gear': {'items': {
            'head': {'item_id': 1, 'item_level': 321, 'enchant': 8017, 'gems': [], 'tier': 36, 'bonuses': [7, 8],
                     'enchants_detail': [{'name': 'Enchant Helm - Rune of Avoidance'}], 'name': 'Fangs', 'icon': 'x'},
            'hands': {'item_id': 2, 'item_level': 308, 'gems': [], 'tier': 36, 'bonuses': [], 'name': 'Grips', 'icon': 'y'},
            'neck': {'item_id': 3, 'item_level': 321, 'gems': [240914], 'bonuses': [9], 'name': 'Neck', 'icon': 'z',
                     'gems_detail': [{'name': '16 Vers'}]}}}}}
        gear = armory.items(data)
        self.assertEqual(gear['HEAD']['tooltip'], 'bonus=7:8&ilvl=321&ench=8017&pcs=1:2&spec=254')
        self.assertEqual(gear['HEAD']['enchant'], 'Rune of Avoidance')
        self.assertEqual(gear['NECK']['tooltip'], 'bonus=9&ilvl=321&gems=240914&spec=254')  # not a set piece
        self.assertEqual(gear['NECK']['gems'], ['16 Vers'])

    def test_stat_sheet_from_blizzard(self):
        from raidanalysis import armory
        from raidanalysis.web import armory as view
        data = {'statistics': {'health': 1800000, 'power': 100, 'power_type': {'name': 'Focus'},
                               'strength': {'effective': 900}, 'agility': {'effective': 41000},
                               'intellect': {'effective': 1200}, 'stamina': {'effective': 90000},
                               'melee_crit': {'rating': 6000, 'value': 27.9}, 'spell_crit': {'value': 5},
                               'melee_haste': {'rating': 3000, 'value': 9.1}, 'mastery': {'rating': 11000, 'value': 44.8},
                               'versatility': 4000, 'versatility_damage_done_bonus': 7.9,
                               'lifesteal': {'value': 0}, 'avoidance': {'rating': 800, 'rating_bonus': 2.6},
                               'armor': {'effective': 24000}}}
        st = armory.stats(data)
        self.assertEqual(st['primary'], ('Agility', 41000))
        self.assertEqual([s[0] for s in st['secondary']], ['Critical Strike', 'Haste', 'Mastery', 'Versatility'])
        self.assertEqual(st['secondary'][0][1], 27.9)  # melee crit for an agility user
        self.assertEqual([t[0] for t in st['tertiary']], ['Avoidance'])
        html = view.sheet(data)
        self.assertIn('Attributes', html)
        self.assertIn('27.90%', html)
        self.assertIsNone(armory.stats({}))
        # Blizzard's current shape: 'rating_normalized' in place of 'rating' (which could overflow)
        data['statistics'].update({'melee_crit': {'rating_normalized': 611, 'rating_bonus': 0.87, 'value': 5.87},
                                   'mastery': {'rating': 4294967066, 'value': 44.8}})
        st = armory.stats(data)
        self.assertEqual(st['secondary'][0][2], 611)
        self.assertEqual(st['secondary'][2][2], 0)                   # the old overflow: not a rating
        html = view.sheet(data)
        self.assertIn('title="Critical Strike: 611 rating"', html)
        self.assertIn('<div class="ar-srow"><span>Mastery</span>', html)  # unknown: no tip, not "0 rating"

    def test_tier_set_from_blizzard_and_wowhead(self):
        from raidanalysis import armory
        data = {'equipped_items': [{'slot': {'type': 'HEAD'}, 'set': {
            'item_set': {'name': 'Viper Set'}, 'items': [{'is_equipped': True}, {'is_equipped': True}, {}],
            'effects': [{'display_string': '(2) Set: Two piece.', 'required_count': 2, 'is_active': True},
                        {'display_string': '(4) Set: Four piece.', 'required_count': 4, 'is_active': False}]}}]}
        tier = armory.tier_set(data)
        self.assertEqual((tier['name'], tier['worn'], tier['size']), ('Viper Set', 2, 3))
        self.assertEqual([(b['count'], b['active']) for b in tier['bonuses']], [(2, True), (4, False)])
        wh = armory._set_from_wowhead(self.RAW_SET, 2, 254)
        self.assertEqual((wh['name'], wh['worn'], wh['size']), ('Viper Set', 2, 5))
        self.assertEqual([(b['count'], b['text'], b['active']) for b in wh['bonuses']],
                         [(2, 'MM two', True), (4, 'MM four', False)])


class TestCharacterFilters(unittest.TestCase):
    def test_latest_tier_and_hardest_real_difficulty_by_default(self):
        from raidanalysis import character
        pull = lambda code, zone, diff, start: {'report_code': code, 'zone_id': zone, 'zone_name': f'Zone {zone}',  # noqa: E731
                                                'difficulty': diff, 'report_start': start}
        pulls = ([pull('old', 38, 5, 1)] * 3 + [pull('new', 42, 5, 4)] * 4 + [pull('new', 42, 4, 9)] * 9
                 + [pull('new2', 42, 4, 10)])
        # Mostly Heroic farm, but Mythic is a real part of it (4 of 14 pulls): Mythic
        chosen, tier, diff, diffs = character.filter_pulls(pulls)
        self.assertEqual((tier, diff, len(chosen)), (42, 5, 4))
        self.assertEqual(diffs, [(5, 4), (4, 10)])
        # ...but one stray Mythic pull among 30 Heroic ones isn't: Heroic
        stray = [pull('new', 42, 5, 4)] + [pull('new', 42, 4, 9)] * 30
        self.assertEqual(character.filter_pulls(stray)[2], 4)
        self.assertEqual([t['zone_id'] for t in character.tiers_of(pulls)], [42, 38])
        chosen, tier, diff, _ = character.filter_pulls(pulls, 38, None)
        self.assertEqual((tier, diff, len(chosen)), (38, 5, 3))
        chosen, tier, diff, _ = character.filter_pulls(pulls, character.ALL, character.ALL)
        self.assertEqual(len(chosen), len(pulls))
        chosen, tier, diff, _ = character.filter_pulls(pulls, 999, 3)  # unknown: back to the defaults
        self.assertEqual((tier, diff), (42, 5))


class TestArmoryNewestCopy(unittest.TestCase):
    """armory.cached(): the newer of a linked character's cache (admin site) and ours."""

    def run_cached(self, linked_when, own_when, own_extra=None):
        from datetime import datetime, timedelta, timezone
        from unittest import mock
        from raidanalysis import armory, db
        now = datetime.now(timezone.utc)
        gear = lambda ilvl: {'raiderio': {'gear': {'items': {'head': {'item_id': 1, 'item_level': ilvl, 'name': 'H'}}}}}  # noqa: E731
        linked = {'enrichment_cache': gear(295), 'last_enriched': (now - linked_when).replace(tzinfo=None)}
        own = {'data': dict(gear(325), sheet_v=armory.SHEET_VERSION, **(own_extra or {})), 'fetched_at': now - own_when}
        with mock.patch.object(armory, '_linked', lambda name, slug=None: linked), \
                mock.patch.object(db, 'get_armory', lambda name, slug=None: own):
            data, stale = armory.cached('Boopsboops', 'Frostwhisper')
        return armory.items(data)['HEAD']['ilvl'], stale, data

    def test_ours_wins_when_newer(self):
        from datetime import timedelta
        ilvl, stale, _ = self.run_cached(timedelta(days=30), timedelta(minutes=5))
        self.assertEqual((ilvl, stale), (325, False))  # not "refreshing" forever because the linked copy is old

    def test_linked_wins_when_newer_and_keeps_our_sheet(self):
        from datetime import timedelta
        ilvl, stale, data = self.run_cached(timedelta(minutes=1), timedelta(hours=2), {'statistics': {'health': 1}})
        self.assertEqual((ilvl, stale), (295, False))
        self.assertEqual(data['statistics'], {'health': 1})


class TestBossTabsKeepThePlayer(unittest.TestCase):
    def test_player_page_boss_tabs(self):
        from types import SimpleNamespace
        from unittest import mock
        from raidanalysis import db
        from raidanalysis.web import routes
        pull = lambda fid, enc, names: {'fight_id': fid, 'encounter_id': enc, 'difficulty': 5, 'encounter_name': f'Boss {enc}',  # noqa: E731
                                        'kill': False, 'fight_pct': 50.0, 'start_ms': fid * 1000, 'end_ms': fid * 1000 + 500,
                                        'analysis': {'players': [{'name': n} for n in names]}}
        pulls = [pull(1, 10, ['Futhark', 'Bob']), pull(2, 20, ['Bob'])]
        report = {'title': 'Night', 'start_time': 0, 'zone_name': 'Z', 'owner': 'x', 'event_title': None}
        href = lambda key, ps: ('/player-page' if any('Futhark' in [x['name'] for x in p['analysis']['players']]  # noqa: E731
                                                       for p in ps) else None)
        with mock.patch.object(db, 'report_archived', lambda code: False):
            html = routes._night_header(SimpleNamespace(query={}), report, 'CODE', pulls, (10, 5), view='players',
                                        boss_href=href)
        self.assertIn('class="boss-tab active" data-swap="page" href="/player-page"', html)
        self.assertIn('href="/admin/raids/report/CODE?boss=20-5&amp;view=players"', html)  # not in that boss: its page


class TestBossWeightsByDifficulty(unittest.TestCase):
    """coach.boss_weights: difficulty strictly first, then the boss's place in the raid and the pulls."""
    ORDER = {3470: 0, 3445: 1, 3455: 2, 3497: 3, 3420: 4, 3421: 5, 3429: 6, 3492: 7}  # The Venomous Abyss

    def test_a_normal_last_boss_never_beats_a_mythic_first_boss(self):
        from raidanalysis import coach
        normal_last = {'encounter': 3492, 'difficulty': 3, 'pulls': 12, 'killed': False, 'start': 0}
        heroic_first = {'encounter': 3470, 'difficulty': 4, 'pulls': 1, 'killed': True, 'start': 1}   # an easy kill even
        mythic_first = {'encounter': 3470, 'difficulty': 5, 'pulls': 1, 'killed': True, 'start': 2}
        w = coach.boss_weights([normal_last, heroic_first, mythic_first], self.ORDER)
        self.assertTrue(w[0] < w[1] < w[2])
        self.assertEqual(w[2], 1)

    def test_later_bosses_count_more_within_a_difficulty(self):
        from raidanalysis import coach
        # pulled in this order tonight, but Ula'tek is boss 8 and Nek'zali boss 1
        ulatek = {'encounter': 3492, 'difficulty': 4, 'pulls': 5, 'killed': True, 'start': 0}
        nekzali = {'encounter': 3470, 'difficulty': 4, 'pulls': 5, 'killed': True, 'start': 1}
        w_ulatek, w_nekzali = coach.boss_weights([ulatek, nekzali], self.ORDER)
        self.assertGreater(w_ulatek, w_nekzali)

    def test_pulls_still_count_and_easy_kills_hardly(self):
        from raidanalysis import coach
        prog = {'encounter': 3445, 'difficulty': 5, 'pulls': 20, 'killed': False, 'start': 1}   # boss 2, 20 wipes
        farm = {'encounter': 3470, 'difficulty': 5, 'pulls': 1, 'killed': True, 'start': 0}     # boss 1, one-shot
        w_prog, w_farm = coach.boss_weights([prog, farm], self.ORDER)
        self.assertEqual(w_prog, 1)
        self.assertLess(w_farm, 0.15)  # like before: an easy kill hardly counts


class TestArmoryRaidProgress(unittest.TestCase):
    def test_current_raids_first_whatever_jsonb_did_to_the_order(self):
        from unittest import mock
        from raidanalysis import armory
        prog = {'sporefall': {'summary': '1/1 M'}, 'tier-mn-1': {'summary': '8/9 M'},   # as JSONB returns it
                'the-venomous-abyss': {'summary': '1/8 M'}, 'the-tidebound-grotto': {'summary': '1/1 H'}}
        with mock.patch.object(armory, '_our_raids', lambda: ['the-venomous-abyss', 'tier-mn-1']):
            kept = armory.summary({'raid_progression': prog, 'raid_order': ['the-tidebound-grotto', 'the-venomous-abyss',
                                                                              'sporefall', 'tier-mn-1']})
            self.assertEqual(kept['raids'], [('The Venomous Abyss', '1/8 M'), ('Tier Mn 1', '8/9 M')])
        with mock.patch.object(armory, '_our_raids', lambda: []):
            kept = armory.summary({'raid_progression': prog, 'raid_order': ['the-tidebound-grotto', 'the-venomous-abyss',
                                                                              'sporefall', 'tier-mn-1']})
            self.assertEqual([r for r, _ in kept['raids']], ['The Tidebound Grotto', 'The Venomous Abyss'])

    def test_blizzard_set_text(self):
        from raidanalysis import armory
        data = {'equipped_items': [{'set': {'item_set': {'name': 'Guile'}, 'items': [{'is_equipped': True}],
                                            'effects': [{'display_string': 'Set: Rising Sun Kick hits harder.',
                                                         'required_count': 2, 'is_active': True}]}}]}
        self.assertEqual(armory.tier_set(data)['bonuses'][0]['text'], 'Rising Sun Kick hits harder.')


class TestItemIconRetry(unittest.IsolatedAsyncioTestCase):
    """character_enrichment: an item icon that hits a rate limit is asked again, and kept once known."""

    async def test_retry_then_cache(self):
        from unittest import mock
        from aiohttp import ClientSession, web
        from aiohttp.test_utils import TestServer
        from character_enrichment import CharacterEnricher
        calls = {'ring': 0, 'gone': 0}

        async def media(request):
            item = request.match_info['item']
            calls[item] += 1
            if item == 'gone':
                return web.Response(status=404)
            if calls[item] == 1:
                return web.Response(status=429)  # rate limited the first time
            return web.json_response({'assets': [{'key': 'icon', 'value': 'https://render/ring.jpg'}]})
        app = web.Application()
        app.router.add_get('/media/{item}', media)
        server = TestServer(app)
        await server.start_server()
        enricher = CharacterEnricher()
        CharacterEnricher._icon_cache.clear()
        try:
            with mock.patch.object(CharacterEnricher, 'get_blizzard_token', mock.AsyncMock(return_value='t')), \
                    mock.patch('asyncio.sleep', mock.AsyncMock()):
                async with ClientSession() as session:
                    ring, gone = str(server.make_url('/media/ring')), str(server.make_url('/media/gone'))
                    self.assertEqual(await enricher.fetch_item_icon(ring, session), 'https://render/ring.jpg')
                    self.assertEqual(calls['ring'], 2)  # the 429, then the answer
                    self.assertEqual(await enricher.fetch_item_icon(ring, session), 'https://render/ring.jpg')
                    self.assertEqual(calls['ring'], 2)  # kept: not asked again
                    self.assertIsNone(await enricher.fetch_item_icon(gone, session))
                    self.assertIsNone(await enricher.fetch_item_icon(gone, session))
                    self.assertEqual(calls['gone'], 1)  # no icon for it: not asked again either
        finally:
            CharacterEnricher._icon_cache.clear()
            await server.close()


class TestFasterPages(unittest.IsolatedAsyncioTestCase):
    """The site's CSS / JS as kept files; portraits cropped small - and only ever of Blizzard's renders."""

    async def test_static_files_are_versioned_and_kept(self):
        from raidanalysis.web import routes
        self.assertRegex(routes.STATIC_CSS_URL, r'^/raids/static/app-[0-9a-f]{12}\.css$')
        response = await routes.handle_static_js(None)
        self.assertIn('immutable', response.headers['Cache-Control'])
        self.assertIn('onEach', response.text)

    async def test_portraits(self):
        import io
        from PIL import Image
        from raidanalysis import portraits
        self.assertIsNone(await portraits.get('https://evil.example/x.png'))  # not Blizzard's: never fetched
        self.assertIsNone(await portraits.get(None))
        render = Image.new('RGBA', (1600, 1200), (0, 0, 0, 0))
        render.paste((200, 30, 30, 255), (700, 200, 900, 1000))  # a character in the middle
        raw = io.BytesIO()
        render.save(raw, 'PNG')
        with Image.open(io.BytesIO(portraits.crop(raw.getvalue()))) as out:
            self.assertEqual(out.format, 'WEBP')
            self.assertEqual(out.width, portraits.WIDTH)
            self.assertEqual(out.mode, 'RGBA')                       # still see-through around them
            self.assertEqual(out.getpixel((0, 0))[3], 0)
            self.assertGreater(out.getpixel((out.width // 2, out.height // 2))[3], 200)


class TestSharedPageCache(unittest.IsolatedAsyncioTestCase):
    """A page built once serves every officer (and the public view every raider); the warmer builds them ahead."""

    async def test_shared_and_warmed(self):
        from unittest import mock
        from aiohttp.test_utils import make_mocked_request
        from raidanalysis import sync
        from raidanalysis.web import routes
        built = []

        async def night(request):
            built.append((request.path, bool(request.get('public'))))
            session = routes._session(request)
            return routes._page('Night', session, f'<div class="card">night {request.match_info["code"]}</div>')
        routes._bodies.clear()
        with mock.patch.dict(sync.status, {'data_version': 'v1', 'running': False}), \
                mock.patch.object(routes, 'handle_night', night), \
                mock.patch.object(routes, 'handle_overview', mock.AsyncMock()), \
                mock.patch.object(routes.db, 'list_reports', return_value=[{'code': 'abc'}]), \
                mock.patch.object(routes.db, 'list_tiers', return_value=[]), \
                mock.patch('oauth_server.get_session', side_effect=lambda r: {'username': r.headers.get('X-User'), 'role': 'admin'}):
            await routes.warm_pages()
            self.assertEqual(sorted(built), [('/admin/raids/report/abc', False), ('/raids/report/abc', True)])
            # An officer and a raider open the night: both get the warmed page, nothing is built again
            officer = make_mocked_request('GET', '/admin/raids/report/abc', headers={'X-User': 'philip'},
                                          match_info={'code': 'abc'})
            response = await routes._admin_cached(night)(officer)
            self.assertIn('night abc', response.text)
            raider = make_mocked_request('GET', '/raids/report/abc', match_info={'code': 'abc'})
            response = await routes._public(night)(raider)
            self.assertIn('night abc', response.text)
            self.assertEqual(len(built), 2)
            # New data: built anew
            sync.status['data_version'] = 'v2'
            await routes._admin_cached(night)(officer)
            self.assertEqual(len(built), 3)
        routes._bodies.clear()

    def test_front_page_key_follows_team_and_tab(self):
        from unittest import mock
        from aiohttp.test_utils import make_mocked_request
        from raidanalysis import sync
        from raidanalysis.web import routes
        with mock.patch.dict(sync.status, {'data_version': 'v1'}):
            warmed = routes._body_key(make_mocked_request('GET', '/raids?tab=characters&team=moon'), True)
            # A raider coming back by the nav: no tab or team in the address - their browser's choices
            visit = make_mocked_request('GET', '/raids', headers={'Cookie': 'raid_team=moon; raid_home_tab=characters'})
            self.assertEqual(routes._body_key(visit, True), warmed)
            other = make_mocked_request('GET', '/raids', headers={'Cookie': 'raid_team=sun; raid_home_tab=characters'})
            self.assertNotEqual(routes._body_key(other, True), warmed)


class TestWCLTokenRefresh(unittest.TestCase):
    """wcl.query(): a cached token WCL stopped accepting (401) is replaced, not used until a restart."""

    class Resp:
        def __init__(self, status, body=None):
            self.status, self.body, self.headers = status, body or {}, {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def json(self):
            return self.body

        async def text(self):
            return '{"error":"Unauthenticated."}'

    class Session:
        def __init__(self, responses, token_status=200):
            self.responses, self.token_status, self.auth_headers, self.token_requests = list(responses), token_status, [], 0

        def post(self, url, json=None, headers=None, data=None, auth=None):
            if 'oauth/token' in url:
                self.token_requests += 1
                return TestWCLTokenRefresh.Resp(self.token_status, {'access_token': 'fresh', 'expires_in': 3600})
            self.auth_headers.append(headers['Authorization'])
            return self.responses.pop(0)

    def setUp(self):
        import time
        from unittest import mock
        import wcl_api
        from raidanalysis import wcl
        self.wcl = wcl
        for patch in (mock.patch.object(wcl, '_token', 'revoked'), mock.patch.object(wcl, '_token_expires', time.time() + 9e6),
                      mock.patch.object(wcl_api, 'WCL_CLIENT_ID', 'id'), mock.patch.object(wcl_api, 'WCL_CLIENT_SECRET', 'secret')):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_rejected_token_is_replaced_and_the_query_retried(self):
        import asyncio
        session = self.Session([self.Resp(401), self.Resp(200, {'data': {'ok': 1}})])
        self.assertEqual(asyncio.run(self.wcl.query(session, '{ ok }')), {'ok': 1})
        self.assertEqual(session.auth_headers, ['Bearer revoked', 'Bearer fresh'])
        self.assertEqual(self.wcl._token, 'fresh')

    def test_only_one_retry(self):
        import asyncio
        session = self.Session([self.Resp(401), self.Resp(401)])
        with self.assertRaises(self.wcl.WCLError) as caught:
            asyncio.run(self.wcl.query(session, '{ ok }'))
        self.assertIn('401', str(caught.exception))
        self.assertEqual(session.token_requests, 1)

    def test_rejected_credentials_say_so(self):
        import asyncio
        session = self.Session([self.Resp(401)], token_status=401)
        with self.assertRaises(self.wcl.WCLError) as caught:
            asyncio.run(self.wcl.query(session, '{ ok }'))
        self.assertIn('WCL_CLIENT_ID', str(caught.exception))


class TestCoachByRole(unittest.TestCase):
    """Healers' parse is their healing parse; the coach's tips fit the role."""

    @staticmethod
    def ranking(*chars):
        return {'data': [{'roles': {'healers': {'characters': [{'name': n, 'rankPercent': r} for n, r in chars]}}}]}

    def test_healers_get_their_healing_parse(self):
        from raidanalysis import throughput
        roster = [{'name': 'Boopsboops', 'role': 'healer'}, {'name': 'Futhark', 'role': 'dps'}]
        dps = {'data': [{'roles': {'healers': {'characters': [{'name': 'Boopsboops', 'rankPercent': 75}]},
                                   'dps': {'characters': [{'name': 'Futhark', 'rankPercent': 60}]}}}]}
        hps = self.ranking(('Boopsboops', 92), ('Futhark', 3))
        parses = throughput.parses_for_roles(roster, dps, hps)
        self.assertEqual((parses['Boopsboops']['rank'], parses['Futhark']['rank']), (92, 60))

    def test_focus_tips_by_role(self):
        from unittest import mock
        from raidanalysis import coach
        found = [coach._insight('bad', 40, 'reaction', '5.2 s to the add'), coach._insight('good', 45, 'star', 'Most on the add')]
        with mock.patch.object(coach, '_focus_insights', lambda *a: list(found)):
            self.assertEqual(len(coach.focus_insights({}, 1, [], role='dps')), 2)
            self.assertEqual(coach.focus_insights({}, 1, [], role='healer'), [])
            self.assertEqual([i['text'] for i in coach.focus_insights({}, 1, [], role='tank')], ['Most on the add'])

    def test_healer_rotation_is_a_nudge_and_never_over_pressing(self):
        from unittest import mock
        from raidanalysis import coach, throughput
        cpm = {'verdict': 'off', 'abilities': [
            {'name': 'Rising Sun Kick', 'verdict': 'off', 'ours': 2.0, 'top': 5.0},
            {'name': 'Vivify', 'verdict': 'way_over', 'ours': 12.0, 'top': 3.0}]}
        data = {'top': [{}], 'label': 'Mistweaver Monks', 'rows': [], 'player': {}}
        with mock.patch.object(throughput, 'cpm', lambda *a: cpm), \
                mock.patch.object(throughput, 'raid_buff', lambda *a: None), \
                mock.patch.object(throughput, 'uptime', lambda *a: []), \
                mock.patch.object(throughput, 'proc_rows', lambda *a: []), \
                mock.patch.object(throughput, 'active_time', lambda *a: (None, None)):
            healer = coach.rotation_insights([], 'Boopsboops', 'healer', data)
            dps = coach.rotation_insights([], 'Boopsboops', 'dps', data)
        self.assertEqual([i['text'].split(':')[0] for i in healer], ['Rising Sun Kick'])
        self.assertIn('Worth fitting in more often', healer[0]['text'])
        self.assertLess(healer[0]['impact'], dps[0]['impact'])
        self.assertIn('Vivify', ' '.join(i['text'] for i in dps))

    def test_healer_output(self):
        from unittest import mock
        from raidanalysis import coach, throughput
        rows = [{'parse': 92, 'kill': True, 'raid_rank': 1, 'raid_size': 5},
                {'parse': None, 'kill': False, 'raid_rank': 1, 'raid_size': 5},
                {'parse': None, 'kill': False, 'raid_rank': 3, 'raid_size': 5}]
        with mock.patch.object(throughput, 'per_pull', lambda *a: rows):
            found, best = coach.output_insights([], 'Boopsboops', 'healer')
        texts = [i['text'] for i in found]
        self.assertEqual(best, 92)
        self.assertIn("Most healing of the raid's 5 healers in 2 of 3 pulls", texts)
        self.assertIn('Best healing parse 92', texts)

    def test_backfill_writes_the_healing_parse(self):
        from unittest import mock
        from raidanalysis import db
        analysis = {'players': [{'name': 'Boopsboops', 'role': 'healer'}, {'name': 'Futhark', 'role': 'dps'}],
                    'slim_extras': {'Boopsboops': {'parse': {'rank': 75}}, 'Futhark': {'parse': {'rank': 60}}}}
        written = []

        def fake_run(sql, params=(), fetch=None):
            if sql.startswith('SELECT'):
                return {'analysis': analysis}
            written.append(params[0].adapted)
        with mock.patch.object(db, '_run', fake_run):
            db.save_healer_parses('CODE', 3, {'Boopsboops': {'rank': 92, 'metric': 'hps'}})
        saved = written[0]
        self.assertEqual(saved['slim_extras']['Boopsboops']['parse']['rank'], 92)
        self.assertEqual(saved['slim_extras']['Futhark']['parse']['rank'], 60)  # DPS untouched
        self.assertTrue(saved['healer_parses'])


class TestDefensives(unittest.TestCase):
    """defensives.py + coach.defensive_insights: defensives up through heavy damage get a star; tanks are left out."""
    DEF = 108271  # Astral Shift

    @staticmethod
    def pull(extra_hits, start=0, length=120, silent=()):
        """
        Steady 10k a second on everyone (A..D, tank T), plus extra_hits [(name, second, amount, buffs, ability)];
        silent: [(name, from second, to second)] - nothing at all hits them then.
        """
        ids = {'A': 1, 'B': 2, 'C': 3, 'D': 4, 'T': 5}
        quiet = {(n, s) for n, a, b in silent for s in range(a, b)}
        events = [{'type': 'damage', 'timestamp': start + s * 1000 + 500, 'targetID': i, 'unmitigatedAmount': 10000,
                   'abilityGameID': 7} for s in range(length) for n, i in ids.items() if (n, s) not in quiet]
        for name, sec, amount, buffs, ability in extra_hits:
            events.append({'type': 'damage', 'timestamp': start + sec * 1000 + 100, 'targetID': ids[name],
                           'unmitigatedAmount': amount, 'abilityGameID': ability,
                           'buffs': '.'.join(str(b) for b in buffs) + '.' if buffs else None})
        return events, {i: n for n, i in ids.items()}

    def summarize(self, extra, casts, silent=(), defensive_ids=None, immune=()):
        """immune: [(name, second, ability, buffs)] - hits logged as immune for 0 (no unmitigated amount)."""
        from raidanalysis import defensives
        events, names = self.pull(extra, silent=silent)
        ids = {n: i for i, n in names.items()}
        events += [{'type': 'damage', 'timestamp': sec * 1000 + 200, 'targetID': ids[n], 'amount': 0, 'hitType': 10,
                    'abilityGameID': ability, 'buffs': '.'.join(str(b) for b in buffs) + '.'}
                   for n, sec, ability, buffs in immune]
        roles = {'A': 'dps', 'B': 'dps', 'C': 'healer', 'D': 'dps', 'T': 'tank'}
        return defensives.summarize(events, 0, names, roles, casts, defensive_ids)

    def test_raid_burst_aimed_and_quiet(self):
        import json
        from raidanalysis import defensives
        extra = []
        for sec in range(30, 38):  # a raid-wide burst: everyone takes 60k a second more
            for n in 'ABCD':
                extra.append((n, sec, 60000, [self.DEF] if n == 'A' else [], 99))
        for sec in range(80, 86):  # something aimed at C alone
            extra.append(('C', sec, 120000, [self.DEF], 55))
        casts = {'A': [[29000, self.DEF]], 'B': [[60000, self.DEF]], 'C': [[79500, self.DEF]]}
        incoming = json.loads(json.dumps(self.summarize(extra, casts, silent=[('B', 56, 75)])))  # as stored
        self.assertNotIn('T', incoming['players'])  # tanks left out
        analysis = {'incoming': incoming}
        kind = lambda n, t: defensives.moments(analysis, n, [(t, self.DEF, 'Astral Shift')], 120000)['presses'][0]  # noqa: E731
        self.assertEqual((kind('A', 29000)['kind'], kind('A', 29000)['ability']), ('raid', 99))
        self.assertEqual(kind('B', 60000)['kind'], 'quiet')                        # nothing came at all
        self.assertEqual(kind('D', 60000)['kind'], 'used')                         # the usual damage came: fine
        self.assertEqual((kind('C', 79500)['kind'], kind('C', 79500)['ability']), ('aimed', 55))

    def test_spike_with_no_defensive(self):
        from raidanalysis import defensives
        extra = [('D', sec, 150000, [], 66) for sec in range(100, 104)]
        analysis = {'incoming': self.summarize(extra, {})}
        spikes = defensives.moments(analysis, 'D', [], 120000)['spikes']
        self.assertEqual(len(spikes), 1)
        self.assertEqual(spikes[0]['ability'], 66)
        self.assertTrue(98000 <= spikes[0]['t'] <= 100000)

    def test_coach_stars_and_the_pattern_tip(self):
        from raidanalysis import coach
        good_extra = [(n, sec, 60000, [self.DEF] if n == 'A' else [], 99) for sec in range(30, 38) for n in 'ABCD']
        good = {'incoming': self.summarize(good_extra, {'A': [[29000, self.DEF]]}),
                'cooldowns': [{'t': 29000, 'name': 'A', 'ability_id': self.DEF, 'ability': 'Astral Shift',
                               'category': 'personal'}],
                'abilities': [{'id': 99, 'name': 'Blight Vein'}, {'id': 66, 'name': 'Shadow Brand'}]}
        pulls = []
        for number in (1, 2):  # quiet presses while Shadow Brand hits hard with nothing up, twice
            extra = [('A', sec, 150000, [], 66) for sec in range(100, 104)]
            pulls.append((number, {'start_ms': 0, 'end_ms': 120000, 'analysis': {
                'incoming': self.summarize(extra, {}, silent=[('A', 6, 25)]),
                'cooldowns': [{'t': 10000, 'name': 'A', 'ability_id': self.DEF, 'ability': 'Astral Shift',
                               'category': 'personal'}],
                'abilities': [{'id': 66, 'name': 'Shadow Brand'}], 'deaths': []}}))
        pulls.append((3, {'start_ms': 0, 'end_ms': 120000, 'analysis': good}))
        found = {i['tone']: i['text'] for i in coach.defensive_insights(pulls, 'A', 'dps')}
        self.assertIn('Astral Shift up for the raid-wide Blight Vein (pull #3, 0:29)', found['good'])
        self.assertIn('Shadow Brand hit you hard with none up', found['bad'])
        self.assertEqual(coach.defensive_insights(pulls, 'A', 'tank'), [])

    def test_better_safe_than_sorry_isnt_held_against_you(self):
        """
        Boopsproops' Obsidian Scales up through a soak (1.5-1.8× his usual, not "heavy"): what a defensive prevents
        doesn't show in the damage - no tip, even with big unprotected hits elsewhere in the night.
        """
        from raidanalysis import coach
        pulls = []
        for number in (1, 2):
            extra = [('A', sec, 7000, [self.DEF], 77) for sec in range(10, 20)]      # soaking with Scales up
            extra += [('A', sec, 150000, [], 66) for sec in range(100, 104)]          # a big hit with nothing up
            pulls.append((number, {'start_ms': 0, 'end_ms': 120000, 'analysis': {
                'incoming': self.summarize(extra, {'A': [[9500, self.DEF]]}),
                'cooldowns': [{'t': 9500, 'name': 'A', 'ability_id': self.DEF, 'ability': 'Obsidian Scales',
                               'category': 'personal'}],
                'abilities': [{'id': 66, 'name': 'Shadow Brand'}], 'deaths': []}}))
        self.assertFalse([i for i in coach.defensive_insights(pulls, 'A', 'dps') if i['tone'] == 'bad'])

    MIASMA = 1288232
    SCALES, SHIELD = 363916, 642

    def soak_pull(self, number, spell, sid, immune=False):
        """A pull where A soaks Unstable Miasma at 0:40 with a defensive (Scales: hits for less; a bubble: immune)."""
        if immune:
            extra, imm = [], [('A', sec, self.MIASMA, [sid]) for sec in range(40, 46)]
        else:
            extra, imm = [('A', sec, 8000, [sid], self.MIASMA) for sec in range(40, 46)], []
        return (number, {'start_ms': 0, 'end_ms': 120000, 'analysis': {
            'incoming': self.summarize(extra, {'A': [[39500, sid]]}, defensive_ids={'A': {sid}}, immune=imm),
            'cooldowns': [{'t': 39500, 'name': 'A', 'ability_id': sid, 'ability': spell, 'category': 'personal'}],
            'abilities': [{'id': self.MIASMA, 'name': 'Unstable Miasma'}], 'deaths': []}})

    @staticmethod
    def guide_for(ability_id, name):
        if name == 'Unstable Miasma':
            return {'name': name, 'category': 'Soak together', 'subtitle': 'Soak'}
        return None

    def test_soaking_with_a_defensive_is_praised(self):
        """Boopsproops' Obsidian Scales up to soak Unstable Miasma: taking a mechanic for the team."""
        from raidanalysis import coach
        found = coach.defensive_insights([self.soak_pull(37, 'Obsidian Scales', self.SCALES)], 'A', 'dps', self.guide_for)
        soak = next(i for i in found if i['kind'] == 'soak')
        self.assertEqual(soak['tone'], 'good')
        self.assertEqual([i['kind'] for i in found], ['soak'])                     # not praised twice for one press
        self.assertIn('Took mechanics for the team with Obsidian Scales up - Unstable Miasma (1×: #37 0:39)', soak['text'])
        self.assertEqual(soak['ability'], {'id': self.MIASMA, 'name': 'Unstable Miasma'})
        # Without a guide that says to take it: no soak praise (it was just damage)
        self.assertFalse([i for i in coach.defensive_insights([self.soak_pull(37, 'Obsidian Scales', self.SCALES)],
                                                             'A', 'dps', lambda i, n: None) if i['kind'] == 'soak'])

    def test_soaking_with_an_immunity_counts_too(self):
        """Divine Shield up for it: every hit is logged as immune for 0 - still what the bubble was up for."""
        from raidanalysis import coach
        found = coach.defensive_insights([self.soak_pull(5, 'Divine Shield', self.SHIELD, immune=True)], 'A', 'dps',
                                         self.guide_for)
        self.assertIn('with Divine Shield up - Unstable Miasma', next(i for i in found if i['kind'] == 'soak')['text'])

    def test_player_page_shows_the_coach(self):
        from raidanalysis.web import routes
        player = {'name': 'A', 'role': 'dps', 'feedback': [{'tone': 'bad', 'text': 'Hit by X', 'weight': 9, 'ability': None},
                                                          {'tone': 'good', 'text': 'No deaths', 'weight': 1, 'ability': None}]}
        notes = routes._coach_notes(9999, [self.soak_pull(37, 'Obsidian Scales', self.SCALES)], player, self.guide_for)
        self.assertEqual([n['text'][:10] for n in notes], ['Hit by X', 'No deaths', 'Took mecha'])

    def test_older_pulls_say_nothing(self):
        from raidanalysis import coach
        pulls = [(1, {'start_ms': 0, 'end_ms': 60000, 'analysis': {'cooldowns': [
            {'t': 1000, 'name': 'A', 'ability_id': self.DEF, 'ability': 'Astral Shift', 'category': 'personal'}]}})]
        self.assertEqual(coach.defensive_insights(pulls, 'A', 'dps'), [])


class TestCoachNamesProcs(unittest.TestCase):
    """A proc / aura known only by its spell id gets its name (or no tip at all - never "your a proc procs")."""

    def run_procs(self, cached):
        from unittest import mock
        from raidanalysis import coach, db, throughput
        rows = [{'name': '392883', 'id': 392883, 'ours': 0.58, 'top': 0.25, 'verdict': 'off'}]
        data = {'top': [{}], 'label': 'Mistweaver Monks', 'rows': [], 'player': {}}
        with mock.patch.object(throughput, 'cpm', lambda *a: None), \
                mock.patch.object(throughput, 'raid_buff', lambda *a: None), \
                mock.patch.object(throughput, 'uptime', lambda *a: []), \
                mock.patch.object(throughput, 'proc_rows', lambda *a: rows), \
                mock.patch.object(throughput, 'active_time', lambda *a: (None, None)), \
                mock.patch.object(db, 'get_spells', lambda ids: cached), \
                mock.patch.object(db, 'attempted_spell_ids', lambda ids: set(ids)):
            return [i['text'] for i in coach.rotation_insights([], 'Boopsboops', 'healer', data)]

    def test_named_from_the_spell_cache(self):
        texts = self.run_procs({392883: {'name': 'Vivacious Vivification'}})
        self.assertEqual(texts[0].split(' - ')[0], '58% of your Vivacious Vivification procs wasted')

    def test_no_name_no_tip(self):
        self.assertEqual(self.run_procs({}), [])


class TestUpgradedHots(unittest.TestCase):
    """Merithra's Blessing and the Reversion HoTs it leaves are both the Evoker's - each graded on its own."""
    DUR = 520000

    def test_sync_keeps_the_reversions_an_upgraded_cast_applies(self):
        from raidanalysis import throughput
        table = {'auras': [{'guid': 366155, 'name': 'Reversion', 'totalUptime': 0.05 * self.DUR},
                           {'guid': 367364, 'name': 'Reversion', 'totalUptime': 0.75 * self.DUR},
                           {'guid': 1256579, 'name': "Merithra's Blessing", 'totalUptime': 0.72 * self.DUR},
                           {'guid': 9, 'name': 'Some Trinket Proc', 'totalUptime': 0.5 * self.DUR}]}
        kept = {a['name']: round(a['uptime'] / self.DUR, 2) for a in
                throughput.on_others(table, self.DUR, {"Merithra's Blessing": 30, 'Echo': 40})}
        self.assertEqual(kept, {'Reversion': 0.75, "Merithra's Blessing": 0.72})  # not the trinket

    def test_graded_separately(self):
        from raidanalysis import throughput
        top = [{'duration': self.DUR, 'on_others': [{'id': 366155, 'name': 'Reversion', 'uptime': 0.8 * self.DUR},
                                                    {'id': 1256579, 'name': "Merithra's Blessing", 'uptime': 0.7 * self.DUR}]}
               for _ in range(3)]
        mine = [{'id': 367364, 'name': 'Reversion', 'uptime': 0.75 * self.DUR},
                {'id': 1256579, 'name': "Merithra's Blessing", 'uptime': 0.72 * self.DUR}]
        pull = (1, {'analysis': {'extras': {'detail': True, 'duration': self.DUR, 'players': {
            'Boopsproops': {'on_others': mine, 'casts': {"Merithra's Blessing": 30}}}}}})
        rows = {r['name']: r for r in throughput.on_others_rows([pull], 'Boopsproops', top)}
        self.assertEqual(set(rows), {'Reversion', "Merithra's Blessing"})
        self.assertAlmostEqual(rows['Reversion']['ours'], 0.75)
        self.assertAlmostEqual(rows["Merithra's Blessing"]['ours'], 0.72)
        self.assertFalse(rows['Reversion']['not_taken'])  # never cast by that name, but theirs
        self.assertNotEqual(rows['Reversion']['verdict'], 'off')

    def test_backfill_fetches_the_table_again(self):
        import asyncio
        from unittest import mock
        from raidanalysis import db, sync, wcl
        extras = {'duration': self.DUR, 'players': {
            'Boopsproops': {'casts': {"Merithra's Blessing": 30},
                            'on_others': [{'id': 1256579, 'name': "Merithra's Blessing", 'uptime': 0.72 * self.DUR}]},
            'Futhark': {'casts': {'Aimed Shot': 50}, 'on_others': None}}}
        saved = []
        table = {'auras': [{'guid': 367364, 'name': 'Reversion', 'totalUptime': 0.75 * self.DUR},
                           {'guid': 1256579, 'name': "Merithra's Blessing", 'totalUptime': 0.72 * self.DUR}]}

        async def ok(session):
            return True

        async def actor_ids(session, code):
            return {'Boopsproops': 7, 'Futhark': 8}

        async def player_tables(session, code, fight_id, aids, bosses=(), casts=False, others=(), targets=False):
            self.assertEqual(aids, [7])  # only the Evoker
            return {7: {'on_others': table}}
        with mock.patch.object(db, 'pulls_missing_applied_hots', lambda casts, limit: [
                {'report_code': 'C', 'fight_id': 14, 'start_ms': 0, 'end_ms': self.DUR, 'extras': extras}]), \
                mock.patch.object(db, 'set_pull_extras', lambda code, fid, ex: saved.append(ex)), \
                mock.patch.object(sync, '_budget_ok', ok), mock.patch.object(wcl, 'get_actor_ids', actor_ids), \
                mock.patch.object(wcl, 'get_player_tables', player_tables):
            asyncio.run(sync._backfill_applied_hots(None))
        names = {a['name'] for a in saved[0]['players']['Boopsproops']['on_others']}
        self.assertEqual(names, {'Reversion', "Merithra's Blessing"})
        self.assertTrue(saved[0]['applied_hots'])


class TestIcons(unittest.TestCase):
    def test_every_mapped_icon_has_its_drawing_and_every_drawing_is_used(self):
        from raidanalysis.web import icons
        used = {v[0] for v in icons.EMOJI.values()} | {name for name, _ in icons.LEGENDARIES} | {'luminis'}
        self.assertEqual(used - set(icons._SVGS), set())  # a renamed file breaks its emoji
        self.assertEqual(set(icons._SVGS) - used, set())  # a drawing nothing shows

    def test_every_drawing_has_a_body_to_glow_from(self):
        from raidanalysis.web import icons
        for name, text in icons._SVGS.items():
            self.assertEqual(text.count('<g id="body">'), 1, name)

    def test_iconize_swaps_text_only(self):
        from raidanalysis.web import icons
        html = icons.iconize('<span title="⚔ DPS">⚔ Damage</span><script>"⚔"</script>')
        self.assertIn('class="ic ic-blade ic-dps"', html)
        self.assertIn(f'src="{icons.URL_BASE}dps/blade.svg"', html)
        self.assertIn('title="⚔ DPS"', html)
        self.assertIn('<script>"⚔"</script>', html)
        self.assertEqual(icons.iconize(html), html)
        self.assertIn('class="ic ic-blade ic-dps no-legendary"', icons.iconize('🗡️ Arms Warrior'))  # role marker

    def test_a_tone_glows_from_the_body_in_place_of_the_aura(self):
        from raidanalysis.web import icons
        plain, toned = icons.svg('healthstone'), icons.svg('healthstone', 'good')
        self.assertIn('<g class="aura">', plain)
        self.assertNotIn('<g class="aura">', toned)
        self.assertIn('<use href="#body" filter="url(#tone)"/><g id="body">', toned)
        self.assertIn(icons.TONES['good'], toned)
        self.assertIn('<g class="fx">', toned)  # the glimmer stays, unglowed
        self.assertIsNone(icons.svg('healthstone', 'nope'))
        self.assertIsNone(icons.svg('nope'))

    def test_icon_route_serves_them(self):
        import asyncio
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request
        from raidanalysis.web import icons, routes

        def get(version, tone, file):
            request = make_mocked_request('GET', f'/raids/static/icons/{version}/{tone}/{file}',
                                          match_info={'version': version, 'tone': tone, 'file': file})
            return asyncio.run(routes.handle_icon(request))
        response = get(icons.VERSION, 'bad', 'skull.svg')
        self.assertEqual(response.content_type, 'image/svg+xml')
        self.assertIn('immutable', response.headers['Cache-Control'])
        self.assertIn('max-age=300', get('0ld', 'bad', 'skull.svg').headers['Cache-Control'])
        with self.assertRaises(web.HTTPNotFound):
            get(icons.VERSION, 'plain', '..%2Fsecret.svg')

    def test_page_script_knows_the_legendaries(self):
        from raidanalysis.web import render
        self.assertNotIn('__LEGENDARIES__', render.PAGE_JS)
        self.assertIn('Thunderfury, Blessed Blade of the Windseeker', render.PAGE_JS)
