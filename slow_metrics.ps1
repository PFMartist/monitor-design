# Combined slow metrics (temps + GPU) — single PowerShell call
# GPU section wrapped in try/catch so it never fails the whole script

# ACPI thermal zones
$tz = Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue
if ($tz) {
    foreach ($z in $tz) {
        $c = ($z.CurrentTemperature / 10.0) - 273.15
        Write-Output ("TZ|" + $z.InstanceName + "|" + [math]::Round($c, 1))
    }
}

# GPU (may fail in Session 0 — suppressed)
try {
    $gpu = Get-Counter '\GPU Engine(*engtype_3d*)\Utilization Percentage' -ErrorAction Stop
    $gMax = ($gpu.CounterSamples | Where-Object { $_.Path -like '*engtype_3d*' } | Measure-Object -Maximum CookedValue).Maximum
    $mem = Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -ErrorAction Stop
    $mMax = ($mem.CounterSamples | Measure-Object -Maximum CookedValue).Maximum
    Write-Output ("GPU|" + [math]::Round($gMax, 1) + "|" + [math]::Round($mMax))
} catch {
    # GPU data unavailable — no output
}
