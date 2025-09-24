# discord_ui.py
# Discord UI components, views, and formatting functions

import asyncio
import time
import discord
import aiohttp
from wcl_api import get_wcl_token, get_fight_details, get_deaths_for_fight
from wcl_web_scraper import get_all_boss_health_for_report, get_boss_health_for_wipe

# --- Helper functions for formatting ---
async def send_ephemeral_with_auto_delete(interaction, content=None, embed=None, view=None, delete_after=600):
    """
    Send an ephemeral message that automatically disappears.
    
    Note: Ephemeral messages are only visible to the user who triggered the interaction
    and automatically disappear when the user refreshes Discord, navigates away, or
    after Discord's built-in timeout (typically 15 minutes).
    
    Args:
        interaction: Discord interaction object
        content: Message content (optional)
        embed: Discord embed (optional)
        view: Discord view with components (optional)
        delete_after: Ignored for ephemeral messages (kept for API compatibility)
    """
    try:
        kwargs = {'ephemeral': True}
        if content is not None:
            kwargs['content'] = content
        if embed is not None:
            kwargs['embed'] = embed
        if view is not None:
            kwargs['view'] = view
        
        if hasattr(interaction, 'followup') and interaction.response.is_done():
            return await interaction.followup.send(**kwargs)
        else:
            await interaction.response.send_message(**kwargs)
            return await interaction.original_response()
        
    except Exception as e:
        print(f"[ERROR] Failed to send ephemeral message: {e}")
        try:
            fallback_kwargs = {'ephemeral': True}
            if content is not None:
                fallback_kwargs['content'] = content
            if embed is not None:
                fallback_kwargs['embed'] = embed
            if view is not None:
                fallback_kwargs['view'] = view
            
            if hasattr(interaction, 'followup') and interaction.response.is_done():
                return await interaction.followup.send(**fallback_kwargs)
            else:
                await interaction.response.send_message(**fallback_kwargs)
                return await interaction.original_response()
        except Exception as fallback_error:
            print(f"[ERROR] Fallback ephemeral message also failed: {fallback_error}")
            return None

async def send_message_with_auto_delete(channel, content=None, embed=None, view=None, delete_after=None):
    """
    Send a regular message that persists in the channel.
    
    Note: This function used to auto-delete messages after 10 minutes, but now
    regular messages are persistent to avoid losing important log information.
    
    Args:
        channel: Discord channel to send to
        content: Message content (optional)
        embed: Discord embed (optional)
        view: Discord view with components (optional)
        delete_after: Deprecated parameter (kept for compatibility, but ignored)
    """
    try:
        kwargs = {}
        if content is not None:
            kwargs['content'] = content
        if embed is not None:
            kwargs['embed'] = embed
        if view is not None:
            kwargs['view'] = view
        
        message = await channel.send(**kwargs)
        print(f"[DEBUG] Sent persistent message to channel {channel.name}")
        return message
        
    except Exception as e:
        print(f"[ERROR] Failed to send message: {e}")
        return None

# --- Data parsing and formatting functions ---
def _find_ranking_list(ranking_data):
    """Extract ranking list from various nested structures."""
    if not ranking_data:
        return None
    
    if isinstance(ranking_data, list):
        return ranking_data
    
    if not isinstance(ranking_data, dict):
        return None
    
    if 'data' in ranking_data:
        potential_list = ranking_data['data']
        if isinstance(potential_list, list):
            return potential_list
        
        if isinstance(potential_list, dict) and 'rankings' in potential_list:
            nested_rankings = potential_list['rankings']
            if isinstance(nested_rankings, list):
                return nested_rankings
            elif isinstance(nested_rankings, dict) and 'data' in nested_rankings:
                triple_nested = nested_rankings['data']
                if isinstance(triple_nested, list):
                    return triple_nested
    
    if 'rankings' in ranking_data:
        potential_rankings = ranking_data['rankings']
        if isinstance(potential_rankings, list):
            return potential_rankings
        elif isinstance(potential_rankings, dict) and 'data' in potential_rankings:
            data_level = potential_rankings['data']
            if isinstance(data_level, list):
                return data_level
    
    return None

def _parse_ranking_data(ranking_data, fight_details=None):
    """Parse WCL ranking data and extract player parse data and roles."""
    parses = {}
    player_roles = {}
    
    # First priority: Check for scraped web data
    if fight_details and 'scraped_parses' in fight_details:
        scraped_data = fight_details['scraped_parses']
        for player_name, player_data in scraped_data.items():
            parses[player_name] = player_data
        return parses, player_roles
    
    # Fallback: Try to parse GraphQL ranking data
    ranking_list = _find_ranking_list(ranking_data)
    
    if ranking_list and len(ranking_list) > 0:
        ranking_record = ranking_list[0]
        if isinstance(ranking_record, dict) and 'roles' in ranking_record:
            roles = ranking_record['roles']
            for role_name, role_data in roles.items():
                _process_role_data(role_name, role_data, parses, player_roles)
    
    return parses, player_roles

