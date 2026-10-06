"""
Turns raw WCL tables/events for one pull into the compact analysis we store.

Pure functions only (no I/O) so they can be tested against saved WCL JSON.
The stored analysis is tag-independent: which abilities count as "avoidable"
is applied at render time, so retagging a mechanic never needs a re-sync.
"""

ANALYSIS_VERSION = 7

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


def cast_entries(casts_table):
    """
    Every ability in a Casts table, including the variants WCL nests under a parent: a 'composite'
    entry like Immolation Aura lists Consuming Fire (cast during Metamorphosis) only as a sub-entry.
    The raw cast events carry the variant's own spell id, so anything we fetch or look for has to
    include them - top-level entries alone miss those casts entirely.
    """
    out = []
    for entry in _entries(casts_table):
        out.append(entry)
        out.extend(sub for sub in entry.get('subentries') or [] if isinstance(sub, dict) and sub.get('guid'))
    return out


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
    for entry in cast_entries(casts_table):
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


# Which deaths count against a player ("early deaths by mistake"): only the first few of a
# pull, and never one that's part of a mass death (raid-wide mechanic, enrage, collapse).
EARLY_DEATH_LIMIT = 4           # if 4 others already died, yours doesn't count
MASS_DEATH_WINDOW_MS = 3000     # deaths this close together ...
MASS_DEATH_SIZE = 3             # ... this many of them = a mass death, not a personal mistake


# A damage event that landed (a normal hit or a crit) counts as a hit even at 0 damage: Shell Spin's shells
# only stun - every hit is a 0-damage event. Misses, immunes, dodges and the like don't count.
LANDED_HIT_TYPES = {1, 2}


def merge_same_name(abilities):
    """
    One entry per ability *name*: a mechanic is often logged under several spell ids (Evil Eyes' cast and its
    damage, Shell Spin's two waves) - counted, tagged and shown as one. The merged entry keeps the id that did
    the most damage ('ids': all of them), the damage, events and every player's hits added up; it's
    `complete` only if every part was. Idempotent; entries without a name stay as they are.
    """
    groups, out = {}, []
    for ability in abilities or []:
        name = ability.get('name')
        if not name:
            out.append(ability)
            continue
        groups.setdefault(name, []).append(ability)
    for name, parts in groups.items():
        if len(parts) == 1:
            out.append(dict(parts[0], ids=parts[0].get('ids') or [parts[0]['id']]))
            continue
        main = max(parts, key=lambda a: (a.get('total') or 0, -(a['id'] or 0)))
        players = {}
        for part in parts:
            for player, stats in (part.get('players') or {}).items():
                row = players.setdefault(player, {'damage': 0, 'hits': None, 'ticks': None})
                row['damage'] += stats.get('damage') or 0
                for key in ('hits', 'ticks'):
                    if stats.get(key) is not None:
                        row[key] = (row[key] or 0) + stats[key]
                for key in ('times', 'tick_times'):
                    if stats.get(key):
                        row[key] = sorted((row.get(key) or []) + stats[key])
        sources = list(dict.fromkeys(p.get('source') for p in parts if p.get('source')))
        out.append(dict(main, ids=sorted({i for p in parts for i in (p.get('ids') or [p['id']])}),
                        source=', '.join(sources), total=sum(p.get('total') or 0 for p in parts),
                        events=sum(p.get('events') or 0 for p in parts), players=players,
                        complete=all(p.get('complete') for p in parts)))
    return sorted(out, key=lambda a: -(a.get('total') or 0))


def annotate_deaths(analysis):
    """
    Mark every death in a pull with 'order' (1-based), 'mass' (died together with 2+ others) and
    'early' (counts as a personal mistake: one of the first 4 deaths and not part of a mass death) - and
    merge abilities logged under several spell ids into one per name (merge_same_name): every page reads
    a pull through here. Idempotent; works on stored analyses of any version.
    """
    deaths = sorted(analysis.get('deaths') or [], key=lambda d: d['t'])
    for i, death in enumerate(deaths):
        together = sum(1 for other in deaths if abs(other['t'] - death['t']) <= MASS_DEATH_WINDOW_MS)
        death['order'] = i + 1
        death['mass'] = together >= MASS_DEATH_SIZE
        death['early'] = i < EARLY_DEATH_LIMIT and not death['mass']
    analysis['deaths'] = deaths
    if analysis.get('abilities'):
        analysis['abilities'] = merge_same_name(analysis['abilities'])
    return analysis


def death_note(death):
    """Why a death does or doesn't count, for tables and tooltips."""
    if death.get('early'):
        return 'early death by mistake'
    if death.get('mass'):
        return 'part of a mass death'
    return f"death #{death.get('order', '?')} — not counted"


def _killing_blow(death):
    """
    (ability, inferred) for a WCL death entry. WCL sometimes records no killing
    blow; then use the last damaging hit before death, else the biggest damage
    source in the death window - flagged as inferred so the UI can say "likely".
    """
    if death.get('killingBlow'):
        return death['killingBlow'], False
    for event in death.get('events') or []:  # newest first
        if event.get('type') == 'damage' and (event.get('amount') or 0) + (event.get('absorbed') or 0) > 0 \
                and event.get('ability'):
            return event['ability'], True
    top = ((death.get('damage') or {}).get('abilities') or [])
    if top:
        return top[0], True
    return {}, False


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


PREPOT_GRACE_MS = 2000       # a cast this close to a buff's start belongs to it
HEAL_MERGE_MS = 1500         # heal events this close together are one healthstone / potion
BOSS_CAST_SPAM_LIMIT = 40    # enemy abilities cast more often than this per pull are left off the timeline


# Abilities the whole raid casts at most this often in a pull are fetched as events and kept per
# player: cooldowns, trinkets, potions, defensives - what the top-player comparison looks at.
# Rotational spells (cast hundreds of times) stay out.
RARE_CAST_LIMIT = 30


