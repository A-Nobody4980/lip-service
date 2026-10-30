# Makes the Lip Service shortcuts.
#   - A Start menu shortcut is always created.
#   - A Desktop shortcut is created only if you answer Y to the question.
# The Desktop folder is found the way Windows itself finds it, so this works whether or not your Desktop
# is kept in OneDrive. Run it from anywhere:  powershell -ExecutionPolicy Bypass -File launch\create-shortcuts.ps1
# Options: -Desktop yes|no|ask (default ask) skips the question. -DryRun only prints what it would do.
param(
    [ValidateSet("ask", "yes", "no")][string]$Desktop = "ask",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot "start-lip-service.ps1"
$icon = Join-Path $PSScriptRoot "lipservice.ico"
$powershell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$conhost = Join-Path $env:SystemRoot "System32\conhost.exe"
if (-not (Test-Path $conhost)) { throw "conhost.exe was not found. This needs Windows 10 version 1809 or newer." }

function New-LipShortcut([string]$folder, [string]$label) {
    $path = Join-Path $folder "Lip Service.lnk"
    if ($DryRun) { Write-Host "Would create the $label shortcut: $path"; return }
    New-Item -ItemType Directory -Force $folder | Out-Null
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    # conhost --headless runs the launcher with no console window at all. Plain "-WindowStyle Hidden" is
    # ignored when Windows Terminal is the default terminal, which left an empty window open.
    $s.TargetPath = $conhost
    $s.Arguments = "--headless `"$powershell`" -NoProfile -ExecutionPolicy Bypass -File `"$launcher`""
    $s.WorkingDirectory = $root
    $s.IconLocation = "$icon,0"
    $s.Description = "Lip Service"
    $s.Save()
    Write-Host "Created the $label shortcut: $path"
}

New-LipShortcut ([Environment]::GetFolderPath("Programs")) "Start menu"

if ($Desktop -eq "ask") {
    $answer = Read-Host "Add a desktop shortcut too? (Y/N)"
    $wantDesktop = ($answer -match "^\s*[Yy]")
} else {
    $wantDesktop = ($Desktop -eq "yes")
}
if ($wantDesktop) {
    New-LipShortcut ([Environment]::GetFolderPath("Desktop")) "Desktop"
} else {
    Write-Host "No desktop shortcut."
}
