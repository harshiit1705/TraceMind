@echo off
cd /d "%~dp0.."
title TraceMind Demo Services
if not exist "backend\.venv\Scripts\python.exe" (
  echo ERROR: Backend virtual environment not found.
  echo Follow README.md setup instructions to create backend\.venv and install requirements.
  pause
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo ERROR: Frontend dependencies not found.
  echo Run "npm ci" from the frontend directory first.
  pause
  exit /b 1
)
echo Starting TraceMind demo services...
backend\.venv\Scripts\python.exe scripts\start_all_services.py
pause
