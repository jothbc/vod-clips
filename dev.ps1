# API + Vite dev server (Windows PowerShell). Ctrl+C stops the API process.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$VenvReels = Join-Path $Root ".venv\Scripts\reels.exe"
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Error 'reels: missing .venv - run .\install.ps1 first'
    exit 1
}
if (-not (Test-Path $VenvReels)) {
    Write-Host "reels: installing package into .venv (dev,twitch)..." -ForegroundColor Yellow
    & $VenvPy -m pip install -e ".[dev,twitch]"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "reels: pip install failed - close any running reels.exe and run .\install.ps1"
        exit 1
    }
}

$Api = Start-Process -FilePath $VenvReels -ArgumentList "serve" -WorkingDirectory $Root -PassThru -NoNewWindow
Start-Sleep -Seconds 1

$WebDir = Join-Path $Root "web"
Set-Location $WebDir
if (-not (Test-Path "node_modules")) {
    Write-Host "reels: npm install in web/..." -ForegroundColor Yellow
    npm install
}

Write-Host 'reels: API -> http://127.0.0.1:8000' -ForegroundColor DarkGray
Write-Host 'reels: UI  -> http://127.0.0.1:5173' -ForegroundColor DarkGray

try {
    npm run dev
} finally {
    if ($Api -and -not $Api.HasExited) {
        Stop-Process -Id $Api.Id -Force -ErrorAction SilentlyContinue
    }
}
