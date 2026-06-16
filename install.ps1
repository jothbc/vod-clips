# Create .venv and pip install Reels (Windows PowerShell).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
python (Join-Path $Root "scripts\install_deps.py") @args
exit $LASTEXITCODE
