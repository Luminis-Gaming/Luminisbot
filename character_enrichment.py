"""
Character Enrichment Module
Fetches detailed character information from Blizzard API and Raider.IO
"""

import aiohttp
import asyncio
from datetime import datetime, timedelta
import logging
import os
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# API Configuration
BLIZZARD_CLIENT_ID = os.getenv('BLIZZARD_CLIENT_ID')
BLIZZARD_CLIENT_SECRET = os.getenv('BLIZZARD_CLIENT_SECRET')
RAIDERIO_API_BASE = "https://raider.io/api/v1"

# Item slot mapping for display
ITEM_SLOTS = {
    'HEAD': 'Head',
    'NECK': 'Neck',
    'SHOULDER': 'Shoulder',
    'BACK': 'Back',
    'CHEST': 'Chest',
    'WRIST': 'Wrist',
    'HANDS': 'Hands',
    'WAIST': 'Waist',
    'LEGS': 'Legs',
    'FEET': 'Feet',
    'FINGER_1': 'Ring 1',
    'FINGER_2': 'Ring 2',
    'TRINKET_1': 'Trinket 1',
    'TRINKET_2': 'Trinket 2',
    'MAIN_HAND': 'Main Hand',
    'OFF_HAND': 'Off Hand',
    'TABARD': 'Tabard'
}

# Item quality colors (WoW standard)
QUALITY_COLORS = {
    0: '#9d9d9d',  # Poor (gray)
    1: '#ffffff',  # Common (white)
    2: '#1eff00',  # Uncommon (green)
    3: '#0070dd',  # Rare (blue)
    4: '#a335ee',  # Epic (purple)
    5: '#ff8000',  # Legendary (orange)
    6: '#e6cc80',  # Artifact (gold)
    7: '#00ccff',  # Heirloom (light blue)
}