def _process_role_data(role_name, role_data, parses, player_roles):
    """Process a single role's data and update parses and player_roles dictionaries."""
    if not isinstance(role_data, dict) or 'characters' not in role_data:
        return
    
    characters = role_data['characters']
    
    role_mapping = {
        'dps': 'dps',
        'healers': 'healer', 
        'tanks': 'tank'
    }
    simplified_role = role_mapping.get(role_name, role_name)
    
    for char in characters:
        if isinstance(char, dict):
            name = char.get('name', 'Unknown')
            parses[name] = char
            player_roles[name] = simplified_role

def _filter_player_entries(sorted_entries, parses, player_roles):
    """Filter table entries to only include actual players, not NPCs/pets."""
    has_any_ranking_data = len(parses) > 0 or len(player_roles) > 0
    
    if has_any_ranking_data:
        player_entries = []
        for entry in sorted_entries:
            name = entry['name']
            if name in parses or name in player_roles:
                player_entries.append(entry)
        return player_entries
    else:
        return _apply_basic_filtering(sorted_entries)

def _apply_basic_filtering(sorted_entries):
    """Apply basic filtering for encounters without ranking data."""
    filtered_entries = []
    npc_keywords = ['totem', 'pet', 'spirit', 'minion', 'guardian', 'elemental', 'wolf', 'mirror image']
    
    for entry in sorted_entries:
        name = entry['name']
        
        if any(keyword in name.lower() for keyword in npc_keywords):
            continue
            
        if entry['total'] < 1000:
            continue
            
        filtered_entries.append(entry)
    
    return filtered_entries

def _extract_role_data_from_playerdetails(player_details_data):
    """Extract the role data structure from nested playerDetails response."""
    if not isinstance(player_details_data, dict):
        return {}
    
    if 'data' in player_details_data:
        data_level = player_details_data['data']
        if isinstance(data_level, dict):
            if 'playerDetails' in data_level:
                return data_level['playerDetails'] if isinstance(data_level['playerDetails'], dict) else {}
            else:
                return data_level
    
    return player_details_data

def _extract_player_roles_from_playerdetails(player_details_data, friendly_players=None):
    """Extract player roles from playerDetails data."""
    player_roles = {}
    role_data = _extract_role_data_from_playerdetails(player_details_data)
    
    role_mapping = {
        'tanks': 'tank',
        'dps': 'dps', 
        'healers': 'healer'
    }
    
    for api_role_name, players_list in role_data.items():
        if api_role_name in role_mapping and isinstance(players_list, list):
            simplified_role = role_mapping[api_role_name]
            
            for player_entry in players_list:
                if isinstance(player_entry, dict) and 'name' in player_entry:
                    player_name = player_entry['name']
                    player_roles[player_name] = simplified_role
    
    return player_roles

def _get_colored_name(name, player_roles):
    """Apply role-based color to player name."""
    player_role = player_roles.get(name, 'unknown')
    
    color_mapping = {
        'dps': '\033[31m',     # Red
        'healer': '\033[32m',  # Green  
        'tank': '\033[34m'     # Blue
    }
    
    if player_role in color_mapping:
        return f"{color_mapping[player_role]}{name}\033[0m"
    else:
        return name

def _format_name_with_padding(colored_name, target_width=20):
    """Format a name with proper padding, accounting for ANSI color codes."""
    if '\033[' in colored_name:
        return colored_name.ljust(target_width + 10)
    else:
        return colored_name.ljust(target_width)

def _get_colored_percentage(percentage_str, percentage_value):
    """Apply color coding to percentage values based on WoW item quality colors."""
    if percentage_value is None:
        return percentage_str.rjust(3)
    
    if percentage_value >= 95:
        return f"\033[33m{percentage_str.rjust(3)}\033[0m"  # Yellow for legendary (95+)
    elif percentage_value >= 75:
        return f"\033[35m{percentage_str.rjust(3)}\033[0m"  # Purple for epic (75+)
    elif percentage_value >= 50:
        return f"\033[34m{percentage_str.rjust(3)}\033[0m"  # Blue for rare (50+)
    elif percentage_value >= 25:
        return f"\033[32m{percentage_str.rjust(3)}\033[0m"  # Green for uncommon (25+)
    else:
        return percentage_str.rjust(3)

def _get_parse_color_hex(percentage_value):
    """Get Discord embed color hex based on parse percentage (WoW quality colors)."""
    if percentage_value is None:
        return None
    
    if percentage_value >= 95:
        return 0xFFD700  # Gold for legendary (95+)
    elif percentage_value >= 75:
        return 0xA335EE  # Purple for epic (75+)  
    elif percentage_value >= 50:
        return 0x0070DD  # Blue for rare (50+)
    elif percentage_value >= 25:
        return 0x1EFF00  # Green for uncommon (25+)
    else:
        return 0x9D9D9D  # Gray for poor/common

def _get_parse_emoji(percentage_value):
    """Get emoji indicator for parse quality."""
    if percentage_value is None:
        return "⚪"
    
    if percentage_value >= 95:
        return "🟡"  # Gold circle for legendary
    elif percentage_value >= 75:
        return "🟣"  # Purple circle for epic
    elif percentage_value >= 50:
        return "🔵"  # Blue circle for rare
    elif percentage_value >= 25:
        return "🟢"  # Green circle for uncommon
    else:
        return "⚫"  # Black circle for poor

