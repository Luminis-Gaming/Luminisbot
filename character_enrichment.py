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
            enriched['equipped_items'] = equipment.get('equipped_items', [])
        
        # Specializations/Talents
        if isinstance(specializations, dict):
            enriched['sources']['specializations'] = specializations
            enriched['specializations'] = specializations.get('specializations', [])
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
            
            # Talents
            enriched['talents'] = raiderio.get('talents', {})
            
            # URLs
            enriched['raiderio_url'] = raiderio.get('profile_url')
            enriched['thumbnail_url'] = raiderio.get('thumbnail_url')
        
        return enriched


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
