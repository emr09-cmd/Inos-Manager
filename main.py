import discord
from discord.ext import commands
import asyncio
import logging
import os
import json
import time
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =========================
# LOGGING SETUP
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="r!",
    intents=intents,
    help_command=None  # Disable default help if you want custom one
)

# =========================
# COG LOADING
# =========================
async def load_cogs():
    cogs = [
        "gamble_rep",           # Gamble game
        "delete_all_message_channel",  # Purge command
        "chat",                  # Chat AI controller
        "Serika_Image",
        "Stop",
        "Inos-booru",
        "Ban"
    ]
    
    for cog in cogs:
        try:
            await bot.load_extension(cog)
            logger.info(f"✅ Successfully loaded cog: {cog}")
        except Exception as e:
            logger.error(f"❌ Failed to load cog {cog}: {e}")

# =========================
# EVENTS
# =========================
@bot.event
async def on_ready():
    logger.info(f"🚀 Bot is online as {bot.user} (ID: {bot.user.id})")
    await bot.tree.sync()
    logger.info("✅ Slash commands synced")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f"Command error: {error}")
    if isinstance(ctx, commands.Context):
        await ctx.send(f"❌ Error: {error}", delete_after=10)

# =========================
# MAIN ENTRYPOINT
# =========================
async def main():
    STOP_FILE = "stop_state.json"

    if os.path.exists(STOP_FILE):
        try:
            with open(STOP_FILE, "r") as f:
                data = json.load(f)

            restart_after = data.get("restart_after", 0)
            remaining = restart_after - time.time()

            if remaining > 0:
                logger.warning(
                    f"Bot is paused. Waiting {int(remaining)} seconds before login..."
                )
                await asyncio.sleep(remaining)

            # Remove file after pause is complete
            os.remove(STOP_FILE)

        except Exception as e:
            logger.error(f"Failed reading stop file: {e}")

    async with bot:
        await load_cogs()

        token = os.getenv("DISCORD_TOKEN")

        if not token:
            logger.critical("❌ DISCORD_TOKEN not found!")
            return

        try:
            await bot.start(token)
        except discord.LoginFailure:
            logger.critical("❌ Invalid token.")
        except Exception as e:
            logger.critical(f"❌ Failed to start bot: {e}")

if __name__ == "__main__":
    asyncio.run(main())
