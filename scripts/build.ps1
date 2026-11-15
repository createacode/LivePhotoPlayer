#requires -Version 7.0
<#
.SYNOPSIS
    一键构建实况照片播放器发布包。

.DESCRIPTION
    依次执行：依赖同步 -> 版本资源生成 -> 版本文档同步 -> 一致性校验 ->
    PyInstaller（onedir + windowed）-> 复制 exe 同级资源 -> 生成 SHA256SUMS.txt -> 打 zip。

    所有失败都会以非零退出码中止，不会产出"看起来成功"的空壳包。
#>
[CmdletBinding()]
param(
    [switch]$SkipZip
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 控制台默认 GBK，强制 UTF-8 以免中文与 © 输出失败
$env:PYTHONIOENCODING = 'utf-8'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$appName = 'LivePhotoPlayer'
$python = Join-Path $root '.venv\Scripts\python.exe'
$distDir = Join-Path $root 'dist'
$buildDir = Join-Path $root 'build'
$releaseRoot = Join-Path $root 'release'

function Write-Step([string]$message) {
    Write-Host "`n=== $message ===" -ForegroundColor Cyan
}

function Assert-LastExit([string]$what) {
    if ($LASTEXITCODE -ne 0) {
        throw "$what 失败（退出码 $LASTEXITCODE）"
    }
}

function Invoke-Uv {
    # uv 可能未加入 PATH（例如用 pip 安装），退回 `py -m uv`
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) {
        & $cmd.Source @args
    }
    else {
        & py -m uv @args
    }
}

# ---------------------------------------------------------------- 1. 依赖
Write-Step '1/8 同步依赖（uv sync --frozen）'
Invoke-Uv sync --frozen --extra dev
Assert-LastExit 'uv sync'

if (-not (Test-Path $python)) {
    throw "未找到 $python，依赖同步失败"
}

# ---------------------------------------------------------------- 2. 版本资源
Write-Step '2/8 生成版本资源'
& $python scripts/gen_version_info.py
Assert-LastExit 'gen_version_info.py'

# ---------------------------------------------------------------- 3. 版本文档
Write-Step '3/8 同步 VERSION.txt 与文档标题'
& $python scripts/sync_version.py
Assert-LastExit 'sync_version.py'

# ---------------------------------------------------------------- 4. 校验
Write-Step '4/8 校验版本一致性'
& $python scripts/verify_version.py
Assert-LastExit 'verify_version.py'

$version = (& $python -c "import sys; sys.path.insert(0, 'scripts'); from gen_version_info import read_version_source; print(read_version_source()['__version__'])").Trim()
if (-not $version) { throw '无法读取版本号' }
Write-Host "版本号：$version"

# ---------------------------------------------------------------- 5. 静态检查与测试
Write-Step '5/8 ruff / mypy / pytest'
& $python -m ruff check src tests scripts
Assert-LastExit 'ruff check'
& $python -m ruff format --check src tests scripts
Assert-LastExit 'ruff format --check'
& $python -m mypy
Assert-LastExit 'mypy'
& $python -m pytest -q
Assert-LastExit 'pytest'

# ---------------------------------------------------------------- 6. 打包
Write-Step '6/8 PyInstaller（onedir + windowed）'
if (Test-Path $distDir) { Remove-Item $distDir -Recurse -Force }
if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }

$excludes = @(
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick',
    'PySide6.QtQuick3D', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.Qt3DCore',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning', 'PySide6.QtSerialPort',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtDesigner', 'PySide6.QtHelp',
    'tkinter', 'unittest', 'pydoc', 'doctest', 'pytest', 'mypy'
)
$excludeArgs = $excludes | ForEach-Object { @('--exclude-module', $_) } | ForEach-Object { $_ }

& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name $appName `
    --icon app.ico `
    --version-file scripts/version_info.txt `
    --add-data "app.ico;." `
    --add-data "cover;cover" `
    --add-data "src/livephoto_player/resources;livephoto_player/resources" `
    --hidden-import pillow_heif `
    @excludeArgs `
    main.py
Assert-LastExit 'PyInstaller'

# ---------------------------------------------------------------- 7. 整理 exe 同级
Write-Step '7/8 复制 exe 同级文档与目录'
$packageDir = Join-Path $distDir $appName
$stamp = Get-Date -Format 'yyyyMMdd'
$releaseName = "${appName}_v${version}_win-x64_${stamp}"
# 清理历史版本目录：只保留本次产物，避免误点旧 exe
if (Test-Path $releaseRoot) {
    Get-ChildItem $releaseRoot -Directory | Where-Object { $_.Name -ne $releaseName } | ForEach-Object {
        Write-Host "  清理历史版本 $($_.Name)" -ForegroundColor DarkGray
        Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Get-ChildItem $releaseRoot -Filter '*.zip' | Where-Object { $_.BaseName -ne $releaseName } | ForEach-Object {
        Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
    }
}
$releaseDir = Join-Path $releaseRoot $releaseName
if (Test-Path $releaseDir) { Remove-Item $releaseDir -Recurse -Force }
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null

Copy-Item (Join-Path $packageDir '*') $releaseDir -Recurse -Force
Copy-Item 'README.md' $releaseDir -Force
Copy-Item 'THIRD-PARTY-NOTICES.md' $releaseDir -Force
Copy-Item 'LICENSE' $releaseDir -Force
Copy-Item 'VERSION.txt' $releaseDir -Force
if (Test-Path 'app.ico') { Copy-Item 'app.ico' $releaseDir -Force }

$docsTarget = Join-Path $releaseDir 'docs'
New-Item -ItemType Directory -Path $docsTarget -Force | Out-Null
foreach ($doc in @('readme.md', 'develop-readme.md')) {
    $source = Join-Path $root "docs\$doc"
    if (Test-Path $source) { Copy-Item $source $docsTarget -Force }
}
Copy-Item 'THIRD-PARTY-NOTICES.md' $docsTarget -Force

foreach ($dir in @('config', 'logs')) {
    $target = Join-Path $releaseDir $dir
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    New-Item -ItemType File -Path (Join-Path $target '.gitkeep') -Force | Out-Null
}

# ---------------------------------------------------------------- 8. 校验和与 zip
Write-Step '8/8 生成 SHA256SUMS.txt 并打 zip'
$exePath = Join-Path $releaseDir "$appName.exe"
if (-not (Test-Path $exePath)) { throw "未找到 $exePath" }

$sumsPath = Join-Path $releaseDir 'SHA256SUMS.txt'
$hash = (Get-FileHash -Path $exePath -Algorithm SHA256).Hash.ToLower()
"$hash  $appName.exe" | Set-Content -Path $sumsPath -Encoding ascii

if (-not $SkipZip) {
    $zipPath = Join-Path $releaseRoot "$releaseName.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path (Join-Path $releaseDir '*') -DestinationPath $zipPath -CompressionLevel Optimal
    $zipHash = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToLower()
    Add-Content -Path $sumsPath -Value "$zipHash  $releaseName.zip"
    Write-Host "zip：$zipPath" -ForegroundColor Green
}

Write-Host "`n构建完成：$releaseDir" -ForegroundColor Green
Write-Host "exe SHA256：$hash"
