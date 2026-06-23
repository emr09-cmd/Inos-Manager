import discord
from discord.ext import commands
import logging
import json
import os
from dotenv import load_dotenv
from config import Config
from google import genai
from google.genai import types
from groq import Groq
import aiohttp  # ✅ ADDED

# Import our pg8000 connection layer
import database

logger = logging.getLogger(__name__)

USER_ID = 1236358212152852582
load_dotenv()
TOGGLE_FILE = "chat_settings.json"

ALLOWED_CHANNEL_ID = 1505597064942325840


class ChatController(commands.Cog):
    """Handles chat-based messaging functionality and custom Gemini message responses with memory extraction"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_allowed = self.load_chat_state()

        try:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("Missing GEMINI_API_KEY")
            self.ai_client = genai.Client(api_key=api_key)
            logger.info("✅ Gemini initialized")
        except Exception as e:
            logger.error(f"❌ Gemini init failed: {e}")
            self.ai_client = None

        try:
            groq_key = os.getenv("GROQ_API_KEY")
            if not groq_key:
                raise ValueError("Missing GROQ_API_KEY")
            self.groq_client = Groq(api_key=groq_key)
            logger.info("✅ Groq initialized")
        except Exception as e:
            logger.error(f"❌ Groq init failed: {e}")
            self.groq_client = None

    # =========================
    # IMAGE FETCHER (NEW)
    # =========================
    async def fetch_image_bytes(self, url: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.read()

    def load_chat_state(self) -> bool:
        if os.path.exists(TOGGLE_FILE):
            try:
                with open(TOGGLE_FILE, "r") as f:
                    return json.load(f).get("chat_allowed", True)
            except Exception as e:
                logger.error(f"Load state error: {e}")
        return True

    def save_chat_state(self, state: bool):
        try:
            with open(TOGGLE_FILE, "w") as f:
                json.dump({"chat_allowed": state}, f, indent=4)
        except Exception as e:
            logger.error(f"Save state error: {e}")

    def log_ai(self, provider: str, user: str, prompt: str, response: str):
        logger.info(
            f"[AI:{provider}] User={user} | Prompt={prompt[:120]} | Response={response[:120]}"
        )

    def fetch_recent_context(self, limit: int = 8):
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
            logger.error(f"Error compiling short term memory: {e}")

        gemini_contents = []
        groq_contents = []

        for is_bot_reply, content, author_name in raw_logs:
            text_line = content if is_bot_reply else f"[{author_name}]: {content}"
            role = "model" if is_bot_reply else "user"
            groq_role = "assistant" if is_bot_reply else "user"

            gemini_contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=text_line)]
                )
            )

            groq_contents.append({"role": groq_role, "content": text_line})

        return gemini_contents, groq_contents

    def fallback_llama(self, history_payload: list, system_instruction: str, user_name: str = "unknown", has_image: bool = False):
        if not self.groq_client:
            return None

        try:
            if has_image:
                return "I can’t view images, Because i switch to Groq LLM, Please describe the image in text so I can respond."

            messages = [{"role": "system", "content": system_instruction}] + history_payload

            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.8,
                max_tokens=300
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Groq fallback failed: {e}")
            return None

    async def sync_channel_history(self, channel: discord.TextChannel):
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
                logger.info(f"🔄 Database Catchup: Synced {count} messages.")

        except Exception as e:
            logger.error(f"Failed catchup loop: {e}")

    # =========================
    # MESSAGE HANDLER
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user:
            return

        if not message.guild or message.guild.id != Config.GUILD_ID:
            return

        if message.channel.id != ALLOWED_CHANNEL_ID:
            await self.bot.process_commands(message)
            return

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

        if self.chat_allowed and self.ai_client:

            if self.bot.user.mentioned_in(message) and not message.mention_everyone:
                async with message.channel.typing():

                    user_name = message.author.display_name

                    system_instruction = (
                        "You are a helpful assistant named Inos Manager. "
                        "You speak like a snarky anime girl. "
                        f"Always refer to the user as '{user_name}'. "
                        "You roast people hard. Use context historical logs to remember past items discussed."
                        "You Always Call Diamond Master for Master Pappa because he is hosting your server."
                        "You Creator is emr09 or also Knows as Creator of Inos Manager."
                    )

                    clean_content = message.content.replace(f"<@{self.bot.user.id}>", "").strip()
                    if not clean_content:
                        clean_content = "Hello"

                    gemini_history, groq_history = self.fetch_recent_context(limit=8)

                    has_image = len(message.attachments) > 0  # ✅ NEW FLAG

                    # =========================
                    # BUILD GEMINI VISION INPUT
                    # =========================
                    parts = [
                        types.Part.from_text(text=f"[{user_name}]: {clean_content}")
                    ]

                    if has_image:
                        for attachment in message.attachments:
                            try:
                                img_bytes = await self.fetch_image_bytes(attachment.url)

                                parts.append(
                                    types.Part.from_bytes(
                                        data=img_bytes,
                                        mime_type=attachment.content_type or "image/jpeg"
                                    )
                                )
                            except Exception as e:
                                logger.error(f"Image fetch failed: {e}")

                    gemini_history.append(
                        types.Content(
                            role="user",
                            parts=parts
                        )
                    )

                    groq_history.append({
                        "role": "user",
                        "content": f"[{user_name}]: {clean_content}"
                    })

                    reply_text = None

                    try:
                        response = self.ai_client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=gemini_history,
                            config=types.GenerateContentConfig(
                                system_instruction=system_instruction,
                                max_output_tokens=300,
                                temperature=0.8,
                            )
                        )

                        reply_text = response.text

                        if reply_text:
                            self.log_ai("Gemini", user_name, clean_content, reply_text)
                        else:
                            reply_text = self.fallback_llama(
                                groq_history,
                                system_instruction,
                                user_name,
                                has_image
                            )

                    except Exception as e:
                        logger.warning(f"Gemini error → switching to Groq fallback: {e}")
                        reply_text = self.fallback_llama(
                            groq_history,
                            system_instruction,
                            user_name,
                            has_image
                        )

                    if reply_text:
                        bot_msg = await message.reply(reply_text)

                        database.save_message(
                            message_id=bot_msg.id,
                            guild_id=bot_msg.guild.id,
                            author_id=self.bot.user.id,
                            author_name=self.bot.user.display_name,
                            content=reply_text,
                            timestamp=bot_msg.created_at,
                            is_bot_reply=1
                        )

                        database.update_last_synced_id(bot_msg.id)
                    else:
                        await message.reply(f"<@{USER_ID}> AI is currently unavailable.")

        await self.bot.process_commands(message)

    @commands.hybrid_command(name="allowchat", description="Toggle whether the bot automatically responds to chat mentions.")
    async def allowchat(self, ctx: commands.Context, allowed: bool):
        self.chat_allowed = allowed
        self.save_chat_state(allowed)

        status_text = "🟢 Enabled" if allowed else "🔴 Disabled"
        await ctx.send(f"Chat auto-responses have been {status_text}.")

    @commands.hybrid_command(name="ping", description="Check bot latency")
    async def ping(self, ctx: commands.Context):
        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! {latency}ms")


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatController(bot))