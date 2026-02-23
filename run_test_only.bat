@echo off
REM Run this in Terminal 2 to test the API. Server must already be running in Terminal 1.
REM This file ONLY sets DATABASE_URL and runs the test script - it does NOT start the server.
cd /d "%~dp0"
call backend\set_database_url.bat
echo.
echo [run_test_only.bat] Now running test script only - you should see "TEST SCRIPT" below, NOT "API SERVER".
echo.
python "%~dp0test_api.py"
pause
