# 🤖 LuminisBot - Self-Hosted Discord Bot

A Discord bot for Warcraft Logs integration, raid event management, and guild coordination, optimized for self-hosted deployment.

## ✨ Features

- **📊 Warcraft Logs Integration** - Automatic log posting with DPS/HPS/Deaths analysis
- **🗓️ Raid Event System** - Create events with signup buttons and role selection
- **🎮 WoW Addon** - Display Discord events in-game with one-click invites
- **🔗 Battle.net Integration** - Link WoW characters to Discord accounts
- **📝 Auto Log Detection** - Automatically posts new logs to configured channels

## 🚀 Quick Setup

### Prerequisites
- Docker and Docker Compose
- A NAS or self-hosted server

### Deployment

1. **Clone the repository**
   ```bash
   git clone https://github.com/Luminis-Gaming/Luminisbot.git
   cd Luminisbot
   ```

2. **Configure environment**
   ```bash
   cp .env.template .env
   nano .env  # Fill in your credentials
   ```

3. **Deploy with auto-updates**
   ```bash
   docker-compose up -d
   ```

That's it! The bot will automatically update when you push changes to the main branch.

## 🔧 Configuration

Edit the `.env` file with your credentials:

- `DISCORD_BOT_TOKEN` - Your Discord bot token
- `WCL_CLIENT_ID` - Warcraft Logs API client ID
- `WCL_CLIENT_SECRET` - Warcraft Logs API client secret
- `BLIZZARD_CLIENT_ID` - Battle.net API client ID (for character linking)
- `BLIZZARD_CLIENT_SECRET` - Battle.net API client secret
- `BLIZZARD_REDIRECT_URI` - OAuth callback URL (your server)
- `POSTGRES_PASSWORD` - Database password
- `RECORDER_EMAIL` - Warcraft Recorder email (optional)
- `RECORDER_PASSWORD` - Warcraft Recorder password (optional)

## 🎮 WoW Addon

LuminisBot includes a World of Warcraft addon that displays your Discord raid events in-game!

**Features:**
- View all upcoming events from Discord
- See all signups with roles and specs
- One-click invite all signed-up players
- Automatic cross-realm name formatting

**Installation:** See [`wow_addon/README.md`](wow_addon/README.md) for user instructions

**For Developers:** See [`wow_addon/SETUP.md`](wow_addon/SETUP.md) for technical details

## 📋 Services Included

- **LuminisBot** - The Discord bot application
- **PostgreSQL** - Database for storing configurations
- **Watchtower** - Automatic image updates

## 🔄 Auto-Updates

The setup includes Watchtower which automatically:
- Checks for new images every 5 minutes
- Pulls and restarts with updated versions
- Cleans up old Docker images

## 📊 Monitoring

```bash
# Check service status
docker-compose ps

# View bot logs
docker-compose logs -f luminisbot

# View all logs
docker-compose logs -f
```

## 🛠️ Development

For development, the repository includes:
- GitHub Actions for automatic image building
- Source code for the Discord bot
- Database migration scripts

When you push to `main`, GitHub Actions automatically builds and publishes a new Docker image, which Watchtower will deploy to your server within 5 minutes.

## 📦 Architecture

```
GitHub Push → GitHub Actions → Build Image → Push to GHCR → Watchtower Pulls → Auto-Deploy
```

This ensures your self-hosted bot is always running the latest version without manual intervention.