def _get_player_percentages(player_parses):
    """Extract parse and ilvl percentages from player parse data."""
    parse_pct = "N/A"
    ilvl_pct = "N/A"
    
    if player_parses and isinstance(player_parses, dict):
        if 'rankPercent' in player_parses and player_parses['rankPercent'] is not None:
            parse_pct = f"{player_parses['rankPercent']:.0f}"
        
        if 'bracketPercent' in player_parses and player_parses['bracketPercent'] is not None:
            ilvl_pct = f"{player_parses['bracketPercent']:.0f}"
        else:
            # Debug: Log when bracketPercent is missing
            player_name = player_parses.get('name', 'Unknown')
            print(f"[DEBUG] Missing bracketPercent for {player_name}: {list(player_parses.keys())}")
    
    return parse_pct, ilvl_pct

def _format_amounts_and_activity(entry, fight_duration_seconds):
    """Format DPS/HPS amounts and activity percentage."""
    amount_per_second = entry['total'] / fight_duration_seconds
    amount_str = f"{amount_per_second / 1_000_000:.2f}m" if amount_per_second >= 1_000_000 else f"{amount_per_second / 1_000:.1f}k"
    amount_str = amount_str.ljust(6)

    total_amount = entry['total']
    if total_amount >= 1_000_000_000:
        amount_total_str = f"{total_amount / 1_000_000_000:.1f}B"
    elif total_amount >= 1_000_000:
        amount_total_str = f"{total_amount / 1_000_000:.1f}M"
    elif total_amount >= 1_000:
        amount_total_str = f"{total_amount / 1_000:.1f}K"
    else:
        amount_total_str = str(total_amount)
    amount_total_str = amount_total_str.ljust(8)

    active_time = entry.get('activeTime', entry.get('uptime', 0))
    if fight_duration_seconds > 0:
        active_percent = (active_time / 1000) / fight_duration_seconds * 100
        active_percent_str = f"{active_percent:.0f}%".rjust(6)
    else:
        active_percent_str = "N/A".rjust(6)
    
    return amount_str, amount_total_str, active_percent_str

def _format_amounts_and_activity_mobile(entry, fight_duration_seconds):
    """Format DPS/HPS amounts and activity percentage for mobile (no padding)."""
    amount_per_second = entry['total'] / fight_duration_seconds
    amount_str = f"{amount_per_second / 1_000_000:.2f}m" if amount_per_second >= 1_000_000 else f"{amount_per_second / 1_000:.1f}k"

    total_amount = entry['total']
    if total_amount >= 1_000_000_000:
        amount_total_str = f"{total_amount / 1_000_000_000:.1f}B"
    elif total_amount >= 1_000_000:
        amount_total_str = f"{total_amount / 1_000_000:.1f}M"
    elif total_amount >= 1_000:
        amount_total_str = f"{total_amount / 1_000:.1f}K"
    else:
        amount_total_str = str(total_amount)

    active_time = entry.get('activeTime', entry.get('uptime', 0))
    if fight_duration_seconds > 0:
        active_percent = (active_time / 1000) / fight_duration_seconds * 100
        active_percent_str = f"{active_percent:.0f}%"
    else:
        active_percent_str = "N/A"
    
    return amount_str, amount_total_str, active_percent_str

def _format_overheal(entry):
    """Calculate and format overheal percentage for healing entries."""
    overheal = entry.get('overheal', 0)
    total_amount = entry['total']
    
    if total_amount > 0:
        overheal_percent = (overheal / (total_amount + overheal)) * 100
        return f"{overheal_percent:.0f}%".rjust(8)
    else:
        return "N/A".rjust(8)

def _format_overheal_mobile(entry):
    """Calculate and format overheal percentage for healing entries (mobile version)."""
    overheal = entry.get('overheal', 0)
    total_amount = entry['total']
    
    if total_amount > 0:
        overheal_percent = (overheal / (total_amount + overheal)) * 100
        return f"{overheal_percent:.0f}%"
    else:
        return "N/A"

