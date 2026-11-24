@echo off
cd /d "%~dp0"
python futures_app.py
if errorlevel 1 pause
