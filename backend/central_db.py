"""
Central DB client (PostgreSQL). All admin/user and app data live here.
Local SQLite is for cache only. Multiple admins, each with their own users.
"""
import os
import uuid
import json
import secrets
from datetime import datetime, timezone

# Safe alphabet for admin access code (no 0/O, 1/I)
_ADMIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_ADMIN_CODE_LENGTH = 8

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None


def _get_connection_string(url=None, **kwargs):
    if url and str(url).strip():
        return url.strip()
    if kwargs.get("host"):
        u = kwargs.get("user") or os.environ.get("PGUSER", "")
        p = kwargs.get("password") or os.environ.get("PGPASSWORD", "")
        d = kwargs.get("dbname") or kwargs.get("database") or os.environ.get("PGDATABASE", "curax_central")
        port = kwargs.get("port") or os.environ.get("PGPORT", "5432")
        return f"postgresql://{u}:{p}@{kwargs['host']}:{port}/{d}"
    return (os.environ.get("DATABASE_URL") or os.environ.get("CENTRAL_DB_URL") or "").strip() or None


class EmailAlreadyUsedError(Exception):
    """Raised when creating or updating an admin with an email that another admin already has."""


class CentralDB:
    """PostgreSQL central DB: admins and users (one admin ↔ their users; multiple admins)."""

    def __init__(self, connection_string=None, **kwargs):
        self._conn_str = _get_connection_string(connection_string, **kwargs) or ""
        self._conn = None

    def connect(self):
        if not psycopg2:
            raise RuntimeError("Install psycopg2-binary: pip install psycopg2-binary")
        if not self._conn_str:
            raise ValueError("Central DB: set DATABASE_URL or CENTRAL_DB_URL, or pass connection_string/host")
        self._conn = psycopg2.connect(self._conn_str)
        return self._conn

    def _ensure_conn(self):
        if self._conn is None or self._conn.closed:
            self.connect()
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def is_available(self):
        """True if connection string is set and we can connect."""
        if not self._conn_str:
            return False
        try:
            self._ensure_conn()
            return True
        except Exception:
            return False

    def _generate_admin_access_code(self):
        """Generate a unique 8-char admin access code (e.g. A1B2C3D4)."""
        for _ in range(20):
            code = "A" + "".join(secrets.choice(_ADMIN_CODE_ALPHABET) for _ in range(_ADMIN_CODE_LENGTH - 1))
            conn = self._ensure_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
            try:
                cur.execute("SELECT 1 FROM admins WHERE admin_access_code = %s LIMIT 1", (code,))
                if cur.fetchone() is None:
                    return code
            finally:
                cur.close()
        return "A" + (secrets.token_hex(4).upper()[: _ADMIN_CODE_LENGTH - 1])  # fallback

    def _generate_connection_code(self):
        """Generate a unique 8-char connection code (e.g. C1B2C3D4) for linking users to this admin."""
        for _ in range(20):
            code = "C" + "".join(secrets.choice(_ADMIN_CODE_ALPHABET) for _ in range(_ADMIN_CODE_LENGTH - 1))
            conn = self._ensure_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
            try:
                cur.execute("SELECT 1 FROM admins WHERE connection_code = %s LIMIT 1", (code,))
                if cur.fetchone() is None:
                    return code
            finally:
                cur.close()
        return "C" + (secrets.token_hex(4).upper()[: _ADMIN_CODE_LENGTH - 1])  # fallback

    def _admin_id_by_email(self, email):
        """Return admin id that has this email (normalized: strip + lower), or None."""
        raw = (email or "").strip()
        if not raw:
            return None
        norm = raw.lower()
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id FROM admins WHERE LOWER(TRIM(email)) = %s LIMIT 1",
                (norm,),
            )
            row = cur.fetchone()
            if row:
                return str(row["id"]) if hasattr(row, "keys") else str(row[0])
            return None
        finally:
            cur.close()

    # ---- Admins (from Admin Panel: bot_id + api_key) ----
    def upsert_admin_from_bot(self, bot_id, api_key, name=None, email=None):
        """Insert or update admin by (bot_id, api_key). Returns (admin_id, admin_access_code, connection_code) or (None, None, None).
        New admins get unique admin_access_code and connection_code; existing admins keep their codes.
        """
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        email_val = (email or "").strip()
        if not bot_id or not api_key:
            return None, None, None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            if email_val:
                existing_id = self._admin_id_by_email(email_val)
                if existing_id:
                    cur.execute(
                        "SELECT id FROM admins WHERE bot_id = %s AND api_key = %s LIMIT 1",
                        (bot_id, api_key),
                    )
                    current = cur.fetchone()
                    current_id = str(current["id"]) if current and hasattr(current, "keys") else (str(current[0]) if current else None)
                    if current_id != existing_id:
                        raise EmailAlreadyUsedError("An admin with this email already exists.")
            access_code = self._generate_admin_access_code()
            connection_code = self._generate_connection_code()
            cur.execute(
                """
                INSERT INTO admins (name, email, bot_id, api_key, admin_access_code, connection_code, is_admin, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, true, NOW())
                ON CONFLICT (bot_id, api_key)
                DO UPDATE SET name = COALESCE(EXCLUDED.name, admins.name),
                              email = COALESCE(EXCLUDED.email, admins.email),
                              admin_access_code = COALESCE(admins.admin_access_code, EXCLUDED.admin_access_code),
                              connection_code = COALESCE(admins.connection_code, EXCLUDED.connection_code),
                              is_admin = true,
                              updated_at = NOW()
                RETURNING id, admin_access_code, connection_code
                """,
                (name or "", email_val or "", bot_id, api_key, access_code, connection_code),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                aid = row["id"] if hasattr(row, "keys") else row[0]
                ac = (row["admin_access_code"] if hasattr(row, "keys") else row[1]) if row else None
                cc = (row["connection_code"] if hasattr(row, "keys") else row[2]) if row else None
                return (str(aid) if isinstance(aid, uuid.UUID) else aid), (ac or access_code), (cc or connection_code)
            return None, None, None
        except EmailAlreadyUsedError:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            print(f"CentralDB upsert_admin_from_bot: {e}")
            return None, None, None
        finally:
            cur.close()

    def update_admin_bot_by_access_code(self, access_code, bot_id, api_key, name=None, email=None):
        """Find admin by access_code and set their bot_id, api_key, name, email (e.g. when app registers).
        If another admin row has this (bot_id, api_key), delete it first so we keep one admin per access_code.
        Returns (admin_id, admin_access_code, connection_code) or (None, None, None).
        """
        code = (access_code or "").strip().upper()
        if not code or not (bot_id or "").strip() or not (api_key or "").strip():
            return None, None, None
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        email_val = (email or "").strip()
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute("SELECT id FROM admins WHERE admin_access_code = %s LIMIT 1", (code,))
            target = cur.fetchone()
            if not target:
                return None, None, None
            target_id = target["id"] if hasattr(target, "keys") else target[0]
            target_id_str = str(target_id)
            if email_val:
                existing_id = self._admin_id_by_email(email_val)
                if existing_id and existing_id != target_id_str:
                    raise EmailAlreadyUsedError("An admin with this email already exists.")
            cur.execute(
                "DELETE FROM admins WHERE bot_id = %s AND api_key = %s AND id != %s::uuid",
                (bot_id, api_key, target_id),
            )
            cur.execute(
                """
                UPDATE admins SET bot_id = %s, api_key = %s, name = COALESCE(NULLIF(%s, ''), name),
                email = COALESCE(NULLIF(%s, ''), email), is_admin = true, updated_at = NOW()
                WHERE admin_access_code = %s
                RETURNING id, admin_access_code, connection_code
                """,
                (bot_id, api_key, name or "", email_val or "", code),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                aid = row["id"] if hasattr(row, "keys") else row[0]
                ac = (row["admin_access_code"] if hasattr(row, "keys") else row[1]) if row else None
                cc = (row["connection_code"] if hasattr(row, "keys") else row[2]) if row else None
                return (str(aid) if isinstance(aid, uuid.UUID) else aid), ac, cc
            return None, None, None
        except EmailAlreadyUsedError:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            print(f"CentralDB update_admin_bot_by_access_code: {e}")
            return None, None, None
        finally:
            cur.close()

    def get_admin_by_access_code(self, access_code):
        """Return admin row { id, name, admin_access_code, connection_code } for this access code, or None.
        Used by Android app: enter code → identify as admin.
        """
        code = (access_code or "").strip().upper()
        if not code:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id, name, admin_access_code, connection_code FROM admins WHERE admin_access_code = %s LIMIT 1",
                (code,),
            )
            row = cur.fetchone()
            if row and hasattr(row, "keys"):
                return {
                    "id": str(row["id"]), "name": row["name"],
                    "admin_access_code": row["admin_access_code"],
                    "connection_code": row.get("connection_code") if hasattr(row, "get") else (row[3] if len(row) > 3 else None),
                }
            if row:
                return {"id": str(row[0]), "name": row[1], "admin_access_code": row[2], "connection_code": row[3] if len(row) > 3 else None}
            return None
        except Exception as e:
            print(f"CentralDB get_admin_by_access_code: {e}")
            return None
        finally:
            cur.close()

    def get_admin_by_connection_code(self, connection_code):
        """Return admin row { id, name, connection_code } for this connection code, or None.
        Used when a user enters admin's connection code to link to that admin.
        """
        code = (connection_code or "").strip().upper()
        if not code:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id, name, connection_code FROM admins WHERE connection_code = %s LIMIT 1",
                (code,),
            )
            row = cur.fetchone()
            if row and hasattr(row, "keys"):
                return {"id": str(row["id"]), "name": row["name"], "connection_code": row["connection_code"]}
            if row:
                return {"id": str(row[0]), "name": row[1], "connection_code": row[2]}
            return None
        except Exception as e:
            print(f"CentralDB get_admin_by_connection_code: {e}")
            return None
        finally:
            cur.close()

    def delete_admin_by_access_code(self, access_code):
        """Delete full admin identity by access_code; removes all admins with same email."""
        code = (access_code or "").strip().upper()
        if not code:
            return False
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT email FROM admins WHERE admin_access_code = %s LIMIT 1", (code,))
            row = cur.fetchone()
            if not row:
                return False
            email_val = (row[0] or "").strip()
            if email_val:
                cur.execute("DELETE FROM admins WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))", (email_val,))
            else:
                cur.execute("DELETE FROM admins WHERE admin_access_code = %s", (code,))
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            conn.rollback()
            print(f"CentralDB delete_admin_by_access_code: {e}")
            return False
        finally:
            cur.close()

    def get_admin_id_by_bot(self, bot_id, api_key):
        """Return admin UUID (string) for this bot_id+api_key, or None."""
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id FROM admins WHERE bot_id = %s AND api_key = %s LIMIT 1",
                (bot_id, api_key),
            )
            row = cur.fetchone()
            if row:
                aid = row["id"] if hasattr(row, "keys") else row[0]
                return str(aid) if isinstance(aid, uuid.UUID) else aid
            return None
        except Exception as e:
            print(f"CentralDB get_admin_id_by_bot: {e}")
            return None
        finally:
            cur.close()

    def get_admin_info_from_bot(self, bot_id=None, api_key=None):
        """Return admin row (id, name, email, bot_id, api_key, admin_access_code, connection_code) for display. If no args, return first admin (dev)."""
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            if bot_id and api_key:
                cur.execute(
                    "SELECT id, name, email, bot_id, api_key, admin_access_code, connection_code FROM admins WHERE bot_id = %s AND api_key = %s LIMIT 1",
                    (bot_id.strip(), api_key.strip()),
                )
            else:
                cur.execute("SELECT id, name, email, bot_id, api_key, admin_access_code, connection_code FROM admins LIMIT 1")
            row = cur.fetchone()
            if row:
                if hasattr(row, "keys"):
                    return {
                        "id": str(row["id"]), "name": row["name"], "email": row["email"],
                        "bot_id": row["bot_id"], "api_key": row["api_key"],
                        "admin_access_code": (row.get("admin_access_code") if hasattr(row, "get") else (row[5] if len(row) > 5 else None)),
                        "connection_code": (row.get("connection_code") if hasattr(row, "get") else (row[6] if len(row) > 6 else None)),
                    }
                return {"id": str(row[0]), "name": row[1], "email": row[2], "bot_id": row[3], "api_key": row[4], "admin_access_code": row[5] if len(row) > 5 else None, "connection_code": row[6] if len(row) > 6 else None}
            return None
        except Exception as e:
            print(f"CentralDB get_admin_info_from_bot: {e}")
            return None
        finally:
            cur.close()

    # ---- Users (from System Settings: bot_id + api_key, linked to admin_id) ----
    def upsert_user_from_bot(self, bot_id, api_key, admin_id, name=None):
        """Insert or update the user by (bot_id, api_key); links this app to the given admin_id. Returns user id or None.
        Many users (app instances) can link to the same admin. Unique key is (bot_id, api_key).
        """
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key or not admin_id:
            return None
        try:
            uuid.UUID(str(admin_id))
        except (ValueError, TypeError):
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO users (admin_id, name, bot_id, api_key, role, updated_at)
                VALUES (%s::uuid, %s, %s, %s, 'user', NOW())
                ON CONFLICT (bot_id, api_key)
                DO UPDATE SET admin_id = EXCLUDED.admin_id,
                              name = COALESCE(EXCLUDED.name, users.name),
                              updated_at = NOW()
                RETURNING id
                """,
                (admin_id, name or "", bot_id, api_key),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                uid = row["id"] if hasattr(row, "keys") else row[0]
                return str(uid) if isinstance(uid, uuid.UUID) else uid
            return None
        except Exception as e:
            conn.rollback()
            print(f"CentralDB upsert_user_from_bot: {e}")
            return None
        finally:
            cur.close()

    def get_user_by_admin_id(self, admin_id):
        """Return user row for this admin (for display)."""
        if not admin_id:
            return None
        try:
            uuid.UUID(str(admin_id))
        except (ValueError, TypeError):
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id, admin_id, name, bot_id, api_key, role FROM users WHERE admin_id = %s::uuid LIMIT 1",
                (admin_id,),
            )
            row = cur.fetchone()
            if row:
                if hasattr(row, "keys"):
                    return {
                        "id": str(row["id"]),
                        "admin_id": str(row["admin_id"]),
                        "name": row["name"],
                        "bot_id": row["bot_id"],
                        "api_key": row["api_key"],
                        "role": row["role"],
                    }
                return {
                    "id": str(row[0]),
                    "admin_id": str(row[1]),
                    "name": row[2],
                    "bot_id": row[3],
                    "api_key": row[4],
                    "role": row[5],
                }
            return None
        except Exception as e:
            print(f"CentralDB get_user_by_admin_id: {e}")
            return None
        finally:
            cur.close()

    def get_user_id_by_bot(self, bot_id, api_key):
        """Return user UUID (string) for this bot_id+api_key, or None."""
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id FROM users WHERE bot_id = %s AND api_key = %s LIMIT 1",
                (bot_id, api_key),
            )
            row = cur.fetchone()
            if row:
                uid = row["id"] if hasattr(row, "keys") else row[0]
                return str(uid) if isinstance(uid, uuid.UUID) else uid
            return None
        except Exception as e:
            print(f"CentralDB get_user_id_by_bot: {e}")
            return None
        finally:
            cur.close()

    def get_role_by_bot(self, bot_id, api_key):
        """Return 'admin' or 'user' and id for this bot_id+api_key. None if not found."""
        aid = self.get_admin_id_by_bot(bot_id, api_key)
        if aid:
            return "admin", aid
        uid = self.get_user_id_by_bot(bot_id, api_key)
        if uid:
            return "user", uid
        return None

    def get_role_by_access_code(self, access_code):
        """Return ('admin', admin_id) if access_code matches an admin; else None. For Android app."""
        info = self.get_admin_by_access_code(access_code)
        if info and info.get("id"):
            return "admin", info["id"]
        return None

    def get_dashboard_user_id(self, admin_id):
        """Return user_id for the admin's dashboard data (one user per admin with bot_id='dashboard').
        Creates that user if it does not exist. Used for syncing desktop medicine_boxes and for app GET /admin/data.
        """
        if not admin_id:
            return None
        try:
            uuid.UUID(str(admin_id))
        except (ValueError, TypeError):
            return None
        uid = self.get_user_id_by_bot("dashboard", str(admin_id))
        if uid:
            return uid
        return self.upsert_user_from_bot("dashboard", str(admin_id), admin_id, name="Admin dashboard")

    def get_admin_dashboard_data(self, admin_id, last_sync_time=None):
        """Return dashboard data for this admin. If last_sync_time (ISO) is set, return only data updated after that time (incremental).
        Always returns server_time for next poll. Used by Android GET /admin/data?access_code=...&last_sync_time=...
        """
        duid = self.get_dashboard_user_id(admin_id)
        if not duid:
            return None
        now = datetime.now(timezone.utc).isoformat()
        incremental = bool(last_sync_time and (last_sync_time or "").strip())
        if incremental:
            medicines = self.list_medicines(duid, since=last_sync_time)
            dose_logs = self.list_dose_logs(duid, from_=last_sync_time, limit=500)
            alert_settings = self.get_alert_settings_if_updated_since(duid, last_sync_time)
            alerts = self.list_alerts(admin_id=admin_id, since=last_sync_time, limit=200)
        else:
            medicines = self.list_medicines(duid)
            dose_logs = self.list_dose_logs(duid, limit=500)
            alert_settings = self.get_alert_settings(duid)
            alerts = self.list_alerts(admin_id=admin_id, limit=200)
        medical_reminders = (alert_settings or {}).get("medical_reminders") if alert_settings else None
        if medical_reminders is None and not incremental:
            medical_reminders = {"appointments": [], "prescriptions": [], "lab_tests": [], "custom": []}
        out = {
            "medicines": medicines,
            "dose_logs": dose_logs,
            "alert_settings": alert_settings,
            "alerts": alerts,
            "medical_reminders": medical_reminders,
            "server_time": now,
            "incremental": incremental,
        }
        if incremental:
            all_meds = self.list_medicines(duid)
            out["medicine_box_ids"] = [m.get("box_id") for m in all_meds if m.get("box_id")]
        return out

    def sync_admin_dashboard_data(self, admin_id, medicine_boxes, dose_log):
        """Sync desktop medicine_boxes and dose_log to Central DB for this admin.
        medicine_boxes: dict B1..B6 -> { name, quantity?, dose_per_day?, exact_time?, instructions?, ... }
        dose_log: list of { timestamp, box, medicine, dose_taken, remaining }.
        """
        duid = self.get_dashboard_user_id(admin_id)
        if not duid:
            return False
        existing_medicines = self.list_medicines(duid)
        by_box = {m.get("box_id"): m for m in existing_medicines if m.get("box_id")}

        for box_id in [f"B{i}" for i in range(1, 7)]:
            med = (medicine_boxes or {}).get(box_id) if isinstance(medicine_boxes, dict) else None
            if med and isinstance(med, dict):
                name = (med.get("name") or "").strip() or "Medicine"
                dosage = med.get("instructions") or str(med.get("dose_per_day") or "")
                exact_time = med.get("exact_time") or "08:00"
                times = [exact_time] if isinstance(exact_time, str) else (exact_time if isinstance(exact_time, (list, tuple)) else [])
                low_stock = 5
                if med.get("low_stock") is not None:
                    try:
                        low_stock = int(med.get("low_stock"))
                    except (TypeError, ValueError):
                        pass
                quantity = 0
                if med.get("quantity") is not None:
                    try:
                        quantity = int(med.get("quantity"))
                    except (TypeError, ValueError):
                        pass
                existing = by_box.get(box_id)
                if existing:
                    self.update_medicine(
                        existing.get("id"),
                        name=name,
                        box_id=box_id,
                        dosage=dosage,
                        times=times,
                        low_stock=low_stock,
                        quantity=quantity,
                    )
                else:
                    self.create_medicine(duid, name, box_id=box_id, dosage=dosage, times=times, low_stock=low_stock, quantity=quantity)
            else:
                existing = by_box.get(box_id)
                if existing:
                    self.delete_medicine(existing.get("id"))

        # Replace dose_logs for dashboard user: delete all then insert from dose_log
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM dose_logs WHERE user_id = %s::uuid", (duid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"CentralDB sync_admin_dashboard_data delete dose_logs: {e}")
            cur.close()
            return True
        finally:
            cur.close()

        for entry in (dose_log or [])[:500]:
            if not isinstance(entry, dict):
                continue
            ts = entry.get("timestamp") or entry.get("taken_at")
            box = entry.get("box") or entry.get("box_id") or ""
            if ts:
                self.create_dose_log(duid, medicine_id=None, box_id=box, taken_at=ts, source="desktop")
        return True

    # ---- Medicines, dose_logs, alert_settings, alerts, get_sync (abbreviated for length - same as pyqt) ----
    def list_medicines(self, user_id, since=None):
        if not user_id:
            return []
        try:
            uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            return []
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        use_quantity = True
        try:
            cols = "id, user_id, name, box_id, dosage, times, low_stock, quantity"
            if since:
                cur.execute(
                    f"""SELECT {cols} FROM medicines
                       WHERE user_id = %s::uuid AND (updated_at > %s::timestamptz OR created_at > %s::timestamptz)
                       ORDER BY created_at""",
                    (user_id, since, since),
                )
            else:
                cur.execute(
                    f"SELECT {cols} FROM medicines WHERE user_id = %s::uuid ORDER BY created_at",
                    (user_id,),
                )
            rows = cur.fetchall()
        except Exception:
            use_quantity = False
            try:
                cols = "id, user_id, name, box_id, dosage, times, low_stock"
                if since:
                    cur.execute(
                        f"""SELECT {cols} FROM medicines
                           WHERE user_id = %s::uuid AND (updated_at > %s::timestamptz OR created_at > %s::timestamptz)
                           ORDER BY created_at""",
                        (user_id, since, since),
                    )
                else:
                    cur.execute(
                        f"SELECT {cols} FROM medicines WHERE user_id = %s::uuid ORDER BY created_at",
                        (user_id,),
                    )
                rows = cur.fetchall()
            except Exception as e:
                print(f"CentralDB list_medicines: {e}")
                cur.close()
                return []
        try:
            out = []
            for row in rows:
                r = row if hasattr(row, "keys") else None
                if r:
                    times = r["times"]
                    if isinstance(times, str):
                        try:
                            times = json.loads(times)
                        except Exception:
                            times = []
                    qty = 0
                    if use_quantity:
                        qty = r.get("quantity", 0)
                        if qty is None:
                            qty = 0
                        try:
                            qty = int(qty)
                        except (TypeError, ValueError):
                            qty = 0
                    out.append({
                        "id": str(r["id"]), "user_id": str(r["user_id"]), "name": r["name"],
                        "box_id": r["box_id"], "dosage": r["dosage"], "times": times, "low_stock": r["low_stock"],
                        "quantity": qty,
                    })
                else:
                    qty = int(row[7]) if len(row) > 7 else 0
                    out.append({
                        "id": str(row[0]), "user_id": str(row[1]), "name": row[2], "box_id": row[3],
                        "dosage": row[4], "times": json.loads(row[5]) if isinstance(row[5], str) else (row[5] or []), "low_stock": row[6],
                        "quantity": qty,
                    })
            return out
        except Exception as e:
            print(f"CentralDB list_medicines: {e}")
            return []
        finally:
            cur.close()

    def create_medicine(self, user_id, name, box_id=None, dosage=None, times=None, low_stock=5, quantity=0):
        if not user_id or not name:
            return None
        times = times if isinstance(times, (list, tuple)) else []
        times_json = json.dumps(times)
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                """INSERT INTO medicines (user_id, name, box_id, dosage, times, low_stock, quantity)
                   VALUES (%s::uuid, %s, %s, %s, %s::jsonb, %s, %s)
                   RETURNING id""",
                (user_id, name, box_id or "", dosage or "", times_json, low_stock, quantity),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                mid = row["id"] if hasattr(row, "keys") else row[0]
                return str(mid) if isinstance(mid, uuid.UUID) else mid
            return None
        except Exception as e:
            conn.rollback()
            try:
                cur.execute(
                    """INSERT INTO medicines (user_id, name, box_id, dosage, times, low_stock)
                       VALUES (%s::uuid, %s, %s, %s, %s::jsonb, %s)
                       RETURNING id""",
                    (user_id, name, box_id or "", dosage or "", times_json, low_stock),
                )
                row = cur.fetchone()
                conn.commit()
                if row:
                    mid = row["id"] if hasattr(row, "keys") else row[0]
                    return str(mid) if isinstance(mid, uuid.UUID) else mid
            except Exception as e2:
                conn.rollback()
                print(f"CentralDB create_medicine: {e2}")
            return None
        finally:
            cur.close()

    def update_medicine(self, medicine_id, name=None, box_id=None, dosage=None, times=None, low_stock=None, quantity=None):
        if not medicine_id:
            return False
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            updates = []
            params = []
            if name is not None:
                updates.append("name = %s")
                params.append(name)
            if box_id is not None:
                updates.append("box_id = %s")
                params.append(box_id)
            if dosage is not None:
                updates.append("dosage = %s")
                params.append(dosage)
            if times is not None:
                updates.append("times = %s::jsonb")
                params.append(json.dumps(times))
            if low_stock is not None:
                updates.append("low_stock = %s")
                params.append(low_stock)
            if quantity is not None:
                updates.append("quantity = %s")
                params.append(quantity)
            if not updates:
                return True
            updates.append("updated_at = NOW()")
            params.append(medicine_id)
            cur.execute(
                f"UPDATE medicines SET {', '.join(updates)} WHERE id = %s::uuid",
                params,
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            conn.rollback()
            print(f"CentralDB update_medicine: {e}")
            return False
        finally:
            cur.close()

    def delete_medicine(self, medicine_id):
        if not medicine_id:
            return False
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM medicines WHERE id = %s::uuid", (medicine_id,))
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            conn.rollback()
            print(f"CentralDB delete_medicine: {e}")
            return False
        finally:
            cur.close()

    def create_dose_log(self, user_id, medicine_id=None, box_id=None, taken_at=None, source="desktop"):
        if not user_id:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                """INSERT INTO dose_logs (user_id, medicine_id, box_id, taken_at, source)
                   VALUES (%s::uuid, %s::uuid, %s, COALESCE(%s::timestamptz, NOW()), %s)
                   RETURNING id""",
                (user_id, medicine_id or None, box_id or "", taken_at, source),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                return str(row["id"]) if hasattr(row, "keys") else str(row[0])
            return None
        except Exception as e:
            conn.rollback()
            print(f"CentralDB create_dose_log: {e}")
            return None
        finally:
            cur.close()

    def list_dose_logs(self, user_id, from_=None, to=None, limit=500):
        if not user_id:
            return []
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            q = "SELECT id, user_id, medicine_id, box_id, taken_at, source FROM dose_logs WHERE user_id = %s::uuid"
            params = [user_id]
            if from_:
                q += " AND taken_at > %s::timestamptz"
                params.append(from_)
            if to:
                q += " AND taken_at <= %s::timestamptz"
                params.append(to)
            q += " ORDER BY taken_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(q, params)
            rows = cur.fetchall()
            out = []
            for row in rows:
                r = row if hasattr(row, "keys") else None
                if r:
                    out.append({
                        "id": str(r["id"]), "user_id": str(r["user_id"]),
                        "medicine_id": str(r["medicine_id"]) if r["medicine_id"] else None,
                        "box_id": r["box_id"],
                        "taken_at": r["taken_at"].isoformat() if hasattr(r["taken_at"], "isoformat") else str(r["taken_at"]),
                        "source": r["source"],
                    })
                else:
                    out.append({
                        "id": str(row[0]), "user_id": str(row[1]),
                        "medicine_id": str(row[2]) if row[2] else None, "box_id": row[3],
                        "taken_at": row[4].isoformat() if hasattr(row[4], "isoformat") else str(row[4]),
                        "source": row[5],
                    })
            return out
        except Exception as e:
            print(f"CentralDB list_dose_logs: {e}")
            return []
        finally:
            cur.close()

    def get_alert_settings(self, user_id):
        if not user_id:
            return {}
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute("SELECT settings FROM alert_settings WHERE user_id = %s::uuid LIMIT 1", (user_id,))
            row = cur.fetchone()
            if row:
                s = row["settings"] if hasattr(row, "keys") else row[0]
                if isinstance(s, dict):
                    return s
                if isinstance(s, str):
                    return json.loads(s) if s else {}
                return {}
            return {}
        except Exception as e:
            print(f"CentralDB get_alert_settings: {e}")
            return {}
        finally:
            cur.close()

    def get_alert_settings_if_updated_since(self, user_id, since):
        """Return alert_settings only if row updated_at > since; else None (so client keeps previous)."""
        if not user_id or not since:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT settings FROM alert_settings WHERE user_id = %s::uuid AND updated_at > %s::timestamptz LIMIT 1",
                (user_id, since),
            )
            row = cur.fetchone()
            if row:
                s = row["settings"] if hasattr(row, "keys") else row[0]
                if isinstance(s, dict):
                    return s
                if isinstance(s, str):
                    return json.loads(s) if s else {}
            return None
        except Exception as e:
            print(f"CentralDB get_alert_settings_if_updated_since: {e}")
            return None
        finally:
            cur.close()

    def upsert_alert_settings(self, user_id, settings):
        if not user_id:
            return False
        s = json.dumps(settings) if isinstance(settings, dict) else "{}"
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """INSERT INTO alert_settings (user_id, settings, updated_at)
                   VALUES (%s::uuid, %s::jsonb, NOW())
                   ON CONFLICT (user_id) DO UPDATE SET settings = EXCLUDED.settings, updated_at = NOW()""",
                (user_id, s),
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"CentralDB upsert_alert_settings: {e}")
            return False
        finally:
            cur.close()

    def create_alert(self, user_id, admin_id, type_, message):
        if not user_id or not admin_id:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                """INSERT INTO alerts (user_id, admin_id, type, message, status)
                   VALUES (%s::uuid, %s::uuid, %s, %s, 'pending')
                   RETURNING id""",
                (user_id, admin_id, type_, message),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                return str(row["id"]) if hasattr(row, "keys") else str(row[0])
            return None
        except Exception as e:
            conn.rollback()
            print(f"CentralDB create_alert: {e}")
            return None
        finally:
            cur.close()

    def list_alerts(self, user_id=None, admin_id=None, status=None, since=None, limit=100):
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            q = "SELECT id, user_id, admin_id, type, message, status, created_at FROM alerts WHERE 1=1"
            params = []
            if user_id:
                q += " AND user_id = %s::uuid"
                params.append(user_id)
            if admin_id:
                q += " AND admin_id = %s::uuid"
                params.append(admin_id)
            if status:
                q += " AND status = %s"
                params.append(status)
            if since:
                q += " AND created_at > %s::timestamptz"
                params.append(since)
            q += " ORDER BY created_at DESC LIMIT %s"
            params.append(limit)
            cur.execute(q, params)
            rows = cur.fetchall()
            out = []
            for row in rows:
                r = row if hasattr(row, "keys") else row
                if hasattr(r, "keys"):
                    out.append({
                        "id": str(r["id"]), "user_id": str(r["user_id"]), "admin_id": str(r["admin_id"]),
                        "type": r["type"], "message": r["message"], "status": r["status"],
                        "created_at": r["created_at"].isoformat() if hasattr(r["created_at"], "isoformat") else str(r["created_at"]),
                    })
                else:
                    out.append({
                        "id": str(row[0]), "user_id": str(row[1]), "admin_id": str(row[2]),
                        "type": row[3], "message": row[4], "status": row[5],
                        "created_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
                    })
            return out
        except Exception as e:
            print(f"CentralDB list_alerts: {e}")
            return []
        finally:
            cur.close()

    def get_sync(self, bot_id, api_key):
        user_id = self.get_user_id_by_bot(bot_id, api_key)
        if not user_id:
            return None
        medicines = self.list_medicines(user_id)
        settings = self.get_alert_settings(user_id)
        alerts = self.list_alerts(user_id=user_id, status="pending", limit=50)
        now = datetime.now(timezone.utc).isoformat()
        return {
            "medicines": medicines,
            "alert_settings": settings,
            "alerts": alerts,
            "server_time": now,
        }

    def get_all_users_by_admin_id(self, admin_id):
        """Return all real users linked to this admin (excludes the dashboard system user)."""
        if not admin_id:
            return []
        try:
            uuid.UUID(str(admin_id))
        except (ValueError, TypeError):
            return []
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id, name, bot_id, api_key, created_at FROM users WHERE admin_id = %s::uuid AND bot_id != 'dashboard' ORDER BY created_at DESC",
                (admin_id,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                if hasattr(row, "keys"):
                    result.append({"id": str(row["id"]), "name": row["name"] or "", "bot_id": row["bot_id"] or "", "api_key": row["api_key"] or ""})
                else:
                    result.append({"id": str(row[0]), "name": row[1] or "", "bot_id": row[2] or "", "api_key": row[3] or ""})
            return result
        except Exception as e:
            print(f"CentralDB get_all_users_by_admin_id: {e}")
            return []
        finally:
            cur.close()

    def get_all_active_admins(self):
        """Return list of {id, name, bot_id, api_key} for all admins."""
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute("SELECT id, name, bot_id, api_key FROM admins ORDER BY created_at")
            rows = cur.fetchall()
            result = []
            for row in rows:
                if hasattr(row, "keys"):
                    result.append({
                        "id": str(row["id"]),
                        "name": row["name"] or "",
                        "bot_id": row["bot_id"] or "",
                        "api_key": row["api_key"] or "",
                    })
                else:
                    result.append({"id": str(row[0]), "name": row[1] or "", "bot_id": row[2] or "", "api_key": row[3] or ""})
            return result
        except Exception as e:
            print(f"CentralDB get_all_active_admins: {e}")
            return []
        finally:
            cur.close()
