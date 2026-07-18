"""
Mythic+ background work: the deadline watcher.

The loop itself is created in __init__.setup() with discord.ext.tasks so the
bot only needs a single setup() call.
"""
import logging

from psycopg2.extras import RealDictCursor

from . import db
from .service import finalize_event

logger = logging.getLogger(__name__)


async def check_deadlines(client):
    """Finalize every open event whose signup deadline has passed."""
    try:
        conn = db.get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT id, title FROM mplus_events
            WHERE status = 'open'
              AND signup_deadline IS NOT NULL
              AND signup_deadline <= NOW()
        """)
        due = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"[MPLUS] Deadline check query failed: {e}")
        return

    for event in due:
        logger.info(f"[MPLUS] Deadline reached for event {event['id']} "
                    f"('{event['title']}') — forming groups")
        try:
            await finalize_event(client, event['id'])
        except Exception as e:
            logger.error(f"[MPLUS] Finalize failed for event {event['id']}: {e}")
