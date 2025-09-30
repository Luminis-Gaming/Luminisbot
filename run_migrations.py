"""
Database Migration Runner
Runs on bot startup to ensure all tables exist
"""
import os
import psycopg2
from psycopg2 import sql
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migrations():
    """Create OAuth tables if they don't exist"""
    try:
        # Get database connection details from environment
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST', 'postgres'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'luminisbot'),
            user=os.getenv('DB_USER', 'luminisbot'),
            password=os.getenv('DB_PASSWORD', 'changeme123')
        )
        
        cursor = conn.cursor()
        
        logger.info("[MIGRATIONS] Running database migrations...")
        
        # Create oauth_states table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                id SERIAL PRIMARY KEY,
                state_token TEXT UNIQUE NOT NULL,
                discord_id TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_oauth_states_token ON oauth_states(state_token);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_oauth_states_created ON oauth_states(created_at);
        """)
        
        logger.info("[MIGRATIONS] ✓ oauth_states table ready")
        
        # Create wow_connections table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wow_connections (
                discord_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        logger.info("[MIGRATIONS] ✓ wow_connections table ready")
        
        # Create wow_characters table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wow_characters (
                id SERIAL PRIMARY KEY,
                discord_id TEXT NOT NULL REFERENCES wow_connections(discord_id) ON DELETE CASCADE,
                character_name TEXT NOT NULL,
                realm_name TEXT NOT NULL,
                realm_slug TEXT NOT NULL,
                character_class TEXT,
                character_race TEXT,
                faction TEXT,
                level INTEGER,
                character_id BIGINT,
                item_level INTEGER,
                last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(discord_id, character_name, realm_slug)
            );
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wow_characters_discord ON wow_characters(discord_id);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wow_characters_name ON wow_characters(character_name);
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_wow_characters_realm ON wow_characters(realm_slug);
        """)
        
        logger.info("[MIGRATIONS] ✓ wow_characters table ready")
        
        # Grant permissions
        cursor.execute("""
            GRANT ALL PRIVILEGES ON TABLE oauth_states TO luminisbot;
        """)
        
        cursor.execute("""
            GRANT ALL PRIVILEGES ON TABLE wow_connections TO luminisbot;
        """)
        
        cursor.execute("""
            GRANT ALL PRIVILEGES ON TABLE wow_characters TO luminisbot;
        """)
        
        cursor.execute("""
            GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO luminisbot;
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info("[MIGRATIONS] ✅ All database migrations completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"[MIGRATIONS] ❌ Migration failed: {e}")
        return False

if __name__ == "__main__":
    run_migrations()
