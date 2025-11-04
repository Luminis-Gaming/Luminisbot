# Quick Test Steps

## After Installing the Addon

### 1. Check Addon Loads
When you log in, you should see a green banner in chat:
```
===========================================
Luminisbot Events v1.0.0 loaded!
Type /luminisbot or /lb to get started
===========================================
```

**Don't see it?** → See TROUBLESHOOTING.md

### 2. Test Commands (in order)

```
/luminisbot help
```
Should show a list of available commands.

```
/lb
```
Should toggle the event window (or show "No events yet").

```
/luminisbot list
```
Should show "No events imported yet!" if no events.

### 3. Import Test Event

In Discord:
1. Open any raid event
2. Click Admin Panel
3. Click "Copy Event String"
4. Copy the entire `/luminisbot import ...` command

In WoW:
1. Paste the command
2. Press Enter
3. Should see: `✓ Imported event: <EventName> (X signups)`

### 4. View Events

```
/lb show
```

You should see a window with your imported event!

### 5. Test Invite (Optional)

If you have actual signups:
1. Open event window (`/lb`)
2. Click "Invite All" button
3. Should send invites to all signed players

---

## Debug Commands

If something doesn't work, run these and report the output:

```lua
/run print("WoW Version:", GetBuildInfo())
/run print("Interface:", select(4, GetBuildInfo()))
/run print("Slash 1:", SLASH_LUMINISBOT1 or "NIL")
/run print("Slash 2:", SLASH_LUMINISBOT2 or "NIL")
/run print("Handler:", SlashCmdList["LUMINISBOT"] and "YES" or "NO")
```

Enable error display:
```
/console scriptErrors 1
/reload
```

---

## Expected Behavior

### ✅ Working Correctly
- Green banner on login
- `/luminisbot` opens window
- `/lb` works same as `/luminisbot`
- Import shows success message
- Events appear in window
- Invite button sends invites

### ❌ Common Issues
- No banner = Addon not loaded
- "Unknown command" = Slash command not registered
- "UI not loaded yet" = Timing issue, try `/reload`
- Window appears but empty = No events imported yet
- Invite fails = Players offline/wrong realm/full raid

---

## File Check

Your addon folder should be:
```
World of Warcraft\_retail_\Interface\AddOns\LuminisbotEvents\
    ├── LuminisbotEvents.toc
    ├── Core.lua
    └── UI.lua
```

**Not like this:**
```
❌ AddOns\LuminisbotEvents\LuminisbotEvents\
❌ AddOns\wow_addon\LuminisbotEvents\
❌ AddOns\Luminisbot\LuminisbotEvents\
```

---

## Quick Fixes

**"Unknown command":**
```
/reload
```

**Addon not in list:**
- Check folder name (must be `LuminisbotEvents` exactly)
- Check all 3 files exist
- Restart WoW completely

**UI not showing:**
```lua
/run LuminisbotEventsFrame:Show()
```

**Import failing:**
- Copy ENTIRE command (can be 1000+ characters)
- Paste in WoW chat
- For large events, use multi-part import

---

## Working Example

```
User: /luminisbot help
Bot: Available commands:
     /luminisbot show - Toggle event window
     /luminisbot import <string> - Import event from Discord
     /luminisbot list - List all imported events
     ...

User: /lb import eyJpZCI6NDIsInRpdGxlIjoiTW9uZGF5IFJhaWQiLC4uLg==
Bot: ✓ Imported event: Monday Raid (12 signups)

User: /lb
Bot: [Opens window showing Monday Raid event]
```
