# Vectra Discord bot

Vectra is a Python moderation and support bot with a static Vercel dashboard. The bot and dashboard are separate services: Vercel serves the HTML, while the Discord gateway bot runs continuously on a persistent Python host.

## Features

- Slash commands for warnings, warning history, clearing warnings, mute/timeout, kick, ban, unban, bulk purge, slowmode, lock, and unlock.
- Persistent SQLite warning history and per-server configuration.
- Ticket panels with persistent buttons, private ticket channels, staff access, and close controls.
- Five independently configurable log destinations: moderation, messages, members, roles, and channels.
- Optional per-server Discord invite filter that deletes invite links and times out the sender.
- Logs for edited/deleted messages, member joins/leaves and role changes, role create/update/delete, channel create/update/delete, and moderation actions.
- Responsive static dashboard with command reference, setup instructions, ticket overview, and a browser-local log-channel preview.

## Run the bot

1. Create a bot application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Enable **Server Members Intent** and **Message Content Intent** under Bot settings.
3. Invite the bot with the `bot` and `applications.commands` OAuth scopes. Grant only the permissions it needs: View Channels, Send Messages, Manage Messages, Manage Channels, Kick Members, Ban Members, and Moderate Members.
4. Install Python 3.10 or newer and run:

   ```sh
   pip install -r requirements.txt
   ```

5. Set `DISCORD_TOKEN` in the host's private environment settings. For local work, create `.env` (never commit it):

   ```env
   DISCORD_TOKEN=your_bot_token
   # Optional; defaults to ./data/vectra.sqlite3
   VECTRA_DB_PATH=data/vectra.sqlite3
   ```

6. Start the persistent process:

   ```sh
   python main.py
   ```

Keep `data/vectra.sqlite3` on persistent storage. It contains warnings and server configuration. On Inject Cloud, `data/` is a persistent app-data directory; back up the database with the host's normal backup process.

## Configure a server

- Use `/setup-logs` and select a category and destination channel. Categories: moderation, messages, members, roles, and channels. Omit the channel to disable a category.
- Use `/logs` to review destinations.
- Run `/ticket-panel` in the channel where members should contact staff; choose an optional ticket category.
- Enable invite filtering with `/link-filter` or `!linkfilter on 10`. It is off by default; matching invite links are deleted and the sender is timed out for the configured duration. Server owners and members with Manage Messages, Moderate Members, or Administrator are exempt. The filter targets invite URLs (`discord.gg` and `/invite/` links), not ordinary Discord channel links.
- Place Vectra's role above the roles it needs to moderate. Its ticket flow grants staff access to roles with **Manage Channels**.
- Configure `Manage Server`, moderation, and channel permissions for the appropriate staff roles.

Slash commands sync on startup. Discord can take a short time to show global commands after first deploy. Use `/help` or `!help` to see the available commands in Discord.

## Prefix commands

All moderation, log setup, and ticket panel commands are also available with the `!` prefix. Use `!help` for a short in-server list. Examples:

```text
!warn @member Please follow the server rules
!mute @member 30 Please cool off
!purge 25
!setup-logs moderation #mod-log
!ticket-panel
!linkfilter on 10
```

Prefix commands require **Message Content Intent** enabled both in this code and in the Discord Developer Portal. The bot currently uses `!` as its prefix.

## Deploy the dashboard on Vercel

Import the repository into Vercel with the project root as the root directory. Vercel serves the static site from `public/`. No bot token or environment variable is needed for this dashboard.

## Hosting limitation

Vercel Functions are short-lived and cannot hold the persistent Discord gateway connection required by this bot. Host `main.py` on an always-on worker (for example, a VPS or persistent Python worker service) and keep Vercel for the dashboard. The current dashboard is informational and its channel preview is saved only in the browser; real bot configuration is applied with Discord slash commands. Discord OAuth and a remote configuration API are not included.

## Security

- Never put a Discord token in HTML, browser storage, GitHub, or client-side environment variables.
- `.env` and SQLite database files are excluded from Git.
- Reset the bot token in Discord Developer Portal if it is exposed.
