-- Luminisbot Events - Core Logic
-- Handles data import, storage, and business logic

local ADDON_NAME, addon = ...

-- Initialize addon namespace
addon.version = "1.0.0"
addon.events = {}

-- Make addon globally accessible
_G.LuminisbotEvents = addon

-- Saved variables (persisted between sessions)
LuminisbotEventsDB = LuminisbotEventsDB or {
    events = {},
    lastUpdate = 0,
    settings = {
        showTooltips = true,
        sortByDate = true
    }
}

-- Import buffer for multi-part imports
local importBuffer = ""
local importPartCount = 0

-- Track last known update time for auto-refresh
local lastKnownUpdate = 0

-- ============================================================================
-- TIME FORMATTING UTILITIES
-- ============================================================================

-- Format timestamp as "X minutes ago" or actual time
function addon:FormatTimeAgo(timestamp)
    if not timestamp or timestamp == 0 then
        return "Never"
    end
    
    local currentTime = time()
    local diff = currentTime - timestamp
    
    if diff < 60 then
        return "Just now"
    elseif diff < 3600 then
        local mins = math.floor(diff / 60)
        return mins .. " minute" .. (mins ~= 1 and "s" or "") .. " ago"
    elseif diff < 86400 then
        local hours = math.floor(diff / 3600)
        return hours .. " hour" .. (hours ~= 1 and "s" or "") .. " ago"
    else
        -- Show actual date/time for older timestamps
        return date("%b %d, %H:%M", timestamp)
    end
end

-- Format timestamp as readable date/time
function addon:FormatDateTime(timestamp)
    if not timestamp or timestamp == 0 then
        return "Unknown"
    end
    return date("%b %d, %Y at %H:%M", timestamp)
end

-- ============================================================================
-- BASE64 DECODER
-- ============================================================================

-- Base64 decoding lookup table
local b64chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
local b64lookup = {}
for i = 1, #b64chars do
    b64lookup[string.byte(b64chars, i)] = i - 1
end

