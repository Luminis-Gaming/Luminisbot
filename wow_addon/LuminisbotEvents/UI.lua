-- Luminisbot Events - UI
-- Handles the in-game interface and display

local ADDON_NAME, addon = ...

-- Role icons (using default WoW textures)
local ROLE_ICONS = {
    tank = "|TInterface\\LFGFrame\\UI-LFG-ICON-PORTRAITROLES:16:16:0:0:64:64:0:19:22:41|t",
    healer = "|TInterface\\LFGFrame\\UI-LFG-ICON-PORTRAITROLES:16:16:0:0:64:64:20:39:1:20|t",
    dps = "|TInterface\\LFGFrame\\UI-LFG-ICON-PORTRAITROLES:16:16:0:0:64:64:20:39:22:41|t"
}

-- Class colors
local CLASS_COLORS = {
    ["Death Knight"] = {r=0.77, g=0.12, b=0.23},
    ["Demon Hunter"] = {r=0.64, g=0.19, b=0.79},
    ["Druid"] = {r=1.00, g=0.49, b=0.04},
    ["Evoker"] = {r=0.20, g=0.58, b=0.50},
    ["Hunter"] = {r=0.67, g=0.83, b=0.45},
    ["Mage"] = {r=0.25, g=0.78, b=0.92},
    ["Monk"] = {r=0.00, g=1.00, b=0.59},
    ["Paladin"] = {r=0.96, g=0.55, b=0.73},
    ["Priest"] = {r=1.00, g=1.00, b=1.00},
    ["Rogue"] = {r=1.00, g=0.96, b=0.41},
    ["Shaman"] = {r=0.00, g=0.44, b=0.87},
    ["Warlock"] = {r=0.53, g=0.53, b=0.93},
    ["Warrior"] = {r=0.78, g=0.61, b=0.43}
}

-- ============================================================================
-- MAIN FRAME
-- ============================================================================

