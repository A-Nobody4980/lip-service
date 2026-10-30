# Dot-source before running npm: . .\desktop\dev-env.ps1
# Portable Node and every npm/Electron cache stay on D:. Nothing is written to C:.
$node = "D:\Node\node-v24.22.2-win-x64"
$env:PATH = "$node;$env:PATH"
$env:npm_config_cache = "D:\Cache\npm-cache"
$env:npm_config_prefix = "D:\Cache\npm-global"
$env:npm_config_userconfig = "D:\Cache\npm\userrc"
$env:npm_config_globalconfig = "D:\Cache\npm\globalrc"
$env:npm_config_update_notifier = "false"
$env:npm_config_audit = "false"
$env:npm_config_fund = "false"
$env:ELECTRON_CACHE = "D:\Cache\electron"
$env:electron_config_cache = "D:\Cache\electron"
New-Item -ItemType Directory -Force D:\Cache\npm, D:\Cache\npm-cache, D:\Cache\npm-global, D:\Cache\electron | Out-Null
