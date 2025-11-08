@echo off
echo Building Luminisbot Companion executable...
echo.

REM Install PyInstaller if not already installed
pip install pyinstaller >nul 2>&1

REM Run the build script
python build_exe.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ============================================
    echo Build successful!
    echo Executable: dist\LuminisbotCompanion.exe
    echo ============================================
    echo.
    pause
) else (
    echo.
    echo ============================================
    echo Build failed! Check the error messages above.
    echo ============================================
    echo.
    pause
    exit /b 1
)
