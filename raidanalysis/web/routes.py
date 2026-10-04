"""
Raid analysis admin pages: raid nights, a night's "all pulls" view, a single
pull, and per-boss progression with mechanic tagging.

Mounted on the oauth server via register_routes(app), which create_app()
calls at startup, so this module can import oauth_server freely (it is fully
loaded by then) and reuse its session auth, CSS and nav.
"""
import asyncio
import logging
import re
from urllib.parse import quote

from aiohttp import web

from .. import analyzer, benchmarks, db, guides, progstats, spells, sync, teams
from . import compare, consumables, insights, players
from .render import (CLIP_MODAL, DIFFICULTY_NAMES, PAGE_CSS, PAGE_JS, ability, boss_portrait, deaths_strip,
                     hit_timeline,
                     difficulty_pill,
                     pull_histogram,
                     phase_funnel,
                     phase_heatmap, esc, fmt_amount, fmt_duration,
                     guide_button, killers_table, phase_label, player_name, progress_chart, pull_timeline,
                     result_pill, scoreboard_table, sync_banner, tag_buttons, tag_pill, ts)

logger = logging.getLogger(__name__)

REPORT_CODE_RE = re.compile(r'(?:reports/)?([A-Za-z0-9]{16})\b')


def register_routes(app):
    app.router.add_get('/admin/raids', handle_overview)
    app.router.add_post('/admin/raids/sync', handle_sync)
    app.router.add_post('/admin/raids/benchmarks', handle_fetch_benchmarks)
    app.router.add_get('/admin/raids/sync/status', handle_sync_status)
    app.router.add_get('/admin/raids/report/{code}', handle_night)
    app.router.add_get('/admin/raids/report/{code}/{fight_id}', handle_pull)
    app.router.add_get('/admin/raids/report/{code}/player/{name}', handle_player)
    app.router.add_get('/admin/raids/report/{code}/compare/{name}', handle_compare)
    app.router.add_get('/admin/raids/boss/{encounter_id}/{difficulty}', handle_boss)
    app.router.add_post('/admin/raids/boss/{encounter_id}/{difficulty}/tag', handle_tag)
    app.router.add_get('/admin/raids/boss/{encounter_id}/{difficulty}/player/{name}', handle_player_trend)

    # Read-only public mirror for raiders (linked from the "Full analysis" button in Discord)
    app.router.add_get('/raids', _public(handle_overview))
    app.router.add_get('/raids/spell/{spell_id}', handle_spell)
    app.router.add_get('/raids/report/{code}', _public(handle_night))
    app.router.add_get('/raids/report/{code}/{fight_id}', _public(handle_pull))
    app.router.add_get('/raids/report/{code}/player/{name}', _public(handle_player))
    app.router.add_get('/raids/report/{code}/compare/{name}', _public(handle_compare))
    app.router.add_get('/raids/boss/{encounter_id}/{difficulty}', _public(handle_boss))
    app.router.add_get('/raids/boss/{encounter_id}/{difficulty}/player/{name}', _public(handle_player_trend))
    app.router.add_post('/admin/raids/boss/{encounter_id}/{difficulty}/guides', handle_rescan_guides)
    logger.info("[RAIDS] Admin web routes registered")


PUBLIC_SESSION = {'username': 'guest', 'role': 'public'}


def _session(request):
    if request.get('public'):
        return PUBLIC_SESSION
    from oauth_server import get_session
    session = get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')
    return session


# ============================================================================
# Public read-only mirror (/raids/...) - same pages, admin controls removed
# ============================================================================

_PUBLIC_STRIP = [
    re.compile(r'<td>\s*<form[^>]*class="tag-form".*?</form>\s*</td>', re.S),   # tag buttons (table cells)
    re.compile(r'<form[^>]*class="tag-form".*?</form>', re.S),
    re.compile(r'<form[^>]*action="[^"]*/(sync|guides|benchmarks)".*?</form>', re.S),  # sync / re-analyze / rescan
    re.compile(r'<th>Tag</th>'),
    re.compile(r'<span class="admin-only">.*?</span>', re.S),                   # officer-only hints
]


def _publicize(html):
    for pattern in _PUBLIC_STRIP:
        html = pattern.sub('', html)
    html = re.sub(r'<a href="/admin/events">(.*?)</a>', r'\1', html)  # admin-only page: keep the text
    return html.replace('/admin/raids', '/raids')


def _public(handler):
    """Serve an admin page handler read-only at /raids/..., without login."""
    async def wrapper(request):
        request['public'] = True
        try:
            return await handler(request)
        except web.HTTPFound as redirect:
            raise web.HTTPFound(redirect.location.replace('/admin/raids', '/raids', 1)) from None
    return wrapper


def public_base_url():
    """Where the public pages live, for links from Discord (RAID_ANALYSIS_PUBLIC_URL, else the OAuth host)."""
    import os
    from urllib.parse import urlsplit
    explicit = os.getenv('RAID_ANALYSIS_PUBLIC_URL')
    if explicit:
        return explicit.rstrip('/')
    callback = urlsplit(os.getenv('BLIZZARD_REDIRECT_URI') or '')
    return f'{callback.scheme}://{callback.netloc}' if callback.netloc else None


def _page(title, session, body, waiting=False):
    from oauth_server import ADMIN_CSS, render_nav
    if session is PUBLIC_SESSION:
        body = _publicize(body)
        nav = ('<nav class="nav"><a href="/raids" class="active">⚔️ Raid Analysis</a><div class="spacer"></div>'
               '<span class="user-info">Read-only view</span></nav>')
        render_nav = lambda _session, active=None: nav  # noqa: E731 - public pages get their own nav
    else:
        body = sync_banner(sync.status, waiting) + body
    prefix = 'Luminis Raids' if session is PUBLIC_SESSION else 'LuminisBot Admin'
    response = web.Response(text=f"""<!DOCTYPE html>
<html>
<head>
    <title>{prefix} - {esc(title)}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>{ADMIN_CSS}{PAGE_CSS}</style>
</head>
<body>
    <div class="container">
        {render_nav(session, active='raids')}
        {body}
    </div>
    {CLIP_MODAL}
    <script>{PAGE_JS}</script>
</body>
</html>""", content_type='text/html')
    response.enable_compression()  # pages are big but very repetitive - gzip shrinks them ~10x
    return response


def _flash(request):
    out = ''
    if request.query.get('msg'):
        out += f'<p class="success">✅ {esc(request.query["msg"])}</p>'
    if request.query.get('error'):
        out += f'<p class="error">❌ {esc(request.query["error"])}</p>'
    return out


def _with_duration(pull):
    """The pull's analysis plus its duration, as analyzer.scoreboard expects."""
    analysis = analyzer.annotate_deaths(dict(pull.get('analysis') or {}))
    analysis['_duration'] = pull['end_ms'] - pull['start_ms']
    return analysis


def _has_avoidable(tags):
    return any(tag in analyzer.AVOIDABLE_TAGS for tag in tags.values())


# Shared with the Discord recap (raidanalysis/discord_recap.py).
_effective_tags = guides.effective_tags
_guide_lookup = guides.guide_lookup


def _group_by_boss(pulls):
    groups = {}
    for pull in pulls:
        groups.setdefault((pull['encounter_id'], pull['difficulty']), []).append(pull)
    return groups


def _result_text(pull):
    result = 'Kill' if pull['kill'] else f"{pull['fight_pct'] or 0:.1f}%"
    return f"{result} · {fmt_duration(pull['end_ms'] - pull['start_ms'])}"


def _boss_status(boss):
    if boss['kills']:
        return f'<span class="pill pill-kill">✔ Killed</span> {ts(boss["first_kill"], "date")}'
    if boss['best_pct'] is not None:
        return f'Best <strong>{boss["best_pct"]:.1f}%</strong>'
    return ''


# ============================================================================
# GET /admin/raids - raid nights + boss progression + sync controls
# ============================================================================

def _team_query(team, **more):
    """'?team=sun&nights=3' - the query string that keeps a team (and other params) on links."""
    params = {'team': team or teams.ALL, **more}
    query = '&'.join(f'{k}={quote(str(v))}' for k, v in params.items() if v)
    return f'?{query}' if query else ''


TEAM_COOKIE = 'raid_team'


def _team(request):
    """The team to show: ?team= if given, else the one this browser picked last (cookie), else teams.DEFAULT."""
    return teams.parse(request.query.get('team') or request.cookies.get(TEAM_COOKIE))


def _remember_team(request, response):
    """
    Picking a team in the team dropdown / chips (?team=…&pick=1) sticks for this browser, so Team Moon
    raiders don't have to switch every time. Other links that merely carry a team don't change it.
    """
    value = request.query.get('team')
    if request.query.get('pick') and value and (value == teams.ALL or value in dict(teams.options())):
        response.set_cookie(TEAM_COOKIE, value, max_age=365 * 24 * 3600, path='/', samesite='Lax')
    return response


def _night_team(report):
    """The team whose night this is (None = all teams: unattached logs, for-fun raids)."""
    team = teams.of_channel(report.get('event_channel_id'))
    return team if team in dict(teams.options()) else None


def _team_pill(channel_id):
    team = teams.of_channel(channel_id)
    if team is None:
        return ''
    if team == teams.OTHER:
        return ('<span class="pill pill-wipe" title="Raid event posted outside the team signup channels - '
                'not counted in boss progress">for fun</span>')
    return f'<span class="pill">{esc(teams.label(team))}</span>'


