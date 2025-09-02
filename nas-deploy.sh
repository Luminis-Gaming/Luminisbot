#!/bin/bash

# nas-deploy.sh - Deploy LuminisBot on NAS using pre-built Docker image
# This script downloads only the necessary files and deploys the bot

set -e

echo "🚀 LuminisBot NAS Deployment Script"
echo "===================================="
echo "This script will download and deploy LuminisBot using a pre-built Docker image"
echo ""

# Variables
REPO_URL="https://raw.githubusercontent.com/PhilipAubert/LuminisBot/main"
COMPOSE_FILE="docker-compose.prebuilt.yml"

echo "🤔 Choose deployment method:"
echo "1) Pre-built image (recommended, no local building)"
echo "2) Build locally with full features (requires good hardware)"
echo "3) Build locally minimal version (lightweight, faster build)"
echo ""
read -p "Enter choice (1-3) [default: 1]: " deploy_choice
deploy_choice=${deploy_choice:-1}

case $deploy_choice in
    1)
        COMPOSE_FILE="docker-compose.prebuilt.yml"
        echo "✅ Using pre-built Docker image"
        ;;
    2)
        COMPOSE_FILE="docker-compose.yml"
        echo "✅ Will build locally with full features"
        ;;
    3)
        COMPOSE_FILE="docker-compose.minimal.yml"
        echo "✅ Will build locally minimal version"
        ;;
    *)
        echo "❌ Invalid choice, using pre-built image"
        COMPOSE_FILE="docker-compose.prebuilt.yml"
        ;;
esac

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed or not in PATH"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed or not in PATH"
    exit 1
fi

echo "✅ Docker and Docker Compose found"

# Create deployment directory
DEPLOY_DIR="LuminisBot"
if [ ! -d "$DEPLOY_DIR" ]; then
    echo "📁 Creating deployment directory: $DEPLOY_DIR"
    mkdir -p "$DEPLOY_DIR"
fi

cd "$DEPLOY_DIR"

# Download necessary files
echo "⬬ Downloading deployment files..."

# Download docker-compose file
echo "  - docker-compose.yml"
curl -fsSL "$REPO_URL/$COMPOSE_FILE" -o docker-compose.yml

# Download environment template
echo "  - .env.template"
curl -fsSL "$REPO_URL/.env.template" -o .env.template

# Download setup guides
echo "  - Setup documentation"
curl -fsSL "$REPO_URL/DATABASE_SETUP.md" -o DATABASE_SETUP.md 2>/dev/null || echo "    (DATABASE_SETUP.md not available)"
curl -fsSL "$REPO_URL/QUICK_REFERENCE.md" -o QUICK_REFERENCE.md 2>/dev/null || echo "    (QUICK_REFERENCE.md not available)"

echo "✅ Files downloaded successfully"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  Configuration required!"
    echo "📝 Please configure your environment variables:"
    echo ""
    echo "1. Copy the template:"
    echo "   cp .env.template .env"
    echo ""
    echo "2. Edit the .env file with your actual credentials:"
    echo "   nano .env"
    echo ""
    echo "3. Required variables:"
    echo "   - DISCORD_BOT_TOKEN=your_bot_token"
    echo "   - WCL_CLIENT_ID=your_wcl_client_id"
    echo "   - WCL_CLIENT_SECRET=your_wcl_secret"
    echo "   - POSTGRES_PASSWORD=your_secure_password"
    echo ""
    echo "4. Then run this script again or use:"
    echo "   docker-compose up -d"
    echo ""
    
    # Offer to copy template
    read -p "🤔 Copy .env.template to .env now? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp .env.template .env
        echo "✅ .env file created from template"
        echo "📝 Please edit .env with your actual credentials before deploying"
        
        # Try to open editor
        if command -v nano &> /dev/null; then
            read -p "🤔 Open .env in nano editor now? (y/n): " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                nano .env
            fi
        fi
    fi
    
    exit 0
fi

# Validate environment file
echo "🔍 Validating environment configuration..."
required_vars=("DISCORD_BOT_TOKEN" "WCL_CLIENT_ID" "WCL_CLIENT_SECRET" "POSTGRES_PASSWORD")
missing_vars=()

for var in "${required_vars[@]}"; do
    if ! grep -q "^$var=.*[^[:space:]]" .env || grep -q "^$var=your_.*_here" .env; then
        missing_vars+=("$var")
    fi
done

if [ ${#missing_vars[@]} -ne 0 ]; then
    echo "❌ Missing or unconfigured required environment variables:"
    for var in "${missing_vars[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "📝 Please edit your .env file with actual values:"
    echo "   nano .env"
    exit 1
fi

echo "✅ Environment configuration validated"

# Deploy
echo ""
echo "🚀 Deploying LuminisBot..."
docker-compose up -d

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 Check status:"
echo "   docker-compose ps"
echo ""
echo "📋 View logs:"
echo "   docker-compose logs -f luminisbot"
echo ""
echo "🌐 Health check:"
echo "   curl http://localhost:10000"
echo ""
echo "📚 For more commands, see QUICK_REFERENCE.md"
