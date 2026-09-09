@echo off
REM Double-click to install MonitorAgent Task Scheduler task.
REM Will prompt for administrator permission.
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0install_task.ps1"
pause
