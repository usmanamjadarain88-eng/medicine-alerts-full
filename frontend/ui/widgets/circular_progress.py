try:
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPainter, QPen, QColor, QBrush
except ImportError:
    from PyQt5.QtWidgets import QWidget
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPainter, QPen, QColor, QBrush


class CircularProgressWidget(QWidget):
    def __init__(self, parent=None, value=0, full_scale=80, track_color="#252532", fill_color="#2DD4BF", bg_color="#1a1a22"):
        super().__init__(parent)
        self._value = 0
        self._full_scale = max(1, full_scale)
        self._track_color = track_color
        self._track_pen_width = 3
        self._fill_color = fill_color
        self._bg_color = bg_color
        self.setValue(value)
        self.setMinimumSize(80, 80)

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = max(0, min(100, value))
        self.update()

    def setFullScale(self, scale):
        self._full_scale = max(1, scale)
        self.update()

    def setColors(self, track=None, fill=None, bg=None, track_pen_width=None):
        if track is not None:
            self._track_color = track
        if fill is not None:
            self._fill_color = fill
        if bg is not None:
            self._bg_color = bg
        if track_pen_width is not None:
            self._track_pen_width = max(1, int(track_pen_width))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        qp = QPainter(self)
        try:
            qp.setRenderHint(QPainter.RenderHint.Antialiasing)
            qp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        except AttributeError:
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        side = min(w, h)
        x = (w - side) // 2
        y = (h - side) // 2
        margin = 5
        r = (side // 2) - margin
        cx, cy = x + side // 2, y + side // 2

        try:
            round_cap = Qt.PenCapStyle.RoundCap
        except AttributeError:
            round_cap = Qt.RoundCap

        track_pen = QPen(QColor(self._track_color), self._track_pen_width)
        track_pen.setCapStyle(round_cap)
        qp.setPen(track_pen)
        try:
            qp.setBrush(Qt.BrushStyle.NoBrush)
        except AttributeError:
            qp.setBrush(Qt.NoBrush)
        qp.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)

        fill_pen_width = max(2, self._track_pen_width)
        if self._value > 0:
            span = int(-(self._value / 100.0) * 360 * 16)
            fill_pen = QPen(QColor(self._fill_color), fill_pen_width)
            fill_pen.setCapStyle(round_cap)
            qp.setPen(fill_pen)
            qp.setBrush(QBrush(QColor(self._fill_color)))
            qp.drawPie(cx - r, cy - r, 2 * r, 2 * r, 90 * 16, span)

        qp.end()