def _overview_filters(request, tiers):
    """
    (zone_id or None, difficulty or None, team or None, filter-bar HTML). Defaults to the newest
    tier, all difficulties, all teams.
    """
    known = [t for t in tiers if t['zone_id'] is not None]
    tier_arg = request.query.get('tier')
    if tier_arg == 'all':
        zone_id = None
    elif tier_arg and tier_arg.isdigit() and any(t['zone_id'] == int(tier_arg) for t in known):
        zone_id = int(tier_arg)
    else:
        zone_id = known[0]['zone_id'] if known else None
    team = _team(request)
    diff_arg = request.query.get('difficulty')
    difficulty = int(diff_arg) if diff_arg and diff_arg.isdigit() and int(diff_arg) in DIFFICULTY_NAMES else None

    tier_options = ''.join(
        f'<option value="{t["zone_id"]}"{" selected" if t["zone_id"] == zone_id else ""}>'
        f'{esc(t["zone_name"] or "Unknown zone")} ({t["nights"]} night{"s" if t["nights"] != 1 else ""})</option>'
        for t in known)
    tier_options += f'<option value="all"{" selected" if zone_id is None else ""}>All tiers</option>'
    diff_options = f'<option value=""{" selected" if difficulty is None else ""}>All difficulties</option>' + ''.join(
        f'<option value="{d}"{" selected" if d == difficulty else ""}>{name}</option>'
        for d, name in sorted(DIFFICULTY_NAMES.items(), reverse=True))
    team_options = f'<option value="{teams.ALL}"{" selected" if team is None else ""}>All teams</option>' + ''.join(
        f'<option value="{key}"{" selected" if key == team else ""}>{esc(teams.label(key))}</option>'
        for key, _ in teams.options())
    bar = (f'<form method="get" class="filter-bar">'
           f'<label>Raid tier <select name="tier" onchange="this.form.submit()">{tier_options}</select></label>'
           f'<label>Difficulty <select name="difficulty" onchange="this.form.submit()">{diff_options}</select></label>'
           f'<label>Team <select name="team" onchange="this.form.submit()">{team_options}</select></label>'
           f'<input type="hidden" name="pick" value="1">'
           f'<noscript><button class="btn btn-secondary btn-sm">Filter</button></noscript></form>')
    return zone_id, difficulty, team, bar


async def handle_overview(request):
    session = _session(request)
    zone_id, difficulty, team, filter_bar = _overview_filters(request, db.list_tiers())
    reports = db.list_reports(limit=40, zone_id=zone_id, difficulty=difficulty, team=team)
    bosses = db.list_bosses(zone_id=zone_id, difficulty=difficulty, team=team)
    team_q = _team_query(team)

    st = sync.status
    if st['running']:
        sync_state = ''  # the progress banner at the top covers it
    elif st['last_finished']:
        sync_state = (f'<p class="muted small">Last sync: {ts(st["last_finished"] * 1000)} — '
                      f'{esc(st["last_result"])}</p>')
        if st['last_error']:
            sync_state += f'<p class="error small">⚠️ {esc(st["last_error"])}</p>'
    else:
        sync_state = '<p class="muted small">Syncs automatically every 10 minutes.</p>'
    budget = st.get('wcl')
    if budget:
        share = budget['spent'] / (budget['limit'] or 1)
        resets = f" · resets in {int((budget.get('reset_in') or 0) / 60)} min" if budget.get('reset_in') else ''
        last = f" · last sync used {st['last_points']}" if st.get('last_points') is not None else ''
        sync_state += (f'<p class="small {"bad-text" if share >= 0.7 else "muted"}" title="WCL allows a number of '
                       f'points per hour (bigger queries cost more), shared with the bot\'s other WCL buttons. '
                       f'The sync pauses at 70% to leave room for them.">WCL API: {budget["spent"]}/{budget["limit"]} '
                       f'points this hour{resets}{last}</p>')

    boss_rows = ''.join(f"""
        <tr onclick="location='/admin/raids/boss/{b['encounter_id']}/{b['difficulty']}{team_q}'" style="cursor:pointer">
            <td><a href="/admin/raids/boss/{b['encounter_id']}/{b['difficulty']}{team_q}" style="color:#fff">
                {boss_portrait(b['encounter_id'], 'sm', killed=bool(b['kills']))}<strong>{esc(b['name'])}</strong></a></td>
            <td>{difficulty_pill(b['difficulty'])}</td>
            <td class="num">{b['pulls']}</td>
            <td class="num">{b['nights']}</td>
            <td>{_boss_status(b)}</td>
            <td class="muted small">{ts(b['last_seen'], 'date')}</td>
        </tr>""" for b in bosses)

    night_rows = []
    for r in reports:
        span = (r['last_pull_ms'] or 0) - (r['first_pull_ms'] or 0)
        engaged = 100 * r['combat_ms'] / span if span else 0
        diffs = ' '.join(difficulty_pill(d) for d in sorted(r['difficulties'] or [], reverse=True))
        night_rows.append(f"""
            <tr>
                <td>{ts(r['start_time'], 'date')}</td>
                <td><a href="/admin/raids/report/{esc(r['code'])}" style="color:#fff"><strong>{esc(r['title'])}</strong></a>
                    {_team_pill(r['event_channel_id'])}
                    {'<span class="pill pill-wipe">imported</span>' if r['source'] == 'manual' else ''}
                    {f'<br><span class="small muted">📅 {esc(r["event_title"])}</span>' if r['event_title'] else ''}</td>
                <td>{esc(r['zone_name'] or '')} {diffs}</td>
                <td class="num">{r['pulls']}</td>
                <td class="num">{r['kills']}</td>
                <td class="num" title="Time in combat vs. time from first to last pull">{engaged:.0f}%</td>
                <td><a class="btn btn-primary btn-sm" href="/admin/raids/report/{esc(r['code'])}">All pulls</a></td>
            </tr>""")

    body = f"""
    <div class="card">
        <h1>⚔️ Raid Analysis</h1>
        {_flash(request) if session is not PUBLIC_SESSION else ''}
        <p class="muted">Every raid pull from the guild's Warcraft Logs and from the logs attached to raid
           events, analyzed for deaths, mechanics, interrupts, dispels and consumables.</p>
        {sync_state if session is not PUBLIC_SESSION else ''}
        <form method="post" action="/admin/raids/sync" class="inline-form">
            <label class="small muted">Latest reports</label>
            <input type="number" name="limit" value="10" min="1" max="50" style="width:80px">
            <input type="text" name="code" placeholder="…or a WCL report URL / code to import" style="min-width:320px">
            <button class="btn btn-primary btn-sm" {'disabled' if st['running'] else ''}>🔄 Sync now</button>
        </form>
        {_benchmarks_line(st['running']) if session is not PUBLIC_SESSION else ''}
    </div>
    <div class="card">{filter_bar}</div>
    <div class="card">
        <h2>🐉 Bosses{f" — {esc(teams.label(team))}" if team else ""}</h2>
        <p class="muted small">{"Only this team's raid nights." if team else "Both teams together."} Raid events
           posted outside the team signup channels (e.g. #for-fun-raids) aren't counted.</p>
        <div class="table-wrapper"><table class="compact">
            <tr><th>Boss</th><th>Difficulty</th><th class="num">Pulls</th><th class="num">Nights</th>
                <th>Progress</th><th>Last pulled</th></tr>
            {boss_rows or '<tr><td colspan="6" class="muted">No raid pulls synced yet — hit Sync now.</td></tr>'}
        </table></div>
    </div>
    <div class="card">
        <h2>📅 Raid nights</h2>
        <div class="table-wrapper"><table class="compact">
            <tr><th>Date</th><th>Report</th><th>Zone</th><th class="num">Pulls</th><th class="num">Kills</th>
                <th class="num">Engaged</th><th></th></tr>
            {''.join(night_rows) or '<tr><td colspan="7" class="muted">Nothing yet.</td></tr>'}
        </table></div>
    </div>"""
    return _remember_team(request, _page("Raid Analysis", session, body))


# ============================================================================
# POST /admin/raids/sync
# ============================================================================

async def handle_sync(request):
    _session(request)
    data = await request.post()
    try:
        limit = max(1, min(50, int(data.get('limit') or 10)))
    except ValueError:
        limit = 10
    codes = []
    raw = (data.get('code') or '').strip()
    if raw:
        match = REPORT_CODE_RE.search(raw)
        if not match:
            raise web.HTTPFound('/admin/raids?error=' + quote("That doesn't look like a WCL report URL or code."))
        codes.append(match.group(1))

    if sync.status['running']:
        raise web.HTTPFound('/admin/raids?error=' + quote('A sync is already running.'))
    if sync._paused():
        raise web.HTTPFound('/admin/raids?error=' + quote(sync._pause_message()))
    # Mark it running now, so the page we redirect to already shows (and polls) the progress banner.
    sync.status.update(running=True, current='Starting sync…')
    asyncio.create_task(sync.sync_guild(limit=limit, force_codes=codes))

    if codes:  # importing / re-analyzing one report: go watch it fill in
        raise web.HTTPFound(f'/admin/raids/report/{codes[0]}')
    back = data.get('back') or '/admin/raids'
    if not back.startswith('/admin/raids'):
        back = '/admin/raids'
    raise web.HTTPFound(back)


async def handle_fetch_benchmarks(request):
    """POST /admin/raids/benchmarks - fetch the top players for every spec we played lately, in the background."""
    _session(request)
    if sync.status['running']:
        raise web.HTTPFound('/admin/raids?error=' + quote('A sync is already running - try again when it is done.'))
    if sync._paused():
        raise web.HTTPFound('/admin/raids?error=' + quote(sync._pause_message()))
    sync.status.update(running=True, current='Fetching top players…')
    asyncio.create_task(sync.fetch_all_benchmarks())
    raise web.HTTPFound('/admin/raids?msg=' + quote('Fetching the top players for every spec in the background - '
                                                     'progress shows at the top of the page.'))


def _benchmarks_line(running):
    """Overview (admin): how many spec / boss combos still lack top players, and the fetch-all button."""
    needed = db.benchmarks_needed(10000, benchmarks.REFRESH_DAYS, benchmarks.DIFFICULTIES)
    if not needed:
        return ('<p class="muted small">⚔️ Top-player benchmarks are up to date for every spec played in the '
                'last 30 days.</p>')
    return f"""
        <form method="post" action="/admin/raids/benchmarks" class="inline-form">
            <span class="small muted">⚔️ {len(needed)} spec/boss combo{'s' if len(needed) != 1 else ''} played in
                the last 30 days {'have' if len(needed) != 1 else 'has'} no (or an outdated) top-player benchmark
                - the sync fetches {benchmarks.SPECS_PER_RUN} per run.</span>
            <button class="btn btn-secondary btn-sm" {'disabled' if running else ''}
                    title="About {1 + benchmarks.TOP_N} WCL requests per combo; pauses at the WCL budget limit">
                Fetch all top players</button>
        </form>"""


