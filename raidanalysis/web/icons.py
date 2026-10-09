"""
The raid pages' own icons (icons/*.svg, drawn by icons_draw.py) - Luminis's: little full-colour illustrations with a
dark ink outline, a shine and a soft shadow; the guild's light spark (a four-point star) where something shines.
A file is named for what it shows (blade, bullseye, horned-helm), never for the emoji it stands in for or one place
it's used: EMOJI is the one place that ties an emoji (a meaning) to a drawing, and to the tone it glows in.

icon(name, tone) gives an <img> of one, served by routes.handle_icon from /raids/static/icons/{version}/{tone}/{name}.svg
- kept by the browser for good (the version is a hash of the drawings, so a redraw is a new address). A tone is a
soft glow in its colour (TONES) traced around the thing itself - the drawing's id="body" layer - with the drawing's
own aura left out, so there is one glow; sparks and flames (its "fx" layer) stay crisp on top of it.

The pages were written with emojis, and still are where it's quickest to write (icon tiles, section heads, insight
rows...): every page goes through iconize() on its way out (routes._page), which swaps the emojis in EMOJI for these -
in the page's text only: an attribute (a tooltip, a placeholder), a <script>, <style>, <title> or <option> can't hold
an image and keeps its emoji. Discord recaps keep theirs too. Typographic marks (✔ ✓ ★ ✕ → ·) aren't emojis and stay
text.

The DPS icon (blade) is an easter egg: the page script (render.PAGE_JS) turns each one into a legendary weapon from
LEGENDARIES, its name in the tooltip - in headings, tabs and tiles (⚔). Not as the role marker next to each player
(render.ROLE_ICONS: 🗡, class "no-legendary") - a list of DPS players, each with a different weapon, is too much.
"""
import hashlib
import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).parent / 'icons'
_SVGS = {p.stem: p.read_text(encoding='utf-8').strip() for p in DIR.glob('*.svg')}

# tone -> its glow's colour
TONES = {'good': '#4ade80', 'bad': '#ff5c5c', 'warn': '#f6c453', 'tank': '#5b9bff', 'dps': '#ff8a5c',
         'accent': '#8f9bff', 'teal': '#2fd0bf', 'magic': '#c084fc', 'gold': '#f5b942'}
PLAIN = 'plain'  # no tone: the drawing as it is, its own aura and all

# emoji -> (drawing, tone or None[, extra class]) - by what it means: red death / bosses / mechanics, green healing / good, blue
# tanks, amber warnings / for-the-raid, violet magic, teal consumables / numbers, gold the brand and achievements,
# indigo finding your way. With and without the emoji variation selector (U+FE0F).
EMOJI = {
    '⚔': ('blade', 'dps'), '🗡': ('blade', 'dps', 'no-legendary'), '🛡': ('shield', 'tank'), '💚': ('plus-diamond', 'good'),
    '💀': ('skull', 'bad'), '🎯': ('bullseye', 'bad'), '📌': ('pushpin', 'bad'), '📈': ('rising-chart', 'accent'),
    '🧪': ('flask', 'teal'), '📋': ('checklist', 'warn'), '⚠': ('warning', 'warn'), '🔄': ('cycle-arrows', 'accent'),
    '👥': ('figures', 'accent'), '👹': ('horned-helm', 'bad'), '🐉': ('horned-helm', 'bad'), '🧙': ('figures', 'accent'),
    '🤝': ('giving-hand', 'warn'), '✨': ('sparkles', 'magic'), '📊': ('bar-chart', 'teal'), '🔎': ('magnifier', 'accent'),
    '✅': ('check', 'good'), '❌': ('cross', 'bad'), '🧯': ('flag', 'bad'), '✋': ('broken-cast-bar', 'warn'),
    '⏳': ('hourglass', 'warn'), '👍': ('check', 'good'), '📅': ('calendar', 'accent'), '🗓': ('calendar', 'accent'),
    '🕒': ('pocket-watch', 'accent'), '💎': ('gem', 'teal'), '❤': ('healthstone', 'good'), '🔁': ('loop-arrows', 'accent'),
    '🧮': ('ranked-bars', 'accent'), '🎞': ('film-strip', 'accent'), '🧭': ('stairs', 'gold'), '🧩': ('bullet-list', 'accent'),
    '🏅': ('medal', 'gold'), '📜': ('scroll', 'gold'), '⚡': ('lightning', 'warn'), '📝': ('quill', 'accent'),
    '🎉': ('popper', 'gold'), '📥': ('inbox-arrow', 'accent'), '👻': ('ghost', None), '🗄': ('chest', None),
    '📺': ('screen', 'accent'), '🍄': ('mushroom', 'bad'), '🧬': ('helix', 'magic'), 'ℹ': ('info', 'accent'),
    '🔴': ('diamond-red', 'bad'), '🟠': ('diamond-amber', 'warn'), '🟢': ('diamond-green', 'good'),
    '⚪': ('diamond-silver', None), '⚫': ('diamond-dark', None),
}
# The DPS icon's easter egg: (drawing, its name in the tooltip)
LEGENDARIES = [
    ('legendary-thunderfury', 'Thunderfury, Blessed Blade of the Windseeker'),
    ('legendary-sulfuras', 'Sulfuras, Hand of Ragnaros'),
    ('legendary-ashbringer', 'Ashbringer'),
    ('legendary-frostmourne', 'Frostmourne'),
    ('legendary-warglaive', 'Warglaive of Azzinoth'),
    ('legendary-shadowmourne', 'Shadowmourne'),
    ('legendary-thoridal', "Thori'dal, the Stars' Fury"),
    ('legendary-dragonwrath', "Dragonwrath, Tarecgosa's Rest"),
]

