#requires -Version 7.0
# 启动打包产物，截取"照片态"与"播放态"两帧，验证实况视频真的能播
param(
    [string]$Release = '',
    [string]$Photo = 'docs\demo\IMG20260809114846.jpg'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class WinCap2 {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool PostMessageW(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
'@
[void][WinCap2]::SetProcessDPIAware()

function Save-Window([IntPtr]$hwnd, [string]$path) {
    $rect = New-Object WinCap2+RECT
    [void][WinCap2]::GetWindowRect($hwnd, [ref]$rect)
    $w = $rect.Right - $rect.Left
    $h = $rect.Bottom - $rect.Top
    $bmp = New-Object System.Drawing.Bitmap $w, $h
    $gfx = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $gfx.GetHdc()
    [void][WinCap2]::PrintWindow($hwnd, $hdc, 2)
    $gfx.ReleaseHdc($hdc)
    $gfx.Dispose()
    $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Host "saved $path (${w}x${h})"
}

if (-not $Release) {
    $latest = Get-ChildItem (Join-Path $root 'release') -Directory -Filter 'LivePhotoPlayer_v*' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw '未找到 release 目录，请先运行 scripts/build.ps1' }
    $Release = $latest.FullName
    Write-Host "使用发布目录: $Release"
}
$exe = (Resolve-Path (Join-Path $Release 'LivePhotoPlayer.exe')).Path
$photo = (Resolve-Path $photo).Path
$proc = Start-Process -FilePath $exe -ArgumentList "`"$photo`"" -PassThru
Start-Sleep -Seconds 6
$proc.Refresh()
$hwnd = $proc.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) { throw '未找到主窗口句柄' }

Save-Window $hwnd "$env:TEMP\lpp_photo_state.png"

# 回车 = 播放 / 暂停
$WM_KEYDOWN = 0x0100; $WM_KEYUP = 0x0101; $VK_RETURN = 0x0D
[void][WinCap2]::PostMessageW($hwnd, $WM_KEYDOWN, [IntPtr]$VK_RETURN, [IntPtr]0)
Start-Sleep -Milliseconds 80
[void][WinCap2]::PostMessageW($hwnd, $WM_KEYUP, [IntPtr]$VK_RETURN, [IntPtr]0)
Start-Sleep -Milliseconds 1200
Save-Window $hwnd "$env:TEMP\lpp_play_state.png"

$proc.Kill()
$proc.WaitForExit(5000) | Out-Null
Write-Host "exited: $($proc.HasExited)"
Get-Content (Get-ChildItem (Join-Path (Resolve-Path $Release) 'logs') -Filter 'log_*.log' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName |
    Select-Object -Last 5
