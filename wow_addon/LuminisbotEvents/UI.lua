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
    
    -- Create main frame
    local frame = CreateFrame("Frame", "LuminisbotEventsFrame", UIParent, "PortraitFrameTemplate")
    frame:SetSize(500, 600)
    frame:SetPoint("CENTER")
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
    frame:SetFrameStrata("HIGH")
    frame:Hide()
    
    -- Title (handle both old and new template structures)
    if frame.TitleText then
        frame.TitleText:SetText("Luminisbot Events")
    elseif frame.TitleContainer and frame.TitleContainer.TitleText then
        frame.TitleContainer.TitleText:SetText("Luminisbot Events")
    end
    
    -- Close button (using default X button from template)
    
    -- Create scroll frame for events
    local scrollFrame = CreateFrame("ScrollFrame", nil, frame, "UIPanelScrollFrameTemplate")
    scrollFrame:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -30)
    scrollFrame:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -30, 50)
    
    local scrollChild = CreateFrame("Frame")
    scrollChild:SetSize(450, 1)
    scrollFrame:SetScrollChild(scrollChild)
    
    frame.scrollFrame = scrollFrame
    frame.scrollChild = scrollChild
    
    -- Help text
    local helpText = frame:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    helpText:SetPoint("TOP", scrollChild, "TOP", 0, -20)
    helpText:SetText("No events imported yet!")
    helpText:Hide()
    frame.helpText = helpText
    
    local helpSubtext = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    helpSubtext:SetPoint("TOP", helpText, "BOTTOM", 0, -10)
    helpSubtext:SetText("Use the Admin Panel in Discord to get an import string")
    helpSubtext:SetTextColor(0.7, 0.7, 0.7)
    helpSubtext:Hide()
    frame.helpSubtext = helpSubtext
    
    -- Bottom buttons
    local refreshButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    refreshButton:SetSize(100, 22)
    refreshButton:SetPoint("BOTTOMLEFT", frame, "BOTTOMLEFT", 10, 10)
    refreshButton:SetText("Refresh")
    refreshButton:SetScript("OnClick", function()
        addon:RefreshUI()
    end)
    frame.refreshButton = refreshButton
    
    local clearButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    clearButton:SetSize(120, 22)
    clearButton:SetPoint("BOTTOM", frame, "BOTTOM", 0, 10)
    clearButton:SetText("Clear Old Events")
    clearButton:SetScript("OnClick", function()
        addon:ClearOldEvents()
        addon:RefreshUI()
    end)
    frame.clearButton = clearButton
    
    local closeButton = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
    closeButton:SetSize(80, 22)
    closeButton:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -10, 10)
    closeButton:SetText("Close")
    closeButton:SetScript("OnClick", function()
        frame:Hide()
    end)
    frame.closeButton = closeButton
    
    self.mainFrame = frame
end

-- ============================================================================
-- EVENT DISPLAY
-- ============================================================================

function addon:RefreshUI()
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
    
    local dateStr = event.date or "Unknown"
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
    header:SetText(string.format("%s - %s", event.date, (event.time or "00:00:00"):sub(1, 5)))
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
        absent = {label = "❌ Absent", color = {1, 0, 0}}
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
                local playerText = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
                playerText:SetPoint("TOPLEFT", scrollChild, "TOPLEFT", 20, yOffset)
                
                -- Get class color
                local classColor = CLASS_COLORS[signup.class] or {r=1, g=1, b=1}
                
                -- Format: [Role Icon] Name (Spec Class)
                local roleIcon = ROLE_ICONS[signup.role] or ""
                local specText = signup.spec and signup.spec ~= "" and signup.spec or signup.class
                
                playerText:SetText(string.format("%s %s", roleIcon, signup.name))
                playerText:SetTextColor(classColor.r, classColor.g, classColor.b)
                
                -- Spec/Class
                local specLabel = scrollChild:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
                specLabel:SetPoint("LEFT", playerText, "RIGHT", 5, 0)
                specLabel:SetText(string.format("(%s)", specText))
                specLabel:SetTextColor(0.6, 0.6, 0.6)
                
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
    local frame = CreateFrame("Frame", "LuminisbotEventsDetailsFrame", UIParent, "PortraitFrameTemplate")
    frame:SetSize(450, 550)
    frame:SetPoint("CENTER")
    frame:SetMovable(true)
    frame:EnableMouse(true)
    frame:RegisterForDrag("LeftButton")
    frame:SetScript("OnDragStart", frame.StartMoving)
    frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
    frame:SetFrameStrata("HIGH")
    frame:Hide()
    
    -- Title (handle both old and new template structures)
    if frame.TitleText then
        frame.TitleText:SetText("Event Details")
    elseif frame.TitleContainer and frame.TitleContainer.TitleText then
        frame.TitleContainer.TitleText:SetText("Event Details")
    end
    
    -- Scroll frame
    local scrollFrame = CreateFrame("ScrollFrame", nil, frame, "UIPanelScrollFrameTemplate")
    scrollFrame:SetPoint("TOPLEFT", frame, "TOPLEFT", 10, -30)
    scrollFrame:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", -30, 50)
    
    local scrollChild = CreateFrame("Frame")
    scrollChild:SetSize(400, 1)
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
