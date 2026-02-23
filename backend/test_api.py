r"""
Quick test that API + DB are working. Run from repo root:
  backend\set_database_url.bat
  python backend\test_api.py

Or with BASE already set:
  set BASE=http://127.0.0.1:5050
  python backend\test_api.py
"""
import os
import sys
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

BASE = os.environ.get("BASE", "http://127.0.0.1:5050").rstrip("/")

def req(path, method="GET", body=None):
    url = BASE + path
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    rq = urllib.request.Request(url, data=data, method=method)
    if data:
        rq.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(rq, timeout=10) as r:
            return r.getcode(), json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        try:
            return e.code, json.loads(body) if body else {}
        except json.JSONDecodeError:
            return e.code, {"message": body or "Request failed"}
    except Exception as e:
        return 0, {"error": str(e)}

def main():
    print("")
    print("==========  TEST SCRIPT  (not the server - will exit when done)  ==========")
    print("")
    print("Base URL:", BASE)
    print()

    # 1) get-role with no params -> should not 503 (DB connected)
    print("1. GET /get-role (no params)...")
    code, out = req("/get-role")
    if code == 503:
        print("   FAIL: 503 - DB not configured. Run set_database_url.bat first.")
        sys.exit(1)
    print("   OK (code %s, role=%s)" % (code, out.get("role")))
    print()

    # 2) save-credentials as admin -> get connection_code
    print("2. POST /save-credentials (role=admin)...")
    code, out = req("/save-credentials", method="POST", body={
        "bot_id": "test-admin-001",
        "api_key": "test-api-key-123",
        "role": "admin",
        "name": "Test Admin"
    })
    if code != 200:
        print("   FAIL:", code, out)
        sys.exit(1)
    admin_id = out.get("admin_id")
    access_code = out.get("admin_access_code")
    connection_code = out.get("connection_code")
    print("   OK admin_id=%s" % admin_id)
    print("   admin_access_code=%s" % access_code)
    print("   connection_code=%s" % connection_code)
    if not connection_code:
        print("   WARN: connection_code missing (check backend has connection_code column)")
    print()

    # 3) get-role with bot_id+api_key -> should return admin + connection_code
    print("3. GET /get-role (bot_id + api_key)...")
    code, out = req("/get-role?" + urlencode({"bot_id": "test-admin-001", "api_key": "test-api-key-123"}))
    if code != 200 or out.get("role") != "admin":
        print("   FAIL:", code, out)
        sys.exit(1)
    print("   OK role=admin, connection_code=%s" % out.get("connection_code"))
    print()

    # 4) connect-to-admin as user with that connection_code
    print("4. POST /connect-to-admin (user links to admin)...")
    code, out = req("/connect-to-admin", method="POST", body={
        "connection_code": connection_code,
        "bot_id": "test-user-001",
        "api_key": "user-key-456",
        "name": "Test User"
    })
    if code != 200:
        print("   FAIL:", code, out)
        sys.exit(1)
    print("   OK user linked to admin_id=%s" % out.get("admin_id"))
    print()

    print("All checks passed. API + DB are working.")

if __name__ == "__main__":
    main()
