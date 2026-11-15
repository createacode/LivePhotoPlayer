#requires -Version 7.0
# 启动打包产物，截取该窗口自身（PrintWindow），用于验证界面是否真的渲染出来
param(
    [string]$Release = '',
    [string]$Photo = 'docs\demo\IMG20260809114846.jpg',
    [string]$Out = "$env:TEMP\lpp_window.png"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class WinCap {
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
'@

[void][WinCap]::SetProcessDPIAware()

if (-not $Release) {
    $latest = Get-ChildItem (Join-Path $root 'release') -Directory -Filter 'LivePhotoPlayer_v*' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw '未找到 release 目录，请先运行 scripts/build.ps1' }
    $Release = $latest.FullName
    Write-Host "使用发布目录: $Release"
}
$exe = (Resolve-Path (Join-Path $Release 'LivePhotoPlayer.exe')).Path
$photo = (Resolve-Path $Photo).Path
$proc = Start-Process -FilePath $exe -ArgumentList "`"$photo`"" -PassThru
Start-Sleep -Seconds 6

$proc.Refresh()
$hwnd = $proc.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) {
    for ($i = 0; $i -lt 20 -and $hwnd -eq [IntPtr]::Zero; $i++) {
        Start-Sleep -Milliseconds 300
        $proc.Refresh()
        $hwnd = $proc.MainWindowHandle
    }
}
if ($hwnd -eq [IntPtr]::Zero) { throw '未找到主窗口句柄' }

$rect = New-Object WinCap+RECT
[void][WinCap]::GetWindowRect($hwnd, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
Write-Host "窗口尺寸: ${width}x${height}"

$bmp = New-Object System.Drawing.Bitmap $width, $height
$gfx = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $gfx.GetHdc()
$ok = [WinCap]::PrintWindow($hwnd, $hdc, 2)
$gfx.ReleaseHdc($hdc)
$gfx.Dispose()
Write-Host "PrintWindow: $ok"
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

Write-Host "已保存: $Out"
Start-Sleep -Milliseconds 300
$proc.Kill()
$proc.WaitForExit(5000) | Out-Null
Write-Host "已退出: $($proc.HasExited)"
