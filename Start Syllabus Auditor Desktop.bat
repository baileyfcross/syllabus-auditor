@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Python environment not found. Start Syllabus Auditor once with the existing launcher.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -c "import webview" >nul 2>&1
if errorlevel 1 (
  echo Installing lightweight native desktop window dependency...
  .venv\Scripts\python.exe -m pip install "pywebview>=6,<8"
  if errorlevel 1 (pause & exit /b 1)
)
rem Desktop development mode now compiles Tailwind before starting the window.
rem Optional: pass --watch to rebuild CSS when files change during development.
.venv\Scripts\python.exe tools\desktop_dev.py %*
if errorlevel 1 (
  echo.
  echo Desktop startup or Tailwind build failed. See the error above.
  pause
  exit /b 1
)
