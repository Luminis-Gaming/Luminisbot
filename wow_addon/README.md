# Luminisbot Events - WoW Addon

> 📦 **Status: Ready for Testing!**  
> The addon is fully implemented and ready to use. See instructions below.

Display your Discord raid events in World of Warcraft with one-click invites!

## 🎮 Features

- **View Events In-Game** - See all upcoming raid events from Discord
- **See All Signups** - View everyone who signed up with their roles and specs
- **One-Click Invites** - Invite all signed-up players with a single button
- **Role Composition** - See tank/healer/DPS breakdown at a glance
- **Multiple Statuses** - Shows signed, late, tentative, benched, and absent players

## 📦 Installation

### Method 1: Manual Installation (Recommended)

1. Download the `LuminisbotEvents` folder
2. Copy it to your WoW AddOns directory:
   - **Windows:** `C:\Program Files (x86)\World of Warcraft\_retail_\Interface\AddOns\`
   - **Mac:** `/Applications/World of Warcraft/_retail_/Interface/AddOns/`
3. Restart World of Warcraft (or reload UI with `/reload`)

### Method 2: From ZIP

1. Download the addon as a ZIP file
2. Extract the contents
3. Move the `LuminisbotEvents` folder to your AddOns directory
4. Restart WoW or `/reload`

## 🚀 Quick Start

### Step 1: Get Your Event String

In Discord, open the raid event you want to import:

1. Click the **⚙️ Admin Panel** button on the event
2. Click **🎮 Copy Event String**
3. Copy the command from the bot's response (it starts with `/luminisbot import`)

### Step 2: Import to WoW

1. Open World of Warcraft
2. **Paste the entire command** in chat (can be very long - that's normal!)
3. Press Enter
4. You should see: `✓ Imported event: <EventName> (X signups)`

**Example:**
```
/luminisbot import eyJpZCI6NDIsInRpdGxlIjoiTW9uZGF5IE15dGhpYyBOaWdodCIsImRhdGUiOiIyMDI1LTExLTA2IiwidGltZSI6IjIwOjAwOjAwIiwic2lnbnVwcyI6W3sibmFtZSI6IkFydGhhcyIsInJlYWxtIjoidGFycmVuLW1pbGwiLCJjbGFzcyI6IlBhbGFkaW4iLCJyb2xlIjoidGFuayIsInNwZWMiOiJQcm90ZWN0aW9uIiwic3RhdHVzIjoic2lnbmVkIn1dfQ==
```

### Step 3: View Your Events

Open the addon window with any of these commands:
```
/luminisbot
/lb
```

You should see a window with your imported event!

### Step 4: Invite Players

Click the **Invite All** button next to an event to invite all signed-up players!

---

## ⚠️ Troubleshooting

**Don't see the window?** → Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

**Commands not working?** → See [TESTING.md](TESTING.md) for debug steps

**When you log in, you should see:**
```
===========================================
Luminisbot Events v1.0.0 loaded!
Type /luminisbot or /lb to get started
===========================================
```

If you don't see this message, the addon isn't loading. Check the file structure in TROUBLESHOOTING.md.

## 🎯 Commands

| Command | Description |
|---------|-------------|
| `/luminisbot` | Toggle event window |
| `/luminisbot show` | Show event window |
| `/luminisbot import <string>` | Import event from Discord |
| `/luminisbot help` | Show help |
| `/lb` | Short alias for `/luminisbot` |

## 💡 Tips & Tricks

### Large Events (Multi-Part Import)

If your event has many signups (30+), you'll get multiple commands to paste:

```
/luminisbot import1 <part1>
/luminisbot import2 <part2>
/luminisbot import3 <part3>
/luminisbot importdone
```

Paste each one in order, then run `/luminisbot importdone` to complete the import.

### Refreshing Events

To update an event with new signups:
1. Get a new event string from Discord (events update in real-time on Discord)
2. Import it again - it will replace the old data

### Inviting Cross-Realm Players

The addon automatically formats character names for cross-realm invites:
- `Arthas-TarrenMill` (spaces removed from realm names)
- `Jaina-Quel'Thalas` (apostrophes kept)

### Sorting and Filtering

Events are automatically sorted by date (soonest first). The signup list shows:
- **Role icons:** 🛡️ Tank, 💚 Healer, ⚔️ DPS
- **Class colors:** Class-specific coloring
- **Specs:** Specialization icons (if available)

## 🔧 Troubleshooting

### "Addon not loading"
- Make sure the folder name is exactly `LuminisbotEvents`
- Check that it's in the correct AddOns directory
- Try `/reload` or restart WoW

### "Import failed"
- Make sure you copied the ENTIRE command (they can be long!)
- Check for extra spaces at the beginning or end
- Try copying again from Discord

### "Invites not working"
- Make sure you're not already in a full raid (40 players max)
- Cross-realm invites require being in the same group finder or have RealID friends
- Some players might be offline or on different factions

### "Event data is outdated"
- Get a new event string from Discord
- Import it again to refresh the data

## 📋 Event Data

Each imported event includes:
- **Event title** and **date/time**
- **All signups** with:
  - Character name and realm
  - Class and specialization
  - Role (tank/healer/dps)
  - Status (signed/late/tentative/benched/absent)

## 🔐 Privacy & Security

- **No account linking required** - Just copy/paste from Discord
- **No internet connection** - Addon works entirely offline
- **No personal data stored** - Only event info you explicitly import
- **Guild-friendly** - Anyone in your Discord can use it

## 🐛 Bug Reports & Feedback

Found a bug or have a suggestion?
- Report in the `#bot-feedback` channel on Discord
- Or open an issue on GitHub (if applicable)

## 📝 Version History

### v1.0.0 (November 2025)
- Initial release
- Event import via base64 strings
- In-game event display
- One-click invite functionality
- Role/spec/status tracking

## ⚙️ Technical Details

**Compatible with:**
- Retail WoW (The War Within - Patch 11.0+)
- WoW Classic (if needed)

**Dependencies:**
- None! Pure Lua, no external libraries required

**SavedVariables:**
- `LuminisbotEventsDB` - Stores imported events between sessions

## 🙏 Credits

- Created for Luminis Gaming guild
- Pairs with the LuminisBot Discord bot
- Powered by ☕ and raiding enthusiasm

---

**Happy Raiding! 🎉**
