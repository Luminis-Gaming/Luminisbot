#!/bin/bash

# deploy.sh - Simple deployment script for LuminisBot

set -e  # Exit on any error

echo "🚀 LuminisBot Deployment Script"
echo "================================"

# Check if Docker and Docker Compose are available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed or not in PATH"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed or not in PATH"
    exit 1
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found!"
    echo "📋 Please copy .env.template to .env and fill in your credentials:"
    echo "   cp .env.template .env"
    echo "   nano .env  # or use your preferred editor"
    exit 1
fi

# Validate required environment variables
echo "🔍 Validating environment variables..."

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
    echo "📝 Please update your .env file with actual values (not the placeholder text)"
    echo "💡 See DATABASE_SETUP.md for detailed instructions"
    exit 1
fi

echo "✅ Environment variables validated"

# Function to show deployment options
show_menu() {
    echo ""
    echo "📋 Deployment Options:"
    echo "1) 🆕 Fresh deployment (build and start)"
    echo "2) 🔄 Update bot (rebuild with new code)"
    echo "3) 🛑 Stop bot"
    echo "4) 📊 View logs"
    echo "5) 🔍 Check status"
    echo "6) 🗑️  Clean up (⚠️  removes all data)"
    echo "7) 🚪 Exit"
    echo ""
}

# Main menu loop
while true; do
    show_menu
    read -p "Choose an option (1-7): " choice
    
    case $choice in
        1)
            echo "🚀 Starting fresh deployment..."
            docker-compose up -d --build
            echo "✅ Deployment complete!"
            echo "🌐 Keep-alive endpoint: http://localhost:10000"
            echo "📊 View logs with: docker-compose logs -f luminisbot"
            ;;
        2)
            echo "🔄 Updating bot with new code..."
            docker-compose up -d --build luminisbot
            echo "✅ Bot updated!"
            ;;
        3)
            echo "🛑 Stopping services..."
            docker-compose down
            echo "✅ Services stopped"
            ;;
        4)
            echo "📊 Showing logs (press Ctrl+C to exit)..."
            docker-compose logs -f
            ;;
        5)
            echo "🔍 Service status:"
            docker-compose ps
            echo ""
            echo "🏥 Health status:"
            docker-compose exec luminisbot curl -s http://localhost:10000 || echo "❌ Bot health check failed"
            ;;
        6)
            echo "⚠️  This will stop all services and DELETE ALL DATA!"
            read -p "Are you sure? Type 'yes' to confirm: " confirm
            if [ "$confirm" = "yes" ]; then
                echo "🗑️  Cleaning up..."
                docker-compose down -v
                docker system prune -f
                echo "✅ Cleanup complete"
            else
                echo "❌ Cleanup cancelled"
            fi
            ;;
        7)
            echo "👋 Goodbye!"
            exit 0
            ;;
        *)
            echo "❌ Invalid option. Please choose 1-7."
            ;;
    esac
    
    echo ""
    read -p "Press Enter to continue..."
done
