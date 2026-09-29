@echo off
title Dynamic Attendance App - Website
echo Starting Dynamic Attendance Website...
echo.
python --version >nul 2>&1
if errorlevel 1 (
  echo Trying python3...
  set PY=python3.13
) else (
  set PY=python
)
%PY% app.py
pause