function addon:CreateMainFrame()
    if self.mainFrame then return end
    
    -- Create main frame with portrait using PortraitFrameTemplate
    local frame = CreateFrame("Frame", "LuminisbotEventsFrame", UIParent, "PortraitFrameTemplate")
    frame:SetSize(550, 650)
    frame:SetPoint("CENTER")
    frame:SetFrameStrata("HIGH")
    frame:Hide()
    
    -- Set title text
    frame:SetTitle("Luminisbot Events")
    
    -- Make the frame draggable
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", function(self)
        self:StartMoving()
    end)
    frame:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        -- Save position
        local point, _, relativePoint, xOfs, yOfs = self:GetPoint()
        if not LuminisbotEventsDB.framePosition then
            LuminisbotEventsDB.framePosition = {}
        end
        LuminisbotEventsDB.framePosition = {
            point = point,
            relativePoint = relativePoint,
            xOffset = xOfs,
            yOffset = yOfs
        }
    end)
    
    -- Set the portrait to the Luminis logo
    local logoPath = "Interface\\AddOns\\LuminisbotEvents\\assets\\luminis_logo"
    
    -- Try different portrait references (varies by WoW version)
    local portraitTexture = frame.PortraitContainer and frame.PortraitContainer.portrait or frame.portrait or frame.Portrait
    
    if portraitTexture then
        portraitTexture:SetTexture(logoPath)
        portraitTexture:SetTexCoord(0, 1, 0, 1)  -- Reset texture coordinates
        
        -- If logo fails to load, use a default icon
        if not portraitTexture:GetTexture() then
            portraitTexture:SetTexture("Interface\\Icons\\INV_Misc_Note_06")
        end
    end
    
    -- Tab buttons for switching between views (positioned to avoid portrait)
    local eventsTab = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    eventsTab:SetSize(100, 25)
    eventsTab:SetPoint("TOPLEFT", frame, "TOPLEFT", 70, -28)  -- Moved right to avoid portrait
    eventsTab:SetText("Events")
    frame.eventsTab = eventsTab
    
    local importTab = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    importTab:SetSize(110, 25)
    importTab:SetPoint("LEFT", eventsTab, "RIGHT", 5, 0)
    importTab:SetText("Import Events")
    frame.importTab = importTab
    
    local companionTab = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    companionTab:SetSize(120, 25)
    companionTab:SetPoint("LEFT", importTab, "RIGHT", 5, 0)
    companionTab:SetText("Companion App")
    frame.companionTab = companionTab
    
    -- Create content frames for each tab
    local eventsContent = CreateFrame("Frame", nil, frame)
    eventsContent:SetPoint("TOPLEFT", frame, "TOPLEFT", 15, -65)
    eventsContent:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -15, 45)
    frame.eventsContent = eventsContent
    
    local importContent = CreateFrame("Frame", nil, frame)
    importContent:SetPoint("TOPLEFT", frame, "TOPLEFT", 15, -65)
    importContent:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -15, 45)
    importContent:Hide()
    frame.importContent = importContent
    
    local companionContent = CreateFrame("Frame", nil, frame)
    companionContent:SetPoint("TOPLEFT", frame, "TOPLEFT", 15, -65)
    companionContent:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -15, 45)
    companionContent:Hide()
    frame.companionContent = companionContent
    
    -- Tab switching
    local function showTab(tab)
        eventsContent:Hide()
        importContent:Hide()
        companionContent:Hide()
        
        eventsTab:Enable()
        importTab:Enable()
        companionTab:Enable()
        
        if tab == "events" then
            eventsContent:Show()
            eventsTab:Disable()
        elseif tab == "import" then
            importContent:Show()
            importTab:Disable()
        elseif tab == "companion" then
            companionContent:Show()
            companionTab:Disable()
            addon:RefreshCompanionTab()
        end
    end
    
    eventsTab:SetScript("OnClick", function() showTab("events") end)
    importTab:SetScript("OnClick", function() showTab("import") end)
    companionTab:SetScript("OnClick", function() showTab("companion") end)
    
    -- ========== EVENTS TAB ==========
    
    -- Scroll frame for events
    local scrollFrame = CreateFrame("ScrollFrame", nil, eventsContent, "UIPanelScrollFrameTemplate")
    scrollFrame:SetPoint("TOPLEFT", 5, -5)
    scrollFrame:SetPoint("BOTTOMRIGHT", -25, 5)
    scrollFrame:SetClipsChildren(true)  -- FIX: Prevent content from rendering outside
    
    local scrollChild = CreateFrame("Frame", nil, scrollFrame)
    scrollChild:SetSize(490, 1)
    scrollFrame:SetScrollChild(scrollChild)
    
    frame.scrollFrame = scrollFrame
    frame.scrollChild = scrollChild
    
    -- Help text
    local helpText = eventsContent:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    helpText:SetPoint("CENTER", eventsContent, "CENTER", 0, 20)
    helpText:SetText("No events yet!")
    helpText:Hide()
    frame.helpText = helpText
    
    local helpSubtext = eventsContent:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    helpSubtext:SetPoint("TOP", helpText, "BOTTOM", 0, -10)
    helpSubtext:SetText("Configure server sync in Settings or import from Discord")
    helpSubtext:SetTextColor(0.7, 0.7, 0.7)
    helpSubtext:Hide()
    frame.helpSubtext = helpSubtext
    
    -- ========== IMPORT TAB ==========
    
    addon:CreateImportTab(importContent)
    
    -- ========== COMPANION APP TAB ==========
    
    addon:CreateCompanionTab(companionContent)
    
    -- ========== BOTTOM BUTTONS ==========
    
    local refreshButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    refreshButton:SetSize(100, 22)
    refreshButton:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 15, 12)
    refreshButton:SetText("Refresh")
    refreshButton:SetScript("OnClick", function()
        addon:RefreshUI()
    end)
    frame.refreshButton = refreshButton
    
    local clearButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    clearButton:SetSize(120, 22)
    clearButton:SetPoint("LEFT", refreshButton, "RIGHT", 5, 0)
    clearButton:SetText("Clear Old Events")
    clearButton:SetScript("OnClick", function()
        addon:ClearOldEvents()
        addon:RefreshUI()
    end)
    frame.clearButton = clearButton
    
    -- Show events tab by default
    showTab("events")
    
    -- Restore saved position if it exists
    if LuminisbotEventsDB.framePosition then
        local pos = LuminisbotEventsDB.framePosition
        frame:ClearAllPoints()
        frame:SetPoint(
            pos.point or "CENTER",
            UIParent,
            pos.relativePoint or "CENTER",
            pos.xOffset or 0,
            pos.yOffset or 0
        )
    end
    
    self.mainFrame = frame
end

-- ============================================================================
-- COMPANION APP TAB
-- ============================================================================

