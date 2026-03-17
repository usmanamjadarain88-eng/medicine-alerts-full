"""
Backend (one server). All data lives in the database; clients use HTTPS and data bus for updates.
Run: python -m backend.api_server or from backend/ python api_server.py
"""
import os
import threading
from flask import Flask, request, jsonify

_backend_dir = os.path.abspath(os.path.dirname(__file__))
# Load .env if present (DATABASE_URL from backend/.env when running locally)
_env_path = os.path.join(_backend_dir, ".env")
if os.path.isfile(_env_path):
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

# Load DATABASE_URL from file if not in environment (works when batch env is not inherited)
if not os.environ.get("DATABASE_URL") and not os.environ.get("CENTRAL_DB_URL"):
    for _path in [
        os.path.join(_backend_dir, "database_url.txt"),
        os.path.join(os.getcwd(), "backend", "database_url.txt"),
        os.path.join(os.getcwd(), "database_url.txt"),
    ]:
        if os.path.isfile(_path):
            try:
                with open(_path, "r", encoding="utf-8") as _f:
                    for _line in _f:
                        _url = _line.strip()
                        if _url and not _url.startswith("#"):
                            os.environ["DATABASE_URL"] = _url
                            break
                if os.environ.get("DATABASE_URL"):
                    break
            except Exception:
                pass

app = Flask(__name__)


@app.after_request
def _log_request(response):
    """Log every request so the terminal shows GET/POST and status codes."""
    try:
        print(f"  {request.method} {request.path} -> {response.status_code}")
    except Exception:
        pass
    return response


