#!/usr/bin/env python3
"""
API Key Management Tool
Generates and manages API keys for WoW addon authentication
"""

import os
import sys
import secrets
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# Database connection
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'luminisbot')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD')


def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def generate_api_key():
    """Generate a secure API key"""
    return secrets.token_urlsafe(32)


def create_key(guild_id, notes=None):
    """Create a new API key for a guild"""
    api_key = generate_api_key()
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO api_keys (guild_id, key_hash, is_active, created_at, request_count, notes)
            VALUES (%s, %s, true, NOW(), 0, %s)
            RETURNING id
        """, (guild_id, api_key, notes))
        
        key_id = cursor.fetchone()[0]
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"\n✅ API Key Created Successfully!")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"Key ID:    {key_id}")
        print(f"Guild ID:  {guild_id}")
        print(f"API Key:   {api_key}")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"\n⚠️  IMPORTANT: Save this key securely!")
        print(f"   This key cannot be retrieved later.")
        print(f"   Share this key ONLY with trusted guild members.")
        print(f"\n📋 Usage in WoW Addon:")
        print(f"   1. Open addon: /lb")
        print(f"   2. Go to Settings tab")
        print(f"   3. Enter Guild ID: {guild_id}")
        print(f"   4. Enter API Key: {api_key}")
        print(f"   5. Click Save and Sync")
        print()
        
    except Exception as e:
        print(f"❌ Error creating API key: {e}")
        sys.exit(1)


def list_keys():
    """List all API keys"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                id,
                guild_id,
                CONCAT(SUBSTRING(key_hash, 1, 8), '...') as key_preview,
                is_active,
                created_at,
                last_used,
                request_count,
                notes
            FROM api_keys
            ORDER BY created_at DESC
        """)
        
        keys = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        if not keys:
            print("No API keys found.")
            return
        
        print(f"\n📋 API Keys ({len(keys)} total)")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        for key in keys:
            status = "✅ Active" if key['is_active'] else "❌ Inactive"
            last_used = key['last_used'].strftime('%Y-%m-%d %H:%M') if key['last_used'] else "Never"
            
            print(f"\nID: {key['id']} | Guild: {key['guild_id']} | {status}")
            print(f"  Key: {key['key_preview']}")
            print(f"  Created: {key['created_at'].strftime('%Y-%m-%d %H:%M')}")
            print(f"  Last Used: {last_used} | Requests: {key['request_count']}")
            if key['notes']:
                print(f"  Notes: {key['notes']}")
        
        print()
        
    except Exception as e:
        print(f"❌ Error listing keys: {e}")
        sys.exit(1)


def revoke_key(key_id):
    """Revoke (deactivate) an API key"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE api_keys
            SET is_active = false
            WHERE id = %s
            RETURNING guild_id
        """, (key_id,))
        
        result = cursor.fetchone()
        
        if not result:
            print(f"❌ Key ID {key_id} not found")
            sys.exit(1)
        
        guild_id = result[0]
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"✅ Revoked API key ID {key_id} for guild {guild_id}")
        
    except Exception as e:
        print(f"❌ Error revoking key: {e}")
        sys.exit(1)


def main():
    """Main CLI interface"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Create key:  python manage_api_keys.py create <guild_id> [notes]")
        print("  List keys:   python manage_api_keys.py list")
        print("  Revoke key:  python manage_api_keys.py revoke <key_id>")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "create":
        if len(sys.argv) < 3:
            print("❌ Error: guild_id required")
            print("Usage: python manage_api_keys.py create <guild_id> [notes]")
            sys.exit(1)
        
        guild_id = sys.argv[2]
        notes = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else None
        create_key(guild_id, notes)
        
    elif command == "list":
        list_keys()
        
    elif command == "revoke":
        if len(sys.argv) < 3:
            print("❌ Error: key_id required")
            print("Usage: python manage_api_keys.py revoke <key_id>")
            sys.exit(1)
        
        try:
            key_id = int(sys.argv[2])
        except ValueError:
            print("❌ Error: key_id must be a number")
            sys.exit(1)
        
        revoke_key(key_id)
        
    else:
        print(f"❌ Unknown command: {command}")
        print("Valid commands: create, list, revoke")
        sys.exit(1)


if __name__ == '__main__':
    main()
