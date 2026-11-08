@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.11+ or download the GitHub Actions EXE.
  pause
  exit /b 1
)
python desktop\main.py
if errorlevel 1 pause