def get_data_bus_url():
    """Base URL of the data bus (e.g. http://127.0.0.1:5052). Used to POST /notify_admin when admin data changes."""
    url = (os.environ.get("DATA_BUS_URL") or "").strip()
    if url:
        return url.rstrip("/")
    for _path in [
        os.path.join(_backend_dir, "data_bus_url.txt"),
        os.path.join(os.getcwd(), "backend", "data_bus_url.txt"),
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
    # Default: deployed data bus on Railway (receives notify_admin from backend for real-time sync)
    return "https://databus-production.up.railway.app"


try:
    from .central_db import EmailAlreadyUsedError
except ImportError:
    from central_db import EmailAlreadyUsedError


def notify_databus(access_code):
    """Tell the data bus to push latest admin data to desktop and app (so changes appear in real time)."""
    code = (access_code or "").strip()
    if not code:
        return
    base = get_data_bus_url()
    if not base:
        return
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(
            base + "/notify_admin",
            data=_json.dumps({"access_code": code}).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            if 200 <= getattr(resp, "status", 0) < 300:
                pass  # success
            else:
                print(f"  [notify_databus] data bus returned {getattr(resp, 'status', 0)}")
    except Exception as e:
        print(f"  [notify_databus] failed: {e}")


def get_db():
    try:
        from .central_db import CentralDB
    except ImportError:
        from central_db import CentralDB
    url = os.environ.get("DATABASE_URL") or os.environ.get("CENTRAL_DB_URL")
    if not url:
        # Fallback: read from file (in case env was not inherited)
        for _path in [
            os.path.join(_backend_dir, "database_url.txt"),
            os.path.join(os.getcwd(), "backend", "database_url.txt"),
        ]:
            if os.path.isfile(_path):
                try:
                    with open(_path, "r", encoding="utf-8") as _f:
                        for _line in _f:
                            url = _line.strip()
                            if url and not url.startswith("#"):
                                os.environ["DATABASE_URL"] = url
                                break
                except Exception:
                    pass
    if not url:
        return None
    db = CentralDB(connection_string=url)
    if not db.is_available():
        return None
    return db


# ---- Root / health (so URL in browser doesn't 404) ----
@app.route("/")
def root():
    """So visiting the backend URL in a browser shows something instead of 404."""
    return jsonify({"status": "ok", "message": "Medicine Alerts API", "docs": "Use POST/GET /save-credentials, /admin/data, /medicines, etc."})


@app.route("/health", methods=["GET"])
def health():
    """Health check for Railway/monitoring."""
    db = get_db()
    return jsonify({"status": "ok", "database": "connected" if (db and db.is_available()) else "disconnected"})


# ---- Auth / credentials ----
@app.route("/save-credentials", methods=["POST"])
def save_credentials():
    """POST { bot_id, api_key, role?, access_code? (for admin), fcm_token? } → admins or users.
    If role=admin and access_code is sent, update that admin's bot_id/api_key (so app links to desktop-created admin).
    """
    data = request.get_json() or {}
    bot_id = (data.get("bot_id") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    role = (data.get("role") or "user").strip().lower()
    access_code = (data.get("access_code") or "").strip()
    fcm_token = (data.get("fcm_token") or "").strip()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not bot_id or not api_key:
        return jsonify({"message": "bot_id and api_key required"}), 400
    deleted_info = getattr(db, "get_deleted_user_notification", None) and db.get_deleted_user_notification(bot_id, api_key)
    if deleted_info:
        return jsonify({
            "reason": "deleted_by_admin",
            "message": deleted_info.get("message", "The admin has removed you from their account."),
        }), 410
    if role == "admin":
        try:
            if access_code:
                admin_id, admin_access_code, connection_code = db.update_admin_bot_by_access_code(
                    access_code, bot_id, api_key, name=name, email=email, fcm_token=fcm_token or None
                )
                if admin_id:
                    notify_databus(admin_access_code or access_code)
                    return jsonify({"message": "ok", "admin_id": admin_id, "admin_access_code": admin_access_code or None, "connection_code": connection_code or None})
            admin_id, admin_access_code, connection_code = db.upsert_admin_from_bot(bot_id, api_key, name=name, email=email, fcm_token=fcm_token or None)
            if admin_access_code:
                notify_databus(admin_access_code)
            return jsonify({"message": "ok", "admin_id": admin_id, "admin_access_code": admin_access_code or None, "connection_code": connection_code or None})
        except EmailAlreadyUsedError:
            return jsonify({"message": "An admin with this email already exists. Delete the existing admin first."}), 409
    admin_id = data.get("admin_id")
    if not admin_id:
        return jsonify({"message": "admin_id required for role=user"}), 400
    user_id = db.upsert_user_from_bot(bot_id, api_key, admin_id, name=name, fcm_token=fcm_token or None)
    return jsonify({"message": "ok", "user_id": user_id})


@app.route("/connect-to-admin", methods=["POST"])
def connect_to_admin():
    """POST { connection_code, bot_id, api_key, name?, email? } → link this app (user) to the admin with that connection_code.
    If email is sent, any previous user row for the same admin+email (e.g. old install) is removed so the same person has only one entry.
    """
    data = request.get_json() or {}
    connection_code = (data.get("connection_code") or "").strip()
    bot_id = (data.get("bot_id") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not connection_code or not bot_id or not api_key:
        return jsonify({"message": "connection_code, bot_id and api_key required"}), 400
    admin = db.get_admin_by_connection_code(connection_code)
    if not admin:
        return jsonify({"message": "Invalid connection code"}), 404
    admin_id = admin.get("id")
    admin_name = admin.get("name") or ""
    user_id = db.upsert_user_from_bot(bot_id, api_key, admin_id, name=name, email=email or None)
    if not user_id:
        return jsonify({"message": "Failed to link user"}), 500
    return jsonify({"message": "ok", "admin_id": admin_id, "user_id": user_id, "admin_name": admin_name})


def _wake_relay_if_needed(relay_url):
    """Hit relay HTTP /status to wake it (e.g. Render cold start). Ignore errors; WebSocket will retry."""
    try:
        import urllib.request as _urllib
        http_url = relay_url.replace("wss://", "https://", 1).replace("ws://", "http://", 1).rstrip("/")
        req = _urllib.Request(http_url + "/status", method="GET")
        _urllib.urlopen(req, timeout=45)
    except Exception:
        pass


def _send_alert_via_relay(bot_id, api_key, alert_type, message, fcm_token=None):
    """Send alert to relay so it reaches the user at any cost. FCM token from DB so push works even when phone is off.
    Wakes relay if cold (Render), then retries WebSocket with long timeouts until relay is up; relay sends via FCM."""
    import json
    import asyncio
    import time
    import urllib.request
    bot_id = (bot_id or "").strip()
    api_key = (api_key or "").strip()
    if not bot_id or not api_key:
        return False, "Missing bot_id or api_key"
    relay_url = os.environ.get("RELAY_URL", "wss://curax-relay.onrender.com").strip()
    payload = {
        "action": "alert",
        "bot_id": bot_id,
        "api_key": api_key,
        "type": alert_type or "alert",
        "message": message or "",
    }
    fcm = (fcm_token or "").strip() or None
    if fcm:
        payload["fcm_token"] = fcm
    last_error = None
    # Wake relay first (GET /status) so cold start begins; then retry WebSocket until relay is up
    _wake_relay_if_needed(relay_url)
    time.sleep(3)
    # 5 attempts with backoff: 3s, +5s, +15s, +30s, +45s between attempts; 60s open_timeout each
    delays = (0, 5, 15, 30, 45)
    for attempt in range(5):
        if attempt > 0:
            time.sleep(delays[attempt])
        try:
            import websockets
            async def _ws_send():
                async with websockets.connect(relay_url, close_timeout=15, open_timeout=60) as ws:
                    await ws.send(json.dumps(payload))
            asyncio.run(_ws_send())
            return True, None
        except Exception as e:
            last_error = str(e).strip() or repr(e)
            print(f"[notify-event] relay attempt {attempt + 1}/5 ({bot_id[:8]}...): {e}")
    err_msg = (last_error or "Unknown error")[:200]
    return False, err_msg


@app.route("/notify-event", methods=["POST"])
def notify_event():
    """POST { access_code, event_type, message } → desktop tells backend of admin-only events.
    Backend finds admin bot_id+api_key by access_code, sends alert to relay → admin's app (FCM preferred).
    Events: system_started, system_unlocked, admin_login, dose_taken, etc.
    """
    data = request.get_json() or {}
    access_code = (data.get("access_code") or "").strip()
    event_type = (data.get("event_type") or "alert").strip()
    message = (data.get("message") or "").strip()
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    bot = db.get_admin_bot_by_access_code(access_code)
    if not bot:
        return jsonify({"message": "Admin not found or credentials not yet registered (admin must sign up on app first)"}), 404
    bid, akey, fcm = bot.get("bot_id"), bot.get("api_key"), bot.get("fcm_token")
    def _deliver():
        _send_alert_via_relay(bid, akey, event_type, message, fcm_token=fcm)
    threading.Thread(target=_deliver, daemon=True, name="NotifyRelay").start()
    return jsonify({"message": "ok"}), 200


@app.route("/notify-event-by-user", methods=["POST"])
def notify_event_by_user():
    """POST { bot_id, api_key, event_type, message } → from a user's desktop/app.
    Backend finds that user's admin, sends alert to admin's app via relay, and creates an alert row so admin sees it in Alerts tab. Events: dose_taken, system_started, system_unlocked, etc."""
    data = request.get_json() or {}
    bot_id = (data.get("bot_id") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    event_type = (data.get("event_type") or "alert").strip()
    message = (data.get("message") or "").strip()
    if not bot_id or not api_key:
        return jsonify({"message": "bot_id and api_key required"}), 400
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    info = db.get_user_and_admin_bot_by_user_bot(bot_id, api_key)
    if not info:
        deleted_info = getattr(db, "get_deleted_user_notification", None) and db.get_deleted_user_notification(bot_id, api_key)
        if deleted_info:
            return jsonify({
                "reason": "deleted_by_admin",
                "message": deleted_info.get("message", "The admin has removed you from their account."),
            }), 410
        return jsonify({"message": "User not found or not linked to an admin"}), 404
    admin_bot_id = info.get("admin_bot_id") or ""
    admin_api_key = info.get("admin_api_key") or ""
    if not admin_bot_id or not admin_api_key:
        return jsonify({"message": "Admin app not registered yet"}), 404
    try:
        db.create_alert(info["user_id"], info["admin_id"], event_type, message)
    except Exception:
        pass
    admin_fcm = db.get_fcm_token_for_bot(admin_bot_id, admin_api_key)
    def _deliver():
        _send_alert_via_relay(admin_bot_id, admin_api_key, event_type, message, fcm_token=admin_fcm)
    threading.Thread(target=_deliver, daemon=True, name="NotifyRelay").start()
    return jsonify({"message": "ok"}), 200


@app.route("/notify-event-to-user", methods=["POST"])
def notify_event_to_user():
    """POST { bot_id, api_key, event_type, message } → send alert to that user's app (e.g. desktop 'Test alert' in user view).
    Backend verifies the user exists, then sends to relay so the user's app receives the alert."""
    data = request.get_json() or {}
    bot_id = (data.get("bot_id") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    event_type = (data.get("event_type") or "alert").strip()
    message = (data.get("message") or "").strip()
    if not bot_id or not api_key:
        return jsonify({"message": "bot_id and api_key required"}), 400
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    user_id = db.get_user_id_by_bot(bot_id, api_key)
    if not user_id:
        deleted_info = getattr(db, "get_deleted_user_notification", None) and db.get_deleted_user_notification(bot_id, api_key)
        if deleted_info:
            return jsonify({
                "reason": "deleted_by_admin",
                "message": deleted_info.get("message", "The admin has removed you from their account."),
            }), 410
        return jsonify({"message": "User not found or not linked to an admin"}), 404
    user_fcm = db.get_fcm_token_for_bot(bot_id, api_key)
    def _deliver():
        _send_alert_via_relay(bot_id, api_key, event_type, message, fcm_token=user_fcm)
    threading.Thread(target=_deliver, daemon=True, name="NotifyRelay").start()
    return jsonify({"message": "ok"}), 200


@app.route("/admin/linked-users", methods=["GET"])
def get_linked_users():
    """GET /admin/linked-users?access_code=... -> list of users linked to this admin (excluding dashboard user)."""
    access_code = (request.args.get("access_code") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"users": []}), 503
    if not access_code:
        return jsonify({"users": []}), 400
    admin = db.get_admin_by_access_code(access_code)
    if not admin:
        return jsonify({"users": []}), 404
    admin_id = admin.get("id")
    users = db.get_all_users_by_admin_id(admin_id) or []
    return jsonify({"users": users})


@app.route("/admin/fcm-token", methods=["PUT"])
def put_admin_fcm_token():
    """PUT { access_code, fcm_token } → update admin's FCM token. Called when app gets FCM token (e.g. after permission).
    So push alerts (and Test alert) work; relay uses FCM first when available."""
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or "").strip()
    fcm_token = (data.get("fcm_token") or "").strip()
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    ok = db.update_admin_fcm_token_by_access_code(access_code, fcm_token if fcm_token else None)
    if not ok:
        return jsonify({"message": "Admin not found for this access code"}), 404
    return jsonify({"message": "ok"})


@app.route("/admin/connection", methods=["GET"])
def get_admin_connection():
    """GET /admin/connection?access_code=... → { fcm_token_set, connected, linked_users } for Connection panel.
    connected = admin has bot_id+api_key (app has registered); fcm_token_set = FCM token stored for push."""
    access_code = (request.args.get("access_code") or "").strip()
    if not access_code:
        return jsonify({"message": "access_code required", "fcm_token_set": False, "connected": False, "linked_users": []}), 400
    db = get_db()
    if not db:
        return jsonify({"fcm_token_set": False, "connected": False, "linked_users": []}), 503
    status = db.get_admin_connection_status(access_code)
    if not status:
        return jsonify({"fcm_token_set": False, "connected": False, "linked_users": []}), 404
    admin = db.get_admin_by_access_code(access_code)
    admin_id = admin.get("id") if admin else None
    users = db.get_all_users_by_admin_id(admin_id) or [] if admin_id else []
    return jsonify({
        "fcm_token_set": status.get("fcm_token_set", False),
        "connected": status.get("connected", False),
        "linked_users": [{"id": str(u.get("id", "")), "name": u.get("name"), "bot_id": u.get("bot_id")} for u in users],
    })


@app.route("/admin/users/<user_id>", methods=["DELETE"])
def delete_admin_user(user_id):
    """DELETE /admin/users/<user_id> with JSON { "access_code": "..." }. Only admin can delete a connected user.
    User cannot delete themselves; deleted user is informed on next app/desktop request (410)."""
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or request.args.get("access_code") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    result = db.get_role_by_access_code(access_code)
    if not result:
        return jsonify({"message": "Invalid access code"}), 404
    role, admin_id = result
    if role != "admin":
        return jsonify({"message": "Access code is not for admin"}), 403
    user_id = (user_id or "").strip()
    if not user_id:
        return jsonify({"message": "user_id required"}), 400
    ok, user_name = db.delete_user_by_admin(admin_id, user_id)
    if not ok:
        return jsonify({"message": "User not found or not linked to this admin"}), 404
    # Notify admin: create alert using dashboard user so it appears in admin alerts
    try:
        duid = db.get_dashboard_user_id(admin_id)
        if duid:
            db.create_alert(duid, admin_id, "user_removed", f"User {user_name or 'User'} was removed from your account.")
    except Exception:
        pass
    return jsonify({"message": "User deleted", "user_name": user_name or "User"})


@app.route("/verify-credentials", methods=["POST"])
def verify_credentials():
    data = request.get_json() or {}
    bot_id = (data.get("bot_id") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"role": None, "message": "Central DB not configured"}), 503
    result = db.get_role_by_bot(bot_id, api_key)
    if not result:
        deleted_info = getattr(db, "get_deleted_user_notification", None) and db.get_deleted_user_notification(bot_id, api_key)
        if deleted_info:
            return jsonify({
                "role": None,
                "reason": "deleted_by_admin",
                "message": deleted_info.get("message", "The admin has removed you from their account."),
            }), 410
        return jsonify({"role": None, "message": "Invalid credentials"}), 401
    role, id_ = result
    return jsonify({"role": role, "message": "ok", "id": id_})


@app.route("/get-role", methods=["GET"])
def get_role():
    access_code = (request.args.get("access_code") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"role": None, "message": "Central DB not configured"}), 503
    if access_code:
        result = db.get_role_by_access_code(access_code)
        if not result:
            return jsonify({"role": None})
        role, id_ = result
        if role == "admin":
            info = db.get_admin_by_access_code(access_code)
            name = (info or {}).get("name")
            conn_code = (info or {}).get("connection_code")
            return jsonify({"role": "admin", "name": name, "admin_id": id_, "connection_code": conn_code})
    bot_id = (request.args.get("bot_id") or "").strip()
    api_key = (request.args.get("api_key") or "").strip()
    result = db.get_role_by_bot(bot_id, api_key)
    if not result:
        deleted_info = getattr(db, "get_deleted_user_notification", None) and db.get_deleted_user_notification(bot_id, api_key)
        if deleted_info:
            return jsonify({
                "role": None,
                "reason": "deleted_by_admin",
                "message": deleted_info.get("message", "The admin has removed you from their account."),
            }), 410
        return jsonify({"role": None})
    role, id_ = result
    if role == "admin":
        info = db.get_admin_info_from_bot(bot_id, api_key)
        name = (info or {}).get("name")
        conn_code = (info or {}).get("connection_code")
        return jsonify({"role": "admin", "name": name, "admin_id": id_, "connection_code": conn_code})
    return jsonify({"role": "user", "name": None, "user_id": id_})


@app.route("/admin/data", methods=["GET"])
def admin_data():
    """GET /admin/data?access_code=...&last_sync_time=...&act_as_user_id=... (optional).
    If act_as_user_id is set and belongs to this admin, returns that user's data (admin acting as that user)."""
    access_code = (request.args.get("access_code") or "").strip()
    last_sync_time = (request.args.get("last_sync_time") or "").strip() or None
    act_as_user_id = (request.args.get("act_as_user_id") or "").strip() or None
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    result = db.get_role_by_access_code(access_code)
    if not result:
        return jsonify({"message": "Invalid access code"}), 404
    role, admin_id = result
    if role != "admin":
        return jsonify({"message": "Access code is not for admin"}), 403
    if act_as_user_id and db.user_belongs_to_admin(act_as_user_id, admin_id):
        data = db.get_user_data_for_admin(admin_id, act_as_user_id, last_sync_time=last_sync_time)
    else:
        data = db.get_admin_dashboard_data(admin_id, last_sync_time=last_sync_time)
    if data is None:
        return jsonify({"message": "Failed to load admin data"}), 500
    # Normalize so app always gets same structure: lists are never None, each medicine has "times" as list
    medicines = data.get("medicines") or []
    out = {
        "medicines": [dict(m) for m in medicines],
        "dose_logs": data.get("dose_logs") or [],
        "alert_settings": data.get("alert_settings") if data.get("alert_settings") is not None else {},
        "alerts": data.get("alerts") or [],
        "medical_reminders": data.get("medical_reminders") if data.get("medical_reminders") is not None else {"appointments": [], "prescriptions": [], "lab_tests": [], "custom": []},
        "server_time": data.get("server_time") or "",
        "incremental": bool(data.get("incremental")),
    }
    settings_obj = out["alert_settings"] if isinstance(out["alert_settings"], dict) else {}
    medicine_meta = settings_obj.get("medicine_meta") if isinstance(settings_obj.get("medicine_meta"), dict) else {}
    for m in out["medicines"]:
        if "times" not in m or m["times"] is None:
            m["times"] = []
        elif not isinstance(m["times"], list):
            m["times"] = list(m["times"]) if hasattr(m["times"], "__iter__") and not isinstance(m["times"], str) else []
        if "quantity" not in m or m["quantity"] is None:
            m["quantity"] = 0
        else:
            try:
                m["quantity"] = int(m["quantity"])
            except (TypeError, ValueError):
                m["quantity"] = 0

        box_id = (m.get("box_id") or "").strip().upper()
        meta = medicine_meta.get(box_id) if box_id else None
        if not isinstance(meta, dict):
            meta = {}

        exact_time = (meta.get("exact_time") or "").strip() or (m["times"][0] if m["times"] else "08:00")
        dose_per_day = _safe_int(meta.get("dose_per_day"), 0)
        if dose_per_day <= 0:
            dose_per_day = max(1, len(m["times"]))
        instructions = (meta.get("instructions") or m.get("dosage") or "").strip()
        expiry = (meta.get("expiry") or "").strip()

        m["exact_time"] = exact_time
        m["dose_per_day"] = dose_per_day
        m["instructions"] = instructions
        m["expiry"] = expiry
    if data.get("medicine_box_ids") is not None:
        out["medicine_box_ids"] = data["medicine_box_ids"]
    n_meds = len(out["medicines"])
    if n_meds == 0:
        print(f"  [admin/data] returning 0 medicines for this admin")
    else:
        print(f"  [admin/data] returning {n_meds} medicines")
    return jsonify(out)


@app.route("/admin/sync", methods=["POST"])
def admin_sync():
    """POST { "access_code", "medicine_boxes", "dose_log", "alert_settings", "gmail_config", "medical_reminders", "sms_config" }.
    Write all admin data to Central DB (per admin). Then notify data bus so other clients get the update via WebSocket.
    """
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or "").strip()
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    db = get_db()
    if not db:
        return jsonify({
            "message": "Central DB not configured. Set DATABASE_URL (e.g. Neon connection string) in server environment (e.g. Railway project variables)."
        }), 503
    result = db.get_role_by_access_code(access_code)
    if not result:
        return jsonify({"message": "Invalid access code"}), 404
    role, admin_id = result
    if role != "admin":
        return jsonify({"message": "Access code is not for admin"}), 403
    medicine_boxes = data.get("medicine_boxes") if isinstance(data.get("medicine_boxes"), dict) else {}
    dose_log = data.get("dose_log") if isinstance(data.get("dose_log"), list) else []
    act_as_user_id = (data.get("act_as_user_id") or "").strip() or None
    if act_as_user_id and not db.user_belongs_to_admin(act_as_user_id, admin_id):
        act_as_user_id = None
    if act_as_user_id:
        ok = db.sync_admin_dashboard_data_for_user(admin_id, act_as_user_id, medicine_boxes, dose_log)
        if not ok:
            return jsonify({"message": "Failed to write user data"}), 500
        duid = act_as_user_id
    else:
        try:
            ok = db.sync_admin_dashboard_data(admin_id, medicine_boxes, dose_log)
            if not ok:
                print(f"  [admin/sync] sync_admin_dashboard_data returned False (dashboard user may be missing)")
                return jsonify({"message": "Failed to write dashboard data (no dashboard user)"}), 500
        except Exception as e:
            print(f"  [admin/sync] sync_admin_dashboard_data: {e}")
            return jsonify({"message": "Failed to write dashboard data"}), 500
        duid = db.get_dashboard_user_id(admin_id)
    if duid:
        settings = db.get_alert_settings(duid) or {}
        if isinstance(data.get("alert_settings"), dict):
            settings["alert_settings"] = data["alert_settings"]
        if isinstance(data.get("gmail_config"), dict):
            settings["gmail_config"] = data["gmail_config"]
        if isinstance(data.get("medical_reminders"), dict):
            settings["medical_reminders"] = data["medical_reminders"]
        if isinstance(data.get("sms_config"), dict):
            settings["sms_config"] = data["sms_config"]
        if isinstance(data.get("mobile_bot_config"), dict):
            settings["mobile_bot_config"] = data["mobile_bot_config"]
        if isinstance(data.get("admin_bot_config"), dict):
            settings["admin_bot_config"] = data["admin_bot_config"]

        incoming_meta = _extract_medicine_meta_from_boxes(medicine_boxes)
        existing_meta = settings.get("medicine_meta") if isinstance(settings.get("medicine_meta"), dict) else {}
        merged_meta = {}
        for box in [f"B{i}" for i in range(1, 7)]:
            if box in (medicine_boxes or {}):
                if isinstance((medicine_boxes or {}).get(box), dict) and box in incoming_meta:
                    merged_meta[box] = incoming_meta[box]
            elif box in existing_meta:
                merged_meta[box] = existing_meta[box]
        settings["medicine_meta"] = merged_meta

        if not db.upsert_alert_settings(duid, settings):
            return jsonify({"message": "Failed to save alert settings"}), 500
    notify_databus(access_code)
    _trigger_alert_checks_for_admin(admin_id)
    return jsonify({"message": "ok"})


@app.route("/admin/notify", methods=["POST"])
def admin_notify():
    """POST { "access_code": "..." } → tell data bus to push latest admin data to connected clients (WebSocket)."""
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or "").strip()
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    notify_databus(access_code)
    return jsonify({"message": "ok"})