function addon:Base64Decode(data)
    data = string.gsub(data, '[^'..b64chars..'=]', '')
    return (data:gsub('.', function(x)
        if (x == '=') then return '' end
        local r,f='',(b64lookup[x:byte()] or 0)
        for i=6,1,-1 do r=r..(f%2^i-f%2^(i-1)>0 and '1' or '0') end
        return r;
    end):gsub('%d%d%d?%d?%d?%d?%d?%d?', function(x)
        if (#x ~= 8) then return '' end
        local c=0
        for i=1,8 do c=c+(x:sub(i,i)=='1' and 2^(8-i) or 0) end
        return string.char(c)
    end))
end

-- ============================================================================
-- JSON PARSER (Simple)
-- ============================================================================

-- Escape special characters in strings
local function json_unescape(str)
    return str:gsub('\\(.)', {
        ['"'] = '"',
        ['\\'] = '\\',
        ['/'] = '/',
        ['b'] = '\b',
        ['f'] = '\f',
        ['n'] = '\n',
        ['r'] = '\r',
        ['t'] = '\t'
    })
end

-- Parse a JSON string (improved recursive parser)
function addon:ParseJSON(str)
    if not str or str == "" then return nil end
    
    -- Parse value at position, returns value and next position
    local function parseValue(s, pos)
        pos = pos or 1
        
        -- Skip whitespace
        while pos <= #s and s:sub(pos, pos):match("%s") do
            pos = pos + 1
        end
        
        if pos > #s then return nil, pos end
        
        local char = s:sub(pos, pos)
        
        -- null
        if s:sub(pos, pos+3) == "null" then
            return nil, pos + 4
        end
        
        -- true
        if s:sub(pos, pos+3) == "true" then
            return true, pos + 4
        end
        
        -- false
        if s:sub(pos, pos+4) == "false" then
            return false, pos + 5
        end
        
        -- number
        if char == "-" or char:match("%d") then
            local numStr = s:match("^%-?%d+%.?%d*[eE]?[%+%-]?%d*", pos)
            if numStr then
                return tonumber(numStr), pos + #numStr
            end
        end
        
        -- string
        if char == '"' then
            local endPos = pos + 1
            while endPos <= #s do
                if s:sub(endPos, endPos) == '"' and s:sub(endPos-1, endPos-1) ~= '\\' then
                    local str = s:sub(pos+1, endPos-1)
                    -- Unescape common sequences
                    str = str:gsub('\\n', '\n')
                    str = str:gsub('\\t', '\t')
                    str = str:gsub('\\r', '\r')
                    str = str:gsub('\\"', '"')
                    str = str:gsub('\\\\', '\\')
                    -- Handle unicode escapes (convert to UTF-8)
                    str = str:gsub('\\u(%x%x%x%x)', function(hex)
                        local codepoint = tonumber(hex, 16)
                        if codepoint < 0x80 then
                            return string.char(codepoint)
                        elseif codepoint < 0x800 then
                            return string.char(
                                0xC0 + math.floor(codepoint / 0x40),
                                0x80 + (codepoint % 0x40)
                            )
                        else
                            return string.char(
                                0xE0 + math.floor(codepoint / 0x1000),
                                0x80 + (math.floor(codepoint / 0x40) % 0x40),
                                0x80 + (codepoint % 0x40)
                            )
                        end
                    end)
                    return str, endPos + 1
                end
                endPos = endPos + 1
            end
            return nil, pos
        end
        
        -- array
        if char == '[' then
            local arr = {}
            pos = pos + 1
            
            -- Skip whitespace
            while pos <= #s and s:sub(pos, pos):match("%s") do
                pos = pos + 1
            end
            
            -- Empty array
            if s:sub(pos, pos) == ']' then
                return arr, pos + 1
            end
            
            while pos <= #s do
                local val
                val, pos = parseValue(s, pos)
                table.insert(arr, val)
                
                -- Skip whitespace
                while pos <= #s and s:sub(pos, pos):match("%s") do
                    pos = pos + 1
                end
                
                local nextChar = s:sub(pos, pos)
                if nextChar == ']' then
                    return arr, pos + 1
                elseif nextChar == ',' then
                    pos = pos + 1
                else
                    return nil, pos
                end
            end
            return nil, pos
        end
        
        -- object
        if char == '{' then
            local obj = {}
            pos = pos + 1
            
            -- Skip whitespace
            while pos <= #s and s:sub(pos, pos):match("%s") do
                pos = pos + 1
            end
            
            -- Empty object
            if s:sub(pos, pos) == '}' then
                return obj, pos + 1
            end
            
            while pos <= #s do
                -- Parse key
                local key
                key, pos = parseValue(s, pos)
                
                if type(key) ~= "string" then
                    return nil, pos
                end
                
                -- Skip whitespace and colon
                while pos <= #s and s:sub(pos, pos):match("%s") do
                    pos = pos + 1
                end
                
                if s:sub(pos, pos) ~= ':' then
                    return nil, pos
                end
                pos = pos + 1
                
                -- Parse value
                local val
                val, pos = parseValue(s, pos)
                obj[key] = val
                
                -- Skip whitespace
                while pos <= #s and s:sub(pos, pos):match("%s") do
                    pos = pos + 1
                end
                
                local nextChar = s:sub(pos, pos)
                if nextChar == '}' then
                    return obj, pos + 1
                elseif nextChar == ',' then
                    pos = pos + 1
                else
                    return nil, pos
                end
            end
            return nil, pos
        end
        
        return nil, pos
    end
    
    local result, _ = parseValue(str, 1)
    return result
end

-- ============================================================================
-- EVENT IMPORT
-- ============================================================================

function addon:ImportEventString(encodedString)
    -- Clean up the string
    encodedString = encodedString:gsub("^%s*", ""):gsub("%s*$", "")
    
    addon:Print("Import string length: " .. #encodedString .. " chars")
    
    -- Decode base64
    local jsonString = self:Base64Decode(encodedString)
    if not jsonString or jsonString == "" then
        self:PrintError("Failed to decode import string! Make sure you copied the entire command.")
        return false
    end
    
    -- Debug: Show decoded JSON info
    addon:Print("Decoded JSON length: " .. #jsonString .. " chars")
    addon:Print("First 100 chars: " .. jsonString:sub(1, 100))
    addon:Print("Last 50 chars: " .. jsonString:sub(-50))
    
    -- Parse JSON
    local eventData = self:ParseJSON(jsonString)
    if not eventData or type(eventData) ~= "table" then
        self:PrintError("Failed to parse event data! The import string may be corrupted.")
        self:PrintError("JSON was " .. #jsonString .. " chars long")
        return false
    end
    
    addon:Print("Parsed event data successfully!")
    addon:Print("Event ID: " .. tostring(eventData.id))
    addon:Print("Event title: " .. tostring(eventData.title))
    addon:Print("Signups count: " .. (eventData.signups and #eventData.signups or 0))
    
    -- Validate event data
    if not eventData.id or not eventData.title then
        self:PrintError("Invalid event data! Missing required fields.")
        return false
    end
    
    -- Add/update event in saved variables
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
        if a.date == b.date then
            return (a.time or "00:00:00") < (b.time or "00:00:00")
        end
        return a.date < b.date
    end)
    
    LuminisbotEventsDB.lastUpdate = time()
    
    -- Count signups
    local signupCount = 0
    if eventData.signups then
        for _, signup in ipairs(eventData.signups) do
            if signup.status == "signed" then
                signupCount = signupCount + 1
            end
        end
    end
    
    self:Print(string.format("✓ Imported event: |cff00ff00%s|r (%d signups)", eventData.title, signupCount))
    
    -- Refresh UI if open
    if addon.mainFrame and addon.mainFrame:IsShown() then
        addon:RefreshUI()
    end
    
    return true
end

-- ============================================================================
-- EVENT MANAGEMENT
-- ============================================================================

function addon:GetEvents()
    return LuminisbotEventsDB.events or {}
end

function addon:GetEvent(eventId)
    for _, event in ipairs(LuminisbotEventsDB.events) do
        if event.id == eventId then
            return event
        end
    end
    return nil
end

function addon:DeleteEvent(eventId)
    for i, event in ipairs(LuminisbotEventsDB.events) do
        if event.id == eventId then
            table.remove(LuminisbotEventsDB.events, i)
            self:Print(string.format("Deleted event: %s", event.title))
            return true
        end
    end
    return false
end

-- ============================================================================
-- COMMAND QUEUE (for two-way sync with companion app)
-- ============================================================================

function addon:QueueCommand(commandType, eventId, data)
    -- Initialize if needed
    if not LuminisbotCommands then
        LuminisbotCommands = {queue = {}, lastCommandId = 0}
    end
    
    -- Generate unique command ID
    LuminisbotCommands.lastCommandId = (LuminisbotCommands.lastCommandId or 0) + 1
    
    -- Add command to queue
    local command = {
        id = LuminisbotCommands.lastCommandId,
        type = commandType,
        eventId = eventId,
        timestamp = time(),
        data = data or {}
    }
    
    table.insert(LuminisbotCommands.queue, command)
    
    self:Print(string.format("|cff00ff00Command queued: %s|r", commandType))
    self:Print("|cffffff00Companion app will process it on next sync|r")
    
    return command.id
end

function addon:IsCompanionActive()
    -- Check if companion app is running by checking heartbeat age
    if LuminisbotCompanionData and LuminisbotCompanionData.companionHeartbeat then
        local heartbeatAge = time() - LuminisbotCompanionData.companionHeartbeat
        return heartbeatAge < 120  -- Active if heartbeat less than 2 minutes old
    end
    return false
end

function addon:IsEventOwner(event)
    -- Check if current player is the owner of the event
    if not event or not event.owner_character then
        return false
    end
    
    local playerName = UnitName("player")
    return playerName and playerName == event.owner_character
end

function addon:ChangeSignupStatus(eventId, status)
    -- Check if companion app is active
    if not self:IsCompanionActive() then
        self:Print("|cffff0000Status changes require the Companion App to be running!|r")
        self:Print("|cffffff00Download it from CurseForge or use /lb import to sync manually|r")
        return
    end
    
    -- Prevent players from benching themselves
    if status == "benched" then
        self:Print("|cffff0000You cannot bench yourself! Contact the event organizer if needed.|r")
        return
    end
    
    -- Get player's character name and realm
    local playerName = UnitName("player")
    local realmName = GetRealmName()
    
    -- Queue the command
    self:QueueCommand("change_status", eventId, {
        character = playerName,
        realm = realmName,
        status = status
    })
end

function addon:ParseSubscriptionString(subString)
    -- Decode Base64
    local decoded = self:Base64Decode(subString)
    if not decoded then
        self:PrintError("Invalid subscription string format!")
        return
    end
    
    -- Parse guild_id:api_key format
    local guildId, apiKey = decoded:match("^(%d+):(.+)$")
    if not guildId or not apiKey then
        self:PrintError("Invalid subscription format! Expected guild_id:api_key")
        return
    end
    
    -- Save to database
    LuminisbotEventsDB.guildId = guildId
    LuminisbotEventsDB.apiKey = apiKey
    
    self:Print("[OK] Subscription saved successfully!")
    self:Print("Server ID: " .. guildId)
    self:Print("Syncing events...")
    
    -- Refresh settings tab
    self:RefreshSettingsTab()
    
    -- Auto-sync
    self:SyncEvents()
end

function addon:SyncEvents()
    if not LuminisbotEventsDB.guildId or LuminisbotEventsDB.guildId == "" then
        self:PrintError("No subscription configured!")
        self:PrintError("Go to Settings tab and enter your subscription string")
        self:PrintError("Get it from Discord with /subscribe command")
        return
    end
    
    if not LuminisbotEventsDB.apiKey or LuminisbotEventsDB.apiKey == "" then
        self:PrintError("No API key found!")
        self:PrintError("Please re-subscribe using /subscribe in Discord")
        return
    end
    
    -- Create sync command for Discord
    local syncCommand = "/syncevents"
    
    -- Show instructions
    self:Print("|cff00ff00=== Quick Sync Instructions ===|r")
    self:Print("1. Type |cff00ff00/syncevents|r in any Discord channel")
    self:Print("2. Bot will DM you an import string")
    self:Print("3. Copy the string from Discord")
    self:Print("4. Paste it into the Import tab here")
    self:Print("|cff00ff00==============================|r")
    self:Print("TIP: Create a private Discord channel for easy syncing!")
end

function addon:ImportFromAPI(jsonData)
    -- Import events from API response (called by WeakAura)
    local parsed
    
    if type(jsonData) == "string" then
        -- Parse JSON string
        parsed = self:ParseJSON(jsonData)
    elseif type(jsonData) == "table" then
        parsed = jsonData
    else
        self:PrintError("Invalid API data format")
        return
    end
    
    if not parsed or not parsed.events then
        self:PrintError("Invalid API response format")
        return
    end
    
    -- Import the events
    local events = parsed.events
    if type(events) == "table" then
        LuminisbotEventsDB.events = events
        LuminisbotEventsDB.lastUpdate = date("%Y-%m-%d %H:%M:%S")
        
        self:Print(string.format("|cff00ff00[OK] Auto-synced %d event(s)|r", #events))
        
        -- Refresh UI if it's open
        if self.mainFrame and self.mainFrame:IsShown() then
            self:RefreshUI()
        end
    end
end

function addon:ClearOldEvents()
    local today = date("%Y-%m-%d")
    local removed = 0
    
    for i = #LuminisbotEventsDB.events, 1, -1 do
        local event = LuminisbotEventsDB.events[i]
        if event.date < today then
            table.remove(LuminisbotEventsDB.events, i)
            removed = removed + 1
        end
    end
    
    if removed > 0 then
        self:Print(string.format("Removed %d old event(s)", removed))
    end
    
    return removed
end

-- ============================================================================
-- INVITE FUNCTIONALITY
-- ============================================================================

function addon:InviteEventSignups(event)
    if not event or not event.signups then
        self:PrintError("No signups found for this event!")
        return
    end
    
    -- Only allow event owner to invite all
    if not self:IsEventOwner(event) then
        self:Print("|cffff0000Only the event owner can use Invite All!|r")
        return
    end
    
    local invited = 0
    local failed = 0
    
    for _, signup in ipairs(event.signups) do
        if signup.status == "signed" then
            local playerName = signup.name
            
            -- Add realm if present
            if signup.realm and signup.realm ~= "" then
                -- Format realm name for WoW (remove spaces and hyphens)
                local realmFormatted = signup.realm:gsub(" ", ""):gsub("%-", "")
                playerName = playerName .. "-" .. realmFormatted
            end
            
            -- Attempt invite
            C_PartyInfo.InviteUnit(playerName)
            invited = invited + 1
        end
    end
    
    if invited > 0 then
        self:Print(string.format("Sent %d invite(s) for: |cff00ff00%s|r", invited, event.title))
    else
        self:PrintWarning("No signed-up players to invite!")
    end
end

-- ============================================================================
-- SLASH COMMAND HANDLER
-- ============================================================================

-- Slash commands will be registered in PLAYER_LOGIN event
local function RegisterSlashCommands()
    SLASH_LUMINISBOT1 = "/luminisbot"
    SLASH_LUMINISBOT2 = "/lb"
    SlashCmdList["LUMINISBOT"] = function(msg)
        local command, arg = strsplit(" ", msg, 2)
        command = (command or ""):lower()
        
        if command == "" or command == "show" then
            if addon.ToggleUI then
                addon:ToggleUI()
            else
                addon:PrintError("UI not loaded yet! Try /reload and try again.")
            end
        
    elseif command == "import" then
        if arg and arg ~= "" then
            -- Clean up the string (remove extra spaces)
            arg = arg:gsub("^%s*", ""):gsub("%s*$", "")
            addon:ImportEventString(arg)
        else
            addon:PrintError("Usage: /luminisbot import <string>")
        end
        
    elseif command:match("^import%d+$") then
        -- Multi-part import
        if not arg or arg == "" then
            addon:PrintError("Missing import data!")
            return
        end
        
        local partNum = tonumber(command:match("%d+"))
        arg = arg:gsub("^%s*", ""):gsub("%s*$", "")
        importBuffer = importBuffer .. arg
        importPartCount = math.max(importPartCount, partNum)
        
        addon:Print(string.format("Import part %d received (%d chars total)", partNum, #importBuffer))
        
    elseif command == "importdone" then
        if importBuffer == "" then
            addon:PrintError("No import data buffered! Use /luminisbot import1, import2, etc. first.")
            return
        end
        
        addon:Print(string.format("Processing %d-part import (%d chars)...", importPartCount, #importBuffer))
        
        if addon:ImportEventString(importBuffer) then
            importBuffer = ""
            importPartCount = 0
        end
        
    elseif command == "clear" then
        addon:ClearOldEvents()
        
    elseif command == "reset" then
        -- Complete reset - wipe all saved data
        LuminisbotEventsDB = {
            events = {},
            lastUpdate = 0,
            guildId = nil,
            apiKey = nil,
            autoSync = false
        }
        addon.events = {}
        addon:Print("All saved data has been reset!")
        if addon.mainFrame then
            addon:RefreshUI()
            addon:RefreshSettingsTab()
        end
        
    elseif command == "list" then
        local events = addon:GetEvents()
        if #events == 0 then
            addon:Print("No events imported yet!")
        else
            addon:Print(string.format("Imported events (%d):", #events))
            for i, event in ipairs(events) do
                addon:Print(string.format("  %d. %s (%s)", i, event.title, event.date))
            end
        end
        
    elseif command == "help" then
        addon:Print("Available commands:")
        addon:Print("  /luminisbot (or /lb) - Open event window")
        addon:Print("  /luminisbot show - Open event window")
        addon:Print("  /luminisbot import <string> - Import event (for small events)")
        addon:Print("  /luminisbot list - List all imported events")
        addon:Print("  /luminisbot clear - Remove past events")
        addon:Print("  /luminisbot reset - Wipe ALL saved data (fresh start)")
        addon:Print("  /luminisbot help - Show this help")
        addon:Print(" ")
        addon:Print("To import: Click 'Copy Event String' in Discord,")
        addon:Print("copy the string from the modal, open the addon UI")
        addon:Print("with /luminisbot, paste in the import box, and click Import.")
        
    else
        -- Default: toggle UI
        if addon.ToggleUI then
            addon:ToggleUI()
        else
            addon:PrintError("UI not loaded yet! Try /reload and try again.")
        end
    end
end
end

-- ============================================================================
-- PRINT HELPERS
-- ============================================================================

function addon:Print(msg)
    print("|cff00ff00Luminisbot:|r " .. msg)
end

function addon:PrintError(msg)
    print("|cffff0000Luminisbot:|r " .. msg)
end

function addon:PrintWarning(msg)
    print("|cffffff00Luminisbot:|r " .. msg)
end

-- ============================================================================
-- INITIALIZATION
-- ============================================================================

local frame = CreateFrame("Frame")
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")

frame:SetScript("OnEvent", function(self, event, arg1)
    if event == "ADDON_LOADED" and arg1 == ADDON_NAME then
        -- Initialize SavedVariables
        if not LuminisbotEventsDB then
            LuminisbotEventsDB = {}
        end
        if not LuminisbotEventsDB.events then
            LuminisbotEventsDB.events = {}
        end
        if not LuminisbotEventsDB.lastUpdate then
            LuminisbotEventsDB.lastUpdate = 0
        end
        if not LuminisbotEventsDB.guildId then
            LuminisbotEventsDB.guildId = ""
        end
        if not LuminisbotEventsDB.apiKey then
            LuminisbotEventsDB.apiKey = ""
        end
        if not LuminisbotEventsDB.autoSync then
            LuminisbotEventsDB.autoSync = false
        end
        if not LuminisbotEventsDB.minimapAngle then
            LuminisbotEventsDB.minimapAngle = 225  -- Default position (bottom-left)
        end
        
        -- Addon loaded - register slash commands
        RegisterSlashCommands()
        
        -- Create minimap button
        addon:CreateMinimapButton()
        
        -- Start companion app detection
        addon:StartCompanionDetection()
        
        -- Print to chat so user knows addon loaded
        print(" ")
        print("|cff00ff00===========================================|r")
        print("|cff00ff00Luminisbot Events v" .. addon.version .. " loaded!|r")
        print("|cffffffffType |cff00ff00/luminisbot|r or |cff00ff00/lb|r to get started|r")
        print("|cffffffffOr click the minimap button!|r")
        print("|cff00ff00===========================================|r")
        print(" ")
        
    elseif event == "PLAYER_LOGIN" then
        -- Player logged in - check for updates
        local events = addon:GetEvents()
        if #events > 0 then
            addon:Print(string.format("%d event(s) loaded. Type |cff00ff00/lb show|r to view.", #events))
        else
            addon:Print("No events yet. Import from Discord with |cff00ff00/lb import|r")
        end
        
        -- Start companion app sync detection
        addon:StartCompanionDetection()
        
        -- Reopen window if it was open before reload
        if LuminisbotEventsDB.wasOpen then
            LuminisbotEventsDB.wasOpen = false
            -- Use C_Timer to delay slightly so UI is fully loaded
            C_Timer.After(0.1, function()
                addon:ShowUI()
            end)
        end
    end
end)

-- ============================================================================
-- COMPANION APP INTEGRATION
-- ============================================================================

-- Track last known update time
addon.lastKnownUpdate = LuminisbotEventsDB.lastUpdate or 0

function addon:LoadCompanionData()
    -- WoW can't reload .lua files at runtime, so this just checks the already-loaded data
    -- Users need to /reload to see updates from the companion app
    -- However, when they click Refresh, we can update the UI from SavedVariables
    
    -- Check if SavedVariables has newer data than we're currently showing
    if LuminisbotEventsDB.lastUpdate and 
       LuminisbotEventsDB.lastUpdate > (self.lastKnownUpdate or 0) then
        
        self.lastKnownUpdate = LuminisbotEventsDB.lastUpdate
        
        local eventCount = 0
        for _ in pairs(LuminisbotEventsDB.events or {}) do
            eventCount = eventCount + 1
        end
        
        if eventCount > 0 then
            addon:Print(string.format("|cff00ff00[OK] Loaded %d event(s)|r", eventCount))
        end
        
        return true
    end
    
    -- Also inform user if they need to /reload to see new data
    if LuminisbotCompanionData and LuminisbotCompanionData.companionHeartbeat then
        local heartbeatAge = time() - LuminisbotCompanionData.companionHeartbeat
        if heartbeatAge < 120 then
            -- Companion is active
            addon:Print("|cffff9900[!] Companion app is running. Type |r|cff00ff00/reload|r|cffff9900 to load new events.|r")
        end
    end
    
    return false
end

function addon:StartCompanionDetection()
    -- On addon load/reload, check if CompanionData has newer data
    if LuminisbotCompanionData and LuminisbotCompanionData.lastUpdate then
        local companionUpdate = LuminisbotCompanionData.lastUpdate
        local dbUpdate = LuminisbotEventsDB.lastUpdate or 0
        
        -- Debug output
        addon:Print(string.format("|cffcccccc[DEBUG] CompanionData timestamp: %s|r", tostring(companionUpdate)))
        addon:Print(string.format("|cffcccccc[DEBUG] SavedVariables timestamp: %s|r", tostring(dbUpdate)))
        
        -- If CompanionData is newer, update our SavedVariables
        if companionUpdate > dbUpdate then
            LuminisbotEventsDB.events = LuminisbotCompanionData.events
            LuminisbotEventsDB.lastUpdate = LuminisbotCompanionData.lastUpdate
            
            local eventCount = 0
            for _ in pairs(LuminisbotEventsDB.events or {}) do
                eventCount = eventCount + 1
            end
            
            if eventCount > 0 then
                addon:Print(string.format("|cff00ff00[OK] Loaded %d event(s) from companion app|r", eventCount))
            end
        else
            addon:Print("|cffffff00[DEBUG] CompanionData is not newer than SavedVariables|r")
        end
    else
        addon:Print("|cffff0000[DEBUG] CompanionData not found or has no lastUpdate|r")
    end
    
    self.lastKnownUpdate = LuminisbotEventsDB.lastUpdate or 0
end
