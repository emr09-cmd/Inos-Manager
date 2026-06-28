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


# ============================================================
# VIEW: Booru browser — random order, no search
# ============================================================
class BooruView(discord.ui.View):

    def __init__(self, invoker: discord.Member, all_files: list[str], folder: str):
        super().__init__(timeout=300)
        self.invoker = invoker
        self.folder = folder
        # Shuffle once on creation — order stays stable while browsing
        self.files = all_files.copy()
        random.shuffle(self.files)
        self.page = 0
        self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "❌ Only the person who opened this browser can use these buttons.",
                ephemeral=True
            )
            return False
        return True

    # ── helpers ──

    def current_file(self) -> str:
        return self.files[self.page]

    def current_url(self) -> str:
        return BASE_URL + self.folder + "/" + quote(self.current_file())

    def _update_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= len(self.files) - 1

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="📁 Inos Booru — Questionable",
            color=discord.Color.red()
        )
        embed.set_footer(text=f"📄 {self.current_file()}  •  {self.page + 1} / {len(self.files)}")
        return embed

    async def _render(self, interaction: discord.Interaction, first: bool = False):
        self._update_buttons()
        embed = self._build_embed()
        content = f"||{self.current_url()}||"

        if first:
            await interaction.followup.send(
                content=content,
                embed=embed,
                view=self,
                ephemeral=True
            )
        else:
            await interaction.response.edit_message(
                content=content,
                embed=embed,
                view=self
            )

    # ── buttons ──

    @discord.ui.button(label="⬅️ Prev", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        await self._render(interaction)

    @discord.ui.button(label="➡️ Next", style=discord.ButtonStyle.primary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self._render(interaction)

    @discord.ui.button(label="🔀 Reshuffle", style=discord.ButtonStyle.secondary)
    async def reshuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        random.shuffle(self.files)
        self.page = 0
        await self._render(interaction)

    @discord.ui.button(label="Debug.delete", style=discord.ButtonStyle.danger)
    async def debug_delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in ALLOWED_USERS:
            return await interaction.response.send_message(
                "❌ You are not authorized to use this button.",
                ephemeral=True
            )
        filename = self.current_file()
        await interaction.response.send_message(
            f"🗑️ **Debug.delete** triggered\n"
            f"`{filename}`\n"
            f"Page {self.page + 1} / {len(self.files)}",
            ephemeral=True
        )


# ============================================================
# COG
# ============================================================
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

        await interaction.response.defer(ephemeral=True)

        # ── Load local index ──
        try:
            with open(INDEX_PATH, encoding="utf-8") as f:
                index_data = json.load(f)
        except FileNotFoundError:
            return await interaction.followup.send(
                "❌ `storage_index.json` not found next to the bot script.",
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Booru index load failed: {e}")
            return await interaction.followup.send(
                "❌ Could not load the image index. Try again later.",
                ephemeral=True
            )

        folder = "Questionable"
        all_files = index_data.get("Inos-booru", {}).get(folder, [])

        if not all_files:
            return await interaction.followup.send(
                f"❌ No images found in the **{folder}** folder.",
                ephemeral=True
            )

        view = BooruView(invoker=interaction.user, all_files=all_files, folder=folder)
        await view._render(interaction, first=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(InosBooru(bot))