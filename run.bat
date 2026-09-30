@echo off
setlocal enabledelayedexpansion
REM Campus ERP - one-double-click local run (no Docker required).
REM Requirements on this PC: Python 3.12+ and Node.js 18+ installed and on PATH.
REM First run takes longer (creates a virtual environment and installs dependencies).
REM Closing a service's window stops that service; close all windows to stop everything.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [Campus ERP] Python was not found on PATH. Install Python 3.12+ from https://www.python.org/downloads/ and try again.
    pause
    exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
    echo [Campus ERP] Node.js was not found on PATH. Install Node.js 18+ from https://nodejs.org/ and try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [Campus ERP] Creating Python virtual environment...
    python -m venv .venv || goto :fail
)

echo [Campus ERP] Installing backend dependencies (skips already-installed packages)...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt || goto :fail

if not exist "frontend\node_modules" (
    echo [Campus ERP] Installing frontend dependencies (first run only, this can take a few minutes)...
    call npm --prefix frontend install || goto :fail
)

echo [Campus ERP] Preparing local signing keys and seeded demo data...
".venv\Scripts\python.exe" scripts\bootstrap.py || goto :fail
".venv\Scripts\python.exe" scripts\seed_local.py || goto :fail

REM Shared local-run settings. CAMPUS_DEMO permits the fixed demo HMAC secrets below.
set CAMPUS_LOCAL=1
set CAMPUS_DEMO=1
set CAMPUS_ORIGINS=http://localhost:5173
set IDENTITY_URL=http://localhost:8001
set WEBHOOK_SECRET=local-development-only-secret
set QR_SECRET=local-development-only-secret
set SIMULATOR_KEY=local-development-only-secret

echo [Campus ERP] Starting Identity (8001), Academic (8002), Finance (8003), HR (8004)...
start "Campus ERP - Identity (8001)"  cmd /k "cd /d "%~dp0" && set CAMPUS_LOCAL=1&& set CAMPUS_DEMO=1&& set CAMPUS_ORIGINS=http://localhost:5173&& set IDENTITY_URL=http://localhost:8001&& set WEBHOOK_SECRET=local-development-only-secret&& set QR_SECRET=local-development-only-secret&& set SIMULATOR_KEY=local-development-only-secret&& ".venv\Scripts\python.exe" -m uvicorn services.identity.app.main:application --factory --host 127.0.0.1 --port 8001"
start "Campus ERP - Academic (8002)"  cmd /k "cd /d "%~dp0" && set CAMPUS_LOCAL=1&& set CAMPUS_ORIGINS=http://localhost:5173&& set IDENTITY_URL=http://localhost:8001&& set WEBHOOK_SECRET=local-development-only-secret&& set QR_SECRET=local-development-only-secret&& set SIMULATOR_KEY=local-development-only-secret&& ".venv\Scripts\python.exe" -m uvicorn services.academic.app.main:application --factory --host 127.0.0.1 --port 8002"
start "Campus ERP - Finance (8003)"   cmd /k "cd /d "%~dp0" && set CAMPUS_LOCAL=1&& set CAMPUS_ORIGINS=http://localhost:5173&& set IDENTITY_URL=http://localhost:8001&& set WEBHOOK_SECRET=local-development-only-secret&& set QR_SECRET=local-development-only-secret&& set SIMULATOR_KEY=local-development-only-secret&& ".venv\Scripts\python.exe" -m uvicorn services.finance.app.main:application --factory --host 127.0.0.1 --port 8003"
start "Campus ERP - HR (8004)"        cmd /k "cd /d "%~dp0" && set CAMPUS_LOCAL=1&& set CAMPUS_ORIGINS=http://localhost:5173&& set IDENTITY_URL=http://localhost:8001&& set WEBHOOK_SECRET=local-development-only-secret&& set QR_SECRET=local-development-only-secret&& set SIMULATOR_KEY=local-development-only-secret&& ".venv\Scripts\python.exe" -m uvicorn services.hr.app.main:application --factory --host 127.0.0.1 --port 8004"

echo [Campus ERP] Waiting for the backend services to come up...
timeout /t 6 /nobreak >nul

echo [Campus ERP] Starting the frontend (Vite dev server) on http://localhost:5173 ...
start "Campus ERP - Frontend (5173)" cmd /k "cd /d "%~dp0frontend" && set CAMPUS_DIRECT=1&& npm run dev"

timeout /t 4 /nobreak >nul
start "" "http://localhost:5173"

echo.
echo [Campus ERP] All services started in separate windows. Sign in with any demo account
echo shown on the login page (password: CampusDemo!2026). Close a window to stop that
echo service; close all four backend windows plus the frontend window to stop everything.
echo This is a local demo run: SQLite databases, no RabbitMQ (asynchronous invoicing runs
echo only via docker-compose). Use "docker compose up --build" instead for the full stack.
pause
exit /b 0

:fail
echo.
echo [Campus ERP] Setup failed. See the error above.
pause
exit /b 1