async def handle_sync_status(request):
    _session(request)
    st = sync.status
    return web.json_response({key: st.get(key) for key in
                              ('running', 'current', 'last_finished', 'last_result', 'last_error', 'last_new')})


# ============================================================================
# GET /admin/raids/report/{code} - one raid night, every pull grouped by boss
# ============================================================================

def _reason_html(reason):
    if not reason:
        return '<span class="good-text reason">✔ Kill</span>'
    return f'<span class="reason">{esc(reason["label"])}</span><span class="reason-detail">{esc(reason["detail"])}</span>'


def _enrage_ids(encounter_id, guide_for):
    """Logged abilities whose Mythic Trap entry describes an enrage / berserk timer."""
    out = set()
    for ability_id, info in db.ability_shares(encounter_id).items():
        guide = guide_for(ability_id, info['name']) or {}
        if 'enrage' in f"{guide.get('category', '')} {guide.get('subtitle', '')}".lower():
            out.add(ability_id)
    return out


def _pull_reason(pull, enrage_ids):
    return analyzer.wipe_reason(pull.get('analysis') or {}, pull['kill'], pull['end_ms'] - pull['start_ms'],
                                enrage_ids)


def _pull_row(code, number, pull, phase_names, tags, reason=None):
    analysis = pull.get('analysis') or {}
    deaths = analysis.get('deaths') or []
    avoidable = sum(s['hits'] for s in analyzer.avoidable_by_player(analysis, tags).values())
    wipe_at = analysis.get('wipe_at')
    boss_hp = '' if pull['kill'] or pull.get('boss_pct') is None else f"{pull['boss_pct']:.1f}%"
    return f"""
        <tr onclick="location='/admin/raids/report/{esc(code)}/{pull['fight_id']}'" style="cursor:pointer">
            <td class="num">{number}</td>
            <td>{ts(pull['_abs_start'], 'time')}</td>
            <td class="num">{fmt_duration(pull['end_ms'] - pull['start_ms'])}</td>
            <td data-v="{0 if pull['kill'] else pull['fight_pct'] or 0}">{result_pill(pull)}</td>
            <td class="num small">{boss_hp}</td>
            <td class="small">{phase_label(pull, phase_names)}</td>
            <td class="num">{len(deaths)}</td>
            <td class="num" data-v="{wipe_at or 0}">{fmt_duration(wipe_at) if wipe_at is not None else ''}</td>
            <td>{_reason_html(reason)}</td>
            <td class="num{' bad' if avoidable else ''}">{avoidable if _has_avoidable(tags) else '<span class="muted">—</span>'}</td>
            <td><a href="/admin/raids/report/{esc(code)}/{pull['fight_id']}" class="btn btn-secondary btn-sm">Details</a></td>
        </tr>"""


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _killer_label(death):
    """Killing blow text; 'likely …' when WCL had none and we inferred it from the death window."""
    return f"{'likely ' if death.get('likely') else ''}{death['ability']}"


def _selected_boss(request, groups):
    """?boss=<encounter>-<difficulty>, defaulting to the boss with the most pulls (the progression boss)."""
    try:
        encounter_id, difficulty = (int(v) for v in request.query.get('boss', '').split('-'))
        if (encounter_id, difficulty) in groups:
            return encounter_id, difficulty
    except ValueError:
        pass
    keys = list(groups)
    return max(keys, key=lambda k: (len(groups[k]), keys.index(k)))


def _night_header(request, report, code, pulls, selected, fight_id=None, view='mechanics'):
    """Night summary, boss tabs, Overall / pull chips and the Mechanics / Players switch."""
    players_q = view == 'players'
    groups = _group_by_boss(pulls)
    combat = sum(p['end_ms'] - p['start_ms'] for p in pulls)
    span = (pulls[-1]['end_ms'] - pulls[0]['start_ms']) if pulls else 0
    gaps = [b['start_ms'] - a['end_ms'] for a, b in zip(pulls, pulls[1:])]
    avg_gap = sum(gaps) / len(gaps) if gaps else 0

    tabs = []
    for (encounter_id, difficulty), boss_pulls in groups.items():
        kill = any(p['kill'] for p in boss_pulls)
        best = min((p['fight_pct'] or 0 for p in boss_pulls if not p['kill']), default=None)
        state = '✔ Killed' if kill else (f'best {best:.1f}%' if best is not None else '')
        active = ' active' if (encounter_id, difficulty) == selected else ''
        tabs.append(f'<a class="boss-tab{active}" href="/admin/raids/report/{esc(code)}?boss={encounter_id}-{difficulty}'
                    f'{"&view=players" if players_q else ""}">{boss_portrait(encounter_id, killed=kill)}'
                    f'<span><strong>{esc(boss_pulls[0]["encounter_name"])}</strong> {difficulty_pill(difficulty)}'
                    f'<small>{_plural(len(boss_pulls), "pull")} · {state}</small></span></a>')

    boss_pulls = groups[selected]
    overall_href = f'/admin/raids/report/{esc(code)}?boss={selected[0]}-{selected[1]}'
    chips = ['<span class="chips-label">Pulls</span>',
             f'<a class="pull-chip overall{" active" if fight_id is None else ""}" '
             f'href="{overall_href}{"&view=players" if players_q else ""}">Overall ({len(boss_pulls)})</a>']
    for number, pull in enumerate(boss_pulls, 1):
        label = '✔ Kill' if pull['kill'] else f"{pull['fight_pct'] or 0:.0f}%"
        classes = 'pull-chip' + (' kill' if pull['kill'] else '') + (' active' if pull['fight_id'] == fight_id else '')
        chips.append(f'<a class="{classes}" href="/admin/raids/report/{esc(code)}/{pull["fight_id"]}'
                     f'{"?view=players" if players_q else ""}" '
                     f'title="Pull {number}: {esc(_result_text(pull))}">#{number} {label}</a>')

    # Mechanics / Players switch, keeping the selected boss and pull.
    here_base = (f'/admin/raids/report/{esc(code)}/{fight_id}?' if fight_id else f'{overall_href}&')
    views = ''.join(
        f'<a class="view-tab{" active" if view == key else ""}" href="{here_base}view={key}">'
        f'<span class="vt-icon">{icon}</span><span><strong>{label}</strong><small>{hint}</small></span></a>'
        for key, icon, label, hint in (
            ('mechanics', '📋', 'Mechanics', 'What happened: wipes, deaths, mechanics, consumables'),
            ('players', '👥', 'Players', 'Who did what: scores, feedback, cooldowns vs top players')))

    event = (f' · 📅 <a href="/admin/events">{esc(report["event_title"])}</a>'
             if report.get('event_title') else '')
    return f"""
    <div class="card">
        <p><a href="/admin/raids">← All raid nights</a></p>
        <h1>{esc(report['title'])}</h1>
        {_flash(request)}
        <p class="muted">{ts(report['start_time'])} · {esc(report['zone_name'] or '')} ·
           logged by {esc(report['owner'] or '?')}{event} ·
           <a href="https://www.warcraftlogs.com/reports/{esc(code)}" target="_blank">Warcraft Logs ↗</a></p>
        <div class="muted small">{_plural(len(pulls), "pull")} · {sum(1 for p in pulls if p['kill'])} kills ·
           {fmt_duration(span)} raid · {100 * combat / span if span else 0:.0f}% of it in combat ·
           {fmt_duration(avg_gap)} between pulls on average
           <form method="post" action="/admin/raids/sync" class="inline-form" style="margin-left:10px">
               <input type="hidden" name="code" value="{esc(code)}">
               <button class="btn btn-secondary btn-sm" title="Fetch this report again from WCL">🔄 Re-analyze</button>
           </form></div>
        <div class="boss-tabs">{''.join(tabs)}</div>
        <div class="pull-chips">{''.join(chips)}</div>
        <nav class="view-tabs">{views}</nav>
    </div>"""


CHEVRON = ('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
           'stroke-linejoin="round"><path d="M6 4l4 4-4 4"/></svg>')

# Filter groups for the mechanics table, in chip order: (key, label, shown by default).
MECH_GROUPS = (('avoidable', '🔴 Avoidable', True), ('nontank', '🟠 Non-tanks', True),
               ('untagged', '⚪ Untagged', True), ('expected', '🟢 Expected', False), ('ignored', '⚫ Ignored', False))


def _mech_group(tag):
    return {analyzer.TAG_AVOIDABLE: 'avoidable', analyzer.TAG_AVOIDABLE_NON_TANK: 'nontank',
            guides.EXPECTED: 'expected', analyzer.TAG_IGNORE: 'ignored'}.get(tag, 'untagged')


