# Cross-platform env check (Windows PowerShell).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    & $VenvPy (Join-Path $Root "scripts\env_check.py") @args
} else {
    python (Join-Path $Root "scripts\env_check.py") @args
}
exit $LASTEXITCODE
