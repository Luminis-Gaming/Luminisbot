"""
The Analytics page (event managers): who uses the raid analysis - "My performance" clicks, Full analysis clicks,
unique visitors, per team and per raid night, and the Discord users we know. Data: analytics.summary().
"""
from .. import teams
from ..analytics import NO_EVENT, NOT_A_NIGHT
from .render import esc, section_head, stat_tiles, ts

PERIODS = (('7', 'Last 7 days'), ('30', 'Last 30 days'), ('90', 'Last 90 days'), ('all', 'Everything'))
GROUP_LABELS = {teams.OTHER: 'For-fun raids', NO_EVENT: 'Nights without an event',
                NOT_A_NIGHT: 'Other pages (front page, bosses, characters)'}


def period_key(value):
    """?days= -> (key, days or None for everything); 30 days unless asked."""
    if value == 'all':
        return 'all', None
    return (value, int(value)) if value in ('7', '30', '90') else ('30', 30)


def _n(value):
    return f'{value or 0:,}'.replace(',', ' ')


def _daily_chart(daily):
    """Unique visitors a day: thin bars, one hue, a tooltip each. Days without a view are gaps on the axis."""
    if not daily:
        return '<p class="muted">No page views in this period yet.</p>'
    from datetime import timedelta
    first, last = daily[0]['day'], daily[-1]['day']
    by_day = {d['day']: d for d in daily}
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    top = max(d['visitors'] for d in daily) or 1
    bars = []
    for day in days:
        d = by_day.get(day) or {'visitors': 0, 'views': 0}
        tip = f"{day:%a %d %b}: {d['visitors']} unique visitor{'s' if d['visitors'] != 1 else ''} · {d['views']} views"
        bars.append(f'<div class="an-day has-tip" data-tip="{esc(tip)}" title="{esc(tip)}">'
                    + (f'<i style="height:{100 * d["visitors"] / top:.1f}%"></i>' if d['visitors'] else '') + '</div>')
    # a date under ~every sixth of the period (each under its own day), the first and last always
    every = max(1, round(len(days) / 6))
    marks = sorted({0, len(days) - 1} | set(range(0, len(days) - every // 2, every)))
    axis = ''.join(f'<span style="left:{100 * (i + 0.5) / len(days):.2f}%">{days[i]:%d %b}</span>' for i in marks)
    return (f'<div class="an-chart" role="img" aria-label="Unique visitors per day, at most {top}">'
            f'<span class="an-top">{top}</span>{"".join(bars)}</div>'
            f'<div class="an-axis"><div>{axis}</div></div>')


def _counts_cells(row):
    users = row.get('my_performance_users') or 0
    who = f' <span class="small muted">({users} {"person" if users == 1 else "people"})</span>' if users else ''
    return (f'<td class="num">{_n(row["visitors"])}</td><td class="num">{_n(row["views"])}</td>'
            f'<td class="num">{_n(row["my_performance"])}{who}</td><td class="num">{_n(row["full_analysis"])}</td>')


COUNT_HEADS = ('<th class="num" title="Different browsers that opened a page">Unique visitors</th>'
               '<th class="num">Page views</th><th class="num">My performance</th>'
               '<th class="num" title="Pages opened from a Full analysis link in Discord">Full analysis</th>')


def _team_label(key):
    if key in GROUP_LABELS:
        return GROUP_LABELS[key]
    return teams.label(key) if key else 'Unknown team'


def _teams_table(groups):
    order = [k for k, _ in teams.options()] + [teams.OTHER, NO_EVENT, NOT_A_NIGHT]
    rows = ''.join(f'<tr><td><strong>{esc(_team_label(key))}</strong></td>{_counts_cells(row)}</tr>'
                   for key, row in sorted(groups, key=lambda g: order.index(g[0]) if g[0] in order else len(order)))
    return (f'<div class="table-wrapper"><table class="compact"><tr><th>Pages</th>{COUNT_HEADS}</tr>'
            f'{rows or "<tr><td colspan=5 class=muted>Nothing yet.</td></tr>"}</table></div>')


def _team_pill(team):
    if team is None:
        return ''
    if team == teams.OTHER:
        return '<span class="pill pill-wipe">for fun</span>'
    return f'<span class="pill">{esc(teams.label(team))}</span>'


def _nights_table(nights):
    rows = []
    for n in nights:
        title = esc(n['title'] or n['report_code'])
        event = f'<br><span class="small muted">📅 {esc(n["event_title"])}</span>' if n['event_title'] else ''
        rows.append(f'<tr><td>{ts(n["start_time"], "date") if n["start_time"] else ""}</td>'
                    f'<td><a href="/admin/raids/report/{esc(n["report_code"])}" style="color:#fff"><strong>{title}</strong>'
                    f'</a> {_team_pill(n["team"])}{event}</td>{_counts_cells(n)}</tr>')
    return (f'<div class="table-wrapper"><table class="compact"><tr><th>Date</th><th>Raid night</th>{COUNT_HEADS}</tr>'
            f'{"".join(rows) or "<tr><td colspan=6 class=muted>Nothing yet.</td></tr>"}</table></div>')


def _last_seen(at):
    return ts(int(at.timestamp() * 1000)) if at else ''


LINKED = ('<span class="good-text" title="Opened a link from their own My performance reply: that browser\'s views '
          'count as theirs">✔ linked</span>')
NOT_LINKED = ('<span class="muted" title="Hasn\'t opened a link from their My performance reply yet - their page views '
              'are counted, just not as theirs">not yet</span>')


def _users_table(users):
    rows = ''.join(
        f'<tr><td><strong>{esc(u["name"] or "Unknown")}</strong> <span class="small muted">{u["discord_id"]}</span></td>'
        f'<td class="num">{_n(u["my_performance"])}</td><td>{LINKED if u["linked"] else NOT_LINKED}</td>'
        f'<td class="num">{_n(u["full_analysis"])}</td>'
        f'<td class="num">{_n(u["own_analysis"])}</td><td class="num">{_n(u["views"])}</td>'
        f'<td class="num">{_n(u["nights"])}</td><td class="small muted">{_last_seen(u["last_seen"])}</td></tr>'
        for u in users)
    return (f'<div class="table-wrapper"><table class="compact"><tr><th>Discord user</th>'
            f'<th class="num">My performance</th><th>Browser</th><th class="num">Full analysis</th>'
            f'<th class="num" title="Opened their own analysis from the My performance reply">Own analysis</th>'
            f'<th class="num">Page views</th><th class="num">Nights viewed</th><th>Last seen</th></tr>'
            f'{rows or "<tr><td colspan=8 class=muted>Nobody yet - names show up once someone presses My performance.</td></tr>"}'
            f'</table></div>')


def _officers_table(officers):
    rows = ''.join(f'<tr><td><strong>{esc(o["admin_user"])}</strong></td><td class="num">{_n(o["views"])}</td>'
                   f'<td class="num">{_n(o["nights"])}</td><td class="small muted">{_last_seen(o["last_seen"])}</td></tr>'
                   for o in officers)
    return (f'<div class="table-wrapper"><table class="compact"><tr><th>Admin login</th><th class="num">Page views</th>'
            f'<th class="num">Nights viewed</th><th>Last seen</th></tr>'
            f'{rows or "<tr><td colspan=4 class=muted>No officer views yet.</td></tr>"}</table></div>')


USERS_SUB = ('Discord only tells the bot who presses <strong>My performance</strong>. Everything else - Full analysis '
             'clicks, page views - gets a name once that person has opened one of the links in their own My '
             'performance reply in their browser: from then on, and back in time, that browser\'s views are theirs. '
             '"not yet" with zeros means they read the reply in Discord without opening its links (or browse '
             'elsewhere).')
OFFICERS_SUB = ('Views while logged in to the admin site - by admin login, which isn\'t tied to a Discord user. Open a '
                'link from your own My performance reply in the same browser and these count under your Discord name '
                'too.')


def page(data, key):
    t = data['totals'] or {}
    chips = ''.join(f'<a class="pull-chip{" active" if k == key else ""}" data-swap="page" '
                    f'href="/admin/raids/analytics?days={k}">{label}</a>' for k, label in PERIODS)
    tiles = stat_tiles([
        (_n(t.get('visitors')), 'Unique visitors'),
        (_n(t.get('views')), 'Page views'),
        (_n(t.get('my_performance')), f'My performance clicks · {_n(t.get("my_performance_users"))} '
                                      f'{"person" if t.get("my_performance_users") == 1 else "people"}'),
        (_n(t.get('full_analysis')), 'Full analysis clicks'),
        (_n(t.get('discord_users')), 'Discord users we know'),
    ])
    return f"""
    <div class="card">
        <p><a href="/admin/raids">← Raid Analysis</a></p>
        <h1>📈 Analytics</h1>
        <p class="muted">Who uses the raid analysis. A visitor is a browser (an anonymous id in a cookie - no IP, no
           login); <strong>My performance</strong> clicks are known by Discord user. Discord doesn't say who clicks a
           link button, so <strong>Full analysis</strong> clicks and page views get a name only once that browser has
           opened a link from its owner's own My performance reply - from then on (and back in time) they count as
           theirs. Officers' views here count too.</p>
        <div class="pull-chips">{chips}</div>
    </div>
    <div class="card">{tiles}{section_head('👀', 'Unique visitors per day')}{_daily_chart(data['daily'])}</div>
    <div class="card">{section_head('🌗', 'By team', 'Raid nights are split by the event they were linked to: its signup channel says the team. A visitor who looked at both teams counts once in each.')}
        {_teams_table(data['teams'])}</div>
    <div class="card">{section_head('📅', 'By raid night')}{_nights_table(data['nights'])}</div>
    <div class="card">{section_head('👥', 'Discord users', USERS_SUB)}{_users_table(data['users'])}</div>
    <div class="card">{section_head('🛡️', 'Officers', OFFICERS_SUB)}
        {_officers_table(data.get('officers') or [])}</div>"""