function addon:CreateCompanionTab(parent)
    -- Scroll frame for content
    local scrollFrame = CreateFrame("ScrollFrame", nil, parent, "UIPanelScrollFrameTemplate")
    scrollFrame:SetPoint("TOPLEFT", parent, "TOPLEFT", 5, -5)
    scrollFrame:SetPoint("BOTTOMRIGHT", parent, "BOTTOMRIGHT", -25, 5)
    
    local scrollChild = CreateFrame("Frame", nil, scrollFrame)
    scrollChild:SetSize(480, 1000)
    scrollFrame:SetScrollChild(scrollChild)
    
    local yOffset = -10
    
    -- Header
    local headerLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    headerLabel:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    headerLabel:SetText("Companion App (Optional)")
    headerLabel:SetTextColor(1, 0.82, 0)
    yOffset = yOffset - 30
    
    -- Description
    local descLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    descLabel:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    descLabel:SetWidth(460)
    descLabel:SetJustifyH("LEFT")
    descLabel:SetText("The Companion App enables automatic syncing without manual copy/paste.")
    yOffset = yOffset - 35
    
    local warningLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    warningLabel:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    warningLabel:SetWidth(460)
    warningLabel:SetJustifyH("LEFT")
    warningLabel:SetText("|cffffaa00[!] This is completely OPTIONAL!|r")
    yOffset = yOffset - 25
    
    local altLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    altLabel:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    altLabel:SetWidth(460)
    altLabel:SetJustifyH("LEFT")
    altLabel:SetText("You can use the |cff00ff00Import Events|r tab to manually sync anytime.")
    yOffset = yOffset - 35
    
    -- Setup section
    local setupHeader = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    setupHeader:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    setupHeader:SetText("|cff00ff00Companion App Setup:|r")
    yOffset = yOffset - 25
    
    -- Steps
    local steps = {
        "1. Download the Companion App from CurseForge or GitHub",
        "2. In Discord, type /subscribe to get your subscription string",
        "3. Paste the subscription string into the Companion App",
        "4. Click 'Start Syncing' in the app - Done!"
    }
    
    for _, step in ipairs(steps) do
        local stepLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        stepLabel:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 20, yOffset)
        stepLabel:SetWidth(450)
        stepLabel:SetJustifyH("LEFT")
        stepLabel:SetText(step)
        yOffset = yOffset - 20
    end
    
    yOffset = yOffset - 10
    
    -- Subscription string reference
    local subLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    subLabel:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    subLabel:SetText("Your Subscription String (for reference):")
    subLabel:SetTextColor(0.7, 0.7, 0.7)
    yOffset = yOffset - 20
    
    local subBox = CreateFrame("EditBox", nil, scrollChild, "InputBoxTemplate")
    subBox:SetSize(380, 20)
    subBox:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 15, yOffset)
    subBox:SetAutoFocus(false)
    subBox:SetMaxLetters(0)
    subBox:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    parent.subBox = subBox
    yOffset = yOffset - 35
    
    -- Status section
    local statusHeader = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    statusHeader:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    statusHeader:SetText("|cff00ff00Companion App Status:|r")
    yOffset = yOffset - 25
    
    local statusText = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    statusText:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    statusText:SetJustifyH("LEFT")
    statusText:SetWidth(460)
    parent.statusText = statusText
    yOffset = yOffset - 60
    
    -- Benefits section
    local benefitsHeader = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    benefitsHeader:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    benefitsHeader:SetText("|cff00ff00Why Use the Companion App?|r")
    yOffset = yOffset - 25
    
    local benefits = {
        "[+] Automatic syncing every 60 seconds",
        "[+] No manual copy/paste needed",
        "[+] Runs in background (system tray)",
        "[+] Real-time notifications in-game"
    }
    
    for _, benefit in ipairs(benefits) do
        local benefitLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        benefitLabel:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 20, yOffset)
        benefitLabel:SetWidth(450)
        benefitLabel:SetJustifyH("LEFT")
        benefitLabel:SetText(benefit)
        benefitLabel:SetTextColor(0.5, 1, 0.5)
        yOffset = yOffset - 18
    end
    
    yOffset = yOffset - 10
    
    local noteLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    noteLabel:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
    noteLabel:SetWidth(460)
    noteLabel:SetJustifyH("LEFT")
    noteLabel:SetText("Without the app, you can still manually sync using the Import Events tab - it works perfectly fine!")
    noteLabel:SetTextColor(0.7, 0.7, 0.7)
end

