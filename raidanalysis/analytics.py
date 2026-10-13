"""
Who uses the raid analysis - for officers (the event managers' Analytics page, web/analyticsview.py).

Two things are recorded (raid_analytics):
- "📊 My performance" clicks in Discord: the bot knows who clicked, and which night.
- Page views on the raid pages, sent by the page itself (PAGE_JS: on load and on every in-page swap - not hover
  prefetches, not the bots that don't run scripts) with an anonymous browser id kept in a cookie. No IP, no login.

Discord's link buttons ("Full analysis") never tell the bot who clicked. So the links carry where they came from
(?src=full / ?src=mine), and the ones in someone's private recap also carry their Discord id, signed (?u=): the first
time a browser opens one, that browser's id is tied to that Discord user (raid_visitors), and all its views - earlier
ones too - count as theirs. The page drops both from the address once recorded, so a copied link doesn't carry them.
"""
import hashlib
import hmac
import logging
import os
import re

from . import db, teams

logger = logging.getLogger(__name__)

VIEW, MY_PERFORMANCE = 'view', 'my_performance'
SOURCES = {'full', 'mine'}   # a view's way in: a Full analysis link, the recap's link to your own analysis
KEEP_DAYS = 400
REPORT_RE = re.compile(r'^/(?:admin/)?raids/report/([A-Za-z0-9]{16})(?:/|$)')
MAX_PATH = 300


def _key():
    secret = os.getenv('OAUTH_STATE_SECRET') or os.getenv('DISCORD_BOT_TOKEN') or ''
    return hashlib.sha256(b'raid-analytics:' + secret.encode()).digest() if secret else None


def sign(discord_id):
    """A link token for someone's own recap links - '<id>.<signature>', or None without a secret to sign with."""
    key = _key()
    if not key or not discord_id:
        return None
    mac = hmac.new(key, str(int(discord_id)).encode(), hashlib.sha256).hexdigest()[:20]
    return f'{int(discord_id)}.{mac}'


def verify(token):
    """The Discord id a token was signed for, or None."""
    key = _key()
    if not key or not token or '.' not in token:
        return None
    raw, mac = token.split('.', 1)
    if not raw.isdigit():
        return None
    good = hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()[:20]
    return int(raw) if hmac.compare_digest(good, mac) else None


def report_of(path):
    match = REPORT_RE.match(path or '')
    return match.group(1) if match else None


def record_click(discord_id, discord_name, code):
    """Someone pressed "My performance" on a night's post. Never fails the button."""
    try:
        db.record_analytics(MY_PERFORMANCE, discord_id=discord_id, discord_name=(discord_name or '')[:100] or None,
                            report_code=code)
    except Exception:
        logger.warning('[RAIDS] My performance click not recorded', exc_info=True)


def record_view(visitor, path, src=None, token=None, admin_user=None):
    """A page view (web: POST .../raids/hit). path: the page's own path; src / token: from its address."""
    path = (path or '')[:MAX_PATH]
    if not visitor or not re.match(r'^/(admin/)?raids(/|$)', path):
        return
    discord_id = verify(token)
    if discord_id:
        db.link_visitor(visitor, discord_id)
    db.record_analytics(VIEW, src=src if src in SOURCES else None, visitor=visitor, discord_id=discord_id,
                        admin_user=admin_user, report_code=report_of(path),
                        path=path[len('/admin'):] if path.startswith('/admin/') else path)


# ============================================================================
# The page's numbers
# ============================================================================

NO_EVENT, NOT_A_NIGHT = 'no_event', 'not_a_night'


def summary(days=None):
    """
    {'totals', 'daily', 'teams', 'nights', 'users'} over the last `days` days (None: everything kept) - see
    db.analytics_*. nights carry 'team' (teams.of_channel: a team key, OTHER, None without an event); teams:
    [(key - a team key, OTHER, NO_EVENT or NOT_A_NIGHT, row)] - unique visitors are counted per group, not summed.
    """
    nights = db.analytics_nights(days)
    for n in nights:
        n['team'] = teams.of_channel(n['event_channel_id'])
    channels = {cfg['channel_id']: key for key, cfg in teams._teams().items()}
    groups = []
    for row in db.analytics_by_channel(days, list(channels)):
        key = {'other': teams.OTHER, 'no_event': NO_EVENT, 'not_a_night': NOT_A_NIGHT}.get(row['bucket'])
        groups.append((key or channels.get(row['channel_id']), row))
    return {'totals': db.analytics_totals(days), 'daily': db.analytics_daily(days), 'teams': groups,
            'nights': nights, 'users': db.analytics_users(days)}
