@echo off
cd /d "%~dp0"
set AGENT_PATH=%~dp0..\agent.py
if not exist "%AGENT_PATH%" set AGENT_PATH=%~dp0agent.py

REM Find Python
set PYTHON=
set PYTHONW=
for %%p in (
    "%LOCALAPPDATA%\Programs\Python\Python310"
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python310"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python313"
    "C:\Program Files\Python310"
    "C:\Program Files\Python311"
    "C:\Program Files\Python312"
) do (
    if exist "%%p\pythonw.exe" (
        set PYTHON=%%p\python.exe
        set PYTHONW=%%p\pythonw.exe
    )
)
if "%PYTHONW%"=="" (
    where python >nul 2>&1 && set PYTHON=python
    if "%PYTHON%"=="" (
        echo ERROR: Python not found.
        exit /b 1
    )
    REM pythonw not found, fall back to python (will show console)
    set PYTHONW=%PYTHON%
)

REM Device defaults to hostname. Override with MONITOR_DEVICE if desired.

REM Access control: the agent serves loopback only until you list the networks
REM your dashboard calls from. Comma-separated CIDRs; empty = refuse everything.
REM set MONITOR_ALLOW_NETS=10.0.0.0/24,127.0.0.1/32

REM Secrets
REM AdGuard Home:
REM set ADGUARD_PASS=your_password_here

REM Syncthing / uTorrent:
REM set SYNCTHING_KEY=your_api_key_here
REM set UTORRENT_PASS=your_utorrent_password_here

REM Kill old agent
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":9090.*LISTENING"') do taskkill /F /PID %%a >nul 2>&1

REM Start agent (device auto-detected by hostname; set MONITOR_DEVICE to override)
if defined MONITOR_DEVICE (
    "%PYTHONW%" "%AGENT_PATH%" --device %MONITOR_DEVICE% --port 9090
) else (
    "%PYTHONW%" "%AGENT_PATH%" --port 9090
)
