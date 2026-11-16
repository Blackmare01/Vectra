import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Local development reads .env. On a hosting platform, set DISCORD_TOKEN
# in that platform's Environment Variables dashboard.
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Set it in your host's environment variables.")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="-!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    await member.kick(reason=reason)
    await ctx.send(f"Kicked {member.mention}. Reason: {reason}")

@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    await member.ban(reason=reason)
    await ctx.send(f"Banned {member.mention}. Reason: {reason}")

@bot.command()
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member, minutes: int, *, reason="No reason provided"):
    if minutes < 1 or minutes > 40320:
        await ctx.send("Choose a duration from 1 to 40320 minutes.")
        return
    from datetime import timedelta
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await ctx.send(f"Timed out {member.mention} for {minutes} minutes.")

@bot.command()
async def time(ctx):
    from datetime import datetime, timezone
    await ctx.send(f"Current UTC time: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You do not have permission to use that command.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("A required argument is missing. Check the command usage.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("Member not found.")
    else:
        raise error

bot.run(TOKEN)
