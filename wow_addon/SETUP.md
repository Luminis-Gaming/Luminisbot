# WoW Addon Quick Setup Guide

## For Guild Members

### Installing the Addon

1. **Download the addon:**
   - Get the `LuminisbotEvents` folder from your guild's shared drive/Discord
   - Or clone this repository and find it in `wow_addon/LuminisbotEvents`

2. **Install to WoW:**
   - Windows: Copy to `C:\Program Files (x86)\World of Warcraft\_retail_\Interface\AddOns\`
   - Mac: Copy to `/Applications/World of Warcraft/_retail_/Interface/AddOns/`

3. **Restart WoW** or type `/reload` in-game

### Using the Addon

1. **In Discord:** Open any raid event and click **⚙️ Admin Panel**
2. **Click:** **🎮 Copy Event String**
3. **Copy** the command from the bot's message
4. **In WoW:** Paste the entire command in chat and press Enter
5. **View events:** Type `/luminisbot` or `/lb`
6. **Invite players:** Click the **Invite All** button

That's it! 🎉

---

## For Developers

### Project Structure

```
wow_addon/
├── README.md                    # User documentation
├── SETUP.md                     # This file
└── LuminisbotEvents/            # Addon folder
    ├── LuminisbotEvents.toc     # Addon manifest
    ├── Core.lua                 # Data import & logic
    └── UI.lua                   # Interface & display
```

### Architecture

**Data Flow:**
1. Discord bot encodes event data to Base64 JSON
2. User copies string and pastes in WoW
3. `Core.lua` decodes Base64 → parses JSON → saves to `SavedVariables`
4. `UI.lua` reads from `SavedVariables` → displays in-game UI
5. User clicks "Invite" → addon calls `C_PartyInfo.InviteUnit()`

**Key Files:**

- **`LuminisbotEvents.toc`**: Addon manifest (interface version, files to load)
- **`Core.lua`**: 
  - Base64 decoder (pure Lua)
  - Simple JSON parser (handles nested objects/arrays)
  - Event import/export logic
  - Slash command handler (`/luminisbot`)
- **`UI.lua`**:
  - Main event list window
  - Event details popup
  - Invite functionality
  - Frame templates and styling

### Saved Variables

The addon persists data in `WTF/Account/<ACCOUNT>/SavedVariables/LuminisbotEvents.lua`:

```lua
LuminisbotEventsDB = {
    events = {
        [1] = {
            id = 42,
            title = "Monday Mythic Raid",
            date = "2025-11-06",
            time = "20:00:00",
            signups = {
                {
                    name = "Arthas",
                    realm = "tarren-mill",
                    class = "Paladin",
                    role = "tank",
                    spec = "Protection",
                    status = "signed"
                },
                -- ... more signups
            }
        }
    },
    lastUpdate = 1730745600,
    settings = {
        showTooltips = true,
        sortByDate = true
    }
}
```

### Testing Locally

1. **Install addon** in your WoW `AddOns` folder
2. **Launch WoW** (or `/reload`)
3. **Generate test string** in Discord (use admin panel on any event)
4. **Import in WoW:** `/luminisbot import <string>`
5. **Open UI:** `/lb show`

**Debug Tips:**
- Use `/console scriptErrors 1` to see Lua errors
- Check `Logs/` folder for WoW error logs
- Install **BugSack** addon for better error reporting
- Install **ViragDevTool** for inspecting saved variables

### Common Issues

**"Addon not loading":**
- Check folder name is exactly `LuminisbotEvents`
- Verify `.toc` file has correct `## Interface:` version
- Try `/reload` or restart WoW

**"Import failed":**
- String might be truncated (Discord has character limits)
- Use multi-part import for large events
- Check for extra spaces/newlines in pasted string

**"Invites not working":**
- Verify realm formatting (spaces removed)
- Check player is online and same faction
- Raid might be full (40 player max)

### Extending the Addon

**Adding Features:**

1. **Auto-refresh via API** (advanced):
   - Create Python helper program that polls Discord bot API
   - Helper writes to `SavedVariables` file
   - Addon detects file changes and reloads data

2. **LibDataBroker support**:
   - Add minimap button integration
   - Quick access to events from minimap

3. **Whisper notifications**:
   - Whisper players when invited
   - Send event reminders

4. **Guild calendar integration**:
   - Export events to WoW calendar
   - Set reminders in-game

### Code Style

- **Indentation:** 4 spaces
- **Naming:** camelCase for locals, PascalCase for globals
- **Comments:** Explain "why", not "what"
- **Structure:** Separate concerns (data vs UI)

### Contributing

When making changes:

1. Test thoroughly in-game
2. Check for Lua errors (`/console scriptErrors 1`)
3. Test with multiple events (small and large)
4. Test multi-part import for large events
5. Update this documentation

### Deployment

**Releasing a new version:**

1. Update version in `LuminisbotEvents.toc`
2. Update version in `Core.lua` (`addon.version`)
3. Test on live WoW realms
4. Package: Zip the `LuminisbotEvents` folder
5. Distribute via Discord/GitHub

**Update Process for Users:**

1. Download new version
2. Replace old `LuminisbotEvents` folder
3. `/reload` in WoW
4. Existing imported events are preserved (stored in SavedVariables)

---

## Troubleshooting

### For Users

**Q: Addon disappeared after update?**  
A: Check AddOns folder, might need to re-extract from ZIP

**Q: Lost all my events!**  
A: Check `WTF/Account/<YOUR_ACCOUNT>/SavedVariables/LuminisbotEvents.lua`  
   If it exists, `/reload` should restore them

**Q: Import string too long for chat?**  
A: Use multi-part import (bot will provide import1, import2, etc.)

### For Developers

**Q: How to debug Base64 decoding?**  
A: Add `print(jsonString)` after decoding to see raw JSON

**Q: JSON parsing failing?**  
A: The parser is simple - might fail on complex nested structures.  
   Consider using a Lua JSON library like `dkjson` or `cjson`

**Q: Want to add network requests?**  
A: WoW Lua can't make HTTP requests directly.  
   Need external helper program or WeakAuras integration

---

## Resources

- **WoW API Docs:** https://warcraft.wiki.gg/
- **Lua 5.1 Reference:** https://www.lua.org/manual/5.1/
- **Addon Development:** https://www.wowace.com/
- **Frame Templates:** https://www.townlong-yak.com/framexml/

---

## License

This addon is part of the Luminisbot project.  
Created for Luminis Gaming guild.

**Use freely within your guild!**  
If sharing publicly, please credit Luminis Gaming.