def _mech_detail(a, counts, pname, per_pull, pull_href, timeline, avoidable=False):
    """The expanded part of a mechanics row: per pull (night view), who took it, when (one pull)."""
    parts = []
    if per_pull:
        rows = []
        for p in per_pull:
            own = next((x for x in p['analysis'].get('abilities') or [] if x['id'] == a['id']), None)
            if not own:
                continue
            own_counts = analyzer.mistake_counts(own)
            victims = sorted((own.get('players') or {}).items(),
                             key=lambda kv: -(own_counts.get(kv[0], 0) * 1e12 + (kv[1].get('damage') or 0)))
            worst = ', '.join(pname(n) + (f' ×{own_counts[n]}' if own_counts.get(n) else '') for n, _ in victims[:4])
            result = '✔ Kill' if p.get('kill') else f"{p.get('fight_pct') or 0:.0f}%"
            rows.append(f'<tr><td><a href="{esc(pull_href(p))}">#{p["number"]}</a> '
                        f'<span class="muted small">{esc(result)}</span></td>'
                        f'<td class="num">{fmt_amount(own.get("total") or 0)}</td>'
                        f'<td class="num">{len(own.get("players") or {}) if own.get("complete") else "5+"}</td>'
                        f'<td class="num">{sum(own_counts.values()) if own.get("complete") else "—"}</td>'
                        f'<td class="small">{worst}</td></tr>')
        if rows:
            parts.append('<div><h4>Per pull</h4><div class="table-wrapper"><table class="compact"><tr><th>Pull</th>'
                         '<th class="num">Damage</th><th class="num">Players</th>'
                         f'<th class="num">{"Mistakes" if avoidable else "Hits"}</th>'
                         f'<th>Worst hit</th></tr>{"".join(rows)}</table></div></div>')
    players = sorted((a.get('players') or {}).items(),
                     key=lambda kv: -(counts.get(kv[0], 0) * 1e12 + (kv[1].get('damage') or 0)))
    if players:
        rows = ''.join(f'<tr><td>{pname(n)}</td><td class="num">{fmt_amount(st.get("damage") or 0)}</td>'
                       f'<td class="num">{st.get("hits") or 0}</td><td class="num">{st.get("ticks") or 0}</td>'
                       + (f'<td class="num">{counts.get(n) or ""}</td>' if avoidable else '') + '</tr>'
                       for n, st in players)
        note = '' if a.get('complete') else ('<p class="muted small">Raid-wide ability: Warcraft Logs only lists '
                                             'its top 5 targets.</p>')
        parts.append(f'<div><h4>Who took it</h4><div class="table-wrapper"><table class="compact"><tr><th>Player</th>'
                     f'<th class="num">Damage</th><th class="num">Hits</th><th class="num">Ticks</th>'
                     + ('<th class="num" title="Hits that count as a mistake for its tag">Mistakes</th>' if avoidable else '')
                     + f'</tr>{rows}</table>'
                     f'</div>{note}</div>')
    if timeline:
        duration, phases = timeline
        times = [(n, st.get('times') or []) for n, st in players if st.get('times')]
        if times:
            parts.append(f'<div class="mech-wide"><h4>When</h4>{hit_timeline(times, duration, phases)}</div>')
    return f'<div class="mech-detail-grid">{"".join(parts)}</div>' if parts else '<p class="muted">No details.</p>'


def _mechanics_table(analysis, tags, sources, guide_for, pname, encounter_id, difficulty, here,
                     per_pull=None, pull_href=None, timeline=None):
    """
    Damage taken per enemy ability (one pull, or several merged) with tag buttons, filter chips per tag
    (Expected / Ignored start hidden: rarely what a review is about) and a click-to-expand detail per
    ability: per pull (per_pull + pull_href, night view), who took it, and when (timeline = (duration,
    phases), pull view).
    """
    raid_size = max(1, len(analysis.get('players') or []))
    rows, group_counts = [], {}
    for a in analysis.get('abilities') or []:
        tag = tags.get(a['id'])
        group = _mech_group(tag)
        group_counts[group] = group_counts.get(group, 0) + 1
        counts = analyzer.mistake_counts(a)
        players = sorted((a.get('players') or {}).items(),
                         key=lambda kv: -(counts.get(kv[0], 0) * 1e12 + (kv[1].get('damage') or 0)))
        who = ', '.join(f'{pname(n)}' + (f' ×{counts[n]}' if counts.get(n) else '') for n, _ in players[:5])
        if len(players) > 5:
            who += f' <span class="muted">+{len(players) - 5}</span>'
        hits = sum(counts.values()) if a.get('complete') else None
        hidden = '' if dict((k, on) for k, _, on in MECH_GROUPS)[group] else ' hidden'
        rows.append(f"""
            <tr class="mech-row" data-mg="{group}"{hidden} tabindex="0" title="Click for details">
                <td><span class="mech-caret" aria-hidden="true">{CHEVRON}</span>{ability(a['name'], a.get('icon'), a['id'], guide_for(a['id'], a['name']))}
                    {tag_pill(tag, sources.get(a['id'])) if tag != analyzer.TAG_IGNORE else ''}</td>
                <td class="small muted">{esc(a.get('source') or '')}</td>
                <td class="num" data-v="{a['total']}">{fmt_amount(a['total'])}</td>
                <td class="num" data-v="{len(players)}">{len(players) if a.get('complete') else '5+'}/{raid_size}</td>
                <td class="num" data-v="{hits or 0}">{hits if hits is not None else '<span class="muted" title="Raid-wide ability — only the top 5 targets are known">—</span>'}</td>
                <td class="small">{who}</td>
                <td>{tag_buttons(encounter_id, difficulty, a['id'], a['name'], tag, sources.get(a['id']), here)}</td>
            </tr>
            <tr class="mech-detail" data-mg="{group}" hidden><td colspan="7">
                {_mech_detail(a, counts, pname, per_pull, pull_href, timeline, group in ('avoidable', 'nontank'))}</td></tr>""")
    chips = ''.join(
        f'<button type="button" class="tl-chip" data-mg="{key}" aria-pressed="{"true" if on else "false"}">'
        f'{label} <span class="muted">{group_counts[key]}</span></button>'
        for key, label, on in MECH_GROUPS if group_counts.get(key))
    head = ('<tr><th data-sort>Ability</th><th>Source</th><th data-sort class="num">Damage</th>'
            '<th data-sort class="num">Players hit</th><th data-sort class="num" title="Direct hits, counted the way '
            'mistakes are (several ticks of one cast count once) - mistakes when the ability is tagged avoidable">'
            'Hits</th><th>Who</th><th>Tag</th></tr>')
    return (f'<div class="mech-wrap"><div class="tl-chips">{chips}</div>'
            f'<div class="table-wrapper"><table class="compact mech-table">{head}{"".join(rows)}</table></div>'
            f'<p class="muted small mech-empty" hidden>Nothing in the selected groups.</p></div>')


def _roster_names(analysis):
    roster = {p['name']: p for p in analysis.get('players') or []}

    def pname(name):
        p = roster.get(name, {})
        return player_name(name, p.get('class', ''), p.get('role'))
    return pname


def _consumables_card(insight_pulls, roster, boss=None):
    """The raid timeline: enemy casts on top; every player's potions, healthstones, cooldowns and deaths below."""
    analyses = [p['analysis'] for p in insight_pulls]
    if not consumables.has_details(analyses):
        return ('<div class="card"><h2>🕒 Raid timeline</h2>' + insights.REANALYZE_HINT + '</div>')
    single = len(insight_pulls) == 1
    reference = consumables.reference_pull(insight_pulls)
    majors = benchmarks.spec_majors(*boss, spells.lookup) if boss else {}
    if single:
        hint = ('Boss casts on top; underneath, each player\'s potions (bar = buff duration), healthstones / '
                'healing potions (diamonds), deaths and cooldowns - damage &amp; healing cooldowns, defensives, '
                'externals, raid cooldowns and utility. Toggle what to show with the chips, pick single abilities '
                'under Abilities, hover anything for details.')
    else:
        hint = ('Every pull on one axis: potions, healthstones and cooldowns from all of them - clusters show '
                'each player\'s habits (e.g. always potting at the pull and again around 5:00, or saving a '
                'cooldown for the same moment every pull). Toggle what to show with the chips.')
        if reference:
            which = 'the kill' if reference.get('kill') else 'the longest pull'
            hint += (f' Enemy casts on top are from pull #{reference["number"]} ({which}); boss timers are mostly '
                     'the same every pull, but shift when a phase is pushed faster or slower. Open a single pull '
                     'for its exact timeline.')
    return (f'<div class="card"><h2>🕒 Raid timeline</h2><p class="muted small">{hint}</p>'
            f'{consumables.timeline(insight_pulls, roster, spells.lookup, majors)}</div>')


def _insight_pulls(numbered, enrage_ids=()):
    return [{'number': number, 'kill': pull['kill'], 'analysis': _with_duration(pull),
             'fight_id': pull['fight_id'], 'fight_pct': pull.get('fight_pct'),
             'reason': _pull_reason(pull, enrage_ids),
             'phases': [p['start'] for p in (pull.get('phases') or [])[1:]]} for number, pull in numbered]


