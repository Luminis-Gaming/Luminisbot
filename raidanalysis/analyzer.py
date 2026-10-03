"""
Turns raw WCL tables/events for one pull into the compact analysis we store.

Pure functions only (no I/O) so they can be tested against saved WCL JSON.
The stored analysis is tag-independent: which abilities count as "avoidable"
is applied at render time, so retagging a mechanic never needs a re-sync.
"""

ANALYSIS_VERSION = 2

# Officer tags on boss abilities (stored in raid_ability_tags).
TAG_AVOIDABLE = 'avoidable'                   # any hit is a mistake
TAG_AVOIDABLE_NON_TANK = 'avoidable_nontank'  # tanks are meant to take it
TAG_IGNORE = 'ignore'                         # hide from tables
AVOIDABLE_TAGS = {TAG_AVOIDABLE, TAG_AVOIDABLE_NON_TANK}

# Combat/mana potions whose names don't say "potion" (Midnight). Names containing
# "potion" are picked up automatically; add the odd ones here each expansion.
COMBAT_POTION_IDS = {1236616, 1236648, 1236994, 1236998, 1238443, 1239479, 1295015, 1295132}
# Healthstones and healing potions (names with healthstone/health potion also match).
DEFENSIVE_IDS = {6262, 452930, 1234768, 1235568, 1236590, 1238009, 1263074, 1295247}

# Damage-taken abilities with at most this many events get fetched as events,
# giving every player's hits. Above it they're raid-wide pulses/ticks where the
# table's top-5 breakdown is enough (tagged abilities are always fetched).
EVENT_FETCH_MAX_EVENTS = 400

# A pull counts as "wiped" from the moment this share of the raid is dead;
# deaths after that are flagged so they don't count against anyone.
WIPE_DEATH_SHARE = 0.5

HOSTILE_SOURCE_TYPES = {'Boss', 'NPC'}
MELEE_ABILITY_ID = 1


def _entries(table):
    """Tables nest entries differently (interrupts/dispels add a level)."""
    entries = (table or {}).get('entries') or []
    if len(entries) == 1 and isinstance(entries[0], dict) and 'entries' in entries[0] \
            and 'guid' not in entries[0]:
        return entries[0]['entries'] or []
    return entries


def hostile_damage_entries(damage_taken_table):
    """Damage-taken-by-ability entries that came from enemies (not stagger, trinkets, ...)."""
    out = []
    for entry in _entries(damage_taken_table):
        source_types = {s.get('type') for s in entry.get('sources') or []}
        if source_types and source_types <= HOSTILE_SOURCE_TYPES:
            out.append(entry)
        elif not source_types and entry.get('actorType') in HOSTILE_SOURCE_TYPES:
            out.append(entry)
    return out


def event_ability_ids(hostile_entries, tagged_ids=()):
    """Which hostile abilities to fetch as events for a complete per-player breakdown."""
    ids = set()
    for entry in hostile_entries:
        count = (entry.get('hitCount') or 0) + (entry.get('tickCount') or 0)
        if count <= EVENT_FETCH_MAX_EVENTS or entry.get('guid') in tagged_ids:
            ids.add(entry['guid'])
    return sorted(ids)


def consumable_ids(casts_table):
    """
    (combat/mana potion IDs, healthstone/healing potion IDs), found by name so
    new expansions just work.
    """
    potions, defensives = set(), set()
    for entry in _entries(casts_table):
        guid = entry.get('guid')
        name = (entry.get('name') or '').lower()
        if guid in DEFENSIVE_IDS or 'healthstone' in name \
                or ('potion' in name and ('health' in name or 'healing' in name)):
            defensives.add(guid)
        elif guid in COMBAT_POTION_IDS or 'potion' in name:
            potions.add(guid)
    return sorted(potions), sorted(defensives)


def _event_ability(event):
    if 'abilityGameID' in event:
        return event['abilityGameID']
    return (event.get('ability') or {}).get('guid')


def _roster(fight, actors, player_details):
    """name -> {class, spec, role} for every player in the pull."""
    by_id = {a['id']: a for a in actors}
    roster = {}
    for actor_id in fight.get('friendlyPlayers') or []:
        actor = by_id.get(actor_id)
        if actor:
            roster[actor['name']] = {'name': actor['name'], 'class': actor.get('subType') or '',
                                     'spec': '', 'role': 'dps'}

    details = (player_details or {}).get('playerDetails', player_details) or {}
    for role_key, role in (('tanks', 'tank'), ('healers', 'healer'), ('dps', 'dps')):
        for entry in details.get(role_key) or []:
            player = roster.setdefault(entry['name'], {'name': entry['name'],
                                                       'class': entry.get('type') or '', 'spec': '', 'role': role})
            player['role'] = role
            icon = entry.get('icon') or ''
            if '-' in icon:
                player['spec'] = icon.split('-', 1)[1]
            player['class'] = player['class'] or entry.get('type') or ''
    return roster


