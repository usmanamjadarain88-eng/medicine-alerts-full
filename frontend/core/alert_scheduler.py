import datetime
import schedule
import time
import threading
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib


class AlertScheduler:
    def __init__(self, controller):
        self.app = controller
        self.running = True
        self.scheduled_alerts = {}
        self._sent_reminder_alerts = set()
        self._sent_medicine_alerts = set()
        self._sent_missed_escalation = set()
        self._sent_expiry_alerts = set()
        self._sent_stock_alerts = set()

    def cancel_medicine_alerts_for_box(self, box_id):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        to_discard = [(b, d, t) for (b, d, t) in self._sent_medicine_alerts if b == box_id and d == today]
        for x in to_discard:
            self._sent_medicine_alerts.discard(x)
        to_discard_esc = [(b, d, t) for (b, d, t) in self._sent_missed_escalation if b == box_id and d == today]
        for x in to_discard_esc:
            self._sent_missed_escalation.discard(x)
        for x in list(self._sent_stock_alerts):
            if x[0] == box_id:
                self._sent_stock_alerts.discard(x)
        for x in list(self._sent_expiry_alerts):
            if x[0] == box_id:
                self._sent_expiry_alerts.discard(x)
        prefix = f"{box_id}_"
        for key in list(self.scheduled_alerts.keys()):
            if key.startswith(prefix):
                job = self.scheduled_alerts.pop(key, None)
                if job is not None:
                    try:
                        schedule.cancel_job(job)
                    except Exception:
                        pass

    def schedule_medicine_alert(self, medicine, box_id):
        if not medicine:
            return
        medicine_time = medicine.get("exact_time", medicine.get("time", "08:00"))
        try:
            hour, minute = map(int, str(medicine_time).strip().split(":"))
        except Exception:
            hour, minute = 8, 0
        medicine_alerts = self.app.alert_settings.get("medicine_alerts", {})
        dose_time_str = f"{hour:02d}:{minute:02d}"
        parts = []
        if medicine_alerts.get("15_min_before", True):
            parts.append(f"15min before {dose_time_str}")
        if medicine_alerts.get("exact_time", True):
            parts.append(f"exact {dose_time_str}")
        if medicine_alerts.get("5_min_after", True):
            parts.append(f"5min after {dose_time_str}")
        esc = self.app.alert_settings.get("missed_dose_escalation", {})
        if esc.get("15_min_urgent") or esc.get("30_min_family") or esc.get("1_hour_log"):
            parts.append("missed escalation 15/30/60min + 1h log")
        if parts:
            try:
                msg = f"Alerts for {medicine.get('name', 'Medicine')} ({box_id}): {', '.join(parts)}"
                self.app._log(f"[AlertScheduler] {msg}")
                self.app.status_message.emit(msg)
            except Exception:
                pass

    def send_alert(self, alert_type, medicine, box_id):
        if alert_type == "pre":
            subject = f"⏰ Reminder: {medicine.get('name', 'Medicine')} in 15 minutes"
            body = f"Time to take {medicine.get('name', 'Medicine')} from Box {box_id} is approaching (in 15 minutes)."
        elif alert_type == "time":
            subject = f"✅ TIME NOW: {medicine.get('name', 'Medicine')}"
            body = f"Please take {medicine.get('name', 'Medicine')} from Box {box_id} immediately."
        else:
            subject = f"⚠️ MISSED: {medicine.get('name', 'Medicine')}"
            body = f"You may have missed your {medicine.get('name', 'Medicine')} dose from Box {box_id}."
        try:
            self.app.status_message.emit(body)
        except Exception:
            pass
        email_enabled = self.app.alert_settings.get("email_alerts", {}).get("enabled", False)
        if email_enabled:
            self.send_gmail_alert(subject, body)
        # pre, time, 5min missed → user only (admin gets only escalation 15/30min + dose_taken + system_unlocked + login + daily summary)
        try:
            self.app.send_mobile_alert(alert_type, body)
        except Exception:
            pass

    def _check_medicine_alerts(self):
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_hm = (now.hour, now.minute)
        self._sent_medicine_alerts = {(b, d, t) for (b, d, t) in self._sent_medicine_alerts if d >= today_str}
        self._sent_missed_escalation = {(b, d, t) for (b, d, t) in self._sent_missed_escalation if d >= today_str}
        boxes = getattr(self.app, "medicine_boxes", {}) or {}
        medicine_alerts = self.app.alert_settings.get("medicine_alerts", {})
        esc = self.app.alert_settings.get("missed_dose_escalation", {})

        for box_id, medicine in boxes.items():
            if not medicine:
                continue
            medicine_time = medicine.get("exact_time", medicine.get("time", "08:00"))
            try:
                h, m = map(int, str(medicine_time).strip().split(":"))
            except Exception:
                h, m = 8, 0
            try:
                dose_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if dose_dt > now:
                    dose_dt = dose_dt - datetime.timedelta(days=1)
            except ValueError:
                continue

            if medicine_alerts.get("15_min_before", True):
                if m >= 15:
                    h_before, m_before = h, m - 15
                else:
                    m_before = m + 45
                    h_before = 23 if h == 0 else h - 1
                if (h_before, m_before) == current_hm and (box_id, today_str, "pre") not in self._sent_medicine_alerts:
                    self._sent_medicine_alerts.add((box_id, today_str, "pre"))
                    self.send_alert("pre", medicine, box_id)
            if medicine_alerts.get("exact_time", True):
                if (h, m) == current_hm and (box_id, today_str, "time") not in self._sent_medicine_alerts:
                    self._sent_medicine_alerts.add((box_id, today_str, "time"))
                    self.send_alert("time", medicine, box_id)
            if medicine_alerts.get("5_min_after", True):
                total_mins = h * 60 + m + 5
                h_5 = (total_mins // 60) % 24
                m_5 = total_mins % 60
                if (h_5, m_5) == current_hm and (box_id, today_str, "5min") not in self._sent_medicine_alerts:
                    self._sent_medicine_alerts.add((box_id, today_str, "5min"))
                    self.send_alert("missed", medicine, box_id)

            if (box_id, today_str, "5min") not in self._sent_medicine_alerts:
                continue
            if now < dose_dt + datetime.timedelta(minutes=15):
                continue
            if esc.get("15_min_urgent", True) and (box_id, today_str, "15min") not in self._sent_missed_escalation:
                if now >= dose_dt + datetime.timedelta(minutes=15):
                    self._sent_missed_escalation.add((box_id, today_str, "15min"))
                    subject = f"⚠️ URGENT: Missed dose – {medicine.get('name', 'Medicine')} (Box {box_id})"
                    body = f"15 minutes past dose time. Please take {medicine.get('name', 'Medicine')} from Box {box_id}."
                    try:
                        self.app.status_message.emit(body)
                    except Exception:
                        pass
                    if self.app.alert_settings.get("email_alerts", {}).get("enabled"):
                        self.send_gmail_alert(subject, body)
                    try:
                        self.app.send_admin_alert("missed", body)
                    except Exception:
                        pass
            if now >= dose_dt + datetime.timedelta(minutes=30) and (box_id, today_str, "30min") not in self._sent_missed_escalation:
                if esc.get("30_min_family", True):
                    self._sent_missed_escalation.add((box_id, today_str, "30min"))
                    family_email = (esc.get("family_email") or "").strip()
                    subject = f"⚠️ Missed dose (30 min): {medicine.get('name', 'Medicine')} – Box {box_id}"
                    body = f"Patient may have missed {medicine.get('name', 'Medicine')} from Box {box_id} (30 minutes ago)."
                    try:
                        self.app.status_message.emit(body)
                    except Exception:
                        pass
                    if self.app.alert_settings.get("email_alerts", {}).get("enabled"):
                        self.send_gmail_alert(subject, body)
                    if family_email:
                        try:
                            self._send_to_recipient(subject, body, family_email)
                        except Exception:
                            pass
                    try:
                        self.app.send_admin_alert("missed", body)
                    except Exception:
                        pass
            if now >= dose_dt + datetime.timedelta(hours=1) and (box_id, today_str, "1h") not in self._sent_missed_escalation:
                if esc.get("1_hour_log", True):
                    self._sent_missed_escalation.add((box_id, today_str, "1h"))
                    dose_log = getattr(self.app, "dose_log", [])
                    if not isinstance(dose_log, list):
                        dose_log = []
                    dose_log.append({
                        "date": today_str,
                        "time": f"{h:02d}:{m:02d}",
                        "box_id": box_id,
                        "medicine": medicine.get("name", "Medicine"),
                        "status": "missed",
                    })
                    self.app.dose_log = dose_log
                    try:
                        self.app.save_data()
                    except Exception:
                        pass
                    try:
                        self.app.medicine_updated.emit()
                    except Exception:
                        pass

    def send_gmail_alert(self, subject, body):
        try:
            sender_email = self.app.gmail_config.get("sender_email", "")
            sender_password = self.app.gmail_config.get("sender_password", "")
            if not sender_email or not sender_password:
                return
            recipient_text = self.app.gmail_config.get("recipients", "")
            recipient_list = [e.strip() for e in recipient_text.split(",") if e.strip()] if recipient_text else [sender_email]
            self._send_to_recipient(subject, body, recipient_list)
        except Exception as e:
            print(f"Failed to send email: {e}")

    def _send_to_recipient(self, subject, body, recipient):
        try:
            sender_email = self.app.gmail_config.get("sender_email", "")
            sender_password = self.app.gmail_config.get("sender_password", "")
            if not sender_email or not sender_password:
                return
            if isinstance(recipient, str):
                recipient_list = [e.strip() for e in recipient.split(",") if e.strip()]
            else:
                recipient_list = [e.strip() for e in recipient if (e and e.strip())]
            if not recipient_list:
                return
            # Keep delivery resilient: skip invalid addresses instead of failing all.
            email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
            valid_recipients = [e for e in recipient_list if email_re.match(e)]
            if not valid_recipients:
                return
            html = f"<html><body><h3>{subject}</h3><p>{body}</p><p>Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p></body></html>"
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender_email, sender_password)
                for rcpt in valid_recipients:
                    msg = MIMEMultipart()
                    msg["From"] = sender_email
                    msg["To"] = rcpt
                    msg["Subject"] = subject
                    msg.attach(MIMEText(html, "html"))
                    try:
                        server.send_message(msg)
                    except Exception:
                        # Continue sending remaining recipients.
                        continue
        except Exception as e:
            print(f"Failed to send email: {e}")

    def _check_medical_reminder_alerts(self):
        now = datetime.datetime.now()
        reminders_data = getattr(self.app, "medical_reminders", {}) or {}
        for key in ["appointments", "prescriptions", "lab_tests", "custom"]:
            lst = reminders_data.get(key, [])
            for idx, r in enumerate(lst):
                date_str = r.get("date", "")
                time_str = r.get("time", "09:00")
                if not date_str:
                    continue
                try:
                    dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                except Exception:
                    try:
                        dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        continue
                reminders = r.get("reminders", {})
                title = r.get("title", r.get("doctor", r.get("medicine", r.get("test_name", "Reminder"))))
                if reminders.get("24h"):
                    t24 = dt - datetime.timedelta(hours=24)
                    if abs((t24 - now).total_seconds()) < 90 and (key, idx, "24h") not in self._sent_reminder_alerts:
                        self._sent_reminder_alerts.add((key, idx, "24h"))
                        self._send_reminder_alert(title, "24 hours", dt, key)
                if reminders.get("2h"):
                    t2 = dt - datetime.timedelta(hours=2)
                    if abs((t2 - now).total_seconds()) < 90 and (key, idx, "2h") not in self._sent_reminder_alerts:
                        self._sent_reminder_alerts.add((key, idx, "2h"))
                        self._send_reminder_alert(title, "2 hours", dt, key)
                if now > dt + datetime.timedelta(minutes=5):
                    self._sent_reminder_alerts.discard((key, idx, "24h"))
                    self._sent_reminder_alerts.discard((key, idx, "2h"))

    def _check_expiry_alerts(self):
        now = datetime.datetime.now()
        today = now.date()
        expiry_settings = self.app.alert_settings.get("expiry_alerts", {})
        boxes = getattr(self.app, "medicine_boxes", {}) or {}
        for box_id, medicine in boxes.items():
            if not medicine:
                continue
            expiry_str = medicine.get("expiry", "")
            if not expiry_str:
                continue
            try:
                expiry_date = datetime.datetime.strptime(expiry_str.strip()[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            delta = (expiry_date - today).days
            if delta < 0:
                continue
            name = medicine.get("name", "Medicine")
            for key, days in [("30_days_before", 30), ("15_days_before", 15), ("7_days_before", 7), ("1_day_before", 1)]:
                if not expiry_settings.get(key, True):
                    continue
                if delta != days:
                    continue
                tag = key.replace("_days_before", "d")
                if (box_id, expiry_str, tag) in self._sent_expiry_alerts:
                    continue
                self._sent_expiry_alerts.add((box_id, expiry_str, tag))
                subject = f"📅 Expiry alert: {name} (Box {box_id}) in {days} day(s)"
                body = f"{name} in Box {box_id} expires on {expiry_str} ({days} day(s) from now)."
                try:
                    self.app._log(f"[AlertScheduler] Expiry: {body}")
                except Exception:
                    pass
                if self.app.alert_settings.get("email_alerts", {}).get("enabled"):
                    self.send_gmail_alert(subject, body)
                try:
                    self.app.send_admin_alert("expiry", body)
                except Exception:
                    pass

    def _check_stock_alerts(self):
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        stock_settings = self.app.alert_settings.get("stock_alerts", {})
        if not stock_settings.get("enabled", True):
            return
        threshold = int(stock_settings.get("low_stock_threshold", 5))
        empty_alert = stock_settings.get("empty_alert", True)
        critical_alert = stock_settings.get("critical_alert", True)
        boxes = getattr(self.app, "medicine_boxes", {}) or {}
        for box_id, medicine in boxes.items():
            if not medicine:
                continue
            try:
                qty = int(medicine.get("quantity", 0))
            except (TypeError, ValueError):
                qty = 0
            name = medicine.get("name", "Medicine")
            if qty <= 0 and empty_alert:
                if (box_id, today_str, "empty") not in self._sent_stock_alerts:
                    self._sent_stock_alerts.add((box_id, today_str, "empty"))
                    subject = f"📦 Stock alert: {name} (Box {box_id}) is empty"
                    body = f"{name} in Box {box_id} has no stock. Please refill."
                    try:
                        self.app._log(f"[AlertScheduler] Stock: {body}")
                    except Exception:
                        pass
                    if self.app.alert_settings.get("email_alerts", {}).get("enabled"):
                        self.send_gmail_alert(subject, body)
                    try:
                        self.app.send_admin_alert("stock", body)
                    except Exception:
                        pass
            elif qty <= threshold and (critical_alert or stock_settings.get("enabled", True)):
                if (box_id, today_str, "low") not in self._sent_stock_alerts:
                    self._sent_stock_alerts.add((box_id, today_str, "low"))
                    subject = f"📦 Low stock: {name} (Box {box_id}) – {qty} left"
                    body = f"{name} in Box {box_id} has low stock ({qty} left, threshold {threshold})."
                    try:
                        self.app._log(f"[AlertScheduler] Stock: {body}")
                    except Exception:
                        pass
                    if self.app.alert_settings.get("email_alerts", {}).get("enabled"):
                        self.send_gmail_alert(subject, body)
                    try:
                        self.app.send_admin_alert("stock", body)
                    except Exception:
                        pass
        today_str_clean = now.strftime("%Y-%m-%d")
        self._sent_stock_alerts = {(b, d, t) for (b, d, t) in self._sent_stock_alerts if d >= today_str_clean}
        self._sent_expiry_alerts = {(b, e, t) for (b, e, t) in self._sent_expiry_alerts if e >= today_str_clean}

    def _send_reminder_alert(self, title, before_str, event_dt, reminder_type):
        msg = f"Reminder: {title} in {before_str} (at {event_dt.strftime('%Y-%m-%d %H:%M')})"
        try:
            self.app.status_message.emit(msg)
        except Exception:
            pass
        try:
            self.send_gmail_alert(f"⏰ {before_str} before: {title}", msg)
        except Exception:
            pass
        try:
            self.app.send_mobile_alert("reminder", msg)
        except Exception:
            pass

    def _send_daily_admin_summary(self):
        """Send to admin once per day: medicine status + today's dose log."""
        try:
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            lines = ["=== Medicine status ==="]
            boxes = getattr(self.app, "medicine_boxes", {}) or {}
            for box_id, med in sorted(boxes.items()):
                if med:
                    name = med.get("name", "Unknown")
                    qty = med.get("quantity", 0)
                    expiry = med.get("expiry", "") or "-"
                    lines.append(f"Box {box_id}: {name} – qty {qty}, expiry {expiry}")
                else:
                    lines.append(f"Box {box_id}: empty")
            lines.append("")
            lines.append("=== Today's dose log ===")
            dose_log = getattr(self.app, "dose_log", []) or []
            if not isinstance(dose_log, list):
                dose_log = []
            today_entries = [e for e in dose_log if (e.get("timestamp") or "").startswith(today_str)]
            if today_entries:
                for e in reversed(today_entries[-20:]):  # last 20 today
                    ts = e.get("timestamp", "")
                    box = e.get("box", e.get("box_id", ""))
                    med = e.get("medicine", "")
                    dose = e.get("dose_taken", "")
                    rem = e.get("remaining", "")
                    lines.append(f"  {ts} | {box} | {med} | dose {dose} | remaining {rem}")
            else:
                lines.append("  No doses logged today.")
            body = "\n".join(lines)
            self.app.send_admin_alert("daily_summary", body)
        except Exception:
            pass

    def start(self):
        try:
            schedule.every().minute.do(self._check_medical_reminder_alerts)
            self._check_medical_reminder_alerts()
            schedule.every().minute.do(self._check_medicine_alerts)
            self._check_medicine_alerts()
            schedule.every().minute.do(self._check_expiry_alerts)
            self._check_expiry_alerts()
            schedule.every().minute.do(self._check_stock_alerts)
            self._check_stock_alerts()
            schedule.every().day.at("23:00").do(self._send_daily_admin_summary)
        except Exception:
            pass
        def run():
            while self.running:
                try:
                    schedule.run_pending()
                except Exception:
                    pass
                time.sleep(0.2)
        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self.running = False
        schedule.clear()