async def handle_night(request):
    session = _session(request)
    code = request.match_info['code']
    report = db.get_report(code)
    pulls = db.get_pulls(code) if report else []
    if not pulls:
        if sync.status['running']:
            body = f"""
            <div class="card">
                <p><a href="/admin/raids">← All raid nights</a></p>
                <h1>Importing {esc(code)}…</h1>
                <p class="muted">Fetching the report from Warcraft Logs and analyzing every pull.
                   This page fills in by itself when it's done.</p>
            </div>"""
            return _page('Importing report', session, body, waiting=True)
        if report:
            error = 'That report has no raid boss pulls (Mythic+ or trash only).'
        else:
            error = sync.status.get('last_error') or 'Report not found — sync or import it first.'
        raise web.HTTPFound('/admin/raids?error=' + quote(error))

    for pull in pulls:
        pull['_abs_start'] = report['start_time'] + pull['start_ms']
    phase_names = report['phase_names'] or {}
    groups = _group_by_boss(pulls)
    selected = _selected_boss(request, groups)
    encounter_id, difficulty = selected
    boss_pulls = groups[selected]
    numbered = list(enumerate(boss_pulls, 1))
    here = f'/admin/raids/report/{code}?boss={encounter_id}-{difficulty}'

    tags, sources = _effective_tags(encounter_id)
    guide_for = _guide_lookup(encounter_id)
    analyses = [_with_duration(p) for p in boss_pulls]
    merged = analyzer.merge_pulls(analyses)
    name = boss_pulls[0]['encounter_name']

    if request.query.get('view') == 'players':
        report_rows = analyzer.player_report(_insight_pulls(numbered), tags)
        body = (_night_header(request, report, code, pulls, selected, view='players')
                + players.players_view(report_rows, guide_for,
                                       lambda player: players.player_url(code, player, selected)))
        return _page(f"Players · {name}", session, body)

    enrage_ids = _enrage_ids(encounter_id, guide_for)
    insight_pulls = _insight_pulls(numbered, enrage_ids)
    reasons = {p['number']: p['reason'] for p in insight_pulls}
    points = [{'pct': p['fight_pct'], 'kill': p['kill'], 'href': f"/admin/raids/report/{code}/{p['fight_id']}",
               'tip': f"Pull {i}: {_result_text(p)}"
                      + (f" — {reasons[i]['label']}" if reasons[i] else '')} for i, p in numbered]
    rows = ''.join(_pull_row(code, i, p, phase_names, tags, reasons[i]) for i, p in numbered)
    phases = analyzer.phase_progress(
        [{'phases': p.get('phases'), 'duration': p['end_ms'] - p['start_ms']} for p in boss_pulls],
        phase_names.get(str(encounter_id)))
    phase_html = (f'<h3 style="margin-top:8px">How far we got</h3>{phase_funnel(phases, len(boss_pulls))}'
                  if len(phases) > 1 else '')

    body = _night_header(request, report, code, pulls, selected) + f"""
    <div class="card">
        <h2>{esc(name)} {difficulty_pill(difficulty)} — overall
            <a href="/admin/raids/boss/{encounter_id}/{difficulty}{_team_query(_night_team(report))}" class="btn btn-secondary btn-sm"
               style="float:right">Progression across nights →</a></h2>
        <p class="muted">{_plural(len(boss_pulls), "pull")} ·
           {fmt_duration(sum(p['end_ms'] - p['start_ms'] for p in boss_pulls))} in combat</p>
        {progress_chart(points)}
        {phase_html}
        <h3 style="margin-top:8px">Every pull</h3>
        <div class="table-wrapper"><table class="compact">
            <tr><th data-sort class="num">#</th><th>Time</th><th data-sort class="num">Duration</th>
                <th data-sort title="WCL fight %: how much of the encounter was left, accounting for phases">Fight %</th>
                <th data-sort class="num" title="Boss health when the pull ended">Boss HP</th>
                <th>Phase</th><th data-sort class="num">Deaths</th>
                <th data-sort class="num" title="When half the raid was dead">Half dead</th>
                <th data-sort>Why it ended</th>
                <th data-sort class="num" title="Hits from avoidable mechanics">Avoidable</th><th></th></tr>
            {rows}
        </table></div>
    </div>
    <div class="card">
        <h2>📋 Mechanics</h2>
        {insights.build(insight_pulls, tags, guide_for, code)}
    </div>
    {_consumables_card(insight_pulls, merged['players'], (encounter_id, difficulty))}
    <div class="card">
        <h2>💀 Deaths in every pull</h2>
        <p class="muted small">One row per pull, along its own length: red ticks are early deaths by mistake (one of
           the first 4 deaths, not part of a mass death), grey ones are the rest; the dashed yellow line is where half
           the raid was dead, thin lines are phase changes. Zoom in like a video editor's timeline to pick apart deaths that happen close together; click a row to open that pull.</p>
        {deaths_strip(insights.death_strip_rows(code, numbered), spells.lookup)}
    </div>
    <div class="card">
        <h2>🎯 Damage taken by mechanic — all pulls</h2>
        <p class="muted small">Pick which tags to show with the chips; click an ability for its damage per pull
           and who took it.</p>
        {_mechanics_table(merged, tags, sources, guide_for, _roster_names(merged), encounter_id, difficulty, here,
                          per_pull=insight_pulls, pull_href=lambda p: f'/admin/raids/report/{code}/{p["fight_id"]}')}
    </div>
    <div class="card">
        <h2>👥 Players</h2>
        {scoreboard_table(analyzer.scoreboard(analyses, tags), show_avoidable=_has_avoidable(tags))}
    </div>"""
    return _page(f"{name} · {report['title']}", session, body)


async def handle_pull(request):
    session = _session(request)
    code = request.match_info['code']
    try:
        fight_id = int(request.match_info['fight_id'])
    except ValueError:
        raise web.HTTPNotFound()
    report = db.get_report(code)
    pulls = db.get_pulls(code, with_analysis=False) if report else []
    pull = db.get_pull(code, fight_id)
    if not pull:
        raise web.HTTPFound(f'/admin/raids/report/{quote(code)}?error=' + quote('Pull not found.'))

    analysis = analyzer.annotate_deaths(pull['analysis'] or {})
    phase_names = pull['phase_names'] or {}
    encounter_id, difficulty = pull['encounter_id'], pull['difficulty']
    tags, sources = _effective_tags(encounter_id)
    guide_for = _guide_lookup(encounter_id)
    pname = _roster_names(analysis)
    here = f'/admin/raids/report/{code}/{fight_id}'
    same_boss = [p for p in pulls if p['encounter_id'] == encounter_id and p['difficulty'] == difficulty]
    number = next(i for i, p in enumerate(same_boss, 1) if p['fight_id'] == fight_id)

    if request.query.get('view') == 'players':
        selected = (encounter_id, difficulty)
        report_rows = analyzer.player_report(_insight_pulls([(number, pull)]), tags)
        body = (_night_header(request, report, code, pulls, selected, fight_id, view='players')
                + players.players_view(report_rows, guide_for,
                                       lambda player: players.player_url(code, player, selected, fight_id)))
        return _page(f"Players · {pull['encounter_name']} pull {number}", session, body)

    death_rows = ''.join(
        f'<tr{"" if d.get("early") else " class=muted"}><td class="num">{fmt_duration(d["t"])}</td>'
        f'<td>{pname(d["name"])}</td>'
        f'<td>{"<span class=muted>likely</span> " if d.get("likely") else ""}'
        f'{ability(d["ability"], d.get("icon"), d.get("ability_id"), guide_for(d.get("ability_id"), d["ability"]))}</td>'
        f'<td class="small{" bad-text" if d.get("early") else ""}">{analyzer.death_note(d)}</td></tr>'
        for d in analysis.get('deaths') or [])

    result = 'Kill' if pull['kill'] else f"Wipe at {pull['fight_pct'] or 0:.1f}%"
    pull_insights = _insight_pulls([(number, pull)], _enrage_ids(encounter_id, guide_for))
    reason = pull_insights[0]['reason']
    reason_html = f'<p>🧯 {_reason_html(reason)}</p>' if reason else ''
    body = _night_header(request, report, code, pulls, (encounter_id, difficulty), fight_id) + f"""
    <div class="card">
        <h2>{esc(pull['encounter_name'])} {difficulty_pill(difficulty)} — pull {number} {result_pill(pull)}</h2>
        <p class="muted">{ts(pull['report_start'] + pull['start_ms'])} · {fmt_duration(pull['end_ms'] - pull['start_ms'])} ·
           {result}{' · ' + phase_label(pull, phase_names) if pull.get('last_phase') else ''} ·
           <a href="https://www.warcraftlogs.com/reports/{esc(code)}#fight={fight_id}" target="_blank">Warcraft Logs ↗</a></p>
        {reason_html}
        {pull_timeline(pull, analysis, phase_names)}
        <p class="muted small">Red ticks are early deaths by mistake (one of the first 4 deaths, not part of a mass
           death of 3+ players within 3s); grey ones don't count against anyone. Hover for details.</p>
    </div>
    <div class="card">
        <h2>📋 Mechanics</h2>
        {insights.build(pull_insights, tags, guide_for, code)}
    </div>
    {_consumables_card(pull_insights, analysis.get('players') or [], (encounter_id, difficulty))}
    <div class="card">
        <h2>💀 Deaths</h2>
        <div class="table-wrapper"><table class="compact"><tr><th class="num">Time</th><th>Player</th>
            <th>Killing blow</th><th></th></tr>
        {death_rows or '<tr><td colspan="4" class="muted">Nobody died.</td></tr>'}</table></div>
    </div>
    <div class="card">
        <h2>🎯 Damage taken by mechanic</h2>
        <p class="muted small">Tags marked <em>auto</em> come from the boss's Mythic Trap guide; clicking a tag
           overrides it for this boss on every night. Raid-wide abilities only show their top 5 targets.
           Pick tags with the chips; click an ability to see who took it and when.</p>
        {_mechanics_table(analysis, tags, sources, guide_for, pname, encounter_id, difficulty, here,
                          timeline=(pull['end_ms'] - pull['start_ms'],
                                    [p['start'] for p in (pull.get('phases') or [])[1:]]))}
    </div>
    <div class="card">
        <h2>👥 Players</h2>
        {scoreboard_table(analyzer.scoreboard([_with_duration(pull)], tags), show_avoidable=_has_avoidable(tags))}
    </div>"""
    return _page(f"{pull['encounter_name']} pull {number}", session, body)


def _avoidable_summary(analyses, tags, guide_for=lambda ability_id, name: None):
    totals = {}
    for analysis in analyses:
        roles = {p['name']: p.get('role') for p in analysis.get('players') or []}
        for a in analysis.get('abilities') or []:
            tag = tags.get(a['id'])
            if tag not in analyzer.AVOIDABLE_TAGS:
                continue
            entry = totals.setdefault(a['id'], {'name': a['name'], 'icon': a.get('icon'), 'hits': 0,
                                                'damage': 0, 'players': {}})
            counts = analyzer.mistake_counts(a)
            for name, s in (a.get('players') or {}).items():
                if not counts.get(name) or (tag == analyzer.TAG_AVOIDABLE_NON_TANK and roles.get(name) == 'tank'):
                    continue
                entry['hits'] += counts[name]
                entry['damage'] += s.get('damage') or 0
                entry['players'][name] = entry['players'].get(name, 0) + counts[name]
    if not totals:
        return '<p class="muted">No avoidable mechanics tagged (or nobody got hit).</p>'
    rows = []
    for ability_id, t in sorted(totals.items(), key=lambda kv: -kv[1]['hits']):
        worst = sorted(t['players'].items(), key=lambda kv: -kv[1])[:4]
        rows.append(f'<tr><td>{ability(t["name"], t["icon"], ability_id, guide_for(ability_id, t["name"]))}</td>'
                    f'<td class="num">{t["hits"]}</td>'
                    f'<td class="num">{fmt_amount(t["damage"])}</td>'
                    f'<td class="small">{", ".join(f"{esc(n)} ×{c}" for n, c in worst if c)}</td></tr>')
    return (f'<div class="table-wrapper"><table class="compact"><tr><th>Mechanic</th><th class="num">Hits</th>'
            f'<th class="num">Damage</th><th>Most hit</th></tr>{"".join(rows)}</table></div>')


