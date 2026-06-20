import discord
from discord.ext import commands
import logging
import json
import os
import requests
from dotenv import load_dotenv
from config import Config

logger = logging.getLogger(__name__)

USER_ID = 1236358212152852582
TOGGLE_FILE = "chat_settings.json"

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
    # GEMINI HTTP
    # =========================
    def gemini_request(self, prompt, system):
        if not self.gemini_key:
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={self.gemini_key}"

        payload = {
            "contents": [
                {"parts": [{"text": f"{system}\n\nUser: {prompt}"}]}
            ]
        }

        try:
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code != 200:
                return None

            return r.json()["candidates"][0]["content"]["parts"][0]["text"]

        except:
            return None

    # =========================
    # GROQ HTTP (no SDK)
    # =========================
    def groq_request(self, prompt):
        if not self.groq_key:
            return None

        url = "https://api.groq.com/openai/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}]
        }

        try:
            r = requests.post(url, json=data, headers=headers)
            if r.status_code != 200:
                return None

            return r.json()["choices"][0]["message"]["content"]

        except:
            return None

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

        if not self.bot.user.mentioned_in(message):
            return

        async with message.channel.typing():

            user = message.author.display_name
            content = message.content.replace(f"<@{self.bot.user.id}>", "").strip()

            if not content:
                content = "Hello"

            system = (
                f"You are Inos Manager. You roast users. User is {user}"
            )

            reply = self.gemini_request(content, system)

            if not reply:
                reply = self.groq_request(content)

            if reply:
                await message.reply(reply)
            else:
                await message.reply(f"<@{USER_ID}> AI unavailable.")

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