def create_mobile_friendly_embed(table_data, ranking_data, fight_details, fight_duration_seconds, metric, boss_health_percentage=None, encounter_name=None):
    """Create a mobile-friendly embed version of the performance data."""
    print(f"[DEBUG] Mobile embed - table_data exists: {table_data is not None}")
    print(f"[DEBUG] Mobile embed - table_data entries: {len(table_data.get('entries', [])) if table_data else 0}")
    print(f"[DEBUG] Mobile embed - ranking_data exists: {ranking_data is not None}")
    
    if not table_data or not table_data.get('entries'):
        print(f"[ERROR] Mobile embed - No table data or entries found")
        embed = discord.Embed(
            title="No Data Found",
            description="No performance data found for this fight.",
            color=0xff6b6b
        )
        return embed
    
    # Create title
    if boss_health_percentage is not None and boss_health_percentage < 100:
        title = f"{metric.upper()} - {encounter_name} Wipe ({boss_health_percentage:.1f}%)"
    else:
        title = f"{metric.upper()} - {encounter_name}" if encounter_name else f"{metric.upper()} Performance"
    
    # Parse data first to get top performer's color
    parses, player_roles = _parse_ranking_data(ranking_data, fight_details)
    
    if not player_roles:
        player_details_data = fight_details.get('playerDetails')
        player_roles = _extract_player_roles_from_playerdetails(player_details_data)

    if fight_duration_seconds <= 0: 
        fight_duration_seconds = 1

    sorted_entries = sorted(table_data.get('entries', []), key=lambda x: x['total'], reverse=True)
    player_entries = _filter_player_entries(sorted_entries, parses, player_roles)

    # Show more players for mobile (same as desktop) but limit to prevent Discord limits
    max_players = 25
    if len(player_entries) > max_players:
        player_entries = player_entries[:max_players]
    
    # Set embed color based on top performer's parse quality
    embed_color = 0x0099ff  # Default blue
    if player_entries:
        top_player_name = player_entries[0]['name']
        top_player_parses = parses.get(top_player_name)
        if top_player_parses:
            top_parse_pct, _ = _get_player_percentages(top_player_parses)
            top_parse_value = int(top_parse_pct) if top_parse_pct != "N/A" and top_parse_pct.isdigit() else None
            parse_color = _get_parse_color_hex(top_parse_value)
            if parse_color:
                embed_color = parse_color
    
    embed = discord.Embed(title=title, color=embed_color)
    
    # Create a clean, aligned table format using Discord's code block formatting
    player_lines = []
    
    for i, entry in enumerate(player_entries):
        name = entry['name']
        player_parses = parses.get(name)
        
        # Get role icon (much clearer than text)
        role = player_roles.get(name, 'unknown')
        role_icons = {
            'tank': '🛡️',
            'healer': '💚', 
            'dps': '⚔️',
            'unknown': '❓'
        }
        role_icon = role_icons.get(role, '❓')
        
        # Get percentages
        parse_pct, ilvl_pct = _get_player_percentages(player_parses)
        
        # Get parse quality indicators with ANSI colors for supported clients
        parse_value = int(parse_pct) if parse_pct != "N/A" and parse_pct.isdigit() else None
        ilvl_value = int(ilvl_pct) if ilvl_pct != "N/A" and ilvl_pct.isdigit() else None
        
        parse_emoji = _get_parse_emoji(parse_value)
        ilvl_emoji = _get_parse_emoji(ilvl_value)
        
        # Format main metric value only (remove total and active)
        amount_per_second = entry['total'] / fight_duration_seconds
        if amount_per_second >= 1_000_000:
            amount_str = f"{amount_per_second / 1_000_000:.1f}M"
        elif amount_per_second >= 1_000:
            amount_str = f"{amount_per_second / 1_000:.0f}K" 
        else:
            amount_str = f"{amount_per_second:.0f}"
        
        # Truncate long names and format with fixed widths for alignment
        display_name = name[:13] if len(name) > 13 else name
        
        # Use the same ANSI color coding as desktop version for consistency
        def get_desktop_ansi_color(parse_val):
            """Same colors as desktop _get_colored_percentage function"""
            if parse_val is None:
                return ""
            elif parse_val >= 95:
                return "\033[33m"  # Yellow for legendary (95+) - same as desktop
            elif parse_val >= 75:
                return "\033[35m"  # Purple for epic (75+) - same as desktop
            elif parse_val >= 50:
                return "\033[34m"  # Blue for rare (50+) - same as desktop
            elif parse_val >= 25:
                return "\033[32m"  # Green for uncommon (25+) - same as desktop
            else:
                return ""  # No color for gray - same as desktop
        
        ansi_color = get_desktop_ansi_color(parse_value)
        ansi_reset = "\033[0m" if ansi_color else ""
        
        # Create aligned format using fixed-width formatting
        rank_str = f"{i+1:2d}"
        name_str = f"{display_name:<11}"  # Shortened to make room for ilvl
        
        # Parse percentage with color
        if parse_pct != "N/A":
            parse_str = f"{ansi_color}{parse_emoji}{parse_pct:>2s}%{ansi_reset}"
        else:
            parse_str = "   --"
        
        # Item level percentage (compact) - always show if available
        if ilvl_pct != "N/A":
            ilvl_color = get_desktop_ansi_color(ilvl_value)
            ilvl_reset = "\033[0m" if ilvl_color else ""
            ilvl_str = f"{ilvl_color}{ilvl_emoji}{ilvl_pct:>2s}%{ilvl_reset}"
        else:
            ilvl_str = "   --"
            
        amount_padded = f"{amount_str:>6s}"
        
        # Add overheal for HPS (compact)
        if metric.upper() == "HPS":
            overheal_str = _format_overheal_mobile(entry)
            overheal_padded = f"{overheal_str:>4s}"
            player_line = f"{rank_str} {role_icon} {name_str} {parse_str} {ilvl_str} {amount_padded} {overheal_padded}"
        else:
            player_line = f"{rank_str} {role_icon} {name_str} {parse_str} {ilvl_str} {amount_padded}"
        
        player_lines.append(player_line)
    
    # Create header with proper alignment to match data columns
    if metric.upper() == "HPS":
        header = " #   Name         Parse  iLvl    HPS  OH%"
        separator = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    else:
        header = " #   Name         Parse  iLvl    DPS"
        separator = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Combine all lines with code block formatting for monospace alignment
    all_lines = [header, separator] + player_lines
    
    # Use ansi code block to potentially support colors on some Discord clients
    content = "```ansi\n" + "\n".join(all_lines) + "\n```"
    
    # Check if content fits in one field (Discord limit is 1024 chars per field)
    if len(content) <= 1020:  # Leave some margin
        embed.add_field(name="📊 Rankings", value=content, inline=False)
    else:
        # Split into chunks if needed
        lines_per_chunk = 20
        chunks = [player_lines[i:i + lines_per_chunk] for i in range(0, len(player_lines), lines_per_chunk)]
        
        for idx, chunk in enumerate(chunks):
            chunk_lines = [header, separator] + chunk
            chunk_content = "```ansi\n" + "\n".join(chunk_lines) + "\n```"
            field_name = "📊 Rankings" if idx == 0 else f"📊 Rankings (Page {idx + 1})"
            embed.add_field(name=field_name, value=chunk_content, inline=False)
    
    # Add footer with legend
    legend_parts = []
    legend_parts.append("🛡️=Tank 💚=Healer ⚔️=DPS")
    legend_parts.append("Parse/iLvl: 🟡95+ 🟣75+ 🔵50+ 🟢25+ ⚫<25")
    
    if len(player_entries) >= max_players:
        legend_parts.append(f"Top {max_players} shown")
    
    embed.set_footer(text=" • ".join(legend_parts))
    
    return embed

