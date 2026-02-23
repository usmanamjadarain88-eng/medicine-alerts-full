try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QListWidget, QListWidgetItem, QGroupBox, QLineEdit, QTimeEdit,
        QComboBox, QTabWidget, QMessageBox, QDialog, QDialogButtonBox,
        QFormLayout, QScrollArea, QFrame, QDateEdit,
        QTableWidget, QTableWidgetItem, QCheckBox
    )
    from PyQt6.QtCore import Qt, QTime, QDate
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
        QListWidget, QListWidgetItem, QGroupBox, QLineEdit, QTimeEdit,
        QComboBox, QTabWidget, QMessageBox, QDialog, QDialogButtonBox,
        QFormLayout, QScrollArea, QFrame, QDateEdit,
        QTableWidget, QTableWidgetItem, QCheckBox
    )
    from PyQt5.QtCore import Qt, QTime, QDate

from ui.styles import NEON_GREEN, TEXT_SECONDARY, CARD_STYLE, ACCENT_LIGHT, SECONDARY_LIGHT_DARK


class AddReminderDialog(QDialog):
    def __init__(self, reminder_type, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Reminder")
        self.reminder_type = reminder_type
        layout = QFormLayout(self)
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Title / Name")
        layout.addRow("Title:", self.title_edit)

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Location / Clinic / Pharmacy (optional)")
        layout.addRow("Location:", self.location_edit)

        self.date_edit = QDateEdit()
        try:
            self.date_edit.setDate(QDate.currentDate())
        except AttributeError:
            self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        cal = self.date_edit.calendarWidget()
        if cal is not None:
            cal.setMinimumSize(300, 260)
        layout.addRow("Date:", self.date_edit)

        self.time_edit = QTimeEdit()
        self.time_edit.setTime(QTime.currentTime())
        layout.addRow("Time:", self.time_edit)

        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("Description (optional)")
        layout.addRow("Description:", self.desc_edit)

        self.cb_24h = QCheckBox("24 hours before")
        self.cb_24h.setChecked(True)
        self.cb_2h = QCheckBox("2 hours before")
        self.cb_2h.setChecked(True)
        self.cb_alert = QCheckBox("Send mobile/email alert")
        self.cb_alert.setChecked(True)
        layout.addRow("", self.cb_24h)
        layout.addRow("", self.cb_2h)
        layout.addRow("", self.cb_alert)
        try:
            bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        except TypeError:
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addRow(bb)

    def get_reminder(self):
        return {
            "title": self.title_edit.text().strip(),
            "date": self.date_edit.date().toString("yyyy-MM-dd"),
            "time": self.time_edit.time().toString("HH:mm"),
            "description": self.desc_edit.text().strip(),
            "location": self.location_edit.text().strip(),
            "reminders": {
                "24h": self.cb_24h.isChecked(),
                "2h": self.cb_2h.isChecked(),
                "alert": self.cb_alert.isChecked(),
            },
        }


class MedicalRemindersTab(QWidget):
    def __init__(self, controller, main_window=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.main_window = main_window
        self._build_ui()
        self._refresh_all()
        self.apply_theme(getattr(controller, "appearance_theme", "light"))

    def apply_theme(self, theme_name: str):
        """Title and subtitle: light mode uses ACCENT_LIGHT and SECONDARY_LIGHT_DARK."""
        name = (theme_name or "light").lower()
        title_color = ACCENT_LIGHT if name == "light" else NEON_GREEN
        secondary = SECONDARY_LIGHT_DARK if name == "light" else TEXT_SECONDARY
        try:
            self._title_label.setStyleSheet(
                f"font-size: 18pt; font-weight: bold; color: {title_color};"
            )
            self._subtitle_label.setStyleSheet(f"color: {secondary};")
        except Exception:
            pass

    def _build_ui(self):
        outer = QVBoxLayout(self)
        self._title_label = QLabel("Medical Reminders & Appointments")
        self._title_label.setStyleSheet(f"font-size: 18pt; font-weight: bold; color: {NEON_GREEN};")
        outer.addWidget(self._title_label)
        self._subtitle_label = QLabel("Manage appointments, prescriptions, lab tests, and custom reminders.")
        self._subtitle_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        outer.addWidget(self._subtitle_label)

        quick_row = QHBoxLayout()
        for key, label in [
            ("appointments", "📅 Add Appointment"),
            ("prescriptions", "💊 Add Prescription"),
            ("lab_tests", "🧪 Add Lab Test"),
            ("custom", "🔔 Custom Reminder"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked, k=key: self._add_reminder(k))
            quick_row.addWidget(btn)
        outer.addLayout(quick_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)

        self.tabs = QTabWidget()

        all_page = QWidget()
        all_layout = QVBoxLayout(all_page)
        self.all_table = QTableWidget()
        self.all_table.setColumnCount(7)
        self.all_table.setHorizontalHeaderLabels(
            ["Type", "Title / Doctor", "Date", "Time", "Location / Details", "Reminders", "Status"]
        )
        try:
            from PyQt6.QtWidgets import QAbstractItemView, QHeaderView
            self.all_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.all_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.all_table.horizontalHeader().setStretchLastSection(True)
        except Exception:
            pass
        all_layout.addWidget(self.all_table)
        all_btn_row = QHBoxLayout()
        self.all_delete_btn = QPushButton("🗑️ Delete Selected Reminder (Admin)")
        self.all_delete_btn.clicked.connect(self._delete_from_all)
        self.all_save_btn = QPushButton("💾 Save All Reminders")
        self.all_save_btn.clicked.connect(self._save)
        all_btn_row.addWidget(self.all_delete_btn)
        all_btn_row.addWidget(self.all_save_btn)
        all_layout.addLayout(all_btn_row)
        self.tabs.addTab(all_page, "📋 All Reminders")

        self._type_tables = {}
        for key, label in [
            ("appointments", "📅 Appointments"),
            ("prescriptions", "💊 Prescriptions"),
            ("lab_tests", "🔬 Lab Tests"),
            ("custom", "📌 Custom"),
        ]:
            page = QWidget()
            page_layout = QVBoxLayout(page)

            table = QTableWidget()
            if key == "appointments":
                headers = ["Doctor", "Specialty", "Date", "Time", "Location", "24h / 2h", "Status"]
            elif key == "prescriptions":
                headers = ["Medicine", "Doctor", "Expiry", "Pharmacy", "7d / 3d / 1d", "Status"]
            elif key == "lab_tests":
                headers = ["Test Name", "Date", "Time", "Location", "Status"]
            else:  # custom
                headers = ["Title", "Date", "Time", "Description", "Status"]
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            try:
                from PyQt6.QtWidgets import QAbstractItemView, QHeaderView
                table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
                table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
                table.horizontalHeader().setStretchLastSection(True)
            except Exception:
                pass
            page_layout.addWidget(table)

            self._type_tables[key] = table
            self.tabs.addTab(page, label)

        export_page = QWidget()
        export_layout = QVBoxLayout(export_page)
        info = QLabel(
            "Export, import, and backup your medical reminders and related settings.\n\n"
            "• Export: save reminders to JSON.\n"
            "• Import: load reminders from a JSON file.\n"
            "• Backup All: save reminders + alert settings + email/SMS + medicine data."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {TEXT_SECONDARY};")
        export_layout.addWidget(info)

        btn_row_exp = QHBoxLayout()
        export_btn = QPushButton("⬇️ Export Reminders")
        export_btn.clicked.connect(self._export)
        import_btn = QPushButton("⬆️ Import Reminders")
        import_btn.clicked.connect(self._import)
        backup_btn = QPushButton("🗄️ Backup All Data")
        backup_btn.clicked.connect(self._backup_all)
        btn_row_exp.addWidget(export_btn)
        btn_row_exp.addWidget(import_btn)
        btn_row_exp.addWidget(backup_btn)
        export_layout.addLayout(btn_row_exp)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        export_layout.addWidget(self._status_label)

        self.tabs.addTab(export_page, "⬇️ Export / Import")
        layout.addWidget(self.tabs)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _add_reminder(self, key):
        if key != "custom" and self.main_window:
            if not self.main_window.verify_admin_for_action("Add Medical Reminder"):
                return

        d = AddReminderDialog(key, self)
        try:
            Accepted = QDialog.DialogCode.Accepted
        except AttributeError:
            Accepted = QDialog.Accepted
        if d.exec() == Accepted:
            r = d.get_reminder()
            if not r["title"]:
                QMessageBox.warning(self, "Validation", "Title is required.")
                return
            self.controller.medical_reminders[key].append(r)
            self.controller.save_medical_reminders()
            self._refresh_all()
            rem = r.get("reminders", {})
            parts = []
            if rem.get("24h"):
                parts.append("24h before")
            if rem.get("2h"):
                parts.append("2h before")
            if parts:
                try:
                    self.controller.status_message.emit(
                        f"Reminder saved. Alerts will go automatically: {', '.join(parts)}."
                    )
                except Exception:
                    pass

    def _delete_selected(self, key):
        return

    def _delete_from_all(self):
        """Delete from All Reminders view (admin-protected)."""
        if self.main_window and not self.main_window.verify_admin_for_action("Delete Medical Reminder"):
            return
        row = self.all_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Delete", "Select a reminder row first.")
            return
        index = 0
        for key in ["appointments", "prescriptions", "lab_tests", "custom"]:
            lst = self.controller.medical_reminders.get(key, [])
            if row < index + len(lst):
                inner_index = row - index
                lst.pop(inner_index)
                self.controller.save_medical_reminders()
                self._refresh_all()
                QMessageBox.information(self, "Deleted", "Reminder removed.")
                return
            index += len(lst)

    def _export(self):
        if self.main_window and not self.main_window.verify_admin_for_action("Export Medical Reminders"):
            return
        import json
        import os
        try:
            from PyQt6.QtWidgets import QFileDialog
        except ImportError:
            from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Export Reminders", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.controller.medical_reminders, f, indent=2)
            msg = f"Exported to {os.path.basename(path)}"
            if self._status_label:
                self._status_label.setText(f"✅ {msg}")
            QMessageBox.information(self, "Export", msg)
        except Exception as e:
            if self._status_label:
                self._status_label.setText(f"❌ Export failed: {e}")
            QMessageBox.warning(self, "Export Failed", str(e))

    def _import(self):
        if self.main_window and not self.main_window.verify_admin_for_action("Import Medical Reminders"):
            return
        import json
        import os
        try:
            from PyQt6.QtWidgets import QFileDialog
        except ImportError:
            from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "Import Reminders", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Invalid file format")
            self.controller.medical_reminders = data
            self._refresh_all()
            if self._status_label:
                self._status_label.setText(f"✅ Reminders imported from {os.path.basename(path)}")
            QMessageBox.information(self, "Import", f"Imported from {os.path.basename(path)}")
        except Exception as e:
            if self._status_label:
                self._status_label.setText(f"❌ Import failed: {e}")
            QMessageBox.warning(self, "Import Failed", str(e))

    def _backup_all(self):
        if self.main_window and not self.main_window.verify_admin_for_action("Backup All Data"):
            return
        import json
        import os
        try:
            from PyQt6.QtWidgets import QFileDialog
        except ImportError:
            from PyQt5.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Backup All Data", "", "JSON (*.json)")
        if not path:
            return
        try:
            backup = {
                "medical_reminders": self.controller.medical_reminders,
                "alert_settings": self.controller.alert_settings,
                "gmail_config": getattr(self.controller, "gmail_config", {}),
                "sms_config": getattr(self.controller, "sms_config", {}),
                "medicine_boxes": self.controller.medicine_boxes,
                "dose_log": self.controller.dose_log,
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(backup, f, indent=2)
            msg = f"Backup saved to {os.path.basename(path)}"
            if self._status_label:
                self._status_label.setText(f"✅ {msg}")
            QMessageBox.information(self, "Backup", msg)
        except Exception as e:
            if self._status_label:
                self._status_label.setText(f"❌ Backup failed: {e}")
            QMessageBox.warning(self, "Backup Failed", str(e))

    def _refresh_all(self):
        """Refresh per-type tables and combined 'All Reminders' table."""
        for key, table in self._type_tables.items():
            data = self.controller.medical_reminders.get(key, [])
            table.setRowCount(len(data))
            for row, r in enumerate(data):
                if key == "appointments":
                    reminders = r.get("reminders", {})
                    rem_txt = ", ".join(
                        part for part, flag in [("24h", reminders.get("24h")), ("2h", reminders.get("2h"))]
                        if flag
                    ) or "—"
                    values = [
                        r.get("doctor") or r.get("title", ""),
                        r.get("specialty") or r.get("description", ""),
                        r.get("date", ""),
                        r.get("time", ""),
                        r.get("location", ""),
                        rem_txt,
                        r.get("status", "scheduled"),
                    ]
                elif key == "prescriptions":
                    reminders = r.get("reminders", {})
                    rem_txt = ", ".join(
                        part for part, flag in [("7d", reminders.get("7d")), ("3d", reminders.get("3d")), ("1d", reminders.get("1d"))]
                        if flag
                    ) or ", ".join(
                        part for part, flag in [("24h", reminders.get("24h")), ("2h", reminders.get("2h"))]
                        if flag
                    ) or "—"
                    values = [
                        r.get("medicine") or r.get("title", ""),
                        r.get("doctor") or r.get("description", ""),
                        r.get("expiry_date") or r.get("date", ""),
                        r.get("pharmacy") or r.get("location", ""),
                        rem_txt,
                        r.get("status", "active"),
                    ]
                elif key == "lab_tests":
                    values = [
                        r.get("test_name") or r.get("title", ""),
                        r.get("date", ""),
                        r.get("time", ""),
                        r.get("location", ""),
                        r.get("status", "scheduled"),
                    ]
                else:  # custom
                    reminders = r.get("reminders", {})
                    rem_txt = ", ".join(
                        part for part, flag in [("24h", reminders.get("24h")), ("2h", reminders.get("2h"))]
                        if flag
                    ) or "—"
                    values = [
                        r.get("title", ""),
                        r.get("date", ""),
                        r.get("time", ""),
                        r.get("description", ""),
                        r.get("status", "active"),
                    ]
                for col, val in enumerate(values):
                    table.setItem(row, col, QTableWidgetItem(str(val)))

        all_rows = []
        for key in ["appointments", "prescriptions", "lab_tests", "custom"]:
            for r in self.controller.medical_reminders.get(key, []):
                if key == "appointments":
                    reminders = r.get("reminders", {})
                    rem_txt = ", ".join(
                        part for part, flag in [("24h", reminders.get("24h")), ("2h", reminders.get("2h"))]
                        if flag
                    ) or "—"
                    title_or_doc = r.get("doctor") or r.get("title", "—")
                    row = [
                        "Appointment",
                        title_or_doc,
                        r.get("date", ""),
                        r.get("time", ""),
                        r.get("location", ""),
                        rem_txt,
                        r.get("status", "scheduled"),
                    ]
                elif key == "prescriptions":
                    reminders = r.get("reminders", {})
                    rem_txt = ", ".join(
                        part for part, flag in [("7d", reminders.get("7d")), ("3d", reminders.get("3d")), ("1d", reminders.get("1d"))]
                        if flag
                    ) or ", ".join(
                        part for part, flag in [("24h", reminders.get("24h")), ("2h", reminders.get("2h"))]
                        if flag
                    ) or "—"
                    med = r.get("medicine") or r.get("title", "")
                    doc = r.get("doctor") or r.get("description", "")
                    pharm = r.get("pharmacy") or r.get("location", "")
                    loc_detail = f"By: {doc} @ {pharm}" if (doc or pharm) else (r.get("location") or r.get("description", "") or "—")
                    row = [
                        "Prescription",
                        med,
                        r.get("expiry_date") or r.get("date", ""),
                        r.get("time", ""),
                        loc_detail,
                        rem_txt,
                        r.get("status", "active"),
                    ]
                elif key == "lab_tests":
                    row = [
                        "Lab Test",
                        r.get("test_name") or r.get("title", ""),
                        r.get("date", ""),
                        r.get("time", ""),
                        r.get("location", ""),
                        "—",
                        r.get("status", "scheduled"),
                    ]
                else:
                    reminders = r.get("reminders", {})
                    rem_txt = ", ".join(
                        part for part, flag in [("24h", reminders.get("24h")), ("2h", reminders.get("2h"))]
                        if flag
                    ) or "—"
                    row = [
                        "Custom",
                        r.get("title", ""),
                        r.get("date", ""),
                        r.get("time", ""),
                        r.get("description", "")[:60],
                        rem_txt,
                        r.get("status", "active"),
                    ]
                all_rows.append(row)

        self.all_table.setRowCount(len(all_rows))
        for row_idx, row_vals in enumerate(all_rows):
            for col, val in enumerate(row_vals):
                self.all_table.setItem(row_idx, col, QTableWidgetItem(str(val)))

    def _save(self):
        if self.main_window and not self.main_window.verify_admin_for_action("Save Medical Reminders"):
            return
        self.controller.save_medical_reminders()
        QMessageBox.information(self, "Saved", "Reminders saved.")
