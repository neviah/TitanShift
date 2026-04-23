@echo off
title TitanShift Launcher
echo ============================================
echo  TitanShift - Starting servers...
echo ============================================
echo.

cd /d "%~dp0"

echo [1/2] Starting backend API (port 8000)...
start "TitanShift Backend" cmd /k ".venv\Scripts\python.exe -m harness serve-api"

timeout /t 2 /nobreak >nul

echo [2/2] Starting frontend (port 5173)...
start "TitanShift Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo Both servers are starting in separate windows.
echo  - Backend:  http://127.0.0.1:8000
echo  - Frontend: http://127.0.0.1:5173
echo.
echo Open http://127.0.0.1:5173 in your browser.
pause