def format_merged_table(fight_details, metric, fight_duration_seconds, encounter_name=None, boss_health_percentage=None):
    """Format the main performance table."""
    table_data = fight_details.get('table', {}).get('data', {})
    ranking_data = fight_details.get('rankings') 
    
    # Create header with encounter name and boss health percentage for wipes
    if encounter_name:
        if boss_health_percentage is not None:
            table_title = f"{metric.upper()} on {encounter_name} Wipe ({boss_health_percentage:.2f}%)"
        else:
            table_title = f"{metric.upper()} on {encounter_name}"
    else:
        table_title = metric.upper()
    
    if metric.upper() == "DPS":
        header = "Parse% | Name                 | DPS      | Amount   | Active% | iLvl %"
    else:  # HPS
        header = "Parse% | Name                 | HPS      | Amount   | Overheal | Active% | iLvl %"
    
    lines = [f"```ansi\n{table_title}", "=" * len(table_title), header, "-" * len(header)]

    if not table_data or not table_data.get('entries'):
        return "```No performance data found for this fight.```"

    parses, player_roles = _parse_ranking_data(ranking_data, fight_details)
    
    if not player_roles:
        player_details_data = fight_details.get('playerDetails')
        player_roles = _extract_player_roles_from_playerdetails(player_details_data)

    if fight_duration_seconds <= 0: 
        fight_duration_seconds = 1

    sorted_entries = sorted(table_data.get('entries', []), key=lambda x: x['total'], reverse=True)
    player_entries = _filter_player_entries(sorted_entries, parses, player_roles)

    max_players = 25
    if len(player_entries) > max_players:
        player_entries = player_entries[:max_players]

    for entry in player_entries:
        name = entry['name']
        player_parses = parses.get(name)

        colored_name = _get_colored_name(name, player_roles)
        formatted_name = _format_name_with_padding(colored_name)

        parse_pct, ilvl_pct = _get_player_percentages(player_parses)

        parse_value = int(parse_pct) if parse_pct != "N/A" and parse_pct.isdigit() else None
        ilvl_value = int(ilvl_pct) if ilvl_pct != "N/A" and ilvl_pct.isdigit() else None
        
        parse_pct_display = _get_colored_percentage(parse_pct, parse_value)
        ilvl_pct_display = _get_colored_percentage(ilvl_pct, ilvl_value)

        amount_str, amount_total_str, active_percent_str = _format_amounts_and_activity(
            entry, fight_duration_seconds
        )

        if metric.upper() == "DPS":
            lines.append(f"{parse_pct_display}%   | {formatted_name} | {amount_str} | {amount_total_str} | {active_percent_str} | {ilvl_pct_display}%")
        else:  # HPS
            overheal_str = _format_overheal(entry)
            lines.append(f"{parse_pct_display}%   | {formatted_name} | {amount_str} | {amount_total_str} | {overheal_str} | {active_percent_str} | {ilvl_pct_display}%")

    # Add note if we limited the number of players shown
    has_any_ranking_data = len(parses) > 0 or len(player_roles) > 0
    if has_any_ranking_data:
        total_player_entries = len([entry for entry in sorted_entries if entry['name'] in parses or entry['name'] in player_roles])
    else:
        total_player_entries = len(sorted_entries)
        
    if total_player_entries > max_players:
        lines.append("")
        lines.append(f"(Showing top {max_players} players - {total_player_entries - max_players} more players not shown)")

    lines.append("```")
    return "\n".join(lines)

