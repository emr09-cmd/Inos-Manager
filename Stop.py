import discord
from discord.ext import commands

# Only this user can stop the bot
AUTHORIZED_USER_ID = 1236358212152852582

class Stop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="stop",
        description="Stops the bot"
    )
    async def stop(self, interaction: discord.Interaction):
        # Check user ID
        if interaction.user.id != AUTHORIZED_USER_ID:
            await interaction.response.send_message(
                "❌ You are not authorized to use this command.",
                ephemeral=True
            )
            return

        # Hidden message visible only to command user
        await interaction.response.send_message(
            "🛑 Stopping...",
            ephemeral=True
        )

        # Gracefully close bot
        await self.bot.close()

async def setup(bot):
    await bot.add_cog(Stop(bot))