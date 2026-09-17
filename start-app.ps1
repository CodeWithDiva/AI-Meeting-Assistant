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
        "Set-Location '$backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
    )
    Write-Host "Backend starting on http://0.0.0.0:8000 (reachable from other devices on this network too)"
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
        "Set-Location '$frontend'; npx next dev -H 0.0.0.0 -p 3000"
    )
    Write-Host "Frontend starting on http://localhost:3000 (reachable from other devices on this network too)"
} else {
    Write-Host "Frontend already running on port 3000"
}

# Give the frontend a moment to come up, then open it for whoever double-clicked
# the shortcut — they should never need to type a URL or a command themselves.
Start-Sleep -Seconds 6
Start-Process "http://localhost:3000"
Write-Host "Opened http://localhost:3000 in your browser."
Write-Host "Other computers on this network can reach it at: http://$(([System.Net.Dns]::GetHostAddresses($env:COMPUTERNAME) | Where-Object { $_.AddressFamily -eq 'InterNetwork' } | Select-Object -First 1).IPAddressToString):3000"