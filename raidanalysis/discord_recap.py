"""
"📊 My performance" - a private, per-player raid recap in Discord.

The button sits on raid events with a linked log (and older log posts). Clicking it replies with an
ephemeral message (only the clicker sees it): one message for the night - the few things to work on and
what went well, picked by coach.py from everything we know (mechanics, priority adds, potion timing,
cooldowns and rotation against the top players, output) and weighted toward the bosses that mattered, a
line per boss, and links to the full pages. The coaching may load the key pulls' focus data from Warcraft
Logs first - Discord shows "thinking" meanwhile.

Players are matched to the log through their linked Battle.net characters
(wow_characters) and the character they signed up with for the event.
"""
import asyncio
import logging
import re
from urllib.parse import quote

import discord

from . import coach, db

logger = logging.getLogger(__name__)

CUSTOM_ID = 'raidanalysis:mine'
DIFFICULTY_NAMES = {1: 'LFR', 3: 'Normal', 4: 'Heroic', 5: 'Mythic'}
_REPORT_CODE_RE = re.compile(r'reports/([A-Za-z0-9]{16})')


# ============================================================================
# Data (no Discord objects - testable on its own)
# ============================================================================

def _player_characters(discord_id, message_id=None):
    """
    Character names (lower-case) that are this Discord user's: their linked characters that nobody
    else plays (shared Battle.net accounts link both people's characters), plus their signup here.
    """
    from .people import own_characters
    rows = db._run("SELECT character_name FROM wow_characters WHERE discord_id = %s",
                   (str(discord_id),), fetch='all')
    signed = []
    if message_id:
        signed = [r['character_name'] for r in db._run("""
            SELECT rs.character_name FROM raid_signups rs JOIN raid_events re ON re.id = rs.event_id
            WHERE re.message_id = %s AND rs.discord_id = %s
        """, (message_id, str(discord_id)), fetch='all')]
    return own_characters(discord_id, [r['character_name'] for r in rows], db.character_owners(), signed)


def _event_log_code(message_id):
    row = db._run("SELECT log_url FROM raid_events WHERE message_id = %s", (message_id,), fetch='one')
    match = _REPORT_CODE_RE.search((row or {}).get('log_url') or '')
    return match.group(1) if match else None


# ============================================================================
# Embeds
# ============================================================================

KIND_ICONS = {'mechanic': '💥', 'death': '💀', 'focus': '🎯', 'reaction': '⏱️', 'potion': '🧪', 'cooldowns': '⚔️',
              'rotation': '🔁', 'uptime': '⏳', 'procs': '♻️', 'active': '⏸️', 'parse': '🏆', 'star': '⭐',
              'prep': '🍲', 'utility': '🛠️', 'kill': '✔️', 'note': '•'}


def _band(score):
    if score >= 80:
        return 'Great', 0x51CF66
    if score >= 60:
        return 'OK', 0xFCC419
    return 'Room to improve', 0xFF6B6B


def _line(insight, multi_boss):
    """One coaching line: icon, the boss when the night had several, the text, a Mythic Trap clip if there is one."""
    line = f'{KIND_ICONS.get(insight["kind"], "•")} ' + (f'**{insight["boss"]}** · ' if multi_boss else '') + insight['text']
    ability = insight.get('ability')
    if ability and insight.get('guide_for'):
        guide = insight['guide_for'](ability['id'], ability['name'])
        if guide and guide.get('video_url'):
            line += f' — [🎞 clip]({guide["embed_url"]})'
    return line


def _field_text(lines, limit=1024):
    out = ''
    for line in lines:
        if len(out) + len(line) + 1 > limit:
            break
        out += line + '\n'
    return out.strip() or '—'


def _boss_line(b):
    diff = DIFFICULTY_NAMES.get(b['difficulty'], b['difficulty'])
    result = '✔' if b['killed'] else '✖'
    progress = '' if b['killed'] or b['best'] is None else f' · best {b["best"]:.1f}%'
    parse = f' · parse **{b["parse"]:.0f}**' if b.get('parse') is not None else ''
    star = f' · ⭐ {b["star"]}' if b.get('star') else ''
    return (f'{result} **{b["name"]}** ({diff}) · {b["pulls"]} pull{"s" if b["pulls"] != 1 else ""}{progress} · '
            f'score **{b["score"]}**{parse}{star}')


