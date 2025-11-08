# Luminisbot Companion App

Desktop companion app that enables real-time syncing between the WoW addon and Discord bot.

## Features

**With Companion App:**
- ✅ Auto-sync events every 60 seconds
- ✅ No manual copy/paste needed
- ✅ Background operation (system tray)
- ✅ Real-time updates

**Without Companion App:**
- ✅ Manual sync via `/syncevents` in Discord
- ✅ Still fully functional
- ✅ No extra software required

## Installation

### Windows

1. Download `LuminisbotCompanion.exe` from releases
2. Run the executable
3. Enter your subscription string (from `/subscribe` in Discord)
4. Set your WoW installation path
5. Enter your WoW account name
6. Click "Start Syncing"

### From Source

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python luminisbot_companion.py
```

### Build Executable

```bash
# Install PyInstaller
pip install pyinstaller

# Build for Windows
pyinstaller --onefile --windowed --name "LuminisbotCompanion" --icon=icon.ico luminisbot_companion.py

# Executable will be in dist/
```

## Configuration

### Getting Your Subscription String

1. Open Discord
2. Type `/subscribe` in your guild's server
3. Copy the entire encoded string shown
4. Paste into companion app

**Why?** This string contains your guild ID and secure API key that lets the app fetch your guild's events.

### Setting Your WoW Path

Point the app to your World of Warcraft installation folder. This is usually:
- Windows: `C:\Program Files (x86)\World of Warcraft\_retail_`
- Mac: `/Applications/World of Warcraft/_retail_`

**Why?** The app needs to save event data to your WoW addon's folder so it can read it.

### Selecting Your WoW Account

After setting your WoW path, the app will automatically detect your account folders. Just select which account you play on.

**Why?** WoW stores addon data separately for each Battle.net account (like WoW1, WoW2, etc). This tells the app where to save the events file.

## How It Works

1. **Polls API** every 60 seconds for new events
2. **Writes to SavedVariables** file that WoW addon reads
3. **Addon auto-reloads** data when file changes
4. **Runs in background** - minimize to system tray

## Troubleshooting

**"Invalid API key"**
- Get a new subscription string with `/subscribe` in Discord

**"WoW path not found"**
- Make sure you selected the correct WoW installation folder
- Path should end with `World of Warcraft` or similar

**"Account name not found"**
- The app should auto-detect accounts from your WoW path
- If dropdown is empty, double-check your WoW path is correct

**Events not showing in-game**
- Type `/reload` in WoW after companion syncs
- Check that LuminisbotEvents addon is installed and enabled

## Privacy & Security

- Your API key stays on your computer
- Only communicates with luminisbot.flipflix.no
- No data collected or sent elsewhere
- Open source - audit the code yourself

## License

MIT License - See main repository
