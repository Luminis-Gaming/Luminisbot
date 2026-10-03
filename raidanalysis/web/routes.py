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

from .. import analyzer, db, guides, sync
from . import consumables, insights, players
from .render import (CLIP_MODAL, PAGE_CSS, PAGE_JS, ability, deaths_strip, difficulty_pill, phase_funnel,
                     phase_heatmap, esc, fmt_amount, fmt_duration,
                     guide_button, killers_table, phase_label, player_name, progress_chart, pull_timeline,
                     result_pill, scoreboard_table, sync_banner, tag_buttons, tag_pill, ts)

logger = logging.getLogger(__name__)

REPORT_CODE_RE = re.compile(r'(?:reports/)?([A-Za-z0-9]{16})\b')


def register_routes(app):
    app.router.add_get('/admin/raids', handle_overview)
    app.router.add_post('/admin/raids/sync', handle_sync)
    app.router.add_get('/admin/raids/sync/status', handle_sync_status)
    app.router.add_get('/admin/raids/report/{code}', handle_night)
    app.router.add_get('/admin/raids/report/{code}/{fight_id}', handle_pull)
    app.router.add_get('/admin/raids/report/{code}/player/{name}', handle_player)
    app.router.add_get('/admin/raids/boss/{encounter_id}/{difficulty}', handle_boss)
    app.router.add_post('/admin/raids/boss/{encounter_id}/{difficulty}/tag', handle_tag)
    app.router.add_get('/admin/raids/boss/{encounter_id}/{difficulty}/player/{name}', handle_player_trend)
    app.router.add_post('/admin/raids/boss/{encounter_id}/{difficulty}/guides', handle_rescan_guides)
    logger.info("[RAIDS] Admin web routes registered")


def _session(request):
    from oauth_server import get_session
    session = get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')
    return session


