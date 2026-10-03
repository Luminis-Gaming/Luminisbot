"""
"📊 My analysis" - a private, per-player raid recap in Discord.

The button sits on the bot's log posts and on raid events with a linked log.
Clicking it replies with an ephemeral message (only the clicker sees it):
their score, sub-scores and feedback for every boss they pulled that night,
with Mythic Trap clips for the mechanics they struggled with.

Players are matched to the log through their linked Battle.net characters
(wow_characters) and the character they signed up with for the event.
"""
import asyncio
import logging
import re

import discord

from . import analyzer, db, guides

logger = logging.getLogger(__name__)

CUSTOM_ID = 'raidanalysis:mine'
MAX_BOSS_EMBEDS = 4
DIFFICULTY_NAMES = {1: 'LFR', 3: 'Normal', 4: 'Heroic', 5: 'Mythic'}
_REPORT_CODE_RE = re.compile(r'reports/([A-Za-z0-9]{16})')


# ============================================================================
# Data (no Discord objects - testable on its own)
# ============================================================================

def _player_characters(discord_id, message_id=None):
    """Character names (lower-case) linked to a Discord user, plus their signup for this event."""
    rows = db._run("SELECT character_name FROM wow_characters WHERE discord_id = %s",
                   (str(discord_id),), fetch='all')
    names = {r['character_name'].lower() for r in rows}
    if message_id:
        rows = db._run("""
            SELECT rs.character_name FROM raid_signups rs JOIN raid_events re ON re.id = rs.event_id
            WHERE re.message_id = %s AND rs.discord_id = %s
        """, (message_id, str(discord_id)), fetch='all')
        names |= {r['character_name'].lower() for r in rows}
    return names


def _event_log_code(message_id):
    row = db._run("SELECT log_url FROM raid_events WHERE message_id = %s", (message_id,), fetch='one')
    match = _REPORT_CODE_RE.search((row or {}).get('log_url') or '')
    return match.group(1) if match else None


def player_recap(code, character_names):
    """
    {'report', 'character', 'other_characters', 'bosses': [{'name', 'difficulty', 'pulls', 'killed',
    'best', 'row', 'guide_for'}]} for one player in one report, or a dict with only 'error'.
    """
    report = db.get_report(code)
    pulls = db.get_pulls(code) if report else []
    if not pulls:
        return {'error': 'not_analyzed' if not report else 'no_raid'}

    played = {}
    for pull in pulls:
        for p in (pull.get('analysis') or {}).get('players') or []:
            if p['name'].lower() in character_names:
                played[p['name']] = played.get(p['name'], 0) + 1
    if not played:
        return {'error': 'not_in_log', 'report': report}
    character = max(played, key=played.get)

    groups = {}
    for pull in pulls:
        groups.setdefault((pull['encounter_id'], pull['difficulty']), []).append(pull)
    bosses = []
    for (encounter_id, difficulty), boss_pulls in groups.items():
        numbered = [{'number': i, 'kill': p['kill'],
                     'analysis': dict(p['analysis'] or {}, _duration=p['end_ms'] - p['start_ms'])}
                    for i, p in enumerate(boss_pulls, 1)]
        tags, _ = guides.effective_tags(encounter_id)
        row = next((r for r in analyzer.player_report(numbered, tags) if r['name'] == character), None)
        if not row:
            continue
        bosses.append({
            'name': boss_pulls[0]['encounter_name'], 'difficulty': difficulty, 'pulls': len(boss_pulls),
            'killed': any(p['kill'] for p in boss_pulls),
            'best': min((p['fight_pct'] or 0 for p in boss_pulls if not p['kill']), default=None),
            'row': row, 'guide_for': guides.guide_lookup(encounter_id)})
    bosses.sort(key=lambda b: -b['row']['pulls'])
    return {'report': report, 'character': character, 'bosses': bosses,
            'other_characters': sorted(set(played) - {character})}


# ============================================================================
# Embeds
# ============================================================================

def _band(score):
    if score >= 85:
        return 'Great', 0x51CF66
    if score >= 70:
        return 'OK', 0xFCC419
    return 'Room to improve', 0xFF6B6B


def _note_line(note, guide_for):
    icon = {'bad': '⚠️', 'good': '✅', 'info': 'ℹ️'}[note['tone']]
    line = f'{icon} {note["text"]}'
    ability = note.get('ability')
    if ability:
        guide = guide_for(ability['id'], ability['name'])
        if guide and guide.get('video_url'):
            line += f' — [▶ how it works]({guide["embed_url"]})'
    return line


