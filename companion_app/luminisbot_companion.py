#!/usr/bin/env python3
"""
Luminisbot Companion App
Bridges WoW addon and Discord bot API for real-time event syncing
"""

import os
import sys
import time
import json
import requests
import base64
from datetime import datetime
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pystray
from PIL import Image, ImageDraw, ImageTk
from dotenv import load_dotenv

try:
    from updater import AutoUpdater
    AUTO_UPDATE_AVAILABLE = True
except ImportError:
    AUTO_UPDATE_AVAILABLE = False
    print("Warning: updater.py not found - auto-update disabled")

# Version
VERSION = "1.0.2.3"

# Luminis Colors
LUMINIS_BG = "#1a1a1a"
LUMINIS_FG = "#ffffff"
LUMINIS_ACCENT = "#4a9eff"
LUMINIS_SUCCESS = "#00ff00"
LUMINIS_WARNING = "#ffaa00"
LUMINIS_ERROR = "#ff0000"

# Configuration
SYNC_INTERVAL = 60  # seconds
API_BASE_URL = "https://luminisbot.flipflix.no/api/v1"

class LuminisbotCompanion:
    def __init__(self):
        self.running = False
        self.api_key = None
        self.guild_id = None
        self.wow_path = None
        self.account_name = None
        self.sync_thread = None
        self.last_sync = None
        self.event_count = 0
        
        # Load saved config
        self.config_file = Path.home() / ".luminisbot_companion.json"
        self.load_config()
        
    def load_config(self):
        """Load saved configuration"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.api_key = config.get('api_key')
                    self.guild_id = config.get('guild_id')
                    self.wow_path = config.get('wow_path')
                    self.account_name = config.get('account_name')
            except Exception as e:
                print(f"Error loading config: {e}")
    
    def save_config(self):
        """Save configuration"""
        try:
            config = {
                'api_key': self.api_key,
                'guild_id': self.guild_id,
                'wow_path': self.wow_path,
                'account_name': self.account_name
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def get_savedvariables_path(self):
        """Get path to WoW SavedVariables file"""
        if not self.wow_path or not self.account_name:
            return None
        
        return Path(self.wow_path) / "WTF" / "Account" / self.account_name / "SavedVariables" / "LuminisbotEvents.lua"
    
    def parse_subscription_string(self, subscription_string):
        """Parse base64 subscription string"""
        try:
            decoded = base64.b64decode(subscription_string).decode('utf-8')
            guild_id, api_key = decoded.split(':', 1)
            return guild_id, api_key
        except Exception as e:
            raise ValueError(f"Invalid subscription string: {e}")
    
    def detect_wow_accounts(self):
        """Auto-detect WoW account folders"""
        if not self.wow_path:
            return []
        
        wtf_path = Path(self.wow_path) / "WTF" / "Account"
        if not wtf_path.exists():
            return []
        
        accounts = []
        for account_folder in wtf_path.iterdir():
            if account_folder.is_dir() and account_folder.name not in ["SavedVariables"]:
                accounts.append(account_folder.name)
        
        return sorted(accounts)
    
    def fetch_events(self):
        """Fetch events from API"""
        if not self.api_key or not self.guild_id:
            return None
        
        try:
            headers = {
                'X-API-Key': self.api_key,
                'Content-Type': 'application/json'
            }
            
            response = requests.get(
                f"{API_BASE_URL}/events",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Debug: Log character names from API response
                if 'events' in data:
                    for event in data['events']:
                        if 'signups' in event and len(event['signups']) > 0:
                            sample_signup = event['signups'][0]
                            char_name = sample_signup.get('character', '')
                            print(f"[DEBUG] API returned character: '{char_name}' (empty: {char_name == ''})")
                            break  # Only log first event
                
                return data
            elif response.status_code == 401:
                print("Error: Invalid API key")
                return None
            elif response.status_code == 429:
                print("Warning: Rate limited")
                return None
            else:
                print(f"Error: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Error fetching events: {e}")
            return None
    
    def read_savedvariables(self):
        """Read current SavedVariables file"""
        path = self.get_savedvariables_path()
        if not path or not path.exists():
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse Lua table (basic parsing)
            # Look for LuminisbotEventsDB = { ... }
            if 'LuminisbotEventsDB' in content:
                return content
            return None
            
        except Exception as e:
            print(f"Error reading SavedVariables: {e}")
            return None
    
    def write_savedvariables(self, events_data):
        """Write events to both SavedVariables and a runtime-loadable data file"""
        path = self.get_savedvariables_path()
        if not path:
            print("Error: SavedVariables path not configured")
            return False
        
        try:
            # Ensure directory exists
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert events to Lua format
            lua_events = self.events_to_lua(events_data)
            timestamp = int(datetime.now().timestamp())
            
            # Build Lua content
            lua_content = f"""LuminisbotEventsDB = {{
    ["events"] = {lua_events},
    ["lastUpdate"] = {timestamp},
    ["guildId"] = "{self.guild_id}",
    ["apiKey"] = "{self.api_key}",
    ["autoSync"] = true,
}}
"""
            
            # Write to SavedVariables (for persistence)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(lua_content)
            
            # ALSO write to a runtime data file in the addon directory
            # This file can be loaded at runtime using Lua's loadfile()
            runtime_path = Path(self.wow_path) / "Interface" / "AddOns" / "LuminisbotEvents" / "CompanionData.lua"
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            
            runtime_content = f"""-- Auto-generated by Luminisbot Companion App
