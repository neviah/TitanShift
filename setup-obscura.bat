@echo off
title TitanShift - Install Obscura
echo ============================================
echo  Installing Obscura browser backend...
echo ============================================
echo.

where npm >nul 2>nul
if errorlevel 1 (
	echo [error] npm is not installed or not on PATH.
	echo Please install Node.js first: https://nodejs.org/
	pause
	exit /b 1
)

echo [1/1] Installing obscura globally via npm...
call npm install -g obscura

if errorlevel 1 (
	echo [error] Failed to install obscura. Check your npm installation and permissions.
	pause
	exit /b 1
)

echo.
echo [ok] Obscura installed successfully!
where obscura >nul 2>nul
if errorlevel 0 (
	for /f "delims=" %%i in ('obscura --version') do echo Version: %%i
)

echo.
echo You can now use Obscura as the web browser backend in Settings.
echo.
pause
