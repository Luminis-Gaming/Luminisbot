@echo off
setlocal EnableDelayedExpansion

REM deploy.bat - Windows deployment script for LuminisBot

echo 🚀 LuminisBot Deployment Script
echo ================================

REM Check if Docker is available
docker --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if Docker Compose is available
docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker Compose is not installed or not in PATH
    pause
    exit /b 1
)

REM Check if .env file exists
if not exist ".env" (
    echo ❌ .env file not found!
    echo 📋 Please copy .env.template to .env and fill in your credentials:
    echo    copy .env.template .env
    echo    notepad .env
    pause
    exit /b 1
)

echo ✅ Prerequisites validated

:menu
echo.
echo 📋 Deployment Options:
echo 1^) 🆕 Fresh deployment ^(build and start^)
echo 2^) 🔄 Update bot ^(rebuild with new code^)
echo 3^) 🛑 Stop bot
echo 4^) 📊 View logs
echo 5^) 🔍 Check status
echo 6^) 🗑️  Clean up ^(⚠️  removes all data^)
echo 7^) 🚪 Exit
echo.

set /p choice="Choose an option (1-7): "

if "%choice%"=="1" (
    echo 🚀 Starting fresh deployment...
    docker-compose up -d --build
    if errorlevel 1 (
        echo ❌ Deployment failed!
        pause
        goto menu
    )
    echo ✅ Deployment complete!
    echo 🌐 Keep-alive endpoint: http://localhost:10000
    echo 📊 View logs with: docker-compose logs -f luminisbot
) else if "%choice%"=="2" (
    echo 🔄 Updating bot with new code...
    docker-compose up -d --build luminisbot
    if errorlevel 1 (
        echo ❌ Update failed!
        pause
        goto menu
    )
    echo ✅ Bot updated!
) else if "%choice%"=="3" (
    echo 🛑 Stopping services...
    docker-compose down
    echo ✅ Services stopped
) else if "%choice%"=="4" (
    echo 📊 Showing logs ^(press Ctrl+C to exit^)...
    docker-compose logs -f
) else if "%choice%"=="5" (
    echo 🔍 Service status:
    docker-compose ps
    echo.
    echo 🏥 Health status:
    docker-compose exec luminisbot curl -s http://localhost:10000 2>nul
    if errorlevel 1 echo ❌ Bot health check failed
) else if "%choice%"=="6" (
    echo ⚠️  This will stop all services and DELETE ALL DATA!
    set /p confirm="Are you sure? Type 'yes' to confirm: "
    if "!confirm!"=="yes" (
        echo 🗑️  Cleaning up...
        docker-compose down -v
        docker system prune -f
        echo ✅ Cleanup complete
    ) else (
        echo ❌ Cleanup cancelled
    )
) else if "%choice%"=="7" (
    echo 👋 Goodbye!
    exit /b 0
) else (
    echo ❌ Invalid option. Please choose 1-7.
)

echo.
pause
goto menu
