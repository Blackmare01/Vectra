"""Vectra moderation and support bot. Run as a persistent process, not a Vercel Function."""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("VECTRA_DB_PATH", "data/vectra.sqlite3")
BRAND = 0x7867F0
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


with db() as con:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS settings (
            guild_id INTEGER PRIMARY KEY, mod_log INTEGER, message_log INTEGER,
            member_log INTEGER, role_log INTEGER, channel_log INTEGER, ticket_category INTEGER
        );
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS automod_settings (
            guild_id INTEGER PRIMARY KEY, invite_filter INTEGER NOT NULL DEFAULT 0,
            timeout_minutes INTEGER NOT NULL DEFAULT 10
        );
    """)


intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.messages = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

LOG_FIELDS = {
    "moderation": "mod_log", "messages": "message_log", "members": "member_log",
    "roles": "role_log", "channels": "channel_log",
}
INVITE_LINK = re.compile(r"(?i)(?:https?://)?(?:www\.)?(?:discord\.gg/[a-z0-9-]+|discord(?:app)?\.com/invite/[a-z0-9-]+)")


def setting(guild_id: int, key: str):
    with db() as con:
        row = con.execute(f"SELECT {key} FROM settings WHERE guild_id=?", (guild_id,)).fetchone()
        return row[key] if row else None


def set_setting(guild_id: int, key: str, value: Optional[int]):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO settings(guild_id) VALUES(?)", (guild_id,))
        con.execute(f"UPDATE settings SET {key}=? WHERE guild_id=?", (value, guild_id))


def invite_filter_settings(guild_id: int):
    with db() as con:
        row = con.execute("SELECT invite_filter,timeout_minutes FROM automod_settings WHERE guild_id=?", (guild_id,)).fetchone()
        return (bool(row["invite_filter"]), row["timeout_minutes"]) if row else (False, 10)


def set_invite_filter(guild_id: int, enabled: bool, minutes: int):
    with db() as con:
        con.execute("INSERT INTO automod_settings(guild_id,invite_filter,timeout_minutes) VALUES(?,?,?) "
                    "ON CONFLICT(guild_id) DO UPDATE SET invite_filter=excluded.invite_filter, timeout_minutes=excluded.timeout_minutes",
                    (guild_id, int(enabled), minutes))


async def log(guild: discord.Guild, key: str, title: str, detail: str, color: int = BRAND):
    channel_id = setting(guild.id, key)
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel:
        embed = discord.Embed(title=title, description=detail, color=color, timestamp=datetime.now(timezone.utc))
        await channel.send(embed=embed)


def moderation_embed(title: str, member: discord.abc.User, moderator: discord.abc.User, reason: str):
    return discord.Embed(title=title, description=f"**User:** {member.mention} (`{member.id}`)\n**Moderator:** {moderator.mention}\n**Reason:** {reason}", color=BRAND, timestamp=datetime.now(timezone.utc))


async def moderation_log(guild: discord.Guild, title: str, member: discord.abc.User, moderator: discord.abc.User, reason: str):
    channel_id = setting(guild.id, "mod_log")
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel:
        await channel.send(embed=moderation_embed(title, member, moderator, reason))


def prefix_hierarchy_error(ctx: commands.Context, member: discord.Member) -> Optional[str]:
    if member.id == ctx.author.id:
        return "You cannot apply this action to yourself."
    if member.id == ctx.guild.owner_id:
        return "The server owner cannot be moderated."
    if member.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
        return "Your highest role must be above the target's role."
    if member.top_role >= ctx.guild.me.top_role:
        return "Vectra's highest role must be above the target's role."
    return None


def hierarchy_check(interaction: discord.Interaction, member: discord.Member):
    if member.id == interaction.user.id:
        raise app_commands.AppCommandError("You cannot apply this action to yourself.")
    if member.id == interaction.guild.owner_id:
        raise app_commands.AppCommandError("The server owner cannot be moderated.")
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        raise app_commands.AppCommandError("Your highest role must be above the target's role.")
    if member.top_role >= interaction.guild.me.top_role:
        raise app_commands.AppCommandError("Vectra's highest role must be above the target's role.")


async def ephemeral(interaction: discord.Interaction, text: str):
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


@bot.command(name="help")
async def prefix_help(ctx: commands.Context):
    embed = discord.Embed(title="Vectra commands", description="Use slash commands or prefix commands starting with `!`.", color=BRAND)
    embed.add_field(name="Moderation", value="`!warn`, `!warnings`, `!clear-warnings`, `!mute`, `!timeout`, `!untimeout`, `!kick`, `!ban`, `!unban`, `!purge`, `!slowmode`, `!lock`, `!unlock`, `!linkfilter`", inline=False)
    embed.add_field(name="Tickets & logs", value="`!ticket-panel`, `!setup-logs`, `!logs`", inline=False)
    await ctx.send(embed=embed)


@bot.tree.command(name="help", description="Show Vectra's command list")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(title="Vectra commands", description="Use a slash command or its `!` prefix equivalent.", color=BRAND)
    embed.add_field(name="Moderation", value="`/warn`, `/warnings`, `/clear-warnings`, `/mute`, `/timeout`, `/untimeout`, `/kick`, `/ban`, `/unban`, `/purge`, `/slowmode`, `/lock`, `/unlock`", inline=False)
    embed.add_field(name="Tickets & logs", value="`/ticket-panel`, `/setup-logs`, `/logs`, `/link-filter`", inline=False)
    embed.add_field(name="Prefix help", value="Run `!help` for the prefix command list. Configure invite filtering with `!linkfilter on [minutes]`.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.command(name="linkfilter")
@commands.has_permissions(manage_guild=True)
async def prefix_link_filter(ctx: commands.Context, mode: Optional[str] = None, minutes: Optional[int] = None):
    enabled, current_minutes = invite_filter_settings(ctx.guild.id)
    if mode is None or mode.lower() == "status":
        await ctx.send(f"Discord invite filter is **{'ON' if enabled else 'OFF'}**. Timeout: **{current_minutes} minutes**. Use `!linkfilter on [minutes]` or `!linkfilter off`.")
        return
    if mode.lower() not in ("on", "off"):
        await ctx.send("Use `!linkfilter on [minutes]`, `!linkfilter off`, or `!linkfilter status`.")
        return
    timeout_minutes = minutes if minutes is not None else current_minutes
    if not 1 <= timeout_minutes <= 40320:
        await ctx.send("Timeout duration must be between 1 and 40320 minutes.")
        return
    set_invite_filter(ctx.guild.id, mode.lower() == "on", timeout_minutes)
    await ctx.send(f"Discord invite filter is now **{'ON' if mode.lower() == 'on' else 'OFF'}**. Timeout: **{timeout_minutes} minutes**.")


@bot.tree.command(name="link-filter", description="Configure automatic Discord invite link deletion and timeout")
@app_commands.describe(enabled="Delete Discord invite links and timeout their sender", timeout_minutes="Timeout duration when an invite is posted")
@app_commands.checks.has_permissions(manage_guild=True)
async def slash_link_filter(interaction: discord.Interaction, enabled: bool, timeout_minutes: app_commands.Range[int, 1, 40320] = 10):
    set_invite_filter(interaction.guild_id, enabled, timeout_minutes)
    status = "enabled" if enabled else "disabled"
    await ephemeral(interaction, f"Discord invite filter {status}. Timeout duration: **{timeout_minutes} minutes**.")


@bot.command(name="warn")
@commands.has_permissions(moderate_members=True)
async def prefix_warn(ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
    error = prefix_hierarchy_error(ctx, member)
    if error:
        await ctx.send(error)
        return
    with db() as con:
        cur = con.execute("INSERT INTO warnings(guild_id,user_id,moderator_id,reason,created_at) VALUES(?,?,?,?,?)",
                          (ctx.guild.id, member.id, ctx.author.id, reason[:1000], datetime.now(timezone.utc).isoformat()))
    await ctx.send(f"⚠️ Warned {member.mention}. Warning **#{cur.lastrowid}** recorded.")
    await moderation_log(ctx.guild, "Member warned", member, ctx.author, reason)


@bot.command(name="warnings")
@commands.has_permissions(moderate_members=True)
async def prefix_warnings(ctx: commands.Context, member: discord.Member):
    with db() as con:
        rows = con.execute("SELECT id,moderator_id,reason,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10", (ctx.guild.id, member.id)).fetchall()
    embed = discord.Embed(title=f"Warnings · {member}", color=BRAND)
    embed.description = "\n".join(f"**#{r['id']}** · <@{r['moderator_id']}> · {discord.utils.escape_markdown(r['reason'])[:220]} · <t:{int(datetime.fromisoformat(r['created_at']).timestamp())}:R>" for r in rows) or "No warnings found."
    await ctx.send(embed=embed)


@bot.command(name="clear-warnings")
@commands.has_permissions(moderate_members=True)
async def prefix_clear_warnings(ctx: commands.Context, member: discord.Member):
    with db() as con:
        cur = con.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
    await ctx.send(f"Cleared **{cur.rowcount}** warning(s) for {member.mention}.")
    await moderation_log(ctx.guild, "Warnings cleared", member, ctx.author, f"{cur.rowcount} warning(s) cleared")


@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def prefix_mute(ctx: commands.Context, member: discord.Member, minutes: int, *, reason: str = "No reason provided"):
    error = prefix_hierarchy_error(ctx, member)
    if error:
        await ctx.send(error)
        return
    if not 1 <= minutes <= 40320:
        await ctx.send("Duration must be between 1 and 40320 minutes.")
        return
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await ctx.send(f"Muted {member.mention} for **{minutes} minutes**.")
    await moderation_log(ctx.guild, "Member muted", member, ctx.author, f"{minutes} minutes · {reason}")


@bot.command(name="timeout")
@commands.has_permissions(moderate_members=True)
async def prefix_timeout(ctx: commands.Context, member: discord.Member, minutes: int, *, reason: str = "No reason provided"):
    error = prefix_hierarchy_error(ctx, member)
    if error:
        await ctx.send(error)
        return
    if not 1 <= minutes <= 40320:
        await ctx.send("Duration must be between 1 and 40320 minutes.")
        return
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await ctx.send(f"Timed out {member.mention} for **{minutes} minutes**.")
    await moderation_log(ctx.guild, "Member timed out", member, ctx.author, f"{minutes} minutes · {reason}")


@bot.command(name="untimeout")
@commands.has_permissions(moderate_members=True)
async def prefix_untimeout(ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
    error = prefix_hierarchy_error(ctx, member)
    if error:
        await ctx.send(error)
        return
    await member.timeout(None, reason=reason)
    await ctx.send(f"Timeout removed for {member.mention}.")
    await moderation_log(ctx.guild, "Timeout removed", member, ctx.author, reason)


@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def prefix_kick(ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
    error = prefix_hierarchy_error(ctx, member)
    if error:
        await ctx.send(error)
        return
    await member.kick(reason=reason)
    await ctx.send(f"Kicked **{member}**.")
    await moderation_log(ctx.guild, "Member kicked", member, ctx.author, reason)


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def prefix_ban(ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
    error = prefix_hierarchy_error(ctx, member)
    if error:
        await ctx.send(error)
        return
    await ctx.guild.ban(member, reason=reason)
    await ctx.send(f"Banned **{member}**.")
    await moderation_log(ctx.guild, "Member banned", member, ctx.author, reason)


@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def prefix_unban(ctx: commands.Context, user_id: int, *, reason: str = "No reason provided"):
    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=reason)
    except discord.NotFound:
        await ctx.send("That user is not banned, or the ID is invalid.")
        return
    await ctx.send(f"Unbanned **{user}**.")
    await moderation_log(ctx.guild, "Member unbanned", user, ctx.author, reason)


@bot.command(name="purge")
@commands.has_permissions(manage_messages=True)
async def prefix_purge(ctx: commands.Context, amount: int, member: Optional[discord.Member] = None):
    if not 1 <= amount <= 100:
        await ctx.send("Choose an amount from 1 to 100.")
        return
    if member:
        deleted = await ctx.channel.purge(limit=amount + 1, check=lambda message: message.author.id == member.id)
    else:
        deleted = await ctx.channel.purge(limit=amount + 1)
    count = sum(1 for message in deleted if message.id != ctx.message.id)
    notice = await ctx.send(f"Deleted **{count}** message(s).")
    await log(ctx.guild, "message_log", "Messages purged", f"{ctx.author.mention} deleted {count} messages in {ctx.channel.mention}.")
    await notice.delete(delay=5)


@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
async def prefix_slowmode(ctx: commands.Context, seconds: int):
    if not 0 <= seconds <= 21600:
        await ctx.send("Choose a duration from 0 to 21600 seconds.")
        return
    await ctx.channel.edit(slowmode_delay=seconds, reason=f"Set by {ctx.author}")
    await ctx.send(f"Slowmode set to **{seconds} seconds**.")
    await log(ctx.guild, "channel_log", "Slowmode changed", f"{ctx.author.mention} set slowmode in {ctx.channel.mention} to {seconds}s.")


@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
async def prefix_lock(ctx: commands.Context):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=False, reason=f"Locked by {ctx.author}")
    await ctx.send("🔒 Channel locked for @everyone.")
    await log(ctx.guild, "channel_log", "Channel locked", f"{ctx.channel.mention} locked by {ctx.author.mention}.")


@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
async def prefix_unlock(ctx: commands.Context):
    await ctx.channel.set_permissions(ctx.guild.default_role, send_messages=None, reason=f"Unlocked by {ctx.author}")
    await ctx.send("🔓 Channel unlocked.")
    await log(ctx.guild, "channel_log", "Channel unlocked", f"{ctx.channel.mention} unlocked by {ctx.author.mention}.")


@bot.command(name="setup-logs")
@commands.has_permissions(manage_guild=True)
async def prefix_setup_logs(ctx: commands.Context, category: str, channel: Optional[discord.TextChannel] = None):
    key = LOG_FIELDS.get(category.lower())
    if not key:
        await ctx.send("Choose a category: moderation, messages, members, roles, or channels.")
        return
    set_setting(ctx.guild.id, key, channel.id if channel else None)
    await ctx.send(f"{category.title()} logging {f'will go to {channel.mention}' if channel else 'is disabled'}.")


@bot.command(name="logs")
@commands.has_permissions(manage_guild=True)
async def prefix_logs(ctx: commands.Context):
    embed = discord.Embed(title="Vectra log destinations", color=BRAND)
    for label, key in LOG_FIELDS.items():
        channel = ctx.guild.get_channel(setting(ctx.guild.id, key) or 0)
        embed.add_field(name=label.title(), value=channel.mention if channel else "Disabled", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="ticket-panel")
@commands.has_permissions(manage_guild=True)
async def prefix_ticket_panel(ctx: commands.Context, category: Optional[discord.CategoryChannel] = None):
    set_setting(ctx.guild.id, "ticket_category", category.id if category else None)
    embed = discord.Embed(title="Contact the staff team", description="Press the button below to open a private support channel. Only you and the staff can see it.", color=BRAND)
    await ctx.send(embed=embed, view=TicketOpenView())
    await ctx.send("Ticket panel posted.", delete_after=5)


@bot.event
async def on_ready():
    if not getattr(bot, "_synced", False):
        synced = await bot.tree.sync()
        bot._synced = True
        print(f"Synced {len(synced)} commands")
    print(f"Vectra ready as {bot.user} ({bot.user.id})")


@bot.tree.command(name="setup-logs", description="Choose or clear a channel for a Vectra event log")
@app_commands.describe(category="Which events to log", channel="Leave empty to disable this log")
@app_commands.choices(category=[app_commands.Choice(name=x.title(), value=x) for x in LOG_FIELDS])
@app_commands.checks.has_permissions(manage_guild=True)
async def setup_logs(interaction: discord.Interaction, category: app_commands.Choice[str], channel: Optional[discord.TextChannel] = None):
    key = LOG_FIELDS[category.value]
    set_setting(interaction.guild_id, key, channel.id if channel else None)
    await ephemeral(interaction, f"{category.name} logging {f'will go to {channel.mention}' if channel else 'is disabled'}.")


@bot.tree.command(name="logs", description="Show the configured Vectra log destinations")
@app_commands.checks.has_permissions(manage_guild=True)
async def show_logs(interaction: discord.Interaction):
    embed = discord.Embed(title="Vectra log destinations", color=BRAND)
    for label, key in LOG_FIELDS.items():
        channel = interaction.guild.get_channel(setting(interaction.guild_id, key) or 0)
        embed.add_field(name=label.title(), value=channel.mention if channel else "Disabled", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="warn", description="Record a warning for a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn_member(interaction: discord.Interaction, member: discord.Member, reason: str):
    hierarchy_check(interaction, member)
    with db() as con:
        cur = con.execute("INSERT INTO warnings(guild_id,user_id,moderator_id,reason,created_at) VALUES(?,?,?,?,?)",
                          (interaction.guild_id, member.id, interaction.user.id, reason[:1000], datetime.now(timezone.utc).isoformat()))
        warning_id = cur.lastrowid
    await ephemeral(interaction, f"⚠️ Warned {member.mention}. Warning **#{warning_id}** recorded.")
    await moderation_log(interaction.guild, "Member warned", member, interaction.user, reason)


@bot.tree.command(name="warnings", description="Review a member's warning history")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(interaction: discord.Interaction, member: discord.Member):
    with db() as con:
        rows = con.execute("SELECT id,moderator_id,reason,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10", (interaction.guild_id, member.id)).fetchall()
    embed = discord.Embed(title=f"Warnings · {member}", color=BRAND)
    embed.description = "\n".join(f"**#{r['id']}** · <@{r['moderator_id']}> · {discord.utils.escape_markdown(r['reason'])[:220]} · <t:{int(datetime.fromisoformat(r['created_at']).timestamp())}:R>" for r in rows) or "No warnings found."
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clear-warnings", description="Clear a member's warning history")
@app_commands.checks.has_permissions(moderate_members=True)
async def clear_warnings(interaction: discord.Interaction, member: discord.Member):
    with db() as con:
        cur = con.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (interaction.guild_id, member.id))
    await ephemeral(interaction, f"Cleared **{cur.rowcount}** warning(s) for {member.mention}.")
    await moderation_log(interaction.guild, "Warnings cleared", member, interaction.user, f"{cur.rowcount} warning(s) cleared")


@bot.tree.command(name="timeout", description="Timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def timeout_member(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str):
    hierarchy_check(interaction, member)
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await ephemeral(interaction, f"Timed out {member.mention} for **{minutes} minutes**.")
    await moderation_log(interaction.guild, "Member timed out", member, interaction.user, f"{minutes} minutes · {reason}")


@bot.tree.command(name="mute", description="Mute a member with a Discord timeout")
@app_commands.checks.has_permissions(moderate_members=True)
async def mute_member(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str):
    hierarchy_check(interaction, member)
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await ephemeral(interaction, f"Muted {member.mention} for **{minutes} minutes**.")
    await moderation_log(interaction.guild, "Member muted", member, interaction.user, f"{minutes} minutes · {reason}")


@bot.tree.command(name="untimeout", description="Remove a member's timeout")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout_member(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    hierarchy_check(interaction, member)
    await member.timeout(None, reason=reason)
    await ephemeral(interaction, f"Timeout removed for {member.mention}.")
    await moderation_log(interaction.guild, "Timeout removed", member, interaction.user, reason)


@bot.tree.command(name="kick", description="Kick a member")
@app_commands.checks.has_permissions(kick_members=True)
async def kick_member(interaction: discord.Interaction, member: discord.Member, reason: str):
    hierarchy_check(interaction, member)
    await member.kick(reason=reason)
    await ephemeral(interaction, f"Kicked **{member}**.")
    await moderation_log(interaction.guild, "Member kicked", member, interaction.user, reason)


@bot.tree.command(name="ban", description="Ban a member")
@app_commands.checks.has_permissions(ban_members=True)
async def ban_member(interaction: discord.Interaction, member: discord.Member, reason: str, delete_days: app_commands.Range[int, 0, 7] = 0):
    hierarchy_check(interaction, member)
    await interaction.guild.ban(member, reason=reason, delete_message_seconds=delete_days * 86400)
    await ephemeral(interaction, f"Banned **{member}**.")
    await moderation_log(interaction.guild, "Member banned", member, interaction.user, reason)


@bot.tree.command(name="unban", description="Unban a user by ID")
@app_commands.checks.has_permissions(ban_members=True)
async def unban_member(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user, reason=reason)
    except (ValueError, discord.NotFound):
        await ephemeral(interaction, "That user is not banned, or the ID is invalid.")
        return
    await ephemeral(interaction, f"Unbanned **{user}**.")
    await moderation_log(interaction.guild, "Member unbanned", user, interaction.user, reason)


@bot.tree.command(name="purge", description="Bulk delete recent messages (up to 100)")
@app_commands.checks.has_permissions(manage_messages=True)
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100], member: Optional[discord.Member] = None):
    await interaction.response.defer(ephemeral=True)
    if member:
        deleted = await interaction.channel.purge(limit=amount, check=lambda message: message.author.id == member.id)
    else:
        deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"Deleted **{len(deleted)}** message(s).", ephemeral=True)
    await log(interaction.guild, "message_log", "Messages purged", f"{interaction.user.mention} deleted {len(deleted)} messages in {interaction.channel.mention}.")


@bot.tree.command(name="slowmode", description="Set the channel slowmode")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]):
    await interaction.channel.edit(slowmode_delay=seconds, reason=f"Set by {interaction.user}")
    await ephemeral(interaction, f"Slowmode set to **{seconds} seconds**.")
    await log(interaction.guild, "channel_log", "Slowmode changed", f"{interaction.user.mention} set slowmode in {interaction.channel.mention} to {seconds}s.")


@bot.tree.command(name="lock", description="Lock this text channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock_channel(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False, reason=f"Locked by {interaction.user}")
    await ephemeral(interaction, "🔒 Channel locked for @everyone.")
    await log(interaction.guild, "channel_log", "Channel locked", f"{interaction.channel.mention} locked by {interaction.user.mention}.")


@bot.tree.command(name="unlock", description="Unlock this text channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock_channel(interaction: discord.Interaction):
    await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=None, reason=f"Unlocked by {interaction.user}")
    await ephemeral(interaction, "🔓 Channel unlocked.")
    await log(interaction.guild, "channel_log", "Channel unlocked", f"{interaction.channel.mention} unlocked by {interaction.user.mention}.")


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close ticket", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="vectra:ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels and interaction.channel.topic != f"vectra-ticket:{interaction.user.id}":
            await ephemeral(interaction, "Only the ticket owner or a moderator can close this ticket.")
            return
        await interaction.response.send_message("Closing ticket…", ephemeral=True)
        await log(interaction.guild, "member_log", "Ticket closed", f"{interaction.channel.mention} closed by {interaction.user.mention}.")
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")


class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open a staff ticket", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="vectra:ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        existing = discord.utils.find(lambda c: isinstance(c, discord.TextChannel) and c.topic == f"vectra-ticket:{interaction.user.id}", guild.text_channels)
        if existing:
            await ephemeral(interaction, f"You already have a ticket: {existing.mention}")
            return
        category_id = setting(guild.id, "ticket_category")
        category = guild.get_channel(category_id) if category_id else None
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        for role in guild.roles:
            if role.permissions.manage_channels:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        channel = await guild.create_text_channel(f"ticket-{interaction.user.name}"[:90], category=category, overwrites=overwrites, topic=f"vectra-ticket:{interaction.user.id}", reason="Vectra support ticket")
        await channel.send(f"{interaction.user.mention} Thanks for contacting the staff team. Share the details here and a moderator will help.", view=TicketCloseView())
        await interaction.response.send_message(f"Your private ticket is ready: {channel.mention}", ephemeral=True)
        await log(guild, "member_log", "Ticket opened", f"{channel.mention} opened by {interaction.user.mention}.")


@bot.tree.command(name="ticket-panel", description="Post a staff ticket panel in this channel")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(category="Optional category for newly created tickets")
async def ticket_panel(interaction: discord.Interaction, category: Optional[discord.CategoryChannel] = None):
    set_setting(interaction.guild_id, "ticket_category", category.id if category else None)
    embed = discord.Embed(title="Contact the staff team", description="Press the button below to open a private support channel. Only you and the staff can see it.", color=BRAND)
    await interaction.channel.send(embed=embed, view=TicketOpenView())
    await ephemeral(interaction, "Ticket panel posted.")


async def enforce_invite_filter(message: discord.Message):
    if message.guild and isinstance(message.author, discord.Member) and not message.author.bot:
        enabled, timeout_minutes = invite_filter_settings(message.guild.id)
        author = message.author
        is_staff = author.id == message.guild.owner_id or author.guild_permissions.administrator or author.guild_permissions.manage_messages or author.guild_permissions.moderate_members
        if enabled and not is_staff and INVITE_LINK.search(message.content):
            deleted = False
            try:
                await message.delete()
                deleted = True
            except discord.NotFound:
                deleted = True
            except discord.HTTPException as exc:
                print(f"Could not delete invite from {author.id}: {exc!r}")
            reason = f"Posted a Discord invite in #{getattr(message.channel, 'name', 'unknown')}; message deletion {'succeeded' if deleted else 'failed'}"
            try:
                await author.timeout(timedelta(minutes=timeout_minutes), reason="Vectra automatic Discord invite filter")
                reason += f"; timed out for {timeout_minutes} minutes"
            except discord.HTTPException as exc:
                reason += f"; timeout failed ({type(exc).__name__})"
                print(f"Could not timeout invite sender {author.id}: {exc!r}")
            if bot.user:
                await moderation_log(message.guild, "Discord invite auto-moderation", author, bot.user, reason)


@bot.event
async def on_message(message: discord.Message):
    await enforce_invite_filter(message)
    await bot.process_commands(message)


@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild and not message.author.bot:
        content = INVITE_LINK.sub("[Discord invite link]", message.content[:1200] or "[no text]")
        content = discord.utils.escape_mentions(content)
        await log(message.guild, "message_log", "Message deleted", f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Content:** {content}", 0xED5B68)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.guild and not before.author.bot and before.content != after.content:
        await enforce_invite_filter(after)
        before_text = discord.utils.escape_mentions(INVITE_LINK.sub("[Discord invite link]", before.content[:700] or "[empty]"))
        after_text = discord.utils.escape_mentions(INVITE_LINK.sub("[Discord invite link]", after.content[:700] or "[empty]"))
        await log(before.guild, "message_log", "Message edited", f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}\n[Jump to message]({after.jump_url})\n**Before:** {before_text}\n**After:** {after_text}")


@bot.event
async def on_member_join(member: discord.Member):
    await log(member.guild, "member_log", "Member joined", f"{member.mention} (`{member.id}`) joined. Account created <t:{int(member.created_at.timestamp())}:R>.", 0x48C78E)


@bot.event
async def on_member_remove(member: discord.Member):
    await log(member.guild, "member_log", "Member left", f"**{member}** (`{member.id}`) left or was removed.", 0xED5B68)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.roles != after.roles:
        old, new = set(before.roles), set(after.roles)
        added = ", ".join(r.mention for r in new - old) or "None"
        removed = ", ".join(r.mention for r in old - new) or "None"
        await log(after.guild, "role_log", "Member roles changed", f"**Member:** {after.mention}\n**Added:** {added}\n**Removed:** {removed}")
    if before.nick != after.nick:
        await log(after.guild, "member_log", "Nickname changed", f"{after.mention}: `{before.nick or before.name}` → `{after.nick or after.name}`")


@bot.event
async def on_guild_role_create(role: discord.Role):
    await log(role.guild, "role_log", "Role created", f"{role.mention} (`{role.id}`)", 0x48C78E)


@bot.event
async def on_guild_role_delete(role: discord.Role):
    await log(role.guild, "role_log", "Role deleted", f"**{role.name}** (`{role.id}`)", 0xED5B68)


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    changes = []
    if before.name != after.name:
        changes.append(f"Name: `{before.name}` → `{after.name}`")
    if before.permissions != after.permissions:
        changes.append("Permissions changed")
    if before.color != after.color:
        changes.append("Color changed")
    if changes:
        await log(after.guild, "role_log", "Role updated", f"**Role:** {after.mention}\n" + "\n".join(changes))


@bot.event
async def on_guild_channel_create(channel: discord.abc.GuildChannel):
    await log(channel.guild, "channel_log", "Channel created", f"{channel.mention if hasattr(channel, 'mention') else channel.name} (`{channel.id}`)", 0x48C78E)


@bot.event
async def on_guild_channel_delete(channel: discord.abc.GuildChannel):
    await log(channel.guild, "channel_log", "Channel deleted", f"**{channel.name}** (`{channel.id}`)", 0xED5B68)


@bot.event
async def on_guild_channel_update(before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
    if before.name != after.name:
        await log(after.guild, "channel_log", "Channel renamed", f"`{before.name}` → {after.mention if hasattr(after, 'mention') else after.name}")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You don't have permission to use this command."
    elif isinstance(error, app_commands.CommandInvokeError):
        print(f"Command error: {error.original!r}")
        message = f"Action failed: {error.original}" if isinstance(error.original, discord.Forbidden) else "Something went wrong while running that command. Check Vectra's role and channel permissions."
    else:
        message = str(error) or "Something went wrong."
    await ephemeral(interaction, message)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        message = "You don't have permission to use this command."
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        message = f"Check the command format with `!help`. ({error})"
    elif isinstance(error, commands.CommandInvokeError):
        print(f"Prefix command error: {error.original!r}")
        message = f"Action failed: {error.original}" if isinstance(error.original, discord.Forbidden) else "Something went wrong. Check Vectra's role and channel permissions."
    else:
        message = "Something went wrong while running that command."
    await ctx.send(message)


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Set DISCORD_TOKEN in your environment or .env file.")
    bot.add_view(TicketOpenView())
    bot.add_view(TicketCloseView())
    bot.run(TOKEN)
