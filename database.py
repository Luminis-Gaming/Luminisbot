# database.py
# Database connection and setup functions

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

def get_db_connection():
    """Get a database connection."""
    print("[DEBUG] DB: Getting connection.")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.OperationalError as e:
        print(f"[ERROR] DB: Could not connect to database: {e}")
        return None

def setup_database():
    """Initialize the database schema."""
    print("[DEBUG] DB: Running setup_database.")
    conn = get_db_connection()
    if not conn:
        print("[ERROR] DB: Skipping setup, no connection.")
        return
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS guild_channels (
                guild_id BIGINT PRIMARY KEY,
                channel_id BIGINT NOT NULL,
                last_log_id TEXT
            );
        """)
    conn.commit()
    conn.close()
    print("[DEBUG] DB: Setup complete.")
