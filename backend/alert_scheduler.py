"""
Backend alert scheduler: event-based. Alert checks run when data changes (API writes),
not on a fixed timer. Sends alerts via relay WebSocket and Gmail SMTP.
Daily summary still runs once at 23:00.
"""
import datetime
import time
import threading
import json
import re
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import schedule

RELAY_URL = "wss://curax-relay.onrender.com"


class BackendAlertScheduler:
    def __init__(self, get_db_func):
        """get_db_func: callable that returns a CentralDB instance (or None)."""
        self._get_db = get_db_func
        self.running = False
        self._thread = None
        # Per-admin dedup state keyed by admin_id
        self._admin_state = {}

    # ---- Per-admin state container ----

    def _state(self, admin_id, user_id=None):
        """State keyed by (admin_id, user_id). Use user_id=None for dashboard."""
        key = f"{admin_id}_{user_id or 'dashboard'}"
        if key not in self._admin_state:
            self._admin_state[key] = {
                "sent_medicine": set(),
                "sent_escalation": set(),
                "sent_reminder": set(),
                "condition_alert": {},
            }
        return self._admin_state[key]

    # ---- Data loading helpers ----

    def _load_admin_context(self, db, admin):
        """Load all data needed to run checks for one admin. Returns dict or None."""
        admin_id = admin["id"]
        duid = db.get_dashboard_user_id(admin_id)
        if not duid:
            return None

        medicines_raw = db.list_medicines(duid) or []
        settings_blob = db.get_alert_settings(duid) or {}
        if not isinstance(settings_blob, dict):
            settings_blob = {}

        medicine_meta = settings_blob.get("medicine_meta") if isinstance(settings_blob.get("medicine_meta"), dict) else {}
        alert_settings = settings_blob.get("alert_settings") if isinstance(settings_blob.get("alert_settings"), dict) else {}
        gmail_config = settings_blob.get("gmail_config") if isinstance(settings_blob.get("gmail_config"), dict) else {}
        medical_reminders = settings_blob.get("medical_reminders") if isinstance(settings_blob.get("medical_reminders"), dict) else {}

        # Admin bot config synced from desktop (admin must configure on desktop)
        admin_bot_config = settings_blob.get("admin_bot_config") if isinstance(settings_blob.get("admin_bot_config"), dict) else {}

        boxes = {}
        for m in medicines_raw:
            box_id = (m.get("box_id") or "B1").strip().upper()
            times = m.get("times") if isinstance(m.get("times"), list) else []
            meta = medicine_meta.get(box_id) if isinstance(medicine_meta.get(box_id), dict) else {}
            exact_time = (meta.get("exact_time") or "").strip() or (times[0] if times else "08:00")
            expiry = (meta.get("expiry") or "").strip()
            qty = 0
            try:
                qty = int(m.get("quantity", 0))
            except (TypeError, ValueError):
                pass
            boxes[box_id] = {
                "name": (m.get("name") or "").strip() or "Medicine",
                "quantity": qty,
                "exact_time": exact_time,
                "expiry": expiry,
                "times": times,
            }

        users = db.get_all_users_by_admin_id(admin_id) or []
        dose_logs = db.list_dose_logs(duid, limit=200) if hasattr(db, "list_dose_logs") else []

        # Desktop-synced mobile_bot_config for user alerts
        mobile_bot_config = settings_blob.get("mobile_bot_config") if isinstance(settings_blob.get("mobile_bot_config"), dict) else {}

        return {
            "admin_id": admin_id,
            "duid": duid,
            "admin_bot_id": admin.get("bot_id", ""),
            "admin_api_key": admin.get("api_key", ""),
            "mobile_bot_config": mobile_bot_config,
            "users": users,
            "boxes": boxes,
            "alert_settings": alert_settings,
            "gmail_config": gmail_config,
            "medical_reminders": medical_reminders,
            "dose_logs": dose_logs,
        }

    def _load_user_context(self, db, admin_ctx, user_id, user_bot_id, user_api_key, user_name):
        """Build context for one connected user: that user's medicines/boxes/dose_logs, same alert_settings/gmail/admin_bot. Admin receives all alerts from all users."""
        medicines_raw = db.list_medicines(user_id) or []
        settings_blob = db.get_alert_settings(user_id) or {}
        if not isinstance(settings_blob, dict):
            settings_blob = {}
        medicine_meta = settings_blob.get("medicine_meta") if isinstance(settings_blob.get("medicine_meta"), dict) else {}
        if not medicine_meta and isinstance(admin_ctx.get("duid"), str):
            dashboard_settings = db.get_alert_settings(admin_ctx["duid"]) or {}
            if isinstance(dashboard_settings, dict):
                medicine_meta = dashboard_settings.get("medicine_meta") if isinstance(dashboard_settings.get("medicine_meta"), dict) else {}

        boxes = {}
        for m in medicines_raw:
            box_id = (m.get("box_id") or "B1").strip().upper()
            times = m.get("times") if isinstance(m.get("times"), list) else []
            meta = medicine_meta.get(box_id) if isinstance(medicine_meta.get(box_id), dict) else {}
            exact_time = (meta.get("exact_time") or "").strip() or (times[0] if times else "08:00")
            expiry = (meta.get("expiry") or "").strip()
            qty = 0
            try:
                qty = int(m.get("quantity", 0))
            except (TypeError, ValueError):
                pass
            boxes[box_id] = {
                "name": (m.get("name") or "").strip() or "Medicine",
                "quantity": qty,
                "exact_time": exact_time,
                "expiry": expiry,
                "times": times,
            }

        dose_logs = db.list_dose_logs(user_id, limit=200) if hasattr(db, "list_dose_logs") else []
        prefix = f"[{user_name or 'User'}] " if (user_name or "").strip() else ""
        return {
            "admin_id": admin_ctx["admin_id"],
            "duid": user_id,
            "admin_bot_id": admin_ctx.get("admin_bot_id", ""),
            "admin_api_key": admin_ctx.get("admin_api_key", ""),
            "mobile_bot_config": {},
            "users": [],
            "boxes": boxes,
            "alert_settings": admin_ctx.get("alert_settings") or {},
            "gmail_config": admin_ctx.get("gmail_config") or {},
            "medical_reminders": admin_ctx.get("medical_reminders") or {},
            "dose_logs": dose_logs,
            "single_user_mode": True,
            "user_bot_id": (user_bot_id or "").strip(),
            "user_api_key": (user_api_key or "").strip(),
            "user_name": (user_name or "").strip(),
            "message_prefix": prefix,
        }

    # ---- Alert delivery ----

    def _send_via_relay(self, bot_id, api_key, alert_type, message):
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key:
            return False
        try:
            import websockets

            async def _ws_send():
                async with websockets.connect(RELAY_URL, close_timeout=2, open_timeout=15) as ws:
                    await ws.send(json.dumps({
                        "action": "alert",
                        "bot_id": bot_id,
                        "api_key": api_key,
                        "type": alert_type,
                        "message": message,
                    }))

            asyncio.run(_ws_send())
            return True
        except Exception as e:
            print(f"[AlertScheduler] relay send failed ({bot_id[:6]}...): {e}")
            return False

    def _send_user_alerts(self, ctx, alert_type, message):
        """Send alert to users. Desktop-synced mobile_bot_config is the essential
        source; users linked via connection code are additional recipients."""
        if ctx.get("single_user_mode") and ctx.get("user_bot_id") and ctx.get("user_api_key"):
            self._send_via_relay(ctx["user_bot_id"], ctx["user_api_key"], alert_type, message)
            return
        sent_keys = set()
        # Desktop-configured mobile_bot_config (essential -- admin enters on desktop)
        mbc = ctx.get("mobile_bot_config") or {}
        mbid = (mbc.get("bot_id") or "").strip()
        makey = (mbc.get("api_key") or "").strip()
        if mbid and makey:
            sent_keys.add((mbid, makey))
            self._send_via_relay(mbid, makey, alert_type, message)
        # Users linked via connection code (additional)
        for user in ctx["users"]:
            bid = (user.get("bot_id") or "").strip()
            akey = (user.get("api_key") or "").strip()
            if bid and akey and (bid, akey) not in sent_keys:
                sent_keys.add((bid, akey))
                self._send_via_relay(bid, akey, alert_type, message)

    def _send_admin_alert(self, ctx, alert_type, message):
        """Send alert to admin's mobile app. Credentials from admins table
        (auto-stored when admin registers on Android app with access code)."""
        bid = (ctx.get("admin_bot_id") or "").strip()
        akey = (ctx.get("admin_api_key") or "").strip()
        if bid and akey:
            self._send_via_relay(bid, akey, alert_type, message)

    def _notify_user_and_admin(self, ctx, alert_type, subject, body, send_email=True):
        """Send to user(s) and always to admin. In single_user_mode sends to that user + admin; body is prefixed with [User name]."""
        prefix = ctx.get("message_prefix") or ""
        if prefix:
            body = prefix + body
            subject = prefix.strip() + " " + subject if subject else subject
        if send_email:
            email_enabled = ctx["alert_settings"].get("email_alerts", {}).get("enabled", False)
            if email_enabled:
                self._send_gmail(ctx["gmail_config"], subject, body)
        self._send_user_alerts(ctx, alert_type, body)
        self._send_admin_alert(ctx, alert_type, body)

    def _send_gmail(self, gmail_config, subject, body):
        try:
            sender_email = (gmail_config.get("sender_email") or "").strip()
            sender_password = (gmail_config.get("sender_password") or "").strip()
            if not sender_email or not sender_password:
                return
            recipient_text = gmail_config.get("recipients", "")
            recipient_list = [e.strip() for e in recipient_text.split(",") if e.strip()] if recipient_text else [sender_email]
            self._send_email_to(sender_email, sender_password, subject, body, recipient_list)
        except Exception as e:
            print(f"[AlertScheduler] gmail error: {e}")

    def _send_email_to(self, sender_email, sender_password, subject, body, recipients, extra_recipients=None):
        try:
            if isinstance(recipients, str):
                recipients = [e.strip() for e in recipients.split(",") if e.strip()]
            if extra_recipients:
                if isinstance(extra_recipients, str):
                    recipients = recipients + [e.strip() for e in extra_recipients.split(",") if e.strip()]
                else:
                    recipients = recipients + list(extra_recipients)
            email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
            valid = [e for e in recipients if email_re.match(e)]
            if not valid:
                return
            html = f"<html><body><h3>{subject}</h3><p>{body}</p><p>Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p></body></html>"
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(sender_email, sender_password)
                for rcpt in valid:
                    msg = MIMEMultipart()
                    msg["From"] = sender_email
                    msg["To"] = rcpt
                    msg["Subject"] = subject
                    msg.attach(MIMEText(html, "html"))
                    try:
                        server.send_message(msg)
                    except Exception:
                        continue
        except Exception as e:
            print(f"[AlertScheduler] email send error: {e}")

    # ---- Anti-spam / dedup ----

    def _allow_condition_alert(self, state, key):
        now_ts = time.time()
        now_date = datetime.datetime.now().strftime("%Y-%m-%d")
        cond = state["condition_alert"]
        entry = cond.get(key)

        if str(key).startswith("expiry:"):
            if not entry:
                cond[key] = {"count": 1, "next_ts": now_ts + 8 * 3600, "day": now_date}
                return True
            if entry.get("day") != now_date:
                return False
            if int(entry.get("count", 1)) >= 3:
                return False
            if now_ts >= float(entry.get("next_ts", 0)):
                count = int(entry.get("count", 1)) + 1
                cond[key] = {"count": count, "next_ts": now_ts + 8 * 3600, "day": now_date}
                return True
            return False

        if not entry:
            cond[key] = {"count": 1, "next_ts": now_ts + 2 * 3600}
            return True
        if now_ts >= float(entry.get("next_ts", 0)):
            count = int(entry.get("count", 1)) + 1
            gap = 24 * 3600 if count >= 2 else 2 * 3600
            cond[key] = {"count": count, "next_ts": now_ts + gap}
            return True
        return False

    def _clear_condition_alert(self, state, key):
        state["condition_alert"].pop(key, None)

    # ---- Check: medicine timing ----

    def _check_medicine_alerts(self, ctx, state):
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_hm = (now.hour, now.minute)

        state["sent_medicine"] = {(b, d, t) for (b, d, t) in state["sent_medicine"] if d >= today_str}
        state["sent_escalation"] = {(b, d, t) for (b, d, t) in state["sent_escalation"] if d >= today_str}

        alert_cfg = ctx["alert_settings"].get("medicine_alerts", {})
        esc = ctx["alert_settings"].get("missed_dose_escalation", {})

        for box_id, medicine in ctx["boxes"].items():
            if not medicine:
                continue
            medicine_time = medicine.get("exact_time", "08:00")
            try:
                h, m = map(int, str(medicine_time).strip().split(":"))
            except Exception:
                h, m = 8, 0
            try:
                dose_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            except ValueError:
                continue

            name = medicine.get("name", "Medicine")

            # 30 min before
            if alert_cfg.get("30_min_before", True):
                total_mins = h * 60 + m - 30
                if total_mins < 0:
                    total_mins += 24 * 60
                h_30 = (total_mins // 60) % 24
                m_30 = total_mins % 60
                if (h_30, m_30) == current_hm and (box_id, today_str, "pre30") not in state["sent_medicine"]:
                    state["sent_medicine"].add((box_id, today_str, "pre30"))
                    body = f"Medicine {name} from box {box_id} is due in 30 minutes."
                    email_enabled = ctx["alert_settings"].get("email_alerts", {}).get("enabled", False)
                    if email_enabled:
                        self._send_gmail(ctx["gmail_config"], f"Reminder: {name} from box {box_id} in 30 minutes", body)
                    self._send_user_alerts(ctx, "pre30", body)

            # 15 min before
            if alert_cfg.get("15_min_before", True):
                if m >= 15:
                    h_before, m_before = h, m - 15
                else:
                    m_before = m + 45
                    h_before = 23 if h == 0 else h - 1
                if (h_before, m_before) == current_hm and (box_id, today_str, "pre") not in state["sent_medicine"]:
                    state["sent_medicine"].add((box_id, today_str, "pre"))
                    body = f"Medicine {name} from box {box_id} is due in 15 minutes. Time to take soon."
                    email_enabled = ctx["alert_settings"].get("email_alerts", {}).get("enabled", False)
                    if email_enabled:
                        self._send_gmail(ctx["gmail_config"], f"Reminder: {name} from box {box_id} in 15 minutes", body)
                    self._send_user_alerts(ctx, "pre", body)

            # Exact time
            if alert_cfg.get("exact_time", True):
                if (h, m) == current_hm and (box_id, today_str, "time") not in state["sent_medicine"]:
                    state["sent_medicine"].add((box_id, today_str, "time"))
                    body = f"Medicine {name} from box {box_id} \u2013 time to take now."
                    email_enabled = ctx["alert_settings"].get("email_alerts", {}).get("enabled", False)
                    if email_enabled:
                        self._send_gmail(ctx["gmail_config"], f"Time now: {name} from box {box_id}", body)
                    self._send_user_alerts(ctx, "time", body)

            # Missed dose escalation
            delta = now - dose_dt
            minutes_late = delta.total_seconds() / 60.0
            if minutes_late < 5 or minutes_late > 180:
                continue

            # 5 min after
            if esc.get("5_min_reminder", True) and (box_id, today_str, "5min") not in state["sent_escalation"]:
                if 5 <= minutes_late < 15:
                    state["sent_escalation"].add((box_id, today_str, "5min"))
                    subject = f"MISSED REMINDER: {name} from box {box_id}"
                    body = f"Missed reminder: {name} from box {box_id} is 5 minutes late. Please take now if not taken."
                    email_enabled = ctx["alert_settings"].get("email_alerts", {}).get("enabled", False)
                    if email_enabled:
                        self._send_gmail(ctx["gmail_config"], subject, body)
                    self._send_user_alerts(ctx, "missed_reminder", body)

            # 15 min after: urgent (admin + user)
            if esc.get("15_min_urgent", True) and (box_id, today_str, "15min") not in state["sent_escalation"]:
                if 15 <= minutes_late < 30:
                    state["sent_escalation"].add((box_id, today_str, "15min"))
                    subject = f"URGENT: {name} from box {box_id} missed by 15 min"
                    body = f"URGENT: {name} from box {box_id} is 15 minutes overdue. Immediate action required."
                    self._notify_user_and_admin(ctx, "urgent", subject, body, send_email=True)

            # 30 min after: family escalation
            if esc.get("30_min_family", True) and (box_id, today_str, "30min") not in state["sent_escalation"]:
                if 30 <= minutes_late < 60:
                    state["sent_escalation"].add((box_id, today_str, "30min"))
                    family_email = (esc.get("family_email") or "").strip()
                    subject = f"FAMILY ESCALATION: {name} from box {box_id} missed by 30 min"
                    body = f"Family escalation: {name} from box {box_id} is 30 minutes overdue. Please check patient immediately."
                    self._notify_user_and_admin(ctx, "family", subject, body, send_email=True)
                    if family_email:
                        sender_email = (ctx["gmail_config"].get("sender_email") or "").strip()
                        sender_password = (ctx["gmail_config"].get("sender_password") or "").strip()
                        if sender_email and sender_password:
                            try:
                                self._send_email_to(sender_email, sender_password, subject, body, [family_email])
                            except Exception:
                                pass

            # 60+ min after: log as missed in dose_log
            if esc.get("1_hour_log", True) and (box_id, today_str, "1h") not in state["sent_escalation"]:
                if 60 <= minutes_late <= 180:
                    state["sent_escalation"].add((box_id, today_str, "1h"))
                    db = self._get_db()
                    if db:
                        try:
                            ts = f"{today_str} {h:02d}:{m:02d}:00"
                            db.create_dose_log(ctx["duid"], medicine_id=None, box_id=box_id, taken_at=ts, source="missed")
                        except Exception as e:
                            print(f"[AlertScheduler] missed dose log error: {e}")

    # ---- Check: medical reminders ----

    def _check_medical_reminders(self, ctx, state):
        now = datetime.datetime.now()
        reminders_data = ctx.get("medical_reminders") or {}

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
                    if abs((t24 - now).total_seconds()) < 90 and (key, idx, "24h") not in state["sent_reminder"]:
                        state["sent_reminder"].add((key, idx, "24h"))
                        msg = f"Reminder: {title} in 24 hours (at {dt.strftime('%Y-%m-%d %H:%M')})"
                        self._send_gmail(ctx["gmail_config"], f"24 hours before: {title}", msg)
                        self._send_user_alerts(ctx, "reminder", msg)

                if reminders.get("2h"):
                    t2 = dt - datetime.timedelta(hours=2)
                    if abs((t2 - now).total_seconds()) < 90 and (key, idx, "2h") not in state["sent_reminder"]:
                        state["sent_reminder"].add((key, idx, "2h"))
                        msg = f"Reminder: {title} in 2 hours (at {dt.strftime('%Y-%m-%d %H:%M')})"
                        self._send_gmail(ctx["gmail_config"], f"2 hours before: {title}", msg)
                        self._send_user_alerts(ctx, "reminder", msg)

                if now > dt + datetime.timedelta(minutes=5):
                    state["sent_reminder"].discard((key, idx, "24h"))
                    state["sent_reminder"].discard((key, idx, "2h"))

    # ---- Check: expiry alerts ----

    def _check_expiry_alerts(self, ctx, state):
        today = datetime.datetime.now().date()
        expiry_settings = ctx["alert_settings"].get("expiry_alerts", {})

        for box_id, medicine in ctx["boxes"].items():
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
                for k in list(state["condition_alert"].keys()):
                    if k.startswith(f"expiry:{box_id}:{expiry_str}:"):
                        self._clear_condition_alert(state, k)
                continue

            name = medicine.get("name", "Medicine")
            matched_any = False
            for key, days in [("30_days_before", 30), ("15_days_before", 15), ("7_days_before", 7), ("1_day_before", 1)]:
                cond_key = f"expiry:{box_id}:{expiry_str}:{days}"
                if not expiry_settings.get(key, True) or delta != days:
                    self._clear_condition_alert(state, cond_key)
                    continue
                matched_any = True
                if not self._allow_condition_alert(state, cond_key):
                    continue
                subject = f"Expiry alert: {name} (Box {box_id}) in {days} day(s)"
                body = f"{name} in Box {box_id} expires on {expiry_str} ({days} day(s) from now)."
                self._notify_user_and_admin(ctx, "expiry", subject, body, send_email=True)

            if not matched_any:
                for k in list(state["condition_alert"].keys()):
                    if k.startswith(f"expiry:{box_id}:{expiry_str}:"):
                        self._clear_condition_alert(state, k)

    # ---- Check: stock alerts ----

    def _check_stock_alerts(self, ctx, state):
        stock_settings = ctx["alert_settings"].get("stock_alerts", {})
        if not stock_settings.get("enabled", True):
            return

        threshold = int(stock_settings.get("low_stock_threshold", 5))
        empty_alert = stock_settings.get("empty_alert", True)
        critical_alert = stock_settings.get("critical_alert", True)

        for box_id, medicine in ctx["boxes"].items():
            if not medicine:
                continue
            try:
                qty = int(medicine.get("quantity", 0))
            except (TypeError, ValueError):
                qty = 0

            name = medicine.get("name", "Medicine")
            empty_key = f"stock:{box_id}:empty"
            low_key = f"stock:{box_id}:low"

            if qty <= 0 and empty_alert:
                self._clear_condition_alert(state, low_key)
                if self._allow_condition_alert(state, empty_key):
                    subject = f"Stock alert: {name} (Box {box_id}) is empty"
                    body = f"{name} in Box {box_id} has no stock. Please refill."
                    self._notify_user_and_admin(ctx, "stock", subject, body, send_email=True)
            elif qty <= threshold and critical_alert:
                self._clear_condition_alert(state, empty_key)
                if self._allow_condition_alert(state, low_key):
                    subject = f"Low stock: {name} (Box {box_id}) - {qty} left"
                    body = f"{name} in Box {box_id} has low stock ({qty} left, threshold {threshold})."
                    self._notify_user_and_admin(ctx, "stock", subject, body, send_email=True)
            else:
                self._clear_condition_alert(state, empty_key)
                self._clear_condition_alert(state, low_key)

    # ---- Event-based: run checks for one admin (called from API after data changes) ----

    def run_checks_for_admin(self, admin_id):
        """Run medicine/reminder/expiry/stock checks for a single admin. Called when data changes (event-based) instead of polling.
        Safe to call from a background thread; errors are logged and not raised."""
        if not admin_id:
            return
        db = self._get_db()
        if not db:
            return
        try:
            admin = db.get_admin_by_id(admin_id)
            if not admin:
                return
            ctx = self._load_admin_context(db, admin)
            if not ctx:
                return
            aid = ctx["admin_id"]
            duid = ctx["duid"]
            if ctx["boxes"]:
                state = self._state(aid, duid)
                self._check_medicine_alerts(ctx, state)
                self._check_expiry_alerts(ctx, state)
                self._check_stock_alerts(ctx, state)
            self._check_medical_reminders(ctx, self._state(aid, duid))
            for user in ctx.get("users") or []:
                uid = user.get("id")
                bid = (user.get("bot_id") or "").strip()
                akey = (user.get("api_key") or "").strip()
                name = (user.get("name") or "").strip() or "User"
                if not uid:
                    continue
                user_ctx = self._load_user_context(db, ctx, uid, bid, akey, name)
                if not user_ctx["boxes"]:
                    continue
                state = self._state(aid, uid)
                self._check_medicine_alerts(user_ctx, state)
                self._check_expiry_alerts(user_ctx, state)
                self._check_stock_alerts(user_ctx, state)
        except Exception as e:
            print(f"[AlertScheduler] run_checks_for_admin error ({admin_id}): {e}")

    # ---- Daily admin summary ----

    def _send_daily_admin_summary(self, ctx):
        try:
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            lines = ["=== Medicine status ==="]
            for box_id, med in sorted(ctx["boxes"].items()):
                if med:
                    name = med.get("name", "Unknown")
                    qty = med.get("quantity", 0)
                    expiry = med.get("expiry", "") or "-"
                    lines.append(f"Box {box_id}: {name} \u2013 qty {qty}, expiry {expiry}")
                else:
                    lines.append(f"Box {box_id}: empty")
            lines.append("")
            lines.append("=== Today's dose log ===")
            dose_logs = ctx.get("dose_logs") or []
            today_entries = [e for e in dose_logs if isinstance(e, dict) and (e.get("taken_at") or "").startswith(today_str)]
            if today_entries:
                for e in today_entries[-20:]:
                    ts = e.get("taken_at", "")
                    box = e.get("box_id", "")
                    lines.append(f"  {ts} | {box}")
            else:
                lines.append("  No doses logged today.")
            body = "\n".join(lines)
            self._send_admin_alert(ctx, "daily_summary", body)
        except Exception as e:
            print(f"[AlertScheduler] daily summary error: {e}")

    # ---- Main tick: run all checks for all admins ----

    def _tick(self):
        db = self._get_db()
        if not db:
            return
        try:
            admins = db.get_all_active_admins()
        except Exception as e:
            print(f"[AlertScheduler] failed to load admins: {e}")
            return

        for admin in admins:
            try:
                ctx = self._load_admin_context(db, admin)
                if not ctx:
                    continue
                admin_id = ctx["admin_id"]
                duid = ctx["duid"]
                # Dashboard user: medicine/reminder/expiry/stock checks (same as before)
                if ctx["boxes"]:
                    state = self._state(admin_id, duid)
                    self._check_medicine_alerts(ctx, state)
                    self._check_expiry_alerts(ctx, state)
                    self._check_stock_alerts(ctx, state)
                self._check_medical_reminders(ctx, self._state(admin_id, duid))

                # Each connected user: run same medicine/expiry/stock checks; admin receives all alerts
                for user in ctx.get("users") or []:
                    uid = user.get("id")
                    bid = (user.get("bot_id") or "").strip()
                    akey = (user.get("api_key") or "").strip()
                    name = (user.get("name") or "").strip() or "User"
                    if not uid:
                        continue
                    user_ctx = self._load_user_context(db, ctx, uid, bid, akey, name)
                    if not user_ctx["boxes"]:
                        continue
                    state = self._state(admin_id, uid)
                    self._check_medicine_alerts(user_ctx, state)
                    self._check_expiry_alerts(user_ctx, state)
                    self._check_stock_alerts(user_ctx, state)
            except Exception as e:
                print(f"[AlertScheduler] error for admin {admin.get('id', '?')}: {e}")

    def _daily_summary_tick(self):
        db = self._get_db()
        if not db:
            return
        try:
            admins = db.get_all_active_admins()
        except Exception:
            return
        for admin in admins:
            try:
                ctx = self._load_admin_context(db, admin)
                if not ctx:
                    continue
                self._send_daily_admin_summary(ctx)
            except Exception as e:
                print(f"[AlertScheduler] daily summary error for admin {admin.get('id', '?')}: {e}")

    # ---- Lifecycle ----

    def start(self):
        if self.running:
            return
        self.running = True
        self._scheduler = schedule.Scheduler()
        self._scheduler.every().day.at("23:00").do(self._daily_summary_tick)

        print("[AlertScheduler] Event-based: checks run on data change; daily summary at 23:00")

        def run():
            while self.running:
                try:
                    self._scheduler.run_pending()
                except Exception as e:
                    print(f"[AlertScheduler] tick error: {e}")
                time.sleep(30)

        self._thread = threading.Thread(target=run, daemon=True, name="AlertScheduler")
        self._thread.start()

    def stop(self):
        self.running = False
        if hasattr(self, "_scheduler"):
            self._scheduler.clear()
