-- Commands.lua
-- Queue of commands to be processed by the companion app
-- This file is written by the addon and read by the companion app
-- Commands are processed once and then cleared

LuminisbotCommands = LuminisbotCommands or {
    queue = {},
    lastCommandId = 0
}