async def handle_player(request):
    """One player across a boss's pulls on a night (or one pull with ?pull=)."""
    session = _session(request)
    code, name = request.match_info['code'], request.match_info['name']
    report = db.get_report(code)
    pulls = db.get_pulls(code) if report else []
    if not pulls:
        raise web.HTTPFound('/admin/raids?error=' + quote('Report not found.'))
    groups = _group_by_boss(pulls)
    selected = _selected_boss(request, groups)
    numbered = list(enumerate(groups[selected], 1))
    fight_id = request.query.get('pull')
    if fight_id and fight_id.isdigit():
        numbered = [(n, p) for n, p in numbered if p['fight_id'] == int(fight_id)] or numbered
        fight_id = int(fight_id) if len(numbered) == 1 else None
    else:
        fight_id = None

    tags, _ = _effective_tags(selected[0])
    guide_for = _guide_lookup(selected[0])
    player = next((p for p in analyzer.player_report(_insight_pulls(numbered), tags) if p['name'] == name), None)
    if not player:
        raise web.HTTPFound(f'/admin/raids/report/{quote(code)}?boss={selected[0]}-{selected[1]}&view=players'
                            f'&error=' + quote(f'{name} was not in those pulls.'))
    fights = {number: pull['fight_id'] for number, pull in numbered}
    await benchmarks.ensure_spells_for(list(enumerate(groups[selected], 1)), name)
    body = (_night_header(request, report, code, pulls, selected, fight_id, view='players')
            + players.player_page(player, guide_for,
                                  lambda number: f'/admin/raids/report/{code}/{fights[number]}')
            + _compare_card(request, code, selected, name, list(enumerate(groups[selected], 1)),
                            f'/admin/raids/report/{quote(code)}/player/{quote(name)}?boss={selected[0]}-{selected[1]}'
                            + (f'&pull={fight_id}' if fight_id else '')))
    return _page(f"{name} · {groups[selected][0]['encounter_name']}", session, body)


async def handle_spell(request):
    """GET /raids/spell/{id} - tooltip data for one spell (cached; looked up on Wowhead the first time)."""
    try:
        spell_id = int(request.match_info['spell_id'])
    except ValueError:
        raise web.HTTPNotFound()
    found = db.get_spells([spell_id])
    if spell_id not in found and spell_id not in db.attempted_spell_ids([spell_id]):
        await spells.fetch_ids([spell_id])
        found = db.get_spells([spell_id])
    info = found.get(spell_id)
    if not info:
        raise web.HTTPNotFound()
    return web.json_response({'name': info['name'], 'icon': spells.icon_url(info['icon']),
                              'meta': info['meta'] or '', 'desc': info['description'] or ''},
                             headers={'Cache-Control': 'public, max-age=86400'})


def compare_url(code, selected, name, fight_id=None):
    return (f'/admin/raids/report/{quote(code)}/compare/{quote(name)}?boss={selected[0]}-{selected[1]}'
            + (f'&pull={fight_id}' if fight_id else ''))


def _benchmark_status(data):
    """Why there's no comparison yet, in words."""
    bench = data['benchmark'] if data else None
    if not data:
        return "We don't know this character's spec in these pulls, so there's nothing to compare."
    if not bench:
        return (f"The top {esc(data['label'])} on this boss haven't been fetched yet - the sync picks up a few "
                f"specs at a time, so check back after the next syncs.")
    if bench['status'] == 'empty':
        return f"Warcraft Logs has no public top parses for {esc(data['label'])} on this boss yet."
    if bench['status'] == 'error' and not bench['players']:
        return f"Fetching the top {esc(data['label'])} failed ({esc(bench['error'] or '')}) - it's retried tomorrow."
    return ''


def _compare_pull(data, wanted=None):
    """Which pull the timeline shows: the one asked for, else the kill, else the longest (1 min+ preferred)."""
    eligible = [p for p in data['pulls'] if p['duration'] >= benchmarks.MIN_PULL_MS] or data['pulls']
    pull = next((p for p in eligible if wanted and str(p['fight_id']) == str(wanted)), None) or \
        max(eligible, key=lambda p: (bool(p.get('kill')), p['duration']))
    return eligible, pull


def _compare_sections(code, numbered, data, pull, eligible, chip_href):
    """(intro, summary, timeline) HTML for the comparison - the compare page and the player page share it."""
    rows_by_fight = {p['fight_id']: p for _, p in numbered}

    def chip_label(p):
        return '✔ Kill' if p.get('kill') else f"{rows_by_fight[p['fight_id']]['fight_pct'] or 0:.0f}%"
    pull_chips = ''.join(
        f'<a class="pull-chip{" kill" if p.get("kill") else ""}{" active" if p is pull else ""}" '
        f'href="{chip_href(p["fight_id"])}" '
        f'title="Pull {p["number"]}: {esc(_result_text(rows_by_fight[p["fight_id"]]))}">'
        f'#{p["number"]} {chip_label(p)}</a>' for p in eligible)
    fetched = data['benchmark'].get('fetched_at')
    intro = f"""
        <p class="small">Major cooldowns, potions and defensives next to the top {len(data['top'])}
           {esc(data['label'])} parses on Warcraft Logs{f" (fetched {ts(fetched.timestamp() * 1000, 'date')})" if fetched else ""}.
           "Major" = anything they press rarely with a 30 s+ cooldown, plus potions and defensives.
           Verdicts use all of tonight's pulls of 1 min+; the timeline shows one pull.</p>
        {_reanalyze_hint(data, code)}"""
    summary = f"""
        <p class="muted small">"Lined up" counts the moments where at least 3 of the top {len(data['top'])} press an
           ability (phase by phase, as phases start at different times for everyone) that your pulls reached,
           and how many of those you pressed it within ±{benchmarks.TOLERANCE_MS // 1000} s. Externals and raid
           cooldowns are shown for reference only - they depend on your raid's plan.</p>
        {compare.summary(data)}"""
    timeline = f"""
        <p class="muted small">Grouped by ability: your pull first, then the top players. Shaded bands are the
           moments most of them agree on; the boss's abilities on top are from your pull.
           <strong>Align phases</strong> lines everyone's phases up;
           <strong>Real time</strong> shows each fight as it happened. Pick abilities with the chips; hover
           anything for details.</p>
        <div class="pull-chips" style="margin-bottom:12px"><span class="chips-label">Pull</span>{pull_chips}</div>
        {compare.timeline(data, pull, _boss_timeline_of(numbered, pull['fight_id']), spells.lookup)}"""
    return intro, summary, timeline


def _compare_card(request, code, selected, name, numbered, page_href):
    """Player page: the whole comparison right there - verdicts, then the timeline (no extra click)."""
    data = benchmarks.for_player(numbered, name)
    why = _benchmark_status(data)
    if why or not data['rows']:
        return (f'<div class="card" id="compare"><h2>⚔️ Cooldowns vs top players</h2>'
                f'<p class="muted">{why or "Not enough long pulls to compare yet."}</p></div>')
    eligible, pull = _compare_pull(data, request.query.get('tl') or request.query.get('pull'))
    joiner = '&' if '?' in page_href else '?'
    intro, summary, timeline = _compare_sections(
        code, numbered, data, pull, eligible, lambda fight_id: f'{page_href}{joiner}tl={fight_id}#compare')
    return f"""
    <div class="card" id="compare">
        <h2>⚔️ Cooldowns vs top players</h2>
        {intro}
        <details class="top-players"><summary class="small">The top {len(data['top'])} {esc(data['label'])}</summary>
            {compare.top_players(data)}</details>
        <h3 style="margin-top:16px">📋 Summary</h3>
        {summary}
        <h3 style="margin-top:22px">🕒 Timeline</h3>
        {timeline}
    </div>"""


def _reanalyze_hint(data, code):
    """Some abilities can't be judged: tonight's pulls were analyzed before every cast was kept."""
    unknown = [r['name'] for r in data['rows'] if not r['known'] and r['category'] in benchmarks.JUDGED]
    if not unknown:
        return ''
    return (f'<p class="small warn-text">⚠️ This night was analyzed before every cast was kept, so '
            f'{esc(", ".join(unknown[:6]))}{" and more" if len(unknown) > 6 else ""} can\'t be compared yet - '
            f'<strong>🔄 Re-analyze</strong> it on the <a href="/admin/raids/report/{quote(code)}">night page</a>.</p>')


def _boss_timeline_of(numbered, fight_id):
    """The boss's casts in one of our pulls: {'abilities', 'casts'} from its analysis."""
    analysis = next((p.get('analysis') or {} for _, p in numbered if p['fight_id'] == fight_id), {})
    return {'abilities': analysis.get('boss_abilities') or [], 'casts': analysis.get('boss_casts') or []}


async def handle_compare(request):
    """
    GET /admin/raids/report/{code}/compare/{name}?boss=&pull= - cooldowns vs the top parses of the spec,
    on its own page (what the Discord recap links to; on the site it's part of the player page).
    """
    session = _session(request)
    code, name = request.match_info['code'], request.match_info['name']
    report = db.get_report(code)
    pulls = db.get_pulls(code) if report else []
    if not pulls:
        raise web.HTTPFound('/admin/raids?error=' + quote('Report not found.'))
    groups = _group_by_boss(pulls)
    selected = _selected_boss(request, groups)
    numbered = list(enumerate(groups[selected], 1))
    boss_name = groups[selected][0]['encounter_name']
    back = f'/admin/raids/report/{quote(code)}/player/{quote(name)}?boss={selected[0]}-{selected[1]}'
    await benchmarks.ensure_spells_for(numbered, name)
    data = benchmarks.for_player(numbered, name)
    head = (f'<div class="card"><p><a href="{back}">← {esc(name)} on {esc(boss_name)} (full player view)</a></p>'
            f'<h1>⚔️ {esc(name)} vs the top {esc(data["label"]) if data else "players"}</h1>'
            f'<p class="muted">{esc(boss_name)} {difficulty_pill(selected[1])} · {esc(report["title"])}</p>')
    why = _benchmark_status(data)
    if why:
        return _page(f'{name} vs top players', session, head + f'<p>{why}</p></div>')
    eligible, pull = _compare_pull(data, request.query.get('pull'))
    intro, summary, timeline = _compare_sections(
        code, numbered, data, pull, eligible, lambda fight_id: compare_url(code, selected, name, fight_id))
    body = head + f"""
        {intro}
        {compare.top_players(data)}
    </div>
    <div class="card"><h2>📋 Summary</h2>{summary}</div>
    <div class="card"><h2>🕒 Timeline</h2>{timeline}</div>"""
    return _page(f'{name} vs top players · {boss_name}', session, body)


