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

    def create_desktop_link_code(self, access_code, expires_seconds=300):
        """Admin creates a one-time code for a user to link desktop to this admin (user view). Code valid 5 min; one-time use. Returns (code, admin_id, admin_name) or (None, None, None)."""
        code = (access_code or "").strip().upper()
        if not code:
            return None, None, None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id, name FROM admins WHERE admin_access_code = %s LIMIT 1",
                (code,),
            )
            row = cur.fetchone()
            if not row:
                return None, None, None
            admin_id = row["id"] if hasattr(row, "keys") else row[0]
            admin_name = (row["name"] if hasattr(row, "keys") else row[1]) or "Admin"
            from datetime import timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
            for _ in range(20):
                link_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
                try:
                    cur.execute(
                        "INSERT INTO desktop_link_codes (code, admin_id, expires_at) VALUES (%s, %s, %s)",
                        (link_code, admin_id, expires_at),
                    )
                    if cur.rowcount:
                        conn.commit()
                        return link_code, str(admin_id), admin_name
                except Exception:
                    conn.rollback()
                    continue
            return None, None, None
        except Exception as e:
            conn.rollback()
            print(f"CentralDB create_desktop_link_code: {e}")
            return None, None, None
        finally:
            cur.close()

    def get_admin_by_desktop_link_code(self, code):
        """Validate desktop link code, return admin info and consume the code. Returns { admin_id, admin_name } or None."""
        code = (code or "").strip().upper()
        if not code:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT d.admin_id, a.name FROM desktop_link_codes d JOIN admins a ON a.id = d.admin_id WHERE d.code = %s AND d.expires_at > NOW() LIMIT 1",
                (code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            admin_id = row["admin_id"] if hasattr(row, "keys") else row[0]
            admin_name = (row["name"] if hasattr(row, "keys") else row[1]) or "Admin"
            cur.execute("DELETE FROM desktop_link_codes WHERE code = %s", (code,))
            conn.commit()
            return {"admin_id": str(admin_id), "admin_name": admin_name}
        except Exception as e:
            conn.rollback()
            print(f"CentralDB get_admin_by_desktop_link_code: {e}")
            return None
        finally:
            cur.close()

    def create_user_desktop_link_code(self, bot_id, api_key, expires_seconds=300):
        """User (app) creates a one-time code for desktop to link to this user. Code valid 5 min; one-time use. Returns (code, user_id, user_name) or (None, None, None)."""
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key:
            return None, None, None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT id, name FROM users WHERE bot_id = %s AND api_key = %s LIMIT 1",
                (bot_id, api_key),
            )
            row = cur.fetchone()
            if not row:
                return None, None, None
            user_id = row["id"] if hasattr(row, "keys") else row[0]
            user_name = (row["name"] if hasattr(row, "keys") else row[1]) or "User"
            from datetime import timedelta
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)
            for _ in range(20):
                link_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
                try:
                    cur.execute(
                        "INSERT INTO user_desktop_link_codes (code, user_id, expires_at) VALUES (%s, %s, %s)",
                        (link_code, user_id, expires_at),
                    )
                    if cur.rowcount:
                        conn.commit()
                        return link_code, str(user_id), user_name
                except Exception:
                    conn.rollback()
                    continue
            return None, None, None
        except Exception as e:
            conn.rollback()
            print(f"CentralDB create_user_desktop_link_code: {e}")
            return None, None, None
        finally:
            cur.close()

    def get_user_by_desktop_link_code(self, code):
        """Validate user desktop link code, return user info and admin info; consume the code.
        Returns { user_id, user_name, bot_id, api_key, admin_id, admin_name } or None.
        Sets users.desktop_linked_at when code is used so admin can only save for users who linked desktop."""
        code = (code or "").strip().upper()
        if not code:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            try:
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS desktop_linked_at TIMESTAMPTZ DEFAULT NULL")
                conn.commit()
            except Exception:
                conn.rollback()
            cur.execute(
                """SELECT d.user_id, u.name AS user_name, u.bot_id, u.api_key, u.admin_id, a.name AS admin_name
                   FROM user_desktop_link_codes d
                   JOIN users u ON u.id = d.user_id
                   JOIN admins a ON a.id = u.admin_id
                   WHERE d.code = %s AND d.expires_at > NOW() LIMIT 1""",
                (code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            user_id = row["user_id"] if hasattr(row, "keys") else row[0]
            user_name = (row["user_name"] if hasattr(row, "keys") else row[1]) or "User"
            bot_id = (row["bot_id"] if hasattr(row, "keys") else row[2]) or ""
            api_key = (row["api_key"] if hasattr(row, "keys") else row[3]) or ""
            admin_id = row["admin_id"] if hasattr(row, "keys") else row[4]
            admin_name = (row["admin_name"] if hasattr(row, "keys") else row[5]) or "Admin"
            try:
                cur.execute("UPDATE users SET desktop_linked_at = COALESCE(desktop_linked_at, NOW()) WHERE id = %s", (user_id,))
            except Exception:
                pass
            cur.execute("DELETE FROM user_desktop_link_codes WHERE code = %s", (code,))
            conn.commit()
            return {
                "user_id": str(user_id),
                "user_name": user_name,
                "bot_id": bot_id,
                "api_key": api_key,
                "admin_id": str(admin_id) if admin_id else "",
                "admin_name": admin_name,
            }
        except Exception as e:
            conn.rollback()
            print(f"CentralDB get_user_by_desktop_link_code: {e}")
            return None
        finally:
            cur.close()

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
    def upsert_admin_from_bot(self, bot_id, api_key, name=None, email=None, fcm_token=None):
        """Insert or update admin by (bot_id, api_key). Returns (admin_id, admin_access_code, connection_code) or (None, None, None).
        New admins get unique admin_access_code and connection_code; existing admins keep their codes.
        fcm_token: when provided, stored so backend can send push alerts to this admin.
        """
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        email_val = (email or "").strip()
        fcm = (fcm_token or "").strip() or None
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
                INSERT INTO admins (name, email, bot_id, api_key, admin_access_code, connection_code, fcm_token, is_admin, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, true, NOW())
                ON CONFLICT (bot_id, api_key)
                DO UPDATE SET name = COALESCE(EXCLUDED.name, admins.name),
                              email = COALESCE(EXCLUDED.email, admins.email),
                              admin_access_code = COALESCE(admins.admin_access_code, EXCLUDED.admin_access_code),
                              connection_code = COALESCE(admins.connection_code, EXCLUDED.connection_code),
                              fcm_token = COALESCE(NULLIF(TRIM(EXCLUDED.fcm_token), ''), admins.fcm_token),
                              is_admin = true,
                              updated_at = NOW()
                RETURNING id, admin_access_code, connection_code
                """,
                (name or "", email_val or "", bot_id, api_key, access_code, connection_code, fcm),
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

    def update_admin_bot_by_access_code(self, access_code, bot_id, api_key, name=None, email=None, fcm_token=None):
        """Find admin by access_code and set their bot_id, api_key, name, email, fcm_token (e.g. when app registers).
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
            fcm = (fcm_token or "").strip() or None
            cur.execute(
                """
                UPDATE admins SET bot_id = %s, api_key = %s, name = COALESCE(NULLIF(%s, ''), name),
                email = COALESCE(NULLIF(%s, ''), email), fcm_token = COALESCE(NULLIF(%s, ''), fcm_token), is_admin = true, updated_at = NOW()
                WHERE admin_access_code = %s
                RETURNING id, admin_access_code, connection_code
                """,
                (bot_id, api_key, name or "", email_val or "", fcm or "", code),
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

    def get_admin_bot_by_access_code(self, access_code):
        """Return { bot_id, api_key, fcm_token } for admin with this access_code, or None.
        Used when desktop notifies backend of events; fcm_token is passed to relay for FCM-first push."""
        code = (access_code or "").strip().upper()
        if not code:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute("SELECT bot_id, api_key, fcm_token FROM admins WHERE admin_access_code = %s LIMIT 1", (code,))
            row = cur.fetchone()
            if row and hasattr(row, "keys"):
                bid = (row.get("bot_id") or "").strip()
                akey = (row.get("api_key") or "").strip()
                fcm = (row.get("fcm_token") or "").strip() or None
                if bid and akey:
                    return {"bot_id": bid, "api_key": akey, "fcm_token": fcm}
            if row:
                bid = (row[0] or "").strip()
                akey = (row[1] or "").strip()
                fcm = (row[2] or "").strip() or None if len(row) > 2 else None
                if bid and akey:
                    return {"bot_id": bid, "api_key": akey, "fcm_token": fcm}
            return None
        except Exception as e:
            print(f"CentralDB get_admin_bot_by_access_code: {e}")
            return None
        finally:
            cur.close()

    def get_fcm_token_for_bot(self, bot_id, api_key):
        """Return fcm_token for this bot_id+api_key (admin or user). Used so relay can try FCM first."""
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT fcm_token FROM admins WHERE bot_id = %s AND api_key = %s LIMIT 1", (bot_id, api_key))
            row = cur.fetchone()
            if row and row[0]:
                t = (row[0] or "").strip()
                if t:
                    return t
            cur.execute("SELECT fcm_token FROM users WHERE bot_id = %s AND api_key = %s LIMIT 1", (bot_id, api_key))
            row = cur.fetchone()
            if row and row[0]:
                t = (row[0] or "").strip()
                if t:
                    return t
            return None
        except Exception as e:
            print(f"CentralDB get_fcm_token_for_bot: {e}")
            return None
        finally:
            cur.close()

    def update_admin_fcm_token_by_access_code(self, access_code, fcm_token):
        """Update only fcm_token for the admin with this access_code. Used when app gets FCM token after permission grant.
        Returns True if admin was found and updated."""
        code = (access_code or "").strip().upper()
        if not code:
            return False
        fcm = (fcm_token or "").strip() or None
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE admins SET fcm_token = %s, updated_at = NOW() WHERE admin_access_code = %s",
                (fcm or "", code),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception as e:
            conn.rollback()
            print(f"CentralDB update_admin_fcm_token_by_access_code: {e}")
            return False
        finally:
            cur.close()

    def get_admin_connection_status(self, access_code):
        """Return { connected: bool, fcm_token_set: bool } for admin with this access_code, or None if not found.
        connected = has bot_id and api_key; fcm_token_set = has non-empty fcm_token."""
        code = (access_code or "").strip().upper()
        if not code:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT bot_id, api_key, fcm_token FROM admins WHERE admin_access_code = %s LIMIT 1",
                (code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            bid = (row[0] or "").strip()
            akey = (row[1] or "").strip()
            fcm = (row[2] or "").strip() if len(row) > 2 else ""
            return {
                "connected": bool(bid and akey),
                "fcm_token_set": bool(fcm),
            }
        except Exception as e:
            print(f"CentralDB get_admin_connection_status: {e}")
            return None
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
        """Delete admin and all data for that admin: users (and their medicines, dose_logs, alert_settings, alerts), sync_logs. DB is empty for this admin."""
        code = (access_code or "").strip().upper()
        if not code:
            return False
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT id, email FROM admins WHERE admin_access_code = %s LIMIT 1", (code,))
            row = cur.fetchone()
            if not row:
                return False
            admin_id = row[0]
            email_val = (row[1] or "").strip() if len(row) > 1 else ""

            # Get all admin_id(s) we are about to delete (this one, or all with same email)
            if email_val:
                cur.execute("SELECT id FROM admins WHERE LOWER(TRIM(email)) = LOWER(TRIM(%s))", (email_val,))
                admin_ids = [r[0] for r in cur.fetchall()]
            else:
                admin_ids = [admin_id]

            # Delete sync_logs for any user belonging to these admins (sync_logs has no ON DELETE CASCADE on user_id)
            if admin_ids:
                placeholders = ",".join(["%s::uuid"] * len(admin_ids))
                cur.execute(
                    f"DELETE FROM sync_logs WHERE user_id IN (SELECT id FROM users WHERE admin_id IN ({placeholders}))",
                    tuple(admin_ids),
                )

            # Delete admins; CASCADE will delete users -> medicines, dose_logs, alert_settings, alerts
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

    def get_admin_id_by_user_id(self, user_id):
        """Return admin_id for the given user_id, or None. Used for event-based alert triggers."""
        if not user_id:
            return None
        try:
            uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            return None
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT admin_id FROM users WHERE id = %s::uuid LIMIT 1", (user_id,))
            row = cur.fetchone()
            if row:
                aid = row[0]
                return str(aid) if isinstance(aid, uuid.UUID) else aid
            return None
        except Exception as e:
            print(f"CentralDB get_admin_id_by_user_id: {e}")
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
    def _delete_other_users_by_admin_and_email(self, admin_id, email, keep_bot_id, keep_api_key):
        """Remove any other user rows for this admin_id + email (different device/install). Keeps the row for (keep_bot_id, keep_api_key)."""
        email = (email or "").strip()
        if not email:
            return
        try:
            uuid.UUID(str(admin_id))
        except (ValueError, TypeError):
            return
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                """
                DELETE FROM users
                WHERE admin_id = %s::uuid AND LOWER(TRIM(email)) = LOWER(TRIM(%s))
                AND (bot_id != %s OR api_key != %s)
                """,
                (admin_id, email, keep_bot_id, keep_api_key),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            # Ignore if email column does not exist yet (run: ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255))
            if "column" not in str(e).lower() and "email" not in str(e).lower():
                print(f"CentralDB _delete_other_users_by_admin_and_email: {e}")
        finally:
            cur.close()

    def upsert_user_from_bot(self, bot_id, api_key, admin_id, name=None, email=None, fcm_token=None):
        """Insert or update the user by (bot_id, api_key); links this app to the given admin_id. Returns user id or None.
        If email is provided and already exists for this admin, update that user's bot_id/api_key so their data stays intact.
        fcm_token: when provided, stored for push alerts to this user.
        """
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key or not admin_id:
            return None
        try:
            uuid.UUID(str(admin_id))
        except (ValueError, TypeError):
            return None
        email_clean = (email or "").strip()
        fcm = (fcm_token or "").strip() or None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            # Prefer existing user by admin_id + email to preserve data on re-install.
            if email_clean:
                try:
                    cur.execute(
                        """
                        SELECT id FROM users
                        WHERE admin_id = %s::uuid AND LOWER(TRIM(email)) = LOWER(TRIM(%s))
                        AND bot_id != 'dashboard'
                        ORDER BY updated_at DESC NULLS LAST, created_at DESC
                        LIMIT 1
                        """,
                        (admin_id, email_clean),
                    )
                    row = cur.fetchone()
                    if row:
                        uid = row["id"] if hasattr(row, "keys") else row[0]
                        cur.execute(
                            """
                            UPDATE users
                            SET bot_id = %s,
                                api_key = %s,
                                name = COALESCE(NULLIF(%s, ''), name),
                                email = COALESCE(NULLIF(%s, ''), email),
                                fcm_token = COALESCE(NULLIF(TRIM(%s), ''), fcm_token),
                                updated_at = NOW()
                            WHERE id = %s::uuid
                            RETURNING id
                            """,
                            (bot_id, api_key, name or "", email_clean, fcm, str(uid)),
                        )
                        row2 = cur.fetchone()
                        conn.commit()
                        if row2:
                            uid2 = row2["id"] if hasattr(row2, "keys") else row2[0]
                            return str(uid2) if isinstance(uid2, uuid.UUID) else uid2
                        return str(uid) if isinstance(uid, uuid.UUID) else uid
                except Exception:
                    # If email column doesn't exist yet, skip email-based update
                    conn.rollback()

            # Schema: users may have email, fcm_token columns
            cur.execute(
                """
                INSERT INTO users (admin_id, name, email, bot_id, api_key, role, fcm_token, updated_at)
                VALUES (%s::uuid, %s, %s, %s, %s, 'user', %s, NOW())
                ON CONFLICT (bot_id, api_key)
                DO UPDATE SET admin_id = EXCLUDED.admin_id,
                              name = COALESCE(EXCLUDED.name, users.name),
                              email = COALESCE(EXCLUDED.email, users.email),
                              fcm_token = COALESCE(NULLIF(TRIM(EXCLUDED.fcm_token), ''), users.fcm_token),
                              updated_at = NOW()
                RETURNING id
                """,
                (admin_id, name or "", email_clean or None, bot_id, api_key, fcm),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                uid = row["id"] if hasattr(row, "keys") else row[0]
                return str(uid) if isinstance(uid, uuid.UUID) else uid
            return None
        except Exception as e:
            conn.rollback()
            # If email/fcm_token column doesn't exist yet, fallback to insert without them
            if "email" in str(e).lower() or "column" in str(e).lower() or "fcm_token" in str(e).lower():
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
                except Exception as e2:
                    conn.rollback()
                    print(f"CentralDB upsert_user_from_bot fallback: {e2}")
            else:
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

    def get_user_and_admin_bot_by_user_bot(self, bot_id, api_key):
        """Given a user's bot_id+api_key, return user_id, admin_id, user_name, and admin's bot_id/api_key for relaying alerts to admin. Returns dict or None."""
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                """SELECT u.id AS user_id, u.admin_id, u.name AS user_name, a.bot_id AS admin_bot_id, a.api_key AS admin_api_key
                   FROM users u JOIN admins a ON a.id = u.admin_id
                   WHERE u.bot_id = %s AND u.api_key = %s AND u.bot_id != 'dashboard' LIMIT 1""",
                (bot_id, api_key),
            )
            row = cur.fetchone()
            if not row:
                return None
            if hasattr(row, "keys"):
                return {
                    "user_id": str(row["user_id"]),
                    "admin_id": str(row["admin_id"]),
                    "user_name": (row["user_name"] or "").strip() or "User",
                    "admin_bot_id": (row["admin_bot_id"] or "").strip(),
                    "admin_api_key": (row["admin_api_key"] or "").strip(),
                }
            return {
                "user_id": str(row[0]),
                "admin_id": str(row[1]),
                "user_name": (row[2] or "").strip() or "User",
                "admin_bot_id": (row[3] or "").strip(),
                "admin_api_key": (row[4] or "").strip(),
            }
        except Exception as e:
            print(f"CentralDB get_user_and_admin_bot_by_user_bot: {e}")
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

    def sync_admin_dashboard_data_for_user(self, admin_id, user_id, medicine_boxes, dose_log):
        """Sync medicine_boxes and dose_log to a connected user (when admin 'acts as' that user)."""
        if not self.user_belongs_to_admin(user_id, admin_id):
            return False
        existing_medicines = self.list_medicines(user_id)
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
                    self.create_medicine(user_id, name, box_id=box_id, dosage=dosage, times=times, low_stock=low_stock, quantity=quantity)
            else:
                existing = by_box.get(box_id)
                if existing:
                    self.delete_medicine(existing.get("id"))

        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM dose_logs WHERE user_id = %s::uuid", (user_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"CentralDB sync_admin_dashboard_data_for_user delete dose_logs: {e}")
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
                self.create_dose_log(user_id, medicine_id=None, box_id=box, taken_at=ts, source="desktop")
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

    def get_user_id_by_medicine_id(self, medicine_id):
        """Return user_id for the given medicine_id, or None. Used for event-based alert triggers."""
        if not medicine_id:
            return None
        try:
            uuid.UUID(str(medicine_id))
        except (ValueError, TypeError):
            return None
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT user_id FROM medicines WHERE id = %s::uuid LIMIT 1", (medicine_id,))
            row = cur.fetchone()
            if row:
                uid = row[0]
                return str(uid) if isinstance(uid, uuid.UUID) else uid
            return None
        except Exception as e:
            print(f"CentralDB get_user_id_by_medicine_id: {e}")
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
            q = """SELECT a.id, a.user_id, a.admin_id, a.type, a.message, a.status, a.created_at,
                    COALESCE(u.name, '') AS user_name
                    FROM alerts a
                    LEFT JOIN users u ON u.id = a.user_id
                    WHERE 1=1"""
            params = []
            if user_id:
                q += " AND a.user_id = %s::uuid"
                params.append(user_id)
            if admin_id:
                q += " AND a.admin_id = %s::uuid"
                params.append(admin_id)
            if status:
                q += " AND a.status = %s"
                params.append(status)
            if since:
                q += " AND a.created_at > %s::timestamptz"
                params.append(since)
            q += " ORDER BY a.created_at DESC LIMIT %s"
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
                        "user_name": (r.get("user_name") or "").strip() or "User",
                    })
                else:
                    user_name = (row[7] if len(row) > 7 else "") or "User"
                    out.append({
                        "id": str(row[0]), "user_id": str(row[1]), "admin_id": str(row[2]),
                        "type": row[3], "message": row[4], "status": row[5],
                        "created_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
                        "user_name": str(user_name).strip() or "User",
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
            try:
                cur.execute(
                    "SELECT id, name, email, bot_id, api_key, created_at, desktop_linked_at FROM users WHERE admin_id = %s::uuid AND bot_id != 'dashboard' ORDER BY created_at DESC",
                    (admin_id,),
                )
            except Exception:
                cur.execute(
                    "SELECT id, name, bot_id, api_key, created_at FROM users WHERE admin_id = %s::uuid AND bot_id != 'dashboard' ORDER BY created_at DESC",
                    (admin_id,),
                )
            rows = cur.fetchall()
            result = []
            for row in rows:
                if hasattr(row, "keys"):
                    dlinked = row.get("desktop_linked_at") if hasattr(row, "get") else (row[6] if len(row) > 6 else None)
                    result.append({
                        "id": str(row["id"]),
                        "name": row["name"] or "",
                        "email": (row.get("email") or "").strip() if hasattr(row, "get") else "",
                        "bot_id": row["bot_id"] or "",
                        "api_key": row["api_key"] or "",
                        "desktop_linked": dlinked is not None,
                    })
                else:
                    # Fallback when email column isn't selected
                    dlinked = row[6] if len(row) > 6 else None
                    result.append({
                        "id": str(row[0]),
                        "name": row[1] or "",
                        "email": "",
                        "bot_id": row[2] or "",
                        "api_key": row[3] or "",
                        "desktop_linked": dlinked is not None
                    })
            return result
        except Exception as e:
            print(f"CentralDB get_all_users_by_admin_id: {e}")
            return []
        finally:
            cur.close()

    def user_has_desktop_linked(self, user_id):
        """True if this user has linked a desktop at least once (desktop_linked_at set)."""
        if not user_id:
            return False
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1 FROM users WHERE id = %s::uuid AND desktop_linked_at IS NOT NULL LIMIT 1", (user_id,))
            return cur.fetchone() is not None
        except Exception:
            return False
        finally:
            cur.close()

    def user_belongs_to_admin(self, user_id, admin_id):
        """True if user_id is a non-dashboard user under this admin_id."""
        if not user_id or not admin_id:
            return False
        conn = self._ensure_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT 1 FROM users WHERE id = %s::uuid AND admin_id = %s::uuid AND bot_id != 'dashboard' LIMIT 1",
                (user_id, admin_id),
            )
            return cur.fetchone() is not None
        except Exception:
            return False
        finally:
            cur.close()

    def get_deleted_user_notification(self, bot_id, api_key):
        """If this (bot_id, api_key) was deleted by admin, return dict with user_name and message; else None."""
        bot_id = (bot_id or "").strip()
        api_key = (api_key or "").strip()
        if not bot_id or not api_key:
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT user_name FROM deleted_user_notifications WHERE bot_id = %s AND api_key = %s LIMIT 1",
                (bot_id, api_key),
            )
            row = cur.fetchone()
            if not row:
                return None
            name = row["user_name"] if hasattr(row, "keys") else (row[0] if row else None)
            return {"user_name": name or "User", "message": "The admin has removed you from their account."}
        except Exception as e:
            print(f"CentralDB get_deleted_user_notification: {e}")
            return None
        finally:
            cur.close()

    def delete_user_by_admin(self, admin_id, user_id):
        """Admin deletes a connected user. User cannot delete themselves; only admin can.
        Records (bot_id, api_key) in deleted_user_notifications so get-role returns 410 for that user.
        Returns (True, user_name) on success, (False, None) otherwise."""
        if not self.user_belongs_to_admin(user_id, admin_id):
            return False, None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute(
                "SELECT bot_id, api_key, name FROM users WHERE id = %s::uuid LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return False, None
            bot_id = row["bot_id"] if hasattr(row, "keys") else row[0]
            api_key = row["api_key"] if hasattr(row, "keys") else row[1]
            user_name = (row["name"] or "User") if hasattr(row, "keys") else (row[2] if len(row) > 2 else "User")
            cur.execute(
                "INSERT INTO deleted_user_notifications (bot_id, api_key, user_name) VALUES (%s, %s, %s) ON CONFLICT (bot_id, api_key) DO UPDATE SET user_name = EXCLUDED.user_name, deleted_at = NOW()",
                (bot_id, api_key, user_name),
            )
            cur.execute("DELETE FROM users WHERE id = %s::uuid", (user_id,))
            conn.commit()
            return True, user_name
        except Exception as e:
            conn.rollback()
            print(f"CentralDB delete_user_by_admin: {e}")
            return False, None
        finally:
            cur.close()

    def get_user_data_for_admin(self, admin_id, user_id, last_sync_time=None):
        """Return same shape as get_admin_dashboard_data but for the given user_id. Use when admin 'acts as' a connected user."""
        if not self.user_belongs_to_admin(user_id, admin_id):
            return None
        now = datetime.now(timezone.utc).isoformat()
        incremental = bool(last_sync_time and (last_sync_time or "").strip())
        if incremental:
            medicines = self.list_medicines(user_id, since=last_sync_time)
            dose_logs = self.list_dose_logs(user_id, from_=last_sync_time, limit=500)
            alert_settings = self.get_alert_settings_if_updated_since(user_id, last_sync_time)
            alerts = self.list_alerts(admin_id=admin_id, user_id=user_id, since=last_sync_time, limit=200)
        else:
            medicines = self.list_medicines(user_id)
            dose_logs = self.list_dose_logs(user_id, limit=500)
            alert_settings = self.get_alert_settings(user_id)
            alerts = self.list_alerts(admin_id=admin_id, user_id=user_id, limit=200)
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
            all_meds = self.list_medicines(user_id)
            out["medicine_box_ids"] = [m.get("box_id") for m in all_meds if m.get("box_id")]
        return out

    def get_admin_by_id(self, admin_id):
        """Return one admin {id, name, bot_id, api_key} for the given admin_id, or None. Used for event-based alert checks."""
        if not admin_id:
            return None
        try:
            uuid.UUID(str(admin_id))
        except (ValueError, TypeError):
            return None
        conn = self._ensure_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor) if RealDictCursor else conn.cursor()
        try:
            cur.execute("SELECT id, name, bot_id, api_key FROM admins WHERE id = %s::uuid LIMIT 1", (admin_id,))
            row = cur.fetchone()
            if not row:
                return None
            if hasattr(row, "keys"):
                return {"id": str(row["id"]), "name": row["name"] or "", "bot_id": row["bot_id"] or "", "api_key": row["api_key"] or ""}
            return {"id": str(row[0]), "name": row[1] or "", "bot_id": row[2] or "", "api_key": row[3] or ""}
        except Exception as e:
            print(f"CentralDB get_admin_by_id: {e}")
            return None
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