def _process_death_event(event, players, abilities, fight_start_time, player_roles):
    """Process a single death event and return formatted line."""
    if event.get('type') != 'death':
        return None
    
    target_id = event.get('targetID')
    target_name = players.get(target_id, f'Player{target_id}')
    
    relative_timestamp_ms = event['timestamp'] - fight_start_time
    timestamp_str = time.strftime('%M:%S', time.gmtime(relative_timestamp_ms / 1000))
    
    colored_name = _get_colored_name(target_name, player_roles) if player_roles and target_name in player_roles else target_name
    formatted_name = _format_name_with_padding(colored_name)
    
    killing_ability_id = event.get('killingAbilityGameID')
    ability_name = abilities.get(killing_ability_id, f'Ability{killing_ability_id}' if killing_ability_id else 'Unknown')
    
    return f"{timestamp_str.ljust(9)} | {formatted_name} | {ability_name}"

def format_deaths_table(death_data, fight_start_time, player_roles=None, encounter_name=None):
    """Format the deaths table."""
    events = death_data.get('events', [])
    players = death_data.get('players', {})
    abilities = death_data.get('abilities', {})
    
    table_title = f"Deaths on {encounter_name}" if encounter_name else "Deaths"
    header = "Timestamp | Name                 | Killing Blow"
    lines = [f"```ansi\n{table_title}", "=" * len(table_title), header, "-" * len(header)]
    
    if not events:
        if encounter_name and "Kill" in encounter_name:
            return f"```ansi\nDeaths on {encounter_name}\n{'=' * len(f'Deaths on {encounter_name}')}\n\n🎉 Flawless victory! No player deaths occurred during this fight.\n```"
        else:
            return f"```ansi\nDeaths on {encounter_name if encounter_name else 'Unknown Fight'}\n{'=' * len(f'Deaths on {encounter_name}' if encounter_name else 'Deaths on Unknown Fight')}\n\nNo player deaths found for this fight.\n```"

    max_deaths = 50
    death_lines = []
    
    for event in events[:max_deaths]:
        death_line = _process_death_event(event, players, abilities, fight_start_time, player_roles)
        if death_line:
            death_lines.append(death_line)
    
    if not death_lines:
        return "```No player deaths found for this fight.```"
    
    lines.extend(death_lines)
    
    total_deaths = len([e for e in events if e.get('type') == 'death'])
    if total_deaths > max_deaths:
        lines.append("")
        lines.append(f"(Showing first {max_deaths} deaths - {total_deaths - max_deaths} more deaths occurred)")
    
    lines.append("```")
    return "\n".join(lines)

