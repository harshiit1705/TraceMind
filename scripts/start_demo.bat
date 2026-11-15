@echo off
title TraceMind Demo Services
echo Starting all TraceMind services...
backend\.venv\Scripts\python.exe scripts\start_all_services.py
pause
