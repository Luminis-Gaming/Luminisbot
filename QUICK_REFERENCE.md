# 🎯 LuminisBot NAS Deployment - Quick Reference

## 🚀 Quick Setup (3 Steps)

1. **Copy and configure environment**:
   ```bash
   cp .env.template .env
   nano .env  # Fill in your Discord bot token, WCL API credentials, etc.
   ```

2. **Deploy with one command**:
   ```bash
   docker-compose up -d
   ```

3. **Check it's working**:
   ```bash
   docker-compose logs luminisbot
   curl http://localhost:10000  # Should return "Bot is alive!"
   ```

## 🔧 Essential Commands

| Action | Command |
|--------|---------|
| **Start bot** | `docker-compose up -d` |
| **Stop bot** | `docker-compose down` |
| **View logs** | `docker-compose logs -f luminisbot` |
| **Restart bot** | `docker-compose restart luminisbot` |
| **Update code** | `docker-compose up -d --build` |
| **Check status** | `docker-compose ps` |

## 📊 Monitoring

- **Health Check**: http://your-nas-ip:10000
- **Database**: Port 5432 (if external access needed)
- **Logs**: `docker-compose logs luminisbot`

## 🔑 Required Environment Variables

```bash
DISCORD_BOT_TOKEN=your_bot_token
WCL_CLIENT_ID=your_wcl_client_id  
WCL_CLIENT_SECRET=your_wcl_secret
POSTGRES_PASSWORD=secure_db_password
RECORDER_EMAIL=your_email
RECORDER_PASSWORD=your_password
```

## 🆘 Troubleshooting

| Problem | Solution |
|---------|----------|
| Bot won't start | Check `.env` file has all required variables |
| Database connection fails | Ensure PostgreSQL container is healthy: `docker-compose ps` |
| Bot commands not working | Verify Discord bot permissions and token |
| Out of memory | Increase Docker memory limits on your NAS |

## 📱 Bot Commands (once deployed)

- `/set_log_channel` - Configure automatic Warcraft Logs posting
- `/warcraftrecorder` - Add email to Warcraft Recorder roster

## 🔄 Backup & Recovery

**Backup database**:
```bash
docker-compose exec postgres pg_dump -U luminisbot luminisbot > backup.sql
```

**Restore database**:
```bash
docker-compose exec -T postgres psql -U luminisbot -d luminisbot < backup.sql
```

---

💡 **Pro tip**: Use the `deploy.bat` (Windows) or `deploy.sh` (Linux) scripts for an interactive menu!
