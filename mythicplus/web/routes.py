"""
Mythic+ admin web pages: event list, event manage (view/edit roster),
grace-point ledger.

Mounted on the oauth server via register_routes(app), which create_app()
calls at startup — so this module can import oauth_server freely (it is
fully loaded by then) and reuse its session auth, CSS, and nav.
"""
import html
import logging
from urllib.parse import quote

from aiohttp import web

logger = logging.getLogger(__name__)


def register_routes(app):
    app.router.add_get('/admin/mplus', handle_mplus_events_page)
    app.router.add_get('/admin/mplus/grace', handle_mplus_grace_page)
    app.router.add_get('/admin/mplus/{event_id}/manage', handle_mplus_manage_page)
    app.router.add_post('/admin/mplus/{event_id}/manage', handle_mplus_manage_action)
    logger.info("[MPLUS] Admin web routes registered")


def _page(title, session, active, body):
    from oauth_server import ADMIN_CSS, render_nav
    return web.Response(text=f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>LuminisBot Admin - {html.escape(title)}</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>{ADMIN_CSS}
        .status-pill {{ padding: 4px 12px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
        .status-open {{ background: #5865F2; }}
        .status-finalized {{ background: #2ea043; }}
        .status-cancelled {{ background: rgba(255,255,255,0.2); }}
        .group-card {{ background: rgba(255,255,255,0.06); border-radius: 12px; padding: 20px; margin-bottom: 15px; }}
        .inline-form {{ display: inline-flex; gap: 6px; align-items: center; }}
        .inline-form select {{ width: auto; margin: 0; padding: 6px 10px; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="container">
            {render_nav(session, active=active)}
            {body}
        </div>
    </body>
    </html>
    """, content_type='text/html')


def _flash(request):
    msg = request.query.get('msg', '')
    err = request.query.get('error', '')
    out = ''
    if msg:
        out += f'<p class="success">✅ {html.escape(msg)}</p>'
    if err:
        out += f'<p class="error">❌ {html.escape(err)}</p>'
    return out


def _status_pill(status):
    return (f'<span class="status-pill status-{html.escape(status)}">'
            f'{html.escape(status)}</span>')


# ============================================================================
# GET /admin/mplus — event list
# ============================================================================

async def handle_mplus_events_page(request):
    from oauth_server import get_session
    session = get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')

    from .. import db
    from ..constants import format_key_range

    rows = []
    for e in db.admin_list_events():
        keys = format_key_range(e['key_level_min'], e['key_level_max'])
        rows.append(f"""
            <tr>
                <td>{e['id']}</td>
                <td>{html.escape(e['title'])}</td>
                <td>{e['event_date']} {str(e['event_time'])[:5]}</td>
                <td>🔑 {keys}</td>
                <td>{_status_pill(e['status'])}</td>
                <td>{e['player_count']}</td>
                <td>{e['group_count']}</td>
                <td><a class="btn btn-primary btn-sm"
                       href="/admin/mplus/{e['id']}/manage">Manage</a></td>
            </tr>""")

    body = f"""
    <div class="card">
        <h1>🔑 Mythic+ Events</h1>
        {_flash(request)}
        <p><a class="btn btn-secondary btn-sm" href="/admin/mplus/grace">🎟️ Grace point ledger</a></p>
        <div class="table-wrapper">
        <table>
            <tr><th>ID</th><th>Title</th><th>Date</th><th>Keys</th>
                <th>Status</th><th>Players</th><th>Groups</th><th></th></tr>
            {''.join(rows) or '<tr><td colspan="8">No Mythic+ events yet.</td></tr>'}
        </table>
        </div>
    </div>"""
    return _page("Mythic+ Events", session, 'mplus', body)


# ============================================================================
# GET /admin/mplus/{id}/manage — signups, roster, actions
# ============================================================================

async def handle_mplus_manage_page(request):
    from oauth_server import get_session
    session = get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')

    from .. import db
    from ..constants import STATUS_OPEN, format_key_range

    event_id = int(request.match_info['event_id'])
    event = db.get_event(event_id)
    if not event:
        raise web.HTTPFound('/admin/mplus?error=' + quote('Event not found'))

    signups = db.admin_event_signups(event_id)
    groups = db.get_roster(event_id)
    alternates = db.get_alternates(event_id)
    keys = format_key_range(event['key_level_min'], event['key_level_max'])

    # --- Signups table (grouped visually by player) ---
    signup_rows = []
    last_player = None
    for s in signups:
        player = ('' if s['display_name'] == last_player
                  else html.escape(str(s['display_name'])))
        last_player = s['display_name']
        signup_rows.append(f"""
            <tr>
                <td>{player}</td>
                <td>{html.escape(s['character_name'])}-{html.escape(s['realm_slug'])}</td>
                <td>{html.escape(s['character_class'])}</td>
                <td>{html.escape(s['spec'] or '—')} ({html.escape(s['role'])})</td>
                <td>{html.escape(s['armor_type'])}</td>
                <td>{int(s['score'] or 0)}</td>
            </tr>""")

    # --- Roster section (finalized events) ---
    roster_html = ''
    if groups:
        group_numbers = [g['group_number'] for g in groups]
        cards = []
        for g in groups:
            member_rows = []
            for m in g['members']:
                move_options = ''.join(
                    f'<option value="{n}">Group {n}</option>'
                    for n in group_numbers if n != g['group_number'])
                sid = next((s['signup_id'] for s in signups
                            if s['character_name'] == m['character_name']
                            and s['realm_slug'] == m['realm_slug']
                            and s['role'] == m['assigned_role']
                            and s['discord_id'] == m['discord_id']), None)
                actions = ''
                if sid is not None:
                    actions = f"""
                        <form method="post" class="inline-form">
                            <input type="hidden" name="action" value="move">
                            <input type="hidden" name="signup_id" value="{sid}">
                            <select name="target_group">{move_options}</select>
                            <button class="btn btn-secondary btn-sm">Move</button>
                        </form>
                        <form method="post" class="inline-form"
                              onsubmit="return confirm('Remove from group?')">
                            <input type="hidden" name="action" value="remove">
                            <input type="hidden" name="signup_id" value="{sid}">
                            <button class="btn btn-danger btn-sm">Remove</button>
                        </form>"""
                member_rows.append(f"""
                    <tr>
                        <td>{html.escape(m['assigned_role'].capitalize())}</td>
                        <td>{html.escape(m['character_name'])}-{html.escape(m['realm_name'])}</td>
                        <td>{html.escape(m['character_class'])}
                            {html.escape(m.get('spec') or '')}</td>
                        <td>{html.escape(m['armor_type'])}</td>
                        <td class="actions">{actions}</td>
                    </tr>""")
            cards.append(f"""
                <div class="group-card">
                    <h2>Group {g['group_number']} — {html.escape(g['armor_type'] or 'mixed')}</h2>
                    <table>{''.join(member_rows)}</table>
                </div>""")

        alt_rows = []
        for a in alternates:
            alt_signups = [s for s in signups if s['discord_id'] == a['discord_id']]
            name = (html.escape(str(alt_signups[0]['display_name']))
                    if alt_signups else html.escape(a['discord_id']))
            signup_options = ''.join(
                f'<option value="{s["signup_id"]}">'
                f'{html.escape(s["character_name"])} — '
                f'{html.escape(s["spec"] or s["role"])} ({s["role"]})</option>'
                for s in alt_signups)
            group_options = ''.join(
                f'<option value="{n}">Group {n}</option>' for n in group_numbers)
            alt_rows.append(f"""
                <tr>
                    <td>{name}</td>
                    <td>{html.escape(a['reason'])}</td>
                    <td>
                        <form method="post" class="inline-form">
                            <input type="hidden" name="action" value="promote">
                            <select name="signup_id">{signup_options}</select>
                            <select name="target_group">{group_options}</select>
                            <button class="btn btn-primary btn-sm">Promote</button>
                        </form>
                    </td>
                </tr>""")
        alternates_html = f"""
            <div class="group-card">
                <h2>🪑 Reserves</h2>
                <table>
                    <tr><th>Player</th><th>Reason</th><th>Promote</th></tr>
                    {''.join(alt_rows) or '<tr><td colspan="3">None</td></tr>'}
                </table>
            </div>""" if alternates or groups else ''
        roster_html = f"""
        <div class="card">
            <h2>📋 Roster</h2>
            <p style="color:rgba(255,255,255,0.6)">Manual changes update the
            Discord embed immediately but never re-run grace accounting.</p>
            {''.join(cards)}
            {alternates_html}
        </div>"""

    # --- Action buttons ---
    action_buttons = []
    if event['status'] == STATUS_OPEN:
        action_buttons.append("""
            <form method="post" class="inline-form"
                  onsubmit="return confirm('Close signups and form groups now?')">
                <input type="hidden" name="action" value="finalize">
                <button class="btn btn-primary">⚡ Close signups &amp; form groups now</button>
            </form>""")
    if event['status'] != 'cancelled':
        action_buttons.append("""
            <form method="post" class="inline-form"
                  onsubmit="return confirm('Cancel this event?')">
                <input type="hidden" name="action" value="cancel">
                <button class="btn btn-danger">🗑️ Cancel event</button>
            </form>""")

    body = f"""
    <div class="card">
        <p><a href="/admin/mplus">← All Mythic+ events</a></p>
        <h1>{html.escape(event['title'])} {_status_pill(event['status'])}</h1>
        {_flash(request)}
        <p>🗓️ {event['event_date']} {str(event['event_time'])[:5]}
           &nbsp;•&nbsp; 🔑 {keys}
           &nbsp;•&nbsp; ⏳ deadline: {event['signup_deadline'] or '—'}</p>
        <div class="actions">{''.join(action_buttons)}</div>
    </div>
    {roster_html}
    <div class="card">
        <h2>✍️ Signups ({len({s['discord_id'] for s in signups})} players,
            {len(signups)} offerings)</h2>
        <div class="table-wrapper">
        <table>
            <tr><th>Player</th><th>Character</th><th>Class</th>
                <th>Spec (role)</th><th>Armor</th><th>RIO</th></tr>
            {''.join(signup_rows) or '<tr><td colspan="6">No signups yet.</td></tr>'}
        </table>
        </div>
    </div>"""
    return _page(f"M+ · {event['title']}", session, 'mplus', body)


# ============================================================================
# POST /admin/mplus/{id}/manage — apply an admin action
# ============================================================================

async def handle_mplus_manage_action(request):
    import oauth_server
    session = oauth_server.get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')

    from .. import db, service
    from ..constants import STATUS_OPEN

    event_id = int(request.match_info['event_id'])
    event = db.get_event(event_id)
    if not event:
        raise web.HTTPFound('/admin/mplus?error=' + quote('Event not found'))

    data = await request.post()
    action = data.get('action', '')
    bot = oauth_server.discord_bot
    error, msg = None, None

    try:
        if action == 'finalize':
            if event['status'] != STATUS_OPEN:
                error = "Event is not open."
            else:
                await service.finalize_event(bot, event_id)
                msg = "Groups formed — roster posted and members notified."
        elif action == 'cancel':
            db.set_event_status(event_id, 'cancelled')
            if bot:
                await service.refresh_event_message(bot, event_id)
            msg = "Event cancelled."
        elif action == 'move':
            error = db.move_group_member(event_id, int(data['signup_id']),
                                         int(data['target_group']))
            msg = None if error else "Player moved."
        elif action == 'remove':
            error = db.remove_group_member(event_id, int(data['signup_id']))
            msg = None if error else "Player moved to reserves."
        elif action == 'promote':
            error = db.promote_alternate(event_id, int(data['signup_id']),
                                         int(data['target_group']))
            msg = None if error else "Reserve promoted."
        else:
            error = "Unknown action."

        # Push the Discord embed update for roster edits
        if msg and action in ('move', 'remove', 'promote') and bot:
            await service.refresh_event_message(bot, event_id)
    except Exception as e:
        logger.error(f"[MPLUS] Admin action '{action}' failed for event "
                     f"{event_id}: {e}")
        error = str(e)

    suffix = f"?msg={quote(msg)}" if msg else f"?error={quote(error or 'Failed')}"
    raise web.HTTPFound(f"/admin/mplus/{event_id}/manage{suffix}")


# ============================================================================
# GET /admin/mplus/grace — grace point ledger
# ============================================================================

async def handle_mplus_grace_page(request):
    from oauth_server import get_session
    session = get_session(request)
    if not session:
        raise web.HTTPFound('/admin/login')

    from .. import db
    points, log = db.grace_overview()

    point_rows = ''.join(f"""
        <tr><td>{html.escape(str(p['display_name']))}</td>
            <td>{p['points']}</td><td>{p['updated_at']:%Y-%m-%d %H:%M}</td></tr>"""
        for p in points)
    log_rows = ''.join(f"""
        <tr><td>{l['created_at']:%Y-%m-%d %H:%M}</td>
            <td>{html.escape(str(l['display_name']))}</td>
            <td>{'+1' if l['delta'] > 0 else 'reset'}</td>
            <td>{html.escape(l['event_title'] or str(l['event_id'] or '—'))}</td>
            <td>{html.escape(l['reason'] or '')}</td></tr>"""
        for l in log)

    body = f"""
    <div class="card">
        <p><a href="/admin/mplus">← All Mythic+ events</a></p>
        <h1>🎟️ Grace Point Ledger</h1>
        <p style="color:rgba(255,255,255,0.6)">Players see only their own
        points in Discord — this page is for dispute resolution.</p>
        <h2>Current points</h2>
        <table>
            <tr><th>Player</th><th>Points</th><th>Updated</th></tr>
            {point_rows or '<tr><td colspan="3">Nobody holds points right now.</td></tr>'}
        </table>
    </div>
    <div class="card">
        <h2>History (latest 200)</h2>
        <div class="table-wrapper">
        <table>
            <tr><th>When</th><th>Player</th><th>Change</th><th>Event</th><th>Reason</th></tr>
            {log_rows or '<tr><td colspan="5">No grace activity yet.</td></tr>'}
        </table>
        </div>
    </div>"""
    return _page("Grace Ledger", session, 'mplus', body)
