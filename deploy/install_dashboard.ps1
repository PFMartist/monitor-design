# install_dashboard.ps1 — Add dashboard startup shortcut (main machine only)
$instDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path $PSCommandPath -Parent }
$psPath  = Join-Path $instDir "dashboard.ps1"
$taskName = "MonitorDashboard"

Write-Host "=== Monitor Dashboard Installer ==="

if (-not (Test-Path $psPath)) {
    Write-Host "ERROR: dashboard.ps1 not found in $instDir"
    Read-Host "Press Enter to exit"
    exit 1
}

# Remove old task
schtasks /Delete /TN $taskName /F 2>$null | Out-Null

# Create task: runs at logon, hidden PowerShell.
# NO /RL HIGHEST — elevation breaks SetForegroundWindow (UIPI blocks
# high-integrity processes from manipulating medium-integrity Edge windows).
$tr = "powershell.exe -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$psPath`""
schtasks /Create /TN $taskName `
    /SC ONLOGON `
    /TR $tr `
    /RU $env:USERNAME `
    /DELAY 0000:20 `
    /F | Out-Null

# Start now
schtasks /Run /TN $taskName | Out-Null

Write-Host "Done. Dashboard will open on secondary display on login."
Read-Host "Press Enter to close"
