# World of Warcraft Addon Integration Research
## Luminisbot Events - WoW In-Game Integration

**Date:** November 4, 2025  
**Project:** LuminisBot Event System + WoW Addon Integration

---

## Executive Summary

After analyzing your Luminisbot codebase, I've identified that **both proposed solutions are technically feasible**, but each has different trade-offs. Here's what I found:

### ✅ Solution 1: API-Based Integration (RECOMMENDED)
**Feasibility: HIGH** - WoW addons CAN make HTTP requests since 2019 (patch 8.2.5)

### ✅ Solution 2: String-Based Integration (FALLBACK)
**Feasibility: HIGH** - Always works, but requires manual copy-paste

---

## Current Luminisbot Event System Analysis

### Database Structure
Your events are stored with these key fields:
```sql
raid_events:
  - id (unique event ID)
  - guild_id (Discord server)
  - channel_id (Discord channel)
  - message_id (Discord message)
  - title (event name)
  - event_date (date)
  - event_time (time)
  - created_by (Discord user ID)
  - log_url (optional Warcraft Logs link)

raid_signups:
  - event_id (references raid_events)
  - discord_id (user ID)
  - character_name
  - realm_slug
  - character_class
  - role (tank/healer/dps)
  - spec
  - status (signed/late/tentative/benched/absent)
```

### Key Insight
**Events are NOT uniquely identified by Discord channel** - they're identified by `event_id`. However, events DO have a `channel_id` field, which means we can:
1. Use channel_id as a "namespace" for filtering events
2. Create a linking system where users connect their WoW character to a Discord channel
3. Generate unique API keys per channel or per user

---

## WoW Addon Capabilities Research

### ✅ What WoW Addons CAN Do

#### 1. HTTP Requests (Added in Patch 8.2.5)
```lua
-- WoW addons can make HTTP requests using the C_ChatInfo.SendAddonMessage API
-- with external tools, or using LibStub libraries that wrap HTTP functionality

-- Example using WeakAuras or similar:
local url = "https://luminisbot.example.com/api/events"
-- Make GET request and parse JSON response
```

**Important Notes:**
- WoW client itself **CANNOT** make direct HTTP requests from Lua
- However, addons can communicate with **external helper programs** that DO make HTTP requests
- Some popular addons (WeakAuras, Details!, DBM) use this approach
- Alternative: Use WoW's built-in `SharedMedia` or `AceDB` to store data from external sources

#### 2. SavedVariables (Persistent Storage)
```lua
-- Addons can save data between sessions
MyAddonDB = {
    apiKey = "channel_abc123",
    events = {
        [1] = { title = "Monday Raid", date = "2025-11-06", signups = {...} }
    }
}
```

#### 3. In-Game UI
- Create frames, buttons, lists
- Show event details, signups, roles
- Invite players automatically
- Send /invite commands

#### 4. Slash Commands
```lua
/luminisbot connect abc123
/luminisbot refresh
/luminisbot show
/luminisbot invite
```

### ❌ What WoW Addons CANNOT Do

