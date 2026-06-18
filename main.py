import discord
from discord.ext import commands
import asyncio
import logging
import os
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
        "chat"                  # Chat AI controller
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
    async with bot:
        await load_cogs()
        token = os.getenv("DISCORD_TOKEN")
        
        if not token:
            logger.critical("❌ DISCORD_TOKEN not found in .env file!")
            return
            
        try:
            await bot.start(token)
        except discord.LoginFailure:
            logger.critical("❌ Invalid token. Check your .env file.")
        except Exception as e:
            logger.critical(f"❌ Failed to start bot: {e}")

if __name__ == "__main__":
    asyncio.run(main())