class CharacterEnricher:
    """Fetches and aggregates character data from multiple sources"""
    
    def __init__(self):
        self.blizzard_token = None
        self.blizzard_token_expires = None
    
    async def get_blizzard_token(self):
        """Get Blizzard API OAuth token"""
        if self.blizzard_token and self.blizzard_token_expires and self.blizzard_token_expires > datetime.now():
            return self.blizzard_token
        
        async with aiohttp.ClientSession() as session:
            auth = aiohttp.BasicAuth(BLIZZARD_CLIENT_ID, BLIZZARD_CLIENT_SECRET)
            try:
                async with session.post(
                    'https://oauth.battle.net/token',
                    data={'grant_type': 'client_credentials'},
                    auth=auth,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.blizzard_token = data['access_token']
                        self.blizzard_token_expires = datetime.now() + timedelta(seconds=data['expires_in'] - 60)
                        logger.info("Obtained new Blizzard API token")
                        return self.blizzard_token
                    else:
                        logger.error(f"Failed to get Blizzard token: {resp.status}")
                        return None
            except Exception as e:
                logger.error(f"Error getting Blizzard token: {e}")
                return None
    
    async def get_character_profile(self, realm: str, name: str, region: str = 'eu') -> Optional[Dict]:
        """Fetch character profile from Blizzard API"""
        token = await self.get_blizzard_token()
        if not token:
            return None
        
        api_base = f"https://{region}.api.blizzard.com"
        namespace = f"profile-{region}"
        url = f"{api_base}/profile/wow/character/{realm.lower()}/{name.lower()}"
        
        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {token}'}
            params = {'namespace': namespace, 'locale': 'en_US'}
            
            try:
                async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(f"Character profile fetch failed for {name}-{realm}: {resp.status}")
                        return None
            except Exception as e:
                logger.error(f"Error fetching character profile: {e}")
                return None
    
    async def get_character_equipment(self, realm: str, name: str, region: str = 'eu') -> Optional[Dict]:
        """Fetch character equipment from Blizzard API"""
        token = await self.get_blizzard_token()
        if not token:
            return None
        
        api_base = f"https://{region}.api.blizzard.com"
        namespace = f"profile-{region}"
        url = f"{api_base}/profile/wow/character/{realm.lower()}/{name.lower()}/equipment"
        
        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {token}'}
            params = {'namespace': namespace, 'locale': 'en_US'}
            
            try:
                async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(f"Equipment fetch failed for {name}-{realm}: {resp.status}")
                        return None
            except Exception as e:
                logger.error(f"Error fetching equipment: {e}")
                return None
    
    async def get_character_specializations(self, realm: str, name: str, region: str = 'eu') -> Optional[Dict]:
        """Fetch character specializations/talents from Blizzard API"""
        token = await self.get_blizzard_token()
        if not token:
            return None
        
        api_base = f"https://{region}.api.blizzard.com"
        namespace = f"profile-{region}"
        url = f"{api_base}/profile/wow/character/{realm.lower()}/{name.lower()}/specializations"
        
        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {token}'}
            params = {'namespace': namespace, 'locale': 'en_US'}
            
            try:
                async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(f"Specializations fetch failed for {name}-{realm}: {resp.status}")
                        return None
            except Exception as e:
                logger.error(f"Error fetching specializations: {e}")
                return None
    
    async def get_mythic_plus_profile(self, realm: str, name: str, region: str = 'eu') -> Optional[Dict]:
        """Fetch M+ profile from Blizzard API"""
        token = await self.get_blizzard_token()
        if not token:
            return None
        
        api_base = f"https://{region}.api.blizzard.com"
        namespace = f"profile-{region}"
        url = f"{api_base}/profile/wow/character/{realm.lower()}/{name.lower()}/mythic-keystone-profile"
        
        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {token}'}
            params = {'namespace': namespace, 'locale': 'en_US'}
            
            try:
                async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        # M+ profile might not exist if character hasn't done any M+
                        return None
            except Exception as e:
                logger.error(f"Error fetching M+ profile: {e}")
                return None
    
    async def get_character_media(self, realm: str, name: str, region: str = 'eu') -> Optional[Dict]:
        """Fetch character media (render, avatar) from Blizzard API"""
        token = await self.get_blizzard_token()
        if not token:
            return None
        
        api_base = f"https://{region}.api.blizzard.com"
        namespace = f"profile-{region}"
        url = f"{api_base}/profile/wow/character/{realm.lower()}/{name.lower()}/character-media"
        
        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {token}'}
            params = {'namespace': namespace, 'locale': 'en_US'}
            
            try:
                async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        return None
            except Exception as e:
                logger.error(f"Error fetching character media: {e}")
                return None
    
    async def get_raiderio_profile(self, realm: str, name: str, region: str = 'eu') -> Optional[Dict]:
        """Fetch character profile from Raider.IO"""
        url = f"{RAIDERIO_API_BASE}/characters/profile"
        params = {
            'region': region,
            'realm': realm,
            'name': name,
            'fields': 'mythic_plus_scores_by_season:current,mythic_plus_best_runs,raid_progression,gear,guild,talents'
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        logger.warning(f"Raider.IO fetch failed for {name}-{realm}: {resp.status}")
                        return None
            except Exception as e:
                logger.error(f"Error fetching from Raider.IO: {e}")
                return None
    
    async def fetch_item_icon(self, media_href: str) -> Optional[str]:
        """Fetch item icon URL from Blizzard item media endpoint"""
        token = await self.get_blizzard_token()
        if not token:
            return None
        
        async with aiohttp.ClientSession() as session:
            headers = {'Authorization': f'Bearer {token}'}
            
            try:
                async with session.get(media_href, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # Find the icon asset
                        for asset in data.get('assets', []):
                            if asset.get('key') == 'icon':
                                return asset.get('value')
                        return None
                    else:
                        return None
            except Exception as e:
                logger.debug(f"Error fetching item icon: {e}")
                return None
    
    async def enrich_character(self, realm: str, name: str, region: str = 'eu') -> Dict[str, Any]:
        """
        Fetch all data for a character from multiple sources
        Returns aggregated character data
        """
        logger.info(f"Enriching character: {name}-{realm} ({region})")
        
        # Fetch all data in parallel
        results = await asyncio.gather(
            self.get_character_profile(realm, name, region),
            self.get_character_equipment(realm, name, region),
            self.get_character_specializations(realm, name, region),
            self.get_mythic_plus_profile(realm, name, region),
            self.get_character_media(realm, name, region),
            self.get_raiderio_profile(realm, name, region),
            return_exceptions=True
        )
        
        profile, equipment, specializations, mythic_plus, media, raiderio = results
        
        # Aggregate data
        enriched = {
            'character_name': name,
            'realm': realm,
            'region': region,
            'timestamp': datetime.now().isoformat(),
            'sources': {}
        }
        
        # Blizzard Profile Data
        if isinstance(profile, dict):
            enriched['sources']['blizzard_profile'] = profile
            enriched['active_spec'] = profile.get('active_spec', {}).get('name')
            enriched['achievement_points'] = profile.get('achievement_points')
            enriched['faction'] = profile.get('faction', {}).get('name')
            enriched['character_class'] = profile.get('character_class', {}).get('name')
            enriched['level'] = profile.get('level')
            enriched['average_item_level'] = profile.get('average_item_level')
            enriched['equipped_item_level'] = profile.get('equipped_item_level')
            enriched['gender'] = profile.get('gender', {}).get('name')
            enriched['race'] = profile.get('race', {}).get('name')
            
            # Covenant info (if available)
            if 'covenant_progress' in profile:
                enriched['covenant'] = profile['covenant_progress'].get('chosen_covenant', {}).get('name')
                enriched['renown'] = profile['covenant_progress'].get('renown_level')
        
        # Equipment Data
        if isinstance(equipment, dict):
            enriched['sources']['equipment'] = equipment
            equipped_items = equipment.get('equipped_items', [])
            
            # Fetch icon URLs for each item (in parallel)
            if equipped_items:
                icon_tasks = []
                for item in equipped_items:
                    if item.get('media') and item['media'].get('key', {}).get('href'):
                        icon_tasks.append(self.fetch_item_icon(item['media']['key']['href']))
                    else:
                        icon_tasks.append(asyncio.sleep(0))  # placeholder task
                
                icon_results = await asyncio.gather(*icon_tasks, return_exceptions=True)
                
                # Attach icon URLs to items
                for i, item in enumerate(equipped_items):
                    if i < len(icon_results) and isinstance(icon_results[i], str):
                        item['icon_url'] = icon_results[i]
            
            enriched['equipped_items'] = equipped_items
        
        # Specializations/Talents
        if isinstance(specializations, dict):
            enriched['sources']['specializations'] = specializations
            enriched['specializations'] = specializations.get('specializations', [])
            enriched['active_specialization'] = specializations.get('active_specialization', {})
            enriched['active_specialization'] = specializations.get('active_specialization', {})
        
        # M+ Data from Blizzard
        if isinstance(mythic_plus, dict):
            enriched['sources']['mythic_plus_blizzard'] = mythic_plus
            enriched['mythic_plus_season'] = mythic_plus.get('current_period', {})
        
        # Character Media
        if isinstance(media, dict):
            enriched['sources']['media'] = media
            assets = media.get('assets', [])
            for asset in assets:
                if asset.get('key') == 'main-raw':
                    enriched['character_render_url'] = asset.get('value')
                elif asset.get('key') == 'avatar':
                    enriched['avatar_url'] = asset.get('value')
        
        # Raider.IO Data
        if isinstance(raiderio, dict):
            enriched['sources']['raiderio'] = raiderio
            
            # M+ Scores
            scores = raiderio.get('mythic_plus_scores_by_season', [{}])[0] if raiderio.get('mythic_plus_scores_by_season') else {}
            enriched['mythic_plus_score'] = scores.get('scores', {}).get('all', 0)
            enriched['mythic_plus_score_tank'] = scores.get('scores', {}).get('tank', 0)
            enriched['mythic_plus_score_healer'] = scores.get('scores', {}).get('healer', 0)
            enriched['mythic_plus_score_dps'] = scores.get('scores', {}).get('dps', 0)
            
            # Raid Progress
            raid_prog = raiderio.get('raid_progression', {})
            enriched['raid_progression'] = raid_prog
            
            # Best M+ Runs
            enriched['mythic_plus_best_runs'] = raiderio.get('mythic_plus_best_runs', [])
            
            # Gear
            gear = raiderio.get('gear', {})
            enriched['item_level_equipped'] = gear.get('item_level_equipped')
            enriched['item_level_total'] = gear.get('item_level_total')
            
            # Talents - Raider.IO uses 'talentLoadout' (not 'talents'!)
            talents_data = raiderio.get('talents') or raiderio.get('talentLoadout')
            enriched['talents'] = talents_data
            
            # Debug log for talents
            if talents_data:
                logger.info(f"Fetched talents for {name}")
            else:
                logger.warning(f"No talents found in Raider.IO data for {name}")
            
            # URLs
            enriched['raiderio_url'] = raiderio.get('profile_url')
            enriched['thumbnail_url'] = raiderio.get('thumbnail_url')
        
        return enriched


def generate_simc_string(character_data: Dict[str, Any]) -> str:
    """
    Generate a SimulationCraft import string from character data.
    Format based on SimC's addon string format compatible with raidbots.com.
    """
    from datetime import datetime
    
    lines = []
    
    # Character name and server
    name = character_data.get('character_name', 'Unknown')
    realm = character_data.get('realm', 'Unknown')
    region = character_data.get('region', 'EU')
    if isinstance(region, str):
        region = region.upper()
    else:
        region = 'EU'
    
    # Basic character info
    char_class = character_data.get('character_class', 'Unknown')
    race = character_data.get('race', 'Unknown')
    level = character_data.get('level', 70)
    
    # Spec and role
    spec = character_data.get('active_spec', 'Unknown')
    active_spec_data = character_data.get('active_specialization', {})
    
    # Ensure active_spec_data is a dict
    if not isinstance(active_spec_data, dict):
        active_spec_data = {}
    
    # Get spec name safely
    spec_name = spec
    spec_info = active_spec_data.get('specialization', {})
    if isinstance(spec_info, dict):
        spec_name = spec_info.get('name', spec)
    
    # Get role from specialization
    role = 'AUTO'
    role_info = active_spec_data.get('role', {})
    if isinstance(role_info, dict):
        role = role_info.get('type', 'AUTO')
    
    role_clean = role.lower() if role != 'AUTO' else 'auto'
    # Map DPS to proper role names for SimC
    if role_clean == 'dps':
        # SimC expects 'attack' or 'spell', but for compatibility, we can leave as 'dps'
        # However, tank/healer specs should use the proper role name
        role_clean = 'dps'
    elif role_clean == 'healing':
        role_clean = 'healer'
    
    # SimC header - ensure all values are strings
    class_clean = char_class.lower().replace(' ', '') if isinstance(char_class, str) else 'unknown'
    race_clean = race.lower().replace(' ', '_') if isinstance(race, str) else 'unknown'
    realm_clean = realm.lower().replace(' ', '_').replace("'", '') if isinstance(realm, str) else 'unknown'
    spec_clean = spec_name.lower().replace(' ', '_') if isinstance(spec_name, str) else 'unknown'
    
    # Add header comment (like official SimC addon)
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines.append(f"# {name} - {spec_name} - {timestamp} - {region}/{realm}")
    lines.append("")
    
    lines.append(f'{class_clean}="{name}"')
    lines.append(f"level={level}")
    lines.append(f"race={race_clean}")
    lines.append(f"region={region.lower()}")
    lines.append(f"server={realm_clean}")
    lines.append(f"role={role_clean}")
    lines.append(f"spec={spec_clean}")
    
    # Talents - use loadout string if available (CRITICAL for raidbots.com)
    talent_loadout = None
    
    # Try to get from active_specialization loadout_code
    if isinstance(active_spec_data, dict):
        if 'loadout_code' in active_spec_data:
            talent_loadout = active_spec_data['loadout_code']
        elif 'talent_loadout_code' in active_spec_data:
            talent_loadout = active_spec_data['talent_loadout_code']
    
    # Try from Raider.IO talents data (most reliable source)
    if not talent_loadout:
        raiderio_talents = character_data.get('talents')
        
        # Handle different Raider.IO response structures
        if isinstance(raiderio_talents, dict):
            # New structure: single talentLoadout object with loadout_text
            talent_loadout = raiderio_talents.get('loadout_text') or raiderio_talents.get('talentLoadoutString')
        elif isinstance(raiderio_talents, list) and len(raiderio_talents) > 0:
            # Old structure: array of loadouts
            for loadout in raiderio_talents:
                if isinstance(loadout, dict):
                    # Look for active loadout first
                    if loadout.get('active'):
                        talent_loadout = loadout.get('loadout_text') or loadout.get('talent_string')
                        if talent_loadout:
                            break
            # If no active loadout found, use the first one
            if not talent_loadout and raiderio_talents:
                first_loadout = raiderio_talents[0]
                if isinstance(first_loadout, dict):
                    talent_loadout = first_loadout.get('loadout_text') or first_loadout.get('talent_string')
    
    if talent_loadout:
        lines.append("")
        lines.append(f"talents={talent_loadout}")
    else:
        # Log warning if no talents found (important for debugging)
        logger.warning(f"No talent loadout found for {name}. SimC string may be incomplete for raidbots.com")
    
    # Add blank line before equipment
    lines.append("")
    
    # Equipment
    equipped_items = character_data.get('equipped_items', [])
    if isinstance(equipped_items, list):
        # Slot mapping for SimC
        slot_map = {
            'HEAD': 'head',
            'NECK': 'neck',
            'SHOULDER': 'shoulder',
            'BACK': 'back',
            'CHEST': 'chest',
            'WRIST': 'wrist',
            'HANDS': 'hands',
            'WAIST': 'waist',
            'LEGS': 'legs',
            'FEET': 'feet',
            'FINGER_1': 'finger1',
            'FINGER_2': 'finger2',
            'TRINKET_1': 'trinket1',
            'TRINKET_2': 'trinket2',
            'MAIN_HAND': 'main_hand',
            'OFF_HAND': 'off_hand'
        }
        
        for item in equipped_items:
            if not isinstance(item, dict):
                continue
                
            slot_info = item.get('slot', {})
            if not isinstance(slot_info, dict):
                continue
                
            slot_type = slot_info.get('type')
            simc_slot = slot_map.get(slot_type)
            
            if not simc_slot:
                continue
            
            # Item ID and bonus IDs
            item_info = item.get('item', {})
            if not isinstance(item_info, dict):
                continue
                
            item_id = item_info.get('id', 0)
            item_name = item.get('name', 'Unknown Item')
            item_level = item.get('level', {})
            if isinstance(item_level, dict):
                ilvl = item_level.get('value', 0)
            else:
                ilvl = item_level if isinstance(item_level, int) else 0
            
            bonus_ids = []
            
            # Bonus list
            if 'bonus_list' in item and isinstance(item['bonus_list'], list):
                bonus_ids = item['bonus_list']
            
            # Enchantments
            enchant_id = 0
            if 'enchantments' in item and isinstance(item['enchantments'], list):
                for enchant in item['enchantments']:
                    if isinstance(enchant, dict) and enchant.get('enchantment_id'):
                        enchant_id = enchant['enchantment_id']
                        break
            
            # Gems/Sockets
            gem_ids = []
            if 'sockets' in item and isinstance(item['sockets'], list):
                for socket in item['sockets']:
                    if isinstance(socket, dict) and socket.get('item'):
                        socket_item = socket['item']
                        if isinstance(socket_item, dict):
                            gem_ids.append(socket_item.get('id', 0))
            
            # Add item comment (like official SimC addon)
            lines.append(f"# {item_name} ({ilvl})")
            
            # Build item string
            item_str = f"{simc_slot}=,id={item_id}"
            
            # Add enchant_id BEFORE gem_id (official SimC addon order)
            if enchant_id:
                item_str += f",enchant_id={enchant_id}"
            
            # Add gem_id before bonus_id (SimC addon order)
            if gem_ids:
                item_str += f",gem_id={'/'.join(map(str, gem_ids))}"
            
            if bonus_ids:
                item_str += f",bonus_id={'/'.join(map(str, bonus_ids))}"
            
            # Add crafted stats if this is a crafted item
            if 'modified_crafting_stat' in item:
                crafted_stats = []
                modified_stats = item.get('modified_crafting_stat', [])
                if isinstance(modified_stats, list):
                    for stat in modified_stats:
                        if not isinstance(stat, dict):
                            continue
                        stat_type = stat.get('type', {})
                        if isinstance(stat_type, dict):
                            stat_id = stat_type.get('id')
                            if stat_id:
                                crafted_stats.append(str(stat_id))
                if crafted_stats:
                    item_str += f",crafted_stats={'/'.join(crafted_stats)}"
            
            # Add crafting quality if available
            if 'crafting_quality' in item:
                quality_info = item.get('crafting_quality', {})
                if isinstance(quality_info, dict):
                    quality = quality_info.get('id', 0)
                    if quality:
                        item_str += f",crafting_quality={quality}"
            
            lines.append(item_str)
    
    # Join all lines
    simc_string = "\n".join(lines)
    
    return simc_string


async def generate_simc_for_character(character_id: int, realm: str, name: str, region: str = 'eu') -> Optional[str]:
    """
    Generate SimC string for a character, fetching data if necessary
    """
    from database import get_db_connection
    
    # Try to get cached data first
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT enrichment_cache, last_enriched
                FROM wow_characters
                WHERE id = %s
            """, (character_id,))
            result = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if result and result[0]:
                # Check if cache is fresh (less than 6 hours old)
                cache_data, last_enriched = result
                if last_enriched:
                    age = datetime.now() - last_enriched
                    if age < timedelta(hours=6):
                        # Use cached data
                        return generate_simc_string(cache_data)
        except Exception as e:
            logger.error(f"Error checking cache: {e}")
            if conn:
                conn.close()
    
    # Fetch fresh data
    enricher = CharacterEnricher()
    data = await enricher.enrich_character(realm, name, region)
    
    if not data:
        return None
    
    return generate_simc_string(data)


async def enrich_and_cache_character(character_id: int, realm: str, name: str, region: str = 'eu'):
    """
    Enrich character data and store in database
    """
    from database import get_db_connection
    
    enricher = CharacterEnricher()
    data = await enricher.enrich_character(realm, name, region)
    
    # Store in database
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to get database connection")
        return None
    
    try:
        cursor = conn.cursor()
        
        # Build raid progress JSON
        raid_progress_json = json.dumps(data.get('raid_progression', {}))
        
        cursor.execute("""
            UPDATE wow_characters
            SET 
                mythic_plus_score = %s,
                mythic_plus_score_tank = %s,
                mythic_plus_score_healer = %s,
                mythic_plus_score_dps = %s,
                raid_progress_current = %s,
                achievement_points = %s,
                active_spec = %s,
                covenant = %s,
                renown = %s,
                raiderio_url = %s,
                character_render_url = %s,
                enrichment_cache = %s,
                last_enriched = NOW(),
                item_level = %s
            WHERE id = %s
        """, (
            data.get('mythic_plus_score'),
            data.get('mythic_plus_score_tank'),
            data.get('mythic_plus_score_healer'),
            data.get('mythic_plus_score_dps'),
            raid_progress_json,
            data.get('achievement_points'),
            data.get('active_spec'),
            data.get('covenant'),
            data.get('renown'),
            data.get('raiderio_url'),
            data.get('character_render_url'),
            json.dumps(data),
            data.get('equipped_item_level'),
            character_id
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Successfully enriched and cached character {name} (ID: {character_id})")
        return data
        
    except Exception as e:
        logger.error(f"Error caching character data: {e}")
        if conn:
            conn.rollback()
        return None
