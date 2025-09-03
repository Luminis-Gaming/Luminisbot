#!/bin/bash

# setup-auto-update.sh - Setup automatic updates for LuminisBot on NAS
# This script configures cron job for automatic updates

set -e

echo "🚀 LuminisBot Auto-Update Setup"
echo "==============================="
echo ""

# Get deployment directory
read -p "Enter the full path where LuminisBot should be deployed [/opt/luminisbot]: " DEPLOY_DIR
DEPLOY_DIR=${DEPLOY_DIR:-/opt/luminisbot}

# Validate and create directory
if [[ ! -d "$DEPLOY_DIR" ]]; then
    echo "Creating deployment directory: $DEPLOY_DIR"
    sudo mkdir -p "$DEPLOY_DIR"
    sudo chown $(whoami):$(whoami) "$DEPLOY_DIR"
fi

# Download auto-update script
echo "Downloading auto-update script..."
curl -fsSL "https://raw.githubusercontent.com/Luminis-Gaming/Luminisbot/main/auto-update.sh" -o "$DEPLOY_DIR/auto-update.sh"

# Update the deploy directory in the script
sed -i "s|DEPLOY_DIR=\"/path/to/your/luminisbot\"|DEPLOY_DIR=\"$DEPLOY_DIR\"|" "$DEPLOY_DIR/auto-update.sh"

# Make script executable
chmod +x "$DEPLOY_DIR/auto-update.sh"

echo ""
echo "🤔 How often should the bot check for updates?"
echo "1) Every 5 minutes (for development)"
echo "2) Every 30 minutes"
echo "3) Every hour (recommended)"
echo "4) Every 6 hours"
echo "5) Daily at 3 AM"
echo "6) Custom interval"
echo ""
read -p "Enter choice (1-6) [default: 3]: " update_freq
update_freq=${update_freq:-3}

case $update_freq in
    1)
        CRON_SCHEDULE="*/5 * * * *"
        DESCRIPTION="every 5 minutes"
        ;;
    2)
        CRON_SCHEDULE="*/30 * * * *"
        DESCRIPTION="every 30 minutes"
        ;;
    3)
        CRON_SCHEDULE="0 * * * *"
        DESCRIPTION="every hour"
        ;;
    4)
        CRON_SCHEDULE="0 */6 * * *"
        DESCRIPTION="every 6 hours"
        ;;
    5)
        CRON_SCHEDULE="0 3 * * *"
        DESCRIPTION="daily at 3 AM"
        ;;
    6)
        echo "Enter custom cron schedule (e.g., '0 */2 * * *' for every 2 hours):"
        read -p "Cron schedule: " CRON_SCHEDULE
        DESCRIPTION="custom schedule: $CRON_SCHEDULE"
        ;;
    *)
        CRON_SCHEDULE="0 * * * *"
        DESCRIPTION="every hour"
        ;;
esac

# Add cron job
CRON_JOB="$CRON_SCHEDULE cd $DEPLOY_DIR && ./auto-update.sh >> auto-update.log 2>&1"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "auto-update.sh"; then
    echo "Removing existing auto-update cron job..."
    crontab -l 2>/dev/null | grep -v "auto-update.sh" | crontab -
fi

# Add new cron job
echo "Adding cron job for $DESCRIPTION..."
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo ""
echo "✅ Auto-update setup completed!"
echo ""
echo "📋 Summary:"
echo "  • Deploy directory: $DEPLOY_DIR"
echo "  • Update frequency: $DESCRIPTION"
echo "  • Log file: $DEPLOY_DIR/auto-update.log"
echo ""
echo "🔧 Next steps:"
echo "1. Run initial deployment:"
echo "   cd $DEPLOY_DIR && ./auto-update.sh"
echo ""
echo "2. Configure your .env file:"
echo "   nano $DEPLOY_DIR/.env"
echo ""
echo "3. Monitor logs:"
echo "   tail -f $DEPLOY_DIR/auto-update.log"
echo ""
echo "4. View cron jobs:"
echo "   crontab -l"
echo ""
echo "5. Remove auto-update (if needed):"
echo "   crontab -e  # Remove the line containing auto-update.sh"
echo ""
echo "🚀 Your bot will now automatically update $DESCRIPTION!"
