import discord
from discord import app_commands
from discord.ext import commands
import logging
import asyncio
from datetime import datetime, timedelta

import database

logger = logging.getLogger(__name__)

AUTHORIZED_USER_ID   = 1236358212152852582
ALLOWED_GUILD_ID     = 1464575233783631886
ALLOWED_CHANNEL_ID   = 1505597064942325840
INO_WIP_USER_ID      = 1505204063036244059   # Ino (WIP) bot

WAIT_SECONDS         = 10    # seconds to wait for Ino's confirmation
RETRY_TOTAL_SECONDS  = 120   # give up after 2 minutes total


# ============================================================
# DURATION PARSING
# s / m / h / d — 1s and 1y → permanent
# ============================================================

def parse_duration(raw: str) -> tuple[timedelta | None, str]:
    """
    Returns (timedelta | None, display_str).
    None means permanent.
    1s and 1y are forced to permanent per spec.
    """
    if not raw:
        return None, "permanent"

    raw = raw.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "y": 31536000}
    unit = raw[-1]
    if unit not in units:
        return None, "permanent"

    try:
        amount = int(raw[:-1])
    except ValueError:
        return None, "permanent"

    # 1s and 1y → permanent
    if (amount == 1 and unit == "s") or (amount == 1 and unit == "y"):
        return None, "permanent"

    seconds = amount * units[unit]
    td = timedelta(seconds=seconds)
    return td, raw


def duration_to_block_arg(raw: str | None) -> str:
    """Returns the string to append after <block @user, or empty for perm."""
    if not raw:
        return ""
    td, display = parse_duration(raw)
    if td is None:
        return ""          # permanent → no duration arg
    return f" {display}"  # e.g. " 30d"


# ============================================================
# DB HELPERS
# ============================================================

def init_bans_table():
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bans (
                user_id    BIGINT PRIMARY KEY,
                username   TEXT,
                reason     TEXT,
                banned_by  TEXT,
                banned_at  TIMESTAMP WITH TIME ZONE,
                expire_at  TIMESTAMP WITH TIME ZONE,
                confirmed  BOOLEAN DEFAULT FALSE
            )
        ''')
        conn.commit()
        cursor.close()
        conn.close()
        logger.info("✅ Bans table verified.")
    except Exception as e:
        logger.error(f"❌ Failed to init bans table: {e}")


def db_add_ban(user_id: int, username: str, reason: str, banned_by: str,
               banned_at: datetime, expire_at: datetime | None, confirmed: bool = False):
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO bans (user_id, username, reason, banned_by, banned_at, expire_at, confirmed)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                username  = EXCLUDED.username,
                reason    = EXCLUDED.reason,
                banned_by = EXCLUDED.banned_by,
                banned_at = EXCLUDED.banned_at,
                expire_at = EXCLUDED.expire_at,
                confirmed = EXCLUDED.confirmed
        ''', (user_id, username, reason, banned_by,
              banned_at.isoformat(),
              expire_at.isoformat() if expire_at else None,
              confirmed))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ db_add_ban failed for {user_id}: {e}")


def db_set_confirmed(user_id: int, confirmed: bool):
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE bans SET confirmed = %s WHERE user_id = %s", (confirmed, user_id))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ db_set_confirmed failed for {user_id}: {e}")


def db_get_ban(user_id: int) -> dict | None:
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT username, reason, banned_by, banned_at, expire_at, confirmed FROM bans WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        cols = [desc[0] for desc in cursor.description]
        cursor.close()
        conn.close()
        return dict(zip(cols, row)) if row else None
    except Exception as e:
        logger.error(f"❌ db_get_ban failed for {user_id}: {e}")
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
        logger.error(f"❌ db_remove_ban failed for {user_id}: {e}")
        return False


def db_get_unconfirmed() -> list[dict]:
    try:
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, username, expire_at FROM bans WHERE confirmed = FALSE")
        rows = cursor.fetchall()
        cols = [desc[0] for desc in cursor.description]
        cursor.close()
        conn.close()
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        logger.error(f"❌ db_get_unconfirmed failed: {e}")
        return []


# ============================================================
# COG
# ============================================================

