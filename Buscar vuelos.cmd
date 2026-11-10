@echo off
cd /d "%~dp0"
uv run fly web
if errorlevel 1 pause
