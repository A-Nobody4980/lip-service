# Starts the Lip Service backend, then the desktop window. Closing the window stops the backend.
# ComfyUI and the proxy are started by the backend when a render needs them.
# If something goes wrong the reason is written to state\launcher.log and shown in a message box,
# because this script runs with no visible window.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$stateDir = Join-Path $root "state"
New-Item -ItemType Directory -Force $stateDir | Out-Null
$launcherLog = Join-Path $stateDir "launcher.log"
function Log([string]$msg) { Add-Content -Path $launcherLog -Value ("{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg) }

$backend = $null
try {
    Log "start"
    $py = Join-Path $root ".venv\Scripts\python.exe"
    $electron = Join-Path $root "desktop\node_modules\electron\dist\electron.exe"
    if (-not (Test-Path $py)) { throw "The Python environment is missing: $py. Follow the setup steps in the README." }
    if (-not (Test-Path $electron)) { throw "The window program is missing: $electron. Run npm install in the desktop folder." }

    # A backend left over from an earlier launch would hold the port with a different token, so stop it first.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match ' -m app\s*$' } |
        ForEach-Object { Log "stopping an old backend ($($_.ProcessId))"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (Get-NetTCPConnection -LocalPort 8780 -State Listen -ErrorAction SilentlyContinue) {
        throw "Port 8780 is already in use by another program, so the backend cannot start."
    }

    $env:LIPSERVICE_TOKEN = [guid]::NewGuid().ToString("N")
    $backendLog = Join-Path $stateDir "backend.log"
    $backend = Start-Process -FilePath $py -ArgumentList "-m", "app" -WorkingDirectory $root -WindowStyle Hidden `
        -PassThru -RedirectStandardOutput $backendLog -RedirectStandardError ($backendLog + ".err")
    Log "backend started (pid $($backend.Id))"

    $up = $false
    for ($i = 0; $i -lt 120 -and -not $up; $i++) {
        Start-Sleep -Milliseconds 500
        if ($backend.HasExited) { throw "The backend stopped right after starting. See $backendLog.err" }
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8780/ping" -TimeoutSec 5 `
                -Headers @{ "X-Lip-Token" = $env:LIPSERVICE_TOKEN }
            $up = ($r.StatusCode -eq 200)
        } catch { }
    }
    if (-not $up) { throw "The backend did not answer on port 8780 within a minute. See $backendLog.err" }
    Log "backend answered, opening the window"

    $window = Start-Process -FilePath $electron -ArgumentList "." -WorkingDirectory (Join-Path $root "desktop") -PassThru
    Log "window started (pid $($window.Id))"
    $window.WaitForExit()
    Log "window closed (exit code $($window.ExitCode))"
} catch {
    Log ("FAILED: " + $_.Exception.Message)
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show("Lip Service could not start.`n`n" + $_.Exception.Message + "`n`nDetails: $launcherLog", "Lip Service") | Out-Null
} finally {
    if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue }
    Log "stopped"
}