@app.route("/admin", methods=["DELETE"])
def delete_admin():
    """DELETE /admin with JSON { "access_code": "..." } → delete that admin from Central DB.
    Frees access_code and connection_code so they can be allotted to new admins. Called by desktop when user deletes admin.
    """
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or request.args.get("access_code") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    ok = db.delete_admin_by_access_code(access_code)
    if not ok:
        return jsonify({"message": "Admin not found or already deleted"}), 404
    return jsonify({"message": "Admin deleted", "access_code": access_code})


@app.route("/admin/create-desktop-link-code", methods=["POST"])
def create_desktop_link_code():
    """POST { "access_code": "..." } → admin creates a one-time code for a user to link desktop (user view).
    Returns { "code": "ABC12XYZ", "expires_in": 600 }. Only the admin (with access_code) can create this."""
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    code, admin_id, admin_name = db.create_desktop_link_code(access_code, expires_seconds=300)
    if not code:
        return jsonify({"message": "Invalid access code or could not create code"}), 404
    return jsonify({"code": code, "expires_in": 300, "admin_name": admin_name})


@app.route("/desktop/link-to-admin", methods=["POST"])
def desktop_link_to_admin():
    """POST { "code": "..." } → desktop enters the code from admin; links to that admin (user view only).
    Returns { "admin_id": "...", "admin_name": "..." }. Code is consumed (one-time use)."""
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not code:
        return jsonify({"message": "code required"}), 400
    info = db.get_admin_by_desktop_link_code(code)
    if not info:
        return jsonify({"message": "Invalid or expired code"}), 404
    return jsonify({"admin_id": info["admin_id"], "admin_name": info["admin_name"]})


