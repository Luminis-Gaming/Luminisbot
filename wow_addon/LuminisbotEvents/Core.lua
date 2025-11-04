-- Luminisbot Events - Core Logic
-- Handles data import, storage, and business logic

local ADDON_NAME, addon = ...

-- Initialize addon namespace
addon.version = "1.0.0"
addon.events = {}

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

-- Parse a JSON string (simple implementation)
function addon:ParseJSON(str)
    -- Remove whitespace
    str = str:gsub('^%s*', ''):gsub('%s*$', '')
    
    -- Check if it's a string
    if str:match('^".*"$') then
        local content = str:sub(2, -2)
        return json_unescape(content)
    end
    
    -- Check if it's a number
    if str:match('^%-?%d+%.?%d*$') then
        return tonumber(str)
    end
    
    -- Check if it's boolean or null
    if str == 'true' then return true end
    if str == 'false' then return false end
    if str == 'null' then return nil end
    
    -- Check if it's an array
    if str:match('^%[.*%]$') then
        local arr = {}
        local content = str:sub(2, -2)
        
        -- Simple array parser (doesn't handle nested arrays/objects well)
        local depth = 0
        local current = ""
        local inString = false
        
        for i = 1, #content do
            local char = content:sub(i, i)
            
            if char == '"' and content:sub(i-1, i-1) ~= '\\' then
                inString = not inString
            end
            
            if not inString then
                if char == '{' or char == '[' then
                    depth = depth + 1
                elseif char == '}' or char == ']' then
                    depth = depth - 1
                elseif char == ',' and depth == 0 then
                    table.insert(arr, self:ParseJSON(current))
                    current = ""
                    goto continue
                end
            end
            
            current = current .. char
            ::continue::
        end
        
        if #current > 0 then
            table.insert(arr, self:ParseJSON(current))
        end
        
        return arr
    end
    
    -- Check if it's an object
    if str:match('^{.*}$') then
        local obj = {}
        local content = str:sub(2, -2)
        
        -- Simple object parser
        local depth = 0
        local current = ""
        local inString = false
        
        for i = 1, #content do
            local char = content:sub(i, i)
            
            if char == '"' and content:sub(i-1, i-1) ~= '\\' then
                inString = not inString
            end
            
            if not inString then
                if char == '{' or char == '[' then
                    depth = depth + 1
                elseif char == '}' or char == ']' then
                    depth = depth - 1
                elseif char == ',' and depth == 0 then
                    -- Parse key-value pair
                    local key, value = current:match('^"([^"]+)"%s*:%s*(.+)$')
                    if key and value then
                        obj[key] = self:ParseJSON(value)
                    end
                    current = ""
                    goto continue
                end
            end
            
            current = current .. char
            ::continue::
        end
        
        if #current > 0 then
            local key, value = current:match('^"([^"]+)"%s*:%s*(.+)$')
            if key and value then
                obj[key] = self:ParseJSON(value)
            end
        end
        
        return obj
    end
    
    return nil
end

-- ============================================================================
-- EVENT IMPORT
-- ============================================================================

function addon:ImportEventString(encodedString)
    -- Decode base64
    local jsonString = self:Base64Decode(encodedString)
    if not jsonString or jsonString == "" then
        self:PrintError("Failed to decode import string! Make sure you copied the entire command.")
        return false
    end
    
    -- Parse JSON
    local eventData = self:ParseJSON(jsonString)
    if not eventData or type(eventData) ~= "table" then
        self:PrintError("Failed to parse event data! The import string may be corrupted.")
        return false
    end
    
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

SLASH_LUMINISBOT1 = "/luminisbot"
SLASH_LUMINISBOT2 = "/lb"
SlashCmdList["LUMINISBOT"] = function(msg)
    local command, arg = strsplit(" ", msg, 2)
    command = (command or ""):lower()
    
    if command == "" or command == "show" then
        addon:ToggleUI()
        
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
        addon:Print("  /luminisbot show - Toggle event window")
        addon:Print("  /luminisbot import <string> - Import event from Discord")
        addon:Print("  /luminisbot list - List all imported events")
        addon:Print("  /luminisbot clear - Remove past events")
        addon:Print("  /luminisbot help - Show this help")
        
    else
        -- Default: toggle UI
        addon:ToggleUI()
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
        -- Addon loaded
        addon:Print("loaded! Type |cff00ff00/luminisbot|r to get started.")
        
    elseif event == "PLAYER_LOGIN" then
        -- Player logged in - check for updates
        local events = addon:GetEvents()
        if #events > 0 then
            addon:Print(string.format("%d event(s) loaded. Type |cff00ff00/lb show|r to view.", #events))
        else
            addon:Print("No events yet. Import from Discord with |cff00ff00/lb import|r")
        end
    end
end)
