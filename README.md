# Team Vector Discord Bot + Vercel Dashboard

## Project layout

- `main.py` — Discord bot (runs as a persistent Python process).
- `public/index.html` — static dashboard page for Vercel.
- `requirements.txt` — Python dependencies.
- `.env.example` — template for local secrets.
- `.gitignore` — prevents `.env` from being committed.

## Important hosting note

Vercel can host the static dashboard, but Vercel Functions are not a suitable place to run a normal always-connected `discord.py` bot using `bot.run()`. Run `main.py` on a persistent Python host.

## Configure the bot token

### Local computer
1. Copy `.env.example` to `.env`.
2. Put your token after `DISCORD_TOKEN=`.
3. Install dependencies: `pip install -r requirements.txt`.
4. Run: `python main.py`.

### Persistent bot host
Add an environment variable named `DISCORD_TOKEN` in that host's dashboard, then deploy/restart the bot.

### Vercel dashboard
Import this repository into Vercel. The `public/index.html` page is a static dashboard. It does not accept or store bot tokens.

## GitHub upload

```powershell
git init
git add .
git commit -m "Initial Team Vector bot dashboard"
git branch -M main
git remote add origin https://github.com/USERNAME/REPOSITORY.git
git push -u origin main
```

Never commit `.env`. If a token is exposed, reset it in the Discord Developer Portal.
