import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import logging
import io

logger = logging.getLogger(__name__)
SERIKA_BASE_URL = "https://serika.art/api/v1"


class SerikaImage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_key = os.getenv("SERIKA_BOORU_API")
        if not self.api_key:
            logger.warning("⚠️ SERIKA_BOORU_API not found in environment variables")

    async def fetch_image(self, rating: str = "safe"):
        """Fetch image with dynamic rating (safe or questionable)"""
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

    @app_commands.command(
        name="serika-image",
        description="Fetch a random image from Serika (Safe by default, questionable in NSFW channel)"
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
        # =================================

        result = await self.fetch_image(rating)

        if isinstance(result, dict) and "error" in result:
            return await interaction.followup.send(f"❌ Error: {result['error']}")

        image_url = result.get("url")
        thumb_url = result.get("thumbnail_url")
        tags = ", ".join([t["name"] for t in result.get("tags", [])]) or "None"
        rating_str = result.get("rating", "unknown")
        uploader = result.get("user", {}).get("username", "unknown")
        stats = result.get("stats", {})

        embed = discord.Embed(
            title=f"🎴 Serika {'❗ Questionable' if is_nsfw_channel else '✅ Safe'} Image",
            color=discord.Color.red() if is_nsfw_channel else discord.Color.green()
        )

        if thumb_url:
            embed.set_thumbnail(url=thumb_url)

        embed.add_field(name="Rating", value=rating_str.upper(), inline=True)
        embed.add_field(name="Uploader", value=uploader, inline=True)
        embed.add_field(name="Tags", value=tags, inline=False)

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
            # Download image and send as spoiler attachment
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as img_resp:
                    if img_resp.status == 200:
                        image_bytes = await img_resp.read()
                        # Discord recognizes files starting with SPOILER_ as spoiled
                        file = discord.File(
                            fp=io.BytesIO(image_bytes),  # need to import io
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