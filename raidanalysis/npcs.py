"""
Portraits for enemies (adds, bosses) on the timelines. NPCs have no icon in the game files - only a 3D
model - so Wowhead's tooltip API gives just a name for them (and its NPC pages turn scripts away).
Blizzard's Game Data API has a render per model: creature (the log's actors' gameID) -> its first
display -> that display's "zoom" image, a head shot. Looked up in the background the first time a page
shows the enemy (ensure()), cached for good in raid_npcs by name; a miss is kept as NULL (retried daily).
"""
import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

REGION = os.getenv('BLIZZARD_REGION', 'eu')
API = f'https://{REGION}.api.blizzard.com'
NAMESPACE = f'static-{REGION}'
PER_RUN = 20

_token = {'value': None, 'expires': 0}
_in_flight = set()
_tasks = set()  # running fills, kept so they aren't garbage collected mid-way


def icons(names):
    """{name: portrait url} for the enemies with one cached (no lookups here)."""
    from . import db
    try:
        return {n: url for n, url in db.get_npcs(sorted(set(names))).items() if url}
    except Exception:
        logger.exception('[RAIDS] Reading NPC portraits failed')
        return {}


def ensure(code, names):
    """Look up the portraits of these enemies (from report `code`'s actors) not cached yet, in the background."""
    from . import db
    if not os.getenv('BLIZZARD_CLIENT_ID') or not os.getenv('BLIZZARD_CLIENT_SECRET'):
        return
    try:
        known = db.get_npcs(sorted(set(names)))
    except Exception:
        return
    missing = [n for n in set(names) if n and n not in known and n not in _in_flight][:PER_RUN]
    if not missing:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # not in the web server's loop (tests, scripts): the next page view does it
    _in_flight.update(missing)
    task = loop.create_task(fill(code, missing))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def fill(code, names):
    import aiohttp
    from . import db, wcl
    try:
        async with aiohttp.ClientSession() as session:
            actors = await wcl.get_report_actors(session, code)
            ids = {}
            for a in actors:
                if a.get('type') not in ('Player', 'Pet') and a.get('gameID') and a['name'] not in ids:
                    ids[a['name']] = a['gameID']
            token = await _get_token(session)
            if not token:
                return
            for name in names:
                game_id = ids.get(name)
                url = await _portrait(session, token, game_id) if game_id else None
                db.save_npc(name, game_id, url, 'ok' if url else 'missing')
    except Exception:
        logger.exception('[RAIDS] NPC portraits for %s failed', code)
    finally:
        _in_flight.difference_update(names)


async def _get_token(session):
    import aiohttp
    if _token['value'] and _token['expires'] > time.time():
        return _token['value']
    auth = aiohttp.BasicAuth(os.getenv('BLIZZARD_CLIENT_ID'), os.getenv('BLIZZARD_CLIENT_SECRET'))
    async with session.post('https://oauth.battle.net/token', data={'grant_type': 'client_credentials'}, auth=auth,
                            timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            logger.warning('[RAIDS] Blizzard token for NPC portraits: HTTP %s', resp.status)
            return None
        data = await resp.json()
    _token.update(value=data['access_token'], expires=time.time() + data.get('expires_in', 3600) - 60)
    return _token['value']


async def _get(session, token, path):
    import aiohttp
    async with session.get(f'{API}{path}', params={'namespace': NAMESPACE, 'locale': 'en_US'},
                           headers={'Authorization': f'Bearer {token}'},
                           timeout=aiohttp.ClientTimeout(total=10)) as resp:
        return await resp.json() if resp.status == 200 else None


async def _portrait(session, token, game_id):
    """The creature's "zoom" render URL, or None."""
    creature = await _get(session, token, f'/data/wow/creature/{int(game_id)}')
    displays = (creature or {}).get('creature_displays') or []
    if not displays:
        return None
    media = await _get(session, token, f'/data/wow/media/creature-display/{int(displays[0]["id"])}')
    assets = {a.get('key'): a.get('value') for a in (media or {}).get('assets') or []}
    return assets.get('zoom') or next(iter(assets.values()), None)
