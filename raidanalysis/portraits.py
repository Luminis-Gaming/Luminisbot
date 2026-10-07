"""
The Players tab's portraits, made small: Blizzard's full-body render is a 1600 x 1200 PNG (200-550 KB) with the
character in the middle, and a tile shows a bit of it - head to thigh. Here it's cropped to that part and shrunk
to the tile's size (twice over, for sharp screens) as WebP, which keeps the transparency: ~20 KB instead of ~400.

Made on first ask and kept in memory (PORTRAITS_KEPT, the least recently asked go first) - and by the browser for
a day. Only ever for a render we have stored for a character we know (armory.portraits): never a URL from outside.
"""
import asyncio
import io
import logging
from collections import OrderedDict

import aiohttp

logger = logging.getLogger(__name__)

RENDER_HOST = 'https://render.worldofwarcraft.com/'
# The part of the render a tile shows, as shares of its width / height (the character stands in the middle)
CROP = (0.339, 0.135, 0.661, 0.599)
WIDTH = 288                 # px: a tile is ~130-160 px wide, twice that for sharp screens
QUALITY = 82
PORTRAITS_KEPT = 400        # ~20 KB each
FETCH_TIMEOUT = 20

_kept = OrderedDict()       # render url -> webp bytes
_making = {}                # render url -> the task making it (one fetch each, however many ask at once)


def crop(png_bytes):
    """A render (PNG bytes) -> the tile's portrait as WebP bytes."""
    from PIL import Image
    with Image.open(io.BytesIO(png_bytes)) as image:
        image = image.convert('RGBA')
        w, h = image.size
        box = (round(CROP[0] * w), round(CROP[1] * h), round(CROP[2] * w), round(CROP[3] * h))
        part = image.crop(box)
        height = round(WIDTH * part.height / part.width)
        part = part.resize((WIDTH, height), Image.LANCZOS)
        out = io.BytesIO()
        part.save(out, 'WEBP', quality=QUALITY, method=4)
        return out.getvalue()


async def _make(url):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT)) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f'HTTP {resp.status}')
            raw = await resp.read()
    return await asyncio.to_thread(crop, raw)  # decoding a 1600 x 1200 PNG: off the event loop


async def get(url):
    """The portrait for a stored render URL (WebP bytes), or None when it can't be had."""
    if not url or not url.startswith(RENDER_HOST):
        return None
    if url in _kept:
        _kept.move_to_end(url)
        return _kept[url]
    task = _making.get(url)
    if task is None:
        task = _making[url] = asyncio.ensure_future(_make(url))
        task.add_done_callback(lambda _: _making.pop(url, None))
    try:
        data = await asyncio.shield(task)
    except Exception as e:
        logger.info(f'[RAIDS] Portrait {url} not made: {e}')
        return None
    _kept[url] = data
    while len(_kept) > PORTRAITS_KEPT:
        _kept.popitem(last=False)
    return data
