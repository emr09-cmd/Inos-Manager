import discord
from discord.ext import commands
import logging
import json
import os
import requests
from dotenv import load_dotenv
from config import Config

# Import our pg8000 connection layer
import database

logger = logging.getLogger(__name__)

USER_ID = 1236358212152852582
TOGGLE_FILE = "chat_settings.json"
ALLOWED_CHANNEL_ID = 1505597064942325840

load_dotenv()


class ChatController(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_allowed = self.load_chat_state()

        self.gemini_key = os.getenv("GEMINI_API_KEY")
        if self.gemini_key:
            logger.info("✅ Gemini (HTTP) ready")

        self.groq_key = os.getenv("GROQ_API_KEY")

    # =========================
    # STATE
    # =========================
    def load_chat_state(self):
        if os.path.exists(TOGGLE_FILE):
            try:
                with open(TOGGLE_FILE, "r") as f:
                    return json.load(f).get("chat_allowed", True)
            except:
                pass
        return True

    def save_chat_state(self, state: bool):
        with open(TOGGLE_FILE, "w") as f:
            json.dump({"chat_allowed": state}, f)

    # =========================
    # CONTEXT MEMORY LOADER
    # =========================
    def fetch_recent_context(self, limit: int = 8):
        """Pulls logs from the database and structures them for raw HTTP payloads."""
        raw_logs = []
        try:
            conn = database.get_connection()
            cursor = conn.cursor()
            query = f"""
                SELECT is_bot_reply, content, author_name 
                FROM {database.TABLE_NAME} 
                ORDER BY message_id DESC LIMIT %s
            """
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            raw_logs = list(reversed(rows))
        except Exception as e:
            logger.error(f"Error compiling memory logs: {e}")

        gemini_contents = []
        groq_contents = []

        for is_bot_reply, content, author_name in raw_logs:
            text_line = content if is_bot_reply else f"[{author_name}]: {content}"
            
            # Formats for raw Gemini HTTP structure
            gemini_contents.append({
                "role": "model" if is_bot_reply else "user",
                "parts": [{"text": text_line}]
            })
            
            # Formats for standard OpenAI/Groq messages array
            groq_contents.append({
                "role": "assistant" if is_bot_reply else "user",
                "content": text_line
            })

        return gemini_contents, groq_contents

    # =========================
    # GEMINI HTTP
    # =========================
    def gemini_request(self, history_payload, system_instruction):
        if not self.gemini_key:
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.gemini_key}"

        payload = {
            "contents": history_payload,
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "maxOutputTokens": 300,
                "temperature": 0.8
            }
        }

        try:
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code != 200:
                logger.error(f"Gemini HTTP Error: {r.text}")
                return None

            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            logger.error(f"Gemini Request failed exception: {e}")
            return None

    # =========================
    # GROQ HTTP (no SDK)
    # =========================
    def groq_request(self, history_payload, system_instruction):
        if not self.groq_key:
            return None

        url = "https://api.groq.com/openai/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json"
        }

        # Build full messages payload with system role at top
        messages = [{"role": "system", "content": system_instruction}] + history_payload

        data = {
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 300
        }

        try:
            r = requests.post(url, json=data, headers=headers, timeout=20)
            if r.status_code != 200:
                logger.error(f"Groq HTTP Error: {r.text}")
                return None

            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Groq Request failed exception: {e}")
            return None

    async def sync_channel_history(self, channel: discord.TextChannel):
        """Catches up on missed messages securely while the bot was offline."""
        last_id = database.get_last_synced_id()
        after_target = discord.Object(id=last_id) if last_id else None
        count = 0
        latest_processed_id = last_id

        try:
            async for msg in channel.history(limit=100, after=after_target, oldest_first=True):
                guild_id = msg.guild.id if msg.guild else None
                database.save_message(
                    message_id=msg.id,
                    guild_id=guild_id,
                    author_id=msg.author.id,
                    author_name=msg.author.display_name,
                    content=msg.content,
                    timestamp=msg.created_at,
                    is_bot_reply=1 if msg.author == self.bot.user else 0
                )
                latest_processed_id = msg.id
                count += 1
            if latest_processed_id:
                database.update_last_synced_id(latest_processed_id)
            if count > 0:
                logger.info(f"🔄 iPadServer database synced {count} missing records.")
        except Exception as e:
            logger.error(f"Historical catchup processing error: {e}")

    # =========================
    # MESSAGE HANDLER
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot:
            return

        if not message.guild or message.guild.id != Config.GUILD_ID:
            return

        if not self.chat_allowed:
            return

        # 🛑 SECURITY FILTER: Restrict processing only to your target channel
        if message.channel.id != ALLOWED_CHANNEL_ID:
            await self.bot.process_commands(message)
            return

        # 1. Backfill records and save current interaction
        await self.sync_channel_history(message.channel)

        database.save_message(
            message_id=message.id,
            guild_id=message.guild.id,
            author_id=message.author.id,
            author_name=message.author.display_name,
            content=message.content,
            timestamp=message.created_at,
            is_bot_reply=0
        )
        database.update_last_synced_id(message.id)

        if not self.bot.user.mentioned_in(message):
            await self.bot.process_commands(message)
            return

        async with message.channel.typing():

            user = message.author.display_name
            content = message.content.replace(f"<@{self.bot.user.id}>", "").strip()

            if not content:
                content = "Hello"

            system = (
                "You are a helpful assistant named Inos Manager. "
                "You speak like a snarky anime girl. "
                f"Always refer to the user as '{user}'. "
                "You roast people hard. Use context historical logs to remember past items discussed."
            )

            # Fetch recent memory arrays from database
            gemini_history, groq_history = self.fetch_recent_context(limit=8)

            # Append the current active prompt to the end of history payloads
            gemini_history.append({"role": "user", "parts": [{"text": f"[{user}]: {content}"}]})
            groq_history.append({"role": "user", "content": f"[{user}]: {content}"})

            # Fire request checks sequentially
            reply = self.gemini_request(gemini_history, system)

            if not reply:
                logger.warning("Gemini failed/empty → shifting to Groq backup via HTTP")
                reply = self.groq_request(groq_history, system)

            if reply:
                bot_msg = await message.reply(reply)
                
                # Instantly save the reply to database
                database.save_message(
                    message_id=bot_msg.id,
                    guild_id=bot_msg.guild.id,
                    author_id=self.bot.user.id,
                    author_name=self.bot.user.display_name,
                    content=reply,
                    timestamp=bot_msg.created_at,
                    is_bot_reply=1
                )
                database.update_last_synced_id(bot_msg.id)
            else:
                await message.reply(f"<@{USER_ID}> AI unavailable.")

        await self.bot.process_commands(message)

    # =========================
    # COMMANDS
    # =========================
    @commands.hybrid_command(name="allowchat")
    async def allowchat(self, ctx, allowed: bool):
        self.chat_allowed = allowed
        self.save_chat_state(allowed)
        await ctx.send(f"Chat: {allowed}")

    @commands.hybrid_command(name="ping")
    async def ping(self, ctx):
        await ctx.send(f"Pong {round(self.bot.latency*1000)}ms")


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatController(bot))