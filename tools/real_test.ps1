# Real end-to-end test: real backend + the real screen (hidden window) renders one single-singer shot.
$root = Split-Path -Parent $PSScriptRoot
$env:LIPSERVICE_TOKEN = [guid]::NewGuid().ToString("N")
$backend = Start-Process -FilePath (Join-Path $root ".venv\Scripts\python.exe") -ArgumentList "-m", "app" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $root "state\backend.log") -RedirectStandardError (Join-Path $root "state\backend.log.err")
try {
    $up = $false
    for ($i = 0; $i -lt 60 -and -not $up; $i++) {
        Start-Sleep -Milliseconds 500
        try { $up = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8780/status" -TimeoutSec 2 -Headers @{ "X-Lip-Token" = $env:LIPSERVICE_TOKEN }).StatusCode -eq 200 } catch { }
    }
    "backend up: $up"
    Set-Location (Join-Path $root "desktop")
    & .\node_modules\electron\dist\electron.exe . --real 2>&1 | ForEach-Object { $_ }
} finally {
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
}
