@echo off
title TitanShift - Install Obscura
echo ============================================
echo  Installing Obscura browser backend...
echo ============================================
echo.

set "OBSCURA_LOCAL_DIR=%~dp0.tools\obscura"

echo [1/2] Downloading latest Obscura Windows release...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install_obscura.ps1" -InstallDir "%OBSCURA_LOCAL_DIR%"

if errorlevel 1 (
	echo [error] Failed to download/install Obscura from GitHub releases.
	echo Please install manually from: https://github.com/h4ckf0r0day/obscura/releases
	pause
	exit /b 1
)

echo [2/2] Verifying installation...
if exist "%OBSCURA_LOCAL_DIR%\obscura.exe" set "PATH=%OBSCURA_LOCAL_DIR%;%PATH%"

echo.
echo [ok] Obscura installed successfully!
where obscura >nul 2>nul
if not errorlevel 1 (
	for /f "delims=" %%i in ('where obscura') do echo Path: %%i
	for /f "delims=" %%i in ('obscura --help ^| findstr /b /c:"Obscura"') do echo Info: %%i
)
if errorlevel 1 (
	echo [warning] obscura.exe was installed but is not on current PATH.
	echo Add this directory to PATH or keep using start.bat which auto-adds it:
	echo %OBSCURA_LOCAL_DIR%
)

echo.
echo You can now use Obscura as the web browser backend in Settings.
echo.
pause
