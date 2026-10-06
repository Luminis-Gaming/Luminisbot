"""
The player page's Character tab: the in-game character panel - gear down both sides of the character's
render (on a glow in their class colour), weapons underneath - with item level, M+ score and raid progress
on top. Items are quality-coloured tiles with their item level, enchant (or a red "No enchant" where the
logs say one belongs) and gems; each opens on Wowhead. Data: armory.py.
"""
from .. import armory
from .render import CLASS_COLORS, esc

QUALITY_COLORS = {0: '#9d9d9d', 1: '#ffffff', 2: '#1eff00', 3: '#0070dd', 4: '#a335ee', 5: '#ff8000',
                  6: '#e6cc80', 7: '#00ccff'}


def _mplus_color(score):
    """Raider.IO-ish: grey -> green -> blue -> purple -> orange as the score climbs."""
    for limit, color in ((3000, '#ff8000'), (2500, '#a335ee'), (2000, '#0070dd'), (1500, '#1eff00')):
        if score >= limit:
            return color
    return '#9d9d9d'


def _item(item, slot, missing, right=False):
    label = armory.SLOT_NAMES[slot]
    if not item:
        return (f'<div class="ar-item empty{" right" if right else ""}"><span class="ar-icon"></span>'
                f'<span class="ar-text"><span class="ar-name muted">Empty</span><span class="ar-meta">{label}</span></span></div>')
    color = QUALITY_COLORS.get(item['quality'], '#a335ee')
    meta = [label]
    if item['tier']:
        meta.append('<span class="ar-tier" title="Tier set">✦ Tier</span>')
    if item['enchant']:
        text = item['enchant'] if isinstance(item['enchant'], str) else 'Enchanted'
        meta.append(f'<span class="ar-ench" title="{esc(text)}">✧ {esc(text)}</span>')
    elif label in missing:
        meta.append('<span class="ar-bad" title="The logs show this slot unenchanted">No enchant</span>')
    if item['sockets']:
        gems = ''.join('<i class="ar-gem"></i>' for _ in item['gems']) + \
            ''.join('<i class="ar-gem empty"></i>' for _ in range(max(0, item['sockets'] - len(item['gems']))))
        meta.append(f'<span class="ar-gems" title="{len(item["gems"])} of {item["sockets"]} sockets filled">{gems}</span>')
    icon = f'<img src="{esc(item["icon"])}" alt="" loading="lazy">' if item['icon'] else ''
    href = f'https://www.wowhead.com/item={int(item["item_id"])}' if item['item_id'] else '#'
    return (f'<a class="ar-item{" right" if right else ""}" style="--q:{color}" href="{href}" target="_blank" rel="noopener" '
            f'title="{esc(item["name"])} · item level {item["ilvl"] or "?"}">'
            f'<span class="ar-icon">{icon}<b class="ar-ilvl">{item["ilvl"] or ""}</b></span>'
            f'<span class="ar-text"><span class="ar-name">{esc(item["name"])}</span>'
            f'<span class="ar-meta">{" · ".join(meta)}</span></span></a>')


def tab(data, player, stale=False):
    """The Character card. player: analyzer.player_report row (class colour, missing enchants)."""
    info = armory.summary(data)
    gear = armory.items(data)
    render = armory.render_url(data)
    color = CLASS_COLORS.get(player.get('class'), '#9aa1b9')
    missing = set(player.get('missing_enchants') or [])
    left = ''.join(_item(gear.get(s), s, missing) for s in armory.LEFT)
    right = ''.join(_item(gear.get(s), s, missing, right=True) for s in armory.RIGHT)
    weapons = ''.join(_item(gear.get(s), s, missing, right=i == 1) for i, s in enumerate(armory.WEAPONS) if gear.get(s))
    tiles = []
    if info['ilvl']:
        tiles.append(f'<div class="ar-stat"><b>{float(info["ilvl"]):.0f}</b><span>Item level</span></div>')
    if info['mplus']:
        tiles.append(f'<div class="ar-stat"><b style="color:{_mplus_color(info["mplus"])}">{info["mplus"]:.0f}</b>'
                     f'<span>Mythic+ score</span></div>')
    for raid, prog in info['raids']:
        tiles.append(f'<div class="ar-stat"><b>{esc(prog)}</b><span>{esc(raid)}</span></div>')
    who = ' · '.join(esc(x) for x in (info['spec'], info['class'], info['race'], info['realm']) if x)
    guild = f' · &lt;{esc(info["guild"])}&gt;' if info['guild'] else ''
    links = [f'<a class="btn btn-secondary btn-sm" href="{esc(info["raiderio_url"])}" target="_blank" rel="noopener">Raider.IO ↗</a>'
             if info['raiderio_url'] else '']
    realm = armory.realm_slug(info['realm'] or data.get('realm') or '')
    if realm:
        links.append(f'<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener" '
                     f'href="https://www.warcraftlogs.com/character/{armory.REGION}/{esc(realm)}/{esc(player["name"].lower())}">Warcraft Logs ↗</a>')
        links.append(f'<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener" '
                     f'href="https://worldofwarcraft.blizzard.com/en-gb/character/{armory.REGION}/{esc(realm)}/{esc(player["name"].lower())}">Armory ↗</a>')
    model = (f'<img class="ar-render" src="{esc(render)}" alt="{esc(player["name"])}" loading="lazy">' if render else
             f'<div class="ar-noimg">{esc(player["name"][:1])}</div>')
    return f"""
    <div class="card ar-card" style="--c:{color}">
        <div class="ar-head">
            <div><h2 class="ar-title" style="color:{color}">{esc(player['name'])}</h2>
                <p class="muted">{who}{guild}</p></div>
            <div class="ar-stats">{''.join(tiles)}</div>
        </div>
        <div class="ar-doll">
            <div class="ar-col">{left}</div>
            <div class="ar-model">{model}<div class="ar-weapons">{weapons}</div></div>
            <div class="ar-col">{right}</div>
        </div>
        <div class="ar-foot">{''.join(links)}
            <span class="muted small">{'Refreshing in the background - reload in a bit for the latest gear. ' if stale else ''}
            From Blizzard's armory and Raider.IO; kept {armory.FRESH_HOURS} hours.</span></div>
    </div>"""
