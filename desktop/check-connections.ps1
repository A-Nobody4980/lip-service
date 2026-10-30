# Launch the Electron window, then every 0.5 s for $Seconds list every network endpoint opened by
# electron.exe and its child processes. Prints each distinct remote address seen, and any new DNS names.
param([int]$Seconds = 90)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $root "node_modules\electron\dist\electron.exe"
$dnsBefore = @(Get-DnsClientCache | Select-Object -ExpandProperty Entry)
$log = Join-Path $env:TEMP "electron_stdout.log"
$p = Start-Process -FilePath $exe -ArgumentList "." -WorkingDirectory $root -PassThru -RedirectStandardOutput $log
function Tree($id) {
    $kids = Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue
    $id
    foreach ($k in $kids) { Tree $k.ProcessId }
}
$seen = @{}
$maxProcs = 0
$end = (Get-Date).AddSeconds($Seconds)
while ((Get-Date) -lt $end) {
    $ids = @(Tree $p.Id)
    $maxProcs = [Math]::Max($maxProcs, $ids.Count)
    foreach ($c in (Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess })) {
        $k = "TCP {0} {1} -> {2}:{3}" -f $c.OwningProcess, $c.State, $c.RemoteAddress, $c.RemotePort
        if (-not $seen.ContainsKey($k)) { $seen[$k] = Get-Date }
    }
    foreach ($u in (Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess })) {
        $k = "UDP {0} local {1}:{2}" -f $u.OwningProcess, $u.LocalAddress, $u.LocalPort
        if (-not $seen.ContainsKey($k)) { $seen[$k] = Get-Date }
    }
    Start-Sleep -Milliseconds 500
}
foreach ($id in @(Tree $p.Id)) { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue }
"process count seen (max): $maxProcs"
"--- endpoints seen ---"
$seen.Keys | Sort-Object
"--- new DNS names ---"
@(Get-DnsClientCache | Select-Object -ExpandProperty Entry) | Where-Object { $dnsBefore -notcontains $_ }
"--- window stdout ---"
Get-Content $log
