# 🤖 LuminisBot - Self-Hosted Discord Bot

A Discord bot for Warcraft Logs integration and guild management, optimized for self-hosted deployment.

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
- `POSTGRES_PASSWORD` - Database password
- `RECORDER_EMAIL` - Warcraft Recorder email (optional)
- `RECORDER_PASSWORD` - Warcraft Recorder password (optional)

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