# ============================================================================
# GET /admin/raids/boss/{encounter_id}/{difficulty} - progression + tagging
# ============================================================================

async def handle_boss(request):
    session = _session(request)
    try:
        encounter_id = int(request.match_info['encounter_id'])
        difficulty = int(request.match_info['difficulty'])
    except ValueError:
        raise web.HTTPNotFound()
    team = _team(request)
    base = f'/admin/raids/boss/{encounter_id}/{difficulty}'
    pulls = db.get_boss_pulls(encounter_id, difficulty, with_analysis=True, team=team)
    if not pulls:
        if team:
            # to all teams explicitly: the bare URL means the default team again
            raise web.HTTPFound(base + _team_query(None) + '&error=' + quote(f'No {teams.label(team)} pulls on that boss yet.'))
        raise web.HTTPFound('/admin/raids?error=' + quote('No pulls for that boss yet.'))
    tags, sources = _effective_tags(encounter_id)
    guide_for = _guide_lookup(encounter_id)
    name = pulls[-1]['encounter_name']
    here = base + _team_query(team)

    # Nights (most recent first in the table, chronological in the chart)
    nights = {}
    for pull in pulls:
        nights.setdefault(pull['report_code'], []).append(pull)
    try:
        last_n = int(request.query.get('nights') or 0)
    except ValueError:
        last_n = 0
    scope_codes = list(nights)[-last_n:] if last_n else list(nights)
    scoped = [p for p in pulls if p['report_code'] in scope_codes]
    analyses = [_with_duration(p) for p in scoped]

    points, separators, number = [], [], 0
    for code, night in nights.items():
        separators.append((number, _short_date(night[0]['report_start'])))
        for pull in night:
            number += 1
            points.append({'pct': pull['fight_pct'], 'kill': pull['kill'],
                           'href': f"/admin/raids/report/{code}/{pull['fight_id']}",
                           'tip': f"Pull {number} ({_short_date(night[0]['report_start'])}): "
                                  f"{_result_text(pull)}"})

    # Per-night analysis: wipe causes, phase progress, player reports (for trends)
    phase_meta = (pulls[-1]['phase_names'] or {}).get(str(encounter_id)) or {}
    night_data = _night_data(nights, encounter_id, tags, guide_for)

    night_rows = []
    best_before = 100.0
    for nd in night_data:
        code, night = nd['code'], nd['pulls']
        best = min((p['fight_pct'] or 0 for p in night if not p['kill']), default=None)
        killed = any(p['kill'] for p in night)
        improved = best is not None and best < best_before
        causes = {}
        for p in nd['insight_pulls']:
            if p['reason']:
                causes[p['reason']['code']] = causes.get(p['reason']['code'], 0) + 1
        main_cause = max(causes.items(), key=lambda kv: kv[1]) if causes else None
        cause_html = (f'{esc(insights.CAUSE_TITLES.get(main_cause[0], main_cause[0]))} '
                      f'<span class="muted small">({main_cause[1]}/{len(night)})</span>' if main_cause else '')
        night_rows.append(f"""
            <tr>
                <td>{ts(night[0]['report_start'], 'date')}</td>
                <td><a href="/admin/raids/report/{esc(code)}?boss={encounter_id}-{difficulty}" style="color:#fff">
                    {esc(night[0]['report_title'])}</a></td>
                <td class="num">{len(night)}</td>
                <td class="num">{fmt_duration(sum(p['end_ms'] - p['start_ms'] for p in night))}</td>
                <td>{'<span class="pill pill-kill">✔ Kill</span>' if killed else
                     (f'{best:.1f}%' + (' <span class="small good">▼ new best</span>' if improved else '')
                      if best is not None else '')}</td>
                <td class="small">{cause_html}</td>
            </tr>""")
        if best is not None:
            best_before = min(best_before, best)

    # How far each night got, phase by phase
    heat_nights, phase_ids = [], set()
    for nd in night_data:
        progress = analyzer.phase_progress(
            [{'phases': p.get('phases'), 'duration': p['end_ms'] - p['start_ms']} for p in nd['pulls']], phase_meta)
        phase_ids |= {ph['id'] for ph in progress}
        heat_nights.append((esc(nd['label']), {ph['id']: ph['reached'] for ph in progress}, len(nd['pulls'])))
    phase_order = [(pid, (phase_meta.get(str(pid)) or {}).get('name') or f'Phase {pid}') for pid in sorted(phase_ids)]
    heat_html = (f'<h3 style="margin-top:20px">How far we got, night by night</h3>'
                 f'<p class="muted small">Pulls that reached each phase; darker = more of the night\'s pulls got there.</p>'
                 f'{phase_heatmap(list(reversed(heat_nights)), phase_order)}' if len(phase_order) > 1 else '')
    trends_html = _player_trends(night_data, encounter_id, difficulty, team)
    comparison_html = await _progstats_card(encounter_id, pulls) if difficulty == progstats.MYTHIC else ''

    # Mechanics seen on this boss, with tagging
    mechanics = {}
    for analysis in [a for a in (p.get('analysis') for p in pulls) if a]:
        raid = max(1, len(analysis.get('players') or []))
        for a in analysis.get('abilities') or []:
            m = mechanics.setdefault(a['id'], {'name': a['name'], 'icon': a.get('icon'), 'source': a.get('source'),
                                               'pulls': 0, 'damage': 0, 'hits': 0, 'share': 0.0, 'complete': True})
            m['pulls'] += 1
            m['damage'] += a['total']
            m['share'] += len(a.get('players') or {}) / raid
            m['complete'] = m['complete'] and a.get('complete')
            m['hits'] += sum(analyzer.mistake_counts(a).values())
    # Anything Mythic Trap or an officer already decided on isn't up for suggestion.
    suggested = {s['id'] for s in analyzer.suggest_avoidable(
        [p['analysis'] for p in pulls if p.get('analysis')], set(tags) | set(sources))}
    order = {analyzer.TAG_AVOIDABLE: 0, analyzer.TAG_AVOIDABLE_NON_TANK: 0, None: 1,
             guides.EXPECTED: 2, analyzer.TAG_IGNORE: 3}
    mech_rows = []
    for ability_id, m in sorted(mechanics.items(),
                                key=lambda kv: (order.get(tags.get(kv[0]), 1), kv[0] not in suggested, -kv[1]['damage'])):
        tag = tags.get(ability_id)
        pill = tag_pill(tag, sources.get(ability_id)) or (
            '<span class="pill pill-suggest" title="Only ever hits a few players at a time">suggested</span>'
            if ability_id in suggested else '')
        mech_rows.append(f"""
            <tr>
                <td>{ability(m['name'], m['icon'], ability_id, guide_for(ability_id, m['name']))} {pill}</td>
                <td class="small muted">{esc(m['source'] or '')}</td>
                <td class="num">{m['pulls']}</td>
                <td class="num" data-v="{m['share'] / m['pulls']:.3f}">{100 * m['share'] / m['pulls']:.0f}%{'' if m['complete'] else '+'}</td>
                <td class="num">{m['hits'] if m['complete'] else '<span class="muted">—</span>'}</td>
                <td class="num" data-v="{m['damage']}">{fmt_amount(m['damage'])}</td>
                <td>{tag_buttons(encounter_id, difficulty, ability_id, m['name'], tag, sources.get(ability_id),
                                 here + '#mechanics')}</td>
            </tr>""")

    team_links = '<span class="chips-label">Team</span>' + ''.join(
        f'<a class="pull-chip{" active" if key == team else ""}" href="{base}{_team_query(key, nights=last_n or None, pick=1)}">'
        f'{esc(teams.label(key) if key else "All teams")}</a>'
        for key in [None] + [k for k, _ in teams.options()])
    scope_links = '<span class="chips-label">Nights</span>' + ''.join(
        f'<a class="pull-chip{" active" if n == last_n else ""}" href="{base}{_team_query(team, nights=n or None)}">'
        f'{label}</a>'
        for n, label in ((1, 'Last night'), (3, 'Last 3 nights'), (0, 'All nights')) if n <= len(nights))

    kills = sum(1 for p in pulls if p['kill'])
    best_all = min((p['fight_pct'] or 0 for p in pulls if not p['kill']), default=None)
    body = f"""
    <div class="card">
        <p><a href="/admin/raids{_team_query(team)}">← Raid Analysis</a></p>
        <h1>{boss_portrait(encounter_id, 'lg', killed=any(p['kill'] for p in pulls))}{esc(name)} {difficulty_pill(difficulty)}</h1>
        <div class="pull-chips">{team_links}</div>
        {_flash(request)}
        <div class="stats">
            <div class="stat"><div class="stat-value">{len(pulls)}</div><div class="stat-label">Pulls</div></div>
            <div class="stat"><div class="stat-value">{len(nights)}</div><div class="stat-label">Nights</div></div>
            <div class="stat"><div class="stat-value">{kills or (f'{best_all:.1f}%' if best_all is not None else '—')}</div>
                <div class="stat-label">{'Kills' if kills else 'Best pull'}</div></div>
            <div class="stat"><div class="stat-value">{fmt_duration(sum(p['end_ms'] - p['start_ms'] for p in pulls))}</div>
                <div class="stat-label">Time on boss</div></div>
        </div>
        <h2 style="margin-top:24px">📈 Progression</h2>
        {progress_chart(points, separators=separators if len(nights) > 1 else ())}
        <div class="table-wrapper"><table class="compact">
            <tr><th>Date</th><th>Report</th><th class="num">Pulls</th><th class="num">Time</th><th>Result</th>
                <th>Main wipe cause</th></tr>
            {''.join(reversed(night_rows))}
        </table></div>
        {heat_html}
    </div>
    {comparison_html}
    {trends_html}
    <div class="card">
        <h2>👥 Players</h2>
        <div class="pull-chips" style="margin:-4px 0 10px">{scope_links}</div>
        <p class="muted small">{len(scoped)} pulls. Deaths count only as early deaths by mistake: one of a pull's first 4 deaths, and not part of a mass death.</p>
        <div class="grid-2" style="margin-bottom:20px">
            <div><h3>💀 What's killing us</h3>{killers_table(analyzer.killers(analyses), guide_for=guide_for)}</div>
            <div><h3>🧪 Avoidable damage by mechanic</h3>{_avoidable_summary(analyses, tags, guide_for)}</div>
        </div>
        {scoreboard_table(analyzer.scoreboard(analyses, tags), show_avoidable=_has_avoidable(tags))}
    </div>
    {_guides_card(encounter_id, difficulty, base)}
    <div class="card" id="mechanics">
        <h2>🎯 Mechanics</h2>
        <p class="muted small">Every enemy ability that hit the raid on this boss. Tags marked <em>auto</em> come
           from the boss's Mythic Trap guide ("Dodge…" → avoidable, frontals and tail swipes → non-tanks, soaks and
           tankbusters → expected); anything that lands on ~90% of the raid every pull is never auto-blamed.
           Clicking a tag overrides it for this boss; <strong>↺ auto</strong> undoes that.
           <strong>Avoidable</strong> = any hit is a mistake; <strong>Non-tanks</strong> = the same, except tanks
           are meant to take it. Only direct hits count, not damage-over-time ticks — except for auras and pools
           that only ever tick. <span class="pill pill-suggest">suggested</span> = not in the guide, but it only
           ever hits a few players at a time.
           <span class="admin-only">Newly tagged raid-wide abilities need a <em>Re-analyze</em> of a night to get
           per-player hits.</span></p>
        <div class="table-wrapper"><table class="compact">
            <tr><th data-sort>Ability</th><th>Source</th><th data-sort class="num">Pulls seen</th>
                <th data-sort class="num" title="Average share of the raid hit per pull">Raid hit</th>
                <th data-sort class="num">Hits</th><th data-sort class="num">Damage</th><th>Tag</th></tr>
            {''.join(mech_rows)}
        </table></div>
    </div>"""
    return _remember_team(request, _page(name, session, body))


