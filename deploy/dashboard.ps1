# dashboard.ps1
# Launch dashboard on secondary display via Edge --app mode.
# After positioning, sends F11 to enter true fullscreen (zero chrome / no title bar).
# Auto-detects secondary monitor and repositions window via Win32 API.

Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public class WinPos {
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWinProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr hWnd, int nIndex);
    [DllImport("user32.dll")] public static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("dwmapi.dll")]  public static extern int DwmExtendFrameIntoClientArea(IntPtr hWnd, ref MARGINS pMarInset);
    [DllImport("dwmapi.dll")]  public static extern int DwmSetWindowAttribute(IntPtr hwnd, int dwAttribute, ref int pvAttribute, int cbAttribute);
    public delegate bool EnumWinProc(IntPtr hWnd, IntPtr lParam);

    public struct MARGINS { public int leftWidth; public int rightWidth; public int topHeight; public int bottomHeight; }

    public const uint SWP_NOZORDER       = 0x0004;
    public const uint SWP_FRAMECHANGED   = 0x0020;

    public const int GWL_STYLE   = -16;
    public const int GWL_EXSTYLE = -20;
    public const int WS_CAPTION      = 0x00C00000;
    public const int WS_THICKFRAME   = 0x00040000;
    public const int WS_BORDER       = 0x00800000;
    public const int WS_SYSMENU      = 0x00080000;
    public const int WS_MINIMIZEBOX  = 0x00020000;
    public const int WS_MAXIMIZEBOX  = 0x00010000;
    public const int WS_EX_TOOLWINDOW = 0x00000080;

    public const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;

    public const byte VK_F11 = 0x7A;
    public const uint KEYEVENTF_KEYUP = 0x0002;
}
'@

$instDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path $PSCommandPath -Parent }
$dashboardPath = Join-Path $instDir "dashboard.html"
if (-not (Test-Path $dashboardPath)) {
    $dashboardPath = Join-Path (Split-Path $instDir -Parent) "dashboard.html"
}
$dashboardUrl  = "file:///" + ($dashboardPath -replace '\\', '/')

# ---------- detect secondary screen ----------

$screens = [System.Windows.Forms.Screen]::AllScreens
if ($screens.Count -ge 2) {
    $target = $screens | Where-Object { -not $_.Primary } | Select-Object -First 1
    Write-Host "Secondary: $($target.DeviceName)  $($target.Bounds.Width)x$($target.Bounds.Height) +$($target.Bounds.X),+$($target.Bounds.Y)"
} else {
    $target = $screens[0]
    Write-Host "Single display"
}

$tX = $target.Bounds.X
$tY = $target.Bounds.Y
$tW = $target.Bounds.Width
$tH = $target.Bounds.Height

# ---------- close any existing Device Monitor windows ----------

$closeCb = [WinPos+EnumWinProc]{
    param($hWnd, $lParam)
    $sb = New-Object Text.StringBuilder(256)
    [WinPos]::GetWindowText($hWnd, $sb, $sb.Capacity) | Out-Null
    if ($sb.ToString() -eq "Device Monitor" -and [WinPos]::IsWindowVisible($hWnd)) {
        $null = [WinPos]::SendMessage($hWnd, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    return $true
}
[WinPos]::EnumWindows($closeCb, [IntPtr]::Zero) | Out-Null
Start-Sleep -Milliseconds 500

# ---------- launch Edge ----------

$edgePaths = @(
    "${env:ProgramFiles}\Microsoft\Edge\Application\msedge.exe",
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "${env:LOCALAPPDATA}\Microsoft\Edge\Application\msedge.exe"
)
$edge = $edgePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) {
    Write-Error "msedge.exe not found"
    exit 1
}

# No --start-fullscreen here — Edge --app ignores it (Chromium renders its own title bar).
# Instead we launch normally, then send F11 via keybd_event to enter true fullscreen.
$argList = @(
    "--app=$dashboardUrl",
    "--no-first-run",
    "--disable-session-crashed-bubble",
    "--noerrdialogs",
    "--disable-infobars",
    "--no-default-browser-check",
    "--disable-background-mode",
    "--disable-component-update",
    "--disable-features=msEdgeWelcomePage,msShowSignInAfterUpdate"
)

Write-Host "Launching Edge --app ..."
Start-Process -FilePath $edge -ArgumentList $argList | Out-Null

# ---------- wait for window ----------

$foundHwnd = [IntPtr]::Zero

# Up to 60 × 500ms = 30s timeout — generous enough for Edge cold start during boot
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    $captured = [IntPtr]::Zero

    $cb = [WinPos+EnumWinProc]{
        param($hWnd, $lParam)
        $sb = New-Object Text.StringBuilder(256)
        [WinPos]::GetWindowText($hWnd, $sb, $sb.Capacity) | Out-Null
        if ($sb.ToString() -eq "Device Monitor" -and [WinPos]::IsWindowVisible($hWnd)) {
            $script:captured = $hWnd
            return $false
        }
        return $true
    }
    [WinPos]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null

    if ($captured -ne [IntPtr]::Zero) {
        $foundHwnd = $captured
        break
    }
}

if ($foundHwnd -eq [IntPtr]::Zero) {
    Write-Error "Window not found after 30s - may have opened on wrong display"
    exit 1
}

# --- Remove title bar & borders (borderless fill) ---
$style = [WinPos]::GetWindowLong($foundHwnd, [WinPos]::GWL_STYLE)
$newStyle = $style -band (-bnot ([WinPos]::WS_CAPTION -bor [WinPos]::WS_THICKFRAME -bor [WinPos]::WS_BORDER))
$null = [WinPos]::SetWindowLong($foundHwnd, [WinPos]::GWL_STYLE, $newStyle)

# --- Reposition to fill target display ---
[WinPos]::SetWindowPos($foundHwnd, [IntPtr]::Zero, $tX, $tY, $tW, $tH,
    [WinPos]::SWP_NOZORDER -bor [WinPos]::SWP_FRAMECHANGED)

# --- Hide from taskbar ---
$exStyle = [WinPos]::GetWindowLong($foundHwnd, [WinPos]::GWL_EXSTYLE)
$null = [WinPos]::SetWindowLong($foundHwnd, [WinPos]::GWL_EXSTYLE, $exStyle -bor [WinPos]::WS_EX_TOOLWINDOW)

Write-Host "Borderless fullscreen on $($target.DeviceName)  ${tW}x${tH}"
