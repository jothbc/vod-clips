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

function Stop-StaleReelsApi {
    $listeners = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $listeners) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
        if ($proc -and $proc.CommandLine -match 'reels\.exe|reels\.cli|uvicorn') {
            Write-Host "reels: stopping stale API (pid $($conn.OwningProcess))" -ForegroundColor Yellow
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'reels\.exe serve' -and $_.CommandLine -match [regex]::Escape($Root) } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Milliseconds 500
}

Stop-StaleReelsApi

$Api = Start-Process -FilePath $VenvReels -ArgumentList "serve", "--reload" -WorkingDirectory $Root -PassThru -NoNewWindow
Start-Sleep -Seconds 1

$WebDir = Join-Path $Root "web"
Set-Location $WebDir
if (-not (Test-Path "node_modules")) {
    Write-Host "reels: npm install in web/..." -ForegroundColor Yellow
    npm install
}

Write-Host 'reels: API -> http://127.0.0.1:8000 (watch mode)' -ForegroundColor DarkGray
Write-Host 'reels: UI  -> http://127.0.0.1:5173' -ForegroundColor DarkGray

try {
    npm run dev
} finally {
    if ($Api -and -not $Api.HasExited) {
        Stop-Process -Id $Api.Id -Force -ErrorAction SilentlyContinue
    }
}