@app.route("/user/create-desktop-link-code", methods=["POST"])
def user_create_desktop_link_code():
    """POST { "bot_id": "...", "api_key": "..." } → user (app) creates a one-time code for desktop to link to this user.
    Returns { "code": "...", "expires_in": 300, "user_name": "..." }. Code valid 5 min; one-time use."""
    data = request.get_json(silent=True) or {}
    bot_id = (data.get("bot_id") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not bot_id or not api_key:
        return jsonify({"message": "bot_id and api_key required"}), 400
    code, user_id, user_name = db.create_user_desktop_link_code(bot_id, api_key, expires_seconds=300)
    if not code:
        return jsonify({"message": "User not found or could not create code"}), 404
    return jsonify({"code": code, "expires_in": 300, "user_name": user_name})


@app.route("/user/desktop-by-code", methods=["POST"])
def user_desktop_by_code():
    """POST { "code": "..." } → desktop enters the code from the user app; links to that user.
    Returns { "user_id": "...", "user_name": "..." }. Code is consumed (one-time use)."""
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not code:
        return jsonify({"message": "code required"}), 400
    info = db.get_user_by_desktop_link_code(code)
    if not info:
        return jsonify({"message": "Invalid or expired code"}), 404
    return jsonify({
        "user_id": info["user_id"],
        "user_name": info["user_name"],
        "bot_id": info.get("bot_id", ""),
        "api_key": info.get("api_key", ""),
        "admin_id": info.get("admin_id", ""),
        "admin_name": info.get("admin_name", "Admin"),
    })


@app.route("/admin/medical_reminders", methods=["PUT"])
def put_admin_medical_reminders():
    """PUT { "access_code": "...", "medical_reminders": { "appointments": [], "prescriptions": [], "lab_tests": [], "custom": [] } }.
    Updates the dashboard user's alert_settings.medical_reminders. Used by the app Reminders tab.
    """
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or "").strip()
    medical_reminders = data.get("medical_reminders")
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not access_code:
        return jsonify({"message": "access_code required"}), 400
    result = db.get_role_by_access_code(access_code)
    if not result:
        return jsonify({"message": "Invalid access code"}), 404
    role, admin_id = result
    if role != "admin":
        return jsonify({"message": "Access code is not for admin"}), 403
    act_as = (data.get("act_as_user_id") or "").strip() or None
    duid, err = _target_user_for_admin(db, admin_id, act_as)
    if err:
        return err
    # Normalize structure
    if medical_reminders is None:
        medical_reminders = {"appointments": [], "prescriptions": [], "lab_tests": [], "custom": []}
    if not isinstance(medical_reminders, dict):
        return jsonify({"message": "medical_reminders must be an object"}), 400
    for key in ("appointments", "prescriptions", "lab_tests", "custom"):
        if key not in medical_reminders:
            medical_reminders[key] = []
        elif not isinstance(medical_reminders[key], list):
            medical_reminders[key] = []
    settings = db.get_alert_settings(duid) or {}
    settings["medical_reminders"] = medical_reminders
    ok = db.upsert_alert_settings(duid, settings)
    if not ok:
        return jsonify({"message": "Failed to save"}), 500
    notify_databus(access_code)
    _trigger_alert_checks_for_admin(admin_id)
    return jsonify({"message": "ok", "medical_reminders": medical_reminders})