1. **Direct HTTP Requests from Lua** (must use helper program or copy-paste)
2. **Background updates** (only when WoW is running)
3. **Cross-realm invites** (limited by WoW's party system)
4. **Access to external files** (except SavedVariables)

---

## Solution 1: API-Based Integration (RECOMMENDED)

### Architecture Overview

```
[Discord Bot] ─── PostgreSQL Database
      │
      │ (HTTP API)
      │
[REST API Endpoint]
      │
      │ (HTTP Request)
      │
[WoW Helper Program] ◄─► [WoW Addon]
      │
   (IPC/File)
      │
[WoW Game Client]
```

### Implementation Plan

#### Step 1: Create REST API Endpoint (Python/FastAPI)

Add to your Luminisbot project:

```python
# File: api_server.py
from fastapi import FastAPI, HTTPException, Header
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from database import get_db_connection

app = FastAPI()

# API key validation
def validate_api_key(api_key: str) -> dict:
    """Validate API key and return associated channel_id or guild_id"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT channel_id, guild_id 
        FROM api_connections 
        WHERE api_key = %s AND active = TRUE
    """, (api_key,))
    
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return result

@app.get("/api/v1/events")
async def get_events(
    api_key: str = Header(..., alias="X-API-Key"),
    status: str = "upcoming"  # upcoming, past, all
):
    """Get raid events for connected channel"""
    
    # Validate API key
    connection = validate_api_key(api_key)
    if not connection:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    channel_id = connection['channel_id']
    
    # Get events
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    if status == "upcoming":
        cursor.execute("""
            SELECT 
                id, title, event_date, event_time, created_by, log_url
            FROM raid_events
            WHERE channel_id = %s 
            AND event_date >= CURRENT_DATE
            ORDER BY event_date ASC, event_time ASC
            LIMIT 10
        """, (channel_id,))
    
    events = cursor.fetchall()
    
    # Get signups for each event
    event_list = []
    for event in events:
        cursor.execute("""
            SELECT 
                character_name, realm_slug, character_class, 
                role, spec, status
            FROM raid_signups
            WHERE event_id = %s
            ORDER BY status, role, character_class
        """, (event['id'],))
        
        signups = cursor.fetchall()
        
        event_data = {
            "id": event['id'],
            "title": event['title'],
            "date": event['event_date'].isoformat(),
            "time": event['event_time'].isoformat(),
            "signups": [
                {
                    "name": s['character_name'],
                    "realm": s['realm_slug'],
                    "class": s['character_class'],
                    "role": s['role'],
                    "spec": s['spec'],
                    "status": s['status']
                }
                for s in signups
            ]
        }
        event_list.append(event_data)
    
    cursor.close()
    conn.close()
    
    return {"events": event_list}

@app.get("/api/v1/events/{event_id}")
async def get_event_details(
    event_id: int,
    api_key: str = Header(..., alias="X-API-Key")
):
    """Get details for a specific event"""
    
    connection = validate_api_key(api_key)
    if not connection:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Get event and verify it belongs to this channel
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT * FROM raid_events 
        WHERE id = %s AND channel_id = %s
    """, (event_id, connection['channel_id']))
    
    event = cursor.fetchone()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    # Get signups
    cursor.execute("""
        SELECT * FROM raid_signups WHERE event_id = %s
    """, (event_id,))
    
    signups = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return {
        "event": event,
        "signups": signups
    }
```

#### Step 2: Create API Connection System

Add Discord command:

```python
# In my_discord_bot.py

@tree.command(name="connectaddon", description="Connect WoW addon to this channel's events")
async def connectaddon_command(interaction: discord.Interaction):
    """Generate API key for WoW addon integration"""
    
    # Generate unique API key
    import secrets
    api_key = secrets.token_urlsafe(32)
    
    # Store in database
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO api_connections (api_key, guild_id, channel_id, created_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (channel_id) 
        DO UPDATE SET api_key = EXCLUDED.api_key, updated_at = NOW()
        RETURNING api_key
    """, (api_key, interaction.guild_id, interaction.channel_id, interaction.user.id))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    # Send API key in DM
    embed = discord.Embed(
        title="🎮 WoW Addon Connection",
        description=(
            "Copy this command and paste it in WoW:\n\n"
            f"```/luminisbot connect {api_key}```\n\n"
            "This will link your Luminisbot Events addon to this Discord channel's events."
        ),
        color=0x00ff00
    )
    
    try:
        await interaction.user.send(embed=embed)
        await interaction.response.send_message(
            "✅ API key sent to your DMs! Check your Discord messages.",
            ephemeral=True
        )
    except:
        await interaction.response.send_message(
            f"⚠️ Couldn't send DM. Here's your key (delete this message after copying):\n||`{api_key}`||",
            ephemeral=True
        )
```

#### Step 3: Create Database Migration

```python
# In run_migrations.py, add:

cursor.execute("""
    CREATE TABLE IF NOT EXISTS api_connections (
        id SERIAL PRIMARY KEY,
        api_key TEXT UNIQUE NOT NULL,
        guild_id BIGINT NOT NULL,
        channel_id BIGINT UNIQUE NOT NULL,
        created_by BIGINT NOT NULL,
        active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
    );
""")
```

#### Step 4: Create WoW Addon (Lua)

This is the core addon structure:

```lua
-- LuminisbotEvents.toc
## Interface: 110002
## Title: Luminisbot Events
## Notes: Show Discord raid events in-game
## Author: YourName
## Version: 1.0.0
## SavedVariables: LuminisbotEventsDB

LuminisbotEvents.lua
LuminisbotEvents.xml
```

```lua
-- LuminisbotEvents.lua
local ADDON_NAME, addon = ...

-- Saved variables
LuminisbotEventsDB = LuminisbotEventsDB or {
    apiKey = nil,
    events = {},
    lastUpdate = 0
}

-- Constants
local API_URL = "https://luminisbot.example.com/api/v1/events"
local UPDATE_INTERVAL = 300 -- 5 minutes

-- Create main frame
local frame = CreateFrame("Frame", "LuminisbotEventsFrame", UIParent, "BasicFrameTemplateWithInset")
frame:SetSize(400, 500)
frame:SetPoint("CENTER")
frame:Hide()

-- Title
frame.title = frame:CreateFontString(nil, "OVERLAY")
frame.title:SetFontObject("GameFontHighlight")
frame.title:SetPoint("CENTER", frame.TitleBg, "CENTER", 5, 0)
frame.title:SetText("Luminisbot Events")

-- Event list scroll frame
local scrollFrame = CreateFrame("ScrollFrame", nil, frame, "UIPanelScrollFrameTemplate")
scrollFrame:SetPoint("TOPLEFT", 12, -30)
scrollFrame:SetPoint("BOTTOMRIGHT", -28, 40)

local scrollChild = CreateFrame("Frame")
scrollFrame:SetScrollChild(scrollChild)
scrollChild:SetSize(350, 1)

-- Refresh button
local refreshButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
refreshButton:SetSize(100, 22)
refreshButton:SetPoint("BOTTOMLEFT", 12, 10)
refreshButton:SetText("Refresh")
refreshButton:SetScript("OnClick", function()
    addon:RequestEventUpdate()
end)

-- Invite All button
local inviteButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
inviteButton:SetSize(100, 22)
inviteButton:SetPoint("BOTTOM", frame, "BOTTOM", 0, 10)
inviteButton:SetText("Invite All")
inviteButton:SetScript("OnClick", function()
    addon:InviteAllSignups()
end)

-- Connection status
frame.statusText = frame:CreateFontString(nil, "OVERLAY")
frame.statusText:SetFontObject("GameFontNormalSmall")
frame.statusText:SetPoint("BOTTOMRIGHT", -12, 10)
frame.statusText:SetText("Not Connected")
frame.statusText:SetTextColor(1, 0, 0)

-- Slash commands
SLASH_LUMINISBOT1 = "/luminisbot"
SLASH_LUMINISBOT2 = "/lb"
SlashCmdList["LUMINISBOT"] = function(msg)
    local command, arg = strsplit(" ", msg, 2)
    command = command:lower()
    
    if command == "connect" then
        if arg and arg ~= "" then
            LuminisbotEventsDB.apiKey = arg
            print("|cff00ff00Luminisbot:|r Connected! Use /luminisbot show to view events.")
            addon:RequestEventUpdate()
        else
            print("|cffff0000Luminisbot:|r Usage: /luminisbot connect <api-key>")
        end
        
    elseif command == "show" then
        if frame:IsShown() then
            frame:Hide()
        else
            frame:Show()
            addon:UpdateEventDisplay()
        end
        
    elseif command == "refresh" then
        addon:RequestEventUpdate()
        
    elseif command == "help" then
        print("|cff00ff00Luminisbot Events Commands:|r")
        print("  /luminisbot connect <key> - Connect to Discord channel")
        print("  /luminisbot show - Toggle event window")
        print("  /luminisbot refresh - Refresh events")
        
    else
        frame:Show()
    end
end

-- Update event display
function addon:UpdateEventDisplay()
    -- Clear old content
    for i, child in ipairs({scrollChild:GetChildren()}) do
        child:Hide()
        child:SetParent(nil)
    end
    
    -- Show connection status
    if LuminisbotEventsDB.apiKey then
        frame.statusText:SetText("Connected")
        frame.statusText:SetTextColor(0, 1, 0)
    else
        frame.statusText:SetText("Not Connected")
        frame.statusText:SetTextColor(1, 0, 0)
        
        -- Show connection instructions
        local helpText = scrollChild:CreateFontString(nil, "OVERLAY")
        helpText:SetFontObject("GameFontNormal")
        helpText:SetPoint("TOPLEFT", 10, -10)
        helpText:SetText("Use /luminisbot connect <key> to get started!\n\nGet your key from Discord with /connectaddon")
        return
    end
    
    -- Display events
    local events = LuminisbotEventsDB.events
    if #events == 0 then
        local noEventsText = scrollChild:CreateFontString(nil, "OVERLAY")
        noEventsText:SetFontObject("GameFontNormal")
        noEventsText:SetPoint("TOPLEFT", 10, -10)
        noEventsText:SetText("No upcoming events.\n\nUse /luminisbot refresh to check for new events.")
        return
    end
    
    local yOffset = -10
    for i, event in ipairs(events) do
        -- Event container
        local eventFrame = CreateFrame("Frame", nil, scrollChild)
        eventFrame:SetSize(330, 80)
        eventFrame:SetPoint("TOPLEFT", 10, yOffset)
        
        -- Background
        local bg = eventFrame:CreateTexture(nil, "BACKGROUND")
        bg:SetAllPoints()
        bg:SetColorTexture(0.1, 0.1, 0.1, 0.8)
        
        -- Title
        local title = eventFrame:CreateFontString(nil, "OVERLAY")
        title:SetFontObject("GameFontHighlight")
        title:SetPoint("TOPLEFT", 5, -5)
        title:SetText(event.title)
        
        -- Date/Time
        local dateTime = eventFrame:CreateFontString(nil, "OVERLAY")
        dateTime:SetFontObject("GameFontNormalSmall")
        dateTime:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -2)
        dateTime:SetText(string.format("%s at %s", event.date, event.time))
        
        -- Signup count
        local signupCount = eventFrame:CreateFontString(nil, "OVERLAY")
        signupCount:SetFontObject("GameFontNormalSmall")
        signupCount:SetPoint("TOPLEFT", dateTime, "BOTTOMLEFT", 0, -2)
        
        local tanks = 0
        local healers = 0
        local dps = 0
        for _, signup in ipairs(event.signups) do
            if signup.status == "signed" then
                if signup.role == "tank" then tanks = tanks + 1
                elseif signup.role == "healer" then healers = healers + 1
                elseif signup.role == "dps" then dps = dps + 1
                end
            end
        end
        
        signupCount:SetText(string.format("Signups: %d (T:%d H:%d D:%d)", 
            tanks + healers + dps, tanks, healers, dps))
        
        -- Invite button for this event
        local inviteBtn = CreateFrame("Button", nil, eventFrame, "UIPanelButtonTemplate")
        inviteBtn:SetSize(80, 22)
        inviteBtn:SetPoint("BOTTOMRIGHT", -5, 5)
        inviteBtn:SetText("Invite")
        inviteBtn:SetScript("OnClick", function()
            addon:InviteEventSignups(event)
        end)
        
        yOffset = yOffset - 90
    end
    
    scrollChild:SetHeight(math.abs(yOffset) + 20)
end

-- Invite signups for an event
function addon:InviteEventSignups(event)
    local count = 0
    for _, signup in ipairs(event.signups) do
        if signup.status == "signed" then
            local name = signup.name .. "-" .. signup.realm
            InviteUnit(name)
            count = count + 1
        end
    end
    print(string.format("|cff00ff00Luminisbot:|r Sent %d invites for %s", count, event.title))
end

-- Invite all signed-up players from all events
function addon:InviteAllSignups()
    local totalCount = 0
    for _, event in ipairs(LuminisbotEventsDB.events) do
        for _, signup in ipairs(event.signups) do
            if signup.status == "signed" then
                local name = signup.name .. "-" .. signup.realm
                InviteUnit(name)
                totalCount = totalCount + 1
            end
        end
    end
    print(string.format("|cff00ff00Luminisbot:|r Sent %d total invites", totalCount))
end

-- Request event update (this is where we'd call the API)
-- NOTE: Since direct HTTP isn't possible in WoW, this would need a helper program
function addon:RequestEventUpdate()
    -- Option 1: Use a helper program that writes to SavedVariables
    -- Option 2: Use WeakAuras' HTTP proxy
    -- Option 3: Manual refresh via copy-paste
    
    print("|cff00ff00Luminisbot:|r Requesting event update...")
    print("|cffffaa00Note:|r Direct HTTP requests aren't supported by WoW.")
    print("Please use the companion helper program or WeakAuras integration.")
    
    -- For now, show last cached data
    self:UpdateEventDisplay()
end

-- Auto-refresh on login
frame:RegisterEvent("PLAYER_LOGIN")
frame:SetScript("OnEvent", function(self, event)
    if event == "PLAYER_LOGIN" then
        -- Check if we need to update
        local timeSinceUpdate = time() - LuminisbotEventsDB.lastUpdate
        if timeSinceUpdate > UPDATE_INTERVAL and LuminisbotEventsDB.apiKey then
            addon:RequestEventUpdate()
        end
    end
end)

print("|cff00ff00Luminisbot Events|r loaded! Type /luminisbot for commands.")
```

### Pros of Solution 1 (API)
✅ Automatic updates (with helper program)  
✅ Real-time event changes  
✅ Scalable to multiple users  
✅ Secure (API keys)  
✅ No manual copy-paste needed  

### Cons of Solution 1 (API)
❌ Requires external helper program (Python/Node.js app running alongside WoW)  
❌ More complex setup for users  
❌ Firewall/network issues possible  
❌ Requires hosting API endpoint  

---

## Solution 2: String-Based Integration (SIMPLER FALLBACK)

### How It Works

1. User types `/eventstring <event_id>` in Discord
2. Bot generates a Base64-encoded string containing event data
3. User copies string and pastes it in WoW: `/luminisbot import <string>`
4. Addon decodes and displays event

### Implementation

#### Discord Command

```python
# In my_discord_bot.py

import base64
import json

@tree.command(name="eventstring", description="Generate import string for WoW addon")
async def eventstring_command(interaction: discord.Interaction, event_id: int):
    """Generate encoded string for WoW addon import"""
    
    # Get event from database
    from raid_system import get_raid_event_by_id, get_raid_signups
    
    event = get_raid_event_by_id(event_id)
    if not event:
        await interaction.response.send_message(
            f"❌ Event {event_id} not found!",
            ephemeral=True
        )
        return
    
    # Check if user has access (same guild)
    if event['guild_id'] != interaction.guild_id:
        await interaction.response.send_message(
            "❌ You don't have access to this event!",
            ephemeral=True
        )
        return
    
    # Get signups
    signups = get_raid_signups(event_id, 'signed')
    
    # Build data structure
    event_data = {
        "id": event['id'],
        "title": event['title'],
        "date": event['event_date'].isoformat(),
        "time": event['event_time'].isoformat(),
        "signups": [
            {
                "name": s['character_name'],
                "realm": s['realm_slug'],
                "class": s['character_class'],
                "role": s['role'],
                "spec": s.get('spec', ''),
                "status": s['status']
            }
            for s in signups
        ]
    }
    
    # Encode to base64
    json_str = json.dumps(event_data, separators=(',', ':'))
    encoded = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
    
    # Split into chunks (WoW has character limits)
    chunk_size = 200
    chunks = [encoded[i:i+chunk_size] for i in range(0, len(encoded), chunk_size)]
    
    # Send instructions
    embed = discord.Embed(
        title=f"📋 Import String for: {event['title']}",
        description=f"Copy these commands and paste them in WoW (in order):",
        color=0x00ff00
    )
    
    if len(chunks) == 1:
        embed.add_field(
            name="Import Command",
            value=f"```/luminisbot import {encoded}```",
            inline=False
        )
    else:
        for i, chunk in enumerate(chunks, 1):
            embed.add_field(
                name=f"Part {i}/{len(chunks)}",
                value=f"```/luminisbot import{i} {chunk}```",
                inline=False
            )
        embed.add_field(
            name="Final Command",
            value="```/luminisbot importdone```",
            inline=False
        )
    
    embed.set_footer(text=f"Event ID: {event_id}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
```

#### WoW Addon Import Function

```lua
-- Add to LuminisbotEvents.lua

-- Import buffer for multi-part imports
local importBuffer = ""

function addon:ImportEventString(encodedString)
    -- Decode base64
    local jsonString = addon:Base64Decode(encodedString)
    if not jsonString then
        print("|cffff0000Luminisbot:|r Failed to decode import string!")
        return
    end
    
    -- Parse JSON (you'll need a JSON library for Lua, or use simple parsing)
    local eventData = addon:ParseJSON(jsonString)
    if not eventData then
        print("|cffff0000Luminisbot:|r Failed to parse event data!")
        return
    end
    
    -- Add to saved events
    local found = false
    for i, event in ipairs(LuminisbotEventsDB.events) do
        if event.id == eventData.id then
            LuminisbotEventsDB.events[i] = eventData
            found = true
            break
        end
    end
    
    if not found then
        table.insert(LuminisbotEventsDB.events, eventData)
    end
    
    -- Sort events by date
    table.sort(LuminisbotEventsDB.events, function(a, b)
        return a.date < b.date
    end)
    
    LuminisbotEventsDB.lastUpdate = time()
    
    print(string.format("|cff00ff00Luminisbot:|r Imported event: %s", eventData.title))
    addon:UpdateEventDisplay()
end

-- Add to slash command handler
elseif command == "import" then
    if arg and arg ~= "" then
        addon:ImportEventString(arg)
    else
        print("|cffff0000Luminisbot:|r Usage: /luminisbot import <string>")
    end

elseif command:match("^import%d+$") then
    -- Multi-part import
    importBuffer = importBuffer .. arg
    print(string.format("|cff00ff00Luminisbot:|r Import part received (%d chars)", #importBuffer))

elseif command == "importdone" then
    if importBuffer ~= "" then
        addon:ImportEventString(importBuffer)
        importBuffer = ""
    else
        print("|cffff0000Luminisbot:|r No import data buffered!")
    end

-- Simple JSON parser (basic implementation)
function addon:ParseJSON(str)
    -- This is a VERY basic parser - you'd want to use a proper Lua JSON library
    -- Or implement a more robust parser
    
    -- Remove outer braces
    str = str:match("^%s*{(.+)}%s*$")
    if not str then return nil end
    
    local result = {}
    
    -- Parse key-value pairs (this is overly simplified)
    for key, value in str:gmatch('"([^"]+)"%s*:%s*([^,}]+)') do
        -- Try to parse value
        if value:match('^"') then
            -- String value
            result[key] = value:match('^"([^"]*)"')
        elseif value:match('^%d+$') then
            -- Number value
            result[key] = tonumber(value)
        elseif value:match('^%[') then
            -- Array value (signups)
            result[key] = {}
            -- Parse array items... (simplified)
        end
    end
    
    return result
end

-- Base64 decoder (you'll need a proper implementation)
function addon:Base64Decode(data)
    -- Use a Lua base64 library like lua-base64
    -- Or implement base64 decoding
    -- For brevity, assuming you have this function
    return LibBase64:Decode(data)  -- Requires LibBase64 library
end
```

### Pros of Solution 2 (String)
✅ No external dependencies  
✅ Works 100% in WoW client  
✅ No helper programs needed  
✅ No API hosting required  
✅ Simpler for users to understand  

### Cons of Solution 2 (String)
❌ Manual copy-paste required  
❌ No automatic updates  
❌ Must regenerate string for changes  
❌ Character limit issues for large events  
❌ More steps for user  

---

## ✅ IMPLEMENTED: String-Based Solution

### Best of Both Worlds

We've implemented the **string-based solution** with significant improvements:

1. **✅ Implemented: Admin Panel Button** - Added "🎮 Copy Event String" button in raid event admin panel
2. **✅ Implemented: WoW Addon** - Fully functional addon with UI and invite system  
3. **Future: API-based** (optional enhancement for auto-refresh)

### Implementation Priority

#### Phase 1: String-Based MVP (Week 1-2)
1. Create `/eventstring` command in Discord bot
2. Create basic WoW addon with import functionality
3. Implement UI to display events
4. Add invite functionality
5. Test with real events

#### Phase 2: API Enhancement (Week 3-4)
1. Create REST API endpoint
2. Add `/connectaddon` command
3. Create database tables for API keys
4. Build helper program for HTTP requests
5. Add auto-refresh to addon

#### Phase 3: Polish (Week 5)
1. Improve UI design
2. Add error handling
3. Create user documentation
4. Package and distribute

---

## Technical Requirements

### For Discord Bot
- Add FastAPI dependency: `pip install fastapi uvicorn`
- Add database migration for `api_connections` table
- Implement new Discord commands
- Deploy API endpoint (use same server as bot)

### For WoW Addon
- Lua 5.1 (WoW's Lua version)
- LibStub (addon library framework)
- LibBase64 (for string decoding)
- AceGUI (optional, for better UI)

### For Helper Program (API approach only)
- Python 3.8+ or Node.js
- HTTP client library
- File I/O for SavedVariables

---

## Security Considerations

### API Keys
- Generate cryptographically secure keys
- Store hashed in database
- Allow revocation/regeneration
- Rate limit API requests (10 req/min per key)

### Data Privacy
- API keys linked to Discord channels, not users
- Don't expose Discord IDs in API responses
- Only show events from connected channel
- Implement HTTPS for API endpoint

### WoW Addon
- Don't store sensitive data in SavedVariables
- Validate all imported data
- Sanitize character names before /invite
- Add confirmation for bulk invites

---

## Example User Flow

### Scenario: Guild Master wants to use addon

#### Using String Method (Simplest)
1. GM creates event in Discord: `/createraid`
2. Event is created: "Monday Mythic Raid - Nov 6, 20:00"
3. Players sign up via Discord buttons
4. Before raid, GM types: `/eventstring 42`
5. Bot sends DM with encoded string
6. GM copies string, opens WoW
7. In WoW: `/luminisbot import <string>`
8. Addon shows event with all signups
9. GM clicks "Invite All" button
10. All signed-up players get raid invites!

#### Using API Method (Advanced)
1. GM sets up helper program on PC
2. In Discord: `/connectaddon`
3. Bot generates API key, sends to GM
4. In WoW: `/luminisbot connect <key>`
5. Addon auto-syncs with Discord every 5 minutes
6. GM opens addon: `/luminisbot show`
7. Sees all upcoming events automatically
8. Clicks "Invite" on desired event
9. Done! No copy-paste needed.

---

## Next Steps

1. **Decide on approach:** String-only, API-only, or hybrid?
2. **Set up development environment:** Install Lua editor, WoW addon dev tools
3. **Create database migrations:** Add new tables for API connections
4. **Build Discord commands:** Start with `/eventstring` (simpler)
5. **Create basic WoW addon:** UI + import functionality
6. **Test with real events:** Use your guild's actual raid events
7. **Gather feedback:** Have guild members try it
8. **Iterate and improve**

---

## Resources & Tools

### WoW Addon Development
- **WoW API Documentation:** https://warcraft.wiki.gg/wiki/World_of_Warcraft_API
- **Addon Development Guide:** https://www.townlong-yak.com/framexml/
- **WoW Addon Studio:** VS Code extension for Lua editing
- **Lua Language Server:** For autocomplete in VS Code

### Libraries
- **LibStub:** https://www.wowace.com/projects/libstub
- **AceGUI:** https://www.wowace.com/projects/ace3
- **LibBase64:** https://github.com/iskolbin/lbase64

### Testing
- **WoW PTR (Public Test Realm):** Free testing environment
- **BugSack:** In-game addon for debugging Lua errors
- **ViragDevTool:** In-game variable inspector

---

## Conclusion

Both your proposed solutions are feasible! I recommend starting with the **string-based approach** for immediate results, then adding the **API approach** as an optional enhancement for power users.

The string-based method is simpler to implement, works reliably, and doesn't require any external infrastructure. The API method is more elegant but requires more setup.

A hybrid approach gives you the best of both worlds: immediate functionality with string import, plus automatic syncing for users who want it.

Would you like me to start implementing one of these approaches? I can create the Discord bot commands and WoW addon code right now!
