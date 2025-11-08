"""
Build script for creating the Luminisbot Companion executable
Handles PyInstaller configuration with proper icon and file inclusion
"""
import PyInstaller.__main__
import sys
from pathlib import Path

# Get the directory where this script is located
script_dir = Path(__file__).parent

# Prepare PyInstaller arguments
pyinstaller_args = [
    str(script_dir / "luminisbot_companion.py"),  # Main script
    "--onefile",                                   # Single executable file
    "--windowed",                                  # No console window (GUI app)
    "--name=LuminisbotCompanion",                 # Executable name
    f"--icon={script_dir / 'luminis_logo.ico'}",  # Application icon
    # Include the logo files
    f"--add-data={script_dir / 'luminis_logo.png'};.",
    f"--add-data={script_dir / 'luminis_logo.ico'};.",
    # Clean build
    "--clean",
    # Output directory
    f"--distpath={script_dir / 'dist'}",
    f"--workpath={script_dir / 'build'}",
    f"--specpath={script_dir}",
]

print("Building Luminisbot Companion executable...")
print(f"Icon: {script_dir / 'luminis_logo.ico'}")
print(f"Output: {script_dir / 'dist' / 'LuminisbotCompanion.exe'}")
print()

# Run PyInstaller
try:
    PyInstaller.__main__.run(pyinstaller_args)
    print("\n[SUCCESS] Build complete!")
    print(f"  Executable: {script_dir / 'dist' / 'LuminisbotCompanion.exe'}")
except Exception as e:
    print(f"\n[ERROR] Build failed: {e}")
    sys.exit(1)
