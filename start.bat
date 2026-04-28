@echo off
title TitanShift Launcher
echo ============================================
echo  TitanShift - Starting servers...
echo ============================================
echo.

cd /d "%~dp0"

echo [preflight] Checking engine dependencies...
where node >nul 2>nul
if errorlevel 1 (
	echo [error] Node.js is not installed or not on PATH.
	pause
	exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
	echo [error] npm is not installed or not on PATH.
	pause
	exit /b 1
)

where opencode >nul 2>nul
if errorlevel 1 (
	echo [error] opencode is not installed. Run: npm install -g opencode-ai@latest
	pause
	exit /b 1
)

where openclaude >nul 2>nul
if errorlevel 1 (
	echo [error] openclaude is not installed. Run: npm install -g @gitlawb/openclaude
	pause
	exit /b 1
)

for /f "delims=" %%i in ('opencode --version') do set OPENCODE_VERSION=%%i
for /f "delims=" %%i in ('openclaude --version') do set OPENCLAUDE_VERSION=%%i

echo [ok] opencode: %OPENCODE_VERSION%
echo [ok] openclaude: %OPENCLAUDE_VERSION%
echo.

echo [1/2] Starting backend API (port 8000)...
start "TitanShift Backend" cmd /k ".venv\Scripts\python.exe -m harness serve-api"

timeout /t 2 /nobreak >nul

echo [2/2] Starting frontend (port 5173)...
start "TitanShift Frontend" cmd /k "cd frontend && npm run dev -- --host 127.0.0.1"

echo.
echo Both servers are starting in separate windows.
echo  - Backend:  http://127.0.0.1:8000
echo  - Frontend: http://127.0.0.1:5173
echo  - Engines:  GET /engines/health on the backend for sidecar readiness
echo.
echo Open http://127.0.0.1:5173 in your browser.
pause
