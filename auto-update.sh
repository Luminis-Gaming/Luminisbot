#!/bin/bash

# auto-update.sh - Automatic update script for LuminisBot on NAS
# This script checks for new commits and updates the bot automatically

set -e

# Configuration
REPO_OWNER="Luminis-Gaming"
REPO_NAME="Luminisbot"
DEPLOY_DIR="/path/to/your/luminisbot"  # Change this to your actual path
LOG_FILE="$DEPLOY_DIR/auto-update.log"
LOCK_FILE="$DEPLOY_DIR/auto-update.lock"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

log_color() {
    echo -e "${2}$(date '+%Y-%m-%d %H:%M:%S') - $1${NC}" | tee -a "$LOG_FILE"
}

# Check if another update is running
if [[ -f "$LOCK_FILE" ]]; then
    log_color "Another update is already running. Exiting." "$YELLOW"
    exit 0
fi

# Create lock file
echo $$ > "$LOCK_FILE"

# Cleanup function
cleanup() {
    rm -f "$LOCK_FILE"
}
trap cleanup EXIT

log_color "🚀 Starting LuminisBot auto-update check..." "$BLUE"

# Create deploy directory if it doesn't exist
mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

# Function to get latest commit SHA from GitHub
get_latest_commit() {
    curl -s "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/commits/main" | \
    grep '"sha"' | head -1 | sed 's/.*"sha": *"\([^"]*\)".*/\1/'
}

# Function to get current deployed commit
get_current_commit() {
    if [[ -f "current_commit.txt" ]]; then
        cat current_commit.txt
    else
        echo "none"
    fi
}

# Get commit SHAs
LATEST_COMMIT=$(get_latest_commit)
CURRENT_COMMIT=$(get_current_commit)

if [[ -z "$LATEST_COMMIT" ]]; then
    log_color "❌ Failed to get latest commit from GitHub" "$RED"
    exit 1
fi

log "Latest commit: $LATEST_COMMIT"
log "Current commit: $CURRENT_COMMIT"

# Check if update is needed
if [[ "$LATEST_COMMIT" == "$CURRENT_COMMIT" ]]; then
    log_color "✅ Already up to date!" "$GREEN"
    exit 0
fi

log_color "🔄 New version available! Starting update..." "$YELLOW"

# Download the latest docker-compose file
log "Downloading latest docker-compose file..."
curl -fsSL "https://raw.githubusercontent.com/$REPO_OWNER/$REPO_NAME/main/docker-compose.prebuilt.yml" -o docker-compose.yml

# Download .env template if .env doesn't exist
if [[ ! -f ".env" ]]; then
    log "Downloading .env template..."
    curl -fsSL "https://raw.githubusercontent.com/$REPO_OWNER/$REPO_NAME/main/.env.template" -o .env
    log_color "⚠️  Please configure .env file with your credentials!" "$YELLOW"
fi

# Pull the latest Docker image
log "Pulling latest Docker image..."
docker-compose pull

# Stop current container
log "Stopping current container..."
docker-compose down

# Start updated container
log "Starting updated container..."
docker-compose up -d

# Clean up old images to save space
log "Cleaning up old Docker images..."
docker image prune -f

# Update current commit file
echo "$LATEST_COMMIT" > current_commit.txt

log_color "✅ Update completed successfully!" "$GREEN"
log_color "🤖 LuminisBot is now running the latest version" "$GREEN"

# Optional: Send notification (uncomment and configure as needed)
# curl -X POST "YOUR_DISCORD_WEBHOOK_URL" \
#      -H "Content-Type: application/json" \
#      -d "{\"content\": \"🚀 LuminisBot updated to commit \`${LATEST_COMMIT:0:7}\` on NAS\"}"
