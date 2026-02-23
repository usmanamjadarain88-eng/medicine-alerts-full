import os
import sqlite3
import json
import hashlib


class AlertDB:
    def __init__(self, db_path="curax_alerts.db"):
        self.db_path = db_path
        db_dir = os.path.dirname(os.path.abspath(self.db_path))
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_credentials'")
        table_exists = cur.fetchone()
        if table_exists:
            cur.execute("PRAGMA table_info(admin_credentials)")
            columns = [col[1] for col in cur.fetchall()]
            if 'name' not in columns:
                print("Migrating admin_credentials table to new schema...")
                cur.execute("DROP TABLE admin_credentials")
                self.conn.commit()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_credentials (
                id INTEGER PRIMARY KEY,
                name TEXT,
                admin_id TEXT,
                email TEXT,
                phone TEXT,
                password_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                admin_name TEXT,
                status TEXT,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Admins/users live in CENTRAL DB only. Local SQLite = cache + login (admin_credentials) only.
        self.conn.commit()

    def get(self, key):
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value"])
        except Exception:
            return None

    def set(self, key, value):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)",
            (key, json.dumps(value)),
        )
        self.conn.commit()

    def delete(self, key):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM settings WHERE key=?", (key,))
        self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    def set_admin_credentials(self, name, admin_id, email, phone, password):
        try:
            cur = self.conn.cursor()
            password_hash = self._hash_password(password)
            cur.execute("DELETE FROM admin_credentials")
            cur.execute(
                """INSERT INTO admin_credentials (name, admin_id, email, phone, password_hash, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                (name, admin_id, email, phone, password_hash)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error setting admin credentials: {e}")
            return False

    def verify_admin_password(self, password):
        try:
            cur = self.conn.cursor()
            password_hash = self._hash_password(password)
            cur.execute(
                "SELECT * FROM admin_credentials WHERE password_hash=?",
                (password_hash,)
            )
            row = cur.fetchone()
            return row is not None
        except Exception as e:
            print(f"Error verifying admin password: {e}")
            return False

    def verify_admin_credentials(self, email, password):
        try:
            cur = self.conn.cursor()
            password_hash = self._hash_password(password)
            cur.execute(
                "SELECT * FROM admin_credentials WHERE email=? AND password_hash=?",
                (email, password_hash)
            )
            row = cur.fetchone()
            return row is not None
        except Exception as e:
            print(f"Error verifying admin credentials: {e}")
            return False

    def get_admin_info(self):
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT name, admin_id, email, phone FROM admin_credentials LIMIT 1")
            row = cur.fetchone()
            if row:
                return {
                    'name': row[0],
                    'admin_id': row[1],
                    'email': row[2],
                    'phone': row[3]
                }
            return None
        except Exception as e:
            print(f"Error getting admin info: {e}")
            return None

    def update_admin_password(self, new_password):
        try:
            cur = self.conn.cursor()
            password_hash = self._hash_password(new_password)
            cur.execute(
                "UPDATE admin_credentials SET password_hash=?, updated_at=CURRENT_TIMESTAMP",
                (password_hash,)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error updating admin password: {e}")
            return False

    def get_admin_email(self):
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT email FROM admin_credentials LIMIT 1")
            row = cur.fetchone()
            return row["email"] if row else None
        except Exception as e:
            print(f"Error getting admin email: {e}")
            return None

    def has_admin_credentials(self):
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) as count FROM admin_credentials")
            row = cur.fetchone()
            return row["count"] > 0
        except Exception:
            return False

    def delete_admin_account(self):
        try:
            cur = self.conn.cursor()
            cur.execute("DELETE FROM admin_credentials")
            self.conn.commit()
            print("Admin account deleted successfully")
            return True
        except Exception as e:
            print(f"Error deleting admin account: {e}")
            return False

    def log_approval(self, action, admin_name, status, details=""):
        try:
            cur = self.conn.cursor()
            cur.execute(
                """INSERT INTO approval_logs (action, admin_name, status, details, timestamp)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (action, admin_name, status, details)
            )
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error logging approval: {e}")
            return False

    def get_approval_logs(self, limit=100):
        try:
            cur = self.conn.cursor()
            cur.execute(
                """SELECT id, action, admin_name, status, details, timestamp
                   FROM approval_logs
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (limit,)
            )
            rows = cur.fetchall()
            return [
                {
                    'id': row[0],
                    'action': row[1],
                    'admin_name': row[2],
                    'status': row[3],
                    'details': row[4],
                    'timestamp': row[5]
                }
                for row in rows
            ]
        except Exception as e:
            print(f"Error getting approval logs: {e}")
            return []

    # Admin/user identity lives in CENTRAL DB only. Use controller.get_central_db() for upsert_admin_from_bot, etc.