def _resolve_admin_from_access_code(db, access_code):
    """Validate access code and return (admin_id, error_response_or_None)."""
    code = (access_code or "").strip()
    if not code:
        return None, (jsonify({"message": "access_code required"}), 400)
    result = db.get_role_by_access_code(code)
    if not result:
        return None, (jsonify({"message": "Invalid access code"}), 404)
    role, admin_id = result
    if role != "admin":
        return None, (jsonify({"message": "Access code is not for admin"}), 403)
    return admin_id, None


def _target_user_for_admin(db, admin_id, act_as_user_id):
    """Return user_id to use for admin operations: act_as_user_id if valid, else dashboard user. Returns (user_id, None) or (None, error_response)."""
    if act_as_user_id and (act_as_user_id or "").strip():
        uid = (act_as_user_id or "").strip()
        if db.user_belongs_to_admin(uid, admin_id):
            return uid, None
    duid = db.get_dashboard_user_id(admin_id)
    if not duid:
        return None, (jsonify({"message": "Dashboard user not found"}), 500)
    return duid, None


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_medicine_meta_from_medicines(medicines):
    """Build medicine metadata map keyed by box_id (B1..B6) from medicines payload."""
    meta = {}
    if not isinstance(medicines, list):
        return meta
    for m in medicines:
        if not isinstance(m, dict):
            continue
        box_id = (m.get("box_id") or "").strip().upper()
        if box_id not in {"B1", "B2", "B3", "B4", "B5", "B6"}:
            continue

        times = m.get("times")
        if isinstance(times, list):
            times = [str(t).strip() for t in times if str(t).strip()]
        elif isinstance(times, str) and times.strip():
            times = [times.strip()]
        else:
            times = []

        exact_time = (m.get("exact_time") or "").strip() or (times[0] if times else "08:00")
        dose_per_day = _safe_int(m.get("dose_per_day"), 0)
        if dose_per_day <= 0:
            dose_per_day = max(1, len(times))
        instructions = (m.get("instructions") or m.get("dosage") or "").strip()
        expiry = (m.get("expiry") or "").strip()

        meta[box_id] = {
            "dose_per_day": dose_per_day,
            "exact_time": exact_time,
            "instructions": instructions,
            "expiry": expiry,
        }
    return meta


