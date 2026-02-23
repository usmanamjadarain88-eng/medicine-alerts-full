@echo off
REM 1. Edit set_database_url.bat and put your real PostgreSQL password.
REM 2. Then run this script from repo root: backend\run_api_with_db.bat
cd /d "%~dp0"
call set_database_url.bat
cd /d "%~dp0\.."
python -m backend.api_server
