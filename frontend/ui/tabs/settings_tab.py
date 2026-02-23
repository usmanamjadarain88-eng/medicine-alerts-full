try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
        QGroupBox, QLineEdit, QPushButton, QCheckBox, QMessageBox,
        QScrollArea, QFrame, QDialog, QFormLayout, QRadioButton, QSizePolicy
    )
    from PyQt6.QtCore import Qt
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
        QGroupBox, QLineEdit, QPushButton, QCheckBox, QMessageBox,
        QScrollArea, QFrame, QDialog, QFormLayout, QRadioButton, QSizePolicy
    )
    from PyQt5.QtCore import Qt

import uuid
from ui.styles import (
    NEON_GREEN, TEXT_SECONDARY, TEXT_SECONDARY_LIGHT,
    ACCENT_LIGHT, SECONDARY_LIGHT_DARK, RADIUS, BORDER_LIGHT, BORDER,
)
class SettingsTab(QWidget):
    def __init__(self, controller, main_window=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.main_window = main_window
        self._build_ui()
        self._load()
        theme = getattr(self.controller, "appearance_theme", "light")
        self.apply_theme(theme)

    def _title_color(self):
        theme = getattr(self.controller, "appearance_theme", "light")
        return ACCENT_LIGHT if (theme or "light").lower() == "light" else NEON_GREEN

    def _secondary_color(self):
        theme = getattr(self.controller, "appearance_theme", "light")
        return SECONDARY_LIGHT_DARK if (theme or "light").lower() == "light" else TEXT_SECONDARY

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self._title_label = QLabel("Settings")
        self._title_label.setStyleSheet(
            f"font-size: 18pt; font-weight: bold; color: {self._title_color()};"
        )
        layout.addWidget(self._title_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()

        system = QWidget()
        sys_layout = QVBoxLayout(system)
        sys_layout.setSpacing(20)
        sys_layout.setContentsMargins(16, 16, 16, 20)
        self._sys_desc = QLabel("System configuration and device info.")
        self._sys_desc.setStyleSheet(f"color: {self._secondary_color()}; font-size: 10pt;")
        sys_layout.addWidget(self._sys_desc)
        sys_layout.addSpacing(8)

        self.mobile_group = QGroupBox("📱 Mobile App")
        mobile_layout = QVBoxLayout(self.mobile_group)
        mobile_layout.setSpacing(10)
        self.mobile_enabled = QCheckBox("Enable mobile alerts")
        mobile_layout.addWidget(self.mobile_enabled)
        mobile_form = QFormLayout()
        mobile_form.setSpacing(8)
        self.mobile_bot_id = QLineEdit()
        self.mobile_bot_id.setPlaceholderText("From mobile app")
        mobile_form.addRow("App ID:", self.mobile_bot_id)
        self.mobile_api_key = QLineEdit()
        try:
            self.mobile_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            self.mobile_api_key.setEchoMode(QLineEdit.Password)
        self.mobile_api_key.setPlaceholderText("From mobile app")
        mobile_form.addRow("API Key:", self.mobile_api_key)
        self.mobile_server = QLineEdit()
        self.mobile_server.setText("https://curax-relay.onrender.com")
        self.mobile_server.setPlaceholderText("https://curax-relay.onrender.com")
        mobile_form.addRow("Relay URL (for alerts to reach this device):", self.mobile_server)
        mobile_layout.addLayout(mobile_form)
        self._hint_mobile = QLabel("User receives medicine reminders here. Save to apply.")
        self._hint_mobile.setStyleSheet(f"color: {self._secondary_color()}; font-size: 9pt;")
        mobile_layout.addWidget(self._hint_mobile)
        mobile_btn_row = QHBoxLayout()
        self.mobile_test_btn = QPushButton("📤 Send Test Alert")
        self.mobile_test_btn.clicked.connect(self._test_mobile_bot)
        self.mobile_save_btn = QPushButton("💾 Save Mobile Settings")
        self.mobile_save_btn.clicked.connect(self._save_mobile_settings)
        mobile_btn_row.addWidget(self.mobile_test_btn)
        mobile_btn_row.addWidget(self.mobile_save_btn)
        mobile_btn_row.addStretch()
        mobile_layout.addLayout(mobile_btn_row)
        sys_layout.addWidget(self.mobile_group)

        self.email_group = QGroupBox("📧 Email Alerts (Gmail)")
        email_layout = QVBoxLayout(self.email_group)
        email_layout.setSpacing(10)
        email_form = QFormLayout()
        email_form.setSpacing(8)
        self.gmail_sender = QLineEdit()
        self.gmail_sender.setPlaceholderText("you@gmail.com")
        email_form.addRow("Sender email:", self.gmail_sender)
        self.gmail_password = QLineEdit()
        try:
            self.gmail_password.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            self.gmail_password.setEchoMode(QLineEdit.Password)
        self.gmail_password.setPlaceholderText("Gmail app password")
        email_form.addRow("App password:", self.gmail_password)
        self.gmail_recipients = QLineEdit()
        self.gmail_recipients.setPlaceholderText("Optional; comma-separated")
        email_form.addRow("Recipients:", self.gmail_recipients)
        email_layout.addLayout(email_form)
        self._hint_email = QLabel("Uses smtp.gmail.com:465. Save to apply.")
        self._hint_email.setStyleSheet(f"color: {self._secondary_color()}; font-size: 9pt;")
        email_layout.addWidget(self._hint_email)
        email_btn_row = QHBoxLayout()
        self.gmail_test_btn = QPushButton("📤 Send Test Email")
        self.gmail_test_btn.clicked.connect(self._test_gmail)
        self.gmail_save_btn = QPushButton("💾 Save Gmail Settings")
        self.gmail_save_btn.clicked.connect(self._save_gmail_settings)
        email_btn_row.addWidget(self.gmail_test_btn)
        email_btn_row.addWidget(self.gmail_save_btn)
        email_btn_row.addStretch()
        email_layout.addLayout(email_btn_row)
        sys_layout.addWidget(self.email_group)

        self.appearance_group = QGroupBox("🎨 Appearance / Theme")
        appearance_layout = QVBoxLayout(self.appearance_group)
        appearance_layout.setSpacing(10)
        self.appearance_hint = QLabel("Choose theme below; click Save to keep for next time. (Quick switch is in the top bar.)")
        self.appearance_hint.setWordWrap(True)
        self.appearance_hint.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 9pt;")
        appearance_layout.addWidget(self.appearance_hint)

        self.theme_label = QLabel("Interface Theme:")
        self.theme_label.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {NEON_GREEN};")
        appearance_layout.addWidget(self.theme_label)
        theme_column = QVBoxLayout()
        self.theme_dark_radio = QRadioButton("Dark Theme")
        self.theme_light_radio = QRadioButton("Light Theme (default)")
        self.theme_dark_radio.setStyleSheet("font-size: 10pt; font-weight: bold;")
        self.theme_light_radio.setStyleSheet("font-size: 10pt;")
        theme_column.addWidget(self.theme_dark_radio)
        theme_column.addSpacing(6)
        theme_column.addWidget(self.theme_light_radio)
        appearance_layout.addLayout(theme_column)

        def _on_theme_radio_changed():
            if not self.main_window:
                return
            theme = "light" if self.theme_light_radio.isChecked() else "dark"
            self.controller.appearance_theme = theme
            if hasattr(self.main_window, "apply_theme"):
                self.main_window.apply_theme(theme)

        self.theme_dark_radio.toggled.connect(_on_theme_radio_changed)
        self.theme_light_radio.toggled.connect(_on_theme_radio_changed)

        theme_save_row = QHBoxLayout()
        self.theme_save_btn = QPushButton("💾 Save Appearance")
        self.theme_save_btn.clicked.connect(self._save_appearance_settings)
        theme_save_row.addWidget(self.theme_save_btn)
        theme_save_row.addStretch()
        appearance_layout.addLayout(theme_save_row)

        sys_layout.addWidget(self.appearance_group)

        self.dnd_group = QGroupBox("⏰ Do Not Disturb")
        dnd_layout = QVBoxLayout(self.dnd_group)
        dnd_layout.setSpacing(10)
        self.dnd_enabled = QCheckBox("Enable do-not-disturb window")
        dnd_layout.addWidget(self.dnd_enabled)
        dnd_form = QFormLayout()
        dnd_form.setSpacing(8)
        self.dnd_start = QLineEdit()
        self.dnd_start.setPlaceholderText("22:00")
        dnd_form.addRow("Start (HH:MM):", self.dnd_start)
        self.dnd_end = QLineEdit()
        self.dnd_end.setPlaceholderText("07:00")
        dnd_form.addRow("End (HH:MM):", self.dnd_end)
        dnd_layout.addLayout(dnd_form)
        self._hint_dnd = QLabel("Non-critical alerts muted in this window.")
        self._hint_dnd.setStyleSheet(f"color: {self._secondary_color()}; font-size: 9pt;")
        dnd_layout.addWidget(self._hint_dnd)
        sys_layout.addWidget(self.dnd_group)

        self.save_sys_btn = QPushButton("💾 Save System Settings")
        def _save_sys():
            if self.main_window and not self.main_window.verify_admin_for_action("Save System Preferences"):
                return
            self._save_system_settings()
        self.save_sys_btn.clicked.connect(_save_sys)
        sys_layout.addWidget(self.save_sys_btn)
        tabs.addTab(system, "System Settings")

        account = QWidget()
        acc_layout = QVBoxLayout(account)

        acc_title = QLabel("🔑 Password Management")
        acc_title.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {NEON_GREEN};")
        acc_layout.addWidget(acc_title)

        acc_rules = QLabel(
            "Device password protects system unlock and all admin‑level actions.\n\n"
            "• Use a strong, memorable password (numbers only)\n"
            "• Minimum 4 digits recommended\n"
            "• Keep your password secure and confidential\n"
            "• Change regularly for better security"
        )
        acc_rules.setWordWrap(True)
        acc_rules.setStyleSheet(f"color: {TEXT_SECONDARY};")
        acc_layout.addWidget(acc_rules)

        self.change_pwd_btn = QPushButton("🔐 Change Device Password")
        self.change_pwd_btn.clicked.connect(self._change_password)
        pwd_btn_row = QHBoxLayout()
        pwd_btn_row.addWidget(self.change_pwd_btn)
        pwd_btn_row.addStretch()
        acc_layout.addLayout(pwd_btn_row)

        acc_layout.addStretch()
        tabs.addTab(account, "Account Settings")

        admin = QWidget()
        admin_layout = QVBoxLayout(admin)
        admin_layout.setContentsMargins(0, 0, 0, 0)
        admin_layout.setSpacing(8)
        try:
            admin_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        except AttributeError:
            admin_layout.setAlignment(Qt.AlignTop)

        admin_group = QWidget()
        g_admin_layout = QVBoxLayout(admin_group)
        g_admin_layout.setContentsMargins(0, 0, 0, 0)
        g_admin_layout.setSpacing(8)

        self.admin_status_label = QLabel()
        self.admin_status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 9pt;")
        g_admin_layout.addWidget(self.admin_status_label)

        admin_label_min_w = 200  # same width for all labels so inputs align
        admin_input_max_w = 440  # enough for long emails to be visible
        try:
            fixed_h = QSizePolicy.Policy.Fixed
        except AttributeError:
            fixed_h = QSizePolicy.Fixed

        def _admin_label(lbl):
            lbl.setMinimumWidth(admin_label_min_w)

        def _admin_input(w):
            w.setMinimumWidth(280)
            w.setMaximumWidth(admin_input_max_w)
            w.setSizePolicy(fixed_h, w.sizePolicy().verticalPolicy())

        name_row = QHBoxLayout()
        name_lbl = QLabel("Name:")
        _admin_label(name_lbl)
        name_row.addWidget(name_lbl)
        self.admin_name = QLineEdit()
        self.admin_name.setPlaceholderText("Admin name")
        _admin_input(self.admin_name)
        name_row.addWidget(self.admin_name)
        name_row.addStretch(1)
        g_admin_layout.addLayout(name_row)

        id_row = QHBoxLayout()
        id_lbl = QLabel("Admin ID (optional):")
        _admin_label(id_lbl)
        id_row.addWidget(id_lbl)
        self.admin_id = QLineEdit()
        self.admin_id.setPlaceholderText("CNIC / Staff ID")
        _admin_input(self.admin_id)
        id_row.addWidget(self.admin_id)
        id_row.addStretch(1)
        g_admin_layout.addLayout(id_row)

        email_row = QHBoxLayout()
        email_lbl = QLabel("Email:")
        _admin_label(email_lbl)
        email_row.addWidget(email_lbl)
        self.admin_email = QLineEdit()
        self.admin_email.setPlaceholderText("Email")
        _admin_input(self.admin_email)
        email_row.addWidget(self.admin_email)
        email_row.addStretch(1)
        g_admin_layout.addLayout(email_row)

        phone_row = QHBoxLayout()
        phone_lbl = QLabel("Phone:")
        _admin_label(phone_lbl)
        phone_row.addWidget(phone_lbl)
        self.admin_phone = QLineEdit()
        self.admin_phone.setPlaceholderText("Phone")
        _admin_input(self.admin_phone)
        phone_row.addWidget(self.admin_phone)
        phone_row.addStretch(1)
        g_admin_layout.addLayout(phone_row)

        pwd_row = QHBoxLayout()
        pwd_lbl = QLabel("Password:")
        _admin_label(pwd_lbl)
        pwd_row.addWidget(pwd_lbl)
        self.admin_password = QLineEdit()
        try:
            self.admin_password.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            self.admin_password.setEchoMode(QLineEdit.Password)
        self.admin_password.setPlaceholderText("Password")
        _admin_input(self.admin_password)
        pwd_row.addWidget(self.admin_password)
        pwd_row.addStretch(1)
        g_admin_layout.addLayout(pwd_row)

        self.setup_admin_btn = QPushButton("💾 Save Admin Credentials")
        self.setup_admin_btn.clicked.connect(self._setup_admin)
        row_save = QHBoxLayout()
        row_save.addWidget(self.setup_admin_btn)
        row_save.addStretch()
        g_admin_layout.addLayout(row_save)

        self.delete_admin_btn = QPushButton("🗑️ Delete Admin Account (Admin)")
        self.delete_admin_btn.clicked.connect(self._delete_admin_account)
        row_delete = QHBoxLayout()
        row_delete.addWidget(self.delete_admin_btn)
        row_delete.addStretch()
        g_admin_layout.addLayout(row_delete)

        # Admin Mobile App — only shown after admin is created; for linking admin's mobile app (alerts)
        self.admin_bot_group = QGroupBox("📱 Admin Mobile App")
        admin_bot_layout = QVBoxLayout(self.admin_bot_group)
        admin_bot_top_row = QHBoxLayout()
        self.admin_bot_enabled = QCheckBox("Enable admin mobile alerts")
        admin_bot_top_row.addWidget(self.admin_bot_enabled)
        admin_bot_top_row.addStretch()
        self.admin_alert_details_btn = QPushButton("Alert details")
        self.admin_alert_details_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #06402B; border: none; font-size: 9pt; text-decoration: underline; } "
            "QPushButton:hover { color: #0C6A49; }"
        )
        try:
            self.admin_alert_details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        except AttributeError:
            self.admin_alert_details_btn.setCursor(Qt.PointingHandCursor)
        self.admin_alert_details_btn.clicked.connect(self._show_admin_alert_details)
        admin_bot_top_row.addWidget(self.admin_alert_details_btn)
        admin_bot_layout.addLayout(admin_bot_top_row)
        # Admin app inputs: half width (not full screen)
        admin_bot_input_max_w = 420
        admin_bot_layout.addWidget(QLabel("App ID (from Android app after you sign in with access code):"))
        self.admin_bot_id = QLineEdit()
        self.admin_bot_id.setPlaceholderText("Optional: copy from app to receive alerts on your device")
        self.admin_bot_id.setMaximumWidth(admin_bot_input_max_w)
        admin_bot_layout.addWidget(self.admin_bot_id)
        admin_bot_layout.addWidget(QLabel("API Key (from Android app):"))
        self.admin_bot_api_key = QLineEdit()
        try:
            self.admin_bot_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            self.admin_bot_api_key.setEchoMode(QLineEdit.Password)
        self.admin_bot_api_key.setMaximumWidth(admin_bot_input_max_w)
        admin_bot_layout.addWidget(self.admin_bot_api_key)
        admin_bot_layout.addWidget(QLabel("Relay URL (WebSocket — for alerts to reach Android):"))
        self.admin_bot_server = QLineEdit()
        self.admin_bot_server.setText("https://curax-relay.onrender.com")
        self.admin_bot_server.setPlaceholderText("https://curax-relay.onrender.com")
        self.admin_bot_server.setMaximumWidth(admin_bot_input_max_w)
        admin_bot_layout.addWidget(self.admin_bot_server)
        admin_bot_btn_row = QHBoxLayout()
        self.admin_bot_test_btn = QPushButton("📤 Send Test Alert")
        self.admin_bot_test_btn.clicked.connect(self._test_admin_bot)
        self.admin_bot_save_btn = QPushButton("💾 Save Admin App")
        self.admin_bot_save_btn.clicked.connect(self._save_admin_bot)
        admin_bot_btn_row.addWidget(self.admin_bot_test_btn)
        admin_bot_btn_row.addWidget(self.admin_bot_save_btn)
        admin_bot_btn_row.addStretch()
        admin_bot_layout.addLayout(admin_bot_btn_row)
        g_admin_layout.addWidget(self.admin_bot_group)

        # My codes — from server when admin is created (Save Admin Credentials); used to open app
        self.my_codes_group = QGroupBox("🔑 My codes")
        my_codes_layout = QVBoxLayout(self.my_codes_group)
        my_codes_layout.addWidget(QLabel("When you complete Admin setup (Save Admin Credentials), the server gives you these codes. Use the Access Code in the mobile app to open Dashboard, Reminders, and Settings."))
        my_codes_layout.addWidget(QLabel("Admin Access Code (enter in Android app to sign in as admin):"))
        self.admin_access_code_field = QLineEdit()
        self.admin_access_code_field.setPlaceholderText("Shown when admin is created")
        self.admin_access_code_field.setReadOnly(True)
        self.admin_access_code_field.setMaximumWidth(admin_bot_input_max_w)
        try:
            self.admin_access_code_field.setEchoMode(QLineEdit.EchoMode.Password)
        except Exception:
            self.admin_access_code_field.setEchoMode(QLineEdit.Password)
        try:
            self.admin_access_code_field.setStyleSheet("background-color: #f1f5f9; color: #0f172a;")
        except Exception:
            pass
        my_codes_layout.addWidget(self.admin_access_code_field)
        my_codes_layout.addWidget(QLabel("Connection Code (give to users so they can link to you in the app):"))
        self.connection_code_field = QLineEdit()
        self.connection_code_field.setPlaceholderText("Shown when admin is created")
        self.connection_code_field.setReadOnly(True)
        self.connection_code_field.setMaximumWidth(admin_bot_input_max_w)
        try:
            self.connection_code_field.setEchoMode(QLineEdit.EchoMode.Password)
        except Exception:
            self.connection_code_field.setEchoMode(QLineEdit.Password)
        try:
            self.connection_code_field.setStyleSheet("background-color: #f1f5f9; color: #0f172a;")
        except Exception:
            pass
        my_codes_layout.addWidget(self.connection_code_field)
        self._codes_visible = False
        self.codes_show_btn = QPushButton("👁 Show codes")
        self.codes_show_btn.setMaximumWidth(160)
        self.codes_show_btn.clicked.connect(self._toggle_codes_visibility)
        my_codes_layout.addWidget(self.codes_show_btn)
        g_admin_layout.addWidget(self.my_codes_group)

        admin_layout.addWidget(admin_group)

        self.admin_action_btn = QPushButton()
        self.admin_action_btn.clicked.connect(self._handle_admin_login_logout)
        row_action = QHBoxLayout()
        row_action.addWidget(self.admin_action_btn)
        row_action.addStretch()
        admin_layout.addLayout(row_action)

        self._admin_tab_index = 2
        tabs.addTab(admin, "Admin Panel")
        self._settings_tabs = tabs
        # Admin Panel tab hidden until admin logs in (via sidebar Admin Login)
        try:
            tabs.setTabVisible(self._admin_tab_index, False)
        except Exception:
            pass

        c_layout.addWidget(tabs)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        self.controller.admin_status_changed.connect(self._update_admin_tab_visibility)

    def _refresh_admin_ui(self, db=None):
        """Update admin status label and Admin Login/Logout button text from current login state."""
        if not hasattr(self, "admin_status_label") or not hasattr(self, "admin_action_btn"):
            return
        if db is None:
            try:
                db = self.controller.get_db()
            except Exception:
                return
        has_admin = db.has_admin_credentials() if hasattr(db, "has_admin_credentials") else False
        if self.controller.admin_logged_in:
            self.admin_status_label.setText(
                f"✅ Logged in as {self.controller.logged_in_admin_name or 'Admin'} – all features unlocked."
            )
            self.admin_status_label.setStyleSheet(f"color: {NEON_GREEN}; font-size: 9pt;")
            self.admin_action_btn.setText("🔒 Logout")
        elif has_admin:
            self.admin_status_label.setText("🔒 Admin account exists – login to unlock all features.")
            self.admin_status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 9pt;")
            self.admin_action_btn.setText("🔓 Admin Login")
        else:
            self.admin_status_label.setText("⚠️ Admin setup required (fill the form below to create admin).")
            self.admin_status_label.setStyleSheet("color: #f97316; font-size: 9pt;")
            self.admin_action_btn.setText("Create Admin in this panel and Save")

    def _update_admin_tab_visibility(self):
        """Show Admin Panel tab when admin is logged in, or when no admin exists yet (first-time setup)."""
        if not hasattr(self, "_settings_tabs") or not hasattr(self, "_admin_tab_index"):
            return
        try:
            db = self.controller.get_db()
            has_admin = db.has_admin_credentials() if hasattr(db, "has_admin_credentials") else False
            show = bool(getattr(self.controller, "admin_logged_in", False)) or not has_admin
            self._settings_tabs.setTabVisible(self._admin_tab_index, show)
            self._refresh_admin_ui(db)
        except Exception:
            pass

    def _load(self):
        db = self.controller.get_db()
        info = db.get_admin_info() if hasattr(db, "get_admin_info") else None
        if info:
            self.admin_name.setText(info.get("name", ""))
            self.admin_id.setText(info.get("admin_id", ""))
            self.admin_email.setText(info.get("email", ""))
            self.admin_phone.setText(info.get("phone", ""))

        ab = getattr(self.controller, "admin_bot", {})
        self.admin_bot_enabled.setChecked(ab.get("enabled", False))
        self.admin_bot_id.setText(ab.get("bot_id", ""))
        self.admin_bot_api_key.setText(ab.get("api_key", ""))
        self.admin_bot_server.setText(ab.get("server_url") or "https://curax-relay.onrender.com")
        # Access and connection codes come only from when admin was created (Save Admin Credentials), stored in local DB
        if hasattr(self, "admin_access_code_field"):
            access_code = db.get("admin_access_code") if hasattr(db, "get") else None
            connection_code = db.get("admin_connection_code") if hasattr(db, "get") else None
            self.admin_access_code_field.setText(access_code or "")
            if hasattr(self, "connection_code_field"):
                self.connection_code_field.setText(connection_code or "")

        # Show Admin Mobile App and My codes only when admin exists (created via Save Admin Credentials)
        if hasattr(self, "admin_bot_group"):
            self.admin_bot_group.setVisible(db.has_admin_credentials())
        if hasattr(self, "my_codes_group"):
            self.my_codes_group.setVisible(db.has_admin_credentials())

        mob = getattr(self.controller, "mobile_bot", {})
        self.mobile_enabled.setChecked(mob.get("enabled", False))
        self.mobile_bot_id.setText(mob.get("bot_id", ""))
        self.mobile_api_key.setText(mob.get("api_key", ""))
        self.mobile_server.setText(mob.get("server_url") or "https://curax-relay.onrender.com")

        gmail = getattr(self.controller, "gmail_config", {})
        self.gmail_sender.setText(gmail.get("sender_email", ""))
        self.gmail_password.setText(gmail.get("sender_password", ""))
        self.gmail_recipients.setText(gmail.get("recipients", ""))

        theme = getattr(self.controller, "appearance_theme", "light") or "light"
        if str(theme).lower() == "light":
            self.theme_light_radio.setChecked(True)
        else:
            self.theme_dark_radio.setChecked(True)

        dnd = self.controller.alert_settings.get("do_not_disturb", {})
        self.dnd_enabled.setChecked(dnd.get("enabled", False))
        self.dnd_start.setText(dnd.get("start_time", "22:00"))
        self.dnd_end.setText(dnd.get("end_time", "07:00"))

        self._refresh_admin_ui(db)
        self._update_admin_tab_visibility()

    def _save_mobile_settings(self):
        """Save Mobile App settings — admin approval required."""
        if self.main_window and not self.main_window.verify_admin_for_action("Save Mobile App Settings"):
            return
        self._save_system_settings()

    def _save_gmail_settings(self):
        """Save Gmail/Email settings — admin approval required."""
        if self.main_window and not self.main_window.verify_admin_for_action("Save Gmail Settings"):
            return
        self._save_system_settings()

    def _save_appearance_settings(self):
        """Save only the selected appearance/theme (any user can save)."""
        theme = "light" if self.theme_light_radio.isChecked() else "dark"
        self.controller.save_appearance_theme(theme)
        QMessageBox.information(
            self,
            "Appearance",
            "Theme saved. It will be used next time you open CuraX.",
        )

    def apply_theme(self, theme_name: str):
        """
        Adjust title, subtitles, and appearance-section text for dark vs light mode.
        Light mode: prominent title (ACCENT_LIGHT) and body (SECONDARY_LIGHT_DARK).
        """
        name = (theme_name or "light").lower()
        title_color = ACCENT_LIGHT if name == "light" else NEON_GREEN
        secondary = SECONDARY_LIGHT_DARK if name == "light" else TEXT_SECONDARY
        if name == "light":
            main_color = "#0f172a"  # very dark text for radios
        else:
            main_color = "#e5e7eb"  # light text

        try:
            self._title_label.setStyleSheet(
                f"font-size: 18pt; font-weight: bold; color: {title_color};"
            )
            self._sys_desc.setStyleSheet(f"color: {secondary}; font-size: 10pt;")
            self._hint_mobile.setStyleSheet(f"color: {secondary}; font-size: 9pt;")
            self._hint_email.setStyleSheet(f"color: {secondary}; font-size: 9pt;")
            self._hint_dnd.setStyleSheet(f"color: {secondary}; font-size: 9pt;")
        except Exception:
            pass
        try:
            self.theme_label.setStyleSheet(
                f"font-size: 11pt; font-weight: bold; color: {title_color};"
            )
            self.appearance_hint.setStyleSheet(
                f"color: {secondary}; font-size: 9pt;"
            )
            self.theme_dark_radio.setStyleSheet(
                f"font-size: 10pt; font-weight: bold; color: {main_color};"
            )
            self.theme_light_radio.setStyleSheet(
                f"font-size: 10pt; color: {main_color};"
            )
        except Exception:
            pass
        try:
            border = BORDER_LIGHT if name == "light" else BORDER
            bg = "#ffffff" if name == "light" else "#121827"
            section_style = (
                f"QGroupBox {{ border: 1px solid {border}; border-radius: {RADIUS}; "
                f"margin-top: 18px; padding: 24px 14px 14px 14px; background-color: {bg}; }} "
                f"QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 10px 12px 10px; "
                f"color: {title_color}; font-weight: 900; font-size: 17pt; }}"
            )
            for g in (self.mobile_group, self.email_group, self.appearance_group, self.dnd_group):
                g.setStyleSheet(section_style)
        except Exception:
            pass

    def showEvent(self, event):
        """Re-apply section title styles when tab is shown so titles stay bold/accent."""
        try:
            super().showEvent(event)
            theme = getattr(self.controller, "appearance_theme", "light")
            self.apply_theme(theme)
        except Exception:
            super().showEvent(event)

    def _save_system_settings(self):
        """Persist SMS / Gmail / DND settings to controller and DB."""
        mob = getattr(self.controller, "mobile_bot", {})
        mob["enabled"] = self.mobile_enabled.isChecked()
        mob["bot_id"] = self.mobile_bot_id.text().strip()
        mob["api_key"] = self.mobile_api_key.text().strip()
        mob["server_url"] = self.mobile_server.text().strip() or "https://curax-relay.onrender.com"
        self.controller.mobile_bot = mob

        gmail = getattr(self.controller, "gmail_config", {})
        gmail["sender_email"] = self.gmail_sender.text().strip()
        gmail["sender_password"] = self.gmail_password.text().strip()
        gmail["recipients"] = self.gmail_recipients.text().strip()
        self.controller.gmail_config = gmail

        theme = "light" if self.theme_light_radio.isChecked() else "dark"
        self.controller.save_appearance_theme(theme)

        dnd = self.controller.alert_settings.setdefault("do_not_disturb", {})
        dnd["enabled"] = self.dnd_enabled.isChecked()
        start = self.dnd_start.text().strip() or "22:00"
        end = self.dnd_end.text().strip() or "07:00"
        dnd["start_time"] = start
        dnd["end_time"] = end

        try:
            db = self.controller.get_db()
            if hasattr(db, "set"):
                db.set("mobile_bot_config", mob)
                # gmail_config is stored only in Central DB (saved via controller.save_alert_settings -> POST /admin/sync)
            # Central DB: link mobile user to admin if we have admin_id (from logged-in admin or Admin Mobile App)
            central = self.controller.get_central_db()
            if central and mob.get("bot_id") and mob.get("api_key"):
                admin_id = None
                if hasattr(self, "admin_bot_id") and hasattr(self, "admin_bot_api_key"):
                    aid = getattr(self.controller, "admin_bot", {}).get("bot_id") or (self.admin_bot_id.text().strip() if hasattr(self, "admin_bot_id") else "")
                    akey = getattr(self.controller, "admin_bot", {}).get("api_key") or (self.admin_bot_api_key.text().strip() if hasattr(self, "admin_bot_api_key") else "")
                    if aid and akey:
                        admin_id = central.get_admin_id_by_bot(aid, akey)
                if not admin_id and db.has_admin_credentials():
                    info = db.get_admin_info() if hasattr(db, "get_admin_info") else None
                    if info and info.get("admin_id"):
                        admin_id = info.get("admin_id")
                if admin_id:
                    central.upsert_user_from_bot(mob["bot_id"], mob["api_key"], admin_id)
        except Exception:
            pass

        try:
            self.controller.save_alert_settings()
        except Exception:
            pass

        QMessageBox.information(self, "Saved", "System settings saved.")

    def _test_mobile_bot(self):
        """Send a test alert via mobile app using current (unsaved) settings. Admin only."""
        if self.main_window and not self.main_window.verify_admin_for_action("Test Mobile App"):
            return
        enabled = self.mobile_enabled.isChecked()
        bot_id = self.mobile_bot_id.text().strip()
        api_key = self.mobile_api_key.text().strip()
        server = self.mobile_server.text().strip() or "https://curax-relay.onrender.com"
        if not enabled or not bot_id or not api_key:
            QMessageBox.warning(self, "Mobile App", "Enable mobile alerts and fill App ID and API Key first.")
            return
        prev = dict(getattr(self.controller, "mobile_bot", {}))
        self.controller.mobile_bot = {
            "enabled": True,
            "bot_id": bot_id,
            "api_key": api_key,
            "server_url": server,
        }
        ok = False
        try:
            ok = self.controller.send_mobile_alert("test", "Test alert from CuraX settings")
        except Exception:
            ok = False
        self.controller.mobile_bot = prev
        if ok:
            QMessageBox.information(self, "Mobile App", "Test alert sent successfully (if app is running).")
        else:
            QMessageBox.warning(self, "Mobile App", "Failed to send test alert. Check app settings and server.")

    def _show_admin_alert_details(self):
        """Show dialog listing alerts that admin will receive (when credentials are saved)."""
        msg = (
            "Admin will receive these alerts (when Admin App credentials are saved and enabled):\n\n"
            "• System started\n"
            "• System unlocked\n"
            "• Admin panel login\n"
            "• Medicine taken (when someone marks dose taken)\n"
            "• Missed medicine (15 min and 30 min escalation)\n"
            "• Expiry alerts\n"
            "• Stock alerts (empty / low stock)\n"
            "• Daily summary (medicine status + today's dose log at 23:00)"
        )
        QMessageBox.information(self, "Alert details", msg)

    def _toggle_codes_visibility(self):
        """Toggle access and connection code fields between hidden (password-style) and visible."""
        try:
            normal_mode = QLineEdit.EchoMode.Normal
            password_mode = QLineEdit.EchoMode.Password
        except Exception:
            normal_mode = QLineEdit.Normal
            password_mode = QLineEdit.Password
        self._codes_visible = not self._codes_visible
        if self._codes_visible:
            self.admin_access_code_field.setEchoMode(normal_mode)
            self.connection_code_field.setEchoMode(normal_mode)
            self.codes_show_btn.setText("🙈 Hide codes")
        else:
            self.admin_access_code_field.setEchoMode(password_mode)
            self.connection_code_field.setEchoMode(password_mode)
            self.codes_show_btn.setText("👁 Show codes")

    def _save_admin_bot(self):
        """Save Admin Mobile App credentials (ID, API Key, Relay URL). Does not change access/connection codes (those are set only when admin is created)."""
        ab = getattr(self.controller, "admin_bot", {})
        ab["enabled"] = self.admin_bot_enabled.isChecked()
        ab["bot_id"] = self.admin_bot_id.text().strip()
        ab["api_key"] = self.admin_bot_api_key.text().strip()
        ab["server_url"] = self.admin_bot_server.text().strip() or "https://curax-relay.onrender.com"
        self.controller.admin_bot = ab
        self.controller.save_admin_bot_config()
        central = self.controller.get_central_db()
        if central and ab.get("bot_id") and ab.get("api_key"):
            name = self.admin_name.text().strip() if hasattr(self, "admin_name") else ""
            email = self.admin_email.text().strip() if hasattr(self, "admin_email") else ""
            aid, _admin_access_code, _connection_code = central.upsert_admin_from_bot(ab["bot_id"], ab["api_key"], name=name, email=email)
            if aid:
                QMessageBox.information(self, "Saved", "Saved successfully.")
            else:
                QMessageBox.warning(self, "Saved", "Saved locally. Central DB update failed.")
        else:
            QMessageBox.information(self, "Saved", "Saved successfully.")

    def _test_admin_bot(self):
        """Send a test alert via admin app using current (unsaved) settings."""
        if self.main_window and not self.main_window.verify_admin_for_action("Test Admin App"):
            return
        enabled = self.admin_bot_enabled.isChecked()
        bot_id = self.admin_bot_id.text().strip()
        api_key = self.admin_bot_api_key.text().strip()
        server = self.admin_bot_server.text().strip() or "https://curax-relay.onrender.com"
        if not enabled or not bot_id or not api_key:
            QMessageBox.warning(self, "Admin App", "Enable admin alerts and fill App ID and API Key first.")
            return
        prev = dict(getattr(self.controller, "admin_bot", {}))
        self.controller.admin_bot = {
            "enabled": True,
            "bot_id": bot_id,
            "api_key": api_key,
            "server_url": server,
        }
        ok = False
        try:
            ok = self.controller.send_admin_alert("test", "Test alert from CuraX Admin Panel")
        except Exception:
            ok = False
        self.controller.admin_bot = prev
        if ok:
            QMessageBox.information(self, "Admin App", "Test alert sent successfully (if admin app is running).")
        else:
            QMessageBox.warning(self, "Admin App", "Failed to send test alert. Check app settings and server.")

    def _test_gmail(self):
        """Send a test email using current (unsaved) Gmail settings. Admin only."""
        if self.main_window and not self.main_window.verify_admin_for_action("Test Gmail Alerts"):
            return
        sender = self.gmail_sender.text().strip()
        pwd = self.gmail_password.text().strip()
        recips = self.gmail_recipients.text().strip()
        if not sender or not pwd:
            QMessageBox.warning(self, "Gmail Alerts", "Sender email and app password are required.")
            return
        prev = dict(getattr(self.controller, "gmail_config", {}))
        self.controller.gmail_config = {
            "sender_email": sender,
            "sender_password": pwd,
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 465,
            "recipients": recips,
        }
        ok = False
        try:
            self.controller.alert_scheduler.send_gmail_alert(
                "CuraX Test Email",
                "This is a test alert from CuraX Settings."
            )
            ok = True
        except Exception:
            ok = False
        self.controller.gmail_config = prev
        if ok:
            QMessageBox.information(self, "Gmail Alerts", "Test email sent (check your inbox/spam).")
        else:
            QMessageBox.warning(self, "Gmail Alerts", "Failed to send test email. Check Gmail settings and app password.")

    def _change_password(self):
        """
        Change device password: ask for current, then new + confirm, like Tkinter flow.
        """
        if self.main_window and not self.main_window.verify_admin_for_action("Change Device Password"):
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Change Device Password")
        layout = QVBoxLayout(dlg)

        title = QLabel("Change Device Password")
        title.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {NEON_GREEN};")
        layout.addWidget(title)

        info = QLabel("Enter current password to verify, then set a new password.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(info)

        form = QFormLayout()
        current_edit = QLineEdit()
        new_edit = QLineEdit()
        confirm_edit = QLineEdit()
        try:
            current_edit.setEchoMode(QLineEdit.EchoMode.Password)
            new_edit.setEchoMode(QLineEdit.EchoMode.Password)
            confirm_edit.setEchoMode(QLineEdit.EchoMode.Password)
        except AttributeError:
            current_edit.setEchoMode(QLineEdit.Password)
            new_edit.setEchoMode(QLineEdit.Password)
            confirm_edit.setEchoMode(QLineEdit.Password)

        new_edit.setEnabled(False)
        confirm_edit.setEnabled(False)

        current_row = QHBoxLayout()
        current_row.addWidget(current_edit)
        verify_btn = QPushButton("Verify Current")
        current_row.addWidget(verify_btn)
        form.addRow("Current password:", current_row)

        form.addRow("New password:", new_edit)
        form.addRow("Confirm password:", confirm_edit)
        layout.addLayout(form)

        status = QLabel("")
        status.setStyleSheet(f"color: {TEXT_SECONDARY};")
        layout.addWidget(status)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Save New Password")
        ok_btn.setEnabled(False)  # enabled only after successful verify
        cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        verified = {"ok": False}

        def on_verify():
            pwd = current_edit.text().strip()
            if not pwd:
                status.setText("❌ Enter current password.")
                status.setStyleSheet("color: #ef4444;")
                return
            if len(pwd) != 4 or not pwd.isdigit():
                status.setText("❌ Password must be 4 digits (numbers only).")
                status.setStyleSheet("color: #ef4444;")
                return

            status.setText("Verifying current password...")
            status.setStyleSheet("color: #facc15;")

            try:
                from PyQt6.QtWidgets import QApplication
            except ImportError:
                from PyQt5.QtWidgets import QApplication
            QApplication.processEvents()

            success, msg = self.controller.verify_pin_esp32(pwd)
            if success:
                verified["ok"] = True
                status.setText("✅ Current password verified.")
                status.setStyleSheet("color: #22c55e;")
                current_edit.setEnabled(False)
                verify_btn.setEnabled(False)
                verify_btn.setText("Verified")
                new_edit.setEnabled(True)
                confirm_edit.setEnabled(True)
                ok_btn.setEnabled(True)
                new_edit.setFocus()
            else:
                verified["ok"] = False
                if msg:
                    if "not responding" in msg.lower() or "not respond" in msg.lower():
                        msg = "ESP32 did not respond in time. Check cable and power, then try again."
                    status.setText(f"❌ {msg}")
                else:
                    status.setText("❌ Current password is incorrect or device did not respond.")
                status.setStyleSheet("color: #ef4444;")
                new_edit.clear()
                confirm_edit.clear()
                new_edit.setEnabled(False)
                confirm_edit.setEnabled(False)
                ok_btn.setEnabled(False)

        def on_ok():
            if not verified["ok"]:
                status.setText("❌ Verify current password first.")
                status.setStyleSheet("color: #ef4444;")
                return
            current = current_edit.text().strip()
            new = new_edit.text().strip()
            confirm = confirm_edit.text().strip()
            if not current or not new or not confirm:
                status.setText("❌ All fields are required.")
                status.setStyleSheet("color: #f97316;")
                return
            if new != confirm:
                status.setText("❌ New and confirm passwords do not match.")
                status.setStyleSheet("color: #ef4444;")
                return
            ok, msg = self.controller.change_device_password(current, new)
            if ok:
                QMessageBox.information(self, "Device Password", msg)
                dlg.accept()
            else:
                status.setText(f"❌ {msg}")
                status.setStyleSheet("color: #ef4444;")

        verify_btn.clicked.connect(on_verify)
        ok_btn.clicked.connect(on_ok)
        cancel_btn.clicked.connect(dlg.reject)

        dlg.exec()

    def _setup_admin(self):
        """Create admin: email, password, name, id → Central DB creates admin and generates access_code + connection_code. Then show Admin Mobile App section and codes."""
        name = self.admin_name.text().strip()
        admin_id_str = self.admin_id.text().strip() or name or "admin"
        email = self.admin_email.text().strip()
        phone = self.admin_phone.text().strip()
        password = self.admin_password.text().strip()
        if not name or not email or not password:
            QMessageBox.warning(self, "Validation", "Name, email, and password are required.")
            return
        db = self.controller.get_db()
        if db.has_admin_credentials():
            if self.main_window and not self.main_window.verify_admin_for_action("Update Admin Panel"):
                return
        central = self.controller.get_central_db() if hasattr(self.controller, "get_central_db") else None
        aid, access_code, connection_code = None, None, None
        is_new_admin = not db.has_admin_credentials()
        if central and is_new_admin:
            # Create admin in Central DB (generated app credentials for this admin)
            bot_id = str(uuid.uuid4())[:8]
            api_key = uuid.uuid4().hex[:16]
            try:
                aid, access_code, connection_code = central.upsert_admin_from_bot(bot_id, api_key, name=name, email=email)
            except Exception:
                aid, access_code, connection_code = None, None, None
            if aid:
                if access_code:
                    db.set("admin_access_code", access_code)
                if connection_code:
                    db.set("admin_connection_code", connection_code)
                ab = getattr(self.controller, "admin_bot", {})
                ab["bot_id"] = bot_id
                ab["api_key"] = api_key
                ab["server_url"] = ab.get("server_url") or "https://curax-relay.onrender.com"
                self.controller.admin_bot = ab
                self.controller.save_admin_bot_config()
        elif not is_new_admin:
            info = db.get_admin_info() if hasattr(db, "get_admin_info") else None
            admin_id_str = (info.get("admin_id") or admin_id_str) if info else admin_id_str
        if db.set_admin_credentials(name, str(aid or admin_id_str), email, phone, password):
            try:
                self.controller.admin_status_changed.emit()
            except Exception:
                pass
            self._load()
            if hasattr(self, "admin_bot_group"):
                self.admin_bot_group.setVisible(True)
            if hasattr(self, "my_codes_group"):
                self.my_codes_group.setVisible(True)
            if hasattr(self, "admin_access_code_field") and access_code:
                self.admin_access_code_field.setText(access_code)
            if hasattr(self, "connection_code_field") and connection_code:
                self.connection_code_field.setText(connection_code)
            msg = "Admin saved successfully. All data is stored on the server; the app loads it when you open Dashboard."
            QMessageBox.information(self, "Saved", msg)
        else:
            QMessageBox.warning(self, "Error", "Failed to save admin.")

    def _delete_admin_account(self):
        """Delete admin account completely (admin-protected, with confirmations)."""
        db = self.controller.get_db()
        if not db.has_admin_credentials():
            QMessageBox.information(self, "Admin", "No admin account exists to delete.")
            return
        if self.main_window and not self.main_window.verify_admin_for_action("Delete Admin Account"):
            return

        confirm = QMessageBox.question(
            self,
            "Delete Admin Account",
            "⚠ This will permanently delete the current admin account.\n\n"
            "You will need to create a new admin account afterwards.\n\n"
            "Are you sure you want to continue?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        final = QMessageBox.question(
            self,
            "Final Confirmation",
            "This action CANNOT be undone.\n\nDelete admin account now?",
        )
        if final != QMessageBox.StandardButton.Yes:
            return

        access_code = db.get("admin_access_code") if hasattr(db, "get") else None
        if access_code and isinstance(access_code, str) and access_code.strip() and hasattr(self.controller, "delete_admin_from_backend"):
            try:
                self.controller.delete_admin_from_backend(access_code.strip())
            except Exception:
                pass

        if db.delete_admin_account():
            try:
                db.delete("admin_access_code")
            except Exception:
                pass
            try:
                db.delete("admin_connection_code")
            except Exception:
                pass
            try:
                self.controller.admin_logout()
            except Exception:
                self.controller.admin_logged_in = False
                self.controller.logged_in_admin_name = None
            QMessageBox.information(
                self,
                "Admin",
                "Admin account deleted successfully.\nYou can now create a new admin account.",
            )
            self._load()
        else:
            QMessageBox.warning(self, "Admin", "Failed to delete admin account.")

    def _handle_admin_login_logout(self):
        """Mirror Tkinter admin panel's login/logout buttons using MainWindow helpers."""
        db = self.controller.get_db()
        has_admin = db.has_admin_credentials()
        if not has_admin:
            QMessageBox.information(
                self,
                "Admin",
                "No admin account configured yet.\nFill the Admin Setup / Update form and save.",
            )
            return

        if self.controller.admin_logged_in:
            if self.main_window:
                confirm = QMessageBox.question(
                    self,
                    "Logout Admin",
                    f"Logout {self.controller.logged_in_admin_name or 'Admin'}?\n\nAll admin-only features will be locked again.",
                )
                if confirm != QMessageBox.StandardButton.Yes:
                    return
            self.controller.admin_logout()
            self._load()
        else:
            if self.main_window:
                if self.main_window.open_admin_login_dialog():
                    self._load()