def _extract_medicine_meta_from_boxes(medicine_boxes):
    """Build medicine metadata map keyed by box_id (B1..B6) from desktop medicine_boxes payload."""
    meta = {}
    if not isinstance(medicine_boxes, dict):
        return meta
    for box_id in [f"B{i}" for i in range(1, 7)]:
        med = medicine_boxes.get(box_id)
        if not isinstance(med, dict):
            continue
        exact_time = (med.get("exact_time") or "").strip() or "08:00"
        dose_per_day = _safe_int(med.get("dose_per_day"), 1)
        if dose_per_day <= 0:
            dose_per_day = 1
        instructions = (med.get("instructions") or "").strip()
        expiry = (med.get("expiry") or "").strip()
        meta[box_id] = {
            "dose_per_day": dose_per_day,
            "exact_time": exact_time,
            "instructions": instructions,
            "expiry": expiry,
        }
    return meta


@app.route("/admin/medicines", methods=["PUT"])
@app.route("/admin/inventory", methods=["PUT"])
def put_admin_medicines():
    """PUT { access_code, medicines:[{name,box_id,quantity,low_stock,dosage,times,expiry}] }.
    Updates admin dashboard medicines (B1..B6) without touching dose_logs.
    """
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or "").strip()
    medicines = data.get("medicines")

    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503

    admin_id, err = _resolve_admin_from_access_code(db, access_code)
    if err:
        return err

    if not isinstance(medicines, list):
        return jsonify({"message": "medicines must be a list"}), 400

    act_as = (data.get("act_as_user_id") or "").strip() or None
    duid, err = _target_user_for_admin(db, admin_id, act_as)
    if err:
        return err

    desired = {}
    meta_payload = _extract_medicine_meta_from_medicines(medicines)

    for m in medicines:
        if not isinstance(m, dict):
            continue
        box_id = (m.get("box_id") or "").strip().upper()
        if box_id not in {"B1", "B2", "B3", "B4", "B5", "B6"}:
            continue

        name = (m.get("name") or "").strip() or "Medicine"
        qty = max(0, _safe_int(m.get("quantity"), 0))
        low_stock = max(0, _safe_int(m.get("low_stock"), 5))

        meta = meta_payload.get(box_id) or {}
        instructions = (meta.get("instructions") or m.get("dosage") or "").strip()
        exact_time = (meta.get("exact_time") or "").strip() or "08:00"
        dose_per_day = _safe_int(meta.get("dose_per_day"), 1)
        if dose_per_day <= 0:
            dose_per_day = 1

        times = m.get("times")
        if isinstance(times, list):
            times = [str(t).strip() for t in times if str(t).strip()]
        elif isinstance(times, str) and times.strip():
            times = [times.strip()]
        else:
            times = []
        if not times:
            times = [exact_time] * dose_per_day

        desired[box_id] = {
            "name": name,
            "box_id": box_id,
            "quantity": qty,
            "low_stock": low_stock,
            "dosage": instructions,
            "times": times,
        }

    existing = db.list_medicines(duid)
    by_box = {(e.get("box_id") or "").strip().upper(): e for e in existing if isinstance(e, dict)}

    for box_id in ["B1", "B2", "B3", "B4", "B5", "B6"]:
        incoming = desired.get(box_id)
        current = by_box.get(box_id)

        if incoming:
            if current:
                ok = db.update_medicine(
                    current.get("id"),
                    name=incoming["name"],
                    box_id=box_id,
                    dosage=incoming["dosage"],
                    times=incoming["times"],
                    low_stock=incoming["low_stock"],
                    quantity=incoming["quantity"],
                )
                if not ok:
                    return jsonify({"message": f"Failed to update {box_id}"}), 500
            else:
                mid = db.create_medicine(
                    duid,
                    incoming["name"],
                    box_id=box_id,
                    dosage=incoming["dosage"],
                    times=incoming["times"],
                    low_stock=incoming["low_stock"],
                    quantity=incoming["quantity"],
                )
                if not mid:
                    return jsonify({"message": f"Failed to create {box_id}"}), 500
        elif current:
            ok = db.delete_medicine(current.get("id"))
            if not ok:
                return jsonify({"message": f"Failed to delete {box_id}"}), 500

    settings = db.get_alert_settings(duid) or {}
    if not isinstance(settings, dict):
        settings = {}
    merged_meta = {}
    for box in ["B1", "B2", "B3", "B4", "B5", "B6"]:
        if box in desired:
            merged_meta[box] = meta_payload.get(box, {})
    settings["medicine_meta"] = merged_meta
    if not db.upsert_alert_settings(duid, settings):
        return jsonify({"message": "Failed to save medicine metadata"}), 500

    notify_databus(access_code)
    _trigger_alert_checks_for_admin(admin_id)
    return jsonify({"message": "ok", "saved_boxes": len(desired)})


