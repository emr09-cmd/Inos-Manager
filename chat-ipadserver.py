import discord
from discord.ext import commands
import logging
import json
import os
import requests
from dotenv import load_dotenv
from config import Config
from groq import Groq

logger = logging.getLogger(__name__)

USER_ID = 1236358212152852582
TOGGLE_FILE = "chat_settings.json"

load_dotenv()


class ChatController(commands.Cog):
    """Chat handler with Gemini (HTTP) + Groq fallback"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_allowed = self.load_chat_state()

        # =========================
        # GEMINI (RAW HTTP)
        # =========================
        self.gemini_key = os.getenv("GEMINI_API_KEY")

        if self.gemini_key:
            logger.info("✅ Gemini (HTTP) initialized")
        else:
            logger.warning("❌ Gemini key missing")

        # =========================
        # GROQ (FALLBACK)
        # =========================
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
    # LOGGING
    # =========================
    def log_ai(self, provider: str, user: str, prompt: str, response: str):
        logger.info(
            f"[AI:{provider}] User={user} | Prompt={prompt[:120]} | Response={response[:120]}"
        )

    # =========================
    # STATE LOAD
    # =========================
    def load_chat_state(self) -> bool:
        if os.path.exists(TOGGLE_FILE):
            try:
                with open(TOGGLE_FILE, "r") as f:
                    return json.load(f).get("chat_allowed", True)
            except Exception as e:
                logger.error(f"Load state error: {e}")
        return True

    # =========================
    # STATE SAVE
    # =========================
    def save_chat_state(self, state: bool):
        try:
            with open(TOGGLE_FILE, "w") as f:
                json.dump({"chat_allowed": state}, f, indent=4)
        except Exception as e:
            logger.error(f"Save state error: {e}")

    # =========================
    # GEMINI REQUEST (HTTP)
    # =========================
    def gemini_request(self, prompt: str, system_instruction: str):
        if not self.gemini_key:
            return None

        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/gemini-2.5-flash:generateContent?key={self.gemini_key}"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"{system_instruction}\n\nUser: {prompt}"
                        }
                    ]
                }
            ]
        }

        try:
            r = requests.post(url, json=payload, timeout=20)

            if r.status_code != 200:
                logger.warning(f"Gemini HTTP error: {r.text}")
                return None

            data = r.json()

            return data["candidates"][0]["content"]["parts"][0]["text"]

        except Exception as e:
            logger.error(f"Gemini request failed: {e}")
            return None

    # =========================
    # GROQ FALLBACK
    # =========================
    def fallback_llama(self, prompt: str, system_instruction: str, user_name: str = "unknown"):
        if not self.groq_client:
            return None

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=300
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Groq fallback failed: {e}")
            return None

    # =========================
    # MESSAGE HANDLER
    # =========================
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author == self.bot.user:
            return

        if not message.guild or message.guild.id != Config.GUILD_ID:
            return

        if self.chat_allowed:

            if self.bot.user.mentioned_in(message) and not message.mention_everyone:

                async with message.channel.typing():

                    user_name = message.author.display_name

                    system_instruction = (
                        "You are a helpful assistant named Inos Manager. "
                        "You speak like a snarky anime girl. "
                        f"Always refer to the user as '{user_name}'. "
                        "You roast people hard."
                    )

                    clean_content = message.content.replace(
                        f"<@{self.bot.user.id}>", ""
                    ).strip()

                    if not clean_content:
                        clean_content = "Hello"

                    reply_text = None

                    # =========================
                    # GEMINI FIRST (HTTP)
                    # =========================
                    reply_text = self.gemini_request(clean_content, system_instruction)

                    if reply_text:
                        self.log_ai("Gemini-HTTP", user_name, clean_content, reply_text)
                    else:
                        logger.warning("Gemini failed → Groq fallback")

                        reply_text = self.fallback_llama(
                            clean_content,
                            system_instruction,
                            user_name
                        )

                        if reply_text:
                            self.log_ai("Groq", user_name, clean_content, reply_text)

                    # =========================
                    # RESPONSE
                    # =========================
                    if reply_text:
                        await message.reply(reply_text)
                    else:
                        await message.reply(
                            f"<@{USER_ID}> AI is currently unavailable."
                        )

        await self.bot.process_commands(message)

    # =========================
    # TOGGLE COMMANDS
    # =========================
    @commands.hybrid_command(name="allowchat", description="Toggle AI chat")
    async def allowchat(self, ctx: commands.Context, allowed: bool):

        self.chat_allowed = allowed
        self.save_chat_state(allowed)

        status_text = "🟢 Enabled" if allowed else "🔴 Disabled"

        await ctx.send(f"Chat auto-responses: {status_text}")

    @commands.command(name="allowchat_prefix")
    async def allowchat_prefix(self, ctx: commands.Context, allowed: bool):

        self.chat_allowed = allowed
        self.save_chat_state(allowed)

        status_text = "🟢 Enabled" if allowed else "🔴 Disabled"

        await ctx.send(f"Chat auto-responses: {status_text}")

    # =========================
    # PING
    # =========================
    @commands.hybrid_command(name="ping", description="Check bot latency")
    async def ping(self, ctx: commands.Context):

        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! {latency}ms")


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatController(bot))
