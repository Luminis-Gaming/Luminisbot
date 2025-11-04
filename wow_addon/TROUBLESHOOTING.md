# Troubleshooting Guide

## Slash Commands Not Working

If `/luminisbot` or `/lb` doesn't work in-game, follow these steps:

### Step 1: Verify Addon is Loaded

1. At character select screen, click **AddOns** button (bottom-left)
2. Find **Luminisbot Events** in the list
3. Make sure it has a checkmark next to it
4. If not listed, the addon isn't installed correctly

### Step 2: Check for Load Errors

In-game, type:
```
/console scriptErrors 1
```

Then type `/reload` and watch for any red error messages.

### Step 3: Check Chat for Load Message

When you log in, you should see:
```
Luminisbot: loaded! Type /luminisbot or /lb to get started.
```

If you don't see this message, the addon didn't load.

### Step 4: Verify File Structure

Your addon folder should look like this:
```
Interface/AddOns/LuminisbotEvents/
    ├── LuminisbotEvents.toc
    ├── Core.lua
    └── UI.lua
```

**Common mistakes:**
- ❌ `Interface/AddOns/LuminisbotEvents/LuminisbotEvents/` (double folder)
- ❌ `Interface/AddOns/Luminisbot/LuminisbotEvents/` (wrong parent folder)
- ✅ `Interface/AddOns/LuminisbotEvents/` (correct!)

### Step 5: Check Interface Version

Open `LuminisbotEvents.toc` and check the first line:
```
## Interface: 110002
```

This is for The War Within (11.0.2). If you're on a different patch:
- **Classic Era:** Change to `11504`
- **Cataclysm Classic:** Change to `40400`
- **Retail (TWW Season 1):** Keep at `110002`
- **Retail (latest):** Check current interface version with `/run print((select(4, GetBuildInfo())))`

### Step 6: Manual Command Test

Try typing this in-game:
```lua
/run if SlashCmdList["LUMINISBOT"] then print("Command exists!") else print("Command not found!") end
```

**If it says "Command not found":**
- The slash command isn't registered
- Try `/reload` and check for errors

**If it says "Command exists":**
- The command IS registered, but something else is wrong
- Try `/luminisbot help` to see if that works

### Step 7: Test UI Directly

Try this Lua command to open the UI directly:
```lua
/run local addon = select(2, ...) or _G["LuminisbotEvents"]; if addon and addon.ShowUI then addon:ShowUI() else print("Addon table not found!") end
```

### Step 8: Check SavedVariables

If addon loads but has no UI, check if SavedVariables file exists:
- Path: `WTF/Account/<YOUR_ACCOUNT>/SavedVariables/LuminisbotEvents.lua`
- If missing, it's created on first `/reload` or logout

### Step 9: Fresh Install

1. Completely remove the `LuminisbotEvents` folder
2. Delete `WTF/Account/<YOUR_ACCOUNT>/SavedVariables/LuminisbotEvents.lua` (if exists)
3. Re-extract the addon
4. Restart WoW completely (not just `/reload`)
5. Log in and check character select AddOns list

### Step 10: Get Debug Info

Type these commands and report the results:

```lua
/run print("Addon loaded:", select(2, ...) and "YES" or "NO")
/run print("Slash cmd 1:", SLASH_LUMINISBOT1 or "NIL")
/run print("Slash cmd 2:", SLASH_LUMINISBOT2 or "NIL")
/run print("Handler:", SlashCmdList["LUMINISBOT"] and "EXISTS" or "NIL")
```

## Still Not Working?

If none of the above works, it might be:

1. **Addon conflict**: Disable all other addons and test with only LuminisbotEvents
2. **Protected UI issue**: Some commands are protected in combat/instances
3. **Interface locked**: If UI is locked, try `/fstack` then escape, then try again

## Alternative Access Methods

If slash commands still don't work, you can access addon functions directly:

**Open UI:**
```lua
/run LuminisbotEventsFrame:Show()
```

**Import Event (replace <string> with your Base64 string):**
```lua
/run local addon = select(2, ...); addon:ImportEventString("<string>")
```

**List Events:**
```lua
/run local addon = select(2, ...); for i, e in ipairs(addon:GetEvents()) do print(i, e.title, e.date) end
```

## Contact Support

If you've tried all of the above and it still doesn't work, report these details:
- WoW version (Retail/Classic/Era?)
- Interface number from `/run print((select(4, GetBuildInfo())))`
- Error messages (if any)
- Output from Step 10 debug commands
- Screenshot of AddOns folder showing file structure