@app.route("/admin/alert_settings", methods=["PUT"])
@app.route("/admin/settings", methods=["PUT"])
def put_admin_alert_settings():
    """PUT { access_code, alert_settings?, gmail_config?, medical_reminders? }.
    Saves settings under dashboard user's alert_settings JSON and notifies databus.
    """
    data = request.get_json(silent=True) or {}
    access_code = (data.get("access_code") or "").strip()

    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503

    admin_id, err = _resolve_admin_from_access_code(db, access_code)
    if err:
        return err

    act_as = (data.get("act_as_user_id") or "").strip() or None
    duid, err = _target_user_for_admin(db, admin_id, act_as)
    if err:
        return err

    current = db.get_alert_settings(duid) or {}
    if not isinstance(current, dict):
        current = {}

    incoming_alert = data.get("alert_settings")
    incoming_gmail = data.get("gmail_config")
    incoming_reminders = data.get("medical_reminders")

    if not isinstance(incoming_alert, dict):
        direct_keys = {"medicine_alerts", "missed_dose_escalation", "stock_alerts", "expiry_alerts"}
        top = {k: data.get(k) for k in direct_keys if isinstance(data.get(k), dict)}
        if top:
            incoming_alert = top

    if isinstance(incoming_alert, dict):
        current["alert_settings"] = incoming_alert
    if isinstance(incoming_gmail, dict):
        current["gmail_config"] = incoming_gmail
    if isinstance(incoming_reminders, dict):
        current["medical_reminders"] = incoming_reminders

    ok = db.upsert_alert_settings(duid, current)
    if not ok:
        return jsonify({"message": "Failed to save settings"}), 500

    notify_databus(access_code)
    _trigger_alert_checks_for_admin(admin_id)
    return jsonify({"message": "ok", "settings": current})


# ---- Medicines ----
@app.route("/medicines", methods=["GET"])
def list_medicines():
    user_id = request.args.get("user_id")
    db = get_db()
    if not db:
        return jsonify([]), 503
    return jsonify(db.list_medicines(user_id))