def rare_cast_ids(casts_table):
    """Spell IDs from the pull's Casts table cast rarely enough to keep every cast of (see RARE_CAST_LIMIT)."""
    return sorted({e['guid'] for e in cast_entries(casts_table)
                   if e.get('guid') and 0 < (e.get('total') or 0) <= RARE_CAST_LIMIT})


def _player_casts(fight_start, names_by_id, roster, cast_events):
    """{player: [[t, spell id], ...]} for every cast event we fetched (rare abilities, potions, cooldowns)."""
    out = {}
    for event in sorted((e for e in cast_events if e.get('type') == 'cast'), key=lambda e: e['timestamp']):
        name = names_by_id.get(event.get('sourceID'))
        if name in roster and _event_ability(event):
            out.setdefault(name, []).append([event['timestamp'] - fight_start, _event_ability(event)])
    return out


def _cooldown_uses(fight_start, names_by_id, roster, meta, cast_events):
    """
    Every cast of a tracked cooldown (see cooldowns.py): who, what, when, and on whom for
    externals. meta = {spell id: {'name', 'icon', 'category'}}.
    """
    uses = []
    for event in sorted((e for e in cast_events if e.get('type') == 'cast'), key=lambda e: e['timestamp']):
        guid, name = _event_ability(event), names_by_id.get(event.get('sourceID'))
        if guid not in meta or name not in roster:
            continue
        target = names_by_id.get(event.get('targetID'))
        uses.append({'t': event['timestamp'] - fight_start, 'name': name, 'ability_id': guid,
                     'ability': meta[guid]['name'], 'icon': meta[guid].get('icon'),
                     'category': meta[guid]['category'],
                     'target': target if target in roster and target != name else None})
    return uses


def _consumable_uses(fight_start, duration, names_by_id, roster, casts_table, consumable_events,
                     buff_events, heal_events, potion_ids, defensive_ids):
    """
    Every potion / healthstone use in a pull: who, what, when (ms into the pull),
    how long a combat potion's buff lasted, whether it was a pre-pot, and how
    much a healthstone / healing potion healed for.
    """
    meta = {e['guid']: {'name': e.get('name'), 'icon': e.get('abilityIcon')}
            for e in cast_entries(casts_table) if e.get('guid') in potion_ids | defensive_ids}

    def info(guid, event):
        fallback = (event.get('ability') or {})
        m = meta.get(guid) or {'name': fallback.get('name') or f'Spell {guid}', 'icon': fallback.get('abilityIcon')}
        return m['name'], m['icon']

    # Combat-potion buff windows, per (player, potion). A removebuff with no applybuff = pre-pot.
    windows = []
    open_buffs = {}
    for event in sorted(buff_events, key=lambda e: e['timestamp']):
        guid, name = _event_ability(event), names_by_id.get(event.get('targetID'))
        if guid not in potion_ids or name not in roster:
            continue
        t = event['timestamp'] - fight_start
        if event.get('type') == 'applybuff':
            open_buffs[(name, guid)] = {'name': name, 'guid': guid, 'start': t, 'end': None, 'event': event}
        elif event.get('type') == 'removebuff':
            window = open_buffs.pop((name, guid), None) or {'name': name, 'guid': guid, 'start': None,
                                                           'event': event}
            window['end'] = t
            windows.append(window)
    for window in open_buffs.values():
        window['end'] = duration
        windows.append(window)

    uses = []
    casts = [e for e in consumable_events if e.get('type') == 'cast']
    for event in sorted(casts, key=lambda e: e['timestamp']):
        guid, name = _event_ability(event), names_by_id.get(event.get('sourceID'))
        if name not in roster or guid not in potion_ids:
            continue
        t = event['timestamp'] - fight_start
        window = next((w for w in windows if w['name'] == name and w['guid'] == guid and w['start'] is not None
                       and abs(w['start'] - t) <= PREPOT_GRACE_MS and not w.get('used')), None)
        if window:
            window['used'] = True
        ability, icon = info(guid, event)
        uses.append({'t': t, 'name': name, 'ability_id': guid, 'ability': ability, 'icon': icon, 'kind': 'potion',
                     'end': window['end'] if window else None, 'prepot': False})
    for window in windows:
        if window['start'] is None:  # buff was already up when the pull started
            ability, icon = info(window['guid'], window['event'])
            uses.append({'t': 0, 'name': window['name'], 'ability_id': window['guid'], 'ability': ability,
                         'icon': icon, 'kind': 'potion', 'end': window['end'], 'prepot': True})

    # Healthstones / healing potions, with how much they healed for.
    last = {}
    for event in sorted(heal_events, key=lambda e: e['timestamp']):
        guid, name = _event_ability(event), names_by_id.get(event.get('sourceID'))
        if guid not in defensive_ids or name not in roster or event.get('type') != 'heal':
            continue
        t = event['timestamp'] - fight_start
        amount = (event.get('amount') or 0) + (event.get('absorbed') or 0)
        previous = last.get((name, guid))
        if previous and t - previous['t'] <= HEAL_MERGE_MS:
            previous['healing'] += amount
            continue
        ability, icon = info(guid, event)
        use = {'t': t, 'name': name, 'ability_id': guid, 'ability': ability, 'icon': icon, 'kind': 'defensive',
               'healing': amount}
        uses.append(use)
        last[(name, guid)] = use
    return sorted(uses, key=lambda u: (u['t'], u['name']))


# Pre-pull ("ready check") data from each player's combatantinfo event at the pull.
# The old ranged slot (17), shirt (3) and tabard (18) hold placeholder / cosmetic items - left out.
GEAR_SLOTS = {0: 'Head', 1: 'Neck', 2: 'Shoulders', 4: 'Chest', 5: 'Waist', 6: 'Legs', 7: 'Feet', 8: 'Wrists',
              9: 'Hands', 10: 'Ring', 11: 'Ring', 12: 'Trinket', 13: 'Trinket', 14: 'Back', 15: 'Main hand',
              16: 'Off hand'}
