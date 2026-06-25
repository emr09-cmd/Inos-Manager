import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
import os
import logging

logger = logging.getLogger(__name__)

SERIKA_BASE_URL = "https://serika.art/api/v1"


class SerikaImage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_key = os.getenv("SERIKA_BOORU_API")

        if not self.api_key:
            logger.warning("⚠️ SERIKA_BOORU_API not found in environment variables")

    async def fetch_safe_image(self):
        url = f"{SERIKA_BASE_URL}/images"

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        params = {
            "limit": 1,
            "page": 1,
            "sort": "random",
            "ratings": "safe"   # 🔒 SAFE ONLY
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:

                # Rate limit handling
                if resp.status == 429:
                    return {"error": "RATE_LIMITED"}

                # Parse JSON safely
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

                # Extra safety check (belt + suspenders)
                if image.get("rating") != "safe":
                    return {"error": "NON_SAFE_BLOCKED"}

                return image

    @app_commands.command(
        name="serika-image",
        description="Fetch a random SAFE image from Serika"
    )
    async def serika_image(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if not self.api_key:
            return await interaction.followup.send(
                "❌ Missing API key. Set `SERIKA_BOORU_API` in your .env file."
            )

        result = await self.fetch_safe_image()

        if isinstance(result, dict) and "error" in result:
            return await interaction.followup.send(f"❌ Error: {result['error']}")

        image_url = result.get("url")
        thumb_url = result.get("thumbnail_url")

        tags = ", ".join([t["name"] for t in result.get("tags", [])])
        rating = result.get("rating", "unknown")
        uploader = result.get("user", {}).get("username", "unknown")
        stats = result.get("stats", {})

        embed = discord.Embed(
            title="🎴 Serika Safe Image",
            color=discord.Color.green()
        )

        if image_url:
            embed.set_image(url=image_url)

        if thumb_url:
            embed.set_thumbnail(url=thumb_url)

        embed.add_field(name="Rating", value=rating, inline=True)
        embed.add_field(name="Uploader", value=uploader, inline=True)
        embed.add_field(name="Tags", value=tags if tags else "None", inline=False)

        embed.set_footer(
            text=(
                f"👍 {stats.get('upvotes', 0)} | "
                f"👎 {stats.get('downvotes', 0)} | "
                f"⭐ {stats.get('favorites', 0)} | "
                f"👁 {stats.get('views', 0)}"
            )
        )

        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SerikaImage(bot))