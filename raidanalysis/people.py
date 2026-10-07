"""
Who plays which character.

Two sources: raid signups (a Discord user signing up with a character) and
linked Battle.net characters (wow_characters). Signups win - people who share
one Battle.net account still sign up with their own Discord account on their
own characters - and the Battle.net link only decides characters nobody has
signed up with. Pure functions; db.character_owners() feeds them.
"""


def resolve_owners(signups, linked, displays=None):
    """
    {lower-case character: {'key', 'discord_id', 'display'}}.

    signups: [(character, discord_id, times_signed)]; linked: [(character, discord_id)];
    displays: {discord_id: display name}.

    A Discord user whose linked characters include one somebody else signs up with shares a Battle.net account
    (Gastronomic's links Naautilus' characters too): of their linked characters, only the ones they sign up with
    themselves are known to be theirs - the rest (an alt nobody has signed up with yet, which could be either's)
    each stand alone ({'key': 'c<name>', 'discord_id': None}) until someone signs up with it.
    """
    displays = displays or {}
    best = {}
    for character, discord_id, times in signups:
        name = character.lower()
        if name not in best or times > best[name][1]:
            best[name] = (discord_id, times)
    owners = {name: discord_id for name, (discord_id, _) in best.items()}
    shared = {discord_id for character, discord_id in linked
              if character.lower() in owners and owners[character.lower()] != discord_id}
    unsure = set()
    for character, discord_id in linked:
        name = character.lower()
        if name in owners:
            continue
        if discord_id in shared:
            unsure.add(name)
        else:
            owners[name] = discord_id
    out = {name: {'key': f'd{discord_id}', 'discord_id': discord_id, 'display': displays.get(discord_id)}
           for name, discord_id in owners.items()}
    out.update({name: {'key': f'c{name}', 'discord_id': None, 'display': None} for name in unsure - set(owners)})
    return out


def own_characters(discord_id, linked_names, owners, signed_with=()):
    """
    The characters that really belong to this Discord user: linked characters that nobody else
    owns (a shared Battle.net account links the other person's characters too), plus whatever
    they signed up with.
    """
    discord_id = str(discord_id)
    mine = {c.lower() for c in signed_with}
    for name in linked_names:
        owner = owners.get(name.lower())
        if owner is None or str(owner['discord_id']) == discord_id:
            mine.add(name.lower())
    return mine
