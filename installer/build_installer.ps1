# Build TechRadarSetup.exe -- one command, start to finish.
# Ported from Prospector's installer\build_installer.ps1 -- same steps,
# same reasoning, renamed. See techradar.spec's header comment before
# running this for the first time: crawl4ai hasn't been frozen with
# PyInstaller anywhere in this portfolio before Prospector's proven
# pattern was ported here. The [transcribe] extra (faster-whisper) is
# deliberately NOT installed into the build venv -- it's excluded from
# the spec on purpose, see techradar.spec.
#
#     powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1
#
# What it does:
#   1. finds a Python 3.11+ and makes a clean build environment
#   2. installs TechRadar and PyInstaller into it
#   3. freezes the app into dist\TechRadar\ (no Python needed on the target PC)
#   4. finds Inno Setup and compiles dist\TechRadarSetup-<version>.exe
#
# The output installs per-user, so the person running it needs no admin rights.
# It does NOT bundle a Chromium browser -- see techradar_launcher.py's
# one-time-setup message for why, and what the user needs to run once.

[CmdletBinding()]
param(
    [switch]$SkipFreeze,          # reuse an existing dist\TechRadar build
    [switch]$NoInstaller,         # stop after freezing, do not run Inno Setup
    [string]$IsccPath = ""        # override the Inno Setup compiler location
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Say([string]$text, [string]$colour = "Cyan") {
    Write-Host ""
    Write-Host "  $text" -ForegroundColor $colour
}

function Fail([string]$text) {
    Write-Host ""
    Write-Host "  [X] $text" -ForegroundColor Red
    Write-Host ""
    exit 1
}

# ---------------------------------------------------------------- 1. Python
Say "Looking for Python 3.11 or newer..."

$python = $null
foreach ($candidate in @(
    @{ Exe = "py";     Args = @("-3.12") },
    @{ Exe = "py";     Args = @("-3.11") },
    @{ Exe = "py";     Args = @("-3")    },
    @{ Exe = "python"; Args = @()        }
)) {
    if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
    try {
        $version = & $candidate.Exe @($candidate.Args + @("-c", "import sys;print('%d.%d' % sys.version_info[:2])")) 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $version) { continue }
        $parts = $version.Trim().Split('.')
        if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 11) {
            $python = $candidate
            Write-Host "      Using Python $version" -ForegroundColor DarkGray
            break
        }
    } catch { continue }
}

if (-not $python) {
    Fail @"
No Python 3.11 or newer was found.

    Install it from https://www.python.org/downloads/
    Tick "Add python.exe to PATH" on the first screen of the installer,
    then run this script again.
"@
}

# ------------------------------------------------- 2. Clean build environment
$venv = Join-Path $root ".build-venv"
$venvPy = Join-Path $venv "Scripts\python.exe"

if (-not $SkipFreeze) {
    Say "Creating a clean build environment..."
    if (Test-Path $venv) { Remove-Item $venv -Recurse -Force }
    & $python.Exe @($python.Args + @("-m", "venv", $venv))
    if (-not (Test-Path $venvPy)) { Fail "Could not create the build environment." }

    Say "Installing TechRadar and PyInstaller..."
    & $venvPy -m pip install --upgrade pip --quiet
    & $venvPy -m pip install . --quiet
    if ($LASTEXITCODE -ne 0) { Fail "Could not install TechRadar. See the errors above." }
    & $venvPy -m pip install pyinstaller --quiet
    if ($LASTEXITCODE -ne 0) { Fail "Could not install PyInstaller." }

    # Prove the app imports in a clean environment before freezing it. This
    # is the step that will surface a crawl4ai packaging problem, if there
    # is one -- it hasn't been frozen with PyInstaller in this portfolio
    # before this script was ported from Prospector's.
    Say "Checking every module imports cleanly..."
    & $venvPy -c "import importlib, pkgutil, techradar; names = [m.name for m in pkgutil.walk_packages(techradar.__path__, 'techradar.')]; [importlib.import_module(n) for n in names]; print('      ' + str(len(names) + 1) + ' modules import OK')"
    if ($LASTEXITCODE -ne 0) { Fail "The app does not import cleanly. Fix that before building." }
}

# Read the version straight from the package so the installer filename matches.
$version = (& $venvPy -c "import techradar; print(techradar.__version__)").Trim()
if (-not $version) { $version = "0.1.0" }
Write-Host "      Version $version" -ForegroundColor DarkGray

# ------------------------------------------------------------- 3. Freeze
if (-not $SkipFreeze) {
    Say "Freezing the app (this takes a few minutes)..."
    if (Test-Path (Join-Path $root "dist\TechRadar")) {
        Remove-Item (Join-Path $root "dist\TechRadar") -Recurse -Force
    }
    & $venvPy -m PyInstaller (Join-Path $root "installer\techradar.spec") --noconfirm --clean
    if ($LASTEXITCODE -ne 0) { Fail "PyInstaller failed. See the errors above." }
}

$frozen = Join-Path $root "dist\TechRadar\TechRadar.exe"
if (-not (Test-Path $frozen)) { Fail "The frozen app was not produced at $frozen" }

$sizeMb = [math]::Round((Get-ChildItem (Join-Path $root "dist\TechRadar") -Recurse |
          Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "      Frozen app is $sizeMb MB" -ForegroundColor DarkGray

if ($NoInstaller) {
    Say "Done. The app is at dist\TechRadar\TechRadar.exe" "Green"
    exit 0
}

# --------------------------------------------------------- 4. Inno Setup
Say "Looking for the Inno Setup compiler..."

$iscc = $IsccPath
if (-not $iscc) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { $iscc = $c; break } }
    if (-not $iscc) {
        $onPath = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if ($onPath) { $iscc = $onPath.Source }
    }
}

if (-not $iscc) {
    Fail @"
Inno Setup was not found.

    Install it from https://jrsoftware.org/isdl.php (version 6.2 or newer),
    then run this script again. Or point at it directly:

        .\installer\build_installer.ps1 -SkipFreeze -IsccPath "C:\path\to\ISCC.exe"

    The frozen app is already built at dist\TechRadar\ if you just want that.
"@
}
Write-Host "      Using $iscc" -ForegroundColor DarkGray

Say "Building the installer..."
& $iscc "/DMyAppVersion=$version" (Join-Path $root "installer\techradar.iss")
if ($LASTEXITCODE -ne 0) { Fail "Inno Setup failed. See the errors above." }

$setup = Join-Path $root "dist\TechRadarSetup-$version.exe"
if (-not (Test-Path $setup)) { Fail "The installer was not produced at $setup" }

$setupMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)

Write-Host ""
Write-Host "  Done." -ForegroundColor Green
Write-Host ""
Write-Host "    $setup  ($setupMb MB)"
Write-Host ""
Write-Host "  That single file installs without admin rights and needs no"
Write-Host "  Python on the target PC. Link enrichment needs one extra,"
Write-Host "  one-time step (see the message TechRadar shows on first launch)."
Write-Host ""
