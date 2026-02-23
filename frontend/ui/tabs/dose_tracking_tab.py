import datetime
try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QFrame, QTableWidget, QTableWidgetItem,
        QHeaderView, QAbstractItemView, QScrollArea
    )
    from PyQt6.QtCore import Qt
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QPushButton, QFrame, QTableWidget, QTableWidgetItem,
        QHeaderView, QAbstractItemView, QScrollArea
    )
    from PyQt5.QtCore import Qt

from ui.styles import NEON_GREEN, TEXT_SECONDARY, TEXT_SECONDARY_LIGHT, RADIUS, ACCENT_LIGHT, SECONDARY_LIGHT_DARK


class DoseTrackingTab(QWidget):
    def __init__(self, controller, main_window=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.main_window = main_window
        self._init_theme_styles(getattr(controller, "appearance_theme", "light"))
        self._build_ui()
        controller.medicine_updated.connect(self._refresh)

    def _init_theme_styles(self, theme_name: str):
        """Prepare card and button styles for the given theme."""
        name = (theme_name or "light").lower()
        if name == "light":
            self._title_color = ACCENT_LIGHT
            self._secondary_text_color = SECONDARY_LIGHT_DARK
            card_bg = "#ffffff"
            border = "#000000"
            self._btn_style_inactive = (
                "background-color: #e5f2ff; "
                "color: #0f172a; "
                "border: 1px solid #cbd5e1; "
                "border-radius: 6px; "
                "padding: 4px 10px; "
                "font-weight: bold;"
            )
            self._btn_style_active = (
                "background-color: #22c55e; "
                "color: #022c22; "
                "border: 1px solid #16a34a; "
                "border-radius: 6px; "
                "padding: 4px 10px; "
                "font-weight: bold;"
            )
        else:
            self._title_color = NEON_GREEN
            self._secondary_text_color = TEXT_SECONDARY
            card_bg = "#0d1117"
            border = "#21262d"
            self._btn_style_inactive = (
                "background-color: #161b22; "
                "color: #e6edf3; "
                "border: 1px solid #21262d; "
                "border-radius: 8px; "
                "padding: 6px 12px; "
                "font-weight: bold;"
            )
            self._btn_style_active = (
                "background-color: #238636; "
                "color: #ffffff; "
                "border: 1px solid #2ea043; "
                "border-radius: 8px; "
                "padding: 6px 12px; "
                "font-weight: bold;"
            )
        self._card_style_normal = f"""
            background-color: {card_bg};
            border: 1px solid {border};
            border-radius: {RADIUS};
        """
        self._card_style_selected = f"""
            background-color: {card_bg};
            border: 2px solid {NEON_GREEN};
            border-radius: {RADIUS};
        """

    def apply_theme(self, theme_name: str):
        """Called from MainWindow when theme changes at runtime."""
        self._init_theme_styles(theme_name)
        try:
            self._title_label.setStyleSheet(
                f"font-size: 18pt; font-weight: bold; color: {self._title_color};"
            )
            self._subtitle_label.setStyleSheet(
                f"color: {self._secondary_text_color}; font-weight: bold;"
            )
            if hasattr(self, "_title_history"):
                self._title_history.setStyleSheet(
                    f"font-size: 14pt; font-weight: bold; color: {self._title_color};"
                )
        except Exception:
            pass
        for idx, (card, box_id) in enumerate(self.dose_cards):
            card.setStyleSheet(self._card_style_normal)
            btn, med_label, qty_label, _ = self.dose_buttons[idx]
            btn.setStyleSheet(self._btn_style_inactive)
            med_label.setStyleSheet(f"color: {self._secondary_text_color};")
            qty_label.setStyleSheet(f"color: {self._secondary_text_color};")
        self._update_card_highlight()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        self._title_label = QLabel("Dose Tracking & History")
        self._title_label.setStyleSheet(
            f"font-size: 18pt; font-weight: bold; color: {getattr(self, '_title_color', NEON_GREEN)};"
        )
        layout.addWidget(self._title_label)
        self._subtitle_label = QLabel("Click a box to turn ON its LED and take medicine. Then Mark Dose Taken.")
        self._subtitle_label.setStyleSheet(
            f"color: {getattr(self, '_secondary_text_color', TEXT_SECONDARY)}; font-weight: bold;"
        )
        layout.addWidget(self._subtitle_label)

        grid = QGridLayout()
        self.dose_buttons = []
        self.dose_cards = []
        for i in range(1, 7):
            box_id = f"B{i}"
            card = QFrame()
            card.setObjectName("card")
            card.setStyleSheet(self._card_style_normal)
            card_layout = QVBoxLayout(card)
            btn = QPushButton(f"○ {box_id}")
            btn.setStyleSheet(self._btn_style_inactive)
            btn.clicked.connect(lambda checked, b=box_id: self._on_box_click(b))
            card_layout.addWidget(btn)
            med_label = QLabel("Empty")
            med_label.setStyleSheet(f"color: {self._secondary_text_color};")
            card_layout.addWidget(med_label)
            qty_label = QLabel("0 left")
            qty_label.setStyleSheet(f"color: {self._secondary_text_color};")
            card_layout.addWidget(qty_label)
            self.dose_buttons.append((btn, med_label, qty_label, box_id))
            self.dose_cards.append((card, box_id))
            grid.addWidget(card, (i - 1) // 3, (i - 1) % 3)
        layout.addLayout(grid)

        btn_row = QHBoxLayout()
        off_btn = QPushButton("🔴 Turn OFF All LEDs")
        off_btn.setObjectName("danger")
        off_btn.setStyleSheet("padding: 6px 16px; font-size: 10pt;")
        off_btn.clicked.connect(self._turn_off_leds)
        mark_btn = QPushButton("✅ Mark Dose Taken")
        mark_btn.setStyleSheet("padding: 6px 16px; font-size: 10pt;")
        mark_btn.clicked.connect(self._mark_dose)
        btn_row.addWidget(off_btn)
        btn_row.addWidget(mark_btn)
        layout.addLayout(btn_row)

        self._title_history = QLabel("📜 Dose History")
        self._title_history.setStyleSheet(
            f"font-size: 14pt; font-weight: bold; color: {getattr(self, '_title_color', NEON_GREEN)};"
        )
        layout.addWidget(self._title_history)
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Timestamp", "Box", "Medicine", "Dose Taken", "Remaining"])
        try:
            self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        except AttributeError:
            self.table.horizontalHeader().setResizeMode(QHeaderView.Stretch)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(230)
        layout.addWidget(self.table)

        scroll.setWidget(container)
        outer.addWidget(scroll)

        self._refresh()

    def _on_box_click(self, box_id):
        if not self.controller.require_admin():
            try:
                from PyQt6.QtWidgets import QMessageBox
            except ImportError:
                from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Admin Setup Required",
                "Features are locked because no admin account exists.\n\n"
                "Go to Settings → Admin Panel to create an admin account first.",
            )
            return

        if self.controller.connected and self.controller.authenticated:
            self.controller.send_led_on(box_id)
        else:
            self.controller.active_led_box = box_id
        self._update_card_highlight()

    def _turn_off_leds(self):
        if self.controller.connected and self.controller.authenticated:
            self.controller.send_led_all_off()
        else:
            self.controller.active_led_box = None
        self._update_card_highlight()

    def _update_card_highlight(self):
        active = self.controller.active_led_box
        for idx, (card, box_id) in enumerate(self.dose_cards):
            card.setStyleSheet(self._card_style_selected if box_id == active else self._card_style_normal)
            btn, med_label, qty_label, b_id = self.dose_buttons[idx]
            if box_id == active:
                btn.setText(f"📍 {box_id}")
                btn.setStyleSheet(self._btn_style_active)
            else:
                btn.setText(f"○ {box_id}")
                btn.setStyleSheet(self._btn_style_inactive)

    def _mark_dose(self):
        if not self.controller.require_admin():
            try:
                from PyQt6.QtWidgets import QMessageBox
            except ImportError:
                from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Admin Setup Required",
                "Features are locked because no admin account exists.\n\n"
                "Go to Settings → Admin Panel to create an admin account first.",
            )
            return

        box_id = self.controller.active_led_box
        if not box_id:
            try:
                from PyQt6.QtWidgets import QMessageBox
            except ImportError:
                from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Select Box", "Click a box first to select it.")
            return
        med = self.controller.medicine_boxes.get(box_id)
        if not med:
            try:
                from PyQt6.QtWidgets import QMessageBox
            except ImportError:
                from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No Medicine", f"No medicine in {box_id}.")
            return

        current_qty = med.get("quantity", 0)
        dose_per_day = med.get("dose_per_day", 1) or 1

        if current_qty < dose_per_day:
            try:
                from PyQt6.QtWidgets import QMessageBox
            except ImportError:
                from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self,
                "Not Enough Medicine",
                f"Not enough {med.get('name', 'medicine')} available in {box_id} "
                f"to take {dose_per_day} dose(s).",
            )
            return

        qty = current_qty - dose_per_day
        med["quantity"] = qty
        med["last_dose_taken"] = datetime.datetime.now().isoformat()

        self.controller.dose_log.append(
            {
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "box": box_id,
                "medicine": med.get("name", ""),
                "dose_taken": dose_per_day,
                "remaining": qty,
            }
        )
        self.controller.save_data()
        self.controller.medicine_updated.emit()
        # Admin-only alert: medicine taken (full message for admin)
        try:
            name = med.get("name", "Medicine")
            msg = f"Medicine \"{name}\" taken from box {box_id}. Remaining quantity is {qty}."
            self.controller.send_admin_alert("dose_taken", msg)
        except Exception:
            pass
        if self.controller.connected and self.controller.authenticated:
            self.controller.send_led_off(box_id)
        self.controller.active_led_box = None
        self._update_card_highlight()

    def _refresh(self):
        for btn, med_label, qty_label, box_id in self.dose_buttons:
            med = self.controller.medicine_boxes.get(box_id)
            if med:
                med_label.setText(med.get("name", "Unknown"))
                qty_label.setText(f"{med.get('quantity', 0)} left")
            else:
                med_label.setText("Empty")
                qty_label.setText("0 left")
        self._update_card_highlight()
        self.table.setRowCount(0)
        for row, log in enumerate(reversed(self.controller.dose_log)):
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(log.get("timestamp", "")))
            self.table.setItem(row, 1, QTableWidgetItem(log.get("box", "")))
            self.table.setItem(row, 2, QTableWidgetItem(log.get("medicine", "")))
            self.table.setItem(row, 3, QTableWidgetItem(str(log.get("dose_taken", 0))))
            self.table.setItem(row, 4, QTableWidgetItem(str(log.get("remaining", ""))))
