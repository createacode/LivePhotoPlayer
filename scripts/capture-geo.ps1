#requires -Version 7.0
# 用 --geo 启动，按进程号抓取该进程的所有窗口，取面积最小的那个（对话框）
param([string]$Out = "$env:TEMP\lpp_geo.png")
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class WinCap2 {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint f);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    public static List<IntPtr> OfProcess(uint target) {
        var list = new List<IntPtr>();
        EnumWindows((h, p) => {
            if (!IsWindowVisible(h)) return true;
            uint pid; GetWindowThreadProcessId(h, out pid);
            if (pid == target) list.Add(h);
            return true;
        }, IntPtr.Zero);
        return list;
    }
    public static string TitleOf(IntPtr h) {
        var sb = new StringBuilder(256); GetWindowTextW(h, sb, 256); return sb.ToString();
    }
}
'@
[void][WinCap2]::SetProcessDPIAware()

$latest = Get-ChildItem (Join-Path $root 'release') -Directory -Filter 'LivePhotoPlayer_v*' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
$exe = Join-Path $latest.FullName 'LivePhotoPlayer.exe'
$photo = (Resolve-Path 'docs\demo\IMG20261001123328.jpg').Path

$p = Start-Process -FilePath $exe -ArgumentList @("`"$photo`"", '--geo') -PassThru
Start-Sleep -Seconds 6

$handles = [WinCap2]::OfProcess([uint32]$p.Id)
Write-Host "该进程可见窗口数：$($handles.Count)"
$best = [IntPtr]::Zero; $bestArea = [int]::MaxValue
foreach ($h in $handles) {
    $r = New-Object WinCap2+RECT
    [void][WinCap2]::GetWindowRect($h, [ref]$r)
    $area = ($r.Right - $r.Left) * ($r.Bottom - $r.Top)
    Write-Host ("  窗口 0x{0:X} {1}x{2} 标题={3}" -f $h.ToInt64(), ($r.Right - $r.Left), ($r.Bottom - $r.Top), [WinCap2]::TitleOf($h))
    if ($area -gt 20000 -and $area -lt $bestArea) { $bestArea = $area; $best = $h }
}
if ($best -eq [IntPtr]::Zero) { $p.Kill(); throw '未找到可截窗口' }

$rect = New-Object WinCap2+RECT
[void][WinCap2]::GetWindowRect($best, [ref]$rect)
$w = $rect.Right - $rect.Left; $h2 = $rect.Bottom - $rect.Top
$bmp = New-Object System.Drawing.Bitmap $w, $h2
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
[void][WinCap2]::PrintWindow($best, $hdc, 2)
$g.ReleaseHdc($hdc); $g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Host "saved $Out (${w}x${h2})"
$p.Kill(); $p.WaitForExit(4000) | Out-Null
