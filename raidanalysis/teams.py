"""
Which raid team a night belongs to: the signup channel of the raid event its log is
attached to (team_roles.TEAMS - #team-sun-signups / #team-moon-signups).

- Events posted in any other channel (e.g. #for-fun-raids) are 'other': they're still
  listed as raid nights, but left out of boss progress and per-boss stats.
- Guild logs that aren't attached to an event can't be placed; they count for
  "All teams" only.
"""

OTHER = 'other'
ICONS = {'sun': '☀️', 'moon': '🌙'}


def _teams():
    from team_roles import TEAMS  # lazy: team_roles pulls in discord.py
    return TEAMS


def options():
    """[(key, label)] for the team filter."""
    return [(key, cfg['name']) for key, cfg in _teams().items()]


def label(key):
    if key == OTHER:
        return 'Not a team raid'
    return f"{ICONS.get(key, '')} {dict(options()).get(key, '')}".strip()


def of_channel(channel_id):
    """Team key for an event's channel, OTHER for any other channel, None without an event."""
    if channel_id is None:
        return None
    for key, cfg in _teams().items():
        if cfg['channel_id'] == int(channel_id):
            return key
    return OTHER


def parse(value):
    """A ?team= query value -> a team key, or None for all teams."""
    return value if value in dict(options()) else None


def sql_filter(team, column='ev.event_channel_id'):
    """
    (' AND ...', params) restricting rows to one team's nights - or, for all teams, to
    everything except events from non-team channels (for-fun raids).
    """
    channels = [cfg['channel_id'] for cfg in _teams().values()]
    if team:
        return f' AND {column} = %s', [_teams()[team]['channel_id']]
    return f' AND ({column} IS NULL OR {column} = ANY(%s))', [channels]
