
import os
import sqlite3
import discord

from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
from discord.ext import commands

# ==========================================
# CONFIGURATION
# ==========================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = "-!"
DATABASE = Path(__file__).with_name("vector.db")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# ==========================================
# DATABASE
# ==========================================

def database_setup():
    with sqlite3.connect(DATABASE) as db:

        db.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            moderator_id INTEGER,
            reason TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        db.execute("""
        CREATE TABLE IF NOT EXISTS modlogs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER,
            user_id INTEGER,
            moderator_id INTEGER,
            action TEXT,
            reason TEXT,
            date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)


def log_action(guild, user, moderator, action, reason):
    with sqlite3.connect(DATABASE) as db:
        db.execute("""
        INSERT INTO modlogs
        (guild_id, user_id, moderator_id, action, reason)
        VALUES (?, ?, ?, ?, ?)
        """, (guild.id, user.id, moderator.id, action, reason))


def check_hierarchy(ctx, member):
    if member == ctx.author:
        return False, "You cannot moderate yourself."

    if member.id == ctx.guild.owner_id:
        return False, "You cannot moderate the server owner."

    if member.top_role >= ctx.author.top_role:
        return False, "Your role must be higher than the target's role."

    if member.top_role >= ctx.guild.me.top_role:
        return False, "My role must be higher than the target's role."

    return True, None


async def action_embed(ctx, title, description):
    embed = discord.Embed(
        title=f"VECTOR | {title}",
        description=description,
        color=discord.Color.dark_red()
    )

    embed.timestamp = discord.utils.utcnow()
    await ctx.send(embed=embed)


# ==========================================
# EVENTS
# ==========================================

@bot.event
async def on_ready():
    database_setup()

    print("==============================")
    print("VECTOR BOT ONLINE")
    print(f"Bot: {bot.user}")
    print(f"Servers: {len(bot.guilds)}")
    print(f"Prefix: {PREFIX}")
    print("==============================")


# ==========================================
# PING
# ==========================================

@bot.command()
async def ping(ctx):

    latency = round(bot.latency * 1000)

    await ctx.send(f"🏓 Pong! `{latency}ms`")


# ==========================================
# BAN
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):

    allowed, error = check_hierarchy(ctx, member)

    if not allowed:
        return await ctx.send(f"⛔ {error}")

    await member.ban(
        reason=f"{ctx.author}: {reason}"
    )

    log_action(ctx.guild, member, ctx.author, "BAN", reason)

    await action_embed(
        ctx,
        "MEMBER BANNED",
        f"**Member:** {member}\n"
        f"**Moderator:** {ctx.author.mention}\n"
        f"**Reason:** {reason}"
    )


# ==========================================
# UNBAN
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason="No reason provided"):

    try:
        user = await bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=reason)

    except discord.NotFound:
        return await ctx.send("User is not banned.")

    await ctx.send(f"✅ {user} has been unbanned.")

    with sqlite3.connect(DATABASE) as db:
        db.execute("""
        INSERT INTO modlogs
        (guild_id, user_id, moderator_id, action, reason)
        VALUES (?, ?, ?, ?, ?)
        """, (ctx.guild.id, user.id, ctx.author.id, "UNBAN", reason))


# ==========================================
# KICK
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):

    allowed, error = check_hierarchy(ctx, member)

    if not allowed:
        return await ctx.send(f"⛔ {error}")

    await member.kick(reason=reason)

    log_action(ctx.guild, member, ctx.author, "KICK", reason)

    await action_embed(
        ctx,
        "MEMBER KICKED",
        f"**Member:** {member}\n"
        f"**Reason:** {reason}"
    )


# ==========================================
# MUTE / TIMEOUT
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="No reason provided"):

    if not 1 <= minutes <= 40320:
        return await ctx.send("Duration must be between 1 and 40320 minutes.")

    allowed, error = check_hierarchy(ctx, member)

    if not allowed:
        return await ctx.send(f"⛔ {error}")

    await member.timeout(
        timedelta(minutes=minutes),
        reason=reason
    )

    log_action(ctx.guild, member, ctx.author, "MUTE", reason)

    await action_embed(
        ctx,
        "MEMBER MUTED",
        f"**Member:** {member.mention}\n"
        f"**Duration:** {minutes} minutes\n"
        f"**Reason:** {reason}"
    )


# ==========================================
# UNMUTE
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):

    allowed, error = check_hierarchy(ctx, member)

    if not allowed:
        return await ctx.send(f"⛔ {error}")

    await member.timeout(None)

    log_action(ctx.guild, member, ctx.author, "UNMUTE", "Timeout removed")

    await ctx.send(f"🔊 {member.mention} has been unmuted.")


# ==========================================
# WARN
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def warn(ctx, member: discord.Member, *, reason):

    allowed, error = check_hierarchy(ctx, member)

    if not allowed:
        return await ctx.send(f"⛔ {error}")

    with sqlite3.connect(DATABASE) as db:
        cursor = db.execute("""
        INSERT INTO warnings
        (guild_id, user_id, moderator_id, reason)
        VALUES (?, ?, ?, ?)
        """, (ctx.guild.id, member.id, ctx.author.id, reason))

        warning_id = cursor.lastrowid

    log_action(ctx.guild, member, ctx.author, "WARN", reason)

    await action_embed(
        ctx,
        "MEMBER WARNED",
        f"**Warning ID:** {warning_id}\n"
        f"**Member:** {member.mention}\n"
        f"**Moderator:** {ctx.author.mention}\n"
        f"**Reason:** {reason}"
    )

    try:
        await member.send(
            f"You received a warning in {ctx.guild.name}.\nReason: {reason}"
        )
    except discord.Forbidden:
        pass


# ==========================================
# WARNINGS
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def warnings(ctx, member: discord.Member):

    with sqlite3.connect(DATABASE) as db:
        rows = db.execute("""
        SELECT id, reason, moderator_id, date
        FROM warnings
        WHERE guild_id = ? AND user_id = ?
        ORDER BY id DESC
        """, (ctx.guild.id, member.id)).fetchall()

    if not rows:
        return await ctx.send("No warnings found.")

    embed = discord.Embed(
        title=f"VECTOR | WARNINGS",
        color=discord.Color.orange()
    )

    for row in rows[:10]:
        embed.add_field(
            name=f"Warning #{row[0]}",
            value=f"Reason: {row[1]}\nModerator: <@{row[2]}>\nDate: {row[3]}",
            inline=False
        )

    await ctx.send(embed=embed)


# ==========================================
# CLEAR WARNINGS
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def clearwarns(ctx, member: discord.Member):

    with sqlite3.connect(DATABASE) as db:
        cursor = db.execute("""
        DELETE FROM warnings
        WHERE guild_id = ? AND user_id = ?
        """, (ctx.guild.id, member.id))

    await ctx.send(
        f"✅ Cleared {cursor.rowcount} warnings for {member.mention}."
    )


# ==========================================
# PURGE
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True, read_message_history=True)
async def purge(ctx, amount: int):

    if not 1 <= amount <= 100:
        return await ctx.send("Choose between 1 and 100 messages.")

    deleted = await ctx.channel.purge(limit=amount + 1)

    msg = await ctx.send(
        f"🧹 Deleted {max(0, len(deleted) - 1)} messages."
    )

    await msg.delete(delay=4)


# ==========================================
# SLOWMODE
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int):

    if not 0 <= seconds <= 21600:
        return await ctx.send("Enter a value between 0 and 21600.")

    await ctx.channel.edit(slowmode_delay=seconds)

    await ctx.send(f"⏱️ Slowmode set to {seconds} seconds.")


# ==========================================
# LOCK
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def lock(ctx):

    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False

    await ctx.channel.set_permissions(
        ctx.guild.default_role,
        overwrite=overwrite
    )

    await ctx.send("🔒 Channel locked.")


# ==========================================
# UNLOCK
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def unlock(ctx):

    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None

    await ctx.channel.set_permissions(
        ctx.guild.default_role,
        overwrite=overwrite
    )

    await ctx.send("🔓 Channel unlocked.")


# ==========================================
# NICKNAME
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(manage_nicknames=True)
@commands.bot_has_permissions(manage_nicknames=True)
async def nick(ctx, member: discord.Member, *, nickname):

    allowed, error = check_hierarchy(ctx, member)

    if not allowed:
        return await ctx.send(f"⛔ {error}")

    if nickname.lower() == "reset":
        await member.edit(nick=None)
    else:
        await member.edit(nick=nickname)

    await ctx.send(f"✅ Nickname updated for {member.mention}.")


# ==========================================
# MODERATION LOGS
# ==========================================

@bot.command()
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def modlogs(ctx, member: discord.Member):

    with sqlite3.connect(DATABASE) as db:
        rows = db.execute("""
        SELECT action, reason, moderator_id, date
        FROM modlogs
        WHERE guild_id = ? AND user_id = ?
        ORDER BY rowid DESC LIMIT 10
        """, (ctx.guild.id, member.id)).fetchall()

    if not rows:
        return await ctx.send("No moderation history found.")

    embed = discord.Embed(
        title=f"VECTOR | MODERATION HISTORY",
        color=discord.Color.dark_red()
    )

    for row in rows:
        embed.add_field(
            name=row[0],
            value=f"Reason: {row[1]}\nModerator: <@{row[2]}>\nDate: {row[3]}",
            inline=False
        )

    await ctx.send(embed=embed)


# ==========================================
# HELP
# ==========================================

@bot.command()
async def help(ctx):

    embed = discord.Embed(
        title="VECTOR | COMMAND CENTER",
        description=f"Prefix: `{PREFIX}`",
        color=discord.Color.dark_red()
    )

    embed.add_field(
        name="Moderation",
        value=(
            "`-!ban @user reason`\n"
            "`-!unban USER_ID`\n"
            "`-!kick @user reason`\n"
            "`-!mute @user minutes reason`\n"
            "`-!unmute @user`\n"
            "`-!warn @user reason`\n"
            "`-!warnings @user`\n"
            "`-!clearwarns @user`\n"
            "`-!modlogs @user`"
        ),
        inline=False
    )

    embed.add_field(
        name="Channel Management",
        value=(
            "`-!purge amount`\n"
            "`-!slowmode seconds`\n"
            "`-!lock`\n"
            "`-!unlock`"
        ),
        inline=False
    )

    embed.add_field(
        name="Utility",
        value=(
            "`-!ping`\n"
            "`-!help`"
        ),
        inline=False
    )

    embed.set_footer(text="VECTOR Bot | Moderation System")

    await ctx.send(embed=embed)


# ==========================================
# ERROR HANDLING
# ==========================================

@bot.event
async def on_command_error(ctx, error):

    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        return await ctx.send("⛔ You don't have permission.")

    if isinstance(error, commands.BotMissingPermissions):
        return await ctx.send("⛔ I am missing required permissions.")

    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send("⚠️ Missing argument. Use -!help.")

    if isinstance(error, commands.MemberNotFound):
        return await ctx.send("Member not found.")

    if isinstance(error, commands.BadArgument):
        return await ctx.send("Invalid argument.")

    if isinstance(error, discord.Forbidden):
        return await ctx.send("Discord denied this action. Check my permissions.")

    if isinstance(error, commands.NoPrivateMessage):
        return await ctx.send("This command only works inside a server.")

    print(f"Error: {error}")
    await ctx.send("An unexpected error occurred.")


# ==========================================
# START BOT
# ==========================================

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

bot.run(TOKEN)
