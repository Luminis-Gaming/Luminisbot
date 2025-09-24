# LuminisBot Docker Deployment Guide

This guide will help you deploy your LuminisBot Discord bot on your NAS using Docker.

## 📋 Prerequisites

1. **Docker and Docker Compose** installed on your NAS
2. **Discord Bot Token** from Discord Developer Portal
3. **Warcraft Logs API credentials** (Client ID and Secret)
4. **PostgreSQL password** for your database

## 🚀 Quick Start

### 1. Prepare Environment Variables

Copy the template and fill in your actual values:
```bash
cp .env.template .env
```

Edit the `.env` file with your actual credentials:
```bash
# Discord Bot Configuration
DISCORD_BOT_TOKEN=YOUR_ACTUAL_BOT_TOKEN

# Warcraft Logs API Configuration  
WCL_CLIENT_ID=YOUR_ACTUAL_CLIENT_ID
WCL_CLIENT_SECRET=YOUR_ACTUAL_CLIENT_SECRET

# Database Configuration
POSTGRES_PASSWORD=your_secure_database_password

# Warcraft Recorder Configuration
RECORDER_EMAIL=your_warcraft_recorder_email
RECORDER_PASSWORD=your_warcraft_recorder_password
```

### 2. Deploy with Docker Compose

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f luminisbot

# Stop services
docker-compose down

# Stop and remove volumes (⚠️ This will delete your database!)
docker-compose down -v
```

## 📊 Service Information

### Services Included:
- **LuminisBot**: Your Discord bot application
- **PostgreSQL**: Database for storing guild configurations
- **Networks**: Isolated network for service communication
- **Volumes**: Persistent database storage

### Ports Exposed:
- **25432**: PostgreSQL database (optional, for external access)

## 🔧 Configuration

### Discord Bot Setup:
1. Create a Discord application at https://discord.com/developers/applications
2. Create a bot and copy the token
3. Add the bot to your Discord server with appropriate permissions

### Warcraft Logs API Setup:
1. Register at https://www.warcraftlogs.com/api/clients/
2. Create a new client and get your Client ID and Secret

### Required Bot Permissions:
- Send Messages
- Use Slash Commands
- Embed Links
- Read Message History
- Add Reactions

## 📁 File Structure

```
LuminisBot/
├── Dockerfile              # Container build instructions
├── docker-compose.yml      # Multi-service orchestration
├── requirements.txt        # Python dependencies
├── init.sql               # Database initialization
├── .env.template          # Environment variables template
├── .env                   # Your actual environment variables (create this!)
├── .dockerignore          # Files to exclude from Docker build
├── my_discord_bot.py      # Main bot application
├── database.py            # Database functions
├── wcl_api.py            # Warcraft Logs API
├── wcl_web_scraper.py    # Web scraping functions
├── discord_ui.py         # Discord UI components
└── warcraft_recorder_automator.py
```

## 🛠️ Troubleshooting

### Check Service Status:
```bash
docker-compose ps
```

### View Logs:
```bash
# All services
docker-compose logs

# Specific service
docker-compose logs luminisbot
docker-compose logs postgres
```

### Restart Services:
```bash
# Restart bot only
docker-compose restart luminisbot

# Restart database only
docker-compose restart postgres

# Restart everything
docker-compose restart
```

### Database Access:
```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U luminisbot -d luminisbot

# Backup database
docker-compose exec postgres pg_dump -U luminisbot luminisbot > backup.sql

# Restore database
docker-compose exec -T postgres psql -U luminisbot -d luminisbot < backup.sql
```

### Update Bot Code:
```bash
# Rebuild and restart after code changes
docker-compose up -d --build
```

## 📋 Health Checks

The setup includes health checks for the database service:

- **PostgreSQL**: Checks database connectivity

You can check service status with:
```bash
docker-compose ps
```

## 🔒 Security Notes

1. **Keep your `.env` file secure** - never commit it to version control
2. **Use strong passwords** for your database
3. **Limit network access** to only necessary ports
4. **Regularly update Docker images** for security patches

## 🎯 Bot Commands

Once deployed, your bot will have these slash commands:

- `/set_log_channel` - Configure automatic log posting for a channel
- `/warcraftrecorder` - Add email to Warcraft Recorder roster

## 📈 Monitoring

- **Database**: Accessible on port 25432 (if needed)
- **Logs**: Use `docker-compose logs` to monitor activity
- **Bot Status**: Check Discord server to verify bot is online

## 🆘 Support

If you encounter issues:

1. Check the logs with `docker-compose logs`
2. Verify your environment variables in `.env`
3. Ensure your Discord bot has proper permissions
4. Check that your Warcraft Logs API credentials are correct

---

🎉 **Your LuminisBot should now be running successfully on your NAS!**