class Ban(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_bans_table()
        # track pending confirmations: user_id → asyncio.Event
        self._pending: dict[int, asyncio.Event] = {}

    async def cog_load(self):
        self.bot.loop.create_task(self._retry_unconfirmed())

    async def _retry_unconfirmed(self):
        """On startup, re-send block commands for any bans still unconfirmed in the DB."""
        await self.bot.wait_until_ready()
        channel = self.bot.get_channel(ALLOWED_CHANNEL_ID)
        if not channel:
            logger.warning("⚠️ Could not find ban channel for unconfirmed retry.")
            return

        unconfirmed = db_get_unconfirmed()
        if not unconfirmed:
            return

        logger.info(f"🔄 Found {len(unconfirmed)} unconfirmed ban(s) — retrying block commands...")

        for entry in unconfirmed:
            user_id = entry["user_id"]
            expire_at = entry.get("expire_at")

            # Rebuild duration arg from expire_at
            duration_arg = ""
            if expire_at:
                now = datetime.utcnow()
                if isinstance(expire_at, str):
                    expire_at = datetime.fromisoformat(expire_at)
                remaining = expire_at - now
                if remaining.total_seconds() > 0:
                    days = remaining.days
                    hours, rem = divmod(remaining.seconds, 3600)
                    minutes = rem // 60
                    if days > 0:
                        duration_arg = f" {days}d"
                    elif hours > 0:
                        duration_arg = f" {hours}h"
                    elif minutes > 0:
                        duration_arg = f" {minutes}m"
                    # if time has already passed, treat as perm

            try:
                member = channel.guild.get_member(user_id)
                if not member:
                    member = await channel.guild.fetch_member(user_id)
            except Exception:
                logger.warning(f"⚠️ Could not find member {user_id} for unconfirmed ban retry — skipping.")
                continue

            logger.info(f"🔁 Retrying block for {member} (ID: {user_id}){duration_arg or ' [permanent]'}")
            confirmed = await self._send_block_with_retry(channel, member, duration_arg)

            if confirmed:
                logger.info(f"✅ Unconfirmed ban for {member} now confirmed.")
            else:
                logger.error(f"❌ Still could not confirm ban for {member} after retry.")

    # ── guard ──
    async def _check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != ALLOWED_GUILD_ID:
            await interaction.response.send_message("❌ This command is not available in this server.", ephemeral=True)
            return False
        if interaction.channel_id != ALLOWED_CHANNEL_ID:
            await interaction.response.send_message(f"❌ This command can only be used in <#{ALLOWED_CHANNEL_ID}>.", ephemeral=True)
            return False
        if interaction.user.id != AUTHORIZED_USER_ID:
            await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
            return False
        return True

    # ── listen for Ino (WIP) confirmation ──
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id != INO_WIP_USER_ID:
            return
        if message.channel.id != ALLOWED_CHANNEL_ID:
            return

        content = message.content
        # Look for 🔒 confirmation lines
        if "🔒" not in content and "🔓" not in content:
            return

        # Match against any pending ban user IDs
        for user_id, event in list(self._pending.items()):
            if str(user_id) in content or f"<@{user_id}>" in content:
                if "🔒" in content:
                    db_set_confirmed(user_id, True)
                    logger.info(f"✅ Ban confirmed by Ino (WIP) for user {user_id}")
                event.set()
                break

    # ── send block command and wait for Ino confirmation ──
    async def _send_block_with_retry(self, channel: discord.TextChannel,
                                     target: discord.Member, duration_arg: str) -> bool:
        """
        Sends <block @user [duration] to channel.
        Retries every WAIT_SECONDS until RETRY_TOTAL_SECONDS elapses.
        Returns True if Ino confirmed, False if timed out.
        """
        event = asyncio.Event()
        self._pending[target.id] = event

        block_cmd = f"<block {target.mention}{duration_arg}"
        elapsed = 0

        try:
            while elapsed < RETRY_TOTAL_SECONDS:
                await channel.send(block_cmd)
                try:
                    await asyncio.wait_for(event.wait(), timeout=WAIT_SECONDS)
                    return True   # Ino confirmed
                except asyncio.TimeoutError:
                    elapsed += WAIT_SECONDS
                    if elapsed < RETRY_TOTAL_SECONDS:
                        logger.warning(f"No response from Ino (WIP) after {elapsed}s, retrying...")
                    event.clear()
        finally:
            self._pending.pop(target.id, None)

        return False   # gave up

    # ── /ban ──
    @app_commands.command(name="ban", description="Ban a user from the server.")
    @app_commands.describe(
        user="The user to ban",
        reason="Reason for the ban",
        expire="Duration e.g. 30d, 6h, 15m — leave blank for permanent (1s and 1y also count as permanent)"
    )
    async def ban(self, interaction: discord.Interaction, user: discord.Member,
                  reason: str, expire: str = ""):
        if not await self._check(interaction):
            return
        if user.id == interaction.user.id:
            return await interaction.response.send_message("❌ You cannot ban yourself.", ephemeral=True)
        if user.id == self.bot.user.id:
            return await interaction.response.send_message("❌ You cannot ban the bot.", ephemeral=True)

        now = datetime.utcnow()
        td, display = parse_duration(expire)
        expire_at = (now + td) if td else None
        duration_arg = duration_to_block_arg(expire)

        expire_str = "Permanent" if not td else f"{display} — expires <t:{int(expire_at.timestamp())}:R>"

        # Save to DB as unconfirmed
        db_add_ban(
            user_id=user.id,
            username=str(user),
            reason=reason,
            banned_by=str(interaction.user),
            banned_at=now,
            expire_at=expire_at,
            confirmed=False
        )

        await interaction.response.send_message(
            f"⏳ Sending block command to Ino (WIP)... waiting for confirmation.",
            ephemeral=True
        )

        channel = interaction.channel
        confirmed = await self._send_block_with_retry(channel, user, duration_arg)

        if confirmed:
            embed = discord.Embed(title="🔨 User Banned", color=discord.Color.red())
            embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
            embed.add_field(name="Reason", value=reason, inline=False)
            embed.add_field(name="Duration", value=expire_str, inline=False)
            embed.add_field(name="Banned By", value=interaction.user.mention, inline=False)
            embed.set_footer(text=f"Confirmed by Ino (WIP) • {now.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            await channel.send(embed=embed)
            await interaction.edit_original_response(content="✅ Ban applied and confirmed by Ino (WIP).")
        else:
            db_remove_ban(user.id)
            await interaction.edit_original_response(
                content=f"❌ Ino (WIP) did not confirm the block for {user.mention} after {RETRY_TOTAL_SECONDS}s. Ban cancelled."
            )
            logger.error(f"Ban for {user} timed out — Ino (WIP) never responded.")

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

        await interaction.response.send_message(
            f"⏳ Sending unblock command to Ino (WIP)...", ephemeral=True
        )

        channel = interaction.channel
        await channel.send(f"<unblock {user.mention}")

        db_remove_ban(user.id)

        embed = discord.Embed(title="✅ User Unbanned", color=discord.Color.green())
        embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name="Originally Banned For", value=entry.get("reason", "N/A"), inline=False)
        embed.add_field(name="Unbanned By", value=interaction.user.mention, inline=False)
        await channel.send(embed=embed)
        await interaction.edit_original_response(content="✅ Unblock command sent.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Ban(bot))