def recap_message(recap):
    """(embed, view) for one player's night (coach.night): work on, going well, a line per boss, links."""
    from .web.routes import public_base_url
    report, bosses = recap['report'], recap['bosses']
    main = max(bosses, key=lambda b: b['weight']) if bosses else None
    multi = len(bosses) > 1
    kills, pulls = sum(1 for b in bosses if b['killed']), sum(b['pulls'] for b in bosses)
    parsed = [b for b in bosses if b.get('parse') is not None]
    best = max(parsed, key=lambda b: b['parse']) if parsed else None
    lines = [f'Playing **{recap["character"]}** · {len(bosses)} boss{"es" if len(bosses) != 1 else ""} · '
             f'{kills} kill{"s" if kills != 1 else ""} · {pulls} pull{"s" if pulls != 1 else ""}']
    if best:
        lines.append(f'🏆 Best parse **{best["parse"]:.0f}** on {best["name"]}')
    if recap['other_characters']:
        lines.append(f'Also played: {", ".join(recap["other_characters"])}')
    _, color = _band(main['score']) if main else ('', 0x6D7CFF)
    embed = discord.Embed(title=f'📊 Your night: {report["title"][:200]}',
                          url=f'https://www.warcraftlogs.com/reports/{report["code"]}',
                          description='\n'.join(lines), color=color)
    work = [_line(i, multi) for i in recap['work_on']]
    embed.add_field(name='🔧 Work on', inline=False, value=_field_text(work) if work else
                    'Nothing big stands out — a solid night. 👍')
    good = [_line(i, multi) for i in recap['going_well']]
    if good:
        embed.add_field(name='✨ Going well', value=_field_text(good), inline=False)
    embed.add_field(name='📋 Boss by boss', value=_field_text([_boss_line(b) for b in bosses]), inline=False)
    foot = 'Only you can see this · Score = our mechanics grade · Parse = Warcraft Logs'
    if recap.get('missing'):
        foot += ' · Priority-add tips need Warcraft Logs, which is busy - try again later for those'
    embed.set_footer(text=foot)

    view = discord.ui.View()
    base = public_base_url()
    if base and main:
        url = (f'{base}/raids/report/{report["code"]}/player/{quote(recap["character"])}'
               f'?boss={main["key"][0]}-{main["key"][1]}&tab=damage')
        view.add_item(discord.ui.Button(label=f'My full analysis ({main["name"]})'[:80], emoji='🎯',
                                        style=discord.ButtonStyle.link, url=url))
    night = full_analysis_url(report['code'])
    if night:
        view.add_item(discord.ui.Button(label='Full raid analysis', emoji='⚔️', style=discord.ButtonStyle.link, url=night))
    return embed, view


# ============================================================================
# Button + interaction
# ============================================================================

ERRORS = {
    'no_report': "I couldn't tell which log this message is about.",
    'not_analyzed': "This log hasn't been analyzed yet — new logs are picked up every 10 minutes, try again shortly.",
    'no_raid': 'That log has no raid boss pulls to analyze.',
    'no_characters': ("I don't know which characters are yours yet. Link your Battle.net account with "
                      '`/connectwow` (or **Update Characters** on a raid event) and try again.'),
    'not_in_log': ("None of your linked characters are in this log. If you played an alt, link it with "
                   '`/connectwow` and try again.'),
}


ANALYZE_WAIT_SECONDS = 600   # Discord lets us edit the reply for 15 minutes


async def _analyze_now(code):
    """Run a sync that includes this report (waiting for a sync already in progress). True if it ran."""
    from . import sync
    deadline = asyncio.get_running_loop().time() + ANALYZE_WAIT_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        if not sync._lock.locked():
            if await sync.sync_guild(limit=1, extra_codes=[code]) is not None:
                return True
        await asyncio.sleep(3)
    return False


def _report_code(message):
    for embed in (message.embeds if message else []):
        match = _REPORT_CODE_RE.search(embed.url or '') or _REPORT_CODE_RE.search(embed.description or '')
        if match:
            return match.group(1)
    return None


async def handle_my_analysis(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        message = interaction.message
        code = _report_code(message)
        if not code and message:
            code = await asyncio.to_thread(_event_log_code, message.id)
        if not code:
            await interaction.followup.send(ERRORS['no_report'], ephemeral=True)
            return
        names = await asyncio.to_thread(_player_characters, interaction.user.id, message.id if message else None)
        if not names:
            await interaction.followup.send(ERRORS['no_characters'], ephemeral=True)
            return
        recap = await asyncio.to_thread(coach.night, code, names)  # may load from WCL: 'thinking' meanwhile
        if recap.get('error') == 'not_analyzed':
            # Nothing yet: analyze it now and turn this private reply into the recap when done.
            reply = await interaction.followup.send(
                '⏳ This log hasn\'t been analyzed yet — analyzing it now. This message will turn into your '
                'recap when it\'s ready (usually a minute or two).', ephemeral=True, wait=True)
            ran = await _analyze_now(code)
            recap = await asyncio.to_thread(coach.night, code, names)
            if recap.get('error'):
                from .sync import status
                why = (status.get('last_error') or '') if ran else 'the analysis queue was busy'
                await reply.edit(content=ERRORS.get(recap['error'], ERRORS['not_analyzed'])
                                 + (f'\n-# {why[:300]}' if why else ''))
                return
            embed, view = recap_message(recap)
            await reply.edit(content=None, embed=embed, view=view)
            return
        if recap.get('error'):
            await interaction.followup.send(ERRORS[recap['error']], ephemeral=True)
            return
        embed, view = recap_message(recap)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception:
        logger.exception('[RAIDS] My performance failed')
        await interaction.followup.send('Something went wrong building your analysis — try again in a bit.',
                                        ephemeral=True)


class MyAnalysisButton(discord.ui.Button):
    def __init__(self, row=None):
        super().__init__(label='My performance', emoji='📊', style=discord.ButtonStyle.secondary,
                         custom_id=CUSTOM_ID, row=row)

    async def callback(self, interaction: discord.Interaction):
        await handle_my_analysis(interaction)


class MyAnalysisView(discord.ui.View):
    """Registered once at startup so the button keeps working on old messages after restarts."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MyAnalysisButton())


def full_analysis_url(code):
    """Public, read-only night page (no admin login) - None when the site address isn't known."""
    from .web.routes import public_base_url
    base = public_base_url()
    return f'{base}/raids/report/{code}' if base and code else None


def add_button(view, row=None, code=None, log_url=None):
    """Add 'My performance' (private recap) and, when possible, a 'Full analysis' link to a message view."""
    view.add_item(MyAnalysisButton(row=row))
    if not code and log_url:
        match = _REPORT_CODE_RE.search(log_url)
        code = match.group(1) if match else None
    url = full_analysis_url(code)
    if url:
        view.add_item(discord.ui.Button(label='Full analysis', emoji='⚔️', style=discord.ButtonStyle.link,
                                        url=url, row=row))
    return view