# --- Discord UI Classes ---
class FightSelect(discord.ui.Select):
    def __init__(self, fights, report_code, metric, boss_health_data=None):
        self.report_code = report_code
        self.metric = metric
        self.fights = {str(f['id']): f for f in fights}
        self.boss_health_data = boss_health_data or {}

        options = []
        wipe_counters = {}
        for fight in fights:
            boss_name = fight['name']
            if fight['kill']:
                label = f"{boss_name} (Kill)"
            else:
                wipe_counters[boss_name] = wipe_counters.get(boss_name, 0) + 1
                
                # Check if we have boss health data for this fight
                fight_id = fight['id']
                if fight_id in self.boss_health_data:
                    boss_health = self.boss_health_data[fight_id]
                    label = f"{boss_name} (Wipe {wipe_counters[boss_name]} - {boss_health:.2f}%)"
                else:
                    label = f"{boss_name} (Wipe {wipe_counters[boss_name]})"
            
            if len(label) > 100: 
                label = label[:97] + "..."
            options.append(discord.SelectOption(label=label, value=str(fight['id'])))
        
        super().__init__(placeholder="Choose a fight...", min_values=1, max_values=1, options=options[:25])
    
    @staticmethod
    async def create_with_boss_health(fights, report_code, metric, session, token):
        """Create a FightSelect with boss health data for wipes."""
        boss_health_data = await get_all_boss_health_for_report(session, report_code)
        return FightSelect(fights, report_code, metric, boss_health_data)

    async def callback(self, interaction: discord.Interaction):
        fight_id = int(self.values[0])
        selected_fight = self.fights[str(fight_id)]
        
        await interaction.response.defer(thinking=True, ephemeral=True)

        async with aiohttp.ClientSession() as session:
            token = await get_wcl_token(session)
            if not token:
                print("[ERROR] Failed to get WCL token in select callback.")
                await interaction.edit_original_response(content="Error: Could not get WCL token.", view=None)
                return

            formatted_table = "An unknown error occurred."
            if self.metric in ["dps", "hps"]:
                encounter_id = selected_fight.get('encounterID')
                difficulty = selected_fight.get('difficulty')

                if not encounter_id or encounter_id == 0:
                    await interaction.edit_original_response(
                        content=f"The selected fight, **{selected_fight['name']}**, does not have rankings available (it may be a trash fight). Please select a boss kill or wipe.",
                        view=None
                    )
                    return

                is_kill = selected_fight.get('kill', False)
                fight_details = await get_fight_details(session, token, self.report_code, fight_id, encounter_id, difficulty, self.metric, is_kill)
                
                if not fight_details:
                    print("[ERROR] get_fight_details returned no data.")
                    await interaction.edit_original_response(content="Could not retrieve data for the selected fight. The API may have returned an error. Please check the bot's console for details.", view=None)
                    return

                fight_duration_seconds = (selected_fight['endTime'] - selected_fight['startTime']) / 1000
                
                # Create encounter name with kill/wipe status
                encounter_name = selected_fight['name']
                boss_health_percentage = None
                
                if selected_fight['kill']:
                    encounter_name += " (Kill)"
                else:
                    # Count wipes for this encounter name in the fights list
                    wipe_count = 1
                    for fight in self.fights.values():
                        if (fight['name'] == selected_fight['name'] and 
                            fight['id'] < selected_fight['id'] and 
                            not fight['kill']):
                            wipe_count += 1
                    
                    # Get boss health percentage for wipes
                    boss_health = None
                    
                    # First try to get it from scraped data if we have fight_details
                    if fight_details and 'scraped_parses' in fight_details:
                        scraped_data = fight_details['scraped_parses']
                        if 'boss_health_percentage' in scraped_data:
                            boss_health = scraped_data['boss_health_percentage']
                            print(f"[DEBUG] Got boss health from scraped data: {boss_health}%")
                    
                    # If no scraped health data, try the dedicated boss health function
                    if boss_health is None:
                        boss_health = await get_boss_health_for_wipe(session, token, self.report_code, fight_id, boss_health_cache=self.boss_health_data)
                    
                    if boss_health is not None:
                        encounter_name += f" Wipe {wipe_count}"
                        boss_health_percentage = boss_health
                    else:
                        encounter_name += f" Wipe {wipe_count}"
                
                formatted_table = format_merged_table(fight_details, self.metric, fight_duration_seconds, encounter_name, boss_health_percentage)
            
            elif self.metric == "deaths":
                print(f"[UI] Getting death details.")
                fight_start_time = selected_fight['startTime']
                death_events = await get_deaths_for_fight(session, token, self.report_code, fight_id)
                
                # Create encounter name with kill/wipe status
                encounter_name = selected_fight['name']
                if selected_fight['kill']:
                    encounter_name += " (Kill)"
                else:
                    # Count wipes for this encounter name in the fights list
                    wipe_count = 1
                    for fight in self.fights.values():
                        if (fight['name'] == selected_fight['name'] and 
                            fight['id'] < selected_fight['id'] and 
                            not fight['kill']):
                            wipe_count += 1
                    
                    # Get boss health percentage for wipes
                    boss_health = await get_boss_health_for_wipe(session, token, self.report_code, fight_id, boss_health_cache=self.boss_health_data)
                    
                    if boss_health is not None:
                        encounter_name += f" Wipe {wipe_count} ({boss_health:.2f}%)"
                    else:
                        encounter_name += f" Wipe {wipe_count}"
                
                # Also get player roles for color coding in deaths table
                encounter_id = selected_fight.get('encounterID')
                difficulty = selected_fight.get('difficulty')
                player_roles = {}
                
                if encounter_id and encounter_id != 0:
                    # Get rankings data to extract player roles
                    is_kill = selected_fight.get('kill', False)
                    fight_details = await get_fight_details(session, token, self.report_code, fight_id, encounter_id, difficulty, "dps", is_kill)
                    if fight_details and fight_details.get('rankings'):
                        # Try to get roles from ranking data first
                        ranking_data = fight_details.get('rankings')
                        parses, player_roles = _parse_ranking_data(ranking_data)
                    
                    # If no ranking data, try to extract roles from playerDetails
                    if not player_roles and fight_details:
                        print("[DEBUG] No ranking data for deaths table, trying playerDetails role groups")
                        player_details_data = fight_details.get('playerDetails')
                        fights_data = fight_details.get('fights', [])
                        friendly_players = fights_data[0].get('friendlyPlayers', []) if fights_data else None
                        player_roles = _extract_player_roles_from_playerdetails(player_details_data, friendly_players)
                        
                        if not player_roles:
                            print("[DEBUG] No spec data available for deaths table - will show names without role colors")
                
                formatted_table = format_deaths_table(death_events, fight_start_time, player_roles, encounter_name)
            
            print("[UI] Data formatted. Checking if mobile-friendly version should be offered.")
            
            # For DPS/HPS data, use mobile-friendly format by default with optional desktop view
            if self.metric in ["dps", "hps"]:
                # Extract the table data from fight_details (same as format_merged_table does)
                table_data = fight_details.get('table', {}).get('data', {}) if fight_details else {}
                ranking_data = fight_details.get('rankings') if fight_details else None
                
                # Create mobile-friendly embed (works well on all devices)
                mobile_embed = create_mobile_friendly_embed(
                    table_data, 
                    ranking_data,
                    fight_details,
                    fight_duration_seconds, 
                    self.metric, 
                    boss_health_percentage, 
                    encounter_name
                )
                
                # Create view with optional desktop format button
                desktop_view = DesktopFormatView(formatted_table)
                await send_ephemeral_with_auto_delete(
                    interaction, 
                    embed=mobile_embed,
                    view=desktop_view
                )
            else:
                # For deaths and other data, use traditional format with length checking
                if len(formatted_table) > 2000:
                    print(f"[UI] Message too long ({len(formatted_table)} chars), truncating.")
                    
                    warning_msg = "\n\n(Table truncated - too many players to display)\n```"
                    max_content_length = 1950 - len(warning_msg)
                    
                    truncated = formatted_table[:max_content_length]
                    last_newline = truncated.rfind('\n')
                    if last_newline > 0:
                        truncated = truncated[:last_newline]
                    
                    if not truncated.endswith('\033[0m'):
                        truncated += '\033[0m'
                    
                    formatted_table = truncated + warning_msg
                    print(f"[UI] Truncated to {len(formatted_table)} characters.")
                    
                    if len(formatted_table) > 2000:
                        print(f"[UI] Still too long after truncation, doing emergency truncation.")
                        formatted_table = formatted_table[:1990] + "\n```"
                
                await send_ephemeral_with_auto_delete(interaction, content=formatted_table)

