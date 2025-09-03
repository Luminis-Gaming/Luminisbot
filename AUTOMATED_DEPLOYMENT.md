# 🚀 Automated Deployment Guide for LuminisBot

This guide provides multiple options for automatically deploying LuminisBot to your NAS when you push changes to GitHub.

## 🎯 Quick Start (Recommended)

**For the simplest setup, use Option 4 (Watchtower):**

```bash
# On your NAS, run:
curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/docker-compose.auto-update.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/.env.template -o .env

# Configure your environment
nano .env

# Start with auto-updates enabled
docker-compose up -d
```

---

## 📋 All Available Options

### Option 1: GitHub Actions + SSH (Most Robust)

**Best for**: Production environments, immediate deployments, full control

#### Setup:
1. **Add secrets to your GitHub repository:**
   - Go to your GitHub repo → Settings → Secrets and variables → Actions
   - Add these secrets:
     - `NAS_HOST`: Your NAS IP address (e.g., `192.168.1.100`)
     - `NAS_USERNAME`: SSH username for your NAS
     - `NAS_SSH_KEY`: Your private SSH key content
     - `NAS_PORT`: SSH port (usually 22)

2. **Enable SSH on your NAS and add your public key**

3. **The GitHub Action will automatically:**
   - Build Docker image on every push
   - Push to GitHub Container Registry  
   - SSH to your NAS and update the deployment

#### Pros:
✅ Instant deployment on push  
✅ Builds happen on GitHub (no NAS resources used)  
✅ Full deployment logs in GitHub  
✅ Can rollback easily  

#### Cons:
❌ Requires SSH setup  
❌ More complex initial configuration  

---

### Option 2: Scheduled Updates (Good Balance)

**Best for**: Regular updates without constant monitoring

#### Setup:
```bash
# On your NAS, run the setup script
curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/setup-auto-update.sh | bash
```

This will:
- Download the auto-update script
- Set up a cron job to check for updates
- Let you choose update frequency (every hour, daily, etc.)

#### Pros:
✅ Simple setup  
✅ Configurable update frequency  
✅ Detailed logging  
✅ No external dependencies  

#### Cons:
❌ Not instant (depends on schedule)  
❌ Requires cron access  

---

### Option 3: Manual Script (When Needed)

**Best for**: Manual control, testing, or irregular updates

#### Setup:
```bash
# Download the auto-update script
curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/auto-update.sh -o auto-update.sh
chmod +x auto-update.sh

# Edit the deployment path
nano auto-update.sh  # Change DEPLOY_DIR to your path

# Run when you want to update
./auto-update.sh
```

#### Pros:
✅ Full manual control  
✅ Run updates when convenient  
✅ Easy to test and debug  

#### Cons:
❌ Manual process  
❌ Easy to forget to update  

---

### Option 4: Watchtower (Simplest)

**Best for**: Set-and-forget automation, minimal configuration

#### How it works:
- Watchtower monitors your Docker containers
- Checks for new image versions every 5 minutes
- Automatically pulls and restarts with new images

#### Setup:
```bash
# Use the auto-update docker-compose file
curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/docker-compose.auto-update.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/.env.template -o .env

# Configure
nano .env

# Start everything
docker-compose up -d
```

#### Pros:
✅ Zero configuration after setup  
✅ Works with any Docker registry  
✅ Monitors multiple containers  
✅ Automatic cleanup of old images  

#### Cons:
❌ Less control over update timing  
❌ Polls every 5 minutes (network overhead)  

---

## 🔧 Which Option Should You Choose?

| Scenario | Recommended Option | Why |
|----------|-------------------|-----|
| **Development** | Option 1 (GitHub Actions) | Instant feedback, full logs |
| **Production** | Option 4 (Watchtower) | Reliable, simple, proven |
| **Limited SSH access** | Option 2 (Scheduled) | Works without SSH |
| **Irregular updates** | Option 3 (Manual) | Full control |
| **Multiple services** | Option 4 (Watchtower) | Monitors all containers |

---

## 🔍 Monitoring and Troubleshooting

### Check if auto-updates are working:

```bash
# For Watchtower
docker logs luminisbot_watchtower

# For scheduled updates
tail -f /path/to/your/luminisbot/auto-update.log

# For GitHub Actions
# Check the Actions tab in your GitHub repository
```

### Common issues:

1. **Docker image not updating**: Make sure GitHub Actions are building and pushing successfully
2. **SSH connection fails**: Check SSH keys and firewall settings
3. **Cron job not running**: Verify with `crontab -l` and check system logs
4. **Watchtower not updating**: Check container logs and image registry connectivity

---

## 🎉 Next Steps

1. **Choose your preferred option** from above
2. **Follow the setup instructions**
3. **Make a test commit** to verify auto-deployment works
4. **Monitor the first few deployments** to ensure everything is working
5. **Enjoy automatic updates!** 🚀

---

## 📞 Need Help?

- Check the logs first (each option has different log locations)
- Verify your `.env` file is properly configured
- Make sure Docker and required services are running
- Test manually before setting up automation
