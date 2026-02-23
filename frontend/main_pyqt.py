import os
import sys

if getattr(sys, "frozen", False):
    PYQT_ROOT = os.path.dirname(sys.executable)
else:
    PYQT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PYQT_ROOT not in sys.path:
    sys.path.insert(0, PYQT_ROOT)
# Repo root so frontend can import backend (e.g. backend.central_db)
REPO_ROOT = os.path.dirname(PYQT_ROOT)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from PyQt6.QtWidgets import QApplication
except ImportError:
    from PyQt5.QtWidgets import QApplication

from core.controller import AppController
from ui.main_window import MainWindow


def resolve_db_path() -> str:
    """
    - Dev (python run): keep DB in pyqt folder.
    - EXE (frozen): keep DB in AppData for user-safe writable storage.
    """
    if getattr(sys, "frozen", False):
        app_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "CuraxAlerts")
        os.makedirs(app_dir, exist_ok=True)
        target = os.path.join(app_dir, "curax_alerts.db")

        # One-time migration from legacy colocated DB near EXE if present.
        legacy = os.path.join(PYQT_ROOT, "curax_alerts.db")
        if not os.path.exists(target) and os.path.exists(legacy):
            try:
                import shutil
                shutil.copy2(legacy, target)
            except Exception:
                pass
        return target

    return os.path.join(PYQT_ROOT, "curax_alerts.db")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CuraX - Intelligent Medicine System")
    app.setApplicationDisplayName("CuraX Medicine Alerts")

    db_path = resolve_db_path()
    controller = AppController(db_path=db_path)
    window = MainWindow(controller)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
