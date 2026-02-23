try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QGroupBox, QSlider, QFrame,
        QScrollArea, QCheckBox, QDoubleSpinBox, QPushButton
    )
    from PyQt6.QtCore import Qt
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QGroupBox, QSlider, QFrame,
        QScrollArea, QCheckBox, QDoubleSpinBox, QPushButton
    )
    from PyQt5.QtCore import Qt

from ui.styles import (
    NEON_GREEN,
    TEXT_SECONDARY,
    ACCENT_LIGHT,
    SECONDARY_LIGHT_DARK,
    BORDER,
    TEXT_PRIMARY,
)
BORDER_LIGHT_DARK = "#94a3b8"


class TempAdjustmentTab(QWidget):
    def __init__(self, controller, main_window=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.main_window = main_window
        self._build_ui()
        controller.temperature_update.connect(self._on_temp_update)
        self._refresh()
        self.apply_theme(getattr(controller, "appearance_theme", "light"))

    def apply_theme(self, theme_name: str):
        """Title, subtitle, status by theme. Peltier buttons: neutral secondary style (not primary green)."""
        name = (theme_name or "light").lower()
        title_color = ACCENT_LIGHT if name == "light" else NEON_GREEN
        secondary = SECONDARY_LIGHT_DARK if name == "light" else TEXT_SECONDARY
        try:
            self._title_label.setStyleSheet(
                f"font-size: 18pt; font-weight: bold; color: {title_color};"
            )
            self._subtitle_label.setStyleSheet(f"color: {secondary};")
            self.status_label.setStyleSheet(f"color: {secondary}; font-size: 9pt;")
        except Exception:
            pass
        if name == "light":
            input_style_light = (
                f"background-color: #ffffff; color: #0f172a; "
                f"border: 1px solid {BORDER_LIGHT_DARK}; border-radius: 6px; padding: 6px 8px;"
            )
            btn_style_light = (
                "background-color: #f1f5f9; color: #334155; font-weight: 600; "
                "padding: 10px 16px; border-radius: 8px; min-width: 165px; max-width: 165px; min-height: 36px; "
                "border: 1px solid #cbd5e1;"
            )
            quick_style_light = (
                "background-color: #f1f5f9; color: #334155; font-weight: 600; "
                "padding: 10px 16px; border-radius: 8px; min-height: 36px; border: 1px solid #cbd5e1;"
            )
            for key in ["peltier1", "peltier2"]:
                for attr in ["min_spin", "max_spin"]:
                    w = getattr(self, f"{key}_{attr}", None)
                    if w is not None:
                        w.setStyleSheet(input_style_light)
                btn = getattr(self, f"{key}_apply_btn", None)
                if btn is not None:
                    btn.setStyleSheet(btn_style_light)
            if hasattr(self, "apply_both_btn"):
                self.apply_both_btn.setStyleSheet(quick_style_light)
            if hasattr(self, "refresh_btn"):
                self.refresh_btn.setStyleSheet(quick_style_light)
        else:
            input_style = (
                "background-color: #0f172a; color: {0}; "
                "border: 1px solid {1}; border-radius: 6px; padding: 6px 8px;"
            ).format(TEXT_PRIMARY, BORDER)
            btn_style_dark = (
                "background-color: #1e293b; color: #e2e8f0; font-weight: 600; "
                "padding: 10px 16px; border-radius: 8px; min-width: 165px; max-width: 165px; min-height: 36px; "
                "border: 1px solid #475569;"
            )
            quick_style_dark = (
                "background-color: #1e293b; color: #e2e8f0; font-weight: 600; "
                "padding: 10px 16px; border-radius: 8px; min-height: 36px; border: 1px solid #475569;"
            )
            for key in ["peltier1", "peltier2"]:
                for attr in ["min_spin", "max_spin"]:
                    w = getattr(self, f"{key}_{attr}", None)
                    if w is not None:
                        w.setStyleSheet(input_style)
                btn = getattr(self, f"{key}_apply_btn", None)
                if btn is not None:
                    btn.setStyleSheet(btn_style_dark)
            if hasattr(self, "apply_both_btn"):
                self.apply_both_btn.setStyleSheet(quick_style_dark)
            if hasattr(self, "refresh_btn"):
                self.refresh_btn.setStyleSheet(quick_style_dark)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)

        self._title_label = QLabel("🌡️ Temperature Control System")
        self._title_label.setStyleSheet(f"font-size: 18pt; font-weight: bold; color: {NEON_GREEN};")
        layout.addWidget(self._title_label)
        self._subtitle_label = QLabel(
            "Control Peltier modules for medicine storage:\n"
            "• Peltier 1: Boxes B1–B4 (normal medicines)\n"
            "• Peltier 2: Boxes B5–B6 (cold medicines)"
        )
        self._subtitle_label.setStyleSheet(f"color: {TEXT_SECONDARY};")
        self._subtitle_label.setWordWrap(True)
        layout.addWidget(self._subtitle_label)

        self.status_label = QLabel("Temperatures update automatically when ESP32 sends TEMP1/TEMP2 data.")
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 9pt;")
        layout.addWidget(self.status_label)

        grid = QHBoxLayout()

        self._build_peltier_panel(
            grid,
            zone_title="❄️ Peltier 1 (Boxes B1–B4)",
            key="peltier1",
            min_range=(10.0, 25.0),
            max_range=(10.0, 25.0),
            default_min=15.0,
            default_max=20.0,
            current_color=NEON_GREEN,
        )

        self._build_peltier_panel(
            grid,
            zone_title="🧊 Peltier 2 (Boxes B5–B6)",
            key="peltier2",
            min_range=(2.0, 10.0),
            max_range=(2.0, 10.0),
            default_min=5.0,
            default_max=8.0,
            current_color="#4a6fa5",
        )

        layout.addLayout(grid)

        quick_group = QGroupBox("⚡ Quick Actions")
        qlayout = QHBoxLayout(quick_group)
        self.apply_both_btn = QPushButton("Apply Both Peltiers")
        self.apply_both_btn.clicked.connect(self._apply_both)
        self.refresh_btn = QPushButton("Refresh Temperatures")
        self.refresh_btn.clicked.connect(self._refresh_temps)
        qlayout.addWidget(self.apply_both_btn)
        qlayout.addWidget(self.refresh_btn)
        layout.addWidget(quick_group)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_peltier_panel(
        self,
        parent_layout,
        zone_title: str,
        key: str,
        min_range,
        max_range,
        default_min: float,
        default_max: float,
        current_color: str,
    ):
        g = QGroupBox(zone_title)
        g.setMinimumWidth(280)  # So "Apply to Peltier" button is not clipped
        gl = QVBoxLayout(g)
        gl.setSpacing(6)

        ts = self.controller.temp_settings.get(key, {})

        cb = QCheckBox(f"Enable {zone_title.split()[1]}")
        cb.setChecked(ts.get("enabled", True))
        gl.addWidget(cb)
        setattr(self, f"{key}_enabled_cb", cb)

        gl.addWidget(QLabel("Temperature Range (°C):"))

        min_row = QHBoxLayout()
        min_row.addWidget(QLabel("Min:"))
        min_spin = QDoubleSpinBox()
        min_spin.setRange(*min_range)
        min_spin.setDecimals(1)
        min_spin.setSingleStep(0.5)
        min_spin.setValue(ts.get("min", default_min))
        min_row.addWidget(min_spin)
        min_row.addWidget(QLabel("°C"))
        min_row.addStretch()
        gl.addLayout(min_row)

        max_row = QHBoxLayout()
        max_row.addWidget(QLabel("Max:"))
        max_spin = QDoubleSpinBox()
        max_spin.setRange(*max_range)
        max_spin.setDecimals(1)
        max_spin.setSingleStep(0.5)
        max_spin.setValue(ts.get("max", default_max))
        max_row.addWidget(max_spin)
        max_row.addWidget(QLabel("°C"))
        max_row.addStretch()
        gl.addLayout(max_row)

        setattr(self, f"{key}_min_spin", min_spin)
        setattr(self, f"{key}_max_spin", max_spin)

        gl.addWidget(QLabel("Current Temperature:"))
        curr_label = QLabel("— °C")
        curr_label.setStyleSheet(f"font-size: 14pt; font-weight: bold; color: {current_color};")
        gl.addWidget(curr_label)
        setattr(self, f"_curr_{key}", curr_label)

        try:
            slider = QSlider(Qt.Orientation.Horizontal)
        except AttributeError:
            slider = QSlider(Qt.Horizontal)
        slider.setRange(int(min_range[0]) - 5, int(max_range[1]) + 5)
        slider.setEnabled(False)
        gl.addWidget(slider)
        setattr(self, f"_slider_{key}", slider)

        apply_btn = QPushButton(f"Apply to {zone_title.split()[1]}")
        apply_btn.setMinimumWidth(165)
        apply_btn.setMaximumWidth(165)
        apply_btn.setMinimumHeight(36)
        apply_btn.clicked.connect(lambda _, k=key: self._apply_single(k))
        gl.addWidget(apply_btn)
        setattr(self, f"{key}_apply_btn", apply_btn)

        parent_layout.addWidget(g)

    def _on_temp_update(self, line):
        try:
            if "TEMP1:" in line:
                parts = line.split("TEMP1:")[1].strip().split()
                if parts:
                    t = float(parts[0])
                    self.controller.temp_settings.setdefault("peltier1", {})["current"] = t
                    if hasattr(self, "_curr_peltier1"):
                        self._curr_peltier1.setText(f"Current: {t:.1f} °C")
            if "TEMP2:" in line:
                parts = line.split("TEMP2:")[1].strip().split()
                if parts:
                    t = float(parts[0])
                    self.controller.temp_settings.setdefault("peltier2", {})["current"] = t
                    if hasattr(self, "_curr_peltier2"):
                        self._curr_peltier2.setText(f"Current: {t:.1f} °C")
        except Exception:
            pass

    def _refresh(self):
        for key in ["peltier1", "peltier2"]:
            ts = self.controller.temp_settings.get(key, {})
            curr = ts.get("current", "—")
            lbl = getattr(self, f"_curr_{key}", None)
            if lbl:
                lbl.setText(f"Current: {curr} °C")
            sl = getattr(self, f"_slider_{key}", None)
            if sl and isinstance(curr, (int, float)):
                try:
                    sl.setValue(int(curr))
                except Exception:
                    pass

    def _apply_single(self, key: str):
        """Apply settings for a single Peltier using controller helper."""
        enabled_cb = getattr(self, f"{key}_enabled_cb", None)
        min_spin = getattr(self, f"{key}_min_spin", None)
        max_spin = getattr(self, f"{key}_max_spin", None)
        if not (enabled_cb and min_spin and max_spin):
            return
        enabled = enabled_cb.isChecked()
        min_t = min_spin.value()
        max_t = max_spin.value()
        ok, msg = self.controller.apply_peltier_settings(key, enabled, min_t, max_t)
        try:
            from PyQt6.QtWidgets import QMessageBox
        except ImportError:
            from PyQt5.QtWidgets import QMessageBox
        if ok:
            QMessageBox.information(self, "Temperature", msg)
        else:
            QMessageBox.warning(self, "Temperature", msg)

    def _apply_both(self):
        """Apply settings to both Peltiers sequentially, like Tkinter apply_both_temp_settings."""
        self._apply_single("peltier1")
        self._apply_single("peltier2")

    def _refresh_temps(self):
        """Send TEMP_QUERY so current labels update when data arrives."""
        ok, msg = self.controller.query_temperatures()
        if not ok:
            try:
                from PyQt6.QtWidgets import QMessageBox
            except ImportError:
                from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Temperature", msg)
