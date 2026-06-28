import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import logging
import io
import re

logger = logging.getLogger(__name__)
SERIKA_BASE_URL = "https://serika.art/api/v1"
MAX_REROLLS = 10

# ============================================================
# BLOCKLIST — full list loaded from file for client-side check
# ============================================================
_BLOCKLIST_PATH = os.path.join(os.path.dirname(__file__), "BLOCKLIST_FINAL.txt")


def _load_blocklist(path: str) -> set[str]:
    try:
        with open(path, encoding="utf-8") as f:
            tags = {line.strip().lower() for line in f if line.strip()}
        logger.info(f"✅ Blocklist loaded: {len(tags)} tags from {path}")
        return tags
    except FileNotFoundError:
        logger.error(f"❌ Blocklist file not found: {path}")
        return set()


BLOCKED_TAGS: set[str] = _load_blocklist(_BLOCKLIST_PATH)

# ============================================================
# API-SIDE EXCLUSIONS
# ============================================================
API_EXCLUDE_TAGS = ",".join([
    "loli", "shota", "shotacon", "lolicon", "mesugaki",
    "aged_down", "age_regression", "deaged",
    "child", "toddler", "infant", "preschool",
    "elementary_school", "middle_school", "kindergarten",
    "randoseru", "buruma", "serafuku", "gakuran",
    "school_swimsuit", "school_uniform",
    "js", "jc",
    "oppai_loli", "lolibaba", "onee-shota",
    "young_looking", "grade_schooler",
])


def is_blacklisted(tags: list[dict]) -> tuple[bool, str]:
    tag_names = {t["name"].lower() for t in tags}

    hit = tag_names & BLOCKED_TAGS
    if hit:
        sample = ", ".join(sorted(hit)[:5])
        return True, f"blocked tag(s): {sample}"

    has_boy = any(re.search(r"\d*boys?$", tag) for tag in tag_names)
    has_girl = any(re.search(r"\d*girls?$", tag) for tag in tag_names)
    if has_boy and not has_girl:
        return True, "boys without girls"

    return False, ""


# ============================================================
# VIEW: Delete button shown on the publicly posted image
# ============================================================
class DeleteView(discord.ui.View):
    def __init__(self, invoker_id: int):
        super().__init__(timeout=86400)
        self.invoker_id = invoker_id

    @discord.ui.button(label="🗑️ Delete", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker_id:
            return await interaction.response.send_message(
                "❌ Only the person who posted this image can delete it.",
                ephemeral=True
            )
        await interaction.response.send_message("🗑️ Image deleted.", ephemeral=True)
        await interaction.message.delete()


# ============================================================
# VIEW: Ephemeral preview buttons — Reroll / Accept / Reject
# ============================================================
class PreviewView(discord.ui.View):
    def __init__(self, cog: "SerikaImage", rating: str, interaction: discord.Interaction):
        super().__init__(timeout=None)
        self.cog = cog
        self.rating = rating
        self.original_interaction = interaction
        self.result: dict = {}
        self.tags: list[dict] = []
        self.image_bytes: bytes | None = None
        self.is_nsfw_channel: bool = rating == "questionable"

    def _build_embed(self) -> discord.Embed:
        tag_str = ", ".join([t["name"] for t in self.tags]) or "None"
        rating_str = self.result.get("rating", "unknown")
        uploader = self.result.get("user", {}).get("username", "unknown")
        stats = self.result.get("stats", {})

        embed = discord.Embed(
            title=f"🎴 Serika Booru {'❗ Questionable' if self.is_nsfw_channel else '✅ Safe'} Image",
            color=discord.Color.red() if self.is_nsfw_channel else discord.Color.green()
        )

        thumb_url = self.result.get("thumbnail_url")
        if thumb_url:
            embed.set_thumbnail(url=thumb_url)

        embed.add_field(name="Rating", value=rating_str.upper(), inline=True)
        embed.add_field(name="Uploader", value=uploader, inline=True)
        embed.add_field(name="Tags", value=tag_str, inline=False)
        embed.set_footer(
            text=(
                f"👍 {stats.get('upvotes', 0)} | "
                f"👎 {stats.get('downvotes', 0)} | "
                f"⭐ {stats.get('favorites', 0)} | "
                f"👁 {stats.get('views', 0)}"
            )
        )

        if not self.is_nsfw_channel:
            image_url = self.result.get("url")
            if image_url:
                embed.set_image(url=image_url)

        return embed

    async def _lock(self, interaction: discord.Interaction):
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except discord.NotFound:
            pass

    @discord.ui.button(label="🔄 Reroll", style=discord.ButtonStyle.primary)
    async def reroll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="🔄 Finding a new image...",
            attachments=[],
            embed=None,
            view=None
        )

        result, tags = await self.cog.fetch_clean_image(self.rating)

        if isinstance(result, dict) and "error" in result:
            await interaction.edit_original_response(
                content=f"❌ Error: {result['error']}\nTry rerolling again.",
                view=self
            )
            return

        self.result = result
        self.tags = tags
        self.image_bytes = None

        if self.is_nsfw_channel:
            image_url = self.result.get("url")
            if image_url:
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url) as img_resp:
                        if img_resp.status == 200:
                            self.image_bytes = await img_resp.read()

        embed = self._build_embed()

        if self.is_nsfw_channel and self.image_bytes:
            file = discord.File(
                fp=io.BytesIO(self.image_bytes),
                filename="SPOILER_serika_preview.png",
                spoiler=True
            )
            await interaction.edit_original_response(
                content="👀 **Preview** (only you can see this)\n||⚠️ Questionable Image||",
                attachments=[file],
                embed=embed,
                view=self
            )
        else:
            await interaction.edit_original_response(
                content="👀 **Preview** (only you can see this)",
                embed=embed,
                view=self
            )

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._lock(interaction)

        delete_view = DeleteView(invoker_id=interaction.user.id)
        user_mention = interaction.user.mention

        if self.is_nsfw_channel:
            image_bytes = self.image_bytes
            if not image_bytes:
                image_url = self.result.get("url")
                if image_url:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(image_url) as img_resp:
                            if img_resp.status == 200:
                                image_bytes = await img_resp.read()

            embed = self._build_embed()

            if image_bytes:
                try:
                    file = discord.File(
                        fp=io.BytesIO(image_bytes),
                        filename="SPOILER_serika_image.png",
                        spoiler=True
                    )
                    await interaction.channel.send(
                        content=f"{user_mention} ||⚠️ Questionable Image||",
                        file=file,
                        embed=embed,
                        view=delete_view
                    )
                except discord.HTTPException as e:
                    if e.code == 40005:
                        image_url = self.result.get("url", "")
                        await interaction.channel.send(
                            content=f"{user_mention} ||⚠️ Questionable Image (too large to upload) — {image_url}||",
                            embed=embed,
                            view=delete_view
                        )
                    else:
                        raise
            else:
                await interaction.channel.send(
                    content=user_mention,
                    embed=embed,
                    view=delete_view
                )
        else:
            embed = self._build_embed()
            await interaction.channel.send(
                content=user_mention,
                embed=embed,
                view=delete_view
            )

        try:
            await interaction.edit_original_response(
                content="✅ Image posted!",
                attachments=[],
                embed=None,
                view=None
            )
        except discord.NotFound:
            pass

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.secondary)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(
                content="🚫 Image rejected.",
                attachments=[],
                embed=None,
                view=self
            )
        except discord.NotFound:
            pass


