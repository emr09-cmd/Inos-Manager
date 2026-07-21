import discord
from discord import app_commands
from discord.ext import commands
import logging
from datetime import datetime, timedelta

import database

logger = logging.getLogger(__name__)

AUTHORIZED_USER_ID = 1236358212152852582
ALLOWED_GUILD_ID = 1464575233783631886
ALLOWED_CHANNEL_ID = 1505597064942325840


# ============================================================
# DB HELPERS — bans table
# ============================================================

def init_bans_table():
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bans (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                reason TEXT,
                banned_by TEXT,
                banned_at TIMESTAMP WITH TIME ZONE,
                expire_at TIMESTAMP WITH TIME ZONE
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Bans table verified.")
    except Exception as e:
        logger.error(f"❌ Failed to init bans table: {e}")


def db_add_ban(user_id: int, username: str, reason: str, banned_by: str, banned_at: datetime, expire_at: datetime | None):
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO bans (user_id, username, reason, banned_by, banned_at, expire_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                username = EXCLUDED.username,
                reason = EXCLUDED.reason,
                banned_by = EXCLUDED.banned_by,
                banned_at = EXCLUDED.banned_at,
                expire_at = EXCLUDED.expire_at
        ''', (user_id, username, reason, banned_by, banned_at.isoformat(), expire_at.isoformat() if expire_at else None))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to save ban for {user_id}: {e}")


def db_get_ban(user_id: int) -> dict | None:
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, reason, banned_by, banned_at, expire_at FROM bans WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        cols = [desc[0] for desc in cursor.description]
        cursor.close()
        conn.close()
        if row:
            return dict(zip(cols, row))
        return None
    except Exception as e:
        logger.error(f"❌ Failed to get ban for {user_id}: {e}")
        return None


def db_remove_ban(user_id: int) -> bool:
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bans WHERE user_id = %s", (user_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        cursor.close()
        conn.close()
        return deleted
    except Exception as e:
        logger.error(f"❌ Failed to remove ban for {user_id}: {e}")
        return False


# ============================================================
# COG
# ============================================================

class Ban(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_bans_table()

    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != ALLOWED_GUILD_ID:
            await interaction.response.send_message(
                "❌ This command is not available in this server.",
                ephemeral=True
            )
            return False
        if interaction.channel_id != ALLOWED_CHANNEL_ID:
            await interaction.response.send_message(
                f"❌ This command can only be used in <#{ALLOWED_CHANNEL_ID}>.",
                ephemeral=True
            )
            return False
        if interaction.user.id != AUTHORIZED_USER_ID:
            await interaction.response.send_message(
                "❌ You are not authorized to use this command.",
                ephemeral=True
            )
            return False
        return True

    # ── /ban ──
    @app_commands.command(name="ban", description="Ban a user from the server.")
    @app_commands.describe(
        user="The user to ban",
        reason="Reason for the ban",
        expire="Duration in days (0 = permanent)"
    )
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str, expire: int = 0):
        if not await self._check(interaction):
            return

        if user.id == interaction.user.id:
            return await interaction.response.send_message("❌ You cannot ban yourself.", ephemeral=True)
        if user.id == self.bot.user.id:
            return await interaction.response.send_message("❌ You cannot ban the bot.", ephemeral=True)

        now = datetime.utcnow()
        expire_at = None
        expire_str = "Permanent"
        if expire > 0:
            expire_at = now + timedelta(days=expire)
            expire_str = f"{expire} day(s) — expires <t:{int(expire_at.timestamp())}:R>"

        db_add_ban(
            user_id=user.id,
            username=str(user),
            reason=reason,
            banned_by=str(interaction.user),
            banned_at=now,
            expire_at=expire_at
        )
        logger.info(f"🔨 Banned {user} (ID: {user.id}) — reason: {reason} — expire: {expire_str}")

        embed = discord.Embed(title="🔨 User Banned", color=discord.Color.red())
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Duration", value=expire_str, inline=False)
        embed.add_field(name="Banned By", value=interaction.user.mention, inline=False)
        embed.set_footer(text=f"Banned at {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")

        # NOTE: Uncomment when bot has Ban Members permission.
        # await interaction.guild.ban(user, reason=reason, delete_message_days=0)

        await interaction.response.send_message(embed=embed)

    # ── /unban ──
    @app_commands.command(name="unban", description="Unban a user from the server.")
    @app_commands.describe(user="The user to unban")
    async def unban(self, interaction: discord.Interaction, user: discord.User):
        if not await self._check(interaction):
            return

        entry = db_get_ban(user.id)
        if not entry:
            return await interaction.response.send_message(
                f"❌ {user.mention} is not in the ban list.", ephemeral=True
            )

        db_remove_ban(user.id)
        logger.info(f"✅ Unbanned {user} (ID: {user.id})")

        embed = discord.Embed(title="✅ User Unbanned", color=discord.Color.green())
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Originally Banned For", value=entry.get("reason", "N/A"), inline=False)
        embed.add_field(name="Unbanned By", value=interaction.user.mention, inline=False)

        # NOTE: Uncomment when bot has Ban Members permission.
        # await interaction.guild.unban(user)

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ban(bot))