class DesktopFormatView(discord.ui.View):
    def __init__(self, desktop_table):
        super().__init__(timeout=300)  # 5 minute timeout
        self.desktop_table = desktop_table

    @discord.ui.button(label="�️ Desktop Table View", style=discord.ButtonStyle.secondary, custom_id="desktop_format")
    async def desktop_format_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show traditional desktop table format."""
        print("[UI] Desktop format requested.")
        
        # Check if the message is too long for Discord (2000 character limit)
        formatted_table = self.desktop_table
        if len(formatted_table) > 2000:
            print(f"[UI] Message too long ({len(formatted_table)} chars), truncating.")
            
            warning_msg = "\n\n(Table truncated - too many players to display)\n```"
            max_content_length = 1950 - len(warning_msg)
            
            truncated = formatted_table[:max_content_length]
            last_newline = truncated.rfind('\n')
            if last_newline > 0:
                truncated = truncated[:last_newline]
            
            if not truncated.endswith('\033[0m'):
                truncated += '\033[0m'
            
            formatted_table = truncated + warning_msg
            print(f"[UI] Truncated to {len(formatted_table)} characters.")
            
            if len(formatted_table) > 2000:
                print(f"[UI] Still too long after truncation, doing emergency truncation.")
                formatted_table = formatted_table[:1990] + "\n```"
        
        await send_ephemeral_with_auto_delete(interaction, content=formatted_table)

class LogButtonsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        print("[UI] Persistent LogButtonsView created.")

    def _get_report_code_from_interaction(self, interaction: discord.Interaction) -> str | None:
        try:
            if not interaction.message or not interaction.message.embeds:
                print("[ERROR] Interaction message has no embeds.")
                return None
            
            embed_url = interaction.message.embeds[0].url
            if not embed_url or "warcraftlogs.com/reports/" not in embed_url:
                print(f"[ERROR] Embed URL is invalid or missing: {embed_url}")
                return None

            report_code = embed_url.strip().split('/')[-1]
            if not report_code:
                print("[ERROR] Extracted report code is empty.")
                return None
            
            print(f"[UI] Extracted report code: {report_code}")
            return report_code
        except (IndexError, AttributeError) as e:
            print(f"[ERROR] Failed to extract report code from interaction: {e}")
            return None

    async def show_fight_selection(self, interaction: discord.Interaction, metric: str):
        from wcl_api import get_fights_from_report
        
        print(f"[UI] show_fight_selection called for metric: {metric}")
        
        report_code = self._get_report_code_from_interaction(interaction)
        if not report_code:
            await send_ephemeral_with_auto_delete(
                interaction,
                content="Could not find the report code from the original message. The message might be malformed."
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        async with aiohttp.ClientSession() as session:
            token = await get_wcl_token(session)
            if not token:
                await send_ephemeral_with_auto_delete(interaction, content="Error: Could not get WCL token.")
                return
            
            fights = await get_fights_from_report(session, token, report_code)
            if not fights:
                await send_ephemeral_with_auto_delete(interaction, content="Sorry, no boss encounters found in this log.")
                return
            
            select_view = discord.ui.View(timeout=180)
            
            # Create FightSelect with boss health data for wipes
            fight_select = await FightSelect.create_with_boss_health(fights, report_code, metric, session, token)
            select_view.add_item(fight_select)
            
            await send_ephemeral_with_auto_delete(interaction, content="Please select a fight:", view=select_view)

    @discord.ui.button(label="DPS", style=discord.ButtonStyle.primary, custom_id="dps_button_persistent_final")
    async def dps_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("[UI] DPS button pressed.")
        await self.show_fight_selection(interaction, "dps")

    @discord.ui.button(label="Heal", style=discord.ButtonStyle.success, custom_id="heal_button_persistent_final")
    async def heal_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("[UI] Heal button pressed.")
        await self.show_fight_selection(interaction, "hps")
    
    @discord.ui.button(label="Deaths", style=discord.ButtonStyle.secondary, custom_id="deaths_button_persistent_final")
    async def deaths_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        print("[UI] Deaths button pressed.")
        await self.show_fight_selection(interaction, "deaths")