# ============================================================
# COG
# ============================================================
class SerikaImage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_key = os.getenv("SERIKA_BOORU_API")
        if not self.api_key:
            logger.warning("⚠️ SERIKA_BOORU_API not found in environment variables")

    async def fetch_image(self, rating: str = "safe"):
        url = f"{SERIKA_BASE_URL}/random"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {
            "count": 1,
            "ratings": rating,
            "exclude_tags": API_EXCLUDE_TAGS,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:
                if resp.status == 429:
                    return {"error": "RATE_LIMITED"}

                try:
                    data = await resp.json()
                except Exception:
                    return {"error": "INVALID_RESPONSE"}

                if not data.get("success"):
                    return {"error": data.get("error", "API_ERROR")}

                images = data.get("data", [])
                if not images:
                    return {"error": "NO_IMAGES_FOUND"}

                image = images[0] if isinstance(images, list) else images

                if image.get("rating") != rating:
                    return {"error": f"NON_{rating.upper()}_BLOCKED"}

                return image

    async def fetch_clean_image(self, rating: str):
        for attempt in range(1, MAX_REROLLS + 1):
            result = await self.fetch_image(rating)

            if isinstance(result, dict) and "error" in result:
                return result, []

            tags = result.get("tags", [])
            blocked, reason = is_blacklisted(tags)

            if blocked:
                logger.warning(f"⚠️ Client-side catch on attempt {attempt}/{MAX_REROLLS} — {reason}")
                continue

            return result, tags

        return {"error": "BLACKLIST_EXHAUSTED"}, []

    @app_commands.command(
        name="serika-image",
        description="Fetch a random image from Serika Booru (Safe by default, questionable in NSFW channel)"
    )
    async def serika_image(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.api_key:
            return await interaction.followup.send(
                "❌ Missing API key. Set `SERIKA_BOORU_API` in your .env file.",
                ephemeral=True
            )

        target_channel_id = 1516854766016397413
        is_nsfw_channel = interaction.channel_id == target_channel_id
        rating = "questionable" if is_nsfw_channel else "safe"

        result, tags = await self.fetch_clean_image(rating)

        if isinstance(result, dict) and "error" in result:
            error = result["error"]
            if error == "BLACKLIST_EXHAUSTED":
                return await interaction.followup.send(
                    f"❌ Couldn't find a clean image after {MAX_REROLLS} attempts. Try again later!",
                    ephemeral=True
                )
            return await interaction.followup.send(f"❌ Error: {error}", ephemeral=True)

        view = PreviewView(cog=self, rating=rating, interaction=interaction)
        view.result = result
        view.tags = tags
        view.is_nsfw_channel = is_nsfw_channel

        embed = view._build_embed()

        if is_nsfw_channel:
            image_url = result.get("url")
            if image_url:
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url) as img_resp:
                        if img_resp.status == 200:
                            view.image_bytes = await img_resp.read()

            if view.image_bytes:
                file = discord.File(
                    fp=io.BytesIO(view.image_bytes),
                    filename="SPOILER_serika_preview.png",
                    spoiler=True
                )
                await interaction.followup.send(
                    content="👀 **Preview** (only you can see this)\n||⚠️ Questionable Image||",
                    file=file,
                    embed=embed,
                    view=view,
                    ephemeral=True
                )
                return

        await interaction.followup.send(
            content="👀 **Preview** (only you can see this)",
            embed=embed,
            view=view,
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SerikaImage(bot))