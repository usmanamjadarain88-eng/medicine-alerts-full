try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
        QDateEdit, QTextEdit, QScrollArea, QFrame, QSizePolicy
    )
    from PyQt6.QtCore import Qt, QDate
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
        QDateEdit, QTextEdit, QScrollArea, QFrame, QSizePolicy
    )
    from PyQt5.QtCore import Qt, QDate

from ui.styles import (
    NEON_GREEN,
    NEON_GREEN_DIM,
    BG_CARD,
    BG_CARD_LIGHT,
    BG_INPUT,
    BG_INPUT_LIGHT,
    BORDER,
    TEXT_PRIMARY,
    TEXT_PRIMARY_LIGHT,
    ACCENT_LIGHT,
    SECONDARY_LIGHT_DARK,
)


class AddMedicineTab(QWidget):
    def __init__(self, controller, main_window=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.main_window = main_window
        self._input_fields = []
        self._build_ui()
        self.apply_theme(getattr(controller, "appearance_theme", "light"))

    def apply_theme(self, theme_name: str):
        name = (theme_name or "light").lower()
        title_color = ACCENT_LIGHT if name == "light" else NEON_GREEN
        try:
            self._title_label.setStyleSheet(
                f"font-size: 18pt; font-weight: bold; color: {title_color};"
            )
        except Exception:
            pass
        if name == "light":
            border_color = NEON_GREEN_DIM
            input_bg = BG_INPUT_LIGHT
            style = f"border: 2px solid {border_color}; border-radius: 6px; background-color: {input_bg};"
            popup_bg = BG_CARD_LIGHT
            popup_fg = TEXT_PRIMARY_LIGHT
        else:
            input_bg = "#000000"
            style = f"border: 1px solid {BORDER}; border-radius: 6px; background-color: {input_bg};"
            popup_bg = "#0a0e17"
            popup_fg = TEXT_PRIMARY

        try:
            from PyQt6.QtWidgets import QComboBox  # type: ignore
        except Exception:  # pragma: no cover - PyQt5 fallback
            from PyQt5.QtWidgets import QComboBox  # type: ignore

        for w in self._input_fields:
            try:
                base = style
                if isinstance(w, QComboBox):
                    combo_extra = (
                        f"background-color: {input_bg}; color: {popup_fg}; "
                        "QComboBox::drop-down { background: transparent; border: none; width: 24px; } "
                        f"QComboBox QAbstractItemView {{ background-color: {popup_bg}; color: {popup_fg}; }}"
                    )
                    base = (
                        f"{style} "
                        "min-height: 32px; padding: 6px 10px; font-size: 11pt; "
                        + combo_extra
                    )
                    if w == getattr(self, "med_hour", None) or w == getattr(self, "med_minute", None):
                        base = (
                            f"{style} "
                            "min-height: 32px; padding: 6px 8px; font-size: 12pt; font-weight: bold; "
                            + combo_extra
                        )
                w.setStyleSheet(base)
            except Exception:
                continue

    def _build_ui(self):
        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")
        try:
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        except AttributeError:
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        container = QWidget()
        try:
            container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        except AttributeError:
            container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        self._title_label = QLabel("Add New Medicine")
        self._title_label.setStyleSheet(f"font-size: 18pt; font-weight: bold; color: {NEON_GREEN};")
        layout.addWidget(self._title_label)

        form_wrapper = QWidget()
        form_wrapper.setMaximumWidth(560)
        form_layout = QVBoxLayout(form_wrapper)
        form_layout.setSpacing(12)
        form_layout.setContentsMargins(0, 0, 0, 0)

        def _row_two_col(left_label, left_widget, right_label, right_widget):
            row = QHBoxLayout()
            row.setSpacing(20)
            left_cell = QWidget()
            left_lo = QVBoxLayout(left_cell)
            left_lo.setContentsMargins(0, 0, 0, 0)
            left_lo.setSpacing(4)
            left_lo.addWidget(left_label)
            left_lo.addWidget(left_widget)
            right_cell = QWidget()
            right_lo = QVBoxLayout(right_cell)
            right_lo.setContentsMargins(0, 0, 0, 0)
            right_lo.setSpacing(4)
            right_lo.addWidget(right_label)
            right_lo.addWidget(right_widget)
            row.addWidget(left_cell, 1)
            row.addWidget(right_cell, 1)
            return row

        lbl_style = "font-size: 11pt;"

        lbl_name = QLabel("💊 Medicine Name:")
        lbl_name.setStyleSheet(lbl_style)
        self.med_name = QLineEdit()
        self.med_name.setPlaceholderText("e.g. Paracetamol")
        self._input_fields.append(self.med_name)
        lbl_qty = QLabel("📦 Quantity:")
        lbl_qty.setStyleSheet(lbl_style)
        self.med_qty = QSpinBox()
        self.med_qty.setRange(1, 1000)
        self.med_qty.setValue(30)
        self._input_fields.append(self.med_qty)
        form_layout.addLayout(_row_two_col(lbl_name, self.med_name, lbl_qty, self.med_qty))

        lbl_dose = QLabel("💊 Dose per Day:")
        lbl_dose.setStyleSheet(lbl_style)
        self.med_dose = QSpinBox()
        self.med_dose.setRange(1, 10)
        self.med_dose.setValue(1)
        self._input_fields.append(self.med_dose)
        lbl_expiry = QLabel("📅 Expiry Date:")
        lbl_expiry.setStyleSheet(lbl_style)
        self.med_expiry = QDateEdit()
        self.med_expiry.setDate(QDate.currentDate().addYears(1))
        self.med_expiry.setCalendarPopup(True)
        cal = self.med_expiry.calendarWidget()
        if cal is not None:
            cal.setMinimumSize(300, 260)
        self._input_fields.append(self.med_expiry)
        form_layout.addLayout(_row_two_col(lbl_dose, self.med_dose, lbl_expiry, self.med_expiry))

        lbl_period = QLabel("🕒 Intake Period:")
        lbl_period.setStyleSheet(lbl_style)
        self.med_period = QComboBox()
        self.med_period.addItems(["Morning (6 AM - 10 AM)", "Afternoon (12 PM - 4 PM)", "Night (8 PM - 10 PM)"])
        self.med_period.setMinimumHeight(32)
        self._input_fields.append(self.med_period)
        lbl_box = QLabel("📥 Assign to Box:")
        lbl_box.setStyleSheet(lbl_style)
        self.med_box = QComboBox()
        self.med_box.addItems(["B1", "B2", "B3", "B4", "B5", "B6"])
        self._input_fields.append(self.med_box)
        form_layout.addLayout(_row_two_col(lbl_period, self.med_period, lbl_box, self.med_box))

        lbl_time = QLabel("⏰ Exact Time (Hour:Minute):")
        lbl_time.setStyleSheet(lbl_style)
        form_layout.addWidget(lbl_time)
        time_widget = QWidget()
        time_widget.setMaximumWidth(250)
        time_row = QHBoxLayout(time_widget)
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(10)
        self.med_hour = QComboBox()
        self.med_hour.addItems([f"{i:02d}" for i in range(0, 24)])
        self.med_hour.setCurrentText("08")
        self.med_hour.setMinimumWidth(64)
        self.med_hour.setMinimumHeight(32)
        self.med_minute = QComboBox()
        self.med_minute.addItems([f"{i:02d}" for i in range(0, 60, 5)])
        self.med_minute.setCurrentText("00")
        self.med_minute.setMinimumWidth(64)
        self.med_minute.setMinimumHeight(32)
        time_colon = QLabel(" : ")
        time_colon.setStyleSheet("font-size: 14pt; font-weight: bold;")
        time_row.addWidget(self.med_hour)
        time_row.addWidget(time_colon)
        time_row.addWidget(self.med_minute)
        time_row.addStretch()
        self._input_fields.extend([self.med_hour, self.med_minute])
        form_layout.addWidget(time_widget)

        lbl_instr = QLabel("📝 Instructions:")
        lbl_instr.setStyleSheet(lbl_style)
        form_layout.addWidget(lbl_instr)
        self.med_instructions = QTextEdit()
        self.med_instructions.setMaximumHeight(64)
        self.med_instructions.setPlaceholderText("Optional instructions")
        form_layout.addWidget(self.med_instructions)
        self._input_fields.append(self.med_instructions)

        self.save_btn = QPushButton("🔒 Save Medicine")
        self.save_btn.clicked.connect(self._save_medicine)
        self.save_btn.setMinimumHeight(38)
        self.save_btn.setMaximumWidth(280)  # half of form container, like Exact Time block
        self.save_btn.setStyleSheet(
            f"background-color: {NEON_GREEN_DIM}; color: #0a0e17; font-weight: bold; "
            "font-size: 11pt; padding: 8px 20px; border-radius: 8px; border: none;"
        )
        form_layout.addWidget(self.save_btn)
        form_layout.addSpacing(16)  # space below button so it’s not cut off when scrolled to bottom

        layout.addWidget(form_wrapper)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _save_medicine(self):
        if not self.controller.require_admin():
            return
        if self.main_window and not self.main_window.verify_admin_for_action("Add/Edit Medicine"):
            return
        name = self.med_name.text().strip()
        if not name:
            from PyQt6.QtWidgets import QMessageBox
            try:
                QMessageBox.warning(self, "Validation", "Medicine name is required.")
            except Exception:
                from PyQt5.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Validation", "Medicine name is required.")
            return
        box_id = self.med_box.currentText()
        exact_time = f"{self.med_hour.currentText()}:{self.med_minute.currentText()}"
        period_map = {
            "Morning (6 AM - 10 AM)": "Morning",
            "Afternoon (12 PM - 4 PM)": "Afternoon",
            "Night (8 PM - 10 PM)": "Night",
        }
        medicine = {
            "name": name,
            "quantity": self.med_qty.value(),
            "dose_per_day": self.med_dose.value(),
            "expiry": self.med_expiry.date().toString("yyyy-MM-dd"),
            "exact_time": exact_time,
            "period": period_map.get(self.med_period.currentText(), "Morning"),
            "instructions": self.med_instructions.toPlainText().strip(),
        }
        self.controller.medicine_boxes[box_id] = medicine
        self.controller.save_data()
        self.controller.alert_scheduler.cancel_medicine_alerts_for_box(box_id)
        self.controller.alert_scheduler.schedule_medicine_alert(medicine, box_id)
        self.controller.medicine_updated.emit()
        self.med_name.clear()
        self.med_qty.setValue(30)
        self.med_dose.setValue(1)
        self.med_instructions.clear()
        msg = f"Medicine saved to {box_id}."
        self.controller._log(msg)
        self.controller.status_message.emit(msg)
        try:
            from PyQt6.QtWidgets import QMessageBox
        except ImportError:
            from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self, "Saved", msg)
