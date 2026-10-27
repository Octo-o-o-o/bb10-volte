@echo off
setlocal
cd /d "%~dp0"
where pythonw.exe >nul 2>nul
if errorlevel 1 (
  echo Python with Tk is required. Install Python 3.14 and reopen this launcher.
  echo See README.en.md for requirements.
  pause
  exit /b 1
)
python.exe -c "import sys,tkinter; sys.exit(0 if sys.version_info >= (3,14) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.14 with Tk is required. See README.en.md.
  pause
  exit /b 1
)
start "" pythonw.exe "%~dp0tools\gui.py"
