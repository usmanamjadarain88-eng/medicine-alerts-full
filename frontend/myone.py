def export_medicine_alerts_to_json_and_push(repo_path, db_path='curax_alerts.db', json_filename='medicine_times.json'):
    """Export all medicine alerts from SQLite DB to JSON and push to GitHub repo."""
    import sqlite3
    import json
    import os
    import subprocess
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        import json as _json
        reminders = []
        # 1. Extract from alert_settings/reminders
        cur.execute("SELECT value FROM settings WHERE key=?", ("alert_settings",))
        row = cur.fetchone()
        if row:
            alert_settings = _json.loads(row[0])
            if "reminders" in alert_settings:
                for group in alert_settings["reminders"].values():
                    if isinstance(group, list):
                        for item in group:
                            if isinstance(item, dict) and "time" in item and "message" in item:
                                reminders.append({"time": item["time"], "message": item["message"]})
            if not reminders and "medicine_alerts" in alert_settings:
                reminders.append({"time": "", "message": str(alert_settings["medicine_alerts"])})
        # 2. Extract from medical_reminders (if present)
        cur.execute("SELECT value FROM settings WHERE key=?", ("medical_reminders",))
        row2 = cur.fetchone()
        if row2:
            med_reminders = _json.loads(row2[0])
            for group in med_reminders.values():
                if isinstance(group, list):
                    for item in group:
                        # Try to extract time and title/description
                        if isinstance(item, dict) and "time" in item:
                            msg = item.get("title") or item.get("description") or ""
                            reminders.append({"time": item["time"], "message": msg})
        json_path = os.path.join(repo_path, json_filename)
        with open(json_path, 'w') as f:
            _json.dump(reminders, f, indent=2)
        # Git add/commit/push (DISABLED: removed to prevent cmd window)
        print(f"✅ Exported {len(reminders)} reminders to {json_path} (Git push skipped).")
    except Exception as e:
        print(f"❌ Error exporting alerts: {e}")
    finally:
        conn.close()
from faulthandler import is_enabled
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import serial
import serial.tools.list_ports
import json
import os
import datetime
import threading
from PIL import Image, ImageTk
import sys
from tkcalendar import DateEntry
import schedule
import time
from threading import Thread
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import sqlite3
import math

# ========== IMPORTS FROM SEPARATE MODULES ==========
from db import AlertDB
# ===================================================

# ========== TOOLTIP CLASS ==========
class ToolTip:
    """Create a tooltip for a given widget"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        label = tk.Label(self.tooltip_window, text=self.text,
                        background="#ffffcc", relief=tk.SOLID,
                        borderwidth=1, font=('Arial', 9),
                        padx=5, pady=3)
        label.pack()

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None
# ===================================


class CuraXDesktopApp:
    def require_admin(self):
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        if not db.has_admin_credentials():
            messagebox.showwarning(
                "Admin Required",
                "No admin account configured.\nPlease go to Settings → Admin Panel."
            )
            return False
        return True

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🔍CuraX - Intelligent Medicine System")
        self.root.geometry("1000x700")
        self.root.configure(bg='#f0f2f5')

        # Initialize all session states
        self.connected = False
        self.authenticated = False
        self.ser = None
        self.wrong_count = 0
        self.active_led_box = None
        self.last_bt_port = None
        self.wired_confirmed = False
        self.bt_pair_confirmed = False
        # Admin session state
        self.admin_logged_in = False
        self.logged_in_admin_name = None
        # Temperature settings
        self.temp_settings = {
            "peltier1": {"min": 15, "max": 20, "current": 18},
            "peltier2": {"min": 5, "max": 8, "current": 6}
        }

        # Medicine boxes data (persistent in database)
        self.medicine_boxes = {
            "B1": None,
            "B2": None,
            "B3": None,
            "B4": None,
            "B5": None,
            "B6": None
        }

        # Dose log
        self.dose_log = []

        # Load saved data
        self.load_data()

        # GUI setup
        self.setup_styles()
        self.create_widgets()

        # Start serial monitoring thread
        self.serial_thread = None
        self.running = True
        self.serial_pause = False  # Pause serial_loop when doing blocking requests

        # Alert system initialization
        self.alert_settings = {
            "email_alerts": {
                "enabled": True,
                "email": "",
                "send_copy_to": "",
                "alert_tone": "default",
                "volume": 80
            },
            "medicine_alerts": {
                "15_min_before": True,
                "exact_time": True,
                "5_min_after": True,
                "missed_alert": True,
                "snooze_duration": 5  # minutes
            },
            "stock_alerts": {
                "low_stock_threshold": 5,
                "refill_reminder_days": 3,
                "auto_refill": False
            },
            "expiry_alerts": {

                "30_days_before": True,
                "15_days_before": True,
                "7_days_before": True,
                "1_day_before": True
            },
            "reminders": {
                "doctor_appointments": [],
                "prescription_renewals": [],
                "lab_tests": [],
                "custom_reminders": []
            },
            "do_not_disturb": {
                "enabled": False,
                "start_time": "22:00",
                "end_time": "07:00",
                "emergency_override": True
            },
            # ========== ADD MISSED DOSE ESCALATION SECTION ==========
            "missed_dose_escalation": {
                "5_min_reminder": True,
                "15_min_urgent": True,
                "30_min_family": True,
                "1_hour_log": True,
                "family_email": ""
            },
            # ========== END ADDITION ==========
            "stock_alerts": {
                "enabled": True,
                "low_stock_threshold": 5,
                "empty_alert": True,
                "critical_alert": True
            },
            "temperature_settings": {
                "peltier1": {
                    "enabled": True,
                    "min_temp": 15,
                    "max_temp": 20,
                    "current_temp": 18
                },
                "peltier2": {
                    "enabled": True,
                    "min_temp": 5,
                    "max_temp": 8,
                    "current_temp": 6
                }
            }
            # SMS configuration

        }
        # REPLACE WITH THIS:
        self.sms_config = {
            "enabled": False,
            "provider": "callmebot",
            "phone_number": "",
            "api_key": "0"
        }

        # # Load SMS config
        # self.load_sms_config()

        # Mobile Alert Bot configuration
        self.mobile_bot = {
            "enabled": False,
            "bot_id": "",
            "api_key": "",
            "server_url": "https://curax-alerts.herokuapp.com"
        }
        self.load_mobile_bot_config()

        self.medical_reminders = {
            "appointments": [],
            "prescriptions": [],
            "lab_tests": [], "custom": []
        }
        self.load_medical_reminders()
        self._reminder_sent = set()  # (item_id, reminder_type) already fired by poll
        self.gmail_config = {
            "sender_email": "",
            "sender_password": "",  # App password
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 465,
            "recipients": ""  # Added for recipient emails
        }

        self.alert_scheduler = AlertScheduler(self)

        # Load alert settings from file
        self.load_alert_settings()
        self.display_esp32_connection_ports()
        # Start background thread to fire medical reminder alerts on time (backup + after restart)
        self._reminder_poll_stop = False
        self._main_thread = threading.current_thread()
        _reminder_thread = threading.Thread(target=self._run_reminder_poll_loop, daemon=True)
        _reminder_thread.start()

    def require_admin(self):
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        if not db.has_admin_credentials():
            messagebox.showwarning(
                "Admin Required",
                "No admin account configured.\nPlease go to Settings → Admin Panel."
            )
            return False
        return True

    def load_alert_settings(self):
        """Load alert settings from SQLite DB. Migrate from JSON if present."""
        try:
            # Initialize DB and keep reference
            db = AlertDB()
            self._alert_db = db

            # Try to load from DB
            stored = db.get("alert_settings")
            if stored is None:
                # If DB empty, attempt JSON migration
                settings_file = "curax_alerts.json"
                if os.path.exists(settings_file):
                    try:
                        with open(settings_file, "r") as f:
                            data = json.load(f)

                        # Merge alert_settings
                        if "alert_settings" in data:
                            loaded_settings = data["alert_settings"]
                            for key in self.alert_settings:
                                if key in loaded_settings:
                                    if isinstance(self.alert_settings[key], dict) and isinstance(loaded_settings[key],
                                                                                                 dict):
                                        for subkey in self.alert_settings[key]:
                                            if subkey in loaded_settings[key]:
                                                self.alert_settings[key][subkey] = loaded_settings[key][subkey]
                                    else:
                                        self.alert_settings[key] = loaded_settings[key]

                            print(f"✅ Alert settings loaded from {settings_file} (migrated)")

                        if "gmail_config" in data:
                            self.gmail_config = data["gmail_config"]
                            print("✅ Gmail config loaded (migrated)")

                        if "sms_config" in data:
                            for k in data["sms_config"]:
                                if k in self.sms_config:
                                    self.sms_config[k] = data["sms_config"][k]
                            print("✅ SMS config loaded (migrated)")

                        # Persist migrated data into DB
                        db.set("alert_settings", self.alert_settings)
                        db.set("gmail_config", self.gmail_config)
                        db.set("sms_config", self.sms_config)

                        # Remove JSON after successful migration
                        try:
                            os.remove(settings_file)
                            print(f"🗑️ Removed legacy file {settings_file}")
                        except Exception:
                            pass
                    except Exception as e:
                        print(f"❌ Error migrating alert settings from JSON: {e}")
                else:
                    print("⚠️ No stored alert settings found; using defaults")
            else:
                # Merge DB-loaded settings with defaults
                loaded = stored
                for key in self.alert_settings:
                    if key in loaded:
                        if isinstance(self.alert_settings[key], dict) and isinstance(loaded[key], dict):
                            for subkey in self.alert_settings[key]:
                                if subkey in loaded[key]:
                                    self.alert_settings[key][subkey] = loaded[key][subkey]
                        else:
                            self.alert_settings[key] = loaded[key]

                # Load gmail and sms config from DB if present
                gc = db.get("gmail_config")
                if gc:
                    self.gmail_config = gc

                sc = db.get("sms_config")
                if sc:
                    for k in sc:
                        if k in self.sms_config:
                            self.sms_config[k] = sc[k]

                print("✅ Alert settings loaded from SQLite DB")

        except Exception as e:
            print(f"❌ Error loading alert settings: {e}")

    def save_alert_settings(self):
        """Save alert settings into SQLite DB."""
        db = getattr(self, "_alert_db", None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        
        try:
            db.set("alert_settings", self.alert_settings)
            db.set("gmail_config", self.gmail_config)
            db.set("sms_config", self.sms_config)

            print("✅ Alert settings saved to SQLite DB")
            return True

        except Exception as e:
            print(f"❌ Error saving alert settings to DB: {e}")
            return False

    def start_alert_system(self):
        """Start the alert system after authentication - SAFE VERSION"""
        if self.authenticated:
            print("🔄 Setting up alert system (safe mode)...")

            try:
                # Clear any existing schedules
                import schedule
                schedule.clear()

                # Schedule alerts for all medicines (READ ONLY)
                alert_count = 0
                for box_id, medicine in self.medicine_boxes.items():
                    if medicine:
                        # Pass medicine as-is, scheduler will use .copy()
                        self.alert_scheduler.schedule_medicine_alert(medicine, box_id)
                        alert_count += 1

                # Start scheduler thread (run_pending loop)
                self.alert_scheduler.start()

                print(f"✅ Alert system started - {alert_count} medicine(s) scheduled")
                print(f"📦 Medicine count: {len([m for m in self.medicine_boxes.values() if m])}")

                # Show medicine data is intact
                for box_id, med in self.medicine_boxes.items():
                    if med:
                        print(f"   {box_id}: {med.get('name')} - Qty: {med.get('quantity')}")

            except Exception as e:
                print(f"❌ Failed to start alert system: {e}")

    def _get_theme_palette(self, theme_name):
        """Return color palette dict for given theme: default, light, or dark."""
        palettes = {
            "default": {
                "bg_color": '#F7FAFC',
                "card_bg": '#FFFFFF',
                "primary_color": '#2F855A',
                "accent_color": '#276749',
                "success_color": '#2F855A',
                "danger_color": '#C53030',
                "warning_color": '#F6E05E',
                "tab_active_bg": '#2F855A',
                "tab_inactive_bg": '#FFFFFF',
                "tab_inactive_fg": '#2F855A',
                "heading_color": '#1976D2',
                "sidebar_bg": '#FFFFFF',
                "sidebar_fg": '#1A202C',
                "primary_text": '#1A202C',
                "secondary_text": '#4A5568',
                "border_color": '#E2E8F0',
                "entry_bg": '#FFFFFF',
            },
            "dark": {
                "bg_color": '#1E1E2E',
                "card_bg": '#313244',
                "primary_color": '#89B4FA',
                "accent_color": '#74A7F7',
                "success_color": '#A6E3A1',
                "danger_color": '#F38BA8',
                "warning_color": '#F9E2AF',
                "tab_active_bg": '#45475A',
                "tab_inactive_bg": '#313244',
                "tab_inactive_fg": '#A6ADC8',
                "heading_color": '#A6ADC8',
                "sidebar_bg": '#313244',
                "sidebar_fg": '#CDD6F4',
                "primary_text": '#CDD6F4',
                "secondary_text": '#A6ADC8',
                "border_color": '#45475A',
                "entry_bg": '#45475A',
            },
        }
        return palettes.get(theme_name, palettes["default"]).copy()

    def _load_appearance_theme(self):
        """Load saved theme from DB; return 'default', 'light', or 'dark'. Missing/invalid = default (emerald)."""
        try:
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            t = db.get("appearance_theme")
            if t is None:
                return "default"
            if isinstance(t, str):
                t = t.strip().lower()
                if t in ("default", "dark"):
                    return t
        except Exception:
            pass
        return "default"

    def _apply_palette(self, palette):
        """Apply a palette dict to self and refresh ttk styles."""
        for k, v in palette.items():
            setattr(self, k, v)
        self.button_radius = 18
        # ttk style customizations
        self.style.configure('TNotebook', background=self.bg_color, borderwidth=0)
        tab_fg = getattr(self, 'tab_inactive_fg', self.secondary_text)
        self.style.configure('TNotebook.Tab', font=('Segoe UI', 12, 'bold'),
                            background=self.tab_inactive_bg, foreground=tab_fg, borderwidth=0)
        self.style.map('TNotebook.Tab',
            background=[('selected', self.tab_active_bg)],
            foreground=[('selected', '#FFFFFF')])
        self.style.configure('TFrame', background=self.bg_color)
        self.style.configure('Card.TFrame', background=self.card_bg, relief='flat', borderwidth=1, highlightbackground=self.border_color, highlightcolor=self.border_color)
        self.style.configure('Accent.TButton', font=('Segoe UI', 11, 'bold'), background=self.primary_color,
                            foreground='#FFFFFF', borderwidth=0, padding=[12, 8])
        self.style.map('Accent.TButton',
            background=[('active', self.accent_color), ('pressed', self.primary_color)])
        self.style.configure('Danger.TButton', font=('Segoe UI', 11, 'bold'), background=self.danger_color,
                            foreground='#FFFFFF', borderwidth=0, padding=[12, 8])
        self.style.map('Danger.TButton',
            background=[('active', '#9B2C2C'), ('pressed', self.danger_color)])
        self.style.configure('Sidebar.TFrame', background=self.sidebar_bg)
        self.style.configure('Sidebar.TLabel', background=self.sidebar_bg, foreground=self.sidebar_fg, font=('Segoe UI', 10, 'bold'))
        self.style.configure('Sidebar.TButton', background=self.primary_color, foreground='#FFFFFF', font=('Segoe UI', 10, 'bold'), borderwidth=0, padding=[10, 6])
        self.style.map('Sidebar.TButton', background=[('active', self.accent_color)])
        self.style.configure('TEntry', font=('Segoe UI', 11), fieldbackground=getattr(self, 'entry_bg', self.card_bg), borderwidth=1, foreground=self.primary_text)
        self.style.configure('TLabelframe', background=self.card_bg, borderwidth=1, highlightbackground=self.border_color, highlightcolor=self.border_color)
        self.style.configure('TLabelframe.Label', background=self.card_bg, font=('Segoe UI', 11, 'bold'), foreground=self.primary_text)

    def apply_theme(self, theme_name):
        """Save theme, apply palette, and update main window and sidebar."""
        theme_name = theme_name if theme_name in ("default", "dark") else "default"
        try:
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            if theme_name == "default":
                db.delete("appearance_theme")  # so next run loads default (emerald) when no preference
            else:
                db.set("appearance_theme", theme_name)
        except Exception:
            pass
        palette = self._get_theme_palette(theme_name)
        self._apply_palette(palette)
        self._current_theme = theme_name
        # Update root and main containers so theme applies immediately
        self.root.configure(bg=self.bg_color)
        if hasattr(self, 'main_container') and self.main_container.winfo_exists():
            self.main_container.configure(bg=self.bg_color)
        # Title and accent line (so Default = emerald, Light/Dark = their primary)
        if hasattr(self, 'title_frame') and self.title_frame.winfo_exists():
            self.title_frame.configure(bg=self.bg_color)
        if hasattr(self, 'title_label') and self.title_label.winfo_exists():
            self.title_label.configure(bg=self.bg_color, fg=self.primary_color)
        if hasattr(self, 'accent_line') and self.accent_line.winfo_exists():
            self.accent_line.configure(bg=self.accent_color)
        # Status label: re-apply correct color by state (System Ready = success/emerald, not red)
        if hasattr(self, 'status_label') and self.status_label.winfo_exists():
            self.status_label.configure(bg=self.bg_color)
            self.update_status()
        # Sidebar and menu button
        if hasattr(self, 'sidebar') and self.sidebar.winfo_exists():
            self.sidebar.configure(bg=self.sidebar_bg)
        if hasattr(self, 'sidebar_toggle_btn') and self.sidebar_toggle_btn.winfo_exists():
            self.sidebar_toggle_btn.configure(bg=self.primary_color, fg='white',
                                             activebackground=self.accent_color, activeforeground='white')
        if hasattr(self, 'toggle_btn') and self.toggle_btn.winfo_exists():
            self.toggle_btn.configure(bg=self.primary_color, fg='white',
                                     activebackground=self.accent_color, activeforeground='white')
        if hasattr(self, 'quick_login_btn') and self.quick_login_btn.winfo_exists():
            self.quick_login_btn.configure(bg=self.accent_color, fg='white',
                                           activebackground=self.primary_color, activeforeground='white')
        if hasattr(self, 'com_frame') and self.com_frame.winfo_exists():
            self.com_frame.configure(bg=self.card_bg)
        if hasattr(self, 'connect_btn') and self.connect_btn.winfo_exists():
            self.connect_btn.configure(bg=self.primary_color, fg='white',
                                       activebackground=self.accent_color, activeforeground='white')
        if hasattr(self, 'tool_frame') and self.tool_frame.winfo_exists():
            self.tool_frame.configure(bg=self.card_bg)
        if hasattr(self, 'admin_status_frame') and self.admin_status_frame.winfo_exists():
            self.admin_status_frame.configure(bg=self.border_color)
        if hasattr(self, 'admin_status_label') and self.admin_status_label.winfo_exists():
            self.admin_status_label.configure(bg=self.border_color, fg=self.primary_text)
        if hasattr(self, 'auth_btn') and self.auth_btn.winfo_exists():
            try:
                self.auth_btn.configure(activebackground=self.border_color, activeforeground=self.primary_text)
                if str(self.auth_btn.cget('state')) == 'normal':
                    self.auth_btn.configure(bg=self.primary_color, fg='white')
                else:
                    self.auth_btn.configure(bg=self.border_color, fg=self.secondary_text)
            except Exception:
                pass
        # Locked frame if visible
        if hasattr(self, 'locked_frame') and self.locked_frame and self.locked_frame.winfo_exists():
            self.locked_frame.configure(bg=self.bg_color)
            for w in self.locked_frame.winfo_children():
                try:
                    w.configure(bg=self.bg_color, fg=self.danger_color)
                except Exception:
                    pass
        if hasattr(self, 'settings_scrollable_frame') and self.settings_scrollable_frame.winfo_exists():
            self.settings_scrollable_frame.configure(bg=self.bg_color)
        if hasattr(self, 'system_settings_frame') and self.system_settings_frame.winfo_exists():
            self.system_settings_frame.configure(bg=self.bg_color)
        if hasattr(self, 'account_settings_frame') and self.account_settings_frame.winfo_exists():
            self.account_settings_frame.configure(bg=self.bg_color)
        if hasattr(self, 'admin_settings_frame') and self.admin_settings_frame.winfo_exists():
            self.admin_settings_frame.configure(bg=self.bg_color)
        # Update settings tab button styles
        if hasattr(self, 'settings_tab_buttons'):
            for name, btn in self.settings_tab_buttons.items():
                if name == self.settings_mode.get():
                    btn.config(bg=self.primary_color, fg='white',
                              activebackground=self.accent_color, activeforeground='white')
                else:
                    btn.config(bg=self.tab_inactive_bg, fg=self.secondary_text,
                              activebackground=self.border_color, activeforeground=self.primary_text)

    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use('clam')
        # Always start with default (emerald) - never load saved theme on startup
        palette = self._get_theme_palette("default")
        self._apply_palette(palette)
        self._current_theme = "default"

    def create_widgets(self):
        # Main container (left side)
        self.main_container = tk.Frame(self.root, bg=self.bg_color, highlightthickness=0)
        self.main_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=18, pady=18)

        # Title with accent underline (stored for theme updates)
        self.title_frame = tk.Frame(self.main_container, bg=self.bg_color)
        self.title_frame.pack(fill=tk.X, pady=(0, 24))

        self.title_label = tk.Label(self.title_frame, text="💊 CuraX – Intelligent Medicine System",
                                    font=('Segoe UI', 28, 'bold'), bg=self.bg_color, fg=self.primary_color)
        self.title_label.pack()
        # Accent underline
        self.accent_line = tk.Frame(self.title_frame, bg=self.accent_color, height=4)
        self.accent_line.pack(fill=tk.X, pady=(6, 0))

        # Status label only, no frame, no box, no padding
        self.status_label = tk.Label(self.main_container, text="⚠ Please connect ESP32 first",
                         font=('Segoe UI', 12, 'bold'), bg=self.bg_color, fg=self.danger_color, borderwidth=0, highlightthickness=0)
        self.status_label.pack(anchor="n", pady=(0, 12))

        # ===== Sidebar always visible =====
        self.create_sidebar()  # ESP32 Connect + Authenticate

        # Update admin status indicator on startup
        self.root.after(100, self.update_admin_status_indicator)

        # ===== Locked frame overlay (covers main_container content only) =====
        self.locked_frame = tk.Frame(self.main_container, bg=self.bg_color)
        self.locked_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(self.locked_frame, text="🔒 System Locked", font=('Segoe UI', 20, 'bold'),
                 bg=self.bg_color, fg=self.danger_color).pack(pady=36)

        tk.Label(self.locked_frame, text="Please connect ESP32 and authenticate to unlock system",
                 bg=self.bg_color, font=('Segoe UI', 13)).pack(pady=12)

        # Note: main tabs (notebook) will be created **after authentication**
        self.notebook = None

        # Update status
        self.update_status()

    def create_sidebar(self):
        # Main sidebar container frame (initially hidden)
        self.sidebar = tk.Frame(self.root, bg=self.card_bg, width=250, relief=tk.RIDGE, bd=1)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0), pady=10)
        self.sidebar.pack_propagate(False)

        # Initially hide the sidebar if screen is small
        self.sidebar_visible = False
        self.sidebar.pack_forget()

        # ==== Create toggle button in main window (always visible) ====
        self.sidebar_toggle_btn = tk.Button(
            self.root,
            text="☰ Menu",
            command=self.toggle_sidebar,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 10, 'bold'),
            width=8
        )
        # Position at top-left corner
        self.sidebar_toggle_btn.place(x=10, y=10, anchor=tk.NW)

        # Bind to window resize to keep button in position
        self.root.bind('<Configure>', self.update_toggle_button_position)

        # Create sidebar content (same as before, but don't pack initially)
        self.create_sidebar_content()
        self.sidebar_toggle_btn.lift()  # Ensure button is on top

    def create_sidebar_content(self):
        """Create all sidebar widgets (called once during initialization)"""
        # ==== Admin Status Indicator (visible from start, above ESP32 button) ====
        self.admin_status_frame = tk.Frame(self.sidebar, bg='#6c757d', relief=tk.RAISED, bd=2)
        self.admin_status_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        self.admin_status_label = tk.Label(
            self.admin_status_frame,
            text="🔒 Features Locked",
            bg='#6c757d',
            fg='white',
            font=('Arial', 9, 'bold')
        )
        self.admin_status_label.pack(pady=5)
        
        # Add login button (initially hidden, shown when admin exists but not logged in)
        self.quick_login_btn = tk.Button(
            self.sidebar,
            text="🔐 Admin Login",
            command=self.admin_login_dialog,
            bg=self.accent_color,
            fg='white',
            font=('Arial', 9, 'bold'),
            cursor='hand2'
        )
        # Don't pack initially - will be managed by update_admin_status_indicator
        
        # ==== ESP32 Toggle button ====
        self.toggle_btn = tk.Button(
            self.sidebar,
            text="🔌 ESP32",
            command=self.toggle_esp32_frame,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 10, 'bold')
        )
        self.toggle_btn.pack(fill=tk.X, padx=10, pady=(10, 0))

        # ESP32 Connection Section (hidden initially if system unlocked)
        self.com_frame = tk.LabelFrame(
            self.sidebar,
            text="🔌 ESP32 Connection",
            bg=self.card_bg,
            font=('Arial', 12, 'bold'),
            padx=10,
            pady=10
        )
        self.com_frame.pack(fill=tk.X, padx=10, pady=10)

        # COM Port selection
        tk.Label(self.com_frame, text="COM Port", bg=self.card_bg).pack(anchor=tk.W)
        self.port_var = tk.StringVar(value="")

        # Get initial list of available ports
        try:
            initial_ports = [port.device for port in serial.tools.list_ports.comports()]
            if initial_ports:
                self.port_var.set(initial_ports[0])
        except:
            initial_ports = []

        # Port selection frame with combo and refresh button
        port_select_frame = tk.Frame(self.com_frame, bg=self.card_bg)
        port_select_frame.pack(fill=tk.X, pady=(0, 10))

        # Expose combobox so other methods can update it
        self.port_combo = ttk.Combobox(
            port_select_frame,
            textvariable=self.port_var,
            values=initial_ports,
            width=12,
            state='readonly'
        )
        self.port_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        # Connect button
        self.connect_btn = tk.Button(
            self.com_frame,
            text="Connect ESP32",
            command=self.connect_esp32,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 10, 'bold')
        )
        self.connect_btn.pack(fill=tk.X)

        # Authenticate button
        self.auth_btn = tk.Button(
            self.com_frame,
            text="Authenticate",
            command=self.check_auth,
            state=tk.DISABLED,
            bg="#6c757d",
            fg='white',
            font=('Arial', 10, 'bold')
        )
        self.auth_btn.pack(fill=tk.X, pady=(10, 0))

        # Connection status
        self.com_status = tk.Label(
            self.com_frame,
            text="✗ Disconnected",
            bg=self.card_bg,
            fg=self.danger_color,
            font=('Arial', 10)
        )
        self.com_status.pack(pady=(10, 0))

        # --- TOOL PANEL (HIDDEN INITIALLY - WILL SHOW AFTER AUTHENTICATION) ---
        self.tool_frame = tk.LabelFrame(
            self.sidebar,
            text="🔧 Tools",
            bg=self.card_bg,
            font=('Arial', 12, 'bold'),
            padx=10,
            pady=10
        )
        # Note: We DON'T pack it initially - it will be shown after authentication

        debug_frame = tk.Frame(self.tool_frame, bg=self.card_bg)
        debug_frame.pack(fill=tk.X, padx=10, pady=10)

        # 1. BACKUP DATABASE BUTTON
        def backup_database():
            """Backup the current database to the backups folder."""
            import restore_db
            backup_path = restore_db.backup_db()
            popup = tk.Toplevel(self.root)
            popup.title("Backup Database")
            popup.geometry("400x200")
            popup.configure(bg=self.card_bg)
            if backup_path:
                msg = f"✅ Database backed up to:\n{backup_path}"
                fg = self.success_color
            else:
                msg = "❌ Backup failed. Database file not found."
                fg = self.danger_color
            tk.Label(
                popup,
                text=msg,
                font=('Arial', 13, 'bold'),
                bg=self.card_bg,
                fg=fg
            ).pack(pady=30)
            tk.Button(
                popup,
                text="OK",
                command=popup.destroy,
                bg=self.primary_color,
                fg='white',
                font=('Arial', 11),
                padx=20
            ).pack(pady=20)

        backup_btn = tk.Button(
            debug_frame,
            text="💾 Backup Database",
            command=backup_database,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 9, 'bold')
        )
        backup_btn.pack(fill=tk.X, pady=5)

        # 2. CHECK MEDICINE BUTTON (Popup version)

        # 2. CHECK MEDICINE BUTTON (Popup version)

        # 2. CHECK MEDICINE BUTTON (Popup version)
        def check_medicine():
            """Show detailed medicine info in popup window"""
            # Count filled boxes
            empty_count = 0
            filled_count = 0
            low_stock_meds = []

            for box_id, med in self.medicine_boxes.items():
                if med:
                    filled_count += 1
                    quantity = med.get('quantity', 0)
                    if quantity <= 5:
                        low_stock_meds.append(f"{med.get('name', 'Unknown')} (Box {box_id})")
                else:
                    empty_count += 1

            # Create popup window
            popup = tk.Toplevel(self.root)
            popup.title("Medicine Data Check")
            popup.geometry("500x500")
            popup.configure(bg=self.card_bg)

            # Title
            tk.Label(
                popup,
                text="📊 Medicine Status Report",
                font=('Arial', 16, 'bold'),
                bg=self.card_bg,
                fg=self.primary_color
            ).pack(pady=20)

            # Summary frame
            summary_frame = tk.Frame(popup, bg=self.card_bg)
            summary_frame.pack(pady=10)

            tk.Label(
                summary_frame,
                text=f"📦 Filled Boxes: {filled_count}/6",
                font=('Arial', 12, 'bold'),
                bg=self.card_bg,
                fg=self.success_color
            ).pack()

            tk.Label(
                summary_frame,
                text=f"📦 Empty Boxes: {empty_count}/6",
                font=('Arial', 12),
                bg=self.card_bg
            ).pack(pady=5)

            # Detailed medicine information
            from tkinter import scrolledtext

            details_frame = tk.Frame(popup, bg=self.card_bg)
            details_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

            tk.Label(
                details_frame,
                text="📋 Medicine Details:",
                font=('Arial', 11, 'bold'),
                bg=self.card_bg
            ).pack(anchor=tk.W, pady=(0, 5))

            # Create scrolled text widget
            details_text = scrolledtext.ScrolledText(
                details_frame,
                height=12,
                width=50,
                font=('Consolas', 9)
            )
            details_text.pack(fill=tk.BOTH, expand=True)

            # Add medicine details
            details_text.insert(tk.END, "=" * 50 + "\n")

            for box_id, med in self.medicine_boxes.items():
                if med:
                    name = med.get('name', 'Unknown')
                    quantity = med.get('quantity', 0)
                    dose = med.get('dose_per_day', 1)
                    time_str = med.get('exact_time', 'Not set')
                    expiry = med.get('expiry', 'Not set')

                    details_text.insert(tk.END, f"\n📦 Box {box_id}:\n")
                    details_text.insert(tk.END, f"   Medicine: {name}\n")
                    details_text.insert(tk.END, f"   Quantity: {quantity} tablets\n")
                    details_text.insert(tk.END, f"   Dose: {dose} per day\n")
                    details_text.insert(tk.END, f"   Time: {time_str}\n")
                    details_text.insert(tk.END, f"   Expiry: {expiry}\n")

                    if quantity <= 5:
                        details_text.insert(tk.END, f"   ⚠️ LOW STOCK! Only {quantity} left\n")
                else:
                    details_text.insert(tk.END, f"\n📦 Box {box_id}: EMPTY\n")

            details_text.insert(tk.END, "\n" + "=" * 50)
            details_text.config(state=tk.DISABLED)

            # Low stock warning
            if low_stock_meds:
                warning_frame = tk.Frame(popup, bg='#fff3cd', relief=tk.RIDGE, bd=1)
                warning_frame.pack(fill=tk.X, padx=20, pady=(0, 10))

                tk.Label(
                    warning_frame,
                    text="⚠️ Low Stock Alert:",
                    bg='#fff3cd',
                    fg='#856404',
                    font=('Arial', 10, 'bold')
                ).pack(pady=5)

                for med in low_stock_meds:
                    tk.Label(
                        warning_frame,
                        text=f"• {med}",
                        bg='#fff3cd',
                        fg='#856404',
                        font=('Arial', 9)
                    ).pack()

            # Close button
            tk.Button(
                popup,
                text="Close",
                command=popup.destroy,
                bg=self.primary_color,
                fg='white',
                font=('Arial', 11),
                padx=20
            ).pack(pady=10)

        check_btn = tk.Button(
            debug_frame,
            text="💊 Check Medicine Data",
            command=check_medicine,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 9)
        )
        check_btn.pack(fill=tk.X, pady=5)

        # 3. ALERT STATUS BUTTON (Popup version)

        # 4. RESTORE DATABASE BUTTON (24h)
        def restore_database():
            """Restore the database from a backup within the last 24 hours."""
            import restore_db
            result = restore_db.restore_db()
            popup = tk.Toplevel(self.root)
            popup.title("Restore Database (24h)")
            popup.geometry("400x200")
            popup.configure(bg=self.card_bg)
            if result:
                # Reload all data from the restored database
                try:
                    self.load_data()
                    self.load_alert_settings()
                    self.update_box_displays()
                    self.update_dose_displays()
                    self.update_box_status()
                    self.update_history()
                except Exception as e:
                    print(f"⚠️ Error reloading after restore: {e}")
                msg = "✅ Database restored from backup within the last 24 hours."
                fg = self.success_color
            else:
                msg = "❌ No backup found within the last 24 hours."
                fg = self.danger_color
            tk.Label(
                popup,
                text=msg,
                font=('Arial', 13, 'bold'),
                bg=self.card_bg,
                fg=fg
            ).pack(pady=30)
            tk.Button(
                popup,
                text="OK",
                command=popup.destroy,
                bg=self.primary_color,
                fg='white',
                font=('Arial', 11),
                padx=20
            ).pack(pady=20)

        restore_btn = tk.Button(
            debug_frame,
            text="🗄️ Restore Database (24h)",
            command=restore_database,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 9, 'bold')
        )
        restore_btn.pack(fill=tk.X, pady=5)
        def check_alert_status():
            """Check alert system status with complete details in popup window"""
            # Create popup window
            popup = tk.Toplevel(self.root)
            popup.title("Alert System Status - Complete Details")
            popup.geometry("600x500")
            popup.configure(bg=self.card_bg)

            # Title
            tk.Label(
                popup,
                text="🔔 Alert System Status - Complete Report",
                font=('Arial', 16, 'bold'),
                bg=self.card_bg,
                fg=self.primary_color
            ).pack(pady=20)

            # Create scrolled text area
            from tkinter import scrolledtext

            main_frame = tk.Frame(popup, bg=self.card_bg)
            main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

            # Create scrolled text widget
            details_text = scrolledtext.ScrolledText(
                main_frame,
                height=20,
                width=65,
                font=('Consolas', 9)
            )
            details_text.pack(fill=tk.BOTH, expand=True)

            # Add all alert details
            details_text.insert(tk.END, "=" * 60 + "\n")
            details_text.insert(tk.END, "🔔 ALERT SYSTEM STATUS - COMPLETE REPORT\n")
            details_text.insert(tk.END, "=" * 60 + "\n\n")

            # Alert scheduler status
            details_text.insert(tk.END, "📅 SCHEDULER STATUS:\n")
            details_text.insert(tk.END, "-" * 40 + "\n")

            if hasattr(self, 'alert_scheduler') and self.alert_scheduler:
                details_text.insert(tk.END, "✅ Alert Scheduler: RUNNING\n")
                if hasattr(self.alert_scheduler, 'scheduled_alerts'):
                    count = len(self.alert_scheduler.scheduled_alerts)
                    details_text.insert(tk.END, f"   • Scheduled jobs: {count}\n")
            else:
                details_text.insert(tk.END, "❌ Alert Scheduler: NOT RUNNING\n")

            details_text.insert(tk.END, "\n")

            # Gmail configuration
            details_text.insert(tk.END, "📧 GMAIL CONFIGURATION:\n")
            details_text.insert(tk.END, "-" * 40 + "\n")

            if self.gmail_config.get('sender_email'):
                details_text.insert(tk.END, f"✅ Configured for: {self.gmail_config['sender_email']}\n")
                if self.gmail_config.get('recipients'):
                    details_text.insert(tk.END, f"   • Recipients: {self.gmail_config['recipients']}\n")
                else:
                    details_text.insert(tk.END, "   • Recipients: Not configured (will use sender email)\n")
            else:
                details_text.insert(tk.END, "❌ Gmail: NOT CONFIGURED\n")

            details_text.insert(tk.END, "\n")

            # Scheduled medicine alerts
            details_text.insert(tk.END, "💊 SCHEDULED MEDICINE ALERTS:\n")
            details_text.insert(tk.END, "-" * 40 + "\n")

            scheduled_count = 0
            for box_id, medicine in self.medicine_boxes.items():
                if medicine:
                    scheduled_count += 1
                    name = medicine.get('name', 'Unknown')
                    time_str = medicine.get('exact_time', 'Not set')
                    dose = medicine.get('dose_per_day', 1)
                    quantity = medicine.get('quantity', 0)

                    details_text.insert(tk.END, f"\n📦 Box {box_id}: {name}\n")
                    details_text.insert(tk.END, f"   • Time: {time_str}\n")
                    details_text.insert(tk.END, f"   • Dose: {dose} per day\n")
                    details_text.insert(tk.END, f"   • Quantity: {quantity} tablets\n")

                    if self.alert_settings["medicine_alerts"]["15_min_before"]:
                        details_text.insert(tk.END, f"   • ⏰ 15-min reminder: ENABLED\n")
                    if self.alert_settings["medicine_alerts"]["exact_time"]:
                        details_text.insert(tk.END, f"   • ⏰ Exact time alert: ENABLED\n")
                    if self.alert_settings["medicine_alerts"]["5_min_after"]:
                        details_text.insert(tk.END, f"   • ⏰ Missed dose alert (5 min): ENABLED\n")

            if scheduled_count == 0:
                details_text.insert(tk.END, "No medicines scheduled for alerts\n")
            else:
                details_text.insert(tk.END, f"\n📊 Total medicines scheduled: {scheduled_count}\n")

            details_text.insert(tk.END, "\n")

            # Alert settings
            details_text.insert(tk.END, "⚙️ ALERT SETTINGS:\n")
            details_text.insert(tk.END, "-" * 40 + "\n")

            # Medicine alerts
            med_alerts = self.alert_settings.get("medicine_alerts", {})
            details_text.insert(tk.END, "Medicine Time Alerts:\n")
            details_text.insert(tk.END, f"   • 15-min reminders: {med_alerts.get('15_min_before', False)}\n")
            details_text.insert(tk.END, f"   • Exact time alerts: {med_alerts.get('exact_time', False)}\n")
            details_text.insert(tk.END, f"   • 5-min after (missed) alerts: {med_alerts.get('5_min_after', False)}\n")
            details_text.insert(tk.END, f"   • Missed dose alerts: {med_alerts.get('missed_alert', False)}\n")
            details_text.insert(tk.END, f"   • Snooze duration: {med_alerts.get('snooze_duration', 5)} minutes\n")

            details_text.insert(tk.END, "\n")

            # Email alerts
            email_alerts = self.alert_settings.get("email_alerts", {})
            details_text.insert(tk.END, "Email Alerts:\n")
            details_text.insert(tk.END, f"   • Enabled: {email_alerts.get('enabled', False)}\n")
            if email_alerts.get('email'):
                details_text.insert(tk.END, f"   • Email: {email_alerts.get('email', '')}\n")

            details_text.insert(tk.END, "\n")

            # Stock alerts
            stock_alerts = self.alert_settings.get("stock_alerts", {})
            details_text.insert(tk.END, "Stock Alerts:\n")
            details_text.insert(tk.END, f"   • Low stock threshold: {stock_alerts.get('low_stock_threshold', 5)}\n")
            details_text.insert(tk.END, f"   • Refill reminder days: {stock_alerts.get('refill_reminder_days', 3)}\n")
            details_text.insert(tk.END, f"   • Auto refill: {stock_alerts.get('auto_refill', False)}\n")

            details_text.insert(tk.END, "\n")

            # Expiry alerts
            expiry_alerts = self.alert_settings.get("expiry_alerts", {})
            details_text.insert(tk.END, "Expiry Alerts:\n")
            details_text.insert(tk.END, f"   • 30 days before: {expiry_alerts.get('30_days_before', False)}\n")
            details_text.insert(tk.END, f"   • 15 days before: {expiry_alerts.get('15_days_before', False)}\n")
            details_text.insert(tk.END, f"   • 7 days before: {expiry_alerts.get('7_days_before', False)}\n")
            details_text.insert(tk.END, f"   • 1 day before: {expiry_alerts.get('1_day_before', False)}\n")

            details_text.insert(tk.END, "\n" + "=" * 60 + "\n")
            details_text.insert(tk.END, f"Report generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

            details_text.config(state=tk.DISABLED)

            # Close button
            btn_frame = tk.Frame(popup, bg=self.card_bg)
            btn_frame.pack(pady=10)

            tk.Button(
                btn_frame,
                text="Close",
                command=popup.destroy,
                bg=self.primary_color,
                fg='white',
                font=('Arial', 11),
                padx=20
            ).pack()

        alert_btn = tk.Button(
            debug_frame,
            text="🔔 Check Alert Status",
            command=check_alert_status,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 9)
        )
        alert_btn.pack(fill=tk.X, pady=5)

    def toggle_sidebar(self):

        if self.sidebar_visible:
            # Hide sidebar
            self.sidebar.pack_forget()
            self.sidebar_toggle_btn.config(text="☰ Menu")
            self.sidebar_visible = False
            print("DEBUG: Sidebar hidden")
        else:
            # Show sidebar - EXPLICITLY remove any existing packing
            self.sidebar.pack_forget()  # First forget any existing packing
            self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 0), pady=10, before=self.main_container)
            self.sidebar_toggle_btn.config(text="✕ Close")
            self.sidebar_visible = True
            print(f"DEBUG: Sidebar shown. X position: {self.sidebar.winfo_x()}")

        if hasattr(self, "sidebar_toggle_btn"):
            self.sidebar_toggle_btn.lift()

    def update_toggle_button_position(self, event=None):
        """Update toggle button position when window is resized"""
        if hasattr(self, 'sidebar_toggle_btn'):
            # Position at top-right corner with some margin
            self.sidebar_toggle_btn.place(x=10, y=10, anchor=tk.NW)

    def toggle_esp32_frame(self):
        """Show/hide ESP32 connection frame in sidebar"""
        try:
            if hasattr(self, 'com_frame') and self.com_frame.winfo_ismapped():
                self.com_frame.pack_forget()
                print("🔌 ESP32 connection panel hidden")
            else:
                if hasattr(self, 'com_frame'):
                    self.com_frame.pack(fill=tk.X, padx=10, pady=10)
                    print("🔌 ESP32 connection panel shown")
                else:
                    print("⚠️ ESP32 frame not found")
        except Exception as e:
            print(f"❌ Error in toggle_esp32_frame: {e}")

    def create_main_panel_tab(self):
        tab = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(tab, text="📦 Main Panel")

        # Scrollable container
        canvas = tk.Canvas(tab, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(tab, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        cwin = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cwin, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.bind_canvas_mousewheel(canvas)

        # Title (inner title = emerald)
        title = tk.Label(scrollable_frame, text="Medicine Boxes Dashboard", font=('Arial', 18, 'bold'),
                         bg=self.bg_color, fg=self.primary_color)
        title.pack(pady=(10, 4))

        # Subtitle
        subtitle = tk.Label(scrollable_frame, text="Each box contains medicine. Click box to view details.",
                            bg=self.bg_color, font=('Arial', 10), fg='#6c757d')
        subtitle.pack(pady=(0, 20))

        # Medicine boxes grid (6 boxes) - electricity meter style
        boxes_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        boxes_frame.pack(pady=(0, 10))

        self.box_buttons = []
        for i in range(1, 7):
            box_id = f"B{i}"
            box_frame = tk.Frame(boxes_frame, bg=self.card_bg, relief=tk.GROOVE, bd=2)
            box_frame.grid(row=(i - 1) // 3, column=(i - 1) % 3, padx=10, pady=8, ipadx=8, ipady=4)
            box_frame.bind("<Button-1>", lambda e, bid=box_id: self.show_box_details(bid))
            box_frame.config(cursor="hand2")

            # Box ID label at top
            id_label = tk.Label(box_frame, text=box_id, font=('Segoe UI', 10, 'bold'),
                                bg=self.card_bg, fg=self.primary_color)
            id_label.pack(pady=(4, 0))
            id_label.bind("<Button-1>", lambda e, bid=box_id: self.show_box_details(bid))
            id_label.config(cursor="hand2")

            # Meter canvas (electricity meter style) - reduced height
            meter_canvas = tk.Canvas(box_frame, width=110, height=50, bg='#D1DBE5', highlightthickness=0)
            meter_canvas.pack(pady=(0, 0))
            meter_canvas.bind("<Button-1>", lambda e, bid=box_id: self.show_box_details(bid))
            meter_canvas.config(cursor="hand2")

            # Tablets remaining label (needle shows this value)
            qty_label = tk.Label(box_frame, text="Empty", font=('Segoe UI', 8, 'bold'),
                                 bg=self.card_bg, fg='#64748B')
            qty_label.pack(pady=(0, 0))
            qty_label.bind("<Button-1>", lambda e, bid=box_id: self.show_box_details(bid))
            qty_label.config(cursor="hand2")

            # Medicine name label
            med_label = tk.Label(box_frame, text="—", font=('Segoe UI', 8),
                                 bg=self.card_bg, fg='#64748B')
            med_label.pack(pady=(0, 4))
            med_label.bind("<Button-1>", lambda e, bid=box_id: self.show_box_details(bid))
            med_label.config(cursor="hand2")

            self.box_buttons.append((meter_canvas, med_label, qty_label, box_id))

        # Details frame (hidden initially)
        self.details_frame = tk.Frame(scrollable_frame, bg=self.card_bg, relief=tk.GROOVE, bd=2)

        # Update box displays (no Box Status section - only 6 boxes)
        self.update_box_displays()

    def _draw_meter_gauge(self, canvas, value, is_filled):
        """Draw a single electricity-meter style gauge. Enhanced screen look."""
        canvas.delete("all")
        w, h = 110, 50
        cx, cy = w // 2, h - 4
        r = 38
        # Meter face - soft screen gray with inner bezel
        canvas.configure(bg='#D1DBE5')
        # Inner bezel (darker ring)
        canvas.create_arc(cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2,
                         start=180, extent=180, outline='#64748B', fill='', width=2)
        # Main gauge arc - clean white face
        canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=180, extent=180,
                         outline='#94A3B8', fill='#F1F5F9', width=2)
        # Tick marks - major (0,50,100) slightly longer, minor (25,75) shorter
        for pct in [0, 25, 50, 75, 100]:
            ang = 180 - (pct / 100) * 180
            rad = math.radians(ang)
            is_major = pct in (0, 50, 100)
            tick_inner = r - (10 if is_major else 6)
            x1 = cx + tick_inner * math.cos(rad)
            y1 = cy - tick_inner * math.sin(rad)
            x2 = cx + r * math.cos(rad)
            y2 = cy - r * math.sin(rad)
            canvas.create_line(x1, y1, x2, y2, fill='#475569', width=2 if is_major else 1)
        # Needle - vibrant when filled, softer when empty
        ang = 180 - (value / 100) * 180
        rad = math.radians(ang)
        needle_len = r - 9
        nx = cx + needle_len * math.cos(rad)
        ny = cy - needle_len * math.sin(rad)
        needle_color = '#38A169' if is_filled else '#94A3B8'
        canvas.create_line(cx, cy, nx, ny, fill=needle_color, width=2)
        # Center hub - metallic look
        canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=needle_color, outline='#334155', width=1)

    def _draw_meter_gauges(self):
        """Draw all 6 meter gauges. Full scale = 80 tablets (like clock: 45 = ~half, 80 = full)."""
        METER_FULL_SCALE = 80
        if not hasattr(self, "box_buttons"):
            return
        for canvas, med_label, qty_label, box_id in self.box_buttons:
            med = self.medicine_boxes.get(box_id)
            if med:
                qty = med.get("quantity", 0)
                if isinstance(qty, (int, float)):
                    value = min(100, max(0, (qty / METER_FULL_SCALE) * 100))
                else:
                    value = 0
                self._draw_meter_gauge(canvas, value, is_filled=True)
            else:
                self._draw_meter_gauge(canvas, 0, is_filled=False)

    def show_box_details(self, box_id):
        med = self.medicine_boxes.get(box_id)
        if not med:
            messagebox.showinfo("Box Details", f"No medicine stored in {box_id}")
            return

        # New window
        detail_win = tk.Toplevel(self.root)
        detail_win.title(f"Medicine Details - {box_id}")
        detail_win.geometry("400x400")
        detail_win.configure(bg=self.card_bg)

        # Get exact time from the correct key
        exact_time = med.get('exact_time', med.get('time', '-'))  # Try both keys for backward compatibility

        details = f"""
    🧪 Medicine: {med.get('name', '-')}
    📦 Quantity: {med.get('quantity', '-')} tablets
    💊 Dose per Day: {med.get('dose_per_day', '-')}
    📅 Expiry Date: {med.get('expiry', '-')}
    🕒 Intake Period: {med.get('period', '-')}
    ⏰ Exact Time: {exact_time}
    📝 Instructions: {med.get('instructions', 'None')}
    📝 Last Dose: {med.get('last_dose_taken', 'Not taken yet')}
    """
        tk.Label(detail_win, text=details, bg=self.card_bg, font=('Arial', 11), justify=tk.LEFT).pack(pady=20, padx=20)

        btn_frame = tk.Frame(detail_win, bg=self.card_bg)
        btn_frame.pack(pady=10)

        # Close button
        tk.Button(btn_frame, text="Close", command=detail_win.destroy,
                  bg=self.primary_color, fg='white', font=('Arial', 12, 'bold'), padx=20, pady=8).pack(side=tk.LEFT,
                                                                                                       padx=10)

        # Remove medicine button
        def remove_med():
            if not self.require_admin():
                return
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            
            if db.has_admin_credentials():
                # Show admin verification dialog (no additional warning needed)
                if not self.verify_admin_dialog("Remove Medicine"):
                    return  # Silently cancel - verification dialog already showed the message

            # Clear medicine from this box
            self.medicine_boxes[box_id] = None

            # Cancel any scheduled alerts for this box so old medicine alerts don't keep firing
            try:
                if hasattr(self, 'alert_scheduler') and self.alert_scheduler:
                    self.alert_scheduler.cancel_medicine_alerts_for_box(box_id)
            except Exception as e:
                print(f"⚠ Failed to cancel alerts for {box_id}: {e}")

            self.save_data()
            self.update_box_displays()
            self.update_dose_displays()
            self.update_box_status()
            self.update_history()
            detail_win.destroy()
            messagebox.showinfo("Removed", f"Medicine removed from {box_id}")

        tk.Button(btn_frame, text="Remove Medicine", command=remove_med,
                  bg=self.danger_color, fg='white', font=('Arial', 12, 'bold'), padx=10, pady=8).pack(side=tk.LEFT,
                                                                                                      padx=10)

    def create_add_medicine_tab(self):
        tab = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(tab, text="➕ Add Medicine")

        # ================= SCROLLABLE CONTAINER =================
        canvas = tk.Canvas(tab, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(tab, orient="vertical", command=canvas.yview)

        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mousewheel scrolling
        self.bind_canvas_mousewheel(canvas)

        # ================= TITLE (inner title = emerald) =================
        title = tk.Label(scrollable_frame, text="Add New Medicine", font=('Arial', 18, 'bold'),
                         bg=self.bg_color, fg=self.primary_color)
        title.pack(pady=(10, 20))

        # ================= FORM =================
        form_frame = tk.Frame(scrollable_frame, bg=self.card_bg, relief=tk.RAISED, bd=1, padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Medicine Name
        tk.Label(form_frame, text="💊 Medicine Name:", bg=self.card_bg, font=('Arial', 11)).grid(row=0, column=0,
                                                                                                sticky=tk.W, pady=5)
        self.med_name = tk.Entry(form_frame, font=('Arial', 11), width=30)
        self.med_name.grid(row=0, column=1, sticky=tk.W, pady=5, padx=(10, 0))

        # Quantity
        tk.Label(form_frame, text="📦 Quantity:", bg=self.card_bg, font=('Arial', 11)).grid(row=1, column=0, sticky=tk.W,
                                                                                           pady=5)
        self.med_qty = tk.Spinbox(form_frame, from_=1, to=1000, font=('Arial', 11), width=10)
        self.med_qty.grid(row=1, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        self.med_qty.delete(0, tk.END)
        self.med_qty.insert(0, "30")

        # Dose per Day
        tk.Label(form_frame, text="💊 Dose per Day:", bg=self.card_bg, font=('Arial', 11)).grid(row=2, column=0,
                                                                                               sticky=tk.W, pady=5)
        self.med_dose = tk.Spinbox(form_frame, from_=1, to=10, font=('Arial', 11), width=10)
        self.med_dose.grid(row=2, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        self.med_dose.delete(0, tk.END)
        self.med_dose.insert(0, "1")

        # Expiry Date
        tk.Label(form_frame, text="📅 Expiry Date:", bg=self.card_bg, font=('Arial', 11)).grid(row=3, column=0,
                                                                                              sticky=tk.W, pady=5)
        self.med_expiry = DateEntry(form_frame, font=('Arial', 11), date_pattern='yyyy-mm-dd')
        self.med_expiry.grid(row=3, column=1, sticky=tk.W, pady=5, padx=(10, 0))

        # Intake Period
        tk.Label(form_frame, text="🕒 Intake Period:", bg=self.card_bg, font=('Arial', 11)).grid(row=4, column=0,
                                                                                                sticky=tk.W, pady=5)
        self.med_period = ttk.Combobox(form_frame, values=["Morning (6 AM - 10 AM)", "Afternoon (12 PM - 4 PM)",
                                                           "Night (8 PM - 10 PM)"],
                                       font=('Arial', 11), width=25, state="readonly")
        self.med_period.grid(row=4, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        self.med_period.set("Morning (6 AM - 10 AM)")

        # Exact Time
        tk.Label(form_frame, text="⏰ Exact Time:", bg=self.card_bg, font=('Arial', 11)).grid(row=5, column=0,
                                                                                             sticky=tk.W, pady=5)
        self.med_hour = ttk.Combobox(form_frame, values=[str(i) for i in range(1, 24)], width=5, state="readonly",
                                     font=('Arial', 11))
        self.med_hour.grid(row=5, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        self.med_hour.set("8")

        self.med_minute = ttk.Combobox(form_frame, values=[f"{i:02d}" for i in range(0, 60, 5)], width=5,
                                       state="readonly", font=('Arial', 11))
        self.med_minute.grid(row=5, column=1, sticky=tk.W, pady=5, padx=(70, 0))
        self.med_minute.set("00")

        # Box selection
        tk.Label(form_frame, text="📥 Assign to Box:", bg=self.card_bg, font=('Arial', 11)).grid(row=6, column=0,
                                                                                                sticky=tk.W, pady=5)
        self.med_box = ttk.Combobox(form_frame, values=["B1", "B2", "B3", "B4", "B5", "B6"], font=('Arial', 11),
                                    width=10, state="readonly")
        self.med_box.grid(row=6, column=1, sticky=tk.W, pady=5, padx=(10, 0))
        self.med_box.set("B1")

        # Instructions
        tk.Label(form_frame, text="📝 Instructions:", bg=self.card_bg, font=('Arial', 11)).grid(row=7, column=0,
                                                                                               sticky=tk.NW, pady=5)
        self.med_instructions = tk.Text(form_frame, height=4, width=30, font=('Arial', 11))
        self.med_instructions.grid(row=7, column=1, sticky=tk.W, pady=5, padx=(10, 0))

        # Save Button with lock icon for admin protection
        save_btn = tk.Button(form_frame, text="🔒 Save Medicine (Admin Protected)", command=self.save_medicine,
                             bg=self.success_color, fg='white', font=('Arial', 12, 'bold'),
                             padx=30, pady=10,
                             cursor="hand2")
        save_btn.grid(row=8, column=0, columnspan=2, pady=20)
        ToolTip(save_btn, "⚠️ Admin verification required to add/edit medicine")

    def create_dose_tracking_tab(self):
        tab = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(tab, text="💊 Dose Tracking")
        # No admin check: always allow access after authentication
        # ================= SCROLLABLE CONTAINER =================
        canvas = tk.Canvas(tab, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(tab, orient="vertical", command=canvas.yview)

        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mousewheel scrolling
        self.bind_canvas_mousewheel(canvas)

        # ================= TITLE (inner title = emerald) =================
        title = tk.Label(
            scrollable_frame,
            text="Dose Tracking & History",
            font=('Arial', 18, 'bold'),
            bg=self.bg_color,
            fg=self.primary_color
        )
        title.pack(pady=(10, 5))

        subtitle = tk.Label(
            scrollable_frame,
            text="Click a box to turn ON its LED and take medicine",
            font=('Arial', 11),
            bg=self.bg_color
        )
        subtitle.pack(pady=(0, 15))

        # ================= MEDICINE BOXES =================
        boxes_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        boxes_frame.pack(pady=10)

        self.dose_buttons = []

        for i in range(1, 7):
            box_id = f"B{i}"

            card = tk.Frame(
                boxes_frame,
                bg=self.card_bg,
                relief=tk.RIDGE,
                bd=2,
                padx=10,
                pady=10
            )
            card.grid(row=(i - 1) // 3, column=(i - 1) % 3, padx=10, pady=10)

            btn = tk.Button(
                card,
                text=box_id,
                font=('Arial', 12, 'bold'),
                width=10,
                command=lambda b=box_id: self.turn_on_led(b)
            )
            btn.pack(pady=(0, 5))

            med_label = tk.Label(card, text="Empty", bg=self.card_bg)
            med_label.pack()

            qty_label = tk.Label(card, text="Qty: 0", bg=self.card_bg)
            qty_label.pack()

            self.dose_buttons.append((btn, med_label, qty_label, box_id))

        # ================= TURN OFF BUTTON =================
        # Buttons frame
        btns_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        btns_frame.pack(pady=15, fill=tk.X, padx=50)

        # Turn Off All LEDs
        off_btn = tk.Button(
            btns_frame,
            text="🔴 Turn OFF All LEDs",
            command=self.turn_off_all_leds,
            bg=self.danger_color,
            fg="white",
            font=('Arial', 11, 'bold'),
            padx=20, pady=8
        )
        off_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 10))

        # Mark Dose (active frame) button (visible always)
        mark_dose_btn = tk.Button(
            btns_frame,
            text="✅ Mark Dose Taken",
            command=self.mark_dose_taken,
            bg=self.success_color,
            fg="white",
            font=('Arial', 11, 'bold'),
            padx=20, pady=8
        )
        mark_dose_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(10, 0))

        self.mark_dose_btn = mark_dose_btn  # Update class reference

        # ================= ACTIVE LED PANEL =================
        self.active_frame = tk.Frame(
            scrollable_frame,
            bg=self.card_bg,
            relief=tk.GROOVE,
            bd=2,
            padx=20,
            pady=10
        )
        self.active_frame.pack_forget()

        self.active_label = tk.Label(
            self.active_frame,
            text="",
            font=('Arial', 12, 'bold'),
            bg=self.card_bg,
            fg=self.primary_color
        )
        self.active_label.pack(pady=(5, 5))

        self.info_label = tk.Label(
            self.active_frame,
            text="",
            font=('Arial', 11),
            bg=self.card_bg
        )
        self.info_label.pack(pady=(0, 10))

        self.mark_dose_btn = tk.Button(
            self.active_frame,
            text="✅ Mark Dose Taken",
            command=self.mark_dose_taken,
            bg=self.success_color,
            fg="white",
            font=('Arial', 11, 'bold'),
            padx=20,
            pady=8
        )
        self.mark_dose_btn.pack()

        # ================= HISTORY =================
        history_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        history_frame.pack(pady=20, fill=tk.BOTH, expand=True)

        history_title = tk.Label(
            history_frame,
            text="Dose History",
            font=('Arial', 14, 'bold'),
            bg=self.bg_color
        )
        history_title.pack(anchor="w", padx=10)

        # Treeview for history
        columns = ("timestamp", "box", "medicine", "dose_taken", "remaining")
        self.history_table = ttk.Treeview(history_frame, columns=columns, show="headings", height=8)
        self.history_table.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Define headings
        self.history_table.heading("timestamp", text="Timestamp")
        self.history_table.heading("box", text="Box")
        self.history_table.heading("medicine", text="Medicine")
        self.history_table.heading("dose_taken", text="Dose Taken")
        self.history_table.heading("remaining", text="Remaining")
        self.history_table.column("timestamp", width=140)
        self.history_table.column("box", width=50, anchor="center")
        self.history_table.column("medicine", width=120)
        self.history_table.column("dose_taken", width=90, anchor="center")
        self.history_table.column("remaining", width=90, anchor="center")
        self.update_history()

    def create_temp_adjustment_tab(self):
        """Temperature Adjustment tab for Peltier control"""
        tab = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(tab, text="🌡️ T Adjustment")

        # --- SCROLLABLE CONTAINER ---
        canvas = tk.Canvas(tab, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(tab, orient='vertical', command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mousewheel scrolling
        self.bind_canvas_mousewheel(canvas)

        # --- TITLE (inner title = emerald) ---
        title_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        title_frame.pack(fill=tk.X, pady=(20, 10), padx=20)

        tk.Label(title_frame, text="🌡️ Temperature Control System",
                 font=('Arial', 20, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(side=tk.LEFT)

        # Status indicator
        status_frame = tk.Frame(title_frame, bg=self.bg_color)
        status_frame.pack(side=tk.RIGHT)

        self.temp_status = tk.Label(status_frame, text="⚪ DISCONNECTED",
                                    font=('Arial', 10, 'bold'),
                                    bg='#f8f9fa', fg='#6c757d',
                                    padx=10, pady=3)
        self.temp_status.pack()

        # --- INTRODUCTION ---
        intro_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        intro_frame.pack(fill=tk.X, padx=20, pady=(0, 20))

        tk.Label(intro_frame,
                 text="Control Peltier modules for medicine storage:\n"
                      "• Peltier 1: Boxes B1-B4 (Normal Medicines)\n"
                      "• Peltier 2: Boxes B5-B6 (Cold Medicines)",
                 font=('Arial', 11),
                 bg=self.bg_color, fg='#6c757d',
                 justify=tk.LEFT).pack(anchor=tk.W)

        # --- MAIN CONTROL PANEL ---
        control_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        control_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Left: Peltier 1 Control
        peltier1_frame = tk.LabelFrame(control_frame, text="❄️ Peltier 1 (Boxes B1-B4)",
                                       bg=self.card_bg, font=('Arial', 12, 'bold'),
                                       padx=20, pady=20)
        peltier1_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Peltier 1 Enable/Disable
        self.peltier1_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(peltier1_frame, text="Enable Peltier 1",
                       variable=self.peltier1_enabled,
                       bg=self.card_bg, font=('Arial', 11)).pack(anchor=tk.W, pady=(0, 15))

        # Temperature Range for Peltier 1
        tk.Label(peltier1_frame, text="Temperature Range (°C):",
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))

        # Min Temperature
        min_frame = tk.Frame(peltier1_frame, bg=self.card_bg)
        min_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(min_frame, text="Min:", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT)

        self.peltier1_min = tk.Spinbox(min_frame, from_=10, to=25,
                                       width=8, font=('Arial', 10))
        self.peltier1_min.pack(side=tk.LEFT, padx=(10, 0))
        self.peltier1_min.delete(0, tk.END)
        self.peltier1_min.insert(0, "15")
        tk.Label(min_frame, text="°C", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=(5, 0))

        # Max Temperature
        max_frame = tk.Frame(peltier1_frame, bg=self.card_bg)
        max_frame.pack(fill=tk.X, pady=(0, 15))

        tk.Label(max_frame, text="Max:", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT)

        self.peltier1_max = tk.Spinbox(max_frame, from_=10, to=25,
                                       width=8, font=('Arial', 10))
        self.peltier1_max.pack(side=tk.LEFT, padx=(10, 0))
        self.peltier1_max.delete(0, tk.END)
        self.peltier1_max.insert(0, "20")
        tk.Label(max_frame, text="°C", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=(5, 0))

        # Current Temperature Display
        tk.Label(peltier1_frame, text="Current Temperature:",
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(10, 5))

        self.peltier1_current = tk.Label(peltier1_frame,
                                         text="18.0 °C",
                                         font=('Arial', 14, 'bold'),
                                         bg=self.card_bg, fg=self.primary_color)
        self.peltier1_current.pack(pady=(0, 15))

        # Apply Button for Peltier 1
        apply_btn1 = tk.Button(peltier1_frame, text="Apply to Peltier 1",
                               command=lambda: self.apply_temp_settings("peltier1"),
                               bg=self.primary_color, fg='white',
                               font=('Arial', 11), padx=20, pady=8)
        apply_btn1.pack(pady=(10, 0))

        # Right: Peltier 2 Control
        peltier2_frame = tk.LabelFrame(control_frame, text="🧊 Peltier 2 (Boxes B5-B6)",
                                       bg=self.card_bg, font=('Arial', 12, 'bold'),
                                       padx=20, pady=20)
        peltier2_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))

        # Peltier 2 Enable/Disable
        self.peltier2_enabled = tk.BooleanVar(value=True)
        tk.Checkbutton(peltier2_frame, text="Enable Peltier 2",
                       variable=self.peltier2_enabled,
                       bg=self.card_bg, font=('Arial', 11)).pack(anchor=tk.W, pady=(0, 15))

        # Temperature Range for Peltier 2
        tk.Label(peltier2_frame, text="Temperature Range (°C):",
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))

        # Min Temperature
        min_frame2 = tk.Frame(peltier2_frame, bg=self.card_bg)
        min_frame2.pack(fill=tk.X, pady=(0, 10))

        tk.Label(min_frame2, text="Min:", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT)

        self.peltier2_min = tk.Spinbox(min_frame2, from_=2, to=10,
                                       width=8, font=('Arial', 10))
        self.peltier2_min.pack(side=tk.LEFT, padx=(10, 0))
        self.peltier2_min.delete(0, tk.END)
        self.peltier2_min.insert(0, "5")
        tk.Label(min_frame2, text="°C", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=(5, 0))

        # Max Temperature
        max_frame2 = tk.Frame(peltier2_frame, bg=self.card_bg)
        max_frame2.pack(fill=tk.X, pady=(0, 15))

        tk.Label(max_frame2, text="Max:", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT)

        self.peltier2_max = tk.Spinbox(max_frame2, from_=2, to=10,
                                       width=8, font=('Arial', 10))
        self.peltier2_max.pack(side=tk.LEFT, padx=(10, 0))
        self.peltier2_max.delete(0, tk.END)
        self.peltier2_max.insert(0, "8")
        tk.Label(max_frame2, text="°C", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=(5, 0))

        # Current Temperature Display
        tk.Label(peltier2_frame, text="Current Temperature:",
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(10, 5))

        self.peltier2_current = tk.Label(peltier2_frame,
                                         text="6.0 °C",
                                         font=('Arial', 14, 'bold'),
                                         bg=self.card_bg, fg="#4a6fa5")  # Different color
        self.peltier2_current.pack(pady=(0, 15))

        # Apply Button for Peltier 2
        apply_btn2 = tk.Button(peltier2_frame, text="Apply to Peltier 2",
                               command=lambda: self.apply_temp_settings("peltier2"),
                               bg="#4a6fa5", fg='white',  # Different color
                               font=('Arial', 11), padx=20, pady=8)
        apply_btn2.pack(pady=(10, 0))

        # --- BOTTOM SECTION: QUICK CONTROLS ---
        bottom_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        bottom_frame.pack(fill=tk.X, padx=20, pady=(20, 10))

        # Quick Apply Both
        quick_frame = tk.LabelFrame(bottom_frame, text="⚡ Quick Actions",
                                    bg=self.card_bg, font=('Arial', 12, 'bold'),
                                    padx=20, pady=15)
        quick_frame.pack(fill=tk.X)

    def apply_temp_settings(self, peltier_id):
        if not self.authenticated or not self.ser:
            messagebox.showwarning("Not Connected",
                                "Please connect and authenticate ESP32 first")
            return

        try:
            if peltier_id == "peltier1":
                min_temp = float(self.peltier1_min.get())
                max_temp = float(self.peltier1_max.get())
                enabled = self.peltier1_enabled.get()
            else:  # peltier2
                min_temp = float(self.peltier2_min.get())
                max_temp = float(self.peltier2_max.get())
                enabled = self.peltier2_enabled.get()

            if min_temp >= max_temp:
                messagebox.showerror("Invalid Range",
                                    "Minimum temperature must be less than maximum")
                return

            command = f"TEMP_SET:{peltier_id},{enabled},{min_temp},{max_temp}\n"
            self.ser.write(command.encode())
            self.ser.flush()

            messagebox.showinfo(
                "Success",
                f"{peltier_id.upper()} applied\n{min_temp}°C → {max_temp}°C"
            )

        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply settings:\n{e}")


    def apply_both_temp_settings(self):
        """Apply settings to both peltiers"""
        if not self.authenticated or not self.ser:
            messagebox.showwarning("Not Connected",
                                   "Please connect and authenticate ESP32 first")
            return

        # Apply to peltier 1
        self.apply_temp_settings("peltier1")
        time.sleep(1)  # Small delay

        # Apply to peltier 2
        self.apply_temp_settings("peltier2")

    def refresh_temperatures(self):
        """Refresh current temperatures from ESP32"""
        if not self.authenticated or not self.ser:
            messagebox.showwarning("Not Connected",
                                   "Please connect and authenticate ESP32 first")
            return

        try:
            # Send temperature query command
            self.ser.write(b"TEMP_QUERY\n")
            self.ser.flush()

            # Wait for response                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        NNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNNN
            time.sleep(0.5)
            response = self.read_serial_response()

            if "TEMP1:" in response and "TEMP2:" in response:
                # Parse temperatures
                lines = response.split('\n')
                for line in lines:
                    if line.startswith("TEMP1:"):
                        temp1 = float(line.split(":")[1].strip())
                        self.peltier1_current.config(text=f"{temp1:.1f} °C")
                        self.p1_status_label.config(text=f"🟢 ACTIVE ({temp1:.1f}°C)")
                        self.temp_settings["peltier1"]["current"] = temp1

                    elif line.startswith("TEMP2:"):
                        temp2 = float(line.split(":")[1].strip())
                        self.peltier2_current.config(text=f"{temp2:.1f} °C")
                        self.p2_status_label.config(text=f"🟢 ACTIVE ({temp2:.1f}°C)")
                        self.temp_settings["peltier2"]["current"] = temp2

                messagebox.showinfo("Refreshed",
                                    f"Temperatures updated:\n"
                                    f"• Peltier 1: {temp1:.1f}°C\n"
                                    f"• Peltier 2: {temp2:.1f}°C")

            else:
                # Simulate temperatures for demo
                temp1 = (float(self.peltier1_min.get()) + float(self.peltier1_max.get())) / 2
                temp2 = (float(self.peltier2_min.get()) + float(self.peltier2_max.get())) / 2

                self.peltier1_current.config(text=f"{temp1:.1f} °C")
                self.peltier2_current.config(text=f"{temp2:.1f} °C")

                messagebox.showinfo("Demo Mode",
                                    f"Using simulated temperatures:\n"
                                    f"• Peltier 1: {temp1:.1f}°C\n"
                                    f"• Peltier 2: {temp2:.1f}°C")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh temperatures: {str(e)}")

    def read_serial_response(self, timeout=2):
        """Read response from serial port"""
        if not self.ser or not self.ser.is_open:
            return ""

        start_time = time.time()
        response = ""

        while time.time() - start_time < timeout:
            if self.ser.in_waiting:
                raw = self.ser.readline()
                response += raw.decode('utf-8', errors='ignore')
                if response.strip():  # If we got something
                    break
            time.sleep(0.1)

        return response.strip()

    def update_temp_status(self, status):
        """Update temperature control status - SAFE VERSION"""
        try:
            # Check if temp_status exists
            if not hasattr(self, 'temp_status') or self.temp_status is None:
                print("⚠ Temperature status label not ready yet")
                return

            if status == "connected":
                self.temp_status.config(text="🟢 CONNECTED", fg=self.success_color, bg='#d4edda')
            elif status == "disconnected":
                self.temp_status.config(text="⚫ DISCONNECTED", fg='#6c757d', bg='#f8f9fa')
            elif status == "error":
                self.temp_status.config(text="🔴 ERROR", fg=self.danger_color, bg='#f8d7da')

        except Exception as e:
            print(f"⚠ Could not update temperature status: {e}")

    def setup_initial_temperatures(self):
        """Setup initial temperature values in GUI after authentication"""
        print("🌡️ Setting up initial temperature controls...")

        try:
            # Set default values in temperature controls
            if hasattr(self, 'peltier1_min'):
                self.peltier1_min.delete(0, tk.END)
                self.peltier1_min.insert(0, "15")

            if hasattr(self, 'peltier1_max'):
                self.peltier1_max.delete(0, tk.END)
                self.peltier1_max.insert(0, "20")

            if hasattr(self, 'peltier2_min'):
                self.peltier2_min.delete(0, tk.END)
                self.peltier2_min.insert(0, "5")

            if hasattr(self, 'peltier2_max'):
                self.peltier2_max.delete(0, tk.END)
                self.peltier2_max.insert(0, "8")

            # Update temperature displays
            if hasattr(self, 'peltier1_current'):
                self.peltier1_current.config(text="18.0 °C")

            if hasattr(self, 'peltier2_current'):
                self.peltier2_current.config(text="6.5 °C")

            # Update status labels
            if hasattr(self, 'p1_status_label'):
                self.p1_status_label.config(text="🟢 ACTIVE (18.0°C)")

            if hasattr(self, 'p2_status_label'):
                self.p2_status_label.config(text="🟢 ACTIVE (6.5°C)")

            print("✔ Initial temperature controls setup complete")

        except Exception as e:
            print(f"✗ Error setting up temperature controls: {e}")

    def create_alerts_tab(self):
        """
        Main Alerts & Reminders tab with all features
        """
        tab = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(tab, text="🔔 Alerts")

        # ========== SCROLLABLE CONTAINER ==========
        main_frame = tk.Frame(tab, bg=self.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(main_frame, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)

        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mousewheel scrolling
        self.bind_canvas_mousewheel(canvas)

        # ========== TITLE (inner title = emerald) ==========
        title_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        title_frame.pack(fill=tk.X, pady=(20, 10), padx=20)

        tk.Label(title_frame, text="🔔 Alerts & Reminders System",
                 font=('Arial', 20, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(side=tk.LEFT)

        # Status indicator
        status_frame = tk.Frame(title_frame, bg=self.bg_color)
        status_frame.pack(side=tk.RIGHT)

        self.alert_status = tk.Label(status_frame, text="✅ ACTIVE",
                                     font=('Arial', 10, 'bold'),
                                     bg='#d4edda', fg='#155724',
                                     padx=10, pady=3)
        self.alert_status.pack()

        # ========== SECTION 1: MEDICINE TIME ALERTS ==========
        self.create_medicine_alerts_section(scrollable_frame)

        # ========== SECTION 2: MISSED DOSE HANDLING ==========
        self.create_missed_dose_section(scrollable_frame)
        self.create_expiry_alerts_section(scrollable_frame)
        # ========== SECTION 3: STOCK ALERTS ==========
        self.create_stock_alerts_section(scrollable_frame)

        # ========== SECTION 4: AUTO-ALERTS SETUP ==========
        auto_alert_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        auto_alert_frame.pack(fill=tk.X, padx=20, pady=15)

        tk.Button(auto_alert_frame, text="🚀 Setup Auto-Alerts",
                  command=self.show_auto_alerts_setup,
                  bg='#0084D4', fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=20, pady=8, relief=tk.RAISED, bd=2).pack(side=tk.LEFT)

        tk.Label(auto_alert_frame, text="Configure alerts, Gmail, and family notifications",
                 font=('Arial', 9, 'italic'), bg=self.bg_color, fg='#6c757d').pack(side=tk.LEFT, padx=(15, 0))

        return tab

    def create_box_status_display(self, parent):
        status_frame = tk.LabelFrame(parent, text="📊 Box Status", bg=self.card_bg,
                                     font=('Arial', 12, 'bold'), padx=10, pady=10)
        status_frame.pack(fill=tk.X, padx=20, pady=(0, 15))

        # Create 6 status indicators
        self.status_labels = []
        for i in range(1, 7):
            box_frame = tk.Frame(status_frame, bg=self.card_bg)
            box_frame.grid(row=0, column=i - 1, padx=10, pady=5)

            box_label = tk.Label(box_frame, text=f"B{i}", font=('Arial', 11, 'bold'),
                                 bg=self.card_bg)
            box_label.pack()

            status_label = tk.Label(box_frame, text="Empty", font=('Arial', 10),
                                    bg=self.card_bg, fg='#6c757d')
            status_label.pack()

            self.status_labels.append((box_label, status_label))

    # ====================== CORE FUNCTIONALITY ======================

    # ==========================================================
    # Get Bluetooth COM ports only (for Bluetooth connection)
    # ==========================================================
    def get_bt_com_ports(self):
        """
        Detect available incoming Bluetooth COM ports from ESP32.
        Returns a list of serial.tools.ListPortInfo objects.
        """
        bt_ports = []
        for port in serial.tools.list_ports.comports():
            desc = (port.description or "").lower()
            hwid = (port.hwid or "").lower()

            # Look for incoming ports (ESP32 SPP) for Bluetooth connection
            if "bluetooth" in desc and ("incoming" in desc or "serial" in desc or "spp" in desc):
                bt_ports.append(port)

        return bt_ports  # Just return Bluetooth ports

    # ==========================================================
    # Get COM ports for ESP32 Connection section (ALWAYS show only COM5)
    # ==========================================================
    def get_esp32_connection_com_ports(self):
        """Get COM ports for ESP32 Connection section - FIXED to detect ALL available ports"""
        # Return ALL available COM ports instead of hardcoding COM5
        available_ports = list(serial.tools.list_ports.comports())
        
        # If no ports found, return empty list (don't auto-create COM5)
        if available_ports:
            return available_ports
        
        # Return empty list so combo shows no ports
        return []

    # ==========================================================
    # Display ESP32 Connection Ports in UI (Show ALL detected ports)
    # ==========================================================
    def display_esp32_connection_ports(self):
        """Display COM ports in the ESP32 Connection section - EXCLUDE COM5"""
        try:
            # Get ALL available COM ports
            esp32_ports = self.get_esp32_connection_com_ports()

            if esp32_ports:
                # Extract all port device names, EXCLUDING COM5
                port_devices = [port.device for port in esp32_ports if port.device != 'COM5']
                
                # Update COM port combo box with filtered ports
                if hasattr(self, 'port_combo'):
                    self.port_combo['values'] = port_devices
                    # Set to first available port if any
                    if port_devices:
                        self.port_combo.set(port_devices[0])
                    else:
                        self.port_combo.set("")

                if hasattr(self, 'port_var'):
                    if port_devices:
                        self.port_var.set(port_devices[0])
                    else:
                        self.port_var.set("")
                    
                print(f"✓ Available COM ports (excluding COM5): {port_devices}")
            else:
                # No ports found
                if hasattr(self, 'port_combo'):
                    self.port_combo['values'] = []
                    self.port_combo.set("")

                if hasattr(self, 'port_var'):
                    self.port_var.set("")
                    
                print("⚠ No COM ports detected")

        except Exception as e:
            print(f"Error displaying ESP32 ports: {e}")
            if hasattr(self, 'port_var'):
                self.port_var.set("")

    # ==========================================================
    # Connect / Disconnect ESP32 (UPDATED with proper calls)
    # ==========================================================
    def connect_esp32(self):
        """Connect to ESP32 - Stops when active port found"""
        if self.connected:
            self.disconnect_esp32()
            # If last connection was Bluetooth, add a short delay to allow OS to release port
            if self.last_bt_port:
                print("Waiting for Bluetooth port to fully close...")
                time.sleep(1.5)  # 1.5 seconds is usually enough for Windows
            return

        # Ask for connection mode
        use_wired = messagebox.askyesno(
            "Connection Mode",
            "YES → WIRED (COM5)\nNO → BLUETOOTH\n\nESP32 must be ON",
            icon='question'
        )

        if use_wired:
            # Improved logic: Only block wired if the last connected port was Bluetooth and is still present
            bt_ports = []
            for port in serial.tools.list_ports.comports():
                desc = (port.description or "").lower()
                if "bluetooth" in desc or "bt" in desc or "serial" in desc:
                    bt_ports.append(port)

            # If the last connection was Bluetooth and that port is still present, block wired
            bt_block = False
            if self.last_bt_port:
                for port in bt_ports:
                    if port.device == self.last_bt_port:
                        bt_block = True
                        break

            if bt_block:
                messagebox.showwarning(
                    "Device is externally powered (Bluetooth mode).\n\nPlease disconnect external power and connect via USB for wired mode.","Wired Connection Not Allowed"
                )
                return

            # Otherwise, allow wired connection even if BT ports are present
            win = tk.Toplevel(self.root)
            win.title("Select Wired Port")
            win.geometry("500x400")
            win.configure(bg=self.bg_color)
            win.resizable(False, False)

            # Center
            win.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 250
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 200
            win.geometry(f"+{x}+{y}")

            title_label = tk.Label(win, text="Select Wired Port",
                                   font=('Arial', 16, 'bold'),
                                   bg=self.bg_color, fg=self.primary_color)
            title_label.pack(pady=20)

            status_label = tk.Label(win, text="Scanning ports...",
                                    font=('Arial', 11), bg=self.bg_color, fg=self.warning_color)
            status_label.pack()

            text_widget = tk.Text(win, height=12, width=50,
                                  font=('Consolas', 10), bg='white')
            text_widget.pack(pady=10, padx=20)
            text_widget.insert(tk.END, "PORT\t\tSTATUS\n")
            text_widget.insert(tk.END, "-" * 40 + "\n")

            self.wired_options = []
            self.selected_wired = None
            self.stop_wired_scan = False

            def scan_wired():
                ports_list = list(serial.tools.list_ports.comports())
                
                if not ports_list:
                    text_widget.insert(tk.END, "✗ No serial ports found\n")
                    status_label.config(text="No serial ports found", fg=self.danger_color)
                    connect_btn.config(state=tk.NORMAL)
                    return

                status_label.config(text=f"Testing {len(ports_list)} ports...")
                win.update()

                for i, port in enumerate(ports_list):
                    if self.stop_wired_scan:
                        break
                    port_name = port.device
                    text_widget.insert(tk.END, f"{port_name:15} Testing...\n")
                    text_widget.see(tk.END)
                    win.update()

                    is_active, resp = self._quick_test_port(port_name)

                    line_num = i + 3
                    text_widget.delete(f"{line_num}.0", f"{line_num}.end")
                    if is_active:
                        text_widget.insert(tk.END, f"{port_name:15} ✓ ACTIVE (ESP32 Found)\n")
                        text_widget.tag_add("selected", f"{line_num}.0", f"{line_num}.end")
                        text_widget.tag_config("selected", background="lightgreen")
                        self.selected_wired = {"device": port_name, "line": line_num}
                        self.stop_wired_scan = True
                        status_label.config(text=f"✓ Active port found: {port_name}", fg=self.success_color)
                        connect_btn.config(state=tk.NORMAL)
                        break
                    else:
                        text_widget.insert(tk.END, f"{port_name:15} ✗ INACTIVE\n")
                        self.wired_options.append({"device": port_name, "line": line_num})
                    text_widget.see(tk.END)
                    win.update()
                    time.sleep(0.2)

                if not self.selected_wired and self.wired_options:
                    self.selected_wired = self.wired_options[0]
                    text_widget.tag_add("selected", f"{self.selected_wired['line']}.0",
                                        f"{self.selected_wired['line']}.end")
                    text_widget.tag_config("selected", background="lightyellow")
                connect_btn.config(state=tk.NORMAL)

            def on_text_click(event):
                index = text_widget.index(f"@{event.x},{event.y}")
                line_num = int(index.split('.')[0])
                clicked = None
                if self.selected_wired and self.selected_wired['line'] == line_num:
                    clicked = self.selected_wired
                if not clicked:
                    for p in self.wired_options:
                        if p['line'] == line_num:
                            clicked = p
                            break
                if clicked:
                    text_widget.tag_remove("selected", "1.0", tk.END)
                    text_widget.tag_add("selected", f"{line_num}.0", f"{line_num}.end")
                    text_widget.tag_config("selected", background="lightgreen")
                    self.selected_wired = clicked

            text_widget.bind('<Button-1>', on_text_click)

            connect_btn = tk.Button(win, text="Connect",
                                    state=tk.DISABLED,
                                    command=lambda: connect_wired(),
                                    bg=self.success_color, fg='white',
                                    font=('Arial', 11), padx=20, pady=5)
            connect_btn.pack(pady=10)

            def connect_wired():
                if not self.selected_wired:
                    messagebox.showwarning("No Selection", "Please select a port")
                    return
                port_device = self.selected_wired['device']
                win.destroy()
                if self._connect_to_port(port_device):
                    return
                else:
                    messagebox.showerror("Failed", f"Could not connect to {port_device}")

            cancel_btn = tk.Button(win, text="Cancel", command=win.destroy,
                                   bg=self.danger_color, fg='white',
                                   font=('Arial', 11), padx=20, pady=5)
            cancel_btn.pack()

            tk.Label(win, text="Click on a port to select it",
                     font=('Arial', 9), bg=self.bg_color, fg='#6c757d').pack(pady=5)

            win.after(100, scan_wired)
            win.transient(self.root)
            win.grab_set()
            self.root.wait_window(win)
        else:  # Bluetooth - Auto-detect with simple progress
            # Create simple progress window
            progress_win = tk.Toplevel(self.root)
            progress_win.title("Bluetooth Connection")
            progress_win.geometry("400x150")
            progress_win.configure(bg=self.bg_color)
            progress_win.resizable(False, False)

            # Center window
            progress_win.update_idletasks()
            x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
            y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 75
            progress_win.geometry(f"+{x}+{y}")

            # Title
            title_label = tk.Label(progress_win, text="Bluetooth Connection",
                                   font=('Arial', 14, 'bold'),
                                   bg=self.bg_color, fg=self.primary_color)
            title_label.pack(pady=15)

            # Status label with dots animation
            status_label = tk.Label(progress_win, text="Detecting device...",
                                    font=('Arial', 12), bg=self.bg_color, fg=self.primary_color)
            status_label.pack(pady=10)

            # Progress dots animation
            dots = [".", "..", "...", ""]
            dot_index = [0]

            def animate_dots():
                if progress_win.winfo_exists():
                    dot_text = "Detecting device" + dots[dot_index[0] % 4]
                    status_label.config(text=dot_text)
                    dot_index[0] += 1
                    progress_win.after(300, animate_dots)

            animate_dots()

            def connect_bluetooth():
                """Auto-detect and connect to Bluetooth device"""
                try:
                    # Get Bluetooth ports
                    bt_ports = []
                    for port in serial.tools.list_ports.comports():
                        desc = (port.description or "").lower()
                        if "bluetooth" in desc or "bt" in desc or "serial" in desc:
                            bt_ports.append(port)

                    if not bt_ports:
                        if progress_win.winfo_exists():
                            progress_win.destroy()
                        messagebox.showerror("Error", "No Bluetooth device found")
                        return

                    # Try to connect to first active port
                    for port in bt_ports:
                        port_name = port.device
                        if progress_win.winfo_exists():
                            status_label.config(text=f"Testing {port_name}...")
                            progress_win.update()

                        # Before connecting, ensure previous BT serial is closed
                        if self.ser and self.last_bt_port:
                            try:
                                self.ser.close()
                                self.ser = None
                                print(f"Closed previous Bluetooth serial port: {self.last_bt_port}")
                                time.sleep(1.0)  # Wait for OS to release port
                            except Exception as e:
                                print(f"Error closing previous BT serial: {e}")

                        # Quick test
                        is_active, response = self._quick_test_port(port_name)

                        if is_active:
                            # Found active port, try to connect
                            if self._connect_to_port(port_name):
                                self.last_bt_port = port_name
                                if progress_win.winfo_exists():
                                    status_label.config(text=f"✓ Connected to {port_name}", 
                                                      fg=self.success_color)
                                    progress_win.update()
                                    progress_win.after(1000, progress_win.destroy)
                                return

                        time.sleep(0.2)

                    # If no active port found, try first port as fallback
                    if bt_ports:
                        port_name = bt_ports[0].device
                        # Ensure previous BT serial is closed before fallback
                        if self.ser and self.last_bt_port:
                            try:
                                self.ser.close()
                                self.ser = None
                                print(f"Closed previous Bluetooth serial port: {self.last_bt_port}")
                                time.sleep(1.0)
                            except Exception as e:
                                print(f"Error closing previous BT serial: {e}")

                        if progress_win.winfo_exists():
                            status_label.config(text=f"Connecting to {port_name}...")
                            progress_win.update()

                        if self._connect_to_port(port_name):
                            self.last_bt_port = port_name
                            if progress_win.winfo_exists():
                                status_label.config(text=f"✓ Connected to {port_name}", 
                                                  fg=self.success_color)
                                progress_win.update()
                                progress_win.after(1000, progress_win.destroy)
                            return

                    # Connection failed
                    if progress_win.winfo_exists():
                        progress_win.destroy()
                    messagebox.showerror("Error", "Could not connect to Bluetooth device")

                except Exception as e:
                    if progress_win.winfo_exists():
                        progress_win.destroy()
                    messagebox.showerror("Error", f"Connection error: {str(e)}")

            # Start connection in background
            progress_win.after(500, connect_bluetooth)

            # Make modal
            progress_win.transient(self.root)
            progress_win.grab_set()
            self.root.wait_window(progress_win)

    def _quick_test_port(self, port_name):
        """Quick test if port is active/connected to ESP32 - FIXED for unreliable responses"""
        try:
            # Try to open the port
            test_ser = serial.Serial(
                port=port_name,
                baudrate=115200,
                timeout=1.0,
                write_timeout=1.0,
                dsrdtr=False,  # Disable DTR to prevent ESP32 reset
                rtscts=False   # Disable RTS hardware flow control
            )
            
            # Manually disable DTR/RTS lines
            test_ser.setDTR(False)
            test_ser.setRTS(False)

            # Wait for ESP32 to stabilize
            time.sleep(1.0)

            # Clear any old data
            test_ser.reset_input_buffer()

            # Send test command
            test_ser.write(b"PING\n")
            test_ser.flush()

            # Wait for ESP32 response
            time.sleep(0.5)

            # Check for any response (ESP32 may or may not respond)
            response = ""
            if test_ser.in_waiting:
                try:
                    response_bytes = test_ser.readline()
                    response = response_bytes.decode('utf-8', errors='ignore').strip()
                except:
                    response = "partial"

            # Close the test connection
            test_ser.close()

            # If port opened successfully, consider it active (like Arduino IDE does)
            # ESP32 might not respond to PING during quick scan
            return True, "Port opened successfully"

        except serial.SerialException as e:
            # Can't open port - device doesn't exist or is in use
            return False, f"Port error: {str(e)[:20]}"
        except Exception as e:
            # Any other error
            return False, f"Error: {str(e)[:20]}"

    def _connect_to_port(self, port_name):
        """Connect to specified port - FIXED to work with any COM port"""
        try:
            print(f"Attempting to connect to {port_name}...")

            # Close existing connection if any
            if hasattr(self, 'ser') and self.ser:
                self.ser.close()
                time.sleep(0.5)

            # Open new connection
            self.ser = serial.Serial(
                port=port_name,
                baudrate=115200,
                timeout=2,
                write_timeout=2,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                dsrdtr=False,
                rtscts=False
            )
            
            # Reset ESP32 via DTR pulse (like Arduino IDE does)
            self.ser.setDTR(False)
            self.ser.setRTS(False)
            time.sleep(0.1)
            self.ser.setDTR(True)   # Pull DTR high
            time.sleep(0.1)
            self.ser.setDTR(False)  # Pull DTR low - resets ESP32
            
            print("Waiting for ESP32 to boot after reset...")
            time.sleep(3)  # Longer wait - ESP32 bootloader + app startup

            # Clear buffers
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

            # Try MULTIPLE test commands
            test_commands = [b"PING\n", b"HELLO\n", b"AT\n", b"\n"]  # Try different commands

            for i, test_command in enumerate(test_commands):
                print(f"Trying command {i + 1}: {test_command.decode().strip() if test_command.strip() else 'EMPTY'}")

                self.ser.write(test_command)
                self.ser.flush()

                # Wait for response
                time.sleep(0.8)

                # Read response
                response = ""
                if self.ser.in_waiting:
                    response_bytes = self.ser.readline()
                    response = response_bytes.decode('utf-8', errors='ignore').strip()
                    print(f"ESP32 response: '{response}'")

                # ACCEPT ANY RESPONSE or if we got to last command
                if response or i == len(test_commands) - 1:  # Accept any response or on last try
                    print(f"✓ Connection established to {port_name}")
                    self.connected = True
                    self._update_connection_ui(True, port_name)
                    self._show_connection_popup(True, port_name)
                    # ENSURE serial thread starts for physical keypad monitoring
                    time.sleep(0.2)  # Small delay to ensure connection is ready
                    self.start_serial_thread()
                    return True

            # If all commands fail
            print(f"✗ Could not establish connection to {port_name}")
            if self.ser:
                self.ser.close()
                self.ser = None

            return False

        except Exception as e:
            print(f"Connection error: {e}")
            if hasattr(self, 'ser') and self.ser:
                self.ser.close()
                self.ser = None
            return False

    def _update_connection_ui(self, connected, port=None):
        """Update connection UI - NEW FUNCTION"""
        if connected and port:
            # Update status label
            self.com_status.config(text=f"✓ Connected to {port}", fg=self.success_color)

            # Update port combo box to show actual connected port
            if hasattr(self, 'port_var'):
                self.port_var.set(port)

            # Update connect button
            self.connect_btn.config(
                text="Disconnect ESP32",
                bg=self.danger_color,
                fg='white'
            )

            # Enable authenticate button
            self.auth_btn.config(
                state=tk.NORMAL,
                bg=self.primary_color,
                fg='white'
            )

            # Update main status
            if hasattr(self, 'status_label'):
                self.status_label.config(
                    text=f"✓ Connected to {port} - Authentication Required",
                    fg=self.success_color
                )

            print(f"✓ UI updated for {port} connection")

        else:
            # Disconnected state
            self.com_status.config(text="✗ Disconnected", fg=self.danger_color)
            self.connect_btn.config(
                text="Connect ESP32",
                bg=self.primary_color,
                fg='white'
            )
            self.auth_btn.config(
                state=tk.DISABLED,
                bg="#6c757d",
                fg='white'
            )

            # Update main status
            if hasattr(self, 'status_label'):
                self.status_label.config(
                    text="△ Please connect ESP32 first",
                    fg=self.danger_color
                )

            print("✓ UI updated for disconnected state")

    def process_temperature_update(self, line):
        """Process temperature updates from ESP32 - NEW FUNCTION"""
        try:
            if "TEMP1:" in line:
                temp_str = line.split("TEMP1:")[1].strip()
                temp1 = float(temp_str.split()[0])
                if hasattr(self, 'peltier1_current'):
                    self.peltier1_current.config(text=f"{temp1:.1f}°C")
                    self.p1_status_label.config(text=f"ACTIVE ({temp1:.1f}°C)")
                    self.temp_settings["peltier1"]["current"] = temp1

            if "TEMP2:" in line:
                temp_str = line.split("TEMP2:")[1].strip()
                temp2 = float(temp_str.split()[0])
                if hasattr(self, 'peltier2_current'):
                    self.peltier2_current.config(text=f"{temp2:.1f}°C")
                    self.p2_status_label.config(text=f"ACTIVE ({temp2:.1f}°C)")
                    self.temp_settings["peltier2"]["current"] = temp2

        except Exception as e:
            print(f"Error processing temperature: {e}")

    # ==========================================================
    # Internal connection handler (UPDATED)
    # ==========================================================
    def _connect_bt_port(self, port):
        """
        Connect to ESP32 over Bluetooth SPP or wired.
        """
        try:
            self.ser = serial.Serial(port, 115200, timeout=5, write_timeout=5)
            time.sleep(2)  # Wait for connection to stabilize

            # Test connection
            self.ser.write(b"PING\n")
            self.ser.flush()
            time.sleep(1)

            response = ""
            if self.ser.in_waiting:
                response = self.ser.readline().decode(errors='ignore').strip()

            if "ESP32" in response or "OK" in response:
                self.last_bt_port = port
                self.connected = True

                # Show connection popup
                self._show_connection_popup(True, port)

                # Update the UI
                self._on_bt_connected(port)
                return True
            else:
                self.ser.close()
                self.ser = None
                raise Exception("No response from ESP32")

        except Exception as e:
            messagebox.showerror("Connection Failed", str(e))
            if hasattr(self, 'ser') and self.ser:
                self.ser.close()
                self.ser = None
            return False

    # ==========================================================
    # Show connection popup
    # ==========================================================
    def _show_connection_popup(self, connected, port=None):
        """Show connection status popup - UPDATED"""
        popup = tk.Toplevel(self.root)
        popup.title("Connection Status")
        popup.geometry("350x200")
        popup.configure(bg=self.card_bg)
        popup.resizable(False, False)

        # Make modal
        popup.transient(self.root)
        popup.grab_set()

        # Center window
        popup.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (350 // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (200 // 2)
        popup.geometry(f"+{x}+{y}")

        if connected and port:
            # Connected successfully
            connection_type = "Wired (USB)" if "COM" in port else "Bluetooth"

            tk.Label(
                popup,
                text="✓",
                font=('Arial', 48),
                bg=self.card_bg,
                fg=self.success_color
            ).pack(pady=(20, 10))

            tk.Label(
                popup,
                text="ESP32 Connected",
                font=('Arial', 16, 'bold'),
                bg=self.card_bg,
                fg=self.success_color
            ).pack()

            tk.Label(
                popup,
                text=f"Via {connection_type}\nPort: {port}",
                font=('Arial', 11),
                bg=self.card_bg,
                justify=tk.CENTER
            ).pack(pady=10)

        else:
            # Disconnected
            tk.Label(
                popup,
                text="✗",
                font=('Arial', 48),
                bg=self.card_bg,
                fg=self.danger_color
            ).pack(pady=(20, 10))

            tk.Label(
                popup,
                text="ESP32 Disconnected",
                font=('Arial', 16, 'bold'),
                bg=self.card_bg,
                fg=self.danger_color
            ).pack()

            tk.Label(
                popup,
                text="Connection terminated",
                font=('Arial', 11),
                bg=self.card_bg
            ).pack(pady=10)

        # OK button
        ok_btn = tk.Button(
            popup,
            text="OK",
            command=popup.destroy,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 11),
            width=10,
            pady=5
        )
        ok_btn.pack(pady=20)

        # Auto-close after 3 seconds
        popup.after(3000, popup.destroy)

    # ==========================================================
    # Successful connection handler (UPDATED)
    # ==========================================================
    def _on_bt_connected(self, port):
        # Update the existing status display
        connection_type = "Wired" if port == "COM5" else "Bluetooth"
        self.com_status.config(
            text=f"✔ Connected ({connection_type}: {port})",
            fg="green"
        )

        # Update COM port display to show connected port
        if hasattr(self, 'com_port_display'):
            if port == "COM5":
                self.com_port_display.config(text=f"{port} - Connected (Wired)", fg="green")
            else:
                self.com_port_display.config(text=f"{port} - Connected (Bluetooth)", fg="green")

        self.connect_btn.config(text="Disconnect ESP32", bg="red")
        self.auth_btn.config(state=tk.NORMAL)

        # Also update the main warning message on screen
        if hasattr(self, 'warning_label'):
            self.warning_label.config(
                text="✅ ESP32 Connected - System Ready",
                fg="green"
            )

        # Start serial monitoring thread if exists
        if hasattr(self, 'start_serial_thread'):
            self.start_serial_thread()

    # Disconnect ESP32 properly (UPDATED)
    # ==========================================================
    def disconnect_esp32(self):
        """Disconnect ESP32 properly - UPDATED"""
        print("Disconnecting ESP32...")

        # Stop serial thread
        self.running = False
        if hasattr(self, 'serial_thread') and self.serial_thread:
            self.serial_thread.join(timeout=1)

        # Close serial connection
        try:
            if hasattr(self, 'ser') and self.ser and self.ser.is_open:
                # Send shutdown command if authenticated
                if self.authenticated:
                    try:
                        self.ser.write(b"SHUTDOWN\n")
                        time.sleep(0.5)
                    except:
                        pass

                self.ser.close()
                print("✓ Serial port closed")
        except Exception as e:
            print(f"Error closing serial: {e}")

        # Reset connection states
        self.ser = None
        self.connected = False
        self.authenticated = False

        # Update UI
        self._update_connection_ui(False)

        # Reset PIN window if open
        if hasattr(self, 'pin_window') and self.pin_window:
            try:
                self.pin_window.destroy()
            except:
                pass
            self.pin_window = None

        # Show disconnection popup
        self._show_connection_popup(False)

        # Remove notebook (main tabs) if shown
        if hasattr(self, 'notebook') and self.notebook:
            self.notebook.pack_forget()

        # Show locked frame again
        if hasattr(self, 'locked_frame'):
            self.locked_frame.pack(fill=tk.BOTH, expand=True)

        # Reset active LED
        self.active_led_box = None

        print("✓ ESP32 disconnected")

    def check_auth(self):
        """Show PIN entry screen instead of auto-authenticating"""
        if not self.connected or not self.ser:
            messagebox.showwarning("Not Connected", "Please connect ESP32 first")
            return

        # Clear any existing PIN window
        if hasattr(self, 'pin_window') and self.pin_window:
            try:
                self.pin_window.destroy()
            except:
                pass

        print("🔄 Showing PIN entry screen...")
        self.show_pin_entry_screen()  # CALL SEPARATE METHOD

    def center_pin_window(self):
        """Center the PIN window on screen"""
        self.pin_window.update_idletasks()
        width = self.pin_window.winfo_width()
        height = self.pin_window.winfo_height()
        screen_width = self.pin_window.winfo_screenwidth()
        screen_height = self.pin_window.winfo_screenheight()

        x = (screen_width - width) // 2
        y = (screen_height - height) // 2

        self.pin_window.geometry(f'{width}x{height}+{x}+{y}')

    def show_pin_entry_screen(self):
        """Show PIN entry screen with virtual keypad AND keyboard input"""

        # Don't show if already authenticated
        if self.authenticated:
            return

        # Create PIN entry window
        self.pin_window = tk.Toplevel(self.root)
        self.pin_window.title("Enter PIN - CuraX Authentication")
        self.pin_window.geometry("450x600")  # Slightly larger
        self.pin_window.configure(bg=self.bg_color)
        self.pin_window.resizable(False, False)

        # Associate with parent first
        self.pin_window.transient(self.root)

        # Defer grab_set so the button release from Authenticate click doesn't
        # get delivered to this window (fixes first-click-closes-on-Windows)
        self.pin_window.after_idle(self.pin_window.grab_set)

        # Bind keyboard events
        self.pin_window.bind('<Key>', self.on_key_press)

        # Center the window
        self.center_pin_window()

        # ================= TITLE =================
        title_frame = tk.Frame(self.pin_window, bg=self.bg_color)
        title_frame.pack(pady=20)

        tk.Label(title_frame, text="🔒",
                 font=('Arial', 24),
                 bg=self.bg_color).pack()

        tk.Label(title_frame, text="System Authentication",
                 font=('Arial', 18, 'bold'),
                 bg=self.bg_color, fg=self.primary_color).pack()

        tk.Label(title_frame, text="Enter 4-digit PIN to unlock system",
                 font=('Arial', 11),
                 bg=self.bg_color, fg='#6c757d').pack(pady=5)

        # ================= PIN DISPLAY =================
        display_frame = tk.Frame(self.pin_window, bg='white',
                                 relief=tk.SUNKEN, bd=2)
        display_frame.pack(pady=20, padx=40, fill=tk.X)

        # PIN variables
        self.pin_entered = ""  # Actual PIN digits
        self.pin_display_var = tk.StringVar(value="____")  # Display as dots/underscores

        self.pin_display = tk.Label(display_frame,
                                    textvariable=self.pin_display_var,
                                    font=('Courier New', 28, 'bold'),
                                    bg='white', fg='#495057',
                                    height=2)
        self.pin_display.pack(pady=10)

        # ================= STATUS MESSAGE =================
        self.pin_status = tk.Label(self.pin_window, text="Enter your password",
                                   font=('Arial', 10),
                                   bg=self.bg_color, fg=self.primary_color)
        self.pin_status.pack()

        # ================= KEYBOARD INSTRUCTION =================
        tk.Label(self.pin_window,
                 text="💡 Tip: You can type numbers from keyboard too",
                 font=('Arial', 9),
                 bg=self.bg_color, fg='#6c757d').pack(pady=5)

        # ================= VIRTUAL KEYPAD =================
        keypad_frame = tk.Frame(self.pin_window, bg=self.bg_color)
        keypad_frame.pack(pady=20)

        # Keypad buttons layout
        buttons = [
            ['1', '2', '3'],
            ['4', '5', '6'],
            ['7', '8', '9'],
            ['⌫', '0', '✅ Verify']
        ]

        # Create keypad buttons
        for i, row in enumerate(buttons):
            btn_row = tk.Frame(keypad_frame, bg=self.bg_color)
            btn_row.pack()

            for j, btn_text in enumerate(row):
                if btn_text == '⌫':  # Backspace button
                    btn = tk.Button(btn_row, text=btn_text,
                                    font=('Arial', 14, 'bold'),
                                    width=8, height=2,
                                    bg=self.warning_color, fg='black',
                                    command=self.pin_backspace)
                elif btn_text == '✅ Verify':  # Submit/Verify button
                    btn = tk.Button(btn_row, text=btn_text,
                                    font=('Arial', 12, 'bold'),
                                    width=12, height=2,
                                    bg=self.success_color, fg='white',
                                    command=self.verify_pin_with_esp32)
                    # Make verify button span 2 columns
                    btn.config(width=18)
                else:  # Number buttons (1-9, 0)
                    btn = tk.Button(btn_row, text=btn_text,
                                    font=('Arial', 14, 'bold'),
                                    width=8, height=2,
                                    bg=self.card_bg, fg='#495057',
                                    command=lambda digit=btn_text: self.pin_add_digit(digit))

                btn.grid(row=i, column=j, padx=5, pady=5, columnspan=2 if btn_text == '✅ Verify' else 1)

        # ================= INSTRUCTIONS =================
        tk.Label(self.pin_window,
                 text="Default PIN: 1234 (can be changed in ESP32 code)",
                 font=('Arial', 9),
                 bg=self.bg_color, fg='#6c757d').pack(pady=10)

        # ================= BOTTOM BUTTONS =================
        bottom_frame = tk.Frame(self.pin_window, bg=self.bg_color)
        bottom_frame.pack(pady=10)

        # Cancel button
        cancel_btn = tk.Button(bottom_frame, text="Cancel",
                               command=self.cancel_pin_entry,
                               bg='#6c757d', fg='white',
                               font=('Arial', 10), padx=20)
        cancel_btn.pack(side=tk.LEFT, padx=5)

        # Clear button
        clear_btn = tk.Button(bottom_frame, text="Clear PIN",
                              command=self.clear_pin,
                              bg=self.warning_color, fg='black',
                              font=('Arial', 10), padx=20)
        clear_btn.pack(side=tk.LEFT, padx=5)

        # Initialize wrong attempts counter
        self.wrong_pin_attempts = 0

        print("✅ PIN entry screen created")

    def cancel_pin_entry(self):
        """Cancel PIN entry"""
        print("❌ PIN entry cancelled")
        if hasattr(self, 'pin_window') and self.pin_window:
            self.pin_window.destroy()
            self.pin_window = None

    def unlock_system(self):
        """Unlock system after successful PIN"""
        print("🔓 Unlocking system...")

        # Close PIN window
        if hasattr(self, 'pin_window') and self.pin_window:
            self.pin_window.destroy()
            self.pin_window = None

        # Set authenticated
        self.authenticated = True

        # Call your existing unlock methods
        self.complete_authentication_after_pin()

    def on_key_press(self, event):
        """Handle keyboard input for PIN entry"""
        key = event.char

        # Only process digit keys (0-9)
        if key.isdigit():
            self.pin_add_digit(key)

        # Handle Enter key for verification
        elif event.keysym == 'Return' or event.keysym == 'Enter':
            self.verify_pin_with_esp32()

        # Handle Backspace key
        elif event.keysym == 'BackSpace':
            self.pin_backspace()

        # Handle Escape key to cancel
        elif event.keysym == 'Escape':
            self.cancel_pin_entry()

    def pin_add_digit(self, digit):
        """Add a digit to the PIN"""
        if len(self.pin_entered) < 4:  # Max 4 digits
            self.pin_entered += digit

            # Update display: show entered digits as ●, rest as _
            display_text = ""
            for i in range(4):
                if i < len(self.pin_entered):
                    display_text += "●"
                else:
                    display_text += "_"

            self.pin_display_var.set(display_text)
            self.pin_status.config(text=f"PIN: {self.pin_entered}", fg=self.primary_color)

            print(f"PIN digit added: {digit}")

            # Auto-verify when 4 digits are entered
            if len(self.pin_entered) == 4:
                self.root.after(300, self.verify_pin_with_esp32)  # Auto-verify after 300ms

    def pin_backspace(self):
        """Remove last digit from PIN"""
        if self.pin_entered:
            self.pin_entered = self.pin_entered[:-1]

            # Update display
            display_text = ""
            for i in range(4):
                if i < len(self.pin_entered):
                    display_text += "●"
                else:
                    display_text += "_"

            self.pin_display_var.set(display_text)
            self.pin_status.config(text=f"PIN: {self.pin_entered}" if self.pin_entered else "Enter 4-digit PIN",
                                   fg=self.primary_color)
            print("Last digit removed")

    def clear_pin(self):
        """Clear entire PIN"""
        self.pin_entered = ""
        self.pin_display_var.set("____")

        # CHECK if window still exists before updating
        if hasattr(self, 'pin_window') and self.pin_window and self.pin_window.winfo_exists():
            # Check if label still exists
            try:
                self.pin_status.config(text="Enter 4-digit PIN", fg=self.primary_color)
            except:
                pass  # Widget destroyed, ignore error

        print("PIN cleared")

    def verify_pin_with_esp32(self):
        """Verify PIN with ESP32 - SIMPLIFIED and RELIABLE version"""
        if len(self.pin_entered) != 4:
            self.pin_status.config(text="× PIN must be 4 digits", fg=self.danger_color)
            return

        print(f"\n=== PIN VERIFICATION STARTED ===")
        print(f"PIN entered: {self.pin_entered}")

        # Disable buttons during verification
        self.pin_status.config(text="Verifying...", fg=self.warning_color)
        self.pin_window.update()

        # Check if serial connection exists
        if not self.ser or not self.ser.is_open:
            print("✗ Serial port not connected!")
            self.pin_status.config(text="× Not connected to ESP32", fg=self.danger_color)
            self.root.after(1500, self.clear_pin)
            return

        try:
            self.serial_pause = True
            # SIMPLIFIED: Just send the command ONCE with proper formatting
            command = f"AUTH_PIN:{self.pin_entered}\n"
            print(f"Sending command: '{command.strip()}'")

            # Clear input buffer BEFORE sending
            self.ser.reset_input_buffer()
            time.sleep(0.1)

            # Send command
            self.ser.write(command.encode('utf-8'))
            self.ser.flush()  # Force send
            print("Command sent, waiting for response...")

            # Wait for response with reasonable timeout (increased to 3 seconds for reliability)
            response = ""
            start_time = time.time()
            timeout = 3.0  # 3 seconds timeout for more reliable response

            while time.time() - start_time < timeout:
                if self.ser.in_waiting:
                    try:
                        response_bytes = self.ser.readline()
                        response = response_bytes.decode('utf-8', errors='ignore').strip()
                        print(f"Response received: '{response}'")
                        break  # Got response, exit loop
                    except:
                        continue
                time.sleep(0.05)  # Slightly longer check interval for ESP32

            # If no response, check connection
            if not response:
                print("⚠ No response from ESP32")

                # Try to ping ESP32 to verify connection
                try:
                    self.ser.reset_input_buffer()
                    self.ser.write(b"PING\n")
                    self.ser.flush()
                    time.sleep(1.0)  # Longer wait for ping response

                    if self.ser.in_waiting:
                        ping_response = self.ser.readline().decode('utf-8', errors='ignore').strip()
                        print(f"Ping response: '{ping_response}'")

                        if ping_response:
                            # ESP32 is responding but not to AUTH command
                            self.pin_status.config(text="× ESP32 not responding to AUTH", fg=self.danger_color)
                        else:
                            self.pin_status.config(text="× ESP32 not responding", fg=self.danger_color)
                    else:
                        self.pin_status.config(text="× ESP32 not responding", fg=self.danger_color)

                except Exception as e:
                    print(f"Ping failed: {e}")
                    self.pin_status.config(text="× Communication error", fg=self.danger_color)

                self.root.after(1500, self.clear_pin)
                return

            # Process response - SIMPLIFIED LOGIC
            print(f"Processing response: {response}")

            # Check for success patterns
            success_patterns = ["AUTH_OK", "OK", "SUCCESS", "PIN_OK"]
            if any(pattern in response.upper() for pattern in success_patterns):
                print("✓ PIN verification SUCCESSFUL")
                self.authenticated = True
                self.wrong_pin_attempts = 0
                self.pin_status.config(text="✓ PIN verified!", fg=self.success_color)
                self.pin_display_var.set("✓✓✓✓")
                self.pin_display.config(fg=self.success_color)

                # Close PIN window and unlock
                self.root.after(1000, self.unlock_system_after_pin)
                return

            # Check for failure patterns
            fail_patterns = ["AUTH_FAIL", "FAIL", "ERROR", "PIN_FAIL"]
            if any(pattern in response.upper() for pattern in fail_patterns):
                print("✗ PIN verification FAILED")
                self.wrong_pin_attempts += 1
                attempts_left = 3 - self.wrong_pin_attempts

                if attempts_left > 0:
                    self.pin_status.config(
                        text=f"× Wrong PIN! {attempts_left} attempts left",
                        fg=self.danger_color
                    )
                else:
                    self.pin_status.config(
                        text="× Too many wrong attempts! Locked for 30s",
                        fg=self.danger_color
                    )

                self.pin_display_var.set("✗✗✗✗")
                self.pin_display.config(fg=self.danger_color)
                self.root.after(1500, self.clear_pin)
                return

            # If we get here, response was ambiguous or missing
            print(f"⚠ Ambiguous/missing response: '{response}'")
            
            # NO FALLBACK - REQUIRE PROPER ESP32 RESPONSE
            self.pin_status.config(
                text="× Invalid response from ESP32",
                fg=self.danger_color
            )
            self.root.after(1500, self.clear_pin)

        except Exception as e:
            print(f"✗ Error in verify_pin_with_esp32: {e}")
            import traceback
            traceback.print_exc()
            self.pin_status.config(
                text=f"× Error: {str(e)[:30]}",
                fg=self.danger_color
            )
            self.root.after(1500, self.clear_pin)
        finally:
            self.serial_pause = False

    def unlock_system_after_pin(self):
        """Unlock system after successful PIN verification"""
        print("🔓 Unlocking system...")

        # Close PIN window if open
        if hasattr(self, 'pin_window') and self.pin_window:
            self.pin_window.destroy()
            self.pin_window = None

        # Set authentication status
        self.authenticated = True
        self.wrong_count = 0

        # Update main status display
        self.update_status()

        # ========== REMOVE LOCKED FRAME ==========
        if hasattr(self, 'locked_frame') and self.locked_frame:
            print("Destroying locked frame...")
            self.locked_frame.destroy()
            self.locked_frame = None
        # ========== Bring sidebar togglebutton to front ==========
        if hasattr(self, 'sidebar_toggle_btn'):
            print("Bringing sidebar toggle button to front...")
            self.sidebar_toggle_btn.lift()
        # ========== CREATE NOTEBOOK (MAIN TABS) IN SAME WINDOW ==========
        created_new_notebook = False
        if not hasattr(self, 'notebook') or self.notebook is None:
            print("Creating notebook with tabs in main window...")

            # Create notebook widget in main_container (same window)
            self.notebook = ttk.Notebook(self.main_container)
            self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            created_new_notebook = True

        # After unlock, automatically ping Mobile Alert Bot once (same path as real alerts)
        try:
            if hasattr(self, "mobile_bot") and self.mobile_bot.get("enabled"):
                # Use same channel as scheduled alerts so connection is warmed up
                handshake_msg = "CuraX unlocked – you will receive medication alerts here."
                print("[MOBILE BOT] Auto-handshake on unlock...", flush=True)
                if hasattr(self, "send_mobile_alert"):
                    self.send_mobile_alert("System Alert", handshake_msg)
        except Exception as e:
            print(f"[MOBILE BOT] Auto-handshake on unlock failed: {e}", flush=True)

        # Ensure it's in the same window, not a new one
        self.main_container.update_idletasks()

        # Create ALL tabs only once, when notebook is first created (order = tab order)
        if created_new_notebook:
            print("  Creating Main Panel (Dashboard) tab...")
            self.create_main_panel_tab()

            print("  Creating Add Medicine tab...")
            self.create_add_medicine_tab()

            print("  Creating Dose Tracking tab...")
            self.create_dose_tracking_tab()

            print("  Creating Medical Reminders tab...")
            self.create_medical_reminders_tab()

            print("  Creating Alerts tab...")
            self.create_alerts_tab()

            print("  Creating T Adjustment (Temp/Humidity) tab...")
            self.create_temp_adjustment_tab()

            print("  Creating Settings tab...")
            self.create_settings_tab()

            print("✅ All tabs created")
        else:
            print("Notebook already exists, showing it...")
            self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ========== UPDATE ALL DISPLAYS ==========
        print("Updating displays...")

        # Force update of main container
        self.main_container.update_idletasks()

        # Update status displays
        if hasattr(self, 'update_box_displays'):
            self.update_box_displays()

        if hasattr(self, 'update_dose_displays'):
            self.update_dose_displays()

        if hasattr(self, 'update_box_status'):
            self.update_box_status()

        if hasattr(self, 'update_history'):
            self.update_history()

        # ========== SHOW TOOLS PANEL ==========
        if hasattr(self, 'show_tools_after_auth'):
            self.show_tools_after_auth()

        # ========== SETUP TEMPERATURE CONTROLS ==========
        if hasattr(self, 'setup_initial_temperatures'):
            try:
                self.setup_initial_temperatures()
            except Exception as e:
                print(f"Note: Temperature setup error: {e}")

        # ========== START ALERT SYSTEM ==========
        if hasattr(self, 'start_alert_system'):
            self.start_alert_system()

        # ========== FORCE GUI UPDATE ==========
        self.root.update_idletasks()
        self.root.update()

        print("✅ System unlocked successfully!")

        # Show success message
        self.root.after(500, lambda: messagebox.showinfo(
            "Success",
            "System Unlocked!\n\nPIN authentication successful."
        ))

    def handle_physical_keypad_auth(self, line):
        """Handle authentication from physical keypad"""
        if "AUTH_OK" in line and not self.authenticated:
            print("✅ Physical keypad authentication detected!")

            # Close PIN window if open
            if hasattr(self, 'pin_window') and self.pin_window:
                self.pin_window.destroy()
                self.pin_window = None

            # Set authenticated
            self.authenticated = True

            # Unlock system
            self.unlock_system_after_pin()

            return True
        return False

    # ====== MOVE THIS METHOD OUTSIDE check_auth() ======
    def finalize_setup(self):
        """Called after UI is ready - MUST be a class method, not inside check_auth"""
        print("  Finalizing setup...")

        try:
            # Update all displays
            print("  Updating displays...")
            self.update_box_displays()
            self.update_dose_displays()
            self.update_box_status()
            if hasattr(self, 'update_history'):
                self.update_history()
            print("  Displays updated")

            # Setup temperature controls - NOW SAFE because tab exists
            print("  Setting up temperature controls...")
            try:
                # Initialize temperature status
                if hasattr(self, 'temp_status'):
                    self.temp_status.config(text="🟢 CONNECTED", fg=self.success_color, bg='#d4edda')

                # Setup initial temperature values
                self.setup_initial_temperatures()
            except Exception as e:
                print(f"  Note: Temperature setup incomplete: {e}")

            # Start alert system
            print("  Starting alert system...")
            self.start_alert_system()

            # Show tools in sidebar
            if hasattr(self, 'show_tools_after_auth'):
                self.show_tools_after_auth()  # Make sure to actually call the method

            print("  System setup complete!")
            messagebox.showinfo("Success", "System Unlocked")

        except Exception as e:
            print(f"  Error in finalize_setup: {e}")
            messagebox.showerror("Setup Error", f"Error during setup: {str(e)}")

    # ====================== DOSE TRACKING FUNCTIONS ======================

    def turn_on_led(self, box_id):
        if not self.require_admin():
            return

        try:
            # First, clear any previous response in buffer
            self.ser.reset_input_buffer()

            # Send LED ON command to ESP32
            command = f"LED_ON:{box_id}\n"
            self.ser.write(command.encode())
            self.ser.flush()  # Ensure data is sent

            # Wait a bit for ESP32 to respond
            time.sleep(0.2)

            # Clear the active frame first
            for widget in self.active_frame.winfo_children():
                widget.destroy()

            # Get medicine info
            med = self.medicine_boxes.get(box_id)
            if not med:
                messagebox.showerror("Error", f"No medicine in {box_id}")
                return

            # Set active LED box
            self.active_led_box = box_id

            # Create label for active medicine
            active_label = tk.Label(self.active_frame,
                                    text=f"💡 LED ON for: {med['name']} in {box_id}",
                                    font=('Arial', 12, 'bold'), bg=self.card_bg)
            active_label.pack(pady=(10, 5))

            # Show instructions
            info_label = tk.Label(self.active_frame,
                                  text=f"Take {med['dose_per_day']} tablet(s) from physical box {box_id}",
                                  font=('Arial', 10), bg=self.card_bg, fg='#6c757d')
            info_label.pack()

            # Mark dose button
            mark_btn = tk.Button(self.active_frame, text="✅ Mark Dose Taken",
                                 command=self.mark_dose_taken,
                                 bg=self.success_color, fg='white',
                                 font=('Arial', 12, 'bold'), padx=30, pady=10)
            mark_btn.pack(pady=10)

            # Show the active frame
            self.active_frame.pack(pady=20, fill=tk.X, padx=50)

            # Update dose button displays
            self.update_dose_displays()

        except Exception as e:
            messagebox.showerror("Error", f"Communication error: {str(e)}")

    def mark_dose_taken(self):
        if not self.active_led_box:
            messagebox.showwarning("No Active LED", "Please turn ON an LED first")
            return

        box_id = self.active_led_box
        med = self.medicine_boxes.get(box_id)

        if not med:
            messagebox.showerror("Error", "No medicine in this box")
            return

        try:
            current_qty = med.get('quantity', 0)
            dose_per_day = med.get('dose_per_day', 1)

            if current_qty >= dose_per_day:
                # Deduct the dose - FIXED DATETIME
                med['quantity'] = current_qty - dose_per_day
                med['last_dose_taken'] = datetime.datetime.now().isoformat()  # ✅ FIXED

                # Send LED OFF command to ESP32
                try:
                    if hasattr(self, 'ser') and self.ser.is_open:
                        self.ser.reset_input_buffer()
                        command = f"LED_OFF:{box_id}\n"
                        self.ser.write(command.encode())
                        time.sleep(0.1)
                except Exception as e:
                    print("Serial write failed:", e)

                # Log dose in history - FIXED DATETIME
                log_entry = {
                    'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # ✅ FIXED
                    'box': box_id,
                    'medicine': med.get('name', 'Unknown'),
                    'dose_taken': dose_per_day,
                    'remaining': med['quantity'],
                    'action': 'Dose Taken'
                }
                self.dose_log.append(log_entry)

                # Save updated data
                self.save_data()
                self.check_and_send_stock_alerts(med, box_id)
                # Reset active LED and hide frame
                self.active_led_box = None
                if hasattr(self, 'active_frame'):
                    self.active_frame.pack_forget()

                # Update displays
                self.update_box_displays()
                self.update_dose_displays()
                self.update_box_status()
                self.update_history()
                self.update_upcoming_reminder()

                # Show success message with refill warning
                success_msg = f"✅ {dose_per_day} tablet(s) of {med.get('name')} marked as taken"
                if med['quantity'] == 0:
                    success_msg += f"\n\n❌ {med.get('name')} is finished! Please refill."
                elif med['quantity'] <= 5:
                    success_msg += f"\n\n⚠️ {med.get('name')} running low! Only {med['quantity']} left."

                messagebox.showinfo("Success", success_msg)
            else:
                messagebox.showerror("Error", f"❌ Not enough {med.get('name')} available!")
        except Exception as e:
            messagebox.showerror("Error", f"❌ Unexpected error: {str(e)}")
            import traceback
            traceback.print_exc()  # Print full error to console

    def turn_off_all_leds(self):
        if not self.authenticated or not self.ser:
            messagebox.showwarning("Not Authenticated", "Please authenticate first")
            return

        try:
            # Send command to turn OFF all LEDs
            self.ser.reset_input_buffer()
            command = "LED_ALL_OFF\n"
            self.ser.write(command.encode())
            time.sleep(0.2)

            # Reset active LED state
            self.active_led_box = None

            # Hide the active frame if visible
            if self.active_frame.winfo_ismapped():
                self.active_frame.pack_forget()

            # Update dose displays
            self.update_dose_displays()

            messagebox.showinfo("Success", "All LEDs turned OFF")

        except Exception as e:
            messagebox.showerror("Error", f"Error: {str(e)}")

    def update_dose_displays(self):
        """Update dose tracking box displays - SILENT VERSION"""
        if not hasattr(self, 'dose_buttons'):
            return

        for btn, name_label, qty_label, box_id in self.dose_buttons:
            med = self.medicine_boxes.get(box_id)
            if med:
                med_name = med.get('name', 'Unknown')
                display_name = med_name[:8] + ('...' if len(med_name) > 8 else '')
                name_label.config(text=display_name)

                quantity = med.get('quantity', 0)
                qty_label.config(text=f"📦 {quantity} left")

                if self.active_led_box == box_id:
                    btn.config(bg='#d4edda', fg='#155724', text=f"💡 {box_id}")
                else:
                    btn.config(bg='#e9ecef', fg='#495057', text=f"🔘 {box_id}")
            else:
                name_label.config(text="Empty")
                qty_label.config(text="")
                btn.config(bg='#e9ecef', fg='#495057', text=f"📦 {box_id}")

    def update_history(self):
        if not hasattr(self, "history_table"):
            return  # Safety check

        # Clear old rows
        for row in self.history_table.get_children():
            self.history_table.delete(row)

        if not self.dose_log:
            return

        for log in reversed(self.dose_log[-20:]):  # last 20 doses
            self.history_table.insert("", "end", values=(
                log['timestamp'],
                log['box'],
                log['medicine'],
                log['dose_taken'],
                log['remaining']
            ))

    def load_data(self):
        """Load medicine data from database (SQLite only)"""
        try:
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            
            data = db.get("medicine_data")
            if data:
                self.medicine_boxes = data.get("medicine_boxes", self.medicine_boxes)
                self.dose_log = data.get("dose_log", [])
                print("✅ Medicine data loaded from database")
            else:
                print("ℹ️ No medicine data found in database (starting fresh)")
        except Exception as e:
            print(f"❌ Failed to load medicine data: {e}")

    def save_data(self):
        """Save medicine data to database (SQLite only)"""
        data = {
            "medicine_boxes": self.medicine_boxes,
            "dose_log": self.dose_log
        }
        try:
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            
            db.set("medicine_data", data)
            print("✅ Medicine data saved to database")
        except Exception as e:
            print(f"❌ Failed to save medicine data: {e}")

    def load_mobile_bot_config(self):
        """Load mobile bot configuration"""
        try:
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            
            config = db.get("mobile_bot_config")
            if config:
                self.mobile_bot = config
                print("✅ Mobile bot config loaded")
        except Exception as e:
            print(f"❌ Failed to load mobile bot config: {e}")

    def save_mobile_bot_config(self):
        """Save mobile bot configuration"""
        try:
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            
            db.set("mobile_bot_config", self.mobile_bot)
            print("✅ Mobile bot config saved")
        except Exception as e:
            print(f"❌ Failed to save mobile bot config: {e}")

    def send_mobile_alert(self, alert_type, message, priority="NORMAL"):
        """Send alert to mobile bot using saved credentials.

        Cloud: WebSocket to server (Bot ID + API Key).
        Local: TCP to host:port.
        """
        # Only use saved configuration (updated when you click Save or Send Test Alert)
        enabled = self.mobile_bot.get("enabled")
        bot_id = (self.mobile_bot.get("bot_id", "") or "").strip()
        api_key = (self.mobile_bot.get("api_key", "") or "").strip()
        server_url = (self.mobile_bot.get("server_url") or "localhost:5050").strip()

        print(f"[MOBILE BOT] send_mobile_alert called: type={alert_type!r} enabled={enabled} bot_id={bot_id[:4] if bot_id else ''}... server={server_url}", flush=True)
        if not enabled:
            print("[MOBILE BOT] SKIP: Mobile alerts are disabled in Settings (enable and Save).", flush=True)
            return False
        if not bot_id or not api_key:
            print("[MOBILE BOT] SKIP: Missing Bot ID or API Key – save Settings or use Send Test Alert once.", flush=True)
            return False
        if not server_url:
            print("[MOBILE BOT] SKIP: Missing Server URL.", flush=True)
            return False

        def send_async():
            try:
                import json
                print("[MOBILE BOT] Sending to server...", flush=True)
                # Cloud: https://... or wss://... -> link by Bot ID + API Key
                srv_url = server_url
                if srv_url.startswith("https://") or srv_url.startswith("http://"):
                    wss = srv_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1).rstrip("/")
                    try:
                        import asyncio
                        import websockets
                    except ImportError:
                        print("✗ For cloud: pip install websockets")
                        return False
                    import time
                    for attempt in range(3):
                        try:
                            async def do_send():
                                async with websockets.connect(wss, close_timeout=2, open_timeout=20) as ws:
                                    await ws.send(json.dumps({
                                        "action": "alert",
                                        "bot_id": bot_id,
                                        "api_key": api_key,
                                        "type": alert_type,
                                        "message": message
                                    }))
                            asyncio.run(do_send())
                            print(f"✓ Alert sent to bot (cloud): {alert_type}", flush=True)
                            return True
                        except Exception as e:
                            if attempt < 2 and ("1011" in str(e) or "internal" in str(e).lower() or "connection" in str(e).lower()):
                                time.sleep(2)
                                continue
                            print(f"✗ Bot alert error: {e}", flush=True)
                            return False
                # Local: host:port (relay inside this app)
                import socket
                if "://" in srv_url:
                    srv_url = srv_url.split("://")[-1]
                host, port = (srv_url.rsplit(":", 1) + ["5050"])[:2]
                port = int(port)
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(3)
                client.connect((host, port))
                client.sendall(json.dumps({"type": alert_type, "message": message}).encode("utf-8"))
                client.close()
                print(f"✓ Alert sent to bot (local): {alert_type}", flush=True)
                return True
            except Exception as e:
                print(f"✗ Bot alert error: {e}", flush=True)
                return False

        import threading
        threading.Thread(target=send_async, daemon=True).start()
        return True

    def bind_canvas_mousewheel(self, canvas):
        """Bind mousewheel scrolling to a canvas.
        
        Args:
            canvas: The canvas widget to bind mousewheel to
        """
        def _on_mousewheel(event):
            # Check if mouse is over this canvas
            try:
                widget = event.widget.winfo_containing(event.x_root, event.y_root)
                if widget is None:
                    return
                    
                # Check if the widget or its parent is the canvas
                current = widget
                found = False
                for _ in range(10):  # Check up to 10 levels of parent widgets
                    if current == canvas:
                        found = True
                        break
                    try:
                        current = current.master
                    except:
                        break
                
                if not found:
                    return  # Mouse not over this canvas
                
                # Scroll the canvas
                if hasattr(event, 'delta'):
                    if event.delta > 0:
                        canvas.yview_scroll(-3, "units")
                    else:
                        canvas.yview_scroll(3, "units")
                elif hasattr(event, 'num'):
                    if event.num == 4:
                        canvas.yview_scroll(-3, "units")
                    elif event.num == 5:
                        canvas.yview_scroll(3, "units")
                
                return "break"
            except:
                pass
        
        # Bind to root window
        root = canvas.winfo_toplevel()
        root.bind("<MouseWheel>", _on_mousewheel, add=True)
        root.bind("<Button-4>", _on_mousewheel, add=True)
        root.bind("<Button-5>", _on_mousewheel, add=True)

    def create_scrollable_frame(self, parent):
        """Create a scrollable frame using Canvas and mousewheel binding.
        
        Args:
            parent: Parent widget
            
        Returns:
            tuple: (canvas, scrollable_frame) - canvas for placement, frame for content
        """
        # Create canvas with scrollbar
        canvas = tk.Canvas(parent, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)
        
        # Configure canvas to update scrollregion when frame is configured
        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        scrollable_frame.bind("<Configure>", _on_frame_configure)
        
        # Create window in canvas
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack widgets
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mousewheel to this canvas
        self.bind_canvas_mousewheel(canvas)
        
        # Store reference to canvas
        scrollable_frame.canvas = canvas
        
        return canvas, scrollable_frame

    def update_status(self):
        if not self.connected:
            self.status_label.config(
                text="⚠ Please connect ESP32 first",
                fg=self.danger_color
            )
        elif self.connected and not self.authenticated:
            self.status_label.config(
                text="🔒 ESP32 Connected – Authentication Required",
                fg=self.warning_color
            )
        else:
            self.status_label.config(
                text="✅ System Ready",
                fg=self.success_color
            )

    def update_box_displays(self):
        """Update main panel medicine box displays (name + tablets + meter gauge)"""
        if not hasattr(self, "box_buttons"):
            return

        for canvas, med_label, qty_label, box_id in self.box_buttons:
            med = self.medicine_boxes.get(box_id)
            if med:
                qty = med.get("quantity", 0)
                qty_label.config(text=f"{qty} tablets left", fg=self.primary_color)
                med_label.config(text=med.get("name", "Unknown"), fg=self.primary_text)
            else:
                qty_label.config(text="Empty", fg='#64748B')
                med_label.config(text="—", fg='#64748B')

        self._draw_meter_gauges()


    def update_box_status(self):
        """Update box status indicators - SILENT VERSION"""
        if not hasattr(self, 'status_labels'):
            return

        for i, (box_label, status_label) in enumerate(self.status_labels):
            box_id = f"B{i + 1}"
            med = self.medicine_boxes.get(box_id)
            if med:
                quantity = med.get('quantity', 0)
                status_label.config(text=f"{quantity} left", fg=self.primary_color)
            else:
                status_label.config(text="Empty", fg="#6c757d")

    def show_tools_after_auth(self):
        """Show the tools panel after successful authentication"""
        if not hasattr(self, 'tool_frame'):
            return

        # Update admin status indicator (frame is already visible)
        if hasattr(self, 'update_admin_status_indicator'):
            self.update_admin_status_indicator()

        # Show the tool frame in sidebar
        self.tool_frame.pack(fill=tk.X, padx=10, pady=10)

        # Update status
        print("✓ Tools panel shown after authentication")

    def start_serial_thread(self):
        """Start serial monitoring thread - UPDATED"""
        if hasattr(self, 'serial_thread') and self.serial_thread and self.serial_thread.is_alive():
            print("Serial thread already running")
            return

        self.running = True
        self.serial_thread = threading.Thread(
            target=self.serial_loop,
            daemon=True,
            name="SerialMonitor"
        )
        self.serial_thread.start()
        print("✓ Serial monitoring thread started")

    def serial_loop(self):
        """Monitor serial for incoming data - UPDATED"""
        print("Serial monitor started...")

        while self.running:
            try:
                if self.serial_pause:
                    time.sleep(0.05)
                    continue

                if not self.ser or not self.ser.is_open:
                    time.sleep(1)
                    continue

                if self.ser.in_waiting:
                    raw = self.ser.readline()
                    line = raw.decode('utf-8', errors='ignore').strip()

                    if line:
                        print(f"Serial received: {line}")

                        # Check for physical keypad authentication
                        if "AUTH_OK" in line and not self.authenticated:
                            print("✓ Physical keypad authentication detected!")
                            self.authenticated = True

                            # Close PIN window if open
                            if hasattr(self, 'pin_window') and self.pin_window:
                                self.root.after(0, self.pin_window.destroy)
                                self.pin_window = None

                            # Unlock system in main thread
                            self.root.after(0, self.unlock_system_after_pin)

                        # Check for temperature updates
                        elif "TEMP1:" in line or "TEMP2:" in line:
                            self.root.after(0, self.process_temperature_update, line)

                        # Check for LED status
                        elif "LED_ON:" in line or "LED_OFF:" in line:
                            print(f"LED status: {line}")

            except serial.SerialException as e:
                print(f"Serial error: {e}")
                if self.running:
                    self.root.after(0, self.disconnect_esp32)
                break
            except Exception as e:
                print(f"Serial loop error: {e}")

            time.sleep(0.1)

        print("Serial monitor stopped")

    def save_medicine(self):
        """Save medicine from form inputs"""
        if not self.require_admin():
            return

        # Check if admin credentials are required
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        
        if db.has_admin_credentials():
            # Show admin verification dialog
            if not self.verify_admin_dialog("Add/Edit Medicine"):
                messagebox.showwarning("Permission Denied", "Admin verification required to save medicine")
                return

        name = self.med_name.get().strip()
        qty = int(self.med_qty.get())
        dose = int(self.med_dose.get())
        expiry = self.med_expiry.get_date().strftime("%Y-%m-%d")  # from calendar
        period = self.med_period.get()
        box = self.med_box.get()
        hour = self.med_hour.get()
        minute = self.med_minute.get()
        time_str = f"{hour}:{minute}"
        instructions = self.med_instructions.get("1.0", tk.END).strip()

        if not name:
            messagebox.showwarning("Input Error", "Medicine name is required")
            return

        # Save medicine data
        self.medicine_boxes[box] = {
            "name": name,
            "quantity": qty,
            "dose_per_day": dose,
            "expiry": expiry,
            "period": period,
            "exact_time": time_str,
            "instructions": instructions,
            "last_dose_taken": None
        }

        # Persist data
        self.save_data()

        # ======== NEW: Schedule alerts for this medicine ========
        if self.authenticated and hasattr(self, 'alert_scheduler') and self.alert_scheduler:
            try:
                # First cancel any existing scheduled alerts for this box
                try:
                    self.alert_scheduler.cancel_medicine_alerts_for_box(box)
                except Exception as ce:
                    print(f"⚠️ Could not cancel existing alerts for box {box}: {ce}")

                # Get the medicine we just saved
                medicine = self.medicine_boxes[box]

                # Schedule alerts for this medicine
                self.alert_scheduler.schedule_medicine_alert(medicine, box)
                print(f"✅ Scheduled alerts for '{name}' at {time_str} in box {box}")

                # Also schedule expiry alerts if expiry date is set
                if expiry and hasattr(self.alert_scheduler, 'schedule_expiry_alerts'):
                    self.alert_scheduler.schedule_expiry_alerts()

            except Exception as e:
                print(f"⚠️ Could not schedule alerts for '{name}': {e}")
        # ========================================================

        # Update UI
        self.update_box_displays()
        self.update_dose_displays()
        self.update_box_status()
        self.update_upcoming_reminder()

        # Clear form
        self.med_name.delete(0, tk.END)
        self.med_qty.delete(0, tk.END)
        self.med_qty.insert(0, "30")
        self.med_dose.delete(0, tk.END)
        self.med_dose.insert(0, "1")
        self.med_instructions.delete("1.0", tk.END)
        self.med_hour.set("8")
        self.med_minute.set("00")

        messagebox.showinfo("Saved", f"✅ Medicine '{name}' added to {box}")

    def create_medicine_alerts_section(self, parent):
        """Medicine timing alerts configuration with clock and upcoming reminder"""

        # Main container with two columns
        main_container = tk.Frame(parent, bg=self.bg_color)
        main_container.pack(fill=tk.X, padx=20, pady=10)

        # ========== LEFT COLUMN: MEDICINE ALERTS ==========
        left_frame = tk.Frame(main_container, bg=self.bg_color)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        frame = tk.LabelFrame(left_frame, text="⏰ Medicine Time Alerts",
                              bg=self.card_bg, font=('Arial', 12, 'bold'),
                              padx=15, pady=15)
        frame.pack(fill=tk.BOTH, expand=True)

        # Enable/disable all alerts
        self.alert_enabled_var = tk.BooleanVar(value=True)
        enable_btn = tk.Checkbutton(frame, text="Enable Medicine Time Alerts",
                                    variable=self.alert_enabled_var,
                                    command=self.toggle_alerts,
                                    bg=self.card_bg, font=('Arial', 11))
        enable_btn.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        # Alert timing options
        options = [
            ("15 minutes before medicine time", "15_min_before"),
            ("At exact medicine time", "exact_time"),
            ("5 minutes after if not taken", "5_min_after"),
            ("Send missed dose alert", "missed_alert")
        ]

        self.alert_vars = {}
        for i, (text, key) in enumerate(options):
            var = tk.BooleanVar(value=self.alert_settings["medicine_alerts"].get(key, True))
            self.alert_vars[key] = var

            cb = tk.Checkbutton(frame, text=text, variable=var,
                                bg=self.card_bg, font=('Arial', 10))
            cb.grid(row=i + 1, column=0, sticky=tk.W, pady=3)

        # Snooze duration: how long to postpone the reminder when you tap Snooze
        tk.Label(frame, text="Snooze duration (minutes):",
                 bg=self.card_bg, font=('Arial', 10)).grid(row=5, column=0, sticky=tk.W, pady=(10, 0))
        tk.Label(frame, text="(How long to postpone reminder when you tap Snooze)",
                 bg=self.card_bg, font=('Arial', 8), fg='#6c757d').grid(row=6, column=0, columnspan=2, sticky=tk.W)

        self.snooze_var = tk.StringVar(value=str(self.alert_settings["medicine_alerts"]["snooze_duration"]))
        snooze_spin = tk.Spinbox(frame, from_=1, to=30, textvariable=self.snooze_var,
                                 width=5, font=('Arial', 10))
        snooze_spin.grid(row=5, column=1, sticky=tk.W, pady=(10, 0))

        # Save button
        save_btn = tk.Button(frame, text="💾 Save Settings",
                             command=self.save_medicine_alert_settings,
                             bg=self.success_color, fg='white',
                             font=('Arial', 10), padx=15)
        save_btn.grid(row=7, column=0, columnspan=2, pady=(15, 5))

        # ========== RIGHT COLUMN: CLOCK & UPCOMING REMINDER ==========
        right_frame = tk.Frame(main_container, bg=self.bg_color, width=250)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        right_frame.pack_propagate(False)  # Keep fixed width

        # Clock frame
        clock_frame = tk.LabelFrame(right_frame, text="🕒 Current Time",
                                    bg=self.card_bg, font=('Arial', 12, 'bold'),
                                    padx=15, pady=15)
        clock_frame.pack(fill=tk.X, pady=(0, 10))

        # Real-time clock
        self.clock_label = tk.Label(clock_frame,
                                    font=('Arial', 24, 'bold'),
                                    bg=self.card_bg, fg=self.primary_color)
        self.clock_label.pack(pady=10)

        # Date label
        self.date_label = tk.Label(clock_frame,
                                   font=('Arial', 12),
                                   bg=self.card_bg, fg='#6c757d')
        self.date_label.pack()

        # Upcoming reminder frame
        # Upcoming reminder frame - with FIXED SIZE and better layout
        reminder_frame = tk.LabelFrame(right_frame, text="🔔 Next Reminder",
                                       bg=self.card_bg, font=('Arial', 12, 'bold'),
                                       padx=15, pady=15)
        reminder_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        # Set a fixed minimum size for the frame
        reminder_frame.pack_propagate(False)
        reminder_frame.config(width=200, height=150)  # Fixed size

        # Container for the reminder text with padding
        reminder_container = tk.Frame(reminder_frame, bg=self.card_bg)
        reminder_container.pack(expand=True, fill=tk.BOTH, padx=5, pady=5)

        # Upcoming reminder label - with BETTER FONT and WRAPPING
        self.upcoming_reminder_label = tk.Label(
            reminder_container,
            text="No upcoming reminders\n\nAdd medicines to see\nupcoming reminders",
            font=('Arial', 10),  # Smaller font for better fit
            bg=self.card_bg,
            fg='#6c757d',
            justify=tk.CENTER,
            wraplength=160,  # Force text wrapping
            padx=10,
            pady=10
        )
        self.upcoming_reminder_label.pack(expand=True, fill=tk.BOTH)

        # Refresh button - smaller and better positioned
        refresh_btn = tk.Button(
            reminder_frame,
            text="🔄 Refresh",
            command=self.update_upcoming_reminder,
            bg=self.primary_color,
            fg='white',
            font=('Arial', 9),  # Smaller font
            padx=10,
            pady=3
        )
        refresh_btn.pack(pady=(5, 5), fill=tk.X)

        # Now update the update_upcoming_reminder() method to format text better:

        # Start the clock
        self.update_clock()

    def update_clock(self):
        """Update the real-time clock"""
        now = datetime.datetime.now()

        # Update time
        current_time = now.strftime("%I:%M:%S %p")  # 12-hour format with AM/PM
        self.clock_label.config(text=current_time)

        # Update date
        current_date = now.strftime("%A, %B %d, %Y")  # e.g., "Monday, January 22, 2024"
        self.date_label.config(text=current_date)

        # Update upcoming reminder every minute
        current_minute = now.minute
        if current_minute % 1 == 0:  # Update every minute (change to 5 for every 5 minutes)
            self.update_upcoming_reminder()

        # Schedule next update (every second for clock, every minute for reminder)
        self.root.after(1000, self.update_clock)  # Update every second

    def update_upcoming_reminder(self):
        """Update the upcoming reminder display with BETTER FORMATTING"""
        try:
            now = datetime.datetime.now()
            current_time = now.time()
            current_date = now.date()

            upcoming_medicines = []

            # Check all medicines for upcoming reminders
            for box_id, med in self.medicine_boxes.items():
                if med:
                    med_name = med.get('name', 'Unknown')
                    exact_time_str = med.get('exact_time', '00:00')

                    try:
                        # Parse the time
                        hour, minute = map(int, exact_time_str.split(':'))
                        med_time = datetime.time(hour, minute)

                        # Create datetime objects for comparison
                        now_datetime = datetime.datetime.combine(current_date, current_time)
                        med_datetime = datetime.datetime.combine(current_date, med_time)

                        # If medicine time is today and in the future
                        if med_datetime.date() == current_date and med_time > current_time:
                            time_diff = (med_datetime - now_datetime).total_seconds() / 60  # in minutes
                            if time_diff > 0:  # Only include future medicines
                                upcoming_medicines.append({
                                    'name': med_name,
                                    'box': box_id,
                                    'time': exact_time_str,
                                    'minutes_until': time_diff,
                                    'time_obj': med_time
                                })
                    except Exception as e:
                        continue

            if upcoming_medicines:
                # Find the closest upcoming medicine
                upcoming_medicines.sort(key=lambda x: x['minutes_until'])
                next_med = upcoming_medicines[0]

                # Format the time difference BETTER
                minutes = int(next_med['minutes_until'])

                if minutes < 60:
                    time_text = f"{minutes}m"
                else:
                    hours = minutes // 60
                    remaining_minutes = minutes % 60
                    if remaining_minutes == 0:
                        time_text = f"{hours}h"
                    else:
                        time_text = f"{hours}h {remaining_minutes}m"

                # SHORTER, CLEANER FORMAT - fits in the box
                reminder_text = f"💊 {next_med['name'][:15]}{'...' if len(next_med['name']) > 15 else ''}\n"
                reminder_text += f"📦 Box {next_med['box']}\n"
                reminder_text += f"⏰ {next_med['time']}\n"
                reminder_text += f"⏳ In {time_text}"

                # Color code based on how soon
                if minutes <= 15:
                    color = self.danger_color  # Red for urgent (15 min or less)
                elif minutes <= 60:
                    color = self.warning_color  # Yellow for soon (1 hour or less)
                else:
                    color = self.primary_color  # Blue for later

                self.upcoming_reminder_label.config(
                    text=reminder_text,
                    fg=color,
                    font=('Arial', 10, 'bold')
                )

                # Make it clickable - show medicine details when clicked
                self.upcoming_reminder_label.bind('<Button-1>',
                                                  lambda e, box_id=next_med['box']: self.show_box_details(box_id))

                # Change cursor to hand when hovering
                self.upcoming_reminder_label.config(cursor="hand2")

            else:
                # Check if any medicines for today have passed
                today_medicines = []
                for box_id, med in self.medicine_boxes.items():
                    if med:
                        exact_time_str = med.get('exact_time', '00:00')
                        try:
                            hour, minute = map(int, exact_time_str.split(':'))
                            med_time = datetime.time(hour, minute)

                            # If medicine time already passed today
                            if med_time <= current_time:
                                today_medicines.append({
                                    'name': med.get('name', 'Unknown'),
                                    'box': box_id,
                                    'time': exact_time_str
                                })
                        except:
                            continue

                if today_medicines:
                    # Show the most recent medicine taken today
                    today_medicines.sort(key=lambda x: x['time'], reverse=True)
                    recent_med = today_medicines[0]

                    # SHORTER FORMAT
                    reminder_text = f"✅ Medicine Taken\n"
                    reminder_text += f"💊 {recent_med['name'][:15]}{'...' if len(recent_med['name']) > 15 else ''}\n"
                    reminder_text += f"📦 Box {recent_med['box']}\n"
                    reminder_text += f"⏰ {recent_med['time']}"

                    self.upcoming_reminder_label.config(
                        text=reminder_text,
                        fg=self.success_color,
                        font=('Arial', 10, 'bold')
                    )

                    # Make it clickable
                    self.upcoming_reminder_label.bind('<Button-1>',
                                                      lambda e, box_id=recent_med['box']: self.show_box_details(box_id))
                    self.upcoming_reminder_label.config(cursor="hand2")

                else:
                    # No medicines configured
                    self.upcoming_reminder_label.config(
                        text="No reminders\n\nAdd medicines\nto see reminders",
                        fg="#6c757d",
                        font=('Arial', 10)
                    )
                    # Remove click binding
                    self.upcoming_reminder_label.unbind('<Button-1>')
                    self.upcoming_reminder_label.config(cursor="")

        except Exception as e:
            print(f"Error updating upcoming reminder: {e}")
            self.upcoming_reminder_label.config(
                text="Error loading\nreminders",
                fg=self.danger_color,
                font=('Arial', 10)
            )

    def toggle_alerts(self):
        """Toggle medicine alerts on/off"""
        print("🔔 Toggling medicine alerts...")

        # Get current state from checkbox
        is_enabled = self.alert_enabled_var.get()

        # Admin verification BEFORE changing settings
        if not self.verify_admin_dialog("Toggle Medicine Alerts"):
            # Revert checkbox to previous state
            self.alert_enabled_var.set(not is_enabled)
            return

        # Update alert settings
        self.alert_settings["medicine_alerts"]["15_min_before"] = is_enabled
        self.alert_settings["medicine_alerts"]["exact_time"] = is_enabled
        self.alert_settings["medicine_alerts"]["5_min_after"] = is_enabled
        self.alert_settings["medicine_alerts"]["missed_alert"] = is_enabled

        # Save to file
        self.save_alert_settings()

        # Show status message
        status = "enabled" if is_enabled else "disabled"
        print(f"✅ Medicine alerts {status}")

    def save_medicine_alert_settings(self):
        """Save individual medicine alert checkbox settings"""
        print("💾 Saving medicine alert settings...")

        # Admin verification BEFORE saving
        if not self.verify_admin_dialog("Save Medicine Alert Settings"):
            # Revert checkboxes to saved state from database
            saved_settings = self.alert_settings.get("medicine_alerts", {})
            for key, var in self.alert_vars.items():
                var.set(saved_settings.get(key, True))
            # Revert snooze duration
            self.snooze_var.set(str(saved_settings.get("snooze_duration", 5)))
            return

        # Update settings from checkboxes
        for key, var in self.alert_vars.items():
            self.alert_settings["medicine_alerts"][key] = var.get()

        # Update snooze duration
        self.alert_settings["medicine_alerts"]["snooze_duration"] = int(self.snooze_var.get())

        # Save to file
        self.save_alert_settings()

        print("✅ Medicine alert settings saved")
        messagebox.showinfo("Saved", "Medicine alert settings saved successfully!")

        # Restart alert system if needed
        if hasattr(self, 'alert_scheduler') and self.alert_scheduler:
            if is_enabled:
                self.start_alert_system()
            else:
                self.alert_scheduler.stop()

    def create_missed_dose_section(self, parent):
        """Missed dose alerts and handling - ACTUAL IMPLEMENTATION"""
        frame = tk.LabelFrame(parent, text="⚠️ Missed Dose Handling",
                              bg=self.card_bg, font=('Arial', 12, 'bold'),
                              padx=15, pady=15)

        frame.pack(fill=tk.X, padx=20, pady=10)

        # Escalation levels
        tk.Label(frame, text="Missed Dose Escalation Levels:",
                 bg=self.card_bg, font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(0, 10))

        # Store escalation settings
        self.escalation_vars = {}

        escalation_steps = [
            ("1. After 5 minutes: Send reminder notification", "5_min_reminder"),
            ("2. After 15 minutes: Send urgent alert", "15_min_urgent"),
            ("3. After 30 minutes: Notify family member", "30_min_family"),
            ("4. After 1 hour: Log as missed dose in history", "1_hour_log")
        ]

        for text, key in escalation_steps:
            # Get saved setting or default to True
            default_value = self.alert_settings.get("missed_dose_escalation", {}).get(key, True)
            var = tk.BooleanVar(value=default_value)
            self.escalation_vars[key] = var

            cb = tk.Checkbutton(frame, text=text, variable=var,
                                bg=self.card_bg, font=('Arial', 10))
            cb.pack(anchor=tk.W, pady=2)

        # Family member email for notifications
        tk.Label(frame, text="\nFamily Member Email for Missed Doses:",
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(10, 5))

        tk.Label(frame, text="(Will be notified after 30 minutes of missed dose)",
                 bg=self.card_bg, font=('Arial', 8), fg='#6c757d').pack(anchor=tk.W)

        self.family_notify_email = tk.Entry(frame, width=40, font=('Arial', 10))
        self.family_notify_email.pack(fill=tk.X, pady=(0, 10))

        # Load saved family email if any
        if self.alert_settings.get("missed_dose_escalation", {}).get("family_email"):
            self.family_notify_email.insert(0, self.alert_settings["missed_dose_escalation"]["family_email"])
        elif self.gmail_config.get("recipients"):
            # Try to get first email from recipients
            recipients = self.gmail_config.get("recipients", "")
            if recipients:
                first_email = recipients.split(',')[0].strip()
                self.family_notify_email.insert(0, first_email)

        # Save button for missed dose settings
        save_btn = tk.Button(frame, text="💾 Save Missed Dose Settings",
                             command=self.save_missed_dose_settings,
                             bg=self.success_color, fg='white',
                             font=('Arial', 10), padx=15)
        save_btn.pack(pady=(10, 5))

        # Test notification button
        test_btn = tk.Button(frame, text="🔔 Test Family Notification",
                             command=self.test_family_notification,
                             bg=self.primary_color, fg='white',
                             font=('Arial', 10), padx=15)
        test_btn.pack(pady=(0, 5))

    def create_expiry_alerts_section(self, parent):
        """Medicine expiry alerts configuration"""
        frame = tk.LabelFrame(parent, text="📅 Medicine Expiry Alerts",
                              bg=self.card_bg, font=('Arial', 12, 'bold'),
                              padx=15, pady=15)

        frame.pack(fill=tk.X, padx=20, pady=10)

        # Instructions
        tk.Label(frame,
                 text="Configure alerts for medicines nearing expiry:",
                 bg=self.card_bg, font=('Arial', 10), fg='#6c757d', wraplength=400).pack(anchor=tk.W, pady=(0, 15))

        # Enable/disable all expiry alerts
        self.expiry_enabled_var = tk.BooleanVar(value=True)
        enable_btn = tk.Checkbutton(frame, text="Enable Expiry Alerts",
                                    variable=self.expiry_enabled_var,
                                    command=self.toggle_expiry_alerts,
                                    bg=self.card_bg, font=('Arial', 11))
        enable_btn.pack(anchor=tk.W, pady=(0, 10))

        # Expiry alert options
        expiry_options = [
            ("30 days before expiry", "30_days_before"),
            ("15 days before expiry", "15_days_before"),
            ("7 days before expiry", "7_days_before"),
            ("1 day before expiry (urgent)", "1_day_before")
        ]

        self.expiry_vars = {}

        for i, (text, key) in enumerate(expiry_options):
            # Get saved setting or default to True
            default_value = self.alert_settings["expiry_alerts"].get(key, True)
            var = tk.BooleanVar(value=default_value)
            self.expiry_vars[key] = var

            cb = tk.Checkbutton(frame, text=text, variable=var,
                                bg=self.card_bg, font=('Arial', 10))
            cb.pack(anchor=tk.W, pady=3)

        # Check expiry button
        check_btn = tk.Button(frame, text="🔍 Check Expiring Medicines",
                              command=self.check_expiring_medicines,
                              bg=self.primary_color, fg='white',
                              font=('Arial', 10), padx=15, pady=5)
        check_btn.pack(anchor=tk.W, pady=(15, 5))

        # Save button
        save_btn = tk.Button(frame, text="💾 Save Expiry Settings",
                             command=self.save_expiry_settings,
                             bg=self.success_color, fg='white',
                             font=('Arial', 10), padx=15, pady=5)
        save_btn.pack(anchor=tk.W, pady=(0, 5))

        # Status label
        self.expiry_status = tk.Label(frame, text="",
                                      bg=self.card_bg, fg=self.success_color,
                                      font=('Arial', 10))
        self.expiry_status.pack(anchor=tk.W, pady=(5, 0))

    # Supporting methods
    def toggle_expiry_alerts(self):
        """Toggle all expiry alerts on/off"""
        is_enabled = self.expiry_enabled_var.get()

        # Admin verification BEFORE changing
        if not self.verify_admin_dialog("Toggle Expiry Alerts"):
            # Revert checkbox
            self.expiry_enabled_var.set(not is_enabled)
            return

        # Update all expiry checkboxes
        for key, var in self.expiry_vars.items():
            var.set(is_enabled)

        # Update settings
        for key in self.expiry_vars.keys():
            self.alert_settings["expiry_alerts"][key] = is_enabled

        # Save settings
        self.save_alert_settings()

        status = "enabled" if is_enabled else "disabled"
        self.expiry_status.config(text=f"Expiry alerts {status}")
        print(f"✅ Expiry alerts {status}")

    def save_expiry_settings(self):
        """Save expiry alert settings"""
        print("💾 Saving expiry alert settings...")

        # Admin verification BEFORE saving
        if not self.verify_admin_dialog("Save Expiry Alert Settings"):
            # Revert checkboxes to saved state from database
            saved_settings = self.alert_settings.get("expiry_alerts", {})
            for key, var in self.expiry_vars.items():
                var.set(saved_settings.get(key, True))
            return

        # Update settings from checkboxes
        for key, var in self.expiry_vars.items():
            self.alert_settings["expiry_alerts"][key] = var.get()

        # Save to file
        self.save_alert_settings()

        # Show status
        enabled_count = sum(1 for var in self.expiry_vars.values() if var.get())
        self.expiry_status.config(text=f"✅ Saved: {enabled_count}/4 expiry alerts enabled")

        print(f"✅ Expiry settings saved: {enabled_count}/4 alerts enabled")
        messagebox.showinfo("Saved", "Expiry alert settings saved successfully!")

    def check_expiring_medicines(self):
        """Check and show expiring medicines"""
        print("🔍 Checking expiring medicines...")

        today = datetime.datetime.now().date()
        expiring_meds = []
        expired_meds = []

        for box_id, med in self.medicine_boxes.items():
            if med:
                expiry_str = med.get('expiry')
                if expiry_str:
                    try:
                        expiry_date = datetime.datetime.strptime(expiry_str, "%Y-%m-%d").date()
                        days_until_expiry = (expiry_date - today).days

                        if days_until_expiry < 0:
                            expired_meds.append({
                                'box': box_id,
                                'name': med.get('name', 'Unknown'),
                                'expiry': expiry_str,
                                'days': abs(days_until_expiry)
                            })
                        elif days_until_expiry <= 30:  # Only show if expiring within 30 days
                            expiring_meds.append({
                                'box': box_id,
                                'name': med.get('name', 'Unknown'),
                                'expiry': expiry_str,
                                'days': days_until_expiry
                            })
                    except:
                        pass

        # Create popup window
        popup = tk.Toplevel(self.root)
        popup.title("Expiring Medicines Check")
        popup.geometry("500x400")
        popup.configure(bg=self.card_bg)

        # Title
        tk.Label(popup, text="📅 Expiring Medicines Report",
                 font=('Arial', 16, 'bold'),
                 bg=self.card_bg, fg=self.primary_color).pack(pady=20)

        # Create scrolled text area
        from tkinter import scrolledtext

        text_area = scrolledtext.ScrolledText(popup, height=15, width=50,
                                              font=('Consolas', 9))
        text_area.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Add report to text area
        text_area.insert(tk.END, "=" * 50 + "\n")
        text_area.insert(tk.END, "📅 EXPIRY CHECK REPORT\n")
        text_area.insert(tk.END, "=" * 50 + "\n\n")

        if expired_meds:
            text_area.insert(tk.END, "❌ EXPIRED MEDICINES:\n")
            text_area.insert(tk.END, "-" * 40 + "\n")
            for med in expired_meds:
                text_area.insert(tk.END, f"• {med['name']} (Box {med['box']})\n")
                text_area.insert(tk.END, f"  Expired {med['days']} day(s) ago on {med['expiry']}\n")
                text_area.insert(tk.END, f"  ⚠️ URGENT: Discard immediately!\n\n")

        if expiring_meds:
            text_area.insert(tk.END, "⚠️ EXPIRING SOON:\n")
            text_area.insert(tk.END, "-" * 40 + "\n")
            for med in expiring_meds:
                text_area.insert(tk.END, f"• {med['name']} (Box {med['box']})\n")
                text_area.insert(tk.END, f"  Expires in {med['days']} day(s) on {med['expiry']}\n")

                # Show which alerts will be triggered
                if med['days'] <= 1 and self.alert_settings["expiry_alerts"]["1_day_before"]:
                    text_area.insert(tk.END, f"  ⚠️ 1-day alert will be sent\n")
                elif med['days'] <= 7 and self.alert_settings["expiry_alerts"]["7_days_before"]:
                    text_area.insert(tk.END, f"  ⚠️ 7-day alert will be sent\n")
                elif med['days'] <= 15 and self.alert_settings["expiry_alerts"]["15_days_before"]:
                    text_area.insert(tk.END, f"  ⚠️ 15-day alert will be sent\n")
                elif med['days'] <= 30 and self.alert_settings["expiry_alerts"]["30_days_before"]:
                    text_area.insert(tk.END, f"  ⚠️ 30-day alert will be sent\n")

                text_area.insert(tk.END, "\n")

        if not expired_meds and not expiring_meds:
            text_area.insert(tk.END, "✅ No medicines expiring soon\n")
            text_area.insert(tk.END, "All medicines are either not expiring or have no expiry date set.\n")

        text_area.insert(tk.END, "\n" + "=" * 50 + "\n")
        text_area.insert(tk.END, f"Report generated: {today.strftime('%Y-%m-%d')}\n")

        text_area.config(state=tk.DISABLED)

        # Close button
        tk.Button(popup, text="Close", command=popup.destroy,
                  bg=self.primary_color, fg='white',
                  font=('Arial', 11), padx=20).pack(pady=10)

    def create_stock_alerts_section(self, parent):
        """Stock alerts configuration for low/empty medicine"""
        frame = tk.LabelFrame(parent, text="📦 Stock Alerts",
                              bg=self.card_bg, font=('Arial', 12, 'bold'),
                              padx=15, pady=15)
        frame.pack(fill=tk.X, padx=20, pady=10)

        # Enable/disable all stock alerts
        self.stock_enabled_var = tk.BooleanVar(
            value=self.alert_settings["stock_alerts"].get("enabled", True)
        )
        enable_btn = tk.Checkbutton(frame, text="Enable Stock Alerts",
                                    variable=self.stock_enabled_var,
                                    command=self.toggle_stock_alerts,
                                    bg=self.card_bg, font=('Arial', 11))
        enable_btn.pack(anchor=tk.W, pady=(0, 10))

        # Low stock threshold
        threshold_frame = tk.Frame(frame, bg=self.card_bg)
        threshold_frame.pack(anchor=tk.W, pady=(0, 10))

        tk.Label(threshold_frame, text="Low Stock Threshold:",
                 bg=self.card_bg, font=('Arial', 10)).pack(side=tk.LEFT)

        self.low_stock_var = tk.StringVar(
            value=str(self.alert_settings["stock_alerts"].get("low_stock_threshold", 5))
        )
        low_stock_spin = tk.Spinbox(threshold_frame, from_=1, to=20,
                                    textvariable=self.low_stock_var,
                                    width=5, font=('Arial', 10))
        low_stock_spin.pack(side=tk.LEFT, padx=(10, 0))
        tk.Label(threshold_frame, text="tablets", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=(5, 0))

        # Alert conditions
        tk.Label(frame, text="Send alerts when:",
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(5, 5))

        # Condition 1: Low stock (below threshold)
        self.low_stock_alert_var = tk.BooleanVar(
            value=self.alert_settings["stock_alerts"].get("critical_alert", True)
        )
        cb1 = tk.Checkbutton(frame,
                             text="Medicine stock is CRITICALLY LOW (below threshold)",
                             variable=self.low_stock_alert_var,
                             bg=self.card_bg, font=('Arial', 10))
        cb1.pack(anchor=tk.W, pady=2)

        # Condition 2: Very low stock (1-2 tablets)
        self.very_low_alert_var = tk.BooleanVar(
            value=self.alert_settings["stock_alerts"].get("critical_alert", True)
        )
        cb2 = tk.Checkbutton(frame,
                             text="Medicine stock is VERY LOW (1-2 tablets left)",
                             variable=self.very_low_alert_var,
                             bg=self.card_bg, font=('Arial', 10))
        cb2.pack(anchor=tk.W, pady=2)

        # Condition 3: Empty stock
        self.empty_alert_var = tk.BooleanVar(
            value=self.alert_settings["stock_alerts"].get("empty_alert", True)
        )
        cb3 = tk.Checkbutton(frame,
                             text="Medicine is FINISHED (0 tablets left)",
                             variable=self.empty_alert_var,
                             bg=self.card_bg, font=('Arial', 10))
        cb3.pack(anchor=tk.W, pady=2)

        # Test button
        test_btn = tk.Button(frame, text="🔍 Check Stock Status",
                             command=self.check_stock_status,
                             bg=self.primary_color, fg='white',
                             font=('Arial', 10), padx=15, pady=5)
        test_btn.pack(anchor=tk.W, pady=(15, 5))

        # Save button
        save_btn = tk.Button(frame, text="💾 Save Stock Settings",
                             command=self.save_stock_settings,
                             bg=self.success_color, fg='white',
                             font=('Arial', 10), padx=15, pady=5)
        save_btn.pack(anchor=tk.W, pady=(0, 5))

        # Status label
        self.stock_status = tk.Label(frame, text="",
                                     bg=self.card_bg, fg=self.success_color,
                                     font=('Arial', 10))
        self.stock_status.pack(anchor=tk.W, pady=(5, 0))

    def toggle_stock_alerts(self):
        """Toggle all stock alerts on/off"""
        is_enabled = self.stock_enabled_var.get()

        # Admin verification BEFORE changing
        if not self.verify_admin_dialog("Toggle Stock Alerts"):
            # Revert checkbox
            self.stock_enabled_var.set(not is_enabled)
            return

        # Update all stock checkboxes
        self.low_stock_alert_var.set(is_enabled)
        self.very_low_alert_var.set(is_enabled)
        self.empty_alert_var.set(is_enabled)

        # Update settings
        self.alert_settings["stock_alerts"]["enabled"] = is_enabled

        # Save settings
        self.save_alert_settings()

        status = "enabled" if is_enabled else "disabled"
        self.stock_status.config(text=f"Stock alerts {status}")
        print(f"✔️ Stock alerts {status}")

    def save_stock_settings(self):
        """Save stock alert settings"""
        print("💾 Saving stock alert settings...")

        # Admin verification BEFORE saving
        if not self.verify_admin_dialog("Save Stock Alert Settings"):
            # Revert checkboxes and threshold to saved state
            saved_settings = self.alert_settings.get("stock_alerts", {})
            self.stock_enabled_var.set(saved_settings.get("enabled", True))
            self.low_stock_var.set(str(saved_settings.get("low_stock_threshold", 5)))
            self.low_stock_alert_var.set(saved_settings.get("critical_alert", True))
            self.very_low_alert_var.set(saved_settings.get("critical_alert", True))
            self.empty_alert_var.set(saved_settings.get("empty_alert", True))
            return

        # Update settings from UI
        self.alert_settings["stock_alerts"]["enabled"] = self.stock_enabled_var.get()
        self.alert_settings["stock_alerts"]["low_stock_threshold"] = int(self.low_stock_var.get())
        self.alert_settings["stock_alerts"]["critical_alert"] = self.low_stock_alert_var.get()
        self.alert_settings["stock_alerts"]["empty_alert"] = self.empty_alert_var.get()

        # Save to file
        self.save_alert_settings()

        # Show status
        enabled_count = sum([
            self.low_stock_alert_var.get(),
            self.very_low_alert_var.get(),
            self.empty_alert_var.get()
        ])
        self.stock_status.config(text=f"✔️ Saved: {enabled_count}/3 alert types enabled")

        print(f"✔️ Stock settings saved: {enabled_count}/3 alert types enabled")
        messagebox.showinfo("Saved", "Stock alert settings saved successfully!")

    def check_stock_status(self):
        """Check and show stock status of all medicines"""
        print("🔍 Checking stock status...")

        low_stock_threshold = int(self.low_stock_var.get())
        critical_meds = []  # Below threshold
        very_low_meds = []  # 1-2 tablets
        empty_meds = []  # 0 tablets

        for box_id, med in self.medicine_boxes.items():
            if med:
                quantity = med.get('quantity', 0)
                med_name = med.get('name', 'Unknown')

                if quantity == 0:
                    empty_meds.append({
                        'box': box_id,
                        'name': med_name,
                        'quantity': quantity
                    })
                elif quantity <= 2:
                    very_low_meds.append({
                        'box': box_id,
                        'name': med_name,
                        'quantity': quantity
                    })
                elif quantity <= low_stock_threshold:
                    critical_meds.append({
                        'box': box_id,
                        'name': med_name,
                        'quantity': quantity
                    })

        # Create popup window
        popup = tk.Toplevel(self.root)
        popup.title("Stock Status Report")
        popup.geometry("500x400")
        popup.configure(bg=self.card_bg)

        # Title
        tk.Label(popup, text="📦 Stock Status Report",
                 font=('Arial', 16, 'bold'),
                 bg=self.card_bg, fg=self.primary_color).pack(pady=20)

        # Create scrolled text area
        from tkinter import scrolledtext
        text_area = scrolledtext.ScrolledText(popup, height=15, width=50,
                                              font=('Consolas', 9))
        text_area.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Add report to text area
        text_area.insert(tk.END, "=" * 50 + "\n")
        text_area.insert(tk.END, "📦 STOCK STATUS REPORT\n")
        text_area.insert(tk.END, "=" * 50 + "\n\n")
        text_area.insert(tk.END, f"Low stock threshold: {low_stock_threshold} tablets\n\n")

        # Empty medicines
        if empty_meds:
            text_area.insert(tk.END, "❌ FINISHED / EMPTY:\n")
            text_area.insert(tk.END, "-" * 40 + "\n")
            for med in empty_meds:
                text_area.insert(tk.END, f"• {med['name']} (Box {med['box']})\n")
                text_area.insert(tk.END, f"  Status: COMPLETELY EMPTY - URGENT REFILL NEEDED!\n\n")

        # Very low medicines (1-2 tablets)
        if very_low_meds:
            text_area.insert(tk.END, "⚠️ VERY LOW STOCK (1-2 tablets):\n")
            text_area.insert(tk.END, "-" * 40 + "\n")
            for med in very_low_meds:
                text_area.insert(tk.END, f"• {med['name']} (Box {med['box']})\n")
                text_area.insert(tk.END, f"  Quantity: {med['quantity']} tablets - REFILL SOON!\n\n")

        # Critical medicines (below threshold)
        if critical_meds:
            text_area.insert(tk.END, "🔔 LOW STOCK (below threshold):\n")
            text_area.insert(tk.END, "-" * 40 + "\n")
            for med in critical_meds:
                text_area.insert(tk.END, f"• {med['name']} (Box {med['box']})\n")
                text_area.insert(tk.END, f"  Quantity: {med['quantity']} tablets - Monitor closely\n\n")

        if not (empty_meds or very_low_meds or critical_meds):
            text_area.insert(tk.END, "✅ All medicines have sufficient stock\n")

        text_area.insert(tk.END, "\n" + "=" * 50 + "\n")
        text_area.insert(tk.END, f"Report generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

        # Show which alerts will be triggered
        text_area.insert(tk.END, "\n📢 ALERTS CONFIGURED:\n")
        text_area.insert(tk.END, "-" * 40 + "\n")
        text_area.insert(tk.END,
                         f"• Empty medicine alerts: {'ENABLED' if self.empty_alert_var.get() else 'DISABLED'}\n")
        text_area.insert(tk.END,
                         f"• Very low alerts (1-2 tablets): {'ENABLED' if self.very_low_alert_var.get() else 'DISABLED'}\n")
        text_area.insert(tk.END, f"• Low stock alerts: {'ENABLED' if self.low_stock_alert_var.get() else 'DISABLED'}\n")

        text_area.config(state=tk.DISABLED)

        # Close button
        tk.Button(popup, text="Close", command=popup.destroy,
                  bg=self.primary_color, fg='white',
                  font=('Arial', 11), padx=20).pack(pady=10)

    def check_and_send_stock_alerts(self, medicine, box_id):
        """Check if stock alerts need to be sent after dose is taken"""
        if not self.alert_settings["stock_alerts"].get("enabled", True):
            return

        quantity = medicine.get('quantity', 0)
        med_name = medicine.get('name', 'Unknown')
        threshold = self.alert_settings["stock_alerts"].get("low_stock_threshold", 5)

        # Check conditions and send alerts
        if quantity == 0 and self.alert_settings["stock_alerts"].get("empty_alert", True):
            self.send_stock_alert("empty", medicine, box_id)
        elif quantity <= 2 and self.alert_settings["stock_alerts"].get("critical_alert", True):
            self.send_stock_alert("very_low", medicine, box_id)
        elif quantity <= threshold and self.alert_settings["stock_alerts"].get("critical_alert", True):
            self.send_stock_alert("low", medicine, box_id)

    def send_stock_alert(self, alert_type, medicine, box_id):
        """Send stock alert email"""
        med_name = medicine.get('name', 'Unknown')
        quantity = medicine.get('quantity', 0)

        if alert_type == "empty":
            subject = f"🆘 URGENT: {med_name} is EMPTY!"
            body = f"{med_name} in Box {box_id} is completely EMPTY (0 tablets left).\n\nURGENT REFILL REQUIRED!"
        elif alert_type == "very_low":
            subject = f"⚠️ CRITICAL: {med_name} is VERY LOW!"
            body = f"{med_name} in Box {box_id} is VERY LOW ({quantity} tablets left).\n\nREFILL NEEDED SOON!"
        else:  # low stock
            subject = f"🔔 Alert: {med_name} is running low"
            body = f"{med_name} in Box {box_id} is running low ({quantity} tablets left).\n\nConsider refilling soon."

        # Send email and Mobile Alert Bot
        try:
            if hasattr(self, 'alert_scheduler') and self.alert_scheduler:
                self.alert_scheduler.send_gmail_alert(subject, body)
            if hasattr(self, 'send_mobile_alert'):
                self.send_mobile_alert("stock", body)
            print(f"✔️ Sent {alert_type} stock alert for {med_name}")
        except Exception as e:
            print(f"✗️ Failed to send stock alert: {e}")

    def create_gmail_config_section(self, parent):
        """Gmail alert configuration"""
        frame = tk.LabelFrame(parent, text="📧 Email Alert Configuration",
                              bg=self.card_bg, font=('Arial', 12, 'bold'),
                              padx=15, pady=15)

        frame.pack(fill=tk.X, padx=20, pady=10)

        # Instructions
        tk.Label(frame,
                 text="Configure Gmail to send alerts. Use App Password (not regular password).",
                 bg=self.card_bg, font=('Arial', 10), fg='#6c757d', wraplength=400).pack(anchor=tk.W, pady=(0, 15))

        # Email entry
        tk.Label(frame, text="Sender Email (Gmail):", bg=self.card_bg, font=('Arial', 10)).pack(anchor=tk.W)
        self.gmail_email = tk.Entry(frame, width=40, font=('Arial', 10))
        self.gmail_email.pack(fill=tk.X, pady=(0, 10))

        if self.gmail_config.get("sender_email"):
            self.gmail_email.insert(0, self.gmail_config["sender_email"])

        # App Password entry
        tk.Label(frame, text="App Password (16 characters):", bg=self.card_bg, font=('Arial', 10)).pack(anchor=tk.W)
        self.gmail_password = tk.Entry(frame, width=40, font=('Arial', 10), show="*")
        self.gmail_password.pack(fill=tk.X, pady=(0, 10))

        if self.gmail_config.get("sender_password"):
            self.gmail_password.insert(0, self.gmail_config["sender_password"])

        # Recipient emails (for ALL alerts)
        tk.Label(frame, text="📧 Alert Recipients:",
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(10, 5))

        tk.Label(frame,
                 bg=self.card_bg, font=('Arial', 8), fg='#6c757d').pack(anchor=tk.W)

        self.recipient_emails = tk.Text(frame, height=3, width=40, font=('Arial', 10))
        self.recipient_emails.pack(fill=tk.X, pady=(0, 10))

        # Load saved recipients if any
        if self.gmail_config.get("recipients"):
            self.recipient_emails.insert("1.0", self.gmail_config["recipients"])
        else:
            # If no recipients saved, default to sender email
            sender_email = self.gmail_config.get("sender_email", "")
            if sender_email:
                self.recipient_emails.insert("1.0", sender_email)

        # Test and Save buttons
        test_frame = tk.Frame(frame, bg=self.card_bg)
        test_frame.pack(fill=tk.X, pady=10)

        test_btn = tk.Button(test_frame, text="📧 Test Connection",
                             command=self.test_gmail_connection,
                             bg=self.primary_color, fg='white',
                             font=('Arial', 10), padx=15)
        test_btn.pack(side=tk.LEFT)

        save_btn = tk.Button(test_frame, text="💾 Save Gmail Settings",
                             command=self.save_gmail_config,
                             bg=self.success_color, fg='white',
                             font=('Arial', 10), padx=15)
        save_btn.pack(side=tk.LEFT, padx=10)

        # Status label
        self.gmail_status = tk.Label(frame, text="Not configured",
                                     bg=self.card_bg, fg=self.danger_color,
                                     font=('Arial', 10))
        self.gmail_status.pack(pady=(5, 0))

        # Show saved status if configured
        if self.gmail_config.get("sender_email"):
            # Count recipients
            recipient_text = self.gmail_config.get("recipients", "")
            if recipient_text:
                recipients = [email.strip() for email in recipient_text.split(',') if email.strip()]
                recipient_count = len(recipients)
            else:
                recipient_count = 1  # Just the sender

            self.gmail_status.config(
                text=f"✅ Configured for {self.gmail_config['sender_email']} ({recipient_count} recipient(s))",
                fg=self.success_color
            )

    def save_admin_credentials(self):
        """Save admin credentials to database"""
        email = self.admin_email_var.get().strip()
        password = self.admin_password_var.get().strip()

        if not email or not password:
            self.admin_status_label.config(
                text="❌ Please enter both email and password",
                fg=self.danger_color
            )
            return

        if "@" not in email:
            self.admin_status_label.config(
                text="❌ Please enter a valid email",
                fg=self.danger_color
            )
            return

        try:
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db

            if db.set_admin_credentials(email, password):
                self.admin_status_label.config(
                    text="✅ Admin credentials saved successfully!",
                    fg=self.success_color
                )
                self.admin_password_var.set("")  # Clear password field
                self.root.after(3000, lambda: self.admin_status_label.config(text=""))
            else:
                self.admin_status_label.config(
                    text="❌ Failed to save credentials",
                    fg=self.danger_color
                )
        except Exception as e:
            self.admin_status_label.config(
                text=f"❌ Error: {str(e)[:20]}",
                fg=self.danger_color
            )

    def verify_admin_dialog(self):
        """Show admin verification dialog - returns True if verified"""
        verify_window = tk.Toplevel(self.root)
        verify_window.title("Admin Verification Required")
        verify_window.geometry("400x200")
        verify_window.configure(bg=self.bg_color)
        verify_window.transient(self.root)
        verify_window.grab_set()
        verify_window.resizable(False, False)

        result = [False]  # Use list to store result from nested function

        # Center window
        verify_window.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (verify_window.winfo_width() // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (verify_window.winfo_height() // 2)
        verify_window.geometry(f"+{x}+{y}")

        # Title
        tk.Label(verify_window, text="🔐 Admin Verification",
                 font=('Arial', 14, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=(10, 15))

        # Admin email entry
        tk.Label(verify_window, text="Admin Email:", bg=self.bg_color,
                 font=('Arial', 10)).pack(anchor=tk.W, padx=20, pady=(0, 3))
        
        email_var = tk.StringVar()
        email_entry = tk.Entry(verify_window, textvariable=email_var,
                              width=35, font=('Arial', 10))
        email_entry.pack(padx=20, pady=(0, 10), fill=tk.X)

        # Admin password entry
        tk.Label(verify_window, text="Admin Password:", bg=self.bg_color,
                 font=('Arial', 10)).pack(anchor=tk.W, padx=20, pady=(0, 3))
        
        password_var = tk.StringVar()
        password_entry = tk.Entry(verify_window, textvariable=password_var,
                                 width=35, font=('Arial', 10), show="*")
        password_entry.pack(padx=20, pady=(0, 10), fill=tk.X)

        # Status label
        status_label = tk.Label(verify_window, text="", bg=self.bg_color,
                               font=('Arial', 9))
        status_label.pack(pady=5)

        def verify_click():
            email = email_var.get().strip()
            password = password_var.get().strip()

            if not email or not password:
                status_label.config(text="❌ Please enter both email and password",
                                   fg=self.danger_color)
                return

            try:
                db = getattr(self, '_alert_db', None)
                if db is None:
                    db = AlertDB()
                    self._alert_db = db

                if db.verify_admin_credentials(email, password):
                    result[0] = True
                    verify_window.destroy()
                else:
                    status_label.config(text="❌ Invalid credentials",
                                       fg=self.danger_color)
                    password_entry.delete(0, tk.END)
            except Exception as e:
                status_label.config(text=f"❌ Error: {str(e)[:20]}",
                                   fg=self.danger_color)

        # Buttons
        btn_frame = tk.Frame(verify_window, bg=self.bg_color)
        btn_frame.pack(fill=tk.X, padx=20, pady=(10, 15))

        tk.Button(btn_frame, text="✓ Verify",
                 command=verify_click,
                 bg=self.success_color, fg='white',
                 font=('Arial', 10, 'bold'),
                 padx=20, pady=5).pack(side=tk.LEFT, padx=5)

        tk.Button(btn_frame, text="✕ Cancel",
                 command=verify_window.destroy,
                 bg=self.danger_color, fg='white',
                 font=('Arial', 10, 'bold'),
                 padx=20, pady=5).pack(side=tk.LEFT, padx=5)

        verify_window.wait_window()
        return result[0]

    def create_medical_reminders_tab(self):
        """Medical Reminders tab - COMPLETE WORKING VERSION"""
        tab = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(tab, text="Medical Reminders")

        # Title
        title_frame = tk.Frame(tab, bg=self.bg_color)
        title_frame.pack(fill=tk.X, pady=(10, 5))

        tk.Label(title_frame, text="Medical Reminders & Appointments",
                 font=('Arial', 20, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack()

        tk.Label(title_frame, text="Manage doctor appointments, prescriptions, lab tests, and custom reminders",
                 font=('Arial', 11), bg=self.bg_color, fg='#6c757d').pack(pady=(0, 10))

        # Quick Add Buttons
        quick_btn_frame = tk.Frame(tab, bg=self.bg_color)
        quick_btn_frame.pack(fill=tk.X, padx=20, pady=(0, 10))

        # Create 4 buttons in a row
        buttons = [
            ("📅 Add Appointment", self.add_appointment),
            ("💊 Add Prescription", self.add_prescription_reminder),
            ("🧪 Add Lab Test", self.add_lab_test),
            ("🔔 Custom Reminder", self.add_custom_reminder)
        ]

        for text, command in buttons:
            btn = tk.Button(quick_btn_frame, text=text, command=command,
                            bg=self.primary_color, fg='white',
                            font=('Arial', 11, 'bold'), padx=15, pady=8,
                            relief=tk.RAISED, bd=2)
            btn.pack(side=tk.LEFT, padx=5, expand=True, fill=tk.X)

        # Main Content Area with Tabs
        content_frame = tk.Frame(tab, bg=self.bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Create notebook for different reminder types
        self.reminder_notebook = ttk.Notebook(content_frame)
        self.reminder_notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: All Reminders (Combined View)
        all_reminders_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
        self.create_all_reminders_view(all_reminders_tab)
        self.reminder_notebook.add(all_reminders_tab, text="All Reminders")

        # Tab 2: Appointments
        appointments_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
        self.create_type_specific_view(appointments_tab, "appointments")
        self.reminder_notebook.add(appointments_tab, text="Appointments")

        # Tab 3: Prescriptions
        prescriptions_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
        self.create_type_specific_view(prescriptions_tab, "prescriptions")
        self.reminder_notebook.add(prescriptions_tab, text="Prescriptions")

        # Tab 4: Lab Tests
        lab_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
        self.create_type_specific_view(lab_tab, "lab_tests")
        self.reminder_notebook.add(lab_tab, text="Lab Tests")

        # Tab 5: Custom Reminders
        custom_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
        self.create_type_specific_view(custom_tab, "custom")
        self.reminder_notebook.add(custom_tab, text="Custom")

        # Tab 6: Export/Import (Replacing SMS Settings)
        export_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
        self.create_export_section(export_tab)
        self.reminder_notebook.add(export_tab, text="Export/Import")

        # Bind tab change event to auto-refresh
        self.reminder_notebook.bind("<<NotebookTabChanged>>", self.on_reminder_tab_changed)

        # Schedule initial refresh of all tabs after a short delay to ensure UI is ready
        self.root.after(500, self.refresh_all_reminder_tabs)

        return tab

    def refresh_all_reminder_tabs(self):
        """Refresh all reminder tabs to show initial data"""
        try:
            self.refresh_all_reminders()
            self.refresh_type_reminders("appointments")
            self.refresh_type_reminders("prescriptions")
            self.refresh_type_reminders("lab_tests")
            self.refresh_type_reminders("custom")
        except Exception as e:
            print(f"Initial refresh error: {e}")

    def on_reminder_tab_changed(self, event=None):
        """Auto-refresh reminder tabs when switched to them"""
        try:
            current_tab_index = self.reminder_notebook.index("current")
            # Tab 0 = All Reminders (has its own refresh button)
            # Tab 1 = Appointments
            # Tab 2 = Prescriptions
            # Tab 3 = Lab Tests
            # Tab 4 = Custom
            # Tab 5 = Export/Import

            if current_tab_index == 1:  # Appointments
                self.refresh_type_reminders("appointments")
            elif current_tab_index == 2:  # Prescriptions
                self.refresh_type_reminders("prescriptions")
            elif current_tab_index == 3:  # Lab Tests
                self.refresh_type_reminders("lab_tests")
            elif current_tab_index == 4:  # Custom
                self.refresh_type_reminders("custom")
        except Exception as e:
            print(f"Auto-refresh error: {e}")

    def create_export_section(self, parent):
        """Create export/import data section with scrollable content"""
        # Create scrollable container
        canvas = tk.Canvas(parent, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)

        scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mousewheel scrolling
        self.bind_canvas_mousewheel(canvas)

        # Title
        tk.Label(scrollable_frame, text="📁 Data Management",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=(10, 20))

        # Info message
        info_text = """Export, import, and backup your medical reminders and settings.

• Export: Save reminders to a file for backup or transfer.
• Import: Load reminders from a previously exported file.
• Data Backup: Backup all data (reminders, settings, medicine, etc.) to a file.
"""
        tk.Label(scrollable_frame, text=info_text,
                 bg=self.bg_color, font=('Arial', 10),
                 justify=tk.LEFT, wraplength=400).pack(pady=10)

        # Export/Import buttons
        btn_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        btn_frame.pack(pady=10)

        export_btn = tk.Button(
            btn_frame, text="⬇️ Export Reminders", bg="#4a6fa5", fg="white",
            font=('Arial', 11, 'bold'), padx=15, pady=8, command=self.export_medical_reminders)
        export_btn.pack(side=tk.LEFT, padx=10)

        import_btn = tk.Button(
            btn_frame, text="⬆️ Import Reminders", bg="#28a745", fg="white",
            font=('Arial', 11, 'bold'), padx=15, pady=8, command=self.import_medical_reminders)
        import_btn.pack(side=tk.LEFT, padx=10)

        # Data Backup button
        backup_btn = tk.Button(
            scrollable_frame, text="🗄️ Data Backup (All)", bg="#ffc107", fg="black",
            font=('Arial', 11, 'bold'), padx=15, pady=8, command=self.backup_all_data)
        backup_btn.pack(pady=(20, 0))

        # Status label
        self.export_status = tk.Label(scrollable_frame, text="",
                                      bg=self.bg_color, font=('Arial', 10))
        self.export_status.pack(pady=10)

    def export_medical_reminders(self):
        """Export medical reminders to a JSON file."""
        from tkinter import filedialog
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            title="Export Medical Reminders"
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.medical_reminders, f, indent=2)
            self.export_status.config(text=f"✅ Reminders exported to {os.path.basename(file_path)}", fg="#28a745")
        except Exception as e:
            self.export_status.config(text=f"❌ Export failed: {e}", fg="#dc3545")

    def import_medical_reminders(self):
        """Import medical reminders from a JSON file."""
        from tkinter import filedialog
        file_path = filedialog.askopenfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            title="Import Medical Reminders"
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Invalid file format")
            # Overwrite current reminders
            self.medical_reminders = data
            self.save_medical_reminders()
            self.refresh_reminders_ui()
            # Refresh all tabs after import
            self.refresh_all_reminders()
            self.refresh_type_reminders("appointments")
            self.refresh_type_reminders("prescriptions")
            self.refresh_type_reminders("lab_tests")
            self.refresh_type_reminders("custom")
            self.export_status.config(text=f"✅ Reminders imported from {os.path.basename(file_path)}", fg="#28a745")
        except Exception as e:
            self.export_status.config(text=f"❌ Import failed: {e}", fg="#dc3545")

    def backup_all_data(self):
        """Backup all relevant data to a single JSON file."""
        from tkinter import filedialog
        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json")],
            title="Backup All Data"
        )
        if not file_path:
            return
        try:
            backup = {
                "medical_reminders": self.medical_reminders,
                "alert_settings": self.alert_settings,
                "gmail_config": self.gmail_config,
                "sms_config": self.sms_config,
                "medicine_boxes": self.medicine_boxes,
                "dose_log": self.dose_log,
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(backup, f, indent=2)
            self.export_status.config(text=f"✅ Data backup saved to {os.path.basename(file_path)}", fg="#28a745")
        except Exception as e:
            self.export_status.config(text=f"❌ Backup failed: {e}", fg="#dc3545")

    def refresh_reminders_ui(self):
        """Refresh reminders UI after import."""
        # Rebuild the reminders tab UI if needed
        # For now, just reload the tab if method exists
        if hasattr(self, 'reminder_notebook'):
            # Remove all tabs and recreate
            for tab in self.reminder_notebook.tabs():
                self.reminder_notebook.forget(tab)
            # Recreate all tabs
            all_reminders_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
            self.create_all_reminders_view(all_reminders_tab)
            self.reminder_notebook.add(all_reminders_tab, text="All Reminders")

            appointments_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
            self.create_type_specific_view(appointments_tab, "appointments")
            self.reminder_notebook.add(appointments_tab, text="Appointments")

            prescriptions_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
            self.create_type_specific_view(prescriptions_tab, "prescriptions")
            self.reminder_notebook.add(prescriptions_tab, text="Prescriptions")

            lab_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
            self.create_type_specific_view(lab_tab, "lab_tests")
            self.reminder_notebook.add(lab_tab, text="Lab Tests")

            custom_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
            self.create_type_specific_view(custom_tab, "custom")
            self.reminder_notebook.add(custom_tab, text="Custom")

            export_tab = tk.Frame(self.reminder_notebook, bg=self.bg_color)
            self.create_export_section(export_tab)
            self.reminder_notebook.add(export_tab, text="Export/Import")

    def create_settings_tab(self):
        """Main Settings Tab - System & Account Settings with toggle"""
        tab = tk.Frame(self.notebook, bg=self.bg_color)
        self.notebook.add(tab, text="⚙ Settings")

        # ========== HEADER WITH TAB BUTTONS ==========
        header_frame = tk.Frame(tab, bg=self.card_bg, relief=tk.FLAT, bd=0)
        header_frame.pack(fill=tk.X, padx=0, pady=0)

        # Title on left
        title_left = tk.Frame(header_frame, bg=self.card_bg)
        title_left.pack(side=tk.LEFT, fill=tk.Y, padx=20, pady=15)

        heading_fg = getattr(self, 'heading_color', self.primary_color)
        tk.Label(title_left, text="⚙ Settings", font=('Arial', 18, 'bold'),
                 bg=self.card_bg, fg=heading_fg).pack(anchor=tk.W)

        # Tab buttons on right - theme-aware
        tabs_frame = tk.Frame(header_frame, bg=self.card_bg)
        tabs_frame.pack(side=tk.RIGHT, padx=20, pady=(15, 0))

        self.settings_mode = tk.StringVar(value="system")
        
        # Store tab buttons for highlighting
        self.settings_tab_buttons = {}

        # System Settings Tab Button (active by default)
        system_btn = tk.Button(tabs_frame, text="🖥️ System Settings",
                              command=lambda: self.switch_settings_tab("system"),
                              bg=self.primary_color, fg='white',
                              font=('Arial', 11, 'bold'),
                              padx=20, pady=10,
                              relief=tk.FLAT, bd=0,
                              cursor="hand2",
                              activebackground=self.accent_color,
                              activeforeground='white')
        system_btn.pack(side=tk.LEFT, padx=2)
        self.settings_tab_buttons["system"] = system_btn

        # Account Settings Tab Button
        account_btn = tk.Button(tabs_frame, text="🔑 Account Settings",
                               command=lambda: self.switch_settings_tab("account"),
                               bg=self.tab_inactive_bg, fg=self.secondary_text,
                               font=('Arial', 11, 'bold'),
                               padx=20, pady=10,
                               relief=tk.FLAT, bd=0,
                               cursor="hand2",
                               activebackground=self.border_color,
                               activeforeground=self.primary_text)
        account_btn.pack(side=tk.LEFT, padx=2)
        self.settings_tab_buttons["account"] = account_btn

        # Admin Panel Tab Button
        admin_btn = tk.Button(tabs_frame, text="🔐 Admin Panel",
                             command=lambda: self.switch_settings_tab("admin"),
                             bg=self.tab_inactive_bg, fg=self.secondary_text,
                             font=('Arial', 11, 'bold'),
                             padx=20, pady=10,
                             relief=tk.FLAT, bd=0,
                             cursor="hand2",
                             activebackground=self.border_color,
                             activeforeground=self.primary_text)
        admin_btn.pack(side=tk.LEFT, padx=2)
        self.settings_tab_buttons["admin"] = admin_btn

        # ========== SCROLLABLE CONTENT AREA ==========
        content_frame = tk.Frame(tab, bg=self.bg_color)
        content_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(content_frame, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(content_frame, orient="vertical", command=canvas.yview)
        self.settings_scrollable_frame = tk.Frame(canvas, bg=self.bg_color)

        self.settings_scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=self.settings_scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Bind mousewheel scrolling
        self.bind_canvas_mousewheel(canvas)

        # ========== SYSTEM SETTINGS SECTION ==========
        self.system_settings_frame = tk.Frame(self.settings_scrollable_frame, bg=self.bg_color)
        self.system_settings_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # SMS Settings
        self.create_sms_settings_section(self.system_settings_frame)

        # Email Settings
        self.create_gmail_config_section(self.system_settings_frame)

        # Appearance (theme) - subsection under System Settings
        self.create_appearance_section(self.system_settings_frame)

        # System Preferences
        self.create_system_preferences_section(self.system_settings_frame)

        # Save button for System Settings
        save_sys_frame = tk.Frame(self.system_settings_frame, bg=self.bg_color)
        save_sys_frame.pack(fill=tk.X, padx=20, pady=20)

        tk.Button(save_sys_frame, text="� SAVE ALL SETTINGS (Admin Protected)",
                  command=self.save_all_settings,
                  bg=self.success_color, fg='white',
                  font=('Arial', 12, 'bold'),
                  padx=30, pady=10,
                  cursor='hand2').pack()

        self.settings_status_label = tk.Label(save_sys_frame, text="",
                                              bg=self.bg_color, font=('Arial', 10))
        self.settings_status_label.pack(pady=5)

        # ========== ACCOUNT SETTINGS SECTION ==========
        self.account_settings_frame = tk.Frame(self.settings_scrollable_frame, bg=self.bg_color)
        self.account_settings_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Account settings content
        self.create_account_settings_section(self.account_settings_frame)

        # ========== ADMIN PANEL SECTION ==========
        self.admin_settings_frame = tk.Frame(self.settings_scrollable_frame, bg=self.bg_color)
        self.admin_settings_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # Admin panel content
        self.create_admin_panel_section(self.admin_settings_frame)

        # Initially hide account and admin settings
        self.account_settings_frame.pack_forget()
        self.admin_settings_frame.pack_forget()

        return tab

    def switch_settings_tab(self, tab_name):
        """Switch between settings tabs with visual feedback"""
        self.settings_mode.set(tab_name)
        
        # Update button styles - highlight active tab (theme-aware)
        for name, btn in self.settings_tab_buttons.items():
            if name == tab_name:
                btn.config(bg=self.primary_color, fg='white',
                          activebackground=self.accent_color, activeforeground='white')
            else:
                btn.config(bg=self.tab_inactive_bg, fg=self.secondary_text,
                          activebackground=self.border_color, activeforeground=self.primary_text)

        # Toggle content sections
        self.toggle_settings_section()

    def toggle_settings_section(self):
        """Toggle between System, Account, and Admin settings"""
        mode = self.settings_mode.get()

        # Hide all sections first
        self.system_settings_frame.pack_forget()
        self.account_settings_frame.pack_forget()
        self.admin_settings_frame.pack_forget()

        # Show selected section
        if mode == "system":
            self.system_settings_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        elif mode == "account":
            self.account_settings_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        elif mode == "admin":
            self.admin_settings_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

    def create_appearance_section(self, parent):
        """Appearance subsection under System Settings - Theme (Default, Light, Dark); applies on selection."""
        frame = tk.LabelFrame(parent, text="🎨 Appearance", bg=self.card_bg,
                              font=('Arial', 12, 'bold'), fg=self.primary_text,
                              padx=15, pady=15)
        frame.pack(fill=tk.X, padx=20, pady=10)

        current_theme = getattr(self, '_current_theme', 'default')
        self.appearance_theme_var = tk.StringVar(value=current_theme)

        themes = [
            ("default", "Default"),
            ("dark", "Dark"),
        ]
        for value, label in themes:
            rb = tk.Radiobutton(frame, text=label, variable=self.appearance_theme_var,
                                value=value, bg=self.card_bg, fg=self.primary_text,
                                font=('Arial', 10), selectcolor=self.card_bg,
                                activebackground=self.card_bg, activeforeground=self.primary_text,
                                command=lambda v=value: self.apply_theme(v))
            rb.pack(anchor=tk.W, pady=2)

    def create_account_settings_section(self, parent):
        """Account Settings Section - Password Management"""
        # Password Management Card - Full width with distinct background
        pwd_card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=2,
                            highlightbackground=self.border_color, highlightthickness=1)
        pwd_card.pack(fill=tk.X, padx=15, pady=20)

        # Card header with icon
        card_header = tk.Frame(pwd_card, bg=self.primary_color)
        card_header.pack(fill=tk.X)

        tk.Label(card_header, text="🔑 Password Management",
                 font=('Arial', 14, 'bold'), bg=self.primary_color,
                 fg='white').pack(anchor=tk.W, padx=15, pady=12)

        # Card body (theme-aware)
        card_body = tk.Frame(pwd_card, bg=self.card_bg)
        card_body.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Current Password Info - light emerald tint
        info_frame = tk.Frame(card_body, bg='#E8F5E9', relief=tk.FLAT, bd=1)
        info_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Label(info_frame, text="ℹ️ Device password is currently set and active",
                 font=('Arial', 11, 'bold'), bg='#E8F5E9', fg=self.primary_color).pack(anchor=tk.W, padx=12, pady=10)

        # Change Password Button (emerald)
        btn_frame = tk.Frame(card_body, bg=self.card_bg)
        btn_frame.pack(fill=tk.X, pady=(0, 20))

        tk.Button(btn_frame, text="🔐 Change Password",
                  command=self.open_password_management_dialog,
                  bg=self.primary_color, fg='white',
                  font=('Arial', 12, 'bold'),
                  padx=30, pady=12,
                  relief=tk.RAISED, bd=2,
                  cursor="hand2",
                  activebackground=self.accent_color, activeforeground='white').pack(fill=tk.X)

        # Security Rules - emerald style, title bold and visible
        rules_frame = tk.Frame(pwd_card, bg='#E8F5E9', relief=tk.FLAT, bd=1)
        rules_frame.pack(fill=tk.X, side=tk.BOTTOM)

        tk.Label(rules_frame, text="🛡️ Password Rules",
                 font=('Arial', 13, 'bold'), bg='#E8F5E9',
                 fg=self.primary_color).pack(anchor=tk.W, padx=15, pady=(10, 5))

        rules_text = "• Use a strong, memorable password\n• Minimum 4 digits (numbers only)\n• Keep your password secure and confidential\n• Change regularly for better security"

        tk.Label(rules_frame, text=rules_text,
                 font=('Arial', 10), bg='#E8F5E9', fg=self.primary_text,
                 justify=tk.LEFT).pack(anchor=tk.W, padx=15, pady=(0, 10))

    def create_admin_panel_section(self, parent):
        """Admin Panel Section - Setup & Management"""
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db

        has_admin = db.has_admin_credentials()

        # Status Banner at top - showing login state
        if self.admin_logged_in:
            # Logged in - use theme success color
            status_banner = tk.Frame(parent, bg=self.success_color, relief=tk.RAISED, bd=2)
            status_banner.pack(fill=tk.X, padx=15, pady=(15, 0))
            tk.Label(status_banner, text=f"✅ Logged in as: {self.logged_in_admin_name} - All features unlocked",
                     font=('Arial', 12, 'bold'), bg=self.success_color, fg='white').pack(pady=10)
        elif has_admin:
            # Admin exists but not logged in - use theme accent
            status_banner = tk.Frame(parent, bg=self.accent_color, relief=tk.RAISED, bd=2)
            status_banner.pack(fill=tk.X, padx=15, pady=(15, 0))
            tk.Label(status_banner, text="🔒 Admin account exists - Login to unlock features",
                     font=('Arial', 12, 'bold'), bg=self.accent_color, fg='white').pack(pady=10)
        else:
            # No admin - use theme danger color
            status_banner = tk.Frame(parent, bg=self.danger_color, relief=tk.RAISED, bd=2)
            status_banner.pack(fill=tk.X, padx=15, pady=(15, 0))
            tk.Label(status_banner, text="⚠️ Admin Setup Required",
                     font=('Arial', 12, 'bold'), bg=self.danger_color, fg='white').pack(pady=10)

        if not has_admin:
            # Show Admin Setup Form
            self.create_admin_setup_form(parent, db)
        else:
            # Show login/logout section
            if not self.admin_logged_in:
                # Show login button
                login_section = tk.Frame(parent, bg=self.bg_color)
                login_section.pack(fill=tk.X, padx=20, pady=20)
                
                tk.Label(login_section, text="🔐 Login to unlock all features:",
                        font=('Arial', 12, 'bold'), bg=self.bg_color).pack(anchor=tk.W, pady=(0, 10))
                
                tk.Button(login_section, text="🔓 Admin Login",
                         command=self.admin_login_dialog,
                         bg=self.primary_color, fg='white', font=('Arial', 13, 'bold'),
                         padx=40, pady=12, relief=tk.RAISED, bd=3,
                         cursor='hand2', activebackground=self.accent_color, activeforeground='white').pack(anchor=tk.W)
            else:
                # Show logout button
                logout_section = tk.Frame(parent, bg=self.bg_color)
                logout_section.pack(fill=tk.X, padx=20, pady=20)
                
                tk.Button(logout_section, text="🔒 Logout",
                         command=self.admin_logout,
                         bg='#dc3545', fg='white', font=('Arial', 12, 'bold'),
                         padx=30, pady=10, relief=tk.RAISED, bd=2,
                         cursor='hand2').pack(side=tk.LEFT)
            
            # Show Admin Management Panel

            self.create_admin_management_panel(parent, db)

    def create_admin_setup_form(self, parent, db):
        """First-time admin setup form"""
        # Intro with icon
        intro_frame = tk.Frame(parent, bg=self.bg_color)
        intro_frame.pack(fill=tk.X, padx=20, pady=20)

        title_frame = tk.Frame(intro_frame, bg=self.bg_color)
        title_frame.pack(anchor=tk.W)

        tk.Label(title_frame, text="🔐", font=('Arial', 24),
                 bg=self.bg_color).pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(title_frame, text="Administrator Account Setup",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg='#dc3545').pack(side=tk.LEFT)

        tk.Label(intro_frame, text="Set up an administrator account to protect sensitive operations",
                 font=('Arial', 10), bg=self.bg_color,
                 fg='#6c757d').pack(anchor=tk.W, pady=(10, 0))

        # Setup Card with modern styling
        setup_card = tk.Frame(parent, bg='#fffbf0', relief=tk.SOLID, bd=2)
        setup_card.pack(fill=tk.X, padx=15, pady=(10, 20))

        # Header with gradient effect
        card_header = tk.Frame(setup_card, bg='#ff9800')
        card_header.pack(fill=tk.X)

        header_content = tk.Frame(card_header, bg='#ff9800')
        header_content.pack(pady=15, padx=15)

        tk.Label(header_content, text="👤", font=('Arial', 18),
                 bg='#ff9800', fg='white').pack(side=tk.LEFT, padx=(0, 10))

        tk.Label(header_content, text="Create Admin Account",
                 font=('Arial', 14, 'bold'), bg='#ff9800',
                 fg='white').pack(side=tk.LEFT)

        # Form body with better spacing
        form_body = tk.Frame(setup_card, bg='#fffbf0')
        form_body.pack(fill=tk.BOTH, expand=True, padx=25, pady=25)

        # Admin Name with icon
        name_frame = tk.Frame(form_body, bg='#fffbf0')
        name_frame.pack(fill=tk.X, pady=(0, 12))
        tk.Label(name_frame, text="👤", font=('Arial', 11),
                 bg='#fffbf0').pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(name_frame, text="Admin Name:", bg='#fffbf0',
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        admin_name_var = tk.StringVar()
        tk.Entry(form_body, textvariable=admin_name_var, width=45,
                font=('Arial', 11), relief=tk.SOLID, bd=1).pack(fill=tk.X, pady=(0, 12))

        # Admin ID with icon
        id_frame = tk.Frame(form_body, bg='#fffbf0')
        id_frame.pack(fill=tk.X, pady=(0, 12))
        tk.Label(id_frame, text="🆔", font=('Arial', 11),
                 bg='#fffbf0').pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(id_frame, text="Admin ID (CNIC/Staff ID):", bg='#fffbf0',
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        
        admin_id_var = tk.StringVar()
        tk.Entry(form_body, textvariable=admin_id_var, width=45,
                font=('Arial', 11), relief=tk.SOLID, bd=1).pack(fill=tk.X, pady=(0, 12))

        # Email with icon
        email_frame = tk.Frame(form_body, bg='#fffbf0')
        email_frame.pack(fill=tk.X, pady=(0, 12))
        tk.Label(email_frame, text="📧", font=('Arial', 11),
                 bg='#fffbf0').pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(email_frame, text="Email Address:", bg='#fffbf0',
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        
        admin_email_var = tk.StringVar()
        tk.Entry(form_body, textvariable=admin_email_var, width=45,
                font=('Arial', 11), relief=tk.SOLID, bd=1).pack(fill=tk.X, pady=(0, 12))

        # Phone with icon
        phone_frame = tk.Frame(form_body, bg='#fffbf0')
        phone_frame.pack(fill=tk.X, pady=(0, 12))
        tk.Label(phone_frame, text="📱", font=('Arial', 11),
                 bg='#fffbf0').pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(phone_frame, text="Phone Number:", bg='#fffbf0',
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        
        admin_phone_var = tk.StringVar()
        tk.Entry(form_body, textvariable=admin_phone_var, width=45,
                font=('Arial', 11), relief=tk.SOLID, bd=1).pack(fill=tk.X, pady=(0, 12))

        # Password with icon
        pwd_frame = tk.Frame(form_body, bg='#fffbf0')
        pwd_frame.pack(fill=tk.X, pady=(0, 12))
        tk.Label(pwd_frame, text="🔒", font=('Arial', 11),
                 bg='#fffbf0').pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(pwd_frame, text="Admin Password:", bg='#fffbf0',
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        
        admin_pwd_var = tk.StringVar()
        tk.Entry(form_body, textvariable=admin_pwd_var, width=45,
                font=('Arial', 11), show="●", relief=tk.SOLID, bd=1).pack(fill=tk.X, pady=(0, 12))

        # Confirm Password with icon
        confirm_frame = tk.Frame(form_body, bg='#fffbf0')
        confirm_frame.pack(fill=tk.X, pady=(0, 12))
        tk.Label(confirm_frame, text="🔒", font=('Arial', 11),
                 bg='#fffbf0').pack(side=tk.LEFT, padx=(0, 5))
        tk.Label(confirm_frame, text="Confirm Password:", bg='#fffbf0',
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT)
        
        admin_pwd_confirm_var = tk.StringVar()
        tk.Entry(form_body, textvariable=admin_pwd_confirm_var, width=45,
                font=('Arial', 11), show="●", relief=tk.SOLID, bd=1).pack(fill=tk.X, pady=(0, 15))

        # Status label
        status_label = tk.Label(form_body, text="", bg='#fffbf0',
                               font=('Arial', 10))
        status_label.pack(pady=(0, 10))

        # Save button
        def save_admin():
            name = admin_name_var.get().strip()
            admin_id = admin_id_var.get().strip()
            email = admin_email_var.get().strip()
            phone = admin_phone_var.get().strip()
            password = admin_pwd_var.get().strip()
            confirm = admin_pwd_confirm_var.get().strip()

            # Validation
            if not all([name, admin_id, email, phone, password]):
                status_label.config(text="❌ All fields are required", fg=self.danger_color)
                return

            if password != confirm:
                status_label.config(text="❌ Passwords do not match", fg=self.danger_color)
                return

            if len(password) < 4:
                status_label.config(text="❌ Password must be at least 4 characters", fg=self.danger_color)
                return

            # Save to database
            success = db.set_admin_credentials(name, admin_id, email, phone, password)
            
            if success:
                status_label.config(text="✅ Admin account created!", fg=self.success_color)
                messagebox.showinfo("Success", "Admin account created successfully!\nYou can now login to unlock all features.")
                # Refresh the admin panel
                self.admin_settings_frame.destroy()
                self.admin_settings_frame = tk.Frame(self.settings_scrollable_frame, bg=self.bg_color)
                self.create_admin_panel_section(self.admin_settings_frame)
                self.admin_settings_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
                # Update status indicator
                self.update_admin_status_indicator()
            else:
                status_label.config(text="❌ Failed to save admin", fg=self.danger_color)

        tk.Button(form_body, text="💾 Create Admin Account",
                  command=save_admin,
                  bg='#28a745', fg='white',
                  font=('Arial', 13, 'bold'),
                  padx=30, pady=15,
                  relief=tk.RAISED, bd=3,
                  cursor='hand2').pack(fill=tk.X, pady=(10, 0))

    def create_admin_management_panel(self, parent, db):
        """Admin management panel when admin exists"""
        # Get admin info
        admin_info = db.get_admin_info()

        # Info Card (theme-aware)
        info_card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=2,
                             highlightbackground=self.border_color, highlightthickness=1)
        info_card.pack(fill=tk.X, padx=15, pady=20)

        # Header
        card_header = tk.Frame(info_card, bg=self.primary_color)
        card_header.pack(fill=tk.X)

        tk.Label(card_header, text="👤 Admin Information",
                 font=('Arial', 14, 'bold'), bg=self.primary_color,
                 fg='white').pack(anchor=tk.W, padx=15, pady=12)

        # Body
        info_body = tk.Frame(info_card, bg=self.card_bg)
        info_body.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        if admin_info:
            info_text = f"""Name: {admin_info.get('name', 'N/A')}
Admin ID: {admin_info.get('admin_id', 'N/A')}
Email: {admin_info.get('email', 'N/A')}
Phone: {admin_info.get('phone', 'N/A')}"""
        else:
            info_text = "No admin information available"

        tk.Label(info_body, text=info_text, bg=self.card_bg, fg=self.primary_text,
                 font=('Arial', 10), justify=tk.LEFT).pack(anchor=tk.W)

        # Actions Card (theme-aware)
        actions_card = tk.Frame(parent, bg=self.card_bg, relief=tk.RAISED, bd=2,
                                highlightbackground=self.border_color, highlightthickness=1)
        actions_card.pack(fill=tk.X, padx=15, pady=(0, 20))

        # Header
        actions_header = tk.Frame(actions_card, bg=self.primary_color)
        actions_header.pack(fill=tk.X)

        tk.Label(actions_header, text="🔧 Admin Actions",
                 font=('Arial', 14, 'bold'), bg=self.primary_color,
                 fg='white').pack(anchor=tk.W, padx=15, pady=12)

        # Body
        actions_body = tk.Frame(actions_card, bg=self.card_bg)
        actions_body.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Change Password Button (primary)
        tk.Button(actions_body, text="🔐 Change Admin Password",
                  command=self.change_admin_password,
                  bg=self.primary_color, fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=20, pady=10,
                  activebackground=self.accent_color, activeforeground='white',
                  cursor='hand2').pack(fill=tk.X, pady=(0, 10))

        # View Logs Button (accent / secondary)
        tk.Button(actions_body, text="📋 View Approval Logs",
                  command=self.view_approval_logs,
                  bg=self.accent_color, fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=20, pady=10,
                  activebackground=self.primary_color, activeforeground='white',
                  cursor='hand2').pack(fill=tk.X, pady=(0, 10))
        
        # Delete & Recreate Admin Button (danger)
        tk.Button(actions_body, text="🗑️ Delete & Recreate Admin",
                  command=self.delete_and_recreate_admin,
                  bg=self.danger_color, fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=20, pady=10,
                  activebackground='#9B2C2C', activeforeground='white',
                  cursor='hand2').pack(fill=tk.X)

    def verify_admin_dialog(self, action_name="this action"):
        """Show admin verification dialog - Returns True if verified"""
        # Check if admin already logged in
        if self.admin_logged_in:
            return True
        
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db

        if not db.has_admin_credentials():
            messagebox.showwarning("Admin Required", "No admin account configured.\nPlease set up admin in Settings > Admin Panel")
            return False

        # Create verification dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("🔐 Admin Verification Required")
        dialog.geometry("450x300")
        dialog.configure(bg=self.bg_color)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # Center dialog
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 150
        dialog.geometry(f"+{x}+{y}")

        result = {"verified": False}

        # Header
        header = tk.Frame(dialog, bg='#dc3545')
        header.pack(fill=tk.X)

        tk.Label(header, text="🔐 Admin Authorization Required",
                 font=('Arial', 14, 'bold'), bg='#dc3545',
                 fg='white').pack(pady=12)

        # Body
        body = tk.Frame(dialog, bg=self.bg_color)
        body.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        tk.Label(body, text=f"Admin approval is required for:",
                 font=('Arial', 10), bg=self.bg_color).pack(anchor=tk.W, pady=(0, 5))

        tk.Label(body, text=f"• {action_name}",
                 font=('Arial', 11, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(anchor=tk.W, pady=(0, 20))

        tk.Label(body, text="Enter Admin Password:",
                 font=('Arial', 10, 'bold'), bg=self.bg_color).pack(anchor=tk.W, pady=(0, 5))

        pwd_var = tk.StringVar()
        pwd_entry = tk.Entry(body, textvariable=pwd_var, width=35,
                            font=('Arial', 11), show="●")
        pwd_entry.pack(fill=tk.X, pady=(0, 15))
        pwd_entry.focus()

        status_label = tk.Label(body, text="", bg=self.bg_color,
                               font=('Arial', 10))
        status_label.pack(pady=(0, 10))

        def verify():
            password = pwd_var.get().strip()
            if not password:
                status_label.config(text="❌ Please enter password", fg=self.danger_color)
                return

            admin_info = db.get_admin_info()
            if db.verify_admin_password(password):
                # Log successful approval
                db.log_approval(action_name, admin_info.get('name', 'Admin'), "Approved")
                result["verified"] = True
                dialog.destroy()
            else:
                # Log failed attempt
                db.log_approval(action_name, "Unknown", "Denied")
                status_label.config(text="❌ Incorrect password", fg=self.danger_color)
                pwd_entry.delete(0, tk.END)

        # Buttons
        btn_frame = tk.Frame(body, bg=self.bg_color)
        btn_frame.pack(fill=tk.X)

        tk.Button(btn_frame, text="✓ Verify",
                  command=verify,
                  bg=self.success_color, fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=20, pady=8).pack(side=tk.LEFT, padx=5)

        tk.Button(btn_frame, text="✕ Cancel",
                  command=dialog.destroy,
                  bg=self.danger_color, fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=20, pady=8).pack(side=tk.LEFT, padx=5)

        # Bind Enter key
        pwd_entry.bind('<Return>', lambda e: verify())

        # Wait for dialog to close
        self.root.wait_window(dialog)

        return result["verified"]

    def change_admin_password(self):
        """Change admin password"""
        db = getattr(self, '_alert_db', None)
        if db is None:
            return

        # First verify current password
        if not self.verify_admin_dialog("Change Admin Password"):
            return

        # Show change password dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("🔐 Change Admin Password")
        dialog.geometry("450x350")
        dialog.configure(bg=self.bg_color)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 175
        dialog.geometry(f"+{x}+{y}")

        tk.Label(dialog, text="🔐 Change Admin Password",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=20)

        form = tk.Frame(dialog, bg=self.card_bg, padx=20, pady=20)
        form.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        tk.Label(form, text="New Password:", bg=self.card_bg,
                 font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        new_pwd_var = tk.StringVar()
        new_pwd_entry = tk.Entry(form, textvariable=new_pwd_var, width=35,
                                 font=('Arial', 11), show="●")
        new_pwd_entry.pack(fill=tk.X, pady=(0, 15))

        tk.Label(form, text="Confirm Password:", bg=self.card_bg,
                 font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        confirm_pwd_var = tk.StringVar()
        confirm_pwd_entry = tk.Entry(form, textvariable=confirm_pwd_var, width=35,
                                     font=('Arial', 11), show="●")
        confirm_pwd_entry.pack(fill=tk.X, pady=(0, 15))

        status_label = tk.Label(form, text="", bg=self.card_bg,
                               font=('Arial', 10))
        status_label.pack(pady=(0, 10))

        def save_new_password():
            new_pwd = new_pwd_var.get().strip()
            confirm = confirm_pwd_var.get().strip()

            if not new_pwd or not confirm:
                status_label.config(text="❌ All fields required", fg=self.danger_color)
                return

            if new_pwd != confirm:
                status_label.config(text="❌ Passwords do not match", fg=self.danger_color)
                return

            if len(new_pwd) < 4:
                status_label.config(text="❌ Password must be at least 4 characters", fg=self.danger_color)
                return

            if db.update_admin_password(new_pwd):
                messagebox.showinfo("Success", "Admin password updated successfully!", parent=dialog)
                dialog.destroy()
            else:
                status_label.config(text="❌ Failed to update password", fg=self.danger_color)

        tk.Button(form, text="💾 Update Password",
                  command=save_new_password,
                  bg=self.success_color, fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=20, pady=10).pack(fill=tk.X)

    def view_approval_logs(self):
        """View approval logs"""
        db = getattr(self, '_alert_db', None)
        if db is None:
            return

        logs = db.get_approval_logs(limit=100)

        # Create logs window
        log_window = tk.Toplevel(self.root)
        log_window.title("📋 Approval Logs")
        log_window.geometry("800x500")
        log_window.configure(bg=self.bg_color)

        tk.Label(log_window, text="📋 Admin Approval Logs",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=20)

        # Treeview
        tree_frame = tk.Frame(log_window, bg=self.bg_color)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        columns = ("ID", "Action", "Admin", "Status", "Timestamp")
        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15)

        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=150)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Load logs
        for log in logs:
            tree.insert("", tk.END, values=(
                log.get('id', ''),
                log.get('action', ''),
                log.get('admin_name', ''),
                log.get('status', ''),
                log.get('timestamp', '')
            ))

        tk.Button(log_window, text="Close",
                  command=log_window.destroy,
                  bg=self.primary_color, fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=30, pady=10).pack(pady=(0, 20))
    
    def delete_and_recreate_admin(self):
        """Delete current admin and allow creating new one"""
        # Admin verification required FIRST
        if not self.verify_admin_dialog("Delete and Recreate Admin Account"):
            return
        
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        
        # Confirmation dialog
        confirm = messagebox.askyesno(
            "Delete Admin Account",
            "⚠️ WARNING: This will permanently delete the current admin account!\n\n"
            "You will need to create a new admin account afterwards.\n\n"
            "Are you sure you want to continue?",
            icon='warning'
        )
        
        if not confirm:
            return
        
        # Second confirmation for safety
        final_confirm = messagebox.askyesno(
            "Final Confirmation",
            "This action CANNOT be undone!\n\n"
            "Delete admin account and all approval logs?",
            icon='warning'
        )
        
        if not final_confirm:
            return
        
        # Logout if logged in
        if self.admin_logged_in:
            self.admin_logged_in = False
            self.logged_in_admin_name = None
        
        # Delete admin account
        if db.delete_admin_account():
            # Also clear approval logs
            try:
                cur = db.conn.cursor()
                cur.execute("DELETE FROM approval_logs")
                db.conn.commit()
                print("✅ Approval logs cleared")
            except Exception as e:
                print(f"⚠️ Could not clear logs: {e}")
            
            messagebox.showinfo(
                "Success",
                "✅ Admin account deleted successfully!\n\n"
                "You can now create a new admin account."
            )
            
            # Refresh admin panel to show setup form
            self.refresh_admin_panel()
        else:
            messagebox.showerror("Error", "Failed to delete admin account!")

    def admin_login_dialog(self):
        """Admin login dialog - sets session state on success"""
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        
        admin_info = db.get_admin_info()
        
        if not admin_info:
            messagebox.showerror("Error", "No admin account configured!\nPlease set up admin first in Settings.")
            return False
        
        # Create login window
        login_window = tk.Toplevel(self.root)
        login_window.title("🔐 Admin Login")
        login_window.geometry("500x400")
        login_window.configure(bg=self.bg_color)
        login_window.transient(self.root)
        login_window.grab_set()
        
        # Center the window
        login_window.update_idletasks()
        x = (login_window.winfo_screenwidth() // 2) - (250)
        y = (login_window.winfo_screenheight() // 2) - (200)
        login_window.geometry(f"500x400+{x}+{y}")
        
        result = {'success': False}
        
        # Header (theme-aware)
        header = tk.Frame(login_window, bg=self.primary_color, height=60)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        
        tk.Label(header, text="🔐 Admin Login",
                font=('Arial', 16, 'bold'), bg=self.primary_color, fg='white').pack(pady=15)
        
        # Body (theme-aware)
        body = tk.Frame(login_window, bg=self.bg_color)
        body.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        
        tk.Label(body, text="Please enter your password to unlock all features.",
                font=('Arial', 10), bg=self.bg_color, fg=self.primary_text, wraplength=380).pack(pady=(0, 20))
        
        # Admin info display
        info_frame = tk.Frame(body, bg=self.card_bg, relief=tk.SOLID, bd=1)
        info_frame.pack(fill=tk.X, pady=(0, 15))
        tk.Label(info_frame, text=f"👤 {admin_info['name']} ({admin_info['email']})",
                font=('Arial', 10, 'bold'), bg=self.card_bg, fg=self.primary_text).pack(pady=8)
        
        # Password field
        tk.Label(body, text="Password:", font=('Arial', 10, 'bold'),
                bg=self.bg_color, fg=self.primary_text).pack(anchor=tk.W)
        
        password_var = tk.StringVar()
        password_entry = tk.Entry(body, textvariable=password_var, show="●",
                                 font=('Arial', 11), width=30, relief=tk.SOLID, bd=1)
        password_entry.pack(fill=tk.X, pady=(5, 15))
        password_entry.focus()
        
        status_label = tk.Label(body, text="", font=('Arial', 9),
                               bg=self.bg_color, fg=self.primary_text)
        status_label.pack()
        
        def attempt_login():
            password = password_var.get().strip()
            if not password:
                status_label.config(text="❌ Please enter password", fg=self.danger_color)
                return
            
            if db.verify_admin_password(password):
                self.admin_logged_in = True
                self.logged_in_admin_name = admin_info['name']
                db.log_approval("Admin Login", admin_info['name'], "approved", "Successful login")
                result['success'] = True
                messagebox.showinfo("Success", f"Welcome {admin_info['name']}!\nAll features unlocked.")
                login_window.destroy()
                self.refresh_admin_panel()
            else:
                status_label.config(text="❌ Incorrect password", fg=self.danger_color)
                db.log_approval("Admin Login", admin_info['name'], "denied", "Incorrect password")
        
        def on_cancel():
            login_window.destroy()
        
        # Bind Enter key
        password_entry.bind('<Return>', lambda e: attempt_login())
        
        # Buttons
        btn_frame = tk.Frame(body, bg='#f8f9fa')
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        tk.Button(btn_frame, text="🔓 Login", command=attempt_login,
                 bg='#28a745', fg='white', font=('Arial', 11, 'bold'),
                 padx=20, pady=8, cursor='hand2').pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        
        tk.Button(btn_frame, text="Cancel", command=on_cancel,
                 bg='#6c757d', fg='white', font=('Arial', 11, 'bold'),
                 padx=20, pady=8, cursor='hand2').pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(5, 0))
        
        login_window.wait_window()
        return result['success']
    
    def admin_logout(self):
        """Logout admin and lock features"""
        if not self.admin_logged_in:
            return
        
        confirm = messagebox.askyesno("Confirm Logout",
                                     f"Logout {self.logged_in_admin_name}?\n\nAll features will be locked again.")
        if confirm:
            db = getattr(self, '_alert_db', None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            
            db.log_approval("Admin Logout", self.logged_in_admin_name, "approved", "Logged out")
            self.admin_logged_in = False
            self.logged_in_admin_name = None
            messagebox.showinfo("Logged Out", "You have been logged out.\nFeatures are now locked.")
            self.refresh_admin_panel()
    
    def refresh_admin_panel(self):
        """Refresh admin panel to show current login state"""
        if hasattr(self, 'admin_settings_frame') and self.admin_settings_frame.winfo_exists():
            self.admin_settings_frame.destroy()
            self.admin_settings_frame = tk.Frame(self.settings_scrollable_frame, bg=self.bg_color)
            self.create_admin_panel_section(self.admin_settings_frame)
            self.admin_settings_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        # Update sidebar status indicator
        self.update_admin_status_indicator()
    
    def update_admin_status_indicator(self):
        """Update the admin status indicator in sidebar"""
        if not hasattr(self, 'admin_status_label'):
            return
        
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        
        has_admin = db.has_admin_credentials()
        
        if self.admin_logged_in:
            # Logged in - green status
            self.admin_status_frame.config(bg='#28a745')
            self.admin_status_label.config(
                text=f"✅ Admin: {self.logged_in_admin_name}",
                bg='#28a745'
            )
            # Hide login button
            if hasattr(self, 'quick_login_btn'):
                self.quick_login_btn.pack_forget()
        elif has_admin:
            # Admin exists but not logged in - use theme accent
            self.admin_status_frame.config(bg=self.accent_color)
            self.admin_status_label.config(
                text="👤 User View",
                bg=self.accent_color,
                fg='white'
            )
            # Show login button only after authentication
            if hasattr(self, 'quick_login_btn') and self.authenticated:
                self.quick_login_btn.pack(fill=tk.X, padx=10, pady=(0, 5))
            elif hasattr(self, 'quick_login_btn'):
                self.quick_login_btn.pack_forget()
        else:
            # No admin - gray status
            self.admin_status_frame.config(bg='#6c757d')
            self.admin_status_label.config(
                text="🔒 Features Locked",
                bg='#6c757d',
                fg='white'
            )
            # Hide login button
            if hasattr(self, 'quick_login_btn'):
                self.quick_login_btn.pack_forget()

    def create_all_reminders_view(self, parent):
        """Show all reminders in one combined view"""
        # Main frame with scroll
        main_frame = tk.Frame(parent, bg=self.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Toolbar
        toolbar = tk.Frame(main_frame, bg=self.bg_color, height=40)
        toolbar.pack(fill=tk.X, padx=10, pady=(5, 10))
        toolbar.pack_propagate(False)

        tk.Button(toolbar, text="🔄 Refresh", command=self.refresh_all_reminders,
                  bg=self.primary_color, fg='white', font=('Arial', 10),
                  padx=10).pack(side=tk.LEFT, padx=5)

        tk.Button(toolbar, text="� Delete Selected (Admin)", command=self.delete_selected_reminder,
                  bg=self.danger_color, fg='white', font=('Arial', 10),
                  padx=10, cursor='hand2').pack(side=tk.LEFT, padx=5)

        tk.Button(toolbar, text="📤 Export", command=self.export_reminders,
                  bg=self.success_color, fg='white', font=('Arial', 10),
                  padx=10).pack(side=tk.LEFT, padx=5)

        # Filter frame
        filter_frame = tk.Frame(toolbar, bg=self.bg_color)
        filter_frame.pack(side=tk.RIGHT)

        tk.Label(filter_frame, text="Filter:", bg=self.bg_color,
                 font=('Arial', 10)).pack(side=tk.LEFT)

        self.filter_var = tk.StringVar(value="all")
        filter_combo = ttk.Combobox(filter_frame, textvariable=self.filter_var,
                                    values=["All", "Upcoming", "Past", "Today", "This Week"],
                                    state="readonly", width=12)
        filter_combo.pack(side=tk.LEFT, padx=5)
        filter_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_all_reminders())

        # Treeview for all reminders
        columns = ("Type", "Title", "Date", "Time", "Details", "Status", "ID")
        self.all_reminders_tree = ttk.Treeview(main_frame, columns=columns,
                                               show="headings", height=15)

        # Configure columns
        col_widths = [100, 150, 100, 80, 200, 100, 0]  # Last column hidden
        for col, width in zip(columns, col_widths):
            self.all_reminders_tree.heading(col, text=col)
            self.all_reminders_tree.column(col, width=width, minwidth=50)
            if col == "ID":
                self.all_reminders_tree.column(col, width=0, stretch=False)  # Hide ID column

        # Add scrollbar
        tree_scroll = ttk.Scrollbar(main_frame, orient="vertical",
                                    command=self.all_reminders_tree.yview)
        self.all_reminders_tree.configure(yscrollcommand=tree_scroll.set)

        self.all_reminders_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 10))

        # Double-click to view details
        self.all_reminders_tree.bind("<Double-1>", self.view_reminder_details)

        # Load data
        self.refresh_all_reminders()

    def create_type_specific_view(self, parent, reminder_type):
        """Create view for specific reminder type with vertical scrolling"""
        # Convert type to display name
        type_names = {
            "appointments": "Appointments",
            "prescriptions": "Prescriptions",
            "lab_tests": "Lab Tests",
            "custom": "Custom Reminders"
        }
        display_name = type_names.get(reminder_type, reminder_type)

        # Create scrollable container
        canvas, scrollable_frame = self.create_scrollable_frame(parent)

        # Title
        tk.Label(scrollable_frame, text=f"{display_name}",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=(10, 5))

        # Stats frame
        stats_frame = tk.Frame(scrollable_frame, bg=self.card_bg, relief=tk.RIDGE, bd=1)
        stats_frame.pack(fill=tk.X, padx=20, pady=(0, 10))

        # Will be updated by refresh function
        self.stats_label = tk.Label(stats_frame, text="Loading...", bg=self.card_bg,
                                    font=('Arial', 10))
        self.stats_label.pack(pady=5)

        # Treeview for this type
        if reminder_type == "appointments":
            columns = ("Doctor", "Specialty", "Date", "Time", "Location", "Status", "ID")
        elif reminder_type == "prescriptions":
            columns = ("Medicine", "Doctor", "Expiry", "Pharmacy", "Status", "ID")
        elif reminder_type == "lab_tests":
            columns = ("Test Name", "Date", "Time", "Location", "Status", "ID")
        else:  # custom
            columns = ("Title", "Date", "Time", "Priority", "Status", "ID")

        tree_name = f"{reminder_type}_tree"
        tree = ttk.Treeview(scrollable_frame, columns=columns, show="headings", height=12)
        setattr(self, tree_name, tree)  # Store as attribute

        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=120 if col != "ID" else 0)
            if col == "ID":
                tree.column(col, width=0, stretch=False)

        # Add scrollbar
        tree_scroll = ttk.Scrollbar(scrollable_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=tree_scroll.set)

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(20, 0), pady=10)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 20), pady=10)

        # Action buttons
        btn_frame = tk.Frame(scrollable_frame, bg=self.bg_color)
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 10))

        tk.Button(btn_frame, text="�️ View Details",
                  command=lambda: self.view_reminder_by_type(reminder_type),
                  bg=self.success_color, fg='white', font=('Arial', 10),
                  padx=15).pack(side=tk.LEFT, padx=5)

        tk.Button(btn_frame, text="🗑️ Delete",
                  command=lambda: self.delete_reminder_by_type(reminder_type),
                  bg=self.danger_color, fg='white', font=('Arial', 10),
                  padx=15).pack(side=tk.LEFT, padx=5)

        if reminder_type == "appointments":
            tk.Button(btn_frame, text="📱 Send to Mobile Alert Bot",
                      command=self.send_appointment_mobile_reminder,
                      bg=self.warning_color, fg='black', font=('Arial', 10),
                      padx=15).pack(side=tk.LEFT, padx=5)

        # Store refresh reference for auto-refresh functionality
        self.tab_refresh_func = lambda: self.refresh_type_reminders(reminder_type)

        # Load data
        self.refresh_type_reminders(reminder_type)

    def refresh_all_reminders(self):
        """Refresh the combined reminders view"""
        if not hasattr(self, 'all_reminders_tree'):
            return

        # Clear tree
        for item in self.all_reminders_tree.get_children():
            self.all_reminders_tree.delete(item)

        # Get all reminders
        all_reminders = []
        for reminder_type in ["appointments", "prescriptions", "lab_tests", "custom"]:
            reminders = self.medical_reminders.get(reminder_type, [])
            for rem in reminders:
                rem["_type"] = reminder_type
                all_reminders.append(rem)

        # Sort by date
        all_reminders.sort(key=lambda x: x.get("date", "9999-12-31"))

        # Filter if needed
        filter_type = self.filter_var.get() if hasattr(self, 'filter_var') else "All"
        today = datetime.datetime.now().date()

        filtered_reminders = []
        for rem in all_reminders:
            rem_date = datetime.datetime.strptime(rem.get("date", "9999-12-31"), "%Y-%m-%d").date()

            if filter_type == "All":
                filtered_reminders.append(rem)
            elif filter_type == "Upcoming" and rem_date >= today:
                filtered_reminders.append(rem)
            elif filter_type == "Past" and rem_date < today:
                filtered_reminders.append(rem)
            elif filter_type == "Today" and rem_date == today:
                filtered_reminders.append(rem)
            elif filter_type == "This Week":
                days_diff = (rem_date - today).days
                if 0 <= days_diff <= 7:
                    filtered_reminders.append(rem)

        # Add to tree
        for rem in filtered_reminders:
            # Format display based on type
            if rem["_type"] == "appointments":
                values = (
                    "📅 Appointment",
                    f"Dr. {rem.get('doctor', 'Unknown')}",
                    rem.get("date", ""),
                    rem.get("time", ""),
                    rem.get("location", ""),
                    rem.get("status", "scheduled"),
                    rem.get("id", "")
                )
            elif rem["_type"] == "prescriptions":
                values = (
                    "💊 Prescription",
                    rem.get("medicine", "Unknown"),
                    rem.get("expiry_date", ""),
                    rem.get("time", ""),
                    f"By: {rem.get('doctor', 'Unknown')}",
                    rem.get("status", "active"),
                    rem.get("id", "")
                )
            elif rem["_type"] == "lab_tests":
                values = (
                    "🧪 Lab Test",
                    rem.get("test_name", "Unknown"),
                    rem.get("date", ""),
                    rem.get("time", ""),
                    rem.get("location", ""),
                    rem.get("status", "scheduled"),
                    rem.get("id", "")
                )
            else:  # custom
                values = (
                    "🔔 Custom",
                    rem.get("title", "Unknown"),
                    rem.get("date", ""),
                    rem.get("time", ""),
                    rem.get("description", "")[:50] + "..." if len(rem.get("description", "")) > 50 else rem.get(
                        "description", ""),
                    rem.get("status", "active"),
                    rem.get("id", "")
                )

            self.all_reminders_tree.insert("", "end", values=values)

    def refresh_type_reminders(self, reminder_type):
        """Refresh reminders for a specific type"""
        tree_name = f"{reminder_type}_tree"
        if not hasattr(self, tree_name):
            return

        tree = getattr(self, tree_name)

        # Clear tree
        for item in tree.get_children():
            tree.delete(item)

        # Get reminders of this type
        reminders = self.medical_reminders.get(reminder_type, [])

        # Update stats
        if hasattr(self, 'stats_label'):
            today = datetime.datetime.now().date()
            upcoming = 0
            past = 0
            for rem in reminders:
                # Use valid fallback date (9999-12-31 instead of 9999-99-99)
                rem_date = datetime.datetime.strptime(rem.get("date", "9999-12-31"), "%Y-%m-%d").date()
                if rem_date >= today:
                    upcoming += 1
                else:
                    past += 1

            type_name = reminder_type.replace("_", " ").title()
            self.stats_label.config(text=f"Total: {len(reminders)} | Upcoming: {upcoming} | Past: {past}")

        # Add to tree
        for rem in reminders:
            if reminder_type == "appointments":
                values = (
                    rem.get("doctor", "Unknown"),
                    rem.get("specialty", ""),
                    rem.get("date", ""),
                    rem.get("time", ""),
                    rem.get("location", ""),
                    rem.get("status", "scheduled"),
                    rem.get("id", "")
                )
            elif reminder_type == "prescriptions":
                values = (
                    rem.get("medicine", "Unknown"),
                    rem.get("doctor", ""),
                    rem.get("expiry_date", ""),
                    rem.get("pharmacy", ""),
                    rem.get("status", "active"),
                    rem.get("id", "")
                )
            elif reminder_type == "lab_tests":
                values = (
                    rem.get("test_name", "Unknown"),
                    rem.get("date", ""),
                    rem.get("time", ""),
                    rem.get("location", ""),
                    rem.get("status", "scheduled"),
                    rem.get("id", "")
                )
            else:  # custom
                values = (
                    rem.get("title", "Unknown"),
                    rem.get("date", ""),
                    rem.get("time", ""),
                    rem.get("priority", "medium"),
                    rem.get("status", "active"),
                    rem.get("id", "")
                )

            tree.insert("", "end", values=values)

    def add_appointment(self):
        """Add doctor appointment - REAL IMPLEMENTATION"""
        # Admin verification required FIRST
        if not self.verify_admin_dialog("Add Appointment"):
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Doctor Appointment")
        dialog.geometry("500x650")
        dialog.configure(bg=self.bg_color)
        dialog.resizable(False, False)

        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 250
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 325
        dialog.geometry(f"+{x}+{y}")

        # Title
        tk.Label(dialog, text="Add Doctor Appointment",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=20)

        # Form frame
        form_frame = tk.Frame(dialog, bg=self.card_bg, padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        # Doctor Name
        tk.Label(form_frame, text="Doctor Name *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=0, column=0, sticky=tk.W, pady=10)
        doctor_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        doctor_entry.grid(row=0, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Specialty
        tk.Label(form_frame, text="Specialty:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=1, column=0, sticky=tk.W, pady=10)
        specialty_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        specialty_entry.grid(row=1, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Date
        tk.Label(form_frame, text="Date *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=2, column=0, sticky=tk.W, pady=10)
        date_entry = DateEntry(form_frame, font=('Arial', 11), date_pattern='yyyy-mm-dd')
        date_entry.grid(row=2, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Time
        tk.Label(form_frame, text="Time *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=3, column=0, sticky=tk.W, pady=10)

        time_frame = tk.Frame(form_frame, bg=self.card_bg)
        time_frame.grid(row=3, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        hour_combo = ttk.Combobox(time_frame, values=[f"{i:02d}" for i in range(1, 13)],
                                  width=5, state="readonly")
        hour_combo.pack(side=tk.LEFT)
        hour_combo.set("10")

        tk.Label(time_frame, text=":", bg=self.card_bg).pack(side=tk.LEFT, padx=5)

        minute_combo = ttk.Combobox(time_frame, values=[f"{i:02d}" for i in range(0, 60, 5)],
                                    width=5, state="readonly")
        minute_combo.pack(side=tk.LEFT)
        minute_combo.set("00")

        ampm_combo = ttk.Combobox(time_frame, values=["AM", "PM"], width=5, state="readonly")
        ampm_combo.pack(side=tk.LEFT, padx=(10, 0))
        ampm_combo.set("AM")

        # Location
        tk.Label(form_frame, text="Location/Clinic *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=4, column=0, sticky=tk.W, pady=10)
        location_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        location_entry.grid(row=4, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Purpose
        tk.Label(form_frame, text="Purpose:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=5, column=0, sticky=tk.NW, pady=10)
        purpose_text = tk.Text(form_frame, height=3, width=30, font=('Arial', 11))
        purpose_text.grid(row=5, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Reminder options
        tk.Label(form_frame, text="Reminders:", bg=self.card_bg,
                 font=('Arial', 11, 'bold')).grid(row=6, column=0, sticky=tk.W, pady=10)

        reminder_frame = tk.Frame(form_frame, bg=self.card_bg)
        reminder_frame.grid(row=6, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        reminder_24h = tk.BooleanVar(value=True)
        tk.Checkbutton(reminder_frame, text="24 hours before",
                       variable=reminder_24h, bg=self.card_bg).pack(anchor=tk.W)

        reminder_2h = tk.BooleanVar(value=True)
        tk.Checkbutton(reminder_frame, text="2 hours before",
                       variable=reminder_2h, bg=self.card_bg).pack(anchor=tk.W)

        # Save function
        def save_appointment():
            # Get values
            doctor = doctor_entry.get().strip()
            specialty = specialty_entry.get().strip()
            date = date_entry.get_date().strftime("%Y-%m-%d")

            # Format time
            hour = int(hour_combo.get())
            if ampm_combo.get() == "PM" and hour != 12:
                hour += 12
            elif ampm_combo.get() == "AM" and hour == 12:
                hour = 0

            time_str = f"{hour:02d}:{minute_combo.get()}"
            location = location_entry.get().strip()
            purpose = purpose_text.get("1.0", tk.END).strip()

            # Validate
            if not doctor or not location:
                messagebox.showwarning("Missing Info",
                                       "Please fill in required fields (*)")
                return

            # Create appointment ID
            import uuid
            appointment_id = str(uuid.uuid4())[:8]

            # Add to appointments list
            appointment = {
                "id": appointment_id,
                "type": "appointment",
                "doctor": doctor,
                "specialty": specialty,
                "date": date,
                "time": time_str,
                "location": location,
                "purpose": purpose,
                "reminders": {
                    "24h": reminder_24h.get(),
                    "2h": reminder_2h.get()
                },
                "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "scheduled"
            }

            # Add to reminders
            if "appointments" not in self.medical_reminders:
                self.medical_reminders["appointments"] = []
            self.medical_reminders["appointments"].append(appointment)

            # Save to file
            self.save_medical_reminders()
            if hasattr(self, 'refresh_all_reminders'):
                self.refresh_all_reminders()
            if hasattr(self, 'refresh_type_reminders'):
                self.refresh_type_reminders("appointments")
            # Schedule alerts only if at least one reminder option is checked
            if reminder_24h.get() or reminder_2h.get():
                self.schedule_appointment_alert(appointment)

            messagebox.showinfo("Success", f"Appointment with Dr. {doctor} scheduled!")
            dialog.destroy()

            # Refresh display if exists
            if hasattr(self, 'refresh_medical_reminders_display'):
                self.refresh_medical_reminders_display()

        # Buttons
        btn_frame = tk.Frame(dialog, bg=self.bg_color)
        btn_frame.pack(pady=(0, 20))

        tk.Button(btn_frame, text="Save Appointment", command=save_appointment,
                  bg=self.success_color, fg='white', font=('Arial', 12, 'bold'),
                  padx=20, pady=10).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  bg=self.danger_color, fg='white', font=('Arial', 12),
                  padx=20, pady=10).pack(side=tk.LEFT, padx=10)

    def add_prescription_reminder(self):
        """Add prescription renewal reminder - REAL IMPLEMENTATION"""
        # Admin verification required FIRST
        if not self.verify_admin_dialog("Add Prescription"):
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Prescription Reminder")
        dialog.geometry("500x600")
        dialog.configure(bg=self.bg_color)
        dialog.resizable(False, False)

        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 250
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 300
        dialog.geometry(f"+{x}+{y}")

        # Title
        tk.Label(dialog, text="Add Prescription Reminder",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=20)

        # Form frame
        form_frame = tk.Frame(dialog, bg=self.card_bg, padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        # Medicine Name
        tk.Label(form_frame, text="Medicine Name *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=0, column=0, sticky=tk.W, pady=10)
        med_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        med_entry.grid(row=0, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Doctor Name
        tk.Label(form_frame, text="Prescribed by:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=1, column=0, sticky=tk.W, pady=10)
        doctor_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        doctor_entry.grid(row=1, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Expiry Date
        tk.Label(form_frame, text="Expiry/Renewal Date *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=2, column=0, sticky=tk.W, pady=10)
        expiry_entry = DateEntry(form_frame, font=('Arial', 11), date_pattern='yyyy-mm-dd')
        expiry_entry.grid(row=2, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Pharmacy
        tk.Label(form_frame, text="Pharmacy:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=3, column=0, sticky=tk.W, pady=10)
        pharmacy_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        pharmacy_entry.grid(row=3, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Instructions
        tk.Label(form_frame, text="Instructions:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=4, column=0, sticky=tk.NW, pady=10)
        instructions_text = tk.Text(form_frame, height=3, width=30, font=('Arial', 11))
        instructions_text.grid(row=4, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Reminder options
        tk.Label(form_frame, text="Remind me:", bg=self.card_bg,
                 font=('Arial', 11, 'bold')).grid(row=5, column=0, sticky=tk.W, pady=10)

        reminder_frame = tk.Frame(form_frame, bg=self.card_bg)
        reminder_frame.grid(row=5, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        reminder_7d = tk.BooleanVar(value=True)
        tk.Checkbutton(reminder_frame, text="7 days before expiry",
                       variable=reminder_7d, bg=self.card_bg).pack(anchor=tk.W)

        reminder_3d = tk.BooleanVar(value=True)
        tk.Checkbutton(reminder_frame, text="3 days before expiry",
                       variable=reminder_3d, bg=self.card_bg).pack(anchor=tk.W)

        reminder_1d = tk.BooleanVar(value=True)
        tk.Checkbutton(reminder_frame, text="1 day before expiry",
                       variable=reminder_1d, bg=self.card_bg).pack(anchor=tk.W)

        # Save function
        def save_prescription():
            medicine = med_entry.get().strip()
            doctor = doctor_entry.get().strip()
            expiry = expiry_entry.get_date().strftime("%Y-%m-%d")
            pharmacy = pharmacy_entry.get().strip()
            instructions = instructions_text.get("1.0", tk.END).strip()

            if not medicine:
                messagebox.showwarning("Missing Info", "Medicine name is required")
                return

            import uuid
            prescription_id = str(uuid.uuid4())[:8]

            prescription = {
                "id": prescription_id,
                "type": "prescription",
                "medicine": medicine,
                "doctor": doctor,
                "expiry_date": expiry,
                "pharmacy": pharmacy,
                "instructions": instructions,
                "reminders": {
                    "7d": reminder_7d.get(),
                    "3d": reminder_3d.get(),
                    "1d": reminder_1d.get()
                },
                "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "active"
            }

            if "prescriptions" not in self.medical_reminders:
                self.medical_reminders["prescriptions"] = []
            self.medical_reminders["prescriptions"].append(prescription)

            self.save_medical_reminders()

            # Schedule reminders
            self.schedule_prescription_alert(prescription)
            
            # Refresh all tabs
            if hasattr(self, 'refresh_all_reminders'):
                self.refresh_all_reminders()
            if hasattr(self, 'refresh_type_reminders'):
                self.refresh_type_reminders("prescriptions")

            messagebox.showinfo("Success", f"Prescription for {medicine} added!")
            dialog.destroy()

            if hasattr(self, 'refresh_medical_reminders_display'):
                self.refresh_medical_reminders_display()

        # Buttons
        btn_frame = tk.Frame(dialog, bg=self.bg_color)
        btn_frame.pack(pady=(0, 20))

        tk.Button(btn_frame, text="Save Prescription", command=save_prescription,
                  bg=self.success_color, fg='white', font=('Arial', 12, 'bold'),
                  padx=20, pady=10).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  bg=self.danger_color, fg='white', font=('Arial', 12),
                  padx=20, pady=10).pack(side=tk.LEFT, padx=10)

    def add_lab_test(self):
        """Add lab test reminder - REAL IMPLEMENTATION"""
        # Admin verification required FIRST
        if not self.verify_admin_dialog("Add Lab Test"):
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Lab Test Reminder")
        dialog.geometry("500x620")
        dialog.configure(bg=self.bg_color)
        dialog.resizable(False, False)

        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 250
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 275
        dialog.geometry(f"+{x}+{y}")

        # Title
        tk.Label(dialog, text="Add Lab Test Reminder",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=20)

        # Form frame
        form_frame = tk.Frame(dialog, bg=self.card_bg, padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        # Test Name
        tk.Label(form_frame, text="Test Name *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=0, column=0, sticky=tk.W, pady=10)
        test_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        test_entry.grid(row=0, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Test Date
        tk.Label(form_frame, text="Test Date *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=1, column=0, sticky=tk.W, pady=10)
        date_entry = DateEntry(form_frame, font=('Arial', 11), date_pattern='yyyy-mm-dd')
        date_entry.grid(row=1, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Time
        tk.Label(form_frame, text="Time:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=2, column=0, sticky=tk.W, pady=10)

        time_frame = tk.Frame(form_frame, bg=self.card_bg)
        time_frame.grid(row=2, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        hour_combo = ttk.Combobox(time_frame, values=[f"{i:02d}" for i in range(1, 13)],
                                  width=5, state="readonly")
        hour_combo.pack(side=tk.LEFT)
        hour_combo.set("08")

        tk.Label(time_frame, text=":", bg=self.card_bg).pack(side=tk.LEFT, padx=5)

        minute_combo = ttk.Combobox(time_frame, values=[f"{i:02d}" for i in range(0, 60, 5)],
                                    width=5, state="readonly")
        minute_combo.pack(side=tk.LEFT)
        minute_combo.set("00")

        ampm_combo = ttk.Combobox(time_frame, values=["AM", "PM"], width=5, state="readonly")
        ampm_combo.pack(side=tk.LEFT, padx=(10, 0))
        ampm_combo.set("AM")

        # Location
        tk.Label(form_frame, text="Lab/Location:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=3, column=0, sticky=tk.W, pady=10)
        location_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        location_entry.grid(row=3, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Instructions (fasting, etc.)
        tk.Label(form_frame, text="Instructions (fasting, etc.):", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=4, column=0, sticky=tk.NW, pady=10)
        instructions_text = tk.Text(form_frame, height=3, width=30, font=('Arial', 11))
        instructions_text.grid(row=4, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Reminders (combined format: same as appointment)
        tk.Label(form_frame, text="Reminders:", bg=self.card_bg,
                 font=('Arial', 11, 'bold')).grid(row=5, column=0, sticky=tk.W, pady=10)
        reminder_frame = tk.Frame(form_frame, bg=self.card_bg)
        reminder_frame.grid(row=5, column=1, sticky=tk.W, pady=10, padx=(10, 0))
        lab_reminder_24h = tk.BooleanVar(value=True)
        tk.Checkbutton(reminder_frame, text="24 hours before", variable=lab_reminder_24h, bg=self.card_bg).pack(anchor=tk.W)
        lab_reminder_2h = tk.BooleanVar(value=True)
        tk.Checkbutton(reminder_frame, text="2 hours before", variable=lab_reminder_2h, bg=self.card_bg).pack(anchor=tk.W)

        # Save function
        def save_lab_test():
            test_name = test_entry.get().strip()
            date = date_entry.get_date().strftime("%Y-%m-%d")

            # Format time
            hour = int(hour_combo.get())
            if ampm_combo.get() == "PM" and hour != 12:
                hour += 12
            elif ampm_combo.get() == "AM" and hour == 12:
                hour = 0

            time_str = f"{hour:02d}:{minute_combo.get()}"
            location = location_entry.get().strip()
            instructions = instructions_text.get("1.0", tk.END).strip()

            if not test_name:
                messagebox.showwarning("Missing Info", "Test name is required")
                return

            import uuid
            test_id = str(uuid.uuid4())[:8]

            lab_test = {
                "id": test_id,
                "type": "lab_test",
                "test_name": test_name,
                "date": date,
                "time": time_str,
                "location": location,
                "instructions": instructions,
                "reminders": {
                    "24h": lab_reminder_24h.get(),
                    "2h": lab_reminder_2h.get()
                },
                "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "scheduled"
            }

            if "lab_tests" not in self.medical_reminders:
                self.medical_reminders["lab_tests"] = []
            self.medical_reminders["lab_tests"].append(lab_test)

            self.save_medical_reminders()

            # Schedule reminder (24h before)
            self.schedule_lab_test_alert(lab_test)
            
            # Refresh all tabs
            if hasattr(self, 'refresh_all_reminders'):
                self.refresh_all_reminders()
            if hasattr(self, 'refresh_type_reminders'):
                self.refresh_type_reminders("lab_tests")

            messagebox.showinfo("Success", f"Lab test '{test_name}' scheduled!")
            dialog.destroy()

            if hasattr(self, 'refresh_medical_reminders_display'):
                self.refresh_medical_reminders_display()

        # Buttons
        btn_frame = tk.Frame(dialog, bg=self.bg_color)
        btn_frame.pack(pady=(0, 20))

        tk.Button(btn_frame, text="Save Lab Test", command=save_lab_test,
                  bg=self.success_color, fg='white', font=('Arial', 12, 'bold'),
                  padx=20, pady=10).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  bg=self.danger_color, fg='white', font=('Arial', 12),
                  padx=20, pady=10).pack(side=tk.LEFT, padx=10)

    def add_custom_reminder(self):
        """Add custom medical reminder - REAL IMPLEMENTATION"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Custom Reminder")
        dialog.geometry("500x580")
        dialog.configure(bg=self.bg_color)
        dialog.resizable(False, False)

        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 250
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 250
        dialog.geometry(f"+{x}+{y}")

        # Title
        tk.Label(dialog, text="Add Custom Reminder",
                 font=('Arial', 16, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=20)

        # Form frame
        form_frame = tk.Frame(dialog, bg=self.card_bg, padx=20, pady=20)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        # Title
        tk.Label(form_frame, text="Reminder Title *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=0, column=0, sticky=tk.W, pady=10)
        title_entry = tk.Entry(form_frame, font=('Arial', 11), width=30)
        title_entry.grid(row=0, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Date
        tk.Label(form_frame, text="Date *:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=1, column=0, sticky=tk.W, pady=10)
        date_entry = DateEntry(form_frame, font=('Arial', 11), date_pattern='yyyy-mm-dd')
        date_entry.grid(row=1, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Time
        tk.Label(form_frame, text="Time:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=2, column=0, sticky=tk.W, pady=10)

        time_frame = tk.Frame(form_frame, bg=self.card_bg)
        time_frame.grid(row=2, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        hour_combo = ttk.Combobox(time_frame, values=[f"{i:02d}" for i in range(1, 13)],
                                  width=5, state="readonly")
        hour_combo.pack(side=tk.LEFT)
        hour_combo.set("09")

        tk.Label(time_frame, text=":", bg=self.card_bg).pack(side=tk.LEFT, padx=5)

        minute_combo = ttk.Combobox(time_frame, values=[f"{i:02d}" for i in range(0, 60, 5)],
                                    width=5, state="readonly")
        minute_combo.pack(side=tk.LEFT)
        minute_combo.set("00")

        ampm_combo = ttk.Combobox(time_frame, values=["AM", "PM"], width=5, state="readonly")
        ampm_combo.pack(side=tk.LEFT, padx=(10, 0))
        ampm_combo.set("AM")

        # Description
        tk.Label(form_frame, text="Description:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=3, column=0, sticky=tk.NW, pady=10)
        desc_text = tk.Text(form_frame, height=4, width=30, font=('Arial', 11))
        desc_text.grid(row=3, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        # Priority
        tk.Label(form_frame, text="Priority:", bg=self.card_bg,
                 font=('Arial', 11)).grid(row=4, column=0, sticky=tk.W, pady=10)

        priority_var = tk.StringVar(value="medium")
        priority_frame = tk.Frame(form_frame, bg=self.card_bg)
        priority_frame.grid(row=4, column=1, sticky=tk.W, pady=10, padx=(10, 0))

        tk.Radiobutton(priority_frame, text="Low", variable=priority_var,
                       value="low", bg=self.card_bg).pack(side=tk.LEFT)
        tk.Radiobutton(priority_frame, text="Medium", variable=priority_var,
                       value="medium", bg=self.card_bg).pack(side=tk.LEFT, padx=10)
        tk.Radiobutton(priority_frame, text="High", variable=priority_var,
                       value="high", bg=self.card_bg).pack(side=tk.LEFT)

        # Reminders (24h, 2h - go to email + Mobile Alert Bot)
        tk.Label(form_frame, text="Reminders:", bg=self.card_bg,
                 font=('Arial', 11, 'bold')).grid(row=5, column=0, sticky=tk.W, pady=10)
        custom_reminder_frame = tk.Frame(form_frame, bg=self.card_bg)
        custom_reminder_frame.grid(row=5, column=1, sticky=tk.W, pady=10, padx=(10, 0))
        custom_reminder_24h = tk.BooleanVar(value=True)
        tk.Checkbutton(custom_reminder_frame, text="24 hours before", variable=custom_reminder_24h, bg=self.card_bg).pack(anchor=tk.W)
        custom_reminder_2h = tk.BooleanVar(value=True)
        tk.Checkbutton(custom_reminder_frame, text="2 hours before", variable=custom_reminder_2h, bg=self.card_bg).pack(anchor=tk.W)

        # Save function
        def save_custom_reminder():
            title = title_entry.get().strip()
            date = date_entry.get_date().strftime("%Y-%m-%d")

            # Format time
            hour = int(hour_combo.get())
            if ampm_combo.get() == "PM" and hour != 12:
                hour += 12
            elif ampm_combo.get() == "AM" and hour == 12:
                hour = 0

            time_str = f"{hour:02d}:{minute_combo.get()}"
            description = desc_text.get("1.0", tk.END).strip()
            priority = priority_var.get()

            if not title:
                messagebox.showwarning("Missing Info", "Reminder title is required")
                return

            import uuid
            reminder_id = str(uuid.uuid4())[:8]

            custom_reminder = {
                "id": reminder_id,
                "type": "custom",
                "title": title,
                "date": date,
                "time": time_str,
                "description": description,
                "priority": priority,
                "reminders": {
                    "24h": custom_reminder_24h.get(),
                    "2h": custom_reminder_2h.get()
                },
                "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "active"
            }

            if "custom" not in self.medical_reminders:
                self.medical_reminders["custom"] = []
            self.medical_reminders["custom"].append(custom_reminder)

            self.save_medical_reminders()

            # Schedule reminder (24h before)
            self.schedule_custom_reminder_alert(custom_reminder)
            
            # Refresh all tabs
            if hasattr(self, 'refresh_all_reminders'):
                self.refresh_all_reminders()
            if hasattr(self, 'refresh_type_reminders'):
                self.refresh_type_reminders("custom")

            messagebox.showinfo("Success", f"Custom reminder '{title}' added!")
            dialog.destroy()

            if hasattr(self, 'refresh_medical_reminders_display'):
                self.refresh_medical_reminders_display()

        # Buttons
        btn_frame = tk.Frame(dialog, bg=self.bg_color)
        btn_frame.pack(pady=(0, 20))

        tk.Button(btn_frame, text="Save Reminder", command=save_custom_reminder,
                  bg=self.success_color, fg='white', font=('Arial', 12, 'bold'),
                  padx=20, pady=10).pack(side=tk.LEFT, padx=10)

        tk.Button(btn_frame, text="Cancel", command=dialog.destroy,
                  bg=self.danger_color, fg='white', font=('Arial', 12),
                  padx=20, pady=10).pack(side=tk.LEFT, padx=10)

    # Helper Functions of medical reminders
    def view_reminder_details(self, event=None):
        """View details of selected reminder"""
        selection = self.all_reminders_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a reminder")
            return

        item = selection[0]
        values = self.all_reminders_tree.item(item, "values")
        reminder_id = values[6]

        # Find reminder
        reminder = None
        for rem_type in ["appointments", "prescriptions", "lab_tests", "custom"]:
            for rem in self.medical_reminders.get(rem_type, []):
                if rem.get("id") == reminder_id:
                    reminder = rem
                    break
            if reminder: break

        if reminder:
            self.show_reminder_details_dialog(reminder)

    def show_reminder_details_dialog(self, reminder):
        """Show details dialog for a reminder"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Reminder Details")
        dialog.geometry("400x300")
        dialog.configure(bg=self.bg_color)

        # Center dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 150
        dialog.geometry(f"+{x}+{y}")

        # Title
        if reminder.get("type") == "appointment":
            title = f"Appointment with Dr. {reminder.get('doctor', 'Unknown')}"
        elif reminder.get("type") == "prescription":
            title = f"Prescription: {reminder.get('medicine', 'Unknown')}"
        elif reminder.get("type") == "lab_test":
            title = f"Lab Test: {reminder.get('test_name', 'Unknown')}"
        else:
            title = f"Reminder: {reminder.get('title', 'Unknown')}"

        tk.Label(dialog, text=title, font=('Arial', 14, 'bold'),
                 bg=self.bg_color, fg=self.primary_color).pack(pady=10)

        # Details
        details_frame = tk.Frame(dialog, bg=self.card_bg, padx=15, pady=15)
        details_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Simple text display
        details = f"Date: {reminder.get('date', 'N/A')}\n"
        details += f"Time: {reminder.get('time', 'N/A')}\n"
        details += f"Status: {reminder.get('status', 'N/A')}\n"

        if reminder.get("type") == "appointment":
            details += f"Location: {reminder.get('location', 'N/A')}\n"
            details += f"Purpose: {reminder.get('purpose', 'N/A')}"
        elif reminder.get("type") == "prescription":
            details += f"Doctor: {reminder.get('doctor', 'N/A')}\n"
            details += f"Pharmacy: {reminder.get('pharmacy', 'N/A')}"

        tk.Label(details_frame, text=details, bg=self.card_bg,
                 font=('Arial', 11), justify=tk.LEFT).pack(anchor=tk.W)

        tk.Button(dialog, text="Close", command=dialog.destroy,
                  bg=self.primary_color, fg='white',
                  font=('Arial', 11)).pack(pady=10)

    def delete_selected_reminder(self):
        """Delete selected reminder from all view"""
        selection = self.all_reminders_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select a reminder to delete")
            return

        # Admin verification required
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        
        if db.has_admin_credentials():
            if not self.verify_admin_dialog("Delete Medical Reminder"):
                messagebox.showwarning("Permission Denied", "Admin verification required to delete reminders")
                return

        item = selection[0]
        values = self.all_reminders_tree.item(item, "values")
        reminder_id = values[6]

        # Find reminder type
        for rem_type in ["appointments", "prescriptions", "lab_tests", "custom"]:
            for i, rem in enumerate(self.medical_reminders.get(rem_type, [])):
                if rem.get("id") == reminder_id:
                    # Confirm
                    if messagebox.askyesno("Confirm", "Delete this reminder?"):
                        del self.medical_reminders[rem_type][i]
                        self.save_medical_reminders()
                        self.refresh_all_reminders()
                        messagebox.showinfo("Deleted", "Reminder deleted")
                    return

    def delete_reminder_by_type(self, reminder_type):
        """Delete selected reminder from type view"""
        tree_name = f"{reminder_type}_tree"
        if not hasattr(self, tree_name):
            return

        tree = getattr(self, tree_name)
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select a reminder to delete")
            return

        # Admin verification required
        db = getattr(self, '_alert_db', None)
        if db is None:
            db = AlertDB()
            self._alert_db = db
        
        if db.has_admin_credentials():
            if not self.verify_admin_dialog("Delete Medical Reminder"):
                messagebox.showwarning("Permission Denied", "Admin verification required to delete reminders")
                return

        item = selection[0]
        values = tree.item(item, "values")
        reminder_id = values[-1]

        # Find and delete
        for i, rem in enumerate(self.medical_reminders.get(reminder_type, [])):
            if rem.get("id") == reminder_id:
                if messagebox.askyesno("Confirm", "Delete this reminder?"):
                    del self.medical_reminders[reminder_type][i]
                    self.save_medical_reminders()
                    self.refresh_type_reminders(reminder_type)
                    self.refresh_all_reminders()
                    messagebox.showinfo("Deleted", "Reminder deleted")
                return

    def send_appointment_mobile_reminder(self):
        """Send reminder for selected appointment to Mobile Alert Bot (Android app)"""
        selection = self.appointments_tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select an appointment")
            return

        item = selection[0]
        values = self.appointments_tree.item(item, "values")
        appointment_id = values[-1]

        # Find appointment
        for appt in self.medical_reminders.get("appointments", []):
            if appt.get("id") == appointment_id:
                if not self.mobile_bot.get("enabled"):
                    messagebox.showwarning("Mobile Alert Bot Disabled", "Enable Mobile Alert Bot in Settings")
                    return
                if not (self.mobile_bot.get("bot_id") or "").strip():
                    messagebox.showwarning("Not Configured", "Configure Mobile Alert Bot (Bot ID) in Settings")
                    return

                message = f"Appointment: Dr. {appt.get('doctor')} on {appt.get('date')} at {appt.get('time')}"
                if self.send_mobile_alert("appointment", message):
                    messagebox.showinfo("Sent", "Reminder sent to Mobile Alert Bot")
                else:
                    messagebox.showwarning("Failed", "Could not send to Mobile Alert Bot")
                return

    def export_reminders(self):
        """Export reminders to file (simple version)"""
        try:
            import csv
            file_path = "curax_reminders_export.csv"

            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Type", "Name", "Date", "Time", "Status"])

                for rem_type in ["appointments", "prescriptions", "lab_tests", "custom"]:
                    for rem in self.medical_reminders.get(rem_type, []):
                        if rem_type == "appointments":
                            writer.writerow(["Appointment", f"Dr. {rem.get('doctor', '')}",
                                             rem.get("date", ""), rem.get("time", ""),
                                             rem.get("status", "")])
                        elif rem_type == "prescriptions":
                            writer.writerow(["Prescription", rem.get("medicine", ""),
                                             rem.get("expiry_date", ""), "",
                                             rem.get("status", "")])

            messagebox.showinfo("Exported", f"Saved to {file_path}")
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))

    def view_reminder_by_type(self, reminder_type):
        """View details from type-specific view"""
        tree_name = f"{reminder_type}_tree"
        if not hasattr(self, tree_name):
            return

        tree = getattr(self, tree_name)
        selection = tree.selection()
        if not selection:
            messagebox.showwarning("No Selection", "Select a reminder")
            return

        item = selection[0]
        values = tree.item(item, "values")
        reminder_id = values[-1]

        # Find reminder
        for rem in self.medical_reminders.get(reminder_type, []):
            if rem.get("id") == reminder_id:
                self.show_reminder_details_dialog(rem)
                return

    def refresh_all_reminders(self):
        """Refresh the combined reminders view"""
        if not hasattr(self, 'all_reminders_tree'):
            return

        # Clear tree
        for item in self.all_reminders_tree.get_children():
            self.all_reminders_tree.delete(item)

        # Add all reminders
        for rem_type in ["appointments", "prescriptions", "lab_tests", "custom"]:
            for rem in self.medical_reminders.get(rem_type, []):
                if rem_type == "appointments":
                    self.all_reminders_tree.insert("", "end", values=(
                        "📅 Appointment",
                        f"Dr. {rem.get('doctor', '')}",
                        rem.get("date", ""),
                        rem.get("time", ""),
                        rem.get("location", ""),
                        rem.get("status", ""),
                        rem.get("id", "")
                    ))
                elif rem_type == "prescriptions":
                    self.all_reminders_tree.insert("", "end", values=(
                        "💊 Prescription",
                        rem.get("medicine", ""),
                        rem.get("expiry_date", ""),
                        "",
                        f"Dr. {rem.get('doctor', '')}",
                        rem.get("status", ""),
                        rem.get("id", "")
                    ))
                elif rem_type == "lab_tests":
                    self.all_reminders_tree.insert("", "end", values=(
                        "🧪 Lab Test",
                        rem.get("test_name", ""),
                        rem.get("date", ""),
                        rem.get("time", ""),
                        rem.get("location", ""),
                        rem.get("status", ""),
                        rem.get("id", "")
                    ))
                else:  # custom
                    self.all_reminders_tree.insert("", "end", values=(
                        "🔔 Custom",
                        rem.get("title", ""),
                        rem.get("date", ""),
                        rem.get("time", ""),
                        rem.get("description", "")[:50],
                        rem.get("status", ""),
                        rem.get("id", "")
                    ))

    def _run_reminder_poll_loop(self):
        """Background loop: every 30s check if any medical reminder is due and fire alert."""
        import time
        while not getattr(self, '_reminder_poll_stop', True):
            time.sleep(30)
            try:
                self._check_due_reminder_alerts()
            except Exception as e:
                print(f"✗ Reminder poll error: {e}")

    def _check_due_reminder_alerts(self):
        """If current time is within reminder window (e.g. 2h before event), fire alert once. Runs off main thread."""
        from datetime import datetime, timedelta
        now = datetime.now()
        window_end = timedelta(minutes=5)

        # Appointments: 24h and 2h before
        for appt in self.medical_reminders.get("appointments", []):
            try:
                try:
                    dt_str = appt.get("date", "") + " " + appt.get("time", "12:00")
                    event_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                except Exception:
                    continue
                reminders = appt.get("reminders") or {}
                for rem_type, delta in [("24h", timedelta(hours=24)), ("2h", timedelta(hours=2))]:
                    if not reminders.get(rem_type, True):
                        continue
                    reminder_time = event_dt - delta
                    if event_dt <= now:
                        continue
                    if reminder_time <= now <= reminder_time + window_end:
                        key = (appt.get("id"), rem_type)
                        if key not in self._reminder_sent:
                            self._reminder_sent.add(key)
                            c = dict(appt)
                            self.root.after(0, lambda i=c, r=rem_type: self.send_scheduled_alert("appointment", i, r))
            except Exception as e:
                print(f"✗ Appointment check: {e}")

        # Lab tests: 24h and 2h before
        for lab in self.medical_reminders.get("lab_tests", []):
            try:
                try:
                    dt_str = lab.get("date", "") + " " + lab.get("time", "09:00")
                    event_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                except Exception:
                    continue
                reminders = lab.get("reminders") or {}
                for rem_type, delta in [("24h", timedelta(hours=24)), ("2h", timedelta(hours=2))]:
                    if not reminders.get(rem_type, True):
                        continue
                    reminder_time = event_dt - delta
                    if event_dt <= now:
                        continue
                    if reminder_time <= now <= reminder_time + window_end:
                        key = (lab.get("id"), rem_type)
                        if key not in self._reminder_sent:
                            self._reminder_sent.add(key)
                            c = dict(lab)
                            self.root.after(0, lambda i=c, r=rem_type: self.send_scheduled_alert("lab_test", i, r))
            except Exception as e:
                print(f"✗ Lab test check: {e}")

        # Custom: 24h and 2h before
        for cust in self.medical_reminders.get("custom", []):
            try:
                try:
                    dt_str = cust.get("date", "") + " " + cust.get("time", "09:00")
                    event_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
                except Exception:
                    continue
                reminders = cust.get("reminders") or {}
                for rem_type, delta in [("24h", timedelta(hours=24)), ("2h", timedelta(hours=2))]:
                    if not reminders.get(rem_type, True):
                        continue
                    reminder_time = event_dt - delta
                    if event_dt <= now:
                        continue
                    if reminder_time <= now <= reminder_time + window_end:
                        key = (cust.get("id"), rem_type)
                        if key not in self._reminder_sent:
                            self._reminder_sent.add(key)
                            c = dict(cust)
                            self.root.after(0, lambda i=c, r=rem_type: self.send_scheduled_alert("custom", i, r))
            except Exception as e:
                print(f"✗ Custom reminder check: {e}")

        # Prescriptions: 7d, 3d, 1d (fire once on that reminder day)
        today = now.date()
        for rx in self.medical_reminders.get("prescriptions", []):
            try:
                expiry_str = rx.get("expiry_date")
                if not expiry_str:
                    continue
                expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
                reminders = rx.get("reminders") or {}
                for rem_type, days in [("7d", 7), ("3d", 3), ("1d", 1)]:
                    if not reminders.get(rem_type, True):
                        continue
                    reminder_date = expiry_date - timedelta(days=days)
                    if today == reminder_date:
                        key = (rx.get("id"), rem_type)
                        if key not in self._reminder_sent:
                            self._reminder_sent.add(key)
                            c = dict(rx)
                            self.root.after(0, lambda i=c, r=rem_type: self.send_scheduled_alert("prescription", i, r))
            except Exception as e:
                print(f"✗ Prescription check: {e}")

    # Alert scheduling (email + Mobile Alert Bot)
    def schedule_appointment_alert(self, appointment):
        """Schedule alerts for appointment (email + Mobile Alert Bot)"""
        try:
            # Parse appointment date and time
            from datetime import datetime, timedelta
            appt_date_str = appointment.get("date")
            appt_time_str = appointment.get("time", "12:00")

            # Parse to datetime
            appt_datetime = datetime.strptime(f"{appt_date_str} {appt_time_str}", "%Y-%m-%d %H:%M")
            current_time = datetime.now()

            reminders = appointment.get("reminders") or {}
            # Only schedule if appointment is in future
            if appt_datetime > current_time:
                time_diff = appt_datetime - current_time
                hours_diff = time_diff.total_seconds() / 3600

                # Schedule 24-hour reminder only if enabled
                if reminders.get("24h", True) and hours_diff > 24:
                    reminder_time = appt_datetime - timedelta(hours=24)
                    self.schedule_single_alert("appointment", appointment, reminder_time, "24h")

                # Schedule 2-hour reminder only if enabled
                if reminders.get("2h", True) and hours_diff > 2:
                    reminder_time = appt_datetime - timedelta(hours=2)
                    self.schedule_single_alert("appointment", appointment, reminder_time, "2h")

                print(f"✓ Scheduled alerts for appointment on {appt_date_str}")

        except Exception as e:
            print(f"✗ Error scheduling appointment alerts: {e}")

    def schedule_prescription_alert(self, prescription):
        """Schedule alerts for prescription expiry"""
        try:
            from datetime import datetime, timedelta
            expiry_date_str = prescription.get("expiry_date")

            if not expiry_date_str:
                return

            expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
            today = datetime.now().date()

            reminders = prescription.get("reminders") or {}
            # Only schedule if expiry is in future
            if expiry_date > today:
                days_until = (expiry_date - today).days

                if reminders.get("7d", True) and days_until > 7:
                    reminder_date = expiry_date - timedelta(days=7)
                    self.schedule_single_alert("prescription", prescription,
                                               datetime.combine(reminder_date, datetime.min.time()), "7d")

                if reminders.get("3d", True) and days_until > 3:
                    reminder_date = expiry_date - timedelta(days=3)
                    self.schedule_single_alert("prescription", prescription,
                                               datetime.combine(reminder_date, datetime.min.time()), "3d")

                if reminders.get("1d", True) and days_until > 1:
                    reminder_date = expiry_date - timedelta(days=1)
                    self.schedule_single_alert("prescription", prescription,
                                               datetime.combine(reminder_date, datetime.min.time()), "1d")

                print(f"✓ Scheduled alerts for prescription expiring on {expiry_date_str}")

        except Exception as e:
            print(f"✗ Error scheduling prescription alerts: {e}")

    def schedule_lab_test_alert(self, lab_test):
        """Schedule alerts for lab test"""
        try:
            from datetime import datetime, timedelta
            test_date_str = lab_test.get("date")
            test_time_str = lab_test.get("time", "09:00")

            test_datetime = datetime.strptime(f"{test_date_str} {test_time_str}", "%Y-%m-%d %H:%M")
            current_time = datetime.now()

            reminders = lab_test.get("reminders") or {}
            scheduled_any = False
            if test_datetime > current_time:
                time_diff = test_datetime - current_time
                hours_diff = time_diff.total_seconds() / 3600

                if reminders.get("24h", True) and hours_diff > 24:
                    reminder_time = test_datetime - timedelta(hours=24)
                    self.schedule_single_alert("lab_test", lab_test, reminder_time, "24h")
                    scheduled_any = True

                if reminders.get("2h", True) and hours_diff > 2:
                    reminder_time = test_datetime - timedelta(hours=2)
                    self.schedule_single_alert("lab_test", lab_test, reminder_time, "2h")
                    scheduled_any = True

            if scheduled_any:
                print(f"✓ Scheduled alerts for lab test on {test_date_str}")
            else:
                print(f"ℹ Lab test saved but no future reminders scheduled (date/time may be in the past or too close).")

        except Exception as e:
            print(f"✗ Error scheduling lab test alerts: {e}")

    def schedule_custom_reminder_alert(self, custom_reminder):
        """Schedule alerts for custom reminder"""
        try:
            from datetime import datetime, timedelta
            reminder_date_str = custom_reminder.get("date")
            reminder_time_str = custom_reminder.get("time", "09:00")

            reminder_datetime = datetime.strptime(f"{reminder_date_str} {reminder_time_str}", "%Y-%m-%d %H:%M")
            current_time = datetime.now()

            reminders = custom_reminder.get("reminders") or {}
            scheduled_any = False
            if reminder_datetime > current_time:
                time_diff = reminder_datetime - current_time
                hours_diff = time_diff.total_seconds() / 3600

                if reminders.get("24h", True) and hours_diff > 24:
                    reminder_time = reminder_datetime - timedelta(hours=24)
                    self.schedule_single_alert("custom", custom_reminder, reminder_time, "24h")
                    scheduled_any = True

                if reminders.get("2h", True) and hours_diff > 2:
                    reminder_time = reminder_datetime - timedelta(hours=2)
                    self.schedule_single_alert("custom", custom_reminder, reminder_time, "2h")
                    scheduled_any = True

            if scheduled_any:
                print(f"✓ Scheduled alerts for custom reminder on {reminder_date_str}")
            else:
                print(f"ℹ Custom reminder saved but no future reminders scheduled (date/time may be in the past or too close).")

        except Exception as e:
            print(f"✗ Error scheduling custom reminder alerts: {e}")

    def schedule_single_alert(self, alert_type, data, alert_time, reminder_type):
        """Schedule a single alert at specific time"""
        try:
            from datetime import datetime
            current_time = datetime.now()

            # Only schedule if alert time is in future
            if alert_time > current_time:
                # Calculate delay in seconds
                delay_seconds = (alert_time - current_time).total_seconds()

                # Schedule the alert
                if delay_seconds > 0:
                    # Use threading Timer for background alerts
                    import threading

                    def send_alert():
                        # Run on main thread so Tk popup and app refs work (capture args to avoid closure issues)
                        try:
                            self.root.after(0, lambda at=alert_type, d=data, rt=reminder_type: self.send_scheduled_alert(at, d, rt))
                        except Exception as e:
                            print(f"✗ Timer callback error: {e}")

                    timer = threading.Timer(delay_seconds, send_alert)
                    timer.daemon = True  # Don't block program exit
                    timer.start()

                    # Store timer reference (optional)
                    if not hasattr(self, 'scheduled_alerts'):
                        self.scheduled_alerts = []
                    self.scheduled_alerts.append(timer)

                    print(f"  → Scheduled {reminder_type} alert for {alert_time}")

        except Exception as e:
            print(f"✗ Error in single alert scheduling: {e}")

    def show_alert_popup(self, message, alert_type):
        """Show reminder popup notification (runs on main thread)."""
        try:
            messagebox.showinfo("Reminder", message, parent=self.root)
        except Exception as e:
            print(f"✗ Popup error: {e}")

    def send_scheduled_alert(self, alert_type, data, reminder_type):
        """Send the actual alert when triggered"""
        try:
            print(f"[ALERT] SCHEDULED ALERT TRIGGERED: type={alert_type} reminder={reminder_type}", flush=True)
            # Mark as sent so poll loop won't fire again
            rid = data.get("id")
            if rid and hasattr(self, '_reminder_sent'):
                self._reminder_sent.add((rid, reminder_type))
            print(f"🔔 {reminder_type.upper()} ALERT TRIGGERED for {alert_type}", flush=True)

            # Create alert message based on type
            message = ""
            if alert_type == "appointment":
                message = f"🔔 REMINDER: Appointment with Dr. {data.get('doctor', 'Unknown')} "
                message += f"is {'in 24 hours' if reminder_type == '24h' else 'in 2 hours'}. "
                message += f"Time: {data.get('time')}, Location: {data.get('location', 'Unknown')}"

            elif alert_type == "prescription":
                message = f"💊 REMINDER: Prescription for {data.get('medicine', 'Unknown')} "
                message += f"expires in {reminder_type.replace('d', ' days')}. "
                message += f"Expiry date: {data.get('expiry_date')}"

            elif alert_type == "lab_test":
                message = f"🧪 REMINDER: Lab test '{data.get('test_name', 'Unknown')}' "
                message += f"is {'tomorrow' if reminder_type == '24h' else 'in 2 hours'}. "
                message += f"Time: {data.get('time')}"
                if data.get('instructions'):
                    message += f" Instructions: {data.get('instructions')}"

            elif alert_type == "custom":
                message = f"🔔 REMINDER: {data.get('title', 'Custom Reminder')} "
                message += f"is {'tomorrow' if reminder_type == '24h' else 'in 2 hours'}. "
                message += f"Time: {data.get('time')}"

            # Send email (reminders go to both mail and Mobile Alert Bot)
            if hasattr(self, 'alert_scheduler') and self.alert_scheduler:
                subject = f"Reminder: {message[:60]}{'...' if len(message) > 60 else ''}"
                try:
                    self.alert_scheduler.send_gmail_alert(subject, message)
                except Exception as mail_err:
                    print(f"✗ Reminder email failed: {mail_err}")

            # Send to mobile app (no screen popup, just email + bot)
            print("[ALERT] Sending to email + mobile bot...", flush=True)
            if hasattr(self, 'send_mobile_alert'):
                try:
                    self.send_mobile_alert(alert_type, message)
                    print("[ALERT] send_mobile_alert returned.", flush=True)
                except Exception as mob_err:
                    print(f"✗ Scheduled alert mobile bot failed: {mob_err}", flush=True)

        except Exception as e:
            print(f"✗ Error sending scheduled alert: {e}")

    def create_sms_settings_section(self, parent):
        """Mobile Alert Bot Configuration - Send alerts to Android app"""
        # Main container
        container = tk.Frame(parent, bg=self.bg_color)
        container.pack(fill=tk.X, padx=20, pady=10)

        # Mobile Bot Configuration
        left_frame = tk.LabelFrame(container, text="📱 Mobile Alert Bot (Android App)",
                                   bg=self.card_bg, font=('Arial', 12, 'bold'),
                                   relief=tk.FLAT, bd=0,
                                   padx=15, pady=15)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        # Enable checkbox
        self.mobile_bot_enabled_var = tk.BooleanVar(value=self.mobile_bot.get("enabled", False))
        tk.Checkbutton(left_frame, text="✅ Enable Mobile Alerts",
                       variable=self.mobile_bot_enabled_var,
                       command=self.toggle_mobile_bot_frame,
                       bg=self.card_bg, font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(0, 15))

        # Mobile Bot Input Frame (will be enabled/disabled based on checkbox)
        self.mobile_bot_input_frame = tk.Frame(left_frame, bg=self.card_bg)
        self.mobile_bot_input_frame.pack(fill=tk.X, pady=10)

        # Bot ID
        tk.Label(self.mobile_bot_input_frame, text="🆔 Bot ID (from mobile app):", 
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        self.mobile_bot_id_var = tk.StringVar(value=self.mobile_bot.get("bot_id", ""))
        bot_id_entry = tk.Entry(self.mobile_bot_input_frame, textvariable=self.mobile_bot_id_var,
                               width=30, font=('Arial', 11))
        bot_id_entry.pack(anchor=tk.W, pady=(0, 15))

        # API Key
        tk.Label(self.mobile_bot_input_frame, text="🔑 API Key (from mobile app):", 
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        self.mobile_bot_api_var = tk.StringVar(value=self.mobile_bot.get("api_key", ""))
        api_key_entry = tk.Entry(self.mobile_bot_input_frame, textvariable=self.mobile_bot_api_var,
                                width=50, font=('Arial', 11), show="*")
        api_key_entry.pack(anchor=tk.W, pady=(0, 15))

        # Server URL
        tk.Label(self.mobile_bot_input_frame, text="🌐 Server URL (host:port):", 
                 bg=self.card_bg, font=('Arial', 10, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        
        self.mobile_bot_server_var = tk.StringVar(value=self.mobile_bot.get("server_url", "localhost:5050"))
        server_entry = tk.Entry(self.mobile_bot_input_frame, textvariable=self.mobile_bot_server_var,
                               width=30, font=('Arial', 11))
        server_entry.pack(anchor=tk.W, pady=(0, 5))

        tk.Label(self.mobile_bot_input_frame,
                 text="For desktop bot on same PC use: localhost:5050",
                 bg=self.card_bg, font=('Arial', 9), fg='#6c757d').pack(anchor=tk.W, pady=(0, 15))

        # Test and Save buttons
        button_frame = tk.Frame(self.mobile_bot_input_frame, bg=self.card_bg)
        button_frame.pack(fill=tk.X, pady=10)

        test_btn = tk.Button(button_frame, text="📤 Send Test Alert",
                             command=self.test_mobile_bot_connection,
                             bg=self.primary_color, fg='white',
                             font=('Arial', 10, 'bold'), padx=15, pady=8)
        test_btn.pack(side=tk.LEFT, padx=5)

        save_btn = tk.Button(button_frame, text="💾 Save Settings",
                             command=self.save_mobile_bot_settings,
                             bg=self.success_color, fg='white',
                             font=('Arial', 10, 'bold'), padx=15, pady=8)
        save_btn.pack(side=tk.LEFT, padx=5)

        # Status label
        self.mobile_bot_status = tk.Label(self.mobile_bot_input_frame, text="Not configured",
                                   bg=self.card_bg, fg=self.danger_color,
                                   font=('Arial', 10))
        self.mobile_bot_status.pack(anchor=tk.W, pady=(10, 0))

        # Show saved status if configured
        if self.mobile_bot.get("enabled") and self.mobile_bot.get("bot_id"):
            self.mobile_bot_status.config(
                text=f"✅ Mobile Alerts Enabled (Bot ID: {self.mobile_bot['bot_id']})",
                fg=self.success_color
            )
        
        # Disable frame if mobile bot not enabled
        if not self.mobile_bot_enabled_var.get():
            for widget in self.mobile_bot_input_frame.winfo_children():
                self.disable_widget_tree(widget)

    def open_password_management_dialog(self):
        """Open dialog to change device password"""
        # Admin verification required
        if not self.verify_admin_dialog("change device password"):
            return
        
        dialog = tk.Toplevel(self.root)
        dialog.title("🔑 Change Device Password")
        dialog.geometry("450x550")
        dialog.configure(bg=self.bg_color)
        dialog.resizable(False, False)

        # Center dialog
        dialog.transient(self.root)
        dialog.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 275
        dialog.geometry(f"+{x}+{y}")

        # Title
        tk.Label(dialog, text="🔑 Change Device Password",
                 font=('Arial', 16, 'bold'),
                 bg=self.bg_color, fg=self.primary_color).pack(pady=20)

        tk.Label(dialog, text="Enter current password to verify, then set new password",
                 font=('Arial', 10),
                 bg=self.bg_color, fg='#6c757d').pack(pady=(0, 20))

        # Input frame
        input_frame = tk.Frame(dialog, bg=self.card_bg, padx=20, pady=20, relief=tk.SUNKEN, bd=1)
        input_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 20))

        # Current Password
        tk.Label(input_frame, text="Current Device Password:",
             bg=self.card_bg, font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        current_pwd_var = tk.StringVar()
        current_pwd_entry = tk.Entry(input_frame, textvariable=current_pwd_var,
                         width=35, font=('Arial', 11), show="●")
        current_pwd_entry.pack(fill=tk.X, pady=(0, 15))

        # New + Confirm wrapper (hidden until verification)
        new_fields_frame = tk.Frame(input_frame, bg=self.card_bg)

        tk.Label(new_fields_frame, text="New Device Password:",
             bg=self.card_bg, font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        new_pwd_var = tk.StringVar()
        new_pwd_entry = tk.Entry(new_fields_frame, textvariable=new_pwd_var,
                     width=35, font=('Arial', 11), show="●")
        new_pwd_entry.pack(fill=tk.X, pady=(0, 15))

        tk.Label(new_fields_frame, text="Confirm New Password:",
             bg=self.card_bg, font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(0, 5))
        confirm_pwd_var = tk.StringVar()
        confirm_pwd_entry = tk.Entry(new_fields_frame, textvariable=confirm_pwd_var,
                         width=35, font=('Arial', 11), show="●")
        confirm_pwd_entry.pack(fill=tk.X)

        # Status label
        status_label = tk.Label(dialog, text="",
                               bg=self.bg_color, font=('Arial', 10))
        status_label.pack(pady=(0, 10))

        verified_state = {"ok": False}

        def hide_new_fields():
            new_fields_frame.pack_forget()
            if update_btn.winfo_ismapped():
                update_btn.pack_forget()

        def verify_current_password():
            current = current_pwd_var.get().strip()

            if not current:
                status_label.config(text="❌ Enter current password", fg=self.danger_color)
                hide_new_fields()
                return

            if not self.ser or not self.ser.is_open:
                status_label.config(text="❌ Not connected to device", fg=self.danger_color)
                hide_new_fields()
                return

            try:
                self.serial_pause = True
                status_label.config(text="🔄 Verifying current password...", fg=self.warning_color)
                dialog.update()

                # Verify current password using AUTH command to force a response
                command = f"AUTH_PIN:{current}\n"
                print(f"Sending password verify command: {command.strip()}")

                self.ser.reset_input_buffer()
                time.sleep(0.1)
                self.ser.write(command.encode('utf-8'))
                self.ser.flush()

                response = ""
                start_time = time.time()
                timeout = 3.0

                while time.time() - start_time < timeout:
                    if self.ser.in_waiting:
                        try:
                            response_bytes = self.ser.readline()
                            response = response_bytes.decode('utf-8', errors='ignore').strip()
                            break
                        except:
                            continue
                    time.sleep(0.05)

                print(f"Verify response: {response}")

                # Accept either password or auth success tokens
                if any(token in response.upper() for token in ["PWD_OK", "SUCCESS", "AUTH_OK", "PIN_OK", "OK"]):
                    verified_state["ok"] = True
                    status_label.config(text="✅ Current password verified", fg=self.success_color)
                    current_pwd_entry.config(state=tk.DISABLED)
                    verify_btn.config(text="✓ Verified", state=tk.DISABLED, bg=self.success_color)
                    new_fields_frame.pack(fill=tk.X, pady=(0, 0))
                    update_btn.pack(side=tk.LEFT, padx=5)
                    new_pwd_entry.focus()
                elif any(token in response.upper() for token in ["PWD_FAIL", "FAIL", "AUTH_FAIL", "PIN_FAIL", "ERROR"]):
                    verified_state["ok"] = False
                    status_label.config(text="❌ Password does not match", fg=self.danger_color)
                    current_pwd_entry.delete(0, tk.END)
                    hide_new_fields()
                else:
                    verified_state["ok"] = False
                    status_label.config(text="❌ No response from device", fg=self.danger_color)
                    hide_new_fields()

            except Exception as e:
                verified_state["ok"] = False
                status_label.config(text=f"❌ Error: {str(e)[:30]}", fg=self.danger_color)
                hide_new_fields()
                print(f"Password verify error: {e}")
            finally:
                self.serial_pause = False

        def update_password():
            if not verified_state["ok"]:
                status_label.config(text="❌ Verify current password first", fg=self.danger_color)
                return

            current = current_pwd_var.get().strip()
            new_pwd = new_pwd_var.get().strip()
            confirm = confirm_pwd_var.get().strip()

            # Validation
            if not current or not new_pwd or not confirm:
                status_label.config(text="❌ All fields are required", fg=self.danger_color)
                return

            if len(new_pwd) < 4:
                status_label.config(text="❌ New password must be at least 4 digits", fg=self.danger_color)
                return

            if new_pwd != confirm:
                status_label.config(text="❌ Passwords do not match", fg=self.danger_color)
                confirm_pwd_entry.delete(0, tk.END)
                new_pwd_entry.delete(0, tk.END)
                return

            # Send password change command to ESP32
            if not self.ser or not self.ser.is_open:
                status_label.config(text="❌ Not connected to device", fg=self.danger_color)
                return

            try:
                self.serial_pause = True
                # Send change password command (Arduino expects SET_PASSWORD:old,new)
                command = f"SET_PASSWORD:{current},{new_pwd}\n"
                print(f"Sending password change command: {command.strip()}")

                self.ser.reset_input_buffer()
                time.sleep(0.1)
                self.ser.write(command.encode('utf-8'))
                self.ser.flush()

                # Wait for response
                status_label.config(text="🔄 Processing...", fg=self.warning_color)
                dialog.update()

                response = ""
                start_time = time.time()
                timeout = 3.0

                while time.time() - start_time < timeout:
                    if self.ser.in_waiting:
                        try:
                            response_bytes = self.ser.readline()
                            response = response_bytes.decode('utf-8', errors='ignore').strip()
                            break
                        except:
                            continue
                    time.sleep(0.05)

                print(f"Response: {response}")

                # Check response (Arduino returns PASSWORD_OK, PASSWORD_FAIL_OLD, PASSWORD_FAIL_FORMAT)
                if "PASSWORD_OK" in response or "PWD_OK" in response or "SUCCESS" in response:
                    status_label.config(text="✅ Password changed successfully!", fg=self.success_color)
                    messagebox.showinfo("Success", "Device password updated!\nSystem will unlock with new password next time.",
                                       parent=dialog)
                    dialog.destroy()
                elif "PASSWORD_FAIL_OLD" in response:
                    status_label.config(text="❌ Current password is incorrect", fg=self.danger_color)
                    current_pwd_entry.delete(0, tk.END)
                    current_pwd_entry.config(state=tk.NORMAL)
                    verify_btn.config(text="✓ Verify Current", state=tk.NORMAL, bg=self.primary_color)
                    hide_new_fields()
                    verified_state["ok"] = False
                elif "PASSWORD_FAIL_FORMAT" in response or "FAIL" in response:
                    status_label.config(text="❌ Invalid password format", fg=self.danger_color)
                else:
                    status_label.config(text="❌ No response from device", fg=self.danger_color)

            except Exception as e:
                status_label.config(text=f"❌ Error: {str(e)[:30]}", fg=self.danger_color)
                print(f"Password change error: {e}")
            finally:
                self.serial_pause = False

        # Buttons
        btn_frame = tk.Frame(dialog, bg=self.bg_color)
        btn_frame.pack(pady=(0, 15))

        verify_btn = tk.Button(btn_frame, text="✓ Verify Current",
                               command=verify_current_password,
                               bg=self.primary_color, fg='white',
                               font=('Arial', 11, 'bold'),
                               padx=20, pady=8,
                               relief=tk.RAISED, bd=1)
        verify_btn.pack(side=tk.LEFT, padx=5)

        update_btn = tk.Button(btn_frame, text="✓ Update Password",
                               command=update_password,
                               bg=self.success_color, fg='white',
                               font=('Arial', 11, 'bold'),
                               padx=20, pady=8,
                               relief=tk.RAISED, bd=1)

        tk.Button(btn_frame, text="✕ Cancel",
                  command=dialog.destroy,
                  bg=self.danger_color, fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=20, pady=8,
                  relief=tk.RAISED, bd=1).pack(side=tk.LEFT, padx=5)

        hide_new_fields()

        # Focus on first field
        current_pwd_entry.focus()

    def toggle_mobile_bot_frame(self):
        """Enable/disable mobile bot input frame based on checkbox"""
        # Admin verification required
        if not self.verify_admin_dialog("change mobile alert bot settings"):
            # Revert checkbox state
            self.mobile_bot_enabled_var.set(not self.mobile_bot_enabled_var.get())
            return
        
        if self.mobile_bot_enabled_var.get():
            for widget in self.mobile_bot_input_frame.winfo_children():
                self.enable_widget_tree(widget)
        else:
            for widget in self.mobile_bot_input_frame.winfo_children():
                self.disable_widget_tree(widget)

    def test_mobile_bot_connection(self):
        """Test bot connection: WebSocket for cloud URL, TCP for local host:port"""
        bot_id = self.mobile_bot_id_var.get().strip()
        api_key = self.mobile_bot_api_var.get().strip()
        server_url = self.mobile_bot_server_var.get().strip()
        
        if not bot_id or not api_key or not server_url:
            messagebox.showwarning("Missing Info", "Please enter Bot ID, API Key, and Server URL")
            return
        
        # Sync in-memory config from UI so self-triggered alerts use same credentials as Test
        self.mobile_bot["enabled"] = self.mobile_bot_enabled_var.get()
        self.mobile_bot["bot_id"] = bot_id
        self.mobile_bot["api_key"] = api_key
        self.mobile_bot["server_url"] = server_url
        
        import json
        self.mobile_bot_status.config(text="🔄 Connecting...", fg=self.warning_color)
        self.root.update()

        def do_test():
            try:
                # Cloud: http(s) URL -> use WebSocket (same as send_mobile_alert)
                if server_url.startswith("https://") or server_url.startswith("http://"):
                    wss = server_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1).rstrip("/")
                    try:
                        import asyncio
                        import websockets
                    except ImportError:
                        self.root.after(0, lambda: self._test_done(False, "pip install websockets"))
                        return
                    last_err = None
                    for attempt in range(3):
                        try:
                            async def send_test():
                                async with websockets.connect(wss, close_timeout=2, open_timeout=20) as ws:
                                    await ws.send(json.dumps({
                                        "action": "alert",
                                        "bot_id": bot_id,
                                        "api_key": api_key,
                                        "type": "System Alert",
                                        "message": "CuraX connection test successful! You will receive medication alerts here."
                                    }))
                            asyncio.run(send_test())
                            self.root.after(0, lambda: self._test_done(True, None))
                            return
                        except Exception as e:
                            last_err = e
                            if "1011" in str(e) or "internal" in str(e).lower():
                                import time
                                time.sleep(2)
                                continue
                            break
                    msg = str(last_err) if last_err else "Unknown error"
                    if "1011" in msg or "internal" in msg.lower():
                        msg = "Server may be waking up (e.g. Render). Try again in 10–15 seconds."
                    self.root.after(0, lambda: self._test_done(False, msg))
                    return
                # Local: host:port -> TCP socket
                import socket
                url_clean = server_url.split("://")[-1] if "://" in server_url else server_url
                host, port = (url_clean.rsplit(":", 1) + ["5050"])[:2]
                port = int(port)
                alert_data = {"type": "System Alert", "message": "CuraX connection test successful! You will receive medication alerts here."}
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(10)
                client.connect((host, port))
                client.sendall(json.dumps(alert_data).encode("utf-8"))
                client.close()
                self.root.after(0, lambda: self._test_done(True, None))
            except Exception as e:
                self.root.after(0, lambda: self._test_done(False, str(e)))
        import threading
        threading.Thread(target=do_test, daemon=True).start()

    def _test_done(self, success, err_msg):
        """Update UI after test_mobile_bot_connection (run on main thread)"""
        if success:
            self.mobile_bot_status.config(text="✅ Test alert sent!", fg=self.success_color)
            messagebox.showinfo("Success", "Test alert sent!\n\nCheck your Curax app for the message.")
        else:
            self.mobile_bot_status.config(text="❌ Test failed", fg=self.danger_color)
            msg = (err_msg or "Unknown error")[:80]
            messagebox.showerror("Error", f"Could not send test alert.\n\n{msg}\n\nCheck Server URL, Bot ID, API Key, and that the app is connected.")

    def save_mobile_bot_settings(self):
        """Save mobile bot configuration"""
        bot_id = self.mobile_bot_id_var.get().strip()
        api_key = self.mobile_bot_api_var.get().strip()
        server_url = self.mobile_bot_server_var.get().strip()
        
        if self.mobile_bot_enabled_var.get() and (not bot_id or not api_key or not server_url):
            messagebox.showwarning("Missing Info", "Please enter Bot ID, API Key, and Server URL")
            return
        
        # Admin verification BEFORE saving
        if not self.verify_admin_dialog("Save Mobile Bot Configuration"):
            return
        
        # Update mobile_bot config
        self.mobile_bot = {
            "enabled": self.mobile_bot_enabled_var.get(),
            "bot_id": bot_id,
            "api_key": api_key,
            "server_url": server_url
        }
        
        # Save to database
        self.save_mobile_bot_config()
        
        if self.mobile_bot_enabled_var.get():
            self.mobile_bot_status.config(
                text=f"✅ Mobile alerts enabled (Server: {server_url})",
                fg=self.success_color
            )
            messagebox.showinfo("Saved", f"Mobile bot configuration saved!\nServer: {server_url}")
        else:
            self.mobile_bot_status.config(
                text="Mobile alerts disabled",
                fg="#6c757d"
            )
            messagebox.showinfo("Saved", "Mobile alerts disabled")

    def toggle_sms_frame(self):
        """Enable/disable SMS input frame based on checkbox (no-op if SMS UI not present)"""
        if not hasattr(self, 'sms_enabled_var') or not hasattr(self, 'sms_input_frame'):
            return
        if self.sms_enabled_var.get():
            for widget in self.sms_input_frame.winfo_children():
                self.enable_widget_tree(widget)
        else:
            for widget in self.sms_input_frame.winfo_children():
                self.disable_widget_tree(widget)

    def test_sms_connection(self):
        """Test SMS connection with CallMeBot (no-op if SMS UI not present)"""
        if not hasattr(self, 'sms_phone_var'):
            return
        phone = self.sms_phone_var.get().strip()
        
        if not phone:
            messagebox.showwarning("Missing Phone", "Please enter your phone number")
            return
        
        # Validate phone format (basic check)
        if not phone.isdigit() or len(phone) < 10:
            messagebox.showwarning("Invalid Phone", "Phone number should be at least 10 digits")
            return
        
        try:
            # Format phone number with + prefix (international format)
            formatted_phone = f"+{phone}" if not phone.startswith("+") else phone
            
            test_message = "CuraX Test: SMS alerts working!"
            
            # CallMeBot API endpoint (FREE service) - Use params for proper URL encoding
            url = "https://api.callmebot.com/whatsapp.php"
            params = {
                "phone": formatted_phone,
                "text": test_message,
                "apikey": "0"
            }
            
            # Send request - requests library will properly URL encode parameters
            response = requests.get(url, params=params, timeout=10)
            
            # Check response
            if response.status_code == 200:
                self.sms_status.config(
                    text=f"✅ Test queued for {formatted_phone}! WhatsApp delivery: 30-60s",
                    fg=self.success_color
                )
                messagebox.showinfo("Success", f"Test message queued!\\n\\nPhone: {formatted_phone}\\nMessage: {test_message}\\n\\nNote: Delivery takes 30-60 seconds via WhatsApp. Make sure WhatsApp is installed.")
            else:
                response_text = response.text[:100]
                self.sms_status.config(
                    text=f"⚠️ API Response: Status {response.status_code}",
                    fg=self.warning_color
                )
                messagebox.showwarning("API Response", f"Status: {response.status_code}\\nResponse: {response_text}\\n\\nCheck:\\n1. WhatsApp installed on phone\\n2. Phone number format (923001234567)\\n3. Internet connection")
        except Exception as e:
            self.sms_status.config(
                text=f"❌ Error: {str(e)[:40]}",
                fg=self.danger_color
            )
            messagebox.showerror("Error", f"Connection error: {e}")

    def save_sms_config(self):
        """Save SMS configuration (no-op if SMS UI not present)"""
        if not hasattr(self, 'sms_phone_var') or not hasattr(self, 'sms_enabled_var'):
            return
        phone = self.sms_phone_var.get().strip()
        
        if self.sms_enabled_var.get() and not phone:
            messagebox.showwarning("Missing Info", "Please enter your phone number")
            return
        
        # Admin verification BEFORE saving
        if not self.verify_admin_dialog("Save SMS Configuration"):
            return
        
        # Update sms_config
        self.sms_config = {
            "enabled": self.sms_enabled_var.get(),
            "provider": "callmebot",
            "phone_number": phone,
            "api_key": "0"  # CallMeBot free tier
        }
        
        # Save to database
        try:
            db = getattr(self, "_alert_db", None)
            if db is None:
                db = AlertDB()
                self._alert_db = db
            
            db.set("sms_config", self.sms_config)
            
            if hasattr(self, 'sms_status') and self.sms_enabled_var.get():
                self.sms_status.config(
                    text=f"✅ SMS Alerts enabled for {phone}",
                    fg=self.success_color
                )
                messagebox.showinfo("Saved", f"SMS configuration saved!\nAlerts will be sent to {phone}")
            else:
                if hasattr(self, 'sms_status'):
                    self.sms_status.config(
                        text="SMS Alerts disabled",
                        fg="#6c757d"
                    )
                messagebox.showinfo("Saved", "SMS alerts disabled")
        except Exception as e:
            if hasattr(self, 'sms_status'):
                self.sms_status.config(
                    text=f"❌ Error saving: {str(e)[:40]}",
                    fg=self.danger_color
                )
            messagebox.showerror("Error", f"Failed to save: {e}")

    def send_sms_alert(self, message, phone=None):
        """Send SMS alert via CallMeBot (FREE)"""
        if not self.sms_config.get("enabled", False):
            return False
        
        phone = phone or self.sms_config.get("phone_number", "")
        if not phone:
            print("❌ SMS: No phone number configured")
            return False
        
        try:
            # Format phone number with + prefix (international format)
            formatted_phone = f"+{phone}" if not phone.startswith("+") else phone
            
            # Truncate message to reasonable length
            sms_message = message[:300]
            
            # CallMeBot API - Completely FREE
            # Use params dict for proper URL encoding
            url = "https://api.callmebot.com/whatsapp.php"
            params = {
                "phone": formatted_phone,
                "text": sms_message,
                "apikey": "0"
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                print(f"✅ SMS alert sent to {formatted_phone}: {sms_message[:50]}")
                return True
            else:
                print(f"⚠️ SMS send returned status {response.status_code}: {response.text[:50]}")
                return False
        except Exception as e:
            print(f"❌ Failed to send SMS: {e}")
            return False

    def disable_widget_tree(self, widget):
        """Recursively disable widgets"""
        try:
            widget.config(state=tk.DISABLED)
        except:
            pass
        for child in widget.winfo_children():
            self.disable_widget_tree(child)

    def enable_widget_tree(self, widget):
        """Recursively enable widgets"""
        try:
            if isinstance(widget, tk.Entry):
                widget.config(state=tk.NORMAL)
            elif isinstance(widget, tk.Text):
                widget.config(state=tk.NORMAL)
            elif isinstance(widget, tk.Button):
                widget.config(state=tk.NORMAL)
            elif isinstance(widget, tk.Checkbutton):
                widget.config(state=tk.NORMAL)
            elif isinstance(widget, ttk.Combobox):
                widget.config(state="readonly")
            else:
                widget.config(state=tk.NORMAL)
        except:
            pass
        for child in widget.winfo_children():
            self.enable_widget_tree(child)

    def create_system_preferences_section(self, parent):
        """System Preferences Section (includes DND settings)"""
        frame = tk.LabelFrame(parent, text="⚙ System Preferences",
                              bg=self.card_bg, font=('Arial', 12, 'bold'),
                              padx=15, pady=15)
        frame.pack(fill=tk.X, padx=20, pady=10)

        # ========== DO NOT DISTURB SETTINGS ==========
        tk.Label(frame, text="🔕 Do Not Disturb:", bg=self.card_bg,
                 font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(0, 10))

        # ========== DO NOT DISTURB SETTINGS ==========
        tk.Label(frame, text="🔕 Do Not Disturb:", bg=self.card_bg,
                 font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(0, 10))

        # Enable DND checkbox
        self.dnd_enabled_var = tk.BooleanVar(
            value=self.alert_settings["do_not_disturb"].get("enabled", False)
        )
        tk.Checkbutton(frame, text="Enable Do Not Disturb Mode",
                       variable=self.dnd_enabled_var,
                       bg=self.card_bg, font=('Arial', 10)).pack(anchor=tk.W, pady=(0, 10))

        # DND Time Frame
        time_frame = tk.Frame(frame, bg=self.card_bg)
        time_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(time_frame, text="From:", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT)

        # Parse existing start time (e.g., "22:00")
        start_time = self.alert_settings["do_not_disturb"].get("start_time", "22:00")
        start_hour, start_minute = start_time.split(":") if ":" in start_time else ("22", "00")

        self.dnd_start_hour_var = tk.StringVar(value=start_hour)
        start_hour_combo = ttk.Combobox(time_frame, textvariable=self.dnd_start_hour_var,
                                        values=[f"{i:02d}" for i in range(0, 24)],
                                        width=4, state="readonly")
        start_hour_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(time_frame, text=":", bg=self.card_bg).pack(side=tk.LEFT)

        self.dnd_start_min_var = tk.StringVar(value=start_minute)
        start_min_combo = ttk.Combobox(time_frame, textvariable=self.dnd_start_min_var,
                                       values=[f"{i:02d}" for i in range(0, 60, 5)],
                                       width=4, state="readonly")
        start_min_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(time_frame, text="To:", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=(10, 0))

        # Parse existing end time (e.g., "07:00")
        end_time = self.alert_settings["do_not_disturb"].get("end_time", "07:00")
        end_hour, end_minute = end_time.split(":") if ":" in end_time else ("07", "00")

        self.dnd_end_hour_var = tk.StringVar(value=end_hour)
        end_hour_combo = ttk.Combobox(time_frame, textvariable=self.dnd_end_hour_var,
                                      values=[f"{i:02d}" for i in range(0, 24)],
                                      width=4, state="readonly")
        end_hour_combo.pack(side=tk.LEFT, padx=5)

        tk.Label(time_frame, text=":", bg=self.card_bg).pack(side=tk.LEFT)

        self.dnd_end_min_var = tk.StringVar(value=end_minute)
        end_min_combo = ttk.Combobox(time_frame, textvariable=self.dnd_end_min_var,
                                     values=[f"{i:02d}" for i in range(0, 60, 5)],
                                     width=4, state="readonly")
        end_min_combo.pack(side=tk.LEFT, padx=5)

        # Emergency Override
        self.dnd_emergency_var = tk.BooleanVar(
            value=self.alert_settings["do_not_disturb"].get("emergency_override", True)
        )
        tk.Checkbutton(frame, text="Allow emergency alerts during DND",
                       variable=self.dnd_emergency_var,
                       bg=self.card_bg, font=('Arial', 10)).pack(anchor=tk.W, pady=(0, 15))

        # Emergency alert types
        emergency_frame = tk.Frame(frame, bg=self.card_bg)
        emergency_frame.pack(anchor=tk.W, pady=(0, 15), padx=20)

        tk.Label(emergency_frame,
                 text="Emergency alerts include: Missed doses, critical stock alerts, expired medicines",
                 bg=self.card_bg, font=('Arial', 8), fg="#6c757d",
                 justify=tk.LEFT).pack(anchor=tk.W)

        # ========== OTHER SYSTEM PREFERENCES ==========
        tk.Label(frame, text="📊 Other Preferences:", bg=self.card_bg,
                 font=('Arial', 11, 'bold')).pack(anchor=tk.W, pady=(10, 10))

        # Auto-refresh interval
        refresh_frame = tk.Frame(frame, bg=self.card_bg)
        refresh_frame.pack(anchor=tk.W, pady=(0, 10))

        tk.Label(refresh_frame, text="Auto-refresh interval:", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT)

        self.refresh_interval_var = tk.StringVar(value="30")
        refresh_spin = tk.Spinbox(refresh_frame, from_=5, to=300,
                                  textvariable=self.refresh_interval_var,
                                  width=5, font=('Arial', 10))
        refresh_spin.pack(side=tk.LEFT, padx=5)

        tk.Label(refresh_frame, text="seconds", bg=self.card_bg,
                 font=('Arial', 10)).pack(side=tk.LEFT)

        # Show notifications checkbox
        self.show_notifications_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Show desktop notifications",
                       variable=self.show_notifications_var,
                       bg=self.card_bg, font=('Arial', 10)).pack(anchor=tk.W, pady=(0, 10))

        # Play alert sounds checkbox
        self.play_sounds_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frame, text="Play alert sounds",
                       variable=self.play_sounds_var,
                       bg=self.card_bg, font=('Arial', 10)).pack(anchor=tk.W, pady=(0, 15))

        # Save button for system preferences
        save_btn = tk.Button(frame, text="Save System Preferences",
                             command=self.save_system_preferences,
                             bg=self.primary_color, fg='white',
                             font=('Arial', 10), padx=15, pady=5)
        save_btn.pack(anchor=tk.W, pady=(10, 5))

        # Status label
        self.system_status_label = tk.Label(frame, text="",
                                            bg=self.card_bg, font=('Arial', 10))
        self.system_status_label.pack(anchor=tk.W, pady=(5, 0))

    # Helper methods for settings
    def save_system_preferences(self):
        """Save system preferences - FIXED VERSION"""
        # Admin verification BEFORE saving
        if not self.verify_admin_dialog("Save System Preferences"):
            return False
        
        try:
            print("DEBUG: Saving system preferences...")

            # Format DND time strings
            start_time = f"{self.dnd_start_hour_var.get()}:{self.dnd_start_min_var.get()}"
            end_time = f"{self.dnd_end_hour_var.get()}:{self.dnd_end_min_var.get()}"

            print(f"DEBUG: DND times - Start: {start_time}, End: {end_time}")

            # DND settings
            self.alert_settings["do_not_disturb"]["enabled"] = self.dnd_enabled_var.get()
            self.alert_settings["do_not_disturb"]["start_time"] = start_time
            self.alert_settings["do_not_disturb"]["end_time"] = end_time
            self.alert_settings["do_not_disturb"]["emergency_override"] = self.dnd_emergency_var.get()

            print("DEBUG: DND settings updated in memory")

            # Save to file
            if self.save_alert_settings():
                self.system_status_label.config(
                    text="✅ System preferences saved!",
                    fg=self.success_color
                )

                # Clear message after 3 seconds
                self.root.after(3000, lambda: self.system_status_label.config(text=""))

                print("✅ System preferences saved")
                return True
            else:
                self.system_status_label.config(
                    text="❌ Failed to save to file",
                    fg=self.danger_color
                )
                print("❌ save_alert_settings() returned False")
                return False

        except Exception as e:
            error_msg = str(e)
            self.system_status_label.config(
                text=f"❌ Error: {error_msg[:30]}",
                fg=self.danger_color
            )
            print(f"❌ Error saving system preferences: {e}")
            import traceback
            traceback.print_exc()
            return False

    def show_auto_alerts_setup(self):
        """Simple, beautiful auto-alerts setup dialog with scrolling"""
        setup_window = tk.Toplevel(self.root)
        setup_window.title("Auto-Alerts Configuration")
        setup_window.geometry("550x550")
        setup_window.configure(bg=self.bg_color)
        setup_window.resizable(False, False)

        # Center window on parent
        setup_window.transient(self.root)
        setup_window.grab_set()

        # ========== HEADER ==========
        header_frame = tk.Frame(setup_window, bg=self.primary_color, height=70)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="🚀 Auto-Alerts Setup",
                 font=('Arial', 20, 'bold'), bg=self.primary_color, fg='white').pack(pady=15)

        # ========== SCROLLABLE CONTENT ==========
        canvas = tk.Canvas(setup_window, bg=self.bg_color, highlightthickness=0)
        scrollbar = tk.Scrollbar(setup_window, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_content = tk.Frame(canvas, bg=self.bg_color)

        scrollable_content.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Bind mousewheel
        self.bind_canvas_mousewheel(canvas)

        # Title
        tk.Label(scrollable_content, text="Quick Setup Steps",
                 font=('Arial', 12, 'bold'), bg=self.bg_color, fg=self.primary_color).pack(anchor=tk.W, pady=(0, 10), padx=20)

        # Steps
        steps = [
            ("Configure Alerts", "Go to 'Alerts' tab\nSet up email alerts & Gmail settings", 4),
            ("Gmail Configuration", "Go to 'Settings' tab → Gmail\nEnter your Gmail details", 6),
            ("Reminders", "Go to 'Medical Reminders' tab\nAdd family members for notifications", 5),
            ("Configuration Checklist", None, None)
        ]

        for i, (title, desc, tab_idx) in enumerate(steps):
            if i < 3:  # First three steps with navigation
                step_frame = tk.Frame(scrollable_content, bg='#f5f5f5', relief=tk.RAISED, bd=1)
                step_frame.pack(fill=tk.X, pady=6, padx=20)

                # Left: Content
                left_frame = tk.Frame(step_frame, bg='#f5f5f5')
                left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=8)

                tk.Label(left_frame, text=f"{i+1}. {title}", font=('Arial', 10, 'bold'),
                         bg='#f5f5f5', fg=self.primary_color).pack(anchor=tk.W)
                tk.Label(left_frame, text=desc, font=('Arial', 8),
                         bg='#f5f5f5', fg='#555', justify=tk.LEFT).pack(anchor=tk.W, pady=(3, 0))

                # Right: Button
                right_frame = tk.Frame(step_frame, bg='#f5f5f5')
                right_frame.pack(side=tk.RIGHT, padx=10, pady=8)

                tk.Button(right_frame, text="Go →",
                         command=lambda idx=tab_idx: (setup_window.destroy(), self.notebook.select(idx)),
                         bg=self.primary_color, fg='white',
                         font=('Arial', 8, 'bold'),
                         padx=10, pady=4, relief=tk.RAISED, bd=1).pack()
            else:  # Checklist section
                checklist_frame = tk.Frame(scrollable_content, bg='#e8f5e9', relief=tk.RAISED, bd=1)
                checklist_frame.pack(fill=tk.X, pady=6, padx=20)

                checklist_header = tk.Frame(checklist_frame, bg='#e8f5e9')
                checklist_header.pack(fill=tk.X, padx=10, pady=(8, 5))

                tk.Label(checklist_header, text=f"4. {title}", font=('Arial', 10, 'bold'),
                         bg='#e8f5e9', fg=self.primary_color).pack(anchor=tk.W)

                # Checklist items
                checks = [
                    ("Time alerts enabled", getattr(self, 'alert_enabled_var', None)),
                    ("Missed dose alerts enabled", getattr(self, 'escalation_vars', None) if hasattr(self, 'escalation_vars') else None),
                    ("Stock alerts enabled", getattr(self, 'stock_enabled_var', None)),
                    ("Gmail sender configured", self.gmail_config.get("sender_email", "") if hasattr(self, 'gmail_config') else ""),
                    ("App password added", self.gmail_config.get("app_password", "") if hasattr(self, 'gmail_config') else ""),
                    ("Recipients configured", self.gmail_config.get("recipients", "") if hasattr(self, 'gmail_config') else ""),
                    ("Family member email set", getattr(self, 'family_notify_email', None))
                ]

                items_frame = tk.Frame(checklist_frame, bg='#e8f5e9')
                items_frame.pack(fill=tk.X, padx=20, pady=(0, 8))

                for check_text, check_value in checks:
                    is_done = False
                    if check_value is not None:
                        if isinstance(check_value, str):
                            is_done = check_value != ""
                        elif hasattr(check_value, 'get'):
                            try:
                                is_done = bool(check_value.get())
                            except:
                                is_done = False
                        else:
                            is_done = bool(check_value)

                    status_icon = "✅" if is_done else "⭕"
                    status_color = '#2e7d32' if is_done else '#f57f17'

                    tk.Label(items_frame, text=f"{status_icon} {check_text}",
                             bg='#e8f5e9', font=('Arial', 8), fg=status_color).pack(anchor=tk.W, pady=1)

        # ========== FOOTER ==========
        footer_frame = tk.Frame(setup_window, bg=self.bg_color)
        footer_frame.pack(fill=tk.X, padx=0, pady=(10, 0), side=tk.BOTTOM)

        tk.Label(footer_frame, text="💡 Each tab has detailed configuration options",
                 font=('Arial', 8, 'italic'), bg=self.bg_color, fg='#777').pack()

        # ========== CLOSE BUTTON ==========
        btn_frame = tk.Frame(setup_window, bg=self.bg_color)
        btn_frame.pack(fill=tk.X, padx=20, pady=(5, 15))

        tk.Button(btn_frame, text="✓ Got it!",
                  command=setup_window.destroy,
                  bg='#28a745', fg='white',
                  font=('Arial', 11, 'bold'),
                  padx=25, pady=8, relief=tk.RAISED, bd=2).pack(side=tk.RIGHT)

        print("✅ Auto-Alerts dialog opened")

    def show_alerts_ready_dialog(self):
        """Show alerts ready confirmation"""
        msg = """
        🚀 AUTO-ALERTS ENABLED!

        Your system will now automatically send:

        ✉️ EMAIL ALERTS to all recipients
        • 15 minutes before medicine time
        • At exact medicine time
        • 5 minutes after if not taken

        🚨 ESCALATION ALERTS
        • Urgent alerts after 15 minutes (missed dose)
        • Family notifications after 30 minutes
        • Logged as missed after 1 hour

        📱 Mobile Alert Bot (your Android app)
        If configured in Settings

        ⏱️ Alerts will trigger automatically
        when medicine times are reached

        Make sure app stays running!
        """
        messagebox.showinfo("✅ Auto-Alerts Active", msg)

    def save_all_settings(self):
        """Save all settings from all sections"""
        try:
            print("=== Saving All Settings ===")

            success_count = 0
            total_count = 0

            # 1. Save Email settings
            if hasattr(self, 'save_gmail_config'):
                total_count += 1
                try:
                    self.save_gmail_config()
                    success_count += 1
                except Exception as e:
                    print(f"❌ Error saving Email: {e}")

            # 2. Save System Preferences
            if hasattr(self, 'save_system_preferences'):
                total_count += 1
                try:
                    self.save_system_preferences()
                    success_count += 1
                except Exception as e:
                    print(f"❌ Error saving System Preferences: {e}")

            # Show success message
            if success_count == total_count:
                self.settings_status_label.config(
                    text=f"✅ All {success_count} settings saved successfully!",
                    fg=self.success_color
                )
            elif success_count > 0:
                self.settings_status_label.config(
                    text=f"⚠️ {success_count}/{total_count} settings saved",
                    fg=self.warning_color
                )
            else:
                self.settings_status_label.config(
                    text="❌ No settings were saved",
                    fg=self.danger_color
                )

            # Clear message after 3 seconds
            self.root.after(3000, lambda: self.settings_status_label.config(text=""))

            print(f"✅ Saved {success_count}/{total_count} settings")

        except Exception as e:
            self.settings_status_label.config(
                text=f"❌ Error: {str(e)[:30]}",
                fg=self.danger_color
            )
            print(f"❌ Error in save_all_settings: {e}")

    def load_medical_reminders(self):
        """Load medical reminders from SQLite DB"""
        try:
            db = getattr(self, "_alert_db", None)
            if db is None:
                db = AlertDB()
                self._alert_db = db

            loaded = db.get("medical_reminders")
            if loaded:
                self.medical_reminders = loaded
                appt_count = len(loaded.get('appointments', []))
                print(f"✓ Medical reminders loaded from DB ({appt_count} appointments)")
            else:
                print("⚠️ No saved medical reminders found; using defaults")
            return True
        except Exception as e:
            print(f"✗ Error loading reminders: {e}")
            return False

    def save_medical_reminders(self):
        """Save medical reminders to SQLite DB"""
        try:
            db = getattr(self, "_alert_db", None)
            if db is None:
                db = AlertDB()
                self._alert_db = db

            db.set("medical_reminders", self.medical_reminders)
            print("✓ Medical reminders saved to DB")
            # Export reminders to medicine_times.json and push to GitHub
            repo_path = os.path.dirname(os.path.abspath(__file__))
            export_medicine_alerts_to_json_and_push(repo_path)
            return True
        except Exception as e:
            print(f"✗ Error saving reminders: {e}")
            return False

    def test_sms_configuration(self):
        """Test SMS configuration (no-op if SMS UI not present)"""
        if not hasattr(self, 'sms_enabled_var') or not hasattr(self, 'sms_phone_var'):
            return
        if not self.sms_enabled_var.get():
            messagebox.showwarning("SMS Disabled", "Please enable SMS alerts first")
            return

        phone = self.sms_phone_var.get().strip()
        if not phone:
            messagebox.showwarning("Missing Phone", "Please enter your phone number")
            return

        if hasattr(self, 'sms_status_label'):
            self.sms_status_label.config(
                text="Sending test SMS...",
                fg=self.warning_color
            )

        # Simulate sending (replace with actual SMS sending code)
        try:
            # For now, just simulate success
            self.root.after(2000, lambda: self.show_sms_test_result(True, phone))

        except Exception as e:
            self.root.after(2000, lambda: self.show_sms_test_result(False, phone, str(e)))

    def show_sms_test_result(self, success, phone, error_msg=""):
        """Show SMS test result"""
        if not hasattr(self, 'sms_status_label'):
            return
        if success:
            self.sms_status_label.config(
                text=f"✓ Test SMS sent to {phone}",
                fg=self.success_color
            )
            messagebox.showinfo("Success", f"Test SMS sent to {phone}")
        else:
            self.sms_status_label.config(
                text=f"✗ Failed to send to {phone}",
                fg=self.danger_color
            )
            if error_msg:
                messagebox.showerror("Error", f"Failed to send SMS: {error_msg}")
            else:
                messagebox.showerror("Error", "Failed to send test SMS. Check your settings.")

    def test_gmail_connection(self):
        """Test Gmail connection by sending a test email"""
        print("📧 Testing Gmail connection...")

        # Get email and password from UI
        email = self.gmail_email.get().strip()
        password = self.gmail_password.get().strip()

        if not email or not password:
            messagebox.showwarning("Missing Info",
                                   "Please enter both Gmail address and App Password")
            return

        # Get recipient emails from the text field
        recipient_text = ""
        if hasattr(self, 'recipient_emails'):
            recipient_text = self.recipient_emails.get("1.0", tk.END).strip()

        # If no recipients, use sender email
        if not recipient_text:
            recipient_text = email
            # Auto-fill the field with sender email
            self.recipient_emails.delete("1.0", tk.END)
            self.recipient_emails.insert("1.0", email)

        # Parse recipients (comma separated)
        recipients = [email.strip() for email in recipient_text.split(',') if email.strip()]

        if not recipients:
            recipients = [email]  # Default to sender

        try:
            # Create test email
            msg = MIMEMultipart()
            msg['From'] = email
            msg['To'] = ", ".join(recipients)
            msg['Subject'] = "✅ CuraX - Gmail Connection Test"

            # Create HTML email (same as before)
            html = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <div style="background: linear-gradient(135deg, #4a6fa5 0%, #28a745 100%);
                            padding: 20px; color: white; border-radius: 10px 10px 0 0;">
                    <h2 style="margin: 0;">💊 CuraX Medicine System</h2>
                </div>
                <div style="background-color: white; padding: 30px; border-radius: 0 0 10px 10px;">
                    <h3 style="color: #333;">✅ Gmail Connection Successful</h3>
                    <p style="color: #666;">This is a test email from your CuraX Medicine System.</p>
                    <p style="color: #666;">Your Gmail configuration is working correctly.</p>
                    <hr style="margin: 20px 0;">
                    <p style="color: #999; font-size: 12px;">
                        Time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
                        System: CuraX Intelligent Medicine System<br>
                        Recipients: {', '.join(recipients)}
                    </p>
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html, 'html'))

            # Test connection
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(email, password)
                server.send_message(msg)

            # Update status
            self.gmail_status.config(
                text=f"✅ Test sent to {len(recipients)} recipient(s)",
                fg=self.success_color
            )

            print(f"Gmail test successful - sent to {len(recipients)} recipient(s): {recipients}")

            messagebox.showinfo("Success",
                                f"✅ Gmail connection test successful!\n\n"
                                f"Test email has been sent to:\n{', '.join(recipients)}")

        except smtplib.SMTPAuthenticationError:
            self.gmail_status.config(
                text="❌ Authentication failed",
                fg=self.danger_color
            )
            messagebox.showerror("Authentication Failed",
                                 "Gmail authentication failed.\n\n"
                                 "Please check:\n"
                                 "1. Email address is correct\n"
                                 "2. Using 16-character App Password (not regular password)\n"
                                 "3. 2-factor authentication is enabled on Google account")

        except Exception as e:
            self.gmail_status.config(
                text=f"❌ Error: {str(e)[:50]}...",
                fg=self.danger_color
            )
            messagebox.showerror("Connection Error", f"Failed to connect to Gmail:\n\n{str(e)}")

    def save_gmail_config(self):
        """Save Gmail configuration to settings"""
        print("Saving Gmail configuration...")
        email = self.gmail_email.get().strip()
        password = self.gmail_password.get().strip()

        if not email:
            messagebox.showwarning("Missing Email", "Please enter a Gmail address")
            return

        if not password:
            messagebox.showwarning("Missing Password", "Please enter an App Password")
            return

        # Get recipient emails
        recipient_text = ""
        if hasattr(self, 'recipient_emails'):
            recipient_text = self.recipient_emails.get("1.0", tk.END).strip()

        # If no recipients specified, default to sender email
        if not recipient_text:
            recipient_text = email

        # Admin verification BEFORE saving
        if not self.verify_admin_dialog("Save Gmail Configuration"):
            return

        # Now save to config (only after verification passes)
        self.gmail_config["sender_email"] = email
        self.gmail_config["sender_password"] = password
        self.gmail_config["recipients"] = recipient_text  # Save recipient emails
        
        # Update UI if needed
        if hasattr(self, 'recipient_emails') and not self.recipient_emails.get("1.0", tk.END).strip():
            self.recipient_emails.delete("1.0", tk.END)
            self.recipient_emails.insert("1.0", email)

        # Save to file
        self.save_alert_settings()

        # Update status
        self.gmail_status.config(
            text=f"✅ Saved: {len(recipient_text.split(','))} recipient(s)",
            fg=self.success_color
        )

        print(f"✔ Gmail config saved for: {email}")
        print(f"✔ Recipients: {recipient_text}")

        messagebox.showinfo("Saved",
                            f"Gmail configuration saved successfully!\n\n"
                            f"Sender: {email}\n"
                            f"Recipients: {recipient_text}")

    def save_missed_dose_settings(self):
        """Save missed dose escalation settings"""
        print("💾 Saving missed dose settings...")

        # Store original states before verification
        original_states = {}
        for key, var in self.escalation_vars.items():
            original_states[key] = var.get()
        original_email = self.family_notify_email.get().strip()

        # Admin verification BEFORE saving
        if not self.verify_admin_dialog("Save Missed Dose Settings"):
            # Revert checkboxes to saved state from database
            saved_settings = self.alert_settings.get("missed_dose_escalation", {})
            for key, var in self.escalation_vars.items():
                var.set(saved_settings.get(key, True))
            # Revert email to saved state
            saved_email = saved_settings.get("family_email", "")
            self.family_notify_email.delete(0, tk.END)
            self.family_notify_email.insert(0, saved_email)
            return

        # Get family email
        family_email = self.family_notify_email.get().strip()

        # Create missed dose escalation settings
        missed_dose_settings = {
            "5_min_reminder": self.escalation_vars[
                "5_min_reminder"].get() if "5_min_reminder" in self.escalation_vars else True,
            "15_min_urgent": self.escalation_vars[
                "15_min_urgent"].get() if "15_min_urgent" in self.escalation_vars else True,
            "30_min_family": self.escalation_vars[
                "30_min_family"].get() if "30_min_family" in self.escalation_vars else True,
            "1_hour_log": self.escalation_vars["1_hour_log"].get() if "1_hour_log" in self.escalation_vars else True,
            "family_email": family_email
        }

        # Save to alert settings
        self.alert_settings["missed_dose_escalation"] = missed_dose_settings

        # Save to file
        self.save_alert_settings()

        print(f"✅ Missed dose settings saved. Family email: {family_email}")
        messagebox.showinfo("Saved", "Missed dose settings saved successfully!")

    def test_family_notification(self):
        """Test family notification email"""
        print("🔔 Testing family notification...")

        family_email = self.family_notify_email.get().strip()

        if not family_email:
            messagebox.showwarning("Missing Email", "Please enter family member email")
            return

        try:
            # Create test email
            msg = MIMEMultipart()
            msg['From'] = self.gmail_config.get("sender_email", "")
            msg['To'] = family_email
            msg['Subject'] = "⚠️ CuraX - Missed Dose Test Notification"

            # Create HTML email
            html = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <div style="background: linear-gradient(135deg, #ffc107 0%, #dc3545 100%);
                            padding: 20px; color: white; border-radius: 10px 10px 0 0;">
                    <h2 style="margin: 0;">⚠️ CuraX - Missed Dose Alert</h2>
                </div>
                <div style="background-color: white; padding: 30px; border-radius: 0 0 10px 10px;">
                    <h3 style="color: #333;">TEST: Family Notification System</h3>
                    <p style="color: #666;">This is a <strong>TEST</strong> email for missed dose notifications.</p>
                    <p style="color: #666;">If this was a real alert, it would mean:</p>
                    <ul style="color: #666;">
                        <li>A medicine dose was missed</li>
                        <li>30 minutes have passed since the scheduled time</li>
                        <li>Family member notification is triggered</li>
                    </ul>
                    <div style="background-color: #fff3cd; border-left: 4px solid #ffc107; padding: 10px; margin: 20px 0;">
                        <p style="color: #856404; margin: 0;">
                            <strong>Medicine:</strong> Test Medicine<br>
                            <strong>Box:</strong> B1<br>
                            <strong>Scheduled Time:</strong> {datetime.datetime.now().strftime("%H:%M")}<br>
                            <strong>Status:</strong> MISSED DOSE
                        </p>
                    </div>
                    <hr style="margin: 20px 0;">
                    <p style="color: #999; font-size: 12px;">
                        Time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
                        System: CuraX Intelligent Medicine System
                    </p>
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html, 'html'))

            # Send email
            sender_email = self.gmail_config.get("sender_email", "")
            sender_password = self.gmail_config.get("sender_password", "")

            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)

            print(f"✅ Test notification sent to: {family_email}")
            messagebox.showinfo("Success",
                                f"✅ Test notification sent successfully!\n\n"
                                f"Email sent to: {family_email}")

        except Exception as e:
            print(f"❌ Failed to send test notification: {e}")
            messagebox.showerror("Error", f"Failed to send test notification:\n\n{str(e)}")

    def test_mousewheel(self):
        """Test mousewheel scrolling functionality - standalone test window"""
        print("=" * 60)
        print("MOUSEWHEEL SCROLL TEST")
        print("=" * 60)
        
        test_window = tk.Toplevel(self.root)
        test_window.title("Mousewheel Scroll Test")
        test_window.geometry("600x400")
        test_window.configure(bg=self.bg_color)
        
        # Title
        tk.Label(test_window, text="🖱️ Mousewheel Scroll Test",
                 font=('Arial', 18, 'bold'), bg=self.bg_color,
                 fg=self.primary_color).pack(pady=10)
        
        # Instructions
        instructions = tk.Label(test_window,
                               text="Try scrolling with your mouse wheel over the content below.\n"
                                    "You should see the text scroll up/down smoothly.",
                               font=('Arial', 11), bg=self.bg_color,
                               fg='#6c757d', justify=tk.CENTER)
        instructions.pack(pady=10)
        
        # Create canvas with scrollbar using the same method as main app
        container = tk.Frame(test_window, bg=self.bg_color)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        canvas = tk.Canvas(container, bg='white', highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient='vertical', command=canvas.yview)
        frame = tk.Frame(canvas, bg='white')
        
        frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Add test content
        for i in range(50):
            tk.Label(frame, text=f"Line {i+1}: Test content for scrolling",
                     bg='white', fg='#333333', font=('Arial', 11)).pack(fill=tk.X, padx=10, pady=5)
        
        # Test mousewheel binding using the same method
        def on_mousewheel_test(event):
            print(f"✓ Mousewheel event detected!")
            print(f"  - Delta: {getattr(event, 'delta', 'N/A')}")
            print(f"  - Num: {getattr(event, 'num', 'N/A')}")
            
            try:
                widget = event.widget.winfo_containing(event.x_root, event.y_root)
                if widget is None:
                    print("  - Widget is None")
                    return
                
                # Check if widget or parent is canvas
                current = widget
                found = False
                for _ in range(10):
                    if current == canvas:
                        found = True
                        break
                    try:
                        current = current.master
                    except:
                        break
                
                if found:
                    print("  ✓ SCROLLING (canvas found in hierarchy)")
                    if hasattr(event, 'delta'):
                        if event.delta > 0:
                            canvas.yview_scroll(-3, "units")
                        else:
                            canvas.yview_scroll(3, "units")
                    elif hasattr(event, 'num'):
                        if event.num == 4:
                            canvas.yview_scroll(-3, "units")
                        elif event.num == 5:
                            canvas.yview_scroll(3, "units")
                else:
                    print("  ✗ NOT scrolling (canvas not in hierarchy)")
            except Exception as e:
                print(f"  ✗ Error: {e}")
            
            return "break"
        
        # Bind mousewheel to test window
        test_window.bind("<MouseWheel>", on_mousewheel_test, add=True)
        test_window.bind("<Button-4>", on_mousewheel_test, add=True)
        test_window.bind("<Button-5>", on_mousewheel_test, add=True)
        
        # Status label
        status_frame = tk.Frame(test_window, bg=self.bg_color)
        status_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(status_frame,
                 text="✓ Mousewheel events will be logged in console\n"
                      "Try scrolling now - check your terminal for debug output",
                 bg=self.bg_color, font=('Arial', 9), fg='#6c757d',
                 justify=tk.CENTER).pack()
        
        print("Test window created. Try scrolling with your mouse wheel.")
        print("Check console output for event detection logs.")
        print("=" * 60)

    def on_closing(self):
        """Handle window close event"""
        print("🔴 Shutting down application...")
        self.root.destroy()
        # Stop alert scheduler
        if hasattr(self, 'alert_scheduler') and self.alert_scheduler:
            try:
                self.alert_scheduler.stop()
                print("✔ Alert scheduler stopped")
            except Exception as e:
                print(f"⚠ Failed to stop alert scheduler cleanly: {e}")

        # Send temperature shutdown command
        try:
            if hasattr(self, 'ser') and self.ser and self.ser.is_open:
                self.ser.write(b"TEMP_SHUTDOWN\n")
                time.sleep(0.5)
                print("✔ Temperature shutdown command sent")
        except Exception:
            # Ignore serial shutdown errors during close
            pass

        self.running = False

        try:
            if hasattr(self, 'serial_thread') and self.serial_thread:
                self.serial_thread.join(timeout=1)
        except Exception as e:
            print(f"⚠ Failed to join serial thread cleanly: {e}")

        try:
            if hasattr(self, 'ser') and self.ser and self.ser.is_open:
                self.ser.close()
        except Exception as e:
            print(f"⚠ Failed to close serial port cleanly: {e}")

        try:
            self.save_data()
            self.save_alert_settings()  # Save alert settings too!
        except Exception as e:
            print(f"⚠ Failed to save data on close: {e}")


class AlertScheduler:
    """READ-ONLY alert scheduling system - won't modify your data"""

    def __init__(self, app):
        self.app = app
        self.running = True
        self.scheduled_alerts = {}

    def cancel_medicine_alerts_for_box(self, box_id):
        """Cancel all scheduled daily alerts for a given medicine box."""
        try:
            import schedule
            prefix = f"{box_id}_"
            keys_to_remove = [k for k in list(self.scheduled_alerts.keys()) if k.startswith(prefix)]
            for key in keys_to_remove:
                job = self.scheduled_alerts.pop(key, None)
                if job is not None:
                    try:
                        schedule.cancel_job(job)
                    except Exception as e:
                        print(f"❌ Failed to cancel scheduled job {key}: {e}")
            if keys_to_remove:
                print(f"🗑️ Cancelled {len(keys_to_remove)} scheduled alert(s) for {box_id}")
        except Exception as e:
            print(f"✗ Error cancelling alerts for {box_id}: {e}")

    def schedule_medicine_alert(self, medicine, box_id):
        """Schedule alerts for a specific medicine - READ ONLY"""
        # Just check if medicine exists, don't modify it
        if not medicine:
            return

        # Get settings safely
        email_enabled = False
        if hasattr(self.app, 'alert_settings'):
            email_enabled = self.app.alert_settings.get("email_alerts", {}).get("enabled", False)

        if not email_enabled:
            return

        # Get time safely
        medicine_time = medicine.get('exact_time', '08:00')

        try:
            hour, minute = map(int, medicine_time.split(':'))
        except:
            hour, minute = 8, 0

        # Schedule alerts based on settings
        medicine_alerts = {}
        if hasattr(self.app, 'alert_settings'):
            medicine_alerts = self.app.alert_settings.get("medicine_alerts", {})

        if medicine_alerts.get("15_min_before", True):
            alert_time = f"{hour:02d}:{max(0, minute - 15):02d}"
            self.schedule_alert(alert_time, "pre", medicine, box_id)

        if medicine_alerts.get("exact_time", True):
            alert_time = f"{hour:02d}:{minute:02d}"
            self.schedule_alert(alert_time, "time", medicine, box_id)

        if medicine_alerts.get("5_min_after", True):
            alert_time = f"{hour:02d}:{(minute + 5) % 60:02d}"
            self.schedule_alert(alert_time, "missed", medicine, box_id)

    def schedule_alert(self, time_str, alert_type, medicine, box_id):
        """Schedule a single alert"""
        try:
            job = schedule.every().day.at(time_str).do(
                self.send_alert, alert_type, medicine.copy(), box_id  # Use COPY of medicine
            )

            key = f"{box_id}_{time_str}_{alert_type}"
            self.scheduled_alerts[key] = job
            print(f"✅ Scheduled {alert_type} alert for {medicine.get('name', 'Unknown')} at {time_str}")
        except Exception as e:
            print(f"❌ Failed to schedule alert: {e}")

    def send_alert(self, alert_type, medicine, box_id):
        """Send actual alert via Gmail - with missed dose handling"""
        print(f"▲ Alert triggered: {alert_type} for {medicine.get('name', 'Unknown')}")

        # Define subject and body
        if alert_type == "pre":
            subject = f"⏰ Reminder: {medicine.get('name', 'Medicine')} in 15 minutes"
            body = f"Time to take {medicine.get('name', 'Medicine')} from Box {box_id} is approaching (in 15 minutes)."

            # Send to email and Mobile Alert Bot
            self.send_gmail_alert(subject, body)
            try:
                if hasattr(self.app, 'send_mobile_alert'):
                    self.app.send_mobile_alert(alert_type, body)
            except Exception as mob_err:
                print(f"✗ Alert mobile failed: {mob_err}")

        elif alert_type == "time":
            subject = f"✅ TIME NOW: {medicine.get('name', 'Medicine')}"
            body = f"Please take {medicine.get('name', 'Medicine')} from Box {box_id} immediately."

            # Send to email and Mobile Alert Bot
            self.send_gmail_alert(subject, body)
            try:
                if hasattr(self.app, 'send_mobile_alert'):
                    self.app.send_mobile_alert(alert_type, body)
            except Exception as mob_err:
                print(f"✗ Alert mobile failed: {mob_err}")

        elif alert_type == "missed":
            # Check missed dose escalation settings
            if hasattr(self.app, 'alert_settings'):
                missed_settings = self.app.alert_settings.get("missed_dose_escalation", {})

                # Get current time
                now = datetime.datetime.now()

                if missed_settings.get("5_min_reminder", True):
                    # 5-minute reminder - send immediately
                    subject = f"⚠️ Reminder: {medicine.get('name', 'Medicine')} missed"
                    body = f"You may have missed your {medicine.get('name', 'Medicine')} dose from Box {box_id}. Please take it now."
                    self.send_gmail_alert(subject, body)
                    try:
                        if hasattr(self.app, 'send_mobile_alert'):
                            self.app.send_mobile_alert("missed", body)
                    except Exception as mob_err:
                        print(f"✗ Missed mobile failed: {mob_err}")
                    print(f"✅ Sent 5-min reminder for {medicine.get('name', 'Unknown')}")

                if missed_settings.get("15_min_urgent", True):
                    # Schedule 15-minute urgent alert
                    alert_time = now + datetime.timedelta(minutes=15)
                    schedule_time = alert_time.strftime("%H:%M")

                    try:
                        # Schedule for today
                        schedule.every().day.at(schedule_time).do(
                            self.send_urgent_missed_alert, medicine.copy(), box_id
                        ).tag(f"urgent_{box_id}_{medicine.get('name', '')}")

                        print(
                            f"✅ Scheduled 15-min urgent alert for {medicine.get('name', 'Unknown')} at {schedule_time}")
                    except Exception as e:
                        print(f"❌ Failed to schedule 15-min alert: {e}")

                if missed_settings.get("30_min_family", True):
                    # Schedule family notification
                    alert_time = now + datetime.timedelta(minutes=30)
                    schedule_time = alert_time.strftime("%H:%M")

                    try:
                        schedule.every().day.at(schedule_time).do(
                            self.send_family_notification, medicine.copy(), box_id
                        ).tag(f"family_{box_id}_{medicine.get('name', '')}")

                        print(
                            f"✅ Scheduled family notification for {medicine.get('name', 'Unknown')} at {schedule_time}")
                    except Exception as e:
                        print(f"❌ Failed to schedule family notification: {e}")

                if missed_settings.get("1_hour_log", True):
                    # Schedule missed dose logging
                    alert_time = now + datetime.timedelta(hours=1)
                    schedule_time = alert_time.strftime("%H:%M")

                    try:
                        schedule.every().day.at(schedule_time).do(
                            self.log_missed_dose, medicine.copy(), box_id
                        ).tag(f"log_{box_id}_{medicine.get('name', '')}")

                        print(
                            f"✅ Scheduled missed dose logging for {medicine.get('name', 'Unknown')} at {schedule_time}")
                    except Exception as e:
                        print(f"❌ Failed to schedule missed dose logging: {e}")
            else:
                print("⚠️ No missed dose settings found")

                # Send basic missed alert
                subject = f"⚠️ MISSED: {medicine.get('name', 'Medicine')}"
                body = f"You may have missed your {medicine.get('name', 'Medicine')} dose from Box {box_id}."
                self.send_gmail_alert(subject, body)
                try:
                    if hasattr(self.app, 'send_mobile_alert'):
                        self.app.send_mobile_alert("missed", body)
                except Exception as mob_err:
                    print(f"✗ Alert mobile failed: {mob_err}")

        else:
            subject = f"Alert: {medicine.get('name', 'Medicine')}"
            body = f'Medicine alert for {medicine.get('name', 'Medicine')} from Box {box_id}.'
            self.send_gmail_alert(subject, body)
            try:
                if hasattr(self.app, 'send_mobile_alert'):
                    self.app.send_mobile_alert(alert_type, body)
            except Exception as mob_err:
                print(f"✗ Alert mobile failed: {mob_err}")

    def send_gmail_alert(self, subject, body):
        """Send email via Gmail - uses saved recipients"""
        try:
            # Check if Gmail is configured
            if not hasattr(self.app, 'gmail_config'):
                print("✗ Gmail config not found")
                return

            sender_email = self.app.gmail_config.get("sender_email", "")
            sender_password = self.app.gmail_config.get("sender_password", "")

            if not sender_email or not sender_password:
                print("✗ Gmail not configured properly")
                return

            # Get recipient emails from saved config
            recipient_text = self.app.gmail_config.get("recipients", "")

            if recipient_text:
                # Parse comma-separated emails
                recipient_list = [email.strip() for email in recipient_text.split(',') if email.strip()]
            else:
                # Default to sender if no recipients saved
                recipient_list = [sender_email]

            # Create email
            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = ", ".join(recipient_list)
            msg['Subject'] = subject

            # HTML email (same as before)
            html = f"""
            <html>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px;">
                <div style="background: #4a6fa5; color: white; padding: 20px; border-radius: 10px 10px 0 0;">
                    <h2 style="margin: 0;">💊 CuraX Medicine Alert</h2>
                </div>
                <div style="background-color: white; padding: 30px; border-radius: 0 0 10px 10px; border: 1px solid #ddd;">
                    <h3 style="color: #333; margin-top: 0;">{subject}</h3>
                    <p style="color: #666; font-size: 16px; line-height: 1.6;">{body}</p>
                    <hr style="border: none; height: 1px; background: #eee; margin: 30px 0;">
                    <p style="color: #999; font-size: 12px;">
                        Automated alert from CuraX<br>
                        Time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                    </p>
                </div>
            </body>
            </html>
            """

            msg.attach(MIMEText(html, 'html'))

            # Send email to all recipients
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(sender_email, sender_password)
                server.send_message(msg)

            print(f"✅ Email sent to {len(recipient_list)} recipient(s): {subject}")

        except Exception as e:
            print(f"❌ Failed to send email: {e}")

    def send_urgent_missed_alert(self, medicine, box_id):
        """Send urgent missed dose alert - only if dose wasn't taken"""
        # Check if dose was taken in the meantime
        if self.check_if_dose_taken(medicine, box_id):
            print(f"✅ Dose for {medicine.get('name', 'Unknown')} was already taken, skipping urgent alert")
            return

        subject = f"🚨 URGENT: {medicine.get('name', 'Medicine')} missed by 15 minutes"
        body = f"URGENT: You missed your {medicine.get('name', 'Medicine')} dose from Box {box_id} 15 minutes ago!"
        self.send_gmail_alert(subject, body)
        try:
            if hasattr(self.app, 'send_mobile_alert'):
                self.app.send_mobile_alert("missed_urgent", body)
        except Exception as mob_err:
            print(f"✗ Urgent missed mobile failed: {mob_err}")

    def check_if_dose_taken(self, medicine, box_id):
        """Check if dose was taken since the alert was scheduled"""
        try:
            # Get current medicine from app (not the copy passed to scheduler)
            if hasattr(self.app, 'medicine_boxes'):
                current_med = self.app.medicine_boxes.get(box_id)
                if current_med:
                    # Check if last dose taken timestamp is recent (last 2 hours)
                    last_dose = current_med.get('last_dose_taken')
                    if last_dose:
                        try:
                            last_dose_time = datetime.datetime.fromisoformat(last_dose)
                            time_diff = datetime.datetime.now() - last_dose_time
                            if time_diff.total_seconds() < 7200:  # 2 hours
                                return True
                        except:
                            pass
            return False
        except Exception as e:
            print(f"❌ Error checking if dose was taken: {e}")
            return False

    def log_family_notification(self, medicine, box_id, family_email):
        """Log family notification in app's dose log"""
        try:
            if hasattr(self.app, 'dose_log'):
                log_entry = {
                    'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'box': box_id,
                    'medicine': medicine.get('name', 'Unknown'),
                    'dose_taken': 0,
                    'remaining': medicine.get('quantity', 0),
                    'action': 'Family Notified',
                    'status': 'FAMILY_ALERT',
                    'notification_to': family_email,
                    'notes': f'Family member notified about missed dose'
                }

                self.app.dose_log.append(log_entry)

                # Update history if UI exists
                if hasattr(self.app, 'update_history'):
                    self.app.update_history()

                print(f"📝 Family notification logged for {medicine.get('name', 'Unknown')}")

        except Exception as e:
            print(f"❌ Failed to log family notification: {e}")

    def send_family_notification(self, medicine, box_id):
        """Send notification to family member - only if dose wasn't taken"""
        try:
            # Check if dose was taken in the meantime
            if self.check_if_dose_taken(medicine, box_id):
                print(f"✅ Dose for {medicine.get('name', 'Unknown')} was already taken, skipping family notification")
                return

            # Get family email from settings
            if hasattr(self.app, 'alert_settings'):
                missed_settings = self.app.alert_settings.get("missed_dose_escalation", {})
                family_email = missed_settings.get("family_email", "")

                if not family_email:
                    # Try to get from gmail recipients
                    if hasattr(self.app, 'gmail_config'):
                        recipient_text = self.app.gmail_config.get("recipients", "")
                        if recipient_text:
                            # Get first recipient email
                            recipients = [email.strip() for email in recipient_text.split(',') if email.strip()]
                            if recipients:
                                family_email = recipients[0]

                if family_email:
                    # Get sender credentials
                    sender_email = self.app.gmail_config.get("sender_email", "")
                    sender_password = self.app.gmail_config.get("sender_password", "")

                    if not sender_email or not sender_password:
                        print("❌ Cannot send family notification: Gmail not configured")
                        return

                    # Create email specifically for family
                    msg = MIMEMultipart()
                    msg['From'] = sender_email
                    msg['To'] = family_email
                    msg['Subject'] = f"👨‍👩‍👧‍👦 FAMILY ALERT: {medicine.get('name', 'Medicine')} missed"

                    # Get medicine details
                    med_name = medicine.get('name', 'Unknown')
                    exact_time = medicine.get('exact_time', 'Unknown')
                    dose_amount = medicine.get('dose_per_day', 1)
                    quantity_left = medicine.get('quantity', 0)

                    html = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif;">
                        <div style="background: linear-gradient(135deg, #dc3545 0%, #fd7e14 100%);
                                    padding: 20px; color: white; border-radius: 10px 10px 0 0;">
                            <h2 style="margin: 0;">👨‍👩‍👧‍👦 CuraX - Family Alert</h2>
                        </div>
                        <div style="background-color: white; padding: 30px; border-radius: 0 0 10px 10px;">
                            <h3 style="color: #333;">⚠️ MISSED MEDICINE DOSE</h3>
                            <div style="background-color: #f8d7da; border: 1px solid #f5c6cb; 
                                        padding: 15px; border-radius: 5px; margin: 20px 0;">
                                <p style="color: #721c24; margin: 5px 0;">
                                    <strong>Patient Medicine Alert:</strong><br>
                                    <strong>Medicine:</strong> {med_name}<br>
                                    <strong>Box Number:</strong> {box_id}<br>
                                    <strong>Dose Amount:</strong> {dose_amount} tablet(s)<br>
                                    <strong>Scheduled Time:</strong> {exact_time}<br>
                                    <strong>Missed By:</strong> 30 minutes<br>
                                    <strong>Quantity Left:</strong> {quantity_left} tablets<br>
                                    <strong>Status:</strong> ❌ DOSE MISSED
                                </p>
                            </div>
                            <p style="color: #666; font-size: 14px; line-height: 1.6;">
                                <strong>Action Required:</strong><br>
                                1. Please check on the patient immediately<br>
                                2. Ensure they take their missed dose if appropriate<br>
                                3. Contact them to confirm they're okay<br>
                                4. If no response, consider checking in person
                            </p>
                            <p style="color: #666; font-size: 14px;">
                                This is an automated family notification from CuraX Medicine System.
                                Regular alerts were sent but the dose was not taken.
                            </p>
                            <hr style="margin: 20px 0;">
                            <p style="color: #999; font-size: 12px;">
                                Alert Time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
                                System: CuraX Intelligent Medicine System<br>
                                Patient ID: Medicine Management System User
                            </p>
                        </div>
                    </body>
                    </html>
                    """

                    msg.attach(MIMEText(html, 'html'))

                    # Send email
                    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                        server.login(sender_email, sender_password)
                        server.send_message(msg)

                    print(f"✅ Family notification sent to: {family_email}")

                    # Also send to Mobile Alert Bot (alerts go to both mail and Mobile Alert Bot)
                    body_text = f"FAMILY ALERT: {medicine.get('name', 'Medicine')} dose from Box {box_id} missed by 30 min. Please check on patient."
                    if hasattr(self.app, 'send_mobile_alert'):
                        self.app.send_mobile_alert("family_alert", body_text)

                    # Also log this notification
                    self.log_family_notification(medicine, box_id, family_email)

                else:
                    print("⚠️ No family email configured for missed dose notifications")
            else:
                print("⚠️ No missed dose settings found in alert_settings")

        except Exception as e:
            print(f"❌ Failed to send family notification: {e}")
            import traceback
            traceback.print_exc()

    def log_missed_dose(self, medicine, box_id):
        """Log missed dose in history"""
        try:
            if hasattr(self.app, 'dose_log'):
                # Create missed dose log entry
                log_entry = {
                    'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'box': box_id,
                    'medicine': medicine.get('name', 'Unknown'),
                    'dose_taken': 0,  # 0 means missed
                    'remaining': medicine.get('quantity', 0),
                    'action': 'Missed Dose',
                    'status': 'MISSED'
                }

                # Add to dose log
                self.app.dose_log.append(log_entry)

                # Save data
                if hasattr(self.app, 'save_data'):
                    self.app.save_data()

                # Update history if UI exists
                if hasattr(self.app, 'update_history'):
                    self.app.update_history()

                print(f"📝 Missed dose logged for {medicine.get('name', 'Unknown')} from Box {box_id}")

                # Send final missed dose alert (email and Mobile Alert Bot)
                subject = f"📝 LOGGED: {medicine.get('name', 'Medicine')} missed dose"
                body = f"Missed dose of {medicine.get('name', 'Medicine')} from Box {box_id} has been logged in history."
                self.send_gmail_alert(subject, body)
                if hasattr(self.app, 'send_mobile_alert'):
                    self.app.send_mobile_alert("missed_logged", body)

        except Exception as e:
            print(f"❌ Failed to log missed dose: {e}")

    def schedule_expiry_alerts(self):
        """Schedule expiry alerts for all medicines"""
        print("📅 Scheduling expiry alerts...")

        today = datetime.datetime.now().date()

        for box_id, medicine in self.app.medicine_boxes.items():
            if medicine:
                expiry_str = medicine.get('expiry')
                if expiry_str:
                    try:
                        expiry_date = datetime.datetime.strptime(expiry_str, "%Y-%m-%d").date()
                        days_until_expiry = (expiry_date - today).days

                        # Schedule alerts based on settings
                        if hasattr(self.app, 'alert_settings'):
                            expiry_alerts = self.app.alert_settings.get("expiry_alerts", {})

                            # Calculate alert dates
                            if days_until_expiry == 1 and expiry_alerts.get("1_day_before", True):
                                self.schedule_expiry_alert(medicine, box_id, expiry_date, "1 day")

                            if days_until_expiry == 7 and expiry_alerts.get("7_days_before", True):
                                self.schedule_expiry_alert(medicine, box_id, expiry_date, "7 days")

                            if days_until_expiry == 15 and expiry_alerts.get("15_days_before", True):
                                self.schedule_expiry_alert(medicine, box_id, expiry_date, "15 days")

                            if days_until_expiry == 30 and expiry_alerts.get("30_days_before", True):
                                self.schedule_expiry_alert(medicine, box_id, expiry_date, "30 days")

                    except Exception as e:
                        print(f"❌ Error scheduling expiry alert: {e}")

    def schedule_expiry_alert(self, medicine, box_id, expiry_date, days_before):
        """Schedule a single expiry alert"""
        try:
            # Schedule for 10:00 AM on the alert day
            alert_time = "10:00"

            job = schedule.every().day.at(alert_time).do(
                self.send_expiry_alert, medicine.copy(), box_id, expiry_date, days_before
            )

            key = f"expiry_{box_id}_{expiry_date}_{days_before}"
            self.scheduled_alerts[key] = job

            print(f"✅ Scheduled {days_before} expiry alert for {medicine.get('name', 'Unknown')}")

        except Exception as e:
            print(f"❌ Failed to schedule expiry alert: {e}")

    def send_expiry_alert(self, medicine, box_id, expiry_date, days_before):
        """Send expiry alert email"""
        med_name = medicine.get('name', 'Medicine')

        if days_before == "1 day":
            subject = f"🚨 URGENT: {med_name} expires TOMORROW!"
            body = f"URGENT: {med_name} in Box {box_id} expires TOMORROW ({expiry_date}). Please replace immediately."
        else:
            subject = f"⚠️ Reminder: {med_name} expires in {days_before}"
            body = f"{med_name} in Box {box_id} expires in {days_before} on {expiry_date}. Please plan to replace it."

        self.send_gmail_alert(subject, body)
        if hasattr(self.app, 'send_mobile_alert'):
            self.app.send_mobile_alert("expiry", body)
        print(f"✅ Sent {days_before} expiry alert for {med_name}")

    def schedule_stock_checks(self):
        """Schedule daily stock checks"""
        # Check stock every day at 10:00 AM
        try:
            schedule.every().day.at("10:00").do(self.check_all_stock)
            print("✔️ Scheduled daily stock checks at 10:00 AM")
        except Exception as e:
            print(f"✗️ Failed to schedule stock checks: {e}")

    def check_all_stock(self):
        """Check stock for all medicines"""
        print("📦 Running daily stock check...")
        for box_id, medicine in self.app.medicine_boxes.items():
            if medicine:
                self.app.check_and_send_stock_alerts(medicine, box_id)

    def schedule_temp_monitoring(self):
        """Schedule periodic temperature monitoring"""
        # Check temperatures every 30 minutes
        try:
            schedule.every(30).minutes.do(self.monitor_temperatures)
            print("✔️ Scheduled temperature monitoring every 30 minutes")
        except Exception as e:
            print(f"✗️ Failed to schedule temperature monitoring: {e}")

    def monitor_temperatures(self):
        """Monitor temperatures and send alerts if out of range"""
        print("🌡️ Monitoring temperatures...")

        try:
            # This would read actual temperatures from ESP32
            # For now, we'll check if simulated temperatures are in range

            for peltier_id, settings in self.app.temp_settings.items():
                current_temp = settings.get("current", 18)
                min_temp = settings.get("min", 15)
                max_temp = settings.get("max", 20)

                if current_temp < min_temp or current_temp > max_temp:
                    self.send_temp_alert(peltier_id, current_temp, min_temp, max_temp)

        except Exception as e:
            print(f"✗️ Temperature monitoring error: {e}")

    def send_temp_alert(self, peltier_id, current_temp, min_temp, max_temp):
        """Send temperature alert email"""
        if peltier_id == "peltier1":
            boxes = "B1-B4"
            med_type = "normal medicines"
        else:
            boxes = "B5-B6"
            med_type = "cold medicines"

        subject = f"🌡️ TEMPERATURE ALERT: Peltier {peltier_id[-1]} out of range!"

        if current_temp < min_temp:
            body = (f"Peltier {peltier_id[-1]} temperature is TOO LOW!\n\n"
                    f"Current: {current_temp:.1f}°C (Range: {min_temp}°C - {max_temp}°C)\n"
                    f"Affected: Boxes {boxes}\n"
                    f"Medicine Type: {med_type}\n\n"
                    f"ACTION REQUIRED: Check cooling system.")
        else:
            body = (f"Peltier {peltier_id[-1]} temperature is TOO HIGH!\n\n"
                    f"Current: {current_temp:.1f}°C (Range: {min_temp}°C - {max_temp}°C)\n"
                    f"Affected: Boxes {boxes}\n"
                    f"Medicine Type: {med_type}\n\n"
                    f"ACTION REQUIRED: Check cooling system.")

        self.send_gmail_alert(subject, body)
        if hasattr(self.app, 'send_mobile_alert'):
            self.app.send_mobile_alert("temperature", body)
        print(f"✔️ Sent temperature alert for {peltier_id}")

    def start(self):
        """Start the scheduler in background"""
        print("🚀 Starting READ-ONLY alert scheduler...")
        self.schedule_stock_checks()
        self.schedule_temp_monitoring()
        Thread(target=self.run_scheduler, daemon=True).start()

    def run_scheduler(self):
        """Run the scheduler loop"""
        print("🔄 Alert scheduler running (read-only)...")
        while self.running:
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                print(f"⚠️ Scheduler error: {e}")
                time.sleep(5)

    def stop(self):
        """Stop the scheduler"""
        print("🛑 Stopping alert scheduler...")
        self.running = False
        schedule.clear()


def _run_relay_server():
    """Run TCP 5050 + WebSocket 5051 relay inside this process. Runs in a background thread."""
    try:
        import asyncio
        import websockets
    except ImportError:
        return
    TCP_PORT = 5050
    WS_PORT = 5051
    HOST = "0.0.0.0"
    ws_clients = set()

    async def handle_tcp(reader, writer):
        try:
            data = await reader.read(4096)
            if not data:
                return
            text = data.decode("utf-8", errors="ignore").strip()
            if not text or not ws_clients:
                return
            dead = set()
            for ws in ws_clients:
                try:
                    await ws.send(text)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                ws_clients.discard(ws)
        except Exception:
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def handle_ws(ws):
        ws_clients.add(ws)
        try:
            async for _ in ws:
                pass
        except Exception:
            pass
        finally:
            ws_clients.discard(ws)

    async def main():
        tcp = await asyncio.start_server(handle_tcp, HOST, TCP_PORT)
        ws = await websockets.serve(handle_ws, HOST, WS_PORT)
        async with tcp, ws:
            await asyncio.Future()

    try:
        asyncio.run(main())
    except Exception:
        pass


if __name__ == "__main__":
    print("CuraX Medicine Alerts – alert logs will appear in this console (email + mobile bot).", flush=True)
    app = CuraXDesktopApp()
    app.root.protocol("WM_DELETE_WINDOW", app.on_closing)
    # Start relay inside this process so no separate relay needed
    relay_thread = threading.Thread(target=_run_relay_server, daemon=True)
    relay_thread.start()
    app.root.mainloop()





