"""
Raid attendance from the logs: who signed up for an event vs. who was actually
in its analyzed Warcraft Logs report.

Signups marked absent or benched never count against anyone. A player counts
as present when the character they signed with, or any of their linked
Battle.net characters, appears in the report's raid pulls.
"""
import re

from .db import _run

EXPECTED_STATUSES = ('signed', 'late', 'tentative')
_REPORT_CODE_RE = re.compile(r'reports/([A-Za-z0-9]{16})')


def _report_code(log_url):
    match = _REPORT_CODE_RE.search(log_url or '')
    return match.group(1) if match else None


def report_roster(code):
    """{lower-cased name: name as logged} for everyone in the report's analyzed raid pulls."""
    rows = _run("""
        SELECT DISTINCT pl->>'name' AS name
        FROM raid_pulls p, jsonb_array_elements(p.analysis->'players') pl
        WHERE p.report_code = %s
    """, (code,), fetch='all')
    return {r['name'].lower(): r['name'] for r in rows}


def _linked_characters(discord_ids):
    if not discord_ids:
        return {}
    rows = _run("SELECT discord_id, LOWER(character_name) AS name FROM wow_characters WHERE discord_id = ANY(%s)",
                (list(discord_ids),), fetch='all')
    out = {}
    for r in rows:
        out.setdefault(r['discord_id'], set()).add(r['name'])
    return out


def event_attendance(events):
    """
    {event_id: {'expected', 'present': [...], 'no_shows': [...], 'unsigned': [...]}} for every
    event (dict with id, log_url) whose log has been analyzed. Names are display names / characters.
    """
    by_event = {e['id']: _report_code(e.get('log_url')) for e in events}
    by_event = {eid: code for eid, code in by_event.items() if code}
    if not by_event:
        return {}
    signups = _run("""
        SELECT rs.event_id, rs.discord_id, rs.character_name, rs.status,
               COALESCE(wc.discord_display_name, wc.discord_username, rs.character_name) AS display_name
        FROM raid_signups rs
        LEFT JOIN wow_connections wc ON wc.discord_id = rs.discord_id
        WHERE rs.event_id = ANY(%s)
    """, (list(by_event),), fetch='all')
    linked = _linked_characters({s['discord_id'] for s in signups})

    out = {}
    for event_id, code in by_event.items():
        roster = report_roster(code)
        if not roster:
            continue  # log not analyzed yet
        event_signups = [s for s in signups if s['event_id'] == event_id]
        claimed = set()
        present, no_shows, expected = [], [], 0
        for s in event_signups:
            characters = {s['character_name'].lower()} | linked.get(s['discord_id'], set())
            in_log = characters & roster.keys()
            claimed |= in_log
            if s['status'] not in EXPECTED_STATUSES:
                continue
            expected += 1
            (present if in_log else no_shows).append(s['display_name'])
        unsigned = sorted(roster[name] for name in roster.keys() - claimed)
        out[event_id] = {'expected': expected, 'present': sorted(present), 'no_shows': sorted(no_shows),
                         'unsigned': unsigned}
    return out


def user_attendance(discord_id):
    """Per-player summary over events with analyzed logs: {'tracked', 'present', 'no_shows': [event titles]}."""
    signups = _run("""
        SELECT re.id, re.title, re.event_date, re.log_url, rs.character_name, rs.status
        FROM raid_signups rs JOIN raid_events re ON re.id = rs.event_id
        WHERE rs.discord_id = %s AND re.log_url IS NOT NULL AND rs.status = ANY(%s)
        ORDER BY re.event_date DESC
    """, (discord_id, list(EXPECTED_STATUSES)), fetch='all')
    characters = _linked_characters({discord_id}).get(discord_id, set())
    tracked, present, no_shows = 0, 0, []
    for s in signups:
        code = _report_code(s['log_url'])
        roster = report_roster(code) if code else {}
        if not roster:
            continue
        tracked += 1
        if ({s['character_name'].lower()} | characters) & roster.keys():
            present += 1
        else:
            no_shows.append({'title': s['title'], 'date': s['event_date'].isoformat() if s['event_date'] else None})
    return {'tracked': tracked, 'present': present, 'no_shows': no_shows}