@app.route("/medicines", methods=["POST"])
def create_medicine():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    name = (data.get("name") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not user_id or not name:
        return jsonify({"message": "user_id and name required"}), 400
    mid = db.create_medicine(user_id, name, box_id=data.get("box_id"), dosage=data.get("dosage"), times=data.get("times"), low_stock=data.get("low_stock", 5))
    if not mid:
        return jsonify({"message": "create failed"}), 500
    _trigger_alert_checks_for_admin(db.get_admin_id_by_user_id(user_id))
    return jsonify({"id": mid, "user_id": user_id, "name": name, "box_id": data.get("box_id"), "dosage": data.get("dosage"), "times": data.get("times") or [], "low_stock": data.get("low_stock", 5)})


@app.route("/medicines/<medicine_id>", methods=["PATCH"])
def update_medicine(medicine_id):
    data = request.get_json() or {}
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    user_id = db.get_user_id_by_medicine_id(medicine_id)
    ok = db.update_medicine(medicine_id, name=data.get("name"), box_id=data.get("box_id"), dosage=data.get("dosage"), times=data.get("times"), low_stock=data.get("low_stock"))
    if not ok:
        return jsonify({"message": "update failed"}), 404
    _trigger_alert_checks_for_admin(db.get_admin_id_by_user_id(user_id) if user_id else None)
    return jsonify({"message": "ok"})


@app.route("/medicines/<medicine_id>", methods=["DELETE"])
def delete_medicine(medicine_id):
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    user_id = db.get_user_id_by_medicine_id(medicine_id)
    ok = db.delete_medicine(medicine_id)
    if not ok:
        return jsonify({"message": "not found"}), 404
    _trigger_alert_checks_for_admin(db.get_admin_id_by_user_id(user_id) if user_id else None)
    return "", 204


# ---- Dose logs ----
@app.route("/dose_logs", methods=["POST"])
def create_dose_log():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not user_id:
        return jsonify({"message": "user_id required"}), 400
    lid = db.create_dose_log(user_id, medicine_id=data.get("medicine_id"), box_id=data.get("box_id"), taken_at=data.get("taken_at"), source=data.get("source", "desktop"))
    if not lid:
        return jsonify({"message": "create failed"}), 500
    _trigger_alert_checks_for_admin(db.get_admin_id_by_user_id(user_id))
    return jsonify({"id": lid})


@app.route("/dose_logs", methods=["GET"])
def list_dose_logs():
    user_id = request.args.get("user_id")
    from_ = request.args.get("from")
    to = request.args.get("to")
    db = get_db()
    if not db:
        return jsonify([]), 503
    return jsonify(db.list_dose_logs(user_id, from_=from_, to=to))


# ---- Alerts ----
@app.route("/alerts", methods=["POST"])
def create_alert():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    admin_id = data.get("admin_id")
    type_ = data.get("type") or "info"
    message = data.get("message") or ""
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not user_id or not admin_id:
        return jsonify({"message": "user_id and admin_id required"}), 400
    aid = db.create_alert(user_id, admin_id, type_, message)
    if not aid:
        return jsonify({"message": "create failed"}), 500
    return jsonify({"success": True, "id": aid})


@app.route("/alerts", methods=["GET"])
def list_alerts():
    user_id = request.args.get("user_id")
    status = request.args.get("status")
    db = get_db()
    if not db:
        return jsonify([]), 503
    return jsonify(db.list_alerts(user_id=user_id, status=status))


# ---- Alert settings ----
@app.route("/alert_settings", methods=["GET"])
def get_alert_settings():
    user_id = request.args.get("user_id")
    db = get_db()
    if not db:
        return jsonify({}), 503
    return jsonify(db.get_alert_settings(user_id))


@app.route("/alert_settings", methods=["PUT"])
def put_alert_settings():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    settings = data.get("settings")
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    if not user_id:
        return jsonify({"message": "user_id required"}), 400
    ok = db.upsert_alert_settings(user_id, settings or {})
    if ok:
        _trigger_alert_checks_for_admin(db.get_admin_id_by_user_id(user_id))
    return jsonify(settings or {}) if ok else (jsonify({"message": "failed"}), 500)


# ---- Sync ----
@app.route("/sync", methods=["GET"])
def sync_get():
    bot_id = request.args.get("bot_id", "").strip()
    api_key = request.args.get("api_key", "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    out = db.get_sync(bot_id, api_key)
    if out is None:
        return jsonify({"message": "user not found for bot_id+api_key"}), 404
    return jsonify(out)


@app.route("/sync", methods=["POST"])
def sync_post():
    data = request.get_json() or {}
    bot_id = (data.get("bot_id") or "").strip()
    api_key = (data.get("api_key") or "").strip()
    db = get_db()
    if not db:
        return jsonify({"message": "Central DB not configured"}), 503
    out = db.get_sync(bot_id, api_key)
    if out is None:
        return jsonify({"message": "user not found for bot_id+api_key"}), 404
    return jsonify(out)


# ---- Backend alert scheduler (single instance per process) ----
_alert_scheduler_instance = None


def _start_alert_scheduler():
    global _alert_scheduler_instance
    if _alert_scheduler_instance is not None:
        return
    if os.environ.get("DISABLE_ALERT_SCHEDULER", "").strip().lower() in ("1", "true", "yes"):
        print("[AlertScheduler] Disabled via DISABLE_ALERT_SCHEDULER env var")
        return
    try:
        try:
            from .alert_scheduler import BackendAlertScheduler
        except ImportError:
            try:
                from backend.alert_scheduler import BackendAlertScheduler
            except ImportError:
                from alert_scheduler import BackendAlertScheduler
        _alert_scheduler_instance = BackendAlertScheduler(get_db)
        _alert_scheduler_instance.start()
    except Exception as e:
        print(f"[AlertScheduler] Failed to start: {e}")


# Start scheduler when imported by gunicorn (module-level, runs once per worker)
_start_alert_scheduler()


def _trigger_alert_checks_for_admin(admin_id):
    """Event-based: run alert checks for this admin in a background thread after data changed. No-op if scheduler disabled."""
    if not admin_id:
        return
    if _alert_scheduler_instance is None:
        return
    t = threading.Thread(
        target=_alert_scheduler_instance.run_checks_for_admin,
        args=(str(admin_id),),
        daemon=True,
        name="AlertCheck",
    )
    t.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print("")
    print("==========  API SERVER  (leave this window open)  ==========")
    url = os.environ.get("DATABASE_URL") or os.environ.get("CENTRAL_DB_URL")
    if url:
        print("DATABASE_URL: set (%s...)" % (url[:50] if len(url) > 50 else url))
    else:
        print("DATABASE_URL: NOT SET - Central DB will not store data!")
        print("  Local: put Neon URL in backend/database_url.txt (one line)")
        print("  Railway/deploy: set DATABASE_URL in project environment variables")
    db = get_db()
    if db:
        print("Database connection: OK")
    else:
        print("Database connection: FAILED - /admin/sync and /admin/data will return 503")
    print("")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
