"""Vectra moderation and support bot. Run as a persistent process, not a Vercel Function."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("VECTRA_DB_PATH", "vectra.sqlite3")
BRAND = 0x7867F0


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


def setting(guild_id: int, key: str):
    with db() as con:
        row = con.execute(f"SELECT {key} FROM settings WHERE guild_id=?", (guild_id,)).fetchone()
        return row[key] if row else None


def set_setting(guild_id: int, key: str, value: Optional[int]):
    with db() as con:
        con.execute("INSERT OR IGNORE INTO settings(guild_id) VALUES(?)", (guild_id,))
        con.execute(f"UPDATE settings SET {key}=? WHERE guild_id=?", (value, guild_id))


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


@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild and not message.author.bot:
        content = discord.utils.escape_mentions(message.content[:1200] or "[no text]")
        await log(message.guild, "message_log", "Message deleted", f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Content:** {content}", 0xED5B68)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.guild and not before.author.bot and before.content != after.content:
        await log(before.guild, "message_log", "Message edited", f"**Author:** {before.author.mention}\n**Channel:** {before.channel.mention}\n[Jump to message]({after.jump_url})\n**Before:** {discord.utils.escape_mentions(before.content[:700] or '[empty]')}\n**After:** {discord.utils.escape_mentions(after.content[:700] or '[empty]')}")


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


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Set DISCORD_TOKEN in your environment or .env file.")
    bot.add_view(TicketOpenView())
    bot.add_view(TicketCloseView())
    bot.run(TOKEN)
