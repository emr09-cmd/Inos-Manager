import discord
from discord.ext import commands
import json
import time
import os

AUTHORIZED_USER_ID = 1236358212152852582
STOP_FILE = "stop_state.json"

class Stop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="stop",
        description="Stops the bot for 1 minute"
    )
    async def stop(self, interaction: discord.Interaction):
        if interaction.user.id != AUTHORIZED_USER_ID:
            await interaction.response.send_message(
                "❌ Not authorized.",
                ephemeral=True
            )
            return

        data = {
            "restart_after": time.time() + 60
        }

        with open(STOP_FILE, "w") as f:
            json.dump(data, f)

        await interaction.response.send_message(
            "🛑 Stopping bot for 1 minute...",
            ephemeral=True
        )

        await self.bot.close()

async def setup(bot):
    await bot.add_cog(Stop(bot))