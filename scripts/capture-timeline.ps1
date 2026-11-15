#requires -Version 7.0
# 截取"时间线模式"窗口（带 --timeline 启动参数）
param(
    [string]$Photo = 'docs\demo\IMG20261001123328.jpg',
    [string]$Out = "$env:TEMP\lpp_timeline_mode.png"
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class TlCap {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
[void][TlCap]::SetProcessDPIAware()

$latest = Get-ChildItem (Join-Path $root 'release') -Directory -Filter 'LivePhotoPlayer_v*' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$exe = Join-Path $latest.FullName 'LivePhotoPlayer.exe'
$photo = (Resolve-Path $Photo).Path

$p = Start-Process -FilePath $exe -ArgumentList @("`"$photo`"", '--timeline') -PassThru
Start-Sleep -Seconds 8
$p.Refresh()
$hwnd = $p.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) {
    for ($i = 0; $i -lt 20 -and $hwnd -eq [IntPtr]::Zero; $i++) {
        Start-Sleep -Milliseconds 400; $p.Refresh(); $hwnd = $p.MainWindowHandle
    }
}
if ($hwnd -eq [IntPtr]::Zero) { $p.Kill(); throw '未找到窗口' }
$rect = New-Object TlCap+RECT
[void][TlCap]::GetWindowRect($hwnd, [ref]$rect)
$w = $rect.Right - $rect.Left; $h = $rect.Bottom - $rect.Top
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[void][TlCap]::PrintWindow($hwnd, $hdc, 2)
$g.ReleaseHdc($hdc); $g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Host "saved $Out (${w}x${h})"
$p.Kill(); $p.WaitForExit(5000) | Out-Null
