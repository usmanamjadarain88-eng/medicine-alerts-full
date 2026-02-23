try:
    from PyQt6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QFrame, QScrollArea, QDialog, QDialogButtonBox, QPushButton, QMessageBox,
        QGraphicsDropShadowEffect,
    )
    from PyQt6.QtCore import Qt, QEvent, QObject
    from PyQt6.QtGui import QColor
except ImportError:
    from PyQt5.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
        QLabel, QFrame, QScrollArea, QDialog, QDialogButtonBox, QPushButton, QMessageBox,
        QGraphicsDropShadowEffect,
    )
    from PyQt5.QtCore import Qt, QEvent, QObject
    from PyQt5.QtGui import QColor

from ui.widgets.circular_progress import CircularProgressWidget
from ui.widgets.clickable_card import ClickableCard
from ui.styles import (
    NEON_GREEN,
    RADIUS,
    BORDER,
    BORDER_LIGHT,
    TEXT_SECONDARY,
    TEXT_SECONDARY_LIGHT,
    CARD_STYLE,
    CARD_STYLE_GLOW,
    CARD_STYLE_LOW,
    CARD_STYLE_CRITICAL,
    LOW_STOCK_YELLOW,
    LOW_STOCK_RED,
    ACCENT_LIGHT,
    SECONDARY_LIGHT_DARK,
)

BORDER_LIGHT_STRONG = "#475569"
BORDER_LIGHT_CARD = "#cbd5e1"

METER_FULL_SCALE = 80
LOW_THRESHOLD = 10
CRITICAL_THRESHOLD = 5


