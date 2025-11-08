@echo off
REM Build the installer package for Luminisbot Companion
echo ================================================
echo Building Luminisbot Companion Installer
echo ================================================
echo.

REM Step 1: Build the executable
echo [1/3] Building executable...
python build_exe.py
if errorlevel 1 (
    echo.
    echo ERROR: Failed to build executable
    pause
    exit /b 1
)
echo [SUCCESS] Executable built
echo.

REM Step 2: Check for Inno Setup
echo [2/3] Checking for Inno Setup...
set INNO_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe

if not exist "%INNO_PATH%" (
    echo.
    echo WARNING: Inno Setup not found at: %INNO_PATH%
    echo.
    echo Please install Inno Setup from:
    echo https://jrsoftware.org/isdl.php
    echo.
    echo After installing, run this script again.
    pause
    exit /b 1
)
echo [SUCCESS] Inno Setup found
echo.

REM Step 3: Build the installer
echo [3/3] Building installer...
"%INNO_PATH%" installer.iss

if errorlevel 1 (
    echo.
    echo ERROR: Failed to build installer
    pause
    exit /b 1
)

echo.
echo ================================================
echo [SUCCESS] Installer created!
echo ================================================
echo.
echo Installer location: installer\LuminisbotCompanion-Setup-v1.0.0.exe
echo.
echo This installer provides:
echo   - Start Menu shortcuts
echo   - Desktop icon (optional)
echo   - Auto-start with Windows (optional)
echo   - Add/Remove Programs entry
echo   - Clean uninstall
echo.
pause
