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


def is_blacklisted(tags: list[dict]) -> bool:
    """
    Returns True if the image should be rerolled.
    Blacklist rule: has any boy tag (1boy, 2boys, etc.) AND no girl tag (1girl, 2girls, etc.)
    """
    tag_names = {t["name"].lower() for t in tags}

    has_boy = any(re.search(r"\d*boys?$", tag) for tag in tag_names)
    has_girl = any(re.search(r"\d*girls?$", tag) for tag in tag_names)

    return has_boy and not has_girl


class SerikaImage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_key = os.getenv("SERIKA_BOORU_API")
        if not self.api_key:
            logger.warning("⚠️ SERIKA_BOORU_API not found in environment variables")

    async def fetch_image(self, rating: str = "safe"):
        """Fetch a single random image from the API."""
        url = f"{SERIKA_BASE_URL}/images"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {
            "limit": 1,
            "page": 1,
            "sort": "random",
            "ratings": rating
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

                image = images[0]

                if image.get("rating") != rating:
                    return {"error": f"NON_{rating.upper()}_BLOCKED"}

                return image

    async def fetch_clean_image(self, rating: str, interaction: discord.Interaction):
        """
        Keeps rerolling until a non-blacklisted image is found or MAX_REROLLS is hit.
        Sends reroll notices to the channel as it goes.
        """
        for attempt in range(1, MAX_REROLLS + 1):
            result = await self.fetch_image(rating)

            if isinstance(result, dict) and "error" in result:
                return result, []

            tags = result.get("tags", [])

            if is_blacklisted(tags):
                blocked_tags = ", ".join(t["name"] for t in tags)
                logger.info(f"🔄 Reroll {attempt}/{MAX_REROLLS} — blacklisted tags: {blocked_tags}")
                await interaction.followup.send(
                    f"🚫 Image tags were blacklisted (boys without girls), finding another... "
                    f"*(attempt {attempt}/{MAX_REROLLS})*",
                    ephemeral=False
                )
                continue

            return result, tags

        return {"error": "BLACKLIST_EXHAUSTED"}, []

    @app_commands.command(
        name="serika-image",
        description="Fetch a random image from Serika Booru (Safe by default, questionable in NSFW channel)"
    )
    async def serika_image(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if not self.api_key:
            return await interaction.followup.send(
                "❌ Missing API key. Set `SERIKA_BOORU_API` in your .env file."
            )

        # === CHANNEL-BASED RATING LOGIC ===
        target_channel_id = 1516854766016397413
        is_nsfw_channel = interaction.channel_id == target_channel_id
        rating = "questionable" if is_nsfw_channel else "safe"
        # ===================================

        result, tags = await self.fetch_clean_image(rating, interaction)

        if isinstance(result, dict) and "error" in result:
            error = result["error"]
            if error == "BLACKLIST_EXHAUSTED":
                return await interaction.followup.send(
                    f"❌ Couldn't find a clean image after {MAX_REROLLS} attempts. Try again later!"
                )
            return await interaction.followup.send(f"❌ Error: {error}")

        image_url = result.get("url")
        thumb_url = result.get("thumbnail_url")
        tag_str = ", ".join([t["name"] for t in tags]) or "None"
        rating_str = result.get("rating", "unknown")
        uploader = result.get("user", {}).get("username", "unknown")
        stats = result.get("stats", {})

        embed = discord.Embed(
            title=f"🎴 Serika Booru {'❗ Questionable' if is_nsfw_channel else '✅ Safe'} Image",
            color=discord.Color.red() if is_nsfw_channel else discord.Color.green()
        )

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

        # === SPOILER THE IMAGE ITSELF ===
        if is_nsfw_channel and image_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as img_resp:
                    if img_resp.status == 200:
                        image_bytes = await img_resp.read()
                        file = discord.File(
                            fp=io.BytesIO(image_bytes),
                            filename="SPOILER_serika_image.png",
                            spoiler=True
                        )
                        await interaction.followup.send(content="||⚠️ Questionable Image||", file=file, embed=embed)
                        return

        # Safe images or fallback
        if image_url:
            embed.set_image(url=image_url)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SerikaImage(bot))