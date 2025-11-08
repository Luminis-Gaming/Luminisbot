"""
Auto-updater module for Luminisbot Companion App

Checks GitHub releases for new versions and provides in-app update functionality.
"""

import requests
import json
import os
import sys
import subprocess
from pathlib import Path
from packaging import version
import tempfile
import shutil

GITHUB_REPO = "Luminis-Gaming/Luminisbot"
CURRENT_VERSION = "1.0.0"  # This should match VERSION in main file

class AutoUpdater:
    def __init__(self, current_version):
        self.current_version = current_version
        self.latest_version = None
        self.download_url = None
        self.release_notes = None
        
    def check_for_updates(self):
        """
        Check GitHub releases for newer version
        Returns: (has_update: bool, latest_version: str, download_url: str, notes: str)
        """
        try:
            # GitHub API endpoint for latest release
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            
            response = requests.get(url, timeout=10)
            
            if response.status_code != 200:
                return False, None, None, "Could not check for updates"
            
            data = response.json()
            
            # Extract version from tag (e.g., "v1.2.0" -> "1.2.0")
            latest_tag = data.get('tag_name', '').lstrip('v')
            release_notes = data.get('body', 'No release notes available')
            
            # Find the companion app executable in assets
            # Look for the portable .exe, NOT the installer
            download_url = None
            for asset in data.get('assets', []):
                asset_name = asset['name']
                # Match: LuminisbotCompanion.exe or LuminisbotCompanion_v1.0.0.exe
                # Exclude: installers (contain "Setup" or "Installer" or "Install")
                if ('Companion' in asset_name and 
                    asset_name.endswith('.exe') and 
                    'Setup' not in asset_name and 
                    'Installer' not in asset_name and
                    'Install' not in asset_name):
                    download_url = asset['browser_download_url']
                    break
            
            if not download_url:
                return False, None, None, "No companion app executable found in release"
            
            # Compare versions
            try:
                if version.parse(latest_tag) > version.parse(self.current_version):
                    self.latest_version = latest_tag
                    self.download_url = download_url
                    self.release_notes = release_notes
                    return True, latest_tag, download_url, release_notes
                else:
                    return False, latest_tag, None, "You're up to date!"
            except Exception as e:
                return False, None, None, f"Version comparison error: {e}"
                
        except Exception as e:
            return False, None, None, f"Update check failed: {e}"
    
    def download_update(self, progress_callback=None):
        """
        Download the new version
        progress_callback: function(bytes_downloaded, total_bytes)
        Returns: (success: bool, file_path: str, error: str)
        """
        if not self.download_url:
            return False, None, "No download URL available"
        
        try:
            # Create temp directory
            temp_dir = Path(tempfile.gettempdir()) / "luminisbot_update"
            temp_dir.mkdir(exist_ok=True)
            
            # Download file
            response = requests.get(self.download_url, stream=True, timeout=30)
            total_size = int(response.headers.get('content-length', 0))
            
            downloaded = 0
            file_path = temp_dir / "LuminisbotCompanion_new.exe"
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total_size)
            
            return True, str(file_path), None
            
        except Exception as e:
            return False, None, f"Download failed: {e}"
    
    def install_update(self, new_exe_path):
        """
        Install the update by replacing current executable
        This requires a helper script since we can't replace a running executable
        
        Returns: (success: bool, error: str)
        """
        try:
            # Get current executable path
            if getattr(sys, 'frozen', False):
                current_exe = sys.executable
            else:
                # Running from Python, can't auto-update
                return False, "Auto-update only works with compiled executable"
            
            # Create update script that runs after this process exits
            update_script = self._create_update_script(current_exe, new_exe_path)
            
            # Launch update script and exit current app
            if sys.platform == 'win32':
                subprocess.Popen(['cmd', '/c', update_script], 
                               creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                subprocess.Popen(['bash', update_script])
            
            return True, None
            
        except Exception as e:
            return False, f"Installation failed: {e}"
    
    def _create_update_script(self, current_exe, new_exe):
        """Create a batch/shell script to replace exe after app closes"""
        
        if sys.platform == 'win32':
            # Windows batch script
            script_path = Path(tempfile.gettempdir()) / "luminisbot_updater.bat"
            
            # Use process name to wait for full exit
            exe_name = Path(current_exe).name
            
            script_content = f"""@echo off
echo Updating Luminisbot Companion...

REM Wait for the process to fully exit
:waitloop
tasklist /FI "IMAGENAME eq {exe_name}" 2>NUL | find /I "{exe_name}">NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak > nul
    goto waitloop
)

REM Extra wait to ensure DLLs and temp files are released
timeout /t 5 /nobreak > nul

REM Delete old executable
:retrydelete
if exist "{current_exe}" (
    del "{current_exe}" 2>nul
    if exist "{current_exe}" (
        timeout /t 2 /nobreak > nul
        goto retrydelete
    )
)

REM Move new executable into place
move /y "{new_exe}" "{current_exe}"

REM Start new version
start "" "{current_exe}"

REM Clean up this script
(goto) 2>nul & del "%~f0"
"""
            
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            return str(script_path)
        else:
            # Unix shell script
            script_path = Path(tempfile.gettempdir()) / "luminisbot_updater.sh"
            
            script_content = f"""#!/bin/bash
echo "Updating Luminisbot Companion..."
sleep 2

while [ -e "{current_exe}" ]; do
    rm -f "{current_exe}" 2>/dev/null || sleep 1
done

mv "{new_exe}" "{current_exe}"
chmod +x "{current_exe}"
"{current_exe}" &

rm "$0"
"""
            
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            os.chmod(script_path, 0o755)
            return str(script_path)


def check_for_updates_simple(current_version):
    """Simple wrapper for one-line update check"""
    updater = AutoUpdater(current_version)
    return updater.check_for_updates()


# Example usage in main app:
"""
from updater import AutoUpdater

# On app startup or menu click:
updater = AutoUpdater("1.0.0")
has_update, version, url, notes = updater.check_for_updates()

if has_update:
    # Show dialog: "Update available: v1.2.0 - Do you want to update?"
    if user_clicks_yes:
        success, file_path, error = updater.download_update(progress_callback)
        if success:
            updater.install_update(file_path)
            # App will exit and restart with new version
"""