function addon:RefreshCompanionTab()
    if not self.mainFrame or not self.mainFrame.companionContent then return end
    
    local parent = self.mainFrame.companionContent
    if not parent.statusText then return end
    
    local statusText = ""
    
    -- Check if companion app is running by checking heartbeat age
    local companionActive = false
    local heartbeatAge = 999999
    
    if LuminisbotCompanionData and LuminisbotCompanionData.companionHeartbeat then
        heartbeatAge = time() - LuminisbotCompanionData.companionHeartbeat
        -- Consider active if heartbeat is less than 2 minutes old
        companionActive = heartbeatAge < 120
    end
    
    if companionActive and LuminisbotEventsDB.lastUpdate and LuminisbotEventsDB.lastUpdate > 0 then
        local eventCount = 0
        for _ in pairs(LuminisbotEventsDB.events or {}) do
            eventCount = eventCount + 1
        end
        
        -- Format the timestamp nicely
        local timeAgo = LuminisbotEvents:FormatTimeAgo(LuminisbotEventsDB.lastUpdate)
        
        statusText = string.format(
            "|cff00ff00[Active]|r Companion App Running\n\n" ..
            "Events synced: %d\n" ..
            "Last sync: %s\n\n" ..
            "Click Refresh button below to load new events!",
            eventCount,
            timeAgo
        )
    elseif LuminisbotEventsDB.lastUpdate and LuminisbotEventsDB.lastUpdate > 0 then
        -- Has data but companion not running
        local eventCount = 0
        for _ in pairs(LuminisbotEventsDB.events or {}) do
            eventCount = eventCount + 1
        end
        
        local timeAgo = LuminisbotEvents:FormatTimeAgo(LuminisbotEventsDB.lastUpdate)
        
        statusText = string.format(
            "|cffff9900[Not Running]|r Companion App Stopped\n\n" ..
            "Events synced: %d\n" ..
            "Last sync: %s\n\n" ..
            "Start the companion app to sync new events.",
            eventCount,
            timeAgo
        )
    else
        statusText = 
            "|cffff9900[Not Connected]|r\n\n" ..
            "Companion app not detected.\n\n" ..
            "Either the app isn't running, or you haven't completed setup yet."
    end
    
    parent.statusText:SetText(statusText)
    
    -- Update subscription string display
    if parent.subBox and LuminisbotEventsDB.guildId and LuminisbotEventsDB.apiKey then
        local sub_string = self:Base64Encode(LuminisbotEventsDB.guildId .. ":" .. LuminisbotEventsDB.apiKey)
        parent.subBox:SetText(sub_string)
    end
end

