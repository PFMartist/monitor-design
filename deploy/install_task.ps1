# install_task.ps1 — auto-detects pythonw, installs direct task (no VBS)
$taskName = "MonitorAgent"
$instDir  = $PSScriptRoot
$agentPath = Join-Path $instDir "agent.py"
if (-not (Test-Path $agentPath)) {
    $agentPath = Join-Path (Split-Path $instDir -Parent) "agent.py"
}

Write-Host "=== MonitorAgent Task Installer ==="
Write-Host "Installing from: $instDir"

if (-not (Test-Path $agentPath)) {
    Write-Host "ERROR: agent.py not found in $instDir"
    Write-Host "Place all files in the same directory first."
    Read-Host "Press Enter to exit"
    exit 1
}

# Find pythonw.exe
$pythonw = $null
$searchPaths = @(
    "$env:LOCALAPPDATA\Programs\Python\Python311\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python310\pythonw.exe",
    "C:\Program Files\Python311\pythonw.exe",
    "C:\Program Files\Python312\pythonw.exe",
    "C:\Program Files\Python313\pythonw.exe"
)
foreach ($p in $searchPaths) {
    if (Test-Path $p) { $pythonw = $p; break }
}
if (-not $pythonw) {
    Write-Host "ERROR: pythonw.exe not found. Install Python 3.10+."
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "Python: $pythonw"

# Kill old agents
$pids = (netstat -ano 2>$null | Select-String ':9090.*LISTENING' | ForEach-Object { ($_ -split '\s+')[-1] })
foreach ($p in $pids) {
    $id = [int]$p
    if ($id -gt 0) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
}
Start-Sleep -Seconds 1

# Remove old task
schtasks /Delete /TN $taskName /F 2>$null | Out-Null

# Create task directly (no VBS, no bat) — pythonw -> agent.py
$tr = "`"$pythonw`" `"$agentPath`" --port 9090"
schtasks /Create /TN $taskName `
    /SC ONLOGON `
    /TR $tr `
    /RU $env:USERNAME `
    /RL HIGHEST `
    /DELAY 0000:15 `
    /F | Out-Null

# Start now
schtasks /Run /TN $taskName | Out-Null
Start-Sleep -Seconds 2

try {
    $r = Invoke-WebRequest -Uri 'http://localhost:9090/' -TimeoutSec 5 -UseBasicParsing
    Write-Host "Agent ONLINE"
} catch {
    Write-Host "Starting... will be ready on next login."
}

Write-Host "Done. Auto-start on login — no VBS, no bat, no window."
Read-Host "Press Enter to close"
