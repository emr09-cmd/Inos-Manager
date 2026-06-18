import discord
from discord.ext import commands
import asyncio

TARGET_CHANNEL_ID = 1505597064942325840
ALLOWED_USER_ID = 1236358212152852582


class DeleteMessageChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.running = False

    # -------------------------
    # PREFIX COMMAND (R!)
    # -------------------------
    @commands.command(name="delete-message-channel")
    async def delete_message_channel_prefix(self, ctx):
        await self._run(ctx)

    # -------------------------
    # SLASH COMMAND (/)
    # -------------------------
    @discord.app_commands.command(name="delete-message-channel")
    async def delete_message_channel_slash(self, interaction: discord.Interaction):
        await self._run(interaction)

    # -------------------------
    # CORE LOGIC
    # -------------------------
    async def _run(self, ctx_or_interaction):

        # Prevent double execution
        if self.running:
            msg = "⚠️ Purge already running..."
            if isinstance(ctx_or_interaction, discord.Interaction):
                return await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            return await ctx_or_interaction.send(msg)

        user = (
            ctx_or_interaction.user
            if isinstance(ctx_or_interaction, discord.Interaction)
            else ctx_or_interaction.author
        )

        # 🔒 Only allowed user
        if user.id != ALLOWED_USER_ID:
            msg = "❌ You are not allowed to use this command."

            if isinstance(ctx_or_interaction, discord.Interaction):
                return await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            return await ctx_or_interaction.send(msg)

        guild = ctx_or_interaction.guild
        if not guild:
            return

        channel = guild.get_channel(TARGET_CHANNEL_ID)
        if not channel:
            msg = "❌ Target channel not found."

            if isinstance(ctx_or_interaction, discord.Interaction):
                return await ctx_or_interaction.response.send_message(msg, ephemeral=True)
            return await ctx_or_interaction.send(msg)

        self.running = True

        try:
            # Acknowledge
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.response.send_message(
                    f"🧹 Starting purge in {channel.mention}...", ephemeral=True
                )
            else:
                await ctx_or_interaction.send(f"🧹 Starting purge in {channel.mention}...")

            deleted_total = 0

            # -------------------------
            # 🔥 FAST BULK PURGE LOOP
            # -------------------------
            while True:
                deleted = await channel.purge(limit=100)
                deleted_total += len(deleted)

                if len(deleted) == 0:
                    break

                # avoid rate limits
                await asyncio.sleep(1.2)

            # -------------------------
            # AFTER PURGE CLEANUP
            # -------------------------

            # delete command message (prefix only)
            if not isinstance(ctx_or_interaction, discord.Interaction):
                try:
                    await ctx_or_interaction.message.delete()
                except:
                    pass

            result = f"✅ Purge complete: {deleted_total} messages deleted."

            # send final result
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(result, ephemeral=True)
            else:
                msg = await ctx_or_interaction.send(result)

                # auto delete bot message after a few seconds
                await asyncio.sleep(3)
                try:
                    await msg.delete()
                except:
                    pass

        except discord.Forbidden:
            error = "❌ Missing permissions (Manage Messages required)."
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(error, ephemeral=True)
            else:
                await ctx_or_interaction.send(error)

        except Exception as e:
            error = f"❌ Error during purge: {e}"
            if isinstance(ctx_or_interaction, discord.Interaction):
                await ctx_or_interaction.followup.send(error, ephemeral=True)
            else:
                await ctx_or_interaction.send(error)

        finally:
            self.running = False


async def setup(bot):
    await bot.add_cog(DeleteMessageChannel(bot))