def analyze_fight(fight, actors, tables, damage_events, consumable_events, potion_ids, defensive_ids):
    """
    Build the stored analysis for one pull.

    fight: a `fights` entry from the report overview (absolute ms timestamps).
    actors: masterData player actors. tables: output of wcl.get_fight_tables.
    """
    fight_start = fight['startTime']
    roster = _roster(fight, actors, tables.get('playerDetails'))
    names_by_id = {a['id']: a['name'] for a in actors}
    raid_size = fight.get('size') or len(roster) or 20

    # --- Deaths, in order, with the moment the pull was effectively over ---
    deaths = []
    for entry in sorted(_entries(tables.get('deaths')), key=lambda e: e.get('timestamp') or 0):
        if entry.get('name') not in roster:
            continue  # pets / NPC allies
        blow = entry.get('killingBlow') or {}
        deaths.append({
            't': (entry.get('timestamp') or fight_start) - fight_start,
            'name': entry['name'],
            'ability': blow.get('name') or 'Unknown',
            'ability_id': blow.get('guid'),
            'icon': blow.get('abilityIcon'),
        })
    wipe_at = None
    if not fight.get('kill'):
        threshold = max(1, int(raid_size * WIPE_DEATH_SHARE + 0.5))
        if len(deaths) >= threshold:
            wipe_at = deaths[threshold - 1]['t']
    for death in deaths:
        death['after_wipe'] = wipe_at is not None and death['t'] > wipe_at

    # --- Damage taken from enemy abilities ---
    abilities = {}
    for entry in hostile_damage_entries(tables.get('damageTaken')):
        sources = [s.get('name') for s in entry.get('sources') or [] if s.get('name')]
        abilities[entry['guid']] = {
            'id': entry['guid'],
            'name': entry.get('name'),
            'icon': entry.get('abilityIcon'),
            'source': entry.get('actorName') or ', '.join(sources[:2]),
            'total': entry.get('total') or 0,
            'events': (entry.get('hitCount') or 0) + (entry.get('tickCount') or 0),
            # Top-5 only until events fill it in.
            'players': {t['name']: {'damage': t.get('total') or 0, 'hits': None}
                        for t in entry.get('targets') or [] if t.get('name') in roster},
            'complete': False,
        }
    fetched = {}
    for event in damage_events:
        if event.get('type') != 'damage':
            continue
        name = names_by_id.get(event.get('targetID'))
        guid = _event_ability(event)
        if name not in roster or guid not in abilities:
            continue
        damage = (event.get('amount') or 0) + (event.get('absorbed') or 0)
        if not damage:
            continue  # immuned/missed - not a hit, and would skew the hit-vs-tick split
        per_player = fetched.setdefault(guid, {}).setdefault(name, {'damage': 0, 'hits': 0, 'ticks': 0})
        per_player['damage'] += damage
        per_player['ticks' if event.get('tick') else 'hits'] += 1
    for guid, players in fetched.items():
        abilities[guid]['players'] = players
        abilities[guid]['complete'] = True

    # --- Interrupts & dispels ---
    def _breakdown(table, count_key):
        out = []
        for entry in _entries(table):
            by = {d['name']: d.get('total') or 0 for d in entry.get('details') or []
                  if d.get('name') in roster}
            out.append({'id': entry.get('guid'), 'name': entry.get('name'),
                        'icon': entry.get('abilityIcon'),
                        'begun': entry.get('spellsBegun') or 0,
                        'count': entry.get(count_key) or 0, 'by': by})
        return out

    interrupts = _breakdown(tables.get('interrupts'), 'spellsInterrupted')
    dispels = _breakdown(tables.get('dispels'), 'spellsInterrupted')

    # --- Consumables ---
    potions, defensives = {}, {}
    for event in consumable_events:
        if event.get('type') != 'cast':
            continue
        name = names_by_id.get(event.get('sourceID'))
        if name not in roster:
            continue
        guid = _event_ability(event)
        if guid in potion_ids:
            potions[name] = potions.get(name, 0) + 1
        elif guid in defensive_ids:
            defensives[name] = defensives.get(name, 0) + 1

    return {
        'version': ANALYSIS_VERSION,
        'players': sorted(roster.values(), key=lambda p: ({'tank': 0, 'healer': 1}.get(p['role'], 2), p['name'])),
        'deaths': deaths,
        'wipe_at': wipe_at,
        'abilities': sorted(abilities.values(), key=lambda a: -a['total']),
        'interrupts': interrupts,
        'dispels': dispels,
        'potions': potions,
        'defensives': defensives,
    }


# ============================================================================
# Render-time helpers (apply officer tags, aggregate across pulls)
# ============================================================================

def mistake_counts(ability):
    """
    name -> number of times hit. Direct hits only (a DoT ticking after one
    mistake is still one mistake), unless the ability only ever ticks - auras
    and pools you stand in - where every tick is time spent standing in it.
    """
    players = ability.get('players') or {}
    direct = any(p.get('hits') for p in players.values())
    return {name: (p.get('hits') if direct else p.get('ticks')) or 0 for name, p in players.items()}