def _field_text(lines, limit=1024):
    out = ''
    for line in lines:
        if len(out) + len(line) + 1 > limit:
            break
        out += line + '\n'
    return out.strip() or '—'


def recap_embeds(recap):
    report = recap['report']
    title = report['title'][:200]
    header = discord.Embed(
        title=f'📊 Your raid: {title}',
        url=f'https://www.warcraftlogs.com/reports/{report["code"]}',
        description=(f'Playing **{recap["character"]}** · {len(recap["bosses"])} '
                     f'boss{"es" if len(recap["bosses"]) != 1 else ""} · '
                     f'{sum(b["row"]["pulls"] for b in recap["bosses"])} pulls'
                     + (f'\nAlso played: {", ".join(recap["other_characters"])}' if recap['other_characters'] else '')),
        color=0x6D7CFF)
    embeds = [header]
    for boss in recap['bosses'][:MAX_BOSS_EMBEDS]:
        row = boss['row']
        label, color = _band(row['score'])
        result = '✔ killed' if boss['killed'] else (f'best {boss["best"]:.1f}%' if boss['best'] is not None else '')
        scores = ' · '.join(f'{name} **{row["scores"][key]:.0f}**' for key, name in
                            (('survival', 'Survival'), ('mechanics', 'Mechanics'), ('potions', 'Potions'))
                            if key in row['scores'])
        embed = discord.Embed(
            title=f'{boss["name"]} ({DIFFICULTY_NAMES.get(boss["difficulty"], boss["difficulty"])}) — '
                  f'{row["score"]}/100 · {label}',
            description=(f'{scores}\n{row["pulls"]} pull{"s" if row["pulls"] != 1 else ""} ({result}) · '
                         f'{row["deaths"]} death{"s" if row["deaths"] != 1 else ""} before the wipe call · '
                         f'potted {row["potion_pulls"]}/{row["pulls"]}'),
            color=color)
        bad = [_note_line(n, boss['guide_for']) for n in row['feedback'] if n['tone'] == 'bad'][:3]
        good = [_note_line(n, boss['guide_for']) for n in row['feedback'] if n['tone'] == 'good'][:3]
        if bad:
            embed.add_field(name='What to work on', value=_field_text(bad), inline=False)
        if good:
            embed.add_field(name='Going well', value=_field_text(good), inline=False)
        if not bad and not good:
            embed.add_field(name='Feedback', value='Nothing stands out — solid night. 👍' if row['score'] >= 70
                            else 'No single thing stands out — see the scores above.', inline=False)
        embeds.append(embed)
    if len(recap['bosses']) > MAX_BOSS_EMBEDS:
        embeds[-1].set_footer(text=f'+{len(recap["bosses"]) - MAX_BOSS_EMBEDS} more bosses not shown')
    else:
        embeds[-1].set_footer(text='Only you can see this · scores compare you with the rest of the raid')
    return embeds


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


async def handle_my_analysis(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        message = interaction.message
        code = None
        for embed in (message.embeds if message else []):
            match = _REPORT_CODE_RE.search(embed.url or '') or _REPORT_CODE_RE.search(embed.description or '')
            if match:
                code = match.group(1)
                break
        if not code and message:
            code = await asyncio.to_thread(_event_log_code, message.id)
        if not code:
            await interaction.followup.send(ERRORS['no_report'], ephemeral=True)
            return
        names = await asyncio.to_thread(_player_characters, interaction.user.id, message.id if message else None)
        if not names:
            await interaction.followup.send(ERRORS['no_characters'], ephemeral=True)
            return
        recap = await asyncio.to_thread(player_recap, code, names)
        if recap.get('error'):
            await interaction.followup.send(ERRORS[recap['error']], ephemeral=True)
            return
        await interaction.followup.send(embeds=recap_embeds(recap), ephemeral=True)
    except Exception:
        logger.exception('[RAIDS] My analysis failed')
        await interaction.followup.send('Something went wrong building your analysis — try again in a bit.',
                                        ephemeral=True)


class MyAnalysisButton(discord.ui.Button):
    def __init__(self, row=None):
        super().__init__(label='My analysis', emoji='📊', style=discord.ButtonStyle.primary,
                         custom_id=CUSTOM_ID, row=row)

    async def callback(self, interaction: discord.Interaction):
        await handle_my_analysis(interaction)


class MyAnalysisView(discord.ui.View):
    """Registered once at startup so the button keeps working on old messages after restarts."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(MyAnalysisButton())


def add_button(view, row=None):
    """Add the 'My analysis' button to an existing message view."""
    view.add_item(MyAnalysisButton(row=row))
    return view
