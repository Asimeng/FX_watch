<#
.SYNOPSIS
    Create (or rebuild) the local development environment for FX Watch.

.DESCRIPTION
    1. Picks a Python interpreter (3.12 preferred to match production, else 3.11+).
    2. Creates .venv and installs the project with dev tools.
    3. Creates .env from .env.example with a freshly generated SECRET_KEY (never overwrites).
    4. Creates the local SQLite database and fetches the first rates (unless -SkipFetch).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
    powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1 -Recreate
    powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1 -Python 3.14
#>
param(
    [string]$Python = "",      # e.g. "3.12"; empty = auto-detect
    [switch]$Recreate,         # delete and rebuild an existing .venv
    [switch]$SkipFetch         # don't download rates at the end
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- 1. interpreter ---------------------------------------------------------------
Step "Selecting Python"
$candidates = if ($Python) { @($Python) } else { @("3.12", "3.13", "3.11", "3.14") }
$launcherArgs = $null
foreach ($v in $candidates) {
    # Windows PowerShell 5.1 turns redirected native stderr into terminating errors under
    # ErrorActionPreference=Stop, so probe each version inside try/catch.
    try {
        & py "-$v" -c "import sys" 2>$null
        if ($LASTEXITCODE -eq 0) { $launcherArgs = @("-$v"); break }
    } catch { }
}
if (-not $launcherArgs) { throw "No suitable Python found (need 3.11+). Install 3.12 from python.org." }
$version = & py @launcherArgs -c "import sys; print('%d.%d.%d' % sys.version_info[:3])"
Write-Host "Using Python $version"

# --- 2. virtual environment ---------------------------------------------------------
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if ((Test-Path ".venv") -and $Recreate) {
    Step "Removing existing .venv"
    Remove-Item -Recurse -Force ".venv"
}
if (-not (Test-Path $venvPython)) {
    Step "Creating .venv"
    & py @launcherArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
} else {
    $existing = & $venvPython -c "import sys; print('%d.%d' % sys.version_info[:2])"
    Write-Host ".venv already exists (Python $existing); reusing it. Pass -Recreate to rebuild."
}

Step "Installing FX Watch + dev tools"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --- 3. .env ---------------------------------------------------------------------------
if (-not (Test-Path ".env")) {
    Step "Creating .env (console email backend, local SQLite)"
    $secret = & $venvPython -m fxwatch generate-secret
    (Get-Content ".env.example") -replace '^SECRET_KEY=$', "SECRET_KEY=$secret" |
        Set-Content -Encoding utf8 ".env"
} else {
    Write-Host "`n.env already exists; leaving it untouched."
}

# --- 4. database + first data -------------------------------------------------------
Step "Preparing database"
& $venvPython -m fxwatch db upgrade
if (-not $SkipFetch) {
    Step "Fetching rates (the first run also downloads history, ~30 s)"
    & $venvPython -m fxwatch run-once | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "Fetch reported problems; check the log above." }
}

Write-Host "`nDone. Next:" -ForegroundColor Green
Write-Host "  .venv\Scripts\activate"
Write-Host "  streamlit run streamlit_app.py      # http://localhost:8501"
Write-Host "  pytest                              # run the test suite"
Write-Host "  python -m fxwatch run-once          # fetch rates + evaluate alerts again"