-- Base64 encoding (for subscription string display)
function addon:Base64Encode(data)
    local b = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    return ((data:gsub('.', function(x) 
        local r,b='',x:byte()
        for i=8,1,-1 do r=r..(b%2^i-b%2^(i-1)>0 and '1' or '0') end
        return r;
    end)..'0000'):gsub('%d%d%d?%d?%d?%d?', function(x)
        if (#x < 6) then return '' end
        local c=0
        for i=1,6 do c=c+(x:sub(i,i)=='1' and 2^(6-i) or 0) end
        return b:sub(c+1,c+1)
    end)..({ '', '==', '=' })[#data%3+1])
end

-- ============================================================================
-- IMPORT TAB
-- ============================================================================

function addon:CreateImportTab(parent)
    -- Header
    local importLabel = parent:CreateFontString(nil, "OVERLAY", "GameFontNormalHuge")
    importLabel:SetPoint("TOPLEFT", parent, "TOPLEFT", 10, -10)
    importLabel:SetText("Import Events from Discord")
    
    -- Description
    local importDesc = parent:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    importDesc:SetPoint("TOPLEFT", importLabel, "BOTTOMLEFT", 0, -10)
    importDesc:SetText(
        "This is the main way to sync events with Discord.\n" ..
        "It takes about 15 seconds and works perfectly!"
    )
    importDesc:SetWidth(500)
    importDesc:SetJustifyH("LEFT")
    importDesc:SetSpacing(4)
    
    -- Instructions
    local instructLabel = parent:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    instructLabel:SetPoint("TOPLEFT", importDesc, "BOTTOMLEFT", 0, -20)
    instructLabel:SetText("How to Import:")
    
    local step1 = parent:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    step1:SetPoint("TOPLEFT", instructLabel, "BOTTOMLEFT", 0, -10)
    step1:SetText("|cff00ff001.|r In Discord, type |cff00ff00/syncevents|r in any channel")
    step1:SetJustifyH("LEFT")
    
    local step2 = parent:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    step2:SetPoint("TOPLEFT", step1, "BOTTOMLEFT", 0, -5)
    step2:SetText("|cff00ff002.|r Copy the import string Discord sends you")
    step2:SetJustifyH("LEFT")
    
    local step3 = parent:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    step3:SetPoint("TOPLEFT", step2, "BOTTOMLEFT", 0, -5)
    step3:SetText("|cff00ff003.|r Paste it in the box below and click Import")
    step3:SetJustifyH("LEFT")
    
    local divider = parent:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    divider:SetPoint("TOPLEFT", step3, "BOTTOMLEFT", 0, -15)
    divider:SetText("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    divider:SetTextColor(0.3, 0.3, 0.3)
    
    local importBox = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
    importBox:SetSize(500, 20)
    importBox:SetPoint("TOPLEFT", divider, "BOTTOMLEFT", 0, -15)
    importBox:SetAutoFocus(false)
    importBox:SetMaxLetters(0)
    importBox:SetScript("OnEnterPressed", function(self)
        local text = self:GetText()
        if text and text ~= "" then
            addon:ImportEventString(text)
            self:SetText("")
            self:ClearFocus()
            addon:RefreshUI()
        end
    end)
    importBox:SetScript("OnEscapePressed", function(self)
        self:SetText("")
        self:ClearFocus()
    end)
    
    local importButton = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    importButton:SetSize(100, 30)
    importButton:SetPoint("TOPLEFT", importBox, "BOTTOMLEFT", 0, -10)
    importButton:SetText("Import Event")
    importButton:SetScript("OnClick", function()
        local text = importBox:GetText()
        if text and text ~= "" then
            addon:ImportEventString(text)
            importBox:SetText("")
            addon:RefreshUI()
        else
            addon:PrintError("Please paste an event string first!")
        end
    end)
    
    local clearButton = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    clearButton:SetSize(100, 30)
    clearButton:SetPoint("LEFT", importButton, "RIGHT", 10, 0)
    clearButton:SetText("Clear Box")
    clearButton:SetScript("OnClick", function()
        importBox:SetText("")
    end)
end

-- ============================================================================
-- EVENT DISPLAY
-- ============================================================================

function addon:RefreshUI()
    -- First, try to reload data from companion app
    addon:LoadCompanionData()
    
    if not self.mainFrame then
        self:CreateMainFrame()
    end
    
    local scrollChild = self.mainFrame.scrollChild
    
    -- Clear existing content
    for _, child in pairs({scrollChild:GetChildren()}) do
        child:Hide()
        child:SetParent(nil)
    end
    
    -- Get events
    local events = self:GetEvents()
    
    if #events == 0 then
        self.mainFrame.helpText:Show()
        self.mainFrame.helpSubtext:Show()
        return
    end
    
    self.mainFrame.helpText:Hide()
    self.mainFrame.helpSubtext:Hide()
    
    -- Display events
    local yOffset = -10
    
    for i, event in ipairs(events) do
        local eventFrame = self:CreateEventFrame(event)
        eventFrame:SetParent(scrollChild)
        eventFrame:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 5, yOffset)
        eventFrame:Show()
        
        yOffset = yOffset - eventFrame:GetHeight() - 10
    end
    
    scrollChild:SetHeight(math.abs(yOffset) + 20)
end

function addon:CreateEventFrame(event)
    local frame = CreateFrame("Frame", nil, nil, "BackdropTemplate")
    frame:SetSize(440, 120)  -- Base height, will adjust
    
    -- Background
    frame:SetBackdrop({
        bgFile = "Interface\\ChatFrame\\ChatFrameBackground",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
        tile = true,
        tileSize = 16,
        edgeSize = 16,
        insets = {left = 4, right = 4, top = 4, bottom = 4}
    })
    frame:SetBackdropColor(0.1, 0.1, 0.1, 0.9)
    frame:SetBackdropBorderColor(0.4, 0.4, 0.4, 1)
    
    -- Title
    local title = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    title:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -8)
    title:SetText(event.title or "Unknown Event")
    title:SetTextColor(1, 0.82, 0)
    
    -- Date/Time
    local dateTime = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    dateTime:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, -4)
    
    -- Convert date from YYYY-MM-DD to DD/MM/YYYY
    local dateStr = event.date or "Unknown"
    if dateStr ~= "Unknown" and dateStr:match("^%d%d%d%d%-%d%d%-%d%d$") then
        local year, month, day = dateStr:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)$")
        dateStr = string.format("%s/%s/%s", day, month, year)
    end
    
    local timeStr = (event.time or "00:00:00"):sub(1, 5)  -- HH:MM
    dateTime:SetText(string.format("📅 %s  🕐 %s", dateStr, timeStr))
    dateTime:SetTextColor(0.8, 0.8, 0.8)
    
    -- Count signups by status
    local tanks, healers, dps = 0, 0, 0
    local signed, late, tentative, absent = 0, 0, 0, 0
    
    if event.signups then
        for _, signup in ipairs(event.signups) do
            if signup.status == "signed" then
                signed = signed + 1
                if signup.role == "tank" then
                    tanks = tanks + 1
                elseif signup.role == "healer" then
                    healers = healers + 1
                elseif signup.role == "dps" then
                    dps = dps + 1
                end
            elseif signup.status == "late" then
                late = late + 1
            elseif signup.status == "tentative" then
                tentative = tentative + 1
            elseif signup.status == "absent" then
                absent = absent + 1
            end
        end
    end
    
    -- Composition summary
    local composition = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    composition:SetPoint("TOPLEFT", dateTime, "BOTTOMLEFT", 0, -4)
    
    local compText = string.format(
        "%s %d  %s %d  %s %d  |cff808080(%d total)|r",
        ROLE_ICONS.tank, tanks,
        ROLE_ICONS.healer, healers,
        ROLE_ICONS.dps, dps,
        signed
    )
    
    if late > 0 or tentative > 0 then
        compText = compText .. string.format(" |cffffff00+%d late/tent|r", late + tentative)
    end
    
    composition:SetText(compText)
    
    -- Buttons
    local inviteButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    inviteButton:SetSize(100, 24)
    inviteButton:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -10, 8)
    inviteButton:SetText("Invite All")
    inviteButton:SetScript("OnClick", function()
        addon:InviteEventSignups(event)
    end)
    
    -- Disable invite if no signups
    if signed == 0 then
        inviteButton:Disable()
    end
    
    local detailsButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    detailsButton:SetSize(80, 24)
    detailsButton:SetPoint("RIGHT", inviteButton, "LEFT", -5, 0)
    detailsButton:SetText("Details")
    detailsButton:SetScript("OnClick", function()
        addon:ShowEventDetails(event)
    end)
    
    local deleteButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    deleteButton:SetSize(70, 24)
    deleteButton:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 10, 8)
    deleteButton:SetText("Delete")
    deleteButton:SetScript("OnClick", function()
        -- Confirm deletion
        StaticPopup_Show("LUMINISBOT_DELETE_EVENT", event.title, nil, event.id)
    end)
    
    return frame