def _guides_card(encounter_id, difficulty, here):
    """The boss's Mythic Trap ability list (clips + tips) and scan status."""
    scan = db.get_guide_scan(encounter_id)
    boss_guides = db.get_guides(encounter_id)
    rescan = (f'<form method="post" action="{here}/guides" class="inline-form">'
              f'<button class="btn btn-secondary btn-sm">🔎 {"Rescan" if scan else "Look up"} Mythic Trap</button></form>')
    if not scan:
        status = 'Not looked up yet — happens automatically on the next sync.'
    elif scan['status'] == 'not_found':
        status = f"No Mythic Trap page found for this boss (checked {ts(scan['scanned_at'].timestamp() * 1000)})."
    elif scan['status'] == 'error':
        status = f"Last lookup failed: {esc(scan['error'])}"
    else:
        clips = sum(1 for g in boss_guides if g['video_url'])
        status = (f"{clips} clips for {len(boss_guides)} abilities from "
                  f"<a href=\"{esc(scan['page_url'])}\" target=\"_blank\" rel=\"noopener\">Mythic Trap ↗</a> · "
                  f"updated {ts(scan['scanned_at'].timestamp() * 1000)} · refreshed every few days")
    items = ''.join(
        f'<tr><td>{esc(g["name"])}{guide_button(g)}</td>'
        f'<td class="small muted">{esc(g["subtitle"])}</td><td class="small">{esc(g["category"])}</td>'
        f'<td class="small">{esc(g["tip"] or g["description"])}</td></tr>'
        for g in sorted(boss_guides, key=lambda g: (not g['video_url'], g['name'])))
    table = (f'<div class="table-wrapper" style="margin-top:12px"><table class="compact">'
             f'<tr><th>Ability</th><th>Type</th><th>What to do</th><th>Tip</th></tr>{items}</table></div>'
             if items else '')
    return f"""
    <div class="card" id="guides">
        <h2>📺 Mechanic guides</h2>
        <p class="muted small">{status}</p>
        {rescan}
        {table}
    </div>"""


async def handle_rescan_guides(request):
    _session(request)
    encounter_id = int(request.match_info['encounter_id'])
    back = f"/admin/raids/boss/{encounter_id}/{request.match_info['difficulty']}"
    await guides.scan_missing(encounter_ids=[encounter_id])
    raise web.HTTPFound(back + '?msg=' + quote('Mythic Trap guide refreshed.') + '#guides')


async def _progstats_card(encounter_id, pulls):
    """Our Mythic pull count next to every guild that killed the boss (progstats.io)."""
    stats = await progstats.mythic_pull_stats(encounter_id)
    if not stats:
        return ('<div class="card"><h2>📊 Pull count vs other guilds</h2><p class="muted">No Mythic kill data on '
                '<a href="https://progstats.io" target="_blank" rel="noopener">progstats.io</a> for this boss yet.</p></div>')
    kill_at = next((i for i, p in enumerate(pulls, 1) if p['kill']), None)
    ours = kill_at or len(pulls)
    share = progstats.share_needing_more(stats['bins'], ours)
    if kill_at:
        verdict = f'You killed it in <strong>{ours} pulls</strong> — fewer than <strong>{share:.0%}</strong> of guilds needed.'
    else:
        verdict = (f"You're at <strong>{ours} pulls</strong> without a kill — <strong>{share:.0%}</strong> of the guilds "
                   f"that killed it needed more than that.")
    return f"""
    <div class="card">
        <h2>📊 Pull count vs other guilds</h2>
        <p>{verdict}</p>
        <p class="muted small">{stats['kills']} guilds have killed it on Mythic · median <strong>{stats['median']:.0f}</strong>
           pulls · middle half {stats['p25']:.0f}–{stats['p75']:.0f}. Your count only includes the nights synced here.</p>
        {pull_histogram(stats['bins'], ours, bool(kill_at))}
        <p class="muted small">Data: <a href="https://progstats.io" target="_blank" rel="noopener">progstats.io</a>
           (Mythic only, refreshed daily).</p>
    </div>"""


def _trend_url(encounter_id, difficulty, name, team=None):
    return f'/admin/raids/boss/{encounter_id}/{difficulty}/player/{quote(name)}{_team_query(team)}'


def _player_trends(night_data, encounter_id, difficulty, team=None):
    return players.trends_card(night_data, lambda key: _trend_url(encounter_id, difficulty, key, team),
                               db.character_owners())


def _boss_night_data(encounter_id, difficulty, tags, guide_for, team=None):
    """Per-night pulls and player reports for one boss (one team's, or all teams'), oldest night first."""
    nights = {}
    for pull in db.get_boss_pulls(encounter_id, difficulty, with_analysis=True, team=team):
        nights.setdefault(pull['report_code'], []).append(pull)
    return _night_data(nights, encounter_id, tags, guide_for)


def _night_data(nights, encounter_id, tags, guide_for):
    """{report_code: [pulls]} -> [{'code', 'pulls', 'insight_pulls', 'label', 'players'}] in night order."""
    enrage_ids = _enrage_ids(encounter_id, guide_for)
    out = []
    for code, night in nights.items():
        night_pulls = _insight_pulls(list(enumerate(night, 1)), enrage_ids)
        out.append({'code': code, 'pulls': night, 'insight_pulls': night_pulls,
                    'label': _short_date(night[0]['report_start']),
                    'players': analyzer.player_report(night_pulls, tags)})
    return out


async def handle_player_trend(request):
    """GET /admin/raids/boss/{encounter_id}/{difficulty}/player/{name} - one player across nights."""
    session = _session(request)
    try:
        encounter_id = int(request.match_info['encounter_id'])
        difficulty = int(request.match_info['difficulty'])
    except ValueError:
        raise web.HTTPNotFound()
    name = request.match_info['name']
    tags, _ = _effective_tags(encounter_id)
    guide_for = _guide_lookup(encounter_id)
    team = _team(request)
    night_data = _boss_night_data(encounter_id, difficulty, tags, guide_for, team)
    owners = db.character_owners()
    history = players.player_history(night_data, owners)
    # The link carries a person key; a plain character name (e.g. from a night's player page) works too.
    entry = history.get(name) or history.get(players.person_key(name, owners))
    back = f'/admin/raids/boss/{encounter_id}/{difficulty}{_team_query(team)}'
    if not entry:
        raise web.HTTPFound(back + '?error=' + quote(f'No pulls for {name} on this boss.'))
    boss_name = night_data[-1]['pulls'][0]['encounter_name']
    title = entry.get('display') or entry['characters'][-1]
    body = (f'<div class="card"><p><a href="{back}">← {esc(boss_name)} {difficulty_pill(difficulty)}</a></p>'
            f'<h1>{esc(title)} on {esc(boss_name)}</h1></div>'
            + players.trend_page(entry, guide_for,
                                 lambda code, player: players.player_url(code, player, (encounter_id, difficulty))))
    return _remember_team(request, _page(f'{title} · {boss_name} trend', session, body))


def _short_date(epoch_ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).strftime('%d %b')


# ============================================================================
# POST /admin/raids/boss/{encounter_id}/{difficulty}/tag
# ============================================================================

async def handle_tag(request):
    session = _session(request)
    data = await request.post()
    encounter_id = int(request.match_info['encounter_id'])
    back = data.get('back') or f"/admin/raids/boss/{encounter_id}/{request.match_info['difficulty']}"
    if not back.startswith('/admin/raids'):
        back = '/admin/raids'
    try:
        ability_id = int(data['ability_id'])
    except (KeyError, ValueError):
        raise web.HTTPFound(back)
    db.set_tag(encounter_id, ability_id, data.get('ability_name') or '', data.get('tag') or '',
               session.get('username'))
    raise web.HTTPFound(back)
