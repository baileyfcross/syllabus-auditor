@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Python environment not found. Start Syllabus Auditor once with the existing launcher.
  pause
  exit /b 1
)
set "SA_DATA_DIR=%~dp0data"
.venv\Scripts\python.exe -c "import webview" >nul 2>&1
if errorlevel 1 (
  echo Installing lightweight native desktop window dependency...
  .venv\Scripts\python.exe -m pip install "pywebview>=6,<8"
  if errorlevel 1 (pause & exit /b 1)
)
.venv\Scripts\python.exe packaging\windows\desktop_launcher.py
if errorlevel 1 pause
