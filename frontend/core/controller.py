import os
import sys
import json
import queue
import time
import threading
import datetime
import shutil
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import AlertDB

try:
    from backend.central_db import CentralDB
except ImportError:
    CentralDB = None

try:
    from PyQt6.QtCore import QObject, pyqtSignal, QTimer
except ImportError:
    from PyQt5.QtCore import QObject, pyqtSignal, QTimer

import serial


class AppController(QObject):

    status_message = pyqtSignal(str)
    connected_changed = pyqtSignal(bool)
    authenticated_changed = pyqtSignal(bool)
    medicine_updated = pyqtSignal()
    temperature_update = pyqtSignal(str)
    admin_status_changed = pyqtSignal()

    def __init__(self, db_path="curax_alerts.db"):
        super().__init__()
        self._db = AlertDB(db_path)
        self.connected = False
        self.authenticated = False
        self.ser = None
        self.running = True
        self.serial_thread = None
        self.serial_pause = False
        self.active_led_box = None
        self.last_bt_port = None
        self.wrong_count = 0
        self.admin_logged_in = False
        self.logged_in_admin_name = None

        self.temp_settings = {
            "peltier1": {"min": 15, "max": 20, "current": 18},
            "peltier2": {"min": 5, "max": 8, "current": 6},
        }
        self.medicine_boxes = {f"B{i}": None for i in range(1, 7)}
        self.dose_log = []

        self.alert_settings = {
            "email_alerts": {"enabled": True, "email": "", "send_copy_to": "", "alert_tone": "default", "volume": 80},
            "medicine_alerts": {"15_min_before": True, "exact_time": True, "5_min_after": True, "missed_alert": True, "snooze_duration": 5},
            "stock_alerts": {"enabled": True, "low_stock_threshold": 5, "empty_alert": True, "critical_alert": True},
            "expiry_alerts": {"30_days_before": True, "15_days_before": True, "7_days_before": True, "1_day_before": True},
            "reminders": {"doctor_appointments": [], "prescription_renewals": [], "lab_tests": [], "custom_reminders": []},
            "do_not_disturb": {"enabled": False, "start_time": "22:00", "end_time": "07:00", "emergency_override": True},
            "missed_dose_escalation": {"5_min_reminder": True, "15_min_urgent": True, "30_min_family": True, "1_hour_log": True, "family_email": ""},
            "temperature_settings": {
                "peltier1": {"enabled": True, "min_temp": 15, "max_temp": 20, "current_temp": 18},
                "peltier2": {"enabled": True, "min_temp": 5, "max_temp": 8, "current_temp": 6},
            },
        }
        self.sms_config = {"enabled": False, "provider": "callmebot", "phone_number": "", "api_key": "0"}
        self.mobile_bot = {"enabled": False, "bot_id": "", "api_key": "", "server_url": "https://curax-alerts.herokuapp.com"}
        self.admin_bot = {"enabled": False, "bot_id": "", "api_key": "", "server_url": "https://curax-alerts.herokuapp.com"}
        self.gmail_config = {
            "sender_email": "",
            "sender_password": "",
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 465,
            "recipients": "",
        }
        self.medical_reminders = {"appointments": [], "prescriptions": [], "lab_tests": [], "custom": []}
        self.appearance_theme = "light"

        self._central_db = None
        self._init_central_db()

        self.load_alert_settings()
        self.load_mobile_bot_config()
        self.load_admin_bot_config()
        self.load_appearance_theme()
        self.load_data()

        self.fetch_from_central_and_apply()

        self._databus_queue = queue.Queue()
        self._databus_stop = threading.Event()
        self._databus_thread = None
        self._databus_timer = None
        self._start_databus_client()

        from core.alert_scheduler import AlertScheduler
        self.alert_scheduler = AlertScheduler(self)

        try:
            try:
                import schedule as _schedule
                _schedule.clear()
            except Exception:
                pass
            alert_count = 0
            boxes = getattr(self, "medicine_boxes", {}) or {}
            for box_id, medicine in boxes.items():
                if not medicine:
                    continue
                try:
                    self.alert_scheduler.schedule_medicine_alert(medicine, box_id)
                    alert_count += 1
                except Exception:
                    continue
            self.alert_scheduler.start()
            self._log(f"[AlertScheduler] Background scheduler started. {alert_count} medicine(s) scheduled.")
        except Exception as e:
            self._log(f"[AlertScheduler] Failed to start: {e}")

    def _log(self, message: str):
        try:
            print(message)
            sys.stdout.flush()
        except Exception:
            pass

    def get_db(self):
        return self._db

    def _init_central_db(self):
        """Central DB: one URL for all installations. Set via DATABASE_URL (or CENTRAL_DB_URL) env or backend/database_url.txt."""
        url = (os.environ.get("DATABASE_URL") or os.environ.get("CENTRAL_DB_URL") or "").strip()
        if not url:
            # Load from file (same as api_server) so desktop works without setting env
            for _path in [
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", "database_url.txt"),
                os.path.join(os.getcwd(), "backend", "database_url.txt"),
            ]:
                if os.path.isfile(_path):
                    try:
                        with open(_path, "r", encoding="utf-8") as _f:
                            for _line in _f:
                                _line = _line.strip()
                                if _line and not _line.startswith("#"):
                                    url = _line
                                    os.environ["DATABASE_URL"] = url
                                    break
                        if url:
                            break
                    except Exception:
                        pass
        self._central_db = None
        if url and CentralDB is not None:
            try:
                c = CentralDB(connection_string=url)
                if c.is_available():
                    self._central_db = c
                else:
                    c.close()
            except Exception:
                pass

    def get_central_db(self):
        """Return CentralDB client if configured and available. None otherwise."""
        if self._central_db is not None and hasattr(self._central_db, "is_available") and self._central_db.is_available():
            return self._central_db
        return None

    def get_backend_url(self):
        """API and data-bus base URL set in code/config only (no UI). For deploy: set BACKEND_URL env or put URL in backend/backend_url.txt; data bus = same host, port 5052. Curax Relay (alerts) is separate — Server URL in Admin Mobile App."""
        url = (os.environ.get("BACKEND_URL") or os.environ.get("CENTRAL_API_URL") or "").strip()
        if url:
            return url.rstrip("/")
        for _path in [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", "backend_url.txt"),
            os.path.join(os.getcwd(), "backend", "backend_url.txt"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", "api_base_url.txt"),
            os.path.join(os.getcwd(), "backend", "api_base_url.txt"),
        ]:
            if os.path.isfile(_path):
                try:
                    with open(_path, "r", encoding="utf-8") as _f:
                        for _line in _f:
                            _line = _line.strip()
                            if _line and not _line.startswith("#"):
                                return _line.rstrip("/")
                except Exception:
                    pass
        return "http://localhost:5050"

    def get_central_api_base_url(self):
        """Same as get_backend_url(): backend serves API (data) and we derive WebSocket from it."""
        return self.get_backend_url()

    def get_data_bus_url(self):
        """WebSocket for live updates. If DATA_BUS_URL or backend/data_bus_url.txt set, use it; else same host as backend, port 5052."""
        url = (os.environ.get("DATA_BUS_URL") or "").strip().rstrip("/")
        if url:
            if url.startswith("https://"):
                return url.replace("https://", "wss://", 1)
            if url.startswith("http://"):
                return url.replace("http://", "ws://", 1)
            return "wss://" + url
        for _path in [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", "data_bus_url.txt"),
            os.path.join(os.getcwd(), "backend", "data_bus_url.txt"),
        ]:
            if os.path.isfile(_path):
                try:
                    with open(_path, "r", encoding="utf-8") as _f:
                        for _line in _f:
                            _line = _line.strip()
                            if _line and not _line.startswith("#"):
                                url = _line.rstrip("/")
                                if url.startswith("https://"):
                                    return url.replace("https://", "wss://", 1)
                                if url.startswith("http://"):
                                    return url.replace("http://", "ws://", 1)
                                return "wss://" + url if ":" not in url or url.endswith(":443") else "ws://" + url
                except Exception:
                    pass
        base = self.get_backend_url()
        if not base:
            return ""
        if base.startswith("https://"):
            return base.replace("https://", "wss://", 1).rsplit(":", 1)[0] + ":5052"
        if base.startswith("http://"):
            return base.replace("http://", "ws://", 1).rsplit(":", 1)[0] + ":5052"
        return ""

    def delete_admin_from_backend(self, access_code):
        """Call backend DELETE /admin so access_code and connection_code are freed. Returns True on success."""
        base = self.get_central_api_base_url()
        if not base or not (access_code or "").strip():
            return False
        try:
            import urllib.request
            import json as _json
            req = urllib.request.Request(
                f"{base}/admin",
                data=_json.dumps({"access_code": (access_code or "").strip()}).encode("utf-8"),
                method="DELETE",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= getattr(resp, "status", 0) < 300
        except Exception:
            return False

    def _start_databus_client(self):
        """Connect to data bus WebSocket so changes from app (or Central API) are pushed to desktop in real time."""
        access_code = (self._db.get("admin_access_code") or "").strip() if getattr(self, "_db", None) else ""
        ws_url = self.get_data_bus_url()
        if not access_code or not ws_url:
            return
        try:
            from core.databus_client import run_databus_client
        except Exception:
            return
        self._databus_stop.clear()
        self._databus_thread = threading.Thread(
            target=run_databus_client,
            args=(ws_url, access_code, self._databus_queue, self._databus_stop),
            daemon=True,
        )
        self._databus_thread.start()
        self._databus_timer = QTimer(self)
        self._databus_timer.timeout.connect(self._drain_databus_queue)
        self._databus_timer.start(500)

    def _drain_databus_queue(self):
        """Apply data_sync payloads from data bus (backend pushes after any write to that admin)."""
        try:
            while True:
                payload = self._databus_queue.get_nowait()
                self.apply_data_sync_from_central(payload)
        except queue.Empty:
            pass

    def apply_data_sync_from_central(self, payload):
        """Apply admin data payload (from data bus or GET /admin/data). All data lives in Central; no local DB for this."""
        if not payload or not isinstance(payload, dict):
            return
        medicines = payload.get("medicines") or []
        boxes = {f"B{i}": None for i in range(1, 7)}
        for m in medicines:
            box_id = (m.get("box_id") or "B1").strip().upper()
            if box_id not in boxes:
                continue
            times = m.get("times")
            if not isinstance(times, list):
                times = []
            exact = (times[0] if times else "08:00") or "08:00"
            qty = 0
            try:
                qty = int(m.get("quantity", 0))
            except (TypeError, ValueError):
                pass
            boxes[box_id] = {
                "name": (m.get("name") or "").strip() or "Medicine",
                "quantity": qty,
                "stock": qty,
                "dose_per_day": len(times) or 1,
                "exact_time": exact,
                "times": times,
            }
        self.medicine_boxes = boxes
        dose_logs = payload.get("dose_logs") or []
        self.dose_log = [
            {"timestamp": e.get("taken_at"), "box": e.get("box_id") or "", "medicine": "", "dose_taken": 1, "remaining": None}
            for e in dose_logs if isinstance(e, dict) and e.get("taken_at")
        ]
        reminders = payload.get("medical_reminders")
        if isinstance(reminders, dict):
            self.medical_reminders = {
                "appointments": reminders.get("appointments") or [],
                "prescriptions": reminders.get("prescriptions") or [],
                "lab_tests": reminders.get("lab_tests") or [],
                "custom": reminders.get("custom") or [],
            }
        alert_top = payload.get("alert_settings")
        if isinstance(alert_top, dict):
            if "alert_settings" in alert_top and isinstance(alert_top["alert_settings"], dict):
                for k, v in alert_top["alert_settings"].items():
                    if k in self.alert_settings and isinstance(self.alert_settings[k], dict) and isinstance(v, dict):
                        self.alert_settings[k].update(v)
                    else:
                        self.alert_settings[k] = v
            if "gmail_config" in alert_top and isinstance(alert_top["gmail_config"], dict):
                self.gmail_config.update(alert_top["gmail_config"])
        self.medicine_updated.emit()

    def fetch_from_central_and_apply(self):
        """Load admin data from Central API (GET /admin/data) and apply to UI. Single source of truth is Central."""
        base = self.get_central_api_base_url()
        access_code = (self._db.get("admin_access_code") or "").strip() if getattr(self, "_db", None) else ""
        if not base or not access_code:
            return
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{base}/admin/data?access_code={urllib.parse.quote(access_code, safe='')}",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    return
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return
        self.apply_data_sync_from_central(payload)

    def set_central_db_url(self, url):
        """No-op: central DB URL is set once via DATABASE_URL env for all installations, not per-app."""
        pass

    def _save_all_to_central_api(self):
        """POST /admin/sync to write current state to Central DB. Backend then notifies data bus so other clients get the update."""
        base = self.get_central_api_base_url()
        access_code = (self._db.get("admin_access_code") or "").strip() if getattr(self, "_db", None) else ""
        if not base or not access_code:
            return False
        try:
            payload = {
                "access_code": access_code,
                "medicine_boxes": getattr(self, "medicine_boxes", {}) or {},
                "dose_log": getattr(self, "dose_log", []) or [],
                "alert_settings": getattr(self, "alert_settings", {}),
                "gmail_config": getattr(self, "gmail_config", {}),
                "medical_reminders": getattr(self, "medical_reminders", {}),
            }
            import urllib.request
            req = urllib.request.Request(
                base + "/admin/sync",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return 200 <= getattr(resp, "status", 0) < 300
        except Exception:
            return False

    def load_data(self):
        """Load medicines, dose_log, alert_settings, gmail_config, medical_reminders from Central API only. No local DB for this data."""
        try:
            self.fetch_from_central_and_apply()
        except Exception as e:
            self.status_message.emit(f"Failed to load data: {e}")

    def save_data(self):
        """Save medicines and dose_log to Central API only. No local DB."""
        try:
            if self._save_all_to_central_api():
                self.medicine_updated.emit()
            else:
                self.status_message.emit("Failed to save to server (check connection and access code).")
        except Exception as e:
            self.status_message.emit(f"Failed to save data: {e}")

    def load_alert_settings(self):
        """Load only device-local settings from local DB (e.g. sms_config). Alert settings and Gmail come from Central in load_data()."""
        try:
            sc = self._db.get("sms_config")
            if sc and isinstance(sc, dict):
                for key, value in sc.items():
                    if key in self.sms_config:
                        self.sms_config[key] = value
        except Exception:
            pass

    def load_appearance_theme(self):
        try:
            t = self._db.get("appearance_theme")
            if t is None:
                self.appearance_theme = "light"
                return
            if isinstance(t, str):
                name = t.strip().lower()
                if name in ("light", "dark"):
                    self.appearance_theme = name
                    return
                if name == "default":
                    self.appearance_theme = "light"
                    return
        except Exception:
            pass
        self.appearance_theme = "light"

    def save_appearance_theme(self, theme_name: str):
        try:
            name = (theme_name or "").strip().lower()
            if name not in ("dark", "light"):
                return
            self._db.set("appearance_theme", name)
            self.appearance_theme = name
        except Exception:
            pass

    def save_alert_settings(self):
        """Save alert settings and Gmail to Central API. Persist only device-local sms_config to local DB."""
        try:
            if getattr(self, "_db", None) and hasattr(self._db, "set"):
                self._db.set("sms_config", getattr(self, "sms_config", {}))
            if not self._save_all_to_central_api():
                self.status_message.emit("Failed to save alert settings to server.")
        except Exception as e:
            self.status_message.emit(str(e))

    def reschedule_all_medicine_alerts(self):
        try:
            for box_id in list(getattr(self, "medicine_boxes", {}).keys()):
                self.alert_scheduler.cancel_medicine_alerts_for_box(box_id)
            boxes = getattr(self, "medicine_boxes", {}) or {}
            for box_id, medicine in boxes.items():
                if not medicine:
                    continue
                try:
                    self.alert_scheduler.schedule_medicine_alert(medicine, box_id)
                except Exception:
                    continue
        except Exception:
            pass

    def load_medical_reminders(self):
        """Medical reminders are loaded from Central API in load_data(); no local DB."""
        pass

    def save_medical_reminders(self):
        """Save medical reminders to Central API only. No local DB."""
        try:
            if not self._save_all_to_central_api():
                self.status_message.emit("Failed to save reminders to server.")
        except Exception as e:
            self.status_message.emit(str(e))

    def _backup_file_path(self):
        abs_db = os.path.abspath(self._db.db_path)
        dir_path = os.path.dirname(abs_db)
        return os.path.join(dir_path, "curax_alerts_backup.db")

    def save_backup_snapshot(self):
        try:
            snapshot = {
                "timestamp": datetime.datetime.now().isoformat(),
                "medicine_data": {"medicine_boxes": getattr(self, "medicine_boxes", {}), "dose_log": getattr(self, "dose_log", [])},
                "alert_settings": getattr(self, "alert_settings", {}),
                "medical_reminders": getattr(self, "medical_reminders", {}),
                "gmail_config": getattr(self, "gmail_config", {}),
                "sms_config": getattr(self, "sms_config", {}),
                "mobile_bot_config": getattr(self, "mobile_bot", {}),
                "admin_bot_config": getattr(self, "admin_bot", {}),
                "appearance_theme": getattr(self, "appearance_theme", "light"),
            }
            self._db.set("backup_snapshot", snapshot)
            backup_path = self._backup_file_path()
            abs_db = os.path.abspath(self._db.db_path)
            if os.path.exists(abs_db):
                shutil.copy2(abs_db, backup_path)
            return True
        except Exception:
            return False

    def restore_from_backup_snapshot(self):
        try:
            snapshot = self._db.get("backup_snapshot")
            if not snapshot or not isinstance(snapshot, dict):
                return False
            md = snapshot.get("medicine_data")
            if md:
                self.medicine_boxes = md.get("medicine_boxes", self.medicine_boxes)
                self.dose_log = md.get("dose_log", [])
            if snapshot.get("alert_settings") is not None:
                self.alert_settings = snapshot["alert_settings"]
            if snapshot.get("medical_reminders") is not None:
                self.medical_reminders = snapshot["medical_reminders"]
            if snapshot.get("gmail_config") is not None:
                self.gmail_config.update(snapshot["gmail_config"])
            if snapshot.get("sms_config") is not None:
                for k, v in snapshot["sms_config"].items():
                    if k in self.sms_config:
                        self.sms_config[k] = v
                self._db.set("sms_config", self.sms_config)
            if snapshot.get("mobile_bot_config") is not None:
                self.mobile_bot.update(snapshot["mobile_bot_config"])
                self._db.set("mobile_bot_config", self.mobile_bot)
            if snapshot.get("admin_bot_config") is not None:
                self.admin_bot.update(snapshot["admin_bot_config"])
                self._db.set("admin_bot_config", self.admin_bot)
            if snapshot.get("appearance_theme") is not None:
                self.appearance_theme = snapshot["appearance_theme"]
                self._db.set("appearance_theme", self.appearance_theme)
            self._save_all_to_central_api()
            self.medicine_updated.emit()
            return True
        except Exception:
            return False

    def restore_from_backup_file(self):
        backup_path = self._backup_file_path()
        if not os.path.exists(backup_path):
            return False
        try:
            backup_db = AlertDB(backup_path)
            snapshot = backup_db.get("backup_snapshot")
            backup_db.close()
            if not snapshot or not isinstance(snapshot, dict):
                return False
            md = snapshot.get("medicine_data")
            if md:
                self.medicine_boxes = md.get("medicine_boxes", self.medicine_boxes)
                self.dose_log = md.get("dose_log", [])
            if snapshot.get("alert_settings") is not None:
                self.alert_settings = snapshot["alert_settings"]
            if snapshot.get("medical_reminders") is not None:
                self.medical_reminders = snapshot["medical_reminders"]
            if snapshot.get("gmail_config") is not None:
                self.gmail_config.update(snapshot["gmail_config"])
            if snapshot.get("sms_config") is not None:
                for k, v in snapshot["sms_config"].items():
                    if k in self.sms_config:
                        self.sms_config[k] = v
                self._db.set("sms_config", self.sms_config)
            if snapshot.get("mobile_bot_config") is not None:
                self.mobile_bot.update(snapshot["mobile_bot_config"])
                self._db.set("mobile_bot_config", self.mobile_bot)
            if snapshot.get("admin_bot_config") is not None:
                self.admin_bot.update(snapshot["admin_bot_config"])
                self._db.set("admin_bot_config", self.admin_bot)
            if snapshot.get("appearance_theme") is not None:
                self.appearance_theme = snapshot["appearance_theme"]
                self._db.set("appearance_theme", self.appearance_theme)
            self._save_all_to_central_api()
            self.medicine_updated.emit()
            return True
        except Exception:
            return False

    def load_mobile_bot_config(self):
        try:
            data = self._db.get("mobile_bot_config")
            if data:
                self.mobile_bot.update(data)
        except Exception:
            pass

    def load_admin_bot_config(self):
        try:
            data = self._db.get("admin_bot_config")
            if data:
                self.admin_bot.update(data)
        except Exception:
            pass

    def save_admin_bot_config(self):
        try:
            self._db.set("admin_bot_config", self.admin_bot)
        except Exception:
            pass

    def require_admin(self):
        if not self._db.has_admin_credentials():
            self.status_message.emit("Admin Required: No admin configured. Go to Settings → Admin Panel.")
            return False
        return True

    def verify_admin_login(self, password):
        if not self._db.has_admin_credentials():
            return False
        if not self._db.verify_admin_password(password):
            return False
        info = self._db.get_admin_info()
        name = (info or {}).get("name") or "Admin"
        self.admin_logged_in = True
        self.logged_in_admin_name = name
        self._db.log_approval("Admin Login", name, "approved", "Successful login")
        self.admin_status_changed.emit()
        try:
            self.send_admin_alert("admin_login", f"Admin panel logged in by {name}")
        except Exception:
            pass
        return True

    def verify_admin_password_for_action(self, action_label: str, password: str) -> bool:
        if not self._db.has_admin_credentials():
            return False
        info = self._db.get_admin_info()
        name = (info or {}).get("name") or "Admin"
        if not self._db.verify_admin_password(password):
            try:
                self._db.log_approval(action_label, "Unknown", "Denied")
            except Exception:
                pass
            return False
        try:
            self._db.log_approval(action_label, name, "Approved")
        except Exception:
            pass
        return True

    def admin_logout(self):
        self.admin_logged_in = False
        self.logged_in_admin_name = None
        self.admin_status_changed.emit()

    def connect_to_port(self, port_name):
        from connection import serial_connection
        self._connect_port_name = port_name
        return serial_connection.connect_to_port(self)

    def disconnect_esp32(self):
        from connection import serial_connection
        serial_connection.disconnect_esp32(self)

    def start_serial_thread(self):
        from connection import serial_connection
        serial_connection.start_serial_thread(self)

    def get_available_ports(self):
        from connection import serial_connection
        return serial_connection.get_available_ports()

    def get_connected_port(self):
        from connection import serial_connection
        return serial_connection.get_connected_port(self)

    def quick_test_port(self, port_name):
        from connection import serial_connection
        return serial_connection.quick_test_port(port_name)

    def get_bluetooth_ports(self):
        from connection import serial_connection
        return serial_connection.get_bluetooth_ports()

    def connect_bluetooth(self):
        from connection import serial_connection
        return serial_connection.connect_bluetooth(self)

    def verify_pin_esp32(self, pin):
        from auth.verify_esp32 import verify_pin_esp32
        return verify_pin_esp32(self, pin)

    def send_led_on(self, box_id):
        from connection import serial_connection
        return serial_connection.send_led_on(self, box_id)

    def send_led_off(self, box_id):
        from connection import serial_connection
        return serial_connection.send_led_off(self, box_id)

    def send_led_all_off(self):
        from connection import serial_connection
        return serial_connection.send_led_all_off(self)

    def apply_peltier_settings(self, peltier_id: str, enabled: bool, min_temp: float, max_temp: float):
        if not self.authenticated or not self.ser or not self.ser.is_open:
            return False, "Please connect and authenticate ESP32 first."
        try:
            min_t = float(min_temp)
            max_t = float(max_temp)
        except (TypeError, ValueError):
            return False, "Invalid temperature values."
        if min_t >= max_t:
            return False, "Minimum temperature must be less than maximum."

        try:
            self.serial_pause = True
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass
            cmd = f"TEMP_SET:{peltier_id},{enabled},{min_t},{max_t}\n"
            self._log(f"[TEMP] Sending: {cmd.strip()}")
            self.ser.write(cmd.encode("utf-8"))
            self.ser.flush()
            zone = self.temp_settings.setdefault(peltier_id, {})
            zone["min"] = min_t
            zone["max"] = max_t
            zone["enabled"] = bool(enabled)
            return True, f"{peltier_id.upper()} applied: {min_t}°C → {max_t}°C"
        except Exception as e:
            return False, f"Failed to apply settings: {str(e)[:80]}"
        finally:
            self.serial_pause = False

    def query_temperatures(self):
        if not self.authenticated or not self.ser or not self.ser.is_open:
            return False, "Please connect and authenticate ESP32 first."
        try:
            self.serial_pause = True
            try:
                self.ser.reset_input_buffer()
            except Exception:
                pass
            self._log("[TEMP] Sending TEMP_QUERY")
            self.ser.write(b"TEMP_QUERY\n")
            self.ser.flush()
            return True, "Temperature query sent."
        except Exception as e:
            return False, f"Failed to query temperature: {str(e)[:80]}"
        finally:
            self.serial_pause = False

    def _send_bot_alert(self, bot_config, alert_type, message):
        """Send alert to a bot (mobile_bot or admin_bot). Returns True on success."""
        bot_id = (bot_config.get("bot_id") or "").strip()
        api_key = (bot_config.get("api_key") or "").strip()
        if not bot_id or not api_key:
            return False
        server_url = (bot_config.get("server_url") or "localhost:5050").strip()
        if not server_url:
            return False
        try:
            if server_url.startswith("https://") or server_url.startswith("http://"):
                wss = server_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1).rstrip("/")
                try:
                    import asyncio
                    import websockets
                except ImportError:
                    return False

                async def _send_via_ws():
                    async with websockets.connect(wss, close_timeout=2, open_timeout=15) as ws:
                        await ws.send(json.dumps({
                            "action": "alert",
                            "bot_id": bot_id,
                            "api_key": api_key,
                            "type": alert_type,
                            "message": message,
                        }))

                asyncio.run(_send_via_ws())
                return True
            import socket
            srv = server_url.split("://")[-1] if "://" in server_url else server_url
            host, port = (srv.rsplit(":", 1) + ["5050"])[:2]
            port = int(port)
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(3)
            client.connect((host, port))
            client.sendall(json.dumps({"type": alert_type, "message": message}).encode("utf-8"))
            client.close()
            return True
        except Exception:
            return False

    def send_mobile_alert(self, alert_type, message, priority="NORMAL"):
        return self._send_bot_alert(self.mobile_bot, alert_type, message)

    def send_admin_alert(self, alert_type, message, priority="NORMAL"):
        """Send alert to admin bot only (admin_bot config). Used for admin-only and both user+admin alerts."""
        if not self.admin_bot.get("enabled"):
            return False
        return self._send_bot_alert(self.admin_bot, alert_type, message)

    def change_device_password(self, current_password: str, new_password: str):
        if not self.ser or not self.ser.is_open:
            return False, "Not connected to device"
        if not current_password or not new_password:
            return False, "Both current and new passwords are required"
        if len(new_password) < 4 or not new_password.isdigit():
            return False, "New password must be at least 4 digits (numbers only)"
        try:
            self.serial_pause = True
            command = f"SET_PASSWORD:{current_password},{new_password}\n"
            self.ser.reset_input_buffer()
            time.sleep(0.1)
            self.ser.write(command.encode("utf-8"))
            self.ser.flush()

            response = ""
            start_time = time.time()
            timeout = 3.0
            while time.time() - start_time < timeout:
                if self.ser.in_waiting:
                    try:
                        raw = self.ser.readline()
                        response = raw.decode("utf-8", errors="ignore").strip()
                        break
                    except Exception:
                        continue
                time.sleep(0.05)

            up = (response or "").upper()
            if any(tok in up for tok in ["PASSWORD_OK", "PWD_OK", "SUCCESS"]):
                return True, "Device password updated. Use the new PIN next time."
            if "PASSWORD_FAIL_OLD" in up:
                return False, "Current password is incorrect"
            if "PASSWORD_FAIL_FORMAT" in up or "FAIL" in up:
                return False, "Invalid password format"
            if not response:
                return False, "No response from device"
            return False, response
        except Exception as e:
            return False, str(e)[:80]
        finally:
            self.serial_pause = False
