try:
    from PyQt6.QtWidgets import QFrame
    from PyQt6.QtCore import Qt, pyqtSignal
except ImportError:
    from PyQt5.QtWidgets import QFrame
    from PyQt5.QtCore import Qt, pyqtSignal


class ClickableCard(QFrame):
    clicked = pyqtSignal(str)
    hovered = pyqtSignal(bool)

    def __init__(self, box_id, parent=None):
        super().__init__(parent)
        self.box_id = box_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.box_id)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit(False)
        super().leaveEvent(event)
