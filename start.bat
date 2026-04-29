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

set "OBSCURA_LOCAL_DIR=%~dp0.tools\obscura"
if exist "%OBSCURA_LOCAL_DIR%\obscura.exe" set "PATH=%OBSCURA_LOCAL_DIR%;%PATH%"

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

where obscura >nul 2>nul
if errorlevel 1 (
	echo [warning] obscura is not installed. Attempting automatic install from GitHub release...
	powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_obscura.ps1" -InstallDir "%OBSCURA_LOCAL_DIR%"
	if exist "%OBSCURA_LOCAL_DIR%\obscura.exe" set "PATH=%OBSCURA_LOCAL_DIR%;%PATH%"
	where obscura >nul 2>nul
	if errorlevel 1 (
		echo [warning] obscura install failed or command unavailable.
		echo           Run setup-obscura.bat from repo root, or install manually from:
		echo           https://github.com/h4ckf0r0day/obscura/releases
		echo           ^(Playwright will be used as fallback^)
		echo.
	) else (
		echo [ok] obscura installed automatically.
	)
)

for /f "delims=" %%i in ('opencode --version') do set OPENCODE_VERSION=%%i
for /f "delims=" %%i in ('openclaude --version') do set OPENCLAUDE_VERSION=%%i

where obscura >nul 2>nul
if not errorlevel 1 (
	for /f "delims=" %%i in ('where obscura') do echo [ok] obscura: detected at %%i
)

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
