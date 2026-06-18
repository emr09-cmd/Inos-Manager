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

logger = logging.getLogger(__name__)

USER_ID = 1236358212152852582

load_dotenv()

TOGGLE_FILE = "chat_settings.json"


class ChatController(commands.Cog):
    """Handles chat-based messaging functionality and custom Gemini message responses"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.chat_allowed = self.load_chat_state()

        # =========================
        # GEMINI (PRIMARY)
        # =========================
        try:
            api_key = os.getenv("GEMINI_API_KEY")

            if not api_key:
                raise ValueError("Missing GEMINI_API_KEY")

            self.ai_client = genai.Client(api_key=api_key)
            logger.info("✅ Gemini initialized")

        except Exception as e:
            logger.error(f"❌ Gemini init failed: {e}")
            self.ai_client = None

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
    # AI LOGGING HELPER (NEW)
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
    # FALLBACK LLM (GROQ / LLAMA)
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

            text = response.choices[0].message.content

            if text:
                logger.info(
                    f"[AI:GROQ] User={user_name} | Prompt={prompt[:120]} | Response={text[:120]}"
                )

            return text

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

        if self.chat_allowed and self.ai_client:

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
                    # GEMINI FIRST
                    # =========================
                    try:
                        response = self.ai_client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=clean_content,
                            config=types.GenerateContentConfig(
                                system_instruction=system_instruction,
                                max_output_tokens=300,
                                temperature=0.8,
                            )
                        )

                        reply_text = response.text

                        if reply_text:
                            self.log_ai("Gemini", user_name, clean_content, reply_text)

                        # fallback if empty
                        if not reply_text:
                            logger.warning("Gemini returned empty → switching to Groq")
                            reply_text = self.fallback_llama(clean_content, system_instruction, user_name)

                            if reply_text:
                                self.log_ai("Groq (fallback-empty)", user_name, clean_content, reply_text)

                    except Exception as e:
                        logger.warning(f"Gemini failed → Groq fallback: {e}")

                        reply_text = self.fallback_llama(clean_content, system_instruction, user_name)

                        if reply_text:
                            self.log_ai("Groq (fallback-error)", user_name, clean_content, reply_text)

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
    # SLASH COMMAND (/allowchat)
    # =========================
    @commands.hybrid_command(
        name="allowchat",
        description="Toggle whether the bot automatically responds to chat mentions."
    )
    async def allowchat(self, ctx: commands.Context, allowed: bool):

        self.chat_allowed = allowed
        self.save_chat_state(allowed)

        status_text = "🟢 Enabled" if allowed else "🔴 Disabled"

        await ctx.send(
            f"Chat auto-responses have been {status_text}. (Slash command used)"
        )

    # =========================
    # PREFIX COMMAND (r!allowchat)
    # =========================
    @commands.command(name="allowchat_prefix")
    async def allowchat_prefix(self, ctx: commands.Context, allowed: bool):

        self.chat_allowed = allowed
        self.save_chat_state(allowed)

        status_text = "🟢 Enabled" if allowed else "🔴 Disabled"

        await ctx.send(
            f"Chat auto-responses have been {status_text}. (Prefix command used)"
        )

    # =========================
    # PING COMMAND
    # =========================
    @commands.hybrid_command(name="ping", description="Check bot latency")
    async def ping(self, ctx: commands.Context):

        latency = round(self.bot.latency * 1000)
        await ctx.send(f"🏓 Pong! {latency}ms")


async def setup(bot: commands.Bot):
    await bot.add_cog(ChatController(bot))