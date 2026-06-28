import discord
from discord import app_commands
from discord.ext import commands
import logging
import os
import json
import random
from urllib.parse import quote

logger = logging.getLogger(__name__)

ALLOWED_USERS = {1236358212152852582, 1423693860403675205}
BOORU_CHANNEL_ID = 1516854766016397413
BASE_URL = "https://zehjbmjldfkbaumvrtrw.supabase.co/storage/v1/object/public/Inos-booru/"
INDEX_PATH = os.path.join(os.path.dirname(__file__), "storage_index.json")


class BooruView(discord.ui.View):

    def __init__(self, filename: str, image_url: str):
        super().__init__(timeout=None)
        self.filename = filename
        self.image_url = image_url

    @discord.ui.button(label="Debug.delete", style=discord.ButtonStyle.danger)
    async def debug_delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in ALLOWED_USERS:
            return await interaction.response.send_message(
                "❌ You are not authorized to use this button.",
                ephemeral=True
            )
        await interaction.message.delete()


class InosBooru(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="inos-booru",
        description="Browse the Inos Booru image gallery"
    )
    async def inos_booru(self, interaction: discord.Interaction):

        # ── Enforce channel ──
        if interaction.channel_id != BOORU_CHANNEL_ID:
            return await interaction.response.send_message(
                f"❌ This command can only be used in <#{BOORU_CHANNEL_ID}>.",
                ephemeral=False
            )

        # ── Enforce user whitelist ──
        if interaction.user.id not in ALLOWED_USERS:
            return await interaction.response.send_message(
                "🚫 **This Command is unavailable until the Server Owner verifies all the images in the Booru.**",
                ephemeral=False
            )

        # ── Load local index ──
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                index_data = json.load(f)
        except FileNotFoundError:
            return await interaction.response.send_message(
                "❌ `storage_index.json` not found next to the bot script.",
                ephemeral=False
            )
        except Exception as e:
            logger.error(f"Booru index load failed: {e}")
            return await interaction.response.send_message(
                "❌ Could not load the image index. Try again later.",
                ephemeral=False
            )

        folder = "Questionable"
        all_files = index_data.get("Inos-booru", {}).get(folder, [])

        if not all_files:
            return await interaction.response.send_message(
                f"❌ No images found in the **{folder}** folder.",
                ephemeral=False
            )

        filename = random.choice(all_files)
        image_url = BASE_URL + folder + "/" + quote(filename)

        embed = discord.Embed(
            title="📁 Inos Booru — Questionable",
            color=discord.Color.red()
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"📄 {filename}")

        view = BooruView(filename=filename, image_url=image_url)

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=False
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(InosBooru(bot))