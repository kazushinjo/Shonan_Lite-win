<#
Builds the Shonan_Lite for Windows installer (build_installer\output\ShonanLiteSetup.exe).
See build_installer\README.md for prerequisites and background.

Usage (from any folder):
  powershell -ExecutionPolicy Bypass -File build_installer\build_installer.ps1
  powershell -ExecutionPolicy Bypass -File build_installer\build_installer.ps1 -SkipInstaller

Steps:
  1. Prepare build_installer\staging\ (ffmpeg, radioconda installer, prebuilt gr-dvbs2rx).
     Anything already present is kept as-is.
  2. Build the GUI with PyInstaller into build_installer\dist\ShonanLite\
     (uses / creates .venv-win in the repository root).
  3. Compile the installer with Inno Setup 6 (skipped with -SkipInstaller).
#>
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest is very slow with the progress bar

$here = $PSScriptRoot
$repo = Split-Path $here -Parent
$staging = Join-Path $here 'staging'

# The prebuilt gr-dvbs2rx must match this radioconda version (see ShonanLiteSetup.iss).
$radiocondaVersion = '2025.03.14'
$radiocondaName = "radioconda-$radiocondaVersion-Windows-x86_64.exe"
$radiocondaUrl = "https://github.com/radioconda/radioconda-installer/releases/download/$radiocondaVersion/$radiocondaName"
$radiocondaHome = Join-Path $env:USERPROFILE 'radioconda'

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail([string]$msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# Run a native command and stop on a non-zero exit code. Native tools (pip, PyInstaller)
# write progress to stderr, which must not be treated as a PowerShell error.
function Invoke-Native([string]$exe, [string[]]$arguments) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $exe @arguments
    $code = $LASTEXITCODE
    $ErrorActionPreference = $old
    if ($code -ne 0) { Fail "$exe failed with exit code $code" }
}

# ---------------------------------------------------------------- 1. staging
Step 'Preparing staging'

# ffmpeg
$ffmpegDest = Join-Path $staging 'ffmpeg\ffmpeg.exe'
if (-not (Test-Path $ffmpegDest)) {
    $ffmpegSrc = $null
    $cmd = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
    if ($cmd) { $ffmpegSrc = $cmd.Source }
    if (-not $ffmpegSrc) {
        $pkgRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        if (Test-Path $pkgRoot) {
            $found = Get-ChildItem $pkgRoot -Filter 'Gyan.FFmpeg*' -Directory |
                ForEach-Object { Get-ChildItem $_.FullName -Recurse -Filter ffmpeg.exe } |
                Select-Object -First 1
            if ($found) { $ffmpegSrc = $found.FullName }
        }
    }
    if (-not $ffmpegSrc) { Fail 'ffmpeg.exe not found. Run: winget install --id Gyan.FFmpeg' }
    New-Item -ItemType Directory -Force (Split-Path $ffmpegDest) | Out-Null
    Copy-Item $ffmpegSrc $ffmpegDest
    Write-Host "  ffmpeg: copied from $ffmpegSrc"
} else { Write-Host '  ffmpeg: already present' }

# radioconda installer (downloaded from the official release and checked against its .sha256)
$rcDest = Join-Path $staging 'radioconda\radioconda-installer.exe'
if (-not (Test-Path $rcDest)) {
    New-Item -ItemType Directory -Force (Split-Path $rcDest) | Out-Null
    $tmp = "$rcDest.download"
    Write-Host "  radioconda: downloading $radiocondaName (about 600 MB) ..."
    Invoke-WebRequest -Uri $radiocondaUrl -OutFile $tmp -UseBasicParsing
    $shaResp = (Invoke-WebRequest -Uri "$radiocondaUrl.sha256" -UseBasicParsing).Content
    if ($shaResp -is [byte[]]) { $shaResp = [System.Text.Encoding]::ASCII.GetString($shaResp) }
    $expected = ($shaResp.Trim() -split '\s+')[0].ToLower()
    $actual = (Get-FileHash $tmp -Algorithm SHA256).Hash.ToLower()
    if ($expected -ne $actual) { Remove-Item $tmp -Force; Fail "radioconda SHA256 mismatch (expected $expected, got $actual)" }
    Move-Item $tmp $rcDest
    Write-Host '  radioconda: downloaded and verified'
} else { Write-Host '  radioconda: already present' }

