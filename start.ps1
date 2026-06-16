# Start the Reels API using the project venv (Windows).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
$VenvReels = Join-Path $Root ".venv\Scripts\reels.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Error @"
reels: missing .venv — create it once:
  .\install.ps1
"@
    exit 1
}

if (-not (Test-Path $VenvReels)) {
    Write-Host "reels: installing package into .venv…" -ForegroundColor Yellow
    & $VenvPy -m pip install -q -e ".[dev,cuda,twitch]"
}

& $VenvReels serve @args
exit $LASTEXITCODE