def _page(title, session, body, waiting=False):
    from oauth_server import ADMIN_CSS, render_nav
    body = sync_banner(sync.status, waiting) + body
    return web.Response(text=f"""<!DOCTYPE html>
<html>
<head>
    <title>LuminisBot Admin - {esc(title)}</title>
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


def _flash(request):
    out = ''
    if request.query.get('msg'):
        out += f'<p class="success">✅ {esc(request.query["msg"])}</p>'
    if request.query.get('error'):
        out += f'<p class="error">❌ {esc(request.query["error"])}</p>'
    return out


def _with_duration(pull):
    """The pull's analysis plus its duration, as analyzer.scoreboard expects."""
    analysis = dict(pull.get('analysis') or {})
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

async def handle_overview(request):
    session = _session(request)
    reports = db.list_reports(limit=40)
    bosses = db.list_bosses()

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

    boss_rows = ''.join(f"""
        <tr onclick="location='/admin/raids/boss/{b['encounter_id']}/{b['difficulty']}'" style="cursor:pointer">
            <td><a href="/admin/raids/boss/{b['encounter_id']}/{b['difficulty']}" style="color:#fff">
                <strong>{esc(b['name'])}</strong></a></td>
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
        {_flash(request)}
        <p class="muted">Every raid pull from the guild's Warcraft Logs and from the logs attached to raid
           events, analyzed for deaths, mechanics, interrupts, dispels and consumables.</p>
        {sync_state}
        <form method="post" action="/admin/raids/sync" class="inline-form">
            <label class="small muted">Latest reports</label>
            <input type="number" name="limit" value="10" min="1" max="50" style="width:80px">
            <input type="text" name="code" placeholder="…or a WCL report URL / code to import" style="min-width:320px">
            <button class="btn btn-primary btn-sm" {'disabled' if st['running'] else ''}>🔄 Sync now</button>
        </form>
    </div>
    <div class="card">
        <h2>🐉 Bosses</h2>
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
    return _page("Raid Analysis", session, body)


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
    # Mark it running now, so the page we redirect to already shows (and polls) the progress banner.
    sync.status.update(running=True, current='Starting sync…')
    asyncio.create_task(sync.sync_guild(limit=limit, force_codes=codes))

    if codes:  # importing / re-analyzing one report: go watch it fill in
        raise web.HTTPFound(f'/admin/raids/report/{codes[0]}')
    back = data.get('back') or '/admin/raids'
    if not back.startswith('/admin/raids'):
        back = '/admin/raids'
    raise web.HTTPFound(back)


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
                    f'{"&view=players" if players_q else ""}">'
                    f'<strong>{esc(boss_pulls[0]["encounter_name"])}</strong> {difficulty_pill(difficulty)}'
                    f'<small>{_plural(len(boss_pulls), "pull")} · {state}</small></a>')

    boss_pulls = groups[selected]
    overall_href = f'/admin/raids/report/{esc(code)}?boss={selected[0]}-{selected[1]}'
    chips = [f'<a class="pull-chip overall{" active" if fight_id is None else ""}" '
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
        f'<a class="view-tab{" active" if view == key else ""}" href="{here_base}view={key}">{label}</a>'
        for key, label in (('mechanics', '📋 Mechanics'), ('players', '👥 Players')))

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


def _mechanics_table(analysis, tags, sources, guide_for, pname, encounter_id, difficulty, here):
    """Damage taken per enemy ability (one pull, or several merged), with tag buttons."""
    raid_size = max(1, len(analysis.get('players') or []))
    shown, ignored = [], []
    for a in analysis.get('abilities') or []:
        tag = tags.get(a['id'])
        counts = analyzer.mistake_counts(a)
        players = sorted((a.get('players') or {}).items(),
                         key=lambda kv: -(counts.get(kv[0], 0) * 1e12 + (kv[1].get('damage') or 0)))
        who = ', '.join(f'{pname(n)}' + (f' ×{counts[n]}' if counts.get(n) else '') for n, _ in players[:8])
        if len(players) > 8:
            who += f' <span class="muted">+{len(players) - 8} more</span>'
        hits = sum(counts.values()) if a.get('complete') else None
        row = f"""
            <tr>
                <td>{ability(a['name'], a.get('icon'), a['id'], guide_for(a['id'], a['name']))}
                    {tag_pill(tag, sources.get(a['id'])) if tag != analyzer.TAG_IGNORE else ''}</td>
                <td class="small muted">{esc(a.get('source') or '')}</td>
                <td class="num" data-v="{a['total']}">{fmt_amount(a['total'])}</td>
                <td class="num" data-v="{len(players)}">{len(players) if a.get('complete') else '5+'}/{raid_size}</td>
                <td class="num">{hits if hits is not None else '<span class="muted" title="Raid-wide ability — only the top 5 targets are known">—</span>'}</td>
                <td class="small">{who}</td>
                <td>{tag_buttons(encounter_id, difficulty, a['id'], a['name'], tag, sources.get(a['id']), here)}</td>
            </tr>"""
        (ignored if tag == analyzer.TAG_IGNORE else shown).append(row)
    head = ('<tr><th data-sort>Ability</th><th>Source</th><th data-sort class="num">Damage</th>'
            '<th data-sort class="num">Players hit</th><th data-sort class="num">Hits</th><th>Who</th>'
            '<th>Tag</th></tr>')
    ignored_html = (f'<details style="margin-top:10px"><summary class="muted">{len(ignored)} ignored '
                    f'abilit{"y" if len(ignored) == 1 else "ies"}</summary><div class="table-wrapper">'
                    f'<table class="compact">{head}{"".join(ignored)}</table></div></details>') if ignored else ''
    return (f'<div class="table-wrapper"><table class="compact">{head}{"".join(shown)}</table></div>'
            f'{ignored_html}')


def _roster_names(analysis):
    roster = {p['name']: p for p in analysis.get('players') or []}

    def pname(name):
        p = roster.get(name, {})
        return player_name(name, p.get('class', ''), p.get('role'))
    return pname


def _consumables_card(insight_pulls, roster):
    """WCL-style timeline: enemy casts on top, every player's potions / healthstones / deaths below."""
    analyses = [p['analysis'] for p in insight_pulls]
    if not consumables.has_details(analyses):
        return ('<div class="card"><h2>🧪 Consumables timeline</h2>' + insights.REANALYZE_HINT + '</div>')
    single = len(insight_pulls) == 1
    hint = ('Enemy casts on top; each player\'s potions (bar = buff duration), healthstones / healing potions '
            '(diamonds) and deaths underneath. Hover anything for details.' if single else
            'Every potion and healthstone from every pull on one axis — clusters show each player\'s habits '
            '(e.g. always potting at the pull and again around 5:00). Open a single pull for the exact timeline '
            'with boss abilities.')
    return (f'<div class="card"><h2>🧪 Consumables timeline</h2><p class="muted small">{hint}</p>'
            f'{consumables.timeline(insight_pulls, roster)}</div>')


def _insight_pulls(numbered, enrage_ids=()):
    return [{'number': number, 'kill': pull['kill'], 'analysis': _with_duration(pull),
             'fight_id': pull['fight_id'], 'reason': _pull_reason(pull, enrage_ids),
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
            <a href="/admin/raids/boss/{encounter_id}/{difficulty}" class="btn btn-secondary btn-sm"
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
                <th data-sort class="num" title="When half the raid was dead - later deaths don't count against anyone">Wipe called</th>
                <th data-sort>Why it ended</th>
                <th data-sort class="num" title="Hits from avoidable mechanics">Avoidable</th><th></th></tr>
            {rows}
        </table></div>
    </div>
    <div class="card">
        <h2>📋 Mechanics</h2>
        {insights.build(insight_pulls, tags, guide_for, code)}
    </div>
    {_consumables_card(insight_pulls, merged['players'])}
    <div class="card">
        <h2>💀 Deaths in every pull</h2>
        <p class="muted small">One row per pull, along its own length: red ticks are deaths, grey ones came after
           the wipe was called (dashed yellow), thin lines are phase changes. Click a row to open that pull.</p>
        {deaths_strip(insights.death_strip_rows(code, numbered))}
    </div>
    <div class="card">
        <h2>🎯 Damage taken by mechanic — all pulls</h2>
        {_mechanics_table(merged, tags, sources, guide_for, _roster_names(merged), encounter_id, difficulty, here)}
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

    analysis = pull['analysis'] or {}
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
        f'<tr{" class=muted" if d.get("after_wipe") else ""}><td class="num">{fmt_duration(d["t"])}</td>'
        f'<td>{pname(d["name"])}</td>'
        f'<td>{"<span class=muted>likely</span> " if d.get("likely") else ""}'
        f'{ability(d["ability"], d.get("icon"), d.get("ability_id"), guide_for(d.get("ability_id"), d["ability"]))}</td>'
        f'<td class="small">{"after wipe called" if d.get("after_wipe") else ""}</td></tr>'
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
        <p class="muted small">Red ticks are deaths (hover for details); grey ones came after the wipe was called
           (half the raid dead) and don't count against anyone.</p>
    </div>
    <div class="card">
        <h2>📋 Mechanics</h2>
        {insights.build(pull_insights, tags, guide_for, code)}
    </div>
    {_consumables_card(pull_insights, analysis.get('players') or [])}
    <div class="card">
        <h2>💀 Deaths</h2>
        <div class="table-wrapper"><table class="compact"><tr><th class="num">Time</th><th>Player</th>
            <th>Killing blow</th><th></th></tr>
        {death_rows or '<tr><td colspan="4" class="muted">Nobody died.</td></tr>'}</table></div>
    </div>
    <div class="card">
        <h2>🎯 Damage taken by mechanic</h2>
        <p class="muted small">Tags marked <em>auto</em> come from the boss's Mythic Trap guide; clicking a tag
           overrides it for this boss on every night. Raid-wide abilities only show their top 5 targets.</p>
        {_mechanics_table(analysis, tags, sources, guide_for, pname, encounter_id, difficulty, here)}
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
    body = (_night_header(request, report, code, pulls, selected, fight_id, view='players')
            + players.player_page(player, guide_for,
                                  lambda number: f'/admin/raids/report/{code}/{fights[number]}'))
    return _page(f"{name} · {groups[selected][0]['encounter_name']}", session, body)


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
    pulls = db.get_boss_pulls(encounter_id, difficulty, with_analysis=True)
    if not pulls:
        raise web.HTTPFound('/admin/raids?error=' + quote('No pulls for that boss yet.'))
    tags, sources = _effective_tags(encounter_id)
    guide_for = _guide_lookup(encounter_id)
    name = pulls[-1]['encounter_name']
    here = f'/admin/raids/boss/{encounter_id}/{difficulty}'

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
    trends_html = _player_trends(night_data, encounter_id, difficulty)

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

    scope_links = ' · '.join(
        f'<a href="{here}{"?nights=" + str(n) if n else ""}" style="color:{"#fff" if n == last_n else "#8b9cff"}">'
        f'{label}</a>'
        for n, label in ((1, 'last night'), (3, 'last 3 nights'), (0, 'all nights')) if n <= len(nights))

    kills = sum(1 for p in pulls if p['kill'])
    best_all = min((p['fight_pct'] or 0 for p in pulls if not p['kill']), default=None)
    body = f"""
    <div class="card">
        <p><a href="/admin/raids">← Raid Analysis</a></p>
        <h1>{esc(name)} {difficulty_pill(difficulty)}</h1>
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
    {trends_html}
    <div class="card">
        <h2>👥 Players — {scope_links}</h2>
        <p class="muted small">{len(scoped)} pulls. Deaths and first deaths only count before the wipe was called.</p>
        <div class="grid-2" style="margin-bottom:20px">
            <div><h3>💀 What's killing us</h3>{killers_table(analyzer.killers(analyses), guide_for=guide_for)}</div>
            <div><h3>🧪 Avoidable damage by mechanic</h3>{_avoidable_summary(analyses, tags, guide_for)}</div>
        </div>
        {scoreboard_table(analyzer.scoreboard(analyses, tags), show_avoidable=_has_avoidable(tags))}
    </div>
    {_guides_card(encounter_id, difficulty, here)}
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
           Newly tagged raid-wide abilities need a <em>Re-analyze</em> of a night to get per-player hits.</p>
        <div class="table-wrapper"><table class="compact">
            <tr><th data-sort>Ability</th><th>Source</th><th data-sort class="num">Pulls seen</th>
                <th data-sort class="num" title="Average share of the raid hit per pull">Raid hit</th>
                <th data-sort class="num">Hits</th><th data-sort class="num">Damage</th><th>Tag</th></tr>
            {''.join(mech_rows)}
        </table></div>
    </div>"""
    return _page(name, session, body)


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


def _trend_url(encounter_id, difficulty, name):
    return f'/admin/raids/boss/{encounter_id}/{difficulty}/player/{quote(name)}'


def _player_trends(night_data, encounter_id, difficulty):
    return players.trends_card(night_data, lambda key: _trend_url(encounter_id, difficulty, key),
                               db.character_owners())


def _boss_night_data(encounter_id, difficulty, tags, guide_for):
    """Per-night pulls and player reports for one boss, oldest night first."""
    nights = {}
    for pull in db.get_boss_pulls(encounter_id, difficulty, with_analysis=True):
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
    night_data = _boss_night_data(encounter_id, difficulty, tags, guide_for)
    owners = db.character_owners()
    history = players.player_history(night_data, owners)
    # The link carries a person key; a plain character name (e.g. from a night's player page) works too.
    entry = history.get(name) or history.get(players.person_key(name, owners))
    back = f'/admin/raids/boss/{encounter_id}/{difficulty}'
    if not entry:
        raise web.HTTPFound(back + '?error=' + quote(f'No pulls for {name} on this boss.'))
    boss_name = night_data[-1]['pulls'][0]['encounter_name']
    title = entry.get('display') or entry['characters'][-1]
    body = (f'<div class="card"><p><a href="{back}">← {esc(boss_name)} {difficulty_pill(difficulty)}</a></p>'
            f'<h1>{esc(title)} on {esc(boss_name)}</h1></div>'
            + players.trend_page(entry, guide_for,
                                 lambda code, player: players.player_url(code, player, (encounter_id, difficulty))))
    return _page(f'{title} · {boss_name} trend', session, body)


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
