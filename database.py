import os
import pg8000.dbapi
from datetime import datetime
import logging
import json
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TARGET_CHANNEL_ID = 1505597064942325840
TABLE_NAME = f"channel_{TARGET_CHANNEL_ID}"

def get_connection():
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME", "postgres")
    db_port = int(os.getenv("DB_PORT", 5432))
    if not db_user or not db_host or not db_pass:
        raise ValueError(f"❌ Missing Database Credentials in .env!")
    return pg8000.dbapi.connect(
        host=db_host,
        user=db_user,
        password=db_pass,
        database=db_name,
        port=db_port
    )

def init_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channel_sync (
                channel_id BIGINT PRIMARY KEY,
                last_message_id BIGINT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                nickname TEXT,
                personality JSONB DEFAULT '{}',
                favorites JSONB DEFAULT '{}',
                dislikes TEXT[] DEFAULT '{}',
                projects TEXT[] DEFAULT '{}',
                known_friends TEXT[] DEFAULT '{}',
                running_topics TEXT[] DEFAULT '{}',
                birthday TEXT,
                timezone TEXT,
                relationship_score INT DEFAULT 50,
                conversation_count INT DEFAULT 0,
                last_seen TIMESTAMP WITH TIME ZONE,
                memory_history JSONB DEFAULT '[]',
                temp_memories JSONB DEFAULT '{}',
                stats JSONB DEFAULT '{}'
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Database tables verified.")
    except Exception as e:
        logger.error(f"❌ DB Initialization failed: {e}")

def save_message(message_id: int, guild_id: int, author_id: int, author_name: str, content: str, timestamp: datetime, is_bot_reply: int = 0):
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
        logger.error(f"❌ Error saving message: {e}")

def get_last_synced_id() -> int:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT last_message_id FROM channel_sync WHERE channel_id = %s", (TARGET_CHANNEL_ID,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"❌ Error reading sync position: {e}")
        return None

def update_last_synced_id(message_id: int):
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

def get_user_profile(user_id: int) -> dict:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_profiles WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            cols = [desc[0] for desc in cursor.description]
            profile = dict(zip(cols, row))
            for key in ['personality', 'favorites', 'memory_history', 'temp_memories', 'stats']:
                if profile.get(key) and isinstance(profile[key], str):
                    try:
                        profile[key] = json.loads(profile[key])
                    except:
                        profile[key] = {}
            return profile
        return None
    except Exception as e:
        logger.error(f"Failed to get profile {user_id}: {e}")
        return None

def update_user_profile(user_id: int, data: dict):
    try:
        conn = get_connection()
        cursor = conn.cursor()

        update_data = {k: v for k, v in data.items() if k != "user_id"}
        if not update_data:
            return

        columns = list(update_data.keys())
        values = list(update_data.values())

        set_parts = [f"{col} = EXCLUDED.{col}" for col in columns]  # ← use EXCLUDED, no extra params

        query = f"""
            INSERT INTO user_profiles (user_id, {', '.join(columns)})
            VALUES (%s, {', '.join(['%s'] * len(columns))})
            ON CONFLICT (user_id) DO UPDATE SET
            {', '.join(set_parts)}
        """

        cursor.execute(query, [user_id] + values)  # ← only N+1 params, not 2N+1
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update profile {user_id}: {e}")

init_db()