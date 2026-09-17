$deadline = (Get-Date).AddSeconds(300)
$seen = @{}
while ((Get-Date) -lt $deadline) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -like '*bot-profile*' }
    foreach ($p in $procs) {
        if (-not $seen.ContainsKey($p.ProcessId)) {
            $seen[$p.ProcessId] = $true
            "=== chrome.exe PID $($p.ProcessId) at $(Get-Date -Format 'HH:mm:ss') ===" | Out-File -Append chrome_watch.log
            $p.CommandLine | Out-File -Append chrome_watch.log
            "" | Out-File -Append chrome_watch.log
        }
    }
    Start-Sleep -Milliseconds 500
}
