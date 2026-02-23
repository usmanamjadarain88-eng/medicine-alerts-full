import time

try:
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QFrame
    )
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QKeyEvent, QFont, QPalette, QColor
except ImportError:
    from PyQt5.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QFrame
    )
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QKeyEvent, QFont, QPalette, QColor

from theme.tokens import NEON_GREEN, BORDER

KEYPAD_BTN_LIGHT = (
    "background-color: #ffffff; "
    "color: #000000; "
    "border: 1px solid #cbd5e1; "
    "border-radius: 5px; "
    "padding: 2px; "
    "font-size: 12pt; "
    "font-weight: bold; "
    "min-width: 38px; "
    "min-height: 28px;"
)
KEYPAD_BTN_DARK = (
    "background-color: #1e2a42; "
    "color: #f1f5f9; "
    "border: 1px solid #334155; "
    "border-radius: 5px; "
    "padding: 2px; "
    "font-size: 12pt; "
    "font-weight: bold; "
    "min-width: 38px; "
    "min-height: 28px;"
)


class PinDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.pin = ""
        self.wrong_attempts = 0
        self._theme = (getattr(parent, "_current_theme", None) or getattr(controller, "appearance_theme", "light") or "light").lower()
        if self._theme not in ("dark", "light"):
            self._theme = "light"
        self.setWindowTitle("Enter PIN - CuraX Authentication")
        self.setMinimumSize(300, 380)
        self.setMaximumWidth(380)
        self._build_ui()
        self._apply_theme(self._theme)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        self._icon = QLabel("🔒")
        layout.addWidget(self._icon, alignment=Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel("System Authentication")
        layout.addWidget(self._title, alignment=Qt.AlignmentFlag.AlignCenter)
        self._subtitle = QLabel("Enter 4-digit PIN")
        layout.addWidget(self._subtitle, alignment=Qt.AlignmentFlag.AlignCenter)
        display_frame = QFrame()
        self._display_frame = display_frame
        display_layout = QVBoxLayout(display_frame)
        self.display = QLabel("____")
        display_layout.addWidget(self.display, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(display_frame)
        self.status = QLabel("Enter PIN")
        layout.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignCenter)
        try:
            keypad_font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        except AttributeError:
            keypad_font = QFont("Segoe UI", 12, QFont.Bold)
        keypad = QGridLayout()
        self._keypad_btns = []
        self._spacers = []
        buttons = [
            ("1", "2", "3"),
            ("4", "5", "6"),
            ("7", "8", "9"),
            ("",  "0", ""),
        ]
        for row, row_btns in enumerate(buttons):
            for col, txt in enumerate(row_btns):
                if not txt:
                    spacer = QLabel("")
                    self._spacers.append(spacer)
                    keypad.addWidget(spacer, row, col)
                    continue
                btn = QPushButton(txt)
                btn.setFont(keypad_font)
                btn.setToolTip("Digit " + txt)
                btn.clicked.connect(lambda checked, d=txt: self._add_digit(d))
                self._keypad_btns.append(btn)
                keypad.addWidget(btn, row, col)
        layout.addLayout(keypad)
        btn_row = QHBoxLayout()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        self._clear_btn = QPushButton("Clear PIN")
        self._clear_btn.setToolTip("Clear all digits")
        self._clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._clear_btn)
        layout.addLayout(btn_row)

    def apply_theme(self, theme_name: str):
        self._theme = (theme_name or "light").lower()
        if self._theme not in ("dark", "light"):
            self._theme = "light"
        self._apply_theme(self._theme)

    def _apply_theme(self, theme: str):
        dark = theme == "dark"
        if dark:
            self.setStyleSheet(
                "QDialog { background-color: #000000; }\n"
                "QLabel { background-color: transparent; color: #f1f5f9; }"
            )
            self._icon.setStyleSheet("font-size: 16pt; color: #f1f5f9;")
            self._title.setStyleSheet(f"font-size: 12pt; font-weight: bold; color: {NEON_GREEN};")
            self._subtitle.setStyleSheet("font-size: 9pt; color: #94a3b8;")
            self._display_frame.setStyleSheet(
                f"background-color: #0a0e17; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px;"
            )
            self._display_normal = "font-size: 18pt; font-weight: bold; color: #f1f5f9; letter-spacing: 5px;"
            self._display_success = "font-size: 18pt; font-weight: bold; color: #00E6A8; letter-spacing: 5px;"
            self._display_error = "font-size: 18pt; font-weight: bold; color: #ef4444; letter-spacing: 5px;"
            self._status_enter = f"font-size: 9pt; color: {NEON_GREEN};"
            self._status_error = "font-size: 9pt; color: #ef4444;"
            self._status_success = f"font-size: 9pt; color: {NEON_GREEN};"
            self._status_verifying = "font-size: 9pt; color: #facc15;"
            for btn in self._keypad_btns:
                btn.setStyleSheet(KEYPAD_BTN_DARK)
            for s in self._spacers:
                s.setStyleSheet("background-color: #000000; border: none;")
            self._cancel_btn.setStyleSheet(
                "min-height: 30px; min-width: 68px; font-size: 10pt; font-weight: bold; "
                "background-color: #b91c1c; color: #ffffff; border: 1px solid #991b1b; border-radius: 6px;"
            )
            self._clear_btn.setStyleSheet(
                f"background-color: #1e2a42; color: #f1f5f9; border: 1px solid {BORDER}; "
                "border-radius: 6px; padding: 4px 8px; font-size: 10pt; font-weight: bold; min-height: 30px; min-width: 72px;"
            )
        else:
            self.setStyleSheet(
                "QDialog { background-color: #f8fafc; }\n"
                "QLabel { background-color: transparent; color: #334155; }"
            )
            self._icon.setStyleSheet("font-size: 16pt;")
            self._title.setStyleSheet(f"font-size: 12pt; font-weight: bold; color: {NEON_GREEN};")
            self._subtitle.setStyleSheet("font-size: 9pt; color: #64748b;")
            self._display_frame.setStyleSheet(
                "background-color: #ffffff; border: 1px solid #1e293b; border-radius: 6px; padding: 6px;"
            )
            self._display_normal = "font-size: 18pt; font-weight: bold; color: #0a0e17; letter-spacing: 5px;"
            self._display_success = "font-size: 18pt; font-weight: bold; color: #00E6A8; letter-spacing: 5px;"
            self._display_error = "font-size: 18pt; font-weight: bold; color: #ef4444; letter-spacing: 5px;"
            self._status_enter = f"font-size: 9pt; color: {NEON_GREEN};"
            self._status_error = "font-size: 9pt; color: #ef4444;"
            self._status_success = f"font-size: 9pt; color: {NEON_GREEN};"
            self._status_verifying = "font-size: 9pt; color: #facc15;"
            for btn in self._keypad_btns:
                btn.setStyleSheet(KEYPAD_BTN_LIGHT)
            for s in self._spacers:
                s.setStyleSheet("background-color: #f8fafc; border: none;")
            self._cancel_btn.setStyleSheet(
                "min-height: 30px; min-width: 68px; font-size: 10pt; font-weight: bold; "
                "background-color: #b91c1c; color: #ffffff; border: 1px solid #991b1b; border-radius: 6px;"
            )
            self._clear_btn.setStyleSheet(
                "background-color: #ffffff; color: #000000; border: 1px solid #cbd5e1; "
                "border-radius: 6px; padding: 4px 8px; font-size: 10pt; font-weight: bold; min-height: 30px; min-width: 72px;"
            )
        self.display.setStyleSheet(self._display_normal)
        self.status.setStyleSheet(self._status_enter)
        self.status.setText("Enter PIN")

    def _display_text(self):
        txt = "".join("●" if i < len(self.pin) else "_" for i in range(4))
        self.display.setText(txt)

    def _add_digit(self, digit):
        if len(self.pin) < 4:
            self.pin += digit
            self._display_text()
            self.status.setText(f"PIN: {self.pin}")
            if len(self.pin) == 4:
                QTimer.singleShot(300, self._verify)

    def _backspace(self):
        if self.pin:
            self.pin = self.pin[:-1]
            self._display_text()
            self.status.setText(f"PIN: {self.pin}" if self.pin else "Enter PIN")

    def _clear(self):
        self.pin = ""
        self._display_text()
        self.status.setText("Enter PIN")
        self.status.setStyleSheet(getattr(self, "_status_enter", f"font-size: 9pt; color: {NEON_GREEN};"))
        self.display.setStyleSheet(getattr(self, "_display_normal", "font-size: 18pt; font-weight: bold; color: #0a0e17; letter-spacing: 5px;"))

    def _verify(self):
        if len(self.pin) != 4:
            self.status.setText("× PIN must be 4 digits")
            self.status.setStyleSheet(getattr(self, "_status_error", "color: #ef4444;"))
            return
        self.status.setText("Verifying...")
        self.status.setStyleSheet(getattr(self, "_status_verifying", "color: #facc15;"))
        self.repaint()
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            from PyQt5.QtWidgets import QApplication
        QApplication.processEvents()
        from auth.verify_esp32 import verify_pin_esp32
        success, msg = verify_pin_esp32(self.controller, self.pin)
        if success:
            self.controller.authenticated = True
            self.controller.authenticated_changed.emit(True)
            self.display.setText("✓✓✓✓")
            self.display.setStyleSheet(getattr(self, "_display_success", "font-size: 18pt; font-weight: bold; color: #00E6A8; letter-spacing: 5px;"))
            self.status.setText("✓ PIN verified!")
            self.status.setStyleSheet(getattr(self, "_status_success", "color: #00E6A8;"))
            QTimer.singleShot(800, self.accept)
        else:
            if "not responding" in msg.lower() or "not respond" in msg.lower():
                msg = "ESP32 did not respond in time. Check USB cable and that ESP32 is ON, then try again."
            self.status.setText(f"× {msg}")
            self.status.setStyleSheet(getattr(self, "_status_error", "color: #ef4444;") + " font-size: 9pt;")
            self.display.setText("✗✗✗✗")
            self.display.setStyleSheet(getattr(self, "_display_error", "font-size: 18pt; font-weight: bold; color: #ef4444; letter-spacing: 5px;"))
            QTimer.singleShot(1500, self._clear)

    def keyPressEvent(self, event):
        try:
            key = event.key()
            text = event.text()
            if text and len(text) == 1 and text.isdigit():
                self._add_digit(text)
                return
            try:
                key_to_digit = {
                    Qt.Key.Key_0: "0", Qt.Key.Key_1: "1", Qt.Key.Key_2: "2", Qt.Key.Key_3: "3",
                    Qt.Key.Key_4: "4", Qt.Key.Key_5: "5", Qt.Key.Key_6: "6", Qt.Key.Key_7: "7",
                    Qt.Key.Key_8: "8", Qt.Key.Key_9: "9",
                }
                for i in range(10):
                    k = getattr(Qt.Key, f"Key_Keypad{i}", None)
                    if k is not None:
                        key_to_digit[k] = str(i)
            except Exception:
                key_to_digit = {}
            digit = key_to_digit.get(key)
            if digit is not None:
                self._add_digit(digit)
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._verify()
                return
            if key == Qt.Key.Key_Backspace:
                self._backspace()
                return
            if key == Qt.Key.Key_Escape:
                self.reject()
                return
        except AttributeError:
            try:
                k = key
                if k in (Qt.Key_Return, Qt.Key_Enter):
                    self._verify()
                    return
                if k == Qt.Key_Backspace:
                    self._backspace()
                    return
                if getattr(Qt, "Key_Escape", None) is not None and k == Qt.Key_Escape:
                    self.reject()
                    return
                keypad = getattr(Qt, "Key_Keypad0", None)
                if keypad is not None and keypad <= k <= getattr(Qt, "Key_Keypad9", keypad):
                    self._add_digit(str(k - keypad))
                    return
                if Qt.Key_0 <= k <= Qt.Key_9:
                    self._add_digit(str(k - Qt.Key_0))
                    return
            except Exception:
                pass
        super().keyPressEvent(event)
