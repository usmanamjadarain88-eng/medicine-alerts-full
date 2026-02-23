@echo off
REM Edit the line below: set your PostgreSQL password and keep other values if you use defaults.
REM Format: postgresql://USER:PASSWORD@HOST:PORT/DATABASE
REM Default: user=postgres, host=localhost, port=5432, database=curax_central
REM (PostgreSQL 18.2 installs to ...\PostgreSQL\18\...)
set DATABASE_URL=postgresql://postgres:Myiub@123@localhost:5432/curax_central

REM To start server (Terminal 1): run this, then type: python -m backend.api_server
REM To run test only (Terminal 2): run run_test_only.bat from project root (do NOT run api_server there)
echo DATABASE_URL is set.