end

-- ============================================================================
-- EVENT DETAILS WINDOW
-- ============================================================================

function addon:ShowEventDetails(event)
    if not self.detailsFrame then
        self:CreateDetailsFrame()
    end
    
    local frame = self.detailsFrame
    
    -- Re-position next to main frame if shown
    if self.mainFrame and self.mainFrame:IsShown() then
        frame:ClearAllPoints()
        frame:SetPoint("LEFT", self.mainFrame, "RIGHT", 20, 0)
    end
    
    local scrollChild = frame.scrollChild
    
    -- Clear existing content
    for _, child in pairs({scrollChild:GetChildren()}) do
        child:Hide()
        child:SetParent(nil)
    end
    
    -- Title (handle both old and new template structures)
    local title = event.title or "Event Details"
    if frame.TitleText then
        frame.TitleText:SetText(title)
    elseif frame.TitleContainer and frame.TitleContainer.TitleText then
        frame.TitleContainer.TitleText:SetText(title)
    end
    
    -- Create header
    local header = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    header:SetPoint("TOP", scrollChild, "TOP", 0, -10)
    
    -- Convert date from YYYY-MM-DD to DD/MM/YYYY
    local dateStr = event.date or "Unknown"
    if dateStr ~= "Unknown" and dateStr:match("^%d%d%d%d%-%d%d%-%d%d$") then
        local year, month, day = dateStr:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)$")
        dateStr = string.format("%s/%s/%s", day, month, year)
    end
    
    header:SetText(string.format("%s - %s", dateStr, (event.time or "00:00:00"):sub(1, 5)))
    header:SetTextColor(1, 0.82, 0)
    
    local yOffset = -40
    
    -- Group signups by status
    local statusGroups = {
        signed = {},
        late = {},
        tentative = {},
        benched = {},
        absent = {}
    }
    
    if event.signups then
        for _, signup in ipairs(event.signups) do
            local status = signup.status or "signed"
            if not statusGroups[status] then
                statusGroups[status] = {}
            end
            table.insert(statusGroups[status], signup)
        end
    end
    
    -- Display each status group
    local statusLabels = {
        signed = {label = "✓ Signed Up", color = {0, 1, 0}},
        late = {label = "🕐 Late", color = {1, 0.8, 0}},
        tentative = {label = "⚖ Tentative", color = {0.8, 0.8, 0}},
        benched = {label = "🪑 Benched", color = {0.5, 0.5, 0.5}},
        absent = {label = "[X] Absent", color = {1, 0, 0}}
    }
    
    for _, statusKey in ipairs({"signed", "late", "tentative", "benched", "absent"}) do
        local signups = statusGroups[statusKey]
        
        if #signups > 0 then
            -- Status header
            local statusHeader = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormal")
            statusHeader:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 10, yOffset)
            
            local statusInfo = statusLabels[statusKey]
            statusHeader:SetText(string.format("%s (%d)", statusInfo.label, #signups))
            statusHeader:SetTextColor(unpack(statusInfo.color))
            
            yOffset = yOffset - 25
            
            -- Sort signups by role
            table.sort(signups, function(a, b)
                if a.role == b.role then
                    return (a.name or "") < (b.name or "")
                end
                local roleOrder = {tank = 1, healer = 2, dps = 3}
                return (roleOrder[a.role] or 4) < (roleOrder[b.role] or 4)
            end)
            
            -- List signups
            for _, signup in ipairs(signups) do
                -- Create a container frame for this player
                local playerFrame = CreateFrame("Frame", nil, scrollChild)
                playerFrame:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 20, yOffset)
                playerFrame:SetSize(400, 18)
                
                local playerText = playerFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
                playerText:SetPoint("LEFT", playerFrame, "LEFT", 0, 0)
                
                -- Get class color
                local classColor = CLASS_COLORS[signup.class] or {r=1, g=1, b=1}
                
                -- Format: [Role Icon] Name (Spec Class)
                local roleIcon = ROLE_ICONS[signup.role] or ""
                local specText = signup.spec and signup.spec ~= "" and signup.spec or signup.class
                
                -- Get character name (handle both 'character' and 'name' fields, and empty strings)
                local characterName = signup.character or signup.name or ""
                if characterName == "" then
                    characterName = "Unknown"
                end
                
                playerText:SetText(string.format("%s %s", roleIcon, characterName))
                playerText:SetTextColor(classColor.r, classColor.g, classColor.b)
                
                -- Spec/Class
                local specLabel = playerFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
                specLabel:SetPoint("LEFT", playerText, "RIGHT", 5, 0)
                specLabel:SetText(string.format("(%s)", specText))
                specLabel:SetTextColor(0.6, 0.6, 0.6)
                
                -- Individual invite button
                local inviteBtn = CreateFrame("Button", nil, playerFrame, "UIPanelButtonTemplate")
                inviteBtn:SetSize(50, 18)
                inviteBtn:SetPoint("RIGHT", playerFrame, "RIGHT", 0, 0)
                inviteBtn:SetText("Invite")
                inviteBtn:SetScript("OnClick", function()
                    -- Format character name with realm
                    local characterName = signup.character or signup.name or "Unknown"
                    if signup.realm then
                        -- Convert realm to in-game format (remove spaces/hyphens)
                        local realmFormatted = signup.realm:gsub("%-", ""):gsub(" ", "")
                        characterName = characterName .. "-" .. realmFormatted
                    end
                    
                    C_PartyInfo.InviteUnit(characterName)
                    addon:Print("Invited " .. characterName)
                end)
                
                yOffset = yOffset - 18
            end
            
            yOffset = yOffset - 10  -- Extra spacing between groups
        end
    end
    
    if yOffset == -40 then
        -- No signups
        local noSignups = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormal")
        noSignups:SetPoint("TOP", scrollChild, "TOP", 0, -40)
        noSignups:SetText("No signups yet for this event.")
        noSignups:SetTextColor(0.7, 0.7, 0.7)
        yOffset = -80
    end
    
    scrollChild:SetHeight(math.abs(yOffset) + 20)
    frame:Show()
end

function addon:CreateDetailsFrame()
    local frame = CreateFrame("Frame", "LuminisbotEventsDetailsFrame", UIParent, "BasicFrameTemplate")
    frame:SetSize(550, 600)
    -- Position to the right of main frame if it exists, otherwise center
    if self.mainFrame and self.mainFrame:IsShown() then
        frame:SetPoint("LEFT", self.mainFrame, "RIGHT", 20, 0)
    else
        frame:SetPoint("CENTER")
    end
    frame:SetFrameStrata("DIALOG")  -- Higher than main frame
    frame:Hide()
    
    -- Title (handle both old and new template structures)
    if frame.TitleText then
        frame.TitleText:SetText("Event Details")
    elseif frame.TitleContainer and frame.TitleContainer.TitleText then
        frame.TitleContainer.TitleText:SetText("Event Details")
    end
    
    -- Scroll frame
    local scrollFrame = CreateFrame("ScrollFrame", nil, frame, "UIPanelScrollFrameTemplate")
    scrollFrame:SetPoint("TOPLEFT", frame, "TOPLEFT", 15, -35)
    scrollFrame:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -30, 50)
    
    local scrollChild = CreateFrame("Frame")
    scrollChild:SetSize(490, 1)
    scrollFrame:SetScrollChild(scrollChild)
    
    frame.scrollFrame = scrollFrame
    frame.scrollChild = scrollChild
    
    -- Close button
    local closeButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    closeButton:SetSize(80, 22)
    closeButton:SetPoint("BOTTOM", frame, "BOTTOM", 0, 10)
    closeButton:SetText("Close")
    closeButton:SetScript("OnClick", function()
        frame:Hide()
    end)
    
    self.detailsFrame = frame
