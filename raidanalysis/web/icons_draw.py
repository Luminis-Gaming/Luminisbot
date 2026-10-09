"""
Draws the raid pages' icons (icons/*.svg) - run it after changing one: python -m raidanalysis.web.icons_draw

The Luminis style: little illustrations, not glyphs - full colour, a dark ink outline, gradients for form, a white
shine top left, a soft shadow beneath. 64 x 64, with PAD all round for a glow. Each file has four layers:
    <g class="ground">  the shadow
    <g class="aura">    the icon's own soft glow (left out when a page gives it a tone - icons.py)
    <g id="body">       the thing itself - what a tone's glow is traced from
    <g class="fx">      sparks, bolts, flames: light on top, never glowing themselves
A file is named for what it shows. legendary-*: the weapons the DPS icon (blade) turns into, one per page view.
"""
import math
import re

INK = '#14101f'
O = f'stroke="{INK}" stroke-width="2.4" stroke-linejoin="round"'
PAD = 8  # room around the drawing for a glow (a tone's, added by the server) - never clipped
H = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-PAD} {-PAD} {64 + 2 * PAD} {64 + 2 * PAD}">'
GROUND, AURA, FX = [], [], []  # the layers besides the object itself, filled while an icon is drawn

GOLD = ('#fff0b3', '#f5b942', '#9a5c0a')
STEEL = ('#ffffff', '#c3cbdc', '#6b7690')
PARCH = ('#fff8e4', '#efdcab', '#bf9a5e')
WOOD = ('#d39a62', '#8a5530', '#4a2a14')
IRON = ('#9aa3b8', '#565d72', '#262a38')
RED = ('#ffb8b0', '#ef4444', '#86101f')
GREEN = ('#d6fbe2', '#34d36b', '#0d6430')
BLUE = ('#d3e3ff', '#4f8cff', '#173687')
AMBER = ('#fff3c0', '#f6c453', '#b0700c')
VIOLET = ('#f3e3ff', '#b77cf9', '#5b21b6')
TEAL = ('#cafff6', '#2fd0bf', '#0a6660')
INDIGO = ('#e0e4ff', '#8190ff', '#2e3a9e')


def lin(id, c, x1=0, y1=0, x2=0, y2=1):
    stops = ''.join(f'<stop offset="{i / (len(c) - 1):.2f}" stop-color="{col}"/>' for i, col in enumerate(c))
    return f'<linearGradient id="{id}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">{stops}</linearGradient>'


def rad(id, stops, cx=.5, cy=.5, r=.5):
    out = ''
    for o, col, *a in stops:
        op = f' stop-opacity="{a[0]}"' if a else ''
        out += f'<stop offset="{o}" stop-color="{col}"{op}/>'
    return f'<radialGradient id="{id}" cx="{cx}" cy="{cy}" r="{r}">{out}</radialGradient>'


def glow(id, col, op=.55):
    return rad(id, [(0, col, op), (1, col, 0)])


def spark(x, y, r, fill='#fff', part='fx'):
    """The Luminis spark: light on top of the object (fx - never glows), or part='body' when it's drawn on it."""
    w = r * .28
    el = (f'<path d="M{x} {y - r} Q{x + w} {y - w} {x + r} {y} Q{x + w} {y + w} {x} {y + r} '
            f'Q{x - w} {y + w} {x - r} {y} Q{x - w} {y - w} {x} {y - r} Z" fill="{fill}"/>')
    if part == 'body':
        return el
    FX.append(el)
    return ''


def aura(el):
    """The icon's own soft glow - left out when the page gives it a tone (whose glow takes its place)."""
    AURA.append(el)
    return ''


def fx(el):
    FX.append(el)
    return ''


def shadow(cx=32, cy=59, rx=17):
    GROUND.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="3.2" fill="#000" opacity=".35"/>')
    return ''


def shine(d, w=2.6, op=.6):
    return f'<path d="{d}" stroke="#fff" stroke-opacity="{op}" stroke-width="{w}" fill="none" stroke-linecap="round"/>'


