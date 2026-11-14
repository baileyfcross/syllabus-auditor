@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0packaging\windows\build-windows.ps1" %*
if errorlevel 1 (
  echo.
  echo The installer build did not finish. See the error above.
  pause
  exit /b 1
)
echo.
echo Installer build finished. Look in dist\installer\
pause
