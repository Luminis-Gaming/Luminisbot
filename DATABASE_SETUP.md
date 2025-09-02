# 🗄️ Database Setup Guide for LuminisBot

## ✅ Database is Ready to Go - Just Configure Your Password!

The database setup is **completely automated** - you just need to set one environment variable.

## 🔧 Quick Setup Steps

### 1. Copy the Environment Template
```bash
cp .env.template .env
```

### 2. Edit Your `.env` File
Open `.env` in your favorite text editor and set **AT MINIMUM** these required variables:

```bash
# ⚠️ REQUIRED - Your Discord bot token
DISCORD_BOT_TOKEN=your_actual_discord_bot_token

# ⚠️ REQUIRED - Your Warcraft Logs API credentials  
WCL_CLIENT_ID=your_actual_wcl_client_id
WCL_CLIENT_SECRET=your_actual_wcl_client_secret

# ⚠️ REQUIRED - Database password (choose a secure password!)
POSTGRES_PASSWORD=MySecurePassword123!

# 📧 OPTIONAL - Only needed if you want the /warcraftrecorder command
RECORDER_EMAIL=your_email@example.com
RECORDER_PASSWORD=your_password
```

### 3. Deploy
```bash
docker-compose up -d
```

That's it! The database will be automatically:
- ✅ Created with the name `luminisbot`
- ✅ Set up with user `luminisbot` 
- ✅ Initialized with the required tables
- ✅ Connected to your bot

## 🔒 Database Security

### Password Requirements
- **Use a strong, unique password** for `POSTGRES_PASSWORD`
- **Don't use the placeholder text** from the template
- **Examples of good passwords:**
  - `MyBot2025SecureDB!`
  - `LuminisBot#DatabasePwd$2025`
  - `SuperSecure!Discord8ot`

### What Gets Created Automatically
```sql
-- Database: luminisbot
-- User: luminisbot (with your chosen password)
-- Table: guild_channels (for storing Discord server configurations)
```

## 📊 Database Access (if needed)

### Connect to Database from Outside Container
```bash
# Using psql (if installed on your NAS)
psql -h localhost -p 25432 -U luminisbot -d luminisbot

# Using Docker
docker-compose exec postgres psql -U luminisbot -d luminisbot
```

### Database Connection Details
- **Host**: `localhost` (from outside) or `postgres` (from inside containers)
- **Port**: `25432`
- **Database**: `luminisbot`
- **Username**: `luminisbot`
- **Password**: Whatever you set in `POSTGRES_PASSWORD`

## 🛠️ Troubleshooting Database Issues

### ❌ "database connection failed"
**Cause**: Missing or incorrect `POSTGRES_PASSWORD` in `.env`
**Solution**: Check your `.env` file has `POSTGRES_PASSWORD=your_password`

### ❌ "role 'luminisbot' does not exist"
**Cause**: Database container didn't initialize properly
**Solution**: 
```bash
docker-compose down -v  # ⚠️ This deletes data!
docker-compose up -d    # Recreate fresh
```

### ❌ "authentication failed"
**Cause**: Password mismatch between bot and database
**Solution**: Ensure `POSTGRES_PASSWORD` is the same for both services

### ❌ "table 'guild_channels' does not exist"
**Cause**: Database initialization script didn't run
**Solution**: Check logs: `docker-compose logs postgres`

## 📈 Monitoring Database Health

### Check if Database is Running
```bash
docker-compose ps postgres
```

### View Database Logs
```bash
docker-compose logs postgres
```

### Test Database Connection
```bash
docker-compose exec postgres pg_isready -U luminisbot -d luminisbot
```

## 💾 Backup & Restore

### Backup Your Data
```bash
docker-compose exec postgres pg_dump -U luminisbot luminisbot > luminisbot_backup.sql
```

### Restore from Backup
```bash
docker-compose exec -T postgres psql -U luminisbot -d luminisbot < luminisbot_backup.sql
```

## 🎯 Summary

**You only need to set ONE database variable**: `POSTGRES_PASSWORD`

Everything else (database creation, user setup, table creation, connections) is handled automatically by Docker Compose and the initialization script.

**Example minimal `.env` file:**
```bash
DISCORD_BOT_TOKEN=your_real_bot_token_here
WCL_CLIENT_ID=your_real_wcl_client_id
WCL_CLIENT_SECRET=your_real_wcl_secret
POSTGRES_PASSWORD=MySecurePassword123!
```

Then just run: `docker-compose up -d` 🚀