def glyph(d, w=6, ink='#0b0a14'):
    """A white mark with a dark edge (check, cross, !)."""
    return (f'<path d="{d}" stroke="{ink}" stroke-width="{w + 3.4}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="{d}" stroke="#fff" stroke-width="{w}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def svg(defs, body):
    """ground (shadow), aura, the object (id="body": what a tone's glow is traced from), fx (sparks)."""
    layers = (f'<g class="ground">{"".join(GROUND)}</g>' if GROUND else '') + \
             (f'<g class="aura">{"".join(AURA)}</g>' if AURA else '') + f'<g id="body">{body}</g>' + \
             (f'<g class="fx">{"".join(FX)}</g>' if FX else '')
    GROUND.clear(), AURA.clear(), FX.clear()
    return H + (f'<defs>{defs}</defs>' if defs else '') + layers + '</svg>'


icons = {}


# ---- faceted gem diamond (status: check, cross, info, heal, dots) ----
def gem_diamond(p, pal, mark='', scale=1.0):
    a, b, c, d, e = pal
    outer = [(32, 4), (60, 32), (32, 60), (4, 32)]
    inner = [(32, 17), (47, 32), (32, 47), (17, 32)]
    def poly(pts, fill):
        return f'<polygon points="{" ".join(f"{x},{y}" for x, y in pts)}" fill="{fill}"/>'
    g = (poly([outer[3], outer[0], inner[0], inner[3]], a) + poly([outer[0], outer[1], inner[1], inner[0]], b)
         + poly([outer[1], outer[2], inner[2], inner[1]], e) + poly([outer[2], outer[3], inner[3], inner[2]], d)
         + poly(inner, f'url(#{p}-t)')
         + f'<polygon points="32,4 60,32 32,60 4,32" fill="none" {O}/>' + shine('M11 31 L31 11', 2.4, .7) + mark)
    defs = lin(f'{p}-t', [b, c, d], 0, 0, 1, 1)
    if scale != 1:
        g = f'<g transform="translate({32 - 32 * scale} {32 - 32 * scale}) scale({scale})">{g}</g>'
    return svg(defs, g)


def gem_pal(base):
    lt, mid, dk = base
    return (lt, mid, mid, dk, dk)


icons['check'] = gem_diamond('ck', ('#c9f7d8', '#6ee798', '#34d36b', '#1a9a4a', '#0d6430'), glyph('M21.5 32.5 L29 40 L43 24.5'))
icons['cross'] = gem_diamond('cx', ('#ffd0cb', '#ff8077', '#ef4444', '#b91c2c', '#7a0e1c'), glyph('M24 24 L40 40 M40 24 L24 40'))
icons['info'] = gem_diamond('in', ('#dbe4ff', '#93a8ff', '#5b74ff', '#3446c7', '#1f2a85'),
                            glyph('M32 30.5 L32 42.5') + f'<circle cx="32" cy="22.5" r="4.2" fill="#fff" stroke="#0b0a14" stroke-width="1.7"/>')
icons['plus-diamond'] = gem_diamond('pd', ('#d9fff0', '#7cf0c0', '#2fd398', '#14a06c', '#0a6646'),
                                    glyph('M32 22 L32 42 M22 32 L42 32', 6.4))
for name, pal in {'red': ('#ffd0cb', '#ff8077', '#ef4444', '#b91c2c', '#7a0e1c'),
                  'amber': ('#fff3c0', '#fbd56e', '#f2b33a', '#c47f10', '#8a5306'),
                  'green': ('#c9f7d8', '#6ee798', '#34d36b', '#1a9a4a', '#0d6430'),
                  'silver': ('#ffffff', '#dfe4ee', '#b4bccd', '#7d869c', '#525a70'),
                  'dark': ('#9ea4b8', '#6b7187', '#4b5064', '#33374a', '#1f2231')}.items():
    icons[f'diamond-{name}'] = gem_diamond(f'd{name[:2]}', pal, '', .62)


# ---- the 8 from the sample ----
icons['mushroom'] = svg(
    rad('mu-cap', [(0, '#ff9a86'), (.5, '#e5323f'), (1, '#7d0f22')], .36, .25, .85) + lin('mu-stem', ['#fffaf0', '#efe2c4', '#b8a07e'], 0, 0, 1, 0),
    shadow() + f'<path d="M25 37 C24 46 23 52 21.5 56.5 Q32 60 42.5 56.5 C41 52 40 46 39 37 Z" fill="url(#mu-stem)" {O}/>'
    + shine('M26.5 42 C26 48 25.5 52 25 55', 2, .7) + '<ellipse cx="32" cy="38.5" rx="15" ry="3.4" fill="#5a3528"/>'
    + f'<path d="M5 36 C5 18 17 7 32 7 C47 7 59 18 59 36 C50 40 14 40 5 36 Z" fill="url(#mu-cap)" {O}/>'
    + ''.join(f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="#fff6ee"/>' for x, y, rx, ry in
              [(21, 20, 5, 4), (37.5, 15, 3.4, 2.8), (46, 26, 4.2, 3.2), (13.5, 30, 2.6, 2.2), (30, 28, 3.2, 2.6), (52, 33, 2, 1.6)])
    + shine('M12 24 C14 16 20 11.5 27 10', 2.6, .55))

icons['skull'] = svg(
    lin('sk-bone', ['#fbf7ec', '#ded3ba', '#a8977a']) + rad('sk-eye', [(0, '#f3e1ff'), (.35, '#c084fc'), (1, '#c084fc', 0)]),
    shadow() + f'<path d="M32 5 C17 5 9 15 9 28 C9 36 13 41 18 43 L18 50 Q18 55 23 55 L41 55 Q46 55 46 50 L46 43 C51 41 55 36 55 28 C55 15 47 5 32 5 Z" fill="url(#sk-bone)" {O}/>'
    + '<path d="M16 30 Q17 23 25 24 Q29.5 26 27.5 32 Q24.5 37 19 35.5 Q15 34 16 30 Z M48 30 Q47 23 39 24 Q34.5 26 36.5 32 Q39.5 37 45 35.5 Q49 34 48 30 Z" fill="#1d1428"/>'
    + '<circle cx="22" cy="30" r="6" fill="url(#sk-eye)"/><circle cx="42" cy="30" r="6" fill="url(#sk-eye)"/>'
    + '<path d="M32 36.5 L28.8 42.5 L35.2 42.5 Z" fill="#1d1428"/>'
    + '<path d="M22 47.5 L42 47.5 M27 47.5 L27 54.5 M32 47.5 L32 54.5 M37 47.5 L37 54.5" stroke="#5c4f3d" stroke-width="1.8" stroke-linecap="round"/>'
    + '<path d="M41 7.5 L38 13 L41 16.5 L38.5 21" stroke="#6b5c46" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    + shine('M14 22 C16 15 21 10.5 27 9', 2.6, .8))

icons['shield'] = svg(
    lin('sh-rim', ['#eef2fa', '#a3adc4', '#4e5874'], 0, 0, 1, 1) + lin('sh-field', ['#5b95ff', '#16307a']) + lin('sh-gold', GOLD, 0, 0, 1, 1),
    shadow() + f'<path d="M32 3 L55 10 C55 32 48 48 32 60 C16 48 9 32 9 10 Z" fill="url(#sh-rim)" {O}/>'
    + '<path d="M32 9.5 L49 14.5 C49 31 43 43.5 32 52.5 C21 43.5 15 31 15 14.5 Z" fill="url(#sh-field)" stroke="#0d1838" stroke-width="1.6"/>'
    + '<path d="M32 9.5 L15 14.5 C15 31 21 43.5 32 52.5 Z" fill="#fff" opacity=".1"/>'
    + '<path d="M32 18 L41 30.5 L32 43 L23 30.5 Z" fill="url(#sh-gold)" stroke="#5a3606" stroke-width="1.6" stroke-linejoin="round"/>'
    + '<path d="M32 18 L23 30.5 L32 30.5 Z" fill="#fff" opacity=".45"/>'
    + ''.join(f'<circle cx="{x}" cy="{y}" r="1.6" fill="#fff" opacity=".85"/>' for x, y in [(14, 12.5), (50, 12.5), (32, 6.5)]))

icons['flask'] = svg(
    lin('fl-liq', ['#7bf7e4', '#21c2b0', '#0b6d66']) + lin('fl-cork', ['#e0a56b', '#7a4a24']) + glow('fl-glow', '#4fd1c5'),
    shadow() + aura('<circle cx="32" cy="41" r="24" fill="url(#fl-glow)"/>')
    + '<path d="M15 38.5 C21 35.5 27 40.5 33 37.5 C39 34.5 44 38.5 48.8 36.8 C49.6 38.4 50 39.7 50 41 C50 51 42 58 32 58 C22 58 14 51 14 41 C14 40.2 14.3 39.3 15 38.5 Z" fill="url(#fl-liq)"/>'
    + f'<path d="M27 13 L27 24.5 C19 27.5 14 33.5 14 41 C14 51 22 58 32 58 C42 58 50 51 50 41 C50 33.5 45 27.5 37 24.5 L37 13 Z" fill="#dff4ff" fill-opacity=".14" {O}/>'
    + ''.join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" opacity=".75"/>' for x, y, r in [(26, 47, 2.2), (35, 43, 1.5), (39, 51, 2.6), (30, 53, 1.2)])
    + shine('M19.5 37 C17.5 41 17.5 46.5 20.5 50.5', 2.6, .75)
    + f'<rect x="23.5" y="11" width="17" height="4.5" rx="2" fill="#cfe9f7" {O}/>'
    + f'<path d="M25.5 11 L26.5 4.5 Q32 3 37.5 4.5 L38.5 11 Z" fill="url(#fl-cork)" {O}/>')


def crystal(p, shades, glow_col):
    a, b, c, d, e, f = shades
    pts = {'t': (32, 4), 'l': (13, 19), 'r': (51, 19), 'il': (24, 23), 'ir': (40, 23), 'bl': (18, 46), 'br': (46, 46), 'b': (32, 60), 'm': (32, 45)}
    def poly(keys, fill):
        return f'<polygon points="{" ".join(f"{pts[k][0]},{pts[k][1]}" for k in keys.split())}" fill="{fill}"/>'
    return (glow(f'{p}-glow', glow_col, .6),
            aura(f'<circle cx="32" cy="32" r="30" fill="url(#{p}-glow)"/>') + shadow()
            + poly('t l il', b) + poly('t il ir', a) + poly('t ir r', c) + poly('l il bl', c) + poly('il ir m', b)
            + poly('ir r br', e) + poly('il m b bl', d) + poly('ir br b m', f)
            + f'<polygon points="32,4 51,19 46,46 32,60 18,46 13,19" fill="none" {O}/>')


d, b = crystal('hs', ['#e2ffe6', '#9bf5ae', '#55e07f', '#2fbf5f', '#1f9a4a', '#0f6b33'], '#4ade80')
icons['healthstone'] = svg(d, b + spark(21, 14, 5))
d, b = crystal('lu', ['#fffbe8', '#ffe9a3', '#f7c95a', '#e0a12c', '#b97a12', '#7d4f06'], '#f5b942')
icons['luminis'] = svg(d, b + fx('<circle cx="47" cy="13" r="10" fill="url(#lu-glow)"/>') + spark(47, 13, 9.5, '#fffdf2') + spark(15, 50, 4, '#fff3c4'))

icons['blade'] = svg(
    lin('bl-steel', STEEL, 0, 0, 1, 0) + lin('bl-gold', GOLD) + lin('bl-grip', ['#8a5530', '#4a2a14'], 0, 0, 1, 0)
    + rad('bl-gem', [(0, '#f3e1ff'), (.5, '#c084fc'), (1, '#6d28d9')], .35, .35, .7),
    shadow() + '<g transform="rotate(45 32 30)">'
    + f'<path d="M32 1 L37 7.5 L37 40 L27 40 L27 7.5 Z" fill="url(#bl-steel)" {O}/>'
    + '<path d="M32 4.5 L32 39" stroke="#8792ab" stroke-width="1.4"/>'
    + f'<path d="M17 40 L47 40 Q49.5 43 47 46 L17 46 Q14.5 43 17 40 Z" fill="url(#bl-gold)" {O}/>'
    + f'<rect x="28.5" y="46" width="7" height="10" fill="url(#bl-grip)" {O}/>'
    + '<path d="M28.5 49 L35.5 51 M28.5 52.5 L35.5 54.5" stroke="#2a170b" stroke-width="1.3"/>'
    + f'<circle cx="32" cy="59.5" r="3.6" fill="url(#bl-gem)" {O}/></g>')

icons['horned-helm'] = svg(
    lin('hh-iron', IRON, 0, 0, .4, 1) + lin('hh-horn', ['#fffaf0', '#d9c9a6', '#8f7a58'])
    + rad('hh-eye', [(0, '#ffe0e0'), (.4, '#ff4d4d'), (1, '#ff4d4d', 0)]),
    shadow() + f'<path d="M17 27 C8 25 3 16 5.5 4 C9.5 13 14 17 22 19.5 Z" fill="url(#hh-horn)" {O}/>'
    + f'<path d="M47 27 C56 25 61 16 58.5 4 C54.5 13 50 17 42 19.5 Z" fill="url(#hh-horn)" {O}/>'
    + f'<path d="M14 34 C14 20 22 12 32 12 C42 12 50 20 50 34 L50 48 Q50 54 44 56.5 L20 56.5 Q14 54 14 48 Z" fill="url(#hh-iron)" {O}/>'
    + '<path d="M14.6 28 Q32 21.5 49.4 28" stroke="#e0b04a" stroke-width="3" fill="none"/>'
    + '<path d="M19.5 33.5 L44.5 33.5 L42.5 39.5 L21.5 39.5 Z" fill="#14070b"/>'
    + '<ellipse cx="27" cy="36.5" rx="5" ry="3" fill="url(#hh-eye)"/><ellipse cx="37" cy="36.5" rx="5" ry="3" fill="url(#hh-eye)"/>'
    + '<path d="M30 39.5 L34 39.5 L33.2 53 L30.8 53 Z" fill="#9aa3b8" stroke="#14101f" stroke-width="1.2"/>'
    + shine('M19 22 C21 17.5 25 14.5 29 13.8', 2.4, .45))


# ---- the rest ----
icons['chest'] = svg(
    lin('ch-wood', WOOD) + lin('ch-lid', ['#e2ab72', '#a5683a', '#6b3f1e']) + lin('ch-iron', IRON, 0, 0, 1, 0) + lin('ch-gold', GOLD),
    shadow(32, 59, 25) + f'<rect x="7" y="28" width="50" height="28" rx="3" fill="url(#ch-wood)" {O}/>'
    + '<path d="M8.5 38 L55.5 38 M8.5 47 L55.5 47" stroke="#3a210f" stroke-width="1.6" opacity=".7"/>'
    + f'<path d="M7 28 L7 20 C7 13 13 9 20 9 L44 9 C51 9 57 13 57 20 L57 28 Z" fill="url(#ch-lid)" {O}/>'
    + '<path d="M9 28 L55 28" stroke="#2a170b" stroke-width="2.2"/>'
    + ''.join(f'<rect x="{x}" y="9.6" width="5.5" height="46" fill="url(#ch-iron)" stroke="{INK}" stroke-width="1.6"/>' for x in (14, 44.5))
    + ''.join(f'<circle cx="{x + 2.75}" cy="{y}" r="1.1" fill="#e6eaf2"/>' for x in (14, 44.5) for y in (15, 34, 50))
    + f'<rect x="26.5" y="23" width="11" height="13" rx="2.2" fill="url(#ch-gold)" stroke="#5a3606" stroke-width="1.6"/>'
    + '<path d="M32 27 a2 2 0 1 1 0.01 0 M31 29 L30.3 33 L33.7 33 L33 29" fill="#3a2404"/>'
    + shine('M11 19 C12 14.5 15.5 12 20 11.6', 2.4, .5))

icons['bar-chart'] = svg(
    lin('bc-a', TEAL, 0, 0, 1, 0) + lin('bc-b', INDIGO, 0, 0, 1, 0) + lin('bc-c', GOLD, 0, 0, 1, 0) + lin('bc-base', ['#7c8398', '#3a3f52']),
    shadow(32, 59, 25)
    + ''.join(f'<rect x="{x}" y="{y}" width="12" height="{54 - y}" rx="2" fill="url(#{g})" {O}/>'
              f'<rect x="{x + 2.2}" y="{y + 2.2}" width="3" height="{54 - y - 6}" rx="1.5" fill="#fff" opacity=".45"/>'
              for x, y, g in [(10, 34, 'bc-a'), (26, 22, 'bc-b'), (42, 10, 'bc-c')])
    + f'<rect x="5" y="52" width="54" height="6" rx="3" fill="url(#bc-base)" {O}/>' + spark(48, 6, 4.5, '#fff8d6'))

icons['lightning'] = svg(
    lin('lt-b', AMBER, 0, 0, 1, 1) + glow('lt-g', '#f6c453', .6),
    aura('<ellipse cx="32" cy="32" rx="28" ry="30" fill="url(#lt-g)"/>')
    + f'<path d="M39 3 L13 36 L29 36 L22 61 L51 24 L35 24 L43 3 Z" fill="url(#lt-b)" {O}/>'
    + '<path d="M38 9 L21 31.5 L33 31.5 L29.5 47 L42.5 29 L30.5 29 Z" fill="#fffbe6" opacity=".75"/>')

icons['calendar'] = svg(
    lin('ca-p', PARCH) + lin('ca-r', RED) + lin('ca-i', IRON, 0, 0, 1, 0) + lin('ca-g', GOLD),
    shadow(32, 60, 24) + f'<rect x="7" y="11" width="50" height="47" rx="5" fill="url(#ca-p)" {O}/>'
    + f'<path d="M7 25 L7 16 Q7 11 12 11 L52 11 Q57 11 57 16 L57 25 Z" fill="url(#ca-r)" {O}/>'
    + ''.join(f'<rect x="{x}" y="4" width="6" height="13" rx="3" fill="url(#ca-i)" {O}/>' for x in (17, 41))
    + ''.join(f'<rect x="{13 + c * 10}" y="{30 + r * 9}" width="7" height="6" rx="1.4" fill="#b48f58" opacity=".55"/>'
              for r in range(3) for c in range(4) if (r, c) != (1, 2))
    + '<path d="M36.5 37.5 L40 33.5 L43.5 37.5 L40 41.5 Z" fill="url(#ca-g)" stroke="#5a3606" stroke-width="1.3"/>'
    + shine('M11 18 L11 15.5 Q11 14 13 14', 2, .55))

icons['broken-cast-bar'] = svg(
    lin('cb-f', IRON) + lin('cb-v', ['#e9d5ff', '#a855f7', '#5b21b6'], 0, 0, 1, 0) + glow('cb-g', '#ff9f43', .8),
    '<g transform="rotate(-9 30 32) translate(-3 1)">'
    + f'<path d="M4 27 Q4 21 10 21 L31 21 L27 32 L32 43 L10 43 Q4 43 4 37 Z" fill="url(#cb-f)" {O}/>'
    + '<path d="M8 25.5 L29 25.5 L25.5 32 L29.3 38.5 L8 38.5 Z" fill="url(#cb-v)"/>'
    + shine('M10 28 L26 28', 2, .55) + '</g>'
    + '<g transform="rotate(9 34 32) translate(3 1)">'
    + f'<path d="M35 21 L54 21 Q60 21 60 27 L60 37 Q60 43 54 43 L34 43 L39 32 Z" fill="url(#cb-f)" {O}/>'
    + '<path d="M38 25.5 L56 25.5 L56 38.5 L37 38.5 L41.5 32 Z" fill="#1b1430"/>'
    + '<path d="M38 25.5 L44 25.5 L44 38.5 L37 38.5 L41.5 32 Z" fill="url(#cb-v)" opacity=".7"/></g>'
    + fx('<circle cx="32" cy="32" r="14" fill="url(#cb-g)"/>') + spark(32, 32, 11, '#fff3d6')
    + fx(''.join(f'<path d="M{x} {y} l2.2 -2.2 l2.2 2.2 l-2.2 2.2 Z" fill="#ffcf87" stroke="{INK}" stroke-width="1"/>'
              for x, y in [(20, 12), (40, 52), (44, 10), (16, 50)])))

icons['checklist'] = svg(
    lin('cl-w', WOOD) + lin('cl-p', PARCH) + lin('cl-g', GOLD) + lin('cl-c', GREEN),
    shadow(32, 60, 22) + f'<rect x="9" y="8" width="46" height="52" rx="5" fill="url(#cl-w)" {O}/>'
    + f'<rect x="14" y="14" width="36" height="41" rx="2" fill="url(#cl-p)" stroke="#6b4a22" stroke-width="1.4"/>'
    + f'<rect x="22" y="4" width="20" height="10" rx="3" fill="url(#cl-g)" {O}/>'
    + '<circle cx="32" cy="8.5" r="1.8" fill="#5a3606"/>'
    + ''.join(f'<rect x="18" y="{y}" width="8" height="8" rx="1.6" fill="#fffaf0" stroke="#6b4a22" stroke-width="1.5"/>'
              f'<path d="M30 {y + 4} L45 {y + 4}" stroke="#9b7a45" stroke-width="3" stroke-linecap="round"/>' for y in (20, 31, 42))
    + ''.join(f'<path d="M19 {y + 3.5} L21.8 {y + 6.5} L27.5 {y - 1}" stroke="#0b3d1e" stroke-width="4.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
              f'<path d="M19 {y + 3.5} L21.8 {y + 6.5} L27.5 {y - 1}" stroke="url(#cl-c)" stroke-width="2.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>' for y in (20, 31)))

icons['pocket-watch'] = svg(
    lin('pw-g', GOLD, 0, 0, 1, 1) + rad('pw-f', [(0, '#fffdf5'), (.8, '#f1e6cc'), (1, '#cdb88c')], .4, .35, .7),
    shadow(32, 60, 18) + '<circle cx="32" cy="6.5" r="4" fill="none" stroke="#14101f" stroke-width="5"/>'
    + '<circle cx="32" cy="6.5" r="4" fill="none" stroke="url(#pw-g)" stroke-width="2.6"/>'
    + f'<rect x="28" y="9" width="8" height="6" rx="1.5" fill="url(#pw-g)" {O}/>'
    + f'<circle cx="32" cy="36" r="22" fill="url(#pw-g)" {O}/>'
    + '<circle cx="32" cy="36" r="17" fill="url(#pw-f)" stroke="#7a4a0a" stroke-width="1.6"/>'
    + ''.join(f'<path d="M{32 + 14 * math.cos(a):.2f} {36 + 14 * math.sin(a):.2f} L{32 + 16 * math.cos(a):.2f} {36 + 16 * math.sin(a):.2f}" '
              f'stroke="#5a4320" stroke-width="{2.2 if i % 3 == 0 else 1.2}" stroke-linecap="round"/>'
              for i, a in enumerate(math.radians(k * 30) for k in range(12)))
    + '<path d="M32 36 L32 24.5 M32 36 L40.5 40" stroke="#1d1428" stroke-width="2.6" stroke-linecap="round"/>'
    + '<circle cx="32" cy="36" r="2.4" fill="#b8323f" stroke="#1d1428" stroke-width="1"/>'
    + shine('M19 30 C20.5 25 24.5 21.5 29 20.5', 2.4, .75))


def helix_pts(phase, n=40):
    return [(32 + 13 * math.sin(phase + (y - 6) / 52 * 2.2 * math.pi), y) for y in [6 + 52 * i / n for i in range(n + 1)]]


def polyline(pts):
    return 'M' + ' L'.join(f'{x:.2f} {y:.2f}' for x, y in pts)


rungs = ''
for i in range(9):
    y = 9 + i * 5.6
    t = (y - 6) / 52 * 2.2 * math.pi
    x1, x2 = 32 + 13 * math.sin(t), 32 + 13 * math.sin(t + math.pi)
    if abs(x1 - x2) > 4:
        rungs += (f'<path d="M{x1:.2f} {y:.2f} L{x2:.2f} {y:.2f}" stroke="{INK}" stroke-width="4.6" stroke-linecap="round"/>'
                  f'<path d="M{x1:.2f} {y:.2f} L{(x1 + x2) / 2:.2f} {y:.2f}" stroke="#e9d5ff" stroke-width="2.4" stroke-linecap="round"/>'
                  f'<path d="M{(x1 + x2) / 2:.2f} {y:.2f} L{x2:.2f} {y:.2f}" stroke="#99f6e4" stroke-width="2.4" stroke-linecap="round"/>')
a_pts, b_pts = polyline(helix_pts(0)), polyline(helix_pts(math.pi))
icons['helix'] = svg(
    lin('hx-a', VIOLET, 0, 0, 1, 0) + lin('hx-b', TEAL, 0, 0, 1, 0) + glow('hx-g', '#c084fc', .4),
    aura('<ellipse cx="32" cy="32" rx="24" ry="30" fill="url(#hx-g)"/>') + rungs
    + f'<path d="{b_pts}" stroke="{INK}" stroke-width="8.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    + f'<path d="{b_pts}" stroke="url(#hx-b)" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    + f'<path d="{a_pts}" stroke="{INK}" stroke-width="8.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    + f'<path d="{a_pts}" stroke="url(#hx-a)" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')

icons['film-strip'] = svg(
    lin('fs-s', ['#4b5066', '#262a38']) + lin('fs-w', ['#a5b4fc', '#6d5bd0', '#2e1f6b'], 0, 0, 1, 1),
    shadow(32, 59, 24) + '<g transform="rotate(-12 32 32)">'
    + f'<rect x="3" y="15" width="58" height="34" rx="3" fill="url(#fs-s)" {O}/>'
    + ''.join(f'<rect x="{x}" y="{y}" width="4" height="3.4" rx="1" fill="#e8ebf5"/>' for x in range(7, 58, 8) for y in (18, 42.6))
    + ''.join(f'<rect x="{x}" y="24" width="15" height="16" rx="1.6" fill="url(#fs-w)" stroke="#0b0a14" stroke-width="1.2"/>'
              f'<path d="M{x + 1} 37 L{x + 6} 31 L{x + 9} 34 L{x + 11} 32 L{x + 14} 37 Z" fill="#1e1b4b" opacity=".7"/>' for x in (7, 24.5, 42))
    + spark(31.5, 29, 3.4, '#fff6d6', 'body') + '</g>')

icons['flag'] = svg(
    lin('fg-c', RED, 0, 0, 1, 1) + lin('fg-p', WOOD, 0, 0, 1, 0) + lin('fg-g', GOLD),
    shadow(18, 60, 10) + f'<rect x="12.5" y="7" width="5" height="52" rx="2" fill="url(#fg-p)" {O}/>'
    + f'<circle cx="15" cy="6" r="4" fill="url(#fg-g)" {O}/>'
    + f'<path d="M17.5 10 C27 6 35 14 45 10 C49 8.5 53 8.5 57 10 L57 36 C47 40 39 31 29 35 C25 36.5 21 36.5 17.5 35 Z" fill="url(#fg-c)" {O}/>'
    + '<path d="M36 15.5 L41 22.5 L36 29.5 L31 22.5 Z" fill="url(#fg-g)" stroke="#5a3606" stroke-width="1.4" stroke-linejoin="round"/>'
    + shine('M21 14 C26 11.5 31 12.5 35 14.5', 2.2, .5))

icons['gem'] = svg(
    glow('gm-g', '#34d4c3', .5),
    aura('<circle cx="32" cy="34" r="29" fill="url(#gm-g)"/>') + shadow()
    + ''.join(f'<polygon points="{p}" fill="{c}"/>' for p, c in [
        ('8,24 21,11 26,24', '#8ff0e4'), ('21,11 43,11 38,24 26,24', '#d8fffa'), ('43,11 56,24 38,24', '#4fd9c8'),
        ('8,24 26,24 32,58', '#2fb8a9'), ('26,24 38,24 32,58', '#66e6d6'), ('38,24 56,24 32,58', '#0f7f76')])
    + f'<polygon points="21,11 43,11 56,24 32,58 8,24" fill="none" {O}/>'
    + '<path d="M8.5 24 L55.5 24" stroke="#0b4f4a" stroke-width="1.4"/>' + spark(20, 12, 5.5))

icons['ghost'] = svg(
    lin('gh-b', ['#f8fbff', '#cfd8ee', '#8d9ab8']) + glow('gh-g', '#c7d2fe', .35),
    aura('<ellipse cx="32" cy="32" rx="28" ry="30" fill="url(#gh-g)"/>')
    + f'<path d="M13 31 C13 16 21 7 32 7 C43 7 51 16 51 31 L51 55 L45.5 50 L40 56 L34.5 50 L29 56 L23.5 50 L18 56 L13 52 Z" fill="url(#gh-b)" {O}/>'
    + '<ellipse cx="25" cy="28" rx="3.6" ry="5" fill="#1d1a33"/><ellipse cx="39" cy="28" rx="3.6" ry="5" fill="#1d1a33"/>'
    + '<ellipse cx="32" cy="40" rx="3.2" ry="4" fill="#1d1a33"/>'
    + '<circle cx="24" cy="26.3" r="1.2" fill="#fff"/><circle cx="38" cy="26.3" r="1.2" fill="#fff"/>'
    + shine('M18 22 C19.5 15.5 24 11.5 29 10.5', 2.6, .9))

icons['giving-hand'] = svg(
    lin('gv-s', ['#ffe2c6', '#e8ad7c', '#a8683c']) + lin('gv-c', BLUE) + lin('gv-gem', AMBER, 0, 0, 1, 1) + glow('gv-g', '#f6c453', .7),
    aura('<circle cx="32" cy="20" r="17" fill="url(#gv-g)"/>')
    + '<path d="M32 6 L41 19 L32 32 L23 19 Z" fill="url(#gv-gem)" stroke="#5a3606" stroke-width="2" stroke-linejoin="round"/>'
    + '<path d="M32 6 L23 19 L32 19 Z" fill="#fff" opacity=".5"/>' + spark(45, 9, 4) + spark(19, 29, 2.8)
    + f'<path d="M11 44 C17 41.5 22 40.5 27 41.5 L39 43 C43.5 43.5 44 49 39.5 49.5 L30 49.8 L42 50.5 C47 50.5 51.5 46 55.5 42.5 C59 39.6 62 44 59 47.5 C53 54.5 46.5 58.5 38 58.5 L15 58.5 L11 57 Z" fill="url(#gv-s)" {O}/>'
    + '<path d="M30 49.8 L38 50.2" stroke="#8a5530" stroke-width="1.4" stroke-linecap="round"/>'
    + f'<rect x="3" y="42" width="10" height="18" rx="2.5" fill="url(#gv-c)" {O}/>'
    + shine('M17 44.5 C21 43.4 25 43.3 28 43.9', 2, .6))

icons['hourglass'] = svg(
    lin('hg-w', WOOD) + lin('hg-s', ['#ffe9a3', '#f5b942', '#b97a12']) + lin('hg-gl', ['#eaf6ff', '#a9c8e8'], 0, 0, 1, 0),
    shadow(32, 60, 20)
    + ''.join(f'<rect x="{x}" y="9" width="4.5" height="46" rx="2" fill="url(#hg-w)" {O}/>' for x in (12.5, 47))
    + '<path d="M19 11 C19 24 29 28 29 32 C29 36 19 40 19 53 L45 53 C45 40 35 36 35 32 C35 28 45 24 45 11 Z" fill="url(#hg-gl)" fill-opacity=".28" stroke="#14101f" stroke-width="2.2" stroke-linejoin="round"/>'
    + '<path d="M22.5 18 L41.5 18 C40 24 34.5 27.5 32 31 C29.5 27.5 24 24 22.5 18 Z" fill="url(#hg-s)"/>'
    + '<path d="M32 31 L32 45" stroke="#f5b942" stroke-width="1.6"/>'
    + '<path d="M20.5 52 C21.5 45 27 42 32 42 C37 42 42.5 45 43.5 52 Z" fill="url(#hg-s)"/>'
    + shine('M23 14.5 C23.5 21 27 25 29.5 27.5', 2, .8)
    + ''.join(f'<rect x="8" y="{y}" width="48" height="7" rx="2.5" fill="url(#hg-w)" {O}/>' for y in (4, 53)))

icons['inbox-arrow'] = svg(
    lin('ib-t', IRON) + lin('ib-a', INDIGO, 0, 0, 1, 1) + glow('ib-g', '#8190ff', .5),
    aura('<circle cx="32" cy="22" r="19" fill="url(#ib-g)"/>') + shadow(32, 60, 26)
    + f'<path d="M6 38 L17 38 L21 45 L43 45 L47 38 L58 38 L58 54 Q58 58 54 58 L10 58 Q6 58 6 54 Z" fill="url(#ib-t)" {O}/>'
    + '<path d="M9 41 L15.5 41 L19.5 48 L44.5 48 L48.5 41 L55 41" stroke="#fff" stroke-opacity=".35" stroke-width="1.8" fill="none"/>'
    + f'<path d="M27 3 L37 3 L37 21 L46.5 21 L32 37 L17.5 21 L27 21 Z" fill="url(#ib-a)" {O}/>'
    + shine('M30 7 L30 23', 2.2, .6))

icons['bullet-list'] = svg(
    lin('bu-p', PARCH) + lin('bu-r', RED, 0, 0, 1, 1) + lin('bu-a', AMBER, 0, 0, 1, 1) + lin('bu-g', GREEN, 0, 0, 1, 1),
    shadow(32, 60, 22)
    + f'<path d="M10 9 Q10 5 14 5 L42 5 L54 17 L54 55 Q54 59 50 59 L14 59 Q10 59 10 55 Z" fill="url(#bu-p)" {O}/>'
    + f'<path d="M42 5 L42 14 Q42 17 45 17 L54 17 Z" fill="#d9bf86" {O}/>'
    + ''.join(f'<path d="M19 {y - 4.5} L23.5 {y} L19 {y + 4.5} L14.5 {y} Z" fill="url(#{g})" stroke="{INK}" stroke-width="1.6" stroke-linejoin="round"/>'
              f'<path d="M28 {y} L{e} {y}" stroke="#9b7a45" stroke-width="3.4" stroke-linecap="round"/>'
              for y, g, e in [(24, 'bu-r', 47), (36, 'bu-a', 44), (48, 'bu-g', 47)]))

icons['medal'] = svg(
    lin('md-g', GOLD, 0, 0, 1, 1) + lin('md-r', RED) + lin('md-b', BLUE) + glow('md-gl', '#f5b942', .5),
    f'<path d="M15 3 L27 3 L37 27 L27 31 Z" fill="url(#md-b)" {O}/><path d="M49 3 L37 3 L27 27 L37 31 Z" fill="url(#md-r)" {O}/>'
    + aura('<circle cx="32" cy="42" r="21" fill="url(#md-gl)"/>')
    + f'<circle cx="32" cy="42" r="16" fill="url(#md-g)" {O}/>'
    + '<circle cx="32" cy="42" r="11.5" fill="none" stroke="#8a5306" stroke-width="1.8"/>'
    + spark(32, 42, 9, '#fffaf0', 'body') + shine('M20 36 C21.5 32 24.5 29 28.5 28', 2.2, .7))

icons['quill'] = svg(
    lin('ql-f', ['#ffffff', '#e4dcff', '#9f8ad8'], 0, 0, 1, 1) + lin('ql-n', GOLD),
    shadow(18, 60, 10)
    + f'<path d="M57 3 C42 5 27 17 20 35 L16 46 L26 41.5 C42 35 55 21 57 3 Z" fill="url(#ql-f)" {O}/>'
    + '<path d="M55 6 L18 44" stroke="#6b5aa8" stroke-width="1.6" stroke-linecap="round"/>'
    + ''.join(f'<path d="M{x} {y} l{dx} {dy}" stroke="#8b7bc4" stroke-width="1.1" stroke-linecap="round"/>'
              for x, y, dx, dy in [(46, 15, -6, -1), (40, 21, -7, -1), (34, 27, -6, -1), (45, 16, 2, 6), (39, 22, 3, 6), (33, 28, 2, 5)])
    + f'<path d="M20 41 L10 57 L25.5 45 Z" fill="url(#ql-n)" {O}/>'
    + '<circle cx="9" cy="59" r="2.4" fill="#1d1a33"/>' + shine('M52 7.5 C44 10 35 17 29 25', 2, .9))

icons['pushpin'] = svg(
    lin('pp-r', RED, 0, 0, 1, 0) + lin('pp-s', STEEL, 0, 0, 1, 0),
    shadow(23, 59, 10) + '<g transform="rotate(28 32 32)">'
    + f'<path d="M31 37 L33 37 L32 62 Z" fill="url(#pp-s)" stroke="{INK}" stroke-width="1.4" stroke-linejoin="round"/>'
    + f'<path d="M21 5 L43 5 Q45.5 5 44 7.5 L40 13 L40 25 C46.5 27.5 50 32 50 37 L14 37 C14 32 17.5 27.5 24 25 L24 13 L20 7.5 Q18.5 5 21 5 Z" fill="url(#pp-r)" {O}/>'
    + shine('M27.5 13 L27.5 24', 2.4, .6) + shine('M19 33 C20 30.5 22 29 24.5 28', 2, .5) + '</g>')

icons['figures'] = svg(
    lin('fi-v', VIOLET) + lin('fi-b', BLUE) + lin('fi-g', GOLD) + lin('fi-sk', ['#ffe2c6', '#d9a070']),
    shadow(32, 60, 26)
    + f'<path d="M30 52 C30 42 35.5 36 43 36 C50.5 36 56 42 56 52 Z" fill="url(#fi-v)" {O}/>'
    + f'<circle cx="43" cy="22" r="8.5" fill="url(#fi-sk)" {O}/>'
    + f'<path d="M7 60 C7 48 14 42 24 42 C34 42 41 48 41 60 Z" fill="url(#fi-b)" {O}/>'
    + f'<circle cx="24" cy="28" r="9.5" fill="url(#fi-sk)" {O}/>'
    + '<path d="M24 47 L27.5 51.5 L24 56 L20.5 51.5 Z" fill="url(#fi-g)" stroke="#5a3606" stroke-width="1.2"/>'
    + shine('M17.5 25 C18.5 22 20.5 20 23 19.5', 2, .7) + shine('M12 54 C12.5 50.5 14.5 47.5 17.5 46', 2, .45))

icons['popper'] = svg(
    lin('po-c', GOLD, 0, 0, 1, 1) + lin('po-r', RED),
    shadow(18, 60, 12)
    + f'<path d="M7 58 L21 24 L41 44 Z" fill="url(#po-c)" {O}/>'
    + '<path d="M11.5 47 L28.5 31 M15.8 37 L34.8 37.6" stroke="#c0262d" stroke-width="3.4" opacity=".9"/>'
    + f'<path d="M7 58 L21 24 L41 44 Z" fill="none" {O}/>'
    + fx('<path d="M27 21 C31 13 26 9 31 4" stroke="#4f8cff" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
    + '<path d="M44 38 C51 34 55 39 60 35" stroke="#34d36b" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
    + ''.join(f'<rect x="{x}" y="{y}" width="4.6" height="3" rx=".8" transform="rotate({r} {x} {y})" fill="{c}" stroke="{INK}" stroke-width=".9"/>'
              for x, y, r, c in [(38, 13, 30, '#ef4444'), (50, 22, -20, '#c084fc'), (44, 4, 50, '#34d4c3'), (56, 12, 10, '#f6c453'), (33, 29, -35, '#4f8cff')]))
    + spark(45, 27, 4.5, '#fff6d6') + spark(36, 7, 3, '#fff6d6'))

icons['ranked-bars'] = svg(
    lin('rb-1', GOLD, 0, 0, 1, 0) + lin('rb-2', STEEL, 0, 0, 1, 0) + lin('rb-3', ['#f2c094', '#c27a3e', '#7a4318'], 0, 0, 1, 0),
    ''.join(f'<rect x="17" y="{y - 5}" width="{w}" height="10" rx="3" fill="url(#rb-{i})" {O}/>'
            f'<path d="M20 {y - 2} L{14 + w} {y - 2}" stroke="#fff" stroke-opacity=".55" stroke-width="2" stroke-linecap="round"/>'
            f'<circle cx="9.5" cy="{y}" r="6" fill="url(#rb-{i})" {O}/>'
            f'<path d="M9.5 {y - 2.8} L11.6 {y} L9.5 {y + 2.8} L7.4 {y} Z" fill="#fff" opacity=".8"/>'
            for i, y, w in [(1, 14, 43), (2, 32, 33), (3, 50, 23)]))


def arc_arrow(cx, cy, r, a0, a1, grad, w=7):
    p = lambda a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    (x0, y0), (x1, y1) = p(a0), p(a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    d = f'M{x0:.2f} {y0:.2f} A{r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}'
    t = math.radians(a1)
    tx, ty, nx, ny = -math.sin(t), math.cos(t), math.cos(t), math.sin(t)
    h, hw = 9, 8
    tip = (x1 + tx * h, y1 + ty * h)
    b1, b2 = (x1 + nx * hw - tx, y1 + ny * hw - ty), (x1 - nx * hw - tx, y1 - ny * hw - ty)
    head = f'{tip[0]:.2f},{tip[1]:.2f} {b1[0]:.2f},{b1[1]:.2f} {b2[0]:.2f},{b2[1]:.2f}'
    return (f'<path d="{d}" stroke="{INK}" stroke-width="{w + 3.6}" fill="none" stroke-linecap="round"/>'
            f'<polygon points="{head}" fill="url(#{grad})" {O}/>'
            f'<path d="{d}" stroke="url(#{grad})" stroke-width="{w}" fill="none" stroke-linecap="round"/>')


icons['cycle-arrows'] = svg(
    lin('cy-a', BLUE, 0, 0, 1, 1) + lin('cy-g', GOLD, 0, 0, 1, 1) + glow('cy-gl', '#4f8cff', .4),
    aura('<circle cx="32" cy="32" r="28" fill="url(#cy-gl)"/>')
    + arc_arrow(32, 32, 20, 160, 300, 'cy-a') + arc_arrow(32, 32, 20, 340, 480, 'cy-a')
    + '<path d="M32 25 L38 32 L32 39 L26 32 Z" fill="url(#cy-g)" stroke="#5a3606" stroke-width="1.6" stroke-linejoin="round"/>')

loop = 'M14 40 L14 30 Q14 20 24 20 L40 20'
loop2 = 'M50 24 L50 34 Q50 44 40 44 L24 44'


def straight_arrow(d, end, direction, grad, w=7):
    (x, y), (dx, dy) = end, direction
    nx, ny = -dy, dx
    tip = (x + dx * 9, y + dy * 9)
    head = f'{tip[0]},{tip[1]} {x + nx * 8},{y + ny * 8} {x - nx * 8},{y - ny * 8}'
    return (f'<path d="{d}" stroke="{INK}" stroke-width="{w + 3.6}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<polygon points="{head}" fill="url(#{grad})" {O}/>'
            f'<path d="{d}" stroke="url(#{grad})" stroke-width="{w}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


icons['loop-arrows'] = svg(
    lin('lo-a', VIOLET, 0, 0, 1, 1) + lin('lo-b', INDIGO, 0, 0, 1, 1) + glow('lo-gl', '#b77cf9', .35),
    aura('<ellipse cx="32" cy="32" rx="30" ry="24" fill="url(#lo-gl)"/>')
    + straight_arrow(loop, (40, 20), (1, 0), 'lo-a') + straight_arrow(loop2, (24, 44), (-1, 0), 'lo-b'))

icons['bullseye'] = svg(
    lin('be-r', RED, 0, 0, 1, 1) + lin('be-w', ['#ffffff', '#e8e2d4']) + lin('be-g', GOLD) + lin('be-sh', WOOD, 0, 0, 1, 0),
    shadow(30, 60, 20)
    + f'<circle cx="28" cy="34" r="25" fill="url(#be-r)" {O}/>'
    + '<circle cx="28" cy="34" r="18.5" fill="url(#be-w)"/><circle cx="28" cy="34" r="12.5" fill="url(#be-r)"/>'
    + '<circle cx="28" cy="34" r="6.5" fill="url(#be-w)"/><circle cx="28" cy="34" r="3" fill="url(#be-g)"/>'
    + f'<path d="M29 33 L54 8" stroke="{INK}" stroke-width="5.4" stroke-linecap="round"/>'
    + '<path d="M29 33 L54 8" stroke="url(#be-sh)" stroke-width="2.8" stroke-linecap="round"/>'
    + f'<path d="M50 6 L57 0.5 L58 6 L63.5 7 L58 14 Z" fill="#ef4444" {O}/>'
    + shine('M10 28 C11.5 21 16.5 15.5 23 13.5', 2.6, .55))

icons['screen'] = svg(
    lin('sc-b', IRON) + lin('sc-s', ['#8fa2ff', '#5b3fbf', '#1e1450'], 0, 0, 1, 1),
    shadow(32, 60, 16)
    + f'<rect x="27.5" y="44" width="9" height="9" fill="#3a3f52" {O}/>'
    + f'<rect x="17" y="51" width="30" height="6" rx="3" fill="url(#sc-b)" {O}/>'
    + f'<rect x="4" y="7" width="56" height="39" rx="5" fill="url(#sc-b)" {O}/>'
    + '<rect x="9" y="12" width="46" height="29" rx="2" fill="url(#sc-s)" stroke="#0b0a14" stroke-width="1.4"/>'
    + '<path d="M11 39 L32 13 L41 13 L20 39 Z" fill="#fff" opacity=".1"/>'
    + f'<path d="M28 19.5 L40 26.5 L28 33.5 Z" fill="#fff" stroke="#0b0a14" stroke-width="1.6" stroke-linejoin="round"/>')

icons['scroll'] = svg(
    lin('sr-p', PARCH, 0, 0, 1, 0) + lin('sr-r', ['#f7e7bd', '#c9a463', '#8a6a35']) + lin('sr-w', WOOD) + rad('sr-s', [(0, '#ff8a8a'), (.6, '#c81e2c'), (1, '#6b0a14')], .35, .35, .7),
    shadow(32, 60, 22)
    + f'<rect x="13" y="12" width="38" height="40" fill="url(#sr-p)" {O}/>'
    + ''.join(f'<path d="M19 {y} L{e} {y}" stroke="#a5824a" stroke-width="2.6" stroke-linecap="round"/>' for y, e in [(21, 45), (28, 42), (35, 45), (42, 36)])
    + ''.join(f'<rect x="4" y="{y}" width="5" height="10" rx="2" fill="url(#sr-w)" {O}/><rect x="55" y="{y}" width="5" height="10" rx="2" fill="url(#sr-w)" {O}/>'
              f'<rect x="8" y="{y}" width="48" height="10" rx="5" fill="url(#sr-r)" {O}/>' for y in (4, 49))
    + f'<circle cx="45" cy="47" r="6" fill="url(#sr-s)" {O}/>' + '<path d="M45 43.5 L47.5 47 L45 50.5 L42.5 47 Z" fill="#ffd0d0" opacity=".7"/>')

icons['magnifier'] = svg(
    lin('mg-g', GOLD, 0, 0, 1, 1) + rad('mg-l', [(0, '#ffffff', .55), (.7, '#bfe3ff', .3), (1, '#7fb0ff', .45)], .38, .35, .7) + lin('mg-w', WOOD, 0, 0, 1, 0),
    shadow(40, 60, 16)
    + '<g transform="rotate(-45 46 46)">'
    + f'<rect x="41" y="36" width="10" height="24" rx="4" fill="url(#mg-w)" {O}/>'
    + f'<rect x="40" y="34" width="12" height="6" rx="1.5" fill="url(#mg-g)" {O}/></g>'
    + f'<circle cx="26" cy="26" r="20" fill="url(#mg-g)" {O}/>'
    + '<circle cx="26" cy="26" r="14" fill="#14304a" stroke="#14101f" stroke-width="2"/>'
    + '<circle cx="26" cy="26" r="14" fill="url(#mg-l)"/>'
    + shine('M16.5 23 C17.5 19 20.5 16.5 24 15.8', 3, .85))

icons['sparkles'] = svg(
    lin('sp-a', ['#ffffff', '#d8b4fe', '#9333ea'], 0, 0, 1, 1) + glow('sp-g', '#c084fc', .6),
    aura('<circle cx="27" cy="35" r="27" fill="url(#sp-g)"/>')
    + '<path d="M27 8 Q30.5 31.5 54 35 Q30.5 38.5 27 62 Q23.5 38.5 0 35 Q23.5 31.5 27 8 Z" transform="translate(27 35) scale(.88) translate(-27 -35)" fill="url(#sp-a)" ' + O + '/>'
    + '<path d="M50 3 Q51.8 12.2 61 14 Q51.8 15.8 50 25 Q48.2 15.8 39 14 Q48.2 12.2 50 3 Z" fill="url(#sp-a)" ' + O.replace('2.4', '1.8') + '/>'
    + '<path d="M52 44 Q53.2 50.8 60 52 Q53.2 53.2 52 60 Q50.8 53.2 44 52 Q50.8 50.8 52 44 Z" fill="#f3e8ff" ' + O.replace('2.4', '1.6') + '/>')

icons['stairs'] = svg(
    lin('st-s', ['#b3b9c9', '#7b8297', '#4a5064']) + lin('st-t', ['#e8ebf3', '#c2c8d6']) + glow('st-g', '#f5b942', .75),
    shadow(32, 60, 27)
    + ''.join(f'<rect x="{x}" y="{y}" width="{58 - x}" height="{58 - y}" rx="2" fill="url(#st-s)" {O}/>'
              f'<rect x="{x + 1.2}" y="{y + 1.2}" width="{58 - x - 2.4}" height="3.4" rx="1.4" fill="url(#st-t)"/>'
              for x, y in [(6, 46), (19, 34), (32, 22), (45, 10)])
    + fx('<circle cx="51.5" cy="6" r="9" fill="url(#st-g)"/>') + spark(51.5, 5.5, 6, '#fff6d6')
    + '<path d="M12 52 L16 52 M25 40 L29 40 M38 28 L42 28" stroke="#3a3f52" stroke-width="1.4" stroke-linecap="round"/>')

icons['rising-chart'] = svg(
    lin('rc-b', ['#3a4060', '#1c2036']) + lin('rc-l', ['#34d4c3', '#4ade80', '#d9f99d'], 0, 1, 1, 0),
    shadow(32, 60, 26)
    + f'<rect x="4" y="7" width="56" height="49" rx="5" fill="url(#rc-b)" {O}/>'
    + ''.join(f'<path d="M9 {y} L55 {y}" stroke="#ffffff" stroke-opacity=".09" stroke-width="1.2"/>' for y in (18, 29, 40, 51))
    + f'<path d="M10 47 L22 35 L31 40 L47 20" stroke="{INK}" stroke-width="8.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    + '<path d="M10 47 L22 35 L31 40 L47 20" stroke="url(#rc-l)" stroke-width="5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    + f'<path d="M42.5 15 L53.5 12.5 L51 23.5 Z" fill="#d9f99d" {O}/>'
    + ''.join(f'<circle cx="{x}" cy="{y}" r="2.6" fill="#fff" stroke="{INK}" stroke-width="1.4"/>' for x, y in [(22, 35), (31, 40)])
    + spark(54, 7, 4.5, '#fff6d6'))

icons['warning'] = svg(
    lin('wn-a', AMBER, 0, 0, 0, 1) + glow('wn-g', '#f6c453', .4),
    aura('<circle cx="32" cy="36" r="28" fill="url(#wn-g)"/>') + shadow(32, 60, 22)
    + f'<path d="M27.5 9 Q32 1.5 36.5 9 L58.5 49 Q62 56 54 56 L10 56 Q2 56 5.5 49 Z" fill="url(#wn-a)" {O}/>'
    + '<path d="M31 11.5 L11 48" stroke="#fff" stroke-opacity=".6" stroke-width="2.4" stroke-linecap="round"/>'
    + '<path d="M32 22 L32 38" stroke="#2a1a03" stroke-width="6.4" stroke-linecap="round"/>'
    + '<circle cx="32" cy="47" r="3.8" fill="#2a1a03"/>')



# ---- legendary weapons (the DPS icon's easter egg; drawn from the in-game models) ----
W = {}
R = '<g transform="rotate(45 32 32)">'


def bolt(x, y, s=1, col='#a5f3fc'):
    return (f'<path d="M{x} {y} l{-3 * s} {5 * s} l{3 * s} {0.5 * s} l{-2.5 * s} {5 * s}" stroke="{INK}" stroke-width="3.6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path d="M{x} {y} l{-3 * s} {5 * s} l{3 * s} {0.5 * s} l{-2.5 * s} {5 * s}" stroke="{col}" stroke-width="1.8" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


# Thunderfury, Blessed Blade of the Windseeker: two blue-white prongs, one longer, with open air between them all
# the way out; a storm orb crackling at the bottom of the gap; a wide base swept back into spikes, a blue chevron
# collar; a grey collar with bone spurs, a navy wrapped grip, a grey pommel with bone spikes
W['thunderfury'] = svg(
    lin('tf-s', ['#ffffff', '#eef4ff', '#c4d6f7', '#4f7fe0'], 0, 0, 1, 0) + lin('tf-s2', ['#4f7fe0', '#c4d6f7', '#eef4ff', '#ffffff'], 0, 0, 1, 0)
    + lin('tf-b', ['#f4f8ff', '#9cbcf5', '#3b63c4'], 0, 0, 1, 1) + lin('tf-c', ['#93c5fd', '#2563eb', '#1e3a8a'], 0, 0, 1, 1)
    + lin('tf-gr', ['#8a8aa6', '#4a4a66']) + lin('tf-w', ['#2a3f86', '#0f1a40'], 0, 0, 1, 0) + lin('tf-bone', ['#fbf3dc', '#c9b27a'], 0, 0, 1, 0)
    + rad('tf-orb', [(0, '#ffffff'), (.55, '#eef6ff'), (.85, '#7fb0ff'), (1, '#1d4ed8')], .45, .42, .6)
    + glow('tf-a', '#60a5fa', .55) + glow('tf-og', '#dbeafe', 1),
    aura('<circle cx="32" cy="30" r="34" fill="url(#tf-a)"/>') + shadow(30, 64, 16) + R
    + f'<path d="M29.4 31 L29.4 -1 L22.2 28 Z" fill="url(#tf-s)" {O}/>'
    + f'<path d="M34.6 31 L34.6 -11 L41.8 28 Z" fill="url(#tf-s2)" {O}/>'
    + '<path d="M28.4 3 L28.4 27 M35.6 -6 L35.6 27" stroke="#3b82f6" stroke-width="1.8" stroke-linecap="round" opacity=".9"/>'
    + f'<path d="M22.5 26 L41.5 26 L42 33 L47.5 41 L39.5 36.5 L32 39.5 L24.5 36.5 L16.5 41 L22 33 Z" fill="url(#tf-b)" {O}/>'
    + f'<path d="M24.5 36.5 L32 43 L39.5 36.5 L39.5 40 L32 46.5 L24.5 40 Z" fill="url(#tf-c)" stroke="{INK}" stroke-width="1.6" stroke-linejoin="round"/>'
    + '<circle cx="32" cy="29" r="11" fill="url(#tf-og)"/>'
    + f'<circle cx="32" cy="29" r="6.2" fill="url(#tf-orb)" {O}/>'
    + '<path d="M34 23.4 L28.6 29.8 L31.8 29.8 L30 34.8 L35.4 28.2 L32.2 28.2 Z" fill="#1d4ed8" stroke="#0b1e5c" stroke-width=".8" stroke-linejoin="round"/>'
    + f'<rect x="28.6" y="45.5" width="6.8" height="6" rx="1.6" fill="url(#tf-gr)" {O}/>'
    + f'<path d="M28.8 46.5 L23.5 44 L28.8 49 Z M28.8 50 L24 48.8 L28.8 51.5 Z" fill="url(#tf-bone)" stroke="{INK}" stroke-width="1.2" stroke-linejoin="round"/>'
    + f'<rect x="29.8" y="51.5" width="4.4" height="11" fill="url(#tf-w)" {O}/>'
    + '<path d="M29.8 54 L34.2 55.6 M29.8 57 L34.2 58.6 M29.8 60 L34.2 61.6" stroke="#6b8ff0" stroke-width=".9"/>'
    + f'<path d="M30.3 66 L33.7 66 L32 74.5 Z" fill="url(#tf-bone)" stroke="{INK}" stroke-width="1.4" stroke-linejoin="round"/>'
    + f'<path d="M34.6 64 L39.5 67.5 L34 67 Z" fill="url(#tf-bone)" stroke="{INK}" stroke-width="1.2" stroke-linejoin="round"/>'
    + f'<circle cx="32" cy="64.5" r="3.4" fill="url(#tf-gr)" stroke="{INK}" stroke-width="1.6"/></g>'
    + fx(bolt(56, -6) + bolt(8, 20, .9, '#dbeafe') + bolt(62, 30, .8) + bolt(28, -4, .7, '#dbeafe')))

# Sulfuras: a molten obsidian hammer head with fire on top, on a long dark haft
W['sulfuras'] = svg(
    lin('su-h', ['#4a3b3b', '#1f1616', '#0b0707'], 0, 0, 1, 1) + lin('su-m', ['#fff1a8', '#ff9a1f', '#d1330b'], 0, 0, 1, 0)
    + lin('su-f', ['#fff4b0', '#ffb020', '#ff4d0a'], 0, 1, 0, 0) + lin('su-sh', ['#5a4a42', '#221a17'], 0, 0, 1, 0) + lin('su-g', GOLD)
    + glow('su-a', '#ff7a1a', .6),
    aura('<circle cx="34" cy="28" r="34" fill="url(#su-a)"/>') + shadow(26, 64, 16) + R
    + f'<rect x="29" y="14" width="6" height="56" rx="2" fill="url(#su-sh)" {O}/>'
    + ''.join(f'<rect x="27.5" y="{y}" width="9" height="4" rx="1" fill="url(#su-g)" stroke="{INK}" stroke-width="1.6"/>' for y in (30, 50, 64))
    + f'<path d="M24 1 Q32 -5 40 1 L36 4 L28 4 Z" fill="url(#su-f)" {O}/>'
    + f'<path d="M13 4 L51 4 L54 10 L51 17 L13 17 L10 10 Z" fill="url(#su-h)" {O}/>'
    + '<path d="M16 7 L22 10 L19 14 M29 6 L27 11 L31 15 M40 7 L37 11 L42 14 M47 6 L49 11" stroke="url(#su-m)" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
    + '<path d="M10 10 L4 6 L5 14 Z M54 10 L60 6 L59 14 Z" fill="url(#su-h)" stroke="#14101f" stroke-width="1.8" stroke-linejoin="round"/>'
    + f'<path d="M27 17 L37 17 L35 21 L29 21 Z" fill="url(#su-g)" {O}/></g>'
    + fx(f'<path d="M44 2 C40 -6 48 -8 46 -14 C54 -8 56 -2 52 4 C51 0 48 -1 48 3 Z" fill="url(#su-f)" stroke="{INK}" stroke-width="1.8" stroke-linejoin="round"/>'
         f'<path d="M58 10 C56 4 62 2 61 -2 C67 4 67 10 63 14 Z" fill="url(#su-f)" stroke="{INK}" stroke-width="1.6" stroke-linejoin="round"/>'
         + ''.join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#ffd27a"/>' for x, y, r in [(38, -6, 1.4), (64, 22, 1.2), (52, -12, 1)])))

# Ashbringer: a silver cleaver of a blade - a stepped spine, a slanted point, runes down the middle, a pearl set in a
# notch by the hilt - a red-and-gold guard curling up at both ends, a white grip banded red, a gold pommel
W['ashbringer'] = svg(
    lin('ab-s', ['#ffffff', '#e5e9f0', '#a4adbf'], 0, 0, 1, 0) + lin('ab-r', ['#ff9b7a', '#c2261b', '#6b0d0a'], 0, 0, 0, 1)
    + lin('ab-g', GOLD) + lin('ab-w', ['#ffffff', '#cfd6e2'], 0, 0, 1, 0)
    + rad('ab-p', [(0, '#ffffff'), (.6, '#fbf3d5'), (1, '#c9b680')], .38, .35, .7) + glow('ab-a', '#fde68a', .6),
    aura('<circle cx="32" cy="30" r="34" fill="url(#ab-a)"/>') + shadow(30, 64, 16) + R
    + f'<path d="M26 38 L26 35.5 A5.5 5.5 0 0 0 26 24.5 L26 15 L21.5 10.5 L21.5 1 L40 -10 L39.5 38 Z" fill="url(#ab-s)" {O}/>'
    + '<path d="M29.5 35 L29.5 16 L25.5 11.5 L25.5 3 L36.5 -3.5 L36.2 35" stroke="#8a94ab" stroke-width="1.1" fill="none" stroke-linejoin="round"/>'
    + ''.join(f'<path d="{d}" stroke="#4b5568" stroke-width="1.2" fill="none" stroke-linecap="round"/>'
              for d in ('M32.5 30 l1.6 -1.6 l0 3', 'M32.5 24 l2 0 l-1 -2', 'M33.3 18 l0 -2.6 l1.5 1', 'M32.5 11 l1.8 1 l0 -2.2', 'M31.8 4.5 l2 -1 l-0.6 2.2'))
    + f'<circle cx="26" cy="30" r="5" fill="url(#ab-p)" {O}/>'
    + f'<path d="M17 38 L47 38 L47 42.5 L17 42.5 Z" fill="url(#ab-r)" {O}/>'
    + f'<path d="M17 42.5 C12.5 42.5 11.5 38.5 12 33 L15.5 33 C15.5 36 15.5 38 17 38 Z" fill="url(#ab-r)" {O}/>'
    + f'<path d="M47 42.5 C51.5 42.5 52.5 38.5 52 33 L48.5 33 C48.5 36 48.5 38 47 38 Z" fill="url(#ab-r)" {O}/>'
    + '<path d="M12.6 33.6 L15 33.6 M49 33.6 L51.4 33.6 M18 39.2 L46 39.2" stroke="#f5b942" stroke-width="1.4" stroke-linecap="round"/>'
    + f'<rect x="29.5" y="42.5" width="5" height="17" fill="url(#ab-w)" {O}/>'
    + ''.join(f'<rect x="29.5" y="{y}" width="5" height="2.4" fill="url(#ab-r)" stroke="{INK}" stroke-width="1"/>' for y in (46, 51, 56))
    + f'<circle cx="32" cy="63.5" r="4.4" fill="url(#ab-g)" {O}/>'
    + shine('M30.5 61.5 C31 60.6 31.8 60.2 32.6 60.1', 1.4, .9) + '</g>'
    + fx(spark(54, 2, 6) + spark(12, 20, 3.4, '#fff6d6') + spark(60, 34, 2.8, '#fff6d6')))

# Frostmourne: an ice-cold runeblade, a horned skull guard with glowing eyes
W['frostmourne'] = svg(
    lin('fm-s', ['#f0f9ff', '#a5d8f0', '#3f5a73'], 0, 0, 1, 0) + lin('fm-i', ['#7d8597', '#353b4c', '#141722'], 0, 0, 1, 1)
    + lin('fm-gr', ['#3a3f52', '#141722'], 0, 0, 1, 0) + rad('fm-e', [(0, '#ecfeff'), (.4, '#22d3ee'), (1, '#22d3ee', 0)]) + glow('fm-a', '#67e8f9', .5),
    aura('<circle cx="32" cy="30" r="34" fill="url(#fm-a)"/>') + shadow(30, 64, 16) + R
    + f'<path d="M32 -7 L38 0 L38.5 34 L25.5 34 L26 0 Z" fill="url(#fm-s)" {O}/>'
    + ''.join(f'<path d="{d}" stroke="#0e7490" stroke-width="2.6" fill="none" stroke-linecap="round"/><path d="{d}" stroke="#a5f3fc" stroke-width="1.2" fill="none" stroke-linecap="round"/>'
              for d in ('M30 4 L34 6 L30 8', 'M34 12 L30 14 L34 16', 'M30 20 L34 22 L30 24', 'M32 27 L32 31'))
    + f'<path d="M25 36 C15 35 10 40 8 49 C13 44 18 43 23 44 Z" fill="url(#fm-i)" {O}/>'
    + f'<path d="M39 36 C49 35 54 40 56 49 C51 44 46 43 41 44 Z" fill="url(#fm-i)" {O}/>'
    + f'<path d="M22 33 L42 33 Q44 40 39 46 L25 46 Q20 40 22 33 Z" fill="url(#fm-i)" {O}/>'
    + '<ellipse cx="27.8" cy="38.5" rx="3.6" ry="2.6" fill="url(#fm-e)"/><ellipse cx="36.2" cy="38.5" rx="3.6" ry="2.6" fill="url(#fm-e)"/>'
    + '<path d="M28 43 L36 43" stroke="#0b0a14" stroke-width="1.4"/>'
    + f'<rect x="29" y="46" width="6" height="14" fill="url(#fm-gr)" {O}/>'
    + '<path d="M29 49 L35 51 M29 53 L35 55 M29 57 L35 59" stroke="#5c6680" stroke-width="1.1"/>'
    + f'<path d="M32 59 L37 63 L35 66 L32 71 L29 66 L27 63 Z" fill="url(#fm-i)" {O}/></g>'
    + fx(''.join(f'<path d="M{x} {y - r} L{x} {y + r} M{x - r} {y} L{x + r} {y} M{x - r * .7} {y - r * .7} L{x + r * .7} {y + r * .7} M{x - r * .7} {y + r * .7} L{x + r * .7} {y - r * .7}" stroke="#e0f7ff" stroke-width="1.3" stroke-linecap="round"/>'
                 for x, y, r in [(54, 4, 4), (10, 22, 3), (60, 32, 2.4)])))

# Warglaive of Azzinoth: two fel-green crescent blades sweeping up from a dark, toothed grip
def _glaive_half(flip):
    t = (lambda d: d) if not flip else (lambda d: re.sub(r'(-?\d+\.?\d*) (-?\d+\.?\d*)', lambda m: f'{64 - float(m.group(1)):g} {m.group(2)}', d))
    blade = t('M19 33 C12 32 6 28 2.5 21 C0.5 16 -1.5 11 -5 6 C-7.5 16 -7 28 -3 36 C1 43 10 46 19 41 Z')
    edge = t('M-4.2 9 C-6 18 -5.4 28 -1.8 35 C2 41.5 9 44 16 42')
    hole = (61 - 54 if not flip else 54, 37)
    return (f'<path d="{blade}" fill="url(#wg-f)" {O}/>'
            f'<path d="{edge}" stroke="#ecfccb" stroke-width="1.6" fill="none" stroke-linecap="round" opacity=".85"/>'
            f'<path d="{t("M17 34.5 C11 33.5 6 30 3 24")}" stroke="#14532d" stroke-width="1.4" fill="none" stroke-linecap="round"/>'
            f'<circle cx="{(7 if not flip else 57)}" cy="37" r="2.6" fill="#0b1a06" stroke="{INK}" stroke-width="1"/>')


W['warglaive'] = svg(
    lin('wg-f', ['#f7fee7', '#a3e635', '#3f8a12', '#1a3d08'], 0, 0, 1, 1) + lin('wg-i', IRON) + lin('wg-g', GOLD) + glow('wg-a', '#84cc16', .6),
    aura('<ellipse cx="32" cy="30" rx="36" ry="28" fill="url(#wg-a)"/>') + shadow(32, 62, 24)
    + '<g transform="rotate(-14 32 36)">' + _glaive_half(False) + _glaive_half(True)
    + f'<path d="M19 30 L15 24 L22 29 Z M45 30 L49 24 L42 29 Z M19 43 L15 48 L22 43.5 Z M45 43 L49 48 L42 43.5 Z" fill="url(#wg-i)" stroke="{INK}" stroke-width="1.5" stroke-linejoin="round"/>'
    + f'<path d="M19 30 L45 30 L47.5 36.5 L45 43 L19 43 L16.5 36.5 Z" fill="url(#wg-i)" {O}/>'
    + '<path d="M23 34 L41 34 L41 39.5 L23 39.5 Z" fill="#14101f"/>'
    + ''.join(f'<path d="M{x} 34 L{x + 1.3} 37 L{x + 2.6} 34" fill="#d9d2b0"/>' for x in range(24, 40, 3))
    + '<path d="M21 31.8 L43 31.8" stroke="#fff" stroke-opacity=".35" stroke-width="1.2"/></g>'
    + fx(f'<path d="M-2 -4 C-4 -9 1 -11 0 -15 C6 -10 7 -5 3 -1 Z" fill="#a3e635" stroke="{INK}" stroke-width="1.4" stroke-linejoin="round"/>'
         f'<path d="M64 -6 C62 -11 67 -13 66 -17 C72 -12 73 -7 69 -3 Z" fill="#a3e635" stroke="{INK}" stroke-width="1.4" stroke-linejoin="round"/>'
         + ''.join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#d9f99d"/>' for x, y, r in [(10, 4, 1.4), (56, 8, 1.2), (32, 14, 1)])))

# Shadowmourne: an icy saronite double axe, cold runes glowing in its blades, a long dark haft and a soul-gem pommel
W['shadowmourne'] = svg(
    lin('sm-b', ['#e0f2fe', '#60a5fa', '#1e3a8a', '#0b1736'], 0, 0, 1, 1) + lin('sm-h', ['#4a3a3a', '#1a1214'], 0, 0, 1, 0)
    + lin('sm-i', IRON) + lin('sm-g', ['#d6b98a', '#8a6a3a'])
    + rad('sm-o', [(0, '#ecfeff'), (.5, '#22d3ee'), (1, '#0e7490')], .4, .35, .7) + glow('sm-a', '#38bdf8', .5),
    aura('<circle cx="36" cy="26" r="34" fill="url(#sm-a)"/>') + shadow(24, 64, 15) + R
    + f'<rect x="29.6" y="0" width="4.8" height="66" rx="2" fill="url(#sm-h)" {O}/>'
    + ''.join(f'<rect x="28.2" y="{y}" width="7.6" height="3.4" rx="1" fill="url(#sm-g)" stroke="{INK}" stroke-width="1.4"/>' for y in (36, 48, 60))
    + f'<path d="M34 3 C42 1 50 -4 56 -10 C65 2 67 22 58 38 C52 31 44 27 34 25 Z" fill="url(#sm-b)" {O}/>'
    + f'<path d="M30 5 C24 3 18 -1 13 -6 C8 4 8 17 13 27 C17 23 23 20.5 30 20 Z" fill="url(#sm-b)" {O}/>'
    + '<path d="M56 -6 C62 4 63 20 57 33" stroke="#e0f2fe" stroke-width="1.6" fill="none" stroke-linecap="round" opacity=".8"/>'
    + ''.join(f'<path d="{d}" stroke="#0e7490" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
              f'<path d="{d}" stroke="#a5f3fc" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
              for d in ('M41 6 C47 8 51 14 52 22', 'M44 12 L47 10 M46 18 L49.5 17.5', 'M22 6 C18 9 16 14 16 19', 'M20 12 L17.5 10.5'))
    + f'<path d="M32 -12 L35.5 1 L28.5 1 Z" fill="url(#sm-b)" {O}/>'
    + f'<rect x="26.5" y="1" width="11" height="21" rx="2.5" fill="url(#sm-i)" {O}/>'
    + '<circle cx="32" cy="11.5" r="5.5" fill="url(#sm-a)"/>'
    + f'<path d="M32 7.5 L35 11.5 L32 15.5 L29 11.5 Z" fill="url(#sm-o)" stroke="{INK}" stroke-width="1.3" stroke-linejoin="round"/>'
    + f'<circle cx="32" cy="69" r="4" fill="url(#sm-o)" {O}/></g>'
    + fx(''.join(f'<path d="M{x} {y} q3 -4 0 -8 q-3 -4 0 -8" stroke="#a5f3fc" stroke-width="1.6" fill="none" stroke-linecap="round" opacity=".85"/>' for x, y in [(62, 4), (12, 12)])))

# Thori'dal, the Stars' Fury: a dark, ornate bow - a bronze heart set with blue gems, limbs ending in curved
# blue crystal blades - an arrow of starlight nocked
W['thoridal'] = svg(
    lin('td-i', ['#8a93a8', '#3a4055', '#171a26'], 0, 0, 1, 0) + lin('td-b', ['#f6d38b', '#c07a2c', '#6b3a10'], 0, 0, 1, 1)
    + lin('td-c', ['#ecfeff', '#67e8f9', '#0e7490'], 0, 0, 1, 1) + lin('td-l', ['#ffffff', '#bae6fd', '#38bdf8'], 0, 0, 1, 0)
    + rad('td-o', [(0, '#ecfeff'), (.5, '#22d3ee'), (1, '#0e7490')], .4, .35, .7) + glow('td-a', '#67e8f9', .45),
    aura('<circle cx="32" cy="32" r="34" fill="url(#td-a)"/>') + shadow(32, 64, 18) + R
    + '<path d="M30 -3 L30 67" stroke="#e0f2fe" stroke-width="1.4" opacity=".9"/>'
    + f'<path d="M29 -2 C18 6 12 18 13 28 L19 28 C19 18 23 8 31 1 Z" fill="url(#td-i)" {O}/>'
    + f'<path d="M29 66 C18 58 12 46 13 36 L19 36 C19 46 23 56 31 63 Z" fill="url(#td-i)" {O}/>'
    + f'<path d="M28 1 C31 -5 37 -9 44 -10 C40 -6 36 -2 32 5 Z" fill="url(#td-c)" {O}/>'
    + f'<path d="M28 63 C31 69 37 73 44 74 C40 70 36 66 32 59 Z" fill="url(#td-c)" {O}/>'
    + ''.join(f'<circle cx="{x}" cy="{y}" r="2.8" fill="url(#td-o)" stroke="{INK}" stroke-width="1.3"/>' for x, y in [(18.5, 14), (18.5, 50)])
    + f'<path d="M10 24 C6 26 4 29 4 32 C4 35 6 38 10 40 L20 41 C23 38 24 35 24 32 C24 29 23 26 20 23 Z" fill="url(#td-b)" {O}/>'
    + '<path d="M8 26 L3 22 L7 29 Z M8 38 L3 42 L7 35 Z" fill="url(#td-b)" stroke="#14101f" stroke-width="1.3" stroke-linejoin="round"/>'
    + f'<circle cx="14" cy="32" r="4" fill="url(#td-o)" stroke="{INK}" stroke-width="1.5"/>'
    + '<path d="M36 32 L-1 32" stroke="#7dd3fc" stroke-opacity=".35" stroke-width="9" stroke-linecap="round"/>'
    + f'<path d="M36 32 L-1 32" stroke="{INK}" stroke-width="5" stroke-linecap="round"/><path d="M36 32 L-1 32" stroke="url(#td-l)" stroke-width="2.8" stroke-linecap="round"/>'
    + '<path d="M36 32 L41 28 M36 32 L41 36 M32.5 32 L37.5 28 M32.5 32 L37.5 36" stroke="#bae6fd" stroke-width="1.8" stroke-linecap="round"/>'
    + f'<path d="M0 27 L-8 32 L0 37 L-2 32 Z" fill="#ffffff" stroke="{INK}" stroke-width="1.6" stroke-linejoin="round"/></g>'
    + fx(spark(56, 8, 4.4, '#e0f2fe') + spark(4, 10, 5.5) + spark(40, -6, 2.4, '#e0f2fe')))

# Dragonwrath, Tarecgosa's Rest: a great blue orb cradled in curved horn-claws, an amber gem beneath, on a long
# dark staff with an ornate blue foot
W['dragonwrath'] = svg(
    lin('dw-sh', ['#4b3a5e', '#1c1428'], 0, 0, 1, 0) + lin('dw-h', ['#f1f5f9', '#94a3b8', '#475569'], 0, 0, 1, 1)
    + lin('dw-b', ['#c7d2fe', '#4f6bdc', '#1e2a6b'], 0, 0, 1, 1) + lin('dw-g', GOLD)
    + rad('dw-o', [(0, '#ffffff'), (.3, '#bfdbfe'), (.65, '#3b82f6'), (1, '#1e3a8a')], .4, .38, .65)
    + rad('dw-am', [(0, '#fff7cc'), (.5, '#fb923c'), (1, '#9a3412')], .4, .35, .7) + glow('dw-a', '#3b82f6', .65),
    aura('<circle cx="40" cy="22" r="32" fill="url(#dw-a)"/>') + shadow(22, 64, 14) + R
    + f'<rect x="29.8" y="24" width="4.4" height="42" rx="2" fill="url(#dw-sh)" {O}/>'
    + f'<path d="M22 30 L42 30 L39 34 L25 34 Z" fill="url(#dw-b)" {O}/>'
    + f'<rect x="28.5" y="44" width="7" height="3.4" rx="1" fill="url(#dw-g)" stroke="{INK}" stroke-width="1.4"/>'
    + f'<path d="M28 64 L36 64 L39 70 L32 76 L25 70 Z" fill="url(#dw-b)" {O}/>'
    + f'<path d="M24 22 C13 22 7 15 5 6 C11 12 17 14 25 15 Z" fill="url(#dw-h)" {O}/>'
    + f'<path d="M40 22 C51 22 57 15 59 6 C53 12 47 14 39 15 Z" fill="url(#dw-h)" {O}/>'
    + '<circle cx="32" cy="3" r="13" fill="url(#dw-a)"/>'
    + f'<circle cx="32" cy="3" r="9.5" fill="url(#dw-o)" {O}/>'
    + '<path d="M26.5 -1 C27.5 -3.5 29.5 -5 32 -5.5" stroke="#fff" stroke-width="1.8" fill="none" stroke-linecap="round"/>'
    + f'<path d="M25 18 C18 13 18 2 22 -7 C22 -1 24 5 28 10 Z" fill="url(#dw-h)" {O}/>'
    + f'<path d="M39 18 C46 13 46 2 42 -7 C42 -1 40 5 36 10 Z" fill="url(#dw-h)" {O}/>'
    + f'<path d="M24 16 L40 16 L37 25 L27 25 Z" fill="url(#dw-b)" {O}/>'
    + f'<circle cx="32" cy="20" r="3" fill="url(#dw-am)" stroke="{INK}" stroke-width="1.3"/></g>'
    + fx(spark(60, 0, 4, '#dbeafe') + spark(42, -10, 2.6, '#e0e7ff') + spark(68, 20, 2.2, '#dbeafe')))


for _name, _text in W.items():
    icons[f'legendary-{_name}'] = _text


def main():
    from pathlib import Path
    out = Path(__file__).parent / 'icons'
    for old in out.glob('*.svg'):
        old.unlink()
    for name, text in icons.items():
        (out / f'{name}.svg').write_text(text + '\n', encoding='utf-8')
    print(len(icons), 'icons drawn into', out)


if __name__ == '__main__':
    main()
