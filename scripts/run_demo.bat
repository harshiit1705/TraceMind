@echo off
cd /d "%~dp0.."
title TraceMind Demo Scenario Runner
if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: Backend virtual environment not found. Follow README.md setup instructions first.
  pause
  exit /b 1
)
echo Running the optional automated demo scenario...
backend\.venv\Scripts\python.exe scripts\run_demo_scenario.py
pause
