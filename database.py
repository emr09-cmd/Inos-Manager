import os
import pg8000.dbapi
from datetime import datetime
import logging
from dotenv import load_dotenv

# CRITICAL: Load variables right away before any code runs
load_dotenv()

logger = logging.getLogger(__name__)

TARGET_CHANNEL_ID = 1505597064942325840
TABLE_NAME = f"channel_{TARGET_CHANNEL_ID}"

def get_connection():
    """Establishes a pure-python connection to Supabase's connection pooler."""
    # Using fallback strings just in case .env parsing has a delay
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME", "postgres")
    db_port = int(os.getenv("DB_PORT", 5432))

    if not db_user or not db_host or not db_pass:
        raise ValueError(f"❌ Missing Database Credentials in .env! Host: {db_host}, User: {db_user}")

    return pg8000.dbapi.connect(
        host=db_host,
        user=db_user,
        password=db_pass,
        database=db_name,
        port=db_port
    )

def init_db():
    """Creates the necessary tables directly via connection string on startup."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create dedicated table for this specific channel
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                message_id BIGINT PRIMARY KEY,
                guild_id BIGINT,
                author_id BIGINT,
                author_name TEXT,
                content TEXT,
                timestamp TIMESTAMP WITH TIME ZONE,
                is_bot_reply INT DEFAULT 0
            )
        ''')
        
        # Tracking table for syncing positions
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_sync (
                channel_id BIGINT PRIMARY KEY,
                last_message_id BIGINT
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(f"✅ Database tables verified/created via connection pooler.")
    except Exception as e:
        logger.error(f"❌ DB Initialization failed: {e}")

def save_message(message_id: int, guild_id: int, author_id: int, author_name: str, content: str, timestamp: datetime, is_bot_reply: int = 0):
    """Saves a single message into the dedicated channel table."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        query = f'''
            INSERT INTO {TABLE_NAME} (message_id, guild_id, author_id, author_name, content, timestamp, is_bot_reply)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (message_id) DO NOTHING
        '''
        cursor.execute(query, (message_id, guild_id, author_id, author_name, content, timestamp.isoformat(), is_bot_reply))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error saving message via pooler: {e}")

def get_last_synced_id() -> int:
    """Gets the last sync point from the tracking table."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT last_message_id FROM channel_sync WHERE channel_id = %s", (TARGET_CHANNEL_ID,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"❌ Error reading last sync position: {e}")
        return None

def update_last_synced_id(message_id: int):
    """Updates the last sync position tracking using an upsert query."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        query = '''
            INSERT INTO channel_sync (channel_id, last_message_id)
            VALUES (%s, %s)
            ON CONFLICT (channel_id) DO UPDATE SET last_message_id = EXCLUDED.last_message_id
        '''
        cursor.execute(query, (TARGET_CHANNEL_ID, message_id))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error updating sync position: {e}")

# Initialize tables when imported by your Cog
init_db()