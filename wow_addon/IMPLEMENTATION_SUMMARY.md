# 🎮 WoW Addon Integration - Quick Reference

## What Was Implemented

### ✅ Discord Bot Changes (raid_system.py)
Added a **"🎮 Copy Event String"** button to the Admin Panel that:
- Encodes event data (title, date, time, all signups) to Base64 JSON
- Handles both small events (single command) and large events (multi-part)
- Sends ephemeral message with WoW import command

### ✅ WoW Addon (wow_addon/LuminisbotEvents/)
A complete addon that:
- Imports events via `/luminisbot import <string>`
- Displays events in a beautiful in-game UI
- Shows all signups with roles, specs, and classes
- One-click invite functionality (`Invite All` button)
- Persistent storage (survives logout/reload)
- Multi-part import for large events

## How It Works

```
[Discord Event] 
    ↓ (Admin clicks "Copy Event String")
[Bot encodes to Base64] 
    ↓ (User copies command)
[User pastes in WoW] 
    ↓ (/luminisbot import ...)
[Addon decodes & stores] 
    ↓ (User opens UI)
[Display events in-game] 
    ↓ (User clicks "Invite All")
[Send raid invites!] ✨
```

## User Workflow

**In Discord:**
1. Open any raid event
2. Click **⚙️ Admin Panel**
3. Click **🎮 Copy Event String**
4. Copy the command

**In WoW:**
1. Paste command in chat: `/luminisbot import <string>`
2. Open addon: `/luminisbot` or `/lb`
3. Click **Invite All** to invite everyone!

## File Structure

```
Luminisbot/
├── raid_system.py              # Modified: Added copy_event_string_button
├── WOW_ADDON_INTEGRATION_RESEARCH.md  # Research & architecture docs
└── wow_addon/
    ├── README.md               # User documentation
    ├── SETUP.md                # Developer setup guide
    └── LuminisbotEvents/       # Actual addon
        ├── LuminisbotEvents.toc
        ├── Core.lua            # Import logic & data management
        └── UI.lua              # Interface & display
```

## Key Features

### Discord Bot
- ✅ Base64 encoding of event data
- ✅ JSON serialization (compact format)
- ✅ Multi-part splitting for large events
- ✅ Ephemeral responses (private to user)
- ✅ Shows event summary in response

### WoW Addon
- ✅ Base64 decoding (pure Lua implementation)
- ✅ JSON parsing (handles nested objects/arrays)
- ✅ Persistent storage via SavedVariables
- ✅ Beautiful UI with role icons and class colors
- ✅ Event details popup
- ✅ Automatic realm formatting for cross-realm invites
- ✅ Multi-part import support
- ✅ Event management (delete, clear old)

## Testing Checklist

### Before Release
- [ ] Test small event (1-5 signups)
- [ ] Test large event (30+ signups, multi-part)
- [ ] Test cross-realm character names
- [ ] Test with all status types (signed/late/tentative/absent)
- [ ] Test invite functionality
- [ ] Test UI on different screen sizes
- [ ] Test with multiple events imported
- [ ] Test delete event functionality
- [ ] Test after `/reload` (data persistence)

### In Production
- [ ] Install addon for 2-3 beta testers
- [ ] Have them import real events
- [ ] Test invites in actual raid
- [ ] Gather feedback on UI/UX
- [ ] Monitor for Lua errors

## Future Enhancements (Optional)

### Phase 2: API Integration
- REST API endpoint for event data
- Helper program for auto-sync
- Automatic updates every 5 minutes
- No more copy-paste needed!

### Phase 3: Quality of Life
- Minimap button (LibDataBroker)
- Whisper players when invited
- Export to WoW calendar
- Filter events by date/status
- Search functionality

## Troubleshooting

### "Addon not showing in character select"
- Check folder name: Must be exactly `LuminisbotEvents`
- Verify in correct AddOns directory
- Restart WoW completely

### "Import command not working"
- Make sure you copied the ENTIRE command (they can be very long)
- Check for extra spaces or newlines
- For large events, use multi-part import

### "Invites failing"
- Verify players are online and same faction
- Check realm names are formatted correctly
- Ensure not in a full raid (40 max)

### "Events disappeared after logout"
- Check SavedVariables file wasn't deleted
- Path: `WTF/Account/<ACCOUNT>/SavedVariables/LuminisbotEvents.lua`
- Try `/reload` to force save

## Distribution

### For Guild Members
1. Zip the `LuminisbotEvents` folder
2. Upload to Discord/Google Drive
3. Share installation instructions from `wow_addon/README.md`

### For Addon Sites (Future)
- CurseForge: Create project page
- WoWInterface: Upload with screenshots
- GitHub Releases: Tag version, attach .zip

## Credits

- **Idea:** Original concept from guild leadership
- **Implementation:** Based on research and planning documents
- **Testing:** Guild members (thank you!)
- **Powered by:** ☕, 🍕, and many raid wipes

---

## Quick Commands Reference

| Command | Description |
|---------|-------------|
| `/luminisbot` | Toggle event window |
| `/lb` | Short alias |
| `/luminisbot import <string>` | Import event |
| `/luminisbot import1 <part1>` | Multi-part (part 1) |
| `/luminisbot importdone` | Finish multi-part import |
| `/luminisbot list` | List all events |
| `/luminisbot clear` | Delete past events |
| `/luminisbot help` | Show help |

---

**Status:** ✅ Ready for production testing  
**Version:** 1.0.0  
**Last Updated:** November 4, 2025