-- This file is loaded at runtime for real-time updates
-- Refresh the addon UI to load new events (no /reload needed!)
LuminisbotCompanionData = {{
    events = {lua_events},
    lastUpdate = {timestamp},
    timestamp = {timestamp},
    companionRunning = true,
    companionHeartbeat = {timestamp}
}}
"""
            
            with open(runtime_path, 'w', encoding='utf-8') as f:
                f.write(runtime_content)
            
            print(f"[WRITE] Wrote {len(events_data.get('events', []))} events")
            print(f"[WRITE] SavedVariables: {path}")
            print(f"[WRITE] Runtime file: {runtime_path}")
            return True
            
        except Exception as e:
            print(f"Error writing SavedVariables: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def events_to_lua(self, events_data):
        """Convert JSON events to Lua table format"""
        if not events_data or 'events' not in events_data:
            return "{}"
        
        events = events_data['events']
        if not events:
            return "{}"
        
        lua_entries = []
        for event in events:
            # Convert signups
            signups_lua = []
            for signup in event.get('signups', []):
                signup_lua = f"""        {{
            ["character"] = "{signup.get('character', '')}",
            ["realm"] = "{signup.get('realm', '')}",
            ["class"] = "{signup.get('class', '')}",
            ["role"] = "{signup.get('role', '')}",
            ["spec"] = "{signup.get('spec', '')}",
            ["status"] = "{signup.get('status', '')}"
        }}"""
                signups_lua.append(signup_lua)
            
            signups_str = ",\n".join(signups_lua) if signups_lua else ""
            
            event_lua = f"""    {{
        ["id"] = {event.get('id', 0)},
        ["title"] = "{event.get('title', '')}",
        ["date"] = "{event.get('date', '')}",
        ["time"] = "{event.get('time', '')}",
        ["createdBy"] = "{event.get('createdBy', '')}",
        ["logUrl"] = "{event.get('logUrl', '') or ''}",
        ["signups"] = {{
{signups_str}
        }}
    }}"""
            lua_entries.append(event_lua)
        
        return "{\n" + ",\n".join(lua_entries) + "\n}"
    
    def sync_loop(self):
        """Main sync loop"""
        print(f"[SYNC] Loop started (syncing every {SYNC_INTERVAL} seconds)")
        
        while self.running:
            try:
                # Fetch events from API
                print(f"[SYNC] Fetching events from API...")
                events_data = self.fetch_events()
                
                if events_data:
                    # Write to SavedVariables and runtime file
                    if self.write_savedvariables(events_data):
                        self.event_count = len(events_data.get('events', []))
                        self.last_sync = datetime.now()
                        print(f"[SYNC] ✓ Success! Synced {self.event_count} events at {self.last_sync.strftime('%H:%M:%S')}")
                        print(f"[SYNC] ⚠️  Type /reload in WoW to see the new events")
                    else:
                        print("[SYNC] ✗ Failed to write files")
                else:
                    print("[SYNC] ✗ No events data received from API")
                
            except Exception as e:
                print(f"[SYNC] ✗ Error: {e}")
                import traceback
                traceback.print_exc()
            
            # Wait for next sync
            print(f"[SYNC] Waiting {SYNC_INTERVAL} seconds until next sync...")
            for _ in range(SYNC_INTERVAL):
                if not self.running:
                    break
                time.sleep(1)
        
        print("[SYNC] Loop stopped")
    
    def start_sync(self):
        """Start syncing"""
        if self.running:
            return
        
        if not self.api_key or not self.guild_id:
            raise ValueError("API key and Guild ID required")
        
        if not self.get_savedvariables_path():
            raise ValueError("WoW path and account name required")
        
        self.running = True
        self.sync_thread = threading.Thread(target=self.sync_loop, daemon=True)
        self.sync_thread.start()
    
    def stop_sync(self):
        """Stop syncing"""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)


class CompanionGUI:
    def __init__(self):
        self.companion = LuminisbotCompanion()
        self.root = tk.Tk()
        self.root.title(f"Luminisbot Companion v{VERSION}")
        self.root.geometry("650x750")
        self.root.minsize(650, 680)  # Set minimum window size to ensure footer is always visible
        
        # Remove default title bar for custom design
        self.root.overrideredirect(True)
        
        # Enable dragging the frameless window
        self._drag_data = {"x": 0, "y": 0}
        
        # Set window icon (taskbar icon)
        try:
            logo_path = Path(__file__).parent / "luminis_logo.png"
            if logo_path.exists():
                # Load PNG and convert to PhotoImage for tkinter
                icon_image = Image.open(logo_path)
                # Create a square icon for better taskbar display
                icon_image = icon_image.resize((64, 64), Image.Resampling.LANCZOS)
                self.icon_photo = ImageTk.PhotoImage(icon_image)
                self.root.iconphoto(True, self.icon_photo)
        except Exception as e:
            print(f"Could not set window icon: {e}")
        
        # Set dark theme colors
        self.root.configure(bg=LUMINIS_BG)
        
        # Configure ttk styles
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure colors
        style.configure('TFrame', background=LUMINIS_BG)
        style.configure('TLabel', background=LUMINIS_BG, foreground=LUMINIS_FG)
        style.configure('Header.TLabel', background=LUMINIS_BG, foreground=LUMINIS_FG, font=('Arial', 18, 'bold'))
        style.configure('Subtitle.TLabel', background=LUMINIS_BG, foreground='#888888', font=('Arial', 10))
        style.configure('TButton', background=LUMINIS_ACCENT, foreground=LUMINIS_FG)
        style.map('TButton', background=[('active', '#6bb3ff')])
        style.configure('Success.TButton', background=LUMINIS_SUCCESS)
        style.configure('TLabelframe', background=LUMINIS_BG, foreground=LUMINIS_FG)
        style.configure('TLabelframe.Label', background=LUMINIS_BG, foreground=LUMINIS_FG)
        style.configure('TEntry', fieldbackground='#2a2a2a', foreground=LUMINIS_FG)
        
        # System tray icon
        self.tray_icon = None
        
        # Auto-updater
        self.updater = AutoUpdater(VERSION) if AUTO_UPDATE_AVAILABLE else None
        self.last_update_check = None
        
        # Check if setup is complete
        self.is_configured = self.check_configuration()
        self.show_settings = False  # Flag to show settings
        
        self.create_ui()
        
        # Create tray icon on startup
        self.create_tray_icon()
        
        self.update_status()
        
        # Start automatic update checker (every 60 seconds)
        if self.updater:
            self.check_updates_periodic()
        
        # Auto-start syncing if configured
        if self.is_configured and not self.show_settings:
            self.root.after(1000, self.auto_start_sync)
        
        # Handle window close button (X) - note: we removed the default title bar
        # So we'll handle this with our custom close button
    
    def check_configuration(self):
        """Check if the app is properly configured"""
        return (self.companion.api_key and 
                self.companion.guild_id and 
                self.companion.wow_path and 
                self.companion.account_name)
    
    def auto_start_sync(self):
        """Auto-start syncing if configured"""
        try:
            self.companion.start_sync()
            self.log_status("🔄 Auto-started syncing...")
            self.log_status("ℹ️  After sync completes, use /reload in WoW or click Refresh in addon")
            if hasattr(self, 'start_btn'):
                self.start_btn.config(state=tk.DISABLED)
            if hasattr(self, 'stop_btn'):
                self.stop_btn.config(state=tk.NORMAL)
        except Exception as e:
            self.log_status(f"❌ Failed to auto-start: {e}")
    
    def create_custom_title_bar(self):
        """Create custom title bar for frameless window"""
        title_bar = tk.Frame(self.root, bg='#2a2a2a', height=40)
        title_bar.pack(fill=tk.X, side=tk.TOP)
        
        # Make title bar draggable
        title_bar.bind('<Button-1>', self.start_drag)
        title_bar.bind('<B1-Motion>', self.do_drag)
        
        # App title and icon
        title_label = tk.Label(
            title_bar, 
            text=f"  Luminisbot Companion v{VERSION}", 
            bg='#2a2a2a', 
            fg=LUMINIS_FG,
            font=('Arial', 10)
        )
        title_label.pack(side=tk.LEFT, padx=10, pady=8)
        title_label.bind('<Button-1>', self.start_drag)
        title_label.bind('<B1-Motion>', self.do_drag)
        
        # Control buttons on the right
        btn_frame = tk.Frame(title_bar, bg='#2a2a2a')
        btn_frame.pack(side=tk.RIGHT)
        
        # Settings button (only show if configured)
        if self.is_configured:
            settings_btn = tk.Button(
                btn_frame,
                text="⚙",
                bg='#2a2a2a',
                fg=LUMINIS_FG,
                font=('Arial', 14),
                bd=0,
                padx=15,
                pady=5,
                command=self.toggle_settings,
                activebackground='#3a3a3a'
            )
            settings_btn.pack(side=tk.LEFT)
        
        # Minimize to tray button
        minimize_btn = tk.Button(
            btn_frame,
            text="−",
            bg='#2a2a2a',
            fg=LUMINIS_FG,
            font=('Arial', 14),
            bd=0,
            padx=15,
            pady=5,
            command=self.minimize_to_tray,
            activebackground='#3a3a3a'
        )
        minimize_btn.pack(side=tk.LEFT)
        
        # Close button
        close_btn = tk.Button(
            btn_frame,
            text="×",
            bg='#2a2a2a',
            fg='#ff4444',
            font=('Arial', 16),
            bd=0,
            padx=15,
            pady=2,
            command=self.quit_app,
            activebackground='#ff4444',
            activeforeground='#ffffff'
        )
        close_btn.pack(side=tk.LEFT)
    
    def start_drag(self, event):
        """Start dragging the window"""
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y
    
    def do_drag(self, event):
        """Handle window dragging"""
        x = self.root.winfo_x() + (event.x - self._drag_data["x"])
        y = self.root.winfo_y() + (event.y - self._drag_data["y"])
        self.root.geometry(f"+{x}+{y}")
    
    def add_resize_grip(self):
        """Add a resize grip to bottom-right corner for frameless window"""
        # Create a container for the resize grip with padding
        grip_container = tk.Frame(self.root, bg=LUMINIS_BG, width=30, height=30)
        grip_container.place(relx=1.0, rely=1.0, anchor='se', x=-10, y=-10)
        
        # Use three diagonal lines to make it more visible as a resize handle
        grip = tk.Label(
            grip_container,
            text="≡",  # Three horizontal lines
            font=('Arial', 14, 'bold'),
            fg='#999999',
            bg=LUMINIS_BG,
            cursor="size_nw_se",
            padx=5,
            pady=5
        )
        grip.pack()
        
        self._resize_data = {"width": 0, "height": 0}
        
        def start_resize(event):
            self._resize_data["width"] = self.root.winfo_width()
            self._resize_data["height"] = self.root.winfo_height()
            self._resize_data["x"] = event.x_root
            self._resize_data["y"] = event.y_root
            grip.config(fg='#cccccc')  # Brighten on click
        
        def do_resize(event):
            delta_x = event.x_root - self._resize_data["x"]
            delta_y = event.y_root - self._resize_data["y"]
            new_width = max(650, self._resize_data["width"] + delta_x)
            new_height = max(680, self._resize_data["height"] + delta_y)
            self.root.geometry(f"{new_width}x{new_height}")
        
        def end_resize(event):
            grip.config(fg='#999999')  # Reset color
        
        def on_hover_enter(event):
            grip.config(fg='#cccccc')  # Brighten on hover
        
        def on_hover_leave(event):
            grip.config(fg='#999999')  # Reset color
        
        grip.bind("<Button-1>", start_resize)
        grip.bind("<B1-Motion>", do_resize)
        grip.bind("<ButtonRelease-1>", end_resize)
        grip.bind("<Enter>", on_hover_enter)
        grip.bind("<Leave>", on_hover_leave)
    
    def toggle_settings(self):
        """Toggle settings view"""
        self.show_settings = not self.show_settings
        # Remember sync state
        was_syncing = self.companion.running
        # Clear and rebuild UI (keep title bar)
        for widget in self.root.winfo_children():
            if not isinstance(widget, tk.Frame) or widget.winfo_y() > 40:  # Keep title bar
                widget.destroy()
        self.create_main_content()
        # Restore button states if we were syncing
        if was_syncing and hasattr(self, 'start_btn') and hasattr(self, 'stop_btn'):
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
    
    def create_ui(self):
        """Create GUI"""
        # Custom title bar
        self.create_custom_title_bar()
        self.create_main_content()
    
    def create_main_content(self):
        """Create the main content area (setup wizard or main view)"""
        # Header with logo
        header_frame = ttk.Frame(self.root, padding=20)
        header_frame.pack(fill=tk.X)
        
        # Try to load logo
        logo_path = Path(__file__).parent / "luminis_logo.png"
        if logo_path.exists():
            try:
                logo_image = Image.open(logo_path)
                logo_image = logo_image.resize((200, 90), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(logo_image)
                logo_label = tk.Label(header_frame, image=self.logo_photo, bg=LUMINIS_BG)
                logo_label.pack(pady=(0, 10))
            except Exception as e:
                print(f"Could not load logo: {e}")
        
        ttk.Label(
            header_frame,
            text="Luminisbot Companion",
            style='Header.TLabel'
        ).pack()
        
        ttk.Label(
            header_frame,
            text="Real-time event syncing for World of Warcraft",
            style='Subtitle.TLabel'
        ).pack(pady=(5, 0))
        
        # Show configuration only if not configured OR settings is toggled on
        if not self.is_configured or self.show_settings:
            self.create_configuration_section()
        
        # Show control buttons only if configured and not in settings mode
        if self.is_configured and not self.show_settings:
            self.create_control_section()
        
        # Footer and status log
        self.create_footer_and_status()
    
    def create_configuration_section(self):
        """Create configuration UI"""
        # Configuration frame
        config_frame = ttk.LabelFrame(self.root, text="Setup" if not self.is_configured else "Settings", padding=10)
        config_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Subscription string
        ttk.Label(config_frame, text="Subscription String:").grid(row=0, column=0, sticky=tk.W, pady=5)
        ttk.Label(config_frame, text="(from /subscribe in Discord)", font=('Arial', 8), foreground='#888888').grid(row=0, column=1, sticky=tk.W, pady=(0, 2))
        
        self.sub_entry = ttk.Entry(config_frame, width=50)
        self.sub_entry.grid(row=1, column=1, pady=(0, 10), padx=5)
        if self.companion.api_key and self.companion.guild_id:
            sub_string = base64.b64encode(f"{self.companion.guild_id}:{self.companion.api_key}".encode()).decode()
            self.sub_entry.insert(0, sub_string)
        
        ttk.Button(config_frame, text="Apply", command=self.apply_subscription).grid(row=1, column=2, pady=(0, 10))
        
        # WoW Path
        ttk.Label(config_frame, text="WoW Install Path:").grid(row=2, column=0, sticky=tk.W, pady=5)
        ttk.Label(config_frame, text="(select your _retail_ folder)", font=('Arial', 8), foreground='#888888').grid(row=2, column=1, sticky=tk.W, pady=(0, 2))
        
        self.wow_path_entry = ttk.Entry(config_frame, width=50)
        self.wow_path_entry.grid(row=3, column=1, pady=(0, 10), padx=5)
        
        # Auto-detect WoW path if not set
        if not self.companion.wow_path:
            detected_path = self.auto_detect_wow_path()
            if detected_path:
                self.wow_path_entry.insert(0, detected_path)
                self.companion.wow_path = detected_path
        else:
            self.wow_path_entry.insert(0, self.companion.wow_path)
        
        self.wow_path_entry.bind('<FocusOut>', self.on_wow_path_change)
        
        ttk.Button(config_frame, text="Browse", command=self.browse_wow_path).grid(row=3, column=2, pady=(0, 10))
        
        # Account Name with dropdown
        ttk.Label(config_frame, text="WoW Account:").grid(row=4, column=0, sticky=tk.W, pady=5)
        ttk.Label(config_frame, text="(select your WoW account folder)", font=('Arial', 8), foreground='#888888').grid(row=4, column=1, sticky=tk.W, pady=(0, 2))
        
        self.account_var = tk.StringVar()
        self.account_dropdown = ttk.Combobox(config_frame, textvariable=self.account_var, width=47, state='readonly')
        self.account_dropdown.grid(row=5, column=1, pady=(0, 5), padx=5)
        
        # Try to populate dropdown
        self.refresh_accounts()
        if self.companion.account_name:
            self.account_var.set(self.companion.account_name)
        
        # Save/Start button
        btn_text = "Start Syncing" if not self.is_configured else "Save & Close"
        save_btn = ttk.Button(config_frame, text=btn_text, command=self.save_configuration, style='Success.TButton')
        save_btn.grid(row=6, column=1, pady=10, sticky=tk.E)
    
    def create_control_section(self):
        """Create control buttons for main view"""
        # Control frame
        control_frame = ttk.Frame(self.root, padding=10)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.start_btn = ttk.Button(control_frame, text="Start Syncing", command=self.start_sync)
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = ttk.Button(control_frame, text="Stop Syncing", command=self.stop_sync, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)
    
    def create_footer_and_status(self):
        """Create footer and status log"""
        # Footer (moved above status log to ensure it's always visible)
        footer_frame = ttk.Frame(self.root, padding=10)
        footer_frame.pack(fill=tk.X, padx=10, pady=(5, 0))
        
        ttk.Label(
            footer_frame,
            text=f"💡 After sync: /reload WoW or click Refresh in addon  |  Get subscription: /subscribe in Discord  |  v{VERSION}",
            style='Subtitle.TLabel'
        ).pack()
        
        ttk.Label(
            footer_frame,
            text="Luminis Gaming © 2025",
            style='Subtitle.TLabel'
        ).pack()
        
        # Status frame (with extra padding on sides to prevent overlap with resize grip)
        status_frame = ttk.LabelFrame(self.root, text="Status Log", padding=10)
        status_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 15))
        
        self.status_text = tk.Text(
            status_frame, 
            height=18, 
            width=70, 
            state=tk.DISABLED,
            bg='#2a2a2a',
            fg=LUMINIS_FG,
            font=('Consolas', 9),
            relief=tk.FLAT,
            padx=10,
            pady=10
        )
        self.status_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(status_frame, command=self.status_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_text.config(yscrollcommand=scrollbar.set)
        
        # Add resize grip at bottom-right corner
        self.add_resize_grip()
    
    def refresh_accounts(self):
        """Refresh the account dropdown"""
        accounts = self.companion.detect_wow_accounts()
        if accounts:
            self.account_dropdown['values'] = accounts
            if not self.account_var.get() and accounts:
                self.account_var.set(accounts[0])  # Select first account by default
            
            # If only one account exists, auto-save and hide complexity
            if len(accounts) == 1:
                self.account_var.set(accounts[0])
                self.companion.account_name = accounts[0]
                self.log_status(f"✅ Auto-detected WoW account: {accounts[0]}")
        else:
            self.account_dropdown['values'] = []
    
    def on_wow_path_change(self, event=None):
        """Called when WoW path changes"""
        self.companion.wow_path = self.wow_path_entry.get().strip()
        self.refresh_accounts()
    
    def save_configuration(self):
        """Save configuration and start syncing or close settings"""
        try:
            sub_string = self.sub_entry.get().strip()
            if not sub_string:
                messagebox.showerror("Error", "Please enter a subscription string")
                return
            
            wow_path = self.wow_path_entry.get().strip()
            if not wow_path:
                messagebox.showerror("Error", "Please select your WoW _retail_ folder")
                return
            
            account = self.account_var.get().strip()
            if not account:
                messagebox.showerror("Error", "Please select your WoW account")
                return
            
            guild_id, api_key = self.companion.parse_subscription_string(sub_string)
            self.companion.guild_id = guild_id
            self.companion.api_key = api_key
            self.companion.wow_path = wow_path
            self.companion.account_name = account
            self.companion.save_config()
            
            self.is_configured = True
            self.log_status("✅ Configuration saved successfully")
            
            # If this was initial setup, rebuild UI and start syncing
            if not self.show_settings:
                messagebox.showinfo("Setup Complete", "Configuration saved! Syncing will start automatically.")
                # Rebuild UI to show main view
                for widget in self.root.winfo_children():
                    if not isinstance(widget, tk.Frame) or widget.winfo_y() > 40:  # Keep title bar
                        widget.destroy()
                self.show_settings = False
                self.create_main_content()
                # Auto-start syncing
                self.root.after(500, self.auto_start_sync)
            else:
                # Just close settings view - rebuild UI
                was_syncing = self.companion.running
                for widget in self.root.winfo_children():
                    if not isinstance(widget, tk.Frame) or widget.winfo_y() > 40:  # Keep title bar
                        widget.destroy()
                self.show_settings = False
                self.create_main_content()
                # Restore button states if syncing
                if was_syncing and hasattr(self, 'start_btn') and hasattr(self, 'stop_btn'):
                    self.start_btn.config(state=tk.DISABLED)
                    self.stop_btn.config(state=tk.NORMAL)
                messagebox.showinfo("Success", "Settings saved!")
            
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    def apply_subscription(self):
        """Apply subscription string (kept for compatibility)"""
        self.save_configuration()
    
    def auto_detect_wow_path(self):
        """Try to auto-detect WoW _retail_ folder in standard locations"""
        # Common WoW installation paths
        possible_paths = [
            Path("C:/Program Files (x86)/World of Warcraft/_retail_"),
            Path("C:/Program Files/World of Warcraft/_retail_"),
            Path(os.path.expandvars("%ProgramFiles(x86)%/World of Warcraft/_retail_")),
            Path(os.path.expandvars("%ProgramFiles%/World of Warcraft/_retail_")),
        ]
        
        for path in possible_paths:
            if path.exists() and path.is_dir():
                # Verify it's actually a WoW retail folder by checking for WTF directory
                if (path / "WTF").exists():
                    return str(path)
        
        return None
    
    def browse_wow_path(self):
        """Browse for WoW _retail_ directory"""
        # Start in the detected or current path, or default to Program Files
        initial_dir = self.wow_path_entry.get() or "C:/Program Files (x86)/World of Warcraft"
        
        path = filedialog.askdirectory(
            title="Select your _retail_ folder (inside World of Warcraft)", 
            initialdir=initial_dir
        )
        if path:
            self.wow_path_entry.delete(0, tk.END)
            self.wow_path_entry.insert(0, path)
            self.on_wow_path_change()
    
    def start_sync(self):
        """Start syncing"""
        try:
            # Apply current config
            self.apply_subscription()
            
            # Start sync
            self.companion.start_sync()
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.log_status("🔄 Syncing started...")
            
        except Exception as e:
            messagebox.showerror("Error", str(e))
    
    def stop_sync(self):
        """Stop syncing"""
        self.companion.stop_sync()
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.log_status("⏸️ Syncing stopped")
    
    def log_status(self, message):
        """Add message to status log"""
        self.status_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)
    
    def update_status(self):
        """Update status display"""
        if self.companion.running and self.companion.last_sync:
            elapsed = (datetime.now() - self.companion.last_sync).seconds
            # Only log if status changed significantly (every 60 seconds)
            if elapsed % 60 < 5:  # Log around each minute mark
                self.log_status(f"📊 {self.companion.event_count} events synced - /reload WoW to see updates")
        
        self.root.after(5000, self.update_status)
    
    def create_tray_icon(self):
        """Create system tray icon"""
        if self.tray_icon:
            return
        
        # Try to load Luminis logo for tray icon
        logo_path = Path(__file__).parent / "luminis_logo.png"
        if logo_path.exists():
            try:
                icon_image = Image.open(logo_path)
                # Resize to standard tray icon size
                icon_image = icon_image.resize((64, 64), Image.Resampling.LANCZOS)
            except Exception as e:
                print(f"Could not load logo for tray: {e}")
                # Fallback to simple icon
                icon_image = self.create_default_icon()
        else:
            # Fallback to simple icon
            icon_image = self.create_default_icon()
        
        menu = pystray.Menu(
            pystray.MenuItem("Show", self.show_window),
            pystray.MenuItem("Check for Updates", self.check_updates_manual) if self.updater else None,
            pystray.MenuItem("About", self.show_about),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self.quit_app)
        )
        
        # Add left-click handler to show window directly
        self.tray_icon = pystray.Icon(
            "luminisbot", 
            icon_image, 
            "Luminisbot Companion", 
            menu,
            on_click=self.on_tray_click
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()
    
    def create_default_icon(self):
        """Create a default icon if logo not available"""
        icon_image = Image.new('RGB', (64, 64), color='#4a9eff')
        draw = ImageDraw.Draw(icon_image)
        draw.ellipse([8, 8, 56, 56], fill='white')
        draw.ellipse([16, 16, 48, 48], fill='#4a9eff')
        return icon_image
    
    def minimize_to_tray(self):
        """Minimize to system tray"""
        self.root.withdraw()
    
    def on_tray_click(self, icon, item):
        """Handle tray icon left-click to show window"""
        self.show_window()
    
    def show_window(self):
        """Show window from tray"""
        self.root.deiconify()
    
    def quit_app(self):
        """Quit application"""
        self.companion.stop_sync()
        if self.tray_icon:
            self.tray_icon.stop()
        self.root.destroy()
        sys.exit(0)
    
    def check_updates_periodic(self):
        """Check for updates periodically (every 60 seconds)"""
        if not self.updater:
            return
        
        def check():
            has_update, version, url, notes = self.updater.check_for_updates()
            
            if has_update:
                # Show update notification
                self.root.after(0, lambda: self.show_update_notification(version))
        
        # Run check in background thread
        threading.Thread(target=check, daemon=True).start()
        
        # Schedule next check in 60 seconds
        self.root.after(60000, self.check_updates_periodic)
    
    def show_update_notification(self, version):
        """Show update notification toast"""
        result = messagebox.askyesno(
            "Update Available",
            f"Version {version} is available!\n\n"
            f"Current version: {VERSION}\n"
            f"New version: {version}\n\n"
            f"Would you like to download and install it now?",
            icon='info'
        )
        
        if result:
            self.download_and_install_update()
    
    def check_updates_silent(self):
        """Check for updates silently (deprecated - now using periodic checks)"""
        pass
    
    def check_updates_manual(self):
        """Check for updates when user clicks menu"""
        if not self.updater:
            messagebox.showinfo("Updates", "Auto-update not available")
            return
        
        self.log_status("🔍 Checking for updates...")
        
        # Run in thread to avoid blocking UI
        def check():
            has_update, version, url, notes = self.updater.check_for_updates()
            
            if has_update:
                # Ask user if they want to update
                self.root.after(0, lambda: self.prompt_update(version, notes))
            else:
                self.root.after(0, lambda: messagebox.showinfo(
                    "No Updates",
                    f"You're running the latest version (v{VERSION})"
                ))
        
        threading.Thread(target=check, daemon=True).start()
    
    def prompt_update(self, new_version, release_notes):
        """Show update dialog"""
        msg = f"Version {new_version} is available!\n\n"
        msg += f"Current version: {VERSION}\n\n"
        msg += "Release Notes:\n" + release_notes[:200]
        
        if messagebox.askyesno("Update Available", msg + "\n\nDownload and install now?"):
            self.download_and_install_update()
    
    def download_and_install_update(self):
        """Download and install update"""
        # Create progress window
        progress_window = tk.Toplevel(self.root)
        progress_window.title("Updating...")
        progress_window.geometry("400x150")
        progress_window.resizable(False, False)
        progress_window.transient(self.root)
        
        ttk.Label(progress_window, text="Downloading update...").pack(pady=20)
        
        progress_bar = ttk.Progressbar(progress_window, length=300, mode='determinate')
        progress_bar.pack(pady=10)
        
        status_label = ttk.Label(progress_window, text="Starting download...")
        status_label.pack(pady=10)
        
        def update_progress(downloaded, total):
            if total > 0:
                percent = (downloaded / total) * 100
                progress_bar['value'] = percent
                status_label.config(text=f"Downloaded: {downloaded//1024} KB / {total//1024} KB")
        
        def do_update():
            try:
                # Download
                success, file_path, error = self.updater.download_update(update_progress)
                
                if not success:
                    self.root.after(0, lambda: messagebox.showerror("Update Failed", error))
                    self.root.after(0, progress_window.destroy)
                    return
                
                # Install
                self.root.after(0, lambda: status_label.config(text="Installing update..."))
                success, error = self.updater.install_update(file_path)
                
                if success:
                    self.root.after(0, lambda: messagebox.showinfo(
                        "Update Complete",
                        "The app will now restart with the new version."
                    ))
                    self.root.after(0, self.quit_app)
                else:
                    self.root.after(0, lambda: messagebox.showerror("Update Failed", error))
                    self.root.after(0, progress_window.destroy)
                    
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("Update Error", str(e)))
                self.root.after(0, progress_window.destroy)
        
        threading.Thread(target=do_update, daemon=True).start()
    
    def show_about(self):
        """Show about dialog"""
        about_text = f"""Luminisbot Companion v{VERSION}

Real-time event syncing between Discord and World of Warcraft

© 2025 Luminis Gaming
https://github.com/Luminis-Gaming/Luminisbot

This software is open source and licensed under MIT License."""
        
        messagebox.showinfo("About", about_text)
    
    def run(self):
        """Run GUI"""
        self.root.mainloop()


if __name__ == "__main__":
    print(f"Luminisbot Companion v{VERSION}")
    print("="*50)
    
    app = CompanionGUI()
    app.run()