_EMOJI_RE = re.compile('(' + '|'.join(re.escape(e) for e in sorted(EMOJI, key=len, reverse=True)) + ')️?')
# What can't hold an image: tags themselves (their attributes), and the insides of these
_SKIP_RE = re.compile(r'(<script\b.*?</script>|<style\b.*?</style>|<title\b.*?</title>|<textarea\b.*?</textarea>'
                      r'|<option\b.*?</option>|<[^>]*>)', re.S | re.I)
_AURA_RE = re.compile(r'<g class="aura">.*?</g>', re.S)

# A glow traced from the drawing's body: its outline widened a little, blurred, in the tone's colour
_GLOW = ('<filter id="tone" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB">'
         '<feMorphology in="SourceAlpha" operator="dilate" radius="1.6"/><feGaussianBlur stdDeviation="3.4" result="b"/>'
         '<feFlood flood-color="{colour}" flood-opacity=".95"/><feComposite in2="b" operator="in"/></filter>')

VERSION = hashlib.sha256((''.join(sorted(_SVGS.values())) + _GLOW + repr(sorted(TONES.items()))).encode()).hexdigest()[:10]
URL_BASE = f'/raids/static/icons/{VERSION}/'


def url(name, tone=None):
    return f'{URL_BASE}{tone if tone in TONES else PLAIN}/{name}.svg'


@lru_cache(maxsize=None)
def svg(name, tone=PLAIN):
    """A drawing as served: as drawn, or with a tone's glow in place of its own aura. None for an unknown one."""
    text = _SVGS.get(name)
    if text is None or (tone != PLAIN and tone not in TONES):
        return None
    if tone == PLAIN:
        return text
    text = _AURA_RE.sub('', text, count=1)
    glow = _GLOW.format(colour=TONES[tone])
    text = text.replace('<defs>', '<defs>' + glow, 1) if '<defs>' in text else \
        text.replace('>', f'><defs>{glow}</defs>', 1)
    return text.replace('<g id="body">', '<use href="#body" filter="url(#tone)"/><g id="body">', 1)


def icon(name, tone=None, cls=''):
    """One icon: <img class="ic ic-{name} ic-{tone}">; '' for an unknown name."""
    if name not in _SVGS:
        return ''
    classes = ' '.join(c for c in ('ic', f'ic-{name}', f'ic-{tone}' if tone else '', cls) if c)
    return f'<img class="{classes}" src="{url(name, tone)}" alt="" aria-hidden="true" decoding="async">'


def _swap(match):
    return icon(*EMOJI[match.group(1)])


DONE = '<!--ic-->'  # marks a page already through iconize(): the page cache serves it again as it is


def iconize(html):
    """The page's emojis -> our icons, in its text only (see the module doc). Idempotent, and free the 2nd time."""
    if not html or html.startswith(DONE):
        return html
    parts = _SKIP_RE.split(html)
    for i in range(0, len(parts), 2):  # the text between the skipped parts (split keeps those at odd indices)
        if parts[i]:
            parts[i] = _EMOJI_RE.sub(_swap, parts[i])
    return DONE + ''.join(parts)