class BoxDetailDialog(QDialog):
    def __init__(self, controller, box_id, main_window, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.box_id = box_id
        self.main_window = main_window
        self.setWindowTitle(f"Medicine Details - {box_id}")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        med = controller.medicine_boxes.get(box_id)
        if not med:
            layout.addWidget(QLabel("No medicine in this box."))
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(self.accept)
            layout.addWidget(close_btn)
            return
        exact = med.get("exact_time", med.get("time", "—"))
        text = (
            f"🧪 Medicine: {med.get('name', '—')}\n"
            f"📦 Quantity: {med.get('quantity', '—')} tablets\n"
            f"💊 Dose per Day: {med.get('dose_per_day', '—')}\n"
            f"📅 Expiry: {med.get('expiry', '—')}\n"
            f"🕒 Period: {med.get('period', '—')}\n"
            f"⏰ Exact Time: {exact}\n"
            f"📝 Instructions: {med.get('instructions', 'None')}\n"
            f"📝 Last Dose: {med.get('last_dose_taken', 'Not taken yet')}"
        )
        label = QLabel(text)
        label.setStyleSheet("font-size: 11pt; line-height: 1.4;")
        layout.addWidget(label)
        btn_row = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        remove_btn = QPushButton("Remove Medicine")
        remove_btn.setObjectName("danger")
        remove_btn.clicked.connect(self._remove_medicine)
        btn_row.addWidget(close_btn)
        btn_row.addWidget(remove_btn)
        layout.addLayout(btn_row)

    def _remove_medicine(self):
        if not self.controller.require_admin():
            return
        if self.main_window and not self.main_window.verify_admin_for_action("Remove Medicine"):
            return
        try:
            self.controller.alert_scheduler.cancel_medicine_alerts_for_box(self.box_id)
        except Exception:
            pass
        self.controller.medicine_boxes[self.box_id] = None
        self.controller.save_data()
        self.controller.medicine_updated.emit()
        self.accept()
        if self.main_window:
            QMessageBox.information(self.main_window, "Removed", f"Medicine removed from {self.box_id}.")


class MainPanelTab(QWidget):
    def __init__(self, controller, main_window=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.main_window = main_window
        self.box_widgets = []
        self._init_theme_styles(getattr(controller, "appearance_theme", "light"))
        self._build_ui()
        controller.medicine_updated.connect(self.refresh)

    def _init_theme_styles(self, theme_name: str):
        name = (theme_name or "light").lower()
        if name == "light":
            base_bg = """
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #f0f6fc, stop:0.5 #e8f0f8, stop:1 #e2eef8);
            """
            card_border = "#94a3b8"
            self._progress_track_color = BORDER_LIGHT_STRONG
            self._progress_track_pen_width = 3
            self._progress_fill_color = ACCENT_LIGHT
            self._title_color = ACCENT_LIGHT
            self._box_id_color = ACCENT_LIGHT
            self._secondary_text_color = SECONDARY_LIGHT_DARK
            hover_bg_light = """
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #e8eef6, stop:0.5 #dce4f0, stop:1 #e2eaf2);
            """
            hover_border_light = f"1px solid {ACCENT_LIGHT};"
            self._card_style_normal = f"""
                QFrame#card {{
                    {base_bg}
                    border-radius: 18px;
                    border: 1px solid {card_border};
                }}
                QFrame#card:hover {{
                    {hover_bg_light}
                    border: {hover_border_light}
                    border-radius: 18px;
                }}
            """
            self._card_style_low = f"""
                QFrame#card {{
                    {base_bg}
                    border-radius: 18px;
                    border: 1px solid {LOW_STOCK_YELLOW};
                }}
                QFrame#card:hover {{
                    {hover_bg_light}
                    border: {hover_border_light}
                    border-radius: 18px;
                }}
            """
            self._card_style_critical = f"""
                QFrame#card {{
                    {base_bg}
                    border-radius: 18px;
                    border: 1px solid {LOW_STOCK_RED};
                }}
                QFrame#card:hover {{
                    {hover_bg_light}
                    border: {hover_border_light}
                    border-radius: 18px;
                }}
            """
            self._med_text_color = "#111827"
        else:
            self._progress_track_color = "#1e2a42"
            self._progress_track_pen_width = 3
            self._progress_fill_color = NEON_GREEN
            self._title_color = NEON_GREEN
            self._box_id_color = NEON_GREEN
            self._secondary_text_color = TEXT_SECONDARY
            card_bg_dark = "background-color: #000000;"
            card_border_dark = f"border: 1px solid {BORDER}; border-radius: {RADIUS};"
            hover_border_dark = f"1px solid {NEON_GREEN};"
            hover_bg_dark = "background-color: rgba(30, 41, 59, 0.35);"
            self._card_style_normal = f"""
                QFrame#card {{
                    {card_bg_dark}
                    {card_border_dark}
                }}
                QFrame#card:hover {{
                    {hover_bg_dark}
                    border: {hover_border_dark}
                    border-radius: {RADIUS};
                }}
            """
            self._card_style_low = f"""
                QFrame#card {{
                    {card_bg_dark}
                    border: 1px solid {LOW_STOCK_YELLOW};
                    border-radius: {RADIUS};
                }}
                QFrame#card:hover {{
                    {hover_bg_dark}
                    border: {hover_border_dark}
                    border-radius: {RADIUS};
                }}
            """
            self._card_style_critical = f"""
                QFrame#card {{
                    {card_bg_dark}
                    border: 1px solid {LOW_STOCK_RED};
                    border-radius: {RADIUS};
                }}
                QFrame#card:hover {{
                    {hover_bg_dark}
                    border: {hover_border_dark}
                    border-radius: {RADIUS};
                }}
            """
            self._med_text_color = "#f1f5f9"
            self._secondary_text_color = TEXT_SECONDARY

    def apply_theme(self, theme_name: str):
        self._init_theme_styles(theme_name)
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        top_row = QHBoxLayout()
        self._title_label = QLabel("Medicine Boxes Dashboard")
        self._title_label.setStyleSheet(
            f"font-size: 18pt; font-weight: bold; color: {getattr(self, '_title_color', NEON_GREEN)};"
        )
        top_row.addWidget(self._title_label)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._subtitle_label = QLabel("Click a box to view details and mark dose taken.")
        self._subtitle_label.setStyleSheet(
            f"color: {getattr(self, '_secondary_text_color', TEXT_SECONDARY)}; font-size: 13px;"
        )
        layout.addWidget(self._subtitle_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll_w = QWidget()
        scroll_layout = QVBoxLayout(scroll_w)
        grid = QGridLayout()

        for i in range(1, 7):
            box_id = f"B{i}"
            card = ClickableCard(box_id)
            card.setObjectName("card")
            card.setStyleSheet(self._card_style_normal)
            card.clicked.connect(self._on_card_clicked)
            card_layout = QVBoxLayout(card)
            card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            id_label = QLabel(box_id)
            box_id_color = getattr(self, "_box_id_color", NEON_GREEN)
            id_label.setStyleSheet(f"font-weight: bold; color: {box_id_color}; font-size: 11pt;")
            card_layout.addWidget(id_label, alignment=Qt.AlignmentFlag.AlignCenter)

            progress = CircularProgressWidget(
                parent=card, value=0, full_scale=METER_FULL_SCALE,
                track_color="#1e2a42", fill_color=NEON_GREEN, bg_color="#121827"
            )
            progress.setFixedSize(100, 100)
            card_layout.addWidget(progress, alignment=Qt.AlignmentFlag.AlignCenter)

            qty_label = QLabel("Empty")
            qty_label.setStyleSheet(f"color: {getattr(self, '_secondary_text_color', TEXT_SECONDARY)}; font-size: 9pt; font-weight: bold;")
            card_layout.addWidget(qty_label, alignment=Qt.AlignmentFlag.AlignCenter)

            med_label = QLabel("—")
            med_label.setStyleSheet(f"color: {getattr(self, '_secondary_text_color', TEXT_SECONDARY)}; font-size: 9pt;")
            card_layout.addWidget(med_label, alignment=Qt.AlignmentFlag.AlignCenter)

            wrapper = QWidget()
            wrap_layout = QVBoxLayout(wrapper)
            wrap_layout.setContentsMargins(0, 0, 0, 0)
            wrap_layout.setSpacing(0)
            wrap_layout.addWidget(card)

            card.hovered.connect(
                lambda hovered, c=card, p=progress, bid=box_id, w=wrapper: self._on_card_hover(c, p, bid, hovered, w)
            )
            self.box_widgets.append((card, progress, med_label, qty_label, box_id, id_label))
            row, col = (i - 1) // 3, (i - 1) % 3
            grid.addWidget(wrapper, row, col)

        scroll_layout.addLayout(grid)
        scroll.setWidget(scroll_w)
        try:
            wheel_type = QEvent.Type.Wheel
        except AttributeError:
            wheel_type = QEvent.Wheel

        class WheelScrollFilter(QObject):
            def __init__(self, scroll_area, parent=None):
                super().__init__(parent)
                self._scroll = scroll_area

            def eventFilter(self, obj, ev):
                if ev.type() == wheel_type and self._scroll.verticalScrollBar().isVisible():
                    sb = self._scroll.verticalScrollBar()
                    delta = ev.angleDelta().y() if hasattr(ev, "angleDelta") else ev.delta()
                    sb.setValue(sb.value() - delta)
                    return True
                return False

        self._wheel_filter = WheelScrollFilter(scroll, self)
        self.installEventFilter(self._wheel_filter)
        layout.addWidget(scroll)
        self.refresh()

    def _on_card_clicked(self, box_id):
        d = BoxDetailDialog(self.controller, box_id, self.main_window, self)
        d.exec()

    def _on_card_hover(self, card, progress, box_id, hovered, wrapper=None):
        is_light = (getattr(self.controller, "appearance_theme", "light") or "light").lower() == "light"
        if hovered:
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(25)
            shadow.setXOffset(0)
            shadow.setYOffset(10)
            shadow.setColor(QColor(0, 0, 0, 38 if is_light else 153))  # 0.15*255≈38, 0.6*255≈153
            card.setGraphicsEffect(shadow)
        else:
            card.setGraphicsEffect(None)

    def refresh(self):
        if hasattr(self, "_title_label"):
            self._title_label.setStyleSheet(
                f"font-size: 18pt; font-weight: bold; color: {getattr(self, '_title_color', NEON_GREEN)};"
            )
        if hasattr(self, "_subtitle_label"):
            self._subtitle_label.setStyleSheet(
                f"color: {getattr(self, '_secondary_text_color', TEXT_SECONDARY)}; font-size: 13px;"
            )

        track_color = getattr(self, "_progress_track_color", "#1e2a42")
        track_pen = getattr(self, "_progress_track_pen_width", 3)
        fill_normal = getattr(self, "_progress_fill_color", NEON_GREEN)
        box_id_color = getattr(self, "_box_id_color", NEON_GREEN)

        for item in self.box_widgets:
            card, progress, med_label, qty_label, box_id, id_label = item
            id_label.setStyleSheet(f"font-weight: bold; color: {box_id_color}; font-size: 11pt;")
            progress.setColors(track=track_color, track_pen_width=track_pen)
            med = self.controller.medicine_boxes.get(box_id)
            if med:
                qty = med.get("quantity", 0)
                if not isinstance(qty, (int, float)):
                    qty = 0
                value = min(100, max(0, (qty / METER_FULL_SCALE) * 100))
                progress.setValue(value)
                if qty <= CRITICAL_THRESHOLD:
                    fill = LOW_STOCK_RED
                    card.setStyleSheet(self._card_style_critical)
                    progress.setColors(fill=fill)
                elif qty <= LOW_THRESHOLD:
                    fill = LOW_STOCK_YELLOW
                    card.setStyleSheet(self._card_style_low)
                    progress.setColors(fill=fill)
                else:
                    fill = fill_normal
                    card.setStyleSheet(self._card_style_normal)
                    progress.setColors(fill=fill)
                qty_label.setText(f"{qty} tablets left")
                qty_label.setStyleSheet(f"color: {fill}; font-size: 9pt; font-weight: bold;")
                med_label.setText(med.get("name", "Unknown"))
                med_label.setStyleSheet(f"color: {self._med_text_color}; font-size: 9pt;")
            else:
                progress.setValue(0)
                card.setStyleSheet(self._card_style_normal)
                progress.setColors(fill=fill_normal)
                qty_label.setText("Empty")
                qty_label.setStyleSheet(f"color: {self._secondary_text_color}; font-size: 9pt; font-weight: bold;")
                med_label.setText("—")
                med_label.setStyleSheet(f"color: {self._secondary_text_color}; font-size: 9pt;")