end

-- ============================================================================
-- MINIMAP BUTTON
-- ============================================================================

function addon:CreateMinimapButton()
    if self.minimapButton then return end
    
    -- Create minimap button
    local button = CreateFrame("Button", "LuminisbotMinimapButton", Minimap)
    button:SetSize(32, 32)
    button:SetFrameStrata("MEDIUM")
    button:SetFrameLevel(8)
    
    -- Icon texture - using the Luminis logo
    local icon = button:CreateTexture(nil, "BACKGROUND")
    icon:SetSize(20, 20)
    icon:SetPoint("CENTER", 0, 0)
    
    -- Try to load the custom Luminis logo (TGA format required by WoW)
    local logoPath = "Interface\\AddOns\\LuminisbotEvents\\assets\\luminis_logo"
    icon:SetTexture(logoPath)
    
    -- If custom logo doesn't load, use a fallback WoW icon
    if not icon:GetTexture() then
        icon:SetTexture("Interface\\Icons\\INV_Misc_Note_06")
    end
    button.icon = icon
    
    -- Border (circular frame)
    local overlay = button:CreateTexture(nil, "OVERLAY")
    overlay:SetSize(52, 52)
    overlay:SetPoint("TOPLEFT", 0, 0)
    overlay:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
    
    -- Highlight
    button:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
    
    -- Tooltip
    button:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_LEFT")
        GameTooltip:SetText("Luminisbot", 1, 1, 1, 1, true)
        GameTooltip:AddLine("Raid event manager for Luminis Gaming", 0.8, 0.8, 0.8, true)
        GameTooltip:AddLine(" ", 1, 1, 1, true)
        GameTooltip:AddLine("Click to open event list", 1, 1, 1, true)
        GameTooltip:AddLine("Right-click to drag", 0.5, 0.5, 0.5, true)
        GameTooltip:Show()
    end)
    
    button:SetScript("OnLeave", function()
        GameTooltip:Hide()
    end)
    
    -- Click handler
    button:SetScript("OnClick", function(self, btn)
        if btn == "LeftButton" then
            addon:ToggleUI()
        end
    end)
    
    -- Dragging
    button:RegisterForDrag("RightButton")
    button:SetScript("OnDragStart", function(self)
        self:LockHighlight()
        self:SetScript("OnUpdate", addon.MinimapButton_OnUpdate)
    end)
    
    button:SetScript("OnDragStop", function(self)
        self:UnlockHighlight()
        self:SetScript("OnUpdate", nil)
        -- Save position
        local angle = addon:GetMinimapButtonAngle()
        LuminisbotEventsDB.minimapAngle = angle
    end)
    
    self.minimapButton = button
    
    -- Set initial position
    local angle = LuminisbotEventsDB.minimapAngle or 225
    self:SetMinimapButtonPosition(angle)
