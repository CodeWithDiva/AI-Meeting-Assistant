$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

function Test-Port($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-Port 8000)) {
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
    )
    Write-Host "Backend starting on http://127.0.0.1:8000"
} else {
    Write-Host "Backend already running on port 8000"
}

Set-Location $frontend

if (-not (Test-Port 3000)) {
    # Clean stale or corrupted build cache if present
    if (Test-Path ".next") {
        try {
            Remove-Item -Recurse -Force ".next" -ErrorAction SilentlyContinue
        } catch {}
    }

    Start-Process powershell.exe -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$frontend'; npm run dev"
    )
    Write-Host "Frontend starting on http://localhost:3000 (Development mode with fast reload)"
} else {
    Write-Host "Frontend already running on port 3000"
}

Write-Host "Open http://localhost:3000/login"