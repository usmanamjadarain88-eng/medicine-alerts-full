@echo off
REM Run this in Terminal 1 to start the API server WITH database connection.
REM One command - the server gets DATABASE_URL from this same batch process.
cd /d "%~dp0"
call backend\set_database_url.bat
echo.
echo Starting API server (leave this window open)...
echo.
python -m backend.api_server
pause