end

function addon:GetMinimapButtonAngle()
    local button = self.minimapButton
    if not button then return 0 end
    
    local centerX, centerY = Minimap:GetCenter()
    local buttonX, buttonY = button:GetCenter()
    
    if not centerX or not buttonX then return 0 end
    
    local angle = math.deg(math.atan2(buttonY - centerY, buttonX - centerX))
    return angle
end

function addon:SetMinimapButtonPosition(angle)
    local button = self.minimapButton
    if not button then return end
    
    local radius = 80
    local radian = math.rad(angle)
    local x = math.cos(radian) * radius
    local y = math.sin(radian) * radius
    
    button:ClearAllPoints()
    button:SetPoint("CENTER", Minimap, "CENTER", x, y)
end

function addon.MinimapButton_OnUpdate(self)
    local mx, my = Minimap:GetCenter()
    local px, py = GetCursorPosition()
    local scale = Minimap:GetEffectiveScale()
    
    px, py = px / scale, py / scale
    
    local angle = math.deg(math.atan2(py - my, px - mx))
    addon:SetMinimapButtonPosition(angle)
end

-- ============================================================================
-- UI CONTROL
-- ============================================================================

function addon:ToggleUI()
    if not self.mainFrame then
        self:CreateMainFrame()
    end
    
    if self.mainFrame:IsShown() then
        self.mainFrame:Hide()
    else
        self:RefreshUI()
        self.mainFrame:Show()
    end
end

function addon:ShowUI()
    if not self.mainFrame then
        self:CreateMainFrame()
    end
    
    self:RefreshUI()
    self.mainFrame:Show()
end

function addon:HideUI()
    if self.mainFrame then
        self.mainFrame:Hide()
    end
    
    if self.detailsFrame then
        self.detailsFrame:Hide()
    end
end

-- ============================================================================
-- CONFIRMATION DIALOGS
-- ============================================================================

StaticPopupDialogs["LUMINISBOT_DELETE_EVENT"] = {
    text = "Delete event: %s?\n\nThis cannot be undone!",
    button1 = "Delete",
    button2 = "Cancel",
    OnAccept = function(self, eventId)
        addon:DeleteEvent(eventId)
        addon:RefreshUI()
    end,
    timeout = 0,
    whileDead = true,
    hideOnEscape = true,
    preferredIndex = 3,
}