MIN_REAL_ITEM_LEVEL = 100   # anything below is a placeholder (item level 1 relics etc.)
TIER_SLOTS = (0, 2, 4, 6, 9)
RAID_BUFFS = ('Arcane Intellect', 'Power Word: Fortitude', 'Battle Shout', 'Mark of the Wild', 'Skyfury',
              'Blessing of the Bronze')


def _aura_kind(name):
    name = (name or '').lower()
    if 'flask' in name or 'phial' in name:
        return 'flask'
    if 'well fed' in name or name.endswith(' fed'):
        return 'food'
    if 'augment' in name:
        return 'augment'
    return None


def _prepull(names_by_id, roster, combatant_events):
    """{player: {'flask', 'food', 'augment', 'buffs', 'ilvl', 'enchants': {slot: bool}, 'gems', 'tier'}}."""
    out = {}
    for event in combatant_events:
        name = names_by_id.get(event.get('sourceID'))
        if name not in roster or event.get('type') != 'combatantinfo':
            continue
        found = {'flask': None, 'food': None, 'augment': None}
        buffs = []
        for aura in event.get('auras') or []:
            aura_name = aura.get('name') or ''
            kind = _aura_kind(aura_name)
            if kind and not found[kind]:
                found[kind] = aura_name
            if aura_name in RAID_BUFFS:
                buffs.append(aura_name)
        gear = event.get('gear') or []
        items = [(slot, item) for slot, item in enumerate(gear)
                 if item.get('id') and slot in GEAR_SLOTS and (item.get('itemLevel') or 0) >= MIN_REAL_ITEM_LEVEL]
        levels = [item.get('itemLevel') or 0 for _, item in items]
        out[name] = {**found, 'buffs': sorted(set(buffs)),
                     'ilvl': round(sum(levels) / len(levels), 1) if levels else None,
                     'enchants': {str(slot): bool(item.get('permanentEnchant')) for slot, item in items},
                     'gems': sum(len(item.get('gems') or []) for _, item in items),
                     'tier': sum(1 for slot, item in items if slot in TIER_SLOTS and item.get('setID'))}
    return out


def expected_enchant_slots(prepulls, share=0.6):
    """Slots most of the raid enchants (so expansion changes need no code changes)."""
    have, enchanted = {}, {}
    for player in prepulls:
        for slot, done in (player.get('enchants') or {}).items():
            have[slot] = have.get(slot, 0) + 1
            enchanted[slot] = enchanted.get(slot, 0) + (1 if done else 0)
    return {slot for slot, n in have.items() if n and enchanted[slot] / n >= share}


def _boss_timeline(fight_start, enemy_casts_table, enemy_cast_events):
    """Enemy ability casts for the timeline: ([[t, ability_id], ...], [{'id', 'name', 'icon', 'source'}])."""
    meta = {}
    for entry in _entries(enemy_casts_table):
        source = entry.get('actorName') or ''
        if source == 'Environment' or (entry.get('total') or 0) > BOSS_CAST_SPAM_LIMIT:
            continue
        meta[entry['guid']] = {'id': entry['guid'], 'name': entry.get('name'), 'icon': entry.get('abilityIcon'),
                               'source': source}
    casts = [[e['timestamp'] - fight_start, _event_ability(e)] for e in enemy_cast_events
             if e.get('type') == 'cast' and _event_ability(e) in meta]
    used = {guid for _, guid in casts}
    return sorted(casts), [m for guid, m in meta.items() if guid in used]


