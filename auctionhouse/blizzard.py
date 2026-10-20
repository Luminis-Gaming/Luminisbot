"""
The Blizzard API, as the collector uses it: one client-credentials token, retries (the API sometimes cuts a large
auction dump short), and If-Modified-Since so an unchanged auction house costs a 304 instead of 25 MB.
"""
import asyncio
import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)

API = 'https://eu.api.blizzard.com'
DYNAMIC = 'dynamic-eu'
STATIC = 'static-eu'
TOKEN_URL = 'https://oauth.battle.net/token'
RETRIES = 4


class Blizzard:
    def __init__(self, session):
        self.session = session
        self._token = None
        self._expires = 0.0

    async def token(self):
        if self._token and time.time() < self._expires:
            return self._token
        auth = aiohttp.BasicAuth(os.getenv('BLIZZARD_CLIENT_ID', ''), os.getenv('BLIZZARD_CLIENT_SECRET', ''))
        async with self.session.post(TOKEN_URL, data={'grant_type': 'client_credentials'}, auth=auth) as resp:
            if resp.status != 200:
                raise RuntimeError(f'Blizzard token: HTTP {resp.status}')
            data = await resp.json()
        self._token = data['access_token']
        self._expires = time.time() + data.get('expires_in', 3600) - 120
        return self._token

    async def get(self, path, namespace, since=None):
        """-> (status, body bytes or None, Last-Modified or None). 304 when unchanged since `since`."""
        last_error = None
        for attempt in range(RETRIES):
            headers = {'Authorization': f'Bearer {await self.token()}'}
            if since:
                headers['If-Modified-Since'] = since
            try:
                async with self.session.get(API + path, params={'namespace': namespace, 'locale': 'en_GB'},
                                            headers=headers) as resp:
                    if resp.status == 304:
                        return 304, None, since
                    if resp.status == 401:
                        self._token = None
                        last_error = 'HTTP 401'
                        continue
                    if resp.status == 404:
                        return 404, None, None
                    if resp.status >= 500 or resp.status == 429:
                        last_error = f'HTTP {resp.status}'
                    elif resp.status != 200:
                        return resp.status, None, None
                    else:
                        return 200, await resp.read(), resp.headers.get('Last-Modified')
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = str(e) or type(e).__name__
            await asyncio.sleep(2 * (attempt + 1))
        raise RuntimeError(f'Blizzard {path}: {last_error}')