# The bundled gr-dvbs2rx is copied into a fresh radioconda $radiocondaVersion on the user's PC, so it must have been
# built against exactly that radioconda's libraries. A build made in a drifted radioconda (e.g. after `conda update`,
# which moves fmt/spdlog to a newer ABI) installs fine but fails at RX start with
# "DLL load failed ... The specified procedure could not be found" (seen with v1.1.0). Verify the build environment.
$pinnedPackages = 'gnuradio-core-3.10.12.0-', 'fmt-11.0.2-', 'spdlog-1.15.1-', 'libboost-1.86.0-', 'volk-3.2.0-', 'python-3.12.9-'
$condaMeta = Join-Path $radiocondaHome 'conda-meta'
if (Test-Path $condaMeta) {
    $drifted = @($pinnedPackages | Where-Object {
        $prefix = $_
        -not (Get-ChildItem $condaMeta -Filter "$prefix*.json" -ErrorAction SilentlyContinue)
    })
    if ($drifted.Count -gt 0) {
        Fail ("$radiocondaHome is not a pristine radioconda $radiocondaVersion (missing: $($drifted -join ', ')). " +
              'Reinstall radioconda, rebuild gr-dvbs2rx (docs\gr-dvbs2rx-windows), then delete build_installer\staging\dvbs2rx_* and retry.')
    }
    & (Join-Path $radiocondaHome 'python.exe') -c 'import gnuradio.dvbs2rx' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Fail "gnuradio.dvbs2rx does not import in $radiocondaHome. Rebuild gr-dvbs2rx there (docs\gr-dvbs2rx-windows) and retry."
    }
    Write-Host '  radioconda: pinned packages match, gnuradio.dvbs2rx imports'
}

# prebuilt gr-dvbs2rx (taken from the radioconda that docs\gr-dvbs2rx-windows built it into)
$pydDir = Join-Path $staging 'dvbs2rx_pyd\gnuradio\dvbs2rx'
$dllDir = Join-Path $staging 'dvbs2rx_dll'
$pydFiles = '__init__.py', 'defs.py', 'params.py', 'utils.py', 'dvbs2rx_python.cp312-win_amd64.pyd'
$pydSrcDir = Join-Path $radiocondaHome 'Lib\site-packages\gnuradio\dvbs2rx'
$dllSrc = Join-Path $radiocondaHome 'Library\bin\gnuradio-dvbs2rx.dll'
$haveStaged = (Test-Path (Join-Path $dllDir 'gnuradio-dvbs2rx.dll')) -and
    (@($pydFiles | Where-Object { Test-Path (Join-Path $pydDir $_) }).Count -eq $pydFiles.Count)
if (-not $haveStaged) {
    if (-not (Test-Path $dllSrc) -or -not (Test-Path (Join-Path $pydSrcDir 'dvbs2rx_python.cp312-win_amd64.pyd'))) {
        Fail ("Prebuilt gr-dvbs2rx not found under $radiocondaHome. Install radioconda $radiocondaVersion " +
              'and run docs\gr-dvbs2rx-windows\build_gr_dvbs2rx_windows.bat first (see docs\gr-dvbs2rx-windows\README.md).')
    }
    New-Item -ItemType Directory -Force $pydDir, $dllDir | Out-Null
    foreach ($f in $pydFiles) { Copy-Item (Join-Path $pydSrcDir $f) (Join-Path $pydDir $f) -Force }
    Copy-Item $dllSrc (Join-Path $dllDir 'gnuradio-dvbs2rx.dll') -Force
    Write-Host "  gr-dvbs2rx: copied from $radiocondaHome"
} else { Write-Host '  gr-dvbs2rx: already present' }

# ---------------------------------------------------------------- 2. PyInstaller
Step 'Building the GUI with PyInstaller'
$venv = Join-Path $repo '.venv-win'
$py = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host '  creating .venv-win'
    Invoke-Native 'py' @('-m', 'venv', $venv)
}
Invoke-Native $py @('-m', 'pip', 'install', '-q', '-r', (Join-Path $repo 'requirements-win.txt'), '-r', (Join-Path $here 'requirements-build.txt'))
Push-Location $here
try {
    Invoke-Native $py @('-m', 'PyInstaller', 'ShonanLite.spec', '--noconfirm')
} finally { Pop-Location }
if (-not (Test-Path (Join-Path $here 'dist\ShonanLite\ShonanLite.exe'))) { Fail 'PyInstaller did not produce dist\ShonanLite\ShonanLite.exe' }

# ---------------------------------------------------------------- 3. Inno Setup
if ($SkipInstaller) {
    Step 'Done (installer compile skipped: -SkipInstaller)'
    exit 0
}
Step 'Compiling the installer with Inno Setup 6 (this takes several minutes)'
$iscc = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { Fail 'Inno Setup 6 not found. Run: winget install --id JRSoftware.InnoSetup' }
Push-Location $here
try {
    Invoke-Native $iscc @('ShonanLiteSetup.iss')
} finally { Pop-Location }

$out = Join-Path $here 'output\ShonanLiteSetup.exe'
if (-not (Test-Path $out)) { Fail 'Inno Setup did not produce output\ShonanLiteSetup.exe' }
Step ("Done: $out ({0:N0} MB)" -f ((Get-Item $out).Length / 1MB))
