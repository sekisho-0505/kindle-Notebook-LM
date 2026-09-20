@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
where python > nul 2>&1
if errorlevel 1 (
  echo ERROR: Python not found.
  echo Install Python and check "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)
python kindless.py --direction left --ocr
pause > nul