def avoidable_by_player(analysis, tags):
    """name -> {'damage', 'hits'} summed over the abilities tagged avoidable."""
    roles = {p['name']: p.get('role') for p in analysis.get('players') or []}
    out = {}
    for ability in analysis.get('abilities') or []:
        tag = tags.get(ability['id'])
        if tag not in AVOIDABLE_TAGS:
            continue
        counts = mistake_counts(ability)
        for name, stats in (ability.get('players') or {}).items():
            if tag == TAG_AVOIDABLE_NON_TANK and roles.get(name) == 'tank':
                continue
            if not counts.get(name):
                continue
            row = out.setdefault(name, {'damage': 0, 'hits': 0})
            row['damage'] += stats.get('damage') or 0
            row['hits'] += counts[name]
    return out


def scoreboard(analyses, tags):
    """
    Per-player totals across several pulls - the "who needs a word" table.
    Deaths only count before the wipe moment; first deaths likewise.
    """
    rows = {}

    def row(player):
        return rows.setdefault(player['name'], {
            'name': player['name'], 'class': player.get('class') or '', 'spec': player.get('spec') or '',
            'role': player.get('role') or 'dps', 'pulls': 0, 'deaths': 0, 'first_deaths': 0,
            'avoidable_hits': 0, 'avoidable_damage': 0, 'interrupts': 0, 'dispels': 0,
            'potion_pulls': 0, 'potions': 0, 'defensives': 0, 'alive_ms': 0, 'pull_ms': 0})

    for analysis in analyses:
        duration = analysis.get('_duration') or 0
        roster = {p['name']: p for p in analysis.get('players') or []}
        for player in roster.values():
            r = row(player)
            r['pulls'] += 1
            r['pull_ms'] += duration

        counted = [d for d in analysis.get('deaths') or [] if not d.get('after_wipe')]
        death_time = {}
        for i, death in enumerate(counted):
            if death['name'] in roster:
                rows[death['name']]['deaths'] += 1
                death_time.setdefault(death['name'], death['t'])
                if i == 0:
                    rows[death['name']]['first_deaths'] += 1
        end = analysis.get('wipe_at') or duration
        for name in roster:
            rows[name]['alive_ms'] += min(death_time.get(name, end), end)

        for name, stats in avoidable_by_player(analysis, tags).items():
            if name in rows:
                rows[name]['avoidable_hits'] += stats['hits']
                rows[name]['avoidable_damage'] += stats['damage']
        for key in ('interrupts', 'dispels'):
            for entry in analysis.get(key) or []:
                for name, count in entry['by'].items():
                    if name in rows:
                        rows[name][key] += count
        for name, count in (analysis.get('potions') or {}).items():
            if name in rows:
                rows[name]['potions'] += count
                rows[name]['potion_pulls'] += 1
        for name, count in (analysis.get('defensives') or {}).items():
            if name in rows:
                rows[name]['defensives'] += count

    return sorted(rows.values(), key=lambda r: ({'tank': 0, 'healer': 1}.get(r['role'], 2), r['name']))


def killers(analyses):
    """Abilities that killed players before the wipe moment, most lethal first."""
    out = {}
    for analysis in analyses:
        for death in analysis.get('deaths') or []:
            if death.get('after_wipe'):
                continue
            key = death.get('ability_id') or death['ability']
            entry = out.setdefault(key, {'id': death.get('ability_id'), 'name': death['ability'],
                                         'icon': death.get('icon'), 'count': 0, 'players': {}})
            entry['count'] += 1
            entry['players'][death['name']] = entry['players'].get(death['name'], 0) + 1
    return sorted(out.values(), key=lambda e: -e['count'])


def suggest_avoidable(analyses, tagged_ids):
    """
    Untagged abilities that look like personal-responsibility mechanics: across
    the given pulls they only ever hit a small share of the raid, and never by
    a large number of events (which would mean raid-wide pulses).
    """
    seen, tank_only = {}, set()
    for analysis in analyses:
        raid = max(1, len(analysis.get('players') or []))
        tanks = {p['name'] for p in analysis.get('players') or [] if p.get('role') == 'tank'}
        for ability in analysis.get('abilities') or []:
            if ability['id'] in tagged_ids or ability['id'] == MELEE_ABILITY_ID \
                    or not ability.get('complete') or not ability.get('total'):
                continue
            hit = set(ability.get('players') or {})
            if hit and hit <= tanks:
                tank_only.add(ability['id'])  # tank mechanic - few players hit by design
                continue
            stats = seen.setdefault(ability['id'], {'name': ability['name'], 'icon': ability.get('icon'),
                                                    'pulls': 0, 'share_sum': 0.0, 'hits': 0})
            stats['pulls'] += 1
            stats['share_sum'] += len(ability.get('players') or {}) / raid
            stats['hits'] += sum(mistake_counts(ability).values())
    out = []
    for guid, stats in seen.items():
        if guid in tank_only:
            continue
        share = stats['share_sum'] / stats['pulls']
        if share <= 0.35:
            out.append({'id': guid, 'name': stats['name'], 'icon': stats['icon'],
                        'avg_share': share, 'hits': stats['hits'], 'pulls': stats['pulls']})
    return sorted(out, key=lambda s: -s['hits'])