def analyze_fight(fight, actors, tables, damage_events, consumable_events, potion_ids, defensive_ids,
                  buff_events=(), heal_events=(), enemy_cast_events=(), combatant_events=(), cooldown_meta=None):
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
        blow, likely = _killing_blow(entry)
        deaths.append({
            't': (entry.get('timestamp') or fight_start) - fight_start,
            'name': entry['name'],
            'ability': blow.get('name') or 'Unknown',
            'ability_id': blow.get('guid'),
            'icon': blow.get('abilityIcon') or blow.get('icon'),
            'likely': likely,
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
        if not damage and event.get('hitType') not in LANDED_HIT_TYPES:
            continue  # immuned/missed - not a hit, and would skew the hit-vs-tick split
        per_player = fetched.setdefault(guid, {}).setdefault(name, {'damage': 0, 'hits': 0, 'ticks': 0,
                                                                     'times': [], 'tick_times': []})
        per_player['damage'] += damage
        per_player['ticks' if event.get('tick') else 'hits'] += 1
        per_player['tick_times' if event.get('tick') else 'times'].append(event['timestamp'] - fight_start)
    for guid, players in fetched.items():
        # Keep the timestamps that match how mistakes are counted (see mistake_counts).
        direct = any(p['hits'] for p in players.values())
        for p in players.values():
            if not direct:
                p['times'] = p['tick_times']
            del p['tick_times']
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
    duration = fight['endTime'] - fight_start
    uses = _consumable_uses(fight_start, duration, names_by_id, roster, tables.get('casts'), consumable_events,
                            buff_events, heal_events, set(potion_ids), set(defensive_ids))
    boss_casts, boss_abilities = _boss_timeline(fight_start, tables.get('enemyCasts'), enemy_cast_events)

    return annotate_deaths({
        'version': ANALYSIS_VERSION,
        'players': sorted(roster.values(), key=lambda p: ({'tank': 0, 'healer': 1}.get(p['role'], 2), p['name'])),
        'deaths': deaths,
        'wipe_at': wipe_at,
        'abilities': sorted(abilities.values(), key=lambda a: -a['total']),
        'interrupts': interrupts,
        'dispels': dispels,
        'potions': potions,
        'defensives': defensives,
        'consumables': uses,
        'cooldowns': _cooldown_uses(fight_start, names_by_id, roster, cooldown_meta or {}, consumable_events),
        'casts': _player_casts(fight_start, names_by_id, roster, consumable_events),
        'boss_casts': boss_casts,
        'boss_abilities': boss_abilities,
        'prepull': _prepull(names_by_id, roster, combatant_events),
    })


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


def count_spec(row, player):
    """
    A row's spec = the one played on the most of its pulls (ties: the latest), not the first pull's -
    people swap spec mid-night (a Havoc pull 1, then Devourer for the rest). Other specs are kept in
    row['spec_pulls'].
    """
    spec = player.get('spec') or ''
    if not spec:
        return
    counts = row.setdefault('spec_pulls', {})
    counts[spec] = counts.get(spec, 0) + 1
    order = list(counts)
    row['spec'] = max(counts, key=lambda s: (counts[s], order.index(s) if s != spec else len(order)))


def main_spec(pulls_players):
    """The spec played on the most pulls, from [player dict per pull] (ties: the latest); '' if unknown."""
    row = {}
    for player in pulls_players:
        count_spec(row, player)
    return row.get('spec', '')


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
            count_spec(r, player)

        deaths = annotate_deaths(analysis)['deaths']
        death_time = {}
        for death in deaths:
            death_time.setdefault(death['name'], death['t'])
            if death['early'] and death['name'] in roster:
                rows[death['name']]['deaths'] += 1
                if death['order'] == 1:
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


def merge_pulls(analyses):
    """
    Several pulls folded into one analysis-shaped dict (the "Overall" view):
    damage per mechanic and player, interrupts and dispels summed across pulls.
    An ability is only `complete` if every pull had its full per-player breakdown.
    """
    roster, abilities, interrupts, dispels = {}, {}, {}, {}
    for analysis in analyses:
        for player in analysis.get('players') or []:
            roster[player['name']] = player
        for ability in merge_same_name(analysis.get('abilities')):
            merged = abilities.setdefault(ability.get('name') or ability['id'], {
                'id': ability['id'], 'name': ability['name'], 'icon': ability.get('icon'),
                'source': ability.get('source'), 'total': 0, 'events': 0, 'pulls': 0,
                'players': {}, 'complete': True, 'ids': set(), 'by_id': {}})
            merged['ids'].update(ability.get('ids') or [ability['id']])
            merged['by_id'][ability['id']] = merged['by_id'].get(ability['id'], 0) + (ability.get('total') or 0)
            merged['total'] += ability.get('total') or 0
            merged['events'] += ability.get('events') or 0
            merged['pulls'] += 1
            merged['complete'] = merged['complete'] and bool(ability.get('complete'))
            for name, stats in (ability.get('players') or {}).items():
                row = merged['players'].setdefault(name, {'damage': 0, 'hits': 0, 'ticks': 0})
                for key in ('damage', 'hits', 'ticks'):
                    row[key] += stats.get(key) or 0
        for source, target in ((analysis.get('interrupts'), interrupts), (analysis.get('dispels'), dispels)):
            for entry in source or []:
                merged = target.setdefault(entry['id'], {'id': entry['id'], 'name': entry['name'],
                                                         'icon': entry.get('icon'), 'begun': 0, 'count': 0, 'by': {}})
                merged['begun'] += entry.get('begun') or 0
                merged['count'] += entry.get('count') or 0
                for name, count in entry['by'].items():
                    merged['by'][name] = merged['by'].get(name, 0) + count
    for merged in abilities.values():  # the id that did the most damage over the night names the mechanic
        by_id = merged.pop('by_id')
        merged['id'] = max(by_id, key=lambda i: (by_id[i], -i)) if by_id else merged['id']
        merged['ids'] = sorted(merged['ids'])
    return {
        'players': sorted(roster.values(), key=lambda p: ({'tank': 0, 'healer': 1}.get(p.get('role'), 2), p['name'])),
        'abilities': sorted(abilities.values(), key=lambda a: -a['total']),
        'interrupts': sorted(interrupts.values(), key=lambda e: -e['begun']),
        'dispels': sorted(dispels.values(), key=lambda e: -e['count']),
    }


def killers(analyses):
    """
    What's killing the raid, most lethal first: early deaths by mistake plus mass deaths
    (stragglers dying late, one by one, are left out). 'mistakes' / 'mass' split the count.
    """
    out = {}
    for analysis in analyses:
        for death in annotate_deaths(analysis)['deaths']:
            if not (death['early'] or death['mass']):
                continue
            key = death.get('ability_id') or death['ability']
            entry = out.setdefault(key, {'id': death.get('ability_id'), 'name': death['ability'],
                                         'icon': death.get('icon'), 'count': 0, 'mistakes': 0, 'mass': 0,
                                         'players': {}})
            entry['count'] += 1
            entry['mistakes' if death['early'] else 'mass'] += 1
            if death['early']:
                entry['players'][death['name']] = entry['players'].get(death['name'], 0) + 1
    return sorted(out.values(), key=lambda e: -e['count'])


def suggest_avoidable(analyses, tagged_ids):
    """
    Untagged abilities that look like personal-responsibility mechanics: across
    the given pulls they only ever hit a small share of the raid, and never by
    a large number of events (which would mean raid-wide pulses). One per ability name (merge_same_name):
    'id' names it, 'ids' are all its spell ids.
    """
    seen, tank_only = {}, set()
    for analysis in analyses:
        raid = max(1, len(analysis.get('players') or []))
        tanks = {p['name'] for p in analysis.get('players') or [] if p.get('role') == 'tank'}
        for ability in merge_same_name(analysis.get('abilities')):
            ids = set(ability.get('ids') or [ability['id']])
            if ids & set(tagged_ids) or MELEE_ABILITY_ID in ids \
                    or not ability.get('complete') or not ability.get('total'):
                continue
            key = ability.get('name') or ability['id']
            hit = set(ability.get('players') or {})
            if hit and hit <= tanks:
                tank_only.add(key)  # tank mechanic - few players hit by design
                continue
            stats = seen.setdefault(key, {'id': ability['id'], 'ids': set(), 'name': ability['name'],
                                          'icon': ability.get('icon'), 'pulls': 0, 'share_sum': 0.0, 'hits': 0})
            stats['ids'] |= ids
            stats['pulls'] += 1
            stats['share_sum'] += len(ability.get('players') or {}) / raid
            stats['hits'] += sum(mistake_counts(ability).values())
    out = []
    for key, stats in seen.items():
        if key in tank_only:
            continue
        share = stats['share_sum'] / stats['pulls']
        if share <= 0.35:
            out.append({'id': stats['id'], 'ids': sorted(stats['ids']), 'name': stats['name'], 'icon': stats['icon'],
                        'avg_share': share, 'hits': stats['hits'], 'pulls': stats['pulls']})
    return sorted(out, key=lambda s: -s['hits'])


# ============================================================================
# Player report: score + feedback (the "Players" tab)
# ============================================================================

# The score is a weighted mean of 0-100 components (100 = best), like Wipefest:
# survival, deaths, one per avoidable mechanic, potions and healthstones.
# Interrupts / dispels are contributions: shown, and averaged into a separate
# bonus score, but they don't move the main score.
COMPONENT_WEIGHTS = {'survival': 2.0, 'deaths': 1.0, 'mechanic': 1.0, 'potions': 1.0, 'defensives': 0.5}


def _rank_lower_better(value, values):
    """100 = clean (zero); otherwise the share of the raid doing worse, ties split."""
    if value <= 0:
        return 100.0
    if len(values) <= 1:
        return 50.0
    worse = sum(1 for v in values if v > value)
    ties = sum(1 for v in values if v == value) - 1
    return 100.0 * (worse + 0.5 * ties) / (len(values) - 1)


def _rank_higher_better(value, values):
    """100 = top of the raid; the share of the raid doing less, ties split."""
    if len(values) <= 1:
        return 100.0 if value > 0 else 50.0
    less = sum(1 for v in values if v < value)
    ties = sum(1 for v in values if v == value) - 1
    return 100.0 * (less + 0.5 * ties) / (len(values) - 1)


def _new_player_row(player):
    return {
        'name': player['name'], 'class': player.get('class') or '', 'spec': player.get('spec') or '',
        'role': player.get('role') or 'dps', 'pulls': 0, 'pull_ms': 0, 'alive_ms': 0,
        'deaths': 0, 'first_deaths': [], 'killed_by': {}, 'deaths_without_defensive': 0,
        'avoidable': {}, 'avoidable_hits': 0, 'interrupts': 0, 'dispels': 0,
        'potion_pulls': 0, 'defensives': 0, 'per_pull': [],
        'ready_pulls': 0, 'flask_pulls': 0, 'food_pulls': 0, 'augment_pulls': 0, 'last_prepull': None,
        'missing_enchants': []}


def player_report(pulls, tags):
    """
    Per-player score (0-100), sub-scores and plain-language feedback over the
    given pulls of one boss. pulls: [{'number', 'kill', 'analysis' (with _duration)}].
    Sorted best score first.
    """
    rows, mechanics_seen = {}, {}
    for pull in pulls:
        analysis = pull['analysis']
        duration = analysis.get('_duration') or 0
        roster = {p['name']: p for p in analysis.get('players') or []}
        deaths = annotate_deaths(analysis)['deaths']
        first_name = deaths[0]['name'] if deaths and deaths[0]['early'] else None
        end = analysis.get('wipe_at') or duration
        any_death, died = {}, {}  # any death (for time alive) / early deaths by mistake (for blame)
        for d in deaths:
            any_death.setdefault(d['name'], d)
            if d['early']:
                died.setdefault(d['name'], d)

        avoidable = {}
        for ability in analysis.get('abilities') or []:
            tag = tags.get(ability['id'])
            if tag not in AVOIDABLE_TAGS:
                continue
            mechanics_seen.setdefault(ability['id'], {'name': ability['name'], 'icon': ability.get('icon'), 'tag': tag})
            for name, n in mistake_counts(ability).items():
                if n and not (tag == TAG_AVOIDABLE_NON_TANK and roster.get(name, {}).get('role') == 'tank'):
                    avoidable.setdefault(name, {})[ability['id']] = (ability['name'], ability.get('icon'), n)

        for name, player in roster.items():
            r = rows.setdefault(name, _new_player_row(player))
            count_spec(r, player)
            r['pulls'] += 1
            r['pull_ms'] += duration
            death, fell = died.get(name), any_death.get(name)
            r['alive_ms'] += min(fell['t'], end) if fell else end
            used_defensive = (analysis.get('defensives') or {}).get(name, 0)
            potted = (analysis.get('potions') or {}).get(name, 0) > 0
            hits = sum(n for _, _, n in avoidable.get(name, {}).values())
            if death:
                r['deaths'] += 1
                r['killed_by'][death['ability']] = r['killed_by'].get(death['ability'], 0) + 1
                if not used_defensive:
                    r['deaths_without_defensive'] += 1
                if first_name == name:
                    r['first_deaths'].append(death['ability'])
            for ability_id, (ability_name, icon, n) in avoidable.get(name, {}).items():
                entry = r['avoidable'].setdefault(ability_id, {'id': ability_id, 'name': ability_name,
                                                               'icon': icon, 'hits': 0})
                entry['hits'] += n
            r['avoidable_hits'] += hits
            r['potion_pulls'] += 1 if potted else 0
            prepull = (analysis.get('prepull') or {}).get(name)
            if prepull:
                r['ready_pulls'] += 1
                r['flask_pulls'] += 1 if prepull.get('flask') else 0
                r['food_pulls'] += 1 if prepull.get('food') else 0
                r['augment_pulls'] += 1 if prepull.get('augment') else 0
                r['last_prepull'] = prepull
            r['defensives'] += used_defensive
            r['per_pull'].append({'number': pull['number'], 'kill': pull.get('kill'), 'duration': duration,
                                  'died_at': fell['t'] if fell else None,
                                  'died_to': fell['ability'] if fell else None,
                                  'death_note': death_note(fell) if fell else None,
                                  'mistake': bool(death),
                                  'first': first_name == name, 'avoidable_hits': hits,
                                  'potion': potted, 'defensive': used_defensive})
        for key in ('interrupts', 'dispels'):
            for entry in analysis.get(key) or []:
                for name, n in entry['by'].items():
                    if name in rows:
                        rows[name][key] += n

    players = list(rows.values())
    if not players:
        return []
    has_tags = any(t in AVOIDABLE_TAGS for t in tags.values())

    def raid_average(key):
        return sum(p[key] / p['pulls'] for p in players) / len(players)

    raid_hits, raid_deaths = raid_average('avoidable_hits'), raid_average('deaths')
    raid_no_defensive = sum(p['deaths_without_defensive'] for p in players) / len(players)
    raid_by_ability = {}
    for p in players:
        for ability_id, a in p['avoidable'].items():
            raid_by_ability[ability_id] = raid_by_ability.get(ability_id, 0) + a['hits']
    interrupt_rank = sorted((p for p in players if p['interrupts']), key=lambda p: -p['interrupts'])
    dispel_rank = sorted((p for p in players if p['dispels']), key=lambda p: -p['dispels'])

    expected = expected_enchant_slots([p['last_prepull'] for p in players if p['last_prepull']])
    for p in players:
        enchants = (p['last_prepull'] or {}).get('enchants') or {}
        p['missing_enchants'] = [GEAR_SLOTS[int(slot)] for slot, done in sorted(enchants.items(), key=lambda kv: int(kv[0]))
                                 if slot in expected and not done]

    for p in players:
        p['components'] = _components(p, players, mechanics_seen, raid_by_ability)
        scored = [c for c in p['components'] if not c['bonus']]
        p['score'] = round(sum(c['value'] * c['weight'] for c in scored) / sum(c['weight'] for c in scored))
        bonus = [c['value'] for c in p['components'] if c['bonus']]
        p['contribution'] = round(sum(bonus) / len(bonus)) if bonus else None
        mechanic_values = [c['value'] for c in scored if c['key'] == 'mechanic']
        p['scores'] = {'survival': next(c['value'] for c in scored if c['key'] == 'survival'),
                       'potions': next(c['value'] for c in scored if c['key'] == 'potions')}
        if mechanic_values:
            p['scores']['mechanics'] = sum(mechanic_values) / len(mechanic_values)
        p['feedback'] = _feedback(p, p['pulls'], has_tags, raid_hits, raid_deaths, raid_no_defensive,
                                  raid_by_ability, len(players), interrupt_rank, dispel_rank)
    return sorted(players, key=lambda p: -p['score'])


def _components(p, players, mechanics_seen, raid_by_ability):
    """Every 0-100 value behind a player's score, with the raw numbers that produced it."""
    n = p['pulls']
    out = []

    def add(key, label, value, detail, bonus=False, ability=None):
        out.append({'key': key, 'label': label, 'value': round(value, 1), 'detail': detail, 'bonus': bonus,
                    'ability': ability, 'weight': COMPONENT_WEIGHTS.get(key, 1.0)})

    survival = 100.0 * p['alive_ms'] / p['pull_ms'] if p['pull_ms'] else 100.0
    add('survival', 'Survival', survival, f'Alive {survival:.0f}% of the time until half the raid was dead')

    death_rates = [q['deaths'] / q['pulls'] for q in players]
    add('deaths', 'Deaths', _rank_lower_better(p['deaths'] / n, death_rates),
        f"{p['deaths']} early death{'s' if p['deaths'] != 1 else ''} by mistake in {n} pull{'s' if n != 1 else ''} "
        f"(raid average {sum(death_rates) / len(death_rates) * n:.1f})")

    for ability_id, m in mechanics_seen.items():
        if not raid_by_ability.get(ability_id):
            continue  # nobody got hit - nothing to compare
        eligible = [q for q in players if not (m['tag'] == TAG_AVOIDABLE_NON_TANK and q['role'] == 'tank')]
        if p not in eligible:
            continue
        rates = [q['avoidable'].get(ability_id, {}).get('hits', 0) / q['pulls'] for q in eligible]
        hits = p['avoidable'].get(ability_id, {}).get('hits', 0)
        hit_share = sum(1 for r in rates if r > 0) / len(rates)
        raid_avg = sum(rates) / len(rates) * n  # what an average raider would have taken over these pulls
        add('mechanic', m['name'], _rank_lower_better(hits / n, rates),
            f"Hit {hits}× (raid average {raid_avg:.1f}; {hit_share:.0%} of the raid got hit)",
            ability={'id': ability_id, 'name': m['name'], 'icon': m['icon'], 'hit_share': hit_share,
                     'raid_avg': raid_avg})

    add('potions', 'Potions', 100.0 * p['potion_pulls'] / n, f"Combat potion in {p['potion_pulls']} of {n} pulls")

    defensive_rates = [q['defensives'] / q['pulls'] for q in players]
    if any(defensive_rates):
        add('defensives', 'Healthstones / healing potions', _rank_higher_better(p['defensives'] / n, defensive_rates),
            f"Used {p['defensives']} (raid average {sum(defensive_rates) / len(defensive_rates) * n:.1f})")

    for key, label in (('interrupts', 'Interrupts'), ('dispels', 'Dispels')):
        rates = [q[key] / q['pulls'] for q in players]
        if any(rates):
            add(key, label, _rank_higher_better(p[key] / n, rates),
                f"{p[key]} (raid average {sum(rates) / len(rates) * n:.1f})", bonus=True)

    order = {'survival': 0, 'deaths': 1, 'mechanic': 2, 'potions': 3, 'defensives': 4, 'interrupts': 5, 'dispels': 6}
    return sorted(out, key=lambda c: (order[c['key']], c['value'] if c['key'] == 'mechanic' else 0))


def _feedback(p, n, has_tags, raid_hits, raid_deaths, raid_no_defensive, raid_by_ability, raid_size,
              interrupt_rank, dispel_rank):
    """Plain-language notes for one player, problems first (most serious on top)."""
    notes = []
    # Same per-player raid averages as the score breakdown, so the numbers always agree.
    breakdown_avg = {c['ability']['id']: c['ability']['raid_avg']
                     for c in p.get('components') or [] if c['key'] == 'mechanic'}

    def add(tone, text, weight, ability=None):
        notes.append({'tone': tone, 'text': text, 'weight': weight, 'ability': ability})

    # Mechanics this player gets hit by far more than the rest of the raid
    for ability_id, a in sorted(p['avoidable'].items(), key=lambda kv: -kv[1]['hits']):
        raid_avg = breakdown_avg.get(ability_id, raid_by_ability[ability_id] / raid_size)
        if a['hits'] >= 3 and a['hits'] >= 2 * raid_avg:
            add('bad', f"Hit by {a['name']} {a['hits']} times — {a['hits'] / raid_avg:.1f}× the raid average",
                10 + a['hits'] / max(raid_avg, 0.1), a)
    if has_tags and not p['avoidable_hits'] and raid_hits >= 0.5:
        add('good', 'Never hit by an avoidable mechanic', 6)
    else:
        # Mechanics this player handled cleanly while most of the raid didn't.
        clean = [c for c in p.get('components') or [] if c['key'] == 'mechanic' and c['value'] == 100
                 and c['ability']['hit_share'] >= 0.5]
        for c in sorted(clean, key=lambda c: -c['ability']['hit_share'])[:2]:
            add('good', f"Clean on {c['label']} while {c['ability']['hit_share']:.0%} of the raid got hit",
                4 + c['ability']['hit_share'], c['ability'])
    # A low Mechanics score should always come with the reason, even on small samples.
    if p['avoidable'] and p['scores'].get('mechanics', 100) < 60 \
            and not any(n['ability'] and n['tone'] == 'bad' for n in notes):
        a = max(p['avoidable'].values(), key=lambda a: a['hits'])
        raid_avg = breakdown_avg.get(a['id'], raid_by_ability[a['id']] / raid_size)
        add('bad', f"Hit by {a['name']} {a['hits']} time{'s' if a['hits'] != 1 else ''} "
                   f"(raid average {raid_avg:.1f})", 8, a)

    # Deaths
    if len(p['first_deaths']) >= 2:
        common = max(set(p['first_deaths']), key=p['first_deaths'].count)
        add('bad', f"First to die {len(p['first_deaths'])} times (most often to {common})",
            12 + len(p['first_deaths']))
    if n >= 3 and p['deaths'] >= 3 and p['deaths'] / n >= 1.5 * raid_deaths:
        add('bad', f"Early death by mistake in {p['deaths']} of {n} pulls "
                   f"(raid average {raid_deaths * n:.1f})", 9 + p['deaths'] / n)
    # Many deaths are one-shots a healthstone can't fix - only call out clearly-above-raid habits.
    if p['deaths_without_defensive'] >= 3 and p['deaths_without_defensive'] >= 1.5 * raid_no_defensive:
        add('bad', f"Died {p['deaths_without_defensive']} times without using a healthstone or "
                   f"healing potion first (raid average {raid_no_defensive:.1f})", 7)
    if p['killed_by'] and p['deaths'] >= 3:
        top, count = max(p['killed_by'].items(), key=lambda kv: kv[1])
        if count >= 3:
            add('info', f"Most often killed by {top} ({count} of {p['deaths']} deaths)", 3)
    if p['scores']['survival'] >= 97 and not p['deaths'] and n >= 2:
        add('good', 'No early deaths by mistake', 5)

    # Consumables
    if n >= 3 and p['potion_pulls'] / n < 0.5:
        add('bad', f"Used a combat potion in only {p['potion_pulls']} of {n} pulls", 5)
    elif n >= 3 and p['potion_pulls'] == n:
        add('good', 'Potted every pull', 2)

    # Ready check (flask / food at the pull, enchants)
    ready = p.get('ready_pulls') or 0
    if ready >= 2:
        for key, label in (('flask_pulls', 'flask'), ('food_pulls', 'food buff')):
            if p[key] / ready < 0.75:
                add('bad', f"No {label} in {ready - p[key]} of {ready} pulls", 6)
    elif ready == 1:
        missing = [label for key, label in (('flask_pulls', 'flask'), ('food_pulls', 'food buff')) if not p[key]]
        if missing:
            add('bad', f"Pulled without {' or '.join(missing)}", 6)
    if p.get('missing_enchants'):
        add('bad', f"Missing enchants: {', '.join(p['missing_enchants'])}", 5)

    # Contributions
    if interrupt_rank and interrupt_rank[0] is p and p['interrupts'] >= 3:
        add('good', f"Most interrupts in the raid ({p['interrupts']})", 6)
    elif p in interrupt_rank[:3] and p['interrupts'] >= 3:
        add('good', f"Top-3 interrupter ({p['interrupts']})", 4)
    if dispel_rank and dispel_rank[0] is p and p['dispels'] >= 5:
        add('good', f"Most dispels in the raid ({p['dispels']})", 5)

    return sorted(notes, key=lambda f: ({'bad': 0, 'good': 1, 'info': 2}[f['tone']], -f['weight']))


# ============================================================================
# Why a pull ended, and how far pulls got (render-time, from stored analyses)
# ============================================================================

BURST_WINDOW_MS = 10000      # deaths this close together count as one burst
TANK_DEATH_LEAD_MS = 45000   # a tank death this long before the end counts as the trigger
ENRAGE_WORDS = ('berserk', 'enrage', 'frenzy')


def _fmt_ms(ms):
    seconds = int(ms / 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _top(deaths):
    counts = {}
    for d in deaths:
        counts[d['ability']] = counts.get(d['ability'], 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def wipe_reason(analysis, kill, duration, enrage_ids=()):
    """
    {'code', 'label', 'detail'} explaining how a wipe ended, or None for kills.

    When most of the raid dies together, what happened *before* that burst
    decides the story: after a tank death, lost healers or a pile of early
    deaths the burst is the consequence (raid collapsed or the wipe was
    called); with a healthy raid it's a failed raid-wide mechanic (or enrage),
    and a mixed-ability burst out of nowhere is most likely a called wipe.
    enrage_ids: ability IDs known to be enrage timers (e.g. from the Mythic Trap guide).
    """
    if kill:
        return None
    deaths = sorted(analysis.get('deaths') or [], key=lambda d: d['t'])
    counted = [d for d in deaths if not d.get('after_wipe')]
    roles = {p['name']: p.get('role') for p in analysis.get('players') or []}
    raid = max(1, len(roles))

    if duration < 30000 and len(counted) <= 2:
        return {'code': 'reset', 'label': 'Early reset', 'detail': f'Pull ended after {_fmt_ms(duration)}'}

    burst = []
    if deaths:
        last = deaths[-1]['t']
        burst = [d for d in deaths if d['t'] >= last - BURST_WINDOW_MS]
        if len(burst) < max(4, 0.35 * raid):
            burst = []
    end = burst[0]['t'] if burst else duration
    before = [d for d in deaths if d['t'] < end]

    # What went wrong before the end (if anything)
    tank = next((d for d in before if roles.get(d['name']) == 'tank' and end - d['t'] <= TANK_DEATH_LEAD_MS), None)
    healers = [d for d in before if roles.get(d['name']) == 'healer']
    trigger = None
    if tank:
        trigger = ('tank', f'Tank died ({tank["name"]})',
                   f'{tank["name"]} died to {tank["ability"]} at {_fmt_ms(tank["t"])}')
    elif len(healers) >= 2:
        trigger = ('healers', f'Lost {len(healers)} healers',
                   ', '.join(f'{d["name"]} ({d["ability"]}, {_fmt_ms(d["t"])})' for d in healers[:3]))
    elif len(before) >= 0.3 * raid:
        top = ', '.join(f'{a} ×{n}' for a, n in _top(before)[:3])
        trigger = ('attrition', f'{len(before)} early deaths', top)

    if burst:
        ability, n = _top(burst)[0]
        dominant = n / len(burst) >= 0.5
        span = max((burst[-1]['t'] - burst[0]['t']) / 1000, 1)
        burst_text = (f'{n} died to {ability} within {span:.0f}s' if dominant
                      else f'{len(burst)} died within {span:.0f}s')
        if trigger:
            code, label, detail = trigger
            then = ability if dominant else 'wipe'
            return {'code': code, 'label': f'{label} → {then}',
                    'detail': f'{detail}; then {burst_text} at {_fmt_ms(burst[0]["t"])}'}
        if dominant:
            ability_id = next(d.get('ability_id') for d in burst if d['ability'] == ability)
            if ability_id in enrage_ids or any(w in ability.lower() for w in ENRAGE_WORDS):
                return {'code': 'enrage', 'label': 'Enrage', 'detail': f'{burst_text} at {_fmt_ms(burst[0]["t"])}'}
            return {'code': 'mass', 'label': f'{ability} wiped the raid',
                    'detail': f'Failed mechanic: {burst_text} at {_fmt_ms(burst[0]["t"])}, '
                              f'with {len(before)} death{"s" if len(before) != 1 else ""} before'}
        return {'code': 'called', 'label': 'Wipe called (raid died together)',
                'detail': f'{burst_text} at {_fmt_ms(burst[0]["t"])} from different abilities, '
                          f'with {len(before)} death{"s" if len(before) != 1 else ""} before'}

    # No big final burst: the trigger, a mechanic chain, a reset, or slow attrition.
    if trigger and trigger[0] in ('tank', 'healers'):
        return {'code': trigger[0], 'label': trigger[1], 'detail': trigger[2]}
    for i, d in enumerate(counted):
        chain = [x for x in counted[i:] if x['ability'] == d['ability'] and x['t'] - d['t'] <= BURST_WINDOW_MS]
        if len(chain) >= 3:
            return {'code': 'chain', 'label': f'{d["ability"]} chain',
                    'detail': f'{len(chain)} deaths to {d["ability"]} within '
                              f'{(chain[-1]["t"] - d["t"]) / 1000:.0f}s at {_fmt_ms(d["t"])}'}
    if analysis.get('wipe_at') is None:
        first = counted[0] if counted else None
        detail = (f'First death: {first["name"]} to {first["ability"]} at {_fmt_ms(first["t"])}'
                  if first else 'No deaths before the reset')
        return {'code': 'reset_called', 'label': 'Reset called', 'detail': detail}
    top = ', '.join(f'{a} ×{n}' for a, n in _top(counted)[:3])
    span = (counted[-1]['t'] - counted[0]['t']) / 1000 if counted else 0
    return {'code': 'attrition', 'label': 'Attrition', 'detail': f'{len(counted)} deaths over {span:.0f}s — {top}'}


def phase_progress(pulls, phase_names):
    """
    How far pulls got: [{'id', 'name', 'intermission', 'reached', 'avg_entry', 'best_entry', 'avg_time'}]
    in phase order. pulls: [{'phases': [{'id', 'start'}], 'duration'}]; phase_names: {id: {name, intermission}}.
    """
    stats = {}
    for pull in pulls:
        phases = pull.get('phases') or []
        # Council-style fights revisit phases within a pull: count each phase once per pull,
        # entered at its first visit, with all visits' time added up.
        first_entry, time_in = {}, {}
        for i, phase in enumerate(phases):
            end = phases[i + 1]['start'] if i + 1 < len(phases) else pull['duration']
            first_entry.setdefault(phase['id'], phase['start'])
            time_in[phase['id']] = time_in.get(phase['id'], 0) + max(0, end - phase['start'])
        for phase_id, entry in first_entry.items():
            s = stats.setdefault(phase_id, {'reached': 0, 'entries': [], 'times': []})
            s['reached'] += 1
            s['entries'].append(entry)
            s['times'].append(time_in[phase_id])
    out = []
    for phase_id in sorted(stats):
        s = stats[phase_id]
        info = (phase_names or {}).get(str(phase_id)) or {}
        out.append({'id': phase_id, 'name': info.get('name') or f'Phase {phase_id}',
                    'intermission': bool(info.get('intermission')), 'reached': s['reached'],
                    'avg_entry': sum(s['entries']) / len(s['entries']), 'best_entry': min(s['entries']),
                    'avg_time': sum(s['times']) / len(s['times'])})